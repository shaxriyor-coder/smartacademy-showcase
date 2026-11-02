// In-memory brute-force guard for the login form. A Map is enough here —
// this is a single-process admin tool, not a multi-instance deployment, so
// there's no need for a DB-backed store that would survive a restart or be
// shared across processes.
type Entry = { failures: number; firstFailureAt: number; lockedUntil: number | null };

const attempts = new Map<string, Entry>();

const MAX_FAILURES = 5;
const FAILURE_WINDOW_MS = 15 * 60 * 1000;
const LOCKOUT_MS = 15 * 60 * 1000;

function key(email: string): string {
  return email.trim().toLowerCase();
}

export function isLocked(email: string): boolean {
  const entry = attempts.get(key(email));
  if (!entry?.lockedUntil) return false;
  if (Date.now() > entry.lockedUntil) {
    attempts.delete(key(email));
    return false;
  }
  return true;
}

export function recordFailure(email: string): void {
  const k = key(email);
  const now = Date.now();
  const entry = attempts.get(k);

  if (!entry || now - entry.firstFailureAt > FAILURE_WINDOW_MS) {
    attempts.set(k, { failures: 1, firstFailureAt: now, lockedUntil: null });
    return;
  }

  entry.failures += 1;
  if (entry.failures >= MAX_FAILURES) {
    entry.lockedUntil = now + LOCKOUT_MS;
  }
}

export function recordSuccess(email: string): void {
  attempts.delete(key(email));
}
