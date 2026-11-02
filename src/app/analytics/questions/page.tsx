import Link from "next/link";
import { MAX_CHOICES, MIN_CHOICES } from "@/lib/answer-key";
import { scoreTone } from "@/lib/analytics-core";
import { loadQuestionBankAnalytics } from "@/lib/center-analytics";
import { MIN_RESPONSES, THIN_THEME } from "@/lib/center-analytics-core";
import { managerPageSession } from "@/lib/page-auth";
import CountBar from "@/components/analytics/CountBar";
import StatTile from "@/components/analytics/StatTile";

const COVERAGE_SHOWN = 12;
const pct = (n: number | null) => (n == null ? "—" : `${n}%`);

// The question bank as a whole: what it covers, what gets used, which
// questions are hard — and which look broken.
export default async function QuestionBankAnalyticsPage() {
  await managerPageSession();
  const a = await loadQuestionBankAnalytics();
  const maxQuestions = Math.max(0, ...a.subjects.map((s) => s.questions));
  const thin = a.coverage.filter((t) => t.questions < THIN_THEME).slice(0, COVERAGE_SHOWN);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Jami savollar"
          value={`${a.totals.questions}`}
          note={`${a.totals.recent} tasi so'nggi 30 kunda qo'shilgan`}
        />
        <StatTile
          label="Testlarda ishlatilgan"
          value={pct(a.totals.usedShare)}
          note={`${a.totals.unused} tasi hech qaysi testda yo'q`}
        />
        <StatTile
          label="To'g'ri javoblar ulushi"
          value={pct(a.totals.correctRate)}
          note={`${a.totals.responses} ta javob · ${a.totals.answered} ta savol`}
        />
        <StatTile
          label="Biriktirib bo'lmaydi"
          value={`${a.quality.notAssignable}`}
          note={`variantlari soni ${MIN_CHOICES} yoki ${MAX_CHOICES} ta emas`}
        />
      </div>

      <section className="glass-panel p-5">
        <h2 className="mb-4 font-display text-base font-bold">Fanlar bo&apos;yicha</h2>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-xs text-muted">
                <th className="py-2 pr-3 font-semibold">Fan</th>
                <th className="w-56 py-2 pr-3 font-semibold">Savollar</th>
                <th className="py-2 pr-3 text-right font-semibold">Mavzular</th>
                <th className="py-2 pr-3 text-right font-semibold">Ishlatilmagan</th>
                <th className="py-2 pr-3 text-right font-semibold">To&apos;g&apos;ri javob</th>
                <th className="py-2 pr-3 font-semibold">Qiyinlik</th>
              </tr>
            </thead>
            <tbody>
              {a.subjects.map((s) => (
                <tr key={s.name} className="border-b border-white/5">
                  <td className="py-2 pr-3 font-semibold">
                    {s.name}
                    {s.recent > 0 && <span className="ml-1.5 text-xs font-normal text-muted">+{s.recent} yangi</span>}
                  </td>
                  <td className="py-2 pr-3">
                    <CountBar value={s.questions} max={maxQuestions} />
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{s.themes}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-muted">{s.unused}</td>
                  <td className={`py-2 pr-3 text-right font-semibold tabular-nums ${scoreTone(s.correctRate)}`}>
                    {pct(s.correctRate)}
                  </td>
                  <td className="py-2 pr-3 text-xs text-muted">
                    {s.difficulty.length ? s.difficulty.map((d) => `${d.name} ${d.count}`).join(" · ") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {a.subjects.length === 0 && <p className="text-sm text-muted">Hali fan qo&apos;shilmagan.</p>}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="glass-panel p-5">
          <h2 className="font-display text-base font-bold">Kam savolli mavzular</h2>
          <p className="mb-4 text-xs text-muted">
            {THIN_THEME} tadan kam savolli mavzular ({a.thinThemes} ta) — test yig&apos;ishda tanlov tor.
          </p>
          {thin.length > 0 ? (
            <ul className="space-y-1.5 text-sm">
              {thin.map((t) => (
                <li key={t.id} className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0">
                    {t.name} <span className="text-xs text-muted">{t.subjectName}</span>
                  </span>
                  <span className={`shrink-0 tabular-nums ${t.questions === 0 ? "text-red-300" : "text-ivory"}`}>
                    {t.questions === 0 && <span aria-hidden>! </span>}
                    {t.questions} ta
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Hamma mavzuda kamida {THIN_THEME} ta savol bor.</p>
          )}
        </section>

        <section className="glass-panel p-5">
          <h2 className="font-display text-base font-bold">Kalit xato bo&apos;lishi mumkin</h2>
          <p className="mb-4 text-xs text-muted">
            Kamida {MIN_RESPONSES} kishi yechgan, kalitdagi javobni chorakdan kami topgan, lekin ko&apos;pchilik
            boshqa bir javobni tanlagan savollar.
          </p>
          {a.suspectKeys.length > 0 ? (
            <ul className="space-y-3 text-sm">
              {a.suspectKeys.map((s) => (
                <li key={s.questionId}>
                  <Link href={`/questions/${s.questionId}/edit`} className="font-semibold hover:underline">
                    {s.text}
                  </Link>
                  <p className="text-xs text-muted">
                    {s.assignmentTitle} · {s.number}-savol · kalit {s.key} ({s.correctShare}%), lekin{" "}
                    <span className="text-amber-200">{s.share}% {s.popular}</span> ni tanlagan
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Shubhali kalit topilmadi.</p>
          )}
        </section>
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Eng qiyin savollar</h2>
        <p className="mb-4 text-xs text-muted">
          Kamida {MIN_RESPONSES} ta javob olgan savollardan eng kam to&apos;g&apos;ri topilganlari, barcha guruhlar
          bo&apos;yicha.
        </p>
        {a.hardest.length > 0 ? (
          <ol className="space-y-2.5 text-sm">
            {a.hardest.map((q) => (
              <li key={q.id} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0">
                  <Link href={`/questions/${q.id}/edit`} className="hover:underline">
                    {q.text}
                  </Link>
                  <span className="block text-xs text-muted">
                    {q.subjectName}
                    {q.themes.length > 0 && ` · ${q.themes.join(", ")}`} · {q.tests} ta testda
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className={`font-semibold tabular-nums ${scoreTone(q.percentage)}`}>{q.percentage}%</span>
                  <span className="block text-xs text-muted">{q.responses} javob</span>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted">Hali yetarli javob yo&apos;q.</p>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Ma&apos;lumot sifati</h2>
          <ul className="space-y-1.5 text-sm">
            <li className="flex justify-between gap-3">
              <span>
                Variantlari soni {MIN_CHOICES} yoki {MAX_CHOICES} ta emas (guruhga biriktirilmaydi)
              </span>
              <span className={`tabular-nums ${a.quality.notAssignable ? "text-red-300" : "text-muted"}`}>
                {a.quality.notAssignable}
              </span>
            </li>
            <li className="flex justify-between gap-3">
              <span>Ichki mavzusi belgilanmagan</span>
              <span className="tabular-nums text-muted">{a.quality.noSubThemes}</span>
            </li>
            <li className="flex justify-between gap-3">
              <span>Ko&apos;nikmasi belgilanmagan</span>
              <span className="tabular-nums text-muted">{a.quality.noSkills}</span>
            </li>
          </ul>
          {a.quality.notAssignableSamples.length > 0 && (
            <ul className="mt-4 space-y-1.5 border-t border-white/10 pt-3 text-xs">
              {a.quality.notAssignableSamples.map((q) => (
                <li key={q.id} className="flex justify-between gap-3">
                  <Link href={`/questions/${q.id}/edit`} className="min-w-0 truncate hover:underline">
                    {q.text}
                  </Link>
                  <span className="shrink-0 text-muted">{q.options} ta variant</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Mualliflar</h2>
          {a.authors.length > 0 ? (
            <ul className="space-y-1.5 text-sm">
              {a.authors.map((u) => (
                <li key={u.id} className="flex justify-between gap-3">
                  <span>{u.name}</span>
                  <span className="tabular-nums">
                    {u.questions} ta
                    {u.recent > 0 && <span className="ml-1 text-xs text-muted">(+{u.recent} so&apos;nggi 30 kunda)</span>}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Hali savol yo&apos;q.</p>
          )}
        </section>
      </div>
    </div>
  );
}
