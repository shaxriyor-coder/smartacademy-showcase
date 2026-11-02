import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession, requireSuperAdmin } from "@/lib/api-auth";
import { themeCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";

export async function GET(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const subjectId = req.nextUrl.searchParams.get("subjectId") ?? undefined;
  try {
    const themes = await prisma.theme.findMany({
      where: subjectId ? { subjectId } : undefined,
      include: { subThemes: true },
      orderBy: { name: "asc" },
    });
    return NextResponse.json(themes);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = themeCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const theme = await prisma.theme.create({ data: parsed.data });
    return NextResponse.json(theme, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
