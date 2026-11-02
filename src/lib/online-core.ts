import { seededShuffle } from "./shuffle";
import { LETTERS } from "./answer-key";

// The rules of an online attempt, free of the database so they can be pinned
// down by tests/online-core.test.ts and imported by client components.

export type RevealPolicyValue = "IMMEDIATELY" | "AFTER_CLOSE" | "NEVER";

export const REVEAL_LABELS: Record<RevealPolicyValue, string> = {
  IMMEDIATELY: "Topshirishi bilan ko'rinadi",
  AFTER_CLOSE: "Test yopilgandan keyin",
  NEVER: "Ko'rsatilmaydi (faqat ball)",
};

export type OnlineWindow = {
  opensAt: Date | null;
  closesAt: Date | null;
  timeLimitMinutes: number | null;
};

// What the student sees in a question: option text plus its canonical letter
// as the value to send back. Never which option is correct.
export type RunnerQuestion = {
  index: number; // position in Assignment.questionIds
  text: string;
  imageUrl: string | null;
  options: { value: string; text: string }[];
};

// Answers arriving this long after the timer hits zero still count — the
// student clicked in time, the request just didn't make it yet.
export const SAVE_GRACE_MS = 15_000;

export function windowState(w: OnlineWindow, now: Date): "not_open" | "open" | "closed" {
  if (w.opensAt && now < w.opensAt) return "not_open";
  if (w.closesAt && now >= w.closesAt) return "closed";
  return "open";
}

// When an attempt started at `startedAt` is due: the time limit or the
// closing time, whichever comes first. null = no deadline.
export function attemptDeadline(w: OnlineWindow, startedAt: Date): Date | null {
  const limits: number[] = [];
  if (w.timeLimitMinutes) limits.push(startedAt.getTime() + w.timeLimitMinutes * 60_000);
  if (w.closesAt) limits.push(w.closesAt.getTime());
  return limits.length ? new Date(Math.min(...limits)) : null;
}

export function isPastDeadline(deadline: Date | null, now: Date): boolean {
  return deadline != null && now.getTime() > deadline.getTime() + SAVE_GRACE_MS;
}

export type SheetStatus =
  | "checked" // graded: scanned (offline) or submitted / timed out (online)
  | "in_progress"
  | "available"
  | "not_open"
  | "missed" // online, closed without being started
  | "awaiting_scan"; // offline, not checked yet

export function sheetStatus(
  a: OnlineWindow & { mode: "OFFLINE" | "ONLINE" },
  s: { startedAt: Date | null; checkedAt: Date | null },
  now: Date,
): SheetStatus {
  if (s.checkedAt) return "checked";
  if (a.mode === "OFFLINE") return "awaiting_scan";
  if (s.startedAt) return "in_progress";
  const state = windowState(a, now);
  return state === "open" ? "available" : state === "not_open" ? "not_open" : "missed";
}

// The order one student sees the questions in, as canonical indices. Seeded by
// the sheet: a reload or another device shows the same order. Answers are
// always stored canonically, so stats and the answer key don't care.
export function questionOrder(sheetId: string, count: number, shuffle: boolean): number[] {
  const indices = Array.from({ length: count }, (_, i) => i);
  return shuffle ? seededShuffle(`order:${sheetId}`, indices) : indices;
}

// The order one student sees a question's options in, as canonical option
// indices (0 = what the printed paper calls A).
export function optionOrder(
  sheetId: string,
  questionId: string,
  count: number,
  shuffle: boolean,
): number[] {
  const indices = Array.from({ length: count }, (_, i) => i);
  return shuffle ? seededShuffle(`options:${sheetId}:${questionId}`, indices) : indices;
}

// Option texts in canonical order — as the Word paper prints them, and what the
// letters in Assignment.answerKey refer to (same seed as correctLetter()).
export function canonicalOptions(
  testId: string,
  q: { id: string; correctAnswer: string; wrongAnswers: string[] },
): string[] {
  return seededShuffle(`${testId}:${q.id}`, [q.correctAnswer, ...q.wrongAnswers]);
}

export function letterIndex(letter: string): number {
  return (LETTERS as readonly string[]).indexOf(letter);
}

export function revealAllowed(
  policy: RevealPolicyValue,
  closesAt: Date | null,
  now: Date,
): boolean {
  if (policy === "IMMEDIATELY") return true;
  if (policy === "AFTER_CLOSE") return closesAt != null && now >= closesAt;
  return false;
}

const tashkentFormat = new Intl.DateTimeFormat("uz-UZ", {
  dateStyle: "short",
  timeStyle: "short",
  timeZone: "Asia/Tashkent",
});

export function formatTashkent(date: Date): string {
  return tashkentFormat.format(date);
}

const tashkentDay = new Intl.DateTimeFormat("uz-UZ", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Asia/Tashkent",
});
const tashkentDate = new Intl.DateTimeFormat("uz-UZ", {
  dateStyle: "medium",
  timeZone: "Asia/Tashkent",
});

// Server-side only for anything a client component renders: Node's and the
// browser's ICU data format uz-UZ dates differently, which breaks hydration.
export function formatTashkentDay(date: Date): string {
  return tashkentDay.format(date);
}

export function formatTashkentDate(date: Date): string {
  return tashkentDate.format(date);
}
