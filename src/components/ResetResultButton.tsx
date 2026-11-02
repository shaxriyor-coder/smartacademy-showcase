"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiErrorMessage } from "@/lib/fetch-error";
import { useDialog } from "@/components/DialogProvider";

// A checked sheet is never overwritten by a new scan; this is the explicit way
// to clear a wrong result before scanning the sheet again.
export default function ResetResultButton({
  sheetId,
  studentName,
  online = false,
}: {
  sheetId: string;
  studentName: string;
  online?: boolean;
}) {
  const router = useRouter();
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);

  async function reset() {
    const question = online
      ? `${studentName} urinishi o'chirilsinmi? O'quvchi testni boshidan qayta topshira oladi.`
      : `${studentName} natijasi o'chirilsinmi? Shundan keyin varaqni qayta skanerlab tekshirish mumkin.`;
    if (!(await dialog.confirm(question))) return;
    setBusy(true);
    const res = await fetch(`/api/assignment-sheets/${sheetId}/reset`, { method: "POST" });
    setBusy(false);
    if (!res.ok) {
      await dialog.alert(apiErrorMessage(await res.json().catch(() => null)));
      return;
    }
    router.refresh();
  }

  return (
    <button onClick={reset} disabled={busy} className="btn-danger-ghost">
      {busy ? "..." : online ? "Qayta ruxsat" : "Tozalash"}
    </button>
  );
}
