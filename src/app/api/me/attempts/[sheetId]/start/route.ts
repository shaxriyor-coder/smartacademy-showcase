import { NextRequest, NextResponse } from "next/server";
import { requireStudentSession } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { startAttempt } from "@/lib/online";

type Params = { params: Promise<{ sheetId: string }> };

export async function POST(_req: NextRequest, { params }: Params) {
  const auth = await requireStudentSession();
  if ("error" in auth) return auth.error;

  const { sheetId } = await params;
  try {
    await startAttempt(sheetId, auth.session.user.id);
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
