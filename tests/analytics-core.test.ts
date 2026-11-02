import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bandOf,
  computeStudentAnalytics,
  type AnalyticsSheet,
  type QuestionMeta,
} from "../src/lib/analytics-core";

const day = (n: number) => new Date(Date.UTC(2026, 8, n, 10));

function sheet(overrides: Partial<AnalyticsSheet>): AnalyticsSheet {
  return {
    id: "s",
    assignmentId: "a",
    status: "checked",
    mode: "OFFLINE",
    title: "Test",
    subjectName: "Matematika",
    classroomName: "7-A",
    startedAt: null,
    checkedAt: day(1),
    percentage: 50,
    correct: 2,
    total: 4,
    answers: ["A", "B", "", "*"],
    answerKey: ["A", "B", "C", "D"],
    questionIds: ["q1", "q2", "q3", "q4"],
    detailAllowed: true,
    classAverage: null,
    ...overrides,
  };
}

const meta = new Map<string, QuestionMeta>([
  ["q1", { themes: [{ id: "t1", name: "Tenglamalar", subjectName: "Matematika" }], subThemes: [{ id: "st1", name: "Chiziqli", themeId: "t1" }], difficulty: { name: "Oson", order: 1 }, skills: [] }],
  ["q2", { themes: [{ id: "t1", name: "Tenglamalar", subjectName: "Matematika" }], subThemes: [], difficulty: { name: "QIyin", order: 0 }, skills: [{ id: "k1", name: "Muammoli" }] }],
  ["q3", { themes: [{ id: "t2", name: "Foizlar", subjectName: "Matematika" }], subThemes: [], difficulty: { name: "Qiyin", order: 3 }, skills: [{ id: "k1", name: "Muammoli" }] }],
  ["q4", { themes: [{ id: "t2", name: "Foizlar", subjectName: "Matematika" }], subThemes: [], difficulty: { name: "O'rtacha", order: 2 }, skills: [] }],
]);

test("bands", () => {
  assert.equal(bandOf(80), "strong");
  assert.equal(bandOf(79), "developing");
  assert.equal(bandOf(50), "developing");
  assert.equal(bandOf(49), "weak");
});

test("counts, averages, change and class comparison", () => {
  const a = computeStudentAnalytics(
    [
      sheet({ id: "1", checkedAt: day(1), percentage: 40, classAverage: 50 }),
      sheet({ id: "2", checkedAt: day(5), percentage: 70, classAverage: 60 }),
      sheet({ id: "3", checkedAt: null, percentage: null, status: "missed" }),
      sheet({ id: "4", checkedAt: null, percentage: null, status: "available" }),
    ],
    meta,
  );
  assert.deepEqual(a.counts, { assigned: 4, checked: 2, missed: 1, pending: 1 });
  assert.equal(a.average, 55);
  assert.equal(a.change, 30);
  assert.equal(a.vsClass, 0); // (-10 + 10) / 2
  assert.deepEqual(a.timeline.map((t) => t.id), ["1", "2"]);
});

test("answer mix and topic breakdown follow the answers", () => {
  const a = computeStudentAnalytics([sheet({})], meta);
  assert.deepEqual(a.answerMix, { correct: 2, wrong: 0, blank: 1, multi: 1, total: 4 });
  const [weakest, strongest] = a.themes;
  assert.equal(weakest.name, "Foizlar");
  assert.equal(weakest.percentage, 0);
  assert.equal(weakest.band, "weak");
  assert.equal(strongest.name, "Tenglamalar");
  assert.equal(strongest.percentage, 100);
  assert.deepEqual(strongest.subThemes.map((st) => [st.name, st.total]), [["Chiziqli", 1]]);
  assert.deepEqual(a.skills, [{ name: "Muammoli", correct: 1, total: 2, percentage: 50 }]);
});

test("difficulty levels merge by name and keep a sensible order", () => {
  const a = computeStudentAnalytics([sheet({})], meta);
  assert.deepEqual(
    a.difficulty.map((d) => [d.name, d.total]),
    [["Oson", 1], ["O'rtacha", 1], ["Qiyin", 2]],
  );
});

test("sheets whose answers are still hidden count in scores but not in breakdowns", () => {
  const a = computeStudentAnalytics(
    [sheet({ id: "open", percentage: 50 }), sheet({ id: "hidden", percentage: 100, answers: ["A", "B", "C", "D"], detailAllowed: false })],
    meta,
  );
  assert.equal(a.average, 75);
  assert.equal(a.answerMix.total, 4);
  assert.equal(a.hiddenDetails, 1);
});

test("next steps need enough questions per topic", () => {
  const few = computeStudentAnalytics([sheet({})], meta);
  assert.equal(few.focus.length, 0); // 2 questions per topic < FOCUS_MIN_QUESTIONS
  const many = computeStudentAnalytics(
    [sheet({ id: "1" }), sheet({ id: "2", checkedAt: day(2) })],
    meta,
  );
  assert.deepEqual(many.focus.map((t) => t.name), ["Foizlar"]); // Tenglamalar is 100%
});

test("online time is measured from start to submit", () => {
  const a = computeStudentAnalytics(
    [sheet({ mode: "ONLINE", startedAt: new Date(day(1).getTime() - 12 * 60_000), checkedAt: day(1) })],
    meta,
  );
  assert.equal(a.onlineMinutes, 12);
});
