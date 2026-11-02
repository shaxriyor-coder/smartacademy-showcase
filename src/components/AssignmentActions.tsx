"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiErrorMessage } from "@/lib/fetch-error";
import ArchiveAssignmentButton from "./ArchiveAssignmentButton";

type Outcome = {
  page: number;
  status: "saved" | "duplicate" | "error";
  message: string;
  studentName?: string;
  correct?: number;
  total?: number;
  percentage?: number;
  blank?: number;
  multi?: number;
};

type Report = { pageCount: number; outcomes: Outcome[]; annotatedUrl: string | null };

function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function fileNameFrom(res: Response, fallback: string) {
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  return match ? decodeURIComponent(match[1]) : fallback;
}

function base64ToBlob(b64: string, type: string) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return new Blob([bytes], { type });
}

export default function AssignmentActions({
  assignmentId,
  classroomId,
  templateReady,
  studentCount,
}: {
  assignmentId: string;
  classroomId: string;
  templateReady: boolean;
  studentCount: number;
}) {
  const router = useRouter();
  const [sheetsBusy, setSheetsBusy] = useState(false);
  const [checkBusy, setCheckBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  // The annotated PDF lives in a blob URL; free it when replaced or on leave.
  useEffect(() => {
    const url = report?.annotatedUrl;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [report]);

  async function downloadSheets() {
    setSheetsBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/assignments/${assignmentId}/sheets`);
      if (!res.ok) throw new Error(apiErrorMessage(await res.json().catch(() => null)));
      saveBlob(await res.blob(), fileNameFrom(res, "javob-varaqlari.pdf"));
      router.refresh(); // the template now exists, so checking becomes available
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSheetsBusy(false);
    }
  }

  async function checkScan(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Skan faylini tanlang");
      return;
    }
    setCheckBusy(true);
    setError(null);
    setReport(null);
    try {
      const res = await fetch(`/api/assignments/${assignmentId}/check`, {
        method: "POST",
        body: data,
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(apiErrorMessage(body, "Tekshirishda xatolik"));
      setReport({
        pageCount: body.pageCount,
        outcomes: body.outcomes,
        annotatedUrl: body.annotatedPdf
          ? URL.createObjectURL(base64ToBlob(body.annotatedPdf, "application/pdf"))
          : null,
      });
      form.reset();
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCheckBusy(false);
    }
  }

  const saved = report?.outcomes.filter((o) => o.status === "saved").length ?? 0;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="glass-panel p-5">
        <h2 className="mb-1 font-display text-base font-bold">1. Chop etish</h2>
        <p className="mb-4 text-xs text-muted">
          Word — savollar varag&apos;i. Javob varaqlari — har o&apos;quvchiga alohida sahifa,
          QR kodi bilan. Chop etishda «Actual size / 100%» ni tanlang.
        </p>
        <div className="flex flex-wrap gap-2">
          <a href={`/api/assignments/${assignmentId}/export`} className="btn-ghost">
            Test (Word)
          </a>
          <a href={`/api/assignments/${assignmentId}/export?key=1`} className="btn-ghost">
            Word, kalit bilan
          </a>
          <button
            onClick={downloadSheets}
            disabled={sheetsBusy || studentCount === 0}
            className="btn-gold"
          >
            {sheetsBusy ? "Tayyorlanmoqda..." : `Javob varaqlari (PDF, ${studentCount} ta)`}
          </button>
        </div>
        {sheetsBusy && !templateReady && (
          <p className="mt-3 text-xs text-muted">
            Birinchi marta shablon chiziladi — 15-30 soniya kuting.
          </p>
        )}
        {studentCount === 0 && (
          <p className="mt-3 text-xs text-muted">Guruhda o&apos;quvchi yo&apos;q.</p>
        )}
      </section>

      <section className="glass-panel p-5">
        <h2 className="mb-1 font-display text-base font-bold">2. Skanni tekshirish</h2>
        <p className="mb-4 text-xs text-muted">
          To&apos;ldirilgan varaqlarni skaner qiling (bir nechta varaq bitta PDF bo&apos;lsa
          ham bo&apos;ladi) yoki telefonda suratga oling. To&apos;rtala burchak rasmga tushsin.
        </p>
        {templateReady ? (
          <form onSubmit={checkScan} className="flex flex-wrap items-center gap-2">
            <input
              name="file"
              type="file"
              accept="application/pdf,image/jpeg,image/png"
              className="input-field min-w-[220px] flex-1 text-xs"
            />
            <button className="btn-gold" disabled={checkBusy}>
              {checkBusy ? "Tekshirilmoqda..." : "Tekshirish"}
            </button>
          </form>
        ) : (
          <p className="text-sm text-muted">
            Avval javob varaqlarini yuklab oling — tekshiruv aynan o&apos;sha varaq shabloniga
            tayanadi.
          </p>
        )}
      </section>

      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300 lg:col-span-2">
          {error}
        </p>
      )}

      {report && (
        <section className="glass-panel p-5 lg:col-span-2">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-base font-bold">
              Tekshirildi: {saved}/{report.pageCount} varaq saqlandi
            </h2>
            {report.annotatedUrl && (
              <a
                href={report.annotatedUrl}
                target="_blank"
                rel="noreferrer"
                download="tekshirilgan-varaqlar.pdf"
                className="btn-ghost !px-3 !py-1.5 text-xs"
              >
                Belgilangan varaqlar (PDF)
              </a>
            )}
          </div>
          <ul className="space-y-1.5 text-sm">
            {report.outcomes.map((o) => (
              <li key={o.page} className="flex flex-wrap gap-x-2">
                <span className="text-muted">{o.page}-varaq:</span>
                {o.status === "saved" && (
                  <span className="text-emerald-300">
                    ✓ {o.studentName} — {o.correct}/{o.total} ({o.percentage}%)
                    {o.blank ? ` · ${o.blank} ta bo'sh` : ""}
                    {o.multi ? ` · ⚠ ${o.multi} ta ko'p belgilangan` : ""}
                  </span>
                )}
                {o.status === "duplicate" && (
                  <span className="text-gold">
                    ⏭ {o.studentName} — {o.message}
                  </span>
                )}
                {o.status === "error" && (
                  <span className="text-red-300">
                    ✗ {o.studentName ? `${o.studentName} — ` : ""}
                    {o.message}
                  </span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            Belgilangan PDF&apos;da: yashil — to&apos;g&apos;ri, qizil — noto&apos;g&apos;ri,
            ko&apos;k — to&apos;g&apos;ri javob qayerda edi.
          </p>
        </section>
      )}

      <div className="lg:col-span-2">
        <ArchiveAssignmentButton assignmentId={assignmentId} classroomId={classroomId} />
      </div>
    </div>
  );
}
