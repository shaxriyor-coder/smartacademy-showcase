import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

// For the deploy script and monitoring (docs/DEPLOY.md): the app answers and
// reaches its database. Public, and says nothing else.
export async function GET() {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ ok: false }, { status: 503 });
  }
}
