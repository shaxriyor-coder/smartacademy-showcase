// End-to-end check of Telegram notifications against the real database, with
// a fake Telegram (nothing is sent): new online test -> 24h reminder -> result
// -> re-checked result -> teacher's summary; dedupe, an account that blocked
// the bot, and /stop. See docs/DECISIONS.md #22.
//
//   npx tsx scripts/e2e-notifications.ts     # creates its own data, then deletes it
import "dotenv/config";
import { randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";
import { prisma } from "../src/lib/prisma";
import { createAssignment, resetSheetResult } from "../src/lib/assignments";
import { generateLinkCode } from "../src/lib/link-code";
import { deliverNotifications, sweepNotifications, type Sender } from "../src/lib/notifications";
import { startAttempt, submitAttempt } from "../src/lib/online";

const HOUR = 3_600_000;
const later = (from: Date, hours: number) => new Date(from.getTime() + hours * HOUR);

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERT: ${message}`);
}

async function main() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const passwordHash = await bcrypt.hash(randomBytes(24).toString("hex"), 10);
  const teacherChat = `e2e-teacher-${stamp}`;
  const teacher = await prisma.user.create({
    data: {
      name: `E2E O'qituvchi ${stamp}`,
      email: `e2e-notify-${stamp}@e2e.local`,
      passwordHash,
      role: "TEACHER",
      telegramChatId: teacherChat,
    },
  });
  const subject = await prisma.subject.create({
    data: { name: `E2E Xabarlar ${stamp}`, difficultyLevels: { create: [{ name: "O'rta", order: 1 }] } },
    include: { difficultyLevels: true },
  });
  const questions = [];
  for (let i = 0; i < 3; i++) {
    questions.push(
      await prisma.question.create({
        data: {
          subjectId: subject.id,
          text: `Xabarlar sinovi ${i + 1}-savol`,
          correctAnswer: "1",
          wrongAnswers: ["2", "3", "4", "5"],
          difficultyId: subject.difficultyLevels[0].id,
          focus: "ABITURIENT",
          createdById: teacher.id,
        },
      }),
    );
  }
  const test = await prisma.test.create({
    data: { title: `E2E xabarlar testi ${stamp}`, subjectId: subject.id, createdById: teacher.id, questionIds: questions.map((q) => q.id) },
  });
  const classroom = await prisma.classroom.create({ data: { name: `E2E xabarlar ${stamp}`, teacherId: teacher.id } });
  const parent = await prisma.telegramAccount.create({
    data: { id: `e2e-parent-${stamp}`, firstName: "Ota", lastLoginAt: new Date() },
  });
  const blocker = await prisma.telegramAccount.create({
    data: { id: `e2e-blocked-${stamp}`, firstName: "Blok", lastLoginAt: new Date() },
  });
  const chats = [parent.id, blocker.id, teacherChat];

  const sent: { chatId: string; text: string }[] = [];
  const fakeTelegram: Sender = async (chatId, text) => {
    if (chatId === blocker.id) return { ok: false, status: 403, description: "Forbidden: bot was blocked by the user" };
    sent.push({ chatId, text });
    return { ok: true };
  };
  // Rows are created at the real time; a simulated "later" can't be earlier.
  const deliver = (at: Date) =>
    deliverNotifications(new Date(Math.max(Date.now(), at.getTime())), { send: fakeTelegram, chatIds: chats, pauseMs: 0 });
  const last = () => sent.at(-1)!;

  try {
    const ali = await prisma.student.create({
      data: {
        firstName: "Ali",
        lastName: "Sinov",
        linkCode: generateLinkCode(),
        createdById: teacher.id,
        memberships: { create: { classroomId: classroom.id } },
        telegramLinks: { create: [{ telegramAccountId: parent.id }, { telegramAccountId: blocker.id }] },
      },
    });
    // No Telegram at all: gets no messages, shows up in the summary.
    await prisma.student.create({
      data: {
        firstName: "Vali",
        lastName: "Sinov",
        linkCode: generateLinkCode(),
        createdById: teacher.id,
        memberships: { create: { classroomId: classroom.id } },
      },
    });

    const t0 = new Date();
    const assignment = await createAssignment({
      classroomId: classroom.id,
      testId: test.id,
      createdById: teacher.id,
      mode: "ONLINE",
      online: { opensAt: null, closesAt: later(t0, 26), timeLimitMinutes: null, shuffle: false, revealAnswers: "IMMEDIATELY" },
    });
    const scope = { assignmentIds: [assignment.id] };
    const sheet = await prisma.assignmentSheet.findFirstOrThrow({ where: { assignmentId: assignment.id, studentId: ali.id } });

    // 1. New test: queued for both of Ali's chats; the blocked one fails and
    //    the account is marked, so it gets nothing more.
    let q = await sweepNotifications(t0, scope);
    assert(q.newTests === 2, `yangi test 2 ta chatga navbatga qo'yiladi (${q.newTests})`);
    const d = await deliver(t0);
    assert(d.sent === 1 && d.skipped === 1, `1 ta yuborildi, 1 ta yetib bormadi (${d.sent}/${d.skipped})`);
    assert(last().chatId === parent.id && last().text.includes("yangi online test"), "ota-onaga yangi test xabari");
    const blocked = await prisma.telegramAccount.findUniqueOrThrow({ where: { id: blocker.id } });
    assert(blocked.botUnreachableAt, "botni bloklagan akkaunt belgilandi");
    q = await sweepNotifications(t0, scope);
    assert(q.newTests === 0, "test qayta e'lon qilinmaydi");

    // 2. 23 hours before closing: the 24h reminder, once, to the reachable parent.
    const t1 = later(t0, 3);
    q = await sweepNotifications(t1, scope);
    assert(q.reminders === 1, `24 soatlik eslatma 1 ta (${q.reminders})`);
    assert((await sweepNotifications(t1, scope)).reminders === 0, "eslatma takrorlanmaydi");
    await deliver(t1);
    assert(last().text.includes("bir kundan kam"), "eslatma matni");

    // 3. Ali takes the test: 2 of 3 right.
    const key = assignment.answerKey;
    await startAttempt(sheet.id, parent.id);
    await submitAttempt(sheet.id, parent.id, { "0": key[0], "1": key[1] });
    q = await sweepNotifications(t1, scope);
    assert(q.results === 1, `natija 1 ta chatga (${q.results})`);
    await deliver(t1);
    assert(last().text.includes("2/3 to'g'ri — 66.7%"), `natija matni: ${last().text}`);

    // 4. The teacher resets it and Ali retakes: a new result is news again.
    await resetSheetResult(sheet.id);
    await startAttempt(sheet.id, parent.id);
    await submitAttempt(sheet.id, parent.id, { "0": key[0], "1": key[1], "2": key[2] });
    q = await sweepNotifications(t1, scope);
    assert(q.results === 1, `qayta tekshirilgan natija yuboriladi (${q.results})`);
    await deliver(t1);
    assert(last().text.includes("3/3 to'g'ri — 100%"), `yangi natija matni: ${last().text}`);

    // 5. Half an hour before closing: Ali already submitted, Vali has no chat.
    q = await sweepNotifications(later(t0, 25.5), scope);
    assert(q.reminders === 0, `topshirganga eslatma yo'q (${q.reminders})`);

    // 6. Closed: one summary to the teacher, Vali missing.
    const t4 = later(t0, 26.1);
    q = await sweepNotifications(t4, scope);
    assert(q.summaries === 1, `o'qituvchiga xulosa (${q.summaries})`);
    await deliver(t4);
    assert(
      last().chatId === teacherChat && last().text.includes("Topshirdi: 1/2") && last().text.includes("Topshirmadi (1): Sinov Vali"),
      `xulosa matni: ${last().text}`,
    );
    assert((await sweepNotifications(t4, scope)).summaries === 0, "xulosa bir marta");

    // 7. After /stop the parent gets nothing about a new test.
    await prisma.telegramAccount.update({ where: { id: parent.id }, data: { notifyEnabled: false } });
    const second = await createAssignment({
      classroomId: classroom.id,
      testId: test.id,
      createdById: teacher.id,
      mode: "ONLINE",
      online: { opensAt: null, closesAt: later(new Date(), 5), timeLimitMinutes: null, shuffle: false, revealAnswers: "IMMEDIATELY" },
    });
    q = await sweepNotifications(new Date(), { assignmentIds: [second.id] });
    assert(q.newTests === 0, `/stop dan keyin xabar yo'q (${q.newTests})`);

    console.log(`NATIJA: HAMMASI TO'G'RI (${sent.length} ta xabar soxta Telegram'ga "yuborildi")`);
  } finally {
    await prisma.notification.deleteMany({ where: { chatId: { in: chats } } });
    await prisma.assignment.deleteMany({ where: { classroomId: classroom.id } }); // sheets cascade
    await prisma.classroom.delete({ where: { id: classroom.id } }); // memberships cascade
    await prisma.student.deleteMany({ where: { createdById: teacher.id } }); // links cascade
    await prisma.telegramAccount.deleteMany({ where: { id: { in: [parent.id, blocker.id] } } });
    await prisma.test.delete({ where: { id: test.id } });
    await prisma.question.deleteMany({ where: { id: { in: questions.map((q) => q.id) } } });
    await prisma.subject.delete({ where: { id: subject.id } });
    await prisma.user.delete({ where: { id: teacher.id } });
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
