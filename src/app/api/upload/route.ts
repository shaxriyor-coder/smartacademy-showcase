import { NextRequest, NextResponse } from "next/server";
import { mkdir, writeFile } from "fs/promises";
import path from "path";
import { randomUUID } from "crypto";
import { requireSession } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { imageExtension } from "@/lib/upload-image";

const UPLOAD_DIR = path.join(process.cwd(), "public", "uploads");
const MAX_SIZE_BYTES = 5 * 1024 * 1024;

export async function POST(req: NextRequest) {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  const formData = await req.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "Fayl topilmadi" }, { status: 400 });
  }
  if (file.size > MAX_SIZE_BYTES) {
    return NextResponse.json({ error: "Fayl hajmi 5MB dan oshmasligi kerak" }, { status: 400 });
  }

  try {
    const buffer = Buffer.from(await file.arrayBuffer());
    const extension = imageExtension(file.type, buffer);
    if (!extension) {
      return NextResponse.json(
        { error: "Faqat haqiqiy PNG, JPEG, WebP yoki GIF rasmlari qabul qilinadi" },
        { status: 400 },
      );
    }

    await mkdir(UPLOAD_DIR, { recursive: true });

    const filename = `${randomUUID()}${extension}`;
    await writeFile(path.join(UPLOAD_DIR, filename), buffer);

    return NextResponse.json({ url: `/uploads/${filename}` }, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
