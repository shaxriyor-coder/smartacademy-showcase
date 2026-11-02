import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { requireTeacher } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { loadSuggestion } from "@/lib/suggest";
import { MAX_COUNT, MIN_COUNT } from "@/lib/suggest-core";

const schema = z.object({
  classroomId: z.string().min(1),
  // null or absent: the whole group.
  studentId: z.string().min(1).nullable().optional(),
  subjectId: z.string().min(1, "Fanni tanlang"),
  count: z.number().int().min(MIN_COUNT).max(MAX_COUNT),
  seed: z.string().max(64).optional(),
});

// Proposes a test from a student's or a group's weak topics
// (docs/DECISIONS.md #25). Nothing is saved: the teacher edits the list and
// creates the test through POST /api/tests.
export async function POST(req: NextRequest) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const parsed = schema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }
  const d = parsed.data;

  try {
    const suggestion = await loadSuggestion({
      teacherId: auth.session.user.id,
      classroomId: d.classroomId,
      studentId: d.studentId ?? null,
      subjectId: d.subjectId,
      count: d.count,
      seed: d.seed ?? String(Date.now()),
    });
    return NextResponse.json(suggestion);
  } catch (err) {
    return handleApiError(err);
  }
}
