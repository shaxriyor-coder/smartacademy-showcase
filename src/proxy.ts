import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { hasTeacherAccess, isManager } from "@/lib/roles";

const SUPER_ADMIN_ONLY_PREFIXES = ["/categories", "/admins"];
// Classrooms belong to teachers; admins see the centre through /analytics
// instead (docs/DECISIONS.md #20).
const TEACHER_ONLY_PREFIXES = ["/classrooms", "/tests/suggest"];
const MANAGER_ONLY_PREFIXES = ["/analytics"];

// Student-facing pages are a small, explicit list (phase 1 has almost none
// yet) — everything NOT in this list is treated as an admin page. This is
// the inverse of how SUPER_ADMIN_ONLY_PREFIXES works on purpose: the admin
// side is the large, growing surface, so it's cheaper to enumerate the
// small student side than to keep every new admin route in sync with it.
const STUDENT_PREFIXES = ["/classroom-home"];
const STUDENT_LOGIN_PATHS = ["/login/student", "/login/student/dev"];
const ADMIN_LOGIN_PATHS = ["/login", "/login/verify"];
// Telegram Mini App entry (src/app/tg/page.tsx). Open to everyone, signed in
// or not: it signs in whoever Telegram says opened it, replacing any stale
// session left in the in-app browser.
const MINI_APP_PATH = "/tg";

export default auth((req) => {
  const { nextUrl } = req;
  const path = nextUrl.pathname;
  const user = req.auth?.user;

  if (path === MINI_APP_PATH) return NextResponse.next();

  const isStudentLoginPage = STUDENT_LOGIN_PATHS.includes(path);
  const isAdminLoginPage = ADMIN_LOGIN_PATHS.includes(path);
  const isStudentArea = STUDENT_PREFIXES.some((prefix) => path.startsWith(prefix));

  if (!user) {
    if (isStudentArea && !isStudentLoginPage) {
      return NextResponse.redirect(new URL("/login/student", nextUrl.origin));
    }
    if (!isStudentArea && !isAdminLoginPage && !isStudentLoginPage) {
      const loginUrl = new URL("/login", nextUrl.origin);
      loginUrl.searchParams.set("callbackUrl", path);
      return NextResponse.redirect(loginUrl);
    }
    return NextResponse.next();
  }

  // Logged in as a student: only the student area (+ its own login pages,
  // harmless to allow through while signed in) is reachable — everything
  // else bounces back to their home, never an admin page.
  if (user.kind === "student") {
    if (isStudentArea) return NextResponse.next();
    return NextResponse.redirect(new URL("/classroom-home", nextUrl.origin));
  }

  // Logged in as an admin: the student area and its login pages aren't for
  // them either.
  if (isStudentArea || isStudentLoginPage || isAdminLoginPage) {
    return NextResponse.redirect(new URL("/", nextUrl.origin));
  }

  const requiresSuperAdmin = SUPER_ADMIN_ONLY_PREFIXES.some((prefix) =>
    path.startsWith(prefix),
  );
  if (requiresSuperAdmin && user.role !== "SUPER_ADMIN") {
    return NextResponse.redirect(new URL("/", nextUrl.origin));
  }
  if (TEACHER_ONLY_PREFIXES.some((prefix) => path.startsWith(prefix)) && !hasTeacherAccess(user)) {
    return NextResponse.redirect(new URL("/", nextUrl.origin));
  }
  if (MANAGER_ONLY_PREFIXES.some((prefix) => path.startsWith(prefix)) && !isManager(user.role)) {
    return NextResponse.redirect(new URL("/", nextUrl.origin));
  }

  return NextResponse.next();
});

export const config = {
  // Middleware only guards pages (redirects). API routes check the session
  // themselves and return JSON 401/403 responses instead of redirecting.
  // Static assets (logo, uploaded images, etc.) are excluded too, since
  // Next's image optimizer fetches them internally and can't follow a
  // redirect to /login.
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|uploads|.*\\.(?:jpg|jpeg|png|gif|webp|svg|ico)$).*)",
  ],
};
