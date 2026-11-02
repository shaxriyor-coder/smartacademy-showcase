import type { Prisma } from "@prisma/client";
import { prisma } from "./prisma";
import { HttpError } from "./http-error";
import { isManager, type StaffRole } from "./roles";

// Ownership checks behind the role guards in src/lib/api-auth.ts.
// A teacher's miss is a 404, not a 403: another teacher's classroom or
// student shouldn't even be confirmed to exist.

export type Staff = { id: string; role?: StaffRole };

export async function ownClassroom(classroomId: string, teacherId: string) {
  const classroom = await prisma.classroom.findFirst({
    where: { id: classroomId, teacherId },
    select: { id: true },
  });
  if (!classroom) throw new HttpError("Guruh topilmadi", 404);
  return classroom;
}

export async function ownAssignment(assignmentId: string, teacherId: string) {
  const assignment = await prisma.assignment.findFirst({
    where: { id: assignmentId, classroom: { teacherId } },
    select: { id: true, classroomId: true },
  });
  if (!assignment) throw new HttpError("Topshiriq topilmadi", 404);
  return assignment;
}

export async function ownSheet(sheetId: string, teacherId: string) {
  const sheet = await prisma.assignmentSheet.findFirst({
    where: { id: sheetId, assignment: { classroom: { teacherId } } },
    select: { id: true },
  });
  if (!sheet) throw new HttpError("Varaq topilmadi", 404);
  return sheet;
}

// A student is a teacher's while they sit in one of the teacher's classrooms.
export async function ownStudent(studentId: string, teacherId: string) {
  const student = await prisma.student.findFirst({
    where: { id: studentId, memberships: { some: { classroom: { teacherId } } } },
    select: { id: true },
  });
  if (!student) throw new HttpError("O'quvchi topilmadi", 404);
  return student;
}

// Teachers work with the tests they built; admins see every test.
export function testScope(user: Staff): Prisma.TestWhereInput {
  return isManager(user.role) ? {} : { createdById: user.id };
}

export async function accessibleTest(testId: string, user: Staff) {
  const test = await prisma.test.findFirst({
    where: { id: testId, ...testScope(user) },
    select: { id: true },
  });
  if (!test) throw new HttpError("Test topilmadi", 404);
  return test;
}

// The whole bank is visible to all staff (tests are built from it), but a
// teacher changes only the questions they added.
export function canEditQuestion(question: { createdById: string }, user: Staff) {
  return isManager(user.role) || question.createdById === user.id;
}

export async function editableQuestion(questionId: string, user: Staff) {
  const question = await prisma.question.findUnique({
    where: { id: questionId },
    select: { id: true, createdById: true },
  });
  if (!question) throw new HttpError("Topilmadi", 404);
  if (!canEditQuestion(question, user)) {
    throw new HttpError("Faqat o'zingiz qo'shgan savolni o'zgartira olasiz", 403);
  }
  return question;
}
