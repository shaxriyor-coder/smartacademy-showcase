import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { classroomCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";

// A teacher's own classrooms only. Admins don't open classrooms at all — they
// see the centre through /analytics (docs/DECISIONS.md #20).
export async function GET() {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  try {
    const classrooms = await prisma.classroom.findMany({
      where: { archived: false, teacherId: auth.session.user.id },
      include: {
        subject: true,
        teacher: { select: { name: true } },
        _count: { select: { members: true } },
      },
      orderBy: { createdAt: "desc" },
    });
    return NextResponse.json(classrooms);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = classroomCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const classroom = await prisma.classroom.create({
      data: { ...parsed.data, teacherId: auth.session.user.id },
      include: { subject: true, teacher: { select: { name: true } } },
    });
    return NextResponse.json(classroom, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
