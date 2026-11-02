import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { BLANK_ANSWER, MULTI_ANSWER } from "@/lib/answer-key";
import { classAverages, questionMeta } from "@/lib/analytics";
import { computeStudentAnalytics } from "@/lib/analytics-core";
import { HttpError } from "@/lib/http-error";
import { sheetForAccount, type AccountSheet } from "@/lib/online";
import { canonicalOptions, formatTashkent, letterIndex, revealAllowed } from "@/lib/online-core";
import { scoreTone } from "@/lib/progress";
import { studentDisplayName } from "@/lib/students";
import RateList from "@/components/analytics/RateList";

type Props = { params: Promise<{ sheetId: string }> };

function currentTime() {
  return new Date();
}

export default async function StudentResultPage({ params }: Props) {
  const session = await auth();
  if (session?.user.kind !== "student") redirect("/login/student");

  const { sheetId } = await params;
  // Only a sheet of a student linked to THIS account (404 otherwise).
  let sheet: AccountSheet;
  try {
    sheet = await sheetForAccount(sheetId, session.user.id);
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) notFound();
    throw err;
  }

  const a = sheet.assignment;
  if (!sheet.checkedAt) {
    redirect(a.mode === "ONLINE" ? `/classroom-home/tests/${sheet.id}` : "/classroom-home");
  }

  // The score is always shown; which answers were right only per the policy —
  // otherwise classmates still taking the test would get the key. The topic
  // breakdown follows the same rule: per-topic results give answers away too.
  const reveal = revealAllowed(a.revealAnswers, a.closesAt, currentTime());
  const [averages, meta, questions] = await Promise.all([
    classAverages([a.id]),
    reveal ? questionMeta(a.questionIds) : Promise.resolve(new Map()),
    reveal
      ? prisma.question.findMany({
          where: { id: { in: a.questionIds } },
          select: { id: true, correctAnswer: true, wrongAnswers: true },
        })
      : Promise.resolve([]),
  ]);
  const classAverage = averages.get(a.id) ?? null;
  const byId = new Map(questions.map((q) => [q.id, q]));
  const themes = reveal
    ? computeStudentAnalytics(
        [
          {
            id: sheet.id,
            assignmentId: a.id,
            status: "checked",
            mode: a.mode,
            title: a.title,
            subjectName: a.subjectName,
            classroomName: a.classroom.name,
            startedAt: sheet.startedAt,
            checkedAt: sheet.checkedAt,
            percentage: sheet.percentage,
            correct: sheet.correct,
            total: sheet.total,
            answers: sheet.answers,
            answerKey: a.answerKey,
            questionIds: a.questionIds,
            detailAllowed: true,
            classAverage,
          },
        ],
        meta,
      ).themes
    : [];
  const minutes =
    a.mode === "ONLINE" && sheet.startedAt
      ? Math.max(1, Math.round((sheet.checkedAt!.getTime() - sheet.startedAt.getTime()) / 60_000))
      : null;
  const vsClass =
    classAverage != null && sheet.percentage != null
      ? Math.round((sheet.percentage - classAverage) * 10) / 10
      : null;

  function describe(letter: string, options: string[] | null) {
    if (letter === BLANK_ANSWER) return "belgilanmagan";
    if (letter === MULTI_ANSWER) return "bir nechta";
    const text = options?.[letterIndex(letter)];
    if (text === undefined) return letter;
    // With per-student shuffling the student never saw the canonical letters.
    return a.shuffle ? text : `${letter}) ${text}`;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link href={`/classroom-home/students/${sheet.studentId}`} className="text-xs text-muted hover:text-ivory hover:underline">
          ← {studentDisplayName(sheet.student)} tahlili
        </Link>
        <h1 className="mt-2 font-display text-2xl font-bold">{a.title}</h1>
        <p className="text-sm text-muted">
          {studentDisplayName(sheet.student)} · {a.classroom.name} · {a.subjectName} ·{" "}
          {formatTashkent(sheet.checkedAt!)}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="glass-panel p-4">
          <p className="text-xs text-muted">Natija</p>
          <p className={`mt-1 text-2xl font-semibold ${scoreTone(sheet.percentage)}`}>{sheet.percentage}%</p>
          <p className="text-xs text-muted">
            {sheet.correct}/{sheet.total} to&apos;g&apos;ri
          </p>
        </div>
        <div className="glass-panel p-4">
          <p className="text-xs text-muted">Sinf o&apos;rtachasi</p>
          <p className="mt-1 text-2xl font-semibold text-ivory">{classAverage == null ? "—" : `${classAverage}%`}</p>
          <p className={`text-xs ${vsClass == null ? "text-muted" : vsClass >= 0 ? "text-emerald-300" : "text-red-300"}`}>
            {vsClass == null ? (
              "taqqoslash uchun natijalar kam"
            ) : (
              <>
                <span aria-hidden>{vsClass >= 0 ? "▲" : "▼"}</span> {vsClass >= 0 ? "+" : "−"}
                {Math.abs(vsClass)}% sinfga nisbatan
              </>
            )}
          </p>
        </div>
        {minutes != null && (
          <div className="glass-panel p-4">
            <p className="text-xs text-muted">Sarflangan vaqt</p>
            <p className="mt-1 text-2xl font-semibold text-ivory">{minutes} daq</p>
            {a.timeLimitMinutes && <p className="text-xs text-muted">{a.timeLimitMinutes} daqiqadan</p>}
          </div>
        )}
      </div>

      {reveal ? (
        <>
          {themes.length > 0 && (
            <section className="glass-panel p-5">
              <h2 className="mb-4 font-display text-base font-bold">Shu testdagi mavzular</h2>
              <RateList empty="" rows={themes.map((t) => ({ ...t, key: t.id }))} />
            </section>
          )}

          <section className="glass-panel p-5">
            <h2 className="mb-3 font-display text-base font-bold">Savollar bo&apos;yicha</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-left text-xs text-muted">
                    <th className="py-2 pr-3 font-semibold">Savol</th>
                    <th className="py-2 pr-3 font-semibold">Belgilangan</th>
                    <th className="py-2 pr-3 font-semibold">To&apos;g&apos;ri javob</th>
                    <th className="py-2 pr-3 font-semibold">Mavzu</th>
                  </tr>
                </thead>
                <tbody>
                  {a.questionIds.map((qid, i) => {
                    const q = byId.get(qid);
                    const options = q ? canonicalOptions(a.testId, q) : null;
                    const given = sheet.answers[i] ?? BLANK_ANSWER;
                    const want = a.answerKey[i];
                    const ok = given === want;
                    return (
                      <tr key={qid} className="border-b border-white/5 align-top">
                        <td className="py-2 pr-3 text-muted">{i + 1}</td>
                        <td className={`py-2 pr-3 font-semibold ${ok ? "text-emerald-300" : "text-red-300"}`}>
                          <span aria-hidden>{ok ? "✓ " : "✗ "}</span>
                          {describe(given, options)}
                        </td>
                        <td className="py-2 pr-3">{describe(want, options)}</td>
                        <td className="py-2 pr-3 text-xs text-muted">
                          {meta.get(qid)?.themes.map((t: { name: string }) => t.name).join(", ") || "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <section className="glass-panel p-5 text-sm text-muted">
          {a.revealAnswers === "AFTER_CLOSE" && a.closesAt
            ? `To'g'ri javoblar va mavzular tahlili test yopilgandan keyin — ${formatTashkent(a.closesAt)} dan ko'rinadi.`
            : "Bu test uchun to'g'ri javoblar ko'rsatilmaydi."}
        </section>
      )}
    </div>
  );
}
