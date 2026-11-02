"""Checker servisining sozlamalari (`checker/.env` dan o'qiladi).

`omr/` ichidagi smartbot'dan ko'chirilgan modullar `from config import
QR_SECRET, ANSWER_SHEET_ASSETS_DIR` qiladi — shuning uchun bu fayl nomi va
o'sha ikki o'zgaruvchi nomi o'zgarmasligi kerak. Servis `checker/`
papkasining ichidan ishga tushiriladi (qarang: README.md).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# QR kodni imzolash kaliti (HMAC-SHA256). Ishlab turgan smartbot'nikidan
# ATAYLAB boshqa: platforma varag'ini bot tekshirib qo'ya olmasin va aksincha.
# Bo'sh bo'lsa imzosiz QR chiqib ketardi — shuning uchun servis ishga
# tushmaydi (smartbot config.py dagi bilan bir xil qoida).
QR_SECRET = os.getenv("QR_SECRET", "")
if not QR_SECRET:
    raise RuntimeError("QR_SECRET o'rnatilmagan (checker/.env).")

# Platforma bilan servis orasidagi umumiy kalit. Servis faqat localhost'da
# tinglaydi, lekin baribir tokensiz so'rov qabul qilinmaydi.
CHECKER_TOKEN = os.getenv("CHECKER_TOKEN", "")
if not CHECKER_TOKEN:
    raise RuntimeError("CHECKER_TOKEN o'rnatilmagan (checker/.env).")

CHECKER_HOST = os.getenv("CHECKER_HOST", "127.0.0.1")
CHECKER_PORT = int(os.getenv("CHECKER_PORT", "8090"))

ANSWER_SHEET_ASSETS_DIR = Path(
    os.getenv("ANSWER_SHEET_ASSETS_DIR", str(BASE_DIR / "assets" / "answer_sheet"))
)

# Bir vaqtda nechta og'ir ish (shablon chizish / skan tekshirish). Har skan
# ~150 MB oladi — smartbot DECISIONS.md #5 dagi bilan bir xil sabab.
MAX_PARALLEL_JOBS = int(os.getenv("CHECKER_MAX_PARALLEL", "2"))

# Yuklanadigan skan fayli va undagi sahifalar chegarasi.
MAX_UPLOAD_MB = int(os.getenv("CHECKER_MAX_UPLOAD_MB", "80"))
MAX_SCAN_PAGES = int(os.getenv("CHECKER_MAX_SCAN_PAGES", "300"))

# Rasmdan savol o'qish (POST /ocr) — Tesseract. PATH'da bo'lmasa to'liq yo'l
# (Windows: C:\Program Files\Tesseract-OCR\tesseract.exe).
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")
# Til fayllari (uzb.traineddata, eng.traineddata) papkasi; bo'sh bo'lsa
# Tesseract o'zinikini ishlatadi (Linux: apt'dagi tesseract-ocr-uzb).
TESSDATA_DIR = os.getenv("TESSDATA_DIR", "")
# eng qo'shilgani "+", "=" va raqamli qatorlarni ancha yaxshi o'qiydi.
OCR_LANG = os.getenv("OCR_LANG", "uzb+eng")
MAX_OCR_PAGES = int(os.getenv("CHECKER_MAX_OCR_PAGES", "20"))
