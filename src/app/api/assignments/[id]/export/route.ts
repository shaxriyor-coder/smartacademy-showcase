import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireTeacher } from "@/lib/api-auth";
import { buildExportQuestions, generateTestDocx } from "@/lib/docx";
import { handleApiError } from "@/lib/api-error";
import { ownAssignment } from "@/lib/access";

type Params = { params: Promise<{ id: string }> };

// The question paper for an assignment, from its FROZEN question list —
// numbering and option order match the answer sheet and key even if the Test
// was edited later. ?key=1 adds the key at the end (teacher's copy).
export async function GET(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  const includeKey = req.nextUrl.searchParams.get("key") === "1";
  try {
    await ownAssignment(id, auth.session.user.id);
    const assignment = await prisma.assignment.findUnique({ where: { id } });
    if (!assignment) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });

    const questions = await prisma.question.findMany({
      where: { id: { in: assignment.questionIds } },
    });
    const byId = new Map(questions.map((q) => [q.id, q]));
    const missing = assignment.questionIds.filter((qid) => !byId.has(qid)).length;
    if (missing > 0) {
      return NextResponse.json(
        { error: `Topshiriqdagi ${missing} ta savol bazadan o'chirilgan — Word'ni chiqarib bo'lmaydi` },
        { status: 409 },
      );
    }

    const exportQuestions = await buildExportQuestions(
      assignment.testId,
      assignment.questionIds.map((qid) => {
        const q = byId.get(qid)!;
        return {
          id: q.id,
          text: q.text,
          imageUrl: q.imageUrl,
          correctAnswer: q.correctAnswer,
          wrongAnswers: q.wrongAnswers,
        };
      }),
    );
    const docx = await generateTestDocx(assignment.title, assignment.subjectName, exportQuestions, {
      includeKey,
    });

    const suffix = includeKey ? "-kalit-bilan" : "";
    return new NextResponse(new Uint8Array(docx), {
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Content-Disposition": `attachment; filename="${encodeURIComponent(`${assignment.title}${suffix}.docx`)}"`,
      },
    });
  } catch (err) {
    return handleApiError(err);
  }
}
