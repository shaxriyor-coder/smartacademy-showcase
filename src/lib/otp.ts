import { prisma } from "./prisma";
import { sendTelegramMessage } from "./telegram";

const OTP_TTL_MS = 5 * 60 * 1000;
const MAX_ATTEMPTS = 5;
const OTP_COOLDOWN_MS = 30 * 1000;

function generateCode(): string {
  return String(Math.floor(100000 + Math.random() * 900000));
}

// Called after the password check already passed. Creates a fresh code,
// texts it to the admin's linked Telegram chat, and returns the LoginOtp id
// — the caller stores that id (not the code) in a cookie so the browser
// never sees the code itself.
export async function createAndSendOtp(userId: string, chatId: string): Promise<string> {
  // Resubmitting the login form within the cooldown window (double-click, a
  // script retrying with the same valid password) reuses the still-valid
  // code instead of firing another Telegram message — otherwise anyone with
  // a correct password could spam an admin's phone indefinitely.
  const recent = await prisma.loginOtp.findFirst({
    where: {
      userId,
      used: false,
      expiresAt: { gt: new Date() },
      createdAt: { gt: new Date(Date.now() - OTP_COOLDOWN_MS) },
    },
    orderBy: { createdAt: "desc" },
  });
  if (recent) return recent.id;

  const code = generateCode();
  const otp = await prisma.loginOtp.create({
    data: { userId, code, expiresAt: new Date(Date.now() + OTP_TTL_MS) },
  });
  await sendTelegramMessage(chatId, `SmartAcademy kirish kodi: ${code}\nKod 5 daqiqa amal qiladi.`);
  return otp.id;
}

type VerifyResult =
  | { ok: true; userId: string }
  | { ok: false; reason: "not_found" | "expired" | "too_many_attempts" | "wrong_code" };

// One-time, attempt-limited check — a right pendingId with the wrong code
// burns an attempt instead of just failing silently, so guessing the 6-digit
// code is bounded even if someone gets hold of the pending cookie.
export async function verifyOtp(pendingId: string, code: string): Promise<VerifyResult> {
  const otp = await prisma.loginOtp.findUnique({ where: { id: pendingId } });
  if (!otp || otp.used) return { ok: false, reason: "not_found" };
  if (otp.expiresAt < new Date()) return { ok: false, reason: "expired" };
  if (otp.attempts >= MAX_ATTEMPTS) {
    await prisma.loginOtp.update({ where: { id: otp.id }, data: { used: true } });
    return { ok: false, reason: "too_many_attempts" };
  }

  if (otp.code !== code.trim()) {
    await prisma.loginOtp.update({ where: { id: otp.id }, data: { attempts: { increment: 1 } } });
    return { ok: false, reason: "wrong_code" };
  }

  await prisma.loginOtp.update({ where: { id: otp.id }, data: { used: true } });
  return { ok: true, userId: otp.userId };
}
