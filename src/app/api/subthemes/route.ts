import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession, requireSuperAdmin } from "@/lib/api-auth";
import { subThemeCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";

export async function GET(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const themeId = req.nextUrl.searchParams.get("themeId") ?? undefined;
  try {
    const subThemes = await prisma.subTheme.findMany({
      where: themeId ? { themeId } : undefined,
      orderBy: { name: "asc" },
    });
    return NextResponse.json(subThemes);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = subThemeCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const subTheme = await prisma.subTheme.create({ data: parsed.data });
    return NextResponse.json(subTheme, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
