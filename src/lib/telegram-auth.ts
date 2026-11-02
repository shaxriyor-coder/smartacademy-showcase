import { createHash, createHmac, timingSafeEqual } from "crypto";

// Fields the Telegram Login Widget posts back to us — see
// https://core.telegram.org/widgets/login#checking-authorization
export type TelegramWidgetPayload = {
  id: string;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: string;
};

const MAX_AUTH_AGE_SECONDS = 5 * 60;

// The exact fields Telegram itself signs — see
// https://core.telegram.org/widgets/login#checking-authorization. The
// `credentials` object NextAuth passes to `authorize()` isn't limited to
// what we hand `signIn()`: it also injects its own bookkeeping (e.g.
// `callbackUrl`, from the `redirectTo` option). Building the data-check
// string from "every field except hash" — rather than this fixed list —
// pulls that extra field in too, changing the string and making the HMAC we
// recompute here never match the one that was actually signed.
const WIDGET_FIELDS = ["id", "first_name", "last_name", "username", "photo_url", "auth_date"];

// Verifies the HMAC-SHA256 signature Telegram attaches to the widget
// payload (secret = SHA256 of the bot token, per Telegram's documented
// algorithm) and rejects stale payloads — otherwise a captured/replayed
// payload could be resubmitted to log in as that student indefinitely.
// Returns the verified fields (never the raw, unverified input) or null.
export function verifyTelegramWidgetPayload(
  payload: Record<string, string>,
): TelegramWidgetPayload | null {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) return null;

  const hash = payload.hash;
  if (!hash || !payload.id || !payload.first_name || !payload.auth_date) return null;

  const dataCheckString = WIDGET_FIELDS.filter(
    (key) => payload[key] !== undefined && payload[key] !== "",
  )
    .sort()
    .map((key) => `${key}=${payload[key]}`)
    .join("\n");

  const secretKey = createHash("sha256").update(token).digest();
  const computedHash = createHmac("sha256", secretKey).update(dataCheckString).digest("hex");

  const a = Buffer.from(computedHash, "hex");
  const b = Buffer.from(hash, "hex");
  if (a.length !== b.length || !timingSafeEqual(a, b)) return null;

  const authDate = Number(payload.auth_date);
  if (!authDate || Date.now() / 1000 - authDate > MAX_AUTH_AGE_SECONDS) return null;

  const result: TelegramWidgetPayload = {
    id: payload.id,
    first_name: payload.first_name,
    auth_date: payload.auth_date,
  };
  if (payload.last_name) result.last_name = payload.last_name;
  if (payload.username) result.username = payload.username;
  if (payload.photo_url) result.photo_url = payload.photo_url;
  return result;
}

// Dev-only helper: builds a validly-signed widget payload without the real
// widget/domain, so the Classroom/Student flow can be exercised on
// localhost — the real widget requires a public HTTPS domain registered to
// the bot (see src/app/login/student/page.tsx), which doesn't exist yet in
// local dev. Never reachable outside development: guarded here AND at the
// page that calls it (src/app/login/student/dev/page.tsx).
export function signTelegramPayloadForDev(fields: {
  id: string;
  first_name: string;
}): Record<string, string> {
  if (process.env.NODE_ENV === "production") {
    throw new Error("signTelegramPayloadForDev ishlab chiqarishda chaqirilmasligi kerak");
  }
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) throw new Error("TELEGRAM_BOT_TOKEN sozlanmagan");

  const payload: Record<string, string> = {
    id: fields.id,
    first_name: fields.first_name,
    auth_date: String(Math.floor(Date.now() / 1000)),
  };

  const dataCheckString = Object.keys(payload)
    .sort()
    .map((key) => `${key}=${payload[key]}`)
    .join("\n");
  const secretKey = createHash("sha256").update(token).digest();
  const hash = createHmac("sha256", secretKey).update(dataCheckString).digest("hex");

  return { ...payload, hash };
}
