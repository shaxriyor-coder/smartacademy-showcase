"""Ism-familiya bo'yicha o'quvchini topish.

Excel'da Telegram Chat ID ham, telefon ham bo'lmasligi mumkin — yagona
bog'lovchi ma'lumot ism bo'ladi. O'zbek tilida esa bir xil ism turlicha
yozilishi mumkin:

    O'quvchi   O‘quvchi   O`quvchi   Oquvchi
    G'ulom     G‘ulom     Gulom

Shuning uchun oddiy `WHERE full_name = ...` yetarli emas.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

# Apostrof sifatida ishlatiladigan barcha belgilar bitta ko'rinishga keltiriladi.
# U+2018/2019 — chap/o'ng qo'shtirnoq, U+02BB — o'zbek tutuq belgisi,
# U+0060 — grave accent (klaviaturada tez-tez ishlatiladi).
_APOSTROPHES = "‘’ʻʼ′`´'"

# Kirill va lotin o'rtasida chalkashadigan bir xil ko'rinishdagi harflar
_LOOKALIKE = str.maketrans(
    {
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
        "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
        "а": "a", "е": "e", "к": "k", "м": "m", "о": "o", "р": "p",
        "с": "c", "т": "t", "у": "y", "х": "x",
    }
)

# Fuzzy moslikda shu chegaradan pastini umuman taklif qilmaymiz
FUZZY_THRESHOLD = 0.86


def normalize_name(raw: str | None) -> str:
    """Ismni solishtirishga yaroqli ko'rinishga keltiradi.

    - Unicode normalizatsiya (NFKC)
    - apostrof variantlarini olib tashlash
    - kirill/lotin ko'rinishdosh harflarini birlashtirish
    - kichik harf
    - ketma-ket bo'shliqlarni bittaga tushirish
    - harf va raqamdan boshqa belgilarni bo'shliqqa aylantirish

    >>> normalize_name("  MUHAMMAD   RIZO  ")
    'muhammad rizo'
    >>> normalize_name("G'ulom O‘rinov") == normalize_name("G‘ulom O'rinov")
    True
    """
    if not raw:
        return ""

    s = unicodedata.normalize("NFKC", str(raw))
    s = s.translate(_LOOKALIKE)

    for ch in _APOSTROPHES:
        s = s.replace(ch, "")

    s = s.lower()
    # Harf/raqamdan boshqa hamma narsa ajratuvchi hisoblanadi
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def split_name_parts(raw: str | None) -> tuple[str, str]:
    """Ism va familiyani ajratadi.

    O'zbekcha familiyalar deyarli har doim "-v" yoki "-va" bilan tugaydi
    (Aliyev, Karimova, Yusupov, Shukurillayev, ...). Matnda shu so'z
    familiya deb olinadi — "Ism Familiya" yoki "Familiya Ism" tartibida
    yozilganidan qat'i nazar. Hech qaysi so'z bunga mos kelmasa (familiya
    tan olinmasa), oxirgi so'z familiya deb olinadi.

    >>> split_name_parts("Saidbilol Shukurillayev")
    ('saidbilol', 'shukurillayev')
    >>> split_name_parts("Shukurillayev Saidbilol")
    ('saidbilol', 'shukurillayev')
    """
    words = normalize_name(raw).split()
    if not words:
        return "", ""
    if len(words) == 1:
        return words[0], ""
    fam_idx = next(
        (i for i, w in enumerate(words) if w.endswith("va") or w.endswith("v")),
        len(words) - 1,
    )
    familiya = words[fam_idx]
    ism = " ".join(w for i, w in enumerate(words) if i != fam_idx)
    return ism, familiya


def _part_ratio(a: str, b: str) -> float:
    """Ism yoki familiyaning bittasi bo'yicha o'xshashlik (0..1)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def name_key(raw: str | None) -> str:
    """So'zlar tartibiga bog'liq bo'lmagan kalit.

    "Valiyev Ali" va "Ali Valiyev" bir xil kalit beradi — o'zbek
    hujjatlarida ism-familiya tartibi turlicha yoziladi.
    """
    return " ".join(sorted(normalize_name(raw).split()))


def similarity(a: str, b: str) -> float:
    """Ikki ism o'rtasidagi o'xshashlik (0..1)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # So'zlar tartibi farq qilsa ham yuqori baho berilsin
    ka, kb = name_key(a), name_key(b)
    return max(
        SequenceMatcher(None, na, nb).ratio(),
        SequenceMatcher(None, ka, kb).ratio(),
    )


@dataclass(frozen=True)
class Candidate:
    """Moslikka nomzod — ro'yxatdan o'tgan bitta ishtirokchi."""

    result_id: int
    user_id: int
    full_name: str
    school: str | None
    grade: int | None
    phone: str | None
    has_score: bool
    ratio: float = 1.0

    def masked_phone(self) -> str:
        """Telefonning faqat oxirgi 4 raqami ko'rsatiladi."""
        if not self.phone:
            return "—"
        digits = re.sub(r"\D", "", self.phone)
        return f"+{digits[:5]}*****{digits[-4:]}" if len(digits) >= 9 else "—"


class NameIndex:
    """Bir olimpiadaning ishtirokchilari bo'yicha xotiradagi indeks.

    Excel'da minglab qator bo'lishi mumkin. Har qator uchun bazaga
    so'rov yuborish o'rniga, ro'yxat bir marta o'qib olinadi va
    moslashtirish xotirada bajariladi.
    """

    def __init__(self, candidates: list[Candidate]) -> None:
        self._all = candidates
        self._by_name: dict[str, list[Candidate]] = {}
        self._by_key: dict[str, list[Candidate]] = {}
        for c in candidates:
            self._by_name.setdefault(normalize_name(c.full_name), []).append(c)
            self._by_key.setdefault(name_key(c.full_name), []).append(c)

    def __len__(self) -> int:
        return len(self._all)

    def find(self, raw_name: str, grade: int | None = None) -> list[Candidate]:
        """Nomzodlarni ustuvorlik tartibida qaytaradi.

        1-daraja: normalizatsiya qilingan aynan moslik
        2-daraja: so'zlar tartibidan qat'i nazar moslik
        3-daraja: fuzzy (faqat chegaradan yuqori bo'lsa)

        `grade` berilsa, avval o'sha sinfdagilar tekshiriladi — bir xil
        ismli 4-sinf va 5-sinf o'quvchisi chalkashib ketmasligi uchun.
        """
        norm = normalize_name(raw_name)
        if not norm:
            return []

        def by_grade(items: list[Candidate]) -> list[Candidate]:
            if grade is None:
                return list(items)
            same = [c for c in items if c.grade == grade]
            # Sinf mos kelganlar bo'lsa faqat ularni qaytaramiz
            return same if same else list(items)

        exact = self._by_name.get(norm)
        if exact:
            return by_grade(exact)

        reordered = self._by_key.get(name_key(raw_name))
        if reordered:
            return by_grade(reordered)

        # Fuzzy — qimmatroq, shuning uchun faqat aniq moslik topilmaganda
        # ishlatiladi. Butun qatorni bitta satr sifatida solishtirish xato:
        # bir xil FAMILIYALI (yoki bir xil ISMLI) ikki xil odam noto'g'ri
        # "bir xil shaxs" deb topilib, adminga soxta "bir nechta nomzod"
        # tanlovi ko'rsatilardi. Shuning uchun ism va familiya AJRATIB
        # solishtiriladi — ikkalasi ham mos kelgandagina fuzzy moslik
        # hisoblanadi.
        row_ism, row_fam = split_name_parts(raw_name)
        scored = []
        for c in self._all:
            if grade is not None and c.grade is not None and c.grade != grade:
                continue
            c_ism, c_fam = split_name_parts(c.full_name)
            ism_r = _part_ratio(row_ism, c_ism)
            fam_r = _part_ratio(row_fam, c_fam)
            if ism_r >= FUZZY_THRESHOLD and fam_r >= FUZZY_THRESHOLD:
                scored.append(
                    Candidate(
                        result_id=c.result_id,
                        user_id=c.user_id,
                        full_name=c.full_name,
                        school=c.school,
                        grade=c.grade,
                        phone=c.phone,
                        has_score=c.has_score,
                        ratio=(ism_r + fam_r) / 2,
                    )
                )
        scored.sort(key=lambda c: c.ratio, reverse=True)
        return scored

    def search(self, query: str, limit: int = 20) -> list[Candidate]:
        """Admin qo'lda qidirganda ishlatiladi — qismiy moslik ham bo'ladi."""
        q = normalize_name(query)
        if not q:
            return []
        hits = []
        for c in self._all:
            n = normalize_name(c.full_name)
            if q in n or n in q:
                hits.append(c)
            else:
                r = similarity(query, c.full_name)
                if r >= 0.7:
                    hits.append(
                        Candidate(
                            result_id=c.result_id,
                            user_id=c.user_id,
                            full_name=c.full_name,
                            school=c.school,
                            grade=c.grade,
                            phone=c.phone,
                            has_score=c.has_score,
                            ratio=r,
                        )
                    )
        hits.sort(key=lambda c: c.ratio, reverse=True)
        return hits[:limit]
