"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { jsonFetch } from "@/lib/fetch-error";

export default function LinkStudentForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const linkCode = ((new FormData(form).get("linkCode") as string | null) ?? "").trim();
    if (!linkCode) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await jsonFetch<{ studentName: string }>("/api/me/links", {
        method: "POST",
        body: JSON.stringify({ linkCode }),
      });
      setMessage({ ok: true, text: `${res.studentName} ulandi` });
      form.reset();
      router.refresh();
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="flex flex-wrap gap-2">
        <input
          name="linkCode"
          required
          placeholder="Masalan: K7M2-Q9XP"
          autoComplete="off"
          className="input-field min-w-[200px] flex-1 font-mono uppercase"
        />
        <button className="btn-gold" disabled={busy}>
          {busy ? "..." : "Ulash"}
        </button>
      </div>
      {message && (
        <p className={`mt-2 text-sm ${message.ok ? "text-emerald-300" : "text-red-300"}`}>
          {message.text}
        </p>
      )}
    </form>
  );
}
