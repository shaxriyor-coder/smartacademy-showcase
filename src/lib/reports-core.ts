import {
  FOCUS_MIN_QUESTIONS,
  STRONG_FROM,
  computeStudentAnalytics,
  round1,
  type AnalyticsSheet,
  type QuestionMeta,
} from "./analytics-core";
import type { Message } from "./notifications-core";

// Weekly and monthly reports to families over Telegram (docs/DECISIONS.md #24):
// when they're due, what goes in, and the text. Pure; queueing lives in
// src/lib/reports.ts.

const DAY_MS = 86_400_000;
const TASHKENT_OFFSET_MS = 5 * 3_600_000; // UTC+5, no daylight saving

// Sunday (weekly) and the month's last day (monthly), 19:00 in Tashkent.
export const REPORT_HOUR = 19;
// A worker that was down catches up for two days; after that the report is stale.
export const REPORT_GRACE_MS = 2 * DAY_MS;
export const REPORT_TESTS_SHOWN = 6;

const MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"];

export type ReportKind = "weekly" | "monthly";
export type ReportPeriod = { kind: ReportKind; key: string; start: Date; end: Date; label: string };

function local(date: Date) {
  const l = new Date(date.getTime() + TASHKENT_OFFSET_MS);
  return { y: l.getUTCFullYear(), m: l.getUTCMonth(), d: l.getUTCDate(), dow: l.getUTCDay() };
}
function tashkent(y: number, m: number, d: number, h: number) {
  return new Date(Date.UTC(y, m, d, h) - TASHKENT_OFFSET_MS);
}
const pad = (n: number) => String(n).padStart(2, "0");
const dayMonth = (date: Date) => {
  const p = local(date);
  return `${pad(p.d)}.${pad(p.m + 1)}`;
};

// The week that ended at the latest Sunday 19:00 at or before `now`.
export function latestWeeklyPeriod(now: Date): ReportPeriod {
  const p = local(now);
  let end = tashkent(p.y, p.m, p.d - p.dow, REPORT_HOUR);
  if (end > now) end = new Date(end.getTime() - 7 * DAY_MS);
  const start = new Date(end.getTime() - 7 * DAY_MS);
  const e = local(end);
  return {
    kind: "weekly",
    key: `weekly:${e.y}-${pad(e.m + 1)}-${pad(e.d)}`,
    start,
    end,
    label: `${dayMonth(new Date(start.getTime() + DAY_MS))}–${dayMonth(end)}`,
  };
}

// The month that ended at the latest "last day of a month, 19:00" at or before `now`.
export function latestMonthlyPeriod(now: Date): ReportPeriod {
  const p = local(now);
  let end = tashkent(p.y, p.m + 1, 0, REPORT_HOUR);
  if (end > now) end = tashkent(p.y, p.m, 0, REPORT_HOUR);
  const e = local(end);
  return {
    kind: "monthly",
    key: `monthly:${e.y}-${pad(e.m + 1)}`,
    start: tashkent(e.y, e.m, 0, REPORT_HOUR),
    end,
    label: `${MONTHS[e.m]} ${e.y}`,
  };
}

// Periods whose report should go out now: ended recently, and after reports
// were switched on (`since`) — a first deploy doesn't send last week's report.
export function duePeriods(now: Date, since: Date): ReportPeriod[] {
  return [latestWeeklyPeriod(now), latestMonthlyPeriod(now)].filter(
    (period) => period.end > since && now.getTime() - period.end.getTime() <= REPORT_GRACE_MS,
  );
}

export type ReportSheet = AnalyticsSheet & { closesAt: Date | null };

const within = (date: Date | null, start: Date, end: Date) => date != null && date > start && date <= end;

// One student's period. Tests count when checked in it; a missed online test
// counts when it closed in it. Null when nothing happened — no empty reports.
// Topics use only sheets whose answers may be shown (the reveal policy).
export function studentReport(sheets: ReportSheet[], period: ReportPeriod, meta: Map<string, QuestionMeta>) {
  const checked = sheets
    .filter((s) => s.percentage != null && within(s.checkedAt, period.start, period.end))
    .sort((a, b) => a.checkedAt!.getTime() - b.checkedAt!.getTime());
  const missed = sheets.filter((s) => s.status === "missed" && within(s.closesAt, period.start, period.end));
  if (checked.length === 0 && missed.length === 0) return null;

  const length = period.end.getTime() - period.start.getTime();
  const previousStart = new Date(period.start.getTime() - length);
  const previous = computeStudentAnalytics(
    sheets.filter((s) => s.percentage != null && within(s.checkedAt, previousStart, period.start)),
    new Map(),
  );
  const a = computeStudentAnalytics(checked, meta);

  return {
    tests: checked.map((s) => ({ title: s.title, percentage: s.percentage!, classAverage: s.classAverage })),
    missed: missed.map((s) => s.title),
    average: a.average,
    change: a.average != null && previous.average != null ? round1(a.average - previous.average) : null,
    subjects: a.subjects,
    best: checked.length > 1 ? [...checked].sort((x, y) => y.percentage! - x.percentage!)[0].title : null,
    focus: a.themes
      .filter((t) => t.total >= FOCUS_MIN_QUESTIONS && t.percentage < STRONG_FROM)
      .slice(0, 3)
      .map((t) => ({ name: t.name, percentage: t.percentage })),
  };
}

export type StudentReport = NonNullable<ReturnType<typeof studentReport>>;

function changeText(change: number | null, kind: ReportKind) {
  if (change == null) return "";
  const against = kind === "weekly" ? "oldingi haftaga" : "oldingi oyga";
  if (change === 0) return ` (${against} nisbatan o'zgarishsiz)`;
  return ` (${change > 0 ? "▲ +" : "▼ −"}${Math.abs(change)} ${against} nisbatan)`;
}

export function reportMessage(
  period: ReportPeriod,
  studentName: string,
  r: StudentReport,
  link: { url: string; webApp: boolean } | null,
): Message {
  const weekly = period.kind === "weekly";
  const lines = [`${weekly ? "📅 Haftalik" : "🗓 Oylik"} hisobot — ${studentName}`, period.label];

  if (r.tests.length === 0) {
    lines.push(weekly ? "Bu hafta test topshirilmadi." : "Bu oy test topshirilmadi.");
  } else {
    lines.push(`Topshirilgan testlar: ${r.tests.length} ta · o'rtacha ${r.average}%${changeText(r.change, period.kind)}`);
    if (weekly) {
      for (const t of r.tests.slice(0, REPORT_TESTS_SHOWN)) lines.push(`• ${t.title} — ${t.percentage}%`);
      if (r.tests.length > REPORT_TESTS_SHOWN) lines.push(`• va yana ${r.tests.length - REPORT_TESTS_SHOWN} ta`);
    } else {
      if (r.subjects.length > 1) {
        lines.push(`Fanlar: ${r.subjects.map((s) => `${s.name} ${s.average}% (${s.tests} ta)`).join(", ")}`);
      }
      if (r.best) lines.push(`Eng yaxshi natija: ${r.best}`);
    }
  }
  if (r.missed.length > 0) {
    lines.push(weekly ? `Topshirilmadi: ${r.missed.join(", ")}` : `Topshirilmagan testlar: ${r.missed.length} ta`);
  }
  if (r.focus.length > 0) {
    lines.push(`Ko'proq e'tibor kerak: ${r.focus.map((t) => `${t.name} (${t.percentage}%)`).join(", ")}`);
  }
  return { text: lines.join("\n"), button: link ? { text: "📊 To'liq tahlil", ...link } : null };
}
