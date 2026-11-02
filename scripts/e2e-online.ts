// End-to-end check of online assignments against the real database (no
// checker, no browser): assignment -> start -> per-tap saves -> submit or time
// out -> grading, access rules, opening window, late-joining students.
//
//   npx tsx scripts/e2e-online.ts          # creates its own data, then deletes it
//   npx tsx scripts/e2e-online.ts --keep   # leaves it, plus an open test for the UI
import "dotenv/config";
import { prisma } from "../src/lib/prisma";
import { buildSheetsPdf, createAssignment, syncClassroomSheets } from "../src/lib/assignments";
import { LETTERS } from "../src/lib/answer-key";
import { HttpError } from "../src/lib/http-error";
import { generateLinkCode } from "../src/lib/link-code";
import { attemptQuestions, saveAnswer, sheetForAccount, startAttempt, submitAttempt } from "../src/lib/online";
import { revealAllowed } from "../src/lib/online-core";

const KEEP = process.argv.includes("--keep");
const N = 10;
const MINUTE = 60_000;

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERT: ${message}`);
}

async function expectHttpError(action: Promise<unknown>, status: number, label: string) {
  try {
    await action;
  } catch (err) {
    if (err instanceof HttpError && err.status === status) return;
    throw err;
  }
  throw new Error(`ASSERT: ${label} (${status} xato kutilgan edi)`);
}

async function main() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const admin = await prisma.user.findFirst({ orderBy: { createdAt: "asc" } });
  assert(admin, "bazada birorta admin yo'q (npm run db:seed)");

  const subject = await prisma.subject.create({
    data: {
      name: `E2E Online ${stamp}`,
      themes: { create: [{ name: "Tenglamalar" }, { name: "Foizlar" }] },
      difficultyLevels: { create: [{ name: "O'rta", order: 1 }] },
    },
    include: { themes: true, difficultyLevels: true },
  });
  const questions = [];
  for (let i = 0; i < N; i++) {
    questions.push(
      await prisma.question.create({
        data: {
          subjectId: subject.id,
          text: `${i + 1}-savol: x + ${i} = ${2 * i + 1}. x nechaga teng?`,
          correctAnswer: String(i + 1),
          wrongAnswers: [i + 2, i + 3, i + 4, i + 5].map(String),
          difficultyId: subject.difficultyLevels[0].id,
          focus: "ABITURIENT",
          createdById: admin.id,
          themes: { connect: [{ id: subject.themes[i % 2].id }] },
        },
      }),
    );
  }
  const questionIds = questions.map((q) => q.id);
  const correctText = new Map(questions.map((q) => [q.id, q.correctAnswer]));
  const test = await prisma.test.create({
    data: { title: `E2E online test ${stamp}`, subjectId: subject.id, createdById: admin.id, questionIds },
  });
  const classroom = await prisma.classroom.create({
    data: { name: `E2E online guruh ${stamp}`, subjectId: subject.id, teacherId: admin.id },
  });

  const students = [];
  for (const [lastName, firstName] of [
    ["Aliyeva", "Nigora"],
    ["Botirov", "Sardor"],
    ["Qodirov", "Ulug'bek"],
  ]) {
    students.push(
      await prisma.student.create({
        data: {
          firstName,
          lastName,
          grade: "8-B",
          linkCode: generateLinkCode(),
          createdById: admin.id,
          memberships: { create: { classroomId: classroom.id } },
        },
      }),
    );
  }
  const [sa, sb, sc] = students;
  // One parent with two children, another family with one.
  const parent = await prisma.telegramAccount.create({
    data: {
      id: `e2e-${stamp}-1`,
      firstName: "Ota-ona",
      lastLoginAt: new Date(),
      students: { create: [{ studentId: sa.id }, { studentId: sb.id }] },
    },
  });
  const other = await prisma.telegramAccount.create({
    data: {
      id: `e2e-${stamp}-2`,
      firstName: "Boshqa oila",
      lastLoginAt: new Date(),
      students: { create: [{ studentId: sc.id }] },
    },
  });

  try {
    const closesAt = new Date(Date.now() + 60 * MINUTE);
    const assignment = await createAssignment({
      classroomId: classroom.id,
      testId: test.id,
      createdById: admin.id,
      mode: "ONLINE",
      online: { opensAt: null, closesAt, timeLimitMinutes: 30, shuffle: true, revealAnswers: "AFTER_CLOSE" },
    });
    const key = assignment.answerKey;
    const sheetOf = (assignmentId: string, studentId: string) =>
      prisma.assignmentSheet.findFirstOrThrow({ where: { assignmentId, studentId } });
    const ka = await sheetOf(assignment.id, sa.id);
    const kb = await sheetOf(assignment.id, sb.id);
    const kc = await sheetOf(assignment.id, sc.id);

    await expectHttpError(buildSheetsPdf(assignment.id), 409, "online testga javob varag'i chiqmasligi kerak");
    await expectHttpError(sheetForAccount(kc.id, parent.id), 404, "ulanmagan o'quvchining varag'i ko'rinmasligi kerak");
    await expectHttpError(saveAnswer(ka.id, parent.id, 0, "A"), 409, "boshlamasdan javob saqlanmasligi kerak");

    // A: picks each correct option by its TEXT, as a student would, through
    // shuffled questions and options.
    await startAttempt(ka.id, parent.id);
    const view = await attemptQuestions(await sheetForAccount(ka.id, parent.id));
    assert(view.length === N, "savollar soni");
    assert(view.some((q, position) => q.index !== position), "savollar tartibi aralashtirilgan bo'lishi kerak");
    for (const q of view) {
      assert(
        q.options.length === 5 &&
          q.options.every((o) => Object.keys(o).sort().join(",") === "text,value"),
        "variantlarda faqat matn va qiymat bo'lishi kerak (to'g'ri javob belgisi emas)",
      );
      const right = q.options.find((o) => o.text === correctText.get(questionIds[q.index]));
      assert(right, `${q.index + 1}-savolda to'g'ri javob matni yo'q`);
      await saveAnswer(ka.id, parent.id, q.index, right.value);
    }
    await submitAttempt(ka.id, parent.id);
    await submitAttempt(ka.id, parent.id); // a double tap changes nothing
    const doneA = await prisma.assignmentSheet.findUniqueOrThrow({ where: { id: ka.id } });
    assert(doneA.checkedAt && doneA.correct === N, `A: ${N}/${N} kutilgan, ${doneA.correct}`);
    assert(doneA.answers.every((choice, i) => choice === key[i]), "javoblar kanonik harflarda saqlanishi kerak");
    await expectHttpError(saveAnswer(ka.id, parent.id, 0, "B"), 409, "topshirilgan testda javob o'zgarmasligi kerak");

    // B: 4 right; answer #4 only reaches the server inside the submit (a lost autosave).
    await startAttempt(kb.id, parent.id);
    for (let i = 0; i < N; i++) {
      if (i === 3) continue;
      await saveAnswer(kb.id, parent.id, i, i < 4 ? key[i] : LETTERS.find((l) => l !== key[i])!);
    }
    await submitAttempt(kb.id, parent.id, { "3": key[3] });
    const doneB = await prisma.assignmentSheet.findUniqueOrThrow({ where: { id: kb.id } });
    assert(doneB.correct === 4, `B: 4 kutilgan, ${doneB.correct}`);

    // C: 2 right, then the time limit passes with the app closed.
    await startAttempt(kc.id, other.id);
    await saveAnswer(kc.id, other.id, 0, key[0]);
    await saveAnswer(kc.id, other.id, 1, key[1]);
    const startedLongAgo = new Date(Date.now() - 31 * MINUTE);
    await prisma.assignmentSheet.update({ where: { id: kc.id }, data: { startedAt: startedLongAgo } });
    await expectHttpError(saveAnswer(kc.id, other.id, 2, key[2]), 409, "vaqt tugagach javob saqlanmasligi kerak");
    const doneC = await prisma.assignmentSheet.findUniqueOrThrow({ where: { id: kc.id } });
    assert(doneC.checkedAt && doneC.correct === 2, `C: 2 kutilgan, ${doneC.correct}`);
    assert(
      doneC.checkedAt.getTime() === startedLongAgo.getTime() + 30 * MINUTE,
      "C: topshirilgan vaqt muddat bilan teng bo'lishi kerak",
    );

    assert(!revealAllowed(assignment.revealAnswers, closesAt, new Date()), "yopilmaguncha javoblar yashirin");
    assert(revealAllowed(assignment.revealAnswers, closesAt, new Date(closesAt.getTime() + 1)), "yopilgach ko'rinadi");

    // A test that opens later can't be started early.
    const later = await createAssignment({
      classroomId: classroom.id,
      testId: test.id,
      createdById: admin.id,
      title: `Keyinroq ochiladi ${stamp}`,
      mode: "ONLINE",
      online: { opensAt: new Date(Date.now() + 60 * MINUTE), closesAt: null, timeLimitMinutes: null, shuffle: false, revealAnswers: "IMMEDIATELY" },
    });
    await expectHttpError(
      startAttempt((await sheetOf(later.id, sa.id)).id, parent.id),
      409,
      "ochilmagan test boshlanmasligi kerak",
    );

    // A student who joins mid-test gets the running test too.
    const late = await prisma.student.create({
      data: {
        firstName: "Kechikkan",
        lastName: "Yangi",
        linkCode: generateLinkCode(),
        createdById: admin.id,
        memberships: { create: { classroomId: classroom.id } },
      },
    });
    students.push(late);
    await syncClassroomSheets(classroom.id); // what the members API does after adding
    assert(await sheetOf(assignment.id, late.id), "yangi o'quvchiga varaq");

    console.log("NATIJA: HAMMASI TO'G'RI");

    if (KEEP) {
      const ui = await createAssignment({
        classroomId: classroom.id,
        testId: test.id,
        createdById: admin.id,
        title: `UI sinov ${stamp}`,
        mode: "ONLINE",
        online: { opensAt: null, closesAt: new Date(Date.now() + 24 * 60 * MINUTE), timeLimitMinutes: 20, shuffle: true, revealAnswers: "IMMEDIATELY" },
      });
      console.log(`Ma'lumot qoldirildi: /classrooms/${classroom.id}/assignments/${ui.id}`);
      for (const s of students) console.log(`  ${s.lastName} ${s.firstName}: ulash kodi ${s.linkCode}`);
    }
  } finally {
    if (!KEEP) {
      await prisma.assignment.deleteMany({ where: { classroomId: classroom.id } }); // sheets cascade
      await prisma.classroom.delete({ where: { id: classroom.id } }); // memberships cascade
      await prisma.telegramAccount.deleteMany({ where: { id: { in: [parent.id, other.id] } } });
      await prisma.student.deleteMany({ where: { id: { in: students.map((s) => s.id) } } });
      await prisma.test.delete({ where: { id: test.id } });
      await prisma.question.deleteMany({ where: { id: { in: questionIds } } });
      await prisma.subject.delete({ where: { id: subject.id } });
    }
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
