import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/api-auth";
import { questionUpdateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { canEditQuestion, editableQuestion } from "@/lib/access";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    const question = await prisma.question.findUnique({
      where: { id },
      include: {
        subject: true,
        themes: true,
        subThemes: true,
        difficulty: true,
        skills: true,
        createdBy: { select: { id: true, name: true } },
      },
    });
    if (!question) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });
    return NextResponse.json({ ...question, canEdit: canEditQuestion(question, auth.session.user) });
  } catch (err) {
    return handleApiError(err);
  }
}

export async function PATCH(req: NextRequest, { params }: Params) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const body = await req.json();
  const parsed = questionUpdateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  const { themeIds, subThemeIds, skillIds, ...rest } = parsed.data;

  try {
    await editableQuestion(id, auth.session.user);
    const question = await prisma.question.update({
      where: { id },
      data: {
        ...rest,
        ...(themeIds ? { themes: { set: themeIds.map((tid) => ({ id: tid })) } } : {}),
        ...(subThemeIds
          ? { subThemes: { set: subThemeIds.map((tid) => ({ id: tid })) } }
          : {}),
        ...(skillIds ? { skills: { set: skillIds.map((sid) => ({ id: sid })) } } : {}),
      },
      include: { themes: true, subThemes: true, skills: true, difficulty: true },
    });

    return NextResponse.json(question);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await editableQuestion(id, auth.session.user);
    await prisma.question.delete({ where: { id } });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
