"use client";

import Link from "next/link";
import Script from "next/script";
import { useRef, useState } from "react";
import { signIn } from "next-auth/react";
import Logo from "@/components/Logo";

type TelegramWebApp = { initData: string; ready(): void; expand(): void };

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

// Where the bot's "Testlarim" button lands (scripts/telegram-bot.ts). Inside
// Telegram the page receives signed initData and signs the account in with no
// password or code; opened in an ordinary browser, initData is empty.
export default function TelegramMiniAppPage() {
  const [state, setState] = useState<"loading" | "outside" | "failed">("loading");
  // Nega yiqilgani — serverda .env yoki baza sozlanmaganda aynan shu matn
  // muammoni ko'rsatadi (docs/DEPLOY.md, "Muammolar").
  const [reason, setReason] = useState<string | null>(null);
  const started = useRef(false);

  function fail(why: string) {
    setReason(why);
    setState("failed");
  }

  async function enter() {
    if (started.current) return;
    started.current = true;

    const webApp = window.Telegram?.WebApp;
    if (!webApp?.initData) {
      setState("outside");
      return;
    }
    webApp.ready();
    webApp.expand();

    // Javob kelmay qolsa sahifa "Kirilmoqda..." da abadiy turib qolmasin.
    const timer = setTimeout(() => fail("server javob bermadi (30 s)"), 30_000);
    let result;
    try {
      result = await signIn("telegram-webapp", { initData: webApp.initData, redirect: false });
    } catch (e) {
      // Bu yerga server 500/502 qaytarganda tushamiz: signIn javobni JSON deb
      // o'qiy olmay xato tashlaydi. Ilgari bu xato hech qayerda ko'rinmasdi.
      clearTimeout(timer);
      fail(e instanceof Error ? e.message : "server xatosi");
      return;
    }
    clearTimeout(timer);

    if (!result || result.error) {
      fail(result?.error === "CredentialsSignin" ? "imzo mos kelmadi" : (result?.error ?? "noma'lum xato"));
      return;
    }
    // A notification's button says where to go (src/lib/notifications-core.ts);
    // only cabinet paths are followed.
    const next = new URLSearchParams(window.location.search).get("next");
    window.location.replace(next?.startsWith("/classroom-home") ? next : "/classroom-home");
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <Script
        src="https://telegram.org/js/telegram-web-app.js"
        onReady={() => void enter()}
        onError={() => setState("outside")}
      />
      <div className="glass-panel w-full max-w-sm p-7 text-center">
        <div className="mb-6 flex justify-center">
          <Logo subtitle="Telegram" />
        </div>
        {state === "loading" && <p className="text-sm text-muted">Kirilmoqda...</p>}
        {state === "outside" && (
          <p className="text-sm text-muted">
            Bu sahifa Telegram ichida ochiladi — botdagi «Testlarim» tugmasini bosing. Brauzerdan
            kirish:{" "}
            <Link href="/login/student" className="underline">
              o&apos;quvchi kirishi
            </Link>
            .
          </p>
        )}
        {state === "failed" && (
          <>
            <p className="text-sm text-red-300">
              Telegram orqali kirib bo&apos;lmadi. Ilovani yopib, qaytadan oching.
            </p>
            {reason && <p className="mt-2 text-xs text-muted">Sabab: {reason}</p>}
          </>
        )}
      </div>
    </div>
  );
}
