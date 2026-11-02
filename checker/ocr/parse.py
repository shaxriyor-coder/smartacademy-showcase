"""Tesseract qatorlaridan test savollarini ajratib olish.

Bu modul rasm bilan ishlamaydi: kirishi — sahifalardagi qatorlar (matn,
koordinata, ishonchi past so'zlar), chiqishi — savollar. Shuning uchun uni
Tesseract'siz test qilish mumkin (tests/test_ocr_parse.py).

Qoidalar:
- savol "12." yoki "12)" bilan boshlanadi va raqami oldingisidan +1 bo'ladi.
  Aks holda qator boshidagi son ("3, 5, 1 ...", "200 000 so'm") yangi savol
  bo'lib ketardi. Bitta savol o'qilmay qolsa (+2), savol baribir boshlanadi,
  lekin tekshirishga belgilanadi;
- variantlar "A)" ... "E)" (yoki "A."), bir qatorda bir nechtasi bo'lishi
  mumkin; harflar A dan boshlab ketma-ket keladi va birinchisi qator boshida
  turadi;
- birinchi savoldan oldingi kanal nomi (@...) va sana qatorlari tashlanadi,
  qolgani test sarlavhasi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LETTERS = "ABCDE"


@dataclass
class Row:
    """Sahifadagi bitta ko'rinadigan qator (so'zlar chapdan o'ngga)."""

    text: str
    top: int
    bottom: int
    left: int
    right: int
    uncertain: list[str] = field(default_factory=list)


@dataclass
class Segment:
    """Savolning bitta sahifadagi bo'lagi (y oralig'i, qator koordinatasida)."""

    page: int
    top: int
    bottom: int | None = None  # None — sahifa oxirigacha
    rows: int = 0


@dataclass
class Question:
    number: int
    text: str = ""
    options: list[str] = field(default_factory=list)
    options_are_images: bool = False
    segments: list[Segment] = field(default_factory=list)
    option_rows: list[tuple[int, Row]] = field(default_factory=list)  # (sahifa, qator)
    uncertain: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    last_line: str = ""


@dataclass
class ParseResult:
    title: str
    questions: list[Question]


# --- matnni tekislash ---------------------------------------------------------

# o‘/g‘ dagi tutuq belgisi rasmlarda turlicha chiqadi — bittasiga keltiramiz
# (U+2018), aks holda bazada "to'g'ri" va "to‘g‘ri" ikki xil matn bo'lib qoladi.
_OG_MARK = re.compile(r"(?<=[oOgG])[ʻʼ'’`‘]")
# Past sifatli rasmda tutuq nuqta yoki darajaga o'xshab o'qiladi ("so·m").
_OG_NOISE = re.compile(r"(?<=[oOgG])[´·°](?=[a-zA-Z])")
_TIMES = re.compile(r"(?<=\d) ?[xх] ?(?=\d)")
# Suv belgisi ustidagi "0" "@" bo'lib o'qiladi ("3@"); raqam yonida "@" bo'lmaydi.
_AT_ZERO = re.compile(r"(?<=\d)@|@(?=\d)")
_UNIT = re.compile(r"(?<=\d)(kg|km|sm|mm|ml|mg|m|g)\b")  # "3kg" -> "3 kg"
_OPERATOR = re.compile(r"\s*([+=])\s*(?=\d)")  # formulada "+192" -> "+ 192"
_SPACES = re.compile(r"[ \t]+")


def normalize(text: str) -> str:
    text = _OG_MARK.sub("‘", text)
    text = _OG_NOISE.sub("‘", text)
    text = _TIMES.sub(" × ", text)
    text = _AT_ZERO.sub("0", text)
    text = _UNIT.sub(r" \1", text)
    text = _SPACES.sub(" ", text).strip()
    if _is_formula(text):
        text = _SPACES.sub(" ", _OPERATOR.sub(r" \1 ", text)).strip()
    return text


_HEADER = re.compile(r"@\w|t\.me/|kanal|\b\d{1,2}\.\d{1,2}\.\d{4}\b", re.IGNORECASE)
_FORMULA = re.compile(r"[\d\s+\-−–—×x*/=:.,()_?■^<>≤≥%]+")


def _is_formula(line: str) -> bool:
    return (
        bool(_FORMULA.fullmatch(line))
        and any(ch.isdigit() for ch in line)
        and any(op in line for op in "+-−–×*/=<>≤≥")
    )


def _append_line(existing: str, line: str, previous_line: str) -> str:
    """Savol matniga keyingi qatorni qo'shadi.

    Oddiy o'ralgan qator bo'sh joy bilan ulanadi; alohida qatordagi formula
    va savol/ikki nuqta bilan tugagan qatordan keyingisi yangi qatordan
    boshlanadi. Nuqta bilan tugagan qator ko'pincha shunchaki o'ralgan gap.
    """
    if not existing:
        return line
    if existing.endswith("-"):
        return existing + line  # "ketma-" + "ketlikda"
    if existing.endswith(("?", ":", "!")) or _is_formula(line) or _is_formula(previous_line):
        return f"{existing}\n{line}"
    return f"{existing} {line}"


# --- savol boshi va variantlar -----------------------------------------------

_QUESTION = re.compile(r"^([0-9lI|SO]{1,3})\s?[.)]\s*(.*)$")


def _question_start(text: str) -> tuple[int, str] | None:
    m = _QUESTION.match(text)
    if not m:
        return None
    digits = m.group(1).translate(str.maketrans("lI|SO", "11150"))  # "l." -> "1.", "S." -> "5."
    return int(digits), m.group(2).strip()


# Tesseract variant harfini ba'zan boshqa belgi bilan adashtiradi: "8)" (B),
# "0)" (D), "(')" (C). Ular faqat kutilgan harf o'rnida kelsagina qabul qilinadi.
_MARKER = re.compile(r"(?<!\S)(\('|[A-Ea-e]|[480O€£(])\s?[).\]}]")
_MARKER_CANON = {"4": "A", "8": "B", "0": "D", "O": "D", "€": "C", "(": "C", "('": "C", "£": "E"}


def split_options(text: str, next_index: int) -> tuple[list[str], list[str]] | None:
    """Qator variant bilan boshlansa — (variant matnlari, o'qilmay qolgan harflar).

    `next_index` — kutilayotgan harf (0 = A). Marker kutilgan harfdan bitta
    oldinda bo'lsa (masalan "A) 5 B) 6 D) 8" da C o'qilmagan), tushib qolgan
    variant bo'sh matn bilan to'ldiriladi.
    """
    accepted: list[tuple[int, int, str | None]] = []  # (boshi, oxiri, tushib qolgan harf)
    expected = next_index
    for m in _MARKER.finditer(text):
        token = m.group(1)
        # "A." ham marker, lekin "a." (gap oxiridagi so'z) emas.
        if m.group(0).rstrip().endswith(".") and not token.isupper():
            continue
        letter = _MARKER_CANON.get(token, token.upper())
        if expected >= len(LETTERS):
            break
        if letter == LETTERS[expected]:
            if not accepted and m.start() != 0:
                return None
            accepted.append((m.start(), m.end(), None))
            expected += 1
        elif (
            expected + 1 < len(LETTERS)
            and letter == LETTERS[expected + 1]
            and (accepted or m.start() == 0)
        ):
            accepted.append((m.start(), m.end(), LETTERS[expected]))
            expected += 2
    if not accepted:
        return None
    parts: list[str] = []
    missing: list[str] = []
    for i, (_, end, skipped) in enumerate(accepted):
        if skipped:
            parts.append("")
            missing.append(skipped)
        stop = accepted[i + 1][0] if i + 1 < len(accepted) else len(text)
        parts.append(text[end:stop].strip())
    return parts, missing


# --- sahifalar -> savollar ----------------------------------------------------


def _close_segment(question: Question, page: int, bottom: int) -> None:
    seg = question.segments[-1]
    if seg.page != page:
        return
    if seg.rows == 0 and seg.top == 0 and len(question.segments) > 1:
        question.segments.pop()  # yangi sahifa darhol yangi savol bilan boshlandi
    else:
        seg.bottom = bottom


def _finalize(q: Question) -> None:
    q.text = q.text.strip()
    q.options = [o.strip() for o in q.options]
    readable = [any(ch.isalnum() for ch in o) for o in q.options]
    # Variantlar rasm yoki kasr bo'lsa, Tesseract faqat harflarni va shovqinni
    # o'qiydi — ularning yarmidan ko'pi ma'nosiz bo'lsa, variantlar rasmda.
    if q.options and sum(readable) <= len(q.options) // 2:
        q.options = list(LETTERS[: len(q.options)])
        q.options_are_images = True
        q.notes.append("Variantlar rasmda — rasm to'g'ri kesilganini tekshiring")
    elif not all(readable):
        q.notes.append("Ba'zi variantlar o'qilmadi")
    if len(q.options) not in (4, 5):
        q.notes.append(f"{len(q.options)} ta variant topildi (4 yoki 5 bo'lishi kerak)")
    if not q.text:
        q.notes.append("Savol matni o'qilmadi")
    if len(q.options) >= 2 and not q.options_are_images:
        others = sorted(len(o) for o in q.options[:-1])
        if len(q.options[-1]) > max(40, 4 * others[len(others) // 2]):
            q.notes.append("Oxirgi variant juda uzun — keyingi savol qo'shilib ketgan bo'lishi mumkin")
    q.uncertain = list(dict.fromkeys(q.uncertain))


def parse_pages(pages: list[list[Row]]) -> ParseResult:
    title_lines: list[str] = []
    questions: list[Question] = []
    current: Question | None = None

    for page_no, rows in enumerate(pages, start=1):
        if current is not None:
            current.segments.append(Segment(page_no, 0))  # savol yangi sahifada davom etishi mumkin
        for row in rows:
            text = normalize(row.text)
            if not text:
                continue

            if current is None and _HEADER.search(text):
                continue
            start = _question_start(text)
            expected = questions[-1].number + 1 if questions else None
            if start and (expected is None or start[0] in (expected, expected + 1)):
                number, rest = start
                if current is not None:
                    _close_segment(current, page_no, row.top)
                current = Question(number=number, segments=[Segment(page_no, row.top, rows=1)])
                if expected is not None and number == expected + 1:
                    current.notes.append(f"{expected}-savol topilmadi — rasmda bormi, tekshiring")
                questions.append(current)
                current.uncertain.extend(normalize(u) for u in row.uncertain)
                current.text = rest
                current.last_line = rest
                continue

            if current is None:
                if sum(ch.isalpha() for ch in text) >= 4:  # suv belgisi qoldig'i ("U") emas
                    title_lines.append(text)
                continue

            current.segments[-1].rows += 1
            current.uncertain.extend(normalize(u) for u in row.uncertain)
            split = split_options(text, len(current.options))
            if split is not None:
                parts, missing = split
                current.notes.extend(f"{letter} variant o'qilmadi" for letter in missing)
                current.options.extend(parts)
                current.option_rows.append((page_no, row))
            elif current.options:
                current.options[-1] = f"{current.options[-1]} {text}".strip()
            else:
                current.text = _append_line(current.text, text, current.last_line)
                current.last_line = text

    for q in questions:
        _finalize(q)
    return ParseResult(title=" ".join(title_lines), questions=questions)
