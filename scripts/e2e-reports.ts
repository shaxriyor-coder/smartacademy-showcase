// End-to-end check of weekly and monthly family reports against the real
// database (nothing is sent): a parent with two children gets a report for
// each — one with the tests, the change against the previous week, a missed
// test and weak topics; the other, who only missed a test, says so. A second
// sweep adds nothing, and a scoped run never marks a real period as done.
// See docs/DECISIONS.md #24.
//
//   npx tsx scripts/e2e-reports.ts     # creates its own data, then deletes it
import "dotenv/config";
import { randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";
import { prisma } from "../src/lib/prisma";
import { createAssignment } from "../src/lib/assignments";
import { gradeAnswers } from "../src/lib/answer-key";
import { generateLinkCode } from "../src/lib/link-code";
import { sweepReports } from "../src/lib/reports";
import { latestMonthlyPeriod, latestWeeklyPeriod } from "../src/lib/reports-core";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERT: ${message}`);
}

async function main() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const passwordHash = await bcrypt.hash(randomBytes(24).toString("hex"), 10);
  const teacher = await prisma.user.create({
    data: { name: `E2E Hisobot ${stamp}`, email: `e2e-reports-${stamp}@e2e.local`, passwordHash, role: "TEACHER" },
  });
  const subject = await prisma.subject.create({
    data: {
      name: `E2E Hisobot ${stamp}`,
      themes: { create: [{ name: "Foizlar" }] },
      difficultyLevels: { create: [{ name: "O'rta", order: 1 }] },
    },
    include: { themes: true, difficultyLevels: true },
  });
  const questions = [];
  for (let i = 0; i < 3; i++) {
    questions.push(
      await prisma.question.create({
        data: {
          subjectId: subject.id,
          text: `Hisobot sinovi ${i + 1}-savol`,
          correctAnswer: "1",
          wrongAnswers: ["2", "3", "4", "5"],
          difficultyId: subject.difficultyLevels[0].id,
          focus: "ABITURIENT",
          createdById: teacher.id,
          themes: { connect: [{ id: subject.themes[0].id }] },
        },
      }),
    );
  }
  const test = await prisma.test.create({
    data: { title: `E2E hisobot testi ${stamp}`, subjectId: subject.id, createdById: teacher.id, questionIds: questions.map((q) => q.id) },
  });
  const classroom = await prisma.classroom.create({ data: { name: `E2E hisobot ${stamp}`, teacherId: teacher.id } });
  const parent = await prisma.telegramAccount.create({
    data: { id: `e2e-report-parent-${stamp}`, firstName: "Ota", lastLoginAt: new Date() },
  });
  const sent: string[] = [];

  try {
    const [ali, vali] = await Promise.all(
      ["Ali", "Vali"].map((firstName) =>
        prisma.student.create({
          data: {
            firstName,
            lastName: "Sinov",
            linkCode: generateLinkCode(),
            createdById: teacher.id,
            memberships: { create: { classroomId: classroom.id } },
            telegramLinks: { create: { telegramAccountId: parent.id } },
          },
        }),
      ),
    );

    const week = latestWeeklyPeriod(new Date());
    const at = new Date(week.end.getTime() + HOUR);
    // Checks a paper test for Ali with `right` of 3 correct at `checkedAt`.
    async function paperResult(title: string, right: number, checkedAt: Date) {
      const a = await createAssignment({ classroomId: classroom.id, testId: test.id, createdById: teacher.id, title });
      const answers = a.answerKey.map((k, i) => (i < right ? k : k === "A" ? "B" : "A"));
      await prisma.assignmentSheet.updateMany({
        where: { assignmentId: a.id, studentId: ali.id },
        // Marked as already announced: a running bot's sweep must not grab it.
        data: { answers, ...gradeAnswers(answers, a.answerKey), checkedAt, resultNotifiedAt: checkedAt },
      });
      return a;
    }
    await paperResult("Oldingi hafta", 1, new Date(week.start.getTime() - DAY)); // 33.3%
    await paperResult("Nazorat 1", 3, new Date(week.end.getTime() - 3 * DAY)); // 100%
    await paperResult("Nazorat 2", 0, new Date(week.end.getTime() - DAY)); // 0%
    // An online test Ali never opened, closed this week.
    const online = await createAssignment({
      classroomId: classroom.id,
      testId: test.id,
      createdById: teacher.id,
      title: "Online takrorlash",
      mode: "ONLINE",
      online: {
        opensAt: new Date(week.start.getTime() + DAY),
        closesAt: new Date(week.end.getTime() - 2 * DAY),
        timeLimitMinutes: null,
        shuffle: false,
        revealAnswers: "IMMEDIATELY",
      },
    });

    await prisma.assignmentSheet.updateMany({ where: { assignmentId: online.id }, data: { announcedAt: new Date() } });

    const runsBefore = await prisma.reportRun.count();
    const scope = { studentIds: [ali.id, vali.id], since: new Date(0) };
    const counts = await sweepReports(at, scope);
    assert(counts.weekly === 2, `haftalik hisobot ikkala farzandga (${counts.weekly})`);
    assert((await sweepReports(at, scope)).weekly === 0, "hisobot takrorlanmaydi");
    assert((await prisma.reportRun.count()) === runsBefore, "sinov haqiqiy davrni yopilgan deb belgilamaydi");

    // Read from the queue rather than delivering: a bot running meanwhile may send it first.
    sent.push(...(await prisma.notification.findMany({ where: { chatId: parent.id } })).map((n) => n.text));
    const report = sent.find((t) => t.startsWith("📅 Haftalik hisobot — Sinov Ali"));
    assert(report, `haftalik hisobot yuborildi: ${sent.join(" | ")}`);
    for (const piece of [
      week.label,
      "Topshirilgan testlar: 2 ta · o'rtacha 50% (▲ +16.7 oldingi haftaga nisbatan)",
      "• Nazorat 1 — 100%",
      "• Nazorat 2 — 0%",
      "Topshirilmadi: Online takrorlash",
      "Ko'proq e'tibor kerak: Foizlar (50%)",
    ]) {
      assert(report.includes(piece), `hisobotda "${piece}" bor:\n${report}`);
    }
    const missedOnly = sent.find((t) => t.startsWith("📅 Haftalik hisobot — Sinov Vali"));
    assert(
      missedOnly?.includes("Bu hafta test topshirilmadi.") && missedOnly.includes("Topshirilmadi: Online takrorlash"),
      `faqat testni o'tkazib yuborgan Vali hisoboti:
${missedOnly}`,
    );

    // The same data seen as a month (the last month end before now).
    const month = latestMonthlyPeriod(new Date());
    const monthly = await sweepReports(new Date(month.end.getTime() + HOUR), scope);
    const inMonth = week.end > month.start && week.end.getTime() - 3 * DAY <= month.end.getTime();
    assert(!inMonth || monthly.monthly === 1, `oylik hisobot (${monthly.monthly})`);

    console.log(`NATIJA: HAMMASI TO'G'RI\n${report}`);
  } finally {
    await prisma.notification.deleteMany({ where: { chatId: parent.id } });
    await prisma.assignment.deleteMany({ where: { classroomId: classroom.id } }); // sheets cascade
    await prisma.classroom.delete({ where: { id: classroom.id } });
    await prisma.student.deleteMany({ where: { createdById: teacher.id } }); // links cascade
    await prisma.telegramAccount.delete({ where: { id: parent.id } });
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
