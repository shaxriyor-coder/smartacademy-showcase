// Client-side helpers for calling our API routes. Routes answer errors either
// as { error: "message" } or with zod's flatten() shape
// { error: { formErrors, fieldErrors } } — both become one readable line.

export function apiErrorMessage(body: unknown, fallback = "Xatolik yuz berdi"): string {
  if (!body || typeof body !== "object" || !("error" in body)) return fallback;
  const error = (body as { error: unknown }).error;
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const { formErrors, fieldErrors } = error as {
      formErrors?: string[];
      fieldErrors?: Record<string, string[] | undefined>;
    };
    const first = formErrors?.[0] ?? Object.values(fieldErrors ?? {}).flat().find(Boolean);
    if (first) return first;
  }
  return fallback;
}

export async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(apiErrorMessage(body));
  return body as T;
}
