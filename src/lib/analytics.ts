import { prisma } from "./prisma";
import { HttpError } from "./http-error";
import { finalizeIfExpired } from "./online";
import { revealAllowed, sheetStatus } from "./online-core";
import { studentDisplayName } from "./students";
import {
  CLASS_AVERAGE_MIN,
  computeClassroomAnalytics,
  computeStudentAnalytics,
  type AnalyticsSheet,
  type QuestionMeta,
} from "./analytics-core";

// Loads what src/lib/analytics-core.ts computes from.

// Class average per assignment, only where enough classmates were checked
// (CLASS_AVERAGE_MIN) — never individual scores.
export async function classAverages(assignmentIds: string[]): Promise<Map<string, number>> {
  if (assignmentIds.length === 0) return new Map();
  const groups = await prisma.assignmentSheet.groupBy({
    by: ["assignmentId"],
    where: { assignmentId: { in: assignmentIds }, checkedAt: { not: null } },
    _avg: { percentage: true },
    _count: { _all: true },
  });
  return new Map(
    groups
      .filter((g) => g._count._all >= CLASS_AVERAGE_MIN && g._avg.percentage != null)
      .map((g) => [g.assignmentId, Math.round(g._avg.percentage! * 10) / 10]),
  );
}

export async function questionMeta(questionIds: string[]): Promise<Map<string, QuestionMeta>> {
  if (questionIds.length === 0) return new Map();
  const questions = await prisma.question.findMany({
    where: { id: { in: [...new Set(questionIds)] } },
    select: {
      id: true,
      themes: { select: { id: true, name: true, subject: { select: { name: true } } } },
      subThemes: { select: { id: true, name: true, themeId: true } },
      difficulty: { select: { name: true, order: true } },
      skills: { select: { id: true, name: true } },
    },
  });
  return new Map(
    questions.map((q) => [
      q.id,
      {
        themes: q.themes.map((t) => ({ id: t.id, name: t.name, subjectName: t.subject.name })),
        subThemes: q.subThemes,
        difficulty: q.difficulty,
        skills: q.skills,
      },
    ]),
  );
}

// A student's full picture. With `accountId`, only if that Telegram account is
// linked to the student (404 otherwise, like sheetForAccount).
export async function loadStudentAnalytics(studentId: string, opts: { accountId?: string } = {}) {
  const student = await prisma.student.findFirst({
    where: {
      id: studentId,
      ...(opts.accountId
        ? { telegramLinks: { some: { telegramAccountId: opts.accountId } } }
        : {}),
    },
    include: {
      memberships: {
        where: { classroom: { archived: false } },
        include: { classroom: { select: { name: true } } },
      },
      sheets: {
        where: { assignment: { archived: false } },
        orderBy: { assignment: { createdAt: "desc" } },
        include: {
          assignment: {
            select: {
              title: true,
              subjectName: true,
              createdAt: true,
              mode: true,
              opensAt: true,
              closesAt: true,
              timeLimitMinutes: true,
              revealAnswers: true,
              questionIds: true,
              answerKey: true,
              classroom: { select: { name: true } },
            },
          },
        },
      },
    },
  });
  if (!student) throw new HttpError("O'quvchi topilmadi", 404);

  const now = new Date();
  const sheets = await Promise.all(
    student.sheets.map(async (s) => {
      const sheet = await finalizeIfExpired(s.assignment, s, now);
      return { ...sheet, status: sheetStatus(s.assignment, sheet, now) };
    }),
  );

  const checked = sheets.filter((s) => s.checkedAt);
  const averages = await classAverages([...new Set(checked.map((s) => s.assignmentId))]);
  const detailAllowed = (s: (typeof sheets)[number]) =>
    revealAllowed(s.assignment.revealAnswers, s.assignment.closesAt, now);
  const meta = await questionMeta(checked.filter(detailAllowed).flatMap((s) => s.assignment.questionIds));

  const analyticsSheets: AnalyticsSheet[] = sheets.map((s) => ({
    id: s.id,
    assignmentId: s.assignmentId,
    status: s.status,
    mode: s.assignment.mode,
    title: s.assignment.title,
    subjectName: s.assignment.subjectName,
    classroomName: s.assignment.classroom.name,
    startedAt: s.startedAt,
    checkedAt: s.checkedAt,
    percentage: s.percentage,
    correct: s.correct,
    total: s.total,
    answers: s.answers,
    answerKey: s.assignment.answerKey,
    questionIds: s.assignment.questionIds,
    detailAllowed: detailAllowed(s),
    classAverage: averages.get(s.assignmentId) ?? null,
  }));

  return { student, sheets, analytics: computeStudentAnalytics(analyticsSheets, meta) };
}

// The whole classroom, for its teacher: every live assignment and its sheets.
export async function loadClassroomAnalytics(classroomId: string) {
  const classroom = await prisma.classroom.findUnique({
    where: { id: classroomId },
    select: {
      members: { select: { student: { select: { id: true, firstName: true, lastName: true } } } },
      assignments: {
        where: { archived: false },
        select: {
          id: true,
          title: true,
          subjectName: true,
          mode: true,
          createdAt: true,
          opensAt: true,
          closesAt: true,
          timeLimitMinutes: true,
          questionIds: true,
          answerKey: true,
          sheets: {
            select: {
              id: true,
              studentId: true,
              startedAt: true,
              checkedAt: true,
              percentage: true,
              correct: true,
              total: true,
              answers: true,
            },
          },
        },
      },
    },
  });
  if (!classroom) throw new HttpError("Guruh topilmadi", 404);

  const now = new Date();
  const assignments = await Promise.all(
    classroom.assignments.map(async (a) => ({
      ...a,
      sheets: await Promise.all(
        a.sheets.map(async (s) => {
          const sheet = await finalizeIfExpired(a, s, now);
          return { ...sheet, status: sheetStatus(a, sheet, now) };
        }),
      ),
    })),
  );
  const meta = await questionMeta(
    assignments.filter((a) => a.sheets.some((s) => s.checkedAt)).flatMap((a) => a.questionIds),
  );

  return computeClassroomAnalytics(
    classroom.members.map((m) => ({ id: m.student.id, name: studentDisplayName(m.student) })),
    assignments,
    meta,
  );
}
