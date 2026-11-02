import io
import os
import re
import json
import uuid
import asyncio
import logging
from datetime import datetime, date
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, delete, update, func, and_, or_
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from database.db import async_session
from database.models import (
    User,
    Olympiad,
    OlympiadResult,
    OnlineTest,
    OnlineTestResult,
    OlympiadGrade,
    AnswerSheet,
    AnswerSheetSubject,
    OlympiadTimeSlot,
    OlympiadRoom,
    TestSheet,
    TestSheetSubject,
    TestSheetParticipant,
)
from utils.utility import (
    parse_flexible_date,
    fmt_number,
    apply_rubric,
    slugify_olympiad_code,
    split_full_name,
)
from utils.qr_payload import build_ticket_no, is_valid_ticket_no
from utils.participant_photo import PhotoError, prepare_participant_photo
from services.ticket_service import (
    EntryPassContext,
    TicketGenerationError,
    generate_entry_pass,
)
from services.answer_sheet_service import (
    AnswerSheetContext,
    SubjectSpec,
    blank_is_current,
    blank_matches_subjects,
    extract_bubble_boxes,
    extract_field_boxes,
    render_blank_sheet_pdf,
    stamp_answer_sheets_pdf,
)
from services.test_sheet_excel import (
    ParticipantsExcelError,
    build_participants_template,
    parse_participants,
)
from services.online_test_excel import build_history_excel, history_filename
from services.omr_checker import (
    OmrError,
    build_annotated_pdf,
    check_sheet,
    sheet_page_count,
    sheet_page_image,
)
from services.ranking import (
    recalculate_olympiad_places,
    grade_counts,
    grade_ranking,
)
from services.name_matching import NameIndex, Candidate
from services.platform_tests import (
    classroom_by_id,
    classroom_students,
    classrooms_for,
    platform_configured,
    test_by_id,
    tests_for_olympiad,
)
from services.excel_import import (
    parse_results_excel,
    ExcelStructureError,
)
from utils.roles import (
    get_staff_role,
    notify_superadmins,
    ROLE_SUPERADMIN,
    ROLE_ADMIN,
    ROLE_TEACHER,
    ROLE_SMM,
    ROLE_RECEPTION,
)
from handlers.superadmin import get_superadmin_keyboard

logger = logging.getLogger(__name__)

router = Router()


class OlympiadCreationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_grades = State()
    waiting_for_date = State()
    waiting_for_confirm = State()


class OlympiadDetailStates(StatesGroup):
    """Bitta olimpiadaning boshqaruv paneli ochiq turgan holat.

    Panel reply-klaviatura sifatida ko'rsatiladi (tugmalar callback_data
    ichida ID tashiy olmaydi), shuning uchun qaysi olimpiada haqida
    gap ketayotgani shu state ichidagi `detail_olympiad_id`da saqlanadi.
    """

    viewing = State()


class OlympiadResultsImportStates(StatesGroup):
    waiting_for_grade = State()
    waiting_for_excel = State()
    waiting_for_confirm = State()
    dupes_policy = State()
    resolving_dupes = State()
    resolving = State()
    manual_offer = State()
    manual_search = State()


class OlympiadRegisterImportStates(StatesGroup):
    """Excel orqali o'quvchilarni olimpiadaga (natijasiz) ro'yxatdan
    o'tkazish — natijalarni yuklash (`OlympiadResultsImportStates`) dan
    mustaqil, alohida oqim. Bu ikkalasi ORQAMA-KETIN ishlatiladi: avval
    shu oqim bilan ro'yxatga olinadi, keyin xuddi shu fayl natija-import
    oqimiga tashlanadi.
    """

    waiting_for_grade = State()
    waiting_for_excel = State()
    waiting_for_confirm = State()
    resolving = State()
    manual_offer = State()
    manual_search = State()


class UserCreationStates(StatesGroup):
    waiting_for_id = State()
    waiting_for_full_name = State()
    waiting_for_phone = State()
    waiting_for_school = State()
    waiting_for_birth_date = State()
    waiting_for_excel = State()


class UserDeletionStates(StatesGroup):
    waiting_for_query = State()


class UserEditingStates(StatesGroup):
    waiting_for_query = State()
    waiting_for_new_value = State()


class BroadcastStates(StatesGroup):
    waiting_for_content = State()


def get_admin_keyboard(is_superadmin: bool = False) -> ReplyKeyboardMarkup:
    """Admin panelining bosh menyusi — mavzu bo'yicha kategoriyalarga
    guruhlangan (har kategoriya o'zining submenyusini ochadi, "🔙 Orqaga"
    bilan shu yerga qaytadi). `is_superadmin=True` bo'lsa, SuperAdmin
    "🛠 Admin panelga o'tish" orqali shu yerga kirgan bo'ladi — panelga
    qaytish tugmasi qo'shiladi.
    """
    keyboard = [
        [
            KeyboardButton(text="📝 Testlarni tekshirish"),
            KeyboardButton(text="🧩 Online testlar"),
        ],
        [
            KeyboardButton(text="🏆 Olimpiadalar boshqaruvi"),
            KeyboardButton(text="👥 Bot foydalanuvchilari"),
        ],
        [KeyboardButton(text="📢 Reklama jo'natish")],
    ]
    if is_superadmin:
        keyboard.append([KeyboardButton(text="⚡ SuperAdmin panelga qaytish")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_test_checking_menu_keyboard() -> ReplyKeyboardMarkup:
    """Javob varag'i (QR + ArUco + OMR) bo'limi.

    Eski, bubble-ID ga asoslangan tekshiruvchi (Test/TestResult/Orm_Scanner)
    butunlay olib tashlandi — uning o'rnini shu ikki tugma egalladi
    (qarang: DECISIONS.md #35).
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🆕 Javob varag'i yaratish"),
                KeyboardButton(text="✅ Javob varag'ini tekshirish"),
            ],
            [KeyboardButton(text="🔙 Orqaga")],
        ],
        resize_keyboard=True,
    )


def get_online_tests_menu_keyboard() -> ReplyKeyboardMarkup:
    """Botning o'zida ishlanadigan (rasm + javob kaliti) testlar bo'limi."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧩 Test savol yaratish")],
            [KeyboardButton(text="📋 Online testlar ro'yxati")],
            [KeyboardButton(text="📊 Online testlar tarixi (Excel)")],
            [KeyboardButton(text="🔙 Orqaga")],
        ],
        resize_keyboard=True,
    )


def get_olympiad_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏆 Olimpiada qo'shish")],
            [KeyboardButton(text="📋 Olimpiadalarni boshqarish")],
            [KeyboardButton(text="🔙 Orqaga")],
        ],
        resize_keyboard=True,
    )


def get_users_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Userlarni ko'rish (Excel)")],
            [
                KeyboardButton(text="👤 User qo'shish"),
                KeyboardButton(text="🗑 User o'chirish"),
            ],
            [KeyboardButton(text="✏️ User tahrirlash")],
            [KeyboardButton(text="🔙 Orqaga")],
        ],
        resize_keyboard=True,
    )


def get_teacher_keyboard() -> ReplyKeyboardMarkup:
    """O'qituvchi uchun cheklangan panel — faqat javob varag'i bilan
    ishlash (yaratish va tekshirish). Avval bu yerda eski tekshiruvchining
    tugmalari turardi; u olib tashlangach, o'qituvchining huquq DARAJASI
    o'zgarmadi — aynan o'sha ish endi yangi varaq orqali bajariladi."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🆕 Javob varag'i yaratish")],
            [KeyboardButton(text="✅ Javob varag'ini tekshirish")],
        ],
        resize_keyboard=True,
    )


def get_smm_keyboard() -> ReplyKeyboardMarkup:
    """SMM menejer uchun cheklangan panel — faqat reklama jo'natish."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📢 Reklama jo'natish")]],
        resize_keyboard=True,
    )


def get_reception_keyboard() -> ReplyKeyboardMarkup:
    """Reception uchun cheklangan panel — faqat ishtirokchini qabul qilish
    (vaqt/xona belgilash). Natijalar, Excel, reklama kabi boshqa hech
    narsaga tega olmaydi (qarang: DECISIONS.md #26)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Ishtirokchini qabul qilish")]],
        resize_keyboard=True,
    )


# Fan o'chirilganini bildiruvchi maxsus qiymat. Bu oddiy javob emas:
# "0" saqlangan fan umuman tekshirilmaydi, uning savollari umumiy
# ballga ham, foizga ham qo'shilmaydi.
DISABLED_SUBJECT = "0"


def normalize_answers(raw: str) -> str | None:
    """Javob kalitini standart shaklga keltiradi: "ABCD" -> "A,B,C,D".

    Alohida holat: faqat "0" kiritilsa fan o'chirilgan deb qabul qilinadi
    va "0" qaytariladi. Aks holda faqat A-E harflari qoldiriladi;
    yaroqli javob topilmasa None qaytadi.
    """
    text = (raw or "").strip()
    if text == DISABLED_SUBJECT:
        return DISABLED_SUBJECT

    letters = "".join(c for c in text.upper() if c in "ABCDE,")
    if not letters.replace(",", ""):
        return None
    if "," not in letters:
        letters = ",".join(list(letters))
    return letters


def is_subject_disabled(answers: str | None) -> bool:
    """Fan o'chirilganmi?"""
    return (answers or "").strip() == DISABLED_SUBJECT


def parse_answer_key(answers: str | None) -> list[str]:
    """Saqlangan kalitni ro'yxatga aylantiradi.

    Fan o'chirilgan bo'lsa BO'SH ro'yxat qaytadi — tekshiruvchi bo'sh
    kalit bilan hech nimani solishtirmaydi va fan ballga qo'shilmaydi.
    """
    if is_subject_disabled(answers):
        return []
    return [a for a in (answers or "").split(",") if a]


def _rubric_summary(rubric_json: str | None) -> str:
    if not rubric_json:
        return "1 savol = 1 ball"
    try:
        rubric = json.loads(rubric_json)
    except (TypeError, ValueError):
        return "1 savol = 1 ball"
    if rubric.get("mode") == "uniform":
        return f"har savol {fmt_number(rubric.get('points'))} ball"
    if rubric.get("mode") == "ranges":
        parts = [
            f"{r['from']}-{r['to']}: {fmt_number(r['points'])} ball"
            for r in rubric.get("ranges", [])
        ]
        return ", ".join(parts) if parts else "1 savol = 1 ball"
    return "1 savol = 1 ball"


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# Ushbu ro'yxatlar qaysi rol qaysi funksiyalardan foydalana olishini belgilaydi.
FULL_ACCESS_ROLES = {ROLE_ADMIN, ROLE_SUPERADMIN}
TEST_ACCESS_ROLES = FULL_ACCESS_ROLES | {ROLE_TEACHER}
BROADCAST_ACCESS_ROLES = FULL_ACCESS_ROLES | {ROLE_SMM}
CHECKIN_ACCESS_ROLES = FULL_ACCESS_ROLES | {ROLE_RECEPTION}


async def is_admin_or_superadmin(chat_id: int, session) -> bool:
    """To'liq admin panelidan foydalanish huquqi bormi (Admin yoki SuperAdmin).

    Diqqat: O'qituvchi va SMM menejer ham `admins` jadvalida saqlanadi, lekin
    ularga bu yerda ruxsat berilmaydi — ular faqat o'ziga tegishli funksiyalar
    uchun alohida (can_manage_tests / can_broadcast) tekshiriladi.
    """
    role = await get_staff_role(chat_id, session)
    return role in FULL_ACCESS_ROLES


async def can_manage_tests(chat_id: int, session) -> bool:
    """Javob varag'ini yaratish / tekshirish huquqi
    (Admin, SuperAdmin yoki O'qituvchi)."""
    role = await get_staff_role(chat_id, session)
    return role in TEST_ACCESS_ROLES


async def can_broadcast(chat_id: int, session) -> bool:
    """Reklama jo'natish huquqi (Admin, SuperAdmin yoki SMM menejer)."""
    role = await get_staff_role(chat_id, session)
    return role in BROADCAST_ACCESS_ROLES


async def can_checkin(chat_id: int, session) -> bool:
    """Ishtirokchini qabul qilish huquqi (Admin, SuperAdmin yoki Reception)."""
    role = await get_staff_role(chat_id, session)
    return role in CHECKIN_ACCESS_ROLES


def _keyboard_for_role(role: str | None) -> ReplyKeyboardMarkup:
    """Berilgan xodim roliga mos reply-klaviaturani qaytaradi (sinxron)."""
    if role == ROLE_SUPERADMIN:
        return get_superadmin_keyboard()
    if role == ROLE_TEACHER:
        return get_teacher_keyboard()
    if role == ROLE_SMM:
        return get_smm_keyboard()
    if role == ROLE_RECEPTION:
        return get_reception_keyboard()
    return get_admin_keyboard()


async def get_role_keyboard(chat_id: int, session) -> ReplyKeyboardMarkup:
    """chat_id bo'yicha xodim rolini aniqlab, mos reply-klaviaturani qaytaradi.

    Faqat allaqachon rol tekshiruvidan o'tgan (ya'ni admin.py ichidagi biror
    funksiyaga kira olgan) xodimlar uchun ishlatiladi, shuning uchun oxirgi
    fallback sifatida to'liq admin klaviaturasi qaytariladi.
    """
    role = await get_staff_role(chat_id, session)
    return _keyboard_for_role(role)


async def get_or_create_dummy_user(session) -> User:
    res = await session.execute(select(User).where(User.id == 1))
    dummy = res.scalar_one_or_none()
    if not dummy:
        dummy = User(
            id=1,
            full_name="Noma'lum O'quvchi",
            phone="Yo'q",
            school="Yo'q",
            birth_date=datetime.now().date(),
        )
        session.add(dummy)
        await session.commit()
    return dummy


@router.message(F.text == "/admin")
async def admin_panel(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await message.answer("Sizda ushbu komandadan foydalanish ruxsati yo'q.")
            return
        role = await get_staff_role(chat_id, session)

        await message.answer(
            "👑 Admin paneliga xush kelibsiz!\nQuyidagi tugmalardan birini bosing:",
            reply_markup=get_admin_keyboard(is_superadmin=role == ROLE_SUPERADMIN),
        )


# ---------------------------------------------------------------- admin panel navigatsiyasi
# Admin panelidagi tugmalar mavzu bo'yicha kategoriyalarga guruhlangan —
# quyidagi handlerlar shu kategoriyalarni ochadi/yopadi. Har kategoriya
# ichidagi haqiqiy tugmalar ("Javob varag'i yaratish" va h.k.) o'zining
# alohida handleriga ega — bu yerda faqat navigatsiya bor.


@router.message(F.text == "📝 Testlarni tekshirish")
async def open_test_checking_menu(message: Message):
    async with async_session() as session:
        if not await is_admin_or_superadmin(message.chat.id, session):
            return
    await message.answer(
        "📝 Testlarni tekshirish bo'limi:", reply_markup=get_test_checking_menu_keyboard()
    )


@router.message(F.text == "🧩 Online testlar")
async def open_online_tests_menu(message: Message):
    async with async_session() as session:
        if not await is_admin_or_superadmin(message.chat.id, session):
            return
    await message.answer(
        "🧩 Online testlar bo'limi:", reply_markup=get_online_tests_menu_keyboard()
    )


@router.message(F.text == "🏆 Olimpiadalar boshqaruvi")
async def open_olympiad_menu(message: Message):
    async with async_session() as session:
        if not await is_admin_or_superadmin(message.chat.id, session):
            return
    await message.answer(
        "🏆 Olimpiadalar bo'limi:", reply_markup=get_olympiad_menu_keyboard()
    )


@router.message(F.text == "👥 Bot foydalanuvchilari")
async def open_users_menu(message: Message):
    async with async_session() as session:
        if not await is_admin_or_superadmin(message.chat.id, session):
            return
    await message.answer(
        "👥 Bot foydalanuvchilari bo'limi:", reply_markup=get_users_menu_keyboard()
    )


@router.message(F.text == "🔙 Orqaga")
async def back_to_admin_menu(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        role = await get_staff_role(chat_id, session)
        if role not in FULL_ACCESS_ROLES:
            return
    await message.answer(
        "👑 Admin paneli:",
        reply_markup=get_admin_keyboard(is_superadmin=role == ROLE_SUPERADMIN),
    )


@router.message(F.text == "⚡ SuperAdmin panelga qaytish")
async def back_to_superadmin_menu(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        role = await get_staff_role(chat_id, session)
        if role != ROLE_SUPERADMIN:
            return
    await message.answer("⚡ SuperAdmin paneli:", reply_markup=get_superadmin_keyboard())


@router.message(F.text == "🛠 Admin panelga o'tish")
async def open_admin_panel_from_superadmin(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        role = await get_staff_role(chat_id, session)
        if role != ROLE_SUPERADMIN:
            return
    await message.answer(
        "👑 Admin paneli:", reply_markup=get_admin_keyboard(is_superadmin=True)
    )


async def _return_to_menu(
    message: Message, state: FSMContext, menu: str | None, role: str | None
) -> None:
    """Bekor qilingandan keyin qaysi reply-klaviaturaga qaytilishini
    hal qiladi. Jarayonning o'zi bu funksiyaga kelguncha ALLAQACHON
    to'liq bekor qilingan (`state.clear()` chaqirilgan) — bu yerda faqat
    ekranga qaysi klaviatura chiqarilishi tanlanadi: funksiya qaysi
    submenyudan boshlangan bo'lsa, aynan o'sha submenyuga (`return_menu`
    yorlig'i orqali "eslab qolingan").

    `menu` tanilmasa/berilmagan bo'lsa — eski xatti-harakat
    (`_keyboard_for_role`) ishlatiladi, hech narsa buzilmaydi.
    """
    if menu == "test_checking":
        # O'qituvchida "Testlarni tekshirish" submenyusi yo'q — u to'g'ridan
        # to'g'ri o'zining kichik klaviaturasidan shu oqimlarga kiradi.
        if role == ROLE_TEACHER:
            await message.answer("Bosh menyu:", reply_markup=get_teacher_keyboard())
        else:
            await message.answer(
                "📝 Testlarni tekshirish bo'limi:",
                reply_markup=get_test_checking_menu_keyboard(),
            )
        return
    if menu == "online_tests":
        await message.answer(
            "🧩 Online testlar bo'limi:", reply_markup=get_online_tests_menu_keyboard()
        )
        return
    if menu == "olympiad_menu":
        await message.answer(
            "🏆 Olimpiadalar bo'limi:", reply_markup=get_olympiad_menu_keyboard()
        )
        return
    if menu == "users_menu":
        await message.answer(
            "👥 Bot foydalanuvchilari bo'limi:", reply_markup=get_users_menu_keyboard()
        )
        return
    if menu and menu.startswith("olympiad_detail:"):
        try:
            olympiad_id = int(menu.split(":", 1)[1])
        except ValueError:
            olympiad_id = None
        if olympiad_id is not None:
            await _render_olympiad_detail(message, state, olympiad_id)
            return

    await message.answer("Bosh menyu:", reply_markup=_keyboard_for_role(role))


@router.message(Command("cancel"))
@router.message(F.text == "❌ Bekor qilish")
async def cancel_handler(message: Message, state: FSMContext):
    """Cancels any active state/flow."""
    chat_id = message.chat.id
    async with async_session() as session:
        role = await get_staff_role(chat_id, session)

    if role is None:
        # Bu xodim (admin/o'qituvchi/smm/superadmin) emas — bu handler unga
        # tegishli emas, hech narsa qilmaymiz.
        return

    current_state = await state.get_state()
    if current_state is None:
        await message.answer(
            "Hech qanday faol jarayon yo'q.", reply_markup=_keyboard_for_role(role)
        )
        return

    data = await state.get_data()
    return_menu = data.get("return_menu")

    logger.info(f"Cancelling state {current_state}")
    await state.clear()
    await message.answer("Jarayon bekor qilindi. ❌")
    await _return_to_menu(message, state, return_menu, role)


@router.callback_query(F.data == "cancel_process")
async def cancel_callback_handler(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.from_user.id
    async with async_session() as session:
        role = await get_staff_role(chat_id, session)

    data = await state.get_data()
    return_menu = data.get("return_menu")

    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    await callback.answer("Jarayon bekor qilindi.")
    try:
        await callback.message.delete()
    except Exception:
        pass

    if role is None:
        return

    await _return_to_menu(callback.message, state, return_menu, role)


# 1. VIEW USERS AS EXCEL FILE
@router.message(F.text == "👥 Userlarni ko'rish (Excel)")
async def export_users_to_excel(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        result = await session.execute(select(User))
        users = result.scalars().all()

        if not users:
            await message.answer("Ma'lumotlar bazasida foydalanuvchilar yo'q.")
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Foydalanuvchilar"

        headers = [
            "Telegram Chat ID",
            "Ism Familiya",
            "Telefon raqam",
            "Maktab",
            "Tug'ilgan sana",
            "Sinfi",
            "Sinf rahbari",
            "Ro'yxatdan o'tgan sana",
        ]
        ws.append(headers)

        for user in users:
            ws.append(
                [
                    user.id,
                    user.full_name,
                    user.phone,
                    user.school,
                    user.birth_date.strftime("%Y-%m-%d")
                    if user.birth_date
                    else "Kiritilmagan",
                    user.grade if user.grade is not None else "Kiritilmagan",
                    user.teacher_name or "Kiritilmagan",
                    (
                        user.registered_at.strftime("%Y-%m-%d %H:%M")
                        if user.registered_at
                        else "Noma'lum"
                    ),
                ]
            )

        file_path = f"users_{chat_id}.xlsx"
        wb.save(file_path)

        # try/finally: jo'natish yiqilsa ham vaqtinchalik fayl diskda
        # qolib ketmasin (serverda ular yig'ilib boradi).
        try:
            await message.answer_document(
                FSInputFile(file_path),
                caption="📁 Barcha ro'yxatdan o'tgan foydalanuvchilar ro'yxati (Excel formatda).",
            )
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)


# --- Baholash mezoni (savol boshiga necha ball) ---

_RUBRIC_RANGE_ITEM = re.compile(r"(\d+)\s*-\s*(\d+)\s*:\s*([\d.,]+)")


def _parse_rubric_input(text: str) -> dict | None:
    """Baholash mezoni matnini o'qiydi.

    Bitta musbat son — "hammasiga bir xil":
        {"mode": "uniform", "points": X}
    "1-10: 1.1" ko'rinishidagi qatorlar (vergul yoki yangi qator bilan
    ajratilgan, "ball" so'zi bo'lsa ham farqi yo'q) — savol-oralig'iga
    qarab turlicha ball:
        {"mode": "ranges", "ranges": [{"from":1,"to":10,"points":1.1}, ...]}
    Noto'g'ri format — None.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    try:
        points = float(raw.replace(",", "."))
        if points > 0:
            return {"mode": "uniform", "points": points}
    except ValueError:
        pass

    ranges = []
    for item in re.split(r"[,\n]+", raw):
        item = item.strip()
        if not item:
            continue
        m = _RUBRIC_RANGE_ITEM.search(item)
        if not m:
            return None
        frm, to = int(m.group(1)), int(m.group(2))
        points = float(m.group(3).replace(",", "."))
        if to < frm or points <= 0:
            return None
        ranges.append({"from": frm, "to": to, "points": points})

    if not ranges:
        return None
    ranges.sort(key=lambda r: r["from"])
    return {"mode": "ranges", "ranges": ranges}


_RUBRIC_HINT = (
    "Har bir savolga bir xil ball bo'lsa — bitta son yozing (masalan: 1.5).\n"
    "Oraliqqa qarab farqlansa — har birini yozing (masalan:\n1-10: 1.1\n11-30: 2.3):"
)


@router.message(F.text == "🏆 Olimpiada qo'shish")
async def start_add_olympiad(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        await state.update_data(return_menu="olympiad_menu")
        await message.answer(
            "Yangi olimpiada nomini kiriting (Masalan: Matematika Olimpiadasi 2026):",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(OlympiadCreationStates.waiting_for_name)


ALL_GRADES = list(range(1, 12))


def _grades_keyboard(selected: set[int]) -> InlineKeyboardMarkup:
    """Sinf tanlash klaviaturasi — tanlanganlar ✅ bilan belgilanadi."""
    rows, row = [], []
    for g in ALL_GRADES:
        mark = "✅" if g in selected else "▫️"
        row.append(
            InlineKeyboardButton(
                text=f"{mark} {g}-sinf", callback_data=f"olymp_grade:{g}"
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(text="💾 Saqlash", callback_data="olymp_grades_done")]
    )
    rows.append(
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="olymp_create_cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fmt_grades(grades) -> str:
    return ", ".join(f"{g}" for g in sorted(grades)) + "-sinf" if grades else "—"


@router.message(OlympiadCreationStates.waiting_for_name)
async def process_olympiad_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Olimpiada nomi juda qisqa. Iltimos, qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    if len(name) > 200:
        await message.answer(
            f"Nom juda uzun ({len(name)} belgi). 200 belgidan oshmasin:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    async with async_session() as session:
        exists = (
            await session.execute(select(Olympiad.id).where(Olympiad.name == name))
        ).scalar_one_or_none()
    if exists:
        await message.answer(
            "Shu nomdagi olimpiada allaqachon mavjud. Boshqa nom kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(olympiad_name=name, selected_grades=[])
    await message.answer(
        f"🏆 **{name}**\n\nQaysi sinflar uchun ushbu olimpiada o'tkaziladi?\n"
        f"Bir nechtasini tanlashingiz mumkin.",
        parse_mode="Markdown",
        reply_markup=_grades_keyboard(set()),
    )
    await state.set_state(OlympiadCreationStates.waiting_for_grades)


@router.callback_query(
    OlympiadCreationStates.waiting_for_grades, F.data.startswith("olymp_grade:")
)
async def toggle_olympiad_grade(callback: CallbackQuery, state: FSMContext):
    grade = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_grades", []))

    if grade in selected:
        selected.discard(grade)
    else:
        selected.add(grade)

    await state.update_data(selected_grades=sorted(selected))
    try:
        await callback.message.edit_reply_markup(reply_markup=_grades_keyboard(selected))
    except Exception:
        pass
    await callback.answer(
        f"{grade}-sinf {'qo‘shildi' if grade in selected else 'olib tashlandi'}"
    )


@router.callback_query(
    OlympiadCreationStates.waiting_for_grades, F.data == "olymp_grades_done"
)
async def finish_olympiad_grades(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = sorted(data.get("selected_grades", []))
    if not selected:
        await callback.answer("Kamida bitta sinf tanlang!", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        f"🏆 **{data['olympiad_name']}**\n"
        f"📚 Sinflar: {_fmt_grades(selected)}\n\n"
        f"Endi olimpiada sanasini kiriting.",
        parse_mode="Markdown",
    )
    await callback.message.answer(
        "Sanani kiriting (Masalan: 2026-09-15, 15.09.2026 yoki 2026-yil 15-sentyabr):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(OlympiadCreationStates.waiting_for_date)


@router.callback_query(F.data == "olymp_create_cancel")
async def cancel_olympiad_create(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Bekor qilindi.")
    try:
        await callback.message.edit_text("Olimpiada yaratish bekor qilindi.")
    except Exception:
        pass
    await callback.message.answer(
        "🏆 Olimpiadalar bo'limi:", reply_markup=get_olympiad_menu_keyboard()
    )


@router.message(OlympiadCreationStates.waiting_for_date)
async def process_olympiad_date(message: Message, state: FSMContext):
    exam_date = parse_flexible_date(message.text)
    if not exam_date:
        await message.answer(
            "Sana formati tushunilmadi. Iltimos, qaytadan kiriting\n"
            "(Masalan: 2026-09-15, 15.09.2026 yoki 2026-yil 15-sentyabr):",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    await state.update_data(exam_date=exam_date.strftime("%Y-%m-%d"))
    await state.set_state(OlympiadCreationStates.waiting_for_confirm)

    await message.answer(
        f"🏆 Olimpiada: **{data['olympiad_name']}**\n"
        f"📚 Sinflar: {_fmt_grades(data.get('selected_grades', []))}\n"
        f"📅 Sana: {exam_date.strftime('%d.%m.%Y')}\n\n"
        f"Saqlansinmi?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Ha", callback_data="olymp_save")],
                [
                    InlineKeyboardButton(
                        text="❌ Bekor qilish", callback_data="olymp_create_cancel"
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    OlympiadCreationStates.waiting_for_confirm, F.data == "olymp_save"
)
async def save_olympiad(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name = data["olympiad_name"]
    grades = sorted(data.get("selected_grades", []))
    exam_date = datetime.strptime(data["exam_date"], "%Y-%m-%d").date()

    try:
        async with async_session() as session:
            # code ruxsatnoma ticket_no ichiga tushadi (masalan "MATH") —
            # admin alohida kiritmaydi, nomdan avtomatik hosil qilinadi.
            olympiad = Olympiad(
                name=name,
                exam_date=exam_date,
                is_active=True,
                code=slugify_olympiad_code(name),
            )
            session.add(olympiad)
            await session.flush()
            for g in grades:
                session.add(OlympiadGrade(olympiad_id=olympiad.id, grade=g))
            await session.commit()
            olympiad_id = olympiad.id
    except Exception as e:
        logger.error(f"Olimpiada saqlashda xato ({name}): {e}")
        await callback.answer("Saqlashda xatolik!", show_alert=True)
        await callback.message.answer(
            "Olimpiadani saqlashda xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=get_admin_keyboard(),
        )
        await state.clear()
        return

    await state.clear()
    logger.info(f"Olimpiada #{olympiad_id} yaratildi: {name}, sinflar={grades}")
    await callback.answer("Saqlandi! 🎉")
    await callback.message.edit_text(
        f"🎉 **Olimpiada yaratildi!**\n\n"
        f"🏆 {name}\n"
        f"📚 Sinflar: {_fmt_grades(grades)}\n"
        f"📅 {exam_date.strftime('%d.%m.%Y')}\n"
        f"✅ Faol — o'quvchilar ro'yxatdan o'ta oladi",
        parse_mode="Markdown",
    )
    await callback.message.answer("Admin paneli:", reply_markup=get_admin_keyboard())


async def get_olympiad_grades(session, olympiad_id: int) -> list[int]:
    """Olimpiadaga biriktirilgan sinflar ro'yxati (o'sish tartibida)."""
    rows = (
        await session.execute(
            select(OlympiadGrade.grade)
            .where(OlympiadGrade.olympiad_id == olympiad_id)
            .order_by(OlympiadGrade.grade)
        )
    ).scalars().all()
    return list(rows)

def _olympiad_manage_keyboard(olympiads) -> InlineKeyboardMarkup:
    buttons = []
    for o in olympiads:
        status = "✅ Faol" if o.is_active else "⛔️ Nofaol"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{o.name} — {status}",
                    callback_data=f"olymp_manage:{o.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == "📋 Olimpiadalarni boshqarish")
async def list_olympiads_admin(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        res = await session.execute(select(Olympiad).order_by(Olympiad.id.desc()))
        olympiads = res.scalars().all()

        if not olympiads:
            await message.answer("Hali birorta ham olimpiada qo'shilmagan.")
            return

        await message.answer(
            "🏆 **Olimpiadalar ro'yxati**\n\n"
            "Batafsil ko'rish, faollikni o'zgartirish yoki natijalarni yuklab olish uchun tanlang:",
            parse_mode="Markdown",
            reply_markup=_olympiad_manage_keyboard(olympiads),
        )


def _olympiad_detail_keyboard(is_active: bool) -> ReplyKeyboardMarkup:
    toggle_text = "⛔️ Nofaol qilish" if is_active else "✅ Faollashtirish"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=toggle_text)],
            [
                KeyboardButton(text="👥 Ro'yxatdan o'tganlar (Excel)"),
                KeyboardButton(text="📊 Natijalarni yuklab olish (Excel)"),
            ],
            [
                KeyboardButton(text="📝 Excel orqali ro'yxatdan o'tkazish"),
                KeyboardButton(text="📥 Natijalarni Excel orqali yuklash"),
            ],
            [
                KeyboardButton(text="📝 Javob varag'i sozlash"),
                KeyboardButton(text="📄 Javob varaqlari (ZIP)"),
            ],
            [
                KeyboardButton(text="✅ Ishtirokchini qabul qilish"),
                KeyboardButton(text="⚙️ Qabul qilish sozlamalari"),
            ],
            [
                KeyboardButton(text="🔑 Javob kaliti"),
                KeyboardButton(text="📷 Varaqni tekshirish"),
            ],
            [KeyboardButton(text="🏅 Ishtirokchilar (Excel)")],
            [KeyboardButton(text="📊 Sinf bo'yicha natijalar")],
            [KeyboardButton(text="🔙 Ortga")],
        ],
        resize_keyboard=True,
    )


async def _render_olympiad_detail(message: Message, state: FSMContext, olympiad_id: int):
    """Olimpiada boshqaruv panelini reply-klaviatura bilan ko'rsatadi.

    Tugmalar callback_data ichida ID tashiy olmaydi (reply-klaviatura),
    shuning uchun `olympiad_id` FSM state ichiga (`detail_olympiad_id`)
    yoziladi — panel tugmalarining har biri o'sha yerdan o'qiydi.
    """
    async with async_session() as session:
        res = await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        olympiad = res.scalar_one_or_none()
        if not olympiad:
            await message.answer("Topilmadi.")
            return

        count_res = await session.execute(
            select(OlympiadResult).where(OlympiadResult.olympiad_id == olympiad_id)
        )
        participants = count_res.scalars().all()
        checked_count = sum(1 for p in participants if p.score is not None)
        attended_count = sum(1 for p in participants if p.attended_at is not None)

        olymp_grades = await get_olympiad_grades(session, olympiad_id)
        per_grade = await grade_counts(session, olympiad_id)

    date_txt = (
        olympiad.exam_date.strftime("%Y-%m-%d")
        if olympiad.exam_date
        else "Kiritilmagan"
    )
    sinflar_txt = (
        ", ".join(f"{g}-sinf" for g in olymp_grades)
        if olymp_grades
        else "biriktirilmagan"
    )
    text = (
        f"🏆 **{olympiad.name}**\n\n"
        f"📅 Sana: {date_txt}\n"
        f"{'✅ Faol' if olympiad.is_active else '⛔️ Nofaol'}\n"
        f"📚 Sinflar: {sinflar_txt}\n\n"
        f"👥 Ro'yxatdan o'tganlar: {len(participants)}\n"
        f"🏅 Ishtirokchilar (qabul qilingan): {attended_count}\n"
        f"✅ Natijasi tekshirilganlar: {checked_count}"
    )
    if per_grade:
        text += "\n\n**Sinflar bo'yicha:**"
        for g in sorted(per_grade, key=lambda x: (x is None, x)):
            nomi = f"{g}-sinf" if g is not None else "sinfsiz"
            text += f"\n  • {nomi} — {per_grade[g]} ta"

    await state.update_data(detail_olympiad_id=olympiad_id)
    await state.set_state(OlympiadDetailStates.viewing)
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=_olympiad_detail_keyboard(olympiad.is_active),
    )


@router.callback_query(F.data.startswith("olymp_manage:"))
async def manage_olympiad_detail(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.from_user.id
    olympiad_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

    await _render_olympiad_detail(callback.message, state, olympiad_id)
    await callback.answer()


@router.message(OlympiadDetailStates.viewing, F.text == "⛔️ Nofaol qilish")
@router.message(OlympiadDetailStates.viewing, F.text == "✅ Faollashtirish")
async def toggle_olympiad_active(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        res = await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        olympiad = res.scalar_one_or_none()
        if not olympiad:
            await message.answer("Topilmadi.")
            return

        olympiad.is_active = not olympiad.is_active
        await session.commit()

    await message.answer("Holat o'zgartirildi ✅")
    await _render_olympiad_detail(message, state, olympiad_id)


@router.message(OlympiadDetailStates.viewing, F.text == "🔙 Ortga")
async def olympiad_manage_back(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        res = await session.execute(select(Olympiad).order_by(Olympiad.id.desc()))
        olympiads = res.scalars().all()

    await state.clear()
    await message.answer(
        "🏆 **Olimpiadalar ro'yxati**\n\n"
        "Batafsil ko'rish, faollikni o'zgartirish yoki natijalarni yuklab olish uchun tanlang:",
        parse_mode="Markdown",
        reply_markup=_olympiad_manage_keyboard(olympiads),
    )
    await message.answer(
        "🏆 Olimpiadalar bo'limi:", reply_markup=get_olympiad_menu_keyboard()
    )


@router.message(OlympiadDetailStates.viewing, F.text == "👥 Ro'yxatdan o'tganlar (Excel)")
async def export_olympiad_registered_users(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        # Admin huquqini tekshirish
        if not await is_admin_or_superadmin(chat_id, session):
            return

        # Olimpiadani olish
        olympiad_res = await session.execute(
            select(Olympiad).where(Olympiad.id == olympiad_id)
        )
        olympiad = olympiad_res.scalar_one_or_none()

        if not olympiad:
            await message.answer("Olimpiada topilmadi.")
            return

        # Shu olimpiadaga ro'yxatdan o'tgan barcha foydalanuvchilar
        res = await session.execute(
            select(OlympiadResult, User)
            .join(User, OlympiadResult.user_id == User.id)
            .where(OlympiadResult.olympiad_id == olympiad_id)
            .order_by(OlympiadResult.id.asc())
        )
        rows = res.all()

    if not rows:
        await message.answer("Bu olimpiadaga hali hech kim ro'yxatdan o'tmagan.")
        return

    # Excel yaratish
    wb = Workbook()
    ws = wb.active
    ws.title = "Ro'yxatdan o'tganlar"

    ws.append(
        [
            "T/r",
            "Telegram Chat ID",
            "Ism Familiya",
            "Telefon raqam",
            "Maktab/O'quv Markazi",
            "Tug'ilgan sana",
            "Sinfi",
            "Sinf rahbari",
            "Ro'yxatdan o'tgan sana",
            "Natija",
            "Ball",
            "O'rin",
        ]
    )

    for idx, (olymp_result, user) in enumerate(rows, 1):
        # Maktab/sinf/o'qituvchi endi olimpiadaga yozilishda so'raladi va
        # olympiad_results da saqlanadi. Eski ishtirokchilarda u bo'sh —
        # o'shanda foydalanuvchi profilidagi eski qiymatga qaytamiz.
        school = olymp_result.school or user.school or "Kiritilmagan"
        grade = olymp_result.grade if olymp_result.grade is not None else user.grade
        teacher = olymp_result.teacher_name or user.teacher_name or "Kiritilmagan"

        ws.append(
            [
                idx,
                user.id,
                user.full_name,
                user.phone,
                school,
                user.birth_date.strftime("%Y-%m-%d")
                if user.birth_date
                else "Kiritilmagan",
                grade if grade is not None else "Kiritilmagan",
                teacher,
                (
                    olymp_result.registered_at.strftime("%Y-%m-%d %H:%M")
                    if olymp_result.registered_at
                    else "Noma'lum"
                ),
                "Tekshirilgan" if olymp_result.score is not None else "Kutilmoqda",
                round(olymp_result.score, 2) if olymp_result.score is not None else "-",
                olymp_result.place if olymp_result.place is not None else "-",
            ]
        )

    file_path = f"olympiad_{olympiad_id}_registered_users.xlsx"
    wb.save(file_path)

    # Admin'ga yuborish; vaqtinchalik fayl har holatda o'chiriladi.
    try:
        await message.answer_document(
            FSInputFile(file_path),
            caption=(
                f"👥 **{olympiad.name}**\n\n"
                f"Ro'yxatdan o'tganlar soni: **{len(rows)} ta**\n"
                f"📊 Excel formatida."
            ),
            parse_mode="Markdown",
        )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.message(OlympiadDetailStates.viewing, F.text == "🏅 Ishtirokchilar (Excel)")
async def export_olympiad_participants_excel(message: Message, state: FSMContext):
    """Faqat "Ishtirokchi" (reception qabul qilgan, attended_at
    to'ldirilgan) qatorlar uchun — "Ro'yxatdan o'tganlar (Excel)"dan
    farqli, bu yerda vaqt/xona ustunlari bor (qarang: DECISIONS.md #26).
    Proktorlarga xona bo'yicha ro'yxat berish uchun mo'ljallangan, shuning
    uchun vaqt, keyin xona bo'yicha tartiblanadi (id bo'yicha emas).
    """
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        olympiad = (
            await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        ).scalar_one_or_none()
        if not olympiad:
            await message.answer("Olimpiada topilmadi.")
            return

        rows = (
            await session.execute(
                select(OlympiadResult, User, OlympiadTimeSlot, OlympiadRoom)
                .join(User, OlympiadResult.user_id == User.id)
                .outerjoin(
                    OlympiadTimeSlot, OlympiadResult.time_slot_id == OlympiadTimeSlot.id
                )
                .outerjoin(OlympiadRoom, OlympiadResult.room_id == OlympiadRoom.id)
                .where(
                    OlympiadResult.olympiad_id == olympiad_id,
                    OlympiadResult.attended_at.isnot(None),
                )
                .order_by(
                    OlympiadTimeSlot.position.asc().nulls_last(),
                    OlympiadRoom.room_number.asc().nulls_last(),
                    OlympiadResult.last_name.asc().nulls_last(),
                )
            )
        ).all()

    if not rows:
        await message.answer(
            "Bu olimpiadada hali birorta ham ishtirokchi qabul qilinmagan.\n\n"
            "Ro'yxat faqat \"✅ Ishtirokchini qabul qilish\" orqali vaqt/xona "
            "belgilangan ishtirokchilar uchun tuziladi."
        )
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "Ishtirokchilar"

    ws.append(
        [
            "T/r",
            "F.I.Sh",
            "Maktabi",
            "Sinfi",
            "Telefon raqami",
            "Ustozining F.I.Sh",
            "Vaqti",
            "Xona raqami",
        ]
    )

    for idx, (result, user, slot, room) in enumerate(rows, 1):
        if result.first_name and result.last_name:
            fish = f"{result.last_name} {result.first_name}"
        else:
            fish = result.full_name or user.full_name

        school = result.school or user.school or "Kiritilmagan"
        grade = result.grade if result.grade is not None else user.grade
        teacher = result.teacher_name or user.teacher_name or "Kiritilmagan"

        ws.append(
            [
                idx,
                fish,
                school,
                grade if grade is not None else "Kiritilmagan",
                user.phone or "Kiritilmagan",
                teacher,
                slot.label if slot else "-",
                room.room_number if room else "-",
            ]
        )

    file_path = f"olympiad_{olympiad_id}_participants.xlsx"
    wb.save(file_path)

    try:
        await message.answer_document(
            FSInputFile(file_path),
            caption=(
                f"🏅 **{olympiad.name}**\n\n"
                f"Ishtirokchilar soni: **{len(rows)} ta**\n"
                f"📊 Excel formatida."
            ),
            parse_mode="Markdown",
        )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# ============================================================================
# JAVOB VARAG'I: fan/savol/variant sozlash va ommaviy PDF generatsiyasi
#
# QR-asosli (ruxsatnomadagi ticket_no bilan bir xil) yo'l. Qarang:
# database/models.py -> AnswerSheet/AnswerSheetSubject,
# services/answer_sheet_service.py.
# ============================================================================


class AnswerSheetStates(StatesGroup):
    """Javob varag'i uchun fan/savol/variant sozlamalarini kiritish oqimi."""

    waiting_for_subject_count = State()
    waiting_for_subject_name = State()
    waiting_for_question_count = State()
    waiting_for_choice_count = State()
    waiting_for_confirm = State()
    # Platformada shu olimpiada uchun test bor bo'lsa: undan olamizmi yoki
    # qo'lda sozlaymizmi (DECISIONS.md #40).
    waiting_for_source = State()


def _fmt_subject_line(i: int, name: str, question_count: int, choice_count: int) -> str:
    letters = "ABCD" if choice_count == 4 else "ABCDE"
    return f"  {i}. {name} — {question_count} savol, {letters}"


@router.message(OlympiadDetailStates.viewing, F.text == "📝 Javob varag'i sozlash")
async def start_answer_sheet_setup(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        existing_subjects = (
            await session.execute(
                select(AnswerSheetSubject)
                .join(AnswerSheet, AnswerSheetSubject.answer_sheet_id == AnswerSheet.id)
                .where(AnswerSheet.olympiad_id == olympiad_id)
                .order_by(AnswerSheetSubject.position)
            )
        ).scalars().all()

    intro = ""
    if existing_subjects:
        ro_yxat = "\n".join(
            _fmt_subject_line(s.position, s.name, s.question_count, s.choice_count)
            for s in existing_subjects
        )
        intro = (
            f"Hozirgi sozlama:\n{ro_yxat}\n\n"
            f"Qayta sozlasangiz, eskisi butunlay almashtiriladi.\n\n"
        )

    await state.clear()
    await state.update_data(
        as_olympiad_id=olympiad_id,
        as_subjects=[],
        return_menu=f"olympiad_detail:{olympiad_id}",
    )

    # Platformada shu olimpiada uchun test tuzilgan bo'lsa, sozlamani
    # qo'lda kiritish shart emas (DECISIONS.md #40).
    platform_tests = await tests_for_olympiad(olympiad_id) if platform_configured() else []
    if platform_tests:
        rows = [
            [
                InlineKeyboardButton(
                    text=f"📥 {t.title[:38]} — {t.question_count} savol",
                    callback_data=f"as_from_platform:{t.id}",
                )
            ]
            for t in platform_tests
        ]
        rows.append([InlineKeyboardButton(text="✍️ Qo'lda sozlash", callback_data="as_manual")])
        await message.answer(
            f"{intro}📝 **Javob varag'i sozlash**\n\n"
            f"Platformada shu olimpiada uchun test tayyor. Testni tanlasangiz, fan nomi, "
            f"savollar soni, variantlar soni va javob kaliti o'zi to'ldiriladi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await state.set_state(AnswerSheetStates.waiting_for_source)
        return

    await _ask_subject_count(message, state, intro)


async def _ask_subject_count(message: Message, state: FSMContext, intro: str = "") -> None:
    await message.answer(
        f"{intro}📝 **Javob varag'i sozlash**\n\n"
        f"Necha fan bo'yicha imtihon o'tkaziladi? (1, 2 yoki 3):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AnswerSheetStates.waiting_for_subject_count)


@router.callback_query(AnswerSheetStates.waiting_for_source, F.data == "as_manual")
async def as_manual_source(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _ask_subject_count(callback.message, state)


@router.callback_query(
    AnswerSheetStates.waiting_for_source, F.data.startswith("as_from_platform:")
)
async def as_from_platform(callback: CallbackQuery, state: FSMContext):
    """Platformadagi testdan javob varag'i sozlamasini to'ldiradi.

    Test tugma bosilguncha o'zgargan bo'lishi mumkin — shuning uchun qayta
    o'qiladi. Kalit savollar soniga mos kelmasa, sozlama baribir saqlanadi,
    lekin kalitni admin "🔑 Javob kaliti" orqali kiritadi.
    """
    test_id = callback.data.split(":", 1)[1]
    test = await test_by_id(test_id)
    if not test or test.question_count == 0:
        await callback.answer("Test topilmadi — qo'lda sozlang.", show_alert=True)
        return

    subject = {
        "name": test.subject_name[:100],
        "question_count": test.question_count,
        "choice_count": test.choice_count or 5,
        "answer_key": ",".join(test.answer_key) if test.key_matches else None,
    }
    await state.update_data(as_subjects=[subject], as_subject_count=1)

    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    key_line = (
        "🔑 Javob kaliti ham platformadan olindi."
        if subject["answer_key"]
        else "⚠️ Javob kaliti platformada tayyor emas — uni \"🔑 Javob kaliti\" orqali kiritasiz."
    )
    await callback.message.answer(
        f"📝 **Javob varag'i sozlamasi** (platformadagi «{test.title}» testidan):\n\n"
        f"{_fmt_subject_line(1, subject['name'], subject['question_count'], subject['choice_count'])}\n"
        f"{key_line}\n\nSaqlansinmi?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Ha", callback_data="as_save")],
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="as_cancel")],
            ]
        ),
    )
    await state.set_state(AnswerSheetStates.waiting_for_confirm)


@router.message(AnswerSheetStates.waiting_for_subject_count)
async def as_process_subject_count(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if raw not in ("1", "2", "3"):
        await message.answer(
            "Iltimos, 1, 2 yoki 3 dan birini kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(as_subject_count=int(raw))
    await message.answer(
        "1-fan nomini kiriting (Masalan: Matematika):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AnswerSheetStates.waiting_for_subject_name)


@router.message(AnswerSheetStates.waiting_for_subject_name)
async def as_process_subject_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Fan nomi juda qisqa. Iltimos, qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    if len(name) > 100:
        await message.answer(
            f"Fan nomi juda uzun ({len(name)} belgi). 100 belgidan oshmasin:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    subjects = data.get("as_subjects", [])
    subjects.append({"name": name})
    await state.update_data(as_subjects=subjects)

    await message.answer(
        f"«{name}» uchun savollar sonini kiriting (Masalan: 30):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AnswerSheetStates.waiting_for_question_count)


@router.message(AnswerSheetStates.waiting_for_question_count)
async def as_process_question_count(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 200):
        await message.answer(
            "Iltimos, 1 dan 200 gacha bo'lgan butun son kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    subjects = data["as_subjects"]
    subjects[-1]["question_count"] = int(raw)
    await state.update_data(as_subjects=subjects)

    await message.answer(
        f"«{subjects[-1]['name']}» uchun javob variantlari nechta?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="4 (ABCD)", callback_data="as_choice:4"),
                    InlineKeyboardButton(text="5 (ABCDE)", callback_data="as_choice:5"),
                ]
            ]
        ),
    )
    await state.set_state(AnswerSheetStates.waiting_for_choice_count)


@router.callback_query(
    AnswerSheetStates.waiting_for_choice_count, F.data.startswith("as_choice:")
)
async def as_process_choice_count(callback: CallbackQuery, state: FSMContext):
    choice_count = int(callback.data.split(":")[1])
    data = await state.get_data()
    subjects = data["as_subjects"]
    subjects[-1]["choice_count"] = choice_count
    await state.update_data(as_subjects=subjects)

    await callback.answer(f"{choice_count} ta variant tanlandi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    subject_count = data["as_subject_count"]
    if len(subjects) < subject_count:
        next_idx = len(subjects) + 1
        await callback.message.answer(
            f"{next_idx}-fan nomini kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(AnswerSheetStates.waiting_for_subject_name)
        return

    ro_yxat = "\n".join(
        _fmt_subject_line(i, s["name"], s["question_count"], s["choice_count"])
        for i, s in enumerate(subjects, 1)
    )
    await callback.message.answer(
        f"📝 **Javob varag'i sozlamasi:**\n\n{ro_yxat}\n\nSaqlansinmi?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Ha", callback_data="as_save")],
                [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="as_cancel")],
            ]
        ),
    )
    await state.set_state(AnswerSheetStates.waiting_for_confirm)


@router.callback_query(AnswerSheetStates.waiting_for_confirm, F.data == "as_cancel")
async def as_cancel(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    olympiad_id = data.get("as_olympiad_id")
    await state.clear()
    await callback.answer("Bekor qilindi.")
    try:
        await callback.message.edit_text("Javob varag'i sozlash bekor qilindi.")
    except Exception:
        pass
    if olympiad_id:
        await _render_olympiad_detail(callback.message, state, olympiad_id)


@router.callback_query(AnswerSheetStates.waiting_for_confirm, F.data == "as_save")
async def as_save(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    olympiad_id = data["as_olympiad_id"]
    subjects = data["as_subjects"]

    try:
        async with async_session() as session:
            existing_sheet = (
                await session.execute(
                    select(AnswerSheet).where(AnswerSheet.olympiad_id == olympiad_id)
                )
            ).scalar_one_or_none()

            if existing_sheet:
                # Eski fanlarni o'chiramiz (cascade emas, to'g'ridan-to'g'ri) —
                # keyin yangilarini yozamiz. AnswerSheet qatorining o'zi qoladi,
                # shuning uchun uning id'si (va shu bilan olympiad_id bog'lanishi)
                # o'zgarmaydi.
                await session.execute(
                    delete(AnswerSheetSubject).where(
                        AnswerSheetSubject.answer_sheet_id == existing_sheet.id
                    )
                )
                sheet = existing_sheet
                # Eski shablonni SHU YERDA, fanlar bilan bir tranzaksiyada
                # bekor qilamiz. Aks holda quyidagi qayta chizish xato bersa
                # (yoki bot qayta ishga tushsa) bazada ESKI fanlar bo'yicha
                # chizilgan shablon qolib ketardi va eksport uni jimgina
                # ishlatib yuborardi (qarang: DECISIONS.md #30).
                sheet.blank_pdf = None
                sheet.field_boxes = None
                sheet.bubble_boxes = None
            else:
                sheet = AnswerSheet(olympiad_id=olympiad_id)
                session.add(sheet)
                await session.flush()

            for i, s in enumerate(subjects, 1):
                session.add(
                    AnswerSheetSubject(
                        answer_sheet_id=sheet.id,
                        position=i,
                        name=s["name"],
                        question_count=s["question_count"],
                        choice_count=s["choice_count"],
                        # Platformadagi testdan olingan bo'lsa kalit ham shu
                        # yerda yoziladi (DECISIONS.md #40).
                        answer_key=s.get("answer_key"),
                    )
                )
            await session.commit()
    except Exception as e:
        logger.error(
            f"Javob varag'i sozlamasini saqlashda xato (olimpiada={olympiad_id}): {e}"
        )
        await callback.answer("Saqlashda xatolik!", show_alert=True)
        await callback.message.answer(
            "Javob varag'i sozlamasini saqlashda xatolik yuz berdi. "
            "Qaytadan urinib ko'ring."
        )
        await state.clear()
        return

    await state.clear()
    await callback.answer("Saqlandi! 🎉")
    try:
        await callback.message.edit_text(
            "✅ Javob varag'i sozlamasi saqlandi.\n\n"
            "⏳ Bo'sh varaq shabloni fonda chizilmoqda (bir necha daqiqa "
            "vaqt olishi mumkin). Shundan keyin javob varaqlarini yuklab "
            "olish bir necha soniyada bajariladi. Bu orada menyudan boshqa "
            "amallarni bemalol bajaraverishingiz mumkin."
        )
    except Exception:
        pass
    await _render_olympiad_detail(callback.message, state, olympiad_id)

    # Bo'sh shablon shu yerdan BOSHLAB fonda chiziladi (qarang:
    # DECISIONS.md #27). Menyu yuqorida ALLAQACHON qaytarilgan, shuning
    # uchun admin bu bir necha daqiqani kutib turishga majbur emas —
    # natija alohida xabar bilan keladi.
    try:
        await _build_and_store_blank_sheet(olympiad_id)
        try:
            await callback.message.answer(
                "✅ Bo'sh varaq shabloni tayyor. Endi \"📄 Javob varaqlari "
                "(ZIP)\" tugmasi bir necha soniyada natija beradi."
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(
            f"Bo'sh javob varag'i shablonini tayyorlashda xato "
            f"(olimpiada={olympiad_id}): {e}"
        )
        try:
            await callback.message.answer(
                f"⚠️ Bo'sh varaq shablonini tayyorlashda xatolik:\n\n{e}\n\n"
                f"Javob varaqlarini yuklab olmoqchi bo'lganingizda u qaytadan "
                f"urinib ko'riladi."
            )
        except Exception:
            pass
        await notify_superadmins(
            bot,
            f"⚠️ Bo'sh javob varag'i shabloni tayyorlanmadi "
            f"(olimpiada #{olympiad_id}): {e}",
        )


async def _build_and_store_blank_sheet(olympiad_id: int) -> None:
    """Olimpiada uchun BO'SH javob varag'i shablonini chizib, maydon
    koordinatalari bilan birga bazaga yozadi (`AnswerSheet.blank_pdf` +
    `field_boxes`).

    Sekin (doiralar ko'p — bir necha daqiqa), shuning uchun faqat ikki
    joyda chaqiriladi: fan sozlanganda (`as_save`) va eksportda shablon
    topilmasa (`export_answer_sheets_zip`). Ikkalasi ham BIRGA yoziladi:
    bittasi eskirsa matn noto'g'ri joyga tushardi.
    """
    async with async_session() as session:
        row = (
            await session.execute(
                select(AnswerSheet, Olympiad)
                .join(Olympiad, AnswerSheet.olympiad_id == Olympiad.id)
                .where(AnswerSheet.olympiad_id == olympiad_id)
            )
        ).first()
        if not row:
            raise RuntimeError(
                f"Olimpiada #{olympiad_id} uchun javob varag'i sozlamasi yo'q"
            )
        sheet, olympiad = row
        sheet_id, event_title = sheet.id, olympiad.name

        subject_rows = (
            await session.execute(
                select(AnswerSheetSubject)
                .where(AnswerSheetSubject.answer_sheet_id == sheet_id)
                .order_by(AnswerSheetSubject.position)
            )
        ).scalars().all()

    subjects = tuple(
        SubjectSpec(
            name=s.name,
            question_count=s.question_count,
            choice_count=s.choice_count,
        )
        for s in subject_rows
    )
    if not subjects:
        raise RuntimeError(f"Olimpiada #{olympiad_id} uchun fan sozlanmagan")

    blank_pdf = await render_blank_sheet_pdf(subjects, event_title)
    field_boxes = await asyncio.to_thread(extract_field_boxes, blank_pdf)
    # Doira markazlari ham SHU YERDA, shablon bilan bir vaqtda olinadi —
    # keyin avtomatik tekshirishda ishlatiladi (DECISIONS.md #29).
    bubble_boxes = await asyncio.to_thread(
        extract_bubble_boxes, blank_pdf, subjects
    )

    async with async_session() as session:
        db_sheet = await session.get(AnswerSheet, sheet_id)
        db_sheet.blank_pdf = blank_pdf
        db_sheet.field_boxes = field_boxes
        db_sheet.bubble_boxes = bubble_boxes
        await session.commit()


@router.message(OlympiadDetailStates.viewing, F.text == "📄 Javob varaqlari (ZIP)")
async def export_answer_sheets_zip(message: Message, state: FSMContext, bot: Bot):
    """Javob varaqlari VAQT va XONA bo'yicha tayyorlanadi.

    Varaqlar amalda xonama-xona tarqatiladi, shuning uchun butun
    olimpiada uchun bitta katta PDF berish o'rniga avval vaqt oralig'i,
    keyin xona so'raladi va faqat o'sha (vaqt, xona) juftligiga
    biriktirilgan ishtirokchilar uchun generatsiya qilinadi
    (qarang: DECISIONS.md #28).
    """
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        sheet = (
            await session.execute(
                select(AnswerSheet).where(AnswerSheet.olympiad_id == olympiad_id)
            )
        ).scalar_one_or_none()
        if not sheet:
            await message.answer(
                "Bu olimpiada uchun javob varag'i hali sozlanmagan.\n\n"
                "Avval \"📝 Javob varag'i sozlash\" orqali fan/savol/variant "
                "sonini kiriting."
            )
            return

        # Faqat "Ishtirokchi" (Reception qabul qilgan) qatorlar hisobga
        # olinadi — shunchaki "Ro'yxatdan o'tgan" uchun EMAS
        # (qarang: DECISIONS.md #26).
        slot_rows = (
            await session.execute(
                select(OlympiadTimeSlot, func.count(OlympiadResult.id))
                .join(
                    OlympiadResult,
                    and_(
                        OlympiadResult.time_slot_id == OlympiadTimeSlot.id,
                        OlympiadResult.attended_at.isnot(None),
                    ),
                )
                .where(OlympiadTimeSlot.olympiad_id == olympiad_id)
                .group_by(OlympiadTimeSlot.id)
                .order_by(OlympiadTimeSlot.position)
            )
        ).all()

        # Sozlama qayta kiritilgan bo'lsa, ba'zi ishtirokchilarning
        # vaqt/xonasi tozalangan bo'lishi mumkin (DECISIONS.md #26) —
        # ular hech qaysi ro'yxatga tushmaydi, shuning uchun ogohlantiramiz.
        orphan_count = (
            await session.execute(
                select(func.count(OlympiadResult.id)).where(
                    OlympiadResult.olympiad_id == olympiad_id,
                    OlympiadResult.attended_at.isnot(None),
                    or_(
                        OlympiadResult.time_slot_id.is_(None),
                        OlympiadResult.room_id.is_(None),
                    ),
                )
            )
        ).scalar_one()

    if not slot_rows:
        await message.answer(
            "Bu olimpiadada hali birorta ham ishtirokchi qabul qilinmagan.\n\n"
            "Javob varag'i faqat \"✅ Ishtirokchini qabul qilish\" orqali "
            "vaqt/xona belgilangan ishtirokchilar uchun tayyorlanadi."
        )
        return

    text = "⏱ Qaysi vaqt uchun javob varaqlari kerak?"
    if orphan_count:
        text += (
            f"\n\n⚠️ {orphan_count} ta ishtirokchining vaqt/xonasi belgilanmagan "
            f"(sozlama qayta kiritilgan bo'lishi mumkin) — ular hech qaysi "
            f"ro'yxatga kirmaydi. Ularni qaytadan qabul qilish kerak."
        )

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{slot.label} — {cnt} ta",
                        callback_data=f"as_slot:{olympiad_id}:{slot.id}",
                    )
                ]
                for slot, cnt in slot_rows
            ]
        ),
    )


@router.callback_query(F.data.startswith("as_slot:"))
async def as_export_pick_slot(callback: CallbackQuery):
    """Vaqt tanlangandan keyin — o'sha vaqtdagi xonalar ro'yxati."""
    chat_id = callback.from_user.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

        _, olympiad_id_txt, slot_id_txt = callback.data.split(":")
        olympiad_id, slot_id = int(olympiad_id_txt), int(slot_id_txt)

        slot = await session.get(OlympiadTimeSlot, slot_id)
        room_rows = (
            await session.execute(
                select(OlympiadRoom, func.count(OlympiadResult.id))
                .join(
                    OlympiadResult,
                    and_(
                        OlympiadResult.room_id == OlympiadRoom.id,
                        OlympiadResult.time_slot_id == slot_id,
                        OlympiadResult.attended_at.isnot(None),
                    ),
                )
                .where(OlympiadRoom.olympiad_id == olympiad_id)
                .group_by(OlympiadRoom.id)
                .order_by(OlympiadRoom.room_number)
            )
        ).all()

    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not room_rows:
        await callback.message.answer(
            "Bu vaqt uchun birorta ham xonaga ishtirokchi biriktirilmagan."
        )
        return

    await callback.message.answer(
        f"🚪 «{slot.label if slot else '-'}» uchun qaysi xona?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{room.room_number}-xona — {cnt} ta",
                        callback_data=f"as_room:{olympiad_id}:{slot_id}:{room.id}",
                    )
                ]
                for room, cnt in room_rows
            ]
        ),
    )


@router.callback_query(F.data.startswith("as_room:"))
async def as_export_pick_room(callback: CallbackQuery, bot: Bot):
    """Xona tanlangandan keyin — faqat o'sha (vaqt, xona) ishtirokchilari
    uchun javob varaqlarini tayyorlab yuboradi."""
    chat_id = callback.from_user.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

    _, olympiad_id_txt, slot_id_txt, room_id_txt = callback.data.split(":")
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _send_answer_sheets_for_room(
        callback.message,
        bot,
        olympiad_id=int(olympiad_id_txt),
        slot_id=int(slot_id_txt),
        room_id=int(room_id_txt),
    )


async def _send_answer_sheets_for_room(
    message: Message, bot: Bot, olympiad_id: int, slot_id: int, room_id: int
) -> None:
    async with async_session() as session:
        olympiad = (
            await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        ).scalar_one_or_none()
        if not olympiad:
            await message.answer("Olimpiada topilmadi.")
            return

        sheet = (
            await session.execute(
                select(AnswerSheet).where(AnswerSheet.olympiad_id == olympiad_id)
            )
        ).scalar_one_or_none()
        if not sheet:
            await message.answer("Javob varag'i sozlamasi topilmadi.")
            return

        subject_rows = (
            await session.execute(
                select(AnswerSheetSubject)
                .where(AnswerSheetSubject.answer_sheet_id == sheet.id)
                .order_by(AnswerSheetSubject.position)
            )
        ).scalars().all()
        subjects = tuple(
            SubjectSpec(
                name=s.name,
                question_count=s.question_count,
                choice_count=s.choice_count,
            )
            for s in subject_rows
        )
        # Shablon bor bo'lishi YETARLI EMAS — u HOZIRGI fan sozlamasiga mos
        # kelishi ham kerak. Mos kelmasa (fanlar o'zgargan, eskisi qolib
        # ketgan) qaytadan chiziladi (DECISIONS.md #30).
        has_blank = (
            bool(sheet.blank_pdf and sheet.field_boxes)
            and blank_is_current(sheet.field_boxes)
            and blank_matches_subjects(sheet.bubble_boxes, subjects)
        )

        slot = await session.get(OlympiadTimeSlot, slot_id)
        room = await session.get(OlympiadRoom, room_id)

        rows = (
            await session.execute(
                select(OlympiadResult, User)
                .join(User, OlympiadResult.user_id == User.id)
                .where(
                    OlympiadResult.olympiad_id == olympiad_id,
                    OlympiadResult.attended_at.isnot(None),
                    OlympiadResult.time_slot_id == slot_id,
                    OlympiadResult.room_id == room_id,
                )
                .order_by(OlympiadResult.last_name.asc().nulls_last())
            )
        ).all()

    if not rows:
        await message.answer(
            "Bu vaqt va xona bo'yicha ishtirokchi topilmadi."
        )
        return

    contexts: list[AnswerSheetContext] = []
    skipped = 0
    for result, user in rows:
        if not result.ticket_no:
            # Amalda bo'lmasligi kerak — init_db() backfill orqali
            # hammasini to'ldiradi. Ehtiyot chorasi sifatida qoldirilgan.
            skipped += 1
            continue
        if result.first_name and result.last_name:
            first_name, last_name = result.first_name, result.last_name
        else:
            first_name, last_name = split_full_name(result.full_name or user.full_name)

        # Eski (birth_date maydoni qo'shilishidan oldingi) yozuvlarda bu
        # bo'sh — o'sha holatda users.birth_date'ga qaytamiz (aniq mos
        # kelmasligi mumkin, lekin hech narsadan ko'ra yaxshiroq).
        bdate = result.birth_date or user.birth_date
        if bdate:
            kun, oy, yil = f"{bdate.day:02d}", f"{bdate.month:02d}", str(bdate.year)
        else:
            kun, oy, yil = "-", "-", "-"

        sinf_txt = f"{result.grade}-sinf" if result.grade is not None else "-"

        contexts.append(
            AnswerSheetContext(
                ism=first_name,
                familiya=last_name,
                kun=kun,
                oy=oy,
                yil=yil,
                sinf=sinf_txt,
                ticket_no=result.ticket_no,
            )
        )

    if not contexts:
        # Nazariy jihatdan bo'lmasligi kerak (backfill hammasini
        # to'ldiradi), lekin real hayotda bot ticket_no funksiyasi
        # qo'shilgandan keyin QAYTA ISHGA TUSHIRILMAGAN bo'lsa aynan
        # shu holatga tushiladi. Bo'sh fayl jo'natish o'rniga aniq sabab
        # ko'rsatamiz.
        await message.answer(
            f"❌ {skipped} ta ro'yxatdan o'tgan bor, lekin birontasida ham "
            f"ticket_no topilmadi.\n\n"
            f"Bu odatda botni ticket_no funksiyasi qo'shilgandan keyin "
            f"qayta ishga tushirilmagani sababli bo'ladi (eski yozuvlarga "
            f"ticket_no faqat bot ishga tushganda avtomatik to'ldiriladi). "
            f"Botni qayta ishga tushiring va qaytadan urinib ko'ring."
        )
        return

    # Bo'sh shablon yo'q bo'lsa (sozlash paytida chizilmagan yoki xato
    # bo'lgan) — MAJBURIY ravishda shu yerda chizib, saqlab, keyin davom
    # etamiz. "Sekin-lekin-to'g'ri" zaxira yo'l endi yo'q: shablonsiz
    # javob varag'i umuman tayyorlanmaydi (qarang: DECISIONS.md #27).
    if not has_blank:
        await message.answer(
            "⏳ Bo'sh varaq shabloni yo'q yoki hozirgi fan sozlamasiga mos "
            "emas (sozlama o'zgargan bo'lishi mumkin).\n\n"
            "Avval shablon qaytadan chiziladi (bir necha daqiqa), so'ng "
            "javob varaqlari darhol yaratiladi. Kutib turing..."
        )
        try:
            await _build_and_store_blank_sheet(olympiad_id)
        except Exception as e:
            logger.exception(
                f"Bo'sh shablonni eksport paytida tayyorlashda xato "
                f"(olimpiada={olympiad_id}): {e}"
            )
            await message.answer(
                "❌ Bo'sh varaq shablonini tayyorlab bo'lmadi, shuning uchun "
                "javob varaqlari ham yaratilmadi.\n\n"
                "Agar bu lokal (Windows) muhitda sodir bo'lsa — WeasyPrint "
                "uchun kerakli tizim kutubxonalari (GTK3) o'rnatilmagan "
                "bo'lishi mumkin. Administratorga xabar berildi."
            )
            await notify_superadmins(
                bot,
                f"⚠️ Bo'sh javob varag'i shabloni tayyorlanmadi "
                f"(olimpiada #{olympiad_id}): {e}",
            )
            return

    async with async_session() as session:
        fresh = (
            await session.execute(
                select(AnswerSheet).where(AnswerSheet.olympiad_id == olympiad_id)
            )
        ).scalar_one_or_none()
        blank_pdf = fresh.blank_pdf if fresh else None
        field_boxes = fresh.field_boxes if fresh else None

    if not (blank_pdf and field_boxes):
        await message.answer(
            "❌ Bo'sh varaq shabloni topilmadi. \"📝 Javob varag'i sozlash\" "
            "orqali sozlamani qayta saqlab ko'ring."
        )
        return

    slot_txt = slot.label if slot else "-"
    room_txt = f"{room.room_number}-xona" if room else "-"

    await message.answer(
        f"⏳ {slot_txt}, {room_txt} — {len(contexts)} ta javob varag'i "
        f"tayyorlanmoqda..."
    )
    try:
        pdf_bytes = await stamp_answer_sheets_pdf(blank_pdf, field_boxes, contexts)
    except Exception as e:
        logger.exception(f"Javob varaqlarini shtamplashda xato: {e}")
        await message.answer(
            "❌ Javob varaqlarini tayyorlashda texnik xatolik yuz berdi. "
            "Administratorga xabar berildi."
        )
        await notify_superadmins(
            bot,
            f"⚠️ Javob varaqlarini shtamplash ishlamadi "
            f"(olimpiada #{olympiad_id}): {e}",
        )
        return

    caption = (
        f"📄 **{olympiad.name}**\n\n"
        f"⏱ {slot_txt}\n"
        f"🚪 {room_txt}\n"
        f"👥 {len(contexts)} ta javob varag'i, bitta PDF ichida."
    )
    if skipped:
        caption += f"\n⚠️ {skipped} ta yozuvda ticket_no topilmadi, o'tkazib yuborildi."

    room_no = room.room_number if room else 0
    await message.answer_document(
        BufferedInputFile(
            pdf_bytes,
            filename=(
                f"olympiad_{olympiad_id}_xona{room_no}_javob_varaqlari.pdf"
            ),
        ),
        caption=caption,
        parse_mode="Markdown",
    )


# ============================================================================
# JAVOB KALITI va VARAQNI AVTOMATIK TEKSHIRISH (OMR)
#
# Kalit QO'LDA kiritiladi (har fan uchun alohida). Tekshirish esa
# services/omr_checker.py orqali: rasm -> ArUco bo'yicha to'g'rilash ->
# QR'dan ishtirokchini aniqlash -> doiralarning qorong'uligini o'lchash.
# Qarang: DECISIONS.md #29, #31.
# ============================================================================


class AnswerKeyStates(StatesGroup):
    waiting_for_key = State()
    waiting_for_rubric = State()


class OmrCheckStates(StatesGroup):
    waiting_for_image = State()


def _subject_slug(name: str) -> str:
    """Fan nomidan `OlympiadResult.detail` uchun kalit yasaydi.

    Mavjud (Excel'dan keladigan) tafsilot bilan bir xil ko'rinish:
    "Ingliz tili" -> "ingliz_tili".
    """
    out = "".join(c if c.isalnum() else "_" for c in name.lower().replace("'", ""))
    return "_".join(p for p in out.split("_") if p)


async def _load_subjects(session, olympiad_id: int):
    """Olimpiadaning javob varag'i fanlarini tartib bo'yicha qaytaradi."""
    return (
        await session.execute(
            select(AnswerSheetSubject)
            .join(AnswerSheet, AnswerSheetSubject.answer_sheet_id == AnswerSheet.id)
            .where(AnswerSheet.olympiad_id == olympiad_id)
            .order_by(AnswerSheetSubject.position)
        )
    ).scalars().all()


async def _ask_next_key(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    idx = data["ak_index"]
    subs = data["ak_subjects"]
    if idx >= len(subs):
        return

    s = subs[idx]
    letters = "ABCDE"[: s["choice_count"]]
    current = s.get("answer_key")
    hint = f"\n\nHozirgi kalit: `{current}`" if current else ""
    await message.answer(
        f"🔑 **{s['name']}** uchun to'g'ri javoblarni kiriting.\n\n"
        f"{s['question_count']} ta javob, faqat {letters} harflari.\n"
        f"Masalan: `ABCDA...` yoki `A,B,C,D,A...`{hint}",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AnswerKeyStates.waiting_for_key)


@router.message(OlympiadDetailStates.viewing, F.text == "🔑 Javob kaliti")
async def answer_key_start(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        subject_rows = await _load_subjects(session, olympiad_id)

    if not subject_rows:
        await message.answer(
            "Bu olimpiada uchun javob varag'i hali sozlanmagan.\n\n"
            "Avval \"📝 Javob varag'i sozlash\" orqali fanlarni kiriting."
        )
        return

    subs = [
        {
            "id": s.id,
            "name": s.name,
            "question_count": s.question_count,
            "choice_count": s.choice_count,
            "answer_key": s.answer_key,
            "rubric": s.rubric,
        }
        for s in subject_rows
    ]
    await state.clear()
    await state.update_data(
        detail_olympiad_id=olympiad_id,
        ak_olympiad_id=olympiad_id,
        ak_subjects=subs,
        ak_index=0,
        return_menu=f"olympiad_detail:{olympiad_id}",
    )
    await _ask_next_key(message, state)


@router.message(AnswerKeyStates.waiting_for_key)
async def answer_key_process(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["ak_index"]
    subs = data["ak_subjects"]
    s = subs[idx]
    letters = "ABCDE"[: s["choice_count"]]

    normalized = normalize_answers(message.text or "")
    if not normalized or is_subject_disabled(normalized):
        await message.answer(
            f"Javoblarni tushuna olmadim. Faqat {letters} harflarini kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    key = parse_answer_key(normalized)
    if len(key) != s["question_count"]:
        await message.answer(
            f"❌ {len(key)} ta javob kiritildi, lekin «{s['name']}» fanida "
            f"{s['question_count']} ta savol bor. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    bad = sorted({a for a in key if a not in letters})
    if bad:
        await message.answer(
            f"❌ Bu fanda faqat {letters} harflari bo'lishi mumkin, lekin "
            f"{', '.join(bad)} uchradi. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    subs[idx]["answer_key"] = normalized
    await state.update_data(ak_subjects=subs)

    # Kalitdan keyin — SHU FAN uchun baholash mezoni.
    current = _rubric_summary(s.get("rubric")) if s.get("rubric") else None
    hint = f"\n\nHozirgi mezon: {current}" if current else ""
    await message.answer(
        f"✅ «{s['name']}» kaliti qabul qilindi.\n\n"
        f"📐 Endi shu fan uchun **baholash mezonini** kiriting.\n\n"
        f"{_RUBRIC_HINT}\n\n"
        f"Mezon kerak bo'lmasa `-` yuboring "
        f"(u holda har to'g'ri javob 1 ball).{hint}",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(AnswerKeyStates.waiting_for_rubric)


@router.message(AnswerKeyStates.waiting_for_rubric)
async def answer_key_rubric(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["ak_index"]
    subs = data["ak_subjects"]
    s = subs[idx]

    raw = (message.text or "").strip()
    if raw in ("-", "0", "yo'q", "yoq"):
        subs[idx]["rubric"] = None
    else:
        rubric = _parse_rubric_input(raw)
        if not rubric:
            await message.answer(
                f"Mezonni tushuna olmadim.\n\n{_RUBRIC_HINT}\n\n"
                f"Yoki `-` yuboring (har to'g'ri javob 1 ball):",
                parse_mode="Markdown",
                reply_markup=get_cancel_keyboard(),
            )
            return
        # Oraliqli mezonda savol soni mos kelishini tekshiramiz — aks
        # holda ba'zi savollar ballsiz qolib ketardi.
        if rubric.get("mode") == "ranges":
            covered = set()
            for rng in rubric.get("ranges", []):
                covered.update(range(int(rng["from"]), int(rng["to"]) + 1))
            missing = sorted(set(range(1, s["question_count"] + 1)) - covered)
            if missing:
                preview = ", ".join(map(str, missing[:10]))
                more = "..." if len(missing) > 10 else ""
                await message.answer(
                    f"❌ Bu savollar uchun ball ko'rsatilmadi: {preview}{more}\n\n"
                    f"«{s['name']}» fanida {s['question_count']} ta savol bor — "
                    f"hammasini qamrab oling:",
                    reply_markup=get_cancel_keyboard(),
                )
                return
        subs[idx]["rubric"] = json.dumps(rubric)

    await state.update_data(ak_subjects=subs, ak_index=idx + 1)

    if idx + 1 < len(subs):
        await message.answer(f"✅ «{s['name']}» mezoni qabul qilindi.")
        await _ask_next_key(message, state)
        return

    olympiad_id = data["ak_olympiad_id"]
    async with async_session() as session:
        for item in subs:
            row = await session.get(AnswerSheetSubject, item["id"])
            if row:
                row.answer_key = item["answer_key"]
                row.rubric = item.get("rubric")
        await session.commit()

    summary = "\n".join(
        f"  • {item['name']}: {_rubric_summary(item.get('rubric'))}" for item in subs
    )
    await state.clear()
    await message.answer(
        f"✅ Javob kaliti va baholash mezoni saqlandi:\n\n{summary}\n\n"
        f"Endi \"📷 Varaqni tekshirish\" orqali varaqlarni avtomatik "
        f"tekshirsangiz bo'ladi."
    )
    await _render_olympiad_detail(message, state, olympiad_id)


@router.message(OlympiadDetailStates.viewing, F.text == "📷 Varaqni tekshirish")
async def omr_check_start(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        sheet = (
            await session.execute(
                select(AnswerSheet).where(AnswerSheet.olympiad_id == olympiad_id)
            )
        ).scalar_one_or_none()
        subject_rows = await _load_subjects(session, olympiad_id)

    if not sheet or not subject_rows:
        await message.answer("Bu olimpiada uchun javob varag'i sozlanmagan.")
        return
    if not (sheet.blank_pdf and sheet.field_boxes and sheet.bubble_boxes):
        await message.answer(
            "Bu olimpiada uchun varaq shabloni hali tayyorlanmagan.\n\n"
            "Avval \"📄 Javob varaqlari (ZIP)\" orqali varaqlarni bir marta "
            "yarating — shablon o'shanda chiziladi."
        )
        return
    missing = [s.name for s in subject_rows if not s.answer_key]
    if missing:
        await message.answer(
            f"❌ Javob kaliti kiritilmagan: {', '.join(missing)}.\n\n"
            f"Avval \"🔑 Javob kaliti\" orqali to'g'ri javoblarni kiriting."
        )
        return

    await state.update_data(omr_olympiad_id=olympiad_id)
    await message.answer(
        "📷 Javob varag'ining rasmini yoki skanini yuboring.\n\n"
        "• Rasm sifatida ham, fayl (PDF/JPG) sifatida ham bo'ladi\n"
        "• Varaqning TO'RTALA burchagi ham rasmga tushsin\n"
        "• Ko'p varaqni bitta PDF qilib yuborsangiz, hammasi tekshiriladi",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(OmrCheckStates.waiting_for_image)


@router.message(OmrCheckStates.waiting_for_image, F.photo | F.document)
async def omr_check_process(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    olympiad_id = data.get("omr_olympiad_id")
    if not olympiad_id:
        await state.clear()
        return

    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    status = await message.answer("⏳ Varaq o'qilmoqda...")
    try:
        file_info = await bot.get_file(file_id)
        buf = await bot.download_file(file_info.file_path)
        raw = buf.read()
    except Exception as e:
        logger.exception(f"OMR faylini yuklashda xato: {e}")
        await status.edit_text("❌ Faylni yuklab bo'lmadi. Qaytadan yuboring.")
        return

    async with async_session() as session:
        sheet = (
            await session.execute(
                select(AnswerSheet).where(AnswerSheet.olympiad_id == olympiad_id)
            )
        ).scalar_one_or_none()
        subject_rows = await _load_subjects(session, olympiad_id)

    # Sozlama FSM ichida turganda o'zgargan/o'chirilgan bo'lishi mumkin.
    if not (sheet and sheet.field_boxes and sheet.bubble_boxes and subject_rows):
        await state.clear()
        await status.edit_text(
            "❌ Bu olimpiadaning varaq shabloni endi mavjud emas. "
            "Sozlamani qaytadan saqlang va yana urinib ko'ring."
        )
        return

    keys = {s.name: parse_answer_key(s.answer_key) for s in subject_rows}
    rubrics = {s.name: s.rubric for s in subject_rows}
    field_boxes, bubble_boxes = sheet.field_boxes, sheet.bubble_boxes

    try:
        total_pages = await asyncio.to_thread(sheet_page_count, raw)
    except OmrError as e:
        await status.edit_text(f"❌ {e}")
        return

    lines: list[str] = []
    saved = 0
    annotated_pages: list[bytes] = []
    checked_grades: set[int | None] = set()
    # Sahifalar BIRMA-BIR o'qiladi: hammasini bir yo'la ro'yxatga yig'ish
    # 1 GB li serverda xotirani tugatib qo'yardi (qarang: omr_checker.py ->
    # sheet_page_image).
    for page_no in range(1, total_pages + 1):
        prefix = f"{page_no}-varaq: " if total_pages > 1 else ""
        try:
            img = await asyncio.to_thread(sheet_page_image, raw, page_no - 1)
            result = await asyncio.to_thread(
                check_sheet, img, field_boxes, bubble_boxes, keys
            )
        except OmrError as e:
            lines.append(f"❌ {prefix}{e}")
            continue
        if result.annotated_png:
            annotated_pages.append(result.annotated_png)

        async with async_session() as session:
            row = (
                await session.execute(
                    select(OlympiadResult).where(
                        OlympiadResult.olympiad_id == olympiad_id,
                        OlympiadResult.ticket_no == result.ticket_no,
                    )
                )
            ).scalar_one_or_none()

            if not row:
                lines.append(
                    f"❌ {prefix}{result.ticket_no} — bu ID bo'yicha ishtirokchi "
                    f"topilmadi."
                )
                continue

            # Dublikat himoyasi: bitta varaq ikki marta tekshirilsa (bir
            # PDF ichida takrorlangan sahifa yoki qayta yuborilgan fayl),
            # natija QAYTA YOZILMAYDI — aks holda birinchi tekshiruv
            # jimgina almashib ketardi.
            if row.checked_at is not None:
                when = row.checked_at.strftime("%d.%m.%Y %H:%M")
                lines.append(
                    f"⏭ {prefix}{row.full_name or result.ticket_no} — allaqachon "
                    f"tekshirilgan ({when}), saqlanmadi."
                )
                continue

            total_correct = total_questions = 0
            total_score = total_max = 0.0
            has_rubric = False
            detail: dict[str, list[dict]] = {}
            per_subject: list[str] = []
            # Eski tekshiruvchidagi bilan bir xil sxema: Excel hisoboti va
            # o'quvchiga ko'rsatiladigan natija QAT'IY kalitlarga tayanadi
            # ("matematika"/"ingliz_tili" va math_*/english_* ustunlari),
            # shuning uchun fanlar TARTIB bo'yicha shu joylarga tushadi:
            # 1-fan -> matematika, 2-fan -> ingliz tili. Uchinchi fan
            # bo'lsa, u faqat `detail` ichida o'z nomi bilan saqlanadi.
            legacy_slots = ("matematika", "ingliz_tili")
            for pos, subj in enumerate(result.subjects):
                key = keys.get(subj.name) or []
                # Har savol uchun to'g'ri/noto'g'ri — mezon shu asosda
                # og'irlikli ball hisoblaydi (eski oqimdagi bilan bir xil).
                mask = [
                    got is not None and got == want
                    for got, want in zip(subj.answers, key)
                ]
                correct = sum(1 for x in mask if x)
                count = len(key)
                total_correct += correct
                total_questions += count

                subj_score, subj_max, subj_detail = apply_rubric(
                    mask, rubrics.get(subj.name), correct
                )
                total_score += subj_score
                total_max += subj_max
                if subj_detail:
                    has_rubric = True

                slot = (
                    legacy_slots[pos]
                    if pos < len(legacy_slots)
                    else _subject_slug(subj.name)
                )
                # Mezon bo'lmasa tafsilot YOZILMAYDI — eski oqimdagi kabi.
                # Aks holda Excel'da "1-40-savollarga 1 balldan..." degan
                # sun'iy sarlavha chiqib, mezonsiz fan ham mezonli
                # ko'rinishga o'tib ketardi (oddiy "To'g'ri/Jami" o'rniga).
                if subj_detail:
                    detail[slot] = subj_detail
                if pos == 0:
                    row.math_correct, row.math_total = correct, count
                elif pos == 1:
                    row.english_correct, row.english_total = correct, count

                warn = f" ⚠️{len(subj.multi)}ta ko'p belgilangan" if subj.multi else ""
                ball = f" ({fmt_number(subj_score)} ball)" if subj_detail else ""
                per_subject.append(f"{subj.name}: {correct}/{count}{ball}{warn}")

            # Mezon bo'lsa — og'irlikli ball, bo'lmasa eskicha to'g'ri
            # javoblar soni (apply_rubric o'zi shunday qaytaradi).
            row.score = round(total_score, 2)
            row.percentage = (
                round(total_score / total_max * 100, 2) if total_max else None
            )
            row.detail = json.dumps(detail, ensure_ascii=False) if detail else None
            row.checked_at = datetime.utcnow()
            await session.commit()
            saved += 1
            checked_grades.add(row.grade)

        name = row.full_name or "-"
        jami = f"{total_correct}/{total_questions}"
        if has_rubric:
            jami += f" — **{fmt_number(total_score)}/{fmt_number(total_max)} ball**"
        lines.append(
            f"✅ {prefix}**{name}** ({result.ticket_no})\n"
            f"   {' | '.join(per_subject)}\n"
            f"   Jami: {jami}"
        )

    # Ball yozilgan bo'lsa — o'rinlarni qayta hisoblaymiz (eski
    # tekshiruvchidagi kabi, HAR SINF ichida alohida).
    if saved:
        try:
            async with async_session() as session:
                for grade in checked_grades:
                    await recalculate_olympiad_places(session, olympiad_id, grade)
                await session.commit()
        except Exception as e:
            logger.exception(f"Tekshiruvdan keyin reytingni hisoblashda xato: {e}")

    header = f"📷 Tekshirildi: {saved}/{total_pages} varaq\n\n"
    await status.edit_text(header + "\n".join(lines), parse_mode="Markdown")

    # Ustiga belgilangan varaqlar — admin qo'lda tekshirib chiqishi uchun.
    if annotated_pages:
        try:
            await _send_annotated_sheets(
                message, annotated_pages, f"olympiad_{olympiad_id}_tekshirilgan"
            )
        except Exception as e:
            logger.exception(f"Belgilangan PDF yig'ishda xato: {e}")
            await message.answer(
                "⚠️ Natijalar saqlandi, lekin belgilangan PDF tayyorlanmadi."
            )

    await message.answer(
        "Keyingi varaqni yuboring yoki \"❌ Bekor qilish\" bosing.",
        reply_markup=get_cancel_keyboard(),
    )


@router.message(OmrCheckStates.waiting_for_image)
async def omr_check_wrong_input(message: Message):
    await message.answer(
        "Iltimos, varaqning rasmini yoki faylini yuboring.",
        reply_markup=get_cancel_keyboard(),
    )



# Telegram bitta hujjatda 50 MB dan ko'pini qabul qilmaydi. Belgilangan
# varaq ~180 KB (JPEG) bo'lgani uchun ~280 sahifadan keyin fayl shu
# chegaradan oshib ketardi va JO'NATISH JIMGINA YIQILARDI. Shuning uchun
# fayl ehtiyot zaxira bilan bo'laklarga bo'linadi.
_ANNOT_PDF_MAX_BYTES = 40 * 1024 * 1024


async def _send_annotated_sheets(
    message: Message, pages: list[bytes], filename_base: str
) -> None:
    """Ustiga belgilangan varaqlarni PDF(lar) qilib jo'natadi."""
    chunks: list[list[bytes]] = []
    joriy: list[bytes] = []
    hajm = 0
    for p in pages:
        if joriy and hajm + len(p) > _ANNOT_PDF_MAX_BYTES:
            chunks.append(joriy)
            joriy, hajm = [], 0
        joriy.append(p)
        hajm += len(p)
    if joriy:
        chunks.append(joriy)

    izoh = (
        "🖍 Tekshirilgan varaqlar\n\n"
        "🟢 to'g'ri  🔴 noto'g'ri  🔵 to'g'ri javob qayerda edi"
    )
    for i, chunk in enumerate(chunks, 1):
        pdf_bytes = await asyncio.to_thread(build_annotated_pdf, chunk)
        nom = (
            f"{filename_base}.pdf"
            if len(chunks) == 1
            else f"{filename_base}_{i}.pdf"
        )
        cap = izoh if len(chunks) == 1 else f"{izoh}\n\n({i}/{len(chunks)}-qism)"
        await message.answer_document(
            BufferedInputFile(pdf_bytes, filename=nom), caption=cap
        )


class CheckinStates(StatesGroup):
    """Ishtirokchini qabul qilish (reception check-in) oqimi: bir marta
    vaqt/xona sozlanadi (yoki qayta sozlanadi), keyin ID kiritib navbat
    bilan qabul qilinadi (qarang: DECISIONS.md #26)."""

    waiting_for_time_slots = State()
    waiting_for_room_count = State()
    waiting_for_capacity_mode = State()
    waiting_for_uniform_capacity = State()
    waiting_for_custom_capacity = State()
    waiting_for_ticket_no = State()
    waiting_for_continue_confirm = State()
    waiting_for_slot_choice = State()
    waiting_for_room_choice = State()
    waiting_for_photo = State()


async def _enter_checkin_flow(
    message: Message,
    state: FSMContext,
    olympiad_id: int,
    return_menu: str | None,
    force_setup: bool = False,
) -> None:
    """Vaqt/xona sozlamasi bor-yo'qligini tekshiradi: bo'lmasa (yoki
    `force_setup=True` bo'lsa) sozlash oqimini boshlaydi, bo'lsa
    to'g'ridan-to'g'ri ID so'raydi."""
    async with async_session() as session:
        has_config = (
            await session.execute(
                select(OlympiadRoom.id)
                .where(OlympiadRoom.olympiad_id == olympiad_id)
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    await state.update_data(checkin_olympiad_id=olympiad_id, return_menu=return_menu)

    if force_setup or not has_config:
        await message.answer(
            "⏱ Ishtirokchini qabul qilish uchun avval vaqt oraliqlarini "
            "kiriting.\n\nHar bir qatorga bitta variant, masalan:\n"
            "8:00 - 9:30\n10:00 - 11:30",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(CheckinStates.waiting_for_time_slots)
        return

    await _prompt_for_ticket_no(message, state)


async def _prompt_for_ticket_no(message: Message, state: FSMContext) -> None:
    await message.answer(
        "🆔 Ishtirokchi ID raqamini kiriting (ruxsatnomadagi QR kod ostidagi "
        "raqam — to'liq holda yoki faqat oxirgi raqamlar qismini kiritsangiz "
        "ham bo'ladi):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(CheckinStates.waiting_for_ticket_no)


@router.message(OlympiadDetailStates.viewing, F.text == "✅ Ishtirokchini qabul qilish")
async def checkin_entry_from_detail(message: Message, state: FSMContext):
    """Admin/SuperAdmin Olimpiada tafsilotlaridan bosganda — olimpiada
    allaqachon tanlangan, olimpiad tanlash bosqichi kerak emas."""
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    await _enter_checkin_flow(
        message, state, olympiad_id, return_menu=f"olympiad_detail:{olympiad_id}"
    )


def _olympiad_checkin_pick_keyboard(olympiads) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=o.name, callback_data=f"checkin_pick_olymp:{o.id}"
                )
            ]
            for o in olympiads
        ]
    )


@router.message(F.text == "✅ Ishtirokchini qabul qilish")
async def checkin_entry_reception_home(message: Message, state: FSMContext):
    """Reception bosh ekranidan bosganda — avval qaysi olimpiada ekanini
    so'raymiz (Reception hech qachon Olimpiada tafsilotlariga kirmaydi,
    shuning uchun `detail_olympiad_id` unda hech qachon bo'lmaydi)."""
    chat_id = message.chat.id
    async with async_session() as session:
        if not await can_checkin(chat_id, session):
            return

        olympiads = (
            await session.execute(select(Olympiad).order_by(Olympiad.id.desc()))
        ).scalars().all()

    if not olympiads:
        await message.answer("Hali birorta ham olimpiada qo'shilmagan.")
        return

    await message.answer(
        "🏆 Qaysi olimpiada uchun ishtirokchi qabul qilasiz?",
        reply_markup=_olympiad_checkin_pick_keyboard(olympiads),
    )


@router.callback_query(F.data.startswith("checkin_pick_olymp:"))
async def checkin_pick_olympiad(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.from_user.id
    async with async_session() as session:
        if not await can_checkin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

    olympiad_id = int(callback.data.split(":")[1])
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _enter_checkin_flow(callback.message, state, olympiad_id, return_menu=None)


@router.message(OlympiadDetailStates.viewing, F.text == "⚙️ Qabul qilish sozlamalari")
async def checkin_setup_entry(message: Message, state: FSMContext):
    """Admin/SuperAdmin uchun — sozlamani istalgan vaqt qayta kiritish
    (Reception buni ko'rmaydi, faqat qabul qilish tugmasini ko'radi)."""
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    await _enter_checkin_flow(
        message,
        state,
        olympiad_id,
        return_menu=f"olympiad_detail:{olympiad_id}",
        force_setup=True,
    )


@router.message(CheckinStates.waiting_for_time_slots)
async def checkin_process_time_slots(message: Message, state: FSMContext):
    lines = [ln.strip() for ln in (message.text or "").splitlines() if ln.strip()]
    if not lines:
        await message.answer(
            "Kamida bitta vaqt oralig'i kiriting:", reply_markup=get_cancel_keyboard()
        )
        return
    if len(lines) > 20:
        await message.answer(
            "Juda ko'p variant (20 tadan oshmasin). Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    too_long = next((ln for ln in lines if len(ln) > 50), None)
    if too_long:
        await message.answer(
            f"«{too_long}» juda uzun (50 belgidan oshmasin). Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(checkin_time_slots=lines)
    await message.answer(
        "🚪 Jami nechta xona bor? (butun son kiriting):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(CheckinStates.waiting_for_room_count)


@router.message(CheckinStates.waiting_for_room_count)
async def checkin_process_room_count(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 50):
        await message.answer(
            "Iltimos, 1 dan 50 gacha butun son kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(checkin_room_count=int(raw))
    await message.answer(
        "Hamma xonaning sig'imi bir xilmi?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Ha", callback_data="checkin_cap_uniform:yes"
                    ),
                    InlineKeyboardButton(
                        text="❌ Yo'q", callback_data="checkin_cap_uniform:no"
                    ),
                ]
            ]
        ),
    )
    await state.set_state(CheckinStates.waiting_for_capacity_mode)


@router.callback_query(
    CheckinStates.waiting_for_capacity_mode, F.data.startswith("checkin_cap_uniform:")
)
async def checkin_process_capacity_mode(callback: CallbackQuery, state: FSMContext):
    uniform = callback.data.split(":")[1] == "yes"
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if uniform:
        await callback.message.answer(
            "Xonalarning sig'imini kiriting (bitta son, hammasiga qo'llanadi):",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(CheckinStates.waiting_for_uniform_capacity)
        return

    data = await state.get_data()
    n = data["checkin_room_count"]
    await callback.message.answer(
        f"Har bir xona (yoki xonalar guruhi) uchun sig'imni kiriting — har "
        f"qatorga bittadan, 1 dan {n} gacha HAMMASI qamrab olinishi kerak. "
        f"Masalan:\n\n1 - xona 15\n2-xona 16\n3, 4, 5 - xonalar 20",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(CheckinStates.waiting_for_custom_capacity)


@router.message(CheckinStates.waiting_for_uniform_capacity)
async def checkin_process_uniform_capacity(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 1000):
        await message.answer(
            "Iltimos, 1 dan 1000 gacha butun son kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    capacity = int(raw)
    data = await state.get_data()
    n = data["checkin_room_count"]
    room_capacities = {i: capacity for i in range(1, n + 1)}
    await _save_checkin_config_and_continue(message, state, room_capacities)


_ROOM_CAPACITY_LINE_RE = re.compile(
    r"^\s*(\d[\d,\s]*?)\s*-\s*xona\w*\s+(\d+)\s*$", re.IGNORECASE
)


def _parse_room_capacity_text(
    raw_text: str, room_count: int
) -> tuple[dict[int, int] | None, str | None]:
    """Erkin matnni {xona_raqami: sig'im} lug'atiga aylantiradi.

    Har qator: "<raqam[, raqam...]> - xona(lar) <sig'im>" (masalan
    "3, 4, 5 - xonalar 20"). Xato bo'lsa (None, xabar), muvaffaqiyatli
    bo'lsa (lug'at, None) qaytaradi.
    """
    result: dict[int, int] = {}
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    if not lines:
        return None, "Kamida bitta qator kiriting."

    for ln in lines:
        m = _ROOM_CAPACITY_LINE_RE.match(ln)
        if not m:
            return None, (
                f"«{ln}» qatorini tushuna olmadim. Namuna: «1 - xona 15» "
                f"yoki «3, 4, 5 - xonalar 20»."
            )
        room_nums_txt, capacity_txt = m.groups()
        capacity = int(capacity_txt)
        for part in room_nums_txt.split(","):
            part = part.strip()
            if not part.isdigit():
                return None, f"«{ln}» qatoridagi xona raqamini tushuna olmadim."
            room_num = int(part)
            if not (1 <= room_num <= room_count):
                return None, (
                    f"{room_num}-xona mavjud emas (jami {room_count} ta xona bor)."
                )
            if room_num in result:
                return None, f"{room_num}-xona uchun sig'im bir necha marta kiritildi."
            result[room_num] = capacity

    missing = [i for i in range(1, room_count + 1) if i not in result]
    if missing:
        return None, (
            f"Quyidagi xonalar uchun sig'im kiritilmadi: "
            f"{', '.join(map(str, missing))}."
        )

    return result, None


@router.message(CheckinStates.waiting_for_custom_capacity)
async def checkin_process_custom_capacity(message: Message, state: FSMContext):
    data = await state.get_data()
    n = data["checkin_room_count"]
    room_capacities, error = _parse_room_capacity_text(message.text or "", n)
    if error:
        await message.answer(
            f"❌ {error}\n\nQaytadan kiriting:", reply_markup=get_cancel_keyboard()
        )
        return
    await _save_checkin_config_and_continue(message, state, room_capacities)


async def _save_checkin_config_and_continue(
    message: Message, state: FSMContext, room_capacities: dict[int, int]
) -> None:
    """Vaqt/xona sozlamasini saqlaydi (qayta sozlansa — eskisi o'chirilib,
    ALLAQACHON shu xona/vaqtga belgilangan ishtirokchilarning `room_id`/
    `time_slot_id`si aniq NULL qilinadi, `attended_at`/ishtirokchi holati
    esa saqlanib qoladi — qarang: database/models.py -> OlympiadResult,
    DECISIONS.md #26)."""
    data = await state.get_data()
    olympiad_id = data["checkin_olympiad_id"]
    time_slots = data["checkin_time_slots"]

    async with async_session() as session:
        old_slot_ids = (
            await session.execute(
                select(OlympiadTimeSlot.id).where(
                    OlympiadTimeSlot.olympiad_id == olympiad_id
                )
            )
        ).scalars().all()
        old_room_ids = (
            await session.execute(
                select(OlympiadRoom.id).where(OlympiadRoom.olympiad_id == olympiad_id)
            )
        ).scalars().all()

        if old_slot_ids:
            await session.execute(
                update(OlympiadResult)
                .where(OlympiadResult.time_slot_id.in_(old_slot_ids))
                .values(time_slot_id=None)
            )
            await session.execute(
                delete(OlympiadTimeSlot).where(
                    OlympiadTimeSlot.olympiad_id == olympiad_id
                )
            )
        if old_room_ids:
            await session.execute(
                update(OlympiadResult)
                .where(OlympiadResult.room_id.in_(old_room_ids))
                .values(room_id=None)
            )
            await session.execute(
                delete(OlympiadRoom).where(OlympiadRoom.olympiad_id == olympiad_id)
            )

        for i, label in enumerate(time_slots, 1):
            session.add(
                OlympiadTimeSlot(olympiad_id=olympiad_id, position=i, label=label)
            )
        for room_num, capacity in sorted(room_capacities.items()):
            session.add(
                OlympiadRoom(
                    olympiad_id=olympiad_id, room_number=room_num, capacity=capacity
                )
            )
        await session.commit()

    await message.answer("✅ Vaqt/xona sozlamasi saqlandi.")
    await _prompt_for_ticket_no(message, state)


@router.message(CheckinStates.waiting_for_ticket_no)
async def checkin_process_ticket_no(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    data = await state.get_data()
    olympiad_id = data["checkin_olympiad_id"]

    if is_valid_ticket_no(raw):
        # To'liq ID (masalan SA-2026-PMT-0001019) — aniq mos kelishi kerak.
        lookup_filter = OlympiadResult.ticket_no == raw.upper()
    elif raw.isdigit() and 7 <= len(raw) <= 15:
        # Faqat oxirgi (tartib raqami + nazorat raqami) qismi kiritilgan —
        # reception butun "SA-{yil}-{kod}-" prefiksini yozmasdan, ruxsatnoma/
        # javob varag'idagi QR ostidagi raqamlarni to'g'ridan-to'g'ri
        # kiritishi mumkin. Bu qism build_ticket_no'da OlympiadResult.id
        # asosida hosil qilingani uchun (utils/qr_payload.py) allaqachon
        # o'zi global yagona; "-<raqamlar>" bilan TUGASHI shart qilib
        # qidirilsa (oddiy pastki-satr izlash emas), boshqa (masalan
        # kattaroq id'li) yozuvning ICHKARISIDAGI raqamlar ketma-ketligi
        # bilan tasodifan chalkashib ketmaydi.
        lookup_filter = OlympiadResult.ticket_no.endswith(f"-{raw}")
    else:
        await message.answer(
            "❌ ID raqami noto'g'ri formatda. To'liq ID (masalan "
            "SA-2026-PMT-0001019) yoki faqat oxirgi raqamlar qismini "
            "(masalan 0001019) kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    async with async_session() as session:
        row = (
            await session.execute(
                select(OlympiadResult, User)
                .join(User, OlympiadResult.user_id == User.id)
                .where(OlympiadResult.olympiad_id == olympiad_id, lookup_filter)
            )
        ).first()

        if not row:
            await message.answer(
                "❌ Bu ID bo'yicha ushbu olimpiadada ro'yxatdan o'tgan "
                "ishtirokchi topilmadi. Qaytadan kiriting:",
                reply_markup=get_cancel_keyboard(),
            )
            return

        result, user = row
        current_slot_label = None
        current_room_number = None
        if result.time_slot_id:
            slot = await session.get(OlympiadTimeSlot, result.time_slot_id)
            current_slot_label = slot.label if slot else None
        if result.room_id:
            room = await session.get(OlympiadRoom, result.room_id)
            current_room_number = room.room_number if room else None

        if result.first_name and result.last_name:
            ism, familiya = result.first_name, result.last_name
        else:
            ism, familiya = split_full_name(result.full_name or user.full_name)
        grade_txt = f"{result.grade}-sinf" if result.grade is not None else "-"
        result_id = result.id
        ticket_txt = result.ticket_no
        school_txt = result.school

    card_text = (
        f"👤 **{familiya} {ism}**\n"
        f"🏫 Maktab: {school_txt or '-'}\n"
        f"🎓 Sinf: {grade_txt}\n"
        f"🆔 ID: {ticket_txt}"
    )
    if current_slot_label or current_room_number:
        card_text += (
            f"\n\n⚠️ Bu ishtirokchi ALLAQACHON belgilangan: "
            f"{current_slot_label or '-'}, {current_room_number or '-'}-xona.\n"
            f"Davom etsangiz, YANGI vaqt/xona bilan ALMASHTIRILADI."
        )

    await state.update_data(checkin_result_id=result_id)
    await message.answer(
        card_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="➡️ Davom etish", callback_data="checkin_continue"
                    )
                ]
            ]
        ),
    )
    await state.set_state(CheckinStates.waiting_for_continue_confirm)


async def _show_slot_keyboard(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    olympiad_id = data["checkin_olympiad_id"]

    async with async_session() as session:
        slots = (
            await session.execute(
                select(OlympiadTimeSlot)
                .where(OlympiadTimeSlot.olympiad_id == olympiad_id)
                .order_by(OlympiadTimeSlot.position)
            )
        ).scalars().all()

    await message.answer(
        "⏱ Vaqtni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=s.label, callback_data=f"checkin_slot:{s.id}"
                    )
                ]
                for s in slots
            ]
        ),
    )
    await state.set_state(CheckinStates.waiting_for_slot_choice)


@router.callback_query(
    CheckinStates.waiting_for_continue_confirm, F.data == "checkin_continue"
)
async def checkin_continue_to_slot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _show_slot_keyboard(callback.message, state)


@router.callback_query(
    CheckinStates.waiting_for_slot_choice, F.data.startswith("checkin_slot:")
)
async def checkin_show_rooms(callback: CallbackQuery, state: FSMContext):
    slot_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    olympiad_id = data["checkin_olympiad_id"]
    result_id = data["checkin_result_id"]

    async with async_session() as session:
        rooms = (
            await session.execute(
                select(OlympiadRoom)
                .where(OlympiadRoom.olympiad_id == olympiad_id)
                .order_by(OlympiadRoom.room_number)
            )
        ).scalars().all()

        # Sig'im HAR (xona, vaqt) juftligi uchun alohida — shuning uchun
        # faqat shu slot_id bo'yicha hisoblanadi. O'zining eski yozuvi
        # (qayta belgilashda) hisobga OLINMAYDI — aks holda o'sha bitta
        # o'quvchi o'ziga o'zi "joy qoldirmagan" bo'lib chiqardi.
        counts_res = await session.execute(
            select(OlympiadResult.room_id, func.count(OlympiadResult.id))
            .where(
                OlympiadResult.olympiad_id == olympiad_id,
                OlympiadResult.time_slot_id == slot_id,
                OlympiadResult.room_id.isnot(None),
                OlympiadResult.id != result_id,
            )
            .group_by(OlympiadResult.room_id)
        )
        counts = dict(counts_res.all())

    available = [
        (r, counts.get(r.id, 0)) for r in rooms if counts.get(r.id, 0) < r.capacity
    ]

    await state.update_data(checkin_slot_id=slot_id)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not available:
        await callback.message.answer(
            "❌ Bu vaqt uchun barcha xonalar to'lgan. Boshqa vaqtni tanlang:"
        )
        await _show_slot_keyboard(callback.message, state)
        return

    await callback.message.answer(
        "🚪 Xonani tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{r.room_number}-xona ({cnt}/{r.capacity})",
                        callback_data=f"checkin_room:{r.id}",
                    )
                ]
                for r, cnt in available
            ]
        ),
    )
    await state.set_state(CheckinStates.waiting_for_room_choice)


@router.callback_query(
    CheckinStates.waiting_for_room_choice, F.data.startswith("checkin_room:")
)
async def checkin_pick_room(callback: CallbackQuery, state: FSMContext):
    """Xona tanlandi — endi ishtirokchining rasmi so'raladi.

    Vaqt/xona bazaga shu yerda emas, rasm kelganda (`_checkin_with_photo`)
    yoziladi: qabul qilingan har ishtirokchining rasmli ruxsatnomasi
    bo'lsin, rasm bosqichida bekor qilinsa qabul saqlanmasin (DECISIONS.md #39).
    """
    room_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    async with async_session() as session:
        result = await session.get(OlympiadResult, data["checkin_result_id"])
        has_photo = bool(result and result.photo_file_id)

    await state.update_data(checkin_room_id=room_id)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        "📷 Ishtirokchining rasmini yuboring — yuzi aniq ko'rinsin (shu yerning "
        "o'zida telefonda suratga olsa ham bo'ladi). Rasm ruxsatnomaga 3×4 "
        "ko'rinishda qo'yiladi.",
        reply_markup=get_cancel_keyboard(),
    )
    if has_photo:
        await callback.message.answer(
            "Bu ishtirokchining avval yuklangan rasmi bor.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🖼 Avvalgi rasm bilan davom etish",
                            callback_data="checkin_photo_reuse",
                        )
                    ]
                ]
            ),
        )
    await state.set_state(CheckinStates.waiting_for_photo)


@router.message(CheckinStates.waiting_for_photo, F.photo | F.document)
async def checkin_receive_photo(message: Message, state: FSMContext, bot: Bot):
    if message.document and not (message.document.mime_type or "").startswith("image/"):
        await message.answer(
            "❌ Bu fayl rasm emas. Ishtirokchining rasmini yuboring:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    await _checkin_with_photo(message, state, bot, file_id)


@router.callback_query(CheckinStates.waiting_for_photo, F.data == "checkin_photo_reuse")
async def checkin_reuse_photo(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    async with async_session() as session:
        result = await session.get(OlympiadResult, data["checkin_result_id"])
        file_id = result.photo_file_id if result else None

    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    if not file_id:
        await callback.message.answer(
            "❌ Avvalgi rasm topilmadi. Yangi rasm yuboring:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    await _checkin_with_photo(callback.message, state, bot, file_id)


@router.message(CheckinStates.waiting_for_photo)
async def checkin_photo_expected(message: Message):
    await message.answer(
        "📷 Ishtirokchining rasmini yuboring yoki \"❌ Bekor qilish\" bosing.",
        reply_markup=get_cancel_keyboard(),
    )


async def _checkin_with_photo(
    message: Message, state: FSMContext, bot: Bot, file_id: str
) -> None:
    """Rasmni yuklab oladi, qabulni saqlaydi va kirish ruxsatnomasini shu
    chatga (qabulxonaga) yuboradi.

    Rasm diskka yozilmaydi: baytlar xotirada 3x4 ga keltiriladi, bazaga
    faqat Telegram file_id yoziladi (DECISIONS.md #8, #39).
    """
    try:
        file_info = await bot.get_file(file_id)
        buf = await bot.download_file(file_info.file_path)
        photo_jpeg = await asyncio.to_thread(prepare_participant_photo, buf.read())
    except PhotoError as e:
        await message.answer(f"❌ {e}", reply_markup=get_cancel_keyboard())
        return
    except Exception as e:
        logger.exception(f"Ishtirokchi rasmini yuklashda xato: {e}")
        await message.answer(
            "❌ Rasmni yuklab bo'lmadi. Qaytadan yuboring:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    slot_id = data["checkin_slot_id"]
    room_id = data["checkin_room_id"]

    async with async_session() as session:
        result = await session.get(OlympiadResult, data["checkin_result_id"])
        if not result:
            await message.answer("❌ Yozuv topilmadi.")
            await _prompt_for_ticket_no(message, state)
            return
        olympiad = await session.get(Olympiad, result.olympiad_id)
        user = await session.get(User, result.user_id)
        slot = await session.get(OlympiadTimeSlot, slot_id)
        room = await session.get(OlympiadRoom, room_id)

        result.time_slot_id = slot_id
        result.room_id = room_id
        result.attended_at = datetime.utcnow()
        result.photo_file_id = file_id

        if result.first_name and result.last_name:
            ism, familiya = result.first_name, result.last_name
        else:
            ism, familiya = split_full_name(result.full_name or (user.full_name if user else ""))
        birth_date = result.birth_date or (user.birth_date if user else None)
        ctx = EntryPassContext(
            familiya=familiya,
            ism=ism,
            ticket_no=result.ticket_no or "",
            event_title=olympiad.name if olympiad else "",
            exam_date=(
                olympiad.exam_date.strftime("%d.%m.%Y")
                if olympiad and olympiad.exam_date
                else ""
            ),
            slot_label=slot.label if slot else "",
            room_number=str(room.room_number) if room else "",
            birth_date=birth_date.strftime("%d.%m.%Y") if birth_date else "",
            grade=f"{result.grade}-sinf" if result.grade is not None else "",
            school=result.school or "",
            teacher=result.teacher_name or "",
            phone=user.phone if user else "",
            photo_jpeg=photo_jpeg,
        )

        await session.commit()

    await message.answer(
        f"✅ **{familiya} {ism}** muvaffaqiyatli qabul qilindi!\n"
        f"⏱ {ctx.slot_label or '-'}\n"
        f"🚪 {ctx.room_number or '-'}-xona\n\n"
        f"🎫 Ruxsatnoma tayyorlanmoqda...",
        parse_mode="Markdown",
    )

    try:
        pdf_bytes, png_bytes = await generate_entry_pass(ctx)
    except TicketGenerationError as e:
        logger.exception(f"Kirish ruxsatnomasi generatsiyasida xato ({ctx.ticket_no}): {e}")
        await message.answer(
            "❌ Ishtirokchi qabul qilindi, lekin ruxsatnomani tayyorlashda texnik "
            "xatolik yuz berdi. Administratorga xabar berildi. Keyinroq ID'ni "
            "qayta kiritib, \"🖼 Avvalgi rasm bilan davom etish\" orqali qayta "
            "urinib ko'ring."
        )
        await notify_superadmins(
            bot,
            f"⚠️ Kirish ruxsatnomasi generatsiyasi ishlamadi.\n"
            f"ticket_no: {ctx.ticket_no}\nXato: {e}",
        )
    else:
        await message.answer_photo(
            BufferedInputFile(png_bytes, filename=f"{ctx.ticket_no}.png"),
            caption=f"🎫 {familiya} {ism} — {ctx.room_number or '-'}-xona, {ctx.slot_label or '-'}",
        )
        await message.answer_document(
            BufferedInputFile(pdf_bytes, filename=f"{ctx.ticket_no}_ruxsatnoma.pdf"),
            caption="Chop etish uchun — siqilmagan PDF (A4).",
        )

    await _prompt_for_ticket_no(message, state)


@router.message(OlympiadDetailStates.viewing, F.text == "📊 Natijalarni yuklab olish (Excel)")
async def export_olympiad_results(message: Message, state: FSMContext):
    """Avval qaysi sinf natijasini yuklab olishni so'raydi, so'ng faqat
    o'sha sinf uchun Excel tayyorlaydi (`export_results_for_grade`).
    """
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        grades = await get_olympiad_grades(session, olympiad_id)
        counts = await grade_counts(session, olympiad_id)

    if not counts:
        await message.answer("Bu olimpiadada hali ishtirokchi yo'q.")
        return

    # Olimpiadaga umuman sinf biriktirilmagan bo'lsa (hammasi sinfsiz) —
    # so'rashning ma'nosi yo'q, to'g'ridan-to'g'ri eksport qilamiz.
    if not grades and set(counts) == {None}:
        await _send_results_excel(message, olympiad_id, grade=None)
        return

    barcha = sorted(set(grades) | {g for g in counts if g is not None})
    rows = [
        [
            InlineKeyboardButton(
                text=f"{g}-sinf ({counts.get(g, 0)} ta)",
                callback_data=f"export_res_grade:{olympiad_id}:{g}",
            )
        ]
        for g in barcha
    ]
    if None in counts:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Sinfsiz ({counts[None]} ta)",
                    callback_data=f"export_res_grade:{olympiad_id}:none",
                )
            ]
        )

    await message.answer(
        "📊 Qaysi sinf natijalarini Excel qilib yuklab olasiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("export_res_grade:"))
async def export_results_for_grade(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    _, olympiad_id_s, grade_s = callback.data.split(":")
    olympiad_id = int(olympiad_id_s)
    grade = None if grade_s == "none" else int(grade_s)

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

    await callback.answer()
    await _send_results_excel(callback.message, olympiad_id, grade)


# ---------------------------------------------------------------------------
# Natijalarni Excel'ga yozish — umumiy formatlovchi.
#
# Real maktab fayllarida (masalan "Asaka smart academy" tayyorlagan
# namuna) sarlavha ikki qatorli bo'ladi: fan nomi (Matematika/Ingliz tili)
# o'zining savol-oraliqlari ustida keng katak bo'lib turadi, har oraliq
# ostida "to'g'ri soni" va "ball" ustunlari bor. Bot ham natijalarni
# (PDF tekshiruvdan ham, Excel importdan ham) aynan shu ko'rinishda
# beradi — ustiga O'rin va Telegram Chat ID ustunlari qo'shilgan holda.
# ---------------------------------------------------------------------------

_SUBJECT_HEADER_FILL = PatternFill(
    start_color="FF00FF00", end_color="FF00FF00", fill_type="solid"
)
_BALL_TOTAL_HEADER_FILL = PatternFill(
    start_color="FFFFFF00", end_color="FFFFFF00", fill_type="solid"
)
# Quyidagi 3 rang haqiqiy maktab faylidan (theme rang + tint) matematik
# aniqlikda hisoblab olingan — o'zboshimchalik bilan tanlanmagan:
#   Sinf katagi     -> theme "Light 2" (EEECE1), tint -0.09998  -> #DDD9C3
#   Ball ustunlari  -> theme "Accent 1" (4F81BD), tint  0.59978 -> #B9CDE5 (moviy)
#   Foiz ustuni     -> theme "Accent 4" (8064A2), tint  0.39979 -> #B3A2C7 (och binafsha)
_SINF_HEADER_FILL = PatternFill(
    start_color="FFDDD9C3", end_color="FFDDD9C3", fill_type="solid"
)
_BALL_COL_HEADER_FILL = PatternFill(
    start_color="FFB9CDE5", end_color="FFB9CDE5", fill_type="solid"
)
_PERCENT_HEADER_FILL = PatternFill(
    start_color="FFB3A2C7", end_color="FFB3A2C7", fill_type="solid"
)
_RESULTS_HEADER_FONT = Font(bold=True)
_RESULTS_TITLE_FONT = Font(bold=True, size=13)
_RESULTS_HEADER_ALIGN = Alignment(
    horizontal="center", vertical="center", wrap_text=True
)


def _derive_points_per_q(rows: list[dict], detail_key: str, idx: int) -> float | None:
    """Savol boshiga ball qiymati alohida saqlanmagan (eski) yozuvlar
    uchun — shu oraliq (`idx`-o'rin) bo'yicha to'g'ri>0 bo'lgan birinchi
    qatordan `ball / to'g'ri` nisbatini hisoblab, mezonni tiklaydi.

    Bu hech qachon statik/qattiq kodlangan matn emas — har doim aynan
    shu natijalar to'plamidagi haqiqiy ball/to'g'ri nisbatidan olinadi.
    """
    for r in rows:
        detail = r.get(detail_key)
        if not detail or idx >= len(detail):
            continue
        d = detail[idx]
        correct, score = d.get("correct"), d.get("score")
        if correct and score is not None and correct > 0:
            return round(score / correct, 4)
    return None


def _subject_blocks(rows: list[dict], detail_key: str) -> list[dict]:
    """Sheet uchun bitta fan ustunlari tuzilishini aniqlaydi.

    Qatorlardan birontasida oraliq-tafsilot (`detail_key`) topilsa — o'sha
    oraliqlar tartibida qaytadi (savol boshiga necha ball berilgani ham,
    topilsa, saqlanadi — sarlavhaga to'liq yozish uchun). Agar mezon
    alohida saqlanmagan bo'lsa (eski, `points_per_q`siz yozuvlar) —
    `_derive_points_per_q()` orqali boshqa qatorlarning haqiqiy
    ball/to'g'ri nisbatidan tiklanadi, shuning uchun sarlavha hech qachon
    qotib qolgan (statik) matn bo'lmaydi — doim shu natijalarning o'ziga
    mos hisoblanadi. Hech qaysi qatorda tafsilot bo'lmasa (mezonsiz eski
    test yoki oddiy Excel) — bitta "hammasi" bloki (jami to'g'ri/jami
    savol) qaytadi.
    """
    for r in rows:
        detail = r.get(detail_key)
        if detail:
            blocks = []
            for idx, d in enumerate(detail):
                points = d.get("points_per_q")
                if points is None:
                    points = _derive_points_per_q(rows, detail_key, idx)
                blocks.append(
                    {
                        "label": d.get("range"),
                        "kind": "detail",
                        "points_per_q": points,
                        "total": d.get("total"),
                    }
                )
            return blocks
    return [{"label": None, "kind": "aggregate"}]


def _ball_header_text(block: dict) -> str:
    """"1-12-savollarga 1,1 balldan jami 13,2 ball" ko'rinishidagi to'liq
    tavsif — savol boshiga ball va shu oraliqning maksimal balli bilan.
    Bu ma'lumot (mezon) yo'q bo'lsa, qisqa "{oraliq}-ball" ga tushadi.
    """
    points = block.get("points_per_q")
    total = block.get("total")
    if points is not None and total is not None:
        max_score = fmt_number(points * total)
        return f"{block['label']}-savollarga {fmt_number(points)} balldan jami {max_score} ball"
    return f"{block['label']}-ball"


def _write_results_sheet(
    ws,
    rows: list[dict],
    title: str,
    subject_labels: tuple[str, str] = ("Matematika", "Ingliz tili"),
) -> None:
    """`rows` — har biri quyidagi kalitlarga ega lug'at:

    no, name, grade, place, chat_id,
    math_detail (list[dict]|None), math_correct, math_total,
    eng_detail (list[dict]|None), english_correct, english_total,
    score, percentage

    `title` — eng tepadagi qatorga yoziladigan sarlavha (masalan
    "3-sinf natijalari"), haqiqiy maktab fayllaridagi naqshga o'xshab.

    `subject_labels` — ikkita fan ustuni sarlavhasi. Standart qiymat eski
    (Test/Excel) oqimlari uchun, olimpiada natijalarida esa javob varag'i
    sozlamasidagi HAQIQIY fan nomlari uzatiladi (DECISIONS.md #33).
    Ustun ichidagi oraliq sarlavhalari ("1-12-savollarga 1,1 balldan...")
    allaqachon ma'lumotdan hisoblanadi — qarang: `_ball_header_text`.
    """
    math_blocks = _subject_blocks(rows, "math_detail")
    eng_blocks = _subject_blocks(rows, "eng_detail")

    fixed_headers = ["№", "F.I.Sh", "Sinf", "O'rin", "Telegram Chat ID"]
    fixed_fills = {2: _SINF_HEADER_FILL}  # 0-indeksli: "Sinf" — 3-ustun (index 2)
    col = len(fixed_headers) + 1
    math_start = col
    col += len(math_blocks) * 2
    eng_start = col
    col += len(eng_blocks) * 2
    ball_col = col
    percent_col = col + 1
    total_cols = percent_col

    # 1-qator: sarlavha (masalan "3-sinf natijalari"), butun jadval kengligida
    title_cell = ws.cell(1, 1, title)
    title_cell.font = _RESULTS_TITLE_FONT
    title_cell.alignment = _RESULTS_HEADER_ALIGN
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)

    HEADER_TOP = 2  # fan/guruh nomlari shu qatorda
    HEADER_SUB = 3  # savol-oraliq/ball tafsiloti shu qatorda
    DATA_START = 4

    for i, h in enumerate(fixed_headers, 1):
        c = ws.cell(HEADER_TOP, i, h)
        c.font = _RESULTS_HEADER_FONT
        c.alignment = _RESULTS_HEADER_ALIGN
        if (i - 1) in fixed_fills:
            c.fill = fixed_fills[i - 1]
        ws.merge_cells(
            start_row=HEADER_TOP, start_column=i, end_row=HEADER_SUB, end_column=i
        )

    def _subject_header(start: int, blocks: list[dict], label: str) -> None:
        end = start + len(blocks) * 2 - 1
        c = ws.cell(HEADER_TOP, start, label)
        c.font = _RESULTS_HEADER_FONT
        c.alignment = _RESULTS_HEADER_ALIGN
        c.fill = _SUBJECT_HEADER_FILL
        if end > start:
            ws.merge_cells(
                start_row=HEADER_TOP, start_column=start, end_row=HEADER_TOP, end_column=end
            )
        cc = start
        for b in blocks:
            if b["kind"] == "detail":
                t1, t2 = f"{b['label']}-savollar", _ball_header_text(b)
            else:
                t1, t2 = "To'g'ri", "Jami"
            w1 = ws.cell(HEADER_SUB, cc, t1)
            w1.font = _RESULTS_HEADER_FONT
            w1.alignment = _RESULTS_HEADER_ALIGN
            w2 = ws.cell(HEADER_SUB, cc + 1, t2)
            w2.font = _RESULTS_HEADER_FONT
            w2.alignment = _RESULTS_HEADER_ALIGN
            w2.fill = _BALL_COL_HEADER_FILL
            full_column_fills.append((cc + 1, _BALL_COL_HEADER_FILL))
            cc += 2

    # Sinf, Ball, Umumiy ball va Umumiy foiz ustunlari — faqat sarlavhasi
    # emas, butun ustun (ma'lumot qatorlari bilan birga) bo'yaladi. Boshqa
    # ustunlar (№, F.I.Sh, O'rin, ID, "to'g'ri soni", fan nomi) rangsiz
    # qoladi — bu yerda ro'yxat quriladi, pastda ma'lumot yozilgach
    # qo'llaniladi.
    full_column_fills: list[tuple[int, PatternFill]] = [(3, _SINF_HEADER_FILL)]

    _subject_header(math_start, math_blocks, subject_labels[0])
    _subject_header(eng_start, eng_blocks, subject_labels[1])

    for label, cidx, fill in (
        ("Umumiy ball", ball_col, _BALL_TOTAL_HEADER_FILL),
        ("Umumiy foiz (%)", percent_col, _PERCENT_HEADER_FILL),
    ):
        c = ws.cell(HEADER_TOP, cidx, label)
        c.font = _RESULTS_HEADER_FONT
        c.alignment = _RESULTS_HEADER_ALIGN
        c.fill = fill
        ws.merge_cells(
            start_row=HEADER_TOP, start_column=cidx, end_row=HEADER_SUB, end_column=cidx
        )
        full_column_fills.append((cidx, fill))

    ws.freeze_panes = f"A{DATA_START}"

    def _write_blocks(
        start_col: int, blocks: list[dict], detail, agg_correct, agg_total
    ) -> None:
        cc = start_col
        if detail:
            for d in detail:
                ws.cell(r, cc, d.get("correct") if d.get("correct") is not None else "-")
                ws.cell(
                    r, cc + 1, round(d["score"], 2) if d.get("score") is not None else "-"
                )
                cc += 2
        elif len(blocks) == 1 and blocks[0]["kind"] == "aggregate":
            # Butun sheet ham shu qatorlar uchun oraliqsiz (jami) rejimda —
            # to'g'ridan-to'g'ri yozamiz.
            ws.cell(r, cc, agg_correct if agg_correct is not None else "-")
            ws.cell(r, cc + 1, agg_total if agg_total is not None else "-")
        else:
            # Sheet boshqa qatorlar tufayli oraliqli, lekin BU qatorda
            # tafsilot yo'q — jamlangan sonni noto'g'ri ustunga yozib
            # chalg'itmaslik uchun bo'sh qoldiramiz.
            for _ in blocks:
                ws.cell(r, cc, "-")
                ws.cell(r, cc + 1, "-")
                cc += 2

    r = DATA_START
    for row in rows:
        ws.cell(r, 1, row["no"])
        ws.cell(r, 2, row["name"])
        ws.cell(r, 3, f"{row['grade']}-sinf" if row.get("grade") is not None else "-")
        ws.cell(r, 4, row["place"] if row.get("place") is not None else "-")
        ws.cell(r, 5, row["chat_id"])
        _write_blocks(
            math_start, math_blocks, row.get("math_detail"), row.get("math_correct"), row.get("math_total")
        )
        _write_blocks(
            eng_start, eng_blocks, row.get("eng_detail"), row.get("english_correct"), row.get("english_total")
        )
        ws.cell(r, ball_col, round(row["score"], 2) if row.get("score") is not None else "-")
        ws.cell(
            r, percent_col, round(row["percentage"], 2) if row.get("percentage") is not None else "-"
        )
        r += 1

    last_row = r - 1
    for col_idx, fill in full_column_fills:
        for rr in range(HEADER_TOP, last_row + 1):
            ws.cell(rr, col_idx).fill = fill

    for i in range(1, total_cols + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14


async def _send_results_excel(message: Message, olympiad_id: int, grade: int | None):
    """Bitta sinf (yoki `grade=None` bo'lsa — sinfsiz/hammasi) natijalarini
    Excel qilib tayyorlab yuboradi.
    """
    async with async_session() as session:
        o_res = await session.execute(
            select(Olympiad).where(Olympiad.id == olympiad_id)
        )
        olympiad = o_res.scalar_one_or_none()
        if not olympiad:
            await message.answer("Topilmadi.")
            return

        stmt = (
            select(OlympiadResult, User)
            .join(User, OlympiadResult.user_id == User.id)
            .where(OlympiadResult.olympiad_id == olympiad_id)
        )
        stmt = stmt.where(
            OlympiadResult.grade.is_(None) if grade is None else OlympiadResult.grade == grade
        )
        res = await session.execute(
            stmt.order_by(
                OlympiadResult.place.asc().nullslast(),
                OlympiadResult.score.desc().nullslast(),
            )
        )
        rows = res.all()

        # Ustun sarlavhalari uchun HAQIQIY fan nomlari (javob varag'i
        # sozlamasidan). Sozlanmagan bo'lsa — eski standart nomlar.
        subject_rows = await _load_subjects(session, olympiad_id)

    labels = tuple(s.name for s in subject_rows[:2])
    subject_labels = (
        labels + ("Matematika", "Ingliz tili")[len(labels):]
        if labels
        else ("Matematika", "Ingliz tili")
    )

    sinf_txt = f"{grade}-sinf" if grade is not None else "sinfsiz"
    if not rows:
        await message.answer(f"Bu olimpiadada {sinf_txt} ishtirokchi yo'q.")
        return

    sheet_rows = []
    for idx, (r, u) in enumerate(rows, 1):
        detail = {}
        if r.detail:
            try:
                detail = json.loads(r.detail)
            except (TypeError, ValueError):
                detail = {}
        sheet_rows.append(
            {
                "no": idx,
                "name": r.full_name or u.full_name,
                "grade": r.grade,
                "place": r.place,
                "chat_id": u.id,
                "math_detail": detail.get("matematika"),
                "math_correct": r.math_correct,
                "math_total": r.math_total,
                "eng_detail": detail.get("ingliz_tili"),
                "english_correct": r.english_correct,
                "english_total": r.english_total,
                "score": r.score,
                "percentage": r.percentage,
            }
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Natijalar"
    title = f"{grade}-sinf natijalari" if grade is not None else "Sinfsiz natijalar"
    _write_results_sheet(ws, sheet_rows, title, subject_labels)

    file_path = f"olympiad_{olympiad_id}_natijalari_{grade if grade is not None else 'sinfsiz'}.xlsx"
    wb.save(file_path)
    try:
        await message.answer_document(
            FSInputFile(file_path),
            caption=f"📊 **{olympiad.name}** — {sinf_txt} natijalari.",
            parse_mode="Markdown",
        )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


# ============================================================================
# OLIMPIADA NATIJALARINI EXCEL ORQALI YUKLASH
# ============================================================================
# Oqim: olimpiada -> sinf -> Excel -> tahlil/preview -> tasdiq -> yozish
#       -> noaniq qatorlarni admin bilan hal qilish -> yakuniy hisobot


async def _load_candidates(session, olympiad_id: int) -> NameIndex:
    """Olimpiadaga ro'yxatdan o'tganlarni bir marta o'qib, indeks quradi.

    Har Excel qatori uchun alohida so'rov yuborilsa, 5000 qatorli faylda
    10000+ so'rov bo'lardi. Shuning uchun ro'yxat bir marta olinadi va
    moslashtirish xotirada bajariladi.
    """
    rows = (
        await session.execute(
            select(
                OlympiadResult.id,
                OlympiadResult.user_id,
                OlympiadResult.full_name,
                OlympiadResult.school,
                OlympiadResult.grade,
                OlympiadResult.score,
                User.full_name,
                User.phone,
            )
            .join(User, OlympiadResult.user_id == User.id)
            .where(OlympiadResult.olympiad_id == olympiad_id)
        )
    ).all()

    candidates = [
        Candidate(
            result_id=r_id,
            user_id=u_id,
            full_name=(res_name or usr_name or ""),
            school=school,
            grade=grade,
            phone=phone,
            has_score=score is not None,
        )
        for r_id, u_id, res_name, school, grade, score, usr_name, phone in rows
    ]
    return NameIndex(candidates)


def _cand_dict(c: Candidate) -> dict:
    return {
        "result_id": c.result_id,
        "user_id": c.user_id,
        "full_name": c.full_name,
        "school": c.school,
        "grade": c.grade,
        "phone": c.masked_phone(),
    }


@router.message(OlympiadDetailStates.viewing, F.text == "📥 Natijalarni Excel orqali yuklash")
async def start_results_import(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        olympiad = (
            await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        ).scalar_one_or_none()
        if not olympiad:
            await message.answer("Olimpiada topilmadi.")
            return
        grades = await get_olympiad_grades(session, olympiad_id)

    await state.clear()
    await state.update_data(
        import_olympiad_id=olympiad_id,
        import_olympiad=olympiad.name,
        return_menu=f"olympiad_detail:{olympiad_id}",
    )

    if not grades:
        await state.update_data(import_grade=None)
        await message.answer(
            f"🏆 **{olympiad.name}**\n\n"
            f"Bu olimpiadaga sinf biriktirilmagan — natijalar sinfsiz yoziladi.\n\n"
            f"Excel faylini yuboring (.xlsx):",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(OlympiadResultsImportStates.waiting_for_excel)
        return

    rows = [
        [
            InlineKeyboardButton(
                text=f"{g}-sinf", callback_data=f"olymp_imp_grade:{olympiad_id}:{g}"
            )
        ]
        for g in grades
    ]
    await message.answer(
        f"🏆 **{olympiad.name}**\n\nQaysi sinf natijalarini yuklayapsiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await state.set_state(OlympiadResultsImportStates.waiting_for_grade)


@router.callback_query(
    OlympiadResultsImportStates.waiting_for_grade,
    F.data.startswith("olymp_imp_grade:"),
)
async def pick_import_grade(callback: CallbackQuery, state: FSMContext):
    _, _olymp, grade_s = callback.data.split(":")
    grade = int(grade_s)
    data = await state.get_data()

    await state.update_data(import_grade=grade)
    await callback.answer()
    await callback.message.edit_text(
        f"🏆 {data.get('import_olympiad', '')}\n📚 {grade}-sinf"
    )
    await callback.message.answer(
        f"Endi **{grade}-sinf** natijalari bo'lgan Excel faylni yuboring (.xlsx):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(OlympiadResultsImportStates.waiting_for_excel)


@router.message(OlympiadResultsImportStates.waiting_for_excel, F.document)
async def process_olympiad_results_excel(message: Message, state: FSMContext, bot):
    doc = message.document
    if not doc.file_name.lower().endswith((".xlsx", ".xls")):
        await message.answer(
            "⚠️ Iltimos, Excel fayl yuboring (.xlsx yoki .xls):",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    olympiad_id = data.get("import_olympiad_id")
    grade = data.get("import_grade")
    if not olympiad_id:
        await message.answer(
            "Jarayon eskirgan. Qaytadan boshlang.", reply_markup=get_admin_keyboard()
        )
        await state.clear()
        return

    status = await message.answer("⏳ Fayl yuklanmoqda...")
    path = f"olymp_import_{olympiad_id}_{uuid.uuid4().hex[:8]}.xlsx"
    try:
        file_info = await bot.get_file(doc.file_id)
        await bot.download_file(file_info.file_path, path)
        await status.edit_text("⏳ Excel o'qilmoqda...")
        # Katta fayl asosiy siklni bloklamasligi uchun alohida oqimda
        report = await asyncio.to_thread(parse_results_excel, path, grade)
    except ExcelStructureError as e:
        await status.edit_text(
            f"❌ Excel strukturasi aniqlanmadi.\n\n{e}\n\n"
            f"Faylda quyidagi ustunlar bo'lishi kerak:\n"
            f"• O'quvchining ismi va familiyasi\n"
            f"• umumiy ball\n"
            f"• (ixtiyoriy) Sinf, umumiy foiz"
        )
        await state.clear()
        await message.answer("Admin paneli:", reply_markup=get_admin_keyboard())
        return
    except Exception:
        logger.exception(f"Excel import: faylni o'qishda xato (olimpiada={olympiad_id})")
        await status.edit_text(
            "❌ Faylni o'qishda kutilmagan xatolik. Fayl buzilmaganini tekshiring."
        )
        await state.clear()
        await message.answer("Admin paneli:", reply_markup=get_admin_keyboard())
        return
    finally:
        if os.path.exists(path):
            os.remove(path)

    logger.info(
        "Excel import boshlandi: olimpiada=%s sinf=%s qatorlar=%s",
        olympiad_id,
        grade,
        len(report.rows),
    )
    await status.edit_text("⏳ O'quvchilar bilan solishtirilmoqda...")

    async with async_session() as session:
        index = await _load_candidates(session, olympiad_id)

    fresh, dupes, ambiguous, unmatched, bad_grade = [], [], [], [], []
    for row in report.rows:
        if row.score is None:
            unmatched.append(
                {"row": row.row_no, "name": row.full_name, "why": "ball yo'q",
                 "score": None, "percentage": None}
            )
            continue
        if grade is not None and row.grade is not None and row.grade != grade:
            bad_grade.append(
                {"row": row.row_no, "name": row.full_name, "grade": row.grade}
            )
            continue

        cands = index.find(row.full_name, grade if grade is not None else row.grade)
        if not cands:
            unmatched.append(
                {
                    "row": row.row_no,
                    "name": row.full_name,
                    "why": "ro'yxatda topilmadi",
                    "score": row.score,
                    "percentage": row.percentage,
                    "math_correct": row.math_correct,
                    "math_total": row.math_total,
                    "english_correct": row.english_correct,
                    "english_total": row.english_total,
                    "detail": row.detail,
                }
            )
        elif len(cands) == 1:
            item = {
                "result_id": cands[0].result_id,
                "user_id": cands[0].user_id,
                "name": row.full_name,
                "score": row.score,
                "percentage": row.percentage,
                "math_correct": row.math_correct,
                "math_total": row.math_total,
                "english_correct": row.english_correct,
                "english_total": row.english_total,
                "detail": row.detail,
            }
            (dupes if cands[0].has_score else fresh).append(item)
        else:
            ambiguous.append(
                {
                    "name": row.full_name,
                    "score": row.score,
                    "percentage": row.percentage,
                    "math_correct": row.math_correct,
                    "math_total": row.math_total,
                    "english_correct": row.english_correct,
                    "english_total": row.english_total,
                    "detail": row.detail,
                    "candidates": [_cand_dict(c) for c in cands],
                }
            )

    await state.update_data(
        imp_fresh=fresh,
        imp_dupes=dupes,
        imp_ambiguous=ambiguous,
        imp_unmatched=unmatched,
        imp_bad_grade=bad_grade,
        imp_total=len(report.rows),
    )
    await state.set_state(OlympiadResultsImportStates.waiting_for_confirm)

    sinf_txt = f"{grade}-sinf" if grade is not None else "sinfsiz"
    lines = [
        "📊 **Excel tahlili**",
        "",
        f"🏆 Olimpiada: {data.get('import_olympiad', '')}",
        f"📚 Sinf: {sinf_txt}",
        f"👥 Ro'yxatdan o'tganlar: {len(index)} ta",
        "",
        f"📄 Jami qator: {len(report.rows)}",
        f"✅ Yangi natija: {len(fresh)}",
    ]
    if dupes:
        lines.append(f"🔄 Natijasi bor (takror): {len(dupes)}")
    if ambiguous:
        lines.append(f"⚠️ Bir nechta nomzod: {len(ambiguous)}")
    if unmatched:
        lines.append(f"❌ Match topilmadi: {len(unmatched)}")
    if bad_grade:
        lines.append(f"🚫 Sinf mos emas: {len(bad_grade)}")

    if unmatched[:5]:
        lines.append("")
        lines.append("Topilmaganlar:")
        for u in unmatched[:5]:
            lines.append(f"  • {u['name']} ({u['why']})")
        if len(unmatched) > 5:
            lines.append(f"  • … va yana {len(unmatched) - 5} ta")

    lines.append("")
    lines.append("Natijalarni saqlashni boshlaymizmi?")

    await status.delete()
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Saqlash", callback_data="imp_apply")],
                [
                    InlineKeyboardButton(
                        text="❌ Bekor qilish", callback_data="imp_cancel"
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "imp_cancel")
async def cancel_import(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    olympiad_id = data.get("import_olympiad_id")
    await state.clear()
    await callback.answer("Bekor qilindi.")
    try:
        await callback.message.edit_text("Import bekor qilindi. Hech nima yozilmadi.")
    except Exception:
        pass
    if olympiad_id is not None:
        await _render_olympiad_detail(callback.message, state, olympiad_id)
    else:
        await callback.message.answer("Admin paneli:", reply_markup=get_admin_keyboard())


def _int_or_none(v) -> int | None:
    return None if v is None else int(v)


async def _write_result(session, result_id: int, item: dict, grade) -> bool:
    """Bitta natijani yozadi. True — yozildi.

    `item` — `score`/`percentage` bilan bir qatorda, topilgan bo'lsa
    `math_correct`/`math_total`/`english_correct`/`english_total`/`detail`
    (fan-oraliqlari bo'yicha to'liq tafsilot) ni ham olib keladi — Excel
    faylida bor bo'lgan hamma ma'lumot shu yerda saqlanadi, faqat
    umumiy ball emas.
    """
    r = (
        await session.execute(
            select(OlympiadResult).where(OlympiadResult.id == result_id)
        )
    ).scalar_one_or_none()
    if r is None:
        return False
    score = item.get("score")
    percentage = item.get("percentage")
    r.score = round(score, 2) if score is not None else None
    r.percentage = round(percentage, 2) if percentage is not None else None
    r.math_correct = _int_or_none(item.get("math_correct"))
    r.math_total = _int_or_none(item.get("math_total"))
    r.english_correct = _int_or_none(item.get("english_correct"))
    r.english_total = _int_or_none(item.get("english_total"))
    detail = item.get("detail")
    r.detail = json.dumps(detail, ensure_ascii=False) if detail else None
    if grade is not None and r.grade is None:
        r.grade = grade
    r.checked_at = datetime.utcnow()
    return True


@router.callback_query(
    OlympiadResultsImportStates.waiting_for_confirm, F.data == "imp_apply"
)
async def apply_import(callback: CallbackQuery, state: FSMContext):
    """Yangi natijalarni yozadi, keyin takrorlar siyosatini so'raydi."""
    data = await state.get_data()
    fresh = data.get("imp_fresh", [])
    dupes = data.get("imp_dupes", [])
    olympiad_id = data.get("import_olympiad_id")
    grade = data.get("import_grade")

    await callback.answer("Saqlanmoqda...")
    try:
        await callback.message.edit_text("⏳ Yangi natijalar saqlanmoqda...")
    except Exception:
        pass

    saved = failed = 0
    async with async_session() as session:
        for m in fresh:
            try:
                if await _write_result(
                    session, m["result_id"], m, grade
                ):
                    saved += 1
                else:
                    failed += 1
            except Exception:
                logger.exception("Import: qatorni saqlashda xato")
                failed += 1
        await session.commit()
        await recalculate_olympiad_places(session, olympiad_id, grade)
        await session.commit()

    await state.update_data(imp_saved=saved, imp_failed=failed)

    if dupes:
        await state.set_state(OlympiadResultsImportStates.dupes_policy)
        await callback.message.answer(
            f"🔄 **{len(dupes)} ta o'quvchida natija allaqachon bor.**\n\n"
            f"Nima qilamiz?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔄 Hammasini yangilash",
                            callback_data="imp_dup:all",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="⏭ Hammasini o'tkazib yuborish",
                            callback_data="imp_dup:none",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="👀 Bittalab ko'rib chiqaman",
                            callback_data="imp_dup:one",
                        )
                    ],
                ]
            ),
        )
        return

    await _after_dupes(callback.message, state)


@router.callback_query(
    OlympiadResultsImportStates.dupes_policy, F.data.startswith("imp_dup:")
)
async def dupes_policy(callback: CallbackQuery, state: FSMContext):
    policy = callback.data.split(":")[1]
    data = await state.get_data()
    dupes = data.get("imp_dupes", [])
    grade = data.get("import_grade")
    olympiad_id = data.get("import_olympiad_id")

    await callback.answer()

    if policy == "none":
        await state.update_data(imp_skipped_dupes=len(dupes))
        try:
            await callback.message.edit_text(
                f"⏭ {len(dupes)} ta takror o'tkazib yuborildi."
            )
        except Exception:
            pass
        await _after_dupes(callback.message, state)
        return

    if policy == "all":
        try:
            await callback.message.edit_text("⏳ Takrorlar yangilanmoqda...")
        except Exception:
            pass
        updated = 0
        async with async_session() as session:
            for m in dupes:
                if await _write_result(
                    session, m["result_id"], m, grade
                ):
                    updated += 1
            await session.commit()
            await recalculate_olympiad_places(session, olympiad_id, grade)
            await session.commit()
        await state.update_data(imp_updated=updated)
        await _after_dupes(callback.message, state)
        return

    # Bittalab ko'rib chiqish
    await state.update_data(imp_dup_index=0)
    await state.set_state(OlympiadResultsImportStates.resolving_dupes)
    await _show_dupe(callback.message, state)


async def _show_dupe(message: Message, state: FSMContext):
    """Bitta takror natijani eski/yangi bilan ko'rsatadi."""
    data = await state.get_data()
    dupes = data.get("imp_dupes", [])
    idx = data.get("imp_dup_index", 0)

    if idx >= len(dupes):
        await _after_dupes(message, state)
        return

    item = dupes[idx]
    async with async_session() as session:
        r = (
            await session.execute(
                select(OlympiadResult).where(OlympiadResult.id == item["result_id"])
            )
        ).scalar_one_or_none()
        eski = r.score if r is not None else None

    await message.answer(
        f"⚠️ **{item['name']}** uchun ushbu olimpiadada natija allaqachon mavjud.\n\n"
        f"Eski: **{fmt_number(eski)}**\n"
        f"Yangi: **{fmt_number(item['score'])}**\n\n"
        f"Nima qilamiz?  ({idx + 1}/{len(dupes)})",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Yangilash", callback_data="impd:up")],
                [
                    InlineKeyboardButton(
                        text="⏭ O'tkazib yuborish", callback_data="impd:skip"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Qolganini ham yangilash", callback_data="impd:rest_up"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⏭ Qolganini o'tkazib yuborish",
                        callback_data="impd:rest_skip",
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    OlympiadResultsImportStates.resolving_dupes, F.data.startswith("impd:")
)
async def resolve_dupe(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    dupes = data.get("imp_dupes", [])
    idx = data.get("imp_dup_index", 0)
    grade = data.get("import_grade")
    olympiad_id = data.get("import_olympiad_id")

    updated = data.get("imp_updated", 0)
    skipped = data.get("imp_skipped_dupes", 0)

    await callback.answer()

    qolgan = dupes[idx:] if action.startswith("rest") else dupes[idx : idx + 1]

    if action in ("up", "rest_up"):
        async with async_session() as session:
            for m in qolgan:
                if await _write_result(
                    session, m["result_id"], m, grade
                ):
                    updated += 1
            await session.commit()
            await recalculate_olympiad_places(session, olympiad_id, grade)
            await session.commit()
        matn = f"🔄 {len(qolgan)} ta yangilandi."
    else:
        skipped += len(qolgan)
        matn = f"⏭ {len(qolgan)} ta o'tkazib yuborildi."

    try:
        await callback.message.edit_text(matn)
    except Exception:
        pass

    yangi_idx = len(dupes) if action.startswith("rest") else idx + 1
    await state.update_data(
        imp_dup_index=yangi_idx, imp_updated=updated, imp_skipped_dupes=skipped
    )
    await _show_dupe(callback.message, state)


async def _after_dupes(message: Message, state: FSMContext):
    """Takrorlardan keyin — noaniq nomzodlarga o'tamiz."""
    data = await state.get_data()
    if data.get("imp_ambiguous"):
        await state.update_data(imp_amb_index=0, imp_amb_page=0)
        await state.set_state(OlympiadResultsImportStates.resolving)
        await _show_ambiguous(message, state)
        return
    await _offer_manual(message, state)


CANDS_PER_PAGE = 5


async def _show_ambiguous(message: Message, state: FSMContext):
    """Bir nechta nomzodli qatorni admin hal qilishi uchun ko'rsatadi.

    Nomzodlar ko'p bo'lsa sahifalab beriladi — bitta Telegram xabariga
    hammasini tiqib bo'lmaydi.
    """
    data = await state.get_data()
    ambiguous = data.get("imp_ambiguous", [])
    idx = data.get("imp_amb_index", 0)
    page = data.get("imp_amb_page", 0)

    if idx >= len(ambiguous):
        await _offer_manual(message, state)
        return

    item = ambiguous[idx]
    cands = item["candidates"]
    pages = max(1, (len(cands) + CANDS_PER_PAGE - 1) // CANDS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = cands[page * CANDS_PER_PAGE : (page + 1) * CANDS_PER_PAGE]

    lines = [
        f"⚠️ **«{item['name']}»** ismli {len(cands)} ta o'quvchi topildi.",
        "",
        f"📊 Excel'dagi ball: {fmt_number(item['score'])}",
        "",
        "Qaysi o'quvchiga biriktiramiz?",
        "",
    ]
    buttons = []
    for i, c in enumerate(chunk, page * CANDS_PER_PAGE + 1):
        lines.append(
            f"{i}. {c['full_name']}\n"
            f"     🏫 {c['school'] or '—'}\n"
            f"     📚 {c['grade'] or '—'}-sinf\n"
            f"     📱 {c['phone']}\n"
            f"     🆔 {c['user_id']}"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{i}. {c['full_name'][:24]} ({c['grade'] or '?'}-sinf)",
                    callback_data=f"imp_pick:{c['result_id']}",
                )
            ]
        )

    if pages > 1:
        buttons.append(
            [
                InlineKeyboardButton(text="◀️", callback_data="imp_amb_page:prev"),
                InlineKeyboardButton(
                    text=f"{page + 1}/{pages}", callback_data="imp_noop"
                ),
                InlineKeyboardButton(text="▶️", callback_data="imp_amb_page:next"),
            ]
        )
    buttons.append(
        [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="imp_skip")]
    )

    await state.update_data(imp_amb_page=page)
    await message.answer(
        "\n".join(lines) + f"\n\n({idx + 1}/{len(ambiguous)})",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data == "imp_noop")
async def imp_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(
    OlympiadResultsImportStates.resolving, F.data.startswith("imp_amb_page:")
)
async def imp_amb_page(callback: CallbackQuery, state: FSMContext):
    yonalish = callback.data.split(":")[1]
    data = await state.get_data()
    page = data.get("imp_amb_page", 0) + (1 if yonalish == "next" else -1)
    await state.update_data(imp_amb_page=page)
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_ambiguous(callback.message, state)


@router.callback_query(
    OlympiadResultsImportStates.resolving, F.data.startswith("imp_pick:")
)
async def resolve_ambiguous(callback: CallbackQuery, state: FSMContext):
    result_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    ambiguous = data.get("imp_ambiguous", [])
    idx = data.get("imp_amb_index", 0)
    grade = data.get("import_grade")

    if idx >= len(ambiguous):
        await callback.answer()
        await _offer_manual(callback.message, state)
        return

    item = ambiguous[idx]
    async with async_session() as session:
        await _write_result(
            session, result_id, item, grade
        )
        await session.commit()
        await recalculate_olympiad_places(session, data["import_olympiad_id"], grade)
        await session.commit()

    await callback.answer("Biriktirildi ✅")
    try:
        await callback.message.edit_text(
            f"✅ «{item['name']}» → biriktirildi (ball: {fmt_number(item['score'])})"
        )
    except Exception:
        pass

    await state.update_data(
        imp_amb_index=idx + 1,
        imp_amb_page=0,
        imp_resolved=data.get("imp_resolved", 0) + 1,
    )
    await _show_ambiguous(callback.message, state)


@router.callback_query(OlympiadResultsImportStates.resolving, F.data == "imp_skip")
async def skip_ambiguous(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = data.get("imp_amb_index", 0)
    await callback.answer("O'tkazib yuborildi")
    try:
        await callback.message.edit_text("⏭ O'tkazib yuborildi.")
    except Exception:
        pass
    await state.update_data(
        imp_amb_index=idx + 1,
        imp_amb_page=0,
        imp_skipped=data.get("imp_skipped", 0) + 1,
    )
    await _show_ambiguous(callback.message, state)


# ---------------------------------------------------------------- qo'lda qidirish


async def _offer_manual(message: Message, state: FSMContext):
    """Topilmagan qatorlar bo'lsa, qo'lda qidirishni taklif qiladi."""
    data = await state.get_data()
    unmatched = [u for u in data.get("imp_unmatched", []) if u.get("score") is not None]
    if not unmatched:
        await _finish_import(message, state)
        return

    await state.update_data(imp_manual_queue=unmatched, imp_manual_index=0)
    await state.set_state(OlympiadResultsImportStates.manual_offer)
    await message.answer(
        f"❌ **{len(unmatched)} ta o'quvchi ro'yxatdan topilmadi.**\n\n"
        f"Ularni qo'lda qidirib biriktirasizmi?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔎 Ha, qo'lda qidiraman", callback_data="imp_manual:yes"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⏭ Yo'q, hisobotni ko'rsat", callback_data="imp_manual:no"
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    OlympiadResultsImportStates.manual_offer, F.data.startswith("imp_manual:")
)
async def manual_offer(callback: CallbackQuery, state: FSMContext):
    javob = callback.data.split(":")[1]
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    if javob == "no":
        await _finish_import(callback.message, state)
        return
    await state.set_state(OlympiadResultsImportStates.manual_search)
    await _show_manual(callback.message, state)


async def _show_manual(message: Message, state: FSMContext):
    """Navbatdagi topilmagan o'quvchini ko'rsatadi va qidiruv so'raydi."""
    data = await state.get_data()
    queue = data.get("imp_manual_queue", [])
    idx = data.get("imp_manual_index", 0)

    if idx >= len(queue):
        await _finish_import(message, state)
        return

    item = queue[idx]
    await message.answer(
        f"❌ **Match topilmadi**  ({idx + 1}/{len(queue)})\n\n"
        f"Excel:\n"
        f"  Ism: {item['name']}\n"
        f"  Ball: {fmt_number(item['score'])}\n\n"
        f"🔎 O'quvchi nomini yozing (qismi ham bo'ladi) yoki tugmani bosing:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏭ O'tkazib yuborish", callback_data="imp_man_skip"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🛑 Qidirishni tugatish", callback_data="imp_man_stop"
                    )
                ],
            ]
        ),
    )


@router.message(OlympiadResultsImportStates.manual_search)
async def manual_search_query(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer("Kamida 2 ta belgi yozing:")
        return

    data = await state.get_data()
    async with async_session() as session:
        index = await _load_candidates(session, data["import_olympiad_id"])
    hits = index.search(query, limit=10)

    if not hits:
        await message.answer(
            f"«{query}» bo'yicha hech kim topilmadi. Boshqacha yozib ko'ring:"
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=f"{c.full_name[:24]} ({c.grade or '?'}-sinf)",
                callback_data=f"imp_man_pick:{c.result_id}",
            )
        ]
        for c in hits
    ]
    buttons.append(
        [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="imp_man_skip")]
    )

    lines = [f"🔎 «{query}» bo'yicha {len(hits)} ta natija:", ""]
    for i, c in enumerate(hits, 1):
        lines.append(
            f"{i}. {c.full_name}\n"
            f"     🏫 {c.school or '—'}  📚 {c.grade or '—'}-sinf\n"
            f"     📱 {c.masked_phone()}  🆔 {c.user_id}"
        )
    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(
    OlympiadResultsImportStates.manual_search, F.data.startswith("imp_man_pick:")
)
async def manual_pick(callback: CallbackQuery, state: FSMContext):
    result_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    queue = data.get("imp_manual_queue", [])
    idx = data.get("imp_manual_index", 0)
    grade = data.get("import_grade")

    if idx >= len(queue):
        await callback.answer()
        await _finish_import(callback.message, state)
        return

    item = queue[idx]
    async with async_session() as session:
        await _write_result(
            session, result_id, item, grade
        )
        await session.commit()
        await recalculate_olympiad_places(session, data["import_olympiad_id"], grade)
        await session.commit()

    await callback.answer("Biriktirildi ✅")
    try:
        await callback.message.edit_text(
            f"✅ «{item['name']}» → biriktirildi (ball: {fmt_number(item['score'])})"
        )
    except Exception:
        pass
    await state.update_data(
        imp_manual_index=idx + 1, imp_manual=data.get("imp_manual", 0) + 1
    )
    await _show_manual(callback.message, state)


@router.callback_query(
    OlympiadResultsImportStates.manual_search, F.data == "imp_man_skip"
)
async def manual_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await callback.answer("O'tkazib yuborildi")
    await state.update_data(imp_manual_index=data.get("imp_manual_index", 0) + 1)
    await _show_manual(callback.message, state)


@router.callback_query(
    OlympiadResultsImportStates.manual_search, F.data == "imp_man_stop"
)
async def manual_stop(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _finish_import(callback.message, state)


async def _finish_import(message: Message, state: FSMContext):
    """Yakuniy hisobot."""
    data = await state.get_data()
    grade = data.get("import_grade")
    sinf_txt = f"{grade}-sinf" if grade is not None else "sinfsiz"

    saved = data.get("imp_saved", 0)
    updated = data.get("imp_updated", 0)
    skipped_dupes = data.get("imp_skipped_dupes", 0)
    resolved = data.get("imp_resolved", 0)
    manual = data.get("imp_manual", 0)
    skipped = data.get("imp_skipped", 0)
    unmatched = data.get("imp_unmatched", [])
    bad_grade = data.get("imp_bad_grade", [])
    failed = data.get("imp_failed", 0)

    jami_yozildi = saved + updated + resolved + manual

    lines = [
        "✅ **Excel import tugadi**",
        "",
        f"🏆 Olimpiada: {data.get('import_olympiad', '')}",
        f"📚 Sinf: {sinf_txt}",
        "",
        f"📄 Jami qator: {data.get('imp_total', 0)}",
        f"✅ Yangi yozildi: {saved}",
    ]
    if updated:
        lines.append(f"🔄 Yangilandi: {updated}")
    if skipped_dupes:
        lines.append(f"⏭ Takror sifatida o'tkazildi: {skipped_dupes}")
    if resolved:
        lines.append(f"👤 Nomzodlardan tanlandi: {resolved}")
    if manual:
        lines.append(f"🔎 Qo'lda topildi: {manual}")
    if skipped:
        lines.append(f"⏭ O'tkazib yuborildi: {skipped}")
    if bad_grade:
        lines.append(f"🚫 Sinf mos emas: {len(bad_grade)}")
    if failed:
        lines.append(f"⚠️ Xatolik: {failed}")

    lines.append("")
    lines.append(f"📱 Telegram Chat ID topildi: {jami_yozildi}")
    lines.append(f"📞 Telefon bazadan olindi: {jami_yozildi}")
    lines.append("🏅 Reyting shu sinf ichida qayta hisoblandi.")

    qolgan = [
        u
        for u in unmatched
        if u.get("score") is not None
    ]
    if qolgan:
        lines.append("")
        lines.append("**Biriktirilmagan qatorlar:**")
        for u in qolgan[:15]:
            lines.append(f"  • {u['name']} — {u['why']}")
        if len(qolgan) > 15:
            lines.append(f"  • … va yana {len(qolgan) - 15} ta")

    if bad_grade:
        lines.append("")
        lines.append("**Sinf mos kelmadi:**")
        for b in bad_grade[:10]:
            lines.append(f"  • {b['name']} — Excel: {b['grade']}-sinf")

    logger.info(
        "Excel import tugadi: olimpiada=%s sinf=%s yozildi=%s yangilandi=%s "
        "nomzoddan=%s qolda=%s otkazildi=%s topilmadi=%s",
        data.get("import_olympiad_id"),
        grade,
        saved,
        updated,
        resolved,
        manual,
        skipped + skipped_dupes,
        len(unmatched),
    )

    await state.clear()
    await message.answer("\n".join(lines), parse_mode="Markdown")
    await message.answer("Admin paneli:", reply_markup=get_admin_keyboard())


# ---------------------------------------------------------------------------
# Excel orqali ro'yxatdan o'tkazish — natijalar-import oqimidan MUSTAQIL,
# undan oldin ishlatiladigan qadam. `olympiad_results`da hech kim yo'q bo'lsa
# ("Ro'yxatdan o'tganlar: 0 ta"), yuqoridagi natija-import hech kimni topa
# olmaydi — chunki u faqat shu olimpiadaga botda qo'lda ro'yxatdan o'tganlar
# bilan solishtiradi. Bu bo'lim esa Excel'dagi ismlarni BUTUN `users`
# jadvali bo'yicha qidirib, natijasiz OlympiadResult yaratib "ro'yxatdan
# o'tkazadi" — shundan keyin xuddi shu fayl natija-import oqimiga
# tashlanganda ism moslashadi. Yuqoridagi natija-import funksiyalari va
# services/*.py ga bu bo'lim tegmaydi, faqat ularni qayta ishlatadi.
# ---------------------------------------------------------------------------


async def _load_all_users_index(session) -> NameIndex:
    """Botdagi BARCHA foydalanuvchilar bo'yicha indeks (olimpiadaga
    ro'yxatdan o'tgan-o'tmaganidan qat'i nazar) — ro'yxatga olish shu
    ro'yxat bo'yicha ism qidiradi, `olympiad_results` emas.
    """
    rows = (await session.execute(select(User))).scalars().all()
    candidates = [
        Candidate(
            result_id=u.id,
            user_id=u.id,
            full_name=u.full_name,
            school=u.school,
            grade=u.grade,
            phone=u.phone,
            has_score=False,
        )
        for u in rows
    ]
    return NameIndex(candidates)


async def _registered_user_ids(session, olympiad_id: int) -> set[int]:
    """Import bu olimpiadada "o'zi uchun" yozilgan akkauntlar ro'yxati.

    Farzand nomidan yozilgan qatorlar (child_id to'ldirilgan) hisobga
    OLINMAYDI: ota-ona botdan farzandini yozdirgan bo'lsa ham, uning o'z
    yozuvi import orqali qo'shilishi mumkin (DECISIONS.md #41).
    """
    rows = (
        await session.execute(
            select(OlympiadResult.user_id).where(
                OlympiadResult.olympiad_id == olympiad_id,
                OlympiadResult.child_id.is_(None),
            )
        )
    ).scalars().all()
    return set(rows)


@router.message(OlympiadDetailStates.viewing, F.text == "📝 Excel orqali ro'yxatdan o'tkazish")
async def start_register_import(message: Message, state: FSMContext):
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        olympiad = (
            await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        ).scalar_one_or_none()
        if not olympiad:
            await message.answer("Olimpiada topilmadi.")
            return
        grades = await get_olympiad_grades(session, olympiad_id)

    await state.clear()
    await state.update_data(
        reg_olympiad_id=olympiad_id,
        reg_olympiad=olympiad.name,
        return_menu=f"olympiad_detail:{olympiad_id}",
    )

    if not grades:
        await state.update_data(reg_grade=None)
        await message.answer(
            f"📝 **{olympiad.name}** — Excel orqali ro'yxatdan o'tkazish\n\n"
            f"Bu olimpiadaga sinf biriktirilmagan — o'quvchilar sinfsiz "
            f"ro'yxatga olinadi.\n\nExcel faylini yuboring (.xlsx):",
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(OlympiadRegisterImportStates.waiting_for_excel)
        return

    rows = [
        [
            InlineKeyboardButton(
                text=f"{g}-sinf", callback_data=f"olymp_reg_grade:{olympiad_id}:{g}"
            )
        ]
        for g in grades
    ]
    await message.answer(
        f"📝 **{olympiad.name}** — Excel orqali ro'yxatdan o'tkazish\n\n"
        f"Qaysi sinf o'quvchilarini ro'yxatga olyapsiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await state.set_state(OlympiadRegisterImportStates.waiting_for_grade)


@router.callback_query(
    OlympiadRegisterImportStates.waiting_for_grade,
    F.data.startswith("olymp_reg_grade:"),
)
async def pick_register_grade(callback: CallbackQuery, state: FSMContext):
    _, _olymp, grade_s = callback.data.split(":")
    grade = int(grade_s)
    data = await state.get_data()

    await state.update_data(reg_grade=grade)
    await callback.answer()
    await callback.message.edit_text(
        f"📝 {data.get('reg_olympiad', '')}\n📚 {grade}-sinf"
    )
    await callback.message.answer(
        f"Endi **{grade}-sinf** o'quvchilari bo'lgan Excel faylni yuboring (.xlsx):",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(OlympiadRegisterImportStates.waiting_for_excel)


@router.message(OlympiadRegisterImportStates.waiting_for_excel, F.document)
async def process_register_excel(message: Message, state: FSMContext, bot):
    doc = message.document
    if not doc.file_name.lower().endswith((".xlsx", ".xls")):
        await message.answer(
            "⚠️ Iltimos, Excel fayl yuboring (.xlsx yoki .xls):",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    olympiad_id = data.get("reg_olympiad_id")
    grade = data.get("reg_grade")
    if not olympiad_id:
        await message.answer(
            "Jarayon eskirgan. Qaytadan boshlang.", reply_markup=get_admin_keyboard()
        )
        await state.clear()
        return

    status = await message.answer("⏳ Fayl yuklanmoqda...")
    path = f"olymp_register_{olympiad_id}_{uuid.uuid4().hex[:8]}.xlsx"
    try:
        file_info = await bot.get_file(doc.file_id)
        await bot.download_file(file_info.file_path, path)
        await status.edit_text("⏳ Excel o'qilmoqda...")
        report = await asyncio.to_thread(parse_results_excel, path, grade)
    except ExcelStructureError as e:
        await status.edit_text(
            f"❌ Excel strukturasi aniqlanmadi.\n\n{e}\n\n"
            f"Faylda quyidagi ustunlar bo'lishi kerak:\n"
            f"• O'quvchining ismi va familiyasi\n"
            f"• umumiy ball\n"
            f"• (ixtiyoriy) Sinf, umumiy foiz"
        )
        await state.clear()
        await message.answer("Admin paneli:", reply_markup=get_admin_keyboard())
        return
    except Exception:
        logger.exception(
            f"Ro'yxatga olish importi: faylni o'qishda xato (olimpiada={olympiad_id})"
        )
        await status.edit_text(
            "❌ Faylni o'qishda kutilmagan xatolik. Fayl buzilmaganini tekshiring."
        )
        await state.clear()
        await message.answer("Admin paneli:", reply_markup=get_admin_keyboard())
        return
    finally:
        if os.path.exists(path):
            os.remove(path)

    await status.edit_text("⏳ Bot foydalanuvchilari bilan solishtirilmoqda...")

    async with async_session() as session:
        index = await _load_all_users_index(session)
        already_ids = await _registered_user_ids(session, olympiad_id)

    fresh, already, ambiguous, unmatched, bad_grade = [], [], [], [], []
    for row in report.rows:
        if not row.full_name:
            continue
        if grade is not None and row.grade is not None and row.grade != grade:
            bad_grade.append(
                {"row": row.row_no, "name": row.full_name, "grade": row.grade}
            )
            continue

        cands = index.find(row.full_name, grade if grade is not None else row.grade)
        if not cands:
            unmatched.append({"row": row.row_no, "name": row.full_name})
        elif len(cands) == 1:
            c = cands[0]
            item = {
                "user_id": c.user_id,
                "name": c.full_name,
                "school": c.school,
                "grade": grade
                if grade is not None
                else (row.grade if row.grade is not None else c.grade),
            }
            (already if c.user_id in already_ids else fresh).append(item)
        else:
            ambiguous.append(
                {
                    "name": row.full_name,
                    "candidates": [
                        {**_cand_dict(c), "already": c.user_id in already_ids}
                        for c in cands
                    ],
                }
            )

    await state.update_data(
        reg_fresh=fresh,
        reg_already=len(already),
        reg_ambiguous=ambiguous,
        reg_unmatched=unmatched,
        reg_bad_grade=bad_grade,
        reg_total=len(report.rows),
    )
    await state.set_state(OlympiadRegisterImportStates.waiting_for_confirm)

    sinf_txt = f"{grade}-sinf" if grade is not None else "sinfsiz"
    lines = [
        "📊 **Excel tahlili (ro'yxatga olish)**",
        "",
        f"🏆 Olimpiada: {data.get('reg_olympiad', '')}",
        f"📚 Sinf: {sinf_txt}",
        "",
        f"📄 Jami qator: {len(report.rows)}",
        f"✅ Yangi ro'yxatga olinadi: {len(fresh)}",
    ]
    if already:
        lines.append(f"🔄 Allaqachon ro'yxatdan o'tgan: {len(already)}")
    if ambiguous:
        lines.append(f"⚠️ Bir nechta nomzod: {len(ambiguous)}")
    if unmatched:
        lines.append(f"❌ Botda topilmadi: {len(unmatched)}")
    if bad_grade:
        lines.append(f"🚫 Sinf mos emas: {len(bad_grade)}")

    if unmatched[:5]:
        lines.append("")
        lines.append("Botda topilmaganlar:")
        for u in unmatched[:5]:
            lines.append(f"  • {u['name']}")
        if len(unmatched) > 5:
            lines.append(f"  • … va yana {len(unmatched) - 5} ta")

    lines.append("")
    lines.append("Ro'yxatga olishni boshlaymizmi?")

    await status.delete()
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Ro'yxatga olish", callback_data="reg_apply"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Bekor qilish", callback_data="reg_cancel"
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "reg_cancel")
async def cancel_register_import(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    olympiad_id = data.get("reg_olympiad_id")
    await state.clear()
    await callback.answer("Bekor qilindi.")
    try:
        await callback.message.edit_text(
            "Ro'yxatga olish bekor qilindi. Hech nima yozilmadi."
        )
    except Exception:
        pass
    if olympiad_id is not None:
        await _render_olympiad_detail(callback.message, state, olympiad_id)
    else:
        await callback.message.answer("Admin paneli:", reply_markup=get_admin_keyboard())


async def _write_registration(
    session, olympiad_id: int, olympiad_code: str, item: dict
) -> bool:
    """Bitta o'quvchini ro'yxatga oladi. True — yozildi, False — allaqachon bor edi.

    Bot orqali yozilishdagi bilan bir xil: familiya/ism ajratiladi va
    ticket_no shu yerda (flush bilan id olib) beriladi -- aks holda
    import qilingan o'quvchi botdan o'z ruxsatnomasini darhol ola
    olmasdi (ticket_no faqat keyingi bot ishga tushishida to'ldirilardi).
    """
    # Import qilingan qator farzandga bog'lanmaydi (child_id bo'sh), shuning
    # uchun takrorlanish ham aynan shunday qatorlar ichida tekshiriladi: bitta
    # ota-ona botdan bir nechta farzandini yozdirgan bo'lishi mumkin
    # (DECISIONS.md #41), ular importga to'sqinlik qilmasligi kerak.
    existing = (
        await session.execute(
            select(OlympiadResult.id)
            .where(
                OlympiadResult.olympiad_id == olympiad_id,
                OlympiadResult.user_id == item["user_id"],
                OlympiadResult.child_id.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    first_name, last_name = split_full_name(item["name"])
    new_result = OlympiadResult(
        olympiad_id=olympiad_id,
        user_id=item["user_id"],
        full_name=item["name"],
        first_name=first_name,
        last_name=last_name,
        school=item.get("school"),
        grade=item.get("grade"),
    )
    session.add(new_result)
    await session.flush()
    new_result.ticket_no = build_ticket_no(
        datetime.utcnow().year, olympiad_code or "GEN", new_result.id
    )
    return True


@router.callback_query(
    OlympiadRegisterImportStates.waiting_for_confirm, F.data == "reg_apply"
)
async def apply_register_import(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    fresh = data.get("reg_fresh", [])
    olympiad_id = data.get("reg_olympiad_id")

    await callback.answer("Saqlanmoqda...")
    try:
        await callback.message.edit_text("⏳ Ro'yxatga olinmoqda...")
    except Exception:
        pass

    saved = 0
    async with async_session() as session:
        olympiad_code = (
            await session.execute(
                select(Olympiad.code).where(Olympiad.id == olympiad_id)
            )
        ).scalar_one_or_none()
        for item in fresh:
            try:
                if await _write_registration(session, olympiad_id, olympiad_code, item):
                    saved += 1
            except Exception:
                logger.exception("Ro'yxatga olish: qatorni saqlashda xato")
        await session.commit()

    await state.update_data(reg_saved=saved)
    await _after_reg_apply(callback.message, state)


async def _after_reg_apply(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("reg_ambiguous"):
        await state.update_data(reg_amb_index=0, reg_amb_page=0)
        await state.set_state(OlympiadRegisterImportStates.resolving)
        await _show_reg_ambiguous(message, state)
        return
    await _offer_reg_manual(message, state)


async def _show_reg_ambiguous(message: Message, state: FSMContext):
    data = await state.get_data()
    ambiguous = data.get("reg_ambiguous", [])
    idx = data.get("reg_amb_index", 0)
    page = data.get("reg_amb_page", 0)

    if idx >= len(ambiguous):
        await _offer_reg_manual(message, state)
        return

    item = ambiguous[idx]
    cands = item["candidates"]
    pages = max(1, (len(cands) + CANDS_PER_PAGE - 1) // CANDS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = cands[page * CANDS_PER_PAGE : (page + 1) * CANDS_PER_PAGE]

    lines = [
        f"⚠️ **«{item['name']}»** ismli {len(cands)} ta foydalanuvchi topildi.",
        "",
        "Qaysi foydalanuvchini ro'yxatga olamiz?",
        "",
    ]
    buttons = []
    for i, c in enumerate(chunk, page * CANDS_PER_PAGE + 1):
        holat = " (allaqachon ro'yxatdan o'tgan)" if c.get("already") else ""
        lines.append(
            f"{i}. {c['full_name']}{holat}\n"
            f"     🏫 {c['school'] or '—'}\n"
            f"     📚 {c['grade'] or '—'}-sinf\n"
            f"     📱 {c['phone']}\n"
            f"     🆔 {c['user_id']}"
        )
        if not c.get("already"):
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{i}. {c['full_name'][:24]} ({c['grade'] or '?'}-sinf)",
                        callback_data=f"reg_pick:{c['user_id']}",
                    )
                ]
            )

    if pages > 1:
        buttons.append(
            [
                InlineKeyboardButton(text="◀️", callback_data="reg_amb_page:prev"),
                InlineKeyboardButton(
                    text=f"{page + 1}/{pages}", callback_data="imp_noop"
                ),
                InlineKeyboardButton(text="▶️", callback_data="reg_amb_page:next"),
            ]
        )
    buttons.append(
        [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="reg_skip")]
    )

    await state.update_data(reg_amb_page=page)
    await message.answer(
        "\n".join(lines) + f"\n\n({idx + 1}/{len(ambiguous)})",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(
    OlympiadRegisterImportStates.resolving, F.data.startswith("reg_amb_page:")
)
async def reg_amb_page(callback: CallbackQuery, state: FSMContext):
    yonalish = callback.data.split(":")[1]
    data = await state.get_data()
    page = data.get("reg_amb_page", 0) + (1 if yonalish == "next" else -1)
    await state.update_data(reg_amb_page=page)
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_reg_ambiguous(callback.message, state)


@router.callback_query(
    OlympiadRegisterImportStates.resolving, F.data.startswith("reg_pick:")
)
async def resolve_reg_ambiguous(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    ambiguous = data.get("reg_ambiguous", [])
    idx = data.get("reg_amb_index", 0)
    grade = data.get("reg_grade")
    olympiad_id = data.get("reg_olympiad_id")

    if idx >= len(ambiguous):
        await callback.answer()
        await _offer_reg_manual(callback.message, state)
        return

    item = ambiguous[idx]
    picked = next((c for c in item["candidates"] if c["user_id"] == user_id), None)

    async with async_session() as session:
        registered = await _write_registration(
            session,
            olympiad_id,
            {
                "user_id": user_id,
                "name": picked["full_name"] if picked else item["name"],
                "school": picked.get("school") if picked else None,
                "grade": grade,
            },
        )
        await session.commit()

    await callback.answer("Ro'yxatga olindi ✅" if registered else "Allaqachon bor edi")
    try:
        nomi = picked["full_name"] if picked else user_id
        await callback.message.edit_text(f"✅ «{item['name']}» → {nomi} sifatida ro'yxatga olindi")
    except Exception:
        pass

    await state.update_data(
        reg_amb_index=idx + 1,
        reg_amb_page=0,
        reg_resolved=data.get("reg_resolved", 0) + (1 if registered else 0),
    )
    await _show_reg_ambiguous(callback.message, state)


@router.callback_query(OlympiadRegisterImportStates.resolving, F.data == "reg_skip")
async def skip_reg_ambiguous(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = data.get("reg_amb_index", 0)
    await callback.answer("O'tkazib yuborildi")
    try:
        await callback.message.edit_text("⏭ O'tkazib yuborildi.")
    except Exception:
        pass
    await state.update_data(reg_amb_index=idx + 1, reg_amb_page=0)
    await _show_reg_ambiguous(callback.message, state)


async def _offer_reg_manual(message: Message, state: FSMContext):
    data = await state.get_data()
    unmatched = data.get("reg_unmatched", [])
    if not unmatched:
        await _finish_reg_import(message, state)
        return

    await state.update_data(reg_manual_queue=unmatched, reg_manual_index=0)
    await state.set_state(OlympiadRegisterImportStates.manual_offer)
    await message.answer(
        f"❌ **{len(unmatched)} ta o'quvchi botda topilmadi.**\n\n"
        f"Ularni qo'lda qidirib ro'yxatga olasizmi?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔎 Ha, qo'lda qidiraman", callback_data="reg_manual:yes"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⏭ Yo'q, hisobotni ko'rsat", callback_data="reg_manual:no"
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    OlympiadRegisterImportStates.manual_offer, F.data.startswith("reg_manual:")
)
async def reg_manual_offer(callback: CallbackQuery, state: FSMContext):
    javob = callback.data.split(":")[1]
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    if javob == "no":
        await _finish_reg_import(callback.message, state)
        return
    await state.set_state(OlympiadRegisterImportStates.manual_search)
    await _show_reg_manual(callback.message, state)


async def _show_reg_manual(message: Message, state: FSMContext):
    data = await state.get_data()
    queue = data.get("reg_manual_queue", [])
    idx = data.get("reg_manual_index", 0)

    if idx >= len(queue):
        await _finish_reg_import(message, state)
        return

    item = queue[idx]
    await message.answer(
        f"❌ **Botda topilmadi**  ({idx + 1}/{len(queue)})\n\n"
        f"Excel: {item['name']}\n\n"
        f"🔎 Foydalanuvchi nomini yozing (qismi ham bo'ladi) yoki tugmani bosing:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⏭ O'tkazib yuborish", callback_data="reg_man_skip"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🛑 Qidirishni tugatish", callback_data="reg_man_stop"
                    )
                ],
            ]
        ),
    )


@router.message(OlympiadRegisterImportStates.manual_search)
async def reg_manual_search_query(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer("Kamida 2 ta belgi yozing:")
        return

    async with async_session() as session:
        index = await _load_all_users_index(session)
    hits = index.search(query, limit=10)

    if not hits:
        await message.answer(
            f"«{query}» bo'yicha hech kim topilmadi. Boshqacha yozib ko'ring:"
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=f"{c.full_name[:24]} ({c.grade or '?'}-sinf)",
                callback_data=f"reg_man_pick:{c.user_id}",
            )
        ]
        for c in hits
    ]
    buttons.append(
        [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="reg_man_skip")]
    )

    lines = [f"🔎 «{query}» bo'yicha {len(hits)} ta natija:", ""]
    for i, c in enumerate(hits, 1):
        lines.append(
            f"{i}. {c.full_name}\n"
            f"     🏫 {c.school or '—'}  📚 {c.grade or '—'}-sinf\n"
            f"     📱 {c.masked_phone()}  🆔 {c.user_id}"
        )
    await message.answer(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(
    OlympiadRegisterImportStates.manual_search, F.data.startswith("reg_man_pick:")
)
async def reg_manual_pick(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    queue = data.get("reg_manual_queue", [])
    idx = data.get("reg_manual_index", 0)
    grade = data.get("reg_grade")
    olympiad_id = data.get("reg_olympiad_id")

    if idx >= len(queue):
        await callback.answer()
        await _finish_reg_import(callback.message, state)
        return

    item = queue[idx]
    async with async_session() as session:
        user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        registered = await _write_registration(
            session,
            olympiad_id,
            {
                "user_id": user_id,
                "name": user.full_name if user else item["name"],
                "school": user.school if user else None,
                "grade": grade,
            },
        )
        await session.commit()

    await callback.answer("Ro'yxatga olindi ✅" if registered else "Allaqachon bor edi")
    try:
        await callback.message.edit_text(f"✅ «{item['name']}» → biriktirildi")
    except Exception:
        pass
    await state.update_data(
        reg_manual_index=idx + 1,
        reg_manual=data.get("reg_manual", 0) + (1 if registered else 0),
    )
    await _show_reg_manual(callback.message, state)


@router.callback_query(
    OlympiadRegisterImportStates.manual_search, F.data == "reg_man_skip"
)
async def reg_manual_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await callback.answer("O'tkazib yuborildi")
    await state.update_data(reg_manual_index=data.get("reg_manual_index", 0) + 1)
    await _show_reg_manual(callback.message, state)


@router.callback_query(
    OlympiadRegisterImportStates.manual_search, F.data == "reg_man_stop"
)
async def reg_manual_stop(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _finish_reg_import(callback.message, state)


async def _finish_reg_import(message: Message, state: FSMContext):
    data = await state.get_data()
    grade = data.get("reg_grade")
    sinf_txt = f"{grade}-sinf" if grade is not None else "sinfsiz"

    saved = data.get("reg_saved", 0)
    resolved = data.get("reg_resolved", 0)
    manual = data.get("reg_manual", 0)
    already = data.get("reg_already", 0)
    bad_grade = data.get("reg_bad_grade", [])
    unmatched = data.get("reg_unmatched", [])

    jami = saved + resolved + manual

    lines = [
        "✅ **Excel orqali ro'yxatga olish tugadi**",
        "",
        f"🏆 Olimpiada: {data.get('reg_olympiad', '')}",
        f"📚 Sinf: {sinf_txt}",
        "",
        f"📄 Jami qator: {data.get('reg_total', 0)}",
        f"✅ Yangi ro'yxatga olindi: {jami}",
    ]
    if already:
        lines.append(f"🔄 Allaqachon ro'yxatdan o'tgan edi: {already}")
    if bad_grade:
        lines.append(f"🚫 Sinf mos emas: {len(bad_grade)}")
    if unmatched:
        lines.append(f"❌ Botda umuman topilmadi: {len(unmatched)}")

    if unmatched:
        lines.append("")
        lines.append("**Botda topilmagan (hali /start bosmagan) o'quvchilar:**")
        for u in unmatched[:15]:
            lines.append(f"  • {u['name']}")
        if len(unmatched) > 15:
            lines.append(f"  • … va yana {len(unmatched) - 15} ta")

    if jami:
        lines.append("")
        lines.append(
            "➡️ Endi xuddi shu Excel faylni **📥 Natijalarni Excel orqali "
            "yuklash** tugmasi orqali yuklab, ballarni kiritishingiz mumkin."
        )

    logger.info(
        "Excel orqali ro'yxatga olish tugadi: olimpiada=%s sinf=%s yozildi=%s "
        "allaqachon=%s botda_topilmadi=%s",
        data.get("reg_olympiad_id"),
        grade,
        jami,
        already,
        len(unmatched),
    )

    await state.clear()
    await message.answer("\n".join(lines), parse_mode="Markdown")
    await message.answer("Admin paneli:", reply_markup=get_admin_keyboard())


@router.message(F.text == "👤 User qo'shish")
async def start_add_user(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        await state.update_data(return_menu="users_menu")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👤 Qo'lda kiritish",
                        callback_data="add_user_method:manual",
                    ),
                    InlineKeyboardButton(
                        text="📄 Excel orqali yuklash",
                        callback_data="add_user_method:excel",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Bekor qilish", callback_data="cancel_process"
                    )
                ],
            ]
        )
        await message.answer(
            "👤 **Foydalanuvchi qo'shish usulini tanlang:**\n\n"
            "• **Qo'lda kiritish**: Birma-bir ma'lumotlarni qo'lda kiritish.\n"
            "• **Excel orqali yuklash**: Ko'p sonli foydalanuvchilarni Excel fayldan ommaviy yuklash.",
            reply_markup=kb,
            parse_mode="Markdown",
        )


@router.callback_query(F.data == "add_user_method:manual")
async def add_user_manual(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "👤 Yangi foydalanuvchining **Telegram Chat ID** (10 xonali son) sini kiriting:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(UserCreationStates.waiting_for_id)


@router.callback_query(F.data == "add_user_method:excel")
async def add_user_excel_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "📄 **Excel orqali ommaviy foydalanuvchilarni qo'shish**\n\n"
        "Iltimos, `.xlsx` formatidagi faylni yuboring.\n\n"
        "**Fayldagi ustunlar tartibi (va sarlavhalari):**\n"
        "1. **ID / Chat ID** (Aynan 10 xonali raqam)\n"
        "2. **Ism Familiya**\n"
        "3. **Telefon raqam**\n"
        "4. **Maktab/O'quv Markazi**\n"
        "5. **Tug'ilgan sana** (YYYY-MM-DD formatida, masalan: `2008-04-12`)\n\n"
        "*(Eslatma: Birinchi qator sarlavha qatori deb hisoblanadi. Ma'lumotlar to'liq va to'g'ri bo'lishi shart!)*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(UserCreationStates.waiting_for_excel)


@router.message(UserCreationStates.waiting_for_id)
async def process_user_id(message: Message, state: FSMContext):
    id_str = (message.text or "").strip()
    if not id_str.isdigit() or len(id_str) != 10:
        await message.answer(
            "⚠️ Xato! Telegram Chat ID faqat raqamlardan iborat bo'lishi va aynan 10 ta raqam bo'lishi shart.\n"
            "Iltimos, qaytadan to'g'ri ID kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    user_id = int(id_str)
    async with async_session() as session:
        res = await session.execute(select(User).where(User.id == user_id))
        existing_user = res.scalar_one_or_none()
        if existing_user:
            await message.answer(
                f"⚠️ Ushbu ID dagi foydalanuvchi allaqachon ro'yxatdan o'tgan: **{existing_user.full_name}**\n"
                "Iltimos, boshqa ID kiriting yoki bekor qilish uchun pastdagi tugmani bosing:",
                reply_markup=get_cancel_keyboard(),
            )
            return

    await state.update_data(user_id=user_id)
    await message.answer(
        "✍️ Foydalanuvchining To'liq Ismi va Familiyasini kiriting:",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(UserCreationStates.waiting_for_full_name)


@router.message(UserCreationStates.waiting_for_full_name)
async def process_user_full_name(message: Message, state: FSMContext):
    full_name = (message.text or "").strip()
    if len(full_name) < 3:
        await message.answer(
            "⚠️ Ism juda qisqa. Iltimos, to'liqroq kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(full_name=full_name)
    await message.answer(
        "📞 Foydalanuvchining telefon raqamini kiriting (masalan: +998901234567):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(UserCreationStates.waiting_for_phone)


@router.message(UserCreationStates.waiting_for_phone)
async def process_user_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip()
    if len(phone) < 7:
        await message.answer(
            "⚠️ Telefon raqami xato kiritildi. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(phone=phone)
    await message.answer(
        "🏫 Foydalanuvchining maktabi yoki o'quv markazi nomini kiriting:",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(UserCreationStates.waiting_for_school)


@router.message(UserCreationStates.waiting_for_school)
async def process_user_school(message: Message, state: FSMContext):
    school = (message.text or "").strip()
    if len(school) < 2:
        await message.answer(
            "⚠️ Maktab nomi juda qisqa. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(school=school)
    await message.answer(
        "📅 Foydalanuvchining tug'ilgan sanasini kiriting (YYYY-MM-DD formatida, masalan: 2008-04-12):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(UserCreationStates.waiting_for_birth_date)


@router.message(UserCreationStates.waiting_for_birth_date)
async def process_user_birth_date(message: Message, state: FSMContext):
    date_str = (message.text or "").strip()
    try:
        birth_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await message.answer(
            "⚠️ Noto'g'ri format! Sanani YYYY-MM-DD ko'rinishida kiriting (masalan: 2008-04-12):",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    user_id = data["user_id"]
    full_name = data["full_name"]
    phone = data["phone"]
    school = data["school"]

    async with async_session() as session:
        new_user = User(
            id=user_id,
            full_name=full_name,
            phone=phone,
            school=school,
            birth_date=birth_date,
        )
        session.add(new_user)
        await session.commit()

    await message.answer(
        f"🎉 Yangi o'quvchi muvaffaqiyatli qo'shildi!\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"👤 F.I.SH: {full_name}\n"
        f"📞 Telefon: {phone}\n"
        f"🏫 Maktab/O'quv Markazi: {school}\n"
        f"📅 Tug'ilgan sana: {birth_date}",
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown",
    )
    await state.clear()


@router.message(UserCreationStates.waiting_for_excel, F.document)
async def process_user_excel_file(message: Message, state: FSMContext, bot):
    doc = message.document
    if not (
        doc.file_name.lower().endswith(".xlsx")
        or doc.file_name.lower().endswith(".xls")
    ):
        await message.answer("⚠️ Iltimos, faqat Excel (.xlsx) formatidagi fayl yuklang:")
        return

    status_msg = await message.answer(
        "📥 Excel fayl yuklab olinmoqda va tahlil qilinmoqda..."
    )

    file_info = await bot.get_file(doc.file_id)
    excel_path = f"temp_users_import_{message.chat.id}.xlsx"
    await bot.download_file(file_info.file_path, excel_path)

    try:
        wb = load_workbook(excel_path, data_only=True)
        sheet = wb.active
    except Exception as e:
        logger.error(f"Excel faylni yuklashda xatolik: {e}")
        await status_msg.edit_text(f"❌ Excel faylni o'qishda xatolik yuz berdi: {e}")
        if os.path.exists(excel_path):
            os.remove(excel_path)
        return

    max_row = sheet.max_row
    if max_row < 2:
        await status_msg.edit_text(
            "❌ Excel fayl bo'sh yoki unda ma'lumot qatorlari yo'q."
        )
        if os.path.exists(excel_path):
            os.remove(excel_path)
        return

    # Try mapping columns based on first row headers
    header_row = [
        str(cell.value).strip().lower() if cell.value is not None else ""
        for cell in sheet[1]
    ]

    col_id = None
    col_name = None
    col_phone = None
    col_school = None
    col_birth = None

    # Try keyword matches
    for col_idx, h in enumerate(header_row):
        h_clean = h.replace("_", "").replace(" ", "")
        if any(kw in h_clean for kw in ["id", "chat", "telegram", "kod"]):
            if col_id is None:
                col_id = col_idx
        elif any(
            kw in h_clean
            for kw in ["ism", "familiya", "fish", "fio", "name", "oquvchi", "student"]
        ):
            if col_name is None:
                col_name = col_idx
        elif any(kw in h_clean for kw in ["telefon", "phone", "tel", "aloqa"]):
            if col_phone is None:
                col_phone = col_idx
        elif any(kw in h_clean for kw in ["maktab", "school", "markaz"]):
            if col_school is None:
                col_school = col_idx
        elif any(kw in h_clean for kw in ["sana", "birth", "tugilgan"]):
            if col_birth is None:
                col_birth = col_idx

    # Fallbacks if not detected
    if col_id is None:
        col_id = 0
    if col_name is None:
        col_name = 1
    if col_phone is None:
        col_phone = 2
    if col_school is None:
        col_school = 3
    if col_birth is None:
        col_birth = 4

    # Perform strict validation on header bounds
    max_col_index = len(header_row) - 1
    if col_id > max_col_index or col_name > max_col_index:
        await status_msg.edit_text(
            "❌ **Xatolik: Yetarli ma'lumot ustunlari topilmadi!**\n\n"
            "Excel faylda kamida **ID** va **Ism Familiya** ustunlari bo'lishi va ular to'g'ri joylashgan bo'lishi shart.\n"
            "Iltimos, ustunlar joylashuvini yoki sarlavhalarini tekshiring."
        )
        if os.path.exists(excel_path):
            os.remove(excel_path)
        return

    success_count = 0
    errors = []

    async with async_session() as session:
        for row_num in range(2, max_row + 1):
            row_cells = [
                sheet.cell(row=row_num, column=col_num).value
                for col_num in range(1, len(header_row) + 1)
            ]

            if len(row_cells) <= max(col_id, col_name):
                errors.append(
                    f"Qator {row_num}: Ma'lumot yetarli emas (Ustunlar yetishmayapti)."
                )
                continue

            raw_id = row_cells[col_id]
            raw_name = row_cells[col_name]
            raw_phone = row_cells[col_phone] if col_phone < len(row_cells) else None
            raw_school = row_cells[col_school] if col_school < len(row_cells) else None
            raw_birth = row_cells[col_birth] if col_birth < len(row_cells) else None

            # Skip entirely empty rows
            if raw_id is None and raw_name is None:
                continue

            # 1. Parse and validate ID
            if raw_id is None:
                errors.append(f"Qator {row_num}: ID kiritilmagan.")
                continue

            id_str = str(raw_id).strip()
            if "." in id_str:
                id_str = id_str.split(".")[0]

            if not id_str.isdigit() or len(id_str) != 10:
                errors.append(
                    f"Qator {row_num}: ID xato ({raw_id}). ID roppa-rosa 10 ta raqam bo'lishi kerak."
                )
                continue

            user_id = int(id_str)

            # 2. Parse and validate Full Name
            if raw_name is None or not str(raw_name).strip():
                errors.append(
                    f"Qator {row_num} (ID: {user_id}): Ism-familiya kiritilmagan."
                )
                continue
            full_name = str(raw_name).strip()
            if len(full_name) < 3:
                errors.append(
                    f"Qator {row_num} (ID: {user_id}): Ism-familiya juda qisqa ('{full_name}')."
                )
                continue

            # 3. Parse and validate Phone
            phone = str(raw_phone).strip() if raw_phone is not None else ""
            if not phone:
                errors.append(
                    f"Qator {row_num} (ID: {user_id}): Telefon raqam kiritilmagan."
                )
                continue

            # 4. Parse and validate School
            school = str(raw_school).strip() if raw_school is not None else "Yo'q"
            if not school:
                school = "Yo'q"

            # 5. Parse and validate Birth Date
            birth_date = None
            if raw_birth is not None:
                if isinstance(raw_birth, (datetime, date)):
                    birth_date = (
                        raw_birth if isinstance(raw_birth, date) else raw_birth.date()
                    )
                else:
                    date_str = str(raw_birth).strip()
                    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y.%m.%d"):
                        try:
                            birth_date = datetime.strptime(date_str, fmt).date()
                            break
                        except ValueError:
                            continue

            if birth_date is None:
                errors.append(
                    f"Qator {row_num} (ID: {user_id}): Tug'ilgan sana formati xato yoki kiritilmagan ({raw_birth}). Format: YYYY-MM-DD bo'lishi kerak."
                )
                continue

            # Check if user already exists
            try:
                res = await session.execute(select(User).where(User.id == user_id))
                existing_user = res.scalar_one_or_none()
                if existing_user:
                    errors.append(
                        f"Qator {row_num} (ID: {user_id}): Foydalanuvchi dbda allaqachon mavjud."
                    )
                    continue

                # Add new user
                new_user = User(
                    id=user_id,
                    full_name=full_name,
                    phone=phone,
                    school=school,
                    birth_date=birth_date,
                )
                session.add(new_user)
                await session.commit()
                success_count += 1
            except Exception as db_err:
                await session.rollback()
                logger.error(f"Excel row {row_num} db error: {db_err}")
                errors.append(
                    f"Qator {row_num} (ID: {user_id}): Tizim xatosi ({db_err})"
                )

    # Cleanup Excel file
    if os.path.exists(excel_path):
        os.remove(excel_path)

    # Format result message
    res_msg = (
        f"📊 **Excel import natijalari:**\n\n"
        f"✅ Muvaffaqiyatli qo'shildi: **{success_count}** ta foydalanuvchi.\n"
        f"⚠️ Xatoliklar soni: **{len(errors)}** ta qator.\n\n"
    )

    if errors:
        res_msg += "❌ **Batafsil xatoliklar (dastlabki 15 tasi):**\n"
        for err in errors[:15]:
            res_msg += f"• {err}\n"
        if len(errors) > 15:
            res_msg += f"• ... va yana {len(errors) - 15} ta xatolik."

    await status_msg.delete()
    await message.answer(
        res_msg, reply_markup=get_admin_keyboard(), parse_mode="Markdown"
    )
    await state.clear()


# 5. DELETE USER FLOW
@router.message(F.text == "🗑 User o'chirish")
async def start_delete_user(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        await state.update_data(return_menu="users_menu")
        await message.answer(
            "🗑 O'chirmoqchi bo'lgan foydalanuvchining **ID** (Chat ID) raqamini yoki **Ismini** kiriting:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown",
        )
        await state.set_state(UserDeletionStates.waiting_for_query)


@router.message(UserDeletionStates.waiting_for_query)
async def process_delete_query(message: Message, state: FSMContext):
    query = (message.text or "").strip()

    async with async_session() as session:
        if query.isdigit():
            user_id = int(query)
            res = await session.execute(select(User).where(User.id == user_id))
            users = res.scalars().all()
        else:
            res = await session.execute(
                select(User).where(User.full_name.ilike(f"%{query}%"))
            )
            users = res.scalars().all()

        if not users:
            await message.answer(
                "❌ Hech qanday foydalanuvchi topilmadi. Amaliyot bekor qilindi.",
                reply_markup=get_admin_keyboard(),
            )
            await state.clear()
            return

        await message.answer(
            f"🔍 Jami {len(users)} ta mos keluvchi foydalanuvchi topildi.\n"
            f"O'chirish uchun pastdagi o'chirish tugmalaridan birini bosing:",
            reply_markup=get_admin_keyboard(),
        )

        for u in users[:10]:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"🗑 {u.full_name[:20]} ni o'chirish",
                            callback_data=f"delete_user:{u.id}",
                        )
                    ]
                ]
            )
            await message.answer(
                f"👤 **O'quvchi ma'lumotlari:**\n"
                f"🆔 ID: `{u.id}`\n"
                f"📝 F.I.SH: {u.full_name}\n"
                f"📞 Telefon: {u.phone}\n"
                f"🏫 Maktab: {u.school}\n"
                f"📅 Tug'ilgan sana: {u.birth_date}",
                reply_markup=kb,
                parse_mode="Markdown",
            )

        await state.clear()


@router.callback_query(F.data.startswith("delete_user:"))
async def confirm_delete_user(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

        user_id = int(callback.data.split(":")[1])

        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()

        await callback.answer("Foydalanuvchi tizimdan o'chirildi! 🗑", show_alert=True)
        await callback.message.edit_text(
            f"🗑 **Foydalanuvchi o'chirildi!**\nID: `{user_id}` bo'lgan foydalanuvchi ma'lumotlar bazasidan butunlay olib tashlandi.",
            reply_markup=None,
            parse_mode="Markdown",
        )


# 6. EDIT USER FLOW FOR ADMIN
@router.message(F.text == "✏️ User tahrirlash")
async def start_edit_user(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        await state.update_data(return_menu="users_menu")
        await message.answer(
            "✏️ Tahrirlamoqchi bo'lgan foydalanuvchining **ID** (Chat ID) raqamini yoki **Ismini** kiriting:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown",
        )
        await state.set_state(UserEditingStates.waiting_for_query)


@router.message(UserEditingStates.waiting_for_query)
async def process_edit_query(message: Message, state: FSMContext):
    query = (message.text or "").strip()

    async with async_session() as session:
        if query.isdigit():
            user_id = int(query)
            res = await session.execute(select(User).where(User.id == user_id))
            users = res.scalars().all()
        else:
            res = await session.execute(
                select(User).where(User.full_name.ilike(f"%{query}%"))
            )
            users = res.scalars().all()

        if not users:
            await message.answer(
                "❌ Hech qanday foydalanuvchi topilmadi. Amaliyot bekor qilindi.",
                reply_markup=get_admin_keyboard(),
            )
            await state.clear()
            return

        await message.answer(
            f"🔍 Jami {len(users)} ta mos keluvchi foydalanuvchi topildi.\n"
            f"Tahrirlash uchun pastdagi o'quvchi ma'lumotlari yonidagi tugmani bosing:",
            reply_markup=get_admin_keyboard(),
        )

        for u in users[:10]:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="👤 Ismni tahrirlash",
                            callback_data=f"adm_edit_usr:{u.id}:full_name",
                        ),
                        InlineKeyboardButton(
                            text="📱 Telefonni tahrirlash",
                            callback_data=f"adm_edit_usr:{u.id}:phone",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="🏫 Maktabni tahrirlash",
                            callback_data=f"adm_edit_usr:{u.id}:school",
                        ),
                        InlineKeyboardButton(
                            text="📅 Tug'ilgan sanani tahrirlash",
                            callback_data=f"adm_edit_usr:{u.id}:birth_date",
                        ),
                    ],
                ]
            )
            await message.answer(
                f"👤 **O'quvchi ma'lumotlari:**\n"
                f"🆔 ID: `{u.id}`\n"
                f"📝 F.I.SH: {u.full_name}\n"
                f"📞 Telefon: {u.phone}\n"
                f"🏫 Maktab: {u.school}\n"
                f"📅 Tug'ilgan sana: {u.birth_date}",
                reply_markup=kb,
                parse_mode="Markdown",
            )

        await state.clear()


@router.callback_query(F.data.startswith("adm_edit_usr:"))
async def admin_edit_user_callback(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

        parts = callback.data.split(":")
        target_user_id = int(parts[1])
        field = parts[2]

        await state.update_data(target_user_id=target_user_id, edit_field=field)
        await state.set_state(UserEditingStates.waiting_for_new_value)

        field_prompts = {
            "full_name": "yangi ism va familiyani kiriting (Masalan: Ali Valiyev):",
            "phone": "yangi telefon raqamini kiriting (Masalan: +998901234567):",
            "school": "yangi maktab yoki o'quv markazi nomini kiriting:",
            "birth_date": "yangi tug'ilgan sanani kiriting (Format: YYYY-MM-DD, Masalan: 2008-05-15):",
        }

        await callback.message.reply(
            f"✏️ Foydalanuvchi (ID: {target_user_id}) uchun {field_prompts.get(field, 'yangi qiymatni kiriting:')}",
            reply_markup=get_cancel_keyboard(),
        )
        await callback.answer()


@router.message(UserEditingStates.waiting_for_new_value)
async def process_admin_new_user_value(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    field = data.get("edit_field")
    new_val = (message.text or "").strip()

    if not new_val:
        await message.answer(
            "Qiymat matn ko'rinishida bo'lishi kerak. Iltimos, qaytadan kiriting:"
        )
        return

    # Validate inputs
    if field == "full_name":
        if len(new_val.split()) < 2:
            await message.answer(
                "Iltimos, ism va familiyani to'liq kiriting (kamida 2 ta so'z):"
            )
            return
    elif field == "phone":
        if len(new_val) < 7:
            await message.answer("Iltimos, haqiqiy telefon raqamini kiriting:")
            return
    elif field == "school":
        if len(new_val) < 3:
            await message.answer("Iltimos, maktab nomini to'g'riroq kiriting:")
            return
    elif field == "birth_date":
        try:
            birth_date_val = datetime.strptime(new_val, "%Y-%m-%d").date()
        except ValueError:
            await message.answer(
                "Sana formati noto'g'ri. Iltimos, YYYY-MM-DD formatida kiriting (Masalan: 2008-05-15):"
            )
            return

    async with async_session() as session:
        res = await session.execute(select(User).where(User.id == target_user_id))
        user = res.scalar_one_or_none()

        if not user:
            await message.answer(
                "Foydalanuvchi topilmadi. Amaliyot bekor qilindi.",
                reply_markup=get_admin_keyboard(),
            )
            await state.clear()
            return

        if field == "full_name":
            user.full_name = new_val
        elif field == "phone":
            user.phone = new_val
        elif field == "school":
            user.school = new_val
        elif field == "birth_date":
            user.birth_date = birth_date_val

        await session.commit()

        # Display updated user info
        updated_info = (
            f"✅ **Foydalanuvchi ma'lumotlari muvaffaqiyatli yangilandi!**\n\n"
            f"👤 **O'quvchi ma'lumotlari:**\n"
            f"🆔 ID: `{user.id}`\n"
            f"📝 F.I.SH: {user.full_name}\n"
            f"📞 Telefon: {user.phone}\n"
            f"🏫 Maktab: {user.school}\n"
            f"📅 Tug'ilgan sana: {user.birth_date}"
        )
        await message.answer(
            updated_info, reply_markup=get_admin_keyboard(), parse_mode="Markdown"
        )
        await state.clear()


# 7. BROADCAST / REKLAMA JO'NATISH FLOW
@router.message(F.text == "📢 Reklama jo'natish")
async def start_broadcast(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await can_broadcast(chat_id, session):
            return

        await message.answer(
            "📢 **Reklama yoki xabarni jo'natish bo'limi**\n\n"
            "Iltimos, barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring.\n"
            "Bu matn, rasm (tagida matni bilan) yoki boshqa turdagi xabar bo'lishi mumkin.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown",
        )
        await state.set_state(BroadcastStates.waiting_for_content)


@router.message(BroadcastStates.waiting_for_content)
async def process_broadcast_content(message: Message, state: FSMContext):
    chat_id = message.chat.id

    # Double check admin/smm privileges
    async with async_session() as session:
        if not await can_broadcast(chat_id, session):
            await state.clear()
            return
        kb = await get_role_keyboard(chat_id, session)

    # If sender sent cancel text
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Reklama jo'natish bekor qilindi.", reply_markup=kb)
        return

    status_msg = await message.answer(
        "⏳ Reklama barcha foydalanuvchilarga jo'natilmoqda, iltimos kuting..."
    )

    # Fetch all users
    async with async_session() as session:
        res = await session.execute(select(User.id))
        user_ids = res.scalars().all()

    if not user_ids:
        await status_msg.edit_text("❌ Ma'lumotlar bazasida foydalanuvchilar topilmadi.")
        await message.answer("Bosh menyu:", reply_markup=kb)
        await state.clear()
        return

    success_count = 0
    blocked_count = 0
    error_count = 0
    total = len(user_ids)

    for i, uid in enumerate(user_ids, 1):
        # Telegram bir sekundda ~30 ta xabardan ko'pini o'tkazmaydi. Cheklovsiz
        # yuborilsa 429 qaytadi va xabar umuman yetib bormaydi. Sekundiga ~20 ta
        # yuboramiz — chegaradan xavfsiz pastda.
        try:
            await message.copy_to(chat_id=uid)
            success_count += 1
        except TelegramRetryAfter as e:
            # Telegram aniq necha soniya kutishni aytadi — kutib, bir marta qayta uriamiz
            logger.warning(f"Reklama: Telegram {e.retry_after}s kutishni so'radi")
            await asyncio.sleep(e.retry_after + 1)
            try:
                await message.copy_to(chat_id=uid)
                success_count += 1
            except Exception as e2:
                logger.warning(f"Reklama yuborilmadi ({uid}): {e2}")
                error_count += 1
        except TelegramForbiddenError:
            # Foydalanuvchi botni bloklagan yoki chatni o'chirgan
            blocked_count += 1
        except Exception as e:
            logger.warning(f"Reklama yuborilmadi ({uid}): {e}")
            error_count += 1

        await asyncio.sleep(0.05)

        # Har 50 tada holatni yangilaymiz — admin jarayon ketayotganini ko'rib tursin
        if i % 50 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ Yuborilmoqda... {i}/{total}\n"
                    f"✅ {success_count}   🚫 {blocked_count}   ⚠️ {error_count}"
                )
            except Exception:
                pass

    try:
        await status_msg.delete()
    except Exception:
        pass

    report_text = (
        f"📢 **Reklama tarqatildi!** 🎉\n\n"
        f"✅ Yetkazildi: **{success_count}** ta\n"
        f"🚫 Botni bloklagan: **{blocked_count}** ta\n"
        f"⚠️ Boshqa sabab bilan yetmadi: **{error_count}** ta\n"
        f"👥 Jami: **{total}** ta"
    )
    await message.answer(report_text, reply_markup=kb, parse_mode="Markdown")
    await state.clear()


# ============================================================================
# ONLINE TEST (rasm + javob kaliti)
# ============================================================================


class OnlineTestCreationStates(StatesGroup):
    waiting_for_id = State()
    waiting_for_image = State()
    waiting_for_answers = State()


@router.message(F.text == "🧩 Test savol yaratish")
async def start_create_online_test(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

    await state.update_data(return_menu="online_tests")
    await message.answer(
        "🧩 **Online test yaratish**\n\n"
        "Avval test raqamini kiriting — o'quvchilar botga aynan shu raqamni "
        "kiritib testni oladi.\n\n"
        "Masalan: 101",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(OnlineTestCreationStates.waiting_for_id)


@router.message(OnlineTestCreationStates.waiting_for_id)
async def online_test_id(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(
            "Test raqami faqat sonlardan iborat bo'lishi kerak. Qayta kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    test_id = int(raw)
    if not (1 <= test_id <= 999999):
        await message.answer(
            "Raqam 1 va 999999 orasida bo'lsin. Qayta kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    async with async_session() as session:
        existing = (
            await session.execute(select(OnlineTest).where(OnlineTest.id == test_id))
        ).scalar_one_or_none()

    if existing:
        holat = "arxivda" if existing.archived else "faol"
        await message.answer(
            f"#{test_id} raqamli online test allaqachon mavjud ({holat}). "
            f"Boshqa raqam kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(online_test_id=test_id)
    # Savollar botda tarqatilmaydi — ular kanaldagi e'londa (DECISIONS.md #46).
    # Bu yerda faqat muqova (reklama) rasmi so'raladi, u ham majburiy emas.
    await message.answer(
        f"✅ Raqam: **#{test_id}**\n\n"
        f"Muqova rasmini yuboring — o'quvchi test raqamini kiritganda shu "
        f"rasmni ko'radi (reklama, e'lon va h.k.).\n\n"
        f"Savollar rasmi shart emas: ular kanaldagi e'londa turadi, bot "
        f"faqat javoblarni tekshiradi.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Rasmsiz davom etish", callback_data="onl_no_image")]
            ]
        ),
    )
    await state.set_state(OnlineTestCreationStates.waiting_for_image)


@router.message(OnlineTestCreationStates.waiting_for_image, F.photo)
@router.message(OnlineTestCreationStates.waiting_for_image, F.document)
async def online_test_image(message: Message, state: FSMContext):
    if message.photo:
        # Eng katta o'lchamdagisini olamiz
        file_id = message.photo[-1].file_id
        file_type = "photo"
    else:
        doc = message.document
        if not (doc.mime_type or "").startswith("image/"):
            await message.answer(
                "Bu rasm emas. Rasm yuboring yoki «⏭ Rasmsiz davom etish» ni bosing:",
                reply_markup=get_cancel_keyboard(),
            )
            return
        file_id = doc.file_id
        file_type = "document"

    # DIQQAT: rasmning o'zi serverga yuklab olinmaydi — faqat Telegram bergan
    # file_id saqlanadi va o'quvchiga o'sha id bilan qayta yuboriladi.
    await state.update_data(image_file_id=file_id, file_type=file_type)
    await _onl_ask_answers(message, state, "✅ Muqova rasmi qabul qilindi.")


@router.callback_query(
    OnlineTestCreationStates.waiting_for_image, F.data == "onl_no_image"
)
async def online_test_no_image(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.update_data(image_file_id=None, file_type="photo")
    await _onl_ask_answers(callback.message, state, "✅ Rasmsiz davom etamiz.")


async def _onl_ask_answers(message: Message, state: FSMContext, prefix: str) -> None:
    await message.answer(
        f"{prefix}\n\n"
        "Endi to'g'ri javoblarni kiriting.\n\n"
        "Masalan: `ABCDABCD` yoki `A,B,C,D,A,B,C,D`\n"
        "(faqat A, B, C, D, E harflari)",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(OnlineTestCreationStates.waiting_for_answers)


@router.message(OnlineTestCreationStates.waiting_for_image)
async def online_test_image_invalid(message: Message):
    await message.answer(
        "Muqova rasmini yuboring (rasm yoki fayl ko'rinishida) yoki "
        "«⏭ Rasmsiz davom etish» tugmasini bosing:",
        reply_markup=get_cancel_keyboard(),
    )


@router.message(OnlineTestCreationStates.waiting_for_answers)
async def online_test_answers(message: Message, state: FSMContext):
    answers = normalize_answers(message.text)
    if not answers:
        await message.answer(
            "Noto'g'ri format. Javoblar faqat A, B, C, D, E harflaridan iborat "
            "bo'lishi kerak (Masalan: ABCDABCD):",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    test_id = data["online_test_id"]
    count = len(answers.split(","))

    try:
        async with async_session() as session:
            session.add(
                OnlineTest(
                    id=test_id,
                    # Muqova rasmi ixtiyoriy (DECISIONS.md #46).
                    image_file_id=data.get("image_file_id"),
                    file_type=data.get("file_type") or "photo",
                    answers=answers,
                    created_by=message.chat.id,
                )
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Online test saqlashda xato (#{test_id}): {e}")
        await message.answer(
            "Testni saqlashda xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=get_admin_keyboard(),
        )
        await state.clear()
        return

    await state.clear()
    muqova = "bor" if data.get("image_file_id") else "yo'q"
    await message.answer(
        f"🎉 **Online test yaratildi!**\n\n"
        f"🔢 Test raqami: **#{test_id}**\n"
        f"📝 Savollar soni: {count} ta\n"
        f"🖼 Muqova rasmi: {muqova}\n"
        f"🔑 Kalit: `{answers}`\n\n"
        f"Savollarni kanalga joylang va yozing: botda **🧩 Online test** "
        f"tugmasini bosib, **{test_id}** raqamini kiritsinlar.",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard(),
    )


@router.message(F.text == "📋 Online testlar ro'yxati")
async def list_online_tests(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return

        rows = (
            await session.execute(
                select(
                    OnlineTest.id,
                    OnlineTest.answers,
                    func.count(OnlineTestResult.id),
                )
                .outerjoin(
                    OnlineTestResult, OnlineTestResult.online_test_id == OnlineTest.id
                )
                .where(OnlineTest.archived.is_(False))
                .group_by(OnlineTest.id, OnlineTest.answers)
                .order_by(OnlineTest.id.desc())
            )
        ).all()

    if not rows:
        await message.answer(
            "Hozircha birorta online test yo'q.", reply_markup=get_admin_keyboard()
        )
        return

    lines = ["🧩 **Online testlar:**", ""]
    buttons = []
    for tid, answers, solved in rows:
        n = len(answers.split(","))
        lines.append(f"**#{tid}** — {n} ta savol, {solved} o'quvchi ishlagan")
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 #{tid} ni o'chirish",
                    callback_data=f"del_onltest:{tid}",
                )
            ]
        )

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("del_onltest:"))
async def delete_online_test(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    test_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

        solved = (
            await session.execute(
                select(func.count())
                .select_from(OnlineTestResult)
                .where(OnlineTestResult.online_test_id == test_id)
            )
        ).scalar_one()

        test = (
            await session.execute(select(OnlineTest).where(OnlineTest.id == test_id))
        ).scalar_one_or_none()
        if not test:
            await callback.answer("Test topilmadi.", show_alert=True)
            return

        # O'chirmaymiz, arxivlaymiz — o'quvchilarning natijalari saqlanib qoladi
        test.archived = True
        await session.commit()

    logger.info(f"Online test #{test_id} arxivlandi (admin={chat_id})")
    await callback.answer("Test o'chirildi.", show_alert=True)
    await callback.message.edit_text(
        f"🗑 **Online test #{test_id} o'chirildi.**\n\n"
        f"✅ {solved} ta o'quvchi natijasi saqlanib qoldi.",
        parse_mode="Markdown",
        reply_markup=None,
    )


# Bitta faylga olinadigan eng ko'p urinish. Bundan oshsa eng yangilari
# olinadi va buni admin xabarda ko'radi (jimgina qirqib tashlamaymiz).
MAX_HISTORY_ROWS = 20000
# Chatda ko'rinadigan oxirgi urinishlar (qolganini Excel'dan ko'radi).
HISTORY_PREVIEW = 10


# Ro'yxatda ko'rsatiladigan testlar soni (yangisidan boshlab).
HISTORY_TESTS = 12


class OnlineHistoryStates(StatesGroup):
    """Tarix qaysi test bo'yicha kerak — tugmadan yoki ID yozib tanlanadi."""

    waiting_for_id = State()


@router.message(F.text == "📊 Online testlar tarixi (Excel)")
async def online_history_menu(message: Message, state: FSMContext):
    """Qaysi testning tarixi kerakligini so'raydi (DECISIONS.md #43).

    Har bir test alohida: ro'yxatdan tanlanadi yoki ID yoziladi. Hammasini
    bitta faylda olish ham mumkin — alohida tugma.
    """
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        rows = (
            await session.execute(
                select(
                    OnlineTest.id,
                    OnlineTest.title,
                    OnlineTest.archived,
                    func.count(OnlineTestResult.id),
                )
                .outerjoin(
                    OnlineTestResult, OnlineTestResult.online_test_id == OnlineTest.id
                )
                .group_by(OnlineTest.id)
                .order_by(OnlineTest.id.desc())
                .limit(HISTORY_TESTS)
            )
        ).all()

    if not rows:
        await message.answer(
            "Hozircha birorta online test yaratilmagan.",
            reply_markup=get_online_tests_menu_keyboard(),
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=f"📄 #{tid} — {(title or 'nomsiz')[:28]} ({solved} ta)"
                + (" 🗄" if archived else ""),
                callback_data=f"onl_hist:{tid}",
            )
        ]
        for tid, title, archived, solved in rows
    ]
    buttons.append(
        [InlineKeyboardButton(text="📦 Hammasi bitta faylda", callback_data="onl_hist:all")]
    )

    await state.update_data(return_menu="online_tests")
    await state.set_state(OnlineHistoryStates.waiting_for_id)
    await message.answer(
        "📊 **Online testlar tarixi**\n\n"
        "Qaysi testning natijalari kerak? Tugmadan tanlang yoki test ID sini "
        "yozing (masalan: `12`).",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await message.answer("Testlar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("onl_hist:"))
async def online_history_pick(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id
    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return

    raw = callback.data.split(":")[1]
    await state.clear()
    await callback.answer("Tayyorlanmoqda...")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _send_online_history(callback.message, None if raw == "all" else int(raw))


@router.message(OnlineHistoryStates.waiting_for_id)
async def online_history_typed(message: Message, state: FSMContext):
    raw = (message.text or "").strip().lstrip("#")
    if raw.lower() in ("hammasi", "all"):
        await state.clear()
        await _send_online_history(message, None)
        return
    if not raw.isdigit():
        await message.answer(
            "Test ID — raqam (masalan: 12). Hammasini olish uchun «hammasi» deb yozing:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    await state.clear()
    await _send_online_history(message, int(raw))


async def _send_online_history(message: Message, test_id: int | None) -> None:
    """Chatda qisqa xulosa, keyin Excel. `test_id` bo'lsa — faqat o'sha test.

    Excel'da ikkita varaq — har bir urinish alohida qator va test bo'yicha
    yig'ma ko'rsatkich (services/online_test_excel.py). Arxivlangan testlar
    ham kiradi: natijalar o'chirilmaydi (DECISIONS.md #43).
    """
    async with async_session() as session:
        query = (
            select(OnlineTestResult, OnlineTest, User)
            .join(OnlineTest, OnlineTestResult.online_test_id == OnlineTest.id)
            .join(User, OnlineTestResult.user_id == User.id)
            .order_by(OnlineTestResult.checked_at.desc(), OnlineTestResult.id.desc())
            .limit(MAX_HISTORY_ROWS + 1)
        )
        if test_id is not None:
            query = query.where(OnlineTest.id == test_id)
        rows = (await session.execute(query)).all()

        # total = 0 bo'lib qolgan yozuv nolga bo'lishni keltirib chiqarmasin.
        percent = (
            OnlineTestResult.correct * 100.0 / func.nullif(OnlineTestResult.total, 0)
        )
        summary_query = (
            select(
                OnlineTest.id,
                OnlineTest.title,
                OnlineTest.answers,
                OnlineTest.created_at,
                OnlineTest.archived,
                func.count(OnlineTestResult.id),
                func.avg(percent),
                func.max(percent),
            )
            .outerjoin(
                OnlineTestResult, OnlineTestResult.online_test_id == OnlineTest.id
            )
            .group_by(OnlineTest.id)
            .order_by(OnlineTest.id.desc())
        )
        if test_id is not None:
            summary_query = summary_query.where(OnlineTest.id == test_id)
        summary = (await session.execute(summary_query)).all()

    if test_id is not None and not summary:
        await message.answer(
            f"#{test_id} raqamli online test topilmadi.",
            reply_markup=get_online_tests_menu_keyboard(),
        )
        return

    if not rows:
        await message.answer(
            f"#{test_id} testini hali hech kim ishlamagan."
            if test_id is not None
            else "Hozircha birorta o'quvchi online test ishlamagan.",
            reply_markup=get_online_tests_menu_keyboard(),
        )
        return

    truncated = len(rows) > MAX_HISTORY_ROWS
    rows = rows[:MAX_HISTORY_ROWS]

    results = [
        {
            "checked_at": r.checked_at,
            "test_id": t.id,
            "title": t.title,
            "full_name": u.full_name,
            "phone": u.phone,
            "chat_id": u.id,
            "correct": r.correct,
            "total": r.total,
            "given": r.given_answers,
            "key": t.answers,
        }
        for r, t, u in rows
    ]
    tests = [
        {
            "test_id": tid,
            "title": title,
            "questions": len([x for x in (answers or "").split(",") if x.strip()]),
            "solved": solved,
            "avg_percent": float(avg) if avg is not None else None,
            "max_percent": float(top) if top is not None else None,
            "created_at": created_at,
            "archived": archived,
        }
        for tid, title, answers, created_at, archived, solved, avg, top in summary
    ]

    try:
        data = build_history_excel(results, tests)
    except Exception as e:
        logger.exception(f"Online testlar tarixini yig'ishda xato: {e}")
        await message.answer(
            "Tarixni Excel qilishda xatolik yuz berdi. Administratorga xabar bering.",
            reply_markup=get_online_tests_menu_keyboard(),
        )
        return

    percents = [r["correct"] / r["total"] * 100 for r in results if r["total"]]
    avg_all = sum(percents) / len(percents) if percents else 0
    students = len({r["chat_id"] for r in results})

    if test_id is not None:
        t = tests[0]
        holat = " 🗄 (arxivda)" if t["archived"] else ""
        lines = [
            f"📊 **#{test_id} — {t['title'] or 'nomsiz'}**{holat}",
            "",
            f"❓ Savollar: **{t['questions']} ta**",
            f"👥 Ishlaganlar: **{students} ta**",
            f"📈 O'rtacha: **{avg_all:.0f}%**, eng yuqori: "
            f"**{t['max_percent']:.0f}%**" if t["max_percent"] is not None
            else f"📈 O'rtacha: **{avg_all:.0f}%**",
            "",
            f"Natijalar (oxirgi {min(HISTORY_PREVIEW, len(results))} ta):",
        ]
        for r in results[:HISTORY_PREVIEW]:
            pct = r["correct"] / r["total"] * 100 if r["total"] else 0
            lines.append(
                f"• {r['checked_at'].strftime('%d.%m %H:%M')} — {r['full_name']}: "
                f"{r['correct']}/{r['total']} ({pct:.0f}%)"
            )
        caption = f"#{test_id} natijalari — «Natijalar» varag'ida har bir urinish."
    else:
        lines = [
            "📊 **Online testlar tarixi**",
            "",
            f"🧩 Testlar: **{len(tests)} ta**",
            f"✍️ Urinishlar: **{len(results)} ta**",
            f"👥 O'quvchilar: **{students} ta**",
            f"📈 O'rtacha: **{avg_all:.0f}%**",
            f"📅 {results[-1]['checked_at'].strftime('%d.%m.%Y')} — "
            f"{results[0]['checked_at'].strftime('%d.%m.%Y')}",
            "",
            f"Oxirgi {min(HISTORY_PREVIEW, len(results))} ta:",
        ]
        for r in results[:HISTORY_PREVIEW]:
            pct = r["correct"] / r["total"] * 100 if r["total"] else 0
            lines.append(
                f"• {r['checked_at'].strftime('%d.%m %H:%M')} — #{r['test_id']} — "
                f"{r['full_name']}: {r['correct']}/{r['total']} ({pct:.0f}%)"
            )
        caption = "To'liq tarix: «Natijalar» va «Testlar» varaqlari."

    if len(results) > HISTORY_PREVIEW:
        lines.append(f"  … va yana {len(results) - HISTORY_PREVIEW} ta (faylda hammasi)")
    if truncated:
        lines.append("")
        lines.append(
            f"⚠️ Faylga eng yangi {MAX_HISTORY_ROWS} ta urinish kirdi — "
            f"undan eskilari tushmadi."
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")
    await message.answer_document(
        BufferedInputFile(data, filename=history_filename(test_id=test_id)),
        caption=caption,
        reply_markup=get_online_tests_menu_keyboard(),
    )


@router.message(OlympiadDetailStates.viewing, F.text == "📊 Sinf bo'yicha natijalar")
async def show_grade_ranking_menu(message: Message, state: FSMContext):
    """Sinf tanlash — har sinfning reytingi alohida ko'riladi."""
    chat_id = message.chat.id
    data = await state.get_data()
    olympiad_id = data.get("detail_olympiad_id")
    if not olympiad_id:
        return

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            return
        grades = await get_olympiad_grades(session, olympiad_id)
        counts = await grade_counts(session, olympiad_id)

    if not counts:
        await message.answer("Bu olimpiadada hali ishtirokchi yo'q.")
        return

    # Olimpiadaga biriktirilgan sinflar + natijada uchragan sinflar
    barcha = sorted(
        set(grades) | {g for g in counts if g is not None}
    )
    rows = [
        [
            InlineKeyboardButton(
                text=f"{g}-sinf ({counts.get(g, 0)} ta)",
                callback_data=f"olymp_rank_g:{olympiad_id}:{g}",
            )
        ]
        for g in barcha
    ]
    if None in counts:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Sinfsiz ({counts[None]} ta)",
                    callback_data=f"olymp_rank_g:{olympiad_id}:none",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔙 Ortga", callback_data=f"olymp_manage:{olympiad_id}"
            )
        ]
    )

    await message.answer(
        "📊 Qaysi sinf reytingini ko'rasiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("olymp_rank_g:"))
async def show_grade_ranking(callback: CallbackQuery):
    """Bitta sinfning reytingi. O'rinlar shu sinf ichida hisoblangan."""
    chat_id = callback.message.chat.id
    _, olympiad_id_s, grade_s = callback.data.split(":")
    olympiad_id = int(olympiad_id_s)
    grade = None if grade_s == "none" else int(grade_s)

    async with async_session() as session:
        if not await is_admin_or_superadmin(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
        olympiad = (
            await session.execute(select(Olympiad).where(Olympiad.id == olympiad_id))
        ).scalar_one_or_none()
        rows = await grade_ranking(session, olympiad_id, grade, limit=50)

    await callback.answer()
    sinf_txt = f"{grade}-sinf" if grade is not None else "Sinfsiz"

    if not rows:
        await callback.message.answer(
            f"📊 **{olympiad.name if olympiad else ''}** — {sinf_txt}\n\n"
            f"Bu sinfda hali tekshirilgan natija yo'q.",
            parse_mode="Markdown",
        )
        return

    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"📊 **{olympiad.name if olympiad else ''}** — {sinf_txt}", ""]
    for r in rows:
        belgi = medal.get(r.place, f"{r.place}.")
        ball = fmt_number(r.score)
        lines.append(f"{belgi} {r.full_name or '—'} — {ball}")

    matn = "\n".join(lines)
    if len(matn) > 3900:
        matn = matn[:3900] + "\n\n… (ro'yxat qisqartirildi)"
    await callback.message.answer(matn, parse_mode="Markdown")


# ============================================================================
# MUSTAQIL JAVOB VARAG'I (olimpiadadan tashqari)
#
# Olimpiadadagi javob varag'i bilan BIR XIL shablon va bir xil tekshiruv
# mexanizmidan foydalanadi (services/answer_sheet_service.py +
# services/omr_checker.py), lekin olimpiada/ro'yxatdan o'tish tizimiga
# bog'liq emas: varaq o'z nomi bilan yashaydi, ishtirokchilar esa Excel
# orqali kiritiladi yoki umuman bo'lmaydi (DECISIONS.md #34).
#
# Ikki rejim:
#   • "Yo'q"  -> bitta BO'SH varaq: ism/sana/sinf maydonlari va QR o'rni
#                bo'sh qoladi, qo'lda to'ldiriladi. Tekshirilganda faqat
#                belgilangan PDF qaytadi (kim yozgani noma'lum).
#   • "Ha"    -> Excel'dagi har bir ishtirokchi uchun alohida sahifa,
#                ma'lumotlari va QR'i bosilgan holda. Tekshirilganda
#                natijalar Excel'i ham chiqadi.
# ============================================================================


class TestSheetStates(StatesGroup):
    """Mustaqil javob varag'ini yaratish oqimi."""

    waiting_for_name = State()
    waiting_for_participants_choice = State()
    waiting_for_excel = State()
    waiting_for_subject_count = State()
    waiting_for_subject_name = State()
    waiting_for_question_count = State()
    waiting_for_choice_count = State()
    waiting_for_confirm = State()


def _ts_slug(name: str) -> str:
    """Fayl nomi uchun xavfsiz qisqartma."""
    out = "".join(c if c.isalnum() else "_" for c in (name or "varaq").lower())
    return "_".join(p for p in out.split("_") if p)[:40] or "varaq"


@router.message(F.text == "🆕 Javob varag'i yaratish")
async def test_sheet_start(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await can_manage_tests(chat_id, session):
            return

    await state.clear()
    await state.update_data(return_menu="test_checking")
    await message.answer(
        "🆕 **Javob varag'i yaratish**\n\n"
        "Varaqqa nom bering (keyinchalik tekshirishda shu nom bo'yicha "
        "topasiz).\n\nMasalan: `9-sinflar nazorat ishi`",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetStates.waiting_for_name)


@router.message(TestSheetStates.waiting_for_name)
async def ts_process_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 3:
        await message.answer(
            "Nom juda qisqa (kamida 3 belgi). Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    if len(name) > 150:
        await message.answer(
            f"Nom juda uzun ({len(name)} belgi). 150 belgidan oshmasin:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(ts_name=name, ts_subjects=[])
    await message.answer(
        f"«{name}» uchun varaqlarga ishtirokchilarning ma'lumoti "
        f"(ism, familiya, sana, sinf) oldindan bosilsinmi?\n\n"
        f"• **Ha** — ishtirokchilar Excel orqali kiritiladi, har biriga "
        f"o'z ma'lumoti va QR kodi bilan alohida varaq chiqadi. "
        f"Tekshirilganda natijalar Excel'i tayyor bo'ladi.\n"
        f"• **Yo'q** — bitta bo'sh varaq chiqadi, maydonlarni o'quvchi "
        f"qo'lda to'ldiradi. Xohlagancha ko'paytirib chop etasiz.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Ha", callback_data="ts_wp:1"),
                    InlineKeyboardButton(text="❌ Yo'q", callback_data="ts_wp:0"),
                ]
            ]
        ),
    )
    await state.set_state(TestSheetStates.waiting_for_participants_choice)


async def _ts_ask_subject_count(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Necha fan bo'yicha test o'tkaziladi? (1, 2 yoki 3):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetStates.waiting_for_subject_count)


@router.callback_query(
    TestSheetStates.waiting_for_participants_choice, F.data.startswith("ts_wp:")
)
async def ts_process_participants_choice(callback: CallbackQuery, state: FSMContext):
    with_participants = callback.data.split(":")[1] == "1"
    await state.update_data(ts_with_participants=with_participants)
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if not with_participants:
        await callback.message.answer(
            "✅ Bitta bo'sh varaq tayyorlanadi.\n\n"
            "Ism, familiya, tug'ilgan sana va sinf joylari bo'sh qoladi, "
            "QR kod o'rni esa belgilab qo'yiladi."
        )
        await _ts_ask_subject_count(callback.message, state)
        return

    # Platformadagi o'z guruhlaringiz — o'quvchilarni qayta yozib o'tirmaslik
    # uchun (DECISIONS.md #45). Guruh yo'q yoki platforma sozlanmagan bo'lsa
    # to'g'ridan-to'g'ri Excel so'raladi, ya'ni eski yo'l hech qayerga ketmaydi.
    groups = await classrooms_for(callback.message.chat.id) if platform_configured() else []
    usable = [g for g in groups if g.student_count]
    if usable:
        buttons = [
            [InlineKeyboardButton(text=f"👥 {g.label}", callback_data=f"ts_group:{g.id}")]
            for g in usable
        ]
        buttons.append(
            [InlineKeyboardButton(text="📄 Excel orqali kiritish", callback_data="ts_excel")]
        )
        bosh = [g.name for g in groups if not g.student_count]
        izoh = f"\n\n_O'quvchisi yo'q guruhlar chiqmadi: {', '.join(bosh[:5])}._" if bosh else ""
        await callback.message.answer(
            "👥 **Qaysi guruh?**\n\nO'quvchilarning ism, familiya, tug'ilgan "
            "sanasi va sinfi platformadagi guruhdan olinadi." + izoh,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        return

    if groups:
        await callback.message.answer(
            "Guruhlaringizda hali o'quvchi yo'q — ro'yxatni Excel orqali kiritamiz."
        )
    await _ts_ask_excel(callback.message, state)


@router.callback_query(
    TestSheetStates.waiting_for_participants_choice, F.data.startswith("ts_group:")
)
async def ts_pick_group(callback: CallbackQuery, state: FSMContext):
    """Guruh tanlandi — o'quvchilar platformadan olinadi."""
    classroom_id = callback.data.split(":", 1)[1]
    await callback.answer("O'quvchilar olinmoqda...")
    students = await classroom_students(classroom_id)
    if not students:
        await callback.message.answer(
            "Bu guruhda o'quvchi topilmadi (yoki platforma javob bermadi).\n"
            "Ro'yxatni Excel orqali ham kiritishingiz mumkin.",
        )
        await _ts_ask_excel(callback.message, state)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Guruh nomi va id'si ham eslab qolinadi: keyin varaqni boshqa guruhga
    # chiqarganda bu qatorlar qaysi guruhniki ekani bilinadi (DECISIONS.md #47).
    group = await classroom_by_id(classroom_id)
    await state.update_data(
        ts_participants=students,
        ts_group_id=classroom_id,
        ts_group_name=group.name if group else None,
    )
    preview = "\n".join(
        f"  {s['row_no']}. {s['familiya']} {s['ism']}".rstrip() for s in students[:5]
    )
    more = f"\n  … va yana {len(students) - 5} ta" if len(students) > 5 else ""
    await callback.message.answer(
        f"✅ Guruhdan {len(students)} ta o'quvchi olindi:\n\n{preview}{more}"
    )
    await _ts_ask_subject_count(callback.message, state)


@router.callback_query(
    TestSheetStates.waiting_for_participants_choice, F.data == "ts_excel"
)
async def ts_choose_excel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _ts_ask_excel(callback.message, state)


async def _ts_ask_excel(message: Message, state: FSMContext) -> None:
    """Ishtirokchilarni Excel orqali so'rash (guruhsiz, eski yo'l)."""
    # Namuna faylni O'ZIMIZ beramiz — ustunlar tartibi qat'iy, admin
    # ustun nomlarini o'ylab o'tirmaydi.
    await message.answer_document(
        BufferedInputFile(
            build_participants_template(), filename="ishtirokchilar_namuna.xlsx"
        ),
        caption=(
            "📋 **Ishtirokchilar ro'yxati**\n\n"
            "Shu faylni yuklab oling, namuna qatorlarni o'chirib, o'z "
            "ro'yxatingizni yozing va MANA SHU YERGA qaytarib yuboring.\n\n"
            "Ustunlar: № | Ism | Familiya | Tug'ilgan sana | Sinf\n"
            "«Tug'ilgan sana» va «Sinf» bo'sh qolishi mumkin."
        ),
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetStates.waiting_for_excel)


@router.message(TestSheetStates.waiting_for_excel, F.document)
async def ts_process_excel(message: Message, state: FSMContext, bot: Bot):
    doc = message.document
    if not (doc.file_name or "").lower().endswith((".xlsx", ".xlsm")):
        await message.answer(
            "❌ Faqat Excel (.xlsx) fayl qabul qilinadi. Yuborgan namunani "
            "to'ldirib qaytaring:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    try:
        file_info = await bot.get_file(doc.file_id)
        buf = await bot.download_file(file_info.file_path)
        raw = buf.read()
    except Exception as e:
        logger.exception(f"Ishtirokchilar Excel'ini yuklashda xato: {e}")
        await message.answer(
            "❌ Faylni yuklab bo'lmadi. Qaytadan yuboring:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    try:
        rows, warnings = await asyncio.to_thread(parse_participants, raw)
    except ParticipantsExcelError as e:
        await message.answer(f"❌ {e}", reply_markup=get_cancel_keyboard())
        return
    except Exception as e:
        logger.exception(f"Ishtirokchilar Excel'ini o'qishda xato: {e}")
        await message.answer(
            "❌ Faylni o'qib bo'lmadi. Namuna faylning ustunlarini "
            "o'zgartirmagan holda to'ldiring:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    if not rows:
        await message.answer(
            "❌ Faylda birorta ham ishtirokchi topilmadi.\n\n"
            "«Ism» yoki «Familiya» ustunidan kamida bittasi to'ldirilgan "
            "bo'lishi kerak. Qaytadan yuboring:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    # FSM xotirasiga sof JSON-ga yaqin ko'rinishda yozamiz — `date`
    # obyekti saqlanmasin (keyinchalik boshqa storage'ga o'tilsa ham
    # buzilmaydi).
    stored = [
        {**r, "birth_date": r["birth_date"].isoformat() if r["birth_date"] else None}
        for r in rows
    ]
    await state.update_data(ts_participants=stored)

    preview = "\n".join(
        f"  {r['row_no']}. {r['familiya']} {r['ism']}".rstrip() for r in rows[:5]
    )
    more = f"\n  … va yana {len(rows) - 5} ta" if len(rows) > 5 else ""
    ogoh = ("\n\n⚠️ " + "\n⚠️ ".join(warnings[:5])) if warnings else ""

    await message.answer(
        f"✅ {len(rows)} ta ishtirokchi o'qildi:\n\n{preview}{more}{ogoh}"
    )
    await _ts_ask_subject_count(message, state)


@router.message(TestSheetStates.waiting_for_excel)
async def ts_excel_wrong_type(message: Message, state: FSMContext):
    await message.answer(
        "Yuborilgan namuna faylni to'ldirib, FAYL ko'rinishida qaytaring "
        "(matn emas):",
        reply_markup=get_cancel_keyboard(),
    )


@router.message(TestSheetStates.waiting_for_subject_count)
async def ts_process_subject_count(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if raw not in ("1", "2", "3"):
        await message.answer(
            "Iltimos, 1, 2 yoki 3 dan birini kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    await state.update_data(ts_subject_count=int(raw))
    await message.answer(
        "1-fan nomini kiriting (Masalan: Matematika):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetStates.waiting_for_subject_name)


@router.message(TestSheetStates.waiting_for_subject_name)
async def ts_process_subject_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Fan nomi juda qisqa. Iltimos, qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    if len(name) > 100:
        await message.answer(
            f"Fan nomi juda uzun ({len(name)} belgi). 100 belgidan oshmasin:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    subjects = data.get("ts_subjects", [])
    subjects.append({"name": name})
    await state.update_data(ts_subjects=subjects)

    await message.answer(
        f"«{name}» uchun savollar sonini kiriting (Masalan: 30):",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetStates.waiting_for_question_count)


@router.message(TestSheetStates.waiting_for_question_count)
async def ts_process_question_count(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 200):
        await message.answer(
            "Iltimos, 1 dan 200 gacha bo'lgan butun son kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    data = await state.get_data()
    subjects = data["ts_subjects"]
    subjects[-1]["question_count"] = int(raw)
    await state.update_data(ts_subjects=subjects)

    await message.answer(
        f"«{subjects[-1]['name']}» uchun javob variantlari nechta?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="4 (ABCD)", callback_data="ts_choice:4"),
                    InlineKeyboardButton(text="5 (ABCDE)", callback_data="ts_choice:5"),
                ]
            ]
        ),
    )
    await state.set_state(TestSheetStates.waiting_for_choice_count)


@router.callback_query(
    TestSheetStates.waiting_for_choice_count, F.data.startswith("ts_choice:")
)
async def ts_process_choice_count(callback: CallbackQuery, state: FSMContext):
    choice_count = int(callback.data.split(":")[1])
    data = await state.get_data()
    subjects = data["ts_subjects"]
    subjects[-1]["choice_count"] = choice_count
    await state.update_data(ts_subjects=subjects)

    await callback.answer(f"{choice_count} ta variant tanlandi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if len(subjects) < data["ts_subject_count"]:
        await callback.message.answer(
            f"{len(subjects) + 1}-fan nomini kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        await state.set_state(TestSheetStates.waiting_for_subject_name)
        return

    ro_yxat = "\n".join(
        _fmt_subject_line(i, s["name"], s["question_count"], s["choice_count"])
        for i, s in enumerate(subjects, 1)
    )
    if data.get("ts_with_participants"):
        kim = f"{len(data.get('ts_participants', []))} ta ishtirokchi (Excel'dan)"
    else:
        kim = "Bitta bo'sh varaq (ma'lumotlar qo'lda to'ldiriladi)"

    await callback.message.answer(
        f"🆕 **{data['ts_name']}**\n\n"
        f"👥 {kim}\n\n"
        f"{ro_yxat}\n\nYaratilsinmi?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Ha", callback_data="ts_save")],
                [
                    InlineKeyboardButton(
                        text="❌ Bekor qilish", callback_data="ts_cancel"
                    )
                ],
            ]
        ),
    )
    await state.set_state(TestSheetStates.waiting_for_confirm)


@router.callback_query(TestSheetStates.waiting_for_confirm, F.data == "ts_cancel")
async def ts_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Bekor qilindi.")
    try:
        await callback.message.edit_text("Javob varag'i yaratish bekor qilindi.")
    except Exception:
        pass
    await callback.message.answer(
        "📝 Testlarni tekshirish bo'limi:",
        reply_markup=get_test_checking_menu_keyboard(),
    )


@router.callback_query(TestSheetStates.waiting_for_confirm, F.data == "ts_save")
async def ts_save(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    name = data["ts_name"]
    subjects_cfg = data["ts_subjects"]
    with_participants = bool(data.get("ts_with_participants"))
    participants = data.get("ts_participants", []) if with_participants else []

    await state.clear()
    await callback.answer("Saqlandi!")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    status = await callback.message.answer(
        "⏳ Varaq shabloni chizilmoqda (bir necha daqiqa vaqt olishi "
        "mumkin)..."
    )

    # 1) Sozlama va ishtirokchilarni bazaga yozamiz. ticket_no faqat
    #    ishtirokchi id'si ma'lum bo'lgandan keyin yasaladi — olimpiadada
    #    ham aynan shunday (utils/qr_payload.py -> build_ticket_no).
    try:
        async with async_session() as session:
            sheet = TestSheet(
                name=name,
                with_participants=with_participants,
                created_by=callback.from_user.id,
            )
            session.add(sheet)
            await session.flush()

            for i, s in enumerate(subjects_cfg, 1):
                session.add(
                    TestSheetSubject(
                        test_sheet_id=sheet.id,
                        position=i,
                        name=s["name"],
                        question_count=s["question_count"],
                        choice_count=s["choice_count"],
                    )
                )

            rows: list[TestSheetParticipant] = []
            for p in participants:
                bd = p.get("birth_date")
                rows.append(
                    TestSheetParticipant(
                        test_sheet_id=sheet.id,
                        row_no=p["row_no"],
                        ism=p["ism"],
                        familiya=p["familiya"],
                        birth_date=date.fromisoformat(bd) if bd else None,
                        sinf=p["sinf"],
                        # Guruhdan olingan bo'lsa — qaysi guruh ekani
                        # saqlanadi; Excel'dan bo'lsa ikkalasi ham bo'sh.
                        guruh=data.get("ts_group_name"),
                        classroom_id=data.get("ts_group_id"),
                    )
                )
            session.add_all(rows)
            await session.flush()

            year = datetime.utcnow().year
            code = f"TS{sheet.id}"
            for r in rows:
                r.ticket_no = build_ticket_no(year, code, r.id)

            await session.commit()
            sheet_id = sheet.id
    except Exception as e:
        logger.exception(f"Mustaqil javob varag'ini saqlashda xato: {e}")
        await status.edit_text(
            "❌ Saqlashda xatolik yuz berdi. Qaytadan urinib ko'ring."
        )
        await callback.message.answer(
            "📝 Testlarni tekshirish bo'limi:",
            reply_markup=get_test_checking_menu_keyboard(),
        )
        return

    # 2) Bo'sh shablon + koordinatalar (olimpiadadagi bilan bir xil yo'l).
    try:
        await _ts_build_and_store_blank(sheet_id)
    except Exception as e:
        logger.exception(
            f"Mustaqil varaq shablonini tayyorlashda xato (#{sheet_id}): {e}"
        )
        await status.edit_text(
            f"❌ Varaq shablonini tayyorlashda xatolik:\n\n{e}\n\n"
            f"Varaq saqlandi. Sabab tuzalgach «✅ Javob varag'ini "
            f"tekshirish» → shu varaq → «📄 Varaqni qayta yuklab olish» "
            f"orqali shablonni qaytadan chizdirishingiz mumkin."
        )
        await notify_superadmins(
            bot, f"⚠️ Mustaqil varaq shabloni tayyorlanmadi (#{sheet_id}): {e}"
        )
        await callback.message.answer(
            "📝 Testlarni tekshirish bo'limi:",
            reply_markup=get_test_checking_menu_keyboard(),
        )
        return

    # 3) PDF'ni yuboramiz.
    try:
        await status.edit_text("⏳ PDF tayyorlanmoqda...")
    except Exception:
        pass
    try:
        await _ts_send_sheets(callback.message, sheet_id)
    except Exception as e:
        logger.exception(f"Mustaqil varaqni jo'natishda xato (#{sheet_id}): {e}")
        await callback.message.answer(
            "❌ PDF tayyorlashda xatolik yuz berdi. Administratorga xabar "
            "berildi."
        )
        await notify_superadmins(
            bot, f"⚠️ Mustaqil varaq PDF'i tayyorlanmadi (#{sheet_id}): {e}"
        )
    finally:
        try:
            await status.delete()
        except Exception:
            pass

    await callback.message.answer(
        "📝 Testlarni tekshirish bo'limi:",
        reply_markup=get_test_checking_menu_keyboard(),
    )


async def _ts_load_subjects(session, sheet_id: int):
    """Varaqning fanlarini tartib bo'yicha qaytaradi."""
    return (
        await session.execute(
            select(TestSheetSubject)
            .where(TestSheetSubject.test_sheet_id == sheet_id)
            .order_by(TestSheetSubject.position)
        )
    ).scalars().all()


async def _ts_build_and_store_blank(sheet_id: int) -> None:
    """Mustaqil varaq uchun bo'sh shablon chizib, koordinatalari bilan
    birga bazaga yozadi — `_build_and_store_blank_sheet` bilan bir xil
    mantiq, faqat manbasi `TestSheet` (DECISIONS.md #27, #34)."""
    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
        if not sheet:
            raise RuntimeError(f"Varaq #{sheet_id} topilmadi")
        event_title = sheet.name
        subject_rows = await _ts_load_subjects(session, sheet_id)

    subjects = tuple(
        SubjectSpec(
            name=s.name, question_count=s.question_count, choice_count=s.choice_count
        )
        for s in subject_rows
    )
    if not subjects:
        raise RuntimeError(f"Varaq #{sheet_id} uchun fan sozlanmagan")

    blank_pdf = await render_blank_sheet_pdf(subjects, event_title)
    field_boxes = await asyncio.to_thread(extract_field_boxes, blank_pdf)
    bubble_boxes = await asyncio.to_thread(extract_bubble_boxes, blank_pdf, subjects)

    async with async_session() as session:
        db_sheet = await session.get(TestSheet, sheet_id)
        db_sheet.blank_pdf = blank_pdf
        db_sheet.field_boxes = field_boxes
        db_sheet.bubble_boxes = bubble_boxes
        await session.commit()


async def _ts_send_sheets(message: Message, sheet_id: int) -> None:
    """Tayyor shablondan PDF yasab jo'natadi.

    Ishtirokchisiz varaqda shablonning O'ZI natija — maydonlar oq
    (ko'rinmas) matn bilan yozilgani uchun bo'sh ko'rinadi, QR o'rni esa
    rasm bilan belgilangan. Ishtirokchili varaqda esa har biri uchun
    alohida sahifa shtamplanadi.
    """
    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
        if not sheet:
            raise RuntimeError(f"Varaq #{sheet_id} topilmadi")
        parts = (
            (
                await session.execute(
                    select(TestSheetParticipant)
                    .where(TestSheetParticipant.test_sheet_id == sheet_id)
                    .order_by(TestSheetParticipant.row_no)
                )
            ).scalars().all()
            if sheet.with_participants
            else []
        )

    if not (sheet.blank_pdf and sheet.field_boxes):
        raise RuntimeError(f"Varaq #{sheet_id} shabloni topilmadi")
    if sheet.with_participants and not parts:
        # Bo'sh ro'yxatda shtamplash 0 sahifali PDF qaytaradi — Telegram
        # bunday faylni qabul qilmaydi, sabab esa ko'rinmay qoladi.
        raise RuntimeError(f"Varaq #{sheet_id} da ishtirokchi yo'q")

    slug = _ts_slug(sheet.name)

    if not sheet.with_participants:
        await message.answer_document(
            BufferedInputFile(sheet.blank_pdf, filename=f"{slug}_bosh_varaq.pdf"),
            caption=(
                f"📄 **{sheet.name}**\n\n"
                f"Bo'sh javob varag'i — kerakli nusxada chop eting.\n"
                f"O'quvchi yuqoridagi maydonlarni qo'lda to'ldiradi.\n\n"
                f"⚠️ Chop etishda «Actual size» / «100%» tanlang — "
                f"burchaklardagi 4 ta belgi tekshiruvda kerak bo'ladi."
            ),
            parse_mode="Markdown",
        )
        return

    contexts = _ts_contexts(parts)
    pdf_bytes = await stamp_answer_sheets_pdf(
        sheet.blank_pdf, sheet.field_boxes, contexts
    )
    await message.answer_document(
        BufferedInputFile(pdf_bytes, filename=f"{slug}_javob_varaqlari.pdf"),
        caption=(
            f"📄 **{sheet.name}**\n\n"
            f"👥 {len(contexts)} ta javob varag'i, bitta PDF ichida.\n"
            f"Har bir sahifada o'z egasining ma'lumoti va QR kodi bor.\n\n"
            f"⚠️ Chop etishda «Actual size» / «100%» tanlang."
        ),
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------- tekshirish
# Mustaqil varaqni tekshirish olimpiadadagi bilan bir xil OMR yo'lidan
# boradi (services/omr_checker.py), farqi natijaning qayerga borishida:
#   • ishtirokchisiz varaq -> faqat ustiga belgilangan PDF;
#   • ishtirokchili varaq  -> PDF + natijalar Excel'i (bazaga saqlanadi).


class TestSheetCheckStates(StatesGroup):
    """Mustaqil varaqni tekshirish oqimi."""

    waiting_for_image = State()


class TestSheetKeyStates(StatesGroup):
    """Mustaqil varaq uchun javob kaliti va baholash mezoni."""

    waiting_for_key = State()
    waiting_for_rubric = State()


def _rubric_missing_questions(rubric: dict | None, question_count: int) -> list[int]:
    """Oraliqli mezonda ballsiz qolgan savollar ro'yxati."""
    if not rubric or rubric.get("mode") != "ranges":
        return []
    covered: set[int] = set()
    for rng in rubric.get("ranges", []):
        covered.update(range(int(rng["from"]), int(rng["to"]) + 1))
    return sorted(set(range(1, question_count + 1)) - covered)


# Varaq yaratilganda Excel orqali kiritilgan ro'yxatning nomi (guruhi
# yo'q qatorlar) — ekranda va Excel'da shunday ko'rinadi.
EXCEL_BATCH = "Excel ro'yxati"


def _ts_list_keyboard(sheets: list) -> InlineKeyboardMarkup:
    rows = []
    for s in sheets:
        belgi = "👥" if s.with_participants else "📄"
        sana = s.created_at.strftime("%d.%m.%Y") if s.created_at else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{belgi} {s.name} ({sana})", callback_data=f"tsx:{s.id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ts_detail_keyboard(sheet, has_key: bool, has_participants: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=("🔑 Javob kaliti" if not has_key else "🔑 Kalitni o'zgartirish"),
                callback_data=f"tskey:{sheet.id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="📷 Varaqni tekshirish", callback_data=f"tschk:{sheet.id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="📄 Varaqni qayta yuklab olish", callback_data=f"tspdf:{sheet.id}"
            )
        ],
    ]
    if has_participants:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📊 Natijalar (Excel)", callback_data=f"tsxls:{sheet.id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ts_render_detail(message: Message, sheet_id: int, edit: bool = False):
    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
        if not sheet:
            await message.answer("Varaq topilmadi.")
            return
        subs = await _ts_load_subjects(session, sheet_id)
        # Ishtirokchilar varaq yaratilgandan KEYIN ham qo'shilishi mumkin
        # (boshqa guruhga chiqarilganda), shuning uchun `with_participants`
        # bayrog'iga emas, qatorlarning o'ziga qaraymiz (DECISIONS.md #47).
        batches = await _ts_batches(session, sheet_id)
        jami = sum(b["count"] for b in batches)
        tekshirilgan = (
            await session.execute(
                select(func.count())
                .select_from(TestSheetParticipant)
                .where(
                    TestSheetParticipant.test_sheet_id == sheet_id,
                    TestSheetParticipant.checked_at.is_not(None),
                )
            )
        ).scalar_one()

    ro_yxat = "\n".join(
        _fmt_subject_line(s.position, s.name, s.question_count, s.choice_count)
        for s in subs
    )
    kalit_yoq = [s.name for s in subs if not s.answer_key]

    matn = [f"📄 **{sheet.name}**", ""]
    if jami:
        matn.append(f"👥 {jami} ta ishtirokchi, {tekshirilgan} tasi tekshirilgan")
        # Bitta varaq bir nechta guruhga chiqarilgan bo'lishi mumkin
        # (DECISIONS.md #47) — qaysi biriga ekani shu yerda ko'rinadi.
        if len(batches) > 1 or (batches and batches[0]["guruh"]):
            qismlar = [f"{b['guruh'] or EXCEL_BATCH}: {b['count']}" for b in batches]
            matn.append("   " + ", ".join(qismlar))
    else:
        matn.append("📄 Bo'sh varaq (hali ishtirokchi biriktirilmagan)")
    matn += ["", ro_yxat, ""]
    matn.append(
        f"🔑 Javob kaliti kiritilmagan: {', '.join(kalit_yoq)}"
        if kalit_yoq
        else "🔑 Javob kaliti to'liq kiritilgan"
    )
    # Shablon holati. "Eskirgan" va "yo'q" bir xil emas: eskirgani bilan
    # ALLAQACHON BOSIB CHIQARILGAN varaqlarni tekshirish mumkin (qog'oz
    # o'sha koordinatalarga mos), lekin yangi varaq chiqarish kerak
    # bo'lsa uni qaytadan chizish lozim (DECISIONS.md #32).
    if not (sheet.blank_pdf and sheet.field_boxes and sheet.bubble_boxes):
        matn.append(
            "⚠️ Varaq shabloni tayyor emas — «📄 Varaqni qayta yuklab "
            "olish» tugmasi uni qaytadan chizadi."
        )
    elif not blank_is_current(sheet.field_boxes):
        matn.append(
            "ℹ️ Shablon eski formatda. Bosib chiqarilgan varaqlarni "
            "tekshirish ishlayveradi; yangisini chiqarmoqchi bo'lsangiz "
            "«📄 Varaqni qayta yuklab olish» uni yangilab beradi."
        )

    kb = _ts_detail_keyboard(sheet, not kalit_yoq, jami > 0)
    text = "\n".join(matn)
    if edit:
        try:
            await message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.message(F.text == "✅ Javob varag'ini tekshirish")
async def test_sheet_list(message: Message, state: FSMContext):
    async with async_session() as session:
        if not await can_manage_tests(message.chat.id, session):
            return
        sheets = (
            await session.execute(
                select(TestSheet).order_by(TestSheet.created_at.desc()).limit(30)
            )
        ).scalars().all()

    await state.clear()
    if not sheets:
        await message.answer(
            "Hali birorta javob varag'i yaratilmagan.\n\n"
            "Avval \"🆕 Javob varag'i yaratish\" orqali varaq tayyorlang."
        )
        return

    await message.answer(
        "📄 Qaysi varaqni tekshirasiz?", reply_markup=_ts_list_keyboard(sheets)
    )


@router.callback_query(F.data.startswith("tsx:"))
async def ts_open_detail(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        if not await can_manage_tests(callback.from_user.id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
    await callback.answer()
    await state.clear()
    await _ts_render_detail(
        callback.message, int(callback.data.split(":")[1]), edit=True
    )


@router.callback_query(F.data.startswith("tspdf:"))
async def ts_download_menu(callback: CallbackQuery):
    """Varaqni qanday ko'rinishda yuklab olish — tanlov (DECISIONS.md #47).

    Bitta varaq (shablon + javob kaliti) bir nechta guruhga ishlatiladi:
    nusxa ko'paytirmaslik uchun bu yerda faqat KIM uchun chiqarish
    so'raladi — avvalgi ro'yxat, boshqa guruh yoki bo'sh varaq.
    """
    sheet_id = int(callback.data.split(":")[1])
    chat_id = callback.from_user.id
    async with async_session() as session:
        if not await can_manage_tests(chat_id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
        sheet = await session.get(TestSheet, sheet_id)
        if not sheet:
            await callback.answer("Varaq topilmadi.", show_alert=True)
            return
        batches = await _ts_batches(session, sheet_id)

    await callback.answer()
    groups = await classrooms_for(chat_id) if platform_configured() else []
    done = {b["classroom_id"] for b in batches if b["classroom_id"]}

    rows: list[list[InlineKeyboardButton]] = []
    oldingi = next((b for b in batches if b["classroom_id"] is None), None)
    if oldingi:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👥 Avvalgi ro'yxat ({oldingi['count']} ta)",
                    callback_data=f"tsdl:prev:{sheet_id}",
                )
            ]
        )
    for g in groups:
        if not g.student_count:
            continue
        belgi = "🔁" if g.id in done else "👥"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{belgi} {g.label}",
                    callback_data=f"tsdl:grp:{sheet_id}:{g.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="📄 Bo'sh varaq (ma'lumotsiz)",
                callback_data=f"tsdl:blank:{sheet_id}",
            )
        ]
    )

    izoh = ""
    if done:
        izoh = (
            "\n\n🔁 — bu guruhga allaqachon chiqarilgan: o'sha varaqlar qaytadan "
            "keladi, ro'yxatga yangi o'quvchi qo'shilgan bo'lsa ular ham qo'shiladi."
        )
    if not groups and platform_configured():
        izoh += "\n\n_Platformada guruhingiz topilmadi._"

    await callback.message.answer(
        f"📄 **{sheet.name}**\n\nVaraqni kim uchun chiqaramiz?{izoh}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _ts_batches(session, sheet_id: int) -> list[dict]:
    """Varaq qaysi guruhlarga chiqarilgan: (guruh, classroom_id, nechta)."""
    rows = (
        await session.execute(
            select(
                TestSheetParticipant.guruh,
                TestSheetParticipant.classroom_id,
                func.count(TestSheetParticipant.id),
            )
            .where(TestSheetParticipant.test_sheet_id == sheet_id)
            .group_by(TestSheetParticipant.guruh, TestSheetParticipant.classroom_id)
            .order_by(func.min(TestSheetParticipant.row_no))
        )
    ).all()
    return [
        {"guruh": guruh, "classroom_id": classroom_id, "count": count}
        for guruh, classroom_id, count in rows
    ]


@router.callback_query(F.data.startswith("tsdl:"))
async def ts_download_pick(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    kind, sheet_id = parts[1], int(parts[2])
    classroom_id = parts[3] if len(parts) > 3 else None

    async with async_session() as session:
        if not await can_manage_tests(callback.from_user.id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
    await callback.answer("Tayyorlanmoqda...")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        # Shablon yaratilish paytida tayyorlanmagan yoki ESKI formatda
        # qolgan bo'lishi mumkin — ikkala holatda ham qaytadan chiziladi
        # (olimpiada oqimida ham shunday, DECISIONS.md #32).
        async with async_session() as session:
            sheet = await session.get(TestSheet, sheet_id)
            shablon_bor = bool(
                sheet
                and sheet.blank_pdf
                and sheet.field_boxes
                and blank_is_current(sheet.field_boxes)
            )
        if not shablon_bor:
            await callback.message.answer(
                "⏳ Bu varaqning shabloni tayyor emas yoki eski formatda — "
                "hozir qaytadan chiziladi (bir necha daqiqa vaqt olishi mumkin)..."
            )
            await _ts_build_and_store_blank(sheet_id)

        if kind == "blank":
            await _ts_send_blank(callback.message, sheet_id)
        elif kind == "grp":
            await _ts_send_group(callback.message, sheet_id, classroom_id)
        else:
            await _ts_send_batch(callback.message, sheet_id, None, "Avvalgi ro'yxat")
    except Exception as e:
        logger.exception(f"Varaqni qayta jo'natishda xato (#{sheet_id}): {e}")
        await callback.message.answer(f"❌ PDF tayyorlanmadi: {e}")
        await notify_superadmins(
            bot, f"⚠️ Mustaqil varaq PDF'i qayta tayyorlanmadi (#{sheet_id}): {e}"
        )


async def _ts_send_group(message: Message, sheet_id: int, classroom_id: str) -> None:
    """Guruhni varaqqa biriktirib (yangi o'quvchilarini qo'shib) yuboradi."""
    group = await classroom_by_id(classroom_id)
    if group is None:
        await message.answer("Guruh topilmadi — platforma javob bermadi.")
        return
    students = await classroom_students(classroom_id)
    if not students:
        await message.answer(f"«{group.name}» guruhida o'quvchi yo'q.")
        return

    def key(familiya: str, ism: str) -> tuple[str, str]:
        return ((familiya or "").strip().lower(), (ism or "").strip().lower())

    async with async_session() as session:
        mavjud = (
            (
                await session.execute(
                    select(TestSheetParticipant).where(
                        TestSheetParticipant.test_sheet_id == sheet_id,
                        TestSheetParticipant.classroom_id == classroom_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        bor = {key(p.familiya, p.ism) for p in mavjud}
        oxirgi = (
            await session.execute(
                select(func.coalesce(func.max(TestSheetParticipant.row_no), 0)).where(
                    TestSheetParticipant.test_sheet_id == sheet_id
                )
            )
        ).scalar_one()

        yangi: list[TestSheetParticipant] = []
        for s in students:
            if key(s["familiya"], s["ism"]) in bor:
                continue
            oxirgi += 1
            yangi.append(
                TestSheetParticipant(
                    test_sheet_id=sheet_id,
                    row_no=oxirgi,
                    ism=s["ism"],
                    familiya=s["familiya"],
                    birth_date=date.fromisoformat(s["birth_date"]) if s["birth_date"] else None,
                    sinf=s["sinf"],
                    guruh=group.name,
                    classroom_id=classroom_id,
                )
            )
        if yangi:
            session.add_all(yangi)
            await session.flush()
            year = datetime.utcnow().year
            code = f"TS{sheet_id}"
            for r in yangi:
                # ticket_no faqat id ma'lum bo'lgandan keyin — avval
                # chiqarilgan varaqlarning raqami o'zgarmaydi.
                r.ticket_no = build_ticket_no(year, code, r.id)
        # Guruh nomi platformada o'zgargan bo'lsa, eski qatorlarda ham
        # yangilanadi — Excel'da bitta nom ko'rinsin.
        for p in mavjud:
            if p.guruh != group.name:
                p.guruh = group.name
        sheet = await session.get(TestSheet, sheet_id)
        if sheet and not sheet.with_participants:
            sheet.with_participants = True
        await session.commit()

    qoshildi = f"\n➕ {len(yangi)} ta yangi o'quvchi qo'shildi." if yangi and mavjud else ""
    await _ts_send_batch(message, sheet_id, classroom_id, group.name, extra=qoshildi)


async def _ts_send_blank(message: Message, sheet_id: int) -> None:
    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
    if not (sheet and sheet.blank_pdf):
        raise RuntimeError(f"Varaq #{sheet_id} shabloni topilmadi")
    await message.answer_document(
        BufferedInputFile(
            sheet.blank_pdf, filename=f"{_ts_slug(sheet.name)}_bosh_varaq.pdf"
        ),
        caption=(
            f"📄 **{sheet.name}**\n\n"
            f"Bo'sh javob varag'i — kerakli nusxada chop eting.\n"
            f"O'quvchi yuqoridagi maydonlarni qo'lda to'ldiradi.\n\n"
            f"⚠️ Chop etishda «Actual size» / «100%» tanlang — "
            f"burchaklardagi 4 ta belgi tekshiruvda kerak bo'ladi."
        ),
        parse_mode="Markdown",
    )


async def _ts_send_batch(
    message: Message,
    sheet_id: int,
    classroom_id: str | None,
    label: str,
    extra: str = "",
) -> None:
    """Bitta guruhning (yoki birinchi ro'yxatning) varaqlarini yuboradi."""
    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
        if not sheet:
            raise RuntimeError(f"Varaq #{sheet_id} topilmadi")
        query = select(TestSheetParticipant).where(
            TestSheetParticipant.test_sheet_id == sheet_id
        )
        query = query.where(
            TestSheetParticipant.classroom_id == classroom_id
            if classroom_id
            else TestSheetParticipant.classroom_id.is_(None)
        )
        parts = (
            (await session.execute(query.order_by(TestSheetParticipant.row_no)))
            .scalars()
            .all()
        )

    if not (sheet.blank_pdf and sheet.field_boxes):
        raise RuntimeError(f"Varaq #{sheet_id} shabloni topilmadi")
    if not parts:
        await message.answer(
            f"«{label}» uchun ishtirokchi topilmadi. "
            f"Bo'sh varaqni yuklab olishingiz mumkin."
        )
        return

    pdf_bytes = await stamp_answer_sheets_pdf(
        sheet.blank_pdf, sheet.field_boxes, _ts_contexts(parts)
    )
    slug = f"{_ts_slug(sheet.name)}_{_ts_slug(label)}"
    await message.answer_document(
        BufferedInputFile(pdf_bytes, filename=f"{slug}_javob_varaqlari.pdf"),
        caption=(
            f"📄 **{sheet.name}** — {label}\n\n"
            f"👥 {len(parts)} ta javob varag'i, bitta PDF ichida.{extra}\n"
            f"Har bir sahifada o'z egasining ma'lumoti va QR kodi bor.\n\n"
            f"⚠️ Chop etishda «Actual size» / «100%» tanlang."
        ),
        parse_mode="Markdown",
    )


def _ts_contexts(parts: list) -> list[AnswerSheetContext]:
    contexts: list[AnswerSheetContext] = []
    for p in parts:
        if p.birth_date:
            kun = f"{p.birth_date.day:02d}"
            oy = f"{p.birth_date.month:02d}"
            yil = str(p.birth_date.year)
        else:
            kun = oy = yil = "-"
        contexts.append(
            AnswerSheetContext(
                ism=p.ism or "",
                familiya=p.familiya or "",
                kun=kun,
                oy=oy,
                yil=yil,
                sinf=p.sinf or "-",
                ticket_no=p.ticket_no,
            )
        )
    return contexts


# ---- javob kaliti ----------------------------------------------------------


async def _ts_ask_next_key(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    idx, subs = data["tk_index"], data["tk_subjects"]
    if idx >= len(subs):
        return
    s = subs[idx]
    letters = "ABCDE"[: s["choice_count"]]
    current = f"\n\nHozirgi kalit: `{s['answer_key']}`" if s.get("answer_key") else ""
    await message.answer(
        f"🔑 **{s['name']}** uchun to'g'ri javoblarni kiriting.\n\n"
        f"{s['question_count']} ta javob, faqat {letters} harflari.\n"
        f"Masalan: `ABCDA...` yoki `A,B,C,D,A...`{current}",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetKeyStates.waiting_for_key)


@router.callback_query(F.data.startswith("tskey:"))
async def ts_key_start(callback: CallbackQuery, state: FSMContext):
    sheet_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        if not await can_manage_tests(callback.from_user.id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
        subs = await _ts_load_subjects(session, sheet_id)
    await callback.answer()

    await state.clear()
    await state.update_data(
        tk_sheet_id=sheet_id,
        tk_index=0,
        tk_subjects=[
            {
                "id": s.id,
                "name": s.name,
                "question_count": s.question_count,
                "choice_count": s.choice_count,
                "answer_key": s.answer_key,
                "rubric": s.rubric,
            }
            for s in subs
        ],
        return_menu="test_checking",
    )
    await _ts_ask_next_key(callback.message, state)


@router.message(TestSheetKeyStates.waiting_for_key)
async def ts_key_process(message: Message, state: FSMContext):
    data = await state.get_data()
    idx, subs = data["tk_index"], data["tk_subjects"]
    s = subs[idx]
    letters = "ABCDE"[: s["choice_count"]]

    normalized = normalize_answers(message.text or "")
    if not normalized or is_subject_disabled(normalized):
        await message.answer(
            f"Javoblarni tushuna olmadim. Faqat {letters} harflarini kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    key = parse_answer_key(normalized)
    if len(key) != s["question_count"]:
        await message.answer(
            f"❌ {len(key)} ta javob kiritildi, lekin «{s['name']}» fanida "
            f"{s['question_count']} ta savol bor. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return
    bad = sorted({a for a in key if a not in letters})
    if bad:
        await message.answer(
            f"❌ Bu fanda faqat {letters} harflari bo'lishi mumkin, lekin "
            f"{', '.join(bad)} uchradi. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return

    subs[idx]["answer_key"] = normalized
    await state.update_data(tk_subjects=subs)

    current = _rubric_summary(s["rubric"]) if s.get("rubric") else None
    hint = f"\n\nHozirgi mezon: {current}" if current else ""
    await message.answer(
        f"✅ «{s['name']}» kaliti qabul qilindi.\n\n"
        f"📊 Endi shu fanning **baholash mezoni**ni kiriting.\n\n"
        f"{_RUBRIC_HINT}\n\n"
        f"Mezon kerak bo'lmasa — `-` yuboring (har to'g'ri javob 1 ball).{hint}",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetKeyStates.waiting_for_rubric)


@router.message(TestSheetKeyStates.waiting_for_rubric)
async def ts_rubric_process(message: Message, state: FSMContext):
    data = await state.get_data()
    idx, subs = data["tk_index"], data["tk_subjects"]
    s = subs[idx]
    raw = (message.text or "").strip()

    if raw in ("-", "0", "yo'q", "yoq"):
        subs[idx]["rubric"] = None
    else:
        rubric = _parse_rubric_input(raw)
        if not rubric:
            await message.answer(
                f"Mezonni tushuna olmadim.\n\n{_RUBRIC_HINT}\n\n"
                f"Yoki `-` yuboring (har to'g'ri javob 1 ball):",
                parse_mode="Markdown",
                reply_markup=get_cancel_keyboard(),
            )
            return
        missing = _rubric_missing_questions(rubric, s["question_count"])
        if missing:
            preview = ", ".join(map(str, missing[:10]))
            more = "..." if len(missing) > 10 else ""
            await message.answer(
                f"❌ Bu savollar uchun ball ko'rsatilmadi: {preview}{more}\n\n"
                f"«{s['name']}» fanida {s['question_count']} ta savol bor — "
                f"hammasini qamrab oling:",
                reply_markup=get_cancel_keyboard(),
            )
            return
        subs[idx]["rubric"] = json.dumps(rubric)

    await state.update_data(tk_subjects=subs, tk_index=idx + 1)

    if idx + 1 < len(subs):
        await message.answer(f"✅ «{s['name']}» mezoni qabul qilindi.")
        await _ts_ask_next_key(message, state)
        return

    sheet_id = data["tk_sheet_id"]
    try:
        async with async_session() as session:
            for x in subs:
                row = await session.get(TestSheetSubject, x["id"])
                if row:
                    row.answer_key = x["answer_key"]
                    row.rubric = x["rubric"]
            await session.commit()
    except Exception as e:
        logger.exception(f"Mustaqil varaq kalitini saqlashda xato: {e}")
        await state.clear()
        await message.answer("❌ Saqlashda xatolik. Qaytadan urinib ko'ring.")
        return

    await state.clear()
    xulosa = "\n".join(
        f"  • {x['name']}: {_rubric_summary(x['rubric'])}" for x in subs
    )
    await message.answer(
        f"✅ Javob kaliti va mezon saqlandi:\n\n{xulosa}",
        reply_markup=get_test_checking_menu_keyboard(),
    )
    await _ts_render_detail(message, sheet_id)


# ---- tekshirish ------------------------------------------------------------


@router.callback_query(F.data.startswith("tschk:"))
async def ts_check_start(callback: CallbackQuery, state: FSMContext):
    sheet_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        if not await can_manage_tests(callback.from_user.id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
        sheet = await session.get(TestSheet, sheet_id)
        subs = await _ts_load_subjects(session, sheet_id)
    await callback.answer()

    if not (sheet and sheet.field_boxes and sheet.bubble_boxes):
        await callback.message.answer(
            "❌ Bu varaqning shabloni tayyor emas.\n\n"
            "«📄 Varaqni qayta yuklab olish» tugmasini bosing — shablon "
            "qaytadan chiziladi, shundan keyin tekshirish ishlaydi."
        )
        return
    missing = [s.name for s in subs if not s.answer_key]
    if missing:
        await callback.message.answer(
            f"❌ Javob kaliti kiritilmagan: {', '.join(missing)}.\n\n"
            f"Avval \"🔑 Javob kaliti\" tugmasini bosing."
        )
        return

    await state.clear()
    await state.update_data(tc_sheet_id=sheet_id, return_menu="test_checking")
    qosh = (
        ""
        if sheet.with_participants
        else "\n\n⚠️ Bu bo'sh varaq — kim yozgani noma'lum, shuning uchun "
        "natija saqlanmaydi, faqat belgilangan PDF qaytadi."
    )
    await callback.message.answer(
        f"📷 **{sheet.name}** varaqlarining rasmini yoki skanini yuboring.\n\n"
        f"• Rasm sifatida ham, fayl (PDF/JPG) sifatida ham bo'ladi\n"
        f"• Varaqning TO'RTALA burchagi ham rasmga tushsin\n"
        f"• Ko'p varaqni bitta PDF qilib yuborsangiz, hammasi tekshiriladi"
        f"{qosh}",
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(),
    )
    await state.set_state(TestSheetCheckStates.waiting_for_image)


@router.message(TestSheetCheckStates.waiting_for_image, F.photo | F.document)
async def ts_check_process(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    sheet_id = data.get("tc_sheet_id")
    if not sheet_id:
        await state.clear()
        return

    file_id = message.document.file_id if message.document else message.photo[-1].file_id
    status = await message.answer("⏳ Varaq o'qilmoqda...")
    try:
        file_info = await bot.get_file(file_id)
        buf = await bot.download_file(file_info.file_path)
        raw = buf.read()
    except Exception as e:
        logger.exception(f"Varaq faylini yuklashda xato: {e}")
        await status.edit_text("❌ Faylni yuklab bo'lmadi. Qaytadan yuboring.")
        return

    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
        subs = await _ts_load_subjects(session, sheet_id)

    # Varaq boshqa sessiyada o'chirilgan bo'lishi mumkin — FSM ichida
    # turganda ham.
    if not (sheet and sheet.field_boxes and sheet.bubble_boxes and subs):
        await state.clear()
        await status.edit_text(
            "❌ Bu varaq endi mavjud emas yoki shabloni yo'q. "
            "Ro'yxatdan qaytadan tanlang."
        )
        return

    keys = {s.name: parse_answer_key(s.answer_key) for s in subs}
    rubrics = {s.name: s.rubric for s in subs}
    with_participants = sheet.with_participants
    field_boxes, bubble_boxes, sheet_name = (
        sheet.field_boxes,
        sheet.bubble_boxes,
        sheet.name,
    )

    try:
        total_pages = await asyncio.to_thread(sheet_page_count, raw)
    except OmrError as e:
        await status.edit_text(f"❌ {e}")
        return

    lines: list[str] = []
    saved = 0
    annotated_pages: list[bytes] = []
    # Sahifalar birma-bir — xotira sababi olimpiada oqimidagi bilan bir xil.
    for page_no in range(1, total_pages + 1):
        prefix = f"{page_no}-varaq: " if total_pages > 1 else ""
        try:
            img = await asyncio.to_thread(sheet_page_image, raw, page_no - 1)
            result = await asyncio.to_thread(
                check_sheet,
                img,
                field_boxes,
                bubble_boxes,
                keys,
                with_participants,  # QR faqat ishtirokchili varaqda majburiy
            )
        except OmrError as e:
            lines.append(f"❌ {prefix}{e}")
            continue
        if result.annotated_png:
            annotated_pages.append(result.annotated_png)

        if not with_participants:
            # Bo'sh varaq: natija hech kimga tegishli emas — PDF'ning
            # o'zi javob (foydalanuvchi shunday so'ragan).
            continue

        ok, msg = await _ts_save_result(sheet_id, result, keys, rubrics, prefix)
        saved += 1 if ok else 0
        lines.append(msg)

    if with_participants:
        await status.edit_text(
            f"📷 Tekshirildi: {saved}/{total_pages} varaq\n\n" + "\n".join(lines),
            parse_mode="Markdown",
        )
    else:
        xato = "\n".join(lines)
        await status.edit_text(
            f"📷 {len(annotated_pages)}/{total_pages} varaq belgilandi."
            + (f"\n\n{xato}" if xato else "")
        )

    if annotated_pages:
        try:
            await _send_annotated_sheets(
                message, annotated_pages, f"{_ts_slug(sheet_name)}_tekshirilgan"
            )
        except Exception as e:
            logger.exception(f"Belgilangan PDF yig'ishda xato: {e}")
            await message.answer("⚠️ Belgilangan PDF tayyorlanmadi.")

    if with_participants and saved:
        await _ts_send_results_excel(message, sheet_id)

    await message.answer(
        "Keyingi varaqni yuboring yoki \"❌ Bekor qilish\" bosing.",
        reply_markup=get_cancel_keyboard(),
    )


@router.message(TestSheetCheckStates.waiting_for_image)
async def ts_check_wrong_input(message: Message):
    await message.answer(
        "Iltimos, varaqning rasmini yoki faylini yuboring.",
        reply_markup=get_cancel_keyboard(),
    )


async def _ts_save_result(
    sheet_id: int,
    result,
    keys: dict[str, list[str]],
    rubrics: dict[str, str | None],
    prefix: str,
) -> tuple[bool, str]:
    """Bitta varaq natijasini ishtirokchiga yozadi.

    Olimpiadadagi bilan bir xil qoidalar: mezon bo'lsa og'irlikli ball,
    bo'lmasa to'g'ri javoblar soni; bir varaq ikki marta tekshirilsa
    natija QAYTA YOZILMAYDI (DECISIONS.md #31).

    `detail` bu yerda olimpiadadagidan boshqacha — qat'iy ikki fanga
    ("matematika"/"ingliz_tili") bog'lanmagan, fanlar TARTIBI bo'yicha
    ro'yxat: mustaqil varaqda fanlar ixtiyoriy (1-3 ta) va nomlari ham
    har xil bo'lishi mumkin.
    """
    async with async_session() as session:
        row = (
            await session.execute(
                select(TestSheetParticipant).where(
                    TestSheetParticipant.test_sheet_id == sheet_id,
                    TestSheetParticipant.ticket_no == result.ticket_no,
                )
            )
        ).scalar_one_or_none()

        if not row:
            return False, (
                f"❌ {prefix}{result.ticket_no} — bu ID bo'yicha ishtirokchi "
                f"topilmadi."
            )
        if row.checked_at is not None:
            when = row.checked_at.strftime("%d.%m.%Y %H:%M")
            ism = f"{row.familiya} {row.ism}".strip() or result.ticket_no
            return False, (
                f"⏭ {prefix}{ism} — allaqachon tekshirilgan ({when}), saqlanmadi."
            )

        total_correct = total_questions = 0
        total_score = total_max = 0.0
        has_rubric = False
        subjects_detail: list[dict] = []
        per_subject: list[str] = []

        for subj in result.subjects:
            key = keys.get(subj.name) or []
            mask = [
                got is not None and got == want for got, want in zip(subj.answers, key)
            ]
            correct = sum(1 for x in mask if x)
            total_correct += correct
            total_questions += len(key)

            subj_score, subj_max, subj_detail = apply_rubric(
                mask, rubrics.get(subj.name), correct
            )
            total_score += subj_score
            total_max += subj_max
            if subj_detail:
                has_rubric = True

            subjects_detail.append(
                {
                    "name": subj.name,
                    "correct": correct,
                    "total": len(key),
                    # Mezon bo'lmasa tafsilot yozilmaydi — Excel o'shanda
                    # oddiy "To'g'ri/Jami" ustunlarini chizadi (#33).
                    "blocks": subj_detail or None,
                }
            )

            warn = f" ⚠️{len(subj.multi)}ta ko'p belgilangan" if subj.multi else ""
            ball = f" ({fmt_number(subj_score)} ball)" if subj_detail else ""
            per_subject.append(f"{subj.name}: {correct}/{len(key)}{ball}{warn}")

        row.score = round(total_score, 2)
        row.percentage = round(total_score / total_max * 100, 2) if total_max else None
        row.detail = json.dumps({"subjects": subjects_detail}, ensure_ascii=False)
        row.checked_at = datetime.utcnow()
        await session.commit()

        ism = f"{row.familiya} {row.ism}".strip() or "-"

    jami = f"{total_correct}/{total_questions}"
    if has_rubric:
        jami += f" — **{fmt_number(total_score)}/{fmt_number(total_max)} ball**"
    return True, (
        f"✅ {prefix}**{ism}** ({result.ticket_no})\n"
        f"   {' | '.join(per_subject)}\n"
        f"   Jami: {jami}"
    )


# ---- natijalar Excel'i -----------------------------------------------------


def _ts_write_results_sheet(ws, rows: list[dict], title: str, labels: list[str]) -> None:
    """Natijalar jadvali — olimpiadadagi `_write_results_sheet` bilan bir
    xil ko'rinish, farqi ikkitasi:

      • fan soni qat'iy 2 ta emas, `labels` nechta bo'lsa shuncha
        (mustaqil varaqda 1-3 ta fan bo'lishi mumkin);
      • "Telegram Chat ID" ustuni yo'q — bu odamlar botda ro'yxatdan
        o'tmagan bo'lishi mumkin (DECISIONS.md #34).

    Ustun ichidagi sarlavhalar bu yerda ham MA'LUMOTDAN hisoblanadi
    (`_subject_blocks` + `_ball_header_text`), ya'ni kiritilgan mezonga
    qarab o'zgaradi (#33).
    """
    fixed_headers = ["№", "F.I.Sh", "Sinf", "Guruh", "O'rin"]
    blocks_per_subject = [
        _subject_blocks(rows, f"s{i}_detail") for i in range(len(labels))
    ]

    col = len(fixed_headers) + 1
    starts = []
    for blocks in blocks_per_subject:
        starts.append(col)
        col += len(blocks) * 2
    ball_col, percent_col = col, col + 1
    total_cols = percent_col

    title_cell = ws.cell(1, 1, title)
    title_cell.font = _RESULTS_TITLE_FONT
    title_cell.alignment = _RESULTS_HEADER_ALIGN
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)

    HEADER_TOP, HEADER_SUB, DATA_START = 2, 3, 4
    full_column_fills: list[tuple[int, PatternFill]] = [(3, _SINF_HEADER_FILL)]

    for i, h in enumerate(fixed_headers, 1):
        c = ws.cell(HEADER_TOP, i, h)
        c.font = _RESULTS_HEADER_FONT
        c.alignment = _RESULTS_HEADER_ALIGN
        if i == 3:
            c.fill = _SINF_HEADER_FILL
        ws.merge_cells(
            start_row=HEADER_TOP, start_column=i, end_row=HEADER_SUB, end_column=i
        )

    for label, start, blocks in zip(labels, starts, blocks_per_subject):
        end = start + len(blocks) * 2 - 1
        c = ws.cell(HEADER_TOP, start, label)
        c.font = _RESULTS_HEADER_FONT
        c.alignment = _RESULTS_HEADER_ALIGN
        c.fill = _SUBJECT_HEADER_FILL
        if end > start:
            ws.merge_cells(
                start_row=HEADER_TOP,
                start_column=start,
                end_row=HEADER_TOP,
                end_column=end,
            )
        cc = start
        for b in blocks:
            if b["kind"] == "detail":
                t1, t2 = f"{b['label']}-savollar", _ball_header_text(b)
            else:
                t1, t2 = "To'g'ri", "Jami"
            w1 = ws.cell(HEADER_SUB, cc, t1)
            w1.font = _RESULTS_HEADER_FONT
            w1.alignment = _RESULTS_HEADER_ALIGN
            w2 = ws.cell(HEADER_SUB, cc + 1, t2)
            w2.font = _RESULTS_HEADER_FONT
            w2.alignment = _RESULTS_HEADER_ALIGN
            w2.fill = _BALL_COL_HEADER_FILL
            full_column_fills.append((cc + 1, _BALL_COL_HEADER_FILL))
            cc += 2

    for label, cidx, fill in (
        ("Umumiy ball", ball_col, _BALL_TOTAL_HEADER_FILL),
        ("Umumiy foiz (%)", percent_col, _PERCENT_HEADER_FILL),
    ):
        c = ws.cell(HEADER_TOP, cidx, label)
        c.font = _RESULTS_HEADER_FONT
        c.alignment = _RESULTS_HEADER_ALIGN
        c.fill = fill
        ws.merge_cells(
            start_row=HEADER_TOP, start_column=cidx, end_row=HEADER_SUB, end_column=cidx
        )
        full_column_fills.append((cidx, fill))

    ws.freeze_panes = f"A{DATA_START}"

    r = DATA_START
    for row in rows:
        ws.cell(r, 1, row["no"])
        ws.cell(r, 2, row["name"])
        ws.cell(r, 3, row.get("sinf") or "-")
        ws.cell(r, 4, row.get("guruh") or "-")
        ws.cell(r, 5, row["place"] if row.get("place") is not None else "-")
        for i, (start, blocks) in enumerate(zip(starts, blocks_per_subject)):
            detail = row.get(f"s{i}_detail")
            cc = start
            if detail:
                for d in detail:
                    ws.cell(r, cc, d.get("correct") if d.get("correct") is not None else "-")
                    ws.cell(
                        r,
                        cc + 1,
                        round(d["score"], 2) if d.get("score") is not None else "-",
                    )
                    cc += 2
            elif len(blocks) == 1 and blocks[0]["kind"] == "aggregate":
                ws.cell(r, cc, row.get(f"s{i}_correct", "-"))
                ws.cell(r, cc + 1, row.get(f"s{i}_total", "-"))
            else:
                for _ in blocks:
                    ws.cell(r, cc, "-")
                    ws.cell(r, cc + 1, "-")
                    cc += 2
        ws.cell(r, ball_col, round(row["score"], 2) if row.get("score") is not None else "-")
        ws.cell(
            r,
            percent_col,
            round(row["percentage"], 2) if row.get("percentage") is not None else "-",
        )
        r += 1

    last_row = r - 1
    for col_idx, fill in full_column_fills:
        for rr in range(HEADER_TOP, last_row + 1):
            ws.cell(rr, col_idx).fill = fill

    for i in range(1, total_cols + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14


def _ts_build_results_rows(parts: list, labels: list[str]) -> list[dict]:
    """Ishtirokchi yozuvlarini Excel qatorlariga aylantiradi.

    O'rin SHU YERDA hisoblanadi (ball bo'yicha kamayish tartibida, teng
    ballga teng o'rin) — mustaqil varaqda sinflar aralash bo'lishi
    mumkin, shuning uchun olimpiadadagidek sinf ichida emas, butun
    ro'yxat bo'yicha.
    """
    checked = [p for p in parts if p.checked_at is not None]
    checked.sort(key=lambda p: (-(p.score or 0.0), (p.familiya or ""), (p.ism or "")))
    places: dict[int, int] = {}
    oldingi_ball, oldingi_orin = None, 0
    for i, p in enumerate(checked, 1):
        if p.score != oldingi_ball:
            oldingi_orin, oldingi_ball = i, p.score
        places[p.id] = oldingi_orin

    rows = []
    ketma_ket = sorted(
        parts, key=lambda p: (p.checked_at is None, places.get(p.id, 10**6), p.row_no)
    )
    for idx, p in enumerate(ketma_ket, 1):
        detail = {}
        if p.detail:
            try:
                detail = json.loads(p.detail)
            except (TypeError, ValueError):
                detail = {}
        subjects = detail.get("subjects", [])
        row = {
            "no": idx,
            "name": f"{p.familiya or ''} {p.ism or ''}".strip() or "-",
            "sinf": p.sinf,
            # Bitta varaq bir nechta guruhga chiqarilishi mumkin — natijalar
            # bitta jadvalda, lekin guruh ustuni bilan (DECISIONS.md #47).
            "guruh": p.guruh or EXCEL_BATCH,
            "place": places.get(p.id),
            "score": p.score,
            "percentage": p.percentage,
        }
        for i, label in enumerate(labels):
            s = next((x for x in subjects if x.get("name") == label), None)
            row[f"s{i}_detail"] = (s or {}).get("blocks")
            row[f"s{i}_correct"] = (s or {}).get("correct")
            row[f"s{i}_total"] = (s or {}).get("total")
        rows.append(row)
    return rows


async def _ts_send_results_excel(message: Message, sheet_id: int) -> None:
    async with async_session() as session:
        sheet = await session.get(TestSheet, sheet_id)
        subs = await _ts_load_subjects(session, sheet_id)
        parts = (
            await session.execute(
                select(TestSheetParticipant)
                .where(TestSheetParticipant.test_sheet_id == sheet_id)
                .order_by(TestSheetParticipant.row_no)
            )
        ).scalars().all()

    if not parts:
        await message.answer("Bu varaqda ishtirokchi yo'q.")
        return

    labels = [s.name for s in subs]
    rows = _ts_build_results_rows(parts, labels)

    wb = Workbook()
    ws = wb.active
    ws.title = "Natijalar"
    _ts_write_results_sheet(ws, rows, f"{sheet.name} — natijalar", labels)

    buf = io.BytesIO()
    wb.save(buf)
    tekshirilgan = sum(1 for p in parts if p.checked_at is not None)
    await message.answer_document(
        BufferedInputFile(
            buf.getvalue(), filename=f"{_ts_slug(sheet.name)}_natijalar.xlsx"
        ),
        caption=(
            f"📊 **{sheet.name}**\n\n"
            f"👥 {len(parts)} ta ishtirokchi, {tekshirilgan} tasi tekshirilgan."
        ),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("tsxls:"))
async def ts_results_excel(callback: CallbackQuery):
    sheet_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        if not await can_manage_tests(callback.from_user.id, session):
            await callback.answer("Sizda ushbu huquq yo'q!", show_alert=True)
            return
    await callback.answer("Tayyorlanmoqda...")
    try:
        await _ts_send_results_excel(callback.message, sheet_id)
    except Exception as e:
        logger.exception(f"Mustaqil varaq natijalari Excel'ida xato: {e}")
        await callback.message.answer("❌ Excel tayyorlanmadi.")
