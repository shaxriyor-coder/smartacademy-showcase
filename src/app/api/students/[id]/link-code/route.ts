import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { ownStudent } from "@/lib/access";
import { withFreshLinkCode } from "@/lib/students";

type Params = { params: Promise<{ id: string }> };

// Issues a new link code (e.g. the old one was shared with the wrong person).
// Accounts already linked stay linked; only the old code stops working.
export async function POST(_req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownStudent(id, auth.session.user.id);
    const student = await withFreshLinkCode((linkCode) =>
      prisma.student.update({ where: { id }, data: { linkCode } }),
    );
    return NextResponse.json({ linkCode: student.linkCode });
  } catch (err) {
    return handleApiError(err);
  }
}
