import re
import json
import logging
from datetime import date

logger = logging.getLogger(__name__)


MONTHS_MAP = {
    "sentyabr": 9,
    "sentabr": 9,
    "oktyabr": 10,
    "oktabr": 10,
    "noyabr": 11,
    "dekabr": 12,
    "yanvar": 1,
    "fevral": 2,
    "mart": 3,
    "aprel": 4,
    "may": 5,
    "iyun": 6,
    "iyul": 7,
    "avgust": 8,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def parse_flexible_date(text: str) -> date | None:
    """
    Foydalanuvchi kiritgan har xil formatdagi sanalarni date obyektiga o'tkazadi.
    Masalan:
    - 2003.02.19
    - 2003 02 19
    - 2003-02-19
    - 2003yil 2-oy 19-kun
    - 2003-yil fevral 19
    - 19.02.2003
    """
    if not text:
        return None

    s = text.strip().lower()

    # Oy nomlarini raqam ko'rinishiga o'tkazamiz
    for m_name, m_num in MONTHS_MAP.items():
        if m_name in s:
            s = s.replace(m_name, f" {m_num} ")
            break

    # keraksiz so'z va qo'shimchalarni tozalaymiz
    s = re.sub(r"yil|y\.|oy|kun|k\.|г\.|г|года|год", " ", s)

    # Faqat raqamlarni ajratib olamiz
    numbers = [int(n) for n in re.findall(r"\d+", s)]

    if len(numbers) != 3:
        return None

    y, m, d = None, None, None

    # 4-xonali yilni topamiz
    year_idx = -1
    for idx, num in enumerate(numbers):
        if 1900 <= num <= 2026:
            y = num
            year_idx = idx
            break

    if y is not None:
        remains = [numbers[i] for i in range(3) if i != year_idx]
        if year_idx == 0:  # YYYY MM DD yoki YYYY DD MM
            cand1, cand2 = remains[0], remains[1]
            if 1 <= cand1 <= 12 and 1 <= cand2 <= 31:
                m, d = cand1, cand2
            elif 1 <= cand2 <= 12 and 1 <= cand1 <= 31:
                m, d = cand2, cand1
        else:  # DD MM YYYY yoki MM DD YYYY
            cand1, cand2 = remains[0], remains[1]
            if 1 <= cand2 <= 12 and 1 <= cand1 <= 31:
                d, m = cand1, cand2
            elif 1 <= cand1 <= 12 and 1 <= cand2 <= 31:
                m, d = cand1, cand2
    else:
        # 2-xonali yil kiritilganda (masalan: 03.02.19 yoki 19.02.03)
        n0, n1, n2 = numbers[0], numbers[1], numbers[2]
        if n0 > 31 or (n0 <= 30 and n2 <= 31 and n1 <= 12):
            y = 1900 + n0 if n0 > 30 else 2000 + n0
            m, d = n1, n2
        elif n2 > 31 or (n2 <= 30 and n0 <= 31 and n1 <= 12):
            y = 1900 + n2 if n2 > 30 else 2000 + n2
            d, m = n0, n1

    if y and m and d:
        try:
            return date(y, m, d)
        except ValueError:
            return None

    return None


def apply_rubric(
    mask: list[bool], rubric_json: str | None, fallback_count: int
) -> tuple[float, float, list[dict] | None]:
    """Baholash mezoniga (savol boshiga necha ball) asosan og'irlikli
    ballni hisoblaydi.

    `mask` — har savol uchun to'g'ri/noto'g'ri (savol tartibida,
    0-indeksli), tekshiruvchidan keladi.

    `rubric_json` bo'sh/`None` bo'lsa — MEZON YO'Q: eski xatti-harakat
    qaytariladi (1 to'g'ri javob = 1 ball, `fallback_count`), tafsilotsiz.
    Bu muhim — mezon kiritilmagan fan aynan shu holda, oddiy
    to'g'ri/jami hisobida qoladi.

    Qaytaradi: (score, max_score, detail) — `detail` fan ichidagi
    oraliqlar ro'yxati, `services/excel_import.py`dagi `ParsedRow.detail`
    bilan bir xil shaklda (matn ko'rinishidagi natijada birgalikda
    ishlatilishi uchun).
    """
    if not rubric_json:
        return float(fallback_count), float(len(mask)), None

    try:
        rubric = json.loads(rubric_json)
    except (TypeError, ValueError):
        return float(fallback_count), float(len(mask)), None

    n = len(mask)
    mode = rubric.get("mode")

    if mode == "uniform":
        points = float(rubric.get("points") or 1.0)
        correct = sum(1 for x in mask if x)
        score = correct * points
        max_score = n * points
        detail = [
            {
                "range": f"1-{n}" if n else "-",
                "correct": correct,
                "total": n,
                "score": round(score, 2),
                "points_per_q": points,
            }
        ]
        return score, max_score, detail

    if mode == "ranges":
        detail = []
        total_score = 0.0
        max_score = 0.0
        for rng in rubric.get("ranges", []):
            frm, to = int(rng["from"]), int(rng["to"])
            points = float(rng["points"])
            # Savol raqamlari 1-indeksli, mask 0-indeksli.
            lo, hi = max(0, frm - 1), min(n, to)
            if lo >= hi:
                continue
            segment = mask[lo:hi]
            correct = sum(1 for x in segment if x)
            total = len(segment)
            seg_score = correct * points
            total_score += seg_score
            max_score += total * points
            detail.append(
                {
                    "range": f"{frm}-{to}",
                    "correct": correct,
                    "total": total,
                    "score": round(seg_score, 2),
                    "points_per_q": points,
                }
            )
        return total_score, max_score, (detail or None)

    return float(fallback_count), float(len(mask)), None


def fmt_number(value, decimals: int = 2) -> str:
    """Sonni ko'rsatishga tayyorlaydi — float xatoligidan tozalaydi.

    Excel'dan yoki bo'lishdan kelgan qiymatlar ko'pincha
    5.300000000000001 kabi chiqadi. Bu funksiya uni "5.3" ga, butun
    sonlarni esa (12.0) "12" ga aylantiradi.

    >>> fmt_number(5.300000000000001)
    '5.3'
    >>> fmt_number(12.0)
    '12'
    >>> fmt_number(None)
    '-'
    """
    if value is None:
        return "-"
    r = round(float(value), decimals)
    if r == int(r):
        return str(int(r))
    s = f"{r:.{decimals}f}".rstrip("0").rstrip(".")
    return s


# Ticket_no ichiga tushmasligi kerak bo'lgan umumiy so'zlar — bular kod
# sifatida tanlansa hech qanday olimpiadani boshqasidan ajratmas edi.
_CODE_STOPWORDS = {"SINF", "OLIMPIADA", "OLIMPIADASI", "UCHUN", "VA", "BOYICHA"}


def slugify_olympiad_code(name: str) -> str:
    """Olimpiada nomidan ruxsatnoma ticket_no ichiga tushadigan qisqa kod
    yasaydi (masalan "4-sinf matematika olimpiadasi" -> "MATEMATIKA").

    Faqat lotin harflaridan iborat birinchi "ma'noli" so'z olinadi —
    operator ticket_no'ni qo'lda ham terishi mumkinligi uchun kodda
    apostrof yoki o'zbekcha maxsus harf (o', g') bo'lmasligi kerak.
    """
    words = re.findall(r"[A-Za-z]+", name or "")
    candidates = [w.upper() for w in words if len(w) >= 3]
    for w in candidates:
        if w not in _CODE_STOPWORDS:
            return w[:10]
    return candidates[0][:10] if candidates else "GEN"


MAX_GRADE = 11


def academic_year_start(today: date | None = None) -> int:
    """Joriy o'quv yili boshlangan yil (1-sentabrdan yangi o'quv yili)."""
    today = today or date.today()
    return today.year if today.month >= 9 else today.year - 1


def current_grade(grade: int, grade_year: int, today: date | None = None) -> int:
    """Kiritilgan sinfni o'tgan o'quv yillari soniga oshiradi.

    Ota-ona sinfni faqat bir marta kiritadi (farzand qo'shilganda), keyin bot
    uni har 1-sentabrda o'zi oshiradi (database/models.py -> Child). 11-sinfdan
    keyin oshmaydi — bitiruvchi ro'yxatda o'sha holida qoladi.
    """
    passed = max(0, academic_year_start(today) - grade_year)
    return min(MAX_GRADE, grade + passed)


def split_full_name(full_name: str) -> tuple[str, str]:
    """full_name'ni (first_name, last_name) ga ajratadi.

    Qoida: OXIRGI so'z familiya (last_name), qolgan qismi ism
    (first_name) — uch (yoki undan ko'p) so'zli ismlarda ham
    ("Ali Vali Valiyev" -> ism="Ali Vali", familiya="Valiyev").

    Faqat first_name/last_name to'ldirilmagan ESKI OlympiadResult
    yozuvlari uchun zaxira sifatida ishlatiladi — yangi ro'yxatdan
    o'tishda ikkalasi alohida so'raladi va to'g'ridan-to'g'ri saqlanadi.
    """
    parts = (full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]
