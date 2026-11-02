import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { classroomUpdateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { ownClassroom } from "@/lib/access";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownClassroom(id, auth.session.user.id);
    const classroom = await prisma.classroom.findUnique({
      where: { id },
      include: {
        subject: true,
        teacher: { select: { name: true } },
        members: {
          include: { student: { include: { _count: { select: { telegramLinks: true } } } } },
          // class register order
          orderBy: [{ student: { lastName: "asc" } }, { student: { firstName: "asc" } }],
        },
        assignments: {
          where: { archived: false },
          orderBy: { createdAt: "desc" },
          select: {
            id: true,
            title: true,
            mode: true,
            subjectName: true,
            createdAt: true,
            questionIds: true,
            sheets: { select: { checkedAt: true } },
          },
        },
      },
    });
    if (!classroom) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });
    return NextResponse.json({
      ...classroom,
      assignments: classroom.assignments.map(({ sheets, questionIds, ...a }) => ({
        ...a,
        questionCount: questionIds.length,
        sheetCount: sheets.length,
        checkedCount: sheets.filter((s) => s.checkedAt).length,
      })),
    });
  } catch (err) {
    return handleApiError(err);
  }
}

export async function PATCH(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const body = await req.json();
  const parsed = classroomUpdateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    await ownClassroom(id, auth.session.user.id);
    const classroom = await prisma.classroom.update({ where: { id }, data: parsed.data });
    return NextResponse.json(classroom);
  } catch (err) {
    return handleApiError(err);
  }
}

// Archived, not hard-deleted — same reasoning as smartbot's Test/OnlineTest
// (see the sibling project's docs/DECISIONS.md #1): a student's membership
// and future progress history under this classroom shouldn't vanish just
// because a teacher tidied up their classroom list.
export async function DELETE(_req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownClassroom(id, auth.session.user.id);
    await prisma.classroom.update({ where: { id }, data: { archived: true } });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
