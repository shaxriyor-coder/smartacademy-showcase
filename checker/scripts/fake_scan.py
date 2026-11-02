"""Sinov uchun "to'ldirilgan skan" yasaydi.

Shtamplangan javob varaqlari PDF'ini oladi, har sahifani 200 DPI rasmga
aylantiradi, berilgan javoblar bo'yicha doiralarni ruchka bilan bo'yagandek
qoraytiradi, biroz buradi va shovqin qo'shadi, keyin skaner chiqargandek
rasm-PDF qilib saqlaydi. Haqiqiy qog'ozsiz butun oqimni (chop etish ->
skan -> tekshirish) sinab ko'rish uchun.

    python scripts/fake_scan.py sheets.pdf bubble_boxes.json answers.json out.pdf

answers.json — sahifalar ro'yxati; har sahifada fan nomi -> savollar
ro'yxati, har savolda bo'yaladigan harflar: [] bo'sh, ["B"] bitta,
["A", "C"] ko'p belgilangan. Masalan:
    [{"Matematika": [["A"], [], ["B", "D"]]}]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

DPI = 200
PT_TO_PX = DPI / 72.0


def fill_page(image: np.ndarray, boxes: dict, marks: dict[str, list[list[str]]],
              angle_deg: float, seed: int) -> np.ndarray:
    img = image.copy()
    radius = max(3, int(boxes["radius"] * PT_TO_PX * 0.8))
    for subject in boxes["subjects"]:
        per_question = marks.get(subject["name"], [])
        letters = subject["letters"]
        for qn_txt, centers in subject["questions"].items():
            qi = int(qn_txt) - 1
            chosen = per_question[qi] if qi < len(per_question) else []
            for letter in chosen:
                cx, cy = centers[letters.index(letter)]
                cv2.circle(img, (int(cx * PT_TO_PX), int(cy * PT_TO_PX)), radius,
                           (35, 35, 60), -1, cv2.LINE_AA)

    h, w = img.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    img = cv2.warpAffine(img, matrix, (w, h), borderValue=(255, 255, 255))
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 6, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise - 12, 0, 255).astype(np.uint8)


def make_scan(sheets_pdf: bytes, bubble_boxes_json: str,
              answers: list[dict[str, list[list[str]]]]) -> bytes:
    import fitz

    boxes = json.loads(bubble_boxes_json)
    src = fitz.open(stream=sheets_pdf, filetype="pdf")
    out = fitz.open()
    try:
        if src.page_count != len(answers):
            raise ValueError(f"PDF'da {src.page_count} sahifa, javoblar {len(answers)} ta")
        for index, page in enumerate(src):
            pix = page.get_pixmap(dpi=DPI)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            angle = (-1.5, 0.8, 2.0)[index % 3]
            filled = fill_page(bgr, boxes, answers[index], angle, seed=index)
            ok, jpg = cv2.imencode(".jpg", filled, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                raise RuntimeError("JPEG kodlanmadi")
            rect = page.rect
            new_page = out.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(rect, stream=jpg.tobytes())
        return out.tobytes(garbage=3, deflate=True)
    finally:
        out.close()
        src.close()


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(2)
    sheets, boxes_path, answers_path, out_path = sys.argv[1:]
    scan = make_scan(
        Path(sheets).read_bytes(),
        Path(boxes_path).read_text(encoding="utf-8"),
        json.loads(Path(answers_path).read_text(encoding="utf-8")),
    )
    Path(out_path).write_bytes(scan)
    print(f"Yozildi: {out_path} ({len(scan) // 1024} KB)")
