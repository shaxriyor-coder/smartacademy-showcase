"use client";

import { useEffect } from "react";
import { signIn } from "next-auth/react";
import Logo from "@/components/Logo";

declare global {
  interface Window {
    onTelegramAuth: (user: Record<string, string | number>) => void;
  }
}

// Written with or without the "@" in .env; the widget wants it without.
const BOT_USERNAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?.replace(/^@/, "");

// The real Telegram Login Widget. It POSTs a signed payload to a global JS
// callback (rather than our own form) — Telegram requires the bot's domain
// to be registered first (BotFather → /setdomain), which only exists once
// this is deployed to a real HTTPS domain. Until then, use
// /login/student/dev on localhost — see src/lib/telegram-auth.ts.
export default function StudentLoginPage() {
  useEffect(() => {
    window.onTelegramAuth = (user) => {
      const fields: Record<string, string> = {};
      for (const [key, value] of Object.entries(user)) fields[key] = String(value);
      signIn("telegram-student", { ...fields, redirectTo: "/classroom-home" });
    };

    const container = document.getElementById("telegram-login-container");
    if (!container || !BOT_USERNAME) return;

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", BOT_USERNAME);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    script.setAttribute("data-request-access", "write");
    container.appendChild(script);
  }, []);

  return (
    <div className="flex min-h-[80vh] items-center justify-center">
      <div className="glass-panel w-full max-w-sm p-7 text-center shadow-2xl shadow-black/30">
        <div className="mb-7 flex justify-center">
          <Logo subtitle="Telegram orqali kirish" />
        </div>
        <p className="mb-6 text-sm text-muted">
          Parol kerak emas: botdagi xodimlar o&apos;z paneliga, o&apos;quvchi va ota-onalar kabinetga kiradi.
        </p>

        {!BOT_USERNAME && (
          <p className="mb-5 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-xs text-red-300">
            NEXT_PUBLIC_TELEGRAM_BOT_USERNAME .env&apos;da sozlanmagan.
          </p>
        )}

        <div id="telegram-login-container" className="flex justify-center" />

        <p className="mt-6 text-xs text-muted">
          Eslatma: bu tugma faqat botga haqiqiy domen ulangandan keyin ishlaydi
          (BotFather → /setdomain) — localhost&apos;da ishlamaydi. Lokal sinov uchun{" "}
          <a href="/login/student/dev" className="underline">
            /login/student/dev
          </a>
          .
        </p>

        <a
          href="/login"
          className="mt-5 block text-center text-xs text-muted hover:text-ivory hover:underline"
        >
          ← Email va parol bilan kirish
        </a>
      </div>
    </div>
  );
}
