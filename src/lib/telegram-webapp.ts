import { createHmac, timingSafeEqual } from "crypto";

// Telegram Mini App sign-in. Telegram opens the student cabinet inside the app
// and hands the page a signed `initData` string; the server re-verifies it with
// the bot token. https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
//
// Different from the Login Widget (src/lib/telegram-auth.ts): another key
// derivation, and the user arrives as a JSON field.

export type WebAppUser = {
  id: string;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
};

// Telegram signs initData afresh every time the Mini App opens; a day covers a
// long-open app without accepting a leaked string forever.
const MAX_AGE_SECONDS = 24 * 60 * 60;

export function webAppHash(dataCheckString: string, botToken: string): string {
  const secret = createHmac("sha256", "WebAppData").update(botToken).digest();
  return createHmac("sha256", secret).update(dataCheckString).digest("hex");
}

export function verifyWebAppInitData(
  initData: string,
  botToken = process.env.TELEGRAM_BOT_TOKEN,
  now = Date.now(),
): WebAppUser | null {
  if (!botToken || !initData) return null;

  const params = new URLSearchParams(initData);
  const hash = params.get("hash") ?? "";
  if (!/^[0-9a-f]{64}$/.test(hash)) return null;

  // Every received field except `hash`, sorted by key, "key=value" per line.
  const dataCheckString = [...params.entries()]
    .filter(([key]) => key !== "hash")
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
  const expected = Buffer.from(webAppHash(dataCheckString, botToken), "hex");
  if (!timingSafeEqual(expected, Buffer.from(hash, "hex"))) return null;

  const authDate = Number(params.get("auth_date"));
  if (!authDate || now / 1000 - authDate > MAX_AGE_SECONDS) return null;

  try {
    const raw = JSON.parse(params.get("user") ?? "");
    if (!raw || typeof raw.id !== "number" || typeof raw.first_name !== "string") return null;
    const user: WebAppUser = { id: String(raw.id), first_name: raw.first_name };
    if (typeof raw.last_name === "string" && raw.last_name) user.last_name = raw.last_name;
    if (typeof raw.username === "string" && raw.username) user.username = raw.username;
    if (typeof raw.photo_url === "string" && raw.photo_url) user.photo_url = raw.photo_url;
    return user;
  } catch {
    return null;
  }
}
