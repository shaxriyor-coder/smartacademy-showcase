import { NextRequest, NextResponse } from "next/server";
import { requireTeacher } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";
import { ownAssignment } from "@/lib/access";
import { checkUploadedScan } from "@/lib/assignments";

type Params = { params: Promise<{ id: string }> };

const MAX_BYTES = 80 * 1024 * 1024; // checker/config.py MAX_UPLOAD_MB
const ALLOWED_TYPES = new Set(["application/pdf", "image/jpeg", "image/png"]);

export async function POST(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  const { id } = await params;
  try {
    await ownAssignment(id, auth.session.user.id);
    const form = await req.formData();
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      return NextResponse.json({ error: "Skan fayli tanlanmagan" }, { status: 400 });
    }
    if (file.size > MAX_BYTES) {
      return NextResponse.json(
        { error: "Fayl juda katta (80 MB dan oshmasin) — skanni bir necha qismga bo'ling" },
        { status: 413 },
      );
    }
    if (!ALLOWED_TYPES.has(file.type)) {
      return NextResponse.json(
        { error: "Faqat PDF, JPG yoki PNG fayl yuklang" },
        { status: 415 },
      );
    }

    const result = await checkUploadedScan(id, {
      bytes: new Uint8Array(await file.arrayBuffer()),
      name: file.name,
      type: file.type,
    });
    return NextResponse.json(result);
  } catch (err) {
    return handleApiError(err);
  }
}
