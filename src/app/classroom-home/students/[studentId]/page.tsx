import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { HttpError } from "@/lib/http-error";
import { loadStudentAnalytics } from "@/lib/analytics";
import { formatTashkent, formatTashkentDate, formatTashkentDay } from "@/lib/online-core";
import { scoreTone } from "@/lib/progress";
import { studentDisplayName } from "@/lib/students";
import AnswerMix from "@/components/analytics/AnswerMix";
import ProgressChart from "@/components/analytics/ProgressChart";
import RateList from "@/components/analytics/RateList";
import StatTile from "@/components/analytics/StatTile";
import ScoreBar from "@/components/ScoreBar";

type Props = { params: Promise<{ studentId: string }> };

type Data = Awaited<ReturnType<typeof loadStudentAnalytics>>;

const pct = (n: number | null) => (n == null ? "—" : `${n}%`);

// Full analytics for one linked student — what a parent or the student opens
// from the cabinet (and inside the Telegram Mini App).
export default async function StudentAnalyticsPage({ params }: Props) {
  const session = await auth();
  if (session?.user.kind !== "student") redirect("/login/student");

  const { studentId } = await params;
  let data: Data;
  try {
    data = await loadStudentAnalytics(studentId, { accountId: session.user.id });
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) notFound();
    throw err;
  }
  const { student, analytics: a } = data;
  const name = studentDisplayName(student);
  const blankShare = a.answerMix.total ? Math.round((a.answerMix.blank / a.answerMix.total) * 100) : 0;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <Link href="/classroom-home" className="text-xs text-muted hover:text-ivory hover:underline">
          ← Bosh sahifa
        </Link>
        <h1 className="mt-2 font-display text-2xl font-bold">{name}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-muted">
          {student.grade && <span>{student.grade} sinf</span>}
          {student.memberships.map((m) => (
            <span key={m.id} className="tag">
              {m.classroom.name}
            </span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="O'rtacha natija" value={pct(a.average)} note={`${a.counts.checked} ta test bo'yicha`} />
        <StatTile
          label="Oxirgi test"
          value={pct(a.last?.percentage ?? null)}
          delta={a.change == null ? null : { value: a.change, suffix: "%", caption: "oldingisiga nisbatan" }}
          note={a.last?.title}
        />
        <StatTile
          label="Sinf o'rtachasiga nisbatan"
          value={a.vsClass == null ? "—" : `${a.vsClass > 0 ? "+" : a.vsClass < 0 ? "−" : ""}${Math.abs(a.vsClass)}%`}
          note={a.vsClass == null ? "taqqoslash uchun ma'lumot yetarli emas" : "testlar bo'yicha o'rtacha farq"}
        />
        <StatTile
          label="Topshirilgan"
          value={`${a.counts.checked}/${a.counts.assigned}`}
          note={
            a.counts.missed > 0
              ? `${a.counts.missed} ta topshirilmagan`
              : a.counts.pending > 0
                ? `${a.counts.pending} ta kutilmoqda`
                : "hammasi topshirilgan"
          }
        />
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Natija dinamikasi</h2>
        <p className="mb-4 text-xs text-muted">Har bir tekshirilgan test, vaqt bo&apos;yicha.</p>
        {a.timeline.length >= 2 ? (
          <ProgressChart
            seriesLabel={student.firstName}
            points={a.timeline.map((t) => ({
              id: t.id,
              title: t.title,
              subjectName: t.subjectName,
              dayLabel: formatTashkentDay(new Date(t.date)),
              dateLabel: formatTashkentDate(new Date(t.date)),
              percentage: t.percentage,
              classAverage: t.classAverage,
            }))}
          />
        ) : (
          <p className="text-sm text-muted">
            Grafik uchun kamida 2 ta tekshirilgan test kerak.
          </p>
        )}

        {a.timeline.length > 0 && (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <caption className="sr-only">Testlar natijalari jadvali</caption>
              <thead>
                <tr className="border-b border-white/10 text-left text-xs text-muted">
                  <th className="py-2 pr-3 font-semibold">Sana</th>
                  <th className="py-2 pr-3 font-semibold">Test</th>
                  <th className="py-2 pr-3 text-right font-semibold">Natija</th>
                  <th className="py-2 pr-3 text-right font-semibold">Sinf o&apos;rtachasi</th>
                </tr>
              </thead>
              <tbody>
                {[...a.timeline].reverse().map((t) => (
                  <tr key={t.id} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-xs tabular-nums text-muted">{formatTashkent(new Date(t.date))}</td>
                    <td className="py-2 pr-3">
                      <Link href={`/classroom-home/results/${t.id}`} className="hover:underline">
                        {t.title}
                      </Link>
                      <span className="ml-1.5 text-xs text-muted">
                        {t.subjectName} · {t.mode === "ONLINE" ? "online" : "qog'ozda"}
                      </span>
                    </td>
                    <td className={`py-2 pr-3 text-right font-semibold tabular-nums ${scoreTone(t.percentage)}`}>
                      {t.percentage}%{" "}
                      <span className="text-xs font-normal text-muted">
                        ({t.correct}/{t.total})
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-muted">{pct(t.classAverage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {a.hiddenDetails > 0 && (
        <p className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-muted">
          {a.hiddenDetails} ta testning to&apos;g&apos;ri javoblari hali yopiq — ular ball bo&apos;yicha
          hisobga olingan, mavzular va javoblar tahliliga esa test yopilgach qo&apos;shiladi.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Keyingi qadamlar</h2>
          {a.focus.length > 0 ? (
            <ol className="space-y-2.5 text-sm">
              {a.focus.map((t, i) => (
                <li key={t.id} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold">
                    {i + 1}
                  </span>
                  <span>
                    <b>{t.name}</b> <span className="text-muted">({t.subjectName})</span> —{" "}
                    {t.total - t.correct} ta savolda xato ({t.percentage}% to&apos;g&apos;ri). Shu mavzuni
                    takrorlash tavsiya etiladi.
                  </span>
                </li>
              ))}
            </ol>
          ) : a.themes.length > 0 ? (
            <p className="text-sm text-muted">
              Yetarli savol yechilgan mavzularning hammasi yaxshi o&apos;zlashtirilgan. Shu tarzda davom
              eting.
            </p>
          ) : (
            <p className="text-sm text-muted">Tavsiya uchun hali tekshirilgan javoblar yo&apos;q.</p>
          )}
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Javoblar tarkibi</h2>
          {a.answerMix.total > 0 ? (
            <>
              <AnswerMix {...a.answerMix} />
              <ul className="mt-4 space-y-1.5 text-xs text-muted">
                {blankShare >= 15 && (
                  <li>
                    Savollarning {blankShare}% i javobsiz qolgan — vaqtni taqsimlashga e&apos;tibor
                    bering.
                  </li>
                )}
                {a.answerMix.multi > 0 && (
                  <li>
                    {a.answerMix.multi} ta savolda bir nechta doira bo&apos;yalgan — bunday javob
                    hisoblanmaydi.
                  </li>
                )}
                {a.onlineMinutes != null && (
                  <li>
                    Online testlarga o&apos;rtacha{" "}
                    {a.onlineMinutes < 1 ? "1 daqiqadan kam" : `${a.onlineMinutes} daqiqa`} sarflangan.
                  </li>
                )}
              </ul>
            </>
          ) : (
            <p className="text-sm text-muted">Hali tekshirilgan javoblar yo&apos;q.</p>
          )}
        </section>
      </div>

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">Mavzular bo&apos;yicha</h2>
        <p className="mb-4 text-xs text-muted">Eng zaif mavzular yuqorida. Ichki mavzularni ochib ko&apos;rish mumkin.</p>
        <RateList
          empty="Hali tahlil uchun javoblar yo'q."
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
          <RateList empty="Savollarga qiyinlik darajasi belgilanmagan." rows={a.difficulty.map((d) => ({ ...d, key: d.name }))} />
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-4 font-display text-base font-bold">
            {a.skills.length > 0 ? "Ko'nikmalar bo'yicha" : "Fanlar bo'yicha"}
          </h2>
          {a.skills.length > 0 ? (
            <RateList empty="" rows={a.skills.map((s) => ({ ...s, key: s.name }))} />
          ) : (
            <ul className="space-y-3">
              {a.subjects.map((s) => (
                <li key={s.name}>
                  <div className="mb-1 flex justify-between gap-3 text-sm">
                    <span>
                      {s.name} <span className="text-xs text-muted">{s.tests} ta test</span>
                    </span>
                    <span className="font-semibold tabular-nums">{s.average}%</span>
                  </div>
                  <ScoreBar percentage={s.average} label={`${s.name}: ${s.average}%`} />
                </li>
              ))}
              {a.subjects.length === 0 && <li className="text-sm text-muted">Hali tekshirilgan test yo&apos;q.</li>}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
