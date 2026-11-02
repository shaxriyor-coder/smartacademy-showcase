import { NextRequest, NextResponse } from "next/server";
import type { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { studentUpdateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { ownStudent } from "@/lib/access";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const parsed = studentUpdateSchema.safeParse(await req.json());
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const d = parsed.data;

  // Only fields present in the body change. Names already stamped on printed
  // sheets don't matter to the checker — sheets are matched by QR ticket.
  const data: Prisma.StudentUpdateInput = {};
  if (d.firstName !== undefined) data.firstName = d.firstName;
  if (d.lastName !== undefined) data.lastName = d.lastName || null;
  if (d.birthDate !== undefined) {
    data.birthDate = d.birthDate ? new Date(`${d.birthDate}T00:00:00Z`) : null;
  }
  if (d.grade !== undefined) data.grade = d.grade || null;

  try {
    await ownStudent(id, auth.session.user.id);
    const student = await prisma.student.update({ where: { id }, data });
    return NextResponse.json(student);
  } catch (err) {
    return handleApiError(err);
  }
}
