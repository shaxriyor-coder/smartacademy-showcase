import { test } from "node:test";
import assert from "node:assert/strict";
import { suggestQuestions, themeStanding, type Candidate, type SuggestInput } from "../src/lib/suggest-core";

test("topic standing and weight", () => {
  assert.deepEqual(themeStanding(undefined), { standing: "untested", rate: null, weight: 0.35 });
  assert.deepEqual(themeStanding({ correct: 1, total: 2 }), { standing: "few", rate: 50, weight: 0.5 });
  assert.deepEqual(themeStanding({ correct: 3, total: 10 }), { standing: "weak", rate: 30, weight: 0.7 });
  assert.equal(themeStanding({ correct: 6, total: 10 }).standing, "developing");
  assert.deepEqual(themeStanding({ correct: 10, total: 10 }), { standing: "strong", rate: 100, weight: 0.1 });
});

// n questions of a topic, difficulty 1, 2, 3, 1, 2, 3…
const pool = (theme: string, n: number, extra: Partial<Candidate> = {}): Candidate[] =>
  Array.from({ length: n }, (_, i) => ({
    id: `${theme}${i + 1}`,
    themeIds: [theme],
    difficultyOrder: (i % 3) + 1,
    optionCount: 5,
    ...extra,
  }));

function input(o: Partial<SuggestInput>): SuggestInput {
  return {
    themes: [
      { id: "A", name: "Foizlar" },
      { id: "B", name: "Tenglamalar" },
      { id: "C", name: "Geometriya" },
    ],
    stats: new Map([
      ["A", { correct: 3, total: 10 }], // weak, 0.7
      ["B", { correct: 9, total: 10 }], // strong, 0.1
    ]), // C untested, 0.35
    candidates: [...pool("A", 10), ...pool("B", 10), ...pool("C", 10)],
    seen: new Map(),
    count: 10,
    choiceCounts: [4, 5],
    seed: "s",
    ...o,
  };
}

const slotsOf = (r: ReturnType<typeof suggestQuestions>) =>
  Object.fromEntries(r.plan.filter((p) => p.slots > 0).map((p) => [p.themeKey, p.slots]));

test("slots follow weakness: weak topic most, untested some, strong least", () => {
  const r = suggestQuestions(input({}));
  // 10 × 0.7/1.15 = 6.09, 10 × 0.1/1.15 = 0.87, 10 × 0.35/1.15 = 3.04 → 6, 1, 3.
  assert.deepEqual(slotsOf(r), { A: 6, B: 1, C: 3 });
  assert.equal(r.questions.length, 10);
  assert.equal(r.shortfall, 0);
  assert.equal(new Set(r.questions.map((q) => q.id)).size, 10);
  assert.deepEqual(r.plan[0], { themeKey: "A", name: "Foizlar", standing: "weak", rate: 30, slots: 6, available: 10 });
});

test("what a topic can't fill goes to the others; not enough at all is a shortfall", () => {
  const scarce = suggestQuestions(input({ candidates: [...pool("A", 2), ...pool("B", 10), ...pool("C", 10)] }));
  assert.equal(slotsOf(scarce).A, 2);
  assert.equal(scarce.questions.length, 10);
  const tiny = suggestQuestions(input({ candidates: pool("A", 4), count: 10 }));
  assert.equal(tiny.questions.length, 4);
  assert.equal(tiny.shortfall, 6);
});

test("questions they already had come last; unassignable ones never", () => {
  const seen = new Map([
    ["A1", 1],
    ["A2", 1],
    ["A3", 1],
  ]);
  const r = suggestQuestions(input({ candidates: [...pool("A", 8), ...pool("A", 1, { id: "A-bad", optionCount: 4 }), ...pool("C", 10)], seen, stats: new Map([["A", { correct: 0, total: 9 }]]), count: 5 }));
  const fromA = r.questions.filter((q) => q.themeKey === "A").map((q) => q.id);
  assert.ok(fromA.length > 0 && fromA.length <= 5);
  assert.ok(!fromA.some((id) => seen.has(id)), `ko'rilgan savol tanlanmasligi kerak: ${fromA}`);
  assert.ok(!r.questions.some((q) => q.id === "A-bad"));
  // The seen ones wait at the end of the alternates.
  assert.deepEqual(r.alternates.A.slice(-3).sort(), ["A1", "A2", "A3"]);
});

test("fresh questions from other topics before repeating a weak topic's old ones", () => {
  const seen = new Map([
    ["A1", 1],
    ["A2", 1],
    ["A3", 1],
  ]);
  const base = { candidates: [...pool("A", 5), ...pool("C", 10)], seen, stats: new Map([["A", { correct: 0, total: 9 }]]) };
  const fresh = suggestQuestions(input({ ...base, count: 6 }));
  assert.deepEqual(slotsOf(fresh), { A: 2, C: 4 });
  assert.ok(!fresh.questions.some((q) => q.seen > 0));
  // 12 fresh in all: the 13th is one they had, from the weak topic.
  const more = suggestQuestions(input({ ...base, count: 13 }));
  assert.deepEqual(slotsOf(more), { A: 3, C: 10 });
  assert.equal(more.questions.filter((q) => q.seen > 0).length, 1);
});

test("difficulty is mixed, easiest first for a weak topic", () => {
  const r = suggestQuestions(input({ candidates: pool("A", 9), themes: [{ id: "A", name: "Foizlar" }], count: 5 }));
  const orders = r.questions.map((q) => Number(q.id.slice(1)) % 3 || 3).sort();
  // 5 of 9 (three per level): two rounds of 1-2-3, cut after 5 → 1,1,2,2,3.
  assert.deepEqual(orders, [1, 1, 2, 2, 3]);
});

test("a question in two topics counts toward the weaker one", () => {
  const both: Candidate = { id: "AB", themeIds: ["B", "A"], difficultyOrder: 1, optionCount: 5 };
  const r = suggestQuestions(input({ candidates: [both, ...pool("B", 10)], count: 5 }));
  assert.equal(r.questions.find((q) => q.id === "AB")?.themeKey, "A");
});

test("same seed, same test; a weak topic with no questions is still named", () => {
  const a = suggestQuestions(input({}));
  const b = suggestQuestions(input({}));
  assert.deepEqual(a.questions, b.questions);
  const empty = suggestQuestions(
    input({ candidates: pool("C", 10), stats: new Map([["A", { correct: 1, total: 10 }]]), count: 5 }),
  );
  assert.ok(empty.plan.some((p) => p.themeKey === "A" && p.available === 0 && p.standing === "weak"));
});
