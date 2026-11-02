import type { Prisma } from "@prisma/client";
import { prisma } from "./prisma";
import { mean } from "./analytics-core";
import { classAverages } from "./analytics";
import { finalizeIfExpired } from "./online";
import { SAVE_GRACE_MS } from "./online-core";
import { studentDisplayName } from "./students";
import { sendTelegram } from "./telegram";
import {
  MAX_ATTEMPTS,
  REMINDER_HORIZON_MS,
  appLinks,
  classifyFailure,
  dueReminder,
  newTestMessage,
  reminderMessage,
  resultMessage,
  retryAt,
  teacherSummaryMessage,
  type Button,
  type Message,
  type NotificationKind,
  type SendOutcome,
} from "./notifications-core";

// The Telegram notification queue (docs/DECISIONS.md #22). The bot process
// (scripts/telegram-bot.ts) calls sweepNotifications() and then
// deliverNotifications() every cycle. The grading code doesn't know about
// notifications: the sweep finds what changed from marks on the rows
// (resultNotifiedAt, announcedAt, summarySentAt), and a unique dedupeKey keeps
// one event from reaching one chat twice.

const BATCH = 200;

// e2e scripts limit a sweep to their own assignments.
export type SweepScope = { assignmentIds?: string[] };

type Draft = {
  chatId: string;
  kind: NotificationKind;
  dedupeKey: string;
  message: Message;
  sheetId?: string;
  assignmentId?: string;
};

async function enqueue(drafts: Draft[]) {
  if (drafts.length === 0) return 0;
  const { count } = await prisma.notification.createMany({
    data: drafts.map((d) => ({
      chatId: d.chatId,
      kind: d.kind,
      dedupeKey: d.dedupeKey,
      text: d.message.text,
      buttonText: d.message.button?.text ?? null,
      buttonUrl: d.message.button?.url ?? null,
      buttonWebApp: d.message.button?.webApp ?? false,
      sheetId: d.sheetId ?? null,
      assignmentId: d.assignmentId ?? null,
    })),
    skipDuplicates: true,
  });
  return count;
}

// Accounts that want messages and that the bot can reach.
export const REACHABLE = { notifyEnabled: true, botUnreachableAt: null } satisfies Prisma.TelegramAccountWhereInput;

const SHEET_INCLUDE = {
  student: {
    select: {
      firstName: true,
      lastName: true,
      telegramLinks: { where: { telegramAccount: REACHABLE }, select: { telegramAccountId: true } },
    },
  },
  assignment: {
    select: {
      title: true,
      opensAt: true,
      closesAt: true,
      timeLimitMinutes: true,
      questionIds: true,
      classroom: { select: { name: true } },
    },
  },
} satisfies Prisma.AssignmentSheetInclude;

export async function sweepNotifications(now = new Date(), scope: SweepScope = {}) {
  const links = appLinks(process.env.WEBAPP_URL);
  const live = {
    archived: false,
    classroom: { archived: false },
    ...(scope.assignmentIds ? { id: { in: scope.assignmentIds } } : {}),
  } satisfies Prisma.AssignmentWhereInput;
  const counts = { results: 0, newTests: 0, reminders: 0, summaries: 0 };

  // 1. Online attempts whose time ran out with nobody looking: grade them now,
  //    so neither the result nor the teacher's summary waits for a page view.
  const running = await prisma.assignmentSheet.findMany({
    where: { startedAt: { not: null }, checkedAt: null, assignment: { ...live, mode: "ONLINE" } },
    select: {
      id: true,
      startedAt: true,
      checkedAt: true,
      answers: true,
      correct: true,
      total: true,
      percentage: true,
      assignment: {
        select: { mode: true, opensAt: true, closesAt: true, timeLimitMinutes: true, questionIds: true, answerKey: true },
      },
    },
    take: BATCH,
  });
  for (const s of running) await finalizeIfExpired(s.assignment, s, now);

  // 2. Results graded since the last sweep, offline and online alike.
  const graded = await prisma.assignmentSheet.findMany({
    where: { checkedAt: { not: null }, resultNotifiedAt: null, assignment: live },
    include: SHEET_INCLUDE,
    orderBy: { checkedAt: "asc" },
    take: BATCH,
  });
  const averages = await classAverages([...new Set(graded.map((s) => s.assignmentId))]);
  counts.results = await enqueue(
    graded.flatMap((s) =>
      s.student.telegramLinks.map((l) => ({
        chatId: l.telegramAccountId,
        kind: "result" as const,
        sheetId: s.id,
        // A reset clears checkedAt and the mark: a re-checked result is a new event.
        dedupeKey: `result:${s.id}:${s.checkedAt!.getTime()}:${l.telegramAccountId}`,
        message: resultMessage(
          {
            studentName: studentDisplayName(s.student),
            title: s.assignment.title,
            classroomName: s.assignment.classroom.name,
            correct: s.correct ?? 0,
            total: s.total ?? 0,
            percentage: s.percentage ?? 0,
            classAverage: averages.get(s.assignmentId) ?? null,
          },
          links?.miniApp(`/classroom-home/results/${s.id}`) ?? null,
        ),
      })),
    ),
  );
  for (const s of graded) {
    // Only if still the same result — it may have been reset in between.
    await prisma.assignmentSheet.updateMany({
      where: { id: s.id, checkedAt: s.checkedAt, resultNotifiedAt: null },
      data: { resultNotifiedAt: now },
    });
  }

  // 3. New online tests, per sheet: a student added to the group later is told too.
  const fresh = await prisma.assignmentSheet.findMany({
    where: { announcedAt: null, checkedAt: null, assignment: { ...live, mode: "ONLINE" } },
    include: SHEET_INCLUDE,
    take: BATCH,
  });
  counts.newTests = await enqueue(
    fresh
      .filter((s) => !(s.assignment.closesAt && s.assignment.closesAt <= now))
      .flatMap((s) =>
        s.student.telegramLinks.map((l) => ({
          chatId: l.telegramAccountId,
          kind: "new_test" as const,
          sheetId: s.id,
          dedupeKey: `new_test:${s.id}:${l.telegramAccountId}`,
          message: newTestMessage(
            {
              studentName: studentDisplayName(s.student),
              title: s.assignment.title,
              classroomName: s.assignment.classroom.name,
              questionCount: s.assignment.questionIds.length,
              opensAt: s.assignment.opensAt,
              closesAt: s.assignment.closesAt,
              timeLimitMinutes: s.assignment.timeLimitMinutes,
            },
            now,
            links?.miniApp(`/classroom-home/tests/${s.id}`) ?? null,
          ),
        })),
      ),
  );
  if (fresh.length > 0) {
    await prisma.assignmentSheet.updateMany({
      where: { id: { in: fresh.map((s) => s.id) }, announcedAt: null },
      data: { announcedAt: now },
    });
  }

  // 4. Reminders to students who haven't started a test that closes soon.
  const notStarted = await prisma.assignmentSheet.findMany({
    where: {
      startedAt: null,
      checkedAt: null,
      announcedAt: { not: null },
      assignment: {
        ...live,
        mode: "ONLINE",
        closesAt: { gt: now, lte: new Date(now.getTime() + REMINDER_HORIZON_MS) },
      },
    },
    include: SHEET_INCLUDE,
  });
  counts.reminders = await enqueue(
    notStarted.flatMap((s) => {
      const closesAt = s.assignment.closesAt!;
      const reminder = dueReminder(s.assignment, s.announcedAt!, now);
      if (!reminder) return [];
      return s.student.telegramLinks.map((l) => ({
        chatId: l.telegramAccountId,
        kind: reminder.kind,
        sheetId: s.id,
        // closesAt in the key: an extended deadline reminds again.
        dedupeKey: `${reminder.kind}:${s.id}:${closesAt.getTime()}:${l.telegramAccountId}`,
        message: reminderMessage(
          reminder,
          {
            studentName: studentDisplayName(s.student),
            title: s.assignment.title,
            classroomName: s.assignment.classroom.name,
            closesAt,
          },
          links?.miniApp(`/classroom-home/tests/${s.id}`) ?? null,
        ),
      }));
    }),
  );

  // 5. A summary to the teacher once an online test has closed. A minute's
  //    margin lets the last attempts land; unfinished ones wait for step 1.
  const closed = await prisma.assignment.findMany({
    where: {
      ...live,
      mode: "ONLINE",
      summarySentAt: null,
      closesAt: { lte: new Date(now.getTime() - SAVE_GRACE_MS - 60_000) },
    },
    select: {
      id: true,
      title: true,
      classroomId: true,
      closesAt: true,
      classroom: { select: { name: true, teacher: { select: { telegramChatId: true } } } },
      sheets: {
        select: {
          startedAt: true,
          checkedAt: true,
          percentage: true,
          student: { select: { firstName: true, lastName: true } },
        },
      },
    },
    take: 50,
  });
  for (const a of closed) {
    if (a.sheets.some((s) => s.startedAt && !s.checkedAt)) continue;
    const chatId = a.classroom.teacher.telegramChatId;
    if (chatId) {
      const checked = a.sheets.filter((s) => s.checkedAt && s.percentage != null);
      counts.summaries += await enqueue([
        {
          chatId,
          kind: "teacher_summary",
          assignmentId: a.id,
          dedupeKey: `teacher_summary:${a.id}:${a.closesAt!.getTime()}:${chatId}`,
          message: teacherSummaryMessage(
            {
              title: a.title,
              classroomName: a.classroom.name,
              checked: checked.length,
              total: a.sheets.length,
              average: mean(checked.map((s) => s.percentage!)),
              missing: a.sheets
                .filter((s) => !s.checkedAt)
                .map((s) => studentDisplayName(s.student))
                .sort((x, y) => x.localeCompare(y)),
            },
            links?.site(`/classrooms/${a.classroomId}/assignments/${a.id}`) ?? null,
          ),
        },
      ]);
    }
    // Marked even without a Telegram ID: linking one later shouldn't replay old tests.
    await prisma.assignment.updateMany({ where: { id: a.id, summarySentAt: null }, data: { summarySentAt: now } });
  }

  return counts;
}

export type Sender = (chatId: string, text: string, button: Button | null) => Promise<SendOutcome>;

export async function deliverNotifications(
  now = new Date(),
  opts: { send?: Sender; chatIds?: string[]; limit?: number; pauseMs?: number } = {},
) {
  const send = opts.send ?? sendTelegram;
  const pauseMs = opts.pauseMs ?? 40; // well under Telegram's ~30 messages a second
  const due = await prisma.notification.findMany({
    where: {
      status: "PENDING",
      sendAfter: { lte: now },
      ...(opts.chatIds ? { chatId: { in: opts.chatIds } } : {}),
    },
    orderBy: { createdAt: "asc" },
    take: opts.limit ?? 100,
  });

  const result = { sent: 0, skipped: 0, failed: 0, retrying: 0, pausedUntil: null as Date | null };
  const unreachable = new Set<string>();

  for (const n of due) {
    if (unreachable.has(n.chatId)) continue;
    const outcome = await send(
      n.chatId,
      n.text,
      n.buttonUrl && n.buttonText ? { text: n.buttonText, url: n.buttonUrl, webApp: n.buttonWebApp } : null,
    );
    if (pauseMs) await new Promise((r) => setTimeout(r, pauseMs));

    if (outcome.ok) {
      await prisma.notification.update({ where: { id: n.id }, data: { status: "SENT", sentAt: new Date(), attempts: { increment: 1 } } });
      result.sent += 1;
      continue;
    }

    const failure = classifyFailure(outcome);
    if (failure === "rate_limited") {
      result.pausedUntil = new Date(now.getTime() + (outcome.retryAfter ?? 5) * 1000);
      break;
    }
    if (failure === "unreachable") {
      // Everything queued for this chat would fail the same way. The account
      // stops getting new messages until it writes to the bot again.
      unreachable.add(n.chatId);
      const skipped = await prisma.notification.updateMany({
        where: { chatId: n.chatId, status: "PENDING" },
        data: { status: "SKIPPED", lastError: outcome.description },
      });
      await prisma.telegramAccount.updateMany({ where: { id: n.chatId }, data: { botUnreachableAt: now } });
      result.skipped += skipped.count;
      continue;
    }

    const attempts = n.attempts + 1;
    const giveUp = failure === "invalid" || attempts >= MAX_ATTEMPTS;
    await prisma.notification.update({
      where: { id: n.id },
      data: giveUp
        ? { status: "FAILED", attempts, lastError: outcome.description }
        : { attempts, lastError: outcome.description, sendAfter: retryAt(attempts, now) },
    });
    if (giveUp) result.failed += 1;
    else result.retrying += 1;
  }

  return result;
}
