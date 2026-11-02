import { prisma } from "./prisma";

// Shared with client components, so it lives in the database-free module.
export { scoreTone } from "./analytics-core";

export type ThemeStat = {
  id: string;
  name: string;
  correct: number;
  total: number;
  percentage: number;
};

// Topic-level results: each answered question counts toward every theme it's
// tagged with. Pass only CHECKED sheets. Questions deleted from the bank since
// simply stop contributing — the frozen key still grades them.
export async function themeStats(
  sheets: { answers: string[]; questionIds: string[]; answerKey: string[] }[],
): Promise<ThemeStat[]> {
  const ids = [...new Set(sheets.flatMap((s) => s.questionIds))];
  if (ids.length === 0) return [];

  const questions = await prisma.question.findMany({
    where: { id: { in: ids } },
    select: { id: true, themes: { select: { id: true, name: true } } },
  });
  const themesOf = new Map(questions.map((q) => [q.id, q.themes]));

  const acc = new Map<string, ThemeStat>();
  for (const sheet of sheets) {
    sheet.questionIds.forEach((qid, i) => {
      for (const theme of themesOf.get(qid) ?? []) {
        const stat = acc.get(theme.id) ?? { ...theme, correct: 0, total: 0, percentage: 0 };
        stat.total += 1;
        if (sheet.answers[i] === sheet.answerKey[i]) stat.correct += 1;
        acc.set(theme.id, stat);
      }
    });
  }

  return [...acc.values()]
    .map((s) => ({ ...s, percentage: Math.round((s.correct / s.total) * 100) }))
    .sort((a, b) => a.percentage - b.percentage || b.total - a.total);
}
