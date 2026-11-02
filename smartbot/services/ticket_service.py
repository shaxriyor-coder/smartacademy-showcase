"""Ruxsatnoma (ishtirokchi hujjati) PDF/PNG generatsiyasi.

Oqim:  ticket_no -> QR payload -> Jinja2 render -> WeasyPrint PDF ->
       pdftoppm PNG (200 DPI). Hech qanday natija diskda saqlanmaydi —
       PDF va PNG baytlar sifatida qaytariladi. pdftoppm CLI dastur
       bo'lgani uchun vaqtinchalik faylsiz ishlay olmaydi, lekin ular
       `tempfile.TemporaryDirectory()` ichida — funksiya tugashi bilan
       avtomatik o'chib ketadi, hech narsa qoldirilmaydi.

WeasyPrint bloklovchi (sinxron) kutubxona — shuning uchun butun
generatsiya `asyncio.to_thread` ichida ishlaydi.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import QR_SECRET, TICKET_ASSETS_DIR, PDFTOPPM_PATH
from utils.qr_payload import build_qr_payload

logger = logging.getLogger(__name__)


class TicketGenerationError(Exception):
    """WeasyPrint yoki pdftoppm ishlamay qolganda ko'tariladi."""


@dataclass(frozen=True)
class TicketContext:
    """Ruxsatnomaga kerak bo'lgan o'zgaruvchi ma'lumot.

    Lug'at (dict) emas, dataclass — maydon nomini adashtirsangiz
    (masalan "familya") shu yerda darhol xato chiqadi, shablon ichida
    jimgina bo'sh qatorga aylanib qolmaydi.
    """

    familiya: str
    ism: str
    ticket_no: str
    phone: str
    event_title: str


# Jinja2 Environment va shablon bir marta yuklanadi — har so'rovda emas.
_env = Environment(
    loader=FileSystemLoader(str(TICKET_ASSETS_DIR)),
    autoescape=select_autoescape(["html"]),
)
_template = _env.get_template("ruxsatnoma.html")


def _name_size_class(familiya: str, ism: str) -> str:
    """Ism/familiyaning eng uzuni asosida shrift darajasini tanlaydi.

    Maqsad — .zone balandligi (ruxsatnoma.html) hech qachon buzilmasligi:
    har darajada ham matn 2 qatordan oshmaydi. WeasyPrint sertifikat
    generatsiyasidagi kabi ishga tushirish vaqtida piksel o'lchay
    olmaydi (u faqat CSS'ga qarab joylashtiradi), shuning uchun
    o'lchamlar oldindan uzunlik bo'yicha bosqichlarga bo'lingan va
    brauzerda haqiqiy uzun ismlar bilan sinovdan o'tkazilgan.
    """
    n = max(len(familiya), len(ism))
    if n <= 10:
        return "sz1"
    if n <= 16:
        return "sz2"
    if n <= 23:
        return "sz3"
    return "sz4"


def _make_qr_data_uri(ticket_no: str) -> str:
    payload = build_qr_payload(ticket_no, QR_SECRET)
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=2, box_size=10)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1C1440", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _build_record(ctx: TicketContext) -> dict:
    """Bitta ruxsatnoma uchun shablonga kerak bo'lgan hisoblangan
    maydonlarni (QR, shrift darajasi, berilgan vaqt) qo'shib qaytaradi.
    """
    return {
        "familiya": ctx.familiya,
        "ism": ctx.ism,
        "ticket_no": ctx.ticket_no,
        "phone": ctx.phone,
        "event_title": ctx.event_title,
        "qr_data_uri": _make_qr_data_uri(ctx.ticket_no),
        "issued_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "name_size_class": _name_size_class(ctx.familiya, ctx.ism),
    }


def _render_html(ctx: TicketContext) -> str:
    return _template.render(r=_build_record(ctx))


def _weasyprint_html_to_pdf(html_str: str) -> bytes:
    # WeasyPrint shu yerda, funksiya ichida import qilinadi: u tizimga
    # o'rnatilgan libpango/libcairo'ga tayanadi (qarang: README/deploy
    # hujjatidagi apt-get ro'yxati). Bu kutubxonalar bo'lmagan muhitda
    # (masalan lokal ishlab chiqish kompyuterida) modul yuqorida import
    # qilinsa, ruxsatnoma bilan aloqasi yo'q butun bot ishga tushmay
    # qolardi — chunki bu servis handlers/user.py orqali botning har
    # ishga tushishida yuklanadi.
    try:
        from weasyprint import HTML
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        raise TicketGenerationError(f"WeasyPrint yuklanmadi: {e}") from e

    try:
        return HTML(string=html_str, base_url=str(TICKET_ASSETS_DIR)).write_pdf()
    except Exception as e:
        raise TicketGenerationError(f"WeasyPrint PDF generatsiyasida xato: {e}") from e


def _render_pdf_sync(ctx: TicketContext) -> bytes:
    return _weasyprint_html_to_pdf(_render_html(ctx))


def _pdf_to_png_sync(pdf_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "ticket.pdf"
        pdf_path.write_bytes(pdf_bytes)
        out_prefix = Path(tmp) / "ticket"
        try:
            subprocess.run(
                [
                    PDFTOPPM_PATH,
                    "-png",
                    "-r",
                    "200",
                    "-singlefile",
                    str(pdf_path),
                    str(out_prefix),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError as e:
            raise TicketGenerationError(
                f"pdftoppm topilmadi ('{PDFTOPPM_PATH}') — poppler-utils "
                f"o'rnatilganini tekshiring. Windows'da PATH'ga qo'shish "
                f"o'rniga .env dagi PDFTOPPM_PATH'ni to'liq .exe yo'liga "
                f"o'zgartirish mumkin."
            ) from e
        except subprocess.TimeoutExpired as e:
            raise TicketGenerationError("pdftoppm 30 soniyada javob bermadi") from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if e.stderr else ""
            raise TicketGenerationError(f"pdftoppm xato bilan tugadi: {stderr}") from e

        png_path = out_prefix.with_suffix(".png")
        if not png_path.exists():
            raise TicketGenerationError("pdftoppm PNG fayl yaratmadi")
        return png_path.read_bytes()


def _generate_sync(ctx: TicketContext) -> tuple[bytes, bytes]:
    pdf_bytes = _render_pdf_sync(ctx)
    png_bytes = _pdf_to_png_sync(pdf_bytes)
    return pdf_bytes, png_bytes


async def generate_ticket(ctx: TicketContext) -> tuple[bytes, bytes]:
    """(pdf_bytes, png_bytes) qaytaradi. Og'ir ish alohida oqimda bajariladi."""
    return await asyncio.to_thread(_generate_sync, ctx)


# ---------------------------------------------------------------------------
# Kirish ruxsatnomasi (A4) — qabul qilishda, vaqt/xona tanlanib ishtirokchi
# rasmi yuklangandan keyin qabulxonaga yuboriladi (DECISIONS.md #39).
# Yuqoridagi ro'yxatdan o'tish ruxsatnomasidan farqi: rasm, vaqt/xona,
# qoidalar. Xuddi o'shanday hech narsa diskda qolmaydi.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryPassContext:
    familiya: str
    ism: str
    ticket_no: str
    event_title: str
    exam_date: str
    slot_label: str
    room_number: str
    birth_date: str
    grade: str
    school: str
    teacher: str
    phone: str
    photo_jpeg: bytes  # utils/participant_photo.py tayyorlagan 3x4 rasm


_entry_template = _env.get_template("kirish_ruxsatnomasi.html")

# Vaqt katagi 6.2mm shriftda shuncha belgigacha bir qatorga sig'adi
# ("10:00 - 11:30" — 13 belgi, sig'maydi).
_SLOT_LABEL_FULL_SIZE = 11


def _build_entry_record(ctx: EntryPassContext) -> dict:
    def value(text: str) -> str:
        return text.strip() or "—"

    return {
        "familiya": ctx.familiya,
        "ism": ctx.ism,
        "ticket_no": ctx.ticket_no,
        "event_title": ctx.event_title,
        "exam_date": value(ctx.exam_date),
        "slot_label": value(ctx.slot_label),
        "slot_size_class": "slot-sm" if len(ctx.slot_label) > _SLOT_LABEL_FULL_SIZE else "",
        "room_number": value(ctx.room_number),
        "birth_date": value(ctx.birth_date),
        "grade": value(ctx.grade),
        "school": value(ctx.school),
        "teacher": value(ctx.teacher),
        "phone": value(ctx.phone),
        "qr_data_uri": _make_qr_data_uri(ctx.ticket_no),
        "photo_data_uri": "data:image/jpeg;base64," + base64.b64encode(ctx.photo_jpeg).decode(),
        "issued_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def _generate_entry_sync(ctx: EntryPassContext) -> tuple[bytes, bytes]:
    pdf_bytes = _weasyprint_html_to_pdf(_entry_template.render(r=_build_entry_record(ctx)))
    return pdf_bytes, _pdf_to_png_sync(pdf_bytes)


async def generate_entry_pass(ctx: EntryPassContext) -> tuple[bytes, bytes]:
    """Kirish ruxsatnomasi: (pdf_bytes, png_bytes). Og'ir ish alohida oqimda."""
    return await asyncio.to_thread(_generate_entry_sync, ctx)
