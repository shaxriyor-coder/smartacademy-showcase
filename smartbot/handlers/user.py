import logging
import json
import os
import re
import time
from datetime import datetime
from aiogram import Router, F, Bot

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    FSInputFile,
    BufferedInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database.db import async_session
from database.models import (
    User,
    Child,
    Olympiad,
    OlympiadResult,
    OnlineTest,
    OnlineTestResult,
    OlympiadGrade,
)
from utils.platform import send_open_app
from utils.certificate import generate_certificate
from utils.utility import (
    academic_year_start,
    current_grade,
    parse_flexible_date,
    fmt_number,
    split_full_name,
)
from utils.qr_payload import build_ticket_no
from utils.roles import (
    get_staff_role,
    notify_superadmins,
    ROLE_SUPERADMIN,
    ROLE_ADMIN,
    ROLE_TEACHER,
    ROLE_SMM,
    ROLE_RECEPTION,
)
from services.ticket_service import (
    TicketContext,
    TicketGenerationError,
    generate_ticket,
)
from handlers.admin import (
    get_admin_keyboard,
    get_teacher_keyboard,
    get_smm_keyboard,
    get_reception_keyboard,
)
from handlers.superadmin import get_superadmin_keyboard

logger = logging.getLogger(__name__)

router = Router()


# Bazadagi ustun uzunliklari — database/models.py bilan mos bo'lishi SHART.
# Bulardan uzun qiymat kelsa PostgreSQL yozishni rad etadi va ro'yxatdan
# o'tish yiqiladi, shuning uchun kiritish paytida tekshiriladi.
MAX_PHONE_LEN = 20
MAX_NAME_LEN = 150
MAX_SCHOOL_LEN = 150
MAX_TEACHER_LEN = 150


def normalize_phone(raw: str) -> str | None:
    """Telefon raqamini tozalaydi: faqat raqamlar va boshidagi '+' qoladi.

    Foydalanuvchi qavs, bo'shliq yoki izoh bilan yozganda tozalanmagan matn
    20 belgilik ustunga sig'masdi va ro'yxatdan o'tish xatolik bilan tugardi.
    """
    if not raw:
        return None
    s = raw.strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not (9 <= len(digits) <= 15):
        return None
    return ("+" if plus else "") + digits


def is_valid_school(name: str):
    """
    Maktab nomini kiritdimi yoki yo'qligini tekshiradi.
    """
    name = name.lower().strip()

    patterns = [
        r"\d+\s*-?\s*maktab",
        r"\d+\s*-?\s*sonli maktab",
        r"\d+\s*-?\s*idum",
        r"\d+\s*-?\s*ixtisoslashtirilgan maktab",
    ]

    return any(re.search(p, name) for p in patterns)


class RegistrationStates(StatesGroup):
    """Botdan foydalanish uchun zarur bo'lgan eng kam ma'lumot.

    Maktab, sinf va o'qituvchi bu yerda so'ralmaydi: farzand ma'lumotlari
    "👨‍👩‍👧 Farzandlarim" bo'limida (ChildStates), sinf rahbari esa aynan
    olimpiadaga yozilishda (OlympiadChildStates) so'raladi.
    Chat ID ni Telegram beradi, foydalanuvchi yozmaydi.
    """

    waiting_for_phone = State()
    waiting_for_name = State()
    waiting_for_birthdate = State()


class EditProfileStates(StatesGroup):
    waiting_for_new_value = State()


def get_olympiad_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Olimpiadaga yozilish savollari paytidagi bekor qilish tugmasi."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


async def _olymp_cancelled(message: Message, state: FSMContext) -> bool:
    """Foydalanuvchi bekor qilgan bo'lsa jarayonni to'xtatadi."""
    if (message.text or "").strip() == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=get_main_keyboard())
        return True
    return False


def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏆 Olimpiadalar")],
            [KeyboardButton(text="👨‍👩‍👧 Farzandlarim")],
            [KeyboardButton(text="🧩 Online test")],
            [KeyboardButton(text="🏅 Natijalarim")],
            [KeyboardButton(text="ℹ️ Malumotlarim")],
        ],
        resize_keyboard=True,
    )


# ============================================================================
# KANAL A'ZOLIGI
# ============================================================================

REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "").strip()
REQUIRED_CHANNEL_URL = os.getenv("REQUIRED_CHANNEL_URL", "").strip()
if REQUIRED_CHANNEL and not REQUIRED_CHANNEL_URL:
    REQUIRED_CHANNEL_URL = f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}"

# A'zolik natijasi shu muddatga eslab qolinadi. Ularsiz har bosilgan tugma
# uchun Telegram'ga so'rov ketardi — bu ham sekin, ham API chegarasiga yaqin.
_SUB_CACHE_TTL = 600  # sekund
_sub_cache: dict[int, tuple[bool, float]] = {}


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Kanalga qo'shilish", url=REQUIRED_CHANNEL_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ A'zolikni tekshirish", callback_data="check_subscription"
                )
            ],
        ]
    )


async def is_subscribed(bot: Bot, user_id: int) -> bool | None:
    """True — a'zo, False — a'zo emas, None — tekshirib bo'lmadi."""
    if not REQUIRED_CHANNEL:
        return True

    now = time.monotonic()
    cached = _sub_cache.get(user_id)
    if cached and now - cached[1] < _SUB_CACHE_TTL:
        return cached[0]

    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
    except TelegramAPIError as e:
        # Odatda bot kanalga administrator qilib qo'shilmagan bo'ladi.
        logger.error(
            f"Kanal a'zoligini tekshirib bo'lmadi ({REQUIRED_CHANNEL}): {e}. "
            f"Bot kanalga administrator qilib qo'shilganini tekshiring."
        )
        return None

    ok = member.status in {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }
    if member.status == ChatMemberStatus.RESTRICTED:
        ok = bool(getattr(member, "is_member", False))

    _sub_cache[user_id] = (ok, now)
    return ok


async def require_subscription(message: Message, bot: Bot) -> bool:
    """A'zo bo'lmasa xabar berib False qaytaradi.

    Tekshirib bo'lmasa (None) — ichkariga qo'yamiz va logga yozamiz.
    Sozlamadagi nosozlik tufayli barcha o'quvchilar botdan uzilib
    qolmasligi uchun ataylab shunday qilingan.
    """
    subscribed = await is_subscribed(bot, message.chat.id)
    if subscribed is None or subscribed:
        return True

    await message.answer(
        f"❗️ Botdan foydalanish uchun avval {REQUIRED_CHANNEL} kanaliga "
        f"a'zo bo'ling.\n\n"
        f"Qo'shilgach, «✅ A'zolikni tekshirish» tugmasini bosing.",
        reply_markup=get_subscription_keyboard(),
    )
    return False


@router.callback_query(F.data == "check_subscription")
async def check_subscription_handler(
    callback: CallbackQuery, state: FSMContext, bot: Bot
):
    # Tugma bosilganda keshni bekor qilamiz — foydalanuvchi hozirgina qo'shilgan
    _sub_cache.pop(callback.from_user.id, None)
    subscribed = await is_subscribed(bot, callback.from_user.id)

    if subscribed is False:
        await callback.answer(
            f"Siz hali {REQUIRED_CHANNEL} kanaliga a'zo emassiz.", show_alert=True
        )
        return

    await callback.answer("A'zolik tasdiqlandi ✅")
    try:
        await callback.message.edit_text("✅ Kanalga a'zolik tasdiqlandi.")
    except Exception:
        pass
    await start_flow(callback.message, state)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext, bot: Bot):
    """/start: avval kanal a'zoligi tekshiriladi, keyin rolga qarab panel."""
    await state.clear()

    # Xodimlarga kanal sharti qo'yilmaydi — ular boshqaruv uchun kiradi
    async with async_session() as session:
        staff_role = await get_staff_role(message.chat.id, session)
    if staff_role is None and not await require_subscription(message, bot):
        return

    await start_flow(message, state)


async def start_flow(message: Message, state: FSMContext):
    """Rolga qarab tegishli panelni ko'rsatadi.

    Izoh: avval xodim (SuperAdmin/Admin/O'qituvchi/SMM menejer)
    yoki oddiy ro'yxatdan o'tgan foydalanuvchi ekanini tekshiradi va tegishli
    salomlashuv + panelni ko'rsatadi. Hech biriga to'g'ri kelmasa (hali
    ro'yxatdan o'tmagan), ro'yxatdan o'tish jarayonini boshlaydi."""

    chat_id = message.chat.id
    await state.clear()

    async with async_session() as session:
        role = await get_staff_role(chat_id, session)

        if role == ROLE_SUPERADMIN:
            await message.answer(
                "⚡ Assalomu alaykum, SuperAdmin!\n\nSuperAdmin paneliga xush kelibsiz.",
                reply_markup=get_superadmin_keyboard(),
            )
            await send_open_app(message)
            return
        if role == ROLE_ADMIN:
            await message.answer(
                "👑 Assalomu alaykum, Admin!\n\nAdmin paneliga xush kelibsiz.",
                reply_markup=get_admin_keyboard(),
            )
            await send_open_app(message)
            return
        if role == ROLE_TEACHER:
            await message.answer(
                "📚 Assalomu alaykum, O'qituvchi!\n\n"
                "O'qituvchi paneliga xush kelibsiz. Bu yerda test qo'sha va "
                "tekshira olasiz.",
                reply_markup=get_teacher_keyboard(),
            )
            await send_open_app(message)
            return
        if role == ROLE_SMM:
            await message.answer(
                "📢 Assalomu alaykum, SMM menejer!\n\n"
                "SMM menejer paneliga xush kelibsiz. Bu yerdan barcha "
                "foydalanuvchilarga reklama/xabar jo'natishingiz mumkin.",
                reply_markup=get_smm_keyboard(),
            )
            await send_open_app(message)
            return
        if role == ROLE_RECEPTION:
            await message.answer(
                "🏢 Assalomu alaykum!\n\n"
                "Reception paneliga xush kelibsiz. Bu yerdan ishtirokchilarni "
                "qabul qilib, vaqt/xona belgilashingiz mumkin.",
                reply_markup=get_reception_keyboard(),
            )
            await send_open_app(message)
            return

        # Xodim emas — oddiy foydalanuvchi (ota-ona/o'quvchi) ekanini tekshiramiz
        user_res = await session.execute(select(User).where(User.id == chat_id))
        user = user_res.scalar_one_or_none()

    if user:
        await message.answer(
            f"Assalomu alaykum, {user.full_name}! 👋\n\nXush kelibsiz!",
            reply_markup=get_main_keyboard(),
        )
        await send_open_app(message)
        return

    # Hali ro'yxatdan o'tmagan — ro'yxatdan o'tish jarayonini boshlaymiz
    await message.answer(
        "Assalomu alaykum! Ro'yxatdan o'tish uchun telefon raqamingizni yuboring "
        "(yoki quyidagi tugmani bosing):",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📱 Kontakt ulashish", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    await state.set_state(RegistrationStates.waiting_for_phone)


@router.message(RegistrationStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Kontakt orqali yoki qo'lda telefon raqamini qabul qiladi."""

    raw_phone = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw_phone)
    if not phone:
        await message.answer(
            "Telefon raqami tushunarsiz.\n\n"
            "Iltimos, raqamni to'liq yozing (masalan: +998901234567) yoki "
            "«📱 Kontakt ulashish» tugmasidan foydalaning."
        )
        return

    await state.update_data(phone=phone)
    await message.answer(
        "Iltimos, Ism va familiyangizni kiriting (Masalan: Ali Valiyev):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RegistrationStates.waiting_for_name)


@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name.split()) < 2:
        await message.answer(
            "Iltimos, Ism va familiyangizni to'liq kiriting (kamida 2 ta so'z):"
        )
        return
    if len(name) > MAX_NAME_LEN:
        await message.answer(
            f"Ism va familiya juda uzun ({len(name)} belgi). "
            f"Iltimos, {MAX_NAME_LEN} belgidan oshmasin:"
        )
        return

    await state.update_data(name=name)
    await message.answer(
        "Tug'ilgan sanangizni kiriting "
        "(Masalan: 2008-05-15, 15.05.2008 yoki 2008-yil 15-may):"
    )
    await state.set_state(RegistrationStates.waiting_for_birthdate)


@router.message(RegistrationStates.waiting_for_birthdate)
async def process_birthdate(message: Message, state: FSMContext):
    """Ro'yxatdan o'tishning oxirgi bosqichi — foydalanuvchi shu yerda saqlanadi."""
    birthdate = parse_flexible_date(message.text)
    if not birthdate:
        await message.answer(
            "Sana formati tushunilmadi. Iltimos, qaytadan kiriting\n"
            "(Masalan: 2008-05-15, 15.05.2008, 2008yil 15-may yoki 2008 05 15):"
        )
        return

    data = await state.get_data()
    chat_id = message.chat.id  # Telegram beradi, foydalanuvchi yozmaydi
    try:
        async with async_session() as session:
            session.add(
                User(
                    id=chat_id,
                    full_name=data["name"],
                    phone=data["phone"],
                    birth_date=birthdate,
                )
            )
            await session.commit()
    except Exception as e:
        # Bu yerdagi xato ushlanmasa, foydalanuvchi hech qanday javob olmay,
        # kiritgan barcha ma'lumoti bilan birga qotib qoladi.
        logger.error(f"Ro'yxatdan o'tkazishda xato (chat_id={chat_id}): {e}")
        await message.answer(
            "Kechirasiz, ma'lumotlaringizni saqlashda xatolik yuz berdi.\n"
            "Iltimos, /start buyrug'i bilan qaytadan urinib ko'ring."
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"Ro'yxatdan muvaffaqiyatli o'tdingiz, {data['name']}! \U0001f389\n\n"
        f"Olimpiadada qatnashish uchun \"\U0001f3c6 Olimpiadalar\" bo'limiga o'ting.",
        reply_markup=get_main_keyboard(),
    )


# --- OLIMPIADAGA YOZILISH (FARZANDLAR ORQALI) ---
# Ishtirokchining familiyasi, ismi, tug'ilgan sanasi, maktabi va sinfi endi
# "👨‍👩‍👧 Farzandlarim" ro'yxatidan olinadi (DECISIONS.md #41) — olimpiadada
# faqat SINF RAHBARI so'raladi. Sinf har o'quv yili boshida o'zi oshgani
# uchun (utils/utility.py -> current_grade) ota-ona uni qayta kiritmaydi.
#
# Bitta akkaunt bir olimpiadaga bir NECHTA farzandini yozdira oladi: har
# farzand uchun alohida OlympiadResult (va alohida ruxsatnoma) yaratiladi.


class OlympiadChildStates(StatesGroup):
    """Farzandni olimpiadaga yozishda so'raladigan yagona ma'lumot."""

    waiting_for_teacher_name = State()


async def _allowed_grades(session, olympiad_id: int) -> list[int]:
    rows = await session.execute(
        select(OlympiadGrade.grade)
        .where(OlympiadGrade.olympiad_id == olympiad_id)
        .order_by(OlympiadGrade.grade)
    )
    return list(rows.scalars().all())


async def _start_child_registration(
    message: Message,
    state: FSMContext,
    olympiad_id: int,
    olympiad_name: str,
    allowed_grades: list[int] | None = None,
):
    """Olimpiadaga qaysi farzandni yozdirishni so'raydi.

    Sinfi to'g'ri kelmaydigan farzand tugma sifatida chiqmaydi — nega
    qatnasha olmasligi matnda aytiladi, shunda ota-ona xato tanlab ovora
    bo'lmaydi.
    """
    chat_id = message.chat.id
    allowed = allowed_grades or []

    async with async_session() as session:
        children = await _load_children(session, chat_id)
        taken = set(
            (
                await session.execute(
                    select(OlympiadResult.child_id).where(
                        OlympiadResult.olympiad_id == olympiad_id,
                        OlympiadResult.child_id.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    await state.update_data(
        pending_olympiad_id=olympiad_id,
        pending_olympiad_name=olympiad_name,
        allowed_grades=allowed,
    )

    if not children:
        await message.answer(
            f"🏆 **{olympiad_name}**\n\n"
            f"Olimpiadaga farzandingiz nomidan yoziladi, lekin ro'yxatingiz "
            f"hozircha bo'sh.\n\n"
            f"Farzandingizni bir marta qo'shing — keyingi olimpiadalarda "
            f"faqat sinf rahbari so'raladi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="➕ Farzand qo'shish", callback_data="child_add"
                        )
                    ]
                ]
            ),
        )
        return

    buttons, notes = [], []
    for c in children:
        grade = current_grade(c.grade, c.grade_year)
        name = f"{c.last_name} {c.first_name}"
        if c.id in taken:
            notes.append(f"✅ {name} — allaqachon ro'yxatdan o'tgan")
        elif allowed and grade not in allowed:
            notes.append(f"🚫 {name} ({grade}-sinf) — bu olimpiadaga to'g'ri kelmaydi")
        else:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🧒 {name} ({grade}-sinf)",
                        callback_data=f"olymp_child:{olympiad_id}:{c.id}",
                    )
                ]
            )

    buttons.append(
        [InlineKeyboardButton(text="➕ Farzand qo'shish", callback_data="child_add")]
    )

    grades_txt = (
        "\n📚 Qatnashadigan sinflar: " + ", ".join(f"{g}-sinf" for g in allowed)
        if allowed
        else ""
    )
    notes_txt = "\n\n" + "\n".join(notes) if notes else ""
    head = (
        "Qaysi farzandingizni yozdiramiz?"
        if buttons[:-1]
        else "Bu olimpiadaga yozdirish mumkin bo'lgan farzand topilmadi."
    )

    await message.answer(
        f"🏆 **{olympiad_name}**{grades_txt}\n\n{head}{notes_txt}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("olymp_more:"))
async def olymp_register_more(callback: CallbackQuery, state: FSMContext):
    """"Yana farzandni yozdirish" — ro'yxatni qaytadan ko'rsatadi."""
    olympiad_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        olympiad = await session.get(Olympiad, olympiad_id)
        if not olympiad or not olympiad.is_active:
            await callback.answer(
                "Bu olimpiadaga ro'yxatdan o'tish muddati tugagan.", show_alert=True
            )
            return
        allowed = await _allowed_grades(session, olympiad_id)
        name = olympiad.name

    await callback.answer()
    await _start_child_registration(callback.message, state, olympiad_id, name, allowed)


@router.callback_query(F.data.startswith("olymp_child:"))
async def olymp_pick_child(callback: CallbackQuery, state: FSMContext):
    """Farzand tanlandi — endi faqat sinf rahbari so'raladi."""
    _, olympiad_id_raw, child_id_raw = callback.data.split(":")
    olympiad_id, child_id = int(olympiad_id_raw), int(child_id_raw)
    chat_id = callback.message.chat.id

    async with async_session() as session:
        child = await session.get(Child, child_id)
        if not child or child.user_id != chat_id or child.archived_at:
            await callback.answer("Farzand topilmadi.", show_alert=True)
            return

        olympiad = await session.get(Olympiad, olympiad_id)
        if not olympiad or not olympiad.is_active:
            await callback.answer(
                "Bu olimpiadaga ro'yxatdan o'tish muddati tugagan.", show_alert=True
            )
            return

        allowed = await _allowed_grades(session, olympiad_id)
        grade = current_grade(child.grade, child.grade_year)
        if allowed and grade not in allowed:
            await callback.answer(
                f"{grade}-sinf bu olimpiadada qatnashmaydi.", show_alert=True
            )
            return

        already = (
            await session.execute(
                select(OlympiadResult.id).where(
                    OlympiadResult.olympiad_id == olympiad_id,
                    OlympiadResult.child_id == child_id,
                )
            )
        ).scalar_one_or_none()
        if already:
            await callback.answer(
                "Bu farzand allaqachon ro'yxatdan o'tgan.", show_alert=True
            )
            return

        name = f"{child.last_name} {child.first_name}"
        olympiad_name = olympiad.name

    await state.update_data(
        pending_olympiad_id=olympiad_id,
        pending_olympiad_name=olympiad_name,
        pending_child_id=child_id,
    )
    await state.set_state(OlympiadChildStates.waiting_for_teacher_name)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"🧒 **{name}** ({grade}-sinf)\n\n"
        f"Sinf rahbarining ism va familiyasini kiriting "
        f"(Masalan: Otabekov Sardor):",
        parse_mode="Markdown",
        reply_markup=get_olympiad_cancel_keyboard(),
    )


@router.message(OlympiadChildStates.waiting_for_teacher_name)
async def olymp_child_teacher(message: Message, state: FSMContext, bot: Bot):
    if await _olymp_cancelled(message, state):
        return

    teacher_name = (message.text or "").strip()
    parts = teacher_name.split()
    if len(parts) < 2 or len(parts[0]) < 3 or len(parts[1]) < 3:
        await message.answer(
            "Iltimos, sinf rahbarining ism va familiyasini to'liq kiriting "
            "(kamida 2 ta so'z):"
        )
        return
    if len(teacher_name) > MAX_TEACHER_LEN:
        await message.answer(
            f"Sinf rahbarining ismi juda uzun ({len(teacher_name)} belgi). "
            f"Iltimos, {MAX_TEACHER_LEN} belgidan oshmasin:"
        )
        return

    data = await state.get_data()
    olympiad_id = data.get("pending_olympiad_id")
    olympiad_name = data.get("pending_olympiad_name", "Olimpiada")
    child_id = data.get("pending_child_id")
    chat_id = message.chat.id

    try:
        async with async_session() as session:
            user = await session.get(User, chat_id)
            if not user:
                await message.answer(
                    "Avval ro'yxatdan o'ting: /start",
                    reply_markup=get_main_keyboard(),
                )
                await state.clear()
                return

            child = await session.get(Child, child_id)
            if not child or child.user_id != chat_id or child.archived_at:
                await message.answer(
                    "Farzand topilmadi. Ro'yxatni qaytadan oching.",
                    reply_markup=get_main_keyboard(),
                )
                await state.clear()
                return

            olympiad = await session.get(Olympiad, olympiad_id)
            if not olympiad or not olympiad.is_active:
                await message.answer(
                    "Bu olimpiadaga ro'yxatdan o'tish muddati tugagan.",
                    reply_markup=get_main_keyboard(),
                )
                await state.clear()
                return

            # Savolga javob berilayotgan payt boshqa oynadan yozilgan bo'lishi
            # mumkin — unda yangi ID BERILMAYDI, mavjud ruxsatnoma qaytariladi.
            existing = (
                await session.execute(
                    select(OlympiadResult).where(
                        OlympiadResult.olympiad_id == olympiad_id,
                        OlympiadResult.child_id == child_id,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                await message.answer(
                    f"**{child.last_name} {child.first_name}** allaqachon "
                    f"**{olympiad_name}** ga ro'yxatdan o'tgan.",
                    parse_mode="Markdown",
                    reply_markup=get_main_keyboard(),
                )
                await state.clear()
                if existing.ticket_no:
                    await _send_ticket(
                        bot,
                        chat_id,
                        existing.last_name or child.last_name,
                        existing.first_name or child.first_name,
                        existing.ticket_no,
                        user.phone,
                        olympiad.name,
                    )
                return

            grade = current_grade(child.grade, child.grade_year)
            first_name, last_name = child.first_name, child.last_name
            new_result = OlympiadResult(
                olympiad_id=olympiad_id,
                user_id=chat_id,
                child_id=child_id,
                full_name=f"{first_name} {last_name}",
                first_name=first_name,
                last_name=last_name,
                birth_date=child.birth_date,
                school=child.school,
                # Sinf yozilish PAYTIDA nusxalanadi: keyin farzandning sinfi
                # oshsa ham, shu olimpiadadagi natija o'z sinfida qoladi.
                grade=grade,
                teacher_name=teacher_name,
            )
            session.add(new_result)
            # OlympiadResult.id ticket_no uchun kerak — commit qilmasdan
            # turib flush bilan olamiz.
            await session.flush()
            ticket_no = build_ticket_no(
                datetime.utcnow().year, olympiad.code or "GEN", new_result.id
            )
            new_result.ticket_no = ticket_no
            await session.commit()
            phone = user.phone
            event_title = olympiad.name
            school_txt = child.school or "-"
    except Exception as e:
        logger.error(f"Olimpiadaga yozishda xato (chat_id={chat_id}): {e}")
        await message.answer(
            "Kechirasiz, ro'yxatdan o'tkazishda xatolik yuz berdi. "
            "Iltimos, qaytadan urinib ko'ring.",
            reply_markup=get_main_keyboard(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ **{olympiad_name}** ga muvaffaqiyatli ro'yxatdan o'tdingiz!\n\n"
        f"\U0001f464 {first_name} {last_name}\n"
        f"\U0001f3eb {school_txt}\n"
        f"\U0001f4da {grade}-sinf\n"
        f"\U0001f468‍\U0001f3eb {teacher_name}\n\n"
        f"Ruxsatnoma hozir yuboriladi. Natijalar tayyor bo'lgach, "
        f"\"\U0001f3c5 Natijalarim\" bo'limida ko'rinadi.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )

    await _send_ticket(bot, chat_id, last_name, first_name, ticket_no, phone, event_title)

    await message.answer(
        "Boshqa farzandingizni ham shu olimpiadaga yozdirasizmi?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="➕ Yana farzandni yozdirish",
                        callback_data=f"olymp_more:{olympiad_id}",
                    )
                ]
            ]
        ),
    )


async def _send_ticket(
    bot: Bot,
    chat_id: int,
    last_name: str,
    first_name: str,
    ticket_no: str,
    phone: str,
    event_title: str,
) -> None:
    """Ruxsatnomani generatsiya qilib PNG (answer_photo) va PDF
    (answer_document) sifatida yuboradi.

    Hech narsa diskka yozilmaydi -- generate_ticket() baytlarni qaytaradi,
    ular BufferedInputFile orqali to'g'ridan-to'g'ri Telegramga yuboriladi.

    Xato bo'lsa: foydalanuvchiga tushunarli xabar, logga to'liq traceback,
    superadminlarga bildirishnoma -- hech qanday `except: pass` yo'q.
    """
    ctx = TicketContext(
        familiya=last_name,
        ism=first_name,
        ticket_no=ticket_no,
        phone=phone,
        event_title=event_title,
    )
    try:
        pdf_bytes, png_bytes = await generate_ticket(ctx)
    except TicketGenerationError as e:
        logger.exception(f"Ruxsatnoma generatsiyasida xato (chat_id={chat_id}): {e}")
        await bot.send_message(
            chat_id,
            "❌ Ruxsatnomangizni tayyorlashda texnik xatolik yuz berdi.\n"
            "Administratorga xabar berildi. Birozdan so'ng qaytadan urinib "
            "ko'ring — olimpiada sahifasidagi \"🎫 Ruxsatnomani olish\" "
            "tugmasidan.",
        )
        await notify_superadmins(
            bot,
            f"⚠️ Ruxsatnoma generatsiyasi ishlamadi.\n"
            f"chat_id: {chat_id}\nticket_no: {ticket_no}\nXato: {e}",
        )
        return

    await bot.send_photo(
        chat_id,
        BufferedInputFile(png_bytes, filename=f"{ticket_no}.png"),
        caption=f"🎫 **{event_title}**\n\nRuxsatnomangiz tayyor!",
        parse_mode="Markdown",
    )
    await bot.send_document(
        chat_id,
        BufferedInputFile(pdf_bytes, filename=f"{ticket_no}.pdf"),
        caption="Chop etish uchun — siqilmagan PDF nusxa.",
    )


@router.message(F.text == "🏆 Olimpiadalar")
async def show_olympiads(message: Message, bot: Bot):
    if not await require_subscription(message, bot):
        return
    chat_id = message.chat.id
    async with async_session() as session:
        user_res = await session.execute(select(User).where(User.id == chat_id))
        user = user_res.scalar_one_or_none()

        if not user:
            await message.answer("Siz ro'yxatdan o'tmagansiz. Qaytadan /start bosing.")
            return

        # Hozirda faol (ro'yxatdan o'tish mumkin bo'lgan) olimpiadalar
        active_res = await session.execute(
            select(Olympiad)
            .where(Olympiad.is_active.is_(True))
            .order_by(Olympiad.exam_date.asc().nullslast(), Olympiad.id.desc())
        )
        active_olympiads = active_res.scalars().all()

        # Foydalanuvchining barcha olimpiadalardagi (shu jumladan tugagan)
        # natijalari. Bitta olimpiadada bir nechta farzand bo'lishi mumkin,
        # shuning uchun olimpiada bo'yicha RO'YXAT yig'iladi.
        my_res = await session.execute(
            select(OlympiadResult, Olympiad)
            .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
            .where(OlympiadResult.user_id == chat_id)
        )
        my_rows = my_res.all()
        my_by_olympiad: dict[int, list[OlympiadResult]] = {}
        for r, o in my_rows:
            my_by_olympiad.setdefault(o.id, []).append(r)

        if not active_olympiads and not my_rows:
            await message.answer(
                "Hozirda faol olimpiadalar mavjud emas. Tez orada e'lon qilinadi! 🎓"
            )
            return

        def _label(name: str, mine: list[OlympiadResult]) -> str:
            if not mine:
                return f"🆕 {name}"
            icon = "✅" if all(r.score is not None for r in mine) else "⏳"
            suffix = f" ({len(mine)} ta)" if len(mine) > 1 else ""
            return f"{icon} {name}{suffix}"

        buttons = []
        shown_ids = set()

        for o in active_olympiads:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=_label(o.name, my_by_olympiad.get(o.id, [])),
                        callback_data=f"olymp_open:{o.id}",
                    )
                ]
            )
            shown_ids.add(o.id)

        # Faol ro'yxatda yo'q (masalan, tugagan), lekin foydalanuvchi
        # ishtirok etgan olimpiadalar
        for r, o in my_rows:
            if o.id in shown_ids:
                continue
            shown_ids.add(o.id)
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=_label(o.name, my_by_olympiad[o.id]),
                        callback_data=f"olymp_open:{o.id}",
                    )
                ]
            )

        await message.answer(
            "🏆 **Olimpiadalar**\n\n"
            "🆕 — ro'yxatdan o'tishingiz mumkin\n"
            "⏳ — ro'yxatdan o'tgansiz, natija hali kutilmoqda\n"
            "✅ — natijangiz tayyor\n\n"
            "Batafsil ma'lumot uchun olimpiadani tanlang:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )


@router.callback_query(F.data.startswith("olymp_open:"))
async def open_olympiad(callback: CallbackQuery, state: FSMContext):
    """Olimpiada tugmasi bosilganda: hech kim yozilmagan bo'lsa farzandlar
    ro'yxatini beradi, yozilgan bo'lsa har bir farzandning holatini ko'rsatadi.

    Baza sessiyasi qisqa tutiladi — kerakli qiymatlar oddiy o'zgaruvchilarga
    olinadi va sessiya darhol yopiladi, Telegramga javob esa undan keyin
    yuboriladi. Shunda ulanish tarmoq kutish paytida band bo'lib turmaydi.
    """
    chat_id = callback.from_user.id
    olympiad_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        olympiad = await session.get(Olympiad, olympiad_id)
        if olympiad is None:
            await callback.answer("Bu olimpiada topilmadi.", show_alert=True)
            return

        user_exists = (
            await session.execute(select(User.id).where(User.id == chat_id))
        ).scalar_one_or_none() is not None

        mine = list(
            (
                await session.execute(
                    select(OlympiadResult)
                    .where(
                        OlympiadResult.olympiad_id == olympiad_id,
                        OlympiadResult.user_id == chat_id,
                    )
                    .order_by(OlympiadResult.id)
                )
            )
            .scalars()
            .all()
        )

        allowed_grades = await _allowed_grades(session, olympiad_id)
        name, is_active = olympiad.name, olympiad.is_active

    if not user_exists:
        await callback.answer("Avval ro'yxatdan o'ting (/start).", show_alert=True)
        return

    if not mine:
        if not is_active:
            await callback.answer(
                "Bu olimpiadaga ro'yxatdan o'tish muddati tugagan.", show_alert=True
            )
            return
        # Darhol yozmaymiz — avval qaysi farzand ekanini so'raymiz.
        await callback.answer()
        await _start_child_registration(
            callback.message, state, olympiad_id, name, allowed_grades
        )
        return

    lines, buttons = [], []
    for r in mine:
        who = f"{r.last_name or ''} {r.first_name or ''}".strip() or (r.full_name or "-")
        sinf = f" ({r.grade}-sinf)" if r.grade is not None else ""
        if r.score is None:
            holat = "⏳ natija kutilmoqda"
        else:
            place_txt = f", {r.place}-o'rin" if r.place else ""
            holat = f"✅ {fmt_number(r.score)} ball{place_txt}"
        lines.append(f"🧒 **{who}**{sinf} — {holat}")
        if r.ticket_no:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🎫 Ruxsatnoma — {r.first_name or who}",
                        callback_data=f"ticket_one:{r.id}",
                    )
                ]
            )

    if is_active:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="➕ Yana farzandni yozdirish",
                    callback_data=f"olymp_more:{olympiad_id}",
                )
            ]
        )

    await callback.answer()
    await callback.message.answer(
        f"🏆 **{name}**\n\n" + "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("ticket_one:"))
async def resend_one_ticket(callback: CallbackQuery, bot: Bot):
    """Bitta farzandning ruxsatnomasini qayta yuboradi."""
    chat_id = callback.from_user.id
    result_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        row = (
            await session.execute(
                select(OlympiadResult, Olympiad, User)
                .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
                .join(User, OlympiadResult.user_id == User.id)
                .where(
                    OlympiadResult.id == result_id,
                    OlympiadResult.user_id == chat_id,
                )
            )
        ).first()

    if not row:
        await callback.answer("Ruxsatnoma topilmadi.", show_alert=True)
        return

    await callback.answer("Ruxsatnoma tayyorlanmoqda...")
    await _send_result_ticket(bot, chat_id, *row)


@router.callback_query(F.data.startswith("ticket_get:"))
async def resend_ticket(callback: CallbackQuery, bot: Bot):
    """Olimpiada bo'yicha ruxsatnomalarni qayta yuboradi.

    ticket_no o'zgarmagani uchun natija xuddi birinchi safargidek bo'ladi.
    Bir nechta farzand yozilgan bo'lsa — har biriga alohida ruxsatnoma.
    """
    chat_id = callback.from_user.id
    olympiad_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        rows = (
            await session.execute(
                select(OlympiadResult, Olympiad, User)
                .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
                .join(User, OlympiadResult.user_id == User.id)
                .where(
                    OlympiadResult.olympiad_id == olympiad_id,
                    OlympiadResult.user_id == chat_id,
                )
                .order_by(OlympiadResult.id)
            )
        ).all()

    if not rows:
        await callback.answer("Bu olimpiadaga ro'yxatdan o'tmagansiz.", show_alert=True)
        return

    await callback.answer("Ruxsatnoma tayyorlanmoqda...")
    for result, olympiad, user in rows:
        await _send_result_ticket(bot, chat_id, result, olympiad, user)


async def _send_result_ticket(bot: Bot, chat_id: int, result, olympiad, user) -> None:
    """Bitta OlympiadResult uchun ruxsatnomani yuboradi."""
    if not result.ticket_no:
        # Amalda bo'lmasligi kerak — init_db() backfill orqali hammasini
        # to'ldiradi. Ehtiyot chorasi sifatida qoldirilgan.
        await bot.send_message(
            chat_id, "Ruxsatnoma topilmadi. Administratorga murojaat qiling."
        )
        return

    if result.first_name and result.last_name:
        first_name, last_name = result.first_name, result.last_name
    else:
        first_name, last_name = split_full_name(result.full_name or user.full_name)

    await _send_ticket(
        bot, chat_id, last_name, first_name, result.ticket_no, user.phone, olympiad.name
    )


# --- NATIJALARIM VA SERTIFIKAT ---


@router.message(F.text == "🏅 Natijalarim")
async def show_my_results(message: Message, bot: Bot):
    if not await require_subscription(message, bot):
        return
    chat_id = message.chat.id
    async with async_session() as session:
        res = await session.execute(
            select(OlympiadResult, Olympiad)
            .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
            .where(
                OlympiadResult.user_id == chat_id,
                OlympiadResult.score.isnot(None),
            )
            .order_by(OlympiadResult.checked_at.desc())
        )
        rows = res.all()

    if not rows:
        await message.answer(
            "Sizda hali natijasi e'lon qilingan olimpiada yo'q.\n\n"
            "Ishtirok etgan olimpiadangiz natijasi e'lon qilinishi bilan "
            "shu bo'lim orqali (🏅 Natijalarim) ko'rishingiz mumkin bo'ladi."
        )
        return

    # Bitta olimpiadada bir nechta farzand bo'lishi mumkin — tugmada
    # ishtirokchining ismi ham ko'rsatiladi, aks holda qatorlar bir xil
    # ko'rinib qolardi.
    buttons = [
        [
            InlineKeyboardButton(
                text=f"🏆 {o.name} — {r.first_name or r.full_name or '-'}",
                callback_data=f"myres_open:{r.id}",
            )
        ]
        for r, o in rows
    ]
    await message.answer(
        "🏅 **Natijalari e'lon qilingan olimpiadalar:**\n\n"
        "Batafsil ma'lumot va sertifikat olish uchun olimpiadani tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("myres_open:"))
async def open_my_result(callback: CallbackQuery):
    chat_id = callback.from_user.id
    result_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        res = await session.execute(
            select(OlympiadResult, Olympiad)
            .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
            .where(
                OlympiadResult.id == result_id,
                OlympiadResult.user_id == chat_id,
            )
        )
        row = res.first()

    if not row or row[0].score is None:
        await callback.answer("Bu natija topilmadi.", show_alert=True)
        return

    r, o = row
    await callback.answer()
    await callback.message.answer(
        f"🏆 **{o.name}**\n\nQuyidagilardan birini tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📝 Natijani matn ko'rinishida ko'rish",
                        callback_data=f"myres_text:{result_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🎓 Sertifikatni olish",
                        callback_data=f"myres_cert:{result_id}",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("myres_text:"))
async def show_my_result_text(callback: CallbackQuery):
    chat_id = callback.from_user.id
    result_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        res = await session.execute(
            select(OlympiadResult, Olympiad)
            .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
            .where(
                OlympiadResult.id == result_id,
                OlympiadResult.user_id == chat_id,
            )
        )
        row = res.first()

    if not row or row[0].score is None:
        await callback.answer("Bu natija topilmadi.", show_alert=True)
        return

    r, o = row
    await callback.answer()

    math_txt = (
        f"{r.math_correct}/{r.math_total}"
        if r.math_correct is not None and r.math_total is not None
        else "Aniqlanmagan"
    )
    eng_txt = (
        f"{r.english_correct}/{r.english_total}"
        if r.english_correct is not None and r.english_total is not None
        else "Aniqlanmagan"
    )

    # Excel/PDF'dan fan-oraliqlari bo'yicha to'liq tafsilot saqlangan bo'lsa
    # (masalan 1-12-savollar va 13-30-savollar alohida ball bergan bo'lsa),
    # shularni ham qatorma-qator ko'rsatamiz.
    detail = None
    if r.detail:
        try:
            detail = json.loads(r.detail)
        except (TypeError, ValueError):
            detail = None

    def _subject_detail_txt(items) -> str:
        if not items:
            return ""
        lines = []
        for it in items:
            correct, total, score = it.get("correct"), it.get("total"), it.get("score")
            bits = []
            if correct is not None and total is not None:
                bits.append(f"{int(correct)}/{int(total)} to'g'ri")
            if score is not None:
                bits.append(f"{fmt_number(score)} ball")
            lines.append(f"\n   • {it.get('range', '?')}-savollar: " + ", ".join(bits))
        return "".join(lines)

    math_txt += _subject_detail_txt(detail.get("matematika")) if detail else ""
    eng_txt += _subject_detail_txt(detail.get("ingliz_tili")) if detail else ""

    if r.math_total is not None and r.english_total is not None:
        total_questions = r.math_total + r.english_total
        total_correct = (r.math_correct or 0) + (r.english_correct or 0)
        percent_txt = (
            f"{(total_correct / total_questions * 100):.1f}%"
            if total_questions > 0
            else "-"
        )
        total_txt = f"{total_correct}/{total_questions}"
    else:
        percent_txt = "Aniqlanmagan"
        total_txt = fmt_number(r.score)

    place_txt = f"{r.place}-o'rin" if r.place else "Hisoblanmoqda..."

    # O'rin shu sinf ichida hisoblangani uchun sinfni ham ko'rsatamiz
    sinf_txt = f"\n📚 Sinf: {r.grade}-sinf" if r.grade is not None else ""
    sana_txt = f"\n📅 Sana: {o.exam_date.strftime('%d.%m.%Y')}" if o.exam_date else ""
    txt = (
        f"🏆 **{o.name}**{sinf_txt}\n\n"
        f"🔢 Matematika: {math_txt}\n"
        f"🇬🇧 Ingliz tili: {eng_txt}\n"
        f"📈 Umumiy natija: {total_txt}\n"
        f"📊 Foiz: {percent_txt}\n"
        f"🏅 O'rin: {place_txt}"
        + (f" ({r.grade}-sinf bo'yicha)" if r.grade is not None else "")
        + sana_txt
    )
    await callback.message.answer(txt, parse_mode="Markdown")


@router.callback_query(F.data.startswith("myres_cert:"))
async def send_my_certificate(callback: CallbackQuery):
    chat_id = callback.from_user.id
    result_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        res = await session.execute(
            select(OlympiadResult, Olympiad, User)
            .join(Olympiad, OlympiadResult.olympiad_id == Olympiad.id)
            .join(User, OlympiadResult.user_id == User.id)
            .where(
                OlympiadResult.id == result_id,
                OlympiadResult.user_id == chat_id,
            )
        )
        row = res.first()

    if not row or row[0].score is None:
        await callback.answer("Bu natija topilmadi.", show_alert=True)
        return

    r, o, user = row
    await callback.answer("Sertifikat tayyorlanmoqda...")

    full_name = r.full_name or user.full_name

    if r.math_total is not None and r.english_total is not None:
        score_text = f"{fmt_number(r.score)}/{r.math_total + r.english_total}"
    else:
        score_text = fmt_number(r.score)

    place_text = f"{r.place}-o'rin" if r.place else "-"
    date_text = datetime.now().strftime("%d.%m.%Y")

    cert_path = f"temp_cert_{chat_id}_{result_id}.jpg"
    try:
        generate_certificate(
            full_name=full_name,
            olympiad_name=o.name,
            score_text=score_text,
            place_text=place_text,
            date_text=date_text,
            output_path=cert_path,
        )
        cert_file = FSInputFile(cert_path)
        await callback.message.answer_document(
            cert_file,
            caption=f"🎓 **{o.name}**\n\nTabriklaymiz, {full_name}!",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Sertifikat generatsiyasida xato: {e}")
        await callback.message.answer(
            "❌ Sertifikatni tayyorlashda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring."
        )
    finally:
        if os.path.exists(cert_path):
            os.remove(cert_path)


def get_edit_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Ism Familiyani o'zgartirish",
                    callback_data="edit_user_field:full_name",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📱 Telefon raqamni o'zgartirish",
                    callback_data="edit_user_field:phone",
                ),
            ],
            # Maktab bu yerda tahrirlanmaydi — u endi olimpiadaga
            # yozilishda so'raladi va o'sha yozuvda saqlanadi.
            [
                InlineKeyboardButton(
                    text="📅 Tug'ilgan sanani o'zgartirish",
                    callback_data="edit_user_field:birth_date",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data="edit_user_field:cancel"
                )
            ],
        ]
    )


@router.message(F.text == "ℹ️ Malumotlarim")
async def show_profile(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("Siz ro'yxatdan o'tmagansiz. Qaytadan start bosing.")
            return

        txt = (
            "ℹ️ **Sizning ma'lumotlaringiz:**\n\n"
            f"👤 **Ism Familiya:** {user.full_name}\n"
            f"📱 **Telefon:** {user.phone}\n"
            f"📅 **Tug'ilgan sana:** {user.birth_date.strftime('%Y-%m-%d') if user.birth_date else 'Kiritilmagan'}\n"
            f"🆔 **Telegram ID:** `{user.id}`"
        )
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Ma'lumotlarni tahrirlash",
                        callback_data="edit_profile_menu",
                    )
                ]
            ]
        )
        await message.answer(txt, parse_mode="Markdown", reply_markup=inline_kb)


@router.callback_query(F.data == "edit_profile_menu")
async def edit_profile_menu_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "Qaysi ma'lumotni tahrirlamoqchisiz?", reply_markup=get_edit_profile_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_user_field:"))
async def edit_user_field_handler(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]

    if field == "cancel":
        await callback.message.edit_text("Tahrirlash bekor qilindi.")
        await callback.answer()
        return

    await state.update_data(edit_field=field)
    await state.set_state(EditProfileStates.waiting_for_new_value)

    field_prompts = {
        "full_name": "Iltimos, yangi ism va familiyangizni kiriting (Masalan: Ali Valiyev):",
        "phone": "Iltimos, yangi telefon raqamingizni kiriting (Masalan: +998901234567):",
        "school": "Iltimos, yangi maktabingiz yoki o'quv markazingiz nomini kiriting:",
        "birth_date": "Iltimos, yangi tug'ilgan sanangizni kiriting (Masalan: 2008-05-15, 15.05.2008 yoki 2008-yil 15-may):",
    }

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish", callback_data="cancel_edit_profile"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        field_prompts.get(field, "Yangi qiymatni kiriting:"), reply_markup=cancel_kb
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_edit_profile")
async def cancel_edit_profile_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Tahrirlash bekor qilindi.")
    await callback.answer()


@router.message(EditProfileStates.waiting_for_new_value)
async def process_new_profile_value(message: Message, state: FSMContext):
    new_val = message.text

    if new_val == "❌ Bekor qilish" or (
        new_val and new_val.lower() in ["/cancel", "cancel", "bekor qilish"]
    ):
        await state.clear()
        await message.answer(
            "Tahrirlash bekor qilindi.", reply_markup=get_main_keyboard()
        )
        return

    data = await state.get_data()
    field = data.get("edit_field")

    if not new_val:
        await message.answer(
            "Qiymat matn ko'rinishida bo'lishi kerak. Iltimos, qaytadan kiriting:"
        )
        return

    # Validatsiyalar
    parsed_birthdate = None
    if field == "full_name":
        if len(new_val) > MAX_NAME_LEN:
            await message.answer(
                f"Juda uzun ({len(new_val)} belgi). {MAX_NAME_LEN} belgidan oshmasin:"
            )
            return
        if len(new_val.split()) < 2:
            await message.answer(
                "Iltimos, ism va familiyangizni to'liq kiriting (kamida 2 ta so'z):"
            )
            return
    elif field == "phone":
        normalized = normalize_phone(new_val)
        if not normalized:
            await message.answer(
                "Telefon raqami tushunarsiz. Iltimos, to'liq yozing "
                "(masalan: +998901234567):"
            )
            return
        new_val = normalized
    elif field == "school":
        if len(new_val) > MAX_SCHOOL_LEN:
            await message.answer(
                f"Maktab nomi juda uzun ({len(new_val)} belgi). "
                f"{MAX_SCHOOL_LEN} belgidan oshmasin:"
            )
            return
        # Shablon namuna sifatida ko'rsatiladi, lekin har qanday nom qabul qilinadi
        if len(new_val.strip()) < 2:
            await message.answer(
                "Maktab nomi juda qisqa. Iltimos, to'liqroq kiriting.\n\n"
                "Masalan:\n"
                "• 12-maktab\n"
                "• 15-sonli maktab\n"
                "• Prezident maktabi\n"
                "• 44-IDUM"
            )
            return
    elif field == "birth_date":
        parsed_birthdate = parse_flexible_date(new_val)
        if not parsed_birthdate:
            await message.answer(
                "Sana formati tushunilmadi. Iltimos, qaytadan kiriting\n"
                "(Masalan: 2008-05-15, 15.05.2008, 2008yil 15-may yoki 2008 05 15):"
            )
            return

    # DB ga saqlash
    chat_id = message.chat.id
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == chat_id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("Foydalanuvchi topilmadi. Qaytadan start bosing.")
            await state.clear()
            return

        if field == "full_name":
            user.full_name = new_val
        elif field == "phone":
            user.phone = new_val
        elif field == "school":
            user.school = new_val
        elif field == "birth_date":
            user.birth_date = parsed_birthdate

        await session.commit()

    await message.answer(
        "Ma'lumotlaringiz muvaffaqiyatli o'zgartirildi! 🎉",
        reply_markup=get_main_keyboard(),
    )
    await state.clear()


# ============================================================================
# ONLINE TEST ISHLASH
# ============================================================================


def parse_student_answers(raw: str) -> tuple[list[str] | None, str | None]:
    """O'quvchining javoblarini o'qiydi: (javoblar, xato_matni).

    normalize_answers() dan farqi shundaki, bu yerda A-E dan tashqari belgi
    JIMGINA TASHLANMAYDI. Aks holda o'quvchi bitta noto'g'ri harf yozsa,
    qolgan javoblari bir pozitsiyaga siljib, ball xato hisoblanardi.
    """
    if not raw:
        return None, "Javob bo'sh."

    cleaned = raw.upper()
    for ch in (",", ".", ";", ":", "-", "/", "|", " ", "\t", "\n", "\r"):
        cleaned = cleaned.replace(ch, "")

    if not cleaned:
        return None, "Javob topilmadi."

    bad = sorted({c for c in cleaned if c not in "ABCDE"})
    if bad:
        belgilar = ", ".join(f"«{c}»" for c in bad[:5])
        return None, f"Faqat A, B, C, D, E harflari mumkin. Xato belgi: {belgilar}"

    return list(cleaned), None


class OnlineTestStates(StatesGroup):
    waiting_for_test_id = State()
    waiting_for_answers = State()


@router.message(F.text == "🧩 Online test")
async def online_test_start(message: Message, state: FSMContext, bot: Bot):
    if not await require_subscription(message, bot):
        return

    async with async_session() as session:
        exists = (
            await session.execute(select(User.id).where(User.id == message.chat.id))
        ).scalar_one_or_none()
    if exists is None:
        await message.answer("Siz ro'yxatdan o'tmagansiz. /start bosing.")
        return

    await message.answer(
        "🧩 **Online test**\n\n"
        "Test raqamini kiriting (o'qituvchingiz aytgan raqam).\n\n"
        "Masalan: 101",
        parse_mode="Markdown",
        reply_markup=get_olympiad_cancel_keyboard(),
    )
    await state.set_state(OnlineTestStates.waiting_for_test_id)


@router.message(OnlineTestStates.waiting_for_test_id)
async def online_test_receive_id(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return

    raw = (message.text or "").strip().lstrip("#")
    if not raw.isdigit():
        await message.answer(
            "Test raqami faqat sonlardan iborat bo'ladi. Qayta kiriting "
            "(Masalan: 101):",
            reply_markup=get_olympiad_cancel_keyboard(),
        )
        return

    test_id = int(raw)
    chat_id = message.chat.id

    async with async_session() as session:
        test = (
            await session.execute(
                select(OnlineTest).where(
                    OnlineTest.id == test_id, OnlineTest.archived.is_(False)
                )
            )
        ).scalar_one_or_none()

        previous = None
        if test is not None:
            previous = (
                await session.execute(
                    select(OnlineTestResult).where(
                        OnlineTestResult.online_test_id == test_id,
                        OnlineTestResult.user_id == chat_id,
                    )
                )
            ).scalar_one_or_none()

    if test is None:
        await message.answer(
            f"#{test_id} raqamli test topilmadi.\n"
            f"Raqamni tekshirib, qaytadan kiriting:",
            reply_markup=get_olympiad_cancel_keyboard(),
        )
        return

    # Imtihon tartibi: har test bir marta ishlanadi
    if previous is not None:
        percent = previous.correct / previous.total * 100 if previous.total else 0
        await state.clear()
        await message.answer(
            f"ℹ️ Siz **#{test_id}** testini allaqachon ishlagansiz.\n\n"
            f"🔢 Natijangiz: **{previous.correct}/{previous.total}** "
            f"({percent:.0f}%)\n"
            f"📅 {previous.checked_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Bu testni qayta ishlab bo'lmaydi.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    total = len(test.answers.split(","))
    await state.update_data(online_test_id=test_id, total=total)

    # Rasm ixtiyoriy: savollar kanaldagi e'londa, bu yerda faqat muqova
    # bo'lishi mumkin (DECISIONS.md #46). Eski testlarda esa bu — savollar
    # rasmi, shuning uchun qanday yuborilgan bo'lsa shunday qaytariladi
    # (fayl ko'rinishidagi rasm siqilmaydi va mayda matn o'qiladi).
    caption = f"🧩 Test #{test_id} — {total} ta savol"
    if test.image_file_id:
        try:
            if test.file_type == "document":
                await message.answer_document(test.image_file_id, caption=caption)
            else:
                await message.answer_photo(test.image_file_id, caption=caption)
        except TelegramAPIError as e:
            # Rasm yuborilmasa ham test ishlanaveradi — u faqat muqova.
            logger.warning(f"Online test #{test_id} rasmi yuborilmadi: {e}")
            await message.answer(caption)
    else:
        await message.answer(caption)

    example = "".join("ABCDE"[i % 5] for i in range(min(total, 8)))
    await message.answer(
        f"📝 Testni ishlab, javoblaringizni **bitta xabarda** yuboring.\n\n"
        f"Javoblar soni: **{total} ta**\n\n"
        f"Quyidagi ko'rinishda yozing:\n"
        f"`{example}{'...' if total > 8 else ''}`\n\n"
        f"yoki vergul bilan:\n"
        f"`{','.join(example)}{'...' if total > 8 else ''}`\n\n"
        f"(faqat A, B, C, D, E harflari)",
        parse_mode="Markdown",
        reply_markup=get_olympiad_cancel_keyboard(),
    )
    await state.set_state(OnlineTestStates.waiting_for_answers)


@router.message(OnlineTestStates.waiting_for_answers)
async def online_test_receive_answers(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return

    data = await state.get_data()
    test_id = data.get("online_test_id")
    total = data.get("total", 0)

    given_list, err = parse_student_answers(message.text)
    if err:
        await message.answer(
            f"❗️ {err}\n\nQaytadan yuboring:",
            reply_markup=get_olympiad_cancel_keyboard(),
        )
        return

    given = ",".join(given_list)
    if len(given_list) != total:
        await message.answer(
            f"❗️ Javoblar soni mos kelmadi.\n\n"
            f"Kutilgan: **{total} ta**\n"
            f"Siz yubordingiz: **{len(given_list)} ta**\n\n"
            f"Iltimos, {total} ta javob yuboring:",
            parse_mode="Markdown",
            reply_markup=get_olympiad_cancel_keyboard(),
        )
        return

    chat_id = message.chat.id
    try:
        async with async_session() as session:
            test = (
                await session.execute(
                    select(OnlineTest).where(OnlineTest.id == test_id)
                )
            ).scalar_one_or_none()
            if test is None:
                await message.answer(
                    "Test topilmadi — ehtimol o'chirilgan.",
                    reply_markup=get_main_keyboard(),
                )
                await state.clear()
                return

            key_list = test.answers.split(",")
            correct = sum(1 for g, k in zip(given_list, key_list) if g == k)

            # Javob yuborayotgan payt boshqa oynadan yuborilgan bo'lishi mumkin
            already = (
                await session.execute(
                    select(OnlineTestResult.id).where(
                        OnlineTestResult.online_test_id == test_id,
                        OnlineTestResult.user_id == chat_id,
                    )
                )
            ).scalar_one_or_none()
            if already is not None:
                await message.answer(
                    "Siz bu testni allaqachon topshirgansiz.",
                    reply_markup=get_main_keyboard(),
                )
                await state.clear()
                return

            session.add(
                OnlineTestResult(
                    online_test_id=test_id,
                    user_id=chat_id,
                    given_answers=given,
                    correct=correct,
                    total=len(key_list),
                )
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Online test natijasini saqlashda xato (chat={chat_id}): {e}")
        await message.answer(
            "Natijani saqlashda xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=get_main_keyboard(),
        )
        await state.clear()
        return

    await state.clear()

    percent = correct / len(key_list) * 100 if key_list else 0
    if percent >= 90:
        baho, emoji = "A'lo", "🏆"
    elif percent >= 70:
        baho, emoji = "Yaxshi", "👍"
    elif percent >= 50:
        baho, emoji = "Qoniqarli", "🙂"
    else:
        baho, emoji = "Yana harakat qiling", "💪"

    # Qaysi savolda xato qilganini ko'rsatamiz
    wrong = [str(i) for i, (g, k) in enumerate(zip(given_list, key_list), 1) if g != k]
    wrong_txt = ""
    if wrong:
        shown = ", ".join(wrong[:30])
        if len(wrong) > 30:
            shown += f" va yana {len(wrong) - 30} ta"
        wrong_txt = f"\n\n❌ Xato savollar: {shown}"

    await message.answer(
        f"{emoji} **Natijangiz tayyor!**\n\n"
        f"🧩 Test #{test_id}\n"
        f"✅ To'g'ri: **{correct}/{len(key_list)}**\n"
        f"📊 Foiz: **{percent:.0f}%**\n"
        f"🎯 Baho: **{baho}**"
        f"{wrong_txt}",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


# ============================================================================
# FARZANDLARIM
#
# Ota-ona farzandini bir marta qo'shadi, keyin olimpiadalarga shu ro'yxatdan
# yozdiradi (docs/DECISIONS.md #41). Sinf har o'quv yili boshida o'zi oshadi —
# utils/utility.py -> current_grade.
# ============================================================================


class ChildStates(StatesGroup):
    """Farzand qo'shish va tahrirlash oqimi."""

    waiting_for_lastname = State()
    waiting_for_firstname = State()
    waiting_for_birthdate = State()
    waiting_for_school = State()
    waiting_for_grade = State()
    waiting_for_edit_value = State()


CHILD_FIELDS = {
    "lastname": "Familiya",
    "firstname": "Ism",
    "birthdate": "Tug'ilgan sana",
    "school": "Maktab",
    "grade": "Sinf",
}

MIN_GRADE, MAX_GRADE_INPUT = 1, 11
GRADE_INPUT_PATTERN = re.compile(r"^(\d{1,2})\s*(-\s*sinf)?$", re.IGNORECASE)


async def _load_children(session, chat_id: int) -> list[Child]:
    rows = await session.execute(
        select(Child)
        .where(Child.user_id == chat_id, Child.archived_at.is_(None))
        .order_by(Child.created_at)
    )
    return list(rows.scalars().all())


def _child_line(child: Child) -> str:
    school = f" · {child.school}" if child.school else ""
    return (
        f"🧒 **{child.last_name} {child.first_name}** — "
        f"{current_grade(child.grade, child.grade_year)}-sinf{school}\n"
        f"    🎂 {child.birth_date.strftime('%d.%m.%Y')}"
    )


def _children_keyboard(children: list[Child]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text=f"✏️ {c.first_name}", callback_data=f"child_edit:{c.id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"child_del:{c.id}"),
        ]
        for c in children
    ]
    rows.append([InlineKeyboardButton(text="➕ Farzand qo'shish", callback_data="child_add")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_children(message: Message, chat_id: int) -> None:
    async with async_session() as session:
        children = await _load_children(session, chat_id)

    if not children:
        await message.answer(
            "👨‍👩‍👧 **Farzandlarim**\n\nHali farzand qo'shilmagan.\n"
            "Bir marta qo'shsangiz, olimpiadalarga yozilish bir necha bosishda bo'ladi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Farzand qo'shish", callback_data="child_add")]
                ]
            ),
        )
        return

    await message.answer(
        "👨‍👩‍👧 **Farzandlarim**\n\n"
        + "\n\n".join(_child_line(c) for c in children)
        + "\n\n_Sinf har o'quv yili boshida o'zi oshadi._",
        parse_mode="Markdown",
        reply_markup=_children_keyboard(children),
    )


@router.message(F.text == "👨‍👩‍👧 Farzandlarim")
async def show_children(message: Message, state: FSMContext, bot: Bot):
    if not await require_subscription(message, bot):
        return
    await state.clear()
    await _show_children(message, message.chat.id)


# --- Qo'shish ---


@router.callback_query(F.data == "child_add")
async def child_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.set_state(ChildStates.waiting_for_lastname)
    await callback.message.answer(
        "Farzandingizning familiyasini kiriting (Masalan: Valiyev):",
        reply_markup=get_olympiad_cancel_keyboard(),
    )


@router.message(ChildStates.waiting_for_lastname)
async def child_lastname(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return
    last_name = (message.text or "").strip()
    if len(last_name) < 2:
        await message.answer("Iltimos, familiyani to'liq kiriting (kamida 2 ta harf):")
        return
    if len(last_name) > MAX_NAME_LEN:
        await message.answer(f"Familiya juda uzun. {MAX_NAME_LEN} belgidan oshmasin:")
        return
    await state.update_data(child_last_name=last_name)
    await message.answer(
        "Farzandingizning ismini kiriting (Masalan: Ali):",
        reply_markup=get_olympiad_cancel_keyboard(),
    )
    await state.set_state(ChildStates.waiting_for_firstname)


@router.message(ChildStates.waiting_for_firstname)
async def child_firstname(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return
    first_name = (message.text or "").strip()
    if len(first_name) < 2:
        await message.answer("Iltimos, ismni to'liq kiriting (kamida 2 ta harf):")
        return
    if len(first_name) > MAX_NAME_LEN:
        await message.answer(f"Ism juda uzun. {MAX_NAME_LEN} belgidan oshmasin:")
        return
    await state.update_data(child_first_name=first_name)
    await message.answer(
        "Tug'ilgan sanasini kiriting (Masalan: 2014-05-15, 15.05.2014 yoki 2014-yil 15-may):",
        reply_markup=get_olympiad_cancel_keyboard(),
    )
    await state.set_state(ChildStates.waiting_for_birthdate)


@router.message(ChildStates.waiting_for_birthdate)
async def child_birthdate(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return
    birthdate = parse_flexible_date(message.text)
    if not birthdate:
        await message.answer(
            "Sana formati tushunilmadi. Qaytadan kiriting\n"
            "(Masalan: 2014-05-15, 15.05.2014 yoki 2014-yil 15-may):"
        )
        return
    await state.update_data(child_birth_date=birthdate.strftime("%Y-%m-%d"))
    await message.answer(
        "O'qiydigan maktab nomini kiriting (Masalan: 12-maktab):",
        reply_markup=get_olympiad_cancel_keyboard(),
    )
    await state.set_state(ChildStates.waiting_for_school)


@router.message(ChildStates.waiting_for_school)
async def child_school(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return
    school = (message.text or "").strip()
    if len(school) > MAX_SCHOOL_LEN:
        await message.answer(f"Maktab nomi juda uzun. {MAX_SCHOOL_LEN} belgidan oshmasin:")
        return
    await state.update_data(child_school=school)
    await message.answer(
        f"Hozir nechanchi sinfda o'qiydi? ({MIN_GRADE}-{MAX_GRADE_INPUT})\n\n"
        f"Faqat raqam yozing (Masalan: 5).\n"
        f"_Keyingi o'quv yillarida sinfni bot o'zi oshiradi._",
        parse_mode="Markdown",
        reply_markup=get_olympiad_cancel_keyboard(),
    )
    await state.set_state(ChildStates.waiting_for_grade)


def _parse_grade(raw: str) -> int | None:
    match = GRADE_INPUT_PATTERN.match((raw or "").strip())
    if not match:
        return None
    grade = int(match.group(1))
    return grade if MIN_GRADE <= grade <= MAX_GRADE_INPUT else None


@router.message(ChildStates.waiting_for_grade)
async def child_grade(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return
    grade = _parse_grade(message.text or "")
    if grade is None:
        await message.answer(
            f"Sinfni {MIN_GRADE} dan {MAX_GRADE_INPUT} gacha raqam bilan yozing (Masalan: 5):"
        )
        return

    data = await state.get_data()
    chat_id = message.chat.id
    try:
        async with async_session() as session:
            session.add(
                Child(
                    user_id=chat_id,
                    first_name=data["child_first_name"],
                    last_name=data["child_last_name"],
                    birth_date=datetime.strptime(data["child_birth_date"], "%Y-%m-%d").date(),
                    school=data.get("child_school") or None,
                    grade=grade,
                    # Sinf shu o'quv yiliga tegishli — keyingi yillarda o'zi oshadi.
                    grade_year=academic_year_start(),
                )
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Farzand qo'shishda xato (chat_id={chat_id}): {e}")
        await state.clear()
        await message.answer(
            "Farzandni saqlashda xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=get_main_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        f"✅ **{data['child_last_name']} {data['child_first_name']}** qo'shildi.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )
    await _show_children(message, chat_id)


# --- Tahrirlash ---


@router.callback_query(F.data.startswith("child_edit:"))
async def child_edit_start(callback: CallbackQuery, state: FSMContext):
    child_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        child = await session.get(Child, child_id)
        if not child or child.user_id != callback.message.chat.id or child.archived_at:
            await callback.answer("Farzand topilmadi.", show_alert=True)
            return
        name = f"{child.last_name} {child.first_name}"

    await state.update_data(child_id=child_id)
    await callback.answer()
    await callback.message.answer(
        f"✏️ **{name}** — nimani o'zgartiramiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"child_field:{key}")]
                for key, label in CHILD_FIELDS.items()
            ]
        ),
    )


@router.callback_query(F.data.startswith("child_field:"))
async def child_edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    if field not in CHILD_FIELDS:
        await callback.answer()
        return
    hints = {
        "lastname": "Yangi familiyani kiriting:",
        "firstname": "Yangi ismni kiriting:",
        "birthdate": "Yangi tug'ilgan sanani kiriting (Masalan: 15.05.2014):",
        "school": "Yangi maktab nomini kiriting:",
        "grade": f"Hozirgi sinfni raqam bilan yozing ({MIN_GRADE}-{MAX_GRADE_INPUT}):",
    }
    await state.update_data(child_field=field)
    await state.set_state(ChildStates.waiting_for_edit_value)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(hints[field], reply_markup=get_olympiad_cancel_keyboard())


@router.message(ChildStates.waiting_for_edit_value)
async def child_edit_value(message: Message, state: FSMContext):
    if await _olymp_cancelled(message, state):
        return
    data = await state.get_data()
    field = data.get("child_field")
    child_id = data.get("child_id")
    raw = (message.text or "").strip()

    if field in ("lastname", "firstname"):
        if len(raw) < 2 or len(raw) > MAX_NAME_LEN:
            await message.answer(f"2 dan {MAX_NAME_LEN} gacha belgi bo'lsin. Qaytadan kiriting:")
            return
    elif field == "birthdate":
        if not parse_flexible_date(raw):
            await message.answer("Sana tushunilmadi. Masalan: 15.05.2014")
            return
    elif field == "school":
        if len(raw) > MAX_SCHOOL_LEN:
            await message.answer(f"Maktab nomi {MAX_SCHOOL_LEN} belgidan oshmasin:")
            return
    elif field == "grade":
        if _parse_grade(raw) is None:
            await message.answer(f"Sinfni {MIN_GRADE}-{MAX_GRADE_INPUT} oralig'ida yozing:")
            return
    else:
        await state.clear()
        return

    async with async_session() as session:
        child = await session.get(Child, child_id)
        if not child or child.user_id != message.chat.id or child.archived_at:
            await state.clear()
            await message.answer("Farzand topilmadi.", reply_markup=get_main_keyboard())
            return
        if field == "lastname":
            child.last_name = raw
        elif field == "firstname":
            child.first_name = raw
        elif field == "birthdate":
            child.birth_date = parse_flexible_date(raw)
        elif field == "school":
            child.school = raw or None
        elif field == "grade":
            child.grade = _parse_grade(raw)
            # Yangi sinf shu o'quv yiliga tegishli — hisob shu yildan boshlanadi.
            child.grade_year = academic_year_start()
        await session.commit()

    await state.clear()
    await message.answer(f"✅ {CHILD_FIELDS[field]} yangilandi.", reply_markup=get_main_keyboard())
    await _show_children(message, message.chat.id)


# --- O'chirish ---


@router.callback_query(F.data.startswith("child_del:"))
async def child_delete_ask(callback: CallbackQuery):
    child_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        child = await session.get(Child, child_id)
        if not child or child.user_id != callback.message.chat.id or child.archived_at:
            await callback.answer("Farzand topilmadi.", show_alert=True)
            return
        name = f"{child.last_name} {child.first_name}"

    await callback.answer()
    await callback.message.answer(
        f"🗑 **{name}** ro'yxatdan o'chirilsinmi?\n\n"
        f"_Olimpiadalardagi natijalari saqlanib qoladi._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Ha, o'chirilsin", callback_data=f"child_del_ok:{child_id}"
                    )
                ],
                [InlineKeyboardButton(text="❌ Yo'q", callback_data="child_del_no")],
            ]
        ),
    )


@router.callback_query(F.data == "child_del_no")
async def child_delete_cancel(callback: CallbackQuery):
    await callback.answer("Bekor qilindi.")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("child_del_ok:"))
async def child_delete(callback: CallbackQuery):
    child_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        child = await session.get(Child, child_id)
        if not child or child.user_id != callback.message.chat.id or child.archived_at:
            await callback.answer("Farzand topilmadi.", show_alert=True)
            return
        # O'chirish emas, arxivlash: natijalar va ruxsatnomalar tarixda qoladi.
        child.archived_at = datetime.utcnow()
        await session.commit()

    await callback.answer("O'chirildi.")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _show_children(callback.message, callback.message.chat.id)
