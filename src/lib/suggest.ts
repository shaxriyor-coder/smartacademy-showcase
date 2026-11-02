import { prisma } from "./prisma";
import { ALLOWED_OPTION_COUNTS } from "./answer-key";
import { HttpError } from "./http-error";
import { studentDisplayName } from "./students";
import { OTHER_THEME, suggestQuestions } from "./suggest-core";

// Loads what src/lib/suggest-core.ts proposes from: the target's results and
// the questions they've had — in THIS teacher's classrooms only
// (docs/DECISIONS.md #20) — and the subject's whole bank.

export async function loadSuggestion(opts: {
  teacherId: string;
  classroomId: string;
  studentId: string | null;
  subjectId: string;
  count: number;
  seed: string;
}) {
  const classroom = await prisma.classroom.findFirst({
    where: { id: opts.classroomId, teacherId: opts.teacherId, archived: false },
    select: { name: true, members: { select: { student: { select: { id: true, firstName: true, lastName: true } } } } },
  });
  if (!classroom) throw new HttpError("Guruh topilmadi", 404);
  const members = classroom.members.map((m) => m.student);
  const targets = opts.studentId ? members.filter((s) => s.id === opts.studentId) : members;
  if (opts.studentId && targets.length === 0) throw new HttpError("Bu o'quvchi guruhda yo'q", 404);
  if (targets.length === 0) throw new HttpError("Guruhda hali o'quvchi yo'q", 409);

  const subject = await prisma.subject.findUnique({
    where: { id: opts.subjectId },
    select: { id: true, name: true, themes: { select: { id: true, name: true } } },
  });
  if (!subject) throw new HttpError("Fan topilmadi", 404);

  const sheets = await prisma.assignmentSheet.findMany({
    where: {
      studentId: { in: targets.map((s) => s.id) },
      assignment: { archived: false, classroom: { teacherId: opts.teacherId } },
    },
    select: {
      studentId: true,
      checkedAt: true,
      answers: true,
      assignment: { select: { questionIds: true, answerKey: true } },
    },
  });

  // Who has had which question — handed out counts, answered or not.
  const seenBy = new Map<string, Set<string>>();
  for (const s of sheets) {
    for (const qid of s.assignment.questionIds) seenBy.set(qid, (seenBy.get(qid) ?? new Set()).add(s.studentId));
  }
  const tagged = await prisma.question.findMany({
    where: { id: { in: [...seenBy.keys()] } },
    select: { id: true, themes: { select: { id: true } } },
  });
  const themesOf = new Map(tagged.map((q) => [q.id, q.themes.map((t) => t.id)]));
  const stats = new Map<string, { correct: number; total: number }>();
  for (const s of sheets) {
    if (!s.checkedAt) continue;
    s.assignment.questionIds.forEach((qid, i) => {
      const ok = s.answers[i] === s.assignment.answerKey[i];
      for (const themeId of themesOf.get(qid) ?? []) {
        const t = stats.get(themeId) ?? { correct: 0, total: 0 };
        t.total += 1;
        if (ok) t.correct += 1;
        stats.set(themeId, t);
      }
    });
  }

  const bank = await prisma.question.findMany({
    where: { subjectId: subject.id },
    select: {
      id: true,
      text: true,
      wrongAnswers: true,
      themes: { select: { id: true, name: true } },
      difficulty: { select: { name: true, order: true } },
    },
  });
  const result = suggestQuestions({
    themes: subject.themes,
    stats,
    candidates: bank.map((q) => ({
      id: q.id,
      themeIds: q.themes.map((t) => t.id),
      difficultyOrder: q.difficulty.order,
      optionCount: q.wrongAnswers.length + 1,
    })),
    seen: new Map([...seenBy].map(([id, who]) => [id, who.size])),
    count: opts.count,
    choiceCounts: ALLOWED_OPTION_COUNTS,
    seed: opts.seed,
  });

  const byId = new Map(bank.map((q) => [q.id, q]));
  const view = (id: string) => {
    const q = byId.get(id)!;
    return { id, text: q.text, difficulty: q.difficulty.name, themes: q.themes.map((t) => t.name), seen: seenBy.get(id)?.size ?? 0 };
  };

  return {
    target: {
      name: opts.studentId ? studentDisplayName(targets[0]) : classroom.name,
      students: targets.length,
      isGroup: !opts.studentId,
    },
    subject: { id: subject.id, name: subject.name },
    plan: result.plan,
    questions: result.questions.map((q) => ({ ...view(q.id), themeKey: q.themeKey, standing: q.standing, rate: q.rate })),
    alternates: Object.fromEntries(Object.entries(result.alternates).map(([key, ids]) => [key, ids.map(view)])),
    shortfall: result.shortfall,
    otherTheme: OTHER_THEME,
  };
}

export type LoadedSuggestion = Awaited<ReturnType<typeof loadSuggestion>>;
