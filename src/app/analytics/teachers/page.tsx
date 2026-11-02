import Link from "next/link";
import { scoreTone } from "@/lib/analytics-core";
import { loadTeacherAnalytics } from "@/lib/center-analytics";
import { formatTashkentDate } from "@/lib/online-core";
import { managerPageSession } from "@/lib/page-auth";
import StatTile from "@/components/analytics/StatTile";
import ScoreBar from "@/components/ScoreBar";

const pct = (n: number | null) => (n == null ? "—" : `${n}%`);

// Teachers side by side, for admins: how much each one runs and how their
// students do — without opening any of their groups.
export default async function TeacherAnalyticsPage() {
  const session = await managerPageSession();
  const a = await loadTeacherAnalytics();

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="O'qituvchilar"
          value={`${a.teachers}`}
          note={`${a.activeTeachers} tasi so'nggi 30 kunda faol`}
        />
        <StatTile label="Topshiriqlar" value={`${a.recentAssignments}`} note="so'nggi 30 kunda biriktirilgan" />
        <StatTile label="Tekshirilgan natijalar" value={`${a.recentResults}`} note="so'nggi 30 kunda" />
        <StatTile label="Markaz o'rtachasi" value={pct(a.average)} note="barcha guruhlar, butun davr" />
      </div>

      {a.otherOwners > 0 && (
        <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">
          <span aria-hidden>! </span>
          {a.otherOwners} ta xodim o&apos;qituvchi bo&apos;lmasa ham guruhlarga ega — bu guruhlarni hech kim
          ochmaydi.{" "}
          {session.user.role === "SUPER_ADMIN" ? (
            <Link href="/admins" className="font-semibold underline">
              Xodimlar sahifasida o&apos;qituvchiga o&apos;tkazing.
            </Link>
          ) : (
            "SuperAdmin ularni o'qituvchiga o'tkazishi kerak."
          )}
        </p>
      )}

      <section className="glass-panel p-5">
        <h2 className="font-display text-base font-bold">O&apos;qituvchilar</h2>
        <p className="mb-4 text-xs text-muted">
          Topshirish — tekshirilgan / (tekshirilgan + topshirilmagan). Zaif — o&apos;rtachasi 50% dan past
          o&apos;quvchilar.
        </p>
        {a.rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs text-muted">
                  <th className="py-2 pr-3 font-semibold">O&apos;qituvchi</th>
                  <th className="py-2 pr-3 text-right font-semibold">Guruh</th>
                  <th className="py-2 pr-3 text-right font-semibold">O&apos;quvchi</th>
                  <th className="py-2 pr-3 text-right font-semibold">Topshiriq</th>
                  <th className="py-2 pr-3 text-right font-semibold">Topshirish</th>
                  <th className="w-44 py-2 pr-3 font-semibold">O&apos;rtacha</th>
                  <th className="py-2 pr-3 text-right font-semibold">Zaif</th>
                  <th className="py-2 pr-3 text-right font-semibold">Savol</th>
                  <th className="py-2 pr-3 text-right font-semibold">Test</th>
                  <th className="py-2 pr-3 font-semibold">Oxirgi faollik</th>
                </tr>
              </thead>
              <tbody>
                {a.rows.map((r) => (
                  <tr key={r.id} className="border-b border-white/5">
                    <td className="py-2 pr-3">
                      <span className="font-semibold">{r.name}</span>
                      {!r.isTeacher && (
                        <span className="tag ml-1.5 bg-amber-400/10 text-amber-200">o&apos;qituvchi emas</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{r.classrooms}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{r.students}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                      {r.assignments}
                      {r.online > 0 && <span className="ml-1 text-xs text-muted">· {r.online} online</span>}
                    </td>
                    <td className={`py-2 pr-3 text-right tabular-nums ${r.completion == null ? "text-muted" : ""}`}>
                      {pct(r.completion)}
                    </td>
                    <td className="py-2 pr-3">
                      {r.average == null ? (
                        <span className="text-muted">—</span>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span className={`w-12 text-xs font-semibold tabular-nums ${scoreTone(r.average)}`}>
                            {r.average}%
                          </span>
                          <ScoreBar percentage={r.average} label={`${r.name}: o'rtacha ${r.average}%`} />
                        </div>
                      )}
                    </td>
                    <td className={`py-2 pr-3 text-right tabular-nums ${r.weakStudents ? "text-red-300" : "text-muted"}`}>
                      {r.weakStudents}
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                      {r.questions}
                      {r.recentQuestions > 0 && <span className="ml-1 text-xs text-muted">(+{r.recentQuestions})</span>}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{r.tests}</td>
                    <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted">
                      {r.lastActivity ? formatTashkentDate(r.lastActivity) : "—"}
                      {!r.active && r.isTeacher && <span className="ml-1 text-amber-200">· 30 kundan beri faol emas</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted">
              Savol ustunidagi (+N) — so&apos;nggi 30 kunda qo&apos;shilganlari.
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted">
            Hali o&apos;qituvchi yo&apos;q — SuperAdmin Xodimlar sahifasida qo&apos;shadi.
          </p>
        )}
      </section>
    </div>
  );
}
