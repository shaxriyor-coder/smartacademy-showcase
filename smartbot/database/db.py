import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from config import DATABASE_URL


logger = logging.getLogger(__name__)

engine = create_async_engine(DATABASE_URL, echo=False)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Bazadagi jadvallarni yaratadi va kerakli ustunlarni qo‘shadi."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # users jadvaliga yangi ustunlarni qo‘shish
        await conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS grade INTEGER;
                """
            )
        )

        await conn.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS teacher_name VARCHAR(150);
                """
            )
        )

        # olympiad_results jadvaliga fan bo'yicha taqsimot ustunlarini qo'shish
        # (matn ko'rinishidagi natija va sertifikat generatsiyasi uchun kerak)
        await conn.execute(
            text(
                """
                ALTER TABLE olympiad_results
                ADD COLUMN IF NOT EXISTS math_correct INTEGER;
                """
            )
        )
        await conn.execute(
            text(
                """
                ALTER TABLE olympiad_results
                ADD COLUMN IF NOT EXISTS math_total INTEGER;
                """
            )
        )
        await conn.execute(
            text(
                """
                ALTER TABLE olympiad_results
                ADD COLUMN IF NOT EXISTS english_correct INTEGER;
                """
            )
        )
        await conn.execute(
            text(
                """
                ALTER TABLE olympiad_results
                ADD COLUMN IF NOT EXISTS english_total INTEGER;
                """
            )
        )

        # --- Olimpiadaga yozilishda so'raladigan ma'lumotlar ---
        # Bular endi bot ro'yxatida emas, olimpiadaga yozilishda so'raladi.
        for col, coltype in (
            ("school", "VARCHAR(150)"),
            ("grade", "INTEGER"),
            ("teacher_name", "VARCHAR(150)"),
        ):
            await conn.execute(
                text(
                    f"ALTER TABLE olympiad_results "
                    f"ADD COLUMN IF NOT EXISTS {col} {coltype};"
                )
            )

        # users.school endi majburiy emas — yangi foydalanuvchilardan
        # so'ralmaydi. DIQQAT: bu faqat cheklovni bo'shatadi, mavjud
        # foydalanuvchilarning maktab ma'lumoti o'z joyida qoladi.
        await conn.execute(
            text("ALTER TABLE users ALTER COLUMN school DROP NOT NULL;")
        )

        # --- Olimpiada sinflari va foiz ---
        # score butun son emas (71.2 kabi) — turni kengaytiramiz.
        # DIQQAT: INTEGER -> DOUBLE PRECISION kengaytirish, mavjud
        # qiymatlar o'zgarmaydi va yo'qolmaydi.
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ALTER COLUMN score TYPE DOUBLE PRECISION;"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS percentage DOUBLE PRECISION;"
            )
        )

        # --- Fan-oraliqlari bo'yicha to'liq tafsilot (Excel/PDF'dan) ---
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS detail TEXT;"
            )
        )

        # --- Indekslar ---
        # PostgreSQL tashqi kalit ustunlariga indeksni avtomatik yaratmaydi.
        # Ularsiz har "natijalarim" so'rovi butun jadvalni skanlaydi —
        # yozuvlar ko'paygach bu sezilarli yuk beradi.
        for idx, table, col in (
            ("ix_online_test_results_user_id", "online_test_results", "user_id"),
            (
                "ix_online_test_results_test_id",
                "online_test_results",
                "online_test_id",
            ),
            ("ix_olympiad_grades_olympiad_id", "olympiad_grades", "olympiad_id"),
            ("ix_olympiad_results_olympiad_id", "olympiad_results", "olympiad_id"),
            ("ix_olympiad_results_user_id", "olympiad_results", "user_id"),
        ):
            await conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col});")
            )

        # --- Ruxsatnoma: olimpiada kodi, ism/familiya, ticket_no ---
        await conn.execute(
            text("ALTER TABLE olympiads ADD COLUMN IF NOT EXISTS code VARCHAR(10);")
        )
        for col in ("first_name", "last_name"):
            await conn.execute(
                text(
                    f"ALTER TABLE olympiad_results "
                    f"ADD COLUMN IF NOT EXISTS {col} VARCHAR(150);"
                )
            )
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS ticket_no VARCHAR(40);"
            )
        )
        # PostgreSQL unique indeks bir nechta NULL qiymatga ruxsat beradi
        # (NULL hech qachon NULLga teng hisoblanmaydi) — shuning uchun
        # backfill'dan oldin ham xavfsiz yaratsa bo'ladi.
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_olympiad_results_ticket_no "
                "ON olympiad_results (ticket_no);"
            )
        )

        # --- Javob varag'i: ishtirokchining tug'ilgan sanasi ---
        # (answer_sheets / answer_sheet_subjects — yangi jadvallar,
        # Base.metadata.create_all() orqali yuqorida o'zi yaratiladi)
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS birth_date DATE;"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_answer_sheet_subjects_sheet_id "
                "ON answer_sheet_subjects (answer_sheet_id);"
            )
        )

        # Eslatma: `answer_sheets.marking_area_png` ustuni eski bazalarda
        # bor (DECISIONS.md #25), lekin ISHLATILMAYDI — o'rniga butun
        # bo'sh sahifa PDF sifatida saqlanadi (#27). Mavjud bazalarda
        # ustun qoldiriladi (hech qachon DROP qilinmaydi), yangi bazada
        # esa umuman yaratilmaydi: shuning uchun uni qo'shadigan
        # migratsiya bu yerdan olib tashlandi.

        # --- Javob varag'i: oldindan chizilgan BO'SH sahifa + maydon
        # koordinatalari (DECISIONS.md #27) ---
        await conn.execute(
            text("ALTER TABLE answer_sheets ADD COLUMN IF NOT EXISTS blank_pdf BYTEA;")
        )
        await conn.execute(
            text("ALTER TABLE answer_sheets ADD COLUMN IF NOT EXISTS field_boxes TEXT;")
        )
        # Doira markazlari — avtomatik tekshirish uchun (DECISIONS.md #29)
        await conn.execute(
            text(
                "ALTER TABLE answer_sheets "
                "ADD COLUMN IF NOT EXISTS bubble_boxes TEXT;"
            )
        )
        # To'g'ri javoblar kaliti (qo'lda kiritiladi) — DECISIONS.md #31
        await conn.execute(
            text(
                "ALTER TABLE answer_sheet_subjects "
                "ADD COLUMN IF NOT EXISTS answer_key TEXT;"
            )
        )
        # Baholash mezoni (JSON) — DECISIONS.md #33
        await conn.execute(
            text(
                "ALTER TABLE answer_sheet_subjects "
                "ADD COLUMN IF NOT EXISTS rubric TEXT;"
            )
        )

        # --- Olimpiadadan tashqari javob varag'i (DECISIONS.md #34) ---
        # test_sheets / test_sheet_subjects / test_sheet_participants —
        # yangi jadvallar, create_all() orqali yuqorida o'zi yaratiladi.
        for idx, table, col in (
            ("ix_test_sheet_subjects_sheet_id", "test_sheet_subjects", "test_sheet_id"),
            (
                "ix_test_sheet_participants_sheet_id",
                "test_sheet_participants",
                "test_sheet_id",
            ),
        ):
            await conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col});")
            )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_test_sheet_participants_ticket "
                "ON test_sheet_participants (ticket_no);"
            )
        )

        # --- Ishtirokchini qabul qilish (reception check-in): vaqt/xona
        # (olympiad_time_slots / olympiad_rooms — yangi jadvallar,
        # Base.metadata.create_all() orqali yuqorida o'zi yaratiladi).
        # FK EMAS ataylab (qarang: database/models.py -> OlympiadResult) —
        # eski xona/vaqt o'chirilganda bu ustunlar application darajasida
        # aniq NULL qilinadi. DECISIONS.md #26. ---
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS time_slot_id INTEGER;"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS room_id INTEGER;"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS attended_at TIMESTAMP;"
            )
        )
        # Qabulda yuklangan ishtirokchi rasmi (Telegram file_id) — DECISIONS.md #39
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(255);"
            )
        )
        # Bitta varaqni bir nechta guruhga chiqarish (DECISIONS.md #47):
        # har bir ishtirokchi qaysi guruhdan kelgani yoziladi.
        await conn.execute(
            text(
                "ALTER TABLE test_sheet_participants "
                "ADD COLUMN IF NOT EXISTS guruh VARCHAR(150);"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE test_sheet_participants "
                "ADD COLUMN IF NOT EXISTS classroom_id VARCHAR(40);"
            )
        )
        # Online testda rasm endi ixtiyoriy: savollar kanaldagi e'londa
        # turadi, botga faqat muqova (reklama) rasmi qo'yiladi yoki umuman
        # qo'yilmaydi (DECISIONS.md #46).
        await conn.execute(
            text("ALTER TABLE online_tests ALTER COLUMN image_file_id DROP NOT NULL;")
        )
        # --- Farzandlar (DECISIONS.md #41) ---
        # `children` jadvalini create_all() yuqorida o'zi yaratadi.
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_children_user_id ON children (user_id);")
        )
        # Natija endi farzandga bog'lanadi. Eski qatorlarda bo'sh qoladi —
        # ular akkaunt egasining o'zi kiritgan ma'lumotlari bilan qolaveradi.
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "ADD COLUMN IF NOT EXISTS child_id INTEGER "
                "REFERENCES children(id) ON DELETE SET NULL;"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_olympiad_results_child_id "
                "ON olympiad_results (child_id);"
            )
        )
        # Eski yagonalik (bitta akkaunt — bitta yozuv) o'rniga ikkita QISMAN
        # unique indeks: farzand bir olimpiadaga bir marta, farzandsiz eski
        # yozuv esa avvalgidek akkauntga bitta. Shu ALTER bo'lmasa bir nechta
        # farzandni yozdirish bazadan o'tmaydi (database/models.py).
        await conn.execute(
            text(
                "ALTER TABLE olympiad_results "
                "DROP CONSTRAINT IF EXISTS uq_olympiad_user;"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_olympiad_child "
                "ON olympiad_results (olympiad_id, child_id) "
                "WHERE child_id IS NOT NULL;"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_olympiad_user_self "
                "ON olympiad_results (olympiad_id, user_id) "
                "WHERE child_id IS NULL;"
            )
        )

        for idx, table, col in (
            ("ix_olympiad_time_slots_olympiad_id", "olympiad_time_slots", "olympiad_id"),
            ("ix_olympiad_rooms_olympiad_id", "olympiad_rooms", "olympiad_id"),
            ("ix_olympiad_results_time_slot_id", "olympiad_results", "time_slot_id"),
            ("ix_olympiad_results_room_id", "olympiad_results", "room_id"),
        ):
            await conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS {idx} ON {table} ({col});")
            )

    await _backfill_ruxsatnoma_fields()

    logger.info("Database tables initialized successfully.")


async def _backfill_ruxsatnoma_fields() -> None:
    """Ruxsatnoma funksiyasidan OLDIN yaratilgan yozuvlarga code/ticket_no
    to'ldiradi.

    Model klasslari shu funksiya ICHIDA import qilinadi (yuqorida emas) —
    aks holda database.models -> database.db -> database.models aylanma
    import hosil bo'lardi (models.py o'zi `from database.db import Base`
    qiladi).
    """
    from database.models import Olympiad, OlympiadResult
    from utils.qr_payload import build_ticket_no
    from utils.utility import slugify_olympiad_code

    async with async_session() as session:
        kodsiz = (
            await session.execute(select(Olympiad).where(Olympiad.code.is_(None)))
        ).scalars().all()
        for o in kodsiz:
            o.code = slugify_olympiad_code(o.name)
        if kodsiz:
            await session.commit()
            logger.info(f"{len(kodsiz)} ta olimpiadaga kod berildi (backfill).")

    async with async_session() as session:
        ticketsiz = (
            await session.execute(
                select(OlympiadResult, Olympiad.code)
                .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
                .where(OlympiadResult.ticket_no.is_(None))
            )
        ).all()
        for result, code in ticketsiz:
            year = (result.registered_at or result.checked_at or datetime.utcnow()).year
            result.ticket_no = build_ticket_no(year, code or "GEN", result.id)
        if ticketsiz:
            await session.commit()
            logger.info(f"{len(ticketsiz)} ta yozuvga ticket_no berildi (backfill).")
