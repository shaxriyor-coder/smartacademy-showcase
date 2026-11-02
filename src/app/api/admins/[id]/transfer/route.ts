import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { requireSuperAdmin } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { hasTeacherAccess } from "@/lib/roles";

type Params = { params: Promise<{ id: string }> };

const transferSchema = z.object({
  toUserId: z.string().min(1, "O'qituvchini tanlang"),
  includeTests: z.boolean().default(false),
});

// Hands every classroom of one staff member (archived ones too, so history
// stays together) to a teacher — e.g. groups made before the teacher role
// existed, or a teacher who is leaving. The super admin moves them without
// opening them. Assignments keep their frozen questions, so moving tests is
// optional: it only matters for assigning those tests again.
export async function POST(req: NextRequest, { params }: Params) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const parsed = transferSchema.safeParse(await req.json());
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const { toUserId, includeTests } = parsed.data;
  if (toUserId === id) {
    return NextResponse.json({ error: "O'sha xodimning o'ziga o'tkazib bo'lmaydi" }, { status: 400 });
  }

  try {
    const [from, to] = await Promise.all([
      prisma.user.findUnique({ where: { id }, select: { id: true } }),
      prisma.user.findUnique({ where: { id: toUserId }, select: { role: true, canTeach: true } }),
    ]);
    if (!from) return NextResponse.json({ error: "Xodim topilmadi" }, { status: 404 });
    // O'qituvchi roli yoki o'qituvchi huquqi berilgan admin (DECISIONS.md #30).
    if (!hasTeacherAccess(to)) {
      return NextResponse.json(
        { error: "Guruhlarni faqat o'qituvchiga (yoki o'qituvchi huquqi bor xodimga) o'tkazish mumkin" },
        { status: 400 },
      );
    }

    const [classrooms, tests] = await prisma.$transaction([
      prisma.classroom.updateMany({ where: { teacherId: id }, data: { teacherId: toUserId } }),
      prisma.test.updateMany({
        where: includeTests ? { createdById: id } : { id: { in: [] } },
        data: { createdById: toUserId },
      }),
    ]);
    return NextResponse.json({ classrooms: classrooms.count, tests: tests.count });
  } catch (err) {
    return handleApiError(err);
  }
}
