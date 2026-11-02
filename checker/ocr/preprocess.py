"""Sahifa rasmini tayyorlash: rangli sarlavha va suv belgisini ajratish.

Test sahifalari odatda qora matn, kulrang diagonal suv belgisi (kanal nomi)
va rangli kanal sarlavhasidan iborat. Tesseract suv belgisi ustidagi matnni
yomon o'qiydi, shuning uchun:

1. Rangli piksellar (kanal nomi, sana) oq qilinadi.
2. Suv belgisi — qalin kulrang dog'lar. Ingichka matn chetlari "opening"
   bilan yo'qoladi, qalin dog'lar qoladi. Lekin chizmalardagi kulrang bo'yoq
   (uchburchak ichi) ham qalin dog': uni chetining to'q chiziq bilan
   o'ralganidan ajratamiz (suv belgisi harfining atrofi oq).
3. Suv belgisi ustida faqat juda to'q piksel siyoh hisoblanadi, boshqa
   joyda esa ochroq chegara ishlaydi — shunda "=" va "+" kabi ingichka
   belgilar yo'qolmaydi.

Chegara qiymatlari 905x1280 JPEG namunada (Telegram'dan olingan, suv
belgisi ~170 kulrang) tanlangan; yadro o'lchamlari rasm kengligiga
moslashadi.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 5000  # juda katta rasm xotirani to'ldirmasin
TARGET_WIDTH = 2700  # Tesseract uchun sahifa kengligi (~A4, 330 dpi)
REFERENCE_WIDTH = 905  # yadro o'lchamlari shu kenglikdagi namunada tanlangan

COLOR_CHROMA = 60  # max(R,G,B) - min(R,G,B) shundan katta — rangli
WATERMARK_BAND = (130, 240)  # suv belgisi kulrangi shu oraliqda
WATERMARK_THRESHOLD = 110  # suv belgisi ustida bundan to'q piksel — siyoh
PLAIN_THRESHOLD = 185  # suv belgisi yo'q joyda bundan to'q — siyoh
FILL_EDGE_SHARE = 0.45  # kulrang dog' chetining shunchasi to'q — shakl bo'yog'i
PAPER = 235  # bundan och — qog'oz


class OcrError(Exception):
    """O'qituvchiga ko'rsatiladigan xato (o'zbekcha)."""


@dataclass
class Page:
    gray: np.ndarray  # asl o'lcham, o'zgartirilmagan (rasm kesish uchun)
    watermark: np.ndarray  # bool, asl o'lcham
    binary: np.ndarray  # Tesseract uchun: kattalashtirilgan, 0 — siyoh, 255 — qog'oz
    scale: float  # binary = gray * scale

    @property
    def unit(self) -> float:
        return self.gray.shape[1] / REFERENCE_WIDTH


def _odd(value: float) -> int:
    n = max(3, int(round(value)))
    return n if n % 2 else n + 1


def load_image(data: bytes) -> np.ndarray:
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise OcrError("Rasm o'qilmadi — JPEG yoki PNG fayl yuklang.") from e
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.asarray(image)


def watermark_mask(gray: np.ndarray) -> np.ndarray:
    unit = gray.shape[1] / REFERENCE_WIDTH
    k = _odd(5 * unit)
    lo, hi = WATERMARK_BAND
    mid = ((gray >= lo) & (gray <= hi)).astype(np.uint8)
    opened = cv2.morphologyEx(mid, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)

    dark = gray < WATERMARK_THRESHOLD
    kernel = np.ones((k, k), np.uint8)
    watermark = np.zeros(gray.shape, bool)
    fills = np.zeros(gray.shape, bool)
    min_area = 30 * unit * unit
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        x0, y0 = max(x - k, 0), max(y - k, 0)
        x1, y1 = x + w + k, y + h + k
        comp = labels[y0:y1, x0:x1] == i
        ring = cv2.dilate(comp.astype(np.uint8), kernel).astype(bool) & ~comp
        edge_dark = float(dark[y0:y1, x0:x1][ring].mean()) if ring.any() else 0.0
        (fills if edge_dark > FILL_EDGE_SHARE else watermark)[y0:y1, x0:x1] |= comp

    watermark = cv2.dilate(watermark.astype(np.uint8), kernel).astype(bool)
    return watermark & ~fills


def prepare(data: bytes) -> Page:
    rgb = load_image(data)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    wide = rgb.astype(np.int16)
    colored = (wide.max(axis=-1) - wide.min(axis=-1)) > COLOR_CHROMA
    colored = cv2.dilate(colored.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    text_gray = gray.copy()
    text_gray[colored] = 255

    watermark = watermark_mask(text_gray)

    scale = min(max(TARGET_WIDTH / gray.shape[1], 0.5), 4.0)
    size = (round(gray.shape[1] * scale), round(gray.shape[0] * scale))
    interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
    big = cv2.resize(text_gray, size, interpolation=interpolation)
    big_watermark = cv2.resize(watermark.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
    threshold = np.where(big_watermark, WATERMARK_THRESHOLD, PLAIN_THRESHOLD)
    binary = np.where(big < threshold, 0, 255).astype(np.uint8)

    return Page(gray=gray, watermark=watermark, binary=binary, scale=size[0] / gray.shape[1])


def encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise OcrError("Rasmni saqlab bo'lmadi")
    return buf.tobytes()


def encode_jpeg(image: np.ndarray, quality: int = 75) -> bytes:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise OcrError("Rasmni saqlab bo'lmadi")
    return buf.tobytes()


def _drop_edge_slivers(region: np.ndarray, min_height: int) -> np.ndarray:
    """Tepa/pastki chekkaga tegib turgan yupqa siyoh bo'lagini olib tashlaydi.

    Chizma atrofiga qo'shilgan bo'sh joy qo'shni qator harflarining uchini
    ham ilib oladi; u chizmadan oq oraliq bilan ajralgan bo'ladi.
    """
    ink_rows = (region < PAPER).any(axis=1)
    runs: list[tuple[int, int]] = []
    start = None
    for y, has_ink in enumerate(ink_rows):
        if has_ink and start is None:
            start = y
        elif not has_ink and start is not None:
            runs.append((start, y))
            start = None
    if start is not None:
        runs.append((start, len(ink_rows)))
    if len(runs) < 2:
        return region
    top, bottom = 0, region.shape[0]
    if runs[0][0] == 0 and runs[0][1] - runs[0][0] < min_height:
        top = runs[1][0]
    if runs[-1][1] == region.shape[0] and runs[-1][1] - runs[-1][0] < min_height:
        bottom = runs[-2][1]
    return region[top:bottom]


def clean_crop(page: Page, box: tuple[int, int, int, int], sliver: int = 0) -> tuple[np.ndarray, float]:
    """Chizmani kesib, suv belgisidan tozalaydi.

    `box` — asl o'lchamdagi (x0, y0, x1, y1); `sliver` — chekkadagi shundan
    yupqa siyoh bo'lagi tashlanadi. Qaytaradi: rasm va kesilgan joyning suv
    belgisi bilan qoplangan ulushi (katta bo'lsa tozalash chizma qismini ham
    o'chirgan bo'lishi mumkin — o'qituvchi tekshiradi).
    """
    x0, y0, x1, y1 = box
    region = page.gray[y0:y1, x0:x1].copy()
    watermark = page.watermark[y0:y1, x0:x1]
    region[watermark & (region >= WATERMARK_THRESHOLD)] = 255
    covered = float(watermark.mean()) if watermark.size else 0.0
    if sliver:
        region = _drop_edge_slivers(region, sliver)

    ink = region < PAPER
    if ink.any():
        ys, xs = np.nonzero(ink)
        pad = max(2, round(4 * page.unit))
        top, bottom = max(ys.min() - pad, 0), min(ys.max() + pad + 1, region.shape[0])
        left, right = max(xs.min() - pad, 0), min(xs.max() + pad + 1, region.shape[1])
        region = region[top:bottom, left:right]

    # Qog'ozni to'liq oq qilib, o'rta tonlarni biroz to'qlashtiradi.
    leveled = (np.clip(region.astype(np.float32) / PAPER, 0, 1) ** 1.25 * 255).astype(np.uint8)
    return leveled, covered


def source_strip(page: Page, top: int, bottom: int) -> np.ndarray:
    """Savolning asl rasmdagi bo'lagi — o'qituvchi o'qilgan matn bilan solishtiradi."""
    top = min(max(top, 0), page.gray.shape[0] - 1)
    return page.gray[top : max(bottom, top + 1)]


def stack(images: list[np.ndarray], gap: int = 12, max_width: int | None = None) -> np.ndarray:
    """Rasmlarni ustma-ust, chapga tekislab bitta rasmga yig'adi."""
    if max_width:
        resized = []
        for img in images:
            if img.shape[1] > max_width:
                ratio = max_width / img.shape[1]
                img = cv2.resize(img, (max_width, max(1, round(img.shape[0] * ratio))), interpolation=cv2.INTER_AREA)
            resized.append(img)
        images = resized
    width = max(img.shape[1] for img in images)
    height = sum(img.shape[0] for img in images) + gap * (len(images) - 1)
    sheet = np.full((height, width), 255, np.uint8)
    y = 0
    for img in images:
        sheet[y : y + img.shape[0], : img.shape[1]] = img
        y += img.shape[0] + gap
    return sheet
