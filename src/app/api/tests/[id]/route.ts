import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { accessibleTest } from "@/lib/access";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await accessibleTest(id, auth.session.user);
    const test = await prisma.test.findUnique({
      where: { id },
      include: { subject: true, createdBy: { select: { id: true, name: true } } },
    });
    if (!test) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });
    return NextResponse.json(test);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function DELETE(_req: NextRequest, { params }: Params) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    // Assignments freeze the test's questions and key, and their results
    // point back at it — the FK is RESTRICT, so say why instead of a bare 500.
    await accessibleTest(id, auth.session.user);
    const used = await prisma.assignment.count({ where: { testId: id } });
    if (used > 0) {
      return NextResponse.json(
        { error: `Bu test ${used} ta guruh topshirig'ida ishlatilgan — o'chirib bo'lmaydi` },
        { status: 409 },
      );
    }
    await prisma.test.delete({ where: { id } });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
