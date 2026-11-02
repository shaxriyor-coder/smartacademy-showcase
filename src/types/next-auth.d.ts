import { DefaultSession } from "next-auth";
import type { StaffRole } from "@/lib/roles";

// Two kinds of principal share this one NextAuth setup:
// - "admin" — staff (SuperAdmin, Admin or Teacher): email+password, optional
//   Telegram OTP 2FA. What they may do depends on `role` (src/lib/roles.ts).
// - "student" — Telegram Login Widget only, no password.
// `role` only ever exists on an "admin" session; every staff guard
// (src/lib/api-auth.ts, src/proxy.ts) checks `kind === "admin"` explicitly
// rather than just "is there a session", so a student session can never pass
// a staff check by accident.
// `canTeach` — admin/super admin who also teaches: role stays, teacher side
// opens on top of it (src/lib/roles.ts, docs/DECISIONS.md #30).
declare module "next-auth" {
  interface Session {
    user: {
      id: string;
      kind: "admin" | "student";
      role?: StaffRole;
      canTeach?: boolean;
    } & DefaultSession["user"];
  }

  interface User {
    kind: "admin" | "student";
    role?: StaffRole;
    canTeach?: boolean;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    id: string;
    kind: "admin" | "student";
    role?: StaffRole;
    canTeach?: boolean;
  }
}
