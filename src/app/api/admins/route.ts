import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { prisma } from "@/lib/prisma";
import { requireSuperAdmin } from "@/lib/api-auth";
import { adminCreateSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { STAFF_SELECT } from "@/lib/staff";

// Staff: super admins, admins and teachers (see src/lib/roles.ts).
export async function GET() {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  try {
    const staff = await prisma.user.findMany({
      select: STAFF_SELECT,
      orderBy: { createdAt: "asc" },
    });
    return NextResponse.json(staff);
  } catch (err) {
    return handleApiError(err);
  }
}

export async function POST(req: NextRequest) {
  const auth = await requireSuperAdmin();
  if ("error" in auth) return auth.error;

  const body = await req.json();
  if (body.telegramChatId === "") body.telegramChatId = null;
  const parsed = adminCreateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const passwordHash = await bcrypt.hash(parsed.data.password, 10);
    const user = await prisma.user.create({
      data: {
        name: parsed.data.name,
        email: parsed.data.email,
        role: parsed.data.role,
        passwordHash,
        telegramChatId: parsed.data.telegramChatId,
      },
      select: STAFF_SELECT,
    });

    return NextResponse.json(user, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
