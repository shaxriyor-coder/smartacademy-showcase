import { BLANK_ANSWER, MULTI_ANSWER } from "./answer-key";
import {
  DROP_ALERT,
  FOCUS_MIN_QUESTIONS,
  STRONG_FROM,
  WEAK_BELOW,
  bandOf,
  computeStudentAnalytics,
  mean,
  round1,
  type AnalyticsSheet,
  type QuestionMeta,
  type StudentAnalytics,
} from "./analytics-core";
import type { SheetStatus } from "./online-core";
import type { StaffRole } from "./roles";

// Centre-wide analytics for admins (docs/DECISIONS.md #20): students across
// every classroom, teachers, and the question bank. Pure, like
// analytics-core; loading lives in src/lib/center-analytics.ts.

export const RECENT_DAYS = 30;
export const TREND_WEEKS = 12;
// "Best results" needs a steady record, not one lucky test.
export const TOP_MIN_TESTS = 2;
export const TOP_STUDENTS = 10;
// Per-question rates need enough answers to mean anything.
export const MIN_RESPONSES = 5;
export const HARDEST_QUESTIONS = 10;
export const THIN_THEME = 10;
// A likely wrong key: few found the "right" answer while most agreed on
// another one.
export const KEY_SUSPECT_SHARE = 0.6;
export const KEY_SUSPECT_CORRECT_BELOW = 0.25;

const DAY_MS = 86_400_000;
const TASHKENT_OFFSET_MS = 5 * 3_600_000; // UTC+5, no daylight saving

export type CenterSheet = {
  id: string;
  studentId: string;
  teacherId: string;
  assignmentId: string;
  mode: "OFFLINE" | "ONLINE";
  title: string;
  subjectName: string;
  status: SheetStatus;
  startedAt: Date | null;
  checkedAt: Date | null;
  percentage: number | null;
  correct: number | null;
  total: number | null;
  answers: string[];
  answerKey: string[];
  questionIds: string[];
};

type Checked = CenterSheet & { checkedAt: Date; percentage: number };

const isChecked = (s: CenterSheet): s is Checked => s.checkedAt != null && s.percentage != null;

// Age in [fromDays, toDays) before `now`.
function within(date: Date | null, now: Date, fromDays: number, toDays: number) {
  if (!date) return false;
  const age = now.getTime() - date.getTime();
  return age >= fromDays * DAY_MS && age < toDays * DAY_MS;
}
const isRecent = (date: Date | null, now: Date) => within(date, now, 0, RECENT_DAYS);

const percentOf = (part: number, whole: number) => (whole ? Math.round((part / whole) * 100) : null);

function groupBy<T>(items: T[], key: (item: T) => string) {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const k = key(item);
    const list = groups.get(k);
    if (list) list.push(item);
    else groups.set(k, [item]);
  }
  return groups;
}

function latest(dates: Date[]): Date | null {
  let best: number | null = null;
  for (const d of dates) if (best == null || d.getTime() > best) best = d.getTime();
  return best == null ? null : new Date(best);
}

// Monday 00:00 in Tashkent, as a UTC instant.
export function tashkentWeekStart(date: Date): Date {
  const local = new Date(date.getTime() + TASHKENT_OFFSET_MS);
  const back = (local.getUTCDay() + 6) % 7;
  return new Date(
    Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() - back) - TASHKENT_OFFSET_MS,
  );
}

function toAnalyticsSheet(s: CenterSheet): AnalyticsSheet {
  return {
    id: s.id,
    assignmentId: s.assignmentId,
    status: s.status,
    mode: s.mode,
    title: s.title,
    subjectName: s.subjectName,
    classroomName: "",
    startedAt: s.startedAt,
    checkedAt: s.checkedAt,
    percentage: s.percentage,
    correct: s.correct,
    total: s.total,
    answers: s.answers,
    answerKey: s.answerKey,
    questionIds: s.questionIds,
    // Staff-only view: the reveal policy is about what students see.
    detailAllowed: true,
    classAverage: null,
  };
}

function weakestTopic(themes: StudentAnalytics["themes"]) {
  const t = themes.find((x) => x.total >= FOCUS_MIN_QUESTIONS && x.percentage < STRONG_FROM);
  return t ? { name: t.name, percentage: t.percentage } : null;
}

// ---------------------------------------------------------------------------
// Students across the centre

export function computeCenterAnalytics(
  students: { id: string; name: string; teachers: string[] }[],
  sheets: CenterSheet[],
  meta: Map<string, QuestionMeta>,
  now: Date,
) {
  const all = computeStudentAnalytics(sheets.map(toAnalyticsSheet), meta);
  const checked = sheets.filter(isChecked);
  const byStudent = groupBy(sheets, (s) => s.studentId);

  const rows = students.map((st) => {
    const a = computeStudentAnalytics((byStudent.get(st.id) ?? []).map(toAnalyticsSheet), meta);
    return {
      id: st.id,
      name: st.name,
      teachers: st.teachers,
      checked: a.counts.checked,
      missed: a.counts.missed,
      average: a.average,
      last: a.last?.percentage ?? null,
      change: a.change,
      weakestTopic: weakestTopic(a.themes),
    };
  });
  const withAverage = rows.filter((r): r is typeof r & { average: number } => r.average != null);

  const recent = checked.filter((s) => isRecent(s.checkedAt, now));
  const previous = checked.filter((s) => within(s.checkedAt, now, RECENT_DAYS, 2 * RECENT_DAYS));
  const recentAverage = mean(recent.map((s) => s.percentage));
  const previousAverage = mean(previous.map((s) => s.percentage));
  const activeIds = new Set(recent.map((s) => s.studentId));

  const firstWeek = tashkentWeekStart(new Date(now.getTime() - (TREND_WEEKS - 1) * 7 * DAY_MS));
  const weeks = groupBy(
    checked.filter((s) => s.checkedAt >= firstWeek),
    (s) => String(tashkentWeekStart(s.checkedAt).getTime()),
  );
  const trend = [...weeks.entries()]
    .map(([start, list]) => ({
      weekStart: new Date(Number(start)),
      results: list.length,
      average: mean(list.map((s) => s.percentage))!,
    }))
    .sort((a, b) => a.weekStart.getTime() - b.weekStart.getTime());

  const subjects = [...groupBy(checked, (s) => s.subjectName).entries()]
    .map(([name, list]) => ({
      name,
      students: new Set(list.map((s) => s.studentId)).size,
      results: list.length,
      average: mean(list.map((s) => s.percentage))!,
    }))
    .sort((a, b) => b.results - a.results || a.name.localeCompare(b.name));

  const settled = all.counts.checked + all.counts.missed;

  return {
    counts: {
      students: students.length,
      activeStudents: students.filter((s) => activeIds.has(s.id)).length,
      results: all.counts.checked,
      recentResults: recent.length,
      missed: all.counts.missed,
      pending: all.counts.pending,
    },
    average: all.average,
    recentAverage,
    previousAverage,
    change: recentAverage != null && previousAverage != null ? round1(recentAverage - previousAverage) : null,
    completion: settled ? Math.round((all.counts.checked / settled) * 100) : null,
    trend,
    distribution: {
      weak: withAverage.filter((r) => bandOf(r.average) === "weak").length,
      developing: withAverage.filter((r) => bandOf(r.average) === "developing").length,
      strong: withAverage.filter((r) => bandOf(r.average) === "strong").length,
      noResults: rows.length - withAverage.length,
    },
    subjects,
    attention: withAverage
      .filter((r) => r.average < WEAK_BELOW || (r.change != null && r.change <= -DROP_ALERT))
      .map((r) => ({ ...r, reason: r.average < WEAK_BELOW ? ("low" as const) : ("drop" as const) }))
      .sort((a, b) => a.average - b.average || a.name.localeCompare(b.name)),
    top: withAverage
      .filter((r) => r.checked >= TOP_MIN_TESTS && r.average >= STRONG_FROM)
      .sort((a, b) => b.average - a.average || b.checked - a.checked || a.name.localeCompare(b.name))
      .slice(0, TOP_STUDENTS),
    themes: all.themes,
    difficulty: all.difficulty,
    skills: all.skills,
    answerMix: all.answerMix,
  };
}

export type CenterAnalytics = ReturnType<typeof computeCenterAnalytics>;

// ---------------------------------------------------------------------------
// Teachers

export type TeacherInput = {
  staff: { id: string; name: string; role: StaffRole; canTeach?: boolean }[];
  classrooms: { id: string; teacherId: string; studentIds: string[] }[];
  assignments: { id: string; teacherId: string; mode: "OFFLINE" | "ONLINE"; createdAt: Date }[];
  sheets: CenterSheet[];
  questions: { createdById: string; createdAt: Date }[];
  tests: { createdById: string; createdAt: Date }[];
};

export function computeTeacherAnalytics(input: TeacherInput, now: Date) {
  const classroomsBy = groupBy(input.classrooms, (c) => c.teacherId);
  const assignmentsBy = groupBy(input.assignments, (a) => a.teacherId);
  const sheetsBy = groupBy(input.sheets, (s) => s.teacherId);
  const questionsBy = groupBy(input.questions, (q) => q.createdById);
  const testsBy = groupBy(input.tests, (t) => t.createdById);

  const rows = input.staff
    // Anyone else who still owns classrooms is shown too, flagged: those
    // groups need handing to a teacher.
    .filter((u) => u.role === "TEACHER" || u.canTeach || classroomsBy.has(u.id))
    .map((u) => {
      const rooms = classroomsBy.get(u.id) ?? [];
      const assignments = assignmentsBy.get(u.id) ?? [];
      const sheets = sheetsBy.get(u.id) ?? [];
      const checked = sheets.filter(isChecked);
      const missed = sheets.filter((s) => s.status === "missed").length;
      const questions = questionsBy.get(u.id) ?? [];
      const tests = testsBy.get(u.id) ?? [];
      const studentAverages = [...groupBy(checked, (s) => s.studentId).values()].map(
        (list) => mean(list.map((s) => s.percentage))!,
      );
      const lastActivity = latest([
        ...assignments.map((a) => a.createdAt),
        ...checked.map((s) => s.checkedAt),
        ...questions.map((q) => q.createdAt),
        ...tests.map((t) => t.createdAt),
      ]);

      return {
        id: u.id,
        name: u.name,
        // Guruh yuritadigan har kishi — o'qituvchi rolidagilar ham,
        // `canTeach` berilgan adminlar ham (DECISIONS.md #30).
        isTeacher: u.role === "TEACHER" || Boolean(u.canTeach),
        classrooms: rooms.length,
        students: new Set(rooms.flatMap((r) => r.studentIds)).size,
        assignments: assignments.length,
        online: assignments.filter((a) => a.mode === "ONLINE").length,
        recentAssignments: assignments.filter((a) => isRecent(a.createdAt, now)).length,
        results: checked.length,
        recentResults: checked.filter((s) => isRecent(s.checkedAt, now)).length,
        completion: percentOf(checked.length, checked.length + missed),
        average: mean(checked.map((s) => s.percentage)),
        weakStudents: studentAverages.filter((avg) => avg < WEAK_BELOW).length,
        questions: questions.length,
        recentQuestions: questions.filter((q) => isRecent(q.createdAt, now)).length,
        tests: tests.length,
        lastActivity,
        active: isRecent(lastActivity, now),
      };
    })
    .sort(
      (a, b) =>
        Number(b.isTeacher) - Number(a.isTeacher) || b.students - a.students || a.name.localeCompare(b.name),
    );

  const teachers = rows.filter((r) => r.isTeacher);
  return {
    teachers: teachers.length,
    activeTeachers: teachers.filter((r) => r.active).length,
    otherOwners: rows.length - teachers.length,
    recentAssignments: rows.reduce((n, r) => n + r.recentAssignments, 0),
    recentResults: rows.reduce((n, r) => n + r.recentResults, 0),
    average: mean(input.sheets.filter(isChecked).map((s) => s.percentage)),
    rows,
  };
}

export type TeacherAnalytics = ReturnType<typeof computeTeacherAnalytics>;

// ---------------------------------------------------------------------------
// Question bank

export type BankQuestion = {
  id: string;
  text: string;
  subjectName: string;
  themeIds: string[];
  themeNames: string[];
  subThemeCount: number;
  skillCount: number;
  difficulty: { name: string; order: number };
  optionCount: number;
  createdAt: Date;
  author: { id: string; name: string };
};

export type BankInput = {
  questions: BankQuestion[];
  // Every theme in the categories, so a theme with no questions still shows.
  themes: { id: string; name: string; subjectName: string }[];
  tests: { questionIds: string[] }[];
  // Checked sheets only: `answers` holds one canonical answer list per sheet.
  assignments: { id: string; title: string; questionIds: string[]; answerKey: string[]; answers: string[][] }[];
  // Testga tushishi mumkin bo'lgan variantlar soni (4 va/yoki 5).
  choiceCounts: number[];
};

const snippet = (text: string) => (text.length > 140 ? `${text.slice(0, 140).trimEnd()}…` : text);

export function computeQuestionBankAnalytics(input: BankInput, now: Date) {
  const { questions, choiceCounts } = input;
  const byId = new Map(questions.map((q) => [q.id, q]));

  const testUses = new Map<string, number>();
  for (const t of input.tests) for (const id of new Set(t.questionIds)) testUses.set(id, (testUses.get(id) ?? 0) + 1);

  // Outcomes per question across every checked sheet, and per printed
  // position for the key check (letters mean the same only within one assignment).
  const outcomes = new Map<string, { responses: number; correct: number }>();
  const suspects = new Map<
    string,
    { questionId: string; assignmentTitle: string; number: number; key: string; popular: string; share: number; correctShare: number }
  >();
  for (const a of input.assignments) {
    a.questionIds.forEach((qid, i) => {
      const letters = new Map<string, number>();
      let correct = 0;
      for (const answers of a.answers) {
        const given = answers[i] ?? BLANK_ANSWER;
        if (given === a.answerKey[i]) correct += 1;
        else if (given !== BLANK_ANSWER && given !== MULTI_ANSWER) letters.set(given, (letters.get(given) ?? 0) + 1);
      }
      const responses = a.answers.length;
      if (responses === 0) return;
      const o = outcomes.get(qid) ?? { responses: 0, correct: 0 };
      o.responses += responses;
      o.correct += correct;
      outcomes.set(qid, o);

      if (responses < MIN_RESPONSES || correct / responses >= KEY_SUSPECT_CORRECT_BELOW) return;
      const [popular, count] = [...letters.entries()].sort((x, y) => y[1] - x[1])[0] ?? ["", 0];
      if (count / responses < KEY_SUSPECT_SHARE) return;
      const share = Math.round((count / responses) * 100);
      const existing = suspects.get(qid);
      if (!existing || share > existing.share) {
        suspects.set(qid, {
          questionId: qid,
          assignmentTitle: a.title,
          number: i + 1,
          key: a.answerKey[i],
          popular,
          share,
          correctShare: Math.round((correct / responses) * 100),
        });
      }
    });
  }

  const responses = [...outcomes.values()].reduce((n, o) => n + o.responses, 0);
  const correct = [...outcomes.values()].reduce((n, o) => n + o.correct, 0);
  const notAssignable = questions.filter((q) => !choiceCounts.includes(q.optionCount));

  const subjectNames = [...new Set([...input.themes.map((t) => t.subjectName), ...questions.map((q) => q.subjectName)])];
  const subjects = subjectNames
    .map((name) => {
      const list = questions.filter((q) => q.subjectName === name);
      const answered = list.map((q) => outcomes.get(q.id)).filter((o) => o != null);
      const subjectResponses = answered.reduce((n, o) => n + o.responses, 0);
      return {
        name,
        questions: list.length,
        themes: input.themes.filter((t) => t.subjectName === name).length,
        unused: list.filter((q) => !testUses.has(q.id)).length,
        recent: list.filter((q) => isRecent(q.createdAt, now)).length,
        responses: subjectResponses,
        correctRate: percentOf(answered.reduce((n, o) => n + o.correct, 0), subjectResponses),
        // Levels are per subject and their spelling drifts: merge by name.
        difficulty: [...groupBy(list, (q) => q.difficulty.name.trim().toLowerCase()).values()]
          .map((qs) => ({
            name: qs[0].difficulty.name.trim(),
            order: Math.max(...qs.map((q) => q.difficulty.order)),
            count: qs.length,
          }))
          .sort((x, y) => x.order - y.order),
      };
    })
    .sort((a, b) => b.questions - a.questions || a.name.localeCompare(b.name));

  const themeCounts = new Map<string, number>();
  for (const q of questions) for (const id of q.themeIds) themeCounts.set(id, (themeCounts.get(id) ?? 0) + 1);
  const coverage = input.themes
    .map((t) => ({ ...t, questions: themeCounts.get(t.id) ?? 0 }))
    .sort((a, b) => a.questions - b.questions || a.subjectName.localeCompare(b.subjectName) || a.name.localeCompare(b.name));

  const hardest = [...outcomes.entries()]
    .filter(([id, o]) => byId.has(id) && o.responses >= MIN_RESPONSES)
    .map(([id, o]) => {
      const q = byId.get(id)!;
      return {
        id,
        text: snippet(q.text),
        subjectName: q.subjectName,
        themes: q.themeNames,
        responses: o.responses,
        percentage: Math.round((o.correct / o.responses) * 100),
        tests: testUses.get(id) ?? 0,
      };
    })
    .sort((a, b) => a.percentage - b.percentage || b.responses - a.responses)
    .slice(0, HARDEST_QUESTIONS);

  const authors = [...groupBy(questions, (q) => q.author.id).values()]
    .map((list) => ({
      id: list[0].author.id,
      name: list[0].author.name,
      questions: list.length,
      recent: list.filter((q) => isRecent(q.createdAt, now)).length,
    }))
    .sort((a, b) => b.questions - a.questions || a.name.localeCompare(b.name));

  return {
    totals: {
      questions: questions.length,
      recent: questions.filter((q) => isRecent(q.createdAt, now)).length,
      inTests: questions.filter((q) => testUses.has(q.id)).length,
      unused: questions.filter((q) => !testUses.has(q.id)).length,
      usedShare: percentOf(questions.filter((q) => testUses.has(q.id)).length, questions.length),
      answered: [...outcomes.keys()].filter((id) => byId.has(id)).length,
      responses,
      correctRate: percentOf(correct, responses),
    },
    quality: {
      notAssignable: notAssignable.length,
      notAssignableSamples: notAssignable.slice(0, 5).map((q) => ({ id: q.id, text: snippet(q.text), options: q.optionCount })),
      noSubThemes: questions.filter((q) => q.subThemeCount === 0).length,
      noSkills: questions.filter((q) => q.skillCount === 0).length,
    },
    subjects,
    coverage,
    thinThemes: coverage.filter((t) => t.questions < THIN_THEME).length,
    hardest,
    suspectKeys: [...suspects.values()]
      .filter((s) => byId.has(s.questionId))
      .map((s) => ({ ...s, text: snippet(byId.get(s.questionId)!.text) }))
      .sort((a, b) => b.share - a.share),
    authors,
  };
}

export type QuestionBankAnalytics = ReturnType<typeof computeQuestionBankAnalytics>;
