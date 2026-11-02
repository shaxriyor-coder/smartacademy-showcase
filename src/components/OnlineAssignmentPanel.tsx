"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { jsonFetch } from "@/lib/fetch-error";
import { fromLocalInput, toLocalInput } from "@/lib/datetime-local";
import { REVEAL_LABELS, type RevealPolicyValue } from "@/lib/online-core";
import ArchiveAssignmentButton from "./ArchiveAssignmentButton";
import { useDialog } from "@/components/DialogProvider";

type Settings = {
  opensAt: string | null;
  closesAt: string | null;
  timeLimitMinutes: number | null;
  shuffle: boolean;
  revealAnswers: RevealPolicyValue;
};

export default function OnlineAssignmentPanel({
  assignmentId,
  classroomId,
  settings,
}: {
  assignmentId: string;
  classroomId: string;
  settings: Settings;
}) {
  const router = useRouter();
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>, success: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await jsonFetch(`/api/assignments/${assignmentId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setNotice(success);
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const text = (name: string) => ((data.get(name) as string | null) ?? "").trim();
    patch(
      {
        opensAt: fromLocalInput(text("opensAt")),
        closesAt: fromLocalInput(text("closesAt")),
        timeLimitMinutes: text("timeLimitMinutes") ? Number(text("timeLimitMinutes")) : null,
        revealAnswers: text("revealAnswers"),
      },
      "Saqlandi",
    );
  }

  async function closeNow() {
    if (!(await dialog.confirm("Test hozir yopilsinmi? Yechayotgan o'quvchilarning javoblari shu holatida topshiriladi."))) return;
    patch({ closesAt: new Date().toISOString() }, "Test yopildi");
  }

  return (
    <section className="glass-panel p-5">
      <h2 className="mb-1 font-display text-base font-bold">Online test sozlamalari</h2>
      <p className="mb-4 text-xs text-muted">
        O&apos;quvchilar testni kabinetida (saytda yoki Telegram Mini App&apos;da) yechadi.{" "}
        {settings.shuffle
          ? "Har o'quvchiga savollar va variantlar tartibi alohida."
          : "Savollar tartibi hammaga bir xil."}{" "}
        O&apos;zgarish yechayotganlarga ham darhol ta&apos;sir qiladi.
      </p>

      <form onSubmit={save} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className="label-field">Ochilish (bo&apos;sh — ochiq)</span>
          <input
            name="opensAt"
            type="datetime-local"
            defaultValue={toLocalInput(settings.opensAt)}
            suppressHydrationWarning
            className="input-field"
          />
        </label>
        <label className="block">
          <span className="label-field">Yopilish (bo&apos;sh — muddatsiz)</span>
          <input
            name="closesAt"
            type="datetime-local"
            defaultValue={toLocalInput(settings.closesAt)}
            suppressHydrationWarning
            className="input-field"
          />
        </label>
        <label className="block">
          <span className="label-field">Vaqt chegarasi, daqiqa</span>
          <input
            name="timeLimitMinutes"
            type="number"
            min={1}
            max={600}
            defaultValue={settings.timeLimitMinutes ?? ""}
            placeholder="cheklanmagan"
            className="input-field"
          />
        </label>
        <label className="block">
          <span className="label-field">To&apos;g&apos;ri javoblar</span>
          <select name="revealAnswers" defaultValue={settings.revealAnswers} className="input-field">
            {Object.entries(REVEAL_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap gap-2 sm:col-span-2 lg:col-span-4">
          <button className="btn-gold" disabled={busy}>
            Saqlash
          </button>
          <button type="button" onClick={closeNow} disabled={busy} className="btn-ghost">
            Hozir yopish
          </button>
          <ArchiveAssignmentButton assignmentId={assignmentId} classroomId={classroomId} />
        </div>
      </form>

      {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
      {notice && <p className="mt-3 text-sm text-emerald-300">{notice}</p>}
    </section>
  );
}
