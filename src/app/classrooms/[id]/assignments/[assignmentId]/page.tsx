import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { finalizeIfExpired } from "@/lib/online";
import {
  formatTashkent,
  sheetStatus,
  windowState,
  type OnlineWindow,
  type SheetStatus,
} from "@/lib/online-core";
import { scoreTone, themeStats } from "@/lib/progress";
import { studentDisplayName } from "@/lib/students";
import { teacherPageSession } from "@/lib/page-auth";
import AssignmentActions from "@/components/AssignmentActions";
import OnlineAssignmentPanel from "@/components/OnlineAssignmentPanel";
import ResetResultButton from "@/components/ResetResultButton";
import ScoreBar from "@/components/ScoreBar";

type Props = { params: Promise<{ id: string; assignmentId: string }> };

function currentTime() {
  return new Date();
}

// The test's state right now — not just whether an opening time was set.
function windowLine(w: OnlineWindow, now: Date) {
  const limit = w.timeLimitMinutes ? `${w.timeLimitMinutes} daqiqa` : "vaqt cheklanmagan";
  switch (windowState(w, now)) {
    case "not_open":
      return { tone: "text-gold", text: `Hali ochilmagan — ${formatTashkent(w.opensAt!)} da ochiladi · ${limit}` };
    case "open":
      return {
        tone: "text-emerald-300",
        text: `Ochiq${w.closesAt ? ` — ${formatTashkent(w.closesAt)} gacha` : ", muddatsiz"} · ${limit}`,
      };
    case "closed":
      return { tone: "text-muted", text: `Yopilgan — ${formatTashkent(w.closesAt!)} · ${limit}` };
  }
}

const PENDING_LABEL: Record<Exclude<SheetStatus, "checked">, string> = {
  in_progress: "yechmoqda",
  available: "boshlamagan",
  not_open: "hali ochilmagan",
  missed: "topshirmadi",
  awaiting_scan: "kutilmoqda",
};

export default async function AssignmentPage({ params }: Props) {
  const { id, assignmentId } = await params;
  const session = await teacherPageSession();
  const assignment = await prisma.assignment.findFirst({
    where: { id: assignmentId, classroomId: id, classroom: { teacherId: session.user.id } },
    select: {
      id: true,
      title: true,
      subjectName: true,
      createdAt: true,
      archived: true,
      mode: true,
      questionIds: true,
      answerKey: true,
      sheetFieldBoxes: true,
      opensAt: true,
      closesAt: true,
      timeLimitMinutes: true,
      shuffle: true,
      revealAnswers: true,
      classroom: {
        select: { id: true, name: true, members: { select: { student: true } } },
      },
      sheets: { include: { student: true } },
    },
  });
  if (!assignment) notFound();

  const online = assignment.mode === "ONLINE";
  const now = currentTime();
  // Online attempts whose time ran out become results the moment anyone looks.
  const sheets = await Promise.all(
    assignment.sheets.map((s) => finalizeIfExpired(assignment, s, now)),
  );

  // Current members, plus anyone who has since left but still has a sheet.
  const sheetOf = new Map(sheets.map((s) => [s.studentId, s]));
  const memberIds = new Set(assignment.classroom.members.map((m) => m.student.id));
  const rows = [
    ...assignment.classroom.members.map((m) => ({
      student: m.student,
      sheet: sheetOf.get(m.student.id) ?? null,
      member: true,
    })),
    ...sheets
      .filter((s) => !memberIds.has(s.studentId))
      .map((s) => ({ student: s.student, sheet: s, member: false })),
  ].sort((a, b) =>
    studentDisplayName(a.student).localeCompare(studentDisplayName(b.student), "uz"),
  );

  const checked = sheets.filter((s) => s.checkedAt);
  const percentages = checked.map((s) => s.percentage ?? 0);
  const average = percentages.length
    ? Math.round((percentages.reduce((a, b) => a + b, 0) / percentages.length) * 10) / 10
    : null;

  const questions = await prisma.question.findMany({
    where: { id: { in: assignment.questionIds } },
    select: { id: true, themes: { select: { name: true } } },
  });
  const themesOf = new Map(questions.map((q) => [q.id, q.themes.map((t) => t.name)]));
  const perQuestion = assignment.questionIds.map((qid, i) => {
    const right = checked.filter((s) => s.answers[i] === assignment.answerKey[i]).length;
    return {
      n: i + 1,
      key: assignment.answerKey[i],
      pct: checked.length ? Math.round((right / checked.length) * 100) : null,
      themes: themesOf.get(qid) ?? [],
    };
  });
  const themes = await themeStats(
    checked.map((s) => ({
      answers: s.answers,
      questionIds: assignment.questionIds,
      answerKey: assignment.answerKey,
    })),
  );

  const stats = [
    { label: online ? "Topshirgan" : "Tekshirilgan", value: `${checked.length}/${rows.length}` },
    { label: "O'rtacha", value: average == null ? "—" : `${average}%` },
    { label: "Eng yuqori", value: percentages.length ? `${Math.max(...percentages)}%` : "—" },
    { label: "Eng past", value: percentages.length ? `${Math.min(...percentages)}%` : "—" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/classrooms/${assignment.classroom.id}`}
          className="text-xs text-muted hover:text-ivory hover:underline"
        >
          ← {assignment.classroom.name}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="font-display text-2xl font-bold">{assignment.title}</h1>
          <span className="tag">{online ? "Online" : "Offline"}</span>
          {assignment.archived && <span className="tag tag-gold">Arxivda</span>}
        </div>
        <p className="text-sm text-muted">
          {assignment.subjectName} &middot; {assignment.questionIds.length} savol &middot;{" "}
          {formatTashkent(assignment.createdAt)}
        </p>
        {online && (
          <p className={`text-xs ${windowLine(assignment, now).tone}`}>
            {windowLine(assignment, now).text}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="glass-panel p-4">
            <p className="text-xs text-muted">{s.label}</p>
            <p className="mt-1 font-display text-xl font-bold">{s.value}</p>
          </div>
        ))}
      </div>

      {online ? (
        <OnlineAssignmentPanel
          assignmentId={assignment.id}
          classroomId={assignment.classroom.id}
          settings={{
            opensAt: assignment.opensAt?.toISOString() ?? null,
            closesAt: assignment.closesAt?.toISOString() ?? null,
            timeLimitMinutes: assignment.timeLimitMinutes,
            shuffle: assignment.shuffle,
            revealAnswers: assignment.revealAnswers,
          }}
        />
      ) : (
        <AssignmentActions
          assignmentId={assignment.id}
          classroomId={assignment.classroom.id}
          templateReady={Boolean(assignment.sheetFieldBoxes)}
          studentCount={assignment.classroom.members.length}
        />
      )}

      <section className="glass-panel p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-base font-bold">Natijalar</h2>
          {/* Yuklab olish: Excel — jadvalda ishlash uchun, HTML — har bir
              o'quvchining javoblari bilan (ism ustiga bosilganda ochiladi). */}
          <div className="flex gap-2">
            <a
              href={`/api/assignments/${assignment.id}/results?format=xlsx`}
              className="btn-ghost !px-3 !py-1.5 text-xs"
            >
              Excel
            </a>
            <a
              href={`/api/assignments/${assignment.id}/results?format=html`}
              className="btn-ghost !px-3 !py-1.5 text-xs"
            >
              HTML (batafsil)
            </a>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-white/10 text-left text-xs text-muted">
                <th className="py-2 pr-3 font-semibold">№</th>
                <th className="py-2 pr-3 font-semibold">O&apos;quvchi</th>
                <th className="py-2 pr-3 font-semibold">Holat</th>
                <th className="py-2 pr-3 font-semibold">To&apos;g&apos;ri</th>
                <th className="w-48 py-2 pr-3 font-semibold">Foiz</th>
                <th className="py-2 text-right font-semibold">Amallar</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ student, sheet, member }, i) => {
                const name = studentDisplayName(student);
                const status = sheet ? sheetStatus(assignment, sheet, now) : null;
                return (
                  <tr key={student.id} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-muted">{i + 1}</td>
                    <td className="py-2 pr-3">
                      <Link
                        href={`/classrooms/${assignment.classroom.id}/students/${student.id}`}
                        className="font-semibold hover:underline"
                      >
                        {name}
                      </Link>
                      {!member && <span className="ml-2 text-xs text-muted">(guruhdan chiqqan)</span>}
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {!sheet || !status ? (
                        <span className="text-muted">varaq chiqarilmagan</span>
                      ) : status === "checked" ? (
                        <span className="text-emerald-300">✓ {formatTashkent(sheet.checkedAt!)}</span>
                      ) : (
                        <span
                          className={
                            status === "missed"
                              ? "text-red-300"
                              : status === "in_progress"
                                ? "text-gold"
                                : "text-muted"
                          }
                        >
                          {PENDING_LABEL[status]}
                          {status === "in_progress" && sheet.startedAt
                            ? ` · ${formatTashkent(sheet.startedAt)} dan`
                            : ""}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {sheet?.checkedAt ? `${sheet.correct}/${sheet.total}` : "—"}
                    </td>
                    <td className="py-2 pr-3">
                      {sheet?.checkedAt && sheet.percentage != null ? (
                        <div className="flex items-center gap-2">
                          <span className={`w-12 text-xs font-semibold ${scoreTone(sheet.percentage)}`}>
                            {sheet.percentage}%
                          </span>
                          <ScoreBar percentage={sheet.percentage} />
                        </div>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-2">
                      <div className="flex justify-end gap-1.5">
                        {!online && sheet && member && assignment.sheetFieldBoxes && (
                          <a
                            href={`/api/assignments/${assignment.id}/sheets?studentId=${student.id}`}
                            className="btn-ghost !px-2.5 !py-1 text-xs"
                          >
                            Varaq
                          </a>
                        )}
                        {sheet && (sheet.checkedAt || (online && sheet.startedAt)) && (
                          <ResetResultButton sheetId={sheet.id} studentName={name} online={online} />
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && (
            <p className="mt-3 text-sm text-muted">Guruhda o&apos;quvchi yo&apos;q.</p>
          )}
        </div>
      </section>

      {checked.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="glass-panel p-5">
            <h2 className="mb-1 font-display text-base font-bold">Mavzular bo&apos;yicha</h2>
            <p className="mb-4 text-xs text-muted">Eng qiyin mavzular yuqorida.</p>
            <div className="space-y-3">
              {themes.map((t) => (
                <div key={t.id}>
                  <div className="mb-1 flex justify-between gap-3 text-sm">
                    <span>{t.name}</span>
                    <span className={`font-semibold ${scoreTone(t.percentage)}`}>
                      {t.percentage}%{" "}
                      <span className="text-xs font-normal text-muted">
                        ({t.correct}/{t.total})
                      </span>
                    </span>
                  </div>
                  <ScoreBar percentage={t.percentage} />
                </div>
              ))}
              {themes.length === 0 && (
                <p className="text-sm text-muted">Savollarga mavzu biriktirilmagan.</p>
              )}
            </div>
          </section>

          <section className="glass-panel p-5">
            <h2 className="mb-1 font-display text-base font-bold">Savollar bo&apos;yicha</h2>
            <p className="mb-4 text-xs text-muted">
              Raqam, to&apos;g&apos;ri javob (qog&apos;ozdagi tartibda) va uni topgan o&apos;quvchilar
              ulushi.
            </p>
            <div className="grid grid-cols-5 gap-2 sm:grid-cols-8">
              {perQuestion.map((q) => (
                <div
                  key={q.n}
                  title={q.themes.join(", ")}
                  className="rounded-lg border border-white/10 bg-white/[0.03] px-1.5 py-2 text-center"
                >
                  <p className="text-xs text-muted">
                    {q.n}·{q.key}
                  </p>
                  <p className={`text-sm font-semibold ${scoreTone(q.pct)}`}>{q.pct}%</p>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
