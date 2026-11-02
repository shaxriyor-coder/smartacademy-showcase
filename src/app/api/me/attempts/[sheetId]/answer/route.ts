import { NextRequest, NextResponse } from "next/server";
import { requireStudentSession } from "@/lib/api-auth";
import { attemptAnswerSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { saveAnswer } from "@/lib/online";

type Params = { params: Promise<{ sheetId: string }> };

// Saves one answer per tap. `index` is the canonical question position and
// `choice` the canonical letter the page was given — "" clears the answer.
export async function PUT(req: NextRequest, { params }: Params) {
  const auth = await requireStudentSession();
  if ("error" in auth) return auth.error;

  const { sheetId } = await params;
  const parsed = attemptAnswerSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    await saveAnswer(sheetId, auth.session.user.id, parsed.data.index, parsed.data.choice);
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
