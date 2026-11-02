import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { auth } from "@/auth";
import { HttpError } from "@/lib/http-error";
import { attemptQuestions, sheetForAccount, type AccountSheet } from "@/lib/online";
import { attemptDeadline, formatTashkent, windowState } from "@/lib/online-core";
import { studentDisplayName } from "@/lib/students";
import OnlineTestRunner from "@/components/OnlineTestRunner";
import StartAttemptButton from "@/components/StartAttemptButton";

type Props = { params: Promise<{ sheetId: string }> };

function currentTime() {
  return new Date();
}

export default async function OnlineTestPage({ params }: Props) {
  const session = await auth();
  if (session?.user.kind !== "student") redirect("/login/student");

  const { sheetId } = await params;
  let sheet: AccountSheet;
  try {
    sheet = await sheetForAccount(sheetId, session.user.id);
  } catch (err) {
    if (err instanceof HttpError && err.status === 404) notFound();
    throw err;
  }

  const a = sheet.assignment;
  if (a.mode !== "ONLINE") redirect("/classroom-home");
  if (sheet.checkedAt) redirect(`/classroom-home/results/${sheet.id}`);

  const now = currentTime();
  const header = (
    <div>
      <Link href="/classroom-home" className="text-xs text-muted hover:text-ivory hover:underline">
        ← Bosh sahifa
      </Link>
      <h1 className="mt-2 font-display text-2xl font-bold">{a.title}</h1>
      <p className="text-sm text-muted">
        {studentDisplayName(sheet.student)} · {a.classroom.name} · {a.subjectName}
      </p>
    </div>
  );

  if (!sheet.startedAt) {
    const state = windowState(a, now);
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        {header}
        <section className="glass-panel space-y-4 p-6">
          <ul className="space-y-1.5 text-sm">
            <li>
              Savollar: <b>{a.questionIds.length} ta</b>
            </li>
            <li>
              Vaqt: <b>{a.timeLimitMinutes ? `${a.timeLimitMinutes} daqiqa` : "cheklanmagan"}</b>
            </li>
            {a.closesAt && (
              <li>
                Yopiladi: <b>{formatTashkent(a.closesAt)}</b>
              </li>
            )}
            <li className="text-muted">
              Test bir marta topshiriladi. Har bir javob bosilishi bilan saqlanadi; vaqt tugasa test
              o&apos;zi topshiriladi.
            </li>
          </ul>
          {state === "open" && <StartAttemptButton sheetId={sheet.id} />}
          {state === "not_open" && (
            <p className="text-sm text-gold">Test {formatTashkent(a.opensAt!)} da ochiladi.</p>
          )}
          {state === "closed" && <p className="text-sm text-red-300">Test yopilgan.</p>}
        </section>
      </div>
    );
  }

  const questions = await attemptQuestions(sheet);
  const deadline = attemptDeadline(a, sheet.startedAt);
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {header}
      <OnlineTestRunner
        sheetId={sheet.id}
        questions={questions}
        initialAnswers={sheet.answers}
        deadline={deadline?.toISOString() ?? null}
        serverNow={now.toISOString()}
      />
    </div>
  );
}
