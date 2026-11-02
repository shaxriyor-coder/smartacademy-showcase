"""SmartAcademy platformasi bilan bog'lanish: "Open App" tugmasi.

Platforma (Next.js, shu repozitoriyning ildizi) shu botning Mini App'i sifatida
ochiladi va kimligini o'zi aniqlaydi — Telegram imzosi, shu botning `admins`
jadvali va SUPERADMIN_IDS orqali (faqat o'qiydi): xodimga o'z paneli,
qolganlarga o'quvchi/ota-ona kabineti. Botdan faqat tugma kerak
(docs/DECISIONS.md #38, platformaning docs/DECISIONS.md #27).

Telegram Mini App'ni faqat HTTPS manzildan ochadi: PLATFORM_URL https://
bilan boshlanmasa tugmalar qo'shilmaydi va bot avvalgidek ishlaydi.
"""

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from config import DEFAULT_SUPERADMIN_IDS, PLATFORM_URL
from database.db import async_session
from database.models import Admin, ChatMenuButton, User

logger = logging.getLogger(__name__)

OPEN_APP_TEXT = "Open App"

# Telegram cheklovidan ancha past: tugma yangilash xabar emas, lekin baribir API
# chaqiruvi — minglab foydalanuvchida ham bot boshqa ishlariga xalaqit bermasin.
MENU_SYNC_DELAY = 0.05  # sekund (≈20 ta chat/sekund)


def platform_webapp_url() -> str | None:
    """Platformadagi Mini App kirish sahifasi (/tg) yoki sozlanmagan bo'lsa None."""
    if not PLATFORM_URL.startswith("https://"):
        return None
    return f"{PLATFORM_URL}/tg"


async def setup_menu_button(bot: Bot) -> None:
    """Hamma chatlarda xabar maydoni yonidagi menyu tugmasini "Open App" qiladi.

    Xato botni to'xtatmaydi: tugmasiz ham botning barcha funksiyalari ishlaydi.
    """
    url = platform_webapp_url()
    if not url:
        if PLATFORM_URL:
            logger.warning(
                "PLATFORM_URL https:// bilan boshlanishi kerak — Open App tugmasi qo'shilmadi"
            )
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text=OPEN_APP_TEXT, web_app=WebAppInfo(url=url))
        )
        logger.info("Open App tugmasi o'rnatildi: %s", url)
    except Exception as e:
        logger.warning("Open App tugmasini o'rnatib bo'lmadi: %s", e)


async def sync_menu_buttons(bot: Bot) -> None:
    """Manzil o'zgargan bo'lsa "Open App" tugmasini har bir chatga qayta beradi.

    Nega kerak: umumiy (default) tugma o'zgarganda Telegram ilovalari buni
    darhol bilmaydi — eski manzilni keshda saqlab, ishlamay qolgan sahifani
    ochadi (lokal namoyishda tunnel manzili har ishga tushishda yangi bo'ladi,
    serverga ko'chganda ham tunneldan domenga o'tadi). Chatga alohida
    o'rnatilgan tugmani esa Telegram o'sha foydalanuvchining ilovasiga
    darhol yuboradi.

    Kimga: ro'yxatdan o'tganlar, `admins` jadvalidagilar va SUPERADMIN_IDS —
    xodimlar ko'pincha ro'yxatdan o'tmaydi, lekin "Open App" ni aynan ular
    ko'p ochadi. Faqat oxirgi berilgan manzili (chat_menu_buttons) farq
    qiladigan chatlarga yuboriladi, shuning uchun manzil o'zgarmagan qayta
    ishga tushishlarda hech narsa qilinmaydi. PLATFORM_URL olib tashlansa —
    bot o'zi bergan tugmalar olib tashlanadi.
    Fonda ishlaydi: xato botni to'xtatmaydi (DECISIONS.md #42).
    """
    target = platform_webapp_url()
    async with async_session() as session:
        known = dict(
            (await session.execute(select(ChatMenuButton.chat_id, ChatMenuButton.url))).all()
        )
        if target:
            chats = set((await session.execute(select(User.id))).scalars().all())
            chats |= set((await session.execute(select(Admin.id))).scalars().all())
            chats |= set(DEFAULT_SUPERADMIN_IDS) | set(known)
            chat_ids = sorted(c for c in chats if known.get(c) != target)
        else:
            chat_ids = sorted(c for c, url in known.items() if url is not None)

    if not chat_ids:
        return

    button = (
        MenuButtonWebApp(text=OPEN_APP_TEXT, web_app=WebAppInfo(url=target))
        if target
        else MenuButtonDefault()
    )
    done, failed = 0, 0
    for chat_id in chat_ids:
        try:
            await _set_chat_button(bot, chat_id, button)
        except (TelegramForbiddenError, TelegramBadRequest):
            # Botni bloklagan yoki chat yo'q — har safar qayta urinmaymiz;
            # qaytib kelsa, manzil keyingi o'zgarishda yana yuboriladi.
            pass
        except Exception as e:
            failed += 1
            logger.warning("Open App tugmasi chat %s ga yuborilmadi: %s", chat_id, e)
            continue
        async with async_session() as session:
            now = datetime.utcnow()
            await session.execute(
                insert(ChatMenuButton)
                .values(chat_id=chat_id, url=target, updated_at=now)
                .on_conflict_do_update(
                    index_elements=[ChatMenuButton.chat_id],
                    set_={"url": target, "updated_at": now},
                )
            )
            await session.commit()
        done += 1
        await asyncio.sleep(MENU_SYNC_DELAY)

    logger.info(
        "Open App tugmasi %s ta chatda yangilandi%s",
        done,
        f", {failed} tasida xato (keyingi ishga tushishda qayta urinadi)" if failed else "",
    )


async def _set_chat_button(bot: Bot, chat_id: int, button) -> None:
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)


def open_app_keyboard() -> InlineKeyboardMarkup | None:
    url = platform_webapp_url()
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📱 {OPEN_APP_TEXT}", web_app=WebAppInfo(url=url))]
        ]
    )


async def send_open_app(message: Message) -> None:
    """/start salomlashuvidan keyin platformaga kirish tugmasi (sozlangan bo'lsa)."""
    keyboard = open_app_keyboard()
    if keyboard:
        await message.answer(
            "Testlar, natijalar, tahlil va boshqaruv paneli — SmartAcademy platformasida:",
            reply_markup=keyboard,
        )
