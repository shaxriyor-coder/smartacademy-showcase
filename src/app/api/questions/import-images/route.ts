import { NextRequest, NextResponse } from "next/server";
import { requireSession } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { readQuestionImages } from "@/lib/checker";

// Test sahifalarining rasmlari (Telegram'dan saqlangan yoki telefonda suratga
// olingan) -> checker/ocr (Tesseract) -> Word importi bilan bir xil savol
// qoralamalari + o'qituvchi tekshirishi uchun asl rasm bo'lagi va izohlar.
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_PAGES = 20; // checker'dagi CHECKER_MAX_OCR_PAGES bilan bir xil
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

export async function POST(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const formData = await req.formData();
  const files = formData
    .getAll("files")
    .filter((f): f is File => f instanceof File && f.size > 0);
  if (files.length === 0) {
    return NextResponse.json({ error: "Rasm topilmadi" }, { status: 400 });
  }
  if (files.length > MAX_PAGES) {
    return NextResponse.json(
      { error: `Bir yuklashda ko'pi bilan ${MAX_PAGES} ta sahifa` },
      { status: 400 },
    );
  }
  for (const file of files) {
    if (!IMAGE_TYPES.includes(file.type)) {
      return NextResponse.json(
        { error: `${file.name}: faqat JPEG, PNG yoki WEBP rasm qabul qilinadi` },
        { status: 400 },
      );
    }
    if (file.size > MAX_IMAGE_BYTES) {
      return NextResponse.json(
        { error: `${file.name}: rasm hajmi 10MB dan oshmasligi kerak` },
        { status: 400 },
      );
    }
  }
  // Sahifalar fayl nomi bo'yicha tartiblanadi ("2.jpg" "10.jpg" dan oldin).
  files.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));

  try {
    const result = await readQuestionImages(
      await Promise.all(
        files.map(async (f) => ({
          bytes: new Uint8Array(await f.arrayBuffer()),
          name: f.name,
          type: f.type,
        })),
      ),
    );
    if (result.questions.length === 0) {
      return NextResponse.json(
        {
          error:
            "Rasmdan savollar aniqlanmadi. Savollar \"1.\" va variantlar \"A)\" ko'rinishida bo'lishi, rasm tiniq bo'lishi kerak.",
        },
        { status: 400 },
      );
    }
    return NextResponse.json({
      questions: result.questions.map((q) => ({
        text: q.text,
        imageDataUri: q.image ? `data:image/png;base64,${q.image}` : null,
        options: q.options,
        review: {
          number: q.number,
          sourceDataUri: q.source ? `data:image/jpeg;base64,${q.source}` : null,
          notes: q.notes,
          uncertain: q.uncertain,
          needsReview: q.needs_review,
        },
      })),
    });
  } catch (err) {
    return handleApiError(err);
  }
}
