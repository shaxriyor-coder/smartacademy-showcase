"""Rasmdan test savollari: tayyorlash -> Tesseract -> tuzilish -> savollar -> rasmlar.

    result = extract_questions([sahifa1_bytes, sahifa2_bytes], settings)

Natija JSON'ga tayyor (server.py /ocr shuni qaytaradi):

    {title, pages: [{page, questions, figures}],
     questions: [{number, text, options, options_are_images,
                  image  (PNG base64 | null — savol chizmasi, tozalangan),
                  source (JPEG base64 — savolning asl rasmdagi bo'lagi),
                  needs_review, notes: [..], uncertain: [..]}]}
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, replace

import cv2
import numpy as np

from ocr import layout
from ocr.parse import LETTERS, Question, Row, parse_pages
from ocr.preprocess import PAPER, Page, clean_crop, encode_jpeg, encode_png, prepare, source_strip, stack
from ocr.tesseract import TesseractSettings, Word, recognize

WATERMARK_REVIEW_SHARE = 0.15  # chizmaning shunchasi suv belgisi ostida — tekshirish kerak
FIGURE_PAD = 0.3  # chizma atrofidagi bo'sh joy (so'z balandligida)
SLIVER = 0.6  # chekkadagi shundan yupqa bo'lak — qo'shni qator qoldig'i (so'z balandligida)
LABEL_BORDER = 20  # Tesseract chetga yopishgan belgini yomon o'qiydi
LABEL_PSM = 11  # siyrak matn: chizma orasidagi alohida harflar
FIGURE_MAX_WIDTH = 1200
SOURCE_MAX_WIDTH = 1000


_LABEL_LIKE = re.compile(r"^\W?[A-Za-z08]{1,2}[).\]}][;:?]?$")


def _variant_labels(found: list[Word], region: layout.Box) -> list[Word]:
    """Chizma ichidagi variant harflari, sahifa koordinatasida.

    Shakllarsiz rasmda ham namunada "C)" "a)", "D)" "MD)" bo'lib o'qildi.
    Shuning uchun o'qilgan harfga emas, joylashuvga ishonamiz: variantlar
    o'qish tartibida (qatorma-qator, chapdan o'ngga) A, B, C...
    """
    candidates = [w for w in found if _LABEL_LIKE.match(w.text)]
    if len(candidates) == 1 and layout.is_marker(candidates[0].text):
        letters = [candidates[0].text[0].upper()]
    elif 2 <= len(candidates) <= len(LETTERS):
        letters = list(LETTERS[: len(candidates)])
    else:
        return []

    candidates.sort(key=lambda w: w.top)
    rows: list[list[Word]] = []
    for w in candidates:
        center = w.top + w.height / 2
        if rows and abs(center - (rows[-1][0].top + rows[-1][0].height / 2)) < 0.6 * w.height:
            rows[-1].append(w)
        else:
            rows.append([w])
    ordered = [w for row in rows for w in sorted(row, key=lambda w: w.left)]
    return [
        replace(
            w,
            text=f"{letter})",
            conf=max(w.conf, 60.0),
            left=w.left + region[0] - LABEL_BORDER,
            top=w.top + region[1] - LABEL_BORDER,
        )
        for letter, w in zip(letters, ordered)
    ]


@dataclass
class PageLayout:
    page: Page
    height: float  # so'z balandligi (binary px)
    page_bottom: int  # binary balandligi
    figures: list[layout.Box]
    rows: list[Row]


def analyze_page(data: bytes, settings: TesseractSettings) -> PageLayout:
    page = prepare(data)
    words = recognize(encode_png(page.binary), settings)
    height = layout.text_height(words)
    figures = layout.find_figures(page.binary, words, height)
    for region in figures:
        # Chizma ustidagi so'zlar o'rniga shakllarsiz qayta o'qilgan variant harflari.
        words = [w for w in words if not layout.center_inside((w.left, w.top, w.right, w.bottom), region)]
        labels = cv2.copyMakeBorder(
            layout.label_image(page.binary, region, height),
            LABEL_BORDER, LABEL_BORDER, LABEL_BORDER, LABEL_BORDER,
            cv2.BORDER_CONSTANT, value=255,
        )  # fmt: skip
        found = recognize(encode_png(labels), replace(settings, psm=LABEL_PSM))
        words.extend(_variant_labels(found, region))
    rows = layout.build_rows(words, figures)
    page_bottom = page.binary.shape[0]
    # Kattalashtirilgan rasm endi kerak emas (bir sahifada ~10 MB) — ko'p
    # sahifali yuklashda xotirada faqat asl o'lchamdagi rasmlar qoladi.
    page.binary = np.empty((0, 0), np.uint8)
    return PageLayout(page=page, height=height, page_bottom=page_bottom, figures=figures, rows=rows)


def _to_original(page: Page, box: layout.Box, pad: float) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    h, w = page.gray.shape
    s = page.scale
    return (
        max(int((x0 - pad) / s), 0),
        max(int((y0 - pad) / s), 0),
        min(int((x1 + pad) / s) + 1, w),
        min(int((y1 + pad) / s) + 1, h),
    )


def _trim_blank_rows(image: np.ndarray) -> np.ndarray:
    ink = np.nonzero((image < PAPER).any(axis=1))[0]
    return image[ink[0] : ink[-1] + 1] if ink.size else image


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _question_images(q: Question, layouts: list[PageLayout]) -> tuple[str | None, str | None, list[str]]:
    crops: list[np.ndarray] = []
    strips: list[np.ndarray] = []
    notes: list[str] = []

    for seg in q.segments:
        pl = layouts[seg.page - 1]
        page = pl.page
        bottom = seg.bottom if seg.bottom is not None else pl.page_bottom
        pad = FIGURE_PAD * pl.height
        sliver = max(1, int(SLIVER * pl.height / page.scale))

        figures = sorted(
            (f for f in pl.figures if seg.top <= (f[1] + f[3]) / 2 < bottom),
            key=lambda f: (f[1], f[0]),
        )
        for figure in figures:
            crop, covered = clean_crop(page, _to_original(page, figure, pad), sliver)
            crops.append(crop)
            if covered > WATERMARK_REVIEW_SHARE:
                notes.append("Rasm suv belgisi ustida edi — tozalangan rasmni asl rasm bilan solishtiring")

        # Rasm yoki kasr ko'rinishidagi variantlar chizma ichida bo'lmasa,
        # variantlar qatoridan savol oxirigacha bo'lgan joyni ham qo'shamiz
        # (kasrning maxraji Tesseract uchun alohida qator).
        rows = [row for page_no, row in q.option_rows if page_no == seg.page]
        outside = [r for r in rows if not any(layout.center_inside((r.left, r.top, r.right, r.bottom), f) for f in figures)]
        if q.options_are_images and outside:
            band = (
                min(r.left for r in outside),
                min(r.top for r in outside),
                max(r.right for r in outside),
                int(bottom - 0.2 * pl.height),
            )
            crop, _ = clean_crop(page, _to_original(page, band, pad), sliver)
            crops.append(crop)

        strip = source_strip(page, int((seg.top - pad) / page.scale), int((bottom - 0.2 * pl.height) / page.scale))
        strips.append(_trim_blank_rows(strip))

    image = _b64(encode_png(stack(crops, max_width=FIGURE_MAX_WIDTH))) if crops else None
    source = _b64(encode_jpeg(stack(strips, max_width=SOURCE_MAX_WIDTH))) if strips else None
    return image, source, list(dict.fromkeys(notes))


def extract_questions(pages: list[bytes], settings: TesseractSettings) -> dict:
    layouts = [analyze_page(data, settings) for data in pages]
    parsed = parse_pages([pl.rows for pl in layouts])

    per_page = [0] * len(layouts)
    questions = []
    for q in parsed.questions:
        image, source, notes = _question_images(q, layouts)
        q.notes.extend(notes)
        per_page[q.segments[0].page - 1] += 1
        questions.append(
            {
                "number": q.number,
                "text": q.text,
                "options": q.options,
                "options_are_images": q.options_are_images,
                "image": image,
                "source": source,
                "needs_review": bool(q.notes or q.uncertain),
                "notes": q.notes,
                "uncertain": q.uncertain,
            }
        )

    return {
        "title": parsed.title,
        "pages": [
            {"page": i + 1, "questions": per_page[i], "figures": len(pl.figures)} for i, pl in enumerate(layouts)
        ],
        "questions": questions,
    }
