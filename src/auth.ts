import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { prisma } from "@/lib/prisma";
import { verifyPassword } from "@/lib/credentials";
import { verifyOtp } from "@/lib/otp";
import { verifyTelegramWidgetPayload } from "@/lib/telegram-auth";
import { verifyWebAppInitData } from "@/lib/telegram-webapp";
import { telegramSignIn } from "@/lib/telegram-signin";
import { isLocked, recordFailure, recordSuccess } from "@/lib/login-throttle";
import type { StaffRole } from "@/lib/roles";

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      id: "credentials",
      name: "Admin",
      credentials: {
        email: {},
        password: {},
        otpPendingId: {},
        otpCode: {},
      },
      authorize: async (credentials) => {
        const otpPendingId = credentials?.otpPendingId as string | undefined;
        const otpCode = credentials?.otpCode as string | undefined;

        // Step 2 of the Telegram 2FA flow: the login page already checked
        // the password and sent a code, so all that's left is the code.
        if (otpPendingId && otpCode) {
          const result = await verifyOtp(otpPendingId, otpCode);
          if (!result.ok) return null;
          const user = await prisma.user.findUnique({ where: { id: result.userId } });
          if (!user) return null;
          return {
            id: user.id,
            name: user.name,
            email: user.email,
            kind: "admin" as const,
            role: user.role,
            canTeach: user.canTeach,
          };
        }

        const email = credentials?.email as string | undefined;
        const password = credentials?.password as string | undefined;
        if (!email || !password) return null;

        if (isLocked(email)) return null;
        const user = await verifyPassword(email, password);
        if (!user) {
          recordFailure(email);
          return null;
        }
        recordSuccess(email);
        // Admins with a linked Telegram must complete the OTP step above —
        // a correct password alone can't grant a session for them. This is
        // the actual enforcement boundary; the login page's redirect to
        // /login/verify is just the UX for it, not the security control.
        if (user.telegramChatId) return null;

        return {
          id: user.id,
          name: user.name,
          email: user.email,
          kind: "admin" as const,
          role: user.role,
          canTeach: user.canTeach,
        };
      },
    }),
    Credentials({
      id: "telegram-student",
      name: "Telegram",
      credentials: {
        id: {},
        first_name: {},
        last_name: {},
        username: {},
        photo_url: {},
        auth_date: {},
        hash: {},
      },
      // Every field Telegram's widget posts is signed together (see
      // src/lib/telegram-auth.ts) — the HMAC is re-verified here rather than
      // trusting whatever the client claims, since `credentials` is
      // attacker-controlled input like any other form POST.
      authorize: async (credentials) => {
        if (!credentials) return null;
        const raw = Object.fromEntries(
          Object.entries(credentials).filter(
            (entry): entry is [string, string] => typeof entry[1] === "string",
          ),
        );

        const verified = verifyTelegramWidgetPayload(raw);
        if (!verified) return null;

        return telegramSignIn(verified);
      },
    }),
    Credentials({
      id: "telegram-webapp",
      name: "Telegram Mini App",
      credentials: { initData: {} },
      // src/app/tg/page.tsx passes Telegram's signed initData along verbatim;
      // it's re-verified with the bot token here, never trusted as sent.
      authorize: async (credentials) => {
        const initData = credentials?.initData;
        if (typeof initData !== "string") return null;
        const user = verifyWebAppInitData(initData);
        return user ? telegramSignIn(user) : null;
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        const u = user as {
          id: string;
          kind: "admin" | "student";
          role?: StaffRole;
          canTeach?: boolean;
        };
        token.id = u.id;
        token.kind = u.kind;
        token.role = u.role;
        token.canTeach = u.canTeach;
      }
      return token;
    },
    session({ session, token }) {
      if (session.user) {
        const t = token as {
          id: string;
          kind: "admin" | "student";
          role?: StaffRole;
          canTeach?: boolean;
        };
        session.user.id = t.id;
        session.user.kind = t.kind;
        session.user.role = t.role;
        session.user.canTeach = t.canTeach;
      }
      return session;
    },
  },
});
