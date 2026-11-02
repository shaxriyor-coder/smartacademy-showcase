import type { AssignmentMode } from "@prisma/client";
import { prisma } from "./prisma";
import { HttpError } from "./http-error";
import { BLANK_ANSWER, LETTERS, MAX_CHOICES, gradeAnswers } from "./answer-key";
import {
  attemptDeadline,
  canonicalOptions,
  formatTashkent,
  isPastDeadline,
  optionOrder,
  questionOrder,
  windowState,
  type RunnerQuestion,
} from "./online-core";

// Online attempts: through a linked Telegram account a student starts an
// ONLINE assignment's sheet, answers are saved one click at a time, and the
// sheet is graded on submit — or by itself once the time is up.

// Savol 4 yoki 5 variantli bo'lishi mumkin — harf savolning o'ziga qarab
// tekshirilmaydi: bosilmagan harf baribir kalitga to'g'ri kelmaydi.
const VALID_CHOICES = new Set<string>([BLANK_ANSWER, ...LETTERS]);

type ExpirableAssignment = {
  mode: AssignmentMode;
  answerKey: string[];
  opensAt: Date | null;
  closesAt: Date | null;
  timeLimitMinutes: number | null;
};

type ExpirableSheet = {
  id: string;
  startedAt: Date | null;
  checkedAt: Date | null;
  answers: string[];
  correct: number | null;
  total: number | null;
  percentage: number | null;
};

function padAnswers(answers: string[], count: number): string[] {
  return Array.from({ length: count }, (_, i) => answers[i] ?? BLANK_ANSWER);
}

// Grades an attempt whose time ran out with nobody submitting it (the app was
// closed, the phone died). Called wherever sheets are read, so a result never
// waits for the student to come back. Recorded as submitted AT the deadline.
export async function finalizeIfExpired<S extends ExpirableSheet>(
  assignment: ExpirableAssignment,
  sheet: S,
  now = new Date(),
): Promise<S> {
  if (assignment.mode !== "ONLINE" || !sheet.startedAt || sheet.checkedAt) return sheet;
  const deadline = attemptDeadline(assignment, sheet.startedAt);
  if (!deadline || !isPastDeadline(deadline, now)) return sheet;

  const answers = padAnswers(sheet.answers, assignment.answerKey.length);
  const grade = gradeAnswers(answers, assignment.answerKey);
  await prisma.assignmentSheet.updateMany({
    where: { id: sheet.id, checkedAt: null },
    data: { answers, ...grade, checkedAt: deadline },
  });
  return { ...sheet, answers, ...grade, checkedAt: deadline };
}

// A sheet of a student linked to this Telegram account — 404 otherwise, not
// 403, so other students' sheet ids can't be probed.
export async function sheetForAccount(sheetId: string, accountId: string) {
  const sheet = await prisma.assignmentSheet.findFirst({
    where: {
      id: sheetId,
      assignment: { archived: false },
      student: { telegramLinks: { some: { telegramAccountId: accountId } } },
    },
    include: {
      student: { select: { firstName: true, lastName: true } },
      assignment: {
        select: {
          id: true,
          testId: true,
          title: true,
          subjectName: true,
          mode: true,
          questionIds: true,
          answerKey: true,
          opensAt: true,
          closesAt: true,
          timeLimitMinutes: true,
          shuffle: true,
          revealAnswers: true,
          classroom: { select: { name: true } },
        },
      },
    },
  });
  if (!sheet) throw new HttpError("Test topilmadi", 404);
  return finalizeIfExpired(sheet.assignment, sheet);
}

export type AccountSheet = Awaited<ReturnType<typeof sheetForAccount>>;

function requireOnline(sheet: AccountSheet) {
  if (sheet.assignment.mode !== "ONLINE") {
    throw new HttpError("Bu test qog'ozda topshiriladi", 409);
  }
}

export async function startAttempt(sheetId: string, accountId: string) {
  const sheet = await sheetForAccount(sheetId, accountId);
  requireOnline(sheet);
  if (sheet.checkedAt) throw new HttpError("Test allaqachon topshirilgan", 409);
  if (sheet.startedAt) return; // resuming on another device or after a reload

  const a = sheet.assignment;
  const state = windowState(a, new Date());
  if (state === "not_open") {
    throw new HttpError(`Test ${formatTashkent(a.opensAt!)} da ochiladi`, 409);
  }
  if (state === "closed") throw new HttpError("Test yopilgan", 409);

  await prisma.assignmentSheet.updateMany({
    where: { id: sheet.id, startedAt: null, checkedAt: null },
    data: { startedAt: new Date(), answers: padAnswers([], a.questionIds.length) },
  });
}

export async function saveAnswer(sheetId: string, accountId: string, index: number, choice: string) {
  // sheetForAccount already graded the sheet if its time is up, so a late
  // click lands on a checked sheet below.
  const sheet = await sheetForAccount(sheetId, accountId);
  requireOnline(sheet);
  if (!sheet.startedAt) throw new HttpError("Avval testni boshlang", 409);
  if (sheet.checkedAt) {
    throw new HttpError("Test topshirilgan — javobni o'zgartirib bo'lmaydi", 409);
  }
  if (!Number.isInteger(index) || index < 0 || index >= sheet.assignment.questionIds.length) {
    throw new HttpError("Savol raqami noto'g'ri", 400);
  }
  if (!VALID_CHOICES.has(choice)) throw new HttpError("Javob noto'g'ri", 400);

  // One array element, not the whole array: two quick taps on different
  // questions can't overwrite each other.
  const updated = await prisma.$executeRaw`
    UPDATE "AssignmentSheet" SET "answers"[${index + 1}::int] = ${choice}
    WHERE "id" = ${sheet.id} AND "checkedAt" IS NULL`;
  if (updated === 0) {
    throw new HttpError("Test topshirilgan — javobni o'zgartirib bo'lmaydi", 409);
  }
}

// `provided` is the client's own copy of the answers: an autosave that failed
// on a weak connection still counts. Past the deadline sheetForAccount has
// already graded the sheet from what was saved in time, so late copies can't
// change anything.
export async function submitAttempt(
  sheetId: string,
  accountId: string,
  provided: Record<string, string> = {},
) {
  const sheet = await sheetForAccount(sheetId, accountId);
  requireOnline(sheet);
  if (sheet.checkedAt) return; // already submitted — by a double tap or the timer
  if (!sheet.startedAt) throw new HttpError("Avval testni boshlang", 409);

  const a = sheet.assignment;
  const answers = padAnswers(sheet.answers, a.questionIds.length);
  for (const [key, choice] of Object.entries(provided)) {
    const i = Number(key);
    if (Number.isInteger(i) && i >= 0 && i < answers.length && VALID_CHOICES.has(choice)) {
      answers[i] = choice;
    }
  }

  const now = new Date();
  const deadline = attemptDeadline(a, sheet.startedAt);
  await prisma.assignmentSheet.updateMany({
    where: { id: sheet.id, checkedAt: null },
    data: {
      answers,
      ...gradeAnswers(answers, a.answerKey),
      checkedAt: deadline && now > deadline ? deadline : now,
    },
  });
}

export async function attemptQuestions(sheet: AccountSheet): Promise<RunnerQuestion[]> {
  const a = sheet.assignment;
  const questions = await prisma.question.findMany({
    where: { id: { in: a.questionIds } },
    select: { id: true, text: true, imageUrl: true, correctAnswer: true, wrongAnswers: true },
  });
  const byId = new Map(questions.map((q) => [q.id, q]));

  return questionOrder(sheet.id, a.questionIds.length, a.shuffle).map((index) => {
    const qid = a.questionIds[index];
    const q = byId.get(qid);
    if (!q) {
      // Deleted from the bank after assigning. The frozen key still grades
      // it, so the student can still pick a letter.
      return {
        index,
        text: "Bu savol bazadan o'chirilgan — javobni harf bo'yicha belgilang.",
        imageUrl: null,
        options: LETTERS.slice(0, MAX_CHOICES).map((letter) => ({ value: letter, text: letter })),
      };
    }
    const texts = canonicalOptions(a.testId, q);
    return {
      index,
      text: q.text,
      imageUrl: q.imageUrl,
      options: optionOrder(sheet.id, qid, texts.length, a.shuffle).map((ci) => ({
        value: LETTERS[ci],
        text: texts[ci],
      })),
    };
  });
}
