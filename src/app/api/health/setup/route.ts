import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { smartbotDatabaseUrl, smartbotRole } from "@/lib/smartbot";

// Serverda sozlama to'g'ri yozilganini bitta so'rov bilan ko'rsatadi
// (docs/DEPLOY.md -> Muammolar). Mini App "Kirilmoqda..." da qotib qolsa,
// sabab deyarli har doim shu ro'yxatda bo'ladi: .env dagi kalit yozilmagan,
// domen boshqa, migratsiya qo'llanmagan yoki token boshqa botniki.
//
// Maxfiy qiymat QAYTARILMAYDI — faqat bor/yo'qligi. Bot nomi (@username)
// ommaviy ma'lumot. Shunday bo'lsa ham CHECKER_TOKEN bilan yopilgan:
// serverning ichki holati begonaga ko'rinmasin.

function short(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err);
  return text.split("\n")[0].slice(0, 200);
}

async function check(run: () => Promise<unknown>): Promise<string> {
  try {
    await run();
    return "ok";
  } catch (err) {
    return short(err);
  }
}

export async function GET(request: Request) {
  const expected = process.env.CHECKER_TOKEN;
  if (!expected) {
    return NextResponse.json(
      { ok: false, error: "CHECKER_TOKEN .env da yo'q — tekshiruvni ochib bo'lmaydi" },
      { status: 503 },
    );
  }
  const given =
    request.headers.get("x-checker-token") ??
    new URL(request.url).searchParams.get("token");
  if (given !== expected) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const env = {
    AUTH_SECRET: Boolean(process.env.AUTH_SECRET),
    AUTH_TRUST_HOST: process.env.AUTH_TRUST_HOST ?? null,
    NEXTAUTH_URL: process.env.NEXTAUTH_URL ?? null,
    WEBAPP_URL: process.env.WEBAPP_URL ?? null,
    TELEGRAM_BOT_TOKEN: Boolean(process.env.TELEGRAM_BOT_TOKEN),
    NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME ?? null,
    DATABASE_URL: Boolean(process.env.DATABASE_URL),
    SMARTBOT_DATABASE_URL: Boolean(smartbotDatabaseUrl()),
    BOT_POLLING: process.env.BOT_POLLING ?? null,
  };

  const database = await check(() => prisma.$queryRaw`SELECT 1`);
  // Migratsiyalar qo'llanganmi: Mini App kirishi aynan shu jadvalga yozadi.
  const migrations = await check(() => prisma.telegramAccount.count());
  const smartbotDatabase = smartbotDatabaseUrl()
    ? await check(() => smartbotRole("1"))
    : "sozlanmagan";

  // Mini App imzosini shu token tekshiradi — u BOTNING o'zi bo'lishi shart.
  let bot: string | null = null;
  let botError: string | null = null;
  if (process.env.TELEGRAM_BOT_TOKEN) {
    try {
      const resp = await fetch(
        `https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/getMe`,
        { cache: "no-store" },
      );
      const data = (await resp.json()) as { ok?: boolean; description?: string; result?: { username?: string } };
      if (data.ok) bot = data.result?.username ?? null;
      else botError = data.description ?? `HTTP ${resp.status}`;
    } catch (err) {
      botError = short(err);
    }
  }

  const ok =
    env.AUTH_SECRET &&
    env.TELEGRAM_BOT_TOKEN &&
    database === "ok" &&
    migrations === "ok" &&
    Boolean(bot);

  return NextResponse.json({ ok, env, database, migrations, smartbotDatabase, bot, botError });
}
