# Manba: smartbot/utils/qr_payload.py (commit 38373cf, 2026-09-13) — o'zgarishsiz nusxa,
# faqat import yo'llari checker/ tuzilishiga moslangan. Geometriya va OMR
# qarorlari smartbot/docs/DECISIONS.md #27-#37 da tushuntirilgan.
"""Ruxsatnoma ID (ticket_no) yasash va QR payloadni tekshirish.

Bu modul faqat standart kutubxonaga tayanadi va boshqa loyiha
qismlaridan (bot handlerlari, baza) mustaqil — chunki uni alohida OMR
dasturi (javob varaqalarini skanerlaydigan Python+OpenCV dastur) ham
import qiladi. Shu modulni o'zgartirsangiz, OMR tomoni bilan ham
kelishib oling.

Ikkita mustaqil tekshiruv bor:
  * HMAC imzo    — soxta (ataylab o'ylab topilgan) ruxsatnomaning oldini
                    oladi. QR ichida bor, oddiy ko'z bilan ko'rinmaydi.
  * Nazorat raqami (Luhn) — operator ID'ni qo'lda kiritganda qilingan
                    bitta xato raqam yoki qo'shni ikkita raqam
                    almashib ketishini ushlaydi. QR o'qilmasa ham
                    ishlaydi, chunki u ticket_no ning o'zida.

ticket_no ko'rinishi:  SA-{yil}-{olimpiada kodi}-{tartib raqam}{nazorat}
    Masalan:           SA-2026-MATH-0004187
"""

from __future__ import annotations

import hashlib
import hmac
import re

TICKET_PREFIX = "SA"

# SA-2026-MATH-0004187 -> ("2026", "MATH", "000418", "7")
# Tartib qismi kamida 6 xonali, lekin ID 999999 dan oshsa ham (kelajakda)
# ishlashi uchun pastdan chegaralanmagan.
_TICKET_RE = re.compile(r"^SA-(\d{4})-([A-Z0-9]{2,10})-(\d{6,})(\d)$")


def _luhn_check_digit(digits: str) -> str:
    """`digits` (faqat raqamlar) uchun Luhn nazorat raqamini hisoblaydi.

    Luhn — bank kartalarida ishlatiladigan standart algoritm: bitta
    noto'g'ri terilgan raqamni yoki qo'shni ikkita raqamning joyi
    almashib ketishini deyarli har doim ushlaydi.
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)


def _luhn_is_valid(digits_with_check: str) -> bool:
    if not digits_with_check.isdigit():
        return False
    body, check = digits_with_check[:-1], digits_with_check[-1]
    return _luhn_check_digit(body) == check


def _sanitize_code(olympiad_code: str) -> str:
    code = re.sub(r"[^A-Z0-9]", "", (olympiad_code or "").upper())[:10]
    return code or "GEN"


def build_ticket_no(year: int, olympiad_code: str, seq: int) -> str:
    """Yangi ticket_no yasaydi.

    `seq` — OlympiadResult.id (bazada avtomatik beriladi, hech qachon
    takrorlanmaydi) — shuning uchun to'qnashuv yoki alohida hisoblagich
    kerak emas.
    """
    code = _sanitize_code(olympiad_code)
    seq_txt = f"{seq:06d}"
    check = _luhn_check_digit(f"{year:04d}{seq_txt}")
    return f"{TICKET_PREFIX}-{year:04d}-{code}-{seq_txt}{check}"


def is_valid_ticket_no(ticket_no: str) -> bool:
    """Faqat formatni va nazorat raqamini tekshiradi (HMAC imzosiz).

    Operator QR o'qimay qolganda ID'ni qo'lda kiritganda ishlatiladi —
    imzo qog'ozda matn ko'rinishida yo'q, faqat QR ichida.
    """
    m = _TICKET_RE.match((ticket_no or "").strip().upper())
    if not m:
        return False
    year, _code, seq, check = m.groups()
    return _luhn_is_valid(f"{year}{seq}{check}")


def sign_ticket_no(ticket_no: str, secret: str) -> str:
    """ticket_no'dan HMAC-SHA256 imzo (birinchi 6 ta hex belgi) chiqaradi."""
    if not secret:
        raise ValueError("QR_SECRET bo'sh bo'lishi mumkin emas")
    digest = hmac.new(
        secret.encode("utf-8"), ticket_no.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return digest[:6]


def build_qr_payload(ticket_no: str, secret: str) -> str:
    """QR ichiga yoziladigan matn: '{ticket_no}|{imzo}'."""
    return f"{ticket_no}|{sign_ticket_no(ticket_no, secret)}"


def verify_qr_payload(payload: str, secret: str) -> bool:
    """QR'dan o'qilgan payloadni tekshiradi: format, nazorat raqami, imzo.

    Uchalasi ham to'g'ri bo'lsagina True qaytaradi.
    """
    if not payload or "|" not in payload:
        return False
    ticket_no, _, signature = payload.partition("|")
    if not is_valid_ticket_no(ticket_no):
        return False
    try:
        expected = sign_ticket_no(ticket_no.strip().upper(), secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, signature.strip().lower())
