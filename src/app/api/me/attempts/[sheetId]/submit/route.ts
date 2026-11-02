import { NextRequest, NextResponse } from "next/server";
import { requireStudentSession } from "@/lib/api-auth";
import { attemptSubmitSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { submitAttempt } from "@/lib/online";

type Params = { params: Promise<{ sheetId: string }> };

export async function POST(req: NextRequest, { params }: Params) {
  const auth = await requireStudentSession();
  if ("error" in auth) return auth.error;

  const { sheetId } = await params;
  const parsed = attemptSubmitSchema.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    await submitAttempt(sheetId, auth.session.user.id, parsed.data.answers);
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
