"""Tizimdagi rollarni aniqlash uchun umumiy (handlerlar orasida circular
import bo'lmasligi uchun alohida joylashtirilgan) yordamchi modul.

Tizimda 6 ta rol bor:
  - SuperAdmin   — hammasini boshqaradi, Admin/O'qituvchi/SMM menejer/
                    Reception qo'sha/o'chira oladi.
  - Admin        — to'liq admin paneli (test, olimpiada, user, reklama).
  - O'qituvchi   — faqat test qo'shish va test tekshirish.
  - SMM menejer  — faqat reklama (xabar) jo'natish.
  - Reception    — faqat ishtirokchini qabul qilish (vaqt/xona belgilash,
                    qarang: handlers/admin.py -> checkin_entry,
                    DECISIONS.md #26). Natijalar, Excel, reklama kabi
                    boshqa hech narsaga tega olmaydi.
  - User         — oddiy foydalanuvchi (o'quvchi/ota-ona), `users` jadvalida.

Birinchi beshtasi `admins` jadvalidagi `role` ustunida saqlanadi (yoki
SuperAdmin bo'lsa, .env dagi SUPERADMIN_IDS orqali ham berilishi mumkin).
"""

import logging

from sqlalchemy import select
from database.models import Admin
from config import DEFAULT_SUPERADMIN_IDS

logger = logging.getLogger(__name__)

ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"
ROLE_SMM = "smm_manager"
ROLE_RECEPTION = "reception"

# SuperAdmin panelidan qo'shish/o'chirish mumkin bo'lgan rollar
# (SuperAdmin lavozimi faqat .env yoki to'g'ridan-to'g'ri DB orqali beriladi).
ASSIGNABLE_ROLES = [ROLE_ADMIN, ROLE_TEACHER, ROLE_SMM, ROLE_RECEPTION]

ROLE_LABELS = {
    ROLE_SUPERADMIN: "SuperAdmin",
    ROLE_ADMIN: "Admin",
    ROLE_TEACHER: "O'qituvchi",
    ROLE_SMM: "SMM menejer",
    ROLE_RECEPTION: "Reception",
}


async def get_staff_role(chat_id: int, session) -> str | None:
    """Foydalanuvchining "xodim" rolini qaytaradi:
    superadmin / admin / teacher / smm_manager / reception — yoki xodim
    bo'lmasa None.
    """
    if chat_id in DEFAULT_SUPERADMIN_IDS:
        return ROLE_SUPERADMIN

    res = await session.execute(select(Admin).where(Admin.id == chat_id))
    admin = res.scalar_one_or_none()
    return admin.role if admin else None


async def notify_superadmins(bot, text: str) -> None:
    """Superadminlarga xabar yuboradi (masalan, kutilmagan xatolik haqida).

    Bittasiga yetkazib bo'lmasa (bloklagan, chat topilmadi) qolganlariga
    baribir urinadi — bittasining muvaffaqiyatsizligi qolganlarini
    to'xtatib qo'ymasligi kerak.
    """
    for admin_id in DEFAULT_SUPERADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.warning(f"Superadmin {admin_id}ga xabar yuborib bo'lmadi")
