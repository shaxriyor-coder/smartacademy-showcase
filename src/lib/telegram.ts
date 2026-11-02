import type { Button, SendOutcome } from "./notifications-core";

const TELEGRAM_API = "https://api.telegram.org";

function botUrl(method: string) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    throw new Error("TELEGRAM_BOT_TOKEN sozlanmagan");
  }
  return `${TELEGRAM_API}/bot${token}/${method}`;
}

// Login codes: the caller needs to know right away, so failures throw.
export async function sendTelegramMessage(chatId: string, text: string): Promise<void> {
  const res = await fetch(botUrl("sendMessage"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Telegram xabar yuborilmadi: ${body}`);
  }
}

// Notifications: never throws — the queue decides what a failure means
// (classifyFailure in src/lib/notifications-core.ts).
export async function sendTelegram(chatId: string, text: string, button: Button | null): Promise<SendOutcome> {
  try {
    const res = await fetch(botUrl("sendMessage"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        ...(button
          ? {
              reply_markup: {
                inline_keyboard: [
                  [button.webApp ? { text: button.text, web_app: { url: button.url } } : { text: button.text, url: button.url }],
                ],
              },
            }
          : {}),
      }),
    });
    const body = (await res.json().catch(() => null)) as {
      ok?: boolean;
      description?: string;
      parameters?: { retry_after?: number };
    } | null;
    if (res.ok && body?.ok) return { ok: true };
    return {
      ok: false,
      status: res.status,
      description: body?.description ?? `HTTP ${res.status}`,
      retryAfter: body?.parameters?.retry_after,
    };
  } catch (err) {
    return { ok: false, status: 0, description: (err as Error).message };
  }
}
