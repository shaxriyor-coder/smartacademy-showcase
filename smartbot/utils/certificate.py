"""Foydalanuvchi uchun shaxsiylashtirilgan sertifikat (JPG) yaratish.

Smart Academy sertifikat shabloni (assets/certificate_template.png) ustiga
PIL yordamida quyidagilar yoziladi:
  - Ishtirokchining Ism Familiyasi ("Sertifikat" yozuvi ostidagi chiziq ustiga)
  - Olimpiada nomi (katta ko'k to'rtburchak ichiga)
  - Umumiy ball, Ishtirokchi o'rni va berilgan sana (pastdagi ko'k tugmachalar ichiga)

Barcha koordinatalar shablon rasmning original 3510px kengligiga nisbatan
o'lchangan (REF_WIDTH) va shablon boshqa o'lchamda saqlansa ham to'g'ri
joylashishi uchun nisbat (scale) orqali qayta hisoblanadi.
"""

import os
from PIL import Image, ImageDraw, ImageFont

# Barcha kerakli fayllar (shablon rasm va shriftlar) shu modul bilan birga
# utils/assets/ papkasida saqlanadi — deploy.sh faqat "utils" papkasini
# serverga yuboradi, shuning uchun tashqi (loyihaning ildizidagi) papkalarga
# tayanmaymiz. Xuddi shu sababdan tizimga o'rnatilgan shriftlarga emas,
# loyiha ichiga joylashtirilgan shrift fayllariga tayanamiz — bu serverda
# DejaVu shriftlari o'rnatilmagan taqdirda ham ishlashini kafolatlaydi.
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
TEMPLATE_PATH = os.path.join(ASSETS_DIR, "certificate_template.png")

FONT_DIR = os.path.join(ASSETS_DIR, "fonts")
FONT_BOLD_PATH = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FONT_REGULAR_PATH = os.path.join(FONT_DIR, "DejaVuSans.ttf")

NAVY = (0, 27, 100)
WHITE = (255, 255, 255)

# Shablon rasmning o'lchash paytidagi kengligi (piksel). Barcha REGION
# koordinatalari shu kenglikka nisbatan berilgan.
REF_WIDTH = 3510

REGIONS = {
    # Ism-familiya: "Sertifikat" sarlavhasi ostidagi bo'sh chiziq ustida
    "name": {"x_center": 1755, "y_center": 838, "max_width": 1650, "max_font": 100},
    # Olimpiada nomi: katta ko'k to'rtburchak ichida
    "olympiad": {"x_center": 1754, "y_center": 1149, "max_width": 2200, "max_font": 90},
    # "Umumiy bal:" tugmachasi ichidagi bo'sh joy
    "score": {"x_center": 1104, "y_center": 1752, "max_width": 300, "max_font": 62},
    # "Ishtirokchi o'rin:" tugmachasi ichidagi bo'sh joy
    "place": {"x_center": 2796, "y_center": 1751, "max_width": 210, "max_font": 62},
    # "Berilgan sana:" tugmachasi ichidagi bo'sh joy
    "date": {"x_center": 1120, "y_center": 1993, "max_width": 275, "max_font": 56},
}


def _fit_font(draw, text, font_path, max_width, max_font, min_font=16, step=2):
    """Matn max_width ichiga sig'adigan eng katta shrift o'lchamini topadi."""
    size = max_font
    while size > min_font:
        font = ImageFont.truetype(font_path, size)
        w = draw.textlength(text, font=font)
        if w <= max_width:
            return font
        size -= step
    return ImageFont.truetype(font_path, min_font)


def generate_certificate(
    full_name: str,
    olympiad_name: str,
    score_text: str,
    place_text: str,
    date_text: str,
    output_path: str,
) -> str:
    """Sertifikat rasmini yaratadi va output_path ga JPG qilib saqlaydi."""

    img = Image.open(TEMPLATE_PATH).convert("RGB")
    scale = img.width / REF_WIDTH
    draw = ImageDraw.Draw(img)

    fields = [
        ("name", full_name, FONT_BOLD_PATH, NAVY),
        ("olympiad", olympiad_name, FONT_BOLD_PATH, WHITE),
        ("score", score_text, FONT_BOLD_PATH, WHITE),
        ("place", place_text, FONT_BOLD_PATH, WHITE),
        ("date", date_text, FONT_BOLD_PATH, WHITE),
    ]

    for key, text, font_path, color in fields:
        region = REGIONS[key]
        x_center = region["x_center"] * scale
        y_center = region["y_center"] * scale
        max_width = region["max_width"] * scale
        max_font = max(int(region["max_font"] * scale), 10)

        font = _fit_font(draw, text, font_path, max_width, max_font)
        draw.text((x_center, y_center), text, font=font, fill=color, anchor="mm")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "JPEG", quality=92)
    return output_path
