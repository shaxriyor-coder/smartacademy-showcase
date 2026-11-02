// End-to-end check of the offline flow against the real database and a running
// checker service — everything except the browser:
//
//   question bank -> test -> classroom + students -> assignment (frozen key)
//   -> personalized answer sheets (checker) -> simulated filled + skewed scan
//   (checker/scripts/fake_scan.py) -> check -> grade -> stored results
//   -> a second upload of the same scan is refused as a duplicate.
//
// Run with the checker up (`cd checker && python server.py`):
//   npx tsx scripts/e2e-offline.ts          # creates its own data, then deletes it
//   npx tsx scripts/e2e-offline.ts --keep   # leaves the data to look at in the UI
import "dotenv/config";
import { execFileSync } from "child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import path from "path";
import { prisma } from "../src/lib/prisma";
import { buildSheetsPdf, checkUploadedScan, createAssignment } from "../src/lib/assignments";
import { LETTERS } from "../src/lib/answer-key";
import { generateLinkCode } from "../src/lib/link-code";
import { themeStats } from "../src/lib/progress";

const KEEP = process.argv.includes("--keep");
const QUESTION_COUNT = 12;
const CHECKER_DIR = path.resolve(__dirname, "..", "checker");

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`ASSERT: ${message}`);
}

async function main() {
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const admin = await prisma.user.findFirst({ orderBy: { createdAt: "asc" } });
  assert(admin, "bazada birorta admin yo'q (npm run db:seed)");

  // --- question bank + test ------------------------------------------------
  const subject = await prisma.subject.create({
    data: {
      name: `E2E Matematika ${stamp}`,
      themes: { create: [{ name: "Algebra" }, { name: "Geometriya" }] },
      difficultyLevels: { create: [{ name: "O'rta", order: 1 }] },
    },
    include: { themes: true, difficultyLevels: true },
  });
  const questionIds: string[] = [];
  for (let i = 0; i < QUESTION_COUNT; i++) {
    const q = await prisma.question.create({
      data: {
        subjectId: subject.id,
        text: `E2E savol ${i + 1}: ${i + 2} + ${i + 3} = ?`,
        correctAnswer: String(2 * i + 5),
        wrongAnswers: [1, 2, 3, 4].map((d) => String(2 * i + 5 + d)),
        difficultyId: subject.difficultyLevels[0].id,
        focus: "ABITURIENT",
        createdById: admin.id,
        themes: { connect: [{ id: subject.themes[i % 2].id }] },
      },
    });
    questionIds.push(q.id);
  }
  const test = await prisma.test.create({
    data: { title: `E2E test ${stamp}`, subjectId: subject.id, createdById: admin.id, questionIds },
  });

  // --- classroom + roster -------------------------------------------------
  const classroom = await prisma.classroom.create({
    data: { name: `E2E guruh ${stamp}`, subjectId: subject.id, teacherId: admin.id },
  });
  const roster = [
    { lastName: "Aliyev", firstName: "Vali", grade: "7-A", birthDate: new Date("2013-04-09T00:00:00Z") },
    { lastName: "Karimova", firstName: "Madina", grade: "7-A", birthDate: null },
    { lastName: "Toshmatov", firstName: "Jasur", grade: null, birthDate: null },
  ];
  for (const s of roster) {
    await prisma.student.create({
      data: {
        ...s,
        linkCode: generateLinkCode(),
        createdById: admin.id,
        memberships: { create: { classroomId: classroom.id } },
      },
    });
  }

  const work = mkdtempSync(path.join(tmpdir(), "e2e-offline-"));
  try {
    // --- assignment + sheets ----------------------------------------------
    const assignment = await createAssignment({
      classroomId: classroom.id,
      testId: test.id,
      createdById: admin.id,
    });
    assert(assignment.answerKey.length === QUESTION_COUNT, "kalit uzunligi");

    let t0 = Date.now();
    const { pdf } = await buildSheetsPdf(assignment.id);
    console.log(`varaqlar: ${pdf.length} bayt, ${((Date.now() - t0) / 1000).toFixed(1)}s (shablon bilan)`);
    t0 = Date.now();
    await buildSheetsPdf(assignment.id); // second call: template reused, stamping only
    console.log(`qayta chiqarish: ${((Date.now() - t0) / 1000).toFixed(1)}s`);

    const stored = await prisma.assignment.findUniqueOrThrow({ where: { id: assignment.id } });
    assert(stored.sheetBubbleBoxes, "shablon koordinatalari saqlanmadi");
    // Page order = class register order, same as buildSheetsPdf.
    const sheets = await prisma.assignmentSheet.findMany({
      where: { assignmentId: assignment.id },
      include: { student: true },
      orderBy: [{ student: { lastName: "asc" } }, { student: { firstName: "asc" } }],
    });
    assert(sheets.length === roster.length, "har o'quvchiga varaq");

    // --- what each student "wrote" -----------------------------------------
    const key = stored.answerKey;
    const wrong = (letter: string) => LETTERS.find((l) => l !== letter)!;
    const plans: { marks: string[][]; correct: number }[] = [
      { marks: key.map((k) => [k]), correct: QUESTION_COUNT }, // all correct
      { marks: key.map((k, i) => (i < 6 ? [k] : [wrong(k)])), correct: 6 }, // half
      {
        // 2 blank, 1 double-marked, the rest correct
        marks: key.map((k, i) => (i === 0 || i === 1 ? [] : i === 2 ? ["A", "C"] : [k])),
        correct: QUESTION_COUNT - 3,
      },
    ];

    const sheetsPath = path.join(work, "sheets.pdf");
    const boxesPath = path.join(work, "boxes.json");
    const answersPath = path.join(work, "answers.json");
    const scanPath = path.join(work, "scan.pdf");
    writeFileSync(sheetsPath, pdf);
    writeFileSync(boxesPath, stored.sheetBubbleBoxes);
    writeFileSync(
      answersPath,
      JSON.stringify(plans.map((p) => ({ [stored.subjectName]: p.marks }))),
    );
    execFileSync("python", [path.join("scripts", "fake_scan.py"), sheetsPath, boxesPath, answersPath, scanPath], {
      cwd: CHECKER_DIR,
      stdio: "inherit",
    });
    const scan = new Uint8Array(readFileSync(scanPath));

    // --- check ---------------------------------------------------------------
    t0 = Date.now();
    const first = await checkUploadedScan(assignment.id, { bytes: scan, name: "scan.pdf", type: "application/pdf" });
    console.log(`tekshiruv: ${((Date.now() - t0) / 1000).toFixed(1)}s`);
    for (const o of first.outcomes) {
      console.log(`  ${o.page}-varaq: ${o.status} ${o.studentName ?? ""} ${o.correct ?? ""}/${o.total ?? ""} ${o.message}`);
    }
    assert(first.pageCount === roster.length, "sahifalar soni");
    assert(first.outcomes.every((o) => o.status === "saved"), "hamma varaq saqlanishi kerak");
    assert(first.annotatedPdf, "belgilangan PDF qaytishi kerak");

    const results = await prisma.assignmentSheet.findMany({
      where: { assignmentId: assignment.id },
      orderBy: [{ student: { lastName: "asc" } }, { student: { firstName: "asc" } }],
    });
    results.forEach((r, i) => {
      assert(r.checkedAt, `${i + 1}-o'quvchi tekshirilmagan`);
      assert(r.correct === plans[i].correct, `${i + 1}-o'quvchi: kutilgan ${plans[i].correct}, saqlangan ${r.correct}`);
    });
    assert(results[2].answers[0] === "" && results[2].answers[2] === "*", "bo'sh va ko'p belgilangan javob belgisi");

    const second = await checkUploadedScan(assignment.id, { bytes: scan, name: "scan.pdf", type: "application/pdf" });
    assert(second.outcomes.every((o) => o.status === "duplicate"), "qayta yuklash natijani qayta yozmasligi kerak");

    const themes = await themeStats(
      results.map((r) => ({ answers: r.answers, questionIds: stored.questionIds, answerKey: stored.answerKey })),
    );
    console.log("mavzular:", themes.map((t) => `${t.name} ${t.correct}/${t.total} (${t.percentage}%)`).join(", "));
    assert(themes.reduce((n, t) => n + t.total, 0) === QUESTION_COUNT * roster.length, "mavzu statistikasi yig'indisi");

    console.log("NATIJA: HAMMASI TO'G'RI");
    if (KEEP) {
      console.log(`Ma'lumot qoldirildi: /classrooms/${classroom.id}/assignments/${assignment.id}`);
    }
  } finally {
    rmSync(work, { recursive: true, force: true });
    if (!KEEP) {
      await prisma.assignment.deleteMany({ where: { classroomId: classroom.id } }); // sheets cascade
      const members = await prisma.classroomMember.findMany({ where: { classroomId: classroom.id } });
      await prisma.classroom.delete({ where: { id: classroom.id } }); // memberships cascade
      await prisma.student.deleteMany({ where: { id: { in: members.map((m) => m.studentId) } } });
      await prisma.test.delete({ where: { id: test.id } });
      await prisma.question.deleteMany({ where: { id: { in: questionIds } } });
      await prisma.subject.delete({ where: { id: subject.id } }); // themes, levels cascade
    }
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
