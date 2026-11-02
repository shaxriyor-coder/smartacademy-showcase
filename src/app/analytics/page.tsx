import { scoreTone } from "@/lib/analytics-core";
import { loadCenterAnalytics } from "@/lib/center-analytics";
import { TOP_MIN_TESTS } from "@/lib/center-analytics-core";
import { formatTashkentDate, formatTashkentDay } from "@/lib/online-core";
import { managerPageSession } from "@/lib/page-auth";
import AnswerMix from "@/components/analytics/AnswerMix";
import MixBar from "@/components/analytics/MixBar";
import ProgressChart from "@/components/analytics/ProgressChart";
import RateList from "@/components/analytics/RateList";
import StatTile from "@/components/analytics/StatTile";
import { STATUS } from "@/components/analytics/colors";
import ScoreBar from "@/components/ScoreBar";

const ATTENTION_SHOWN = 15;
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

// Students across every classroom, for admins. Names and averages only — the
// assignments and answers inside a group stay with its teacher.
export default async function CenterStudentsPage() {
  await managerPageSession();
  const a = await loadCenterAnalytics();

  if (a.counts.results === 0) {
    return (
      <section className="glass-panel p-6 text-sm text-muted">
        Hali tekshirilgan natija yo&apos;q. O&apos;qituvchilar guruhlarga test biriktirib, natijalar
        kela boshlagach markaz tahlili shu yerda paydo bo&apos;ladi.
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="O'quvchilar"
          value={`${a.counts.students}`}
          note={`${a.counts.activeStudents} tasi so'nggi 30 kunda test topshirgan`}
        />
        <StatTile
          label="So'nggi 30 kun o'rtachasi"
          value={pct(a.recentAverage)}
          delta={a.change == null ? null : { value: a.change, suffix: "%", caption: "oldingi 30 kunga nisbatan" }}
          note={`umumiy o'rtacha ${pct(a.average)} · ${a.counts.results} ta natija`}
        />
        <StatTile
          label="Topshirish darajasi"
          value={pct(a.completion)}
          note={`${a.counts.results} topshirilgan · ${a.counts.missed} topshirilmagan`}
        />
        <StatTile
          label="E'tibor talab qiladi"
          value={`${a.attention.length} ta o'quvchi`}
          note="o'rtacha 50% dan past yoki keskin pasaygan"
        />
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Haftalik o&apos;rtacha</h2>
        <p className="mb-4 text-xs text-muted">So&apos;nggi 12 hafta, barcha guruhlarning tekshirilgan natijalari.</p>
        {a.trend.length >= 2 ? (
          <ProgressChart
            seriesLabel="Markaz o'rtachasi"
            noun="hafta"
            points={a.trend.map((w) => ({
              id: String(w.weekStart.getTime()),
              title: `${w.results} ta natija`,
              subjectName: "",
              dayLabel: formatTashkentDay(w.weekStart),
              dateLabel: `${formatTashkentDate(w.weekStart)} haftasi`,
              percentage: w.average,
              classAverage: null,
            }))}
          />
        ) : (
          <p className="text-sm text-muted">Grafik uchun kamida 2 haftalik natija kerak.</p>
        )}
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[420px] text-sm">
            <caption className="sr-only">Haftalar bo&apos;yicha o&apos;rtacha natija</caption>
            <thead>
              <tr className="border-b border-white/10 text-left text-xs text-muted">
                <th className="py-2 pr-3 font-semibold">Hafta</th>
                <th className="py-2 pr-3 text-right font-semibold">Natijalar</th>
                <th className="py-2 pr-3 text-right font-semibold">O&apos;rtacha</th>
              </tr>
            </thead>
            <tbody>
              {[...a.trend].reverse().map((w) => (
                <tr key={w.weekStart.getTime()} className="border-b border-white/5">
                  <td className="whitespace-nowrap py-2 pr-3 text-xs tabular-nums text-muted">
                    {formatTashkentDate(w.weekStart)} haftasi
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{w.results}</td>
                  <td className={`py-2 pr-3 text-right font-semibold tabular-nums ${scoreTone(w.average)}`}>
                    {w.average}%
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
              a.distribution.noResults > 0 ? `${a.distribution.noResults} ta o'quvchida hali natija yo'q.` : undefined
            }
          />
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Fanlar bo&apos;yicha</h2>
          <ul className="space-y-3">
            {a.subjects.map((s) => (
              <li key={s.name}>
                <div className="mb-1 flex justify-between gap-3 text-sm">
                  <span>
                    {s.name}{" "}
                    <span className="text-xs text-muted">
                      {s.students} o&apos;quvchi · {s.results} natija
                    </span>
                  </span>
                  <span className="font-semibold tabular-nums">{s.average}%</span>
                </div>
                <ScoreBar percentage={s.average} label={`${s.name}: ${s.average}%`} />
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">E&apos;tibor talab qiladi</h2>
        <p className="mb-4 text-xs text-muted">
          O&apos;rtachasi 50% dan past yoki oxirgi testda 15 balldan ko&apos;p pasaygan o&apos;quvchilar, eng pastidan.
        </p>
        {a.attention.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs text-muted">
                  <th className="py-2 pr-3 font-semibold">O&apos;quvchi</th>
                  <th className="py-2 pr-3 font-semibold">O&apos;qituvchi</th>
                  <th className="py-2 pr-3 text-right font-semibold">O&apos;rtacha</th>
                  <th className="py-2 pr-3 text-right font-semibold">Oxirgi</th>
                  <th className="py-2 pr-3 font-semibold">Eng zaif mavzu</th>
                </tr>
              </thead>
              <tbody>
                {a.attention.slice(0, ATTENTION_SHOWN).map((s) => (
                  <tr key={s.id} className="border-b border-white/5">
                    <td className="py-2 pr-3 font-semibold">
                      {s.name}
                      {s.reason === "drop" && (
                        <span className="ml-1.5 text-xs font-normal text-red-300">
                          <span aria-hidden>▼</span> pasaygan
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs text-muted">{s.teachers.join(", ") || "—"}</td>
                    <td className={`py-2 pr-3 text-right font-semibold tabular-nums ${scoreTone(s.average)}`}>
                      {s.average}%
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
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
            {a.attention.length > ATTENTION_SHOWN && (
              <p className="mt-2 text-xs text-muted">Yana {a.attention.length - ATTENTION_SHOWN} ta o&apos;quvchi.</p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted">Past natijali yoki keskin pasaygan o&apos;quvchi yo&apos;q.</p>
        )}
      </section>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Eng yaxshi natijalar</h2>
        <p className="mb-4 text-xs text-muted">
          O&apos;rtachasi 80% va undan yuqori, kamida {TOP_MIN_TESTS} ta test topshirgan o&apos;quvchilar.
        </p>
        {a.top.length > 0 ? (
          <ol className="grid gap-2 text-sm sm:grid-cols-2">
            {a.top.map((s, i) => (
              <li key={s.id} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{s.name}</span>
                  <span className="text-xs text-muted">
                    {s.teachers.join(", ") || "—"} · {s.checked} ta test
                  </span>
                </span>
                <span className={`font-semibold tabular-nums ${scoreTone(s.average)}`}>{s.average}%</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted">Hozircha bu mezonga mos o&apos;quvchi yo&apos;q.</p>
        )}
      </section>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Mavzular bo&apos;yicha</h2>
        <p className="mb-4 text-xs text-muted">Barcha guruhlar javoblari, eng zaif mavzular yuqorida.</p>
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
          <h2 className="mb-4 font-display text-base font-bold">Qiyinlik darajasi bo&apos;yicha</h2>
          <RateList
            empty="Savollarga qiyinlik darajasi belgilanmagan."
            rows={a.difficulty.map((d) => ({ ...d, key: d.name }))}
          />
        </section>
        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Javoblar tarkibi</h2>
          <AnswerMix {...a.answerMix} />
        </section>
      </div>
    </div>
  );
}
