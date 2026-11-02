import { Prisma } from "@prisma/client";
import { generateLinkCode } from "./link-code";

export type StudentInput = {
  firstName: string;
  lastName?: string | null;
  birthDate?: string | null; // "YYYY-MM-DD"
  grade?: string | null;
};

export function toStudentData(input: StudentInput) {
  return {
    firstName: input.firstName.trim(),
    lastName: input.lastName?.trim() || null,
    // @db.Date — midnight UTC, read back with getUTC*() (see sheetParticipant)
    birthDate: input.birthDate ? new Date(`${input.birthDate}T00:00:00Z`) : null,
    grade: input.grade?.trim() || null,
  };
}

// Runs a write that needs a new unique link code, retrying on a unique-key
// clash. At 32^8 codes a clash is practically impossible, but a retry is
// cheaper than a 409 the teacher can't do anything about.
export async function withFreshLinkCode<T>(write: (code: string) => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await write(generateLinkCode());
    } catch (err) {
      const clash =
        err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002";
      if (!clash || attempt >= 2) throw err;
    }
  }
}

// A pasted class register: one student per line, "Familiya Ism [Otasining ismi]".
// A single word is taken as the first name.
export function parseRegisterLines(text: string): { firstName: string; lastName: string | null }[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/\s+/g, " "))
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(" ");
      if (parts.length === 1) return { firstName: parts[0], lastName: null };
      const [lastName, ...rest] = parts;
      return { firstName: rest.join(" "), lastName };
    });
}

export function studentDisplayName(s: { firstName: string; lastName: string | null }) {
  return [s.lastName, s.firstName].filter(Boolean).join(" ");
}
