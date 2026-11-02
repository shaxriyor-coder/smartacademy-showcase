import { test } from "node:test";
import assert from "node:assert/strict";
import type { QuestionMeta } from "../src/lib/analytics-core";
import {
  duePeriods,
  latestMonthlyPeriod,
  latestWeeklyPeriod,
  reportMessage,
  studentReport,
  type ReportSheet,
} from "../src/lib/reports-core";

// 19:00 in Tashkent is 14:00 UTC.
const iso = (d: Date) => d.toISOString();

test("weekly period ends on the latest Sunday 19:00 Tashkent", () => {
  // Sunday 2026-09-13, 20:00 Tashkent (15:00 UTC): this evening's report.
  const sundayEvening = latestWeeklyPeriod(new Date("2026-09-13T15:00:00Z"));
  assert.equal(iso(sundayEvening.end), "2026-09-13T14:00:00.000Z");
  assert.equal(iso(sundayEvening.start), "2026-09-06T14:00:00.000Z");
  assert.equal(sundayEvening.key, "weekly:2026-09-13");
  assert.equal(sundayEvening.label, "07.09–13.09");
  // Sunday 18:00 Tashkent: still last week's.
  assert.equal(iso(latestWeeklyPeriod(new Date("2026-09-13T13:00:00Z")).end), "2026-09-06T14:00:00.000Z");
  // Wednesday.
  assert.equal(iso(latestWeeklyPeriod(new Date("2026-09-16T08:00:00Z")).end), "2026-09-13T14:00:00.000Z");
});

test("monthly period ends on the month's last day at 19:00 Tashkent", () => {
  const sept = latestMonthlyPeriod(new Date("2026-09-30T15:00:00Z"));
  assert.equal(iso(sept.end), "2026-09-30T14:00:00.000Z");
  assert.equal(iso(sept.start), "2026-08-31T14:00:00.000Z");
  assert.equal(sept.key, "monthly:2026-09");
  assert.equal(sept.label, "sentabr 2026");
  // Mid-September: August's report.
  const aug = latestMonthlyPeriod(new Date("2026-09-13T15:00:00Z"));
  assert.equal(aug.key, "monthly:2026-08");
  assert.equal(iso(aug.end), "2026-08-31T14:00:00.000Z");
  // Across a year boundary.
  assert.equal(latestMonthlyPeriod(new Date("2027-01-05T08:00:00Z")).key, "monthly:2026-12");
});

test("due only shortly after the end, and never for periods before reports existed", () => {
  const since = new Date("2026-09-01T00:00:00Z");
  const sundayNight = new Date("2026-09-13T15:00:00Z");
  assert.deepEqual(duePeriods(sundayNight, since).map((p) => p.key), ["weekly:2026-09-13"]);
  // Wednesday: the weekly one is older than two days.
  assert.deepEqual(duePeriods(new Date("2026-09-16T08:00:00Z"), since), []);
  // Switched on after this Sunday's 19:00: nothing for this week.
  assert.deepEqual(duePeriods(sundayNight, new Date("2026-09-13T14:30:00Z")), []);
  // The last day of September, which is a Wednesday: the monthly one.
  assert.deepEqual(duePeriods(new Date("2026-09-30T15:00:00Z"), since).map((p) => p.key), ["monthly:2026-09"]);
});

let n = 0;
function sheet(o: Partial<ReportSheet>): ReportSheet {
  n += 1;
  return {
    id: `s${n}`,
    assignmentId: `a${n}`,
    status: "checked",
    mode: "OFFLINE",
    title: `Test ${n}`,
    subjectName: "Matematika",
    classroomName: "7-A",
    startedAt: null,
    checkedAt: null,
    percentage: null,
    correct: null,
    total: null,
    answers: ["A", "B", "C"],
    answerKey: ["A", "C", "D"],
    questionIds: ["q1", "q2", "q3"],
    detailAllowed: true,
    classAverage: null,
    closesAt: null,
    ...o,
  };
}

const theme = { id: "t1", name: "Foizlar", subjectName: "Matematika" };
const meta = new Map<string, QuestionMeta>(
  ["q1", "q2", "q3"].map((id) => [id, { themes: [theme], subThemes: [], difficulty: null, skills: [] }]),
);
const week = latestWeeklyPeriod(new Date("2026-09-13T15:00:00Z"));

test("a week's report: tests, change, missed, focus topics", () => {
  const r = studentReport(
    [
      sheet({ title: "Oldingi", percentage: 50, checkedAt: new Date("2026-09-03T08:00:00Z") }),
      sheet({ title: "Nazorat 1", percentage: 80, checkedAt: new Date("2026-09-08T08:00:00Z"), classAverage: 70 }),
      sheet({ title: "Nazorat 2", percentage: 30, checkedAt: new Date("2026-09-12T08:00:00Z") }),
      sheet({ title: "Online", status: "missed", mode: "ONLINE", closesAt: new Date("2026-09-10T08:00:00Z") }),
      sheet({ title: "Kelgusi", status: "available", mode: "ONLINE", closesAt: new Date("2026-09-20T08:00:00Z") }),
    ],
    week,
    meta,
  );
  assert.ok(r);
  assert.deepEqual(r.tests.map((t) => t.title), ["Nazorat 1", "Nazorat 2"]);
  assert.equal(r.average, 55);
  assert.equal(r.change, 5);
  assert.deepEqual(r.missed, ["Online"]);
  // Each sheet got 1 of 3 right on the Foizlar questions.
  assert.deepEqual(r.focus, [{ name: "Foizlar", percentage: 33 }]);

  const m = reportMessage(week, "Aliyev Vali", r, null);
  assert.equal(
    m.text,
    [
      "📅 Haftalik hisobot — Aliyev Vali",
      "07.09–13.09",
      "Topshirilgan testlar: 2 ta · o'rtacha 55% (▲ +5 oldingi haftaga nisbatan)",
      "• Nazorat 1 — 80%",
      "• Nazorat 2 — 30%",
      "Topshirilmadi: Online",
      "Ko'proq e'tibor kerak: Foizlar (33%)",
    ].join("\n"),
  );
  assert.equal(m.button, null);
});

test("nothing in the period: no report; hidden answers don't reach topics", () => {
  assert.equal(studentReport([sheet({ percentage: 90, checkedAt: new Date("2026-08-01T08:00:00Z") })], week, meta), null);
  const hidden = studentReport(
    [sheet({ percentage: 40, checkedAt: new Date("2026-09-09T08:00:00Z"), detailAllowed: false })],
    week,
    meta,
  );
  assert.ok(hidden);
  assert.deepEqual(hidden.focus, []);
  assert.equal(hidden.change, null);
});

test("monthly text: subjects and best result instead of every test", () => {
  const month = latestMonthlyPeriod(new Date("2026-09-30T15:00:00Z"));
  const r = studentReport(
    [
      sheet({ title: "A", percentage: 90, checkedAt: new Date("2026-09-05T08:00:00Z") }),
      sheet({ title: "B", percentage: 60, checkedAt: new Date("2026-09-20T08:00:00Z"), subjectName: "Ingliz tili" }),
    ],
    month,
    new Map(),
  );
  assert.ok(r);
  const text = reportMessage(month, "Vali", r, { url: "https://x.uz/tg", webApp: true }).text;
  assert.ok(text.startsWith("🗓 Oylik hisobot — Vali\nsentabr 2026\nTopshirilgan testlar: 2 ta · o'rtacha 75%"));
  assert.ok(text.includes("Fanlar: "));
  assert.ok(text.includes("Eng yaxshi natija: A"));
});
