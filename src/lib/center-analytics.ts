import { prisma } from "./prisma";
import { ALLOWED_OPTION_COUNTS } from "./answer-key";
import { questionMeta } from "./analytics";
import { finalizeIfExpired } from "./online";
import { sheetStatus } from "./online-core";
import { studentDisplayName } from "./students";
import {
  computeCenterAnalytics,
  computeQuestionBankAnalytics,
  computeTeacherAnalytics,
  type CenterSheet,
} from "./center-analytics-core";

// Loads what src/lib/center-analytics-core.ts computes from. Admin-only
// (docs/DECISIONS.md #20).

// Every live classroom with its live assignments and their sheets. Expired
// online attempts are finalized on the way, as on every other results view.
async function loadClassrooms(now: Date) {
  const classrooms = await prisma.classroom.findMany({
    where: { archived: false },
    select: {
      id: true,
      teacherId: true,
      teacher: { select: { name: true } },
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

  const sheets = await Promise.all(
    classrooms.flatMap((c) =>
      c.assignments.flatMap((a) =>
        a.sheets.map(async (raw): Promise<CenterSheet> => {
          const s = await finalizeIfExpired(a, raw, now);
          return {
            id: s.id,
            studentId: s.studentId,
            teacherId: c.teacherId,
            assignmentId: a.id,
            mode: a.mode,
            title: a.title,
            subjectName: a.subjectName,
            status: sheetStatus(a, s, now),
            startedAt: s.startedAt,
            checkedAt: s.checkedAt,
            percentage: s.percentage,
            correct: s.correct,
            total: s.total,
            answers: s.answers,
            answerKey: a.answerKey,
            questionIds: a.questionIds,
          };
        }),
      ),
    ),
  );
  return { classrooms, sheets };
}

export async function loadCenterAnalytics(now = new Date()) {
  const { classrooms, sheets } = await loadClassrooms(now);

  const students = new Map<string, { id: string; name: string; teachers: Set<string> }>();
  for (const c of classrooms) {
    for (const { student } of c.members) {
      const entry = students.get(student.id) ?? {
        id: student.id,
        name: studentDisplayName(student),
        teachers: new Set<string>(),
      };
      entry.teachers.add(c.teacher.name);
      students.set(student.id, entry);
    }
  }
  const meta = await questionMeta([
    ...new Set(sheets.filter((s) => s.checkedAt).flatMap((s) => s.questionIds)),
  ]);

  return computeCenterAnalytics(
    [...students.values()].map((s) => ({ id: s.id, name: s.name, teachers: [...s.teachers].sort() })),
    sheets,
    meta,
    now,
  );
}

export async function loadTeacherAnalytics(now = new Date()) {
  const [{ classrooms, sheets }, staff, questions, tests] = await Promise.all([
    loadClassrooms(now),
    prisma.user.findMany({ select: { id: true, name: true, role: true, canTeach: true } }),
    prisma.question.findMany({ select: { createdById: true, createdAt: true } }),
    prisma.test.findMany({ select: { createdById: true, createdAt: true } }),
  ]);

  return computeTeacherAnalytics(
    {
      staff,
      classrooms: classrooms.map((c) => ({
        id: c.id,
        teacherId: c.teacherId,
        studentIds: c.members.map((m) => m.student.id),
      })),
      assignments: classrooms.flatMap((c) =>
        c.assignments.map((a) => ({ id: a.id, teacherId: c.teacherId, mode: a.mode, createdAt: a.createdAt })),
      ),
      sheets,
      questions,
      tests,
    },
    now,
  );
}

export async function loadQuestionBankAnalytics(now = new Date()) {
  const [questions, themes, tests, assignments] = await Promise.all([
    prisma.question.findMany({
      select: {
        id: true,
        text: true,
        createdAt: true,
        wrongAnswers: true,
        subject: { select: { name: true } },
        themes: { select: { id: true, name: true } },
        difficulty: { select: { name: true, order: true } },
        createdBy: { select: { id: true, name: true } },
        _count: { select: { subThemes: true, skills: true } },
      },
    }),
    prisma.theme.findMany({ select: { id: true, name: true, subject: { select: { name: true } } } }),
    prisma.test.findMany({ select: { questionIds: true } }),
    // Every checked result, archived assignments included: how hard a
    // question is shouldn't change because a teacher tidied up a group.
    prisma.assignment.findMany({
      select: {
        id: true,
        title: true,
        questionIds: true,
        answerKey: true,
        sheets: { where: { checkedAt: { not: null } }, select: { answers: true } },
      },
    }),
  ]);

  return computeQuestionBankAnalytics(
    {
      questions: questions.map((q) => ({
        id: q.id,
        text: q.text,
        subjectName: q.subject.name,
        themeIds: q.themes.map((t) => t.id),
        themeNames: q.themes.map((t) => t.name),
        subThemeCount: q._count.subThemes,
        skillCount: q._count.skills,
        difficulty: q.difficulty,
        optionCount: q.wrongAnswers.length + 1,
        createdAt: q.createdAt,
        author: q.createdBy,
      })),
      themes: themes.map((t) => ({ id: t.id, name: t.name, subjectName: t.subject.name })),
      tests,
      assignments: assignments.map((a) => ({
        id: a.id,
        title: a.title,
        questionIds: a.questionIds,
        answerKey: a.answerKey,
        answers: a.sheets.map((s) => s.answers),
      })),
      choiceCounts: ALLOWED_OPTION_COUNTS,
    },
    now,
  );
}
