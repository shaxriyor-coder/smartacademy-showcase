"""Ruxsatnoma va javob varag'i PDF generatsiyasini LOKAL tekshirish.

Faqat Dockerfile.localtest ICHIDA ishlatish uchun (Windows'da WeasyPrint
kerakli tizim kutubxonalarisiz ishlamaydi). Botga, bazaga yoki Telegramga
umuman ulanmaydi — faqat services/ticket_service.py va
services/answer_sheet_service.py ni haqiqiy WeasyPrint bilan sinaydi.

Ishga tushirish (loyiha papkasida, Docker ichida):
    docker run --rm -v "${PWD}":/app -w /app -e QR_SECRET=lokal-sinov-kaliti \
        smartbot-localtest python scripts/localtest_pdf.py

Natija: localtest_output/ papkasida (host mashinada ham ko'rinadi, chunki
volume orqali ulangan) haqiqiy PDF fayllar paydo bo'ladi.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import io  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

from services.ticket_service import (  # noqa: E402
    EntryPassContext,
    TicketContext,
    generate_entry_pass,
    generate_ticket,
)
from utils.participant_photo import prepare_participant_photo  # noqa: E402
from services.answer_sheet_service import (  # noqa: E402
    AnswerSheetContext,
    SubjectSpec,
    extract_field_boxes,
    render_blank_sheet_pdf,
    stamp_answer_sheets_pdf,
)

import asyncio  # noqa: E402


async def main() -> None:
    out_dir = PROJECT_ROOT / "localtest_output"
    out_dir.mkdir(exist_ok=True)

    print("1) Ruxsatnoma (bitta ishtirokchi: PDF + PNG)...")
    ticket_ctx = TicketContext(
        familiya="Mirzo-Ulug'bekov-Sultonmurodov",
        ism="Muhammadaminxo'jayevich",
        ticket_no="SA-2026-MATH-0004182",
        phone="+998 90 765 43 21",
        event_title="Matematika olimpiadasi 2026 (LOKAL SINOV)",
    )
    ticket_pdf, ticket_png = await generate_ticket(ticket_ctx)
    (out_dir / "ruxsatnoma_sinov.pdf").write_bytes(ticket_pdf)
    (out_dir / "ruxsatnoma_sinov.png").write_bytes(ticket_png)
    print(f"   OK -> {out_dir / 'ruxsatnoma_sinov.pdf'} ({len(ticket_pdf)} bayt)")
    print(f"   OK -> {out_dir / 'ruxsatnoma_sinov.png'} ({len(ticket_png)} bayt)")

    print("2) Javob varag'i: bo'sh shablon (sekin, bir marta)...")
    subjects = (
        SubjectSpec("Matematika", 30, 5),
        SubjectSpec("Ingliz tili", 20, 4),
        SubjectSpec("Mantiq", 15, 5),
    )
    blank_pdf = await render_blank_sheet_pdf(
        subjects, "Matematika olimpiadasi 2026 (LOKAL SINOV)"
    )
    (out_dir / "javob_varagi_bosh_shablon.pdf").write_bytes(blank_pdf)
    print(f"   OK -> {out_dir / 'javob_varagi_bosh_shablon.pdf'} ({len(blank_pdf)} bayt)")

    field_boxes = extract_field_boxes(blank_pdf)
    print("   maydon koordinatalari topildi")

    print("3) Javob varag'i: 2 ta ishtirokchiga shtamplash (tez)...")
    sheet_contexts = [
        AnswerSheetContext(
            ism="Robiyaxon", familiya="Abdurashidxo'jayeva",
            kun="15", oy="05", yil="2014", sinf="5-sinf",
            ticket_no="SA-2026-MATH-0004181",
        ),
        AnswerSheetContext(
            ism="Ali", familiya="Valiyev",
            kun="03", oy="09", yil="2013", sinf="6-sinf",
            ticket_no="SA-2026-MATH-0004182",
        ),
    ]
    sheet_pdf = await stamp_answer_sheets_pdf(blank_pdf, field_boxes, sheet_contexts)
    (out_dir / "javob_varagi_sinov.pdf").write_bytes(sheet_pdf)
    print(f"   OK -> {out_dir / 'javob_varagi_sinov.pdf'} ({len(sheet_pdf)} bayt)")

    print("4) Kirish ruxsatnomasi (qabulda, rasm bilan: PDF + PNG)...")
    photo = Image.new("RGB", (960, 1280), (210, 205, 228))
    ImageDraw.Draw(photo).ellipse([330, 250, 630, 580], fill=(120, 105, 160))
    buf = io.BytesIO()
    photo.save(buf, "JPEG")
    entry_ctx = EntryPassContext(
        familiya="Mirzo-Ulug'bekov-Sultonmurodov",
        ism="Muhammadaminxo'jayevich",
        ticket_no="SA-2026-MATH-0004182",
        event_title="Matematika olimpiadasi 2026 (LOKAL SINOV)",
        exam_date="20.09.2026",
        slot_label="10:00 - 11:30",
        room_number="3",
        birth_date="03.09.2013",
        grade="6-sinf",
        school="Asaka tumani 12-maktab",
        teacher="",
        phone="+998 90 765 43 21",
        photo_jpeg=prepare_participant_photo(buf.getvalue()),
    )
    entry_pdf, entry_png = await generate_entry_pass(entry_ctx)
    (out_dir / "kirish_ruxsatnomasi_sinov.pdf").write_bytes(entry_pdf)
    (out_dir / "kirish_ruxsatnomasi_sinov.png").write_bytes(entry_png)
    print(f"   OK -> {out_dir / 'kirish_ruxsatnomasi_sinov.pdf'} ({len(entry_pdf)} bayt)")

    print("\nHammasi muvaffaqiyatli generatsiya qilindi.")
    print("PDF fayllarni host mashinangizdagi localtest_output/ papkasidan oching.")


if __name__ == "__main__":
    asyncio.run(main())
