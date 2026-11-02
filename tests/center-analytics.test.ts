import { test } from "node:test";
import assert from "node:assert/strict";
import {
  computeCenterAnalytics,
  computeQuestionBankAnalytics,
  computeTeacherAnalytics,
  tashkentWeekStart,
  type BankQuestion,
  type CenterSheet,
} from "../src/lib/center-analytics-core";

const at = (iso: string) => new Date(`${iso}T10:00:00Z`);
const NOW = new Date("2026-09-13T12:00:00Z"); // a Sunday

let seq = 0;
function sheet(overrides: Partial<CenterSheet>): CenterSheet {
  seq += 1;
  return {
    id: `sh${seq}`,
    studentId: "s1",
    teacherId: "t1",
    assignmentId: `a${seq}`,
    mode: "OFFLINE",
    title: "Test",
    subjectName: "Matematika",
    status: "checked",
    startedAt: null,
    checkedAt: null,
    percentage: null,
    correct: null,
    total: null,
    answers: [],
    answerKey: [],
    questionIds: [],
    ...overrides,
  };
}
const done = (studentId: string, percentage: number, day: string, subjectName = "Matematika", teacherId = "t1") =>
  sheet({ studentId, percentage, checkedAt: at(day), subjectName, teacherId });

test("Tashkent weeks start on Monday 00:00 local time", () => {
  assert.equal(tashkentWeekStart(new Date("2026-09-13T10:00:00Z")).toISOString(), "2026-09-06T19:00:00.000Z");
  // Sunday 20:00 UTC is already Monday 01:00 in Tashkent.
  assert.equal(tashkentWeekStart(new Date("2026-09-13T20:00:00Z")).toISOString(), "2026-09-13T19:00:00.000Z");
});

// Ali steady and strong; Vali weak; Gani strong on average but dropping;
// Doni has only an open test.
const centerSheets = [
  done("s1", 90, "2026-08-01"),
  done("s1", 80, "2026-09-10"),
  done("s2", 30, "2026-08-20", "Ingliz tili"),
  done("s2", 40, "2026-09-12"),
  done("s3", 90, "2026-08-05", "Ingliz tili", "t2"),
  done("s3", 70, "2026-09-11", "Ingliz tili", "t2"),
  sheet({ studentId: "s3", teacherId: "t2", status: "missed" }),
  sheet({ studentId: "s4", status: "available" }),
];
const center = computeCenterAnalytics(
  [
    { id: "s1", name: "Ali", teachers: ["Karimova"] },
    { id: "s2", name: "Vali", teachers: ["Karimova"] },
    { id: "s3", name: "Gani", teachers: ["Tursunov"] },
    { id: "s4", name: "Doni", teachers: [] },
  ],
  centerSheets,
  new Map(),
  NOW,
);

test("centre totals and the last 30 days against the 30 before", () => {
  assert.deepEqual(center.counts, {
    students: 4,
    activeStudents: 3,
    results: 6,
    recentResults: 4,
    missed: 1,
    pending: 1,
  });
  assert.equal(center.average, 66.7);
  assert.equal(center.recentAverage, 55);
  assert.equal(center.previousAverage, 90);
  assert.equal(center.change, -35);
  assert.equal(center.completion, 86);
});

test("weekly trend, subjects and distribution", () => {
  assert.deepEqual(
    center.trend.map((w) => [w.weekStart.toISOString().slice(0, 10), w.results, w.average]),
    [
      ["2026-07-26", 1, 90],
      ["2026-08-02", 1, 90],
      ["2026-08-16", 1, 30],
      ["2026-09-06", 3, 63.3],
    ],
  );
  assert.deepEqual(
    center.subjects.map((s) => [s.name, s.students, s.results, s.average]),
    [
      ["Ingliz tili", 2, 3, 63.3],
      ["Matematika", 2, 3, 70],
    ],
  );
  assert.deepEqual(center.distribution, { weak: 1, developing: 0, strong: 2, noResults: 1 });
});

test("attention and best results", () => {
  assert.deepEqual(
    center.attention.map((s) => [s.name, s.reason]),
    [
      ["Vali", "low"],
      ["Gani", "drop"],
    ],
  );
  // Vali has two tests but isn't strong; Doni has none.
  assert.deepEqual(
    center.top.map((s) => [s.name, s.average, s.teachers]),
    [
      ["Ali", 85, ["Karimova"]],
      ["Gani", 80, ["Tursunov"]],
    ],
  );
});

test("teacher rows, including a non-teacher who still owns a classroom", () => {
  const t = computeTeacherAnalytics(
    {
      staff: [
        { id: "t1", name: "Karimova", role: "TEACHER" },
        { id: "t2", name: "Tursunov", role: "TEACHER" },
        { id: "a1", name: "Super Admin", role: "SUPER_ADMIN" },
        { id: "a2", name: "Admin", role: "ADMIN" },
      ],
      classrooms: [
        { id: "c1", teacherId: "t1", studentIds: ["s1", "s2"] },
        { id: "c2", teacherId: "t2", studentIds: ["s3"] },
        { id: "c3", teacherId: "a1", studentIds: ["s1", "s4"] },
      ],
      assignments: [
        { id: "A1", teacherId: "t1", mode: "OFFLINE", createdAt: at("2026-09-01") },
        { id: "A2", teacherId: "t1", mode: "ONLINE", createdAt: at("2026-08-01") },
        { id: "A3", teacherId: "t2", mode: "ONLINE", createdAt: at("2026-09-10") },
        { id: "A4", teacherId: "a1", mode: "OFFLINE", createdAt: at("2026-07-01") },
      ],
      sheets: [
        done("s1", 80, "2026-09-10"),
        done("s2", 40, "2026-09-12"),
        sheet({ studentId: "s2", status: "missed" }),
        done("s3", 70, "2026-09-11", "Matematika", "t2"),
        sheet({ studentId: "s3", teacherId: "t2", status: "available" }),
      ],
      questions: [
        { createdById: "t1", createdAt: at("2026-09-05") },
        { createdById: "t1", createdAt: at("2026-09-05") },
        { createdById: "a2", createdAt: at("2026-09-01") },
      ],
      tests: [{ createdById: "t1", createdAt: at("2026-08-20") }],
    },
    NOW,
  );

  assert.deepEqual(
    t.rows.map((r) => [r.name, r.isTeacher, r.classrooms, r.students, r.assignments, r.online, r.recentAssignments]),
    [
      ["Karimova", true, 1, 2, 2, 1, 1],
      ["Tursunov", true, 1, 1, 1, 1, 1],
      ["Super Admin", false, 1, 2, 1, 0, 0],
    ],
  );
  assert.deepEqual(
    t.rows.map((r) => [r.results, r.completion, r.average, r.weakStudents, r.questions, r.tests, r.active]),
    [
      [2, 67, 60, 1, 2, 1, true],
      [1, 100, 70, 0, 0, 0, true],
      [0, null, null, 0, 0, 0, false],
    ],
  );
  assert.equal(t.rows[0].lastActivity?.toISOString(), at("2026-09-12").toISOString());
  assert.deepEqual(
    [t.teachers, t.activeTeachers, t.otherOwners, t.recentAssignments, t.recentResults, t.average],
    [2, 2, 1, 2, 3, 63.3],
  );
});

test("question bank: usage, quality, coverage, hardest and a suspicious key", () => {
  const q = (id: string, overrides: Partial<BankQuestion>): BankQuestion => ({
    id,
    text: `Savol ${id}`,
    subjectName: "Matematika",
    themeIds: ["th1"],
    themeNames: ["Tenglamalar"],
    subThemeCount: 0,
    skillCount: 0,
    difficulty: { name: "Oson", order: 1 },
    optionCount: 5,
    createdAt: at("2026-09-10"),
    author: { id: "t1", name: "Karimova" },
    ...overrides,
  });

  const bank = computeQuestionBankAnalytics(
    {
      questions: [
        q("q1", { subThemeCount: 1, skillCount: 1 }),
        q("q2", { difficulty: { name: "Qiyin", order: 3 }, createdAt: at("2026-08-01") }),
        q("q3", {
          themeIds: ["th2"],
          themeNames: ["Foizlar"],
          difficulty: { name: "oson ", order: 1 },
          optionCount: 3, // 4 va 5 ruxsat etilgan — bu savol testga tushmaydi

          createdAt: at("2026-09-12"),
          author: { id: "a1", name: "Admin" },
        }),
      ],
      themes: [
        { id: "th1", name: "Tenglamalar", subjectName: "Matematika" },
        { id: "th2", name: "Foizlar", subjectName: "Matematika" },
        { id: "th3", name: "Grammar", subjectName: "Ingliz tili" },
      ],
      tests: [{ questionIds: ["q1", "q2"] }, { questionIds: ["q1"] }],
      assignments: [
        {
          id: "A1",
          title: "Nazorat 1",
          questionIds: ["q1", "q2"],
          answerKey: ["A", "C"],
          answers: [["A", "B"], ["A", "B"], ["A", "B"], ["A", "B"], ["B", "C"], ["", "*"]],
        },
      ],
      choiceCounts: [4, 5],
    },
    NOW,
  );

  assert.deepEqual(bank.totals, {
    questions: 3,
    recent: 2,
    inTests: 2,
    unused: 1,
    usedShare: 67,
    answered: 2,
    responses: 12,
    correctRate: 42,
  });
  assert.equal(bank.quality.notAssignable, 1);
  assert.deepEqual(bank.quality.notAssignableSamples.map((s) => [s.id, s.options]), [["q3", 3]]);
  assert.equal(bank.quality.noSubThemes, 2);
  assert.equal(bank.quality.noSkills, 2);

  assert.deepEqual(
    bank.subjects.map((s) => [s.name, s.questions, s.themes, s.unused, s.responses, s.correctRate]),
    [
      ["Matematika", 3, 2, 1, 12, 42],
      ["Ingliz tili", 0, 1, 0, 0, null],
    ],
  );
  assert.deepEqual(
    bank.subjects[0].difficulty.map((d) => [d.name, d.count]),
    [
      ["Oson", 2],
      ["Qiyin", 1],
    ],
  );
  assert.deepEqual(
    bank.coverage.map((t) => [t.name, t.questions]),
    [
      ["Grammar", 0],
      ["Foizlar", 1],
      ["Tenglamalar", 2],
    ],
  );
  assert.deepEqual(
    bank.hardest.map((h) => [h.id, h.percentage, h.responses, h.tests]),
    [
      ["q2", 17, 6, 1],
      ["q1", 67, 6, 2],
    ],
  );
  assert.deepEqual(
    bank.suspectKeys.map((s) => [s.questionId, s.assignmentTitle, s.number, s.key, s.popular, s.share]),
    [["q2", "Nazorat 1", 2, "C", "B", 67]],
  );
  assert.deepEqual(
    bank.authors.map((a) => [a.name, a.questions, a.recent]),
    [
      ["Karimova", 2, 1],
      ["Admin", 1, 1],
    ],
  );
});
