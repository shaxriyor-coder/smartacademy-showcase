import { seededShuffle } from "./shuffle";

export const LETTERS = ["A", "B", "C", "D", "E"] as const;

// A bank question has 1 correct + 3 or 4 wrong answers (questionCreateSchema),
// so a question is printed as A-D or A-E. A test may mix the two: the paper
// answer sheet is drawn with the widest question's bubbles (ensureTemplate),
// and a 4-option question simply never has E in the key.
export const MIN_CHOICES = 4;
export const MAX_CHOICES = 5;

export const optionCount = (question: { wrongAnswers: string[] }) =>
  question.wrongAnswers.length + 1;

export const isAllowedOptionCount = (count: number) =>
  count >= MIN_CHOICES && count <= MAX_CHOICES;

export const ALLOWED_OPTION_COUNTS = [MIN_CHOICES, MAX_CHOICES];

// The letter under which a question's correct answer is printed.
//
// src/lib/docx.ts shuffles the option OBJECTS with the same seed
// (`testId:questionId`); seededShuffle's permutation depends only on the seed
// and the item count, so shuffling indices here lands the correct answer on
// exactly the letter the Word paper shows it under.
export function correctLetter(
  testId: string,
  question: { id: string; wrongAnswers: string[] },
): string {
  const order = seededShuffle(
    `${testId}:${question.id}`,
    [0, ...question.wrongAnswers.map((_, i) => i + 1)],
  );
  return LETTERS[order.indexOf(0)];
}

// A test's key and bubble count, stored on the Test when it's built and
// refreshed on export (docs/DECISIONS.md #32) — smartbot reads those columns
// when it prepares the answer sheet for an olympiad, so nobody retypes them.
export function buildTestKey(
  testId: string,
  questions: { id: string; wrongAnswers: string[] }[],
): string[] {
  return questions.map((q) => correctLetter(testId, q));
}

export function testChoiceCount(questions: { wrongAnswers: string[] }[]): number {
  if (questions.length === 0) return MIN_CHOICES;
  return Math.min(MAX_CHOICES, Math.max(MIN_CHOICES, ...questions.map(optionCount)));
}

// OMR answers as stored on AssignmentSheet.answers.
export const BLANK_ANSWER = "";
export const MULTI_ANSWER = "*";

export function gradeAnswers(answers: string[], key: string[]) {
  const correct = key.reduce((n, want, i) => (answers[i] === want ? n + 1 : n), 0);
  const total = key.length;
  const percentage = total ? Math.round((correct / total) * 1000) / 10 : 0;
  return { correct, total, percentage };
}
