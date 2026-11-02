import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSuperAdmin } from "@/lib/api-auth";
import { z } from "zod";
import { handleApiError } from "@/lib/api-error";

type Params = { params: Promise<{ id: string }> };

const updateSchema = z.object({ name: z.string().min(1) });

export async function PATCH(req: NextRequest, { params }: Params) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const body = await req.json();
  const parsed = updateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const subject = await prisma.subject.update({ where: { id }, data: parsed.data });
    return NextResponse.json(subject);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await prisma.subject.delete({ where: { id } });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
