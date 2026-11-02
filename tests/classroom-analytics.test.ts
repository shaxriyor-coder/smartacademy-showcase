import { test } from "node:test";
import assert from "node:assert/strict";
import {
  computeClassroomAnalytics,
  type ClassroomAssignment,
  type ClassroomSheet,
  type QuestionMeta,
} from "../src/lib/analytics-core";

const day = (n: number) => new Date(Date.UTC(2026, 8, n, 10));
const KEY = ["A", "B", "C", "D"];

function sheet(studentId: string, answers: string[] | null, overrides: Partial<ClassroomSheet> = {}): ClassroomSheet {
  const correct = answers ? answers.filter((a, i) => a === KEY[i]).length : null;
  return {
    id: `${studentId}-${Math.random()}`,
    studentId,
    status: answers ? "checked" : "missed",
    startedAt: null,
    checkedAt: answers ? day(2) : null,
    percentage: correct == null ? null : (correct / KEY.length) * 100,
    correct,
    total: answers ? KEY.length : null,
    answers: answers ?? [],
    ...overrides,
  };
}

function assignment(id: string, createdDay: number, sheets: ClassroomSheet[]): ClassroomAssignment {
  return {
    id,
    title: id,
    subjectName: "Matematika",
    mode: "OFFLINE",
    createdAt: day(createdDay),
    questionIds: ["q1", "q2", "q3", "q4"],
    answerKey: KEY,
    // Checked the day after it was given.
    sheets: sheets.map((s) => (s.checkedAt ? { ...s, checkedAt: day(createdDay + 1) } : s)),
  };
}

const theme = (id: string, name: string) => ({ id, name, subjectName: "Matematika" });
const meta = new Map<string, QuestionMeta>([
  ["q1", { themes: [theme("t1", "Tenglamalar")], subThemes: [], difficulty: null, skills: [] }],
  ["q2", { themes: [theme("t1", "Tenglamalar")], subThemes: [], difficulty: null, skills: [] }],
  ["q3", { themes: [theme("t2", "Foizlar")], subThemes: [], difficulty: null, skills: [] }],
  ["q4", { themes: [theme("t2", "Foizlar")], subThemes: [], difficulty: null, skills: [] }],
]);

const members = [
  { id: "ali", name: "Ali" },
  { id: "vali", name: "Vali" },
  { id: "gani", name: "Gani" },
  { id: "doni", name: "Doni" },
];

// Ali steady at 100; Vali low (50 → 25); Gani fine on average but dropping
// (75 → 50); Doni missed the first test and hasn't done the second yet.
const assignments = [
  // Listed newest first on purpose: the result must be chronological.
  assignment("second", 5, [
    sheet("ali", ["A", "B", "C", "D"]),
    sheet("vali", ["A", "", "", ""]),
    sheet("gani", ["A", "B", "", ""]),
    sheet("doni", null, { status: "available" }),
  ]),
  assignment("first", 1, [
    sheet("ali", ["A", "B", "C", "D"]),
    sheet("vali", ["A", "B", "", "*"]),
    sheet("gani", ["A", "B", "C", "A"]),
    sheet("doni", null),
  ]),
];

const a = computeClassroomAnalytics(members, assignments, meta);

test("group totals", () => {
  assert.equal(a.members, 4);
  assert.deepEqual(a.counts, { assigned: 8, checked: 6, missed: 1, pending: 1 });
  assert.equal(a.average, 66.7);
  // 6 checked out of 7 settled chances; the open test isn't held against anyone.
  assert.equal(a.completion, 86);
  assert.equal(a.change, -16.7);
});

test("per assignment, oldest first", () => {
  assert.deepEqual(
    a.assignments.map((x) => [x.id, x.checked, x.missed, x.pending, x.average, x.min, x.max]),
    [
      ["first", 3, 1, 0, 75, 50, 100],
      ["second", 3, 0, 1, 58.3, 25, 100],
    ],
  );
});

test("students weakest first, no results last", () => {
  assert.deepEqual(
    a.students.map((s) => [s.name, s.average, s.last, s.change]),
    [
      ["Vali", 37.5, 25, -25],
      ["Gani", 62.5, 50, -25],
      ["Ali", 100, 100, 0],
      ["Doni", null, null, null],
    ],
  );
  assert.equal(a.students[0].weakestTopic?.name, "Foizlar");
  assert.equal(a.students[2].weakestTopic, null);
});

test("distribution and attention list", () => {
  assert.deepEqual(a.distribution, { weak: 1, developing: 1, strong: 1, noResults: 1 });
  assert.deepEqual(
    a.attention.map((s) => [s.name, s.reason]),
    [
      ["Vali", "low"],
      ["Gani", "drop"],
    ],
  );
});

test("hardest questions, multi-marks count as wrong", () => {
  assert.deepEqual(
    a.hardest.map((q) => [q.assignmentId, q.number, q.percentage]),
    [
      ["first", 4, 33],
      ["second", 3, 33],
      ["second", 4, 33],
      ["first", 3, 67],
      ["second", 2, 67],
    ],
  );
  assert.deepEqual(a.hardest[0].themes, ["Foizlar"]);
  assert.equal(a.hardest[0].answer, "D");
});

test("too few checked sheets: no hardest questions", () => {
  const small = computeClassroomAnalytics(
    members.slice(0, 2),
    [assignment("only", 1, [sheet("ali", ["A", "B", "C", "D"]), sheet("vali", ["", "", "", ""])])],
    meta,
  );
  assert.deepEqual(small.hardest, []);
  assert.equal(small.change, null);
});
