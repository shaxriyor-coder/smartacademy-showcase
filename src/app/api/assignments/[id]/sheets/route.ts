import { NextRequest, NextResponse } from "next/server";
import { requireTeacher } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { ownAssignment } from "@/lib/access";
import { buildSheetsPdf } from "@/lib/assignments";

type Params = { params: Promise<{ id: string }> };

// Personalized answer sheets as one PDF. The first call for an assignment
// also has the checker draw its template (~15-30 s); later calls only stamp.
// ?studentId=... reprints one student's sheet with the same ticket.
export async function GET(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const studentId = req.nextUrl.searchParams.get("studentId") ?? undefined;
  try {
    await ownAssignment(id, auth.session.user.id);
    const { pdf, fileName } = await buildSheetsPdf(id, studentId);
    return new NextResponse(new Uint8Array(pdf), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${encodeURIComponent(fileName)}"`,
      },
    });
  } catch (err) {
    return handleApiError(err);
  }
}
