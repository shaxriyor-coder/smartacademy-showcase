import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { requireSession } from "@/lib/api-auth";
import { testCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { testScope } from "@/lib/access";
import { smartbotOlympiads } from "@/lib/smartbot";
import { buildTestKey, testChoiceCount } from "@/lib/answer-key";

// Capped rather than paginated for now — this list only needs to stop
// growing unbounded as tests accumulate over the tool's lifetime; the most
// recent 200 covers realistic usage without a pagination UI.
const MAX_TESTS_LISTED = 200;

export async function GET() {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  try {
    const tests = await prisma.test.findMany({
      where: testScope(auth.session.user),
      include: { subject: true, createdBy: { select: { id: true, name: true } } },
      orderBy: { createdAt: "desc" },
      take: MAX_TESTS_LISTED,
    });
    return NextResponse.json(tests);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  const parsed = testCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  const { title, subjectId, questionIds, isOlympiad, smartbotOlympiadId } = parsed.data;

  try {
    // Olimpiada nomi mijozdan emas, botdan olinadi: ikkala tomonda bir xil
    // nom tursin va yo'q olimpiada yozilib qolmasin (DECISIONS.md #31).
    let olympiad: { id: number; name: string } | null = null;
    if (isOlympiad) {
      const olympiads = await smartbotOlympiads();
      if (!olympiads) {
        return NextResponse.json(
          { error: "Bot bazasi ulanmagan — olimpiadani tanlab bo'lmaydi" },
          { status: 503 },
        );
      }
      const chosen = olympiads.find((o) => o.id === smartbotOlympiadId);
      if (!chosen) {
        return NextResponse.json(
          { error: "Bu olimpiada botda topilmadi — sahifani yangilab, qaytadan tanlang" },
          { status: 400 },
        );
      }
      olympiad = { id: chosen.id, name: chosen.name };
    }

    // Kalit va varaqdagi variantlar soni shu yerda hisoblanadi: smartbot
    // javob varag'ini shulardan sozlaydi (DECISIONS.md #32). Kalit test id'si
    // bilan urug'lanadi, shuning uchun avval test qatori yaratiladi.
    const questions = await prisma.question.findMany({
      where: { id: { in: questionIds } },
      select: { id: true, wrongAnswers: true },
    });
    const byId = new Map(questions.map((q) => [q.id, q]));
    const ordered = questionIds.map((id) => byId.get(id)).filter((q) => q != null);
    if (ordered.length !== questionIds.length) {
      return NextResponse.json({ error: "Tanlangan savollarning ba'zisi topilmadi" }, { status: 400 });
    }

    const test = await prisma.test.create({
      data: {
        title: olympiad ? olympiad.name : title.trim(),
        subjectId,
        questionIds,
        isOlympiad,
        olympiadName: olympiad?.name ?? null,
        smartbotOlympiadId: olympiad?.id ?? null,
        choiceCount: testChoiceCount(ordered),
        createdById: auth.session.user.id,
      },
    });
    await prisma.test.update({
      where: { id: test.id },
      data: { answerKey: buildTestKey(test.id, ordered) },
    });

    return NextResponse.json(test, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
