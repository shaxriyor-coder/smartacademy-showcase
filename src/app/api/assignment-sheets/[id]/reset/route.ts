import { NextRequest, NextResponse } from "next/server";
import { requireTeacher } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { ownSheet } from "@/lib/access";
import { resetSheetResult } from "@/lib/assignments";

type Params = { params: Promise<{ id: string }> };

// Clears a checked result so the sheet can be scanned again. The only way to
// replace a result — a re-upload never overwrites one silently.
export async function POST(_req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownSheet(id, auth.session.user.id);
    await resetSheetResult(id);
    return NextResponse.json({ success: true });
  } catch (err) {
    return handleApiError(err);
  }
}
