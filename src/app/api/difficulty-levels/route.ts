import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession, requireSuperAdmin } from "@/lib/api-auth";
import { difficultyLevelCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";

export async function GET(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const subjectId = req.nextUrl.searchParams.get("subjectId") ?? undefined;
  try {
    const levels = await prisma.difficultyLevel.findMany({
      where: subjectId ? { subjectId } : undefined,
      orderBy: { order: "asc" },
    });
    return NextResponse.json(levels);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = difficultyLevelCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const level = await prisma.difficultyLevel.create({ data: parsed.data });
    return NextResponse.json(level, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
