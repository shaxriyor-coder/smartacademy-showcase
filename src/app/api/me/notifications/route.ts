import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { requireStudentSession } from "@/lib/api-auth";
import { handleApiError } from "@/lib/api-error";

const schema = z.object({ enabled: z.boolean() });

// Telegram notifications on or off for the signed-in account. In production
// the bot's /stop and /start belong to smartbot (docs/DECISIONS.md #23), so
// this is the switch.
export async function PATCH(req: NextRequest) {
  const auth = await requireStudentSession();
  if ("error" in auth) return auth.error;

  const parsed = schema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const account = await prisma.telegramAccount.update({
      where: { id: auth.session.user.id },
      // Switching on is also the moment to try reaching the account again.
      data: { notifyEnabled: parsed.data.enabled, ...(parsed.data.enabled ? { botUnreachableAt: null } : {}) },
      select: { notifyEnabled: true },
    });
    return NextResponse.json(account);
  } catch (err) {
    return handleApiError(err);
  }
}
