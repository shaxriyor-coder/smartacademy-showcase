"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiErrorMessage } from "@/lib/fetch-error";
import type { RunnerQuestion } from "@/lib/online-core";

// Display labels by POSITION. The value sent back is the canonical letter the
// server gave each option, so shuffled options still grade correctly.
const LABELS = ["A", "B", "C", "D", "E"];

function formatRemaining(ms: number) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const mm = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export default function OnlineTestRunner({
  sheetId,
  questions,
  initialAnswers,
  deadline,
  serverNow,
}: {
  sheetId: string;
  questions: RunnerQuestion[];
  initialAnswers: string[]; // by canonical index
  deadline: string | null;
  serverNow: string;
}) {
  const router = useRouter();
  const [position, setPosition] = useState(0);
  const [answers, setAnswers] = useState<string[]>(initialAnswers);
  const [unsaved, setUnsaved] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Counted against the server's clock: a wrong phone clock can't stretch the test.
  const [remaining, setRemaining] = useState<number | null>(() =>
    deadline ? new Date(deadline).getTime() - new Date(serverNow).getTime() : null,
  );
  const answersRef = useRef(answers);
  const submitted = useRef(false);

  useEffect(() => {
    answersRef.current = answers;
  }, [answers]);

  const submit = useCallback(async () => {
    if (submitted.current) return;
    submitted.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/me/attempts/${sheetId}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Our own copy goes along, so an autosave lost to a weak connection still counts.
        body: JSON.stringify({
          answers: Object.fromEntries(answersRef.current.map((choice, i) => [String(i), choice])),
        }),
      });
      // 409: already submitted (the server's timer got there first) — the result exists.
      if (!res.ok && res.status !== 409) {
        throw new Error(apiErrorMessage(await res.json().catch(() => null), "Topshirib bo'lmadi"));
      }
      router.replace(`/classroom-home/results/${sheetId}`);
    } catch (err) {
      submitted.current = false;
      setSubmitting(false);
      setError(`${(err as Error).message}. Internetni tekshirib, qayta bosing.`);
    }
  }, [router, sheetId]);

  useEffect(() => {
    if (!deadline) return;
    const skew = new Date(serverNow).getTime() - Date.now();
    const end = new Date(deadline).getTime();
    const timer = setInterval(() => {
      const left = end - (Date.now() + skew);
      setRemaining(left);
      if (left <= 0) {
        clearInterval(timer);
        submit();
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [deadline, serverNow, submit]);

  async function choose(index: number, value: string) {
    if (submitting) return;
    const choice = answers[index] === value ? "" : value; // tapping the chosen option clears it
    setAnswers((prev) => prev.map((c, i) => (i === index ? choice : c)));
    try {
      const res = await fetch(`/api/me/attempts/${sheetId}/answer`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ index, choice }),
      });
      if (res.status === 409) {
        // Time is up, or the attempt was submitted on another device.
        router.replace(`/classroom-home/results/${sheetId}`);
        return;
      }
      setUnsaved(!res.ok);
    } catch {
      setUnsaved(true);
    }
  }

  const question = questions[position];
  const answered = answers.filter(Boolean).length;
  const unanswered = questions.length - answered;
  const selected = answers[question.index];

  return (
    <div className="space-y-4">
      <div className="glass-panel sticky top-20 z-30 flex items-center justify-between gap-3 px-4 py-3">
        <span className="text-sm text-muted">
          Javob berildi:{" "}
          <b className="text-ivory">
            {answered}/{questions.length}
          </b>
        </span>
        {remaining != null && (
          <span
            className={`font-mono text-lg font-bold ${remaining < 60_000 ? "text-red-300" : "text-gold"}`}
          >
            {formatRemaining(remaining)}
          </span>
        )}
      </div>

      {unsaved && (
        <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
          Oxirgi javob serverga yetib bormadi — internetni tekshiring. Topshirganda barcha
          javoblar qayta yuboriladi.
        </p>
      )}
      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <section className="glass-panel p-5">
        <p className="mb-2 text-xs text-muted">
          {position + 1}-savol / {questions.length}
        </p>
        <p className="whitespace-pre-wrap text-base leading-relaxed">{question.text}</p>
        {question.imageUrl && (
          // eslint-disable-next-line @next/next/no-img-element -- uploaded question images of unknown size
          <img
            src={question.imageUrl}
            alt=""
            className="mt-3 max-h-72 max-w-full rounded-lg border border-white/10"
          />
        )}

        <div className="mt-4 space-y-2">
          {question.options.map((option, i) => {
            const active = selected === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => choose(question.index, option.value)}
                disabled={submitting}
                className={`flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left transition ${
                  active
                    ? "border-gold/70 bg-gold/15"
                    : "border-white/10 bg-white/[0.03] hover:bg-white/[0.07]"
                }`}
              >
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-sm font-bold ${
                    active ? "border-gold bg-gold text-gold-ink" : "border-white/25"
                  }`}
                >
                  {LABELS[i]}
                </span>
                <span className="whitespace-pre-wrap pt-0.5">{option.text}</span>
              </button>
            );
          })}
        </div>

        <div className="mt-5 flex justify-between gap-2">
          <button
            type="button"
            className="btn-ghost"
            disabled={position === 0}
            onClick={() => setPosition((p) => p - 1)}
          >
            ← Oldingi
          </button>
          {position < questions.length - 1 ? (
            <button type="button" className="btn-gold" onClick={() => setPosition((p) => p + 1)}>
              Keyingi →
            </button>
          ) : (
            <button type="button" className="btn-gold" onClick={() => setConfirming(true)}>
              Yakunlash
            </button>
          )}
        </div>
      </section>

      <section className="glass-panel p-4">
        <div className="grid grid-cols-8 gap-1.5 sm:grid-cols-10">
          {questions.map((q, i) => (
            <button
              key={q.index}
              type="button"
              onClick={() => setPosition(i)}
              className={`rounded-lg border py-1.5 text-xs font-semibold ${
                i === position
                  ? "border-gold text-gold"
                  : answers[q.index]
                    ? "border-emerald-400/40 bg-emerald-400/15 text-emerald-200"
                    : "border-white/10 text-muted"
              }`}
            >
              {i + 1}
            </button>
          ))}
        </div>
      </section>

      {confirming ? (
        <section className="glass-panel p-5">
          <p className="mb-3 text-sm">
            {unanswered > 0 && <b className="text-gold">{unanswered} ta savolga javob berilmagan. </b>}
            Topshirgandan keyin javoblarni o&apos;zgartirib bo&apos;lmaydi.
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-gold" onClick={submit} disabled={submitting}>
              {submitting ? "Topshirilmoqda..." : "Ha, topshirish"}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setConfirming(false)}
              disabled={submitting}
            >
              Davom etish
            </button>
          </div>
        </section>
      ) : (
        <button type="button" className="btn-ghost w-full" onClick={() => setConfirming(true)}>
          Testni topshirish
        </button>
      )}
    </div>
  );
}
