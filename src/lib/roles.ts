// Staff roles, in the same sense as smartbot's staff roles (utils/roles.py):
// superadmin / admin / teacher. No server imports — the header uses it too.

export const STAFF_ROLES = ["SUPER_ADMIN", "ADMIN", "TEACHER"] as const;
export type StaffRole = (typeof STAFF_ROLES)[number];

export const ROLE_LABELS: Record<StaffRole, string> = {
  SUPER_ADMIN: "SuperAdmin",
  ADMIN: "Admin",
  TEACHER: "O'qituvchi",
};

// Admins and super admins run the centre — question bank, tests, staff and
// centre-wide analytics — but never open a classroom.
export function isManager(role: StaffRole | null | undefined): boolean {
  return role === "SUPER_ADMIN" || role === "ADMIN";
}

// smartbot's staff roles (smartbot/utils/roles.py) as platform roles. SMM
// managers and reception have no panel here: they open the family cabinet.
export function staffRoleFromBot(role: string | null | undefined): StaffRole | null {
  switch (role) {
    case "superadmin":
      return "SUPER_ADMIN";
    case "admin":
      return "ADMIN";
    case "teacher":
      return "TEACHER";
    default:
      return null;
  }
}

// Only teachers own classrooms, and with them students and assignments.
export function isTeacher(role: StaffRole | null | undefined): boolean {
  return role === "TEACHER";
}

// One person can do both jobs — the centre's owner teaches a group himself.
// Instead of a second account or a second role, the staff page gives that
// admin `canTeach`: the role (and everything it opens) stays, and the
// teacher side opens on top of it. Ownership is unchanged: they see their
// OWN classrooms, exactly like a teacher (docs/DECISIONS.md #30).
export type TeacherAccess = { role?: StaffRole | null; canTeach?: boolean | null };

export function hasTeacherAccess(user: TeacherAccess | null | undefined): boolean {
  return Boolean(user && (isTeacher(user.role) || user.canTeach));
}
