"""SmartAcademy Platform — javob varag'i va OMR servisi.

Platforma (Next.js) bu servisga faqat localhost orqali murojaat qiladi.
Og'ir ish shu yerda: WeasyPrint bilan shablon chizish, PyMuPDF bilan
shtamplash, OpenCV bilan skanni o'qish. Baholash va natijani saqlash esa
platformada — servis bazaga umuman tegmaydi va hech narsani diskda
saqlamaydi.

Endpointlar (health'dan boshqa hammasi `X-Checker-Token` talab qiladi):

  GET  /health
  POST /templates  JSON {title, subjects:[{name, question_count, choice_count}]}
                   -> {blank_pdf (base64), field_boxes, bubble_boxes}
  POST /stamp      JSON {blank_pdf (base64), field_boxes,
                         participants:[{ism, familiya, kun, oy, yil, sinf, ticket_no}]}
                   -> application/pdf (har ishtirokchi alohida sahifada)
  POST /check      multipart: meta (JSON {field_boxes, bubble_boxes,
                         answer_keys:{fan_nomi:[harflar]}}), file (PDF yoki rasm)
                   -> {page_count, pages:[...], annotated_pdf (base64 | null)}
  POST /ocr        multipart: file (test sahifasi rasmi; bir nechta bo'lsa — tartib bilan)
                   -> {title, pages:[...], questions:[{number, text, options,
                       options_are_images, image, source, needs_review, notes,
                       uncertain}]}  (ocr/pipeline.py)

Ishga tushirish: `python server.py` (checker/ papkasi ichidan).
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import sys

from aiohttp import web

from config import (
    CHECKER_HOST,
    CHECKER_PORT,
    CHECKER_TOKEN,
    MAX_OCR_PAGES,
    MAX_PARALLEL_JOBS,
    MAX_SCAN_PAGES,
    MAX_UPLOAD_MB,
    OCR_LANG,
    TESSDATA_DIR,
    TESSERACT_CMD,
)
from omr.answer_sheet_service import (
    AnswerSheetContext,
    AnswerSheetGenerationError,
    SubjectSpec,
    extract_bubble_boxes,
    extract_field_boxes,
    render_blank_sheet_pdf,
    stamp_answer_sheets_pdf,
)
from omr.omr_checker import (
    OmrError,
    build_annotated_pdf,
    check_sheet,
    sheet_page_count,
    sheet_page_image,
)
from omr.qr_payload import is_valid_ticket_no
from ocr.pipeline import extract_questions
from ocr.preprocess import OcrError
from ocr.tesseract import TesseractSettings

logger = logging.getLogger("checker")

# Varaqda ko'pi bilan 3 fan — smartbot javob varag'i sozlamasidagi bilan bir xil.
MAX_SUBJECTS = 3
MAX_QUESTIONS_PER_SUBJECT = 200
MAX_PARTICIPANTS = 1000

_STAMP_FIELDS = ("ism", "familiya", "kun", "oy", "yil", "sinf", "ticket_no")

OCR_SETTINGS = TesseractSettings(cmd=TESSERACT_CMD, tessdata_dir=TESSDATA_DIR, lang=OCR_LANG)


class BadRequest(Exception):
    """So'rov noto'g'ri tuzilgan — 400 qaytadi."""


def _jobs(app: web.Application) -> asyncio.Semaphore:
    return app["jobs"]


@web.middleware
async def guard(request: web.Request, handler):
    if request.path != "/health":
        token = request.headers.get("X-Checker-Token", "")
        if not hmac.compare_digest(token.encode(), CHECKER_TOKEN.encode()):
            return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        return await handler(request)
    except BadRequest as e:
        return web.json_response({"error": str(e)}, status=400)
    except (AnswerSheetGenerationError, OmrError, OcrError) as e:
        # Bu xabarlar o'qituvchiga ko'rsatishga mo'ljallangan (o'zbekcha,
        # nima qilish kerakligi bilan) — platforma ularni o'zgartirmaydi.
        return web.json_response({"error": str(e)}, status=422)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Kutilmagan xato: %s %s", request.method, request.path)
        return web.json_response({"error": "Checker servisida kutilmagan xato"}, status=500)


async def _read_json(request: web.Request) -> dict:
    try:
        body = await request.json()
    except Exception as e:
        raise BadRequest(f"JSON o'qilmadi: {e}") from e
    if not isinstance(body, dict):
        raise BadRequest("JSON obyekt kutilgan")
    return body


def _parse_subjects(raw) -> tuple[SubjectSpec, ...]:
    if not isinstance(raw, list) or not (1 <= len(raw) <= MAX_SUBJECTS):
        raise BadRequest(f"subjects: 1 dan {MAX_SUBJECTS} tagacha fan kerak")
    specs = []
    for i, s in enumerate(raw, start=1):
        if not isinstance(s, dict):
            raise BadRequest(f"subjects[{i}]: obyekt kutilgan")
        name = str(s.get("name") or "").strip()
        qc, cc = s.get("question_count"), s.get("choice_count")
        if not name or len(name) > 100:
            raise BadRequest(f"subjects[{i}].name: 1-100 belgi")
        if not isinstance(qc, int) or not (1 <= qc <= MAX_QUESTIONS_PER_SUBJECT):
            raise BadRequest(f"subjects[{i}].question_count: 1-{MAX_QUESTIONS_PER_SUBJECT}")
        if cc not in (4, 5):
            raise BadRequest(f"subjects[{i}].choice_count: 4 yoki 5")
        specs.append(SubjectSpec(name=name, question_count=qc, choice_count=cc))
    if len({s.name for s in specs}) != len(specs):
        # OMR natijasi va javob kalitlari fan NOMI bo'yicha bog'lanadi.
        raise BadRequest("subjects: fan nomlari takrorlanmasligi kerak")
    return tuple(specs)


def _decode_pdf(raw) -> bytes:
    try:
        data = base64.b64decode(raw or "", validate=True)
    except Exception as e:
        raise BadRequest(f"blank_pdf base64 emas: {e}") from e
    if data[:5] != b"%PDF-":
        raise BadRequest("blank_pdf PDF emas")
    return data


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def create_template(request: web.Request) -> web.Response:
    body = await _read_json(request)
    subjects = _parse_subjects(body.get("subjects"))
    title = str(body.get("title") or "").strip()[:150] or "Test"

    async with _jobs(request.app):
        blank_pdf = await render_blank_sheet_pdf(subjects, title)
        field_boxes = await asyncio.to_thread(extract_field_boxes, blank_pdf)
        bubble_boxes = await asyncio.to_thread(extract_bubble_boxes, blank_pdf, subjects)

    return web.json_response(
        {
            "blank_pdf": base64.b64encode(blank_pdf).decode(),
            "field_boxes": field_boxes,
            "bubble_boxes": bubble_boxes,
        }
    )


async def stamp(request: web.Request) -> web.Response:
    body = await _read_json(request)
    blank_pdf = _decode_pdf(body.get("blank_pdf"))
    field_boxes = body.get("field_boxes")
    if not isinstance(field_boxes, str) or not field_boxes:
        raise BadRequest("field_boxes (JSON matn) kerak")

    raw_parts = body.get("participants")
    if not isinstance(raw_parts, list) or not (1 <= len(raw_parts) <= MAX_PARTICIPANTS):
        # Bo'sh ro'yxatda shtamplash 0 sahifali PDF qaytaradi — undan ko'ra
        # sababini aniq aytamiz.
        raise BadRequest(f"participants: 1 dan {MAX_PARTICIPANTS} tagacha")

    contexts = []
    for i, p in enumerate(raw_parts, start=1):
        if not isinstance(p, dict):
            raise BadRequest(f"participants[{i}]: obyekt kutilgan")
        values = {k: str(p.get(k) or "").strip() for k in _STAMP_FIELDS}
        # Platforma ticket_no'ni o'zi yasaydi (TypeScript'da). Formati yoki
        # nazorat raqami buzuq bo'lsa, bu varaq keyin hech qachon
        # tekshirilmaydi — shuning uchun chop etishdan OLDIN rad etamiz.
        if not is_valid_ticket_no(values["ticket_no"]):
            raise BadRequest(f"participants[{i}].ticket_no yaroqsiz: {values['ticket_no']!r}")
        contexts.append(AnswerSheetContext(**values))

    async with _jobs(request.app):
        pdf = await stamp_answer_sheets_pdf(blank_pdf, field_boxes, contexts)
    return web.Response(body=pdf, content_type="application/pdf")


async def check(request: web.Request) -> web.Response:
    if not request.content_type.startswith("multipart/"):
        raise BadRequest("multipart/form-data kutilgan (meta + file)")

    meta_raw: str | None = None
    file_bytes: bytes | None = None
    reader = await request.multipart()
    async for part in reader:
        if part.name == "meta":
            meta_raw = await part.text()
        elif part.name == "file":
            file_bytes = await part.read()
    if not meta_raw or not file_bytes:
        raise BadRequest("meta va file ikkalasi ham kerak")

    try:
        meta = json.loads(meta_raw)
        field_boxes = meta["field_boxes"]
        bubble_boxes = meta["bubble_boxes"]
        answer_keys = meta["answer_keys"]
    except Exception as e:
        raise BadRequest(f"meta noto'g'ri: {e}") from e
    if not (
        isinstance(field_boxes, str)
        and isinstance(bubble_boxes, str)
        and isinstance(answer_keys, dict)
        and all(isinstance(v, list) for v in answer_keys.values())
    ):
        raise BadRequest("meta: field_boxes/bubble_boxes matn, answer_keys {fan: [harflar]}")

    pages: list[dict] = []
    annotated: list[bytes] = []
    async with _jobs(request.app):
        total = await asyncio.to_thread(sheet_page_count, file_bytes)
        if total > MAX_SCAN_PAGES:
            raise BadRequest(
                f"Faylda {total} sahifa bor — bir yuklashda ko'pi bilan {MAX_SCAN_PAGES} ta."
            )
        # Sahifalar birma-bir: xotirada doim bitta sahifa rasmi turadi
        # (smartbot DECISIONS.md #35, "Xotira").
        for index in range(total):
            try:
                image = await asyncio.to_thread(sheet_page_image, file_bytes, index)
                result = await asyncio.to_thread(
                    check_sheet, image, field_boxes, bubble_boxes, answer_keys, True
                )
            except OmrError as e:
                pages.append({"page": index + 1, "ok": False, "error": str(e)})
                continue
            if result.annotated_png:
                annotated.append(result.annotated_png)
            pages.append(
                {
                    "page": index + 1,
                    "ok": True,
                    "ticket_no": result.ticket_no,
                    "subjects": [
                        {"name": s.name, "answers": s.answers, "multi": s.multi}
                        for s in result.subjects
                    ],
                }
            )

        annotated_pdf = (
            await asyncio.to_thread(build_annotated_pdf, annotated) if annotated else None
        )

    return web.json_response(
        {
            "page_count": total,
            "pages": pages,
            "annotated_pdf": base64.b64encode(annotated_pdf).decode() if annotated_pdf else None,
        }
    )


async def ocr(request: web.Request) -> web.Response:
    if not request.content_type.startswith("multipart/"):
        raise BadRequest("multipart/form-data kutilgan (file)")

    pages: list[bytes] = []
    reader = await request.multipart()
    async for part in reader:
        if part.name != "file":
            continue
        if len(pages) >= MAX_OCR_PAGES:
            raise BadRequest(f"Bir yuklashda ko'pi bilan {MAX_OCR_PAGES} ta sahifa.")
        data = await part.read()
        if data:
            pages.append(data)
    if not pages:
        raise BadRequest("Kamida bitta sahifa rasmi (file) kerak")

    async with _jobs(request.app):
        result = await asyncio.to_thread(extract_questions, pages, OCR_SETTINGS)
    return web.json_response(result)


def create_app() -> web.Application:
    app = web.Application(
        middlewares=[guard], client_max_size=MAX_UPLOAD_MB * 1024 * 1024
    )
    app["jobs"] = asyncio.Semaphore(MAX_PARALLEL_JOBS)
    app.router.add_get("/health", health)
    app.router.add_post("/templates", create_template)
    app.router.add_post("/stamp", stamp)
    app.router.add_post("/check", check)
    app.router.add_post("/ocr", ocr)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger.info("Checker servisi: http://%s:%s", CHECKER_HOST, CHECKER_PORT)
    web.run_app(create_app(), host=CHECKER_HOST, port=CHECKER_PORT, print=None)
