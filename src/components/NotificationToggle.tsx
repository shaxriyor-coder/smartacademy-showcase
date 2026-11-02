"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { jsonFetch } from "@/lib/fetch-error";

// The family cabinet's switch for Telegram notifications, and the place that
// says when they aren't getting through (src/lib/notifications.ts).
export default function NotificationToggle({
  enabled,
  unreachable,
}: {
  enabled: boolean;
  unreachable: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function set(next: boolean) {
    setBusy(true);
    setError(null);
    try {
      await jsonFetch("/api/me/notifications", { method: "PATCH", body: JSON.stringify({ enabled: next }) });
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const state = !enabled
    ? { icon: "🔕", text: "Telegram xabarlari o'chirilgan", tone: "text-muted" }
    : unreachable
      ? { icon: "!", text: "Telegram xabarlari yetib bormayapti — botni bloklamaganingizni tekshiring", tone: "text-amber-200" }
      : { icon: "🔔", text: "Natija, yangi test va eslatmalar Telegram'ga keladi", tone: "text-muted" };

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm">
      <span className={state.tone}>
        <span aria-hidden>{state.icon} </span>
        {state.text}
        {error && <span className="ml-2 text-red-300">{error}</span>}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={() => void set(!enabled || unreachable)}
        className="btn-ghost !px-3 !py-1 text-xs"
      >
        {busy ? "..." : !enabled ? "Yoqish" : unreachable ? "Qayta urinish" : "O'chirish"}
      </button>
    </div>
  );
}
