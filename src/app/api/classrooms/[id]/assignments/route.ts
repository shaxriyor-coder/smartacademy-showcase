import { NextRequest, NextResponse } from "next/server";
import { requireTeacher } from "@/lib/api-auth";
import { assignmentCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { accessibleTest, ownClassroom } from "@/lib/access";
import { createAssignment } from "@/lib/assignments";

type Params = { params: Promise<{ id: string }> };

export async function POST(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id: classroomId } = await params;
  const parsed = assignmentCreateSchema.safeParse(await req.json());
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const d = parsed.data;

  try {
    await ownClassroom(classroomId, auth.session.user.id);
    await accessibleTest(d.testId, auth.session.user);
    const assignment = await createAssignment({
      classroomId,
      testId: d.testId,
      title: d.title,
      createdById: auth.session.user.id,
      mode: d.mode,
      online:
        d.mode === "ONLINE"
          ? {
              opensAt: d.opensAt ? new Date(d.opensAt) : null,
              closesAt: d.closesAt ? new Date(d.closesAt) : null,
              timeLimitMinutes: d.timeLimitMinutes ?? null,
              shuffle: d.shuffle ?? true,
              // Without a closing time, "after it closes" would never come.
              revealAnswers: d.revealAnswers ?? (d.closesAt ? "AFTER_CLOSE" : "IMMEDIATELY"),
            }
          : undefined,
    });
    return NextResponse.json({ id: assignment.id }, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
