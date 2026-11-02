import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { MAX_BULK_STUDENTS, classroomMemberAddSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { ownClassroom } from "@/lib/access";
import { normalizeLinkCode } from "@/lib/link-code";
import { parseRegisterLines, toStudentData, withFreshLinkCode } from "@/lib/students";
import { syncClassroomSheets } from "@/lib/assignments";

type Params = { params: Promise<{ id: string }> };

export async function POST(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id: classroomId } = await params;
  const body = await req.json();
  const parsed = classroomMemberAddSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const input = parsed.data;
  const createdById = auth.session.user.id;

  try {
    await ownClassroom(classroomId, auth.session.user.id);
    const classroom = await prisma.classroom.findUnique({ where: { id: classroomId } });
    if (!classroom || classroom.archived) {
      return NextResponse.json({ error: "Guruh topilmadi" }, { status: 404 });
    }

    if (input.mode === "new") {
      await withFreshLinkCode((linkCode) =>
        prisma.student.create({
          data: {
            ...toStudentData(input.student),
            linkCode,
            createdById,
            memberships: { create: { classroomId } },
          },
        }),
      );
      await syncClassroomSheets(classroomId);
      return NextResponse.json({ added: 1 }, { status: 201 });
    }

    if (input.mode === "bulk") {
      const rows = parseRegisterLines(input.lines);
      if (rows.length === 0) {
        return NextResponse.json({ error: "Ro'yxatda birorta ism yo'q" }, { status: 400 });
      }
      if (rows.length > MAX_BULK_STUDENTS) {
        return NextResponse.json(
          { error: `Bir martada ko'pi bilan ${MAX_BULK_STUDENTS} ta o'quvchi` },
          { status: 400 },
        );
      }
      // Sequential, not one transaction: a unique clash inside a Postgres
      // transaction aborts it, which would defeat withFreshLinkCode's retry.
      for (const row of rows) {
        await withFreshLinkCode((linkCode) =>
          prisma.student.create({
            data: {
              ...toStudentData({ ...row, grade: input.grade }),
              linkCode,
              createdById,
              memberships: { create: { classroomId } },
            },
          }),
        );
      }
      await syncClassroomSheets(classroomId);
      return NextResponse.json({ added: rows.length }, { status: 201 });
    }

    // mode === "code": a student who already exists (e.g. in another
    // classroom) joins this one too, keeping a single progress history.
    const student = await prisma.student.findUnique({
      where: { linkCode: normalizeLinkCode(input.linkCode) },
    });
    if (!student) {
      return NextResponse.json({ error: "Bu kod bo'yicha o'quvchi topilmadi" }, { status: 404 });
    }
    const existing = await prisma.classroomMember.findUnique({
      where: { classroomId_studentId: { classroomId, studentId: student.id } },
    });
    if (existing) {
      return NextResponse.json({ error: "Bu o'quvchi guruhda allaqachon bor" }, { status: 409 });
    }
    await prisma.classroomMember.create({ data: { classroomId, studentId: student.id } });
    await syncClassroomSheets(classroomId);
    return NextResponse.json({ added: 1 }, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}

// Removes the membership only — the Student row, their sheets and results
// stay, since they're the student's history.
export async function DELETE(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id: classroomId } = await params;
  const studentId = req.nextUrl.searchParams.get("studentId");
  if (!studentId) {
    return NextResponse.json({ error: "studentId majburiy" }, { status: 400 });
  }

  try {
    await ownClassroom(classroomId, auth.session.user.id);
    await prisma.classroomMember.delete({
      where: { classroomId_studentId: { classroomId, studentId } },
    });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
