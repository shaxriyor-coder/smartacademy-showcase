import { NextRequest, NextResponse } from "next/server";
import { requireSession } from "@/lib/api-auth";
import { parseQuestionsFromDocx } from "@/lib/docx-import";

// Word docs with several embedded images can legitimately be a few MB, but
// nothing in a real question bank upload needs to exceed this — without a
// cap, mammoth would buffer/parse an arbitrarily large (or malicious)
// .docx entirely in memory.
const MAX_IMPORT_SIZE_BYTES = 20 * 1024 * 1024;

export async function POST(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const formData = await req.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "Fayl topilmadi" }, { status: 400 });
  }
  if (
    !file.name.toLowerCase().endsWith(".docx") &&
    file.type !==
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  ) {
    return NextResponse.json({ error: "Faqat .docx fayl qabul qilinadi" }, { status: 400 });
  }
  if (file.size > MAX_IMPORT_SIZE_BYTES) {
    return NextResponse.json({ error: "Fayl hajmi 20MB dan oshmasligi kerak" }, { status: 400 });
  }

  try {
    const buffer = Buffer.from(await file.arrayBuffer());
    const questions = await parseQuestionsFromDocx(buffer);
    if (questions.length === 0) {
      return NextResponse.json(
        { error: "Word fayldan savollar aniqlanmadi. Fayl formatini tekshiring." },
        { status: 400 },
      );
    }
    return NextResponse.json({ questions });
  } catch (err) {
    console.error("docx import failed:", err);
    return NextResponse.json({ error: "Faylni o'qishda xatolik yuz berdi" }, { status: 400 });
  }
}
