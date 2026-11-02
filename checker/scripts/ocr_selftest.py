"""Rasmdan savol o'qishni boshidan oxirigacha sinaydi (HTTP orqali, port ochmasdan).

Sun'iy test sahifasi chiziladi — rangli kanal sarlavhasi, diagonal kulrang suv
belgisi, 3 ta savol (bittasida kulrang bo'yalgan chizma), JPEG — keyin
POST /ocr natijasi kutilgani bilan solishtiriladi.

    cd checker && python scripts/ocr_selftest.py

Muvaffaqiyatda 0 bilan, birorta farqda 1 bilan chiqadi. Tesseract (uzb, eng)
va serif shrift kerak (Windows: Times New Roman; Linux: fonts-dejavu yoki
fonts-noto).
"""

from __future__ import annotations

import asyncio
import difflib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import FormData  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

from config import CHECKER_TOKEN  # noqa: E402
from server import create_app  # noqa: E402

FONTS = [
    r"C:\Windows\Fonts\times.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
]

# (savol matni, variantlar, chizma bormi)
EXPECTED = [
    (
        "Otabekda 200 000 so‘m pul bor. U 3 ta qalamdon sotib oldi. Unda qancha pul qoldi?",
        ["50 000 so‘m", "15 000 so‘m", "25 000 so‘m", "100 000 so‘m"],
        False,
    ),
    ("Berilgan shaklning qanday qismi bo‘yalgan?", ["3", "4", "5", "6"], True),
    ("Sinfda nechta o‘quvchi qatnashmoqda?", ["22", "26", "28", "30", "32"], False),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("Serif shrift topilmadi: " + ", ".join(FONTS))


def make_page() -> bytes:
    width, height = 1240, 1754  # A4, 150 dpi
    page = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(page)
    text_font, title_font = _font(30), _font(34)

    color = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(color).text((90, 60), "Test kanali  @testkanal (15.09.2026)", font=title_font, fill=(200, 30, 30))

    draw.text((150, 130), "Matematika repetitsion test", font=title_font, fill=0)
    y = 210
    for number, (text, options, figure) in enumerate(EXPECTED, start=1):
        draw.text((90, y), f"{number}. {text}", font=text_font, fill=0)
        y += 50
        if figure:
            # kulrang bo'yalgan uchburchak — suv belgisi bilan adashmasligi kerak
            draw.polygon([(800, y + 190), (1000, y + 190), (900, y)], fill=150, outline=0, width=4)
            draw.line([(850, y + 95), (950, y + 95)], fill=0, width=4)
        for i, option in enumerate(options):
            draw.text((90 + i * 220, y + (220 if figure else 0)), f"{'ABCDE'[i]}) {option}", font=text_font, fill=0)
        y += 290 if figure else 70

    watermark = Image.new("L", (width, height), 255)
    layer = Image.new("L", (1400, 400), 255)
    ImageDraw.Draw(layer).text((20, 40), "@testkanal", font=_font(260), fill=170)
    layer = layer.rotate(35, expand=True, fillcolor=255)
    watermark.paste(layer, (-60, 350))
    page = ImageChops.darker(page, watermark)

    rgb = Image.merge("RGB", (page, page, page))
    rgb = ImageChops.darker(rgb, color)
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _same(expected: str, actual: str) -> bool:
    return difflib.SequenceMatcher(None, expected.replace(" ", ""), actual.replace(" ", "")).ratio() >= 0.9


async def main() -> int:
    image = make_page()
    async with TestClient(TestServer(create_app())) as client:
        form = FormData()
        form.add_field("file", image, filename="sahifa.jpg", content_type="image/jpeg")
        res = await client.post("/ocr", data=form, headers={"X-Checker-Token": CHECKER_TOKEN})
        body = await res.json()
    if res.status != 200:
        print(f"XATO: /ocr {res.status}: {body}")
        return 1

    problems = []
    questions = body["questions"]
    if len(questions) != len(EXPECTED):
        problems.append(f"{len(EXPECTED)} ta savol kutilgan, {len(questions)} ta topildi")
    for q, (text, options, figure) in zip(questions, EXPECTED):
        n = q["number"]
        if not _same(text, q["text"]):
            problems.append(f"{n}-savol matni: {q['text']!r}")
        if len(q["options"]) != len(options) or not all(_same(a, b) for a, b in zip(options, q["options"])):
            problems.append(f"{n}-savol variantlari: {q['options']}")
        if bool(q["image"]) != figure:
            problems.append(f"{n}-savol chizmasi: {'yo‘q' if figure else 'ortiqcha'}")
    if "Matematika repetitsion test" not in body["title"]:
        problems.append(f"sarlavha: {body['title']!r}")

    sys.stdout.reconfigure(encoding="utf-8")
    for q in questions:
        print(f"{q['number']}. {q['text']} | {' / '.join(q['options'])} | rasm: {'bor' if q['image'] else 'yo‘q'}")
    if problems:
        print("\nFARQLAR:\n  " + "\n  ".join(problems))
        return 1
    print("\nOK: savollar, variantlar va chizma to'g'ri o'qildi")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
