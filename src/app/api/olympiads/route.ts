import { NextResponse } from "next/server";
import { requireSession } from "@/lib/api-auth";
import { smartbotOlympiads } from "@/lib/smartbot";

// Botdagi olimpiadalar ro'yxati (faqat o'qish) — test yaratishda "olimpiada
// uchun" deb belgilanganda shu ro'yxatdan tanlanadi (docs/DECISIONS.md #31).
// Bazaga ulanib bo'lmasa 503: sahifa sababini ko'rsatadi, jim qolmaydi.
export async function GET() {
  const auth = await requireSession();
  if ("error" in auth) return auth.error;

  try {
    const olympiads = await smartbotOlympiads();
    if (!olympiads) return NextResponse.json({ configured: false, olympiads: [] });
    return NextResponse.json({ configured: true, olympiads });
  } catch (err) {
    console.error("smartbot olimpiadalarini o'qib bo'lmadi", err);
    return NextResponse.json(
      { error: "Bot bazasidan olimpiadalar ro'yxatini o'qib bo'lmadi" },
      { status: 503 },
    );
  }
}
