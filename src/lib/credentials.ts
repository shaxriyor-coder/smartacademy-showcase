import bcrypt from "bcryptjs";
import { prisma } from "./prisma";

// Shared by src/auth.ts (the Credentials provider) and the login page's
// server action, which needs to check the password itself BEFORE deciding
// whether to route the admin into the Telegram OTP step. Staff who only sign
// in through Telegram have no password and can't use this.
export async function verifyPassword(email: string, password: string) {
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user?.passwordHash) return null;
  const valid = await bcrypt.compare(password, user.passwordHash);
  return valid ? user : null;
}
