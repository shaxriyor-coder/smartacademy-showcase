// Removes what the e2e scripts leave behind with --keep: classrooms, tests and
// subjects whose names start with "E2E ", the students who belong ONLY to those
// classrooms, and the test Telegram accounts (e2e-* and the dev-login account
// 900000001). Anything else is left alone.
//
//   npx tsx scripts/cleanup-e2e.ts          # dry run: shows what would go
//   npx tsx scripts/cleanup-e2e.ts --apply  # deletes, in one transaction
//
// Take a database dump first if in doubt (see README).
import "dotenv/config";
import { prisma } from "../src/lib/prisma";

const APPLY = process.argv.includes("--apply");
const PREFIX = "E2E ";
const TEST_ACCOUNT_IDS = ["900000001"];

async function main() {
  const classrooms = await prisma.classroom.findMany({
    where: { name: { startsWith: PREFIX } },
    select: { id: true, name: true, members: { select: { studentId: true } } },
  });
  const classroomIds = classrooms.map((c) => c.id);

  // Only students with no membership outside the e2e classrooms.
  const candidateIds = [...new Set(classrooms.flatMap((c) => c.members.map((m) => m.studentId)))];
  const students = await prisma.student.findMany({
    where: {
      id: { in: candidateIds },
      memberships: { every: { classroomId: { in: classroomIds } } },
    },
    select: { id: true, firstName: true, lastName: true },
  });

  const accounts = await prisma.telegramAccount.findMany({
    where: { OR: [{ id: { startsWith: "e2e-" } }, { id: { in: TEST_ACCOUNT_IDS } }] },
    select: { id: true, firstName: true },
  });
  const tests = await prisma.test.findMany({
    where: { title: { startsWith: PREFIX } },
    select: { id: true, title: true },
  });
  const subjects = await prisma.subject.findMany({
    where: { name: { startsWith: PREFIX } },
    select: { id: true, name: true, _count: { select: { questions: true } } },
  });
  const assignmentCount = await prisma.assignment.count({ where: { classroomId: { in: classroomIds } } });

  console.log(APPLY ? "O'CHIRILMOQDA:" : "SINOV REJIMI — hech narsa o'chirilmadi (o'chirish uchun --apply)");
  console.log(`  guruhlar (${classrooms.length}): ${classrooms.map((c) => c.name).join("; ") || "—"}`);
  console.log(`  topshiriqlar: ${assignmentCount} (varaqlari bilan)`);
  console.log(`  o'quvchilar (${students.length}): ${students.map((s) => `${s.lastName ?? ""} ${s.firstName}`.trim()).join("; ") || "—"}`);
  console.log(`  Telegram akkauntlar (${accounts.length}): ${accounts.map((a) => `${a.firstName} [${a.id}]`).join("; ") || "—"}`);
  console.log(`  testlar (${tests.length}): ${tests.map((t) => t.title).join("; ") || "—"}`);
  console.log(`  fanlar (${subjects.length}): ${subjects.map((s) => `${s.name} (${s._count.questions} savol)`).join("; ") || "—"}`);

  if (!APPLY) return;

  await prisma.$transaction(
    async (tx) => {
      await tx.assignment.deleteMany({ where: { classroomId: { in: classroomIds } } }); // sheets cascade
      // Tests of other classrooms may still use an e2e test — those block its deletion below.
      await tx.classroom.deleteMany({ where: { id: { in: classroomIds } } }); // memberships cascade
      await tx.student.deleteMany({ where: { id: { in: students.map((s) => s.id) } } }); // links cascade
      await tx.telegramAccount.deleteMany({ where: { id: { in: accounts.map((a) => a.id) } } });
      await tx.test.deleteMany({ where: { id: { in: tests.map((t) => t.id) } } });
      const subjectIds = subjects.map((s) => s.id);
      await tx.question.deleteMany({ where: { subjectId: { in: subjectIds } } });
      await tx.subject.deleteMany({ where: { id: { in: subjectIds } } }); // themes, levels cascade
    },
    { timeout: 60_000 },
  );
  console.log("Tayyor.");
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
