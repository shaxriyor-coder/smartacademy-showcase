"""Mustaqil javob varag'i uchun ishtirokchilar Excel'i.

Bu yerda FAQAT javob varag'ini to'ldirishga yetadigan ma'lumot bor:
ism, familiya, tug'ilgan sana va sinf — varaqdagi maydonlar aynan shular
(qarang: utils/assets/answer_sheet/answer_sheet.html). Telefon, maktab
va hokazo so'ralmaydi, chunki varaqqa chiqmaydi va bu odamlar botda
ro'yxatdan o'tmagan bo'lishi mumkin (DECISIONS.md #34).
"""

from __future__ import annotations

import io
import logging

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from utils.utility import parse_flexible_date

logger = logging.getLogger(__name__)

HEADERS = ["№", "Ism", "Familiya", "Tug'ilgan sana", "Sinf"]
_HEADER_FILL = PatternFill("solid", fgColor="D9D0EF")
_HEADER_FONT = Font(bold=True)
MAX_PARTICIPANTS = 500


class ParticipantsExcelError(Exception):
    """Fayl umuman o'qilmaganda ko'tariladi."""


def build_participants_template() -> bytes:
    """Admin to'ldirib qaytaradigan namuna faylni yasaydi."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Ishtirokchilar"

    ws.append(HEADERS)
    for i, cell in enumerate(ws[1], 1):
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Namuna qatorlar — admin ularni o'chirib, o'zinikini yozadi.
    ws.append([1, "Ali", "Valiyev", "15.05.2010", "9-sinf"])
    ws.append([2, "Robiya", "Karimova", "03.09.2011", "8-sinf"])

    widths = [6, 18, 20, 18, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    note = ws.cell(6, 1, "Eslatma: yuqoridagi 2 qatorni o'chirib, o'z ro'yxatingizni yozing. "
                         "«Tug'ilgan sana» va «Sinf» bo'sh qolishi ham mumkin.")
    note.font = Font(italic=True, color="777777")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_participants(data: bytes) -> tuple[list[dict], list[str]]:
    """Yuklangan Excel'dan ishtirokchilarni o'qiydi.

    Qaytaradi: (qatorlar, ogohlantirishlar). Qatorda ism yoki familiyadan
    biri bo'lsa yetarli — varaqda ikkalasi alohida maydon, biri bo'sh
    qolsa ham varaq yaroqli. Ikkalasi ham bo'sh qator o'tkazib yuboriladi
    (Excel'da odatda pastda bo'sh qatorlar qolib ketadi).
    """
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as e:
        raise ParticipantsExcelError(
            "Faylni Excel sifatida o'qib bo'lmadi. .xlsx formatida yuboring."
        ) from e

    ws = wb.active
    rows: list[dict] = []
    warnings: list[str] = []

    for excel_row, values in enumerate(ws.iter_rows(values_only=True), 1):
        if not values:
            continue
        cells = list(values) + [None] * (5 - len(values))
        # Sarlavha qatorini o'tkazib yuboramiz (birinchi ustun "№" yoki
        # matn bo'lsa — bu ma'lumot emas).
        first = str(cells[0] or "").strip().lower()
        if excel_row == 1 or first in ("№", "no", "n", "t/r", "#"):
            continue

        ism = str(cells[1] or "").strip()
        familiya = str(cells[2] or "").strip()
        if not ism and not familiya:
            continue

        raw_date = cells[3]
        birth = None
        if raw_date not in (None, ""):
            if hasattr(raw_date, "date"):          # Excel sana yacheykasi
                birth = raw_date.date()
            elif hasattr(raw_date, "year"):
                birth = raw_date
            else:
                birth = parse_flexible_date(str(raw_date).strip())
                if birth is None:
                    warnings.append(
                        f"{excel_row}-qator: «{raw_date}» sana sifatida "
                        f"tushunilmadi, bo'sh qoldirildi."
                    )

        sinf = str(cells[4] or "").strip()
        rows.append(
            {
                "row_no": len(rows) + 1,
                "ism": ism[:150],
                "familiya": familiya[:150],
                "birth_date": birth,
                "sinf": sinf[:50],
            }
        )

        if len(rows) >= MAX_PARTICIPANTS:
            warnings.append(
                f"Faqat birinchi {MAX_PARTICIPANTS} ta qator olindi "
                f"(bir varaqqa shundan ko'pi ko'p)."
            )
            break

    return rows, warnings
