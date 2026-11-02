// End-to-end check of staff roles against the real database (no browser):
// a teacher reaches only their own classrooms, students, assignments, sheets
// and tests; admins see every test and edit any question but open no
// classroom; the centre-wide analytics load. See docs/DECISIONS.md #20.
//
//   npx tsx scripts/e2e-roles.ts     # creates its own data, then deletes it
import "dotenv/config";
import { randomBytes } from "node:crypto";
import bcrypt from "bcryptjs";
import { prisma } from "../src/lib/prisma";
import {
  accessibleTest,
  editableQuestion,
  ownAssignment,
  ownClassroom,
  ownSheet,
  ownStudent,
  testScope,
} from "../src/lib/access";
import { createAssignment } from "../src/lib/assignments";
import { loadCenterAnalytics, loadQuestionBankAnalytics, loadTeacherAnalytics } from "../src/lib/center-analytics";
import { HttpError } from "../src/lib/http-error";
import { generateLinkCode } from "../src/lib/link-code";

const N = 5;

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
  // Nobody can sign in as these: the password is random and never kept.
  const passwordHash = await bcrypt.hash(randomBytes(24).toString("hex"), 10);
  const staff = (name: string, role: "TEACHER" | "ADMIN") =>
    prisma.user.create({
      data: { name: `E2E ${name} ${stamp}`, email: `e2e-${name.toLowerCase()}-${stamp}@e2e.local`, passwordHash, role },
    });
  const karimova = await staff("Karimova", "TEACHER");
  const tursunov = await staff("Tursunov", "TEACHER");
  const admin = await staff("Admin", "ADMIN");

  const subject = await prisma.subject.create({
    data: { name: `E2E Rollar ${stamp}`, difficultyLevels: { create: [{ name: "O'rta", order: 1 }] } },
    include: { difficultyLevels: true },
  });
  const questions = [];
  for (let i = 0; i < N; i++) {
    questions.push(
      await prisma.question.create({
        data: {
          subjectId: subject.id,
          text: `Rollar sinovi ${i + 1}-savol`,
          correctAnswer: "1",
          wrongAnswers: ["2", "3", "4", "5"],
          difficultyId: subject.difficultyLevels[0].id,
          focus: "ABITURIENT",
          createdById: karimova.id,
        },
      }),
    );
  }
  const test = await prisma.test.create({
    data: {
      title: `E2E rollar testi ${stamp}`,
      subjectId: subject.id,
      createdById: karimova.id,
      questionIds: questions.map((q) => q.id),
    },
  });
  const groupA = await prisma.classroom.create({ data: { name: `E2E rollar A ${stamp}`, teacherId: karimova.id } });
  const groupB = await prisma.classroom.create({ data: { name: `E2E rollar B ${stamp}`, teacherId: tursunov.id } });
  const studentIds: string[] = [];

  try {
    const student = await prisma.student.create({
      data: {
        firstName: "Rol",
        lastName: "Sinov",
        linkCode: generateLinkCode(),
        createdById: karimova.id,
        memberships: { create: { classroomId: groupA.id } },
      },
    });
    studentIds.push(student.id);
    const assignment = await createAssignment({ classroomId: groupA.id, testId: test.id, createdById: karimova.id });
    const sheet = await prisma.assignmentSheet.findFirstOrThrow({ where: { assignmentId: assignment.id } });

    // A teacher reaches everything of their own.
    await ownClassroom(groupA.id, karimova.id);
    await ownStudent(student.id, karimova.id);
    await ownAssignment(assignment.id, karimova.id);
    await ownSheet(sheet.id, karimova.id);
    await accessibleTest(test.id, karimova);
    await editableQuestion(questions[0].id, karimova);

    // Another teacher: not found, not even "forbidden".
    await expectHttpError(ownClassroom(groupA.id, tursunov.id), 404, "boshqa o'qituvchining guruhi");
    await expectHttpError(ownStudent(student.id, tursunov.id), 404, "boshqa o'qituvchining o'quvchisi");
    await expectHttpError(ownAssignment(assignment.id, tursunov.id), 404, "boshqa o'qituvchining topshirig'i");
    await expectHttpError(ownSheet(sheet.id, tursunov.id), 404, "boshqa o'qituvchining varag'i");
    await expectHttpError(accessibleTest(test.id, tursunov), 404, "boshqa o'qituvchining testi");
    // The bank is shared, so this one is visible — just not editable.
    await expectHttpError(editableQuestion(questions[0].id, tursunov), 403, "boshqa o'qituvchining savolini tahrirlash");
    assert(
      (await prisma.test.count({ where: { id: test.id, ...testScope(tursunov) } })) === 0,
      "Tursunovning testlar ro'yxatida Karimovaning testi yo'q",
    );

    // Admin: every test and question, but no classroom.
    await accessibleTest(test.id, admin);
    await editableQuestion(questions[0].id, admin);
    await expectHttpError(ownClassroom(groupA.id, admin.id), 404, "admin guruhni ochmaydi");

    // The child also joins Tursunov's group: both teachers see the student,
    // and Tursunov still sees none of Karimova's results.
    await prisma.classroomMember.create({ data: { classroomId: groupB.id, studentId: student.id } });
    await ownStudent(student.id, tursunov.id);
    assert(
      (await prisma.assignmentSheet.count({
        where: { studentId: student.id, assignment: { classroom: { teacherId: tursunov.id } } },
      })) === 0,
      "Tursunov Karimovaning topshirig'idagi natijani ko'rmaydi",
    );

    // Access follows the classroom's teacher, e.g. after handing groups over.
    await prisma.classroom.updateMany({ where: { teacherId: karimova.id }, data: { teacherId: tursunov.id } });
    await ownAssignment(assignment.id, tursunov.id);
    await expectHttpError(ownClassroom(groupA.id, karimova.id), 404, "o'tkazilgan guruh eski egasida qolmaydi");

    const [teachers, center, bank] = await Promise.all([
      loadTeacherAnalytics(),
      loadCenterAnalytics(),
      loadQuestionBankAnalytics(),
    ]);
    const row = teachers.rows.find((r) => r.id === tursunov.id);
    assert(row?.isTeacher && row.classrooms === 2 && row.assignments === 1, "o'qituvchilar tahlilida Tursunov: 2 guruh, 1 topshiriq");
    assert(!teachers.rows.some((r) => r.id === admin.id), "guruhsiz admin o'qituvchilar ro'yxatida emas");
    assert(center.counts.students >= 1, "markaz tahlili yuklandi");
    assert(
      bank.authors.some((a) => a.id === karimova.id && a.questions === N),
      "savollar bazasi tahlilida Karimovaning savollari",
    );

    console.log("NATIJA: HAMMASI TO'G'RI");
  } finally {
    await prisma.assignment.deleteMany({ where: { classroomId: { in: [groupA.id, groupB.id] } } }); // sheets cascade
    await prisma.classroom.deleteMany({ where: { id: { in: [groupA.id, groupB.id] } } }); // memberships cascade
    await prisma.student.deleteMany({ where: { id: { in: studentIds } } });
    await prisma.test.delete({ where: { id: test.id } });
    await prisma.question.deleteMany({ where: { id: { in: questions.map((q) => q.id) } } });
    await prisma.subject.delete({ where: { id: subject.id } });
    await prisma.user.deleteMany({ where: { id: { in: [karimova.id, tursunov.id, admin.id] } } });
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
