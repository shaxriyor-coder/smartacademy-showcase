import { test } from "node:test";
import assert from "node:assert/strict";
import { questionCreateSchema, testCreateSchema } from "../src/lib/validation";

const question = {
  subjectId: "s1",
  text: "2 + 2 = ?",
  correctAnswer: "4",
  themeIds: ["t1"],
  difficultyId: "d1",
  focus: "ABITURIENT" as const,
  skillIds: [],
};

// docs/DECISIONS.md #29: savol 4 yoki 5 variantli.
test("question options: 4 or 5, nothing else", () => {
  assert.equal(questionCreateSchema.safeParse({ ...question, wrongAnswers: ["3", "5", "6"] }).success, true);
  assert.equal(questionCreateSchema.safeParse({ ...question, wrongAnswers: ["3", "5", "6", "7"] }).success, true);
  assert.equal(questionCreateSchema.safeParse({ ...question, wrongAnswers: ["3", "5"] }).success, false);
  assert.equal(
    questionCreateSchema.safeParse({ ...question, wrongAnswers: ["3", "5", "6", "7", "8"] }).success,
    false,
  );
});

// docs/DECISIONS.md #31: olimpiada botda yaratiladi, bu yerda faqat tanlanadi.
test("olympiad test needs the bot's olympiad, not a typed name", () => {
  const base = { title: "Test", subjectId: "s1", questionIds: ["q1"] };
  assert.equal(testCreateSchema.safeParse({ ...base, isOlympiad: false }).success, true);
  assert.equal(
    testCreateSchema.safeParse({ ...base, isOlympiad: true, olympiadName: "Qo'lda yozilgan" }).success,
    false,
  );
  assert.equal(testCreateSchema.safeParse({ ...base, isOlympiad: true, smartbotOlympiadId: 3 }).success, true);
});
