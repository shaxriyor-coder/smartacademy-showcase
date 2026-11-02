import type { AssignmentMode, RevealPolicy } from "@prisma/client";
import { prisma } from "./prisma";
import { HttpError } from "./http-error";
import {
  BLANK_ANSWER,
  MAX_CHOICES,
  MIN_CHOICES,
  isAllowedOptionCount,
  optionCount,
  testChoiceCount,
  MULTI_ANSWER,
  correctLetter,
  gradeAnswers,
} from "./answer-key";
import { assignmentTicketCode, buildTicketNo } from "./ticket";
import { checkScan, createTemplate, stampSheets, type StampParticipant } from "./checker";
import { studentDisplayName } from "./students";

// The offline flow: a test is assigned to a classroom (frozen), the checker
// draws one template for it, every student gets a sheet with their own QR,
// scanned sheets come back through the checker and are graded HERE against
// the frozen key.

export type OnlineSettings = {
  opensAt: Date | null;
  closesAt: Date | null;
  timeLimitMinutes: number | null;
  shuffle: boolean;
  revealAnswers: RevealPolicy;
};

export async function createAssignment(opts: {
  classroomId: string;
  testId: string;
  title?: string;
  createdById: string;
  mode?: AssignmentMode;
  online?: OnlineSettings; // required for ONLINE
}) {
  const mode = opts.mode ?? "OFFLINE";
  if (mode === "ONLINE" && !opts.online) {
    throw new HttpError("Online test sozlamalari berilmagan", 400);
  }

  const classroom = await prisma.classroom.findUnique({ where: { id: opts.classroomId } });
  if (!classroom || classroom.archived) throw new HttpError("Guruh topilmadi", 404);

  const test = await prisma.test.findUnique({
    where: { id: opts.testId },
    include: { subject: true },
  });
  if (!test) throw new HttpError("Test topilmadi", 404);

  const questions = await prisma.question.findMany({
    where: { id: { in: test.questionIds } },
    select: { id: true, wrongAnswers: true },
  });
  const byId = new Map(questions.map((q) => [q.id, q]));
  const missing = test.questionIds.filter((id) => !byId.has(id)).length;
  if (missing > 0) {
    throw new HttpError(
      `Testdagi ${missing} ta savol bazadan o'chirilgan — testni qaytadan tuzing.`,
      409,
    );
  }
  const ordered = test.questionIds.map((id) => byId.get(id)!);
  const odd = ordered.findIndex((q) => !isAllowedOptionCount(optionCount(q)));
  if (odd !== -1) {
    throw new HttpError(
      `${odd + 1}-savolda variantlar soni ${MIN_CHOICES} yoki ${MAX_CHOICES} ta emas.`,
      409,
    );
  }

  const assignment = await prisma.assignment.create({
    data: {
      classroomId: classroom.id,
      testId: test.id,
      title: opts.title?.trim() || test.title,
      mode,
      ...(mode === "ONLINE" && opts.online ? opts.online : {}),
      subjectName: test.subject.name,
      questionIds: test.questionIds,
      answerKey: ordered.map((q) => correctLetter(test.id, q)),
      createdById: opts.createdById,
    },
  });
  await syncSheets(assignment.id);
  return assignment;
}

// Gives every current member of the classroom a sheet (and so a ticket).
// Called at creation and again before printing, so students added to the
// classroom later still get paper. Students who LEFT keep their sheet and
// result — it's their history.
export async function syncSheets(assignmentId: string): Promise<number> {
  const assignment = await prisma.assignment.findUnique({
    where: { id: assignmentId },
    include: {
      classroom: { select: { members: { select: { studentId: true } } } },
      sheets: { select: { studentId: true } },
    },
  });
  if (!assignment) throw new HttpError("Topshiriq topilmadi", 404);

  const have = new Set(assignment.sheets.map((s) => s.studentId));
  const missing = assignment.classroom.members
    .map((m) => m.studentId)
    .filter((id) => !have.has(id));
  if (missing.length === 0) return 0;

  // The ticket embeds the sheet's own sequence number, and ticketNo is
  // required + unique — so reserve the numbers before inserting.
  const reserved = await prisma.$queryRaw<{ seq: bigint }[]>`
    SELECT nextval(pg_get_serial_sequence('"AssignmentSheet"', 'seq')) AS seq
    FROM generate_series(1, ${missing.length}::int)`;
  const year = assignment.createdAt.getUTCFullYear();
  const code = assignmentTicketCode(assignment.seq);

  const created = await prisma.assignmentSheet.createMany({
    data: missing.map((studentId, i) => {
      const seq = Number(reserved[i].seq);
      return { assignmentId, studentId, seq, ticketNo: buildTicketNo(year, code, seq), answers: [] };
    }),
    // A concurrent sync for the same student loses quietly; its reserved
    // number is simply never used.
    skipDuplicates: true,
  });
  return created.count;
}

// After students join a classroom: they get sheets in every live assignment,
// so an online test that's already running shows up in their cabinet.
export async function syncClassroomSheets(classroomId: string) {
  const assignments = await prisma.assignment.findMany({
    where: { classroomId, archived: false },
    select: { id: true },
  });
  for (const a of assignments) await syncSheets(a.id);
}

const ONLINE_HAS_NO_PAPER =
  "Bu online test — javob varag'i chiqarilmaydi va skan tekshirilmaydi.";

async function ensureTemplate(assignmentId: string) {
  const a = await prisma.assignment.findUnique({
    where: { id: assignmentId },
    select: {
      title: true,
      subjectName: true,
      questionIds: true,
      sheetBlankPdf: true,
      sheetFieldBoxes: true,
      sheetBubbleBoxes: true,
      classroom: { select: { name: true } },
    },
  });
  if (!a) throw new HttpError("Topshiriq topilmadi", 404);
  if (a.sheetBlankPdf && a.sheetFieldBoxes && a.sheetBubbleBoxes) {
    return { blankPdf: a.sheetBlankPdf, fieldBoxes: a.sheetFieldBoxes };
  }

  // Varaqdagi doiralar testdagi ENG KO'P variantli savolga qarab chiziladi:
  // 4 variantli savolda ortiqcha doira bo'sh qoladi (kalitda E hech qachon
  // bo'lmaydi), aks holda 5 variantli savolning E javobini belgilab
  // bo'lmasdi.
  const sheetQuestions = await prisma.question.findMany({
    where: { id: { in: a.questionIds } },
    select: { wrongAnswers: true },
  });
  const choiceCount = testChoiceCount(sheetQuestions);

  const template = await createTemplate(`${a.title} — ${a.classroom.name}`.slice(0, 150), [
    { name: a.subjectName, question_count: a.questionIds.length, choice_count: choiceCount },
  ]);

  // Two first downloads racing would both render a template; only the first
  // write sticks, so every printed sheet of this assignment shares one.
  const stored = await prisma.assignment.updateMany({
    where: { id: assignmentId, sheetBlankPdf: null },
    data: {
      sheetBlankPdf: new Uint8Array(template.blankPdf),
      sheetFieldBoxes: template.fieldBoxes,
      sheetBubbleBoxes: template.bubbleBoxes,
    },
  });
  if (stored.count === 0) return ensureTemplate(assignmentId);
  return { blankPdf: template.blankPdf, fieldBoxes: template.fieldBoxes };
}

function sheetParticipant(sheet: {
  ticketNo: string;
  student: { firstName: string; lastName: string | null; birthDate: Date | null; grade: string | null };
}): StampParticipant {
  const b = sheet.student.birthDate;
  return {
    ism: sheet.student.firstName,
    familiya: sheet.student.lastName ?? "",
    kun: b ? String(b.getUTCDate()).padStart(2, "0") : "-",
    oy: b ? String(b.getUTCMonth() + 1).padStart(2, "0") : "-",
    yil: b ? String(b.getUTCFullYear()) : "-",
    sinf: sheet.student.grade ?? "-",
    ticket_no: sheet.ticketNo,
  };
}

// One PDF, one page per student (class register order). Pass studentId to
// reprint a single lost sheet — same ticket, so either copy checks the same.
export async function buildSheetsPdf(assignmentId: string, studentId?: string) {
  await syncSheets(assignmentId);
  const assignment = await prisma.assignment.findUnique({
    where: { id: assignmentId },
    select: { title: true, classroomId: true, mode: true },
  });
  if (!assignment) throw new HttpError("Topshiriq topilmadi", 404);
  if (assignment.mode === "ONLINE") throw new HttpError(ONLINE_HAS_NO_PAPER, 409);

  const sheets = await prisma.assignmentSheet.findMany({
    where: {
      assignmentId,
      ...(studentId ? { studentId } : {}),
      student: { memberships: { some: { classroomId: assignment.classroomId } } },
    },
    include: { student: true },
    orderBy: [{ student: { lastName: "asc" } }, { student: { firstName: "asc" } }],
  });
  if (sheets.length === 0) {
    throw new HttpError("Guruhda o'quvchi yo'q — avval o'quvchilarni qo'shing.", 409);
  }

  const template = await ensureTemplate(assignmentId);
  const pdf = await stampSheets(template, sheets.map(sheetParticipant));
  return { pdf, fileName: `${assignment.title}-javob-varaqlari.pdf` };
}

export type PageOutcome = {
  page: number;
  status: "saved" | "duplicate" | "error";
  message: string;
  studentName?: string;
  correct?: number;
  total?: number;
  percentage?: number;
  blank?: number;
  multi?: number;
};

export async function checkUploadedScan(
  assignmentId: string,
  file: { bytes: Uint8Array; name: string; type: string },
) {
  const a = await prisma.assignment.findUnique({
    where: { id: assignmentId },
    select: {
      id: true,
      subjectName: true,
      answerKey: true,
      sheetFieldBoxes: true,
      sheetBubbleBoxes: true,
      mode: true,
    },
  });
  if (!a) throw new HttpError("Topshiriq topilmadi", 404);
  if (a.mode === "ONLINE") throw new HttpError(ONLINE_HAS_NO_PAPER, 409);
  if (!a.sheetFieldBoxes || !a.sheetBubbleBoxes) {
    throw new HttpError(
      "Bu topshiriq uchun javob varaqlari hali chiqarilmagan — avval «Javob varaqlari (PDF)» ni yuklab oling.",
      409,
    );
  }

  const result = await checkScan(
    { fieldBoxes: a.sheetFieldBoxes, bubbleBoxes: a.sheetBubbleBoxes },
    { [a.subjectName]: a.answerKey },
    file,
  );

  const outcomes: PageOutcome[] = [];
  for (const page of result.pages) {
    if (!page.ok) {
      outcomes.push({ page: page.page, status: "error", message: page.error });
      continue;
    }
    const subject = page.subjects.find((s) => s.name === a.subjectName) ?? page.subjects[0];
    const multi = new Set(subject.multi);
    const answers = subject.answers.map(
      (ans, i) => ans ?? (multi.has(i + 1) ? MULTI_ANSWER : BLANK_ANSWER),
    );

    const sheet = await prisma.assignmentSheet.findUnique({
      where: { ticketNo: page.ticket_no },
      include: {
        student: true,
        assignment: { select: { title: true, classroom: { select: { name: true } } } },
      },
    });
    if (!sheet) {
      outcomes.push({
        page: page.page,
        status: "error",
        message: `${page.ticket_no} — bu ID bo'yicha varaq topilmadi.`,
      });
      continue;
    }
    const studentName = studentDisplayName(sheet.student);
    if (sheet.assignmentId !== a.id) {
      outcomes.push({
        page: page.page,
        status: "error",
        studentName,
        message: `Bu varaq boshqa topshiriqqa tegishli: «${sheet.assignment.title}» (${sheet.assignment.classroom.name}).`,
      });
      continue;
    }

    const grade = gradeAnswers(answers, a.answerKey);
    // Never overwrite a checked sheet (the same page scanned twice, or the
    // same PDF uploaded again) — smartbot DECISIONS.md #31. A wrong result is
    // cleared explicitly with "reset", then scanned again.
    const saved = await prisma.assignmentSheet.updateMany({
      where: { id: sheet.id, checkedAt: null },
      data: { answers, ...grade, checkedAt: new Date() },
    });
    if (saved.count === 0) {
      outcomes.push({
        page: page.page,
        status: "duplicate",
        studentName,
        message: "Allaqachon tekshirilgan — natija qayta yozilmadi.",
      });
      continue;
    }
    outcomes.push({
      page: page.page,
      status: "saved",
      studentName,
      message: "Saqlandi",
      ...grade,
      blank: answers.filter((x) => x === BLANK_ANSWER).length,
      multi: multi.size,
    });
  }

  return { pageCount: result.page_count, outcomes, annotatedPdf: result.annotated_pdf };
}

export async function resetSheetResult(sheetId: string) {
  const sheet = await prisma.assignmentSheet.findUnique({ where: { id: sheetId } });
  if (!sheet) throw new HttpError("Varaq topilmadi", 404);
  return prisma.assignmentSheet.update({
    where: { id: sheetId },
    // Online: also clears the start, so the student gets a fresh attempt and timer.
    data: {
      answers: [],
      correct: null,
      total: null,
      percentage: null,
      checkedAt: null,
      startedAt: null,
      // The next result is news again (src/lib/notifications.ts).
      resultNotifiedAt: null,
    },
  });
}
