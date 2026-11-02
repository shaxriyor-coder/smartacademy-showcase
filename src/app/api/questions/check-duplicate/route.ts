import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";

export async function POST(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const subjectId = typeof body.subjectId === "string" ? body.subjectId : "";
  const text = typeof body.text === "string" ? body.text.trim() : "";

  if (!subjectId || !text) {
    return NextResponse.json({ exists: false });
  }

  try {
    const existing = await prisma.question.findFirst({
      where: { subjectId, text: { equals: text, mode: "insensitive" } },
      select: { id: true },
    });

    return NextResponse.json({ exists: !!existing, existingId: existing?.id ?? null });
  } catch (err) {
    return handleApiError(err);
  }
}
