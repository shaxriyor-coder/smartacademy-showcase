import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession, requireSuperAdmin } from "@/lib/api-auth";
import { subjectCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";

export async function GET() {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  try {
    const subjects = await prisma.subject.findMany({
      include: { themes: { include: { subThemes: true } }, difficultyLevels: true },
      orderBy: { name: "asc" },
    });
    return NextResponse.json(subjects);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = subjectCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const subject = await prisma.subject.create({ data: parsed.data });
    return NextResponse.json(subject, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
