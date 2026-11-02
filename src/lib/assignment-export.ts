import ExcelJS from "exceljs";
import { prisma } from "./prisma";
import { finalizeIfExpired } from "./online";
import { formatTashkent, sheetStatus, type SheetStatus } from "./online-core";
import { studentDisplayName } from "./students";
import {
  percent,
  weakThemesOf,
  type ExportAnswer,
  type ExportData,
  type ExportQuestion,
  type ExportStudent,
} from "./assignment-export-core";

// Topshiriq natijalarini yuklab olish: Excel va HTML (docs/DECISIONS.md #34).
// Ma'lumotni shu yerda yig'amiz, ko'rinishini esa assignment-export-core.ts
// (HTML) va pastdagi `buildResultsWorkbook` (Excel) hal qiladi.

const STATUS_LABEL: Record<SheetStatus, string> = {
  checked: "topshirgan",
  in_progress: "yechmoqda",
  available: "boshlamagan",
  not_open: "hali ochilmagan",
  missed: "topshirmadi",
  awaiting_scan: "tekshirilmagan",
};

export async function loadExportData(
  assignmentId: string,
  now = new Date(),
): Promise<ExportData | null> {
  const assignment = await prisma.assignment.findUnique({
    where: { id: assignmentId },
    select: {
      id: true,
      title: true,
      subjectName: true,
      mode: true,
      createdAt: true,
      questionIds: true,
      answerKey: true,
      opensAt: true,
      closesAt: true,
      timeLimitMinutes: true,
      classroom: { select: { name: true, members: { select: { student: true } } } },
      sheets: { include: { student: true } },
    },
  });
  if (!assignment) return null;

  // Vaqti tugagan urinish natijaga aylanadi — sahifadagi bilan bir xil
  // (src/app/classrooms/[id]/assignments/[assignmentId]/page.tsx).
  const sheets = await Promise.all(
    assignment.sheets.map((s) => finalizeIfExpired(assignment, s, now)),
  );
  const sheetOf = new Map(sheets.map((s) => [s.studentId, s]));
  const memberIds = new Set(assignment.classroom.members.map((m) => m.student.id));
  const people = [
    ...assignment.classroom.members.map((m) => ({ student: m.student, sheet: sheetOf.get(m.student.id) ?? null })),
    // Guruhdan chiqqan, lekin testni ishlagan o'quvchi ham ro'yxatda qoladi.
    ...sheets.filter((s) => !memberIds.has(s.studentId)).map((s) => ({ student: s.student, sheet: s })),
  ].sort((a, b) => studentDisplayName(a.student).localeCompare(studentDisplayName(b.student), "uz"));

  const questions = await prisma.question.findMany({
    where: { id: { in: assignment.questionIds } },
    select: { id: true, text: true, themes: { select: { name: true } } },
  });
  const byId = new Map(questions.map((q) => [q.id, q]));
  const meta = assignment.questionIds.map((qid) => ({
    text: byId.get(qid)?.text ?? "(savol o'chirilgan)",
    themes: (byId.get(qid)?.themes ?? []).map((t) => t.name),
  }));

  const checked = sheets.filter((s) => s.checkedAt);
  const percentages = checked.map((s) => s.percentage ?? 0);

  const students: ExportStudent[] = people.map(({ student, sheet }, i) => {
    const status = sheet ? sheetStatus(assignment, sheet, now) : "available";
    const answers: ExportAnswer[] =
      sheet?.checkedAt
        ? assignment.questionIds.map((_, qi) => ({
            n: qi + 1,
            given: sheet.answers[qi] ?? "",
            key: assignment.answerKey[qi] ?? "",
            ok: sheet.answers[qi] === assignment.answerKey[qi],
            text: meta[qi].text,
            themes: meta[qi].themes,
          }))
        : [];
    const minutes =
      sheet?.startedAt && sheet.checkedAt
        ? Math.max(1, Math.round((sheet.checkedAt.getTime() - sheet.startedAt.getTime()) / 60_000))
        : null;
    return {
      n: i + 1,
      name: studentDisplayName(student),
      status: STATUS_LABEL[status],
      correct: sheet?.correct ?? null,
      total: sheet?.total ?? null,
      percentage: sheet?.percentage ?? null,
      startedAt: sheet?.startedAt ? formatTashkent(sheet.startedAt) : null,
      submittedAt: sheet?.checkedAt ? formatTashkent(sheet.checkedAt) : null,
      minutes,
      answers,
      weakThemes: weakThemesOf(answers),
    };
  });

  const exportQuestions: ExportQuestion[] = assignment.questionIds.map((_, qi) => {
    const right = checked.filter((s) => s.answers[qi] === assignment.answerKey[qi]).length;
    return {
      n: qi + 1,
      key: assignment.answerKey[qi] ?? "",
      text: meta[qi].text,
      themes: meta[qi].themes,
      correct: right,
      answered: checked.length,
      // Foiz TEKSHIRILGANLAR soniga nisbatan: bo'sh qoldirilgani ham xato.
      percentage: checked.length ? percent(right, checked.length) : null,
    };
  });

  const themeAcc = new Map<string, { name: string; correct: number; total: number }>();
  for (const s of students) {
    for (const a of s.answers) {
      for (const name of a.themes) {
        const row = themeAcc.get(name) ?? { name, correct: 0, total: 0 };
        row.total += 1;
        if (a.ok) row.correct += 1;
        themeAcc.set(name, row);
      }
    }
  }

  return {
    title: assignment.title,
    subject: assignment.subjectName,
    classroom: assignment.classroom.name,
    mode: assignment.mode,
    createdAt: formatTashkent(assignment.createdAt),
    generatedAt: formatTashkent(now),
    questionCount: assignment.questionIds.length,
    summary: {
      checked: checked.length,
      students: students.length,
      average: percentages.length
        ? Math.round((percentages.reduce((a, b) => a + b, 0) / percentages.length) * 10) / 10
        : null,
      best: percentages.length ? Math.max(...percentages) : null,
      worst: percentages.length ? Math.min(...percentages) : null,
    },
    students,
    questions: exportQuestions,
    themes: [...themeAcc.values()]
      .map((t) => ({ ...t, percentage: percent(t.correct, t.total) ?? 0 }))
      .sort((a, b) => a.percentage - b.percentage || b.total - a.total),
  };
}

const HEADER_FILL: ExcelJS.Fill = {
  type: "pattern",
  pattern: "solid",
  fgColor: { argb: "FFD9D0EF" },
};

function header(sheet: ExcelJS.Worksheet, widths: number[]) {
  sheet.getRow(1).eachCell((cell) => {
    cell.font = { bold: true };
    cell.fill = HEADER_FILL;
    cell.alignment = { vertical: "middle", horizontal: "center", wrapText: true };
  });
  widths.forEach((w, i) => (sheet.getColumn(i + 1).width = w));
  sheet.views = [{ state: "frozen", ySplit: 1 }];
}

// Uchta varaq: o'quvchilar (har savol alohida ustun), savollar va mavzular.
export async function buildResultsWorkbook(data: ExportData): Promise<Buffer> {
  const wb = new ExcelJS.Workbook();
  wb.creator = "SmartAcademy";
  wb.created = new Date();

  const ws = wb.addWorksheet("Natijalar");
  const qHeaders = Array.from({ length: data.questionCount }, (_, i) => `${i + 1}`);
  ws.addRow([
    "№",
    "O'quvchi",
    "Holat",
    "To'g'ri",
    "Jami",
    "Foiz",
    "Boshlagan",
    "Topshirgan",
    "Daqiqa",
    ...qHeaders,
  ]);
  for (const s of data.students) {
    ws.addRow([
      s.n,
      s.name,
      s.status,
      s.correct ?? "-",
      s.total ?? "-",
      s.percentage ?? "-",
      s.startedAt ?? "-",
      s.submittedAt ?? "-",
      s.minutes ?? "-",
      // Har savol: belgilagan javobi (bo'sh bo'lsa "-"), xato bo'lsa qizil.
      ...data.questions.map((q) => {
        const a = s.answers.find((x) => x.n === q.n);
        return a ? (a.given === "" ? "-" : a.given) : "";
      }),
    ]);
  }
  header(ws, [5, 26, 14, 8, 7, 8, 18, 18, 8, ...qHeaders.map(() => 4)]);
  // Xato javoblarni ko'zga tashlanadigan qilamiz — varaqni ochgan
  // o'qituvchi qaysi savol qoqilganini darhol ko'radi.
  data.students.forEach((s, rowIdx) => {
    s.answers.forEach((a, qIdx) => {
      if (a.ok) return;
      const cell = ws.getRow(rowIdx + 2).getCell(10 + qIdx);
      cell.font = { color: { argb: "FFB91C1C" }, bold: true };
      cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFFDE8E8" } };
    });
  });

  const qs = wb.addWorksheet("Savollar");
  qs.addRow(["№", "Savol", "Kalit", "To'g'ri javob bergan", "Tekshirilgan", "Foiz", "Mavzular"]);
  for (const q of data.questions) {
    qs.addRow([q.n, q.text, q.key, q.correct, q.answered, q.percentage ?? "-", q.themes.join(", ")]);
  }
  header(qs, [5, 60, 7, 20, 14, 8, 30]);

  if (data.themes.length) {
    const ts = wb.addWorksheet("Mavzular");
    ts.addRow(["Mavzu", "To'g'ri", "Jami", "Foiz"]);
    for (const t of data.themes) ts.addRow([t.name, t.correct, t.total, t.percentage]);
    header(ts, [34, 10, 8, 8]);
  }

  return Buffer.from(await wb.xlsx.writeBuffer());
}
