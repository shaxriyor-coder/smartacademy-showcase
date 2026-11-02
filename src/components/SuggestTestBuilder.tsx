"use client";

import Link from "next/link";
import { useState } from "react";
import { jsonFetch } from "@/lib/fetch-error";
import type { LoadedSuggestion } from "@/lib/suggest";
import type { Standing } from "@/lib/suggest-core";

type ClassroomOption = { id: string; name: string; subjectId: string | null; students: { id: string; name: string }[] };
type Picked = LoadedSuggestion["questions"][number];

const COUNTS = [10, 15, 20, 30, 40];

// Icon + word for every standing, so it never rests on colour.
const STANDING: Record<Standing, { icon: string; label: string; className: string }> = {
  weak: { icon: "!", label: "zaif", className: "bg-red-400/10 text-red-300" },
  developing: { icon: "◐", label: "o'rtacha", className: "bg-amber-400/10 text-amber-200" },
  strong: { icon: "✓", label: "yaxshi", className: "bg-emerald-400/10 text-emerald-300" },
  few: { icon: "?", label: "kam ma'lumot", className: "bg-white/10 text-muted" },
  untested: { icon: "○", label: "hali sinalmagan", className: "bg-white/10 text-muted" },
};

function StandingTag({ standing, rate }: { standing: Standing; rate: number | null }) {
  const s = STANDING[standing];
  return (
    <span className={`tag ${s.className}`}>
      <span aria-hidden>{s.icon}</span> {s.label}
      {rate != null && ` ${rate}%`}
    </span>
  );
}

export default function SuggestTestBuilder({
  classrooms,
  subjects,
  initialClassroomId,
  initialStudentId,
}: {
  classrooms: ClassroomOption[];
  subjects: { id: string; name: string }[];
  initialClassroomId: string;
  initialStudentId: string;
}) {
  const initial = classrooms.find((c) => c.id === initialClassroomId)!;
  const [classroomId, setClassroomId] = useState(initial.id);
  const [studentId, setStudentId] = useState(initialStudentId);
  const [subjectId, setSubjectId] = useState(initial.subjectId ?? subjects[0]?.id ?? "");
  const [count, setCount] = useState(15);

  const [suggestion, setSuggestion] = useState<LoadedSuggestion | null>(null);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [discarded, setDiscarded] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdTestId, setCreatedTestId] = useState<string | null>(null);

  const classroom = classrooms.find((c) => c.id === classroomId)!;

  function chooseClassroom(id: string) {
    const next = classrooms.find((c) => c.id === id)!;
    setClassroomId(id);
    setStudentId("");
    if (next.subjectId) setSubjectId(next.subjectId);
    setSuggestion(null);
  }

  async function suggest() {
    setBusy(true);
    setError(null);
    setCreatedTestId(null);
    try {
      const s = await jsonFetch<LoadedSuggestion>("/api/tests/suggest", {
        method: "POST",
        body: JSON.stringify({ classroomId, studentId: studentId || null, subjectId, count, seed: String(Date.now()) }),
      });
      setSuggestion(s);
      setPicked(s.questions);
      setDiscarded(new Set());
      setTitle(`${s.target.name} — ${s.subject.name}, takrorlash`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const pickedIds = new Set(picked.map((q) => q.id));
  const nextAlternate = (q: Picked) =>
    suggestion?.alternates[q.themeKey]?.find((a) => !pickedIds.has(a.id) && !discarded.has(a.id)) ?? null;

  function swap(index: number) {
    const current = picked[index];
    const alt = nextAlternate(current);
    if (!alt) return;
    setDiscarded(new Set(discarded).add(current.id));
    setPicked(picked.map((q, i) => (i === index ? { ...alt, themeKey: q.themeKey, standing: q.standing, rate: q.rate } : q)));
  }

  function remove(index: number) {
    setDiscarded(new Set(discarded).add(picked[index].id));
    setPicked(picked.filter((_, i) => i !== index));
  }

  async function create() {
    if (!suggestion) return;
    setBusy(true);
    setError(null);
    try {
      const test = await jsonFetch<{ id: string }>("/api/tests", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), subjectId: suggestion.subject.id, questionIds: picked.map((q) => q.id), isOlympiad: false }),
      });
      setCreatedTestId(test.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (createdTestId) {
    return (
      <div className="glass-panel mx-auto max-w-lg p-8 text-center">
        <h2 className="mb-2 font-display text-xl font-bold">Test tayyor!</h2>
        <p className="mb-6 text-sm text-muted">
          &quot;{title}&quot; — {picked.length} ta savol. Endi uni guruhga online yoki qog&apos;ozda biriktiring.
        </p>
        <div className="flex flex-col gap-3">
          <Link href={`/classrooms/${classroomId}`} className="btn-gold">
            Guruhga biriktirish
          </Link>
          <a href={`/api/tests/${createdTestId}/export`} className="btn-ghost">
            Word&apos;da yuklab olish
          </a>
          <button type="button" className="btn-ghost" onClick={() => { setCreatedTestId(null); setSuggestion(null); }}>
            Yana test tuzish
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="glass-panel grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-5">
        <label className="block">
          <span className="label-field">Guruh</span>
          <select className="input-field" value={classroomId} onChange={(e) => chooseClassroom(e.target.value)}>
            {classrooms.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label-field">Kim uchun</span>
          <select className="input-field" value={studentId} onChange={(e) => setStudentId(e.target.value)}>
            <option value="">Butun guruh ({classroom.students.length})</option>
            {classroom.students.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label-field">Fan</span>
          <select className="input-field" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label-field">Savollar soni</span>
          <select className="input-field" value={count} onChange={(e) => setCount(Number(e.target.value))}>
            {COUNTS.map((n) => (
              <option key={n} value={n}>
                {n} ta
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <button type="button" className="btn-gold w-full" disabled={busy || !subjectId} onClick={() => void suggest()}>
            {busy && !suggestion ? "..." : suggestion ? "Yangi taklif" : "Taklif qilish"}
          </button>
        </div>
      </section>

      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">{error}</p>
      )}

      {suggestion && (
        <>
          <section className="glass-panel p-5">
            <h2 className="font-display text-base font-bold">Mavzular bo&apos;yicha taqsimot</h2>
            <p className="mb-3 text-xs text-muted">
              {suggestion.target.isGroup
                ? `${suggestion.target.name} guruhi (${suggestion.target.students} o'quvchi) natijalari bo'yicha`
                : `${suggestion.target.name} natijalari bo'yicha`}
              {" "}— faqat sizning guruhlaringizdagi testlardan.
            </p>
            <ul className="space-y-1.5 text-sm">
              {suggestion.plan.map((p) => (
                <li key={p.themeKey} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    {p.name}
                    <StandingTag standing={p.standing} rate={p.rate} />
                  </span>
                  <span className={`text-xs tabular-nums ${p.available === 0 ? "text-red-300" : "text-muted"}`}>
                    {p.available === 0 ? "bankda mos savol yo'q" : `${p.slots} ta savol · bankda ${p.available} ta`}
                  </span>
                </li>
              ))}
            </ul>
            {suggestion.shortfall > 0 && (
              <p className="mt-3 text-xs text-amber-200">
                <span aria-hidden>! </span>Bankda yetarli savol yo&apos;q: {suggestion.shortfall} ta kam.
              </p>
            )}
          </section>

          <section className="glass-panel p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-display text-base font-bold">Savollar ({picked.length})</h2>
              <span className="text-xs text-muted">Almashtirish — o&apos;sha mavzudan boshqa savol</span>
            </div>
            <ol className="space-y-2">
              {picked.map((q, i) => (
                <li key={q.id} className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-3.5">
                  <span className="mt-0.5 w-6 shrink-0 text-right text-xs tabular-nums text-muted">{i + 1}.</span>
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-sm">{q.text}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {q.themes.map((t) => (
                        <span key={t} className="tag border border-white/10 text-muted">
                          {t}
                        </span>
                      ))}
                      <span className="tag tag-gold">{q.difficulty}</span>
                      <StandingTag standing={q.standing} rate={q.rate} />
                      {q.seen > 0 && (
                        <span className="tag bg-amber-400/10 text-amber-200">
                          <span aria-hidden>⚠</span>{" "}
                          {suggestion.target.isGroup ? `${q.seen} o'quvchi ko'rgan` : "avval berilgan"}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col gap-1.5 sm:flex-row">
                    <button
                      type="button"
                      className="btn-ghost !px-2.5 !py-1 text-xs"
                      disabled={!nextAlternate(q)}
                      onClick={() => swap(i)}
                    >
                      Almashtirish
                    </button>
                    <button type="button" className="btn-danger-ghost !px-2.5 !py-1 text-xs" onClick={() => remove(i)}>
                      Olib tashlash
                    </button>
                  </div>
                </li>
              ))}
            </ol>

            <div className="mt-5 flex flex-wrap items-end gap-3 border-t border-white/10 pt-4">
              <label className="block min-w-[260px] flex-1">
                <span className="label-field">Test nomi</span>
                <input className="input-field" value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <button
                type="button"
                className="btn-gold"
                disabled={busy || picked.length === 0 || !title.trim()}
                onClick={() => void create()}
              >
                Testni yaratish ({picked.length} ta savol)
              </button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
