// Standalone long-polling bot for a dedicated development bot — run alongside
// the site with `npm run bot`.
//
// - Any message gets the sender's chat ID back: a SuperAdmin pastes it into a
//   staff account on /admins, for Telegram OTP login (src/lib/otp.ts) and for
//   a teacher's "test closed" summaries.
// - With WEBAPP_URL set (public HTTPS — Telegram refuses anything else), the
//   reply carries a button that opens the student cabinet as a Mini App, and
//   the bot's menu button points there too (src/app/tg/page.tsx).
// - Every 30 s it queues and sends notifications: results, new online tests,
//   deadline reminders and teachers' summaries (src/lib/notifications.ts), and
//   weekly/monthly family reports (src/lib/reports.ts).
//   /stop turns them off for a Telegram account, /start turns them back on.
//   `npm run bot -- --no-notify` runs the bot without them.
//
// Long-polling (not a webhook) on purpose: webhooks require a public HTTPS
// URL, while polling works from localhost with zero setup.
//
// PRODUCTION: the platform opens from smartbot, and smartbot itself polls that
// bot's updates. Two pollers on one token steal each other's messages, so
// there run `npm run notify` (or set BOT_POLLING=off): notifications only.
// /stop and /start then don't exist — families switch messages off in the
// cabinet instead.
import "dotenv/config";
import { prisma } from "../src/lib/prisma";
import { deliverNotifications, sweepNotifications } from "../src/lib/notifications";
import { sweepReports } from "../src/lib/reports";
import { smartbotDatabaseUrl } from "../src/lib/smartbot";

const token = process.env.TELEGRAM_BOT_TOKEN;
if (!token) {
  console.error("TELEGRAM_BOT_TOKEN .env faylida topilmadi");
  process.exit(1);
}

const API = `https://api.telegram.org/bot${token}`;
const NOTIFY = !process.argv.includes("--no-notify");
// Joined with smartbot (SMARTBOT_* set), smartbot polls this token itself: this
// process only sends, unless BOT_POLLING=on forces polling for a separate test bot.
const POLL =
  !process.argv.includes("--no-poll") &&
  (process.env.BOT_POLLING === "on" || (process.env.BOT_POLLING !== "off" && !smartbotDatabaseUrl()));
const NOTIFY_EVERY_MS = 30_000;
const webAppUrl = process.env.WEBAPP_URL?.replace(/\/$/, "");
const miniAppUrl = webAppUrl?.startsWith("https://") ? `${webAppUrl}/tg` : null;
if (webAppUrl && !miniAppUrl) {
  console.warn("WEBAPP_URL https:// bilan boshlanishi kerak — Mini App tugmasi qo'shilmaydi");
}
let offset = 0;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function call(method: string, payload: Record<string, unknown>) {
  const res = await fetch(`${API}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (!body.ok) console.error(`${method} failed:`, body);
  return body;
}

// /stop and /start for notifications. Any message at all also shows the bot
// can reach this account again after a failed delivery.
async function replyText(chatId: number, text: string) {
  const id = String(chatId);
  if (/^\/stop\b/.test(text)) {
    const { count } = await prisma.telegramAccount.updateMany({
      where: { id },
      data: { notifyEnabled: false, botUnreachableAt: null },
    });
    return count
      ? "Xabarlar o'chirildi. Qayta yoqish uchun /start yozing."
      : "Bu Telegram akkauntga hali hech bir o'quvchi ulanmagan.";
  }
  const { count: linked } = await prisma.telegramAccount.updateMany({
    where: { id },
    data: { botUnreachableAt: null, ...(/^\/start\b/.test(text) ? { notifyEnabled: true } : {}) },
  });

  const parts = [];
  if (miniAppUrl) parts.push("Assalomu alaykum! Testlar va natijalar — pastdagi tugmada.");
  if (linked) parts.push("Natijalar, yangi testlar va eslatmalar shu yerga keladi. O'chirish: /stop");
  parts.push(
    `Xodim bo'lsangiz — Telegram ID: ${chatId}\n` +
      `Buni SuperAdminga bering: u akkauntingizga shu ID ni ulaydi — har kirishda parol bilan ` +
      `birga shu botdan tasdiqlash kodi keladi, o'qituvchilarga esa test xulosalari.`,
  );
  return parts.join("\n\n");
}

async function poll() {
  const res = await fetch(`${API}/getUpdates?offset=${offset}&timeout=30`);
  const body = await res.json();
  if (!body.ok) {
    console.error("getUpdates failed:", body);
    return;
  }

  for (const update of body.result) {
    offset = update.update_id + 1;
    const chatId = update.message?.chat?.id;
    if (!chatId) continue;

    await call("sendMessage", {
      chat_id: chatId,
      text: await replyText(chatId, update.message?.text ?? ""),
      ...(miniAppUrl
        ? {
            reply_markup: {
              inline_keyboard: [[{ text: "📚 Testlarim va natijalar", web_app: { url: miniAppUrl } }]],
            },
          }
        : {}),
    });
  }
}

async function pollLoop() {
  while (true) {
    try {
      await poll();
    } catch (err) {
      console.error("Poll xatosi:", err);
      await sleep(3000);
    }
  }
}

async function notifyLoop() {
  while (true) {
    let wait = NOTIFY_EVERY_MS;
    try {
      const now = new Date();
      const q = await sweepNotifications(now);
      const r = await sweepReports(now);
      const d = await deliverNotifications(now);
      const reports = r.weekly + r.monthly;
      const queued = q.results + q.newTests + q.reminders + q.summaries + reports;
      if (queued || d.sent || d.skipped || d.failed || d.retrying) {
        console.log(
          `Xabarlar: navbatga ${queued} (natija ${q.results}, yangi test ${q.newTests}, eslatma ${q.reminders}, ` +
            `xulosa ${q.summaries}, hisobot ${reports}) · yuborildi ${d.sent} · yetib bormadi ${d.skipped} · xato ${d.failed} · ` +
            `qayta urinadi ${d.retrying}`,
        );
      }
      if (d.pausedUntil) wait = Math.max(d.pausedUntil.getTime() - Date.now(), 1000);
    } catch (err) {
      console.error("Xabarlar xatosi:", err);
    }
    await sleep(wait);
  }
}

async function main() {
  if (!POLL && !NOTIFY) {
    console.error("--no-poll va --no-notify birga: bajaradigan ish qolmadi");
    process.exit(1);
  }
  // The menu button belongs to whoever polls; in production BotFather sets it.
  if (POLL && miniAppUrl) {
    await call("setChatMenuButton", {
      menu_button: { type: "web_app", text: "Testlarim", web_app: { url: miniAppUrl } },
    });
    console.log(`Mini App: ${miniAppUrl}`);
  }
  console.log(
    POLL
      ? `Telegram bot ishga tushdi (long-polling)${NOTIFY ? ", xabarlar yoqilgan" : ", xabarlarsiz"}...`
      : "Faqat xabarlar yuboriladi (bot xabarlarini smartbot qabul qiladi)...",
  );
  await Promise.all([...(POLL ? [pollLoop()] : []), ...(NOTIFY ? [notifyLoop()] : [])]);
}

main();
