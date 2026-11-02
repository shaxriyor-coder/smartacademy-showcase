import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database.db import init_db
from handlers.user import router as user_router
from handlers.admin import router as admin_router
from handlers.superadmin import router as superadmin_router
from utils.platform import setup_menu_button, sync_menu_buttons

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        logger.error("Fondagi vazifa xato bilan tugadi: %r", task.exception())


async def main():
    # Initialize Database
    logger.info("Initializing PostgreSQL Database schemas...")
    await init_db()

    # Initialize Bot & Dispatcher
    logger.info("Starting Telegram Bot Polling...")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # "Open App" — SmartAcademy platformasi (PLATFORM_URL berilgan bo'lsa).
    # Manzil o'zgargan bo'lsa har bir chatga fonda qayta yuboriladi, aks holda
    # Telegram ilovalari eski manzilni ochib yuradi (DECISIONS.md #42).
    await setup_menu_button(bot)
    menu_sync = asyncio.create_task(sync_menu_buttons(bot))
    menu_sync.add_done_callback(_log_task_error)

    # Register handlers
    dp.include_router(user_router)
    dp.include_router(superadmin_router)
    dp.include_router(admin_router)

    # Run polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Critical error in Telegram Bot process: {e}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Telegram Bot stopped.")
