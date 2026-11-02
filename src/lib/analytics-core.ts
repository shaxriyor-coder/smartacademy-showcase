import { BLANK_ANSWER, MULTI_ANSWER } from "./answer-key";
import type { SheetStatus } from "./online-core";

// Student and classroom analytics, computed from rows that are already loaded
// — no database here, so tests/analytics-core.test.ts and
// tests/classroom-analytics.test.ts can pin the rules down. Loading lives in
// src/lib/analytics.ts.

// Fewer checked sheets than this in an assignment and its class average stays
// hidden: with two or three results an "average" gives away classmates' scores.
export const CLASS_AVERAGE_MIN = 3;

// Mastery bands, shared by every breakdown and by ScoreBar's colours.
export const STRONG_FROM = 80;
export const WEAK_BELOW = 50;

// A topic with fewer answered questions than this says little; it isn't put
// forward as a "next step".
export const FOCUS_MIN_QUESTIONS = 3;

export type Band = "strong" | "developing" | "weak";

export function bandOf(percentage: number): Band {
  if (percentage >= STRONG_FROM) return "strong";
  if (percentage >= WEAK_BELOW) return "developing";
  return "weak";
}

// Text tone for a score, on the same bands as the meters.
export function scoreTone(percentage: number | null | undefined) {
  if (percentage == null) return "text-muted";
  if (percentage >= STRONG_FROM) return "text-emerald-300";
  if (percentage >= WEAK_BELOW) return "text-gold";
  return "text-red-300";
}

export type Rate = { correct: number; total: number; percentage: number };

export type AnalyticsSheet = {
  id: string;
  assignmentId: string;
  status: SheetStatus;
  mode: "OFFLINE" | "ONLINE";
  title: string;
  subjectName: string;
  classroomName: string;
  startedAt: Date | null;
  checkedAt: Date | null;
  percentage: number | null;
  correct: number | null;
  total: number | null;
  answers: string[];
  answerKey: string[];
  questionIds: string[];
  // Whether this sheet's per-question outcome may be shown yet (the reveal
  // policy). Scores always count; topic/answer breakdowns use only these —
  // otherwise a "yopilgach" test would leak which answers were right.
  detailAllowed: boolean;
  classAverage: number | null;
};

export type QuestionMeta = {
  themes: { id: string; name: string; subjectName: string }[];
  subThemes: { id: string; name: string; themeId: string }[];
  difficulty: { name: string; order: number } | null;
  skills: { id: string; name: string }[];
};

type Tally = { correct: number; total: number };

function toRate(t: Tally): Rate {
  return { ...t, percentage: t.total ? Math.round((t.correct / t.total) * 100) : 0 };
}

export function round1(n: number) {
  return Math.round(n * 10) / 10;
}

export function mean(values: number[]): number | null {
  return values.length ? round1(values.reduce((a, b) => a + b, 0) / values.length) : null;
}

function byWeakest<T extends Rate>(a: T, b: T) {
  return a.percentage - b.percentage || b.total - a.total;
}

// Difficulty levels are per subject, and names drift ("QIyin" / "Qiyin"):
// merge by normalised name and show it in one spelling.
function levelLabel(name: string) {
  const trimmed = name.trim();
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
}

export function computeStudentAnalytics(sheets: AnalyticsSheet[], meta: Map<string, QuestionMeta>) {
  const checked = sheets
    .filter((s): s is AnalyticsSheet & { checkedAt: Date; percentage: number } =>
      Boolean(s.checkedAt) && s.percentage != null,
    )
    .sort((a, b) => a.checkedAt.getTime() - b.checkedAt.getTime());

  const last = checked.at(-1) ?? null;
  const previous = checked.length >= 2 ? checked[checked.length - 2] : null;
  const missed = sheets.filter((s) => s.status === "missed").length;

  const subjects = new Map<string, number[]>();
  for (const s of checked) subjects.set(s.subjectName, [...(subjects.get(s.subjectName) ?? []), s.percentage]);

  const onlineMinutes = checked
    .filter((s) => s.mode === "ONLINE" && s.startedAt)
    .map((s) => (s.checkedAt.getTime() - s.startedAt!.getTime()) / 60_000);

  const detailed = checked.filter((s) => s.detailAllowed);
  const answerMix = { correct: 0, wrong: 0, blank: 0, multi: 0, total: 0 };
  const themes = new Map<
    string,
    { id: string; name: string; subjectName: string; tally: Tally; subThemes: Map<string, { id: string; name: string; tally: Tally }> }
  >();
  const levels = new Map<string, { name: string; order: number; tally: Tally }>();
  const skills = new Map<string, { name: string; tally: Tally }>();

  for (const s of detailed) {
    s.questionIds.forEach((qid, i) => {
      const given = s.answers[i] ?? BLANK_ANSWER;
      const ok = given === s.answerKey[i];
      answerMix.total += 1;
      if (ok) answerMix.correct += 1;
      else if (given === BLANK_ANSWER) answerMix.blank += 1;
      else if (given === MULTI_ANSWER) answerMix.multi += 1;
      else answerMix.wrong += 1;

      const m = meta.get(qid);
      if (!m) return; // deleted from the bank: still scored, just untagged
      const count = (t: Tally) => {
        t.total += 1;
        if (ok) t.correct += 1;
      };

      for (const theme of m.themes) {
        const entry = themes.get(theme.id) ?? { ...theme, tally: { correct: 0, total: 0 }, subThemes: new Map() };
        count(entry.tally);
        for (const sub of m.subThemes.filter((st) => st.themeId === theme.id)) {
          const subEntry = entry.subThemes.get(sub.id) ?? { id: sub.id, name: sub.name, tally: { correct: 0, total: 0 } };
          count(subEntry.tally);
          entry.subThemes.set(sub.id, subEntry);
        }
        themes.set(theme.id, entry);
      }
      if (m.difficulty) {
        const key = m.difficulty.name.trim().toLowerCase();
        const entry = levels.get(key) ?? { name: levelLabel(m.difficulty.name), order: m.difficulty.order, tally: { correct: 0, total: 0 } };
        entry.order = Math.max(entry.order, m.difficulty.order);
        count(entry.tally);
        levels.set(key, entry);
      }
      for (const skill of m.skills) {
        const entry = skills.get(skill.id) ?? { name: skill.name, tally: { correct: 0, total: 0 } };
        count(entry.tally);
        skills.set(skill.id, entry);
      }
    });
  }

  const themeRates = [...themes.values()]
    .map((t) => ({
      id: t.id,
      name: t.name,
      subjectName: t.subjectName,
      ...toRate(t.tally),
      band: bandOf(toRate(t.tally).percentage),
      subThemes: [...t.subThemes.values()].map((st) => ({ id: st.id, name: st.name, ...toRate(st.tally) })).sort(byWeakest),
    }))
    .sort(byWeakest);

  return {
    counts: {
      assigned: sheets.length,
      checked: checked.length,
      missed,
      pending: sheets.length - checked.length - missed,
    },
    average: mean(checked.map((s) => s.percentage)),
    last: last ? { title: last.title, percentage: last.percentage } : null,
    change: last && previous ? round1(last.percentage - previous.percentage) : null,
    vsClass: mean(
      checked.filter((s) => s.classAverage != null).map((s) => s.percentage - s.classAverage!),
    ),
    onlineMinutes: mean(onlineMinutes),
    timeline: checked.map((s) => ({
      id: s.id,
      title: s.title,
      subjectName: s.subjectName,
      classroomName: s.classroomName,
      mode: s.mode,
      date: s.checkedAt.toISOString(),
      percentage: s.percentage,
      correct: s.correct,
      total: s.total,
      classAverage: s.classAverage,
    })),
    subjects: [...subjects.entries()]
      .map(([name, values]) => ({ name, tests: values.length, average: mean(values)! }))
      .sort((a, b) => a.average - b.average),
    answerMix,
    themes: themeRates,
    difficulty: [...levels.values()]
      .map((l) => ({ name: l.name, order: l.order, ...toRate(l.tally) }))
      .sort((a, b) => a.order - b.order || a.name.localeCompare(b.name)),
    skills: [...skills.values()].map((s) => ({ name: s.name, ...toRate(s.tally) })).sort(byWeakest),
    // Next steps: the weakest topics with enough questions to mean something.
    focus: themeRates.filter((t) => t.total >= FOCUS_MIN_QUESTIONS && t.percentage < STRONG_FROM).slice(0, 3),
    hiddenDetails: checked.length - detailed.length,
  };
}

export type StudentAnalytics = ReturnType<typeof computeStudentAnalytics>;

// ---------------------------------------------------------------------------
// Classroom (teacher) analytics

// A drop of this many points from one test to the next puts a student on the
// attention list even if their average is still fine.
export const DROP_ALERT = 15;
export const HARDEST_QUESTIONS = 5;

export type ClassroomSheet = {
  id: string;
  studentId: string;
  status: SheetStatus;
  startedAt: Date | null;
  checkedAt: Date | null;
  percentage: number | null;
  correct: number | null;
  total: number | null;
  answers: string[];
};

export type ClassroomAssignment = {
  id: string;
  title: string;
  subjectName: string;
  mode: "OFFLINE" | "ONLINE";
  createdAt: Date;
  questionIds: string[];
  answerKey: string[];
  sheets: ClassroomSheet[];
};

// Group picture for the teacher, built on computeStudentAnalytics so every
// number means the same thing on both sides. Teachers see every checked
// answer, so there is no reveal-policy filtering here.
export function computeClassroomAnalytics(
  members: { id: string; name: string }[],
  assignments: ClassroomAssignment[],
  meta: Map<string, QuestionMeta>,
) {
  const rows = assignments.flatMap((a) =>
    a.sheets.map((s) => ({
      studentId: s.studentId,
      sheet: {
        id: s.id,
        assignmentId: a.id,
        status: s.status,
        mode: a.mode,
        title: a.title,
        subjectName: a.subjectName,
        classroomName: "",
        startedAt: s.startedAt,
        checkedAt: s.checkedAt,
        percentage: s.percentage,
        correct: s.correct,
        total: s.total,
        answers: s.answers,
        answerKey: a.answerKey,
        questionIds: a.questionIds,
        detailAllowed: true,
        classAverage: null,
      } satisfies AnalyticsSheet,
    })),
  );
  const group = computeStudentAnalytics(rows.map((r) => r.sheet), meta);

  const chronological = [...assignments].sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime());
  const perAssignment = chronological.map((a) => {
    const scores = a.sheets.filter((s) => s.checkedAt && s.percentage != null).map((s) => s.percentage!);
    const missed = a.sheets.filter((s) => s.status === "missed").length;
    return {
      id: a.id,
      title: a.title,
      subjectName: a.subjectName,
      mode: a.mode,
      createdAt: a.createdAt,
      assigned: a.sheets.length,
      checked: scores.length,
      missed,
      pending: a.sheets.length - scores.length - missed,
      average: mean(scores),
      min: scores.length ? Math.min(...scores) : null,
      max: scores.length ? Math.max(...scores) : null,
    };
  });
  const scored = perAssignment.filter((a) => a.average != null);
  const lastTest = scored.at(-1);
  const previousTest = scored.at(-2);

  const students = members
    .map((m) => {
      const s = computeStudentAnalytics(rows.filter((r) => r.studentId === m.id).map((r) => r.sheet), meta);
      const weakest = s.themes.find((t) => t.total >= FOCUS_MIN_QUESTIONS && t.percentage < STRONG_FROM);
      return {
        id: m.id,
        name: m.name,
        assigned: s.counts.assigned,
        checked: s.counts.checked,
        missed: s.counts.missed,
        average: s.average,
        last: s.last?.percentage ?? null,
        change: s.change,
        weakestTopic: weakest ? { name: weakest.name, percentage: weakest.percentage } : null,
      };
    })
    // Weakest first — that's who the teacher is looking for; no results last.
    .sort(
      (x, y) =>
        (x.average ?? Number.POSITIVE_INFINITY) - (y.average ?? Number.POSITIVE_INFINITY) ||
        x.name.localeCompare(y.name),
    );

  const withAverage = students.filter((s) => s.average != null);
  const attention = withAverage
    .filter((s) => s.average! < WEAK_BELOW || (s.change != null && s.change <= -DROP_ALERT))
    .map((s) => ({ ...s, reason: s.average! < WEAK_BELOW ? ("low" as const) : ("drop" as const) }));

  // Questions most of the class got wrong, where enough students answered.
  // Ties keep test order, oldest first.
  const hardest = chronological
    .flatMap((a) => {
      const checked = a.sheets.filter((s) => s.checkedAt);
      if (checked.length < CLASS_AVERAGE_MIN) return [];
      return a.questionIds.map((qid, i) => {
        const correct = checked.filter((s) => s.answers[i] === a.answerKey[i]).length;
        return {
          key: `${a.id}:${i}`,
          assignmentId: a.id,
          assignmentTitle: a.title,
          number: i + 1,
          answer: a.answerKey[i],
          themes: (meta.get(qid)?.themes ?? []).map((t) => t.name),
          correct,
          total: checked.length,
          percentage: Math.round((correct / checked.length) * 100),
        };
      });
    })
    .sort((x, y) => x.percentage - y.percentage || y.total - x.total)
    .slice(0, HARDEST_QUESTIONS);

  const settled = group.counts.checked + group.counts.missed;

  return {
    members: members.length,
    average: group.average,
    change: lastTest && previousTest ? round1(lastTest.average! - previousTest.average!) : null,
    // Of the chances that are over (checked or missed); open tests aren't counted against the class.
    completion: settled ? Math.round((group.counts.checked / settled) * 100) : null,
    counts: group.counts,
    assignments: perAssignment,
    students,
    distribution: {
      weak: withAverage.filter((s) => bandOf(s.average!) === "weak").length,
      developing: withAverage.filter((s) => bandOf(s.average!) === "developing").length,
      strong: withAverage.filter((s) => bandOf(s.average!) === "strong").length,
      noResults: students.length - withAverage.length,
    },
    attention,
    hardest,
    themes: group.themes,
    difficulty: group.difficulty,
    skills: group.skills,
    answerMix: group.answerMix,
  };
}

export type ClassroomAnalytics = ReturnType<typeof computeClassroomAnalytics>;
