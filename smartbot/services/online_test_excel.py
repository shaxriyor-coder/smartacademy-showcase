"""Online testlar tarixi — Excel fayl (DECISIONS.md #43).

Ikkita varaq: har bir urinish alohida qator ("Natijalar") va har bir test
bo'yicha yig'ma ko'rsatkich ("Testlar"). Baza so'rovi bu yerda emas —
handler tayyor qatorlarni beradi, shunda fayl bazasiz ham sinaladi
(tests/test_online_test_excel.py).
"""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

RESULT_HEADERS = [
    "T/r",
    "Sana",
    "Test #",
    "Test nomi",
    "O'quvchi",
    "Telefon",
    "Chat ID",
    "To'g'ri",
    "Jami",
    "Foiz",
    "Baho",
    "Xato savollar",
    "Berilgan javoblar",
    "Kalit",
]
RESULT_WIDTHS = [6, 17, 8, 24, 24, 16, 14, 9, 8, 8, 18, 26, 30, 30]

TEST_HEADERS = [
    "Test #",
    "Nomi",
    "Savollar",
    "Ishlaganlar",
    "O'rtacha foiz",
    "Eng yuqori foiz",
    "Yaratilgan",
    "Holati",
]
TEST_WIDTHS = [8, 26, 10, 13, 14, 16, 17, 12]

_HEADER_FILL = PatternFill("solid", fgColor="D9D0EF")
_HEADER_FONT = Font(bold=True)


def grade_label(percent: float) -> str:
    """Botda o'quvchiga ko'rsatiladigan baho bilan bir xil bo'lishi SHART —
    handlers/user.py dagi natija xabaridagi chegaralar (90/70/50)."""
    if percent >= 90:
        return "A'lo"
    if percent >= 70:
        return "Yaxshi"
    if percent >= 50:
        return "Qoniqarli"
    return "Yana harakat qiling"


def wrong_questions(given: str, key: str) -> str:
    """Xato javob berilgan savol raqamlari, vergul bilan.

    Javoblar soni kalitdan kam bo'lsa (eski yozuv yoki yarim ishlangan test)
    yetmagani xato hisoblanadi — o'quvchiga ko'rsatilgan hisob ham shunday.
    """
    given_list = [x.strip().upper() for x in (given or "").split(",") if x.strip()]
    key_list = [x.strip().upper() for x in (key or "").split(",") if x.strip()]
    wrong = [
        str(i)
        for i in range(1, len(key_list) + 1)
        if i > len(given_list) or given_list[i - 1] != key_list[i - 1]
    ]
    return ", ".join(wrong)


def _write_header(ws, headers: list[str], widths: list[int]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def build_history_excel(results: list[dict], tests: list[dict]) -> bytes:
    """`results` — har bir urinish (yangisi birinchi), `tests` — yig'ma.

    Kutiladigan kalitlar:
      results: checked_at, test_id, title, full_name, phone, chat_id,
               correct, total, given, key
      tests:   test_id, title, questions, solved, avg_percent, max_percent,
               created_at, archived
    """
    wb = Workbook()

    ws = wb.active
    ws.title = "Natijalar"
    _write_header(ws, RESULT_HEADERS, RESULT_WIDTHS)
    for idx, r in enumerate(results, 1):
        total = r.get("total") or 0
        correct = r.get("correct") or 0
        percent = round(correct / total * 100, 1) if total else 0.0
        checked_at = r.get("checked_at")
        ws.append(
            [
                idx,
                checked_at.strftime("%Y-%m-%d %H:%M") if checked_at else "-",
                r.get("test_id"),
                r.get("title") or "-",
                r.get("full_name") or "-",
                r.get("phone") or "-",
                r.get("chat_id"),
                correct,
                total,
                percent,
                grade_label(percent),
                wrong_questions(r.get("given", ""), r.get("key", "")) or "-",
                r.get("given") or "-",
                r.get("key") or "-",
            ]
        )

    ws2 = wb.create_sheet("Testlar")
    _write_header(ws2, TEST_HEADERS, TEST_WIDTHS)
    for t in tests:
        created_at = t.get("created_at")
        ws2.append(
            [
                t.get("test_id"),
                t.get("title") or "-",
                t.get("questions"),
                t.get("solved"),
                round(t["avg_percent"], 1) if t.get("avg_percent") is not None else "-",
                round(t["max_percent"], 1) if t.get("max_percent") is not None else "-",
                created_at.strftime("%Y-%m-%d %H:%M") if created_at else "-",
                "Arxivda" if t.get("archived") else "Faol",
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def history_filename(now: datetime | None = None, test_id: int | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    if test_id is not None:
        return f"online_test_{test_id}_natijalar_{stamp}.xlsx"
    return f"online_testlar_tarixi_{stamp}.xlsx"
