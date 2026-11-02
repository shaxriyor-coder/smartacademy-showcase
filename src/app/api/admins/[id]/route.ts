import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { requireSuperAdmin } from "@/lib/api-auth";
import { adminUpdateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { STAFF_SELECT } from "@/lib/staff";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(req: NextRequest, { params }: Params) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const body = await req.json();
  if (body.telegramChatId === "") body.telegramChatId = null;
  const parsed = adminUpdateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  const { password, ...rest } = parsed.data;
  // Demoting yourself could leave the centre with no one who manages staff.
  if (id === auth.session.user.id && rest.role && rest.role !== "SUPER_ADMIN") {
    return NextResponse.json({ error: "O'zingizning rolingizni o'zgartira olmaysiz" }, { status: 400 });
  }

  try {
    const user = await prisma.user.update({
      where: { id },
      data: {
        ...rest,
        ...(password ? { passwordHash: await bcrypt.hash(password, 10) } : {}),
      },
      select: STAFF_SELECT,
    });

    return NextResponse.json(user);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function DELETE(req: NextRequest, { params }: Params) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  if (id === auth.session.user.id) {
    return NextResponse.json(
      { error: "O'zingizni o'chira olmaysiz" },
      { status: 400 },
    );
  }

  try {
    const owned = await prisma.user.findUnique({ where: { id }, select: STAFF_SELECT });
    if (!owned) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });
    // Their classrooms, tests and questions point at them; say so instead of a
    // bare foreign-key 500 (archived classrooms count too).
    const classrooms = await prisma.classroom.count({ where: { teacherId: id } });
    if (classrooms > 0 || owned._count.tests > 0 || owned._count.questions > 0) {
      return NextResponse.json(
        {
          error: `Bu xodimda ${classrooms} ta guruh, ${owned._count.tests} ta test va ${owned._count.questions} ta savol bor — avval guruhlarini boshqa o'qituvchiga o'tkazing`,
        },
        { status: 409 },
      );
    }
    await prisma.user.delete({ where: { id } });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
