import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN o'rnatilmagan (smartbot/.env).")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL o'rnatilmagan (smartbot/.env).")

# Default SuperAdmin Chat IDs (Users who are always SuperAdmins)
DEFAULT_SUPERADMIN_IDS = [
    int(x.strip()) for x in os.getenv("SUPERADMIN_IDS", "").split(",") if x.strip().isdigit()
]

# Ruxsatnoma QR kodlarini imzolash uchun maxfiy kalit (HMAC-SHA256).
# Soxta ruxsatnoma yasashning oldini oladi — shuning uchun bo'sh
# qoldirilsa bot butunlay ishga tushmasligi kerak (jimgina imzosiz
# ishlab ketishi xavfliroq bo'lardi).
QR_SECRET = os.getenv("QR_SECRET", "")
if not QR_SECRET:
    raise RuntimeError(
        "QR_SECRET o'rnatilmagan. .env fayliga QR_SECRET=<maxfiy_qiymat> qo'shing "
        "(masalan: python -c \"import secrets; print(secrets.token_hex(32))\")."
    )

# Ruxsatnoma shabloni (ruxsatnoma.html) va logotip (logo_brend.png) shu
# papkada — utils/certificate.py dagi ASSETS_DIR bilan bir xil mantiq:
# deploy faqat "utils" papkasini serverga yuboradi, shuning uchun
# loyihaning boshqa joyiga tayanmaymiz.
TICKET_ASSETS_DIR = Path(
    os.getenv(
        "TICKET_ASSETS_DIR",
        str(Path(__file__).parent / "utils" / "assets" / "ruxsatnoma"),
    )
)

# Javob varag'i shabloni (answer_sheet.html) va logotip shu papkada.
ANSWER_SHEET_ASSETS_DIR = Path(
    os.getenv(
        "ANSWER_SHEET_ASSETS_DIR",
        str(Path(__file__).parent / "utils" / "assets" / "answer_sheet"),
    )
)

# pdftoppm (poppler-utils) ijro faylining yo'li — PDF -> PNG (ruxsatnoma
# uchun). Production serverda apt orqali PATH'ga tushadi, standart qiymat
# ("pdftoppm") o'zi ishlaydi. Windows'da poppler alohida o'rnatilishi va
# PATH'ga qo'shilmasligi mumkin — o'sha holatda shu yerga to'liq yo'l
# ko'rsatiladi (masalan C:\poppler\Library\bin\pdftoppm.exe), tizim
# PATH'ini o'zgartirishga hojat qolmaydi.
PDFTOPPM_PATH = os.getenv("PDFTOPPM_PATH", "pdftoppm")

# SmartAcademy platformasi — shu botning Mini App'i (docs/DECISIONS.md #38).
# Ommaviy HTTPS manzil, masalan https://platform.example.com. Bo'sh bo'lsa
# "Open App" tugmasi qo'shilmaydi va bot avvalgidek ishlaydi.
PLATFORM_URL = os.getenv("PLATFORM_URL", "").strip().rstrip("/")

# Platforma bazasi — FAQAT O'QISH uchun (docs/DECISIONS.md #40): javob
# varag'ini platformada tuzilgan testdan sozlash. Read-only foydalanuvchi
# bilan ulanadi (deploy/postgres/setup.sql). Bo'sh bo'lsa bu imkoniyat
# ko'rinmaydi va bot avvalgidek ishlayveradi.
PLATFORM_DATABASE_URL = os.getenv("PLATFORM_DATABASE_URL", "").strip()
