"""Tesseract'ni chaqirish (CLI, TSV chiqishi).

pytesseract o'rniga to'g'ridan-to'g'ri subprocess: sozlamalar (til papkasi,
sub-tillar) ustidan to'liq nazorat va qo'shimcha kutubxona kerak emas.
"""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass

from ocr.preprocess import OcrError

TIMEOUT_SECONDS = 120
DPI = 330  # preprocess.TARGET_WIDTH A4 kengligida


@dataclass(frozen=True)
class TesseractSettings:
    cmd: str = "tesseract"
    tessdata_dir: str = ""  # bo'sh — Tesseract o'z papkasini ishlatadi
    lang: str = "uzb"
    psm: int = 4  # bir ustun, har xil o'lchamdagi qatorlar


@dataclass(frozen=True)
class Word:
    text: str
    conf: float  # 0-100
    left: int
    top: int
    width: int
    height: int
    block: int
    par: int
    line: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def parse_tsv(text: str) -> list[Word]:
    words: list[Word] = []
    reader = csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        # level, page, block, par, line, word, left, top, width, height, conf, text
        if len(row) < 12 or row[0] != "5":
            continue
        token = row[11].strip()
        if not token:
            continue
        try:
            words.append(
                Word(
                    text=token,
                    conf=float(row[10]),
                    left=int(row[6]),
                    top=int(row[7]),
                    width=int(row[8]),
                    height=int(row[9]),
                    block=int(row[2]),
                    par=int(row[3]),
                    line=int(row[4]),
                )
            )
        except ValueError:
            continue
    return words


def recognize(png: bytes, settings: TesseractSettings) -> list[Word]:
    cmd = [
        settings.cmd, "stdin", "stdout",
        "-l", settings.lang,
        "--psm", str(settings.psm),
        "--dpi", str(DPI),
        "-c", "tessedit_create_tsv=1",
    ]  # fmt: skip
    if settings.tessdata_dir:
        cmd += ["--tessdata-dir", settings.tessdata_dir]
    try:
        proc = subprocess.run(cmd, input=png, capture_output=True, timeout=TIMEOUT_SECONDS)
    except FileNotFoundError as e:
        raise OcrError(
            "Tesseract topilmadi — checker/README.md dagi \"Rasmdan savol o'qish\" bo'limini bajaring."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise OcrError("Sahifani o'qish juda uzoq davom etdi — rasmni kichikroq qilib yuklang.") from e

    stderr = proc.stderr.decode("utf-8", "replace")
    # tessdata_best'dagi uzb modeli uzb_cyrl'ni ham yuklashga urinadi va topmasa
    # ogohlantiradi — bu zararsiz; faqat so'ralgan til yuklanmasa xato.
    for lang in settings.lang.split("+"):
        if f"Failed loading language '{lang}'" in stderr:
            raise OcrError(f"Tesseract uchun '{lang}' til fayli topilmadi ({lang}.traineddata).")
    if proc.returncode != 0:
        raise OcrError(f"Tesseract xatosi: {stderr.strip()[-300:]}")
    return parse_tsv(proc.stdout.decode("utf-8", "replace"))
