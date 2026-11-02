"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiErrorMessage } from "@/lib/fetch-error";

export default function StartAttemptButton({ sheetId }: { sheetId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/me/attempts/${sheetId}/start`, { method: "POST" });
    if (!res.ok) {
      setError(apiErrorMessage(await res.json().catch(() => null)));
      setBusy(false);
      return;
    }
    router.refresh(); // the page re-renders with the questions
  }

  return (
    <div>
      <button onClick={start} disabled={busy} className="btn-gold w-full">
        {busy ? "Boshlanmoqda..." : "Testni boshlash"}
      </button>
      {error && <p className="mt-2 text-sm text-red-300">{error}</p>}
    </div>
  );
}
