import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/api-auth";
import { buildExportQuestions, generateTestDocx } from "@/lib/docx";
import { handleApiError } from "@/lib/api-error";
import { accessibleTest } from "@/lib/access";
import { buildTestKey, testChoiceCount } from "@/lib/answer-key";

type Params = { params: Promise<{ id: string }> };

export async function GET(_req: NextRequest, { params }: Params) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const { id } = await params;

  try {
    await accessibleTest(id, auth.session.user);
    const test = await prisma.test.findUnique({ where: { id }, include: { subject: true } });
    if (!test) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });

    const questions = await prisma.question.findMany({
      where: { id: { in: test.questionIds } },
    });
    // preserve the order the admin selected the questions in
    const ordered = test.questionIds
      .map((qid) => questions.find((q) => q.id === qid))
      .filter((q): q is NonNullable<typeof q> => Boolean(q));

    const exportQuestions = await buildExportQuestions(
      test.id,
      ordered.map((q) => ({
        id: q.id,
        text: q.text,
        imageUrl: q.imageUrl,
        correctAnswer: q.correctAnswer,
        wrongAnswers: q.wrongAnswers,
      })),
    );

    // Chop etilgan varaq — haqiqatning manbai: kalit va variantlar sonini
    // shu yerda ham yangilab qo'yamiz, savol tahrirlangan bo'lsa smartbot
    // eskisini olib qolmasin (DECISIONS.md #32).
    const answerKey = buildTestKey(test.id, ordered);
    const choiceCount = testChoiceCount(ordered);
    if (
      choiceCount !== test.choiceCount ||
      answerKey.length !== test.answerKey.length ||
      answerKey.some((letter, i) => letter !== test.answerKey[i])
    ) {
      await prisma.test.update({ where: { id: test.id }, data: { answerKey, choiceCount } });
    }

    const docxBuffer = await generateTestDocx(test.title, test.subject.name, exportQuestions);

    return new NextResponse(new Uint8Array(docxBuffer), {
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Content-Disposition": `attachment; filename="${encodeURIComponent(test.title)}.docx"`,
      },
    });
  } catch (err) {
    return handleApiError(err);
  }
}
