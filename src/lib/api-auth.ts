import { NextResponse } from "next/server";
import type { Session } from "next-auth";
import { auth } from "@/auth";
import { hasTeacherAccess, isManager } from "@/lib/roles";

export type AuthedSession = Session;

type Guard = Promise<{ session: AuthedSession } | { error: NextResponse }>;

const forbidden = (error: string) => ({ error: NextResponse.json({ error }, { status: 403 }) });

// "Staff session" — SuperAdmin, Admin or Teacher. Explicitly checks
// `kind === "admin"` rather than just "is there a session", because a Student
// session (Telegram Login Widget, see src/auth.ts) is also a valid NextAuth
// session and must NOT satisfy this — otherwise a student could reach
// question-bank/test staff API routes just by being logged in as themselves.
export async function requireSession(): Guard {
  const session = await auth();
  if (!session?.user || session.user.kind !== "admin") {
    return { error: NextResponse.json({ error: "Unauthorized" }, { status: 401 }) };
  }
  return { session };
}

export async function requireSuperAdmin(): Guard {
  const result = await requireSession();
  if ("error" in result) return result;
  if (result.session.user.role !== "SUPER_ADMIN") return forbidden("Forbidden");
  return result;
}

// Classrooms, their students and assignments. Teachers — and admins the
// super admin gave `canTeach` — and only their own, which each route checks
// with src/lib/access.ts.
export async function requireTeacher(): Guard {
  const result = await requireSession();
  if ("error" in result) return result;
  if (!hasTeacherAccess(result.session.user)) return forbidden("Faqat o'qituvchilar uchun");
  return result;
}

// Centre-wide views: Admin or SuperAdmin.
export async function requireManager(): Guard {
  const result = await requireSession();
  if ("error" in result) return result;
  if (!isManager(result.session.user.role)) return forbidden("Faqat adminlar uchun");
  return result;
}

// Mirror of requireSession() for the student side — rejects staff sessions
// the same way requireSession() rejects student ones.
export async function requireStudentSession(): Guard {
  const session = await auth();
  if (!session?.user || session.user.kind !== "student") {
    return { error: NextResponse.json({ error: "Unauthorized" }, { status: 401 }) };
  }
  return { session };
}
