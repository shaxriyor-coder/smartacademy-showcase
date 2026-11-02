import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/api-auth";
import { questionCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { canEditQuestion } from "@/lib/access";

const ALLOWED_PAGE_SIZES = [15, 30, 50, 100];

function parseCsv(value: string | null): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export async function GET(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const sp = req.nextUrl.searchParams;
  const subjectId = sp.get("subjectId") ?? undefined;
  const themeIds = parseCsv(sp.get("themeIds"));
  const subThemeIds = parseCsv(sp.get("subThemeIds"));
  const difficultyId = sp.get("difficultyId") ?? undefined;
  const focus = sp.get("focus") ?? undefined;
  const skillIds = parseCsv(sp.get("skillIds"));
  const dateFrom = sp.get("dateFrom") ?? undefined;
  const dateTo = sp.get("dateTo") ?? undefined;

  const page = Math.max(1, Number(sp.get("page") ?? "1") || 1);
  const requestedPageSize = Number(sp.get("pageSize") ?? "15") || 15;
  const pageSize = ALLOWED_PAGE_SIZES.includes(requestedPageSize) ? requestedPageSize : 15;

  const where: Prisma.QuestionWhereInput = {
    ...(subjectId ? { subjectId } : {}),
    ...(difficultyId ? { difficultyId } : {}),
    ...(focus ? { focus: focus as "ABITURIENT" | "PMT" } : {}),
    ...(themeIds.length ? { themes: { some: { id: { in: themeIds } } } } : {}),
    ...(subThemeIds.length ? { subThemes: { some: { id: { in: subThemeIds } } } } : {}),
    ...(skillIds.length ? { skills: { some: { id: { in: skillIds } } } } : {}),
    ...(dateFrom || dateTo
      ? {
          createdAt: {
            ...(dateFrom ? { gte: new Date(dateFrom) } : {}),
            ...(dateTo ? { lte: new Date(dateTo) } : {}),
          },
        }
      : {}),
  };

  try {
    const [total, rawItems] = await Promise.all([
      prisma.question.count({ where }),
      prisma.question.findMany({
        where,
        include: {
          subject: true,
          themes: true,
          subThemes: true,
          difficulty: true,
          skills: true,
          createdBy: { select: { id: true, name: true } },
        },
        orderBy: { createdAt: "desc" },
        skip: (page - 1) * pageSize,
        take: pageSize,
      }),
    ]);

    // for each question on this page, which past olympiad tests already used it —
    // lets admins avoid re-using the same question across olympiads
    const itemIds = rawItems.map((q) => q.id);
    const olympiadTests = itemIds.length
      ? await prisma.test.findMany({
          where: { isOlympiad: true, questionIds: { hasSome: itemIds } },
          select: { title: true, olympiadName: true, questionIds: true },
        })
      : [];

    const usageByQuestionId = new Map<string, { olympiadName: string; testTitle: string }[]>();
    for (const test of olympiadTests) {
      for (const qid of test.questionIds) {
        if (!itemIds.includes(qid)) continue;
        const list = usageByQuestionId.get(qid) ?? [];
        list.push({ olympiadName: test.olympiadName ?? test.title, testTitle: test.title });
        usageByQuestionId.set(qid, list);
      }
    }

    const items = rawItems.map((q) => ({
      ...q,
      olympiadUsage: usageByQuestionId.get(q.id) ?? [],
      canEdit: canEditQuestion(q, auth.session.user),
    }));

    return NextResponse.json({
      items,
      total,
      page,
      pageSize,
      totalPages: Math.max(1, Math.ceil(total / pageSize)),
    });
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = questionCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  const { themeIds, subThemeIds, skillIds, ...rest } = parsed.data;

  try {
    const question = await prisma.question.create({
      data: {
        ...rest,
        createdById: auth.session.user.id,
        themes: { connect: themeIds.map((id) => ({ id })) },
        subThemes: { connect: (subThemeIds ?? []).map((id) => ({ id })) },
        skills: { connect: (skillIds ?? []).map((id) => ({ id })) },
      },
      include: { themes: true, subThemes: true, skills: true, difficulty: true },
    });

    return NextResponse.json(question, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
