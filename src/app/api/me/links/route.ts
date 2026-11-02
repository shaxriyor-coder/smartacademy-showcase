import { NextRequest, NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { requireStudentSession } from "@/lib/api-auth";
import { linkCodeSchema } from "@/lib/validation";
import { handleApiError } from "@/lib/api-error";
import { normalizeLinkCode } from "@/lib/link-code";
import { studentDisplayName } from "@/lib/students";

// A logged-in Telegram account (a student or a parent) links a student using
// the code their teacher handed out. One account may link several children.
export async function POST(req: NextRequest) {
  const auth = await requireStudentSession();
  if ("error" in auth) return auth.error;

  const parsed = linkCodeSchema.safeParse(await req.json());
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.flatten() }, { status: 400 });
  }

  try {
    const student = await prisma.student.findUnique({
      where: { linkCode: normalizeLinkCode(parsed.data.linkCode) },
    });
    if (!student) {
      return NextResponse.json(
        { error: "Kod topilmadi — o'qituvchidan kodni qayta so'rang" },
        { status: 404 },
      );
    }

    try {
      await prisma.studentTelegramLink.create({
        data: { studentId: student.id, telegramAccountId: auth.session.user.id },
      });
    } catch (err) {
      const alreadyLinked =
        err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002";
      if (!alreadyLinked) throw err;
    }
    return NextResponse.json({ studentName: studentDisplayName(student) }, { status: 201 });
  } catch (err) {
    return handleApiError(err);
  }
}
