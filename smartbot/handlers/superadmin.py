import html
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, delete
from database.db import async_session
from database.models import Admin
from config import DEFAULT_SUPERADMIN_IDS
from utils.roles import (
    get_staff_role,
    ROLE_SUPERADMIN,
    ROLE_LABELS,
    ASSIGNABLE_ROLES,
)

router = Router()


class SuperAdminStates(StatesGroup):
    waiting_for_add_id = State()
    waiting_for_add_username = State()
    waiting_for_add_role = State()
    waiting_for_remove_id = State()


def get_superadmin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Xodimlar ro'yxati")],
            [
                KeyboardButton(text="➕ Xodim qo'shish"),
                KeyboardButton(text="❌ Xodim o'chirish"),
            ],
            [KeyboardButton(text="🛠 Admin panelga o'tish")],
            [KeyboardButton(text="🔙 Bosh menyu")],
        ],
        resize_keyboard=True,
    )


async def is_superadmin(chat_id: int, session) -> bool:
    """Checks if the user is a SuperAdmin (either default or in database)."""
    role = await get_staff_role(chat_id, session)
    return role == ROLE_SUPERADMIN


@router.message(Command("superadmin"))
async def superadmin_panel(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_superadmin(chat_id, session):
            await message.answer("Sizda ushbu komandadan foydalanish ruxsati yo'q.")
            return

        await message.answer(
            "⚡ <b>SuperAdmin Boshqaruv Paneli:</b>\n\nTizimdagi xodimlarni (Admin, "
            "O'qituvchi, SMM menejer) boshqarish uchun quyidagi tugmalardan foydalaning:",
            reply_markup=get_superadmin_keyboard(),
            parse_mode="HTML",
        )


# 1. VIEW STAFF LIST
@router.message(F.text == "👥 Xodimlar ro'yxati")
async def list_admins(message: Message):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_superadmin(chat_id, session):
            return

        result = await session.execute(select(Admin))
        admins = result.scalars().all()

        txt = "👥 <b>Tizimdagi barcha xodimlar:</b>\n\n"

        # Asosiy (konfiguratsiyadagi) superadminlar
        txt += "⭐️ <b>Asosiy SuperAdminlar (Konfiguratsiya):</b>\n"
        for sa_id in DEFAULT_SUPERADMIN_IDS:
            txt += f"  • ID: <code>{sa_id}</code> (Asosiy tizim egasi)\n"

        # Qolganlarini rol bo'yicha guruhlab ko'rsatamiz
        by_role: dict[str, list[Admin]] = {}
        for adm in admins:
            by_role.setdefault(adm.role, []).append(adm)

        for role_key, role_label in ROLE_LABELS.items():
            group = by_role.get(role_key, [])
            if role_key == ROLE_SUPERADMIN and not group:
                continue  # DB orqali qo'shilgan qo'shimcha superadmin bo'lmasa, o'tkazamiz
            txt += f"\n🔑 <b>{html.escape(role_label)}:</b>\n"
            if not group:
                txt += "  <i>(Hozircha yo'q)</i>\n"
            else:
                for i, adm in enumerate(group, 1):
                    username_escaped = html.escape(adm.username) if adm.username else ""
                    usr_str = f" (@{username_escaped})" if username_escaped else ""
                    txt += f"  {i}. ID: <code>{adm.id}</code>{usr_str}\n"

        await message.answer(txt, parse_mode="HTML")


# 2. ADD STAFF (Admin / O'qituvchi / SMM menejer)
@router.message(F.text == "➕ Xodim qo'shish")
async def start_add_admin(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_superadmin(chat_id, session):
            return

        await message.answer(
            "Yangi xodimning <b>Telegram Chat ID</b> sini kiriting:\n"
            "(ID ni foydalanuvchi profile_bot yoki botlar orqali olishi mumkin)",
            parse_mode="HTML",
        )
        await state.set_state(SuperAdminStates.waiting_for_add_id)


@router.message(SuperAdminStates.waiting_for_add_id)
async def process_new_admin_id(message: Message, state: FSMContext):
    target_id_str = (message.text or "").strip()
    if not target_id_str.isdigit():
        await message.answer(
            "Chat ID faqat sonlardan iborat bo'lishi lozim. Qaytadan kiriting:"
        )
        return

    target_id = int(target_id_str)
    await state.update_data(target_id=target_id)
    await message.answer(
        "Yangi xodimning Telegram usernameni kiriting (Masalan: admin_user) (Agar yo'q bo'lsa '-' kiriting):"
    )
    await state.set_state(SuperAdminStates.waiting_for_add_username)


@router.message(SuperAdminStates.waiting_for_add_username)
async def process_new_admin_username(message: Message, state: FSMContext):
    username = (message.text or "").replace("@", "").strip()
    if username == "-":
        username = None

    await state.update_data(username=username)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=ROLE_LABELS[role], callback_data=f"sadmin_role:{role}"
                )
            ]
            for role in ASSIGNABLE_ROLES
        ]
    )
    await message.answer(
        "Ushbu xodimga qaysi rolni berasiz?", reply_markup=kb
    )
    await state.set_state(SuperAdminStates.waiting_for_add_role)


@router.callback_query(
    SuperAdminStates.waiting_for_add_role, F.data.startswith("sadmin_role:")
)
async def process_new_admin_role(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split(":", 1)[1]
    if role not in ASSIGNABLE_ROLES:
        await callback.answer("Noto'g'ri rol.", show_alert=True)
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    username = data.get("username")

    if not target_id:
        await callback.answer("Jarayon eskirgan. Qaytadan boshlang.", show_alert=True)
        await state.clear()
        return

    async with async_session() as session:
        # Check if already exists
        res = await session.execute(select(Admin).where(Admin.id == target_id))
        existing_admin = res.scalar_one_or_none()

        if existing_admin:
            await callback.answer()
            await callback.message.edit_text(
                "Ushbu foydalanuvchi allaqachon xodimlar tizimida mavjud."
            )
            await state.clear()
            return

        new_admin = Admin(id=target_id, role=role, username=username)
        session.add(new_admin)
        await session.commit()

    username_display = html.escape(username) if username else "Kiritilmagan"
    await callback.answer("Qo'shildi ✅")
    await callback.message.edit_text(
        f"Muvaffaqiyatli qo'shildi! 🚀\n\n"
        f"👤 ID: <code>{target_id}</code>\n"
        f"🏷 Username: {f'@{username_display}' if username else username_display}\n"
        f"🔑 Roli: <b>{html.escape(ROLE_LABELS[role])}</b>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Bosh menyu:", reply_markup=get_superadmin_keyboard()
    )
    await state.clear()


# 3. DELETE STAFF
@router.message(F.text == "❌ Xodim o'chirish")
async def start_remove_admin(message: Message, state: FSMContext):
    chat_id = message.chat.id
    async with async_session() as session:
        if not await is_superadmin(chat_id, session):
            return

        await message.answer(
            "O'chirmoqchi bo'lgan xodimning <b>Telegram Chat ID</b> sini kiriting:",
            parse_mode="HTML",
        )
        await state.set_state(SuperAdminStates.waiting_for_remove_id)


@router.message(SuperAdminStates.waiting_for_remove_id)
async def process_remove_admin_id(message: Message, state: FSMContext):
    target_id_str = (message.text or "").strip()
    if not target_id_str.isdigit():
        await message.answer(
            "Chat ID faqat sonlardan iborat bo'lishi lozim. Qaytadan kiriting:"
        )
        return

    target_id = int(target_id_str)

    if target_id in DEFAULT_SUPERADMIN_IDS:
        await message.answer("Asosiy tizim SuperAdminini o'chirib bo'lmaydi!")
        await state.clear()
        return

    async with async_session() as session:
        res = await session.execute(select(Admin).where(Admin.id == target_id))
        admin = res.scalar_one_or_none()

        if not admin:
            await message.answer("Ushbu ID dagi xodim topilmadi.")
            await state.clear()
            return

        role_label = ROLE_LABELS.get(admin.role, admin.role)
        await session.execute(delete(Admin).where(Admin.id == target_id))
        await session.commit()

    await message.answer(
        f"Muvaffaqiyatli o'chirildi! 🗑\n\n"
        f"ID: <code>{target_id}</code> ({html.escape(role_label)}) xodimlik huquqidan mahrum qilindi.",
        reply_markup=get_superadmin_keyboard(),
        parse_mode="HTML",
    )
    await state.clear()


@router.message(F.text == "🔙 Bosh menyu")
async def return_to_main_menu(message: Message):
    # Sends the regular user keyboard back
    await message.answer(
        "Bosh menyuga qaytdingiz.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🏆 Olimpiadalar")],
                [KeyboardButton(text="🏅 Natijalarim")],
                [KeyboardButton(text="ℹ️ Malumotlarim")],
            ],
            resize_keyboard=True,
        ),
    )
