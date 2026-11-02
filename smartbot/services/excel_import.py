"""Olimpiada natijalari Excel faylini o'qish.

Haqiqiy fayllarda sarlavha bir qatorda turmaydi. Namunaviy faylda u
uch qatorga tarqalgan:

    2-qator:  №  |  O'quvchining ismi va familiyasi  |  4-sinf natijalari
    3-qator:                                         |  Sinf | Matematika | ... | umumiy ball | umumiy foiz (%)
    4-qator:                                         |       | 1-12-savollar | ...
    5-qator:  1  |  Yusufjonov Iskandar             |  4-sinf | 12 | ...

Shuning uchun `header=0` ga tayanib bo'lmaydi — sarlavha qatori
kalit so'zlar bo'yicha qidiriladi va bir necha qator birlashtiriladi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

logger = logging.getLogger(__name__)

# Sarlavhani qidirishda nechta qatorni ko'rib chiqamiz
HEADER_SCAN_ROWS = 15
# Sarlavha bir necha qatorga tarqalgan bo'lishi mumkin
HEADER_MERGE_ROWS = 3

# Ustunlarni tanib olish uchun kalit so'zlar (normalizatsiya qilingan holda)
COLUMN_PATTERNS: dict[str, tuple[str, ...]] = {
    "full_name": ("ismi va familiya", "ism va familiya", "fish", "f i sh", "oquvchining ismi"),
    "grade": ("sinf",),
    "score": ("umumiy ball", "jami ball", "umumiy natija", "ball"),
    "percentage": ("umumiy foiz", "foiz", "%"),
    "math": ("matematika",),
    "english": ("ingliz tili", "ingliz"),
    "row_no": ("№", "n", "t/r", "tr"),
}


class ExcelStructureError(Exception):
    """Excel tuzilishi tanib bo'lmadi."""


@dataclass
class ParsedRow:
    """Excel'dan o'qilgan bitta o'quvchi qatori."""

    row_no: int
    full_name: str
    grade: int | None
    score: float | None
    percentage: float | None
    math_correct: float | None = None
    english_correct: float | None = None
    math_total: int | None = None
    english_total: int | None = None
    # Fan ichidagi savol-oraliqlari bo'yicha tafsilot (topilsa):
    # {"matematika": [{"range": "1-12", "correct": 6, "total": 12, "score": 6.6}, ...],
    #  "ingliz_tili": [...]}
    detail: dict | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return bool(self.full_name) and self.score is not None


@dataclass
class ParseReport:
    """Faylni o'qish natijasi."""

    rows: list[ParsedRow]
    header_row: int
    columns: dict[str, int]
    skipped: list[str] = field(default_factory=list)


def _norm(v) -> str:
    """Sarlavha katagini solishtirishga tayyorlaydi."""
    if v is None:
        return ""
    s = str(v).lower().strip()
    s = s.replace("‘", "").replace("’", "").replace("'", "").replace("`", "")
    s = re.sub(r"\s+", " ", s)
    return s


def parse_grade(value) -> int | None:
    """"4-sinf", "4", "4 sinf", 4.0 -> 4"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        return n if 1 <= n <= 11 else None
    m = re.search(r"(\d{1,2})", str(value))
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 11 else None


def parse_number(value) -> float | None:
    """Ball/foizni o'qiydi: 87, 87.5, "87,5", "87.45%", bo'sh, NaN."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        # NaN o'zi bilan teng emas
        return None if f != f else f
    s = str(value).strip().replace("%", "").replace(" ", "")
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return None if f != f else f


def _find_header(ws) -> tuple[int, dict[str, int]]:
    """Sarlavha qatorini va ustun raqamlarini aniqlaydi.

    Har bir nomzod qator uchun o'zidan keyingi HEADER_MERGE_ROWS qatorni
    ham qo'shib ko'radi — sarlavha bo'lingan holatni shu hal qiladi.
    """
    best: tuple[int, dict[str, int]] | None = None
    best_score = 0
    max_row = min(ws.max_row, HEADER_SCAN_ROWS)

    for top in range(1, max_row + 1):
        cols: dict[str, int] = {}
        for offset in range(HEADER_MERGE_ROWS):
            r = top + offset
            if r > ws.max_row:
                break
            for c in range(1, ws.max_column + 1):
                text = _norm(ws.cell(r, c).value)
                if not text:
                    continue
                for key, patterns in COLUMN_PATTERNS.items():
                    if key in cols:
                        continue
                    for pat in patterns:
                        if pat and pat in text:
                            cols[key] = c
                            break

        # Ism va ball — majburiy; qolgani bonus
        score = 0
        if "full_name" in cols:
            score += 10
        if "score" in cols:
            score += 6
        if "grade" in cols:
            score += 3
        score += sum(1 for k in ("percentage", "math", "english") if k in cols)

        if score > best_score:
            best_score, best = score, (top, cols)

    if not best or "full_name" not in best[1]:
        raise ExcelStructureError(
            "Ism-familiya ustuni topilmadi. Faylda "
            "«O'quvchining ismi va familiyasi» kabi sarlavha bo'lishi kerak."
        )
    if "score" not in best[1]:
        raise ExcelStructureError(
            "Ball ustuni topilmadi. Faylda «umumiy ball» kabi sarlavha "
            "bo'lishi kerak."
        )
    return best


# "1-12-savollar", "13 - 30 savollari" kabi savol-oralig'i sarlavhalarini topadi.
# Ikkinchi son bilan "savol" orasida ham chiziqcha bo'lishi mumkin
# ("1-12-savollar" — 12 va "savollar" orasida "-" bor), shuning uchun
# oxirgi bo'g'in ixtiyoriy chiziqcha/bo'shliq bilan yozilgan.
_RANGE_PATTERN = re.compile(r"(\d+)\s*[-–]\s*(\d+)[\s\-–]*savol")

# Ball ustuni sarlavhasidan savol boshiga necha ball berilishini o'qiydi:
# "1-12-savollarga 1,1 balldan jami 13,2 ball" -> 1.1
_POINTS_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*balldan")


def _find_range_columns(ws, header_row: int) -> dict[str, list[dict]]:
    """Har bir fan ichidagi savol-oraliqlarini (masalan "1-12-savollar" +
    yonidagi "...balldan jami N ball" ustuni) topadi.

    `_find_header()`dagi yagona-ustun ("math"/"english") tanlashiga
    tegilmaydi — bu unga QO'SHIMCHA, alohida aniqlash bosqichi. Oraliq
    topilmasa (fayl eski/oddiy formatda bo'lsa), bo'sh lug'at qaytadi va
    import hozirgidek ishlayveradi.

    Qaytadi: {"matematika": [{"col": 4, "ball_col": 5, "from": 1, "to": 12,
              "points_per_q": 1.1}, ...], "ingliz_tili": [...]}
    """
    subject_keywords = (("matematika", "matematika"), ("ingliz", "ingliz_tili"))
    result: dict[str, list[dict]] = {}
    current_subject: str | None = None

    top = max(1, header_row - HEADER_MERGE_ROWS + 1)
    bottom = min(ws.max_row, header_row + HEADER_MERGE_ROWS)

    # Ustunlar bo'yicha (qatorlar emas) — fan nomi (masalan "Matematika")
    # va savol-oraliqlari bir xil ustunlar guruhi ustida, turli qatorlarda
    # turadi (odatda birlashtirilgan katak sifatida).
    for c in range(1, ws.max_column + 1):
        col_text = " ".join(
            t
            for t in (_norm(ws.cell(r, c).value) for r in range(top, bottom + 1))
            if t
        )
        if not col_text:
            continue

        for kw, subject in subject_keywords:
            if kw in col_text:
                current_subject = subject

        # Ball ustunining o'zi ham "1-12-savollarGA ... ball" deb boshlanishi
        # mumkin — bu range-ustun emas, uni tashlab yuboramiz.
        if "ball" in col_text:
            continue

        m = _RANGE_PATTERN.search(col_text)
        if not m:
            continue
        frm, to = int(m.group(1)), int(m.group(2))
        if to < frm:
            continue

        ball_col = c + 1
        ball_text = " ".join(
            t
            for t in (_norm(ws.cell(r, ball_col).value) for r in range(top, bottom + 1))
            if t
        )
        if "ball" not in ball_text:
            continue

        points_m = _POINTS_PATTERN.search(ball_text)
        points_per_q = float(points_m.group(1).replace(",", ".")) if points_m else None

        subject = current_subject or "fan"
        result.setdefault(subject, []).append(
            {
                "col": c,
                "ball_col": ball_col,
                "from": frm,
                "to": to,
                "points_per_q": points_per_q,
            }
        )

    return result


def parse_results_excel(path: str, expected_grade: int | None = None) -> ParseReport:
    """Excel faylini o'qib, o'quvchi qatorlarini qaytaradi.

    `expected_grade` berilsa, boshqa sinf qatorlari `problems` ga
    belgilanadi (avtomatik tashlab yuborilmaydi — admin ko'rib chiqadi).
    """
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception as e:  # noqa: BLE001 - fayl buzuq bo'lishi mumkin
        raise ExcelStructureError(f"Faylni ochib bo'lmadi: {e}") from e

    try:
        ws = None
        for sheet in wb.worksheets:
            if sheet.max_row and sheet.max_row > 1:
                ws = sheet
                break
        if ws is None:
            raise ExcelStructureError("Faylda ma'lumot topilmadi.")

        header_row, cols = _find_header(ws)
        name_col = cols["full_name"]
        range_cols = _find_range_columns(ws, header_row)

        rows: list[ParsedRow] = []
        skipped: list[str] = []

        for r in range(header_row + 1, ws.max_row + 1):
            raw_name = ws.cell(r, name_col).value
            name = "" if raw_name is None else str(raw_name).strip()
            if not name:
                continue
            # Sarlavhaning o'zi (yoki uning davomi) ma'lumot qatori bo'lib
            # qolmasin — u ko'p qatorga tarqalgani uchun ism ustunida ham
            # sarlavha matni uchraydi.
            norm_name = _norm(name)
            if any(pat in norm_name for pat in COLUMN_PATTERNS["full_name"]):
                continue

            grade = parse_grade(ws.cell(r, cols["grade"]).value) if "grade" in cols else None
            score = parse_number(ws.cell(r, cols["score"]).value)
            percentage = (
                parse_number(ws.cell(r, cols["percentage"]).value)
                if "percentage" in cols
                else None
            )
            math_c = parse_number(ws.cell(r, cols["math"]).value) if "math" in cols else None
            eng_c = (
                parse_number(ws.cell(r, cols["english"]).value)
                if "english" in cols
                else None
            )
            math_total = None
            eng_total = None

            # Oraliqlar topilgan bo'lsa — tafsilotli lug'at quramiz va
            # matematika/ingliz yig'indisini shulardan (aniqroq) hisoblaymiz.
            detail: dict[str, list[dict]] = {}
            for subject, ranges in range_cols.items():
                items = []
                correct_sum = 0.0
                total_sum = 0
                for rng in ranges:
                    correct = parse_number(ws.cell(r, rng["col"]).value)
                    ball = parse_number(ws.cell(r, rng["ball_col"]).value)
                    total = rng["to"] - rng["from"] + 1
                    if correct is None and ball is None:
                        continue
                    items.append(
                        {
                            "range": f"{rng['from']}-{rng['to']}",
                            "correct": correct,
                            "total": total,
                            "score": ball,
                            "points_per_q": rng.get("points_per_q"),
                        }
                    )
                    correct_sum += correct or 0
                    total_sum += total
                if items:
                    detail[subject] = items
                    if subject == "matematika":
                        math_c, math_total = correct_sum, total_sum
                    elif subject == "ingliz_tili":
                        eng_c, eng_total = correct_sum, total_sum

            problems: list[str] = []
            if score is None:
                problems.append("ball o'qilmadi")
            if expected_grade is not None and grade is not None and grade != expected_grade:
                problems.append(f"sinf mos emas ({grade}-sinf)")

            row = ParsedRow(
                row_no=r,
                full_name=name,
                grade=grade,
                score=score,
                percentage=percentage,
                math_correct=math_c,
                english_correct=eng_c,
                math_total=math_total,
                english_total=eng_total,
                detail=detail or None,
                problems=problems,
            )
            if not row.is_usable and score is None:
                skipped.append(f"{r}-qator: {name} — ball yo'q")
            rows.append(row)

        logger.info(
            "Excel o'qildi: sarlavha=%s qatorlar=%s ustunlar=%s",
            header_row,
            len(rows),
            sorted(cols),
        )
        return ParseReport(
            rows=rows, header_row=header_row, columns=cols, skipped=skipped
        )
    finally:
        wb.close()
