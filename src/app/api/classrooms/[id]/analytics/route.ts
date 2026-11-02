import { NextRequest, NextResponse } from "next/server";
import { requireTeacher } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { ownClassroom } from "@/lib/access";
import { loadClassroomAnalytics } from "@/lib/analytics";
import { formatTashkentDate, formatTashkentDay } from "@/lib/online-core";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownClassroom(id, auth.session.user.id);
    const analytics = await loadClassroomAnalytics(id);
    return NextResponse.json({
      ...analytics,
      // Dates leave the server formatted: the browser's ICU writes uz-UZ
      // dates differently from Node's (see formatTashkentDay).
      assignments: analytics.assignments.map(({ createdAt, ...a }) => ({
        ...a,
        dayLabel: formatTashkentDay(createdAt),
        dateLabel: formatTashkentDate(createdAt),
      })),
    });
  } catch (err) {
    return handleApiError(err);
  }
}
