"""Tesseract so'zlaridan sahifa tuzilishi: chizmalar va qatorlar.

Chizma — siyohning katta bo'laklari (shakllar, rasm, katta raqamlar,
katakchalar) va ularga tegib turgan uzun ingichka chiziqlar. Namunada
(binary kengligi 2700) oddiy matn belgisi so'z balandligi medianasining 1.3
baravaridan oshmadi, chizma bo'laklari esa 1.7 va undan katta edi.

Chizma ustida Tesseract ma'nosiz "so'zlar" chiqaradi ("QIN", "UI") — ular
tashlanadi. Faqat variant harfi ("A)") qoladi: rasmli variantlarni aniqlash
uchun kerak.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from ocr.parse import Row
from ocr.tesseract import Word

LOW_CONFIDENCE = 60  # bundan past so'z o'qituvchiga "noaniq" deb ko'rsatiladi
NOISE_CONFIDENCE = 30  # bundan past va harf/raqamsiz — shovqin
TEXT_CONFIDENCE = 85  # shu ishonchli, 3+ harfli so'z ichidagi bo'lak — matn (katta sarlavha)
FIGURE_HEIGHT = 1.5  # siyoh bo'lagi so'z balandligidan shuncha katta — chizma
FIGURE_MIN_WIDTH = 0.5
RULE_WIDTH = 3.0  # uzun ingichka chiziq (ayirish chizig'i, jadval)
RULE_HEIGHT = 0.35
MERGE_GAP = 1.5  # chizma bo'laklari orasidagi ruxsat etilgan masofa
ROW_OVERLAP = 0.5  # so'z qatorga shuncha balandligi bilan tushsa — o'sha qator

Box = tuple[int, int, int, int]  # x0, y0, x1, y1

_MARKER_WORD = re.compile(r"^[A-Ea-e][).][;:?]?$")


def _has_alnum(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def text_height(words: list[Word]) -> float:
    heights = [w.height for w in words if w.conf >= LOW_CONFIDENCE and sum(ch.isalpha() for ch in w.text) >= 3]
    return float(np.median(heights)) if heights else 0.0


def _near(a: Box, b: Box, gap: float) -> bool:
    return a[0] - gap < b[2] and b[0] - gap < a[2] and a[1] - gap < b[3] and b[1] - gap < a[3]


def _union(a: Box, b: Box) -> Box:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def center_inside(box: Box, outer: Box) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def merge_boxes(boxes: list[Box], gap: float) -> list[Box]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        out: list[Box] = []
        for box in merged:
            for i, other in enumerate(out):
                if _near(box, other, gap):
                    out[i] = _union(box, other)
                    changed = True
                    break
            else:
                out.append(box)
        merged = out
    return merged


def find_figures(binary: np.ndarray, words: list[Word], height: float) -> list[Box]:
    if height <= 0:
        return []
    ink = (binary == 0).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    page_h, page_w = binary.shape
    text_boxes = [
        (w.left, w.top, w.right, w.bottom)
        for w in words
        if w.conf >= TEXT_CONFIDENCE and sum(ch.isalpha() for ch in w.text) >= 3
    ]

    parts: list[Box] = []
    rules: list[Box] = []
    for x, y, w, h, _area in stats[1:]:
        box = (int(x), int(y), int(x + w), int(y + h))
        if w > 0.9 * page_w and h > 0.5 * page_h:
            continue  # sahifa ramkasi
        if h >= FIGURE_HEIGHT * height and w >= FIGURE_MIN_WIDTH * height:
            if not any(center_inside(box, tb) for tb in text_boxes):
                parts.append(box)
        elif w >= RULE_WIDTH * height and h <= RULE_HEIGHT * height:
            rules.append(box)

    regions = merge_boxes(parts, MERGE_GAP * height)
    for rule in rules:
        for i, region in enumerate(regions):
            if _near(rule, region, MERGE_GAP * height):
                regions[i] = _union(region, rule)
                break
    regions = merge_boxes(regions, MERGE_GAP * height)
    return [r for r in regions if (r[2] - r[0]) * (r[3] - r[1]) >= 2 * height * height]


def is_marker(text: str) -> bool:
    return bool(_MARKER_WORD.match(text))


def label_image(binary: np.ndarray, region: Box, height: float) -> np.ndarray:
    """Chizma ichidagi kichik belgilar (variant harflari "A)") — katta bo'laklarsiz.

    Butun sahifada Tesseract shakl yonidagi "A)" ni shakl bilan qo'shib o'qiydi
    ("xr", "QIN"); shakllar olib tashlangan rasmda harflar alohida o'qiladi.
    """
    x0, y0, x1, y1 = region
    crop = binary[y0:y1, x0:x1].copy()
    count, labels, stats, _ = cv2.connectedComponentsWithStats((crop == 0).astype(np.uint8), connectivity=8)
    big = [
        i
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_HEIGHT] >= FIGURE_HEIGHT * height or stats[i, cv2.CC_STAT_WIDTH] >= RULE_WIDTH * height
    ]
    if big:
        crop[np.isin(labels, big)] = 255
    return crop


def build_rows(words: list[Word], figures: list[Box]) -> list[Row]:
    kept: list[Word] = []
    for w in words:
        box = (w.left, w.top, w.right, w.bottom)
        if any(center_inside(box, f) for f in figures):
            if not (is_marker(w.text) and w.conf >= 40):
                continue
        if w.conf < NOISE_CONFIDENCE and not _has_alnum(w.text):
            continue
        kept.append(w)

    kept.sort(key=lambda w: (w.top, w.left))
    groups: list[list[Word]] = []
    spans: list[list[int]] = []  # har guruhning [top, bottom]
    for w in kept:
        for group, span in zip(groups, spans):
            overlap = min(span[1], w.bottom) - max(span[0], w.top)
            if overlap >= ROW_OVERLAP * min(w.height, span[1] - span[0]):
                group.append(w)
                span[0], span[1] = min(span[0], w.top), max(span[1], w.bottom)
                break
        else:
            groups.append([w])
            spans.append([w.top, w.bottom])

    rows: list[Row] = []
    for group in groups:
        group.sort(key=lambda w: w.left)
        text = " ".join(w.text for w in group)
        if not _has_alnum(text):
            continue
        rows.append(
            Row(
                text=text,
                top=min(w.top for w in group),
                bottom=max(w.bottom for w in group),
                left=min(w.left for w in group),
                right=max(w.right for w in group),
                uncertain=[w.text for w in group if w.conf < LOW_CONFIDENCE and _has_alnum(w.text)],
            )
        )
    rows.sort(key=lambda r: r.top)
    return rows
