// End-to-end check of "o'quvchiga qarab" tests against the real database
// (docs/DECISIONS.md #25): a student weak in one topic and strong in another
// gets most questions from the weak one, some from the untested one, none they
// already had while unseen ones remain, and nothing unassignable; a group works
// too; another teacher's classroom is not found.
//
//   npx tsx scripts/e2e-suggest.ts     # creates its own data, then deletes it
import "dotenv/config";
import { randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";
import { prisma } from "../src/lib/prisma";
import { createAssignment } from "../src/lib/assignments";
import { gradeAnswers } from "../src/lib/answer-key";
import { HttpError } from "../src/lib/http-error";
import { generateLinkCode } from "../src/lib/link-code";
import { loadSuggestion } from "../src/lib/suggest";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERT: ${message}`);
}

async function main() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const passwordHash = await bcrypt.hash(randomBytes(24).toString("hex"), 10);
  const [teacher, other] = await Promise.all(
    ["a", "b"].map((x) =>
      prisma.user.create({
        data: { name: `E2E Taklif ${x} ${stamp}`, email: `e2e-suggest-${x}-${stamp}@e2e.local`, passwordHash, role: "TEACHER" },
      }),
    ),
  );
  const subject = await prisma.subject.create({
    data: {
      name: `E2E Taklif ${stamp}`,
      themes: { create: [{ name: "Foizlar" }, { name: "Tenglamalar" }, { name: "Geometriya" }] },
      difficultyLevels: { create: [{ name: "Oson", order: 1 }, { name: "O'rta", order: 2 }, { name: "Qiyin", order: 3 }] },
    },
    include: { themes: true, difficultyLevels: true },
  });
  const theme = (name: string) => subject.themes.find((t) => t.name === name)!;
  const make = (themeName: string, i: number, options = 5) =>
    prisma.question.create({
      data: {
        subjectId: subject.id,
        text: `${themeName} ${i}`,
        correctAnswer: "1",
        wrongAnswers: ["2", "3", "4", "5"].slice(0, options - 1),
        difficultyId: subject.difficultyLevels[i % 3].id,
        focus: "ABITURIENT",
        createdById: teacher.id,
        themes: { connect: [{ id: theme(themeName).id }] },
      },
    });
  const questions = [];
  for (const name of ["Foizlar", "Tenglamalar", "Geometriya"]) for (let i = 0; i < 8; i++) questions.push(await make(name, i));
  const broken = await make("Foizlar", 99, 4);
  questions.push(broken);
  const foizlar = questions.filter((q) => q.text.startsWith("Foizlar") && q.id !== broken.id);
  const tenglamalar = questions.filter((q) => q.text.startsWith("Tenglamalar"));

  const given = [...foizlar.slice(0, 3), ...tenglamalar.slice(0, 3)];
  const test = await prisma.test.create({
    data: { title: `E2E taklif testi ${stamp}`, subjectId: subject.id, createdById: teacher.id, questionIds: given.map((q) => q.id) },
  });
  const classroom = await prisma.classroom.create({ data: { name: `E2E taklif ${stamp}`, teacherId: teacher.id, subjectId: subject.id } });

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
          },
        }),
      ),
    );
    // Ali: every Foizlar question wrong, every Tenglamalar question right.
    const a = await createAssignment({ classroomId: classroom.id, testId: test.id, createdById: teacher.id });
    const answers = a.answerKey.map((k, i) => (i < 3 ? (k === "A" ? "B" : "A") : k));
    await prisma.assignmentSheet.updateMany({
      where: { assignmentId: a.id, studentId: ali.id },
      data: { answers, ...gradeAnswers(answers, a.answerKey), checkedAt: new Date(), resultNotifiedAt: new Date() },
    });

    const base = { teacherId: teacher.id, classroomId: classroom.id, subjectId: subject.id, seed: "e2e" };
    const forAli = await loadSuggestion({ ...base, studentId: ali.id, count: 10 });
    const slots = Object.fromEntries(forAli.plan.map((p) => [p.name, p.slots]));
    assert(forAli.questions.length === 10 && forAli.shortfall === 0, `10 ta savol (${forAli.questions.length})`);
    assert(slots.Foizlar > slots.Geometriya && slots.Geometriya > slots.Tenglamalar, `zaif > sinalmagan > yaxshi: ${JSON.stringify(slots)}`);
    assert(forAli.plan.find((p) => p.name === "Foizlar")?.standing === "weak", "Foizlar zaif deb topildi");
    const givenIds = new Set(given.map((q) => q.id));
    assert(!forAli.questions.some((q) => givenIds.has(q.id)), "Aliga avval berilgan savol qaytmadi");
    assert(!forAli.questions.some((q) => q.id === broken.id), "variantlari 4 ta savol taklif qilinmadi");
    assert(forAli.target.name === "Sinov Ali" && !forAli.target.isGroup, "maqsad — Ali");

    const forGroup = await loadSuggestion({ ...base, studentId: null, count: 5 });
    assert(forGroup.target.isGroup && forGroup.target.students === 2 && forGroup.questions.length === 5, "butun guruh uchun taklif");

    try {
      await loadSuggestion({ ...base, teacherId: other.id, studentId: vali.id, count: 5 });
      throw new Error("ASSERT: boshqa o'qituvchi bu guruhni ko'rmasligi kerak");
    } catch (err) {
      assert(err instanceof HttpError && err.status === 404, `boshqa o'qituvchiga 404 (${(err as Error).message})`);
    }

    console.log(`NATIJA: HAMMASI TO'G'RI (Ali uchun: ${JSON.stringify(slots)})`);
  } finally {
    await prisma.assignment.deleteMany({ where: { classroomId: classroom.id } });
    await prisma.classroom.delete({ where: { id: classroom.id } });
    await prisma.student.deleteMany({ where: { createdById: teacher.id } });
    await prisma.test.delete({ where: { id: test.id } });
    await prisma.question.deleteMany({ where: { id: { in: questions.map((q) => q.id) } } });
    await prisma.subject.delete({ where: { id: subject.id } });
    await prisma.user.deleteMany({ where: { id: { in: [teacher.id, other.id] } } });
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
