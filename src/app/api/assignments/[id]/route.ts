import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { assignmentSettingsSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { ownAssignment } from "@/lib/access";

type Params = { params: Promise<{ id: string }> };

// Online settings may change while the test runs — e.g. extending or closing
// it. Running attempts pick the change up immediately: a deadline is always
// computed from the current settings, never stored.
export async function PATCH(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const parsed = assignmentSettingsSchema.safeParse(await req.json());
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const d = parsed.data;

  try {
    await ownAssignment(id, auth.session.user.id);
    const current = await prisma.assignment.findUnique({
      where: { id },
      select: { mode: true, opensAt: true, closesAt: true, timeLimitMinutes: true, revealAnswers: true },
    });
    if (!current) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });
    if (current.mode !== "ONLINE") {
      return NextResponse.json({ error: "Bu sozlamalar faqat online test uchun" }, { status: 409 });
    }

    const pick = (value: string | null | undefined, fallback: Date | null) =>
      value === undefined ? fallback : value ? new Date(value) : null;
    const next = {
      opensAt: pick(d.opensAt, current.opensAt),
      closesAt: pick(d.closesAt, current.closesAt),
      timeLimitMinutes: d.timeLimitMinutes === undefined ? current.timeLimitMinutes : d.timeLimitMinutes,
      revealAnswers: d.revealAnswers ?? current.revealAnswers,
    };
    if (next.revealAnswers === "AFTER_CLOSE" && !next.closesAt) {
      return NextResponse.json(
        { error: "«Test yopilgandan keyin» uchun yopilish vaqtini kiriting" },
        { status: 400 },
      );
    }
    if (next.opensAt && next.closesAt && next.opensAt >= next.closesAt) {
      return NextResponse.json(
        { error: "Yopilish vaqti ochilish vaqtidan keyin bo'lishi kerak" },
        { status: 400 },
      );
    }

    // A changed deadline is a new close: the teacher gets a fresh summary.
    const closeChanged = next.closesAt?.getTime() !== current.closesAt?.getTime();
    const updated = await prisma.assignment.update({
      where: { id },
      data: { ...next, ...(closeChanged ? { summarySentAt: null } : {}) },
      select: { id: true },
    });
    return NextResponse.json(updated);
  } catch (err) {
    return handleApiError(err);
  }
}

// Archived, not deleted — checked sheets are students' results.
export async function DELETE(_req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownAssignment(id, auth.session.user.id);
    await prisma.assignment.update({ where: { id }, data: { archived: true }, select: { id: true } });
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
