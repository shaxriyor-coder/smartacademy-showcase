import { NextRequest, NextResponse } from "next/server";
import { requireTeacher } from "@/lib/api-auth";
import { ownAssignment } from "@/lib/access";
import { handleApiError } from "@/lib/api-error";
import { buildResultsWorkbook, loadExportData } from "@/lib/assignment-export";
import { renderResultsHtml } from "@/lib/assignment-export-core";

type Params = { params: Promise<{ id: string }> };

// Topshiriq natijalarini yuklab olish: `?format=xlsx` yoki `?format=html`
// (docs/DECISIONS.md #34). HTML'da har bir o'quvchining javoblari ham bor —
// ismni bosganda ochiladi; Excel esa jadval sifatida ishlash uchun.
export async function GET(req: NextRequest, { params }: Params) {
  const auth = await requireTeacher();
  if ("error" in auth) return auth.error;

  // Papka nomi `[id]` — shu segmentda butun ilova bo'ylab bitta nom
  // bo'lishi kerak (yonidagi `/api/assignments/[id]` bilan bir xil).
  const { id: assignmentId } = await params;
  const format = req.nextUrl.searchParams.get("format") === "xlsx" ? "xlsx" : "html";

  try {
    await ownAssignment(assignmentId, auth.session.user.id);
    const data = await loadExportData(assignmentId);
    if (!data) return NextResponse.json({ error: "Topilmadi" }, { status: 404 });

    // Fayl nomi: sarlavha + guruh. ASCII bo'lmagan harflar uchun filename*
    // ishlatiladi, aks holda brauzer nomni buzib saqlaydi.
    const base = `${data.title} - ${data.classroom}`.replace(/[\\/:*?"<>|]/g, "-").slice(0, 80);
    const disposition = `attachment; filename="natijalar.${format}"; filename*=UTF-8''${encodeURIComponent(
      `${base}.${format}`,
    )}`;

    if (format === "xlsx") {
      const buffer = await buildResultsWorkbook(data);
      return new NextResponse(new Uint8Array(buffer), {
        headers: {
          "Content-Type":
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "Content-Disposition": disposition,
        },
      });
    }

    return new NextResponse(renderResultsHtml(data), {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Disposition": disposition,
      },
    });
  } catch (err) {
    return handleApiError(err);
  }
}
