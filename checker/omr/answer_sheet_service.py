# Manba: smartbot/services/answer_sheet_service.py (commit 38373cf, 2026-09-13) — o'zgarishsiz nusxa,
# faqat import yo'llari checker/ tuzilishiga moslangan. Geometriya va OMR
# qarorlari smartbot/docs/DECISIONS.md #27-#37 da tushuntirilgan.
"""Javob varag'i (belgilash blankasi) generatsiyasi.

Ikki bosqichli arxitektura (qarang: DECISIONS.md #27):

  1. BO'SH SHABLON — olimpiada uchun BIR MARTA (fan sozlangan paytda)
     WeasyPrint bilan bitta A4 sahifa chiziladi: sarlavha, doiralar to'ri,
     ramkalar — hammasi, lekin ishtirokchi ma'lumotlari BO'SH. Natija PDF
     baytlari `AnswerSheet.blank_pdf` da saqlanadi. Sekin (doiralar ko'p),
     lekin olimpiadaga bir marta.

  2. SHTAMPLASH — har bir ishtirokchi uchun o'sha tayyor sahifa nusxalanadi
     va ustiga FAQAT ism/familiya/sana/sinf matni + QR rasmi qo'yiladi
     (PyMuPDF). WeasyPrint umuman chaqirilmaydi — bu millisekundlar.

Nega shunday: WeasyPrint'ning CSS joylashtirish dvigateli bitta varaqdagi
minglab doira elementini chizishda o'ta sekin (o'lchangan: bitta sahifa
~308 soniya). Doiralar to'ri esa olimpiadaning HAMMA ishtirokchisida bir
xil — faqat sarlavha o'zgaradi. Shuning uchun og'ir qism bir marta
bajariladi.

"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
from dataclasses import dataclass

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import QR_SECRET, ANSWER_SHEET_ASSETS_DIR
from omr.qr_payload import build_qr_payload

logger = logging.getLogger(__name__)

# Bitta sub-ustunda ko'pi bilan shuncha savol.
MAX_ROWS_PER_COL = 22


class AnswerSheetGenerationError(Exception):
    """WeasyPrint yoki PyMuPDF ishlamay qolganda ko'tariladi."""


@dataclass(frozen=True)
class SubjectSpec:
    """Bitta fan bo'yicha sozlama (AnswerSheetSubject'dan olinadi)."""

    name: str
    question_count: int
    choice_count: int  # 4 (ABCD) yoki 5 (ABCDE)


@dataclass(frozen=True)
class AnswerSheetContext:
    """Bitta ishtirokchining bo'sh shablonga shtamplanadigan ma'lumoti.

    Fan tarkibi va olimpiada nomi bu yerda YO'Q — ular bo'sh shablonning
    o'zida allaqachon chizilgan (hamma ishtirokchida bir xil).
    """

    ism: str
    familiya: str
    kun: str
    oy: str
    yil: str
    sinf: str
    ticket_no: str


# Jinja2 Environment va shablon bir marta yuklanadi — har so'rovda emas.
_env = Environment(
    loader=FileSystemLoader(str(ANSWER_SHEET_ASSETS_DIR)),
    autoescape=select_autoescape(["html"]),
)
_template = _env.get_template("answer_sheet.html")

# Bo'sh shablondagi ko'rinmas (oq) orientir matnlar — PyMuPDF shular
# bo'yicha maydon joylarini topadi. answer_sheet.html bilan MOS bo'lishi
# SHART.
# DIQQAT: orientirlar QISQA bo'lishi shart — tug'ilgan sana katakchalari
# atigi 10mm, uzun matn u yerda ikki qatorga bo'linib ketadi va
# `search_for` uni topa olmay qoladi.
_PLACEHOLDERS = {
    "ism": "@I@",
    "familiya": "@F@",
    "kun": "@K@",
    "oy": "@O@",
    "yil": "@Y@",
    "sinf": "@S@",
    "id": "@ID@",
}
# Bu maydonlar katakcha ichida markazlashtiriladi (CSS'dagi .date-box,
# .qr-id).
_CENTERED_FIELDS = {"kun", "oy", "yil", "id"}

# Shablon formati versiyasi. Shablonning O'ZI (maydonlar to'plami)
# o'zgarganda oshiriladi — shunda bazadagi eski shablonlar avtomatik
# qayta chiziladi. Fan sozlamasi o'zgarishini `blank_matches_subjects`
# ushlaydi, lekin u FORMAT o'zgarishini sezmaydi: fanlar o'sha-o'sha
# bo'lsa ham, eski shablonda yangi maydon (masalan QR ostidagi ID)
# bo'lmaydi (qarang: DECISIONS.md #32).
TEMPLATE_VERSION = 3

# Shtamplashda ishlatiladigan shrift: PyMuPDF ichiga qurilgan
# Helvetica-Bold. Tizim shriftlariga bog'liq emas — Windows'da ham,
# Linux serverda ham bir xil chiqadi.
_STAMP_FONT = "hebo"
_STAMP_SIZE_PT = 9.6  # ~3.4mm, shablondagi .fval bilan bir xil
_STAMP_MIN_SIZE_PT = 4.5
_STAMP_COLOR = (0.07, 0.07, 0.07)
_BOX_PAD_PT = 5.0  # .fval padding (2mm) ga yaqin

# --- belgilash zonasi o'lchamlari (mm) -------------------------------------
# Bu qiymatlar CSS bilan BIR XIL bo'lishi shart (answer_sheet.html):
# .marking-area { border: 1.4mm; padding: 3mm; gap: 3mm }
# .subject-block { border: 0.6mm; padding: 2.5mm }
#
# DIQQAT: ilgari bu yerda faqat padding ayirilar edi va .marking-area ning
# 1.4mm qalin RAMKASI (ikki tomondan 2.8mm) hisobga olinmagandi. Natijada
# joylashuv o'zini boridan 2.8mm kengroq deb o'ylab, zich sozlamada eng
# o'ngdagi ustunni ramka ustiga chiqarib yuborardi (DECISIONS.md #37).
_MARKING_BORDER_MM = 1.4   # .marking-area border
_MARKING_PAD_MM = 3.0      # .marking-area padding
# A4 210mm - 2*9mm (@page margin) = 192mm
_AREA_W_MM = 192.0 - 2 * _MARKING_PAD_MM - 2 * _MARKING_BORDER_MM
_BLOCK_GAP_MM = 3.0      # .marking-area gap
_BLOCK_PAD_MM = 2.5      # .subject-block padding
_BLOCK_BORDER_MM = 0.6
# Sub-ustunlar orasidagi ENG KICHIK bo'shliq. Kichik bo'lsa keyingi
# ustunning savol raqami oldingi ustunning oxirgi doirasiga tegib ketadi
# (sinovda ko'rilgan). Haqiqiy bo'shliq bundan KATTA bo'lishi mumkin:
# blokda ortgan kenglik ustunlar orasiga taqsimlanadi (_compute_layout).
_COL_GAP_MM = 3.5        # .subject-cols gap (eng kichigi)
# Taqsimlangan bo'shliqning yuqori chegarasi — ustun kengligiga nisbatan.
# Ustunlar bir-biridan haddan tashqari uzoqlashib, ko'z bir qatorni
# kuzatib bora olmay qolmasligi uchun.
_COL_GAP_MAX_RATIO = 0.8
# Blok ichida ATAYLAB bo'sh qoldiriladigan zaxira. Ustunlar kenglikni
# 100% to'ldirsa, chizishdagi eng kichik farq (masalan serverdagi
# kengroq shrift) oxirgi ustunni ramkadan chiqarib yuboradi — serverda
# 100 savolli varaqda aynan shunday bo'lgan (DECISIONS.md #37).
_BLOCK_SAFETY_MM = 1.5
# Savol raqami ustunining ENG KICHIK kengligi. Haqiqiysi raqamdagi
# belgilar soniga qarab hisoblanadi (_compute_layout): "100" ni 4.2mm ga
# sig'dirib bo'lmaydi va u ustundan toshib, ENG O'NGDAGI ustunni varaq
# ramkasidan chiqarib yuborardi (serverda 100 savolli varaqda aynan
# shunday bo'lgan: oxirgi ustunning "D" doirasi ramka bilan kesilgan).
_NUM_W_MM = 4.2          # savol raqami ustuni (eng kichigi)
# Bitta raqamning kengligi (em). Haqiqiy sans shriftlarda ~0.55-0.64 em;
# 0.68 — server shrifti (DejaVu) lokaldagidan kengroq bo'lishi mumkinligi
# uchun ataylab zaxira bilan olingan (qarang: DECISIONS.md #36).
_NUM_DIGIT_EM = 0.68
_NUM_FONT_MAX_MM = 2.6   # raqam shriftining eng kattasi
_NUM_GAP_MM = 0.5
# Fan bloki ichida SAVOL QATORLARI uchun qoladigan balandlik. Bu qiymat
# taxmin emas — chizilgan PDF'dan o'lchangan: belgilash zonasi 170.4mm,
# undan ramka/padding (2*4.4mm), blok ramkasi/padding (2*3.1mm) va fan
# sarlavhasi (~9.6mm) ayiriladi. Biroz ehtiyot zaxira bilan olingan.
_ROWS_H_MM = 145.0
_HGAP_RATIO = 0.34       # doiralar orasi = bubble * shu nisbat
_VGAP_RATIO = 0.42       # qatorlar orasi
_BUBBLE_MAX_MM = 4.2
_BUBBLE_MIN_MM = 2.2
_MARKER_MM = 7.0         # burchak markerlari (answer_sheet.html -> .marker)
_MM_TO_PT = 72.0 / 25.4

# Burchak markerlari — ArUco (oddiy qora kvadrat emas). Sabab: ArUco'ni
# OpenCV telefonda olingan qiyshiq/soyali rasmdan ham ishonchli topadi va
# har marker o'z ID'sini tashiydi, ya'ni varaqni teskari yoki 90 daraja
# burib skanerlab bo'lmaydi — burchaklar aralashib ketmaydi
# (qarang: DECISIONS.md #29, scripts/gen_aruco_markers.py).
# DIQQAT: bu qiymatlarni o'zgartirsangiz, ALLAQACHON BOSIB CHIQARILGAN
# varaqlar o'qilmay qoladi.
ARUCO_DICT_ID = 0  # cv2.aruco.DICT_4X4_50 — eng yirik katakli, 7mm uchun mos
ARUCO_CORNER_IDS = {"tl": 0, "tr": 1, "bl": 2, "br": 3}


def _subject_columns(question_count: int) -> list[list[int]]:
    """Savol raqamlarini sub-ustunlarga TENG bo'ladi.

    Masalan 30 savol, MAX_ROWS_PER_COL=22 bo'lsa -> 2 ta ustun (15+15),
    "22+8" emas — teng bo'lingani chiroyliroq ko'rinadi.
    """
    n_cols = math.ceil(question_count / MAX_ROWS_PER_COL)
    per_col = math.ceil(question_count / n_cols)
    columns: list[list[int]] = []
    q = 1
    for _ in range(n_cols):
        col_end = min(q + per_col - 1, question_count)
        columns.append(list(range(q, col_end + 1)))
        q = col_end + 1
    return columns


def _build_subjects_data(subjects: tuple[SubjectSpec, ...]) -> list[dict]:
    return [
        {
            "name": s.name,
            "question_count": s.question_count,
            "letters": "ABCDE"[: s.choice_count],
            "columns": _subject_columns(s.question_count),
        }
        for s in subjects
    ]


def _compute_layout(subjects_data: list[dict]) -> dict:
    """Doira o'lchami va oraliqlarini fan/savol/variant soniga moslaydi.

    Doiralar qat'iy o'lchamda bo'lsa, 3 fan x 5 variant kabi sozlamada
    varaq eniga sig'may qolardi. Shuning uchun eng "tor" fan bo'yicha
    hisoblab, hammasiga bir xil o'lcham beriladi (varaq bir xil ko'rinsin).
    """
    n = max(1, len(subjects_data))
    block_inner = (
        (_AREA_W_MM - _BLOCK_GAP_MM * (n - 1)) / n
        - 2 * _BLOCK_PAD_MM
        - 2 * _BLOCK_BORDER_MM
    )

    # Raqam ustuni: eng katta savol raqami necha belgidan iborat bo'lsa,
    # shunga qarab. Shrift o'lchamining ENG KATTA qiymati bilan hisoblanadi
    # — shunda doira o'lchami keyin kichrayib, raqam shrifti ham
    # kichraysa, ustun baribir yetarli bo'ladi (teskarisi xavfli).
    max_digits = max(
        (len(str(s["question_count"])) for s in subjects_data), default=2
    )
    num_w = max(
        _NUM_W_MM,
        round(max_digits * _NUM_DIGIT_EM * _NUM_FONT_MAX_MM + 0.3, 2),
    )

    bubble = _BUBBLE_MAX_MM
    for s in subjects_data:
        cols = max(1, len(s["columns"]))
        choices = max(1, len(s["letters"]))

        # Qator kengligi (CSS: .q-row { display:flex; gap:hgap } va
        # .q-num { margin-right:num_gap }):
        #     num_w + num_gap + hgap          <- raqamdan keyin IKKALASI
        #   + choices*bubble + (choices-1)*hgap
        #   = num_w + num_gap + bubble*choices*(1 + hgap_ratio)
        #
        # DIQQAT: ilgari bu yerda raqam bilan birinchi doira orasidagi
        # flex `gap` HISOBGA OLINMAGANDI (faqat margin-right sanalardi),
        # ya'ni har ustun hisoblanganidan bitta hgap ga keng chiqardi
        # (DECISIONS.md #37).
        col_w = (block_inner - _COL_GAP_MM * (cols - 1)) / cols
        avail_w = col_w - num_w - _NUM_GAP_MM
        denom_w = choices * (1 + _HGAP_RATIO)
        if denom_w > 0:
            bubble = min(bubble, avail_w / denom_w)

        # Balandlik bo'yicha: rows*b + (rows-1)*(vgap_ratio*b) <= joy
        rows = max((len(c) for c in s["columns"]), default=1)
        denom_h = rows + _VGAP_RATIO * (rows - 1)
        if denom_h > 0:
            bubble = min(bubble, _ROWS_H_MM / denom_h)

    bubble = max(_BUBBLE_MIN_MM, min(_BUBBLE_MAX_MM, bubble))
    hgap = round(bubble * _HGAP_RATIO, 2)
    bubble = round(bubble, 2)

    # Vertikal bo'shliqni MAVJUD BALANDLIKKA YOYAMIZ. Avval u doira
    # o'lchamiga bog'langan qat'iy nisbat edi va ko'p savolda qatorlar
    # siqilib, blokning pastida katta bo'sh joy qolib ketardi (o'lchandi:
    # 60 savolda 35.8mm ishlatilmagan). Endi qatorlar butun balandlikka
    # teng taqsimlanadi. Eng ko'p qatorli fan bo'yicha hisoblanadi — CSS
    # qoidasi bitta, hamma fanga bir xil qo'llanadi.
    max_rows = max(
        (len(c) for s in subjects_data for c in s["columns"]), default=1
    )
    if max_rows > 1:
        spread = (_ROWS_H_MM - max_rows * bubble) / (max_rows - 1)
    else:
        spread = bubble * _VGAP_RATIO
    # Pastki chegara — avvalgi zich ko'rinish; yuqori chegara — kam savolda
    # doiralar bir-biridan haddan tashqari uzoqlashib ketmasligi uchun.
    vgap = max(bubble * _VGAP_RATIO, min(spread, bubble * 1.1))

    # Har bir fan uchun ustun kengligini ANIQ hisoblab qo'yamiz. Buni CSS'ga
    # tashlab bo'lmaydi: WeasyPrint flex elementining ichki (intrinsic)
    # kengligini Chrome'dan boshqacha hisoblaydi va ustunni tarkibidan tor
    # qilib qo'yadi — natijada 2-ustunning savol raqami 1-ustunning oxirgi
    # doirasi USTIGA tushib qolardi (sinovda ko'rilgan).
    for s in subjects_data:
        choices = max(1, len(s["letters"]))
        s["col_w"] = round(
            num_w + _NUM_GAP_MM + choices * bubble + choices * hgap, 2
        )

    # Ustunlar orasidagi bo'shliqni ham MAVJUD KENGLIKKA yoyamiz —
    # vertikal bo'shliq bilan bir xil mantiq. Qat'iy 3.5mm bo'lganda
    # 1 fan x 40 savol (2 ustun) kabi sozlamada ustunlar varaq o'rtasida
    # yopishib qolib, chap va o'ng tomonda ~55mm dan bo'sh joy qolardi.
    # Chegarani HAR fan bo'yicha alohida hisoblab, eng kichigini olamiz:
    # CSS qoidasi bitta va u hamma blokka sig'ishi SHART.
    usable = block_inner - _BLOCK_SAFETY_MM
    limits = [
        (usable - len(s["columns"]) * s["col_w"]) / (len(s["columns"]) - 1)
        for s in subjects_data
        if len(s["columns"]) > 1
    ]
    col_gap = _COL_GAP_MM
    if limits:
        widest = max(s["col_w"] for s in subjects_data)
        col_gap = max(
            _COL_GAP_MM, min(min(limits), widest * _COL_GAP_MAX_RATIO)
        )

    # Sig'maganda JIMGINA kesilmasin. Doira o'lchami _BUBBLE_MIN_MM dan
    # pastga tushirilmaydi (qalam bilan bo'yab bo'lmaydigan doira ma'nosiz),
    # shuning uchun juda zich sozlamada ustunlar blokka sig'may qoladi va
    # eng o'ngdagi ustun ramka bilan kesiladi. Kesilgan doira tekshirishda
    # QORA deb o'qilishi mumkin, ya'ni bu jimgina noto'g'ri natija beradi —
    # shuning uchun bu yerda ochiq xato ko'tariladi.
    for s in subjects_data:
        cols = len(s["columns"])
        kerak = cols * s["col_w"] + (cols - 1) * col_gap
        if kerak > block_inner + 0.05:
            raise AnswerSheetGenerationError(
                f"«{s['name']}» fani varaqqa sig'maydi: {s['question_count']} ta "
                f"savol × {len(s['letters'])} ta variant uchun {kerak:.0f}mm kerak, "
                f"bor-yo'g'i {block_inner:.0f}mm joy bor.\n\n"
                f"Savollar sonini kamaytiring, variantni 4 ta qiling yoki "
                f"fanlarni kamroq qilib bo'ling."
            )

    return {
        "bubble": bubble,
        "hgap": hgap,
        "vgap": round(vgap, 2),
        "bubble_font": round(bubble * 0.52, 2),
        # Harfni doira ichida vertikal markazlash uchun: ichki (content)
        # balandlik = bubble - 2*0.3mm chegara (box-sizing: border-box).
        "bubble_line": round(bubble - 0.6, 2),
        "num_w": num_w,
        "num_gap": _NUM_GAP_MM,
        "num_font": round(min(2.6, bubble * 0.62), 2),
        # CSS'dagi ustun bo'shlig'i shu yerdan boshqariladi. Doira
        # o'lchami yuqorida ENG KICHIK bo'shliq (_COL_GAP_MM) bo'yicha
        # hisoblangan, shuning uchun bu qiymat undan katta bo'lishi
        # xavfsiz — ortgan joyni ishlatadi, sig'imni kamaytirmaydi.
        "col_gap": round(col_gap, 2),
    }


def _make_qr_png(ticket_no: str) -> bytes:
    payload = build_qr_payload(ticket_no, QR_SECRET)
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=2, box_size=10)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000000", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _weasyprint_html_to_pdf(html_str: str) -> bytes:
    # WeasyPrint shu yerda import qilinadi — tizim kutubxonalari
    # (libpango/libcairo) bo'lmagan muhitda modul yuqorida import qilinsa,
    # javob varag'i bilan aloqasi yo'q butun bot ishga tushmay qolardi.
    try:
        from weasyprint import HTML
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        raise AnswerSheetGenerationError(f"WeasyPrint yuklanmadi: {e}") from e

    try:
        return HTML(string=html_str, base_url=str(ANSWER_SHEET_ASSETS_DIR)).write_pdf()
    except Exception as e:
        raise AnswerSheetGenerationError(
            f"WeasyPrint PDF generatsiyasida xato: {e}"
        ) from e


# ---------------------------------------------------------------- 1-bosqich
def _render_blank_sheet_sync(
    subjects: tuple[SubjectSpec, ...], event_title: str
) -> bytes:
    subjects_data = _build_subjects_data(subjects)
    html_str = _template.render(
        subjects=subjects_data,
        event_title=event_title,
        layout=_compute_layout(subjects_data),
    )
    pdf_bytes = _weasyprint_html_to_pdf(html_str)

    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count != 1:
            raise AnswerSheetGenerationError(
                f"Bo'sh shablon {doc.page_count} sahifa chiqdi (1 bo'lishi kerak) — "
                f"fan/savol soni varaqqa sig'magan bo'lishi mumkin."
            )
    finally:
        doc.close()
    return pdf_bytes


async def render_blank_sheet_pdf(
    subjects: tuple[SubjectSpec, ...], event_title: str
) -> bytes:
    """Olimpiada uchun BO'SH javob varag'i shablonini (1 sahifa PDF)
    qaytaradi. Sekin — olimpiadaga bir marta chaqiriladi."""
    return await asyncio.to_thread(_render_blank_sheet_sync, subjects, event_title)


def extract_field_boxes(blank_pdf: bytes) -> str:
    """Bo'sh shablondagi maydon joylarini topib, JSON matn qaytaradi.

    Har maydon uchun ikkita to'rtburchak saqlanadi:
      - "box"  — katakchaning o'zi (matnni markazlashtirish/kesish uchun),
      - "text" — ko'rinmas orientir matnning joyi (asos chizig'i uchun).
    QR uchun esa oq o'rin-rasmning bbox'i.
    """
    import fitz

    doc = fitz.open(stream=blank_pdf, filetype="pdf")
    try:
        page = doc[0]
        drawings = [d["rect"] for d in page.get_drawings()]
        boxes: dict[str, dict] = {}

        for key, marker in _PLACEHOLDERS.items():
            hits = page.search_for(marker)
            if len(hits) != 1:
                raise AnswerSheetGenerationError(
                    f"Bo'sh shablonda '{marker}' orientiri {len(hits)} marta "
                    f"topildi (aynan 1 ta bo'lishi kerak)."
                )
            text_rect = hits[0]
            # Orientirni O'RAB turgan eng kichik chizilgan to'rtburchak —
            # bu .fval katakchasi. Topilmasa, matn joyining o'zi ishlatiladi.
            containing = [
                r
                for r in drawings
                if r.x0 <= text_rect.x0 and r.y0 <= text_rect.y0
                and r.x1 >= text_rect.x1 and r.y1 >= text_rect.y1
                and r.get_area() > 0
            ]
            box = min(containing, key=lambda r: r.get_area()) if containing else text_rect
            boxes[key] = {
                "box": [box.x0, box.y0, box.x1, box.y1],
                "text": [text_rect.x0, text_rect.y0, text_rect.x1, text_rect.y1],
            }

        # QR o'rni: sahifadagi 32mm (~90.7pt) kenglikdagi yagona rasm
        # (logotip 13mm — ~36.9pt, adashtirib bo'lmaydi).
        qr_hits = [
            i["bbox"]
            for i in page.get_image_info()
            if 80.0 <= (i["bbox"][2] - i["bbox"][0]) <= 100.0
        ]
        if len(qr_hits) != 1:
            raise AnswerSheetGenerationError(
                f"Bo'sh shablonda QR o'rni {len(qr_hits)} marta topildi "
                f"(aynan 1 ta bo'lishi kerak)."
            )
        boxes["qr"] = {"box": list(qr_hits[0])}
        boxes["version"] = TEMPLATE_VERSION
        return json.dumps(boxes)
    finally:
        doc.close()


def _text_spans(page) -> list[tuple[str, "object"]]:
    """Sahifadagi barcha matn bo'laklarini (matn, bbox) ko'rinishida
    qaytaradi."""
    import fitz

    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip()
                if txt:
                    spans.append((txt, fitz.Rect(span["bbox"])))
    return spans


def extract_bubble_boxes(blank_pdf: bytes, subjects: tuple[SubjectSpec, ...]) -> str:
    """Bo'sh shablondagi HAR BIR doiraning markazini topib, JSON qaytaradi.

    Bu — avtomatik tekshirishning (OMR) kaliti: tekshiruvchi dastur
    doiralarni rasmdan QIDIRMAYDI (bu eng mo'rt qadam), balki shu yerda
    saqlangan ma'lum joylardan o'qiydi. Varaqni o'zimiz chizganimiz uchun
    bu ma'lumot bizda bor — tashqi OMR kutubxonalarida yo'q imkoniyat
    (qarang: DECISIONS.md #29).

    Format:
        {"page": [w, h], "radius": r, "markers": [[x0,y0,x1,y1], ...],
         "subjects": [{"name": ..., "letters": "ABCD",
                       "questions": {"1": [[cx, cy], ...]}}]}
    Doira markazlari HARF TARTIBIDA (A, B, C, ...) yoziladi.

    Har bosqich qat'iy tekshiriladi: biror doira topilmasa yoki soni mos
    kelmasa, xato ko'tariladi — jimgina noto'g'ri koordinata saqlanib,
    keyin butun sinf noto'g'ri baholanib ketishidan ko'ra shunisi xavfsiz.
    """
    import fitz

    subjects_data = _build_subjects_data(subjects)
    layout = _compute_layout(subjects_data)
    bubble_pt = layout["bubble"] * _MM_TO_PT
    marker_pt = _MARKER_MM * _MM_TO_PT

    doc = fitz.open(stream=blank_pdf, filetype="pdf")
    try:
        page = doc[0]

        def _square_like(r, side_pt: float, tol: float) -> bool:
            w, h = r.width, r.height
            return (
                abs(w - side_pt) <= side_pt * tol
                and abs(h - side_pt) <= side_pt * tol
            )

        def _merge_close(items, tol: float):
            """Yaqin markazlarni bitta nuqtaga birlashtiradi.

            WeasyPrint doirani chegara kengligicha (0.3mm = 0.85pt) siljigan
            IKKI kontur bilan chizadi — halqaning tashqi va ichki chekkasi.
            Haqiqiy markaz ularning o'rtasi. Qo'shni doiralar bir-biridan
            15pt dan uzoq, shuning uchun ~1.5pt chegara bilan adashish
            mumkin emas.
            """
            groups: list[list[tuple[float, float]]] = []
            for r in items:
                cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
                for g in groups:
                    gx = sum(p[0] for p in g) / len(g)
                    gy = sum(p[1] for p in g) / len(g)
                    if abs(gx - cx) <= tol and abs(gy - cy) <= tol:
                        g.append((cx, cy))
                        break
                else:
                    groups.append([(cx, cy)])
            return [
                (sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g))
                for g in groups
            ]

        spans = _text_spans(page)

        # Fan bloklarining chegarasi: har blokda "1" raqami AYNAN bir marta
        # uchraydi (savol raqamlari har fanda 1 dan boshlanadi, "10" esa
        # alohida bo'lak — "1" bilan chalkashmaydi). Shuning uchun "1"
        # larning soni = fanlar soni, va ular bloklarni chapdan o'ngga
        # ajratib beradi.
        ones = sorted(
            (r for txt, r in spans if txt == "1"), key=lambda r: r.x0
        )
        if len(ones) != len(subjects):
            raise AnswerSheetGenerationError(
                f"Shablonda «1» savol raqami {len(ones)} marta topildi, "
                f"kutilgani {len(subjects)} ta (har fanga bittadan)."
            )
        # 1-savol har blokdagi eng yuqori qator — undan yuqoridagi hech
        # narsa doira bo'la olmaydi. Bu sarlavhadagi bezak shakllarini
        # (nuqta, badge va h.k.) filtrga tushishdan saqlaydi.
        content_top = min(r.y0 for r in ones) - bubble_pt

        def _is_black(fill) -> bool:
            return fill is not None and all(c <= 0.2 for c in fill)

        drawings_meta = page.get_drawings()
        bubbles = _merge_close(
            [
                r
                for dr, r in ((dr, dr["rect"]) for dr in page.get_drawings())
                if _square_like(r, bubble_pt, 0.30)
                and _is_black(dr.get("fill"))
                and (r.y0 + r.y1) / 2 > content_top
            ],
            1.5,
        )
        expected_total = sum(s.question_count * s.choice_count for s in subjects)
        # Kamlik — jiddiy xato (biror doira topilmagan). Ortiqchasi esa
        # zararsiz: quyidagi savol-bo'yicha moslashtirish faqat kerakli
        # doiralarni oladi va oxirida biriktirilganlar soni tekshiriladi.
        if len(bubbles) < expected_total:
            raise AnswerSheetGenerationError(
                f"Shablonda atigi {len(bubbles)} ta doira topildi, kamida "
                f"{expected_total} ta bo'lishi kerak."
            )
        if len(bubbles) > expected_total:
            logger.warning(
                "Javob varag'i shablonida %d ta ortiqcha doiraga o'xshash "
                "shakl bor (topildi %d, kerak %d) — ular savol qatorlariga "
                "to'g'ri kelmasa, e'tiborsiz qoldiriladi.",
                len(bubbles) - expected_total,
                len(bubbles),
                expected_total,
            )

        # Markerlar endi RASM (ArUco), chizma emas — shuning uchun
        # get_image_info() dan qidiriladi. 7mm: logotip 13mm, QR o'rni
        # 32mm, ya'ni chalkashish mumkin emas.
        marker_rects = [
            fitz.Rect(i["bbox"])
            for i in page.get_image_info()
            if _square_like(fitz.Rect(i["bbox"]), marker_pt, 0.20)
        ]
        marker_centers = _merge_close(marker_rects, 2.0)
        if len(marker_centers) != 4:
            raise AnswerSheetGenerationError(
                f"Burchak markerlari {len(marker_centers)} ta topildi (4 ta kerak)."
            )

        # Chegara "1" ning CHAP chekkasidan emas, raqam USTUNINING chap
        # qirrasidan olinadi: raqamlar o'ngga tekislangan, shuning uchun
        # "10" ning x0 si "1" nikidan kichik va aks holda keyingi fanning
        # ikki xonali raqamlari oldingi fan chegarasiga tushib qolardi.
        num_w_pt = layout["num_w"] * _MM_TO_PT
        edges = [r.x1 - num_w_pt - 1.0 for r in ones] + [page.rect.x1 + 1.0]

        result = {
            "page": [page.rect.width, page.rect.height],
            "radius": round(bubble_pt / 2.0, 2),
            "markers": [[round(cx, 2), round(cy, 2)] for cx, cy in marker_centers],
            "subjects": [],
        }
        row_tol = bubble_pt / 2.0

        for i, (spec, sdata) in enumerate(zip(subjects, subjects_data)):
            lo, hi = edges[i], edges[i + 1]
            letters = sdata["letters"]

            block_bubbles = [(cx, cy) for cx, cy in bubbles if lo <= cx < hi]
            numbers: dict[str, object] = {}
            for txt, r in spans:
                if not (lo <= r.x0 < hi and txt.isdigit()):
                    continue
                if txt in numbers:
                    # Bir blok ichida savol raqami takrorlanmasligi kerak —
                    # takrorlansa blok chegarasi noto'g'ri va koordinatalar
                    # aralashib ketgan bo'lardi.
                    raise AnswerSheetGenerationError(
                        f"«{spec.name}» blokida «{txt}» savol raqami bir "
                        f"necha marta uchradi — blok chegarasi noto'g'ri."
                    )
                numbers[txt] = r

            questions: dict[str, list[list[float]]] = {}
            for qn in range(1, spec.question_count + 1):
                num_rect = numbers.get(str(qn))
                if num_rect is None:
                    raise AnswerSheetGenerationError(
                        f"«{spec.name}» fanida {qn}-savol raqami topilmadi."
                    )
                mid_y = (num_rect.y0 + num_rect.y1) / 2.0
                # Shu qatordagi, raqamdan O'NGDAGI doiralar; eng yaqin
                # choice_count tasi — aynan shu savolniki (keyingi ustunning
                # doiralari o'z raqamidan keyin turadi).
                same_row = sorted(
                    (
                        (cx, cy)
                        for cx, cy in block_bubbles
                        if abs(cy - mid_y) <= row_tol and cx > num_rect.x1
                    ),
                    key=lambda p: p[0],
                )[: spec.choice_count]
                if len(same_row) != spec.choice_count:
                    raise AnswerSheetGenerationError(
                        f"«{spec.name}» fanida {qn}-savol uchun "
                        f"{len(same_row)} ta doira topildi, "
                        f"{spec.choice_count} ta kerak."
                    )
                questions[str(qn)] = [
                    [round(cx, 2), round(cy, 2)] for cx, cy in same_row
                ]

            result["subjects"].append(
                {"name": spec.name, "letters": letters, "questions": questions}
            )

        # Yakuniy nazorat: biriktirilgan doiralar soni kutilganga teng va
        # bironta doira IKKI marta ishlatilmagan bo'lishi kerak. Bu asosiy
        # kafolat — yuqoridagi "ortiqcha shakl" holatida ham natija to'g'ri
        # ekanini shu tekshiradi.
        assigned = [
            tuple(c)
            for s in result["subjects"]
            for centers in s["questions"].values()
            for c in centers
        ]
        if len(assigned) != expected_total:
            raise AnswerSheetGenerationError(
                f"Biriktirilgan doiralar soni {len(assigned)}, kutilgani "
                f"{expected_total} ta."
            )
        if len(set(assigned)) != len(assigned):
            raise AnswerSheetGenerationError(
                "Bitta doira bir necha savolga biriktirildi — koordinatalar "
                "ishonchsiz."
            )

        # Doira RAMKAGA tegib turmasligi kerak. Bu — hisob-kitobga emas,
        # CHIZILGAN natijaga qaraydigan himoya: Python konstantalari CSS
        # bilan mos kelmay qolsa (aynan shunday bo'lgan — blok kengligi
        # 2.8mm ortiqcha hisoblanardi), doira ramka bilan kesiladi va uning
        # ichidan qora chiziq o'tadi. Tekshirishda bunday doira "bo'yalgan"
        # deb o'qilishi mumkin, ya'ni xato JIMGINA noto'g'ri natija berardi.
        # Qarang: DECISIONS.md #37.
        # WeasyPrint ramkani CHIZIQ emas, ichi teshik TO'LDIRILGAN shakl
        # ("halqa") qilib chizadi, shuning uchun get_drawings() faqat
        # tashqi to'rtburchakni beradi va chiziq qalinligi bo'sh
        # (width=None) bo'ladi. Qora bo'yoq shu to'rtburchakdan ichkariga
        # _BLOCK_BORDER_MM ga kiradi — oq ichki maydon shundan boshlanadi.
        r_pt = bubble_pt / 2.0
        kerak = (_BLOCK_BORDER_MM + 0.15) * _MM_TO_PT  # +0.15: doira chizig'i yarmi
        ramkalar = [
            d["rect"]
            for d in drawings_meta
            if d["rect"].width > 40 * _MM_TO_PT
            and d["rect"].height > 60 * _MM_TO_PT
        ]
        if ramkalar:
            for cx, cy in assigned:
                # Doirani O'RAB turgan eng kichik ramka — uning bloki.
                ichida = [
                    r for r in ramkalar if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1
                ]
                if not ichida:
                    continue  # ramka topilmadi — tekshirib bo'lmaydi
                blok = min(ichida, key=lambda r: r.get_area())
                chekka = min(
                    cx - r_pt - blok.x0,
                    blok.x1 - (cx + r_pt),
                    cy - r_pt - blok.y0,
                    blok.y1 - (cy + r_pt),
                )
                if chekka < kerak:
                    raise AnswerSheetGenerationError(
                        f"Javob doirasi varaq ramkasiga tegib qoldi "
                        f"(bo'shliq {chekka / _MM_TO_PT:.2f}mm, kamida "
                        f"{kerak / _MM_TO_PT:.2f}mm kerak). Bu sozlama bir "
                        f"varaqqa sig'maydi — savollar sonini kamaytiring "
                        f"yoki variantni 4 ta qiling."
                    )

        return json.dumps(result)
    finally:
        doc.close()


def blank_is_current(field_boxes_json: str | None) -> bool:
    """Saqlangan shablon HOZIRGI format versiyasidami?

    Shablonga yangi maydon qo'shilganda (masalan QR ostidagi ID) fan
    sozlamasi o'zgarmaydi, shuning uchun `blank_matches_subjects` buni
    sezmaydi — versiya alohida tekshiriladi (DECISIONS.md #32).
    """
    if not field_boxes_json:
        return False
    try:
        return int(json.loads(field_boxes_json).get("version", 1)) >= TEMPLATE_VERSION
    except Exception:
        return False


def blank_matches_subjects(
    bubble_boxes_json: str | None, subjects: tuple[SubjectSpec, ...]
) -> bool:
    """Saqlangan shablon HOZIRGI fan sozlamasiga mos keladimi?

    Fanlar qayta sozlanganda shablon bekor qilinadi, lekin bu ikkinchi
    himoya qatlami: agar biror sabab bilan eski shablon qolib ketsa,
    eksport uni ISHLATMASLIGI kerak — aks holda o'quvchilarga eski
    savol soniga mo'ljallangan varaq berilib ketardi (DECISIONS.md #30).
    """
    if not bubble_boxes_json:
        return False
    try:
        data = json.loads(bubble_boxes_json)
        stored = data["subjects"]
    except Exception:
        return False

    if len(stored) != len(subjects):
        return False
    for saved, spec in zip(stored, subjects):
        if saved.get("name") != spec.name:
            return False
        if len(saved.get("letters", "")) != spec.choice_count:
            return False
        if len(saved.get("questions", {})) != spec.question_count:
            return False
    return True


# ---------------------------------------------------------------- 2-bosqich
def _draw_field(page, spec: dict, text: str, centered: bool) -> None:
    import fitz

    if not text:
        return
    box = fitz.Rect(spec["box"])
    text_rect = fitz.Rect(spec["text"])
    max_w = max(box.width - 2 * _BOX_PAD_PT, 1.0)

    size = _STAMP_SIZE_PT
    while (
        size > _STAMP_MIN_SIZE_PT
        and fitz.get_text_length(text, fontname=_STAMP_FONT, fontsize=size) > max_w
    ):
        size -= 0.3

    width = fitz.get_text_length(text, fontname=_STAMP_FONT, fontsize=size)
    if centered:
        x = box.x0 + (box.width - width) / 2
    else:
        x = box.x0 + _BOX_PAD_PT
    # Asos chizig'i: orientir matnning pastki chekkasidan biroz yuqorida
    # (pastki chekka descender'ni ham o'z ichiga oladi).
    baseline = text_rect.y1 - text_rect.height * 0.18

    page.insert_text(
        (x, baseline),
        text,
        fontname=_STAMP_FONT,
        fontsize=size,
        color=_STAMP_COLOR,
    )


def _stamp_sync(
    blank_pdf: bytes, field_boxes_json: str, contexts: list[AnswerSheetContext]
) -> bytes:
    import fitz

    try:
        boxes = json.loads(field_boxes_json)
    except Exception as e:
        raise AnswerSheetGenerationError(
            f"Maydon koordinatalari o'qilmadi: {e}"
        ) from e

    src = fitz.open(stream=blank_pdf, filetype="pdf")
    out = fitz.open()
    try:
        src_rect = src[0].rect
        for ctx in contexts:
            # insert_pdf() EMAS, show_pdf_page(): birinchisi bo'sh sahifaning
            # (og'ir doiralar to'ri bilan) to'liq nusxasini har sahifaga
            # yozadi — 200 ta ishtirokchida fayl ~32MB gacha shishib ketardi.
            # show_pdf_page esa hamma sahifada BITTA umumiy XObject'ga
            # havola qiladi, shuning uchun to'r faylda bir marta yotadi.
            page = out.new_page(width=src_rect.width, height=src_rect.height)
            page.show_pdf_page(src_rect, src, 0)

            values = {
                "ism": ctx.ism,
                "familiya": ctx.familiya,
                "kun": ctx.kun,
                "oy": ctx.oy,
                "yil": ctx.yil,
                "sinf": ctx.sinf,
                "id": ctx.ticket_no,
            }
            for key, text in values.items():
                spec = boxes.get(key)
                if spec:
                    _draw_field(page, spec, str(text or ""), key in _CENTERED_FIELDS)

            qr_spec = boxes.get("qr")
            if qr_spec and ctx.ticket_no:
                page.insert_image(
                    fitz.Rect(qr_spec["box"]), stream=_make_qr_png(ctx.ticket_no)
                )

        return out.tobytes(garbage=3, deflate=True)
    except AnswerSheetGenerationError:
        raise
    except Exception as e:
        raise AnswerSheetGenerationError(f"PDF shtamplashda xato: {e}") from e
    finally:
        out.close()
        src.close()


async def stamp_answer_sheets_pdf(
    blank_pdf: bytes, field_boxes_json: str, contexts: list[AnswerSheetContext]
) -> bytes:
    """Tayyor bo'sh shablon ustiga har bir ishtirokchining ma'lumotini
    qo'yib, BITTA PDF (har biri alohida sahifada) qaytaradi."""
    return await asyncio.to_thread(
        _stamp_sync, blank_pdf, field_boxes_json, contexts
    )
