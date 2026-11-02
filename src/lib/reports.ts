import { prisma } from "./prisma";
import { classAverages, questionMeta } from "./analytics";
import { REACHABLE } from "./notifications";
import { appLinks } from "./notifications-core";
import { revealAllowed, sheetStatus } from "./online-core";
import { studentDisplayName } from "./students";
import { duePeriods, reportMessage, studentReport, type ReportPeriod, type ReportSheet } from "./reports-core";

// Queues weekly and monthly family reports (docs/DECISIONS.md #24). The
// notification loop delivers them like every other message; a unique dedupe
// key per period, student and chat keeps a report from going out twice.

const INSTALLED = "installed";

// e2e scripts limit a sweep to their own students and choose `since` — and
// never mark a real period as done.
export type ReportScope = { studentIds?: string[]; since?: Date };

export async function sweepReports(now = new Date(), scope: ReportScope = {}) {
  // A row the migration adds: periods that ended before reports existed are skipped.
  const installed = await prisma.reportRun.findUnique({ where: { periodKey: INSTALLED } });
  const since = scope.since ?? installed?.createdAt ?? now;
  const counts = { weekly: 0, monthly: 0 };

  for (const period of duePeriods(now, since)) {
    if (!scope.studentIds && (await prisma.reportRun.findUnique({ where: { periodKey: period.key } }))) continue;
    counts[period.kind] += await queuePeriod(period, now, scope.studentIds);
    if (!scope.studentIds) {
      await prisma.reportRun.createMany({ data: [{ periodKey: period.key }], skipDuplicates: true });
    }
  }
  return counts;
}

async function queuePeriod(period: ReportPeriod, now: Date, studentIds?: string[]) {
  const links = await prisma.studentTelegramLink.findMany({
    where: { telegramAccount: REACHABLE, ...(studentIds ? { studentId: { in: studentIds } } : {}) },
    select: {
      studentId: true,
      telegramAccountId: true,
      student: { select: { firstName: true, lastName: true } },
    },
  });
  const byStudent = new Map<string, typeof links>();
  for (const l of links) byStudent.set(l.studentId, [...(byStudent.get(l.studentId) ?? []), l]);

  // The period before this one too, for the change.
  const from = new Date(period.start.getTime() - (period.end.getTime() - period.start.getTime()));
  const link = appLinks(process.env.WEBAPP_URL);
  let queued = 0;

  for (const [studentId, chats] of byStudent) {
    const rows = await prisma.assignmentSheet.findMany({
      where: {
        studentId,
        assignment: { archived: false },
        OR: [
          { checkedAt: { gt: from, lte: period.end } },
          { checkedAt: null, assignment: { mode: "ONLINE", closesAt: { gt: period.start, lte: period.end } } },
        ],
      },
      select: {
        id: true,
        assignmentId: true,
        startedAt: true,
        checkedAt: true,
        percentage: true,
        correct: true,
        total: true,
        answers: true,
        assignment: {
          select: {
            title: true,
            subjectName: true,
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
    });
    if (rows.length === 0) continue;

    const averages = await classAverages([...new Set(rows.filter((r) => r.checkedAt).map((r) => r.assignmentId))]);
    const sheets: ReportSheet[] = rows.map((r) => ({
      id: r.id,
      assignmentId: r.assignmentId,
      status: sheetStatus(r.assignment, r, now),
      mode: r.assignment.mode,
      title: r.assignment.title,
      subjectName: r.assignment.subjectName,
      classroomName: r.assignment.classroom.name,
      startedAt: r.startedAt,
      checkedAt: r.checkedAt,
      percentage: r.percentage,
      correct: r.correct,
      total: r.total,
      answers: r.answers,
      answerKey: r.assignment.answerKey,
      questionIds: r.assignment.questionIds,
      // Families see topics only where the answers may be shown.
      detailAllowed: revealAllowed(r.assignment.revealAnswers, r.assignment.closesAt, now),
      classAverage: averages.get(r.assignmentId) ?? null,
      closesAt: r.assignment.closesAt,
    }));
    const meta = await questionMeta(
      sheets.filter((s) => s.detailAllowed && s.checkedAt && s.checkedAt > period.start).flatMap((s) => s.questionIds),
    );
    const report = studentReport(sheets, period, meta);
    if (!report) continue;

    const message = reportMessage(
      period,
      studentDisplayName(chats[0].student),
      report,
      link?.miniApp(`/classroom-home/students/${studentId}`) ?? null,
    );
    const { count } = await prisma.notification.createMany({
      data: chats.map((c) => ({
        chatId: c.telegramAccountId,
        kind: `${period.kind}_report`,
        dedupeKey: `report:${period.key}:${studentId}:${c.telegramAccountId}`,
        text: message.text,
        buttonText: message.button?.text ?? null,
        buttonUrl: message.button?.url ?? null,
        buttonWebApp: message.button?.webApp ?? false,
      })),
      skipDuplicates: true,
    });
    queued += count;
  }
  return queued;
}
