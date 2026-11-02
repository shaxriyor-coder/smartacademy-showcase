import { test } from "node:test";
import assert from "node:assert/strict";
import {
  appLinks,
  classifyFailure,
  dueReminder,
  newTestMessage,
  resultMessage,
  retryAt,
  teacherSummaryMessage,
} from "../src/lib/notifications-core";

const NOW = new Date("2026-09-14T09:00:00Z");
const hours = (h: number) => new Date(NOW.getTime() + h * 3_600_000);

test("reminders: the nearest one, only for tests announced before its lead time", () => {
  const long = hours(-48);
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(23) }, long, NOW)?.kind, "reminder_24h");
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(0.5) }, long, NOW)?.kind, "reminder_1h");
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(30) }, long, NOW), null);
  // Given 24h before closing exactly, or 40 minutes before: the "new test"
  // message already said when it closes.
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(23) }, hours(-1), NOW), null);
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(0.5) }, hours(-10 / 60), NOW), null);
  // Under an hour left, a missed 24h reminder isn't sent late.
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(0.5) }, hours(-5), NOW)?.kind, "reminder_1h");
  assert.equal(dueReminder({ opensAt: null, closesAt: hours(-1) }, long, NOW), null);
  assert.equal(dueReminder({ opensAt: null, closesAt: null }, long, NOW), null);
  assert.equal(dueReminder({ opensAt: hours(2), closesAt: hours(20) }, long, NOW), null);
});

test("buttons need a public HTTPS address", () => {
  assert.equal(appLinks(undefined), null);
  assert.equal(appLinks("http://localhost:3000"), null);
  const links = appLinks("https://academy.example.uz/");
  assert.deepEqual(links?.miniApp("/classroom-home/results/abc"), {
    url: "https://academy.example.uz/tg?next=%2Fclassroom-home%2Fresults%2Fabc",
    webApp: true,
  });
  assert.deepEqual(links?.site("/classrooms/x"), { url: "https://academy.example.uz/classrooms/x", webApp: false });
});

test("result message", () => {
  const m = resultMessage(
    { studentName: "Aliyev Vali", title: "Nazorat 1", classroomName: "7-A", correct: 7, total: 10, percentage: 70, classAverage: 65.5 },
    { url: "https://x.uz/tg", webApp: true },
  );
  assert.equal(m.text, "✅ Aliyev Vali — natija\n«Nazorat 1» · 7-A\n7/10 to'g'ri — 70%\nGuruh o'rtachasi: 65.5%");
  assert.deepEqual(m.button, { text: "📊 Natijani ko'rish", url: "https://x.uz/tg", webApp: true });
  const plain = resultMessage(
    { studentName: "V", title: "T", classroomName: "G", correct: 1, total: 2, percentage: 50, classAverage: null },
    null,
  );
  assert.equal(plain.button, null);
  assert.ok(!plain.text.includes("o'rtachasi"));
});

test("new test message says whether it is open and until when", () => {
  const base = { studentName: "V", title: "T", classroomName: "G", questionCount: 10, timeLimitMinutes: null };
  const later = newTestMessage({ ...base, opensAt: hours(2), closesAt: null }, NOW, null).text;
  assert.ok(later.includes("Ochiladi: "));
  assert.ok(later.includes("Muddatsiz"));
  assert.ok(later.includes("10 ta savol · vaqt cheklanmagan"));
  const open = newTestMessage({ ...base, opensAt: hours(-2), closesAt: hours(5), timeLimitMinutes: 40 }, NOW, null).text;
  assert.ok(open.includes("Hozir ochiq"));
  assert.ok(open.includes("Yopiladi: "));
  assert.ok(open.includes("40 daqiqa"));
});

test("teacher summary lists who didn't submit, shortened", () => {
  const missing = Array.from({ length: 17 }, (_, i) => `O'quvchi ${i + 1}`);
  const m = teacherSummaryMessage({ title: "T", classroomName: "G", checked: 3, total: 20, average: 61.3, missing }, null);
  assert.ok(m.text.includes("Topshirdi: 3/20"));
  assert.ok(m.text.includes("O'rtacha: 61.3%"));
  assert.ok(m.text.includes("Topshirmadi (17): O'quvchi 1, "));
  assert.ok(m.text.endsWith("O'quvchi 15 va yana 2 ta"));
  const none = teacherSummaryMessage({ title: "T", classroomName: "G", checked: 0, total: 2, average: null, missing: ["A", "B"] }, null);
  assert.ok(!none.text.includes("O'rtacha"));
});

test("failed sends", () => {
  assert.equal(classifyFailure({ ok: false, status: 403, description: "Forbidden: bot was blocked by the user" }), "unreachable");
  assert.equal(classifyFailure({ ok: false, status: 400, description: "Bad Request: chat not found" }), "unreachable");
  assert.equal(classifyFailure({ ok: false, status: 400, description: "Bad Request: message is too long" }), "invalid");
  assert.equal(classifyFailure({ ok: false, status: 429, description: "Too Many Requests", retryAfter: 3 }), "rate_limited");
  assert.equal(classifyFailure({ ok: false, status: 0, description: "fetch failed" }), "retry");
  assert.equal(retryAt(1, NOW).getTime() - NOW.getTime(), 2 * 60_000);
  assert.equal(retryAt(10, NOW).getTime() - NOW.getTime(), 60 * 60_000);
});
