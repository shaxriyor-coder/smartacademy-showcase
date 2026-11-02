import { formatTashkent } from "./online-core";

// Telegram notifications: message texts, when reminders are due, and what a
// failed send means. Pure — the queue and delivery live in
// src/lib/notifications.ts (docs/DECISIONS.md #22).

const HOUR_MS = 3_600_000;

// Before a test closes, to students who haven't started it.
export const REMINDERS = [
  { kind: "reminder_24h", before: 24 * HOUR_MS, left: "bir kundan kam" },
  { kind: "reminder_1h", before: HOUR_MS, left: "bir soatdan kam" },
] as const;
export type Reminder = (typeof REMINDERS)[number];
export const REMINDER_HORIZON_MS = Math.max(...REMINDERS.map((r) => r.before));

export type NotificationKind =
  | "result"
  | "new_test"
  | Reminder["kind"]
  | "teacher_summary"
  | "weekly_report"
  | "monthly_report";

export const MAX_ATTEMPTS = 5;
export const SUMMARY_NAMES_SHOWN = 15;

export type Button = { text: string; url: string; webApp: boolean };
export type Message = { text: string; button: Button | null };
type Link = Omit<Button, "text">;

// Telegram only accepts public HTTPS addresses in buttons: without WEBAPP_URL
// messages go out as text alone.
export function appLinks(webAppUrl: string | undefined) {
  const base = webAppUrl?.trim().replace(/\/$/, "");
  if (!base?.startsWith("https://")) return null;
  return {
    // Opens inside Telegram already signed in (src/app/tg/page.tsx), then `path`.
    miniApp: (path: string): Link => ({ url: `${base}/tg?next=${encodeURIComponent(path)}`, webApp: true }),
    site: (path: string): Link => ({ url: `${base}${path}`, webApp: false }),
  };
}

const withButton = (text: string, label: string, link: Link | null): Message => ({
  text,
  button: link ? { text: label, ...link } : null,
});

// The nearest reminder that applies right now — but only if the test was
// announced earlier than that reminder's lead time, so a test given 5 hours
// before its deadline doesn't get "less than a day left" right after "new test".
export function dueReminder(
  w: { opensAt: Date | null; closesAt: Date | null },
  announcedAt: Date,
  now: Date,
): Reminder | null {
  if (!w.closesAt || now >= w.closesAt) return null;
  if (w.opensAt && now < w.opensAt) return null;
  const left = w.closesAt.getTime() - now.getTime();
  for (const r of [...REMINDERS].sort((a, b) => a.before - b.before)) {
    if (left <= r.before) return w.closesAt.getTime() - announcedAt.getTime() > r.before ? r : null;
  }
  return null;
}

export function resultMessage(
  r: {
    studentName: string;
    title: string;
    classroomName: string;
    correct: number;
    total: number;
    percentage: number;
    classAverage: number | null;
  },
  link: Link | null,
): Message {
  const lines = [
    `✅ ${r.studentName} — natija`,
    `«${r.title}» · ${r.classroomName}`,
    `${r.correct}/${r.total} to'g'ri — ${r.percentage}%`,
  ];
  if (r.classAverage != null) lines.push(`Guruh o'rtachasi: ${r.classAverage}%`);
  return withButton(lines.join("\n"), "📊 Natijani ko'rish", link);
}

type TestInfo = {
  studentName: string;
  title: string;
  classroomName: string;
  questionCount: number;
  opensAt: Date | null;
  closesAt: Date | null;
  timeLimitMinutes: number | null;
};

export function newTestMessage(t: TestInfo, now: Date, link: Link | null): Message {
  const lines = [
    `📝 ${t.studentName} uchun yangi online test`,
    `«${t.title}» · ${t.classroomName}`,
    `${t.questionCount} ta savol · ${t.timeLimitMinutes ? `${t.timeLimitMinutes} daqiqa` : "vaqt cheklanmagan"}`,
    t.opensAt && t.opensAt > now ? `Ochiladi: ${formatTashkent(t.opensAt)}` : "Hozir ochiq",
    t.closesAt ? `Yopiladi: ${formatTashkent(t.closesAt)}` : "Muddatsiz",
  ];
  return withButton(lines.join("\n"), "▶️ Testni ochish", link);
}

export function reminderMessage(
  reminder: Reminder,
  t: { studentName: string; title: string; classroomName: string; closesAt: Date },
  link: Link | null,
): Message {
  const text = [
    `⏰ Eslatma: ${t.studentName} «${t.title}» testini hali boshlamadi`,
    `${t.classroomName} · yopilishiga ${reminder.left} qoldi (${formatTashkent(t.closesAt)})`,
  ].join("\n");
  return withButton(text, "▶️ Testni ochish", link);
}

export function teacherSummaryMessage(
  s: { title: string; classroomName: string; checked: number; total: number; average: number | null; missing: string[] },
  link: Link | null,
): Message {
  const lines = [`📋 «${s.title}» yopildi — ${s.classroomName}`, `Topshirdi: ${s.checked}/${s.total}`];
  if (s.average != null) lines.push(`O'rtacha: ${s.average}%`);
  if (s.missing.length > 0) {
    const shown = s.missing.slice(0, SUMMARY_NAMES_SHOWN).join(", ");
    const more = s.missing.length - SUMMARY_NAMES_SHOWN;
    lines.push(`Topshirmadi (${s.missing.length}): ${shown}${more > 0 ? ` va yana ${more} ta` : ""}`);
  }
  return withButton(lines.join("\n"), "📋 Natijalar", link);
}

export type SendOutcome =
  | { ok: true }
  | { ok: false; status: number; description: string; retryAfter?: number };

// What a failed send means for the queue:
// - unreachable: blocked the bot, deleted the account, or never pressed Start —
//   nothing will get through until they write to the bot;
// - invalid: Telegram rejects this message itself; retrying can't help;
// - rate_limited: wait `retryAfter` and carry on;
// - retry: network or Telegram-side trouble.
export function classifyFailure(o: Extract<SendOutcome, { ok: false }>) {
  if (o.status === 403) return "unreachable" as const;
  if (o.status === 400 && /chat not found|user not found/i.test(o.description)) return "unreachable" as const;
  if (o.status === 429) return "rate_limited" as const;
  if (o.status === 400) return "invalid" as const;
  return "retry" as const;
}

// 2, 4, 8 … minutes, at most an hour.
export function retryAt(attempts: number, now: Date): Date {
  return new Date(now.getTime() + Math.min(2 ** attempts, 60) * 60_000);
}
