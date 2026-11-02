// One-way import of the Test Maker question bank into this platform: subjects,
// themes, subthemes, difficulty levels, skills, questions (with their images)
// and tests. Test Maker is only READ — the source connection is read-only.
//
// Questions and tests keep their Test Maker ids: option order is seeded by
// `testId:questionId` (src/lib/shuffle.ts), so a Word paper already printed
// from Test Maker still matches its key when the same test is used here.
// Accounts are not copied; authors are matched by email.
//
//   TEST_MAKER_DATABASE_URL=... TEST_MAKER_DIR="D:/Projects/test-checker/Test Maker" \
//     npx tsx scripts/import-test-maker.ts           # dry run: prints the plan
//   ... npx tsx scripts/import-test-maker.ts --apply # writes, in one transaction
//
// Safe to run again: rows that already exist are matched and skipped, so new
// Test Maker questions can be pulled in until Test Maker is retired.
import "dotenv/config";
import { copyFileSync, existsSync, mkdirSync } from "fs";
import path from "path";
import { Client } from "pg";
import type { Prisma } from "@prisma/client";
import { prisma } from "../src/lib/prisma";

const APPLY = process.argv.includes("--apply");

type SourceQuestion = {
  id: string;
  subjectId: string;
  text: string;
  imageUrl: string | null;
  correctAnswer: string;
  wrongAnswers: string[];
  difficultyId: string;
  focus: "ABITURIENT" | "PMT";
  createdById: string;
  createdAt: Date;
  updatedAt: Date;
};

type SourceTest = {
  id: string;
  title: string;
  subjectId: string;
  createdById: string;
  questionIds: string[];
  isOlympiad: boolean;
  olympiadName: string | null;
  createdAt: Date;
};

const counts: Record<string, { yangi: number; bor: number }> = {};
const warnings: string[] = [];

function tally(kind: string, created: boolean) {
  const c = (counts[kind] ??= { yangi: 0, bor: 0 });
  if (created) c.yangi += 1;
  else c.bor += 1;
}

async function main() {
  const sourceUrl = process.env.TEST_MAKER_DATABASE_URL;
  const sourceDir = process.env.TEST_MAKER_DIR;
  if (!sourceUrl || !sourceDir) {
    throw new Error("TEST_MAKER_DATABASE_URL va TEST_MAKER_DIR kerak (skript boshidagi izohga qarang)");
  }

  const source = new Client({ connectionString: sourceUrl });
  await source.connect();
  try {
    // Belt and braces: nothing in this session can write to Test Maker.
    await source.query("SET default_transaction_read_only = on");
    const read = async <T>(sql: string) => (await source.query(sql)).rows as T[];

    const users = await read<{ id: string; email: string }>(`SELECT id, email FROM "User"`);
    const subjects = await read<{ id: string; name: string }>(`SELECT id, name FROM "Subject"`);
    const themes = await read<{ id: string; name: string; subjectId: string }>(
      `SELECT id, name, "subjectId" FROM "Theme"`,
    );
    const subThemes = await read<{ id: string; name: string; themeId: string }>(
      `SELECT id, name, "themeId" FROM "SubTheme"`,
    );
    const levels = await read<{ id: string; name: string; order: number; subjectId: string }>(
      `SELECT id, name, "order", "subjectId" FROM "DifficultyLevel"`,
    );
    const skills = await read<{ id: string; name: string }>(`SELECT id, name FROM "Skill"`);
    const questions = await read<SourceQuestion>(
      `SELECT id, "subjectId", text, "imageUrl", "correctAnswer", "wrongAnswers", "difficultyId",
              focus, "createdById", "createdAt", "updatedAt" FROM "Question" ORDER BY "createdAt"`,
    );
    const tests = await read<SourceTest>(
      `SELECT id, title, "subjectId", "createdById", "questionIds", "isOlympiad", "olympiadName", "createdAt"
       FROM "Test" ORDER BY "createdAt"`,
    );

    const questionIds = new Set(questions.map((q) => q.id));
    // Prisma names implicit join columns A/B by model name order — detect
    // which side is the question instead of assuming.
    async function joinTable(table: string) {
      const rows = await read<{ A: string; B: string }>(`SELECT "A", "B" FROM "${table}"`);
      const questionIsA = rows.every((r) => questionIds.has(r.A));
      const byQuestion = new Map<string, string[]>();
      for (const r of rows) {
        const [qid, other] = questionIsA ? [r.A, r.B] : [r.B, r.A];
        byQuestion.set(qid, [...(byQuestion.get(qid) ?? []), other]);
      }
      return byQuestion;
    }
    const themesOf = await joinTable("_QuestionThemes");
    const subThemesOf = await joinTable("_QuestionSubThemes");
    const skillsOf = await joinTable("_QuestionSkills");

    const platformUsers = await prisma.user.findMany({
      select: { id: true, email: true, role: true },
      orderBy: { createdAt: "asc" },
    });
    const fallback = platformUsers.find((u) => u.role === "SUPER_ADMIN") ?? platformUsers[0];
    if (!fallback) throw new Error("Platformada foydalanuvchi yo'q — avval `npm run db:seed`");
    const platformUserByEmail = new Map(platformUsers.filter((u) => u.email).map((u) => [u.email!.toLowerCase(), u.id]));
    const sourceEmail = new Map(users.map((u) => [u.id, u.email]));
    const unmatchedAuthors = new Set<string>();
    const author = (sourceUserId: string) => {
      const email = sourceEmail.get(sourceUserId) ?? "";
      const id = platformUserByEmail.get(email.toLowerCase());
      if (!id) unmatchedAuthors.add(email || sourceUserId);
      return id ?? fallback.id;
    };

    const oddQuestions = new Set(
      questions.filter((q) => q.wrongAnswers.length !== 4).map((q) => q.id),
    );

    async function run(db: Prisma.TransactionClient) {
      const subjectIds = new Map<string, string>();
      for (const s of subjects) {
        const existing = await db.subject.findUnique({ where: { name: s.name } });
        if (!existing && APPLY) await db.subject.create({ data: { id: s.id, name: s.name } });
        subjectIds.set(s.id, existing?.id ?? s.id);
        tally("fanlar", !existing);
      }

      const themeIds = new Map<string, string>();
      for (const t of themes) {
        const subjectId = subjectIds.get(t.subjectId)!;
        const existing = await db.theme.findUnique({
          where: { subjectId_name: { subjectId, name: t.name } },
        });
        if (!existing && APPLY) await db.theme.create({ data: { id: t.id, name: t.name, subjectId } });
        themeIds.set(t.id, existing?.id ?? t.id);
        tally("mavzular", !existing);
      }

      const subThemeIds = new Map<string, string>();
      for (const st of subThemes) {
        const themeId = themeIds.get(st.themeId)!;
        const existing = await db.subTheme.findUnique({
          where: { themeId_name: { themeId, name: st.name } },
        });
        if (!existing && APPLY) {
          await db.subTheme.create({ data: { id: st.id, name: st.name, themeId } });
        }
        subThemeIds.set(st.id, existing?.id ?? st.id);
        tally("ichki mavzular", !existing);
      }

      const levelIds = new Map<string, string>();
      for (const l of levels) {
        const subjectId = subjectIds.get(l.subjectId)!;
        const existing = await db.difficultyLevel.findUnique({
          where: { subjectId_name: { subjectId, name: l.name } },
        });
        if (!existing && APPLY) {
          await db.difficultyLevel.create({
            data: { id: l.id, name: l.name, order: l.order, subjectId },
          });
        }
        levelIds.set(l.id, existing?.id ?? l.id);
        tally("qiyinlik darajalari", !existing);
      }

      const skillIds = new Map<string, string>();
      for (const sk of skills) {
        const existing = await db.skill.findUnique({ where: { name: sk.name } });
        if (!existing && APPLY) await db.skill.create({ data: { id: sk.id, name: sk.name } });
        skillIds.set(sk.id, existing?.id ?? sk.id);
        tally("mahoratlar", !existing);
      }

      for (const q of questions) {
        const existing = await db.question.findUnique({ where: { id: q.id }, select: { id: true } });
        tally("savollar", !existing);
        if (oddQuestions.has(q.id)) {
          warnings.push(
            `Savol «${q.text.slice(0, 50)}»: ${q.wrongAnswers.length} ta noto'g'ri javob (4 ta kerak) — ` +
              `tahrirlab 4 taga yetkazilmaguncha u bor testni guruhga biriktirib bo'lmaydi.`,
          );
        }
        if (existing || !APPLY) continue;
        await db.question.create({
          data: {
            id: q.id,
            subjectId: subjectIds.get(q.subjectId)!,
            text: q.text,
            imageUrl: q.imageUrl,
            correctAnswer: q.correctAnswer,
            wrongAnswers: q.wrongAnswers,
            difficultyId: levelIds.get(q.difficultyId)!,
            focus: q.focus,
            createdById: author(q.createdById),
            createdAt: q.createdAt,
            updatedAt: q.updatedAt,
            themes: { connect: (themesOf.get(q.id) ?? []).map((id) => ({ id: themeIds.get(id)! })) },
            subThemes: {
              connect: (subThemesOf.get(q.id) ?? []).map((id) => ({ id: subThemeIds.get(id)! })),
            },
            skills: { connect: (skillsOf.get(q.id) ?? []).map((id) => ({ id: skillIds.get(id)! })) },
          },
        });
      }

      for (const t of tests) {
        const existing = await db.test.findUnique({ where: { id: t.id }, select: { id: true } });
        tally("testlar", !existing);
        const odd = t.questionIds.filter((id) => oddQuestions.has(id)).length;
        if (odd) warnings.push(`Test «${t.title}»: ${odd} ta savolda variantlar soni 5 ta emas.`);
        const missing = t.questionIds.filter((id) => !questionIds.has(id)).length;
        if (missing) warnings.push(`Test «${t.title}»: ${missing} ta savol Test Maker'da o'chirilgan.`);
        if (existing || !APPLY) continue;
        await db.test.create({
          data: {
            id: t.id,
            title: t.title,
            subjectId: subjectIds.get(t.subjectId)!,
            createdById: author(t.createdById),
            questionIds: t.questionIds,
            isOlympiad: t.isOlympiad,
            olympiadName: t.olympiadName,
            createdAt: t.createdAt,
          },
        });
      }
    }

    if (APPLY) {
      await prisma.$transaction((tx) => run(tx), { timeout: 120_000 });
    } else {
      await run(prisma);
    }

    // Question images live on disk, outside the database.
    const targetDir = path.resolve(__dirname, "..", "public", "uploads");
    for (const q of questions) {
      if (!q.imageUrl?.startsWith("/uploads/")) continue;
      const file = path.basename(q.imageUrl);
      const from = path.join(sourceDir, "public", "uploads", file);
      const to = path.join(targetDir, file);
      if (!existsSync(from)) {
        warnings.push(`Rasm topilmadi: ${from}`);
        continue;
      }
      const present = existsSync(to);
      tally("rasmlar", !present);
      if (!present && APPLY) {
        mkdirSync(targetDir, { recursive: true });
        copyFileSync(from, to);
      }
    }

    for (const email of unmatchedAuthors) {
      warnings.push(
        `${email} platformada yo'q — uning savol/testlari ${fallback.email ?? fallback.id} nomiga yozildi ` +
          `(akkaunt kerak bo'lsa /admins orqali qo'shing).`,
      );
    }

    console.log(APPLY ? "IMPORT BAJARILDI" : "SINOV REJIMI — hech narsa yozilmadi (yozish uchun --apply)");
    console.table(counts);
    if (warnings.length) {
      console.log("Ogohlantirishlar:");
      for (const w of [...new Set(warnings)]) console.log(`  - ${w}`);
    }
  } finally {
    await source.end();
  }
}

main()
  .catch((err) => {
    console.error(err);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());
