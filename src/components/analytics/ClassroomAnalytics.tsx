"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { scoreTone, type ClassroomAnalytics as Analytics } from "@/lib/analytics-core";
import { apiErrorMessage } from "@/lib/fetch-error";
import ScoreBar from "@/components/ScoreBar";
import AnswerMix from "./AnswerMix";
import MixBar from "./MixBar";
import ProgressChart from "./ProgressChart";
import RateList from "./RateList";
import StatTile from "./StatTile";
import { STATUS } from "./colors";

type AssignmentRow = Omit<Analytics["assignments"][number], "createdAt"> & {
  dayLabel: string;
  dateLabel: string;
};
type Data = Omit<Analytics, "assignments"> & { assignments: AssignmentRow[] };

const pct = (n: number | null) => (n == null ? "—" : `${n}%`);

function Change({ value }: { value: number | null }) {
  if (value == null || value === 0) return null;
  return (
    <span className={`ml-1 text-xs ${value > 0 ? "text-emerald-300" : "text-red-300"}`}>
      <span aria-hidden>{value > 0 ? "▲" : "▼"}</span>
      {value > 0 ? "+" : "−"}
      {Math.abs(value)}
    </span>
  );
}

// The teacher's view of one classroom as a whole.
export default function ClassroomAnalytics({ classroomId }: { classroomId: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/classrooms/${classroomId}/analytics`)
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok) throw new Error(apiErrorMessage(body, "Tahlilni yuklab bo'lmadi"));
        return body as Data;
      })
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      });
    return () => {
      cancelled = true;
    };
  }, [classroomId]);

  if (error) {
    return (
      <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">{error}</p>
    );
  }
  if (!data) return <p className="text-sm text-muted">Tahlil yuklanmoqda...</p>;

  const a = data;
  const withResults = a.assignments.filter((x) => x.average != null);
  if (withResults.length === 0) {
    return (
      <section className="glass-panel p-6 text-sm text-muted">
        Hali tekshirilgan natija yo&apos;q. Test biriktiring — natijalar kelishi bilan guruh tahlili shu
        yerda paydo bo&apos;ladi.
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Guruh o'rtachasi"
          value={pct(a.average)}
          delta={a.change == null ? null : { value: a.change, suffix: "%", caption: "oldingi testga nisbatan" }}
          note={`${a.counts.checked} ta natija bo'yicha`}
        />
        <StatTile
          label="Topshirish darajasi"
          value={pct(a.completion)}
          note={`${a.counts.checked} topshirgan · ${a.counts.missed} topshirmagan${a.counts.pending ? ` · ${a.counts.pending} kutilmoqda` : ""}`}
        />
        <StatTile
          label="E'tibor talab qiladi"
          value={`${a.attention.length} ta o'quvchi`}
          note={a.attention.length ? "past natija yoki keskin pasayish" : "hamma o'quvchi me'yorda"}
        />
        <StatTile
          label="Natijali testlar"
          value={`${withResults.length}`}
          note={`${a.assignments.length} ta topshiriqdan`}
        />
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Guruh natijasi dinamikasi</h2>
        <p className="mb-4 text-xs text-muted">Har bir topshiriq bo&apos;yicha guruh o&apos;rtachasi.</p>
        {withResults.length >= 2 ? (
          <ProgressChart
            seriesLabel="Guruh o'rtachasi"
            points={withResults.map((x) => ({
              id: x.id,
              title: x.title,
              subjectName: x.subjectName,
              dayLabel: x.dayLabel,
              dateLabel: x.dateLabel,
              percentage: x.average!,
              classAverage: null,
            }))}
          />
        ) : (
          <p className="text-sm text-muted">Grafik uchun kamida 2 ta natijali topshiriq kerak.</p>
        )}

        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <caption className="sr-only">Topshiriqlar bo&apos;yicha guruh natijalari</caption>
            <thead>
              <tr className="border-b border-white/10 text-left text-xs text-muted">
                <th className="py-2 pr-3 font-semibold">Sana</th>
                <th className="py-2 pr-3 font-semibold">Topshiriq</th>
                <th className="py-2 pr-3 text-right font-semibold">Topshirgan</th>
                <th className="py-2 pr-3 text-right font-semibold">O&apos;rtacha</th>
                <th className="py-2 pr-3 text-right font-semibold">Eng past – yuqori</th>
              </tr>
            </thead>
            <tbody>
              {[...a.assignments].reverse().map((x) => (
                <tr key={x.id} className="border-b border-white/5">
                  <td className="whitespace-nowrap py-2 pr-3 text-xs tabular-nums text-muted">{x.dateLabel}</td>
                  <td className="py-2 pr-3">
                    <Link href={`/classrooms/${classroomId}/assignments/${x.id}`} className="hover:underline">
                      {x.title}
                    </Link>
                    <span className="ml-1.5 text-xs text-muted">{x.mode === "ONLINE" ? "online" : "qog'ozda"}</span>
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                    {x.checked}/{x.assigned}
                    {x.missed > 0 && <span className="ml-1 text-xs text-red-300">· {x.missed} topshirmadi</span>}
                  </td>
                  <td className={`py-2 pr-3 text-right font-semibold tabular-nums ${scoreTone(x.average)}`}>
                    {pct(x.average)}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums text-muted">
                    {x.min == null ? "—" : `${x.min}% – ${x.max}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">O&apos;quvchilar taqsimoti</h2>
          {/* weak → developing → strong: only validated neighbours touch */}
          <MixBar
            segments={[
              { key: "weak", label: "Zaif (<50%)", icon: "!", color: STATUS.critical, value: a.distribution.weak },
              { key: "developing", label: "O'rtacha", icon: "◐", color: STATUS.warning, value: a.distribution.developing },
              { key: "strong", label: "Yaxshi (80%+)", icon: "✓", color: STATUS.good, value: a.distribution.strong },
            ]}
            note={
              a.distribution.noResults > 0
                ? `${a.distribution.noResults} ta o'quvchida hali natija yo'q.`
                : undefined
            }
          />
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">E&apos;tibor talab qiladi</h2>
          {a.attention.length > 0 ? (
            <ul className="space-y-2 text-sm">
              {a.attention.map((s) => (
                <li key={s.id} className="flex flex-wrap items-baseline justify-between gap-2">
                  <Link href={`/classrooms/${classroomId}/students/${s.id}`} className="font-semibold hover:underline">
                    {s.name}
                  </Link>
                  <span className="text-xs text-muted">
                    {s.reason === "low" ? (
                      <>
                        <span aria-hidden className="text-red-300">! </span>
                        o&apos;rtacha {s.average}%
                      </>
                    ) : (
                      <>
                        <span aria-hidden className="text-red-300">▼ </span>
                        oxirgi testda {Math.abs(s.change!)} ballga pasaygan
                      </>
                    )}
                    {s.weakestTopic && ` · ${s.weakestTopic.name} (${s.weakestTopic.percentage}%)`}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              Past natijali yoki keskin pasaygan o&apos;quvchi yo&apos;q.
            </p>
          )}
        </section>
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">O&apos;quvchilar</h2>
        <p className="mb-4 text-xs text-muted">Eng past o&apos;rtachadan boshlab.</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-xs text-muted">
                <th className="py-2 pr-3 font-semibold">O&apos;quvchi</th>
                <th className="py-2 pr-3 text-right font-semibold">Topshirgan</th>
                <th className="w-44 py-2 pr-3 font-semibold">O&apos;rtacha</th>
                <th className="py-2 pr-3 text-right font-semibold">Oxirgi</th>
                <th className="py-2 pr-3 font-semibold">Eng zaif mavzu</th>
              </tr>
            </thead>
            <tbody>
              {a.students.map((s) => (
                <tr key={s.id} className="border-b border-white/5">
                  <td className="py-2 pr-3">
                    <Link href={`/classrooms/${classroomId}/students/${s.id}`} className="font-semibold hover:underline">
                      {s.name}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                    {s.checked}/{s.assigned}
                    {s.missed > 0 && <span className="ml-1 text-xs text-red-300">· {s.missed} topshirmadi</span>}
                  </td>
                  <td className="py-2 pr-3">
                    {s.average == null ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className={`w-12 text-xs font-semibold tabular-nums ${scoreTone(s.average)}`}>{s.average}%</span>
                        <ScoreBar percentage={s.average} label={`${s.name}: o'rtacha ${s.average}%`} />
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {pct(s.last)}
                    <Change value={s.change} />
                  </td>
                  <td className="py-2 pr-3 text-xs text-muted">
                    {s.weakestTopic ? `${s.weakestTopic.name} (${s.weakestTopic.percentage}%)` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Mavzular bo&apos;yicha</h2>
        <p className="mb-4 text-xs text-muted">Butun guruh javoblari, eng zaif mavzular yuqorida.</p>
        <RateList
          empty="Savollarga mavzu biriktirilmagan."
          rows={a.themes.map((t) => ({
            ...t,
            key: t.id,
            hint: t.subjectName,
            children: t.subThemes.map((st) => ({ ...st, key: st.id })),
          }))}
        />
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="glass-panel p-5">
          <h2 className="font-display text-base font-bold">Eng qiyin savollar</h2>
          <p className="mb-3 text-xs text-muted">Kamida 3 kishi yechgan topshiriqlardan, eng kam topilganlari.</p>
          {a.hardest.length > 0 ? (
            <ol className="space-y-2.5 text-sm">
              {a.hardest.map((q) => (
                <li key={q.key} className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0">
                    <Link href={`/classrooms/${classroomId}/assignments/${q.assignmentId}`} className="hover:underline">
                      {q.assignmentTitle}
                    </Link>
                    <span className="text-muted"> · {q.number}-savol</span>
                    {q.themes.length > 0 && <span className="block text-xs text-muted">{q.themes.join(", ")}</span>}
                  </span>
                  <span className="shrink-0 text-right">
                    <span className={`font-semibold tabular-nums ${scoreTone(q.percentage)}`}>{q.percentage}%</span>
                    <span className="block text-xs text-muted">
                      {q.correct}/{q.total} · javob {q.answer}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted">Hali yetarli natija yo&apos;q.</p>
          )}
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Javoblar tarkibi</h2>
          <AnswerMix {...a.answerMix} />
          <h3 className="mb-3 mt-6 font-display text-sm font-bold">
            {a.skills.length > 0 ? "Ko'nikmalar bo'yicha" : "Qiyinlik darajasi bo'yicha"}
          </h3>
          <RateList
            empty="Savollarga qiyinlik darajasi belgilanmagan."
            rows={
              a.skills.length > 0
                ? a.skills.map((s) => ({ ...s, key: s.name }))
                : a.difficulty.map((d) => ({ ...d, key: d.name }))
            }
          />
        </section>
      </div>
    </div>
  );
}
