import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { hasTeacherAccess, isManager } from "./roles";

// Server-page counterparts of src/lib/api-auth.ts. src/proxy.ts already
// redirects by path prefix; these give the page a typed session and keep the
// rule next to the data it protects.

export async function staffPageSession() {
  const session = await auth();
  if (session?.user.kind !== "admin") redirect("/login");
  return session;
}

export async function teacherPageSession() {
  const session = await staffPageSession();
  if (!hasTeacherAccess(session.user)) redirect("/");
  return session;
}

export async function managerPageSession() {
  const session = await staffPageSession();
  if (!isManager(session.user.role)) redirect("/");
  return session;
}
