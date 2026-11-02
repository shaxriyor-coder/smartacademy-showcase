"""Ishtirokchi rasmini kirish ruxsatnomasi uchun tayyorlash.

Rasmni qabulxona qabul qilish paytida yuklaydi (DECISIONS.md #39). Rasm
serverda saqlanmaydi (#8): bazaga faqat Telegram file_id yoziladi, bu
yerda esa baytlar xotirada hujjat rasmi ko'rinishiga (3x4) keltiriladi.
Modul botning boshqa qismlariga bog'liq emas — shuning uchun alohida
test qilinadi (tests/test_participant_photo.py).
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

PHOTO_RATIO = 3 / 4  # eni / bo'yi — hujjat rasmi
# Ruxsatnomada rasm 42x56 mm; PNG 200 DPI da ~330x440 px, PDF chop etishda
# esa kattaroq kerak — shuning uchun zaxira bilan.
PHOTO_SIZE = (600, 800)
MIN_SIDE = 200  # bundan kichik rasm chop etilganda xira chiqadi
# Rasm kerakdan baland bo'lsa ortiqcha qism yuqoridan kamroq, pastdan
# ko'proq kesiladi: telefonda olingan suratda yuz odatda yuqori qismda.
TOP_SHARE = 0.35


class PhotoError(ValueError):
    """Qabulxonaga ko'rsatiladigan xato (o'zbekcha)."""


def prepare_participant_photo(data: bytes) -> bytes:
    """Rasmni 3x4 ga kesib, eni 600 px dan oshmaydigan JPEG qilib qaytaradi."""
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise PhotoError("Rasm o'qilmadi — JPEG yoki PNG rasm yuboring.") from e

    width, height = image.size
    if min(width, height) < MIN_SIDE:
        raise PhotoError(f"Rasm juda kichik ({width}x{height}). Kattaroq rasm yuboring.")

    if width / height > PHOTO_RATIO:
        crop_width = round(height * PHOTO_RATIO)
        left = (width - crop_width) // 2
        box = (left, 0, left + crop_width, height)
    else:
        crop_height = round(width / PHOTO_RATIO)
        top = round((height - crop_height) * TOP_SHARE)
        box = (0, top, width, top + crop_height)
    image = image.crop(box)
    if image.width > PHOTO_SIZE[0]:
        image = image.resize(PHOTO_SIZE, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    return buf.getvalue()
