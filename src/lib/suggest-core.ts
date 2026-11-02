import { FOCUS_MIN_QUESTIONS, STRONG_FROM, WEAK_BELOW } from "./analytics-core";
import { seededShuffle } from "./shuffle";

// "O'quvchiga qarab" test (docs/DECISIONS.md #25): from how a student or a
// group did per topic, propose questions — more from weak topics, some from
// untested ones, questions they haven't had first, difficulty mixed. Pure;
// loading lives in src/lib/suggest.ts.

export const MIN_COUNT = 5;
export const MAX_COUNT = 60;
export const ALTERNATES_PER_THEME = 10;
export const OTHER_THEME = "other";

export type Standing = "weak" | "developing" | "strong" | "few" | "untested";

// A topic's share of the test follows how the target did in it: the weaker,
// the bigger. Untested and barely tested topics still get a fair share, so the
// test also finds out what isn't known yet.
export function themeStanding(t: { correct: number; total: number } | undefined): {
  standing: Standing;
  rate: number | null;
  weight: number;
} {
  if (!t || t.total === 0) return { standing: "untested", rate: null, weight: 0.35 };
  const rate = Math.round((t.correct / t.total) * 100);
  if (t.total < FOCUS_MIN_QUESTIONS) return { standing: "few", rate, weight: 0.5 };
  const standing = rate < WEAK_BELOW ? "weak" : rate < STRONG_FROM ? "developing" : "strong";
  return { standing, rate, weight: Math.max(0.1, 1 - rate / 100) };
}

export type Candidate = { id: string; themeIds: string[]; difficultyOrder: number; optionCount: number };

export type SuggestInput = {
  themes: { id: string; name: string }[];
  stats: Map<string, { correct: number; total: number }>;
  candidates: Candidate[];
  // How many of the target students have already had each question.
  seen: Map<string, number>;
  count: number;
  // Testga tushishi mumkin bo'lgan variantlar soni (4 va/yoki 5).
  choiceCounts: number[];
  seed: string;
};

type ThemeInfo = { id: string; name: string } & ReturnType<typeof themeStanding>;

// One of each difficulty level in turn — easiest first for a weak topic,
// hardest first for a strong one — so any prefix of the list is mixed.
function interleave(items: Candidate[], hardestFirst: boolean) {
  const levels = new Map<number, Candidate[]>();
  for (const q of items) levels.set(q.difficultyOrder, [...(levels.get(q.difficultyOrder) ?? []), q]);
  const order = [...levels.keys()].sort((a, b) => (hardestFirst ? b - a : a - b));
  const out: Candidate[] = [];
  for (let i = 0; out.length < items.length; i++) {
    for (const level of order) {
      const q = levels.get(level)![i];
      if (q) out.push(q);
    }
  }
  return out;
}

export function suggestQuestions(input: SuggestInput) {
  const info = new Map<string, ThemeInfo>(
    input.themes.map((t) => [t.id, { ...t, ...themeStanding(input.stats.get(t.id)) }]),
  );
  const other: ThemeInfo = { id: OTHER_THEME, name: "Mavzusiz", standing: "untested", rate: null, weight: 0.2 };

  // Each assignable question counts toward its weakest topic.
  const pools = new Map<string, Candidate[]>();
  for (const q of input.candidates) {
    if (!input.choiceCounts.includes(q.optionCount)) continue;
    const own = q.themeIds.map((id) => info.get(id)).filter((t): t is ThemeInfo => t != null);
    const home = own.length ? own.reduce((a, b) => (b.weight > a.weight ? b : a)) : other;
    pools.set(home.id, [...(pools.get(home.id) ?? []), q]);
  }

  // Within a topic: questions fewest of them have had first, then mixed difficulty.
  const ranked = new Map<string, Candidate[]>();
  for (const [themeId, pool] of pools) {
    const theme = info.get(themeId) ?? other;
    const shuffled = seededShuffle(`${input.seed}:${themeId}`, pool);
    const bySeen = new Map<number, Candidate[]>();
    for (const q of shuffled) {
      const n = input.seen.get(q.id) ?? 0;
      bySeen.set(n, [...(bySeen.get(n) ?? []), q]);
    }
    ranked.set(
      themeId,
      [...bySeen.keys()].sort((a, b) => a - b).flatMap((n) => interleave(bySeen.get(n)!, theme.standing === "strong")),
    );
  }

  type Entry = { theme: ThemeInfo; available: number; unseen: number; slots: number };
  const entries: Entry[] = [...ranked.entries()].map(([id, list]) => ({
    theme: info.get(id) ?? other,
    available: list.length,
    unseen: list.filter((q) => !input.seen.get(q.id)).length,
    slots: 0,
  }));

  // Slots by weight (largest remainder) up to each topic's cap; what a topic
  // can't take goes to the rest.
  function fill(want: number, cap: (e: Entry) => number) {
    let remaining = want - entries.reduce((n, e) => n + e.slots, 0);
    while (remaining > 0) {
      const open = entries.filter((e) => e.slots < cap(e));
      if (open.length === 0) break;
      const weightSum = open.reduce((n, e) => n + e.theme.weight, 0);
      const shares = open.map((e) => {
        const exact = (remaining * e.theme.weight) / weightSum;
        return { e, whole: Math.min(Math.floor(exact), cap(e) - e.slots), fraction: exact - Math.floor(exact) };
      });
      let left = remaining;
      for (const s of shares) {
        s.e.slots += s.whole;
        left -= s.whole;
      }
      const byFraction = [...shares].sort(
        (a, b) => b.fraction - a.fraction || b.e.theme.weight - a.e.theme.weight || a.e.theme.name.localeCompare(b.e.theme.name),
      );
      for (const s of byFraction) {
        if (left === 0) break;
        if (s.e.slots < cap(s.e)) {
          s.e.slots += 1;
          left -= 1;
        }
      }
      const next = want - entries.reduce((n, e) => n + e.slots, 0);
      if (next === remaining) break;
      remaining = next;
    }
  }

  const count = Math.min(Math.max(Math.round(input.count), MIN_COUNT), MAX_COUNT);
  // Questions nobody in the target has had come first across ALL topics; a
  // weak topic that runs out of fresh ones lends its slots to the others, and
  // questions they've had are used only once fresh ones run out everywhere.
  fill(Math.min(count, entries.reduce((n, e) => n + e.unseen, 0)), (e) => e.unseen);
  fill(Math.min(count, entries.reduce((n, e) => n + e.available, 0)), (e) => e.available);

  const picked = entries.flatMap((e) => ranked.get(e.theme.id)!.slice(0, e.slots).map((q) => ({ q, theme: e.theme })));
  // Topics mixed through the test, not in blocks.
  const questions = seededShuffle(`${input.seed}:order`, picked).map(({ q, theme }) => ({
    id: q.id,
    themeKey: theme.id,
    standing: theme.standing,
    rate: theme.rate,
    seen: input.seen.get(q.id) ?? 0,
  }));

  const inPlan = new Set(entries.map((e) => e.theme.id));
  const plan = [
    ...entries.map((e) => ({ themeKey: e.theme.id, name: e.theme.name, standing: e.theme.standing, rate: e.theme.rate, slots: e.slots, available: e.available })),
    // A weak topic with nothing in the bank is worth saying out loud.
    ...[...info.values()]
      .filter((t) => !inPlan.has(t.id) && (t.standing === "weak" || t.standing === "developing"))
      .map((t) => ({ themeKey: t.id, name: t.name, standing: t.standing, rate: t.rate, slots: 0, available: 0 })),
  ].sort((a, b) => b.slots - a.slots || (a.rate ?? 101) - (b.rate ?? 101) || a.name.localeCompare(b.name));

  return {
    questions,
    alternates: Object.fromEntries(
      entries.map((e) => [e.theme.id, ranked.get(e.theme.id)!.slice(e.slots, e.slots + ALTERNATES_PER_THEME).map((q) => q.id)]),
    ) as Record<string, string[]>,
    plan,
    shortfall: count - questions.length,
  };
}

export type Suggestion = ReturnType<typeof suggestQuestions>;
