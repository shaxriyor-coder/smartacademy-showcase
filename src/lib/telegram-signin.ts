import { prisma } from "./prisma";
import { staffRoleFromBot, type StaffRole } from "./roles";
import { smartbotDatabaseUrl, smartbotRole } from "./smartbot";
import type { WebAppUser } from "./telegram-webapp";

// One Telegram sign-in for everyone — the Mini App opened from smartbot, or
// the Login Widget on the site. Staff in the bot get the panel for their role;
// everyone else gets the family cabinet (docs/DECISIONS.md #23).

async function lastKnownRole(telegramId: string): Promise<StaffRole | null> {
  const user = await prisma.user.findUnique({ where: { telegramChatId: telegramId }, select: { role: true } });
  return user?.role ?? null;
}

async function staffRole(telegramId: string): Promise<StaffRole | null> {
  if (!smartbotDatabaseUrl()) {
    // No bot database configured (local development): staff are the people
    // with this Telegram ID on the staff page, plus SMARTBOT_SUPERADMIN_IDS.
    return staffRoleFromBot(await smartbotRole(telegramId)) ?? (await lastKnownRole(telegramId));
  }
  try {
    // The bot is the source of truth: someone removed from its admins opens
    // the family cabinet from now on.
    return staffRoleFromBot(await smartbotRole(telegramId));
  } catch (err) {
    // The bot's database is unreachable: keep the role from the last sign-in
    // rather than locking staff out or dropping them into the cabinet.
    console.error("smartbot roli o'qilmadi:", err);
    return lastKnownRole(telegramId);
  }
}

// A family session is a Telegram ACCOUNT (the student or a parent), not a
// Student row — which children it can see comes from StudentTelegramLink,
// added with a teacher-issued link code.
async function familySession(user: WebAppUser) {
  const fields = {
    firstName: user.first_name,
    lastName: user.last_name ?? null,
    username: user.username ?? null,
    photoUrl: user.photo_url ?? null,
    lastLoginAt: new Date(),
  };
  const account = await prisma.telegramAccount.upsert({
    where: { id: user.id },
    create: { id: user.id, ...fields },
    update: fields,
  });
  return { id: account.id, name: account.firstName, kind: "student" as const };
}

export async function telegramSignIn(user: WebAppUser) {
  const role = await staffRole(user.id);
  if (!role) return familySession(user);

  const staff = await prisma.user.upsert({
    where: { telegramChatId: user.id },
    // The role follows the bot; a name set on the staff page is kept.
    update: { role },
    create: { name: [user.first_name, user.last_name].filter(Boolean).join(" "), role, telegramChatId: user.id },
  });
  // `canTeach` botdan kelmaydi — uni SuperAdmin Xodimlar sahifasida beradi,
  // shuning uchun upsert unga tegmaydi va bu yerda o'qib uzatiladi.
  return {
    id: staff.id,
    name: staff.name,
    email: staff.email,
    kind: "admin" as const,
    role: staff.role,
    canTeach: staff.canTeach,
  };
}
