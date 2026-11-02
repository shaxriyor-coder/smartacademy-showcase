import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { scoreTone, themeStats } from "@/lib/progress";
import { studentDisplayName } from "@/lib/students";
import { teacherPageSession } from "@/lib/page-auth";
import ScoreBar from "@/components/ScoreBar";

type Props = { params: Promise<{ id: string; studentId: string }> };

// One student's history across the teacher's classrooms — a child in two of
// their groups has one record, so one progress page. Groups of other teachers
// stay out of it (docs/DECISIONS.md #20).
export default async function StudentProgressPage({ params }: Props) {
  const { id, studentId } = await params;
  const teacherId = (await teacherPageSession()).user.id;
  const student = await prisma.student.findFirst({
    where: { id: studentId, memberships: { some: { classroom: { teacherId } } } },
    include: {
      _count: { select: { telegramLinks: true } },
      memberships: {
        where: { classroom: { archived: false, teacherId } },
        include: { classroom: { select: { id: true, name: true } } },
      },
      sheets: {
        where: { checkedAt: { not: null }, assignment: { archived: false, classroom: { teacherId } } },
        orderBy: { assignment: { createdAt: "asc" } },
        include: {
          assignment: {
            select: {
              id: true,
              title: true,
              subjectName: true,
              createdAt: true,
              questionIds: true,
              answerKey: true,
              classroom: { select: { id: true, name: true } },
            },
          },
        },
      },
    },
  });
  if (!student) notFound();

  const themes = await themeStats(
    student.sheets.map((s) => ({
      answers: s.answers,
      questionIds: s.assignment.questionIds,
      answerKey: s.assignment.answerKey,
    })),
  );
  const percentages = student.sheets.map((s) => s.percentage ?? 0);
  const average = percentages.length
    ? Math.round((percentages.reduce((a, b) => a + b, 0) / percentages.length) * 10) / 10
    : null;
  const trend =
    percentages.length >= 2
      ? Math.round((percentages[percentages.length - 1] - percentages[0]) * 10) / 10
      : null;
  const birth = student.birthDate?.toISOString().slice(0, 10).split("-").reverse().join(".");

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/classrooms/${id}`} className="text-xs text-muted hover:text-ivory hover:underline">
          ← Guruhga qaytish
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <h1 className="font-display text-2xl font-bold">{studentDisplayName(student)}</h1>
          <Link href={`/tests/suggest?classroomId=${id}&studentId=${student.id}`} className="btn-ghost !px-3 !py-1.5 text-xs">
            ✨ Shu o&apos;quvchiga qarab test
          </Link>
        </div>
        <p className="text-sm text-muted">
          {student.grade ? `${student.grade} sinf` : "Sinf ko'rsatilmagan"}
          {birth && ` · ${birth}`} · ulash kodi{" "}
          <span className="font-mono">{`${student.linkCode.slice(0, 4)}-${student.linkCode.slice(4)}`}</span>{" "}
          · Telegram: {student._count.telegramLinks > 0 ? `${student._count.telegramLinks} ta akkaunt` : "ulanmagan"}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {student.memberships.map((m) => (
            <Link key={m.id} href={`/classrooms/${m.classroom.id}`} className="tag hover:underline">
              {m.classroom.name}
            </Link>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="glass-panel p-4">
          <p className="text-xs text-muted">Tekshirilgan testlar</p>
          <p className="mt-1 font-display text-xl font-bold">{student.sheets.length}</p>
        </div>
        <div className="glass-panel p-4">
          <p className="text-xs text-muted">O&apos;rtacha</p>
          <p className={`mt-1 font-display text-xl font-bold ${scoreTone(average)}`}>
            {average == null ? "—" : `${average}%`}
          </p>
        </div>
        <div className="glass-panel p-4">
          <p className="text-xs text-muted">Birinchidan oxirgisigacha</p>
          <p
            className={`mt-1 font-display text-xl font-bold ${
              trend == null ? "" : trend >= 0 ? "text-emerald-300" : "text-red-300"
            }`}
          >
            {trend == null ? "—" : `${trend >= 0 ? "+" : ""}${trend}%`}
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="glass-panel p-5">
          <h2 className="mb-4 font-display text-base font-bold">Natijalar dinamikasi</h2>
          <div className="space-y-3">
            {student.sheets.map((s) => (
              <div key={s.id}>
                <div className="mb-1 flex justify-between gap-3 text-sm">
                  <Link
                    href={`/classrooms/${s.assignment.classroom.id}/assignments/${s.assignment.id}`}
                    className="hover:underline"
                  >
                    {s.assignment.title}
                    <span className="ml-1.5 text-xs text-muted">
                      {s.assignment.classroom.name} · {s.assignment.createdAt.toLocaleDateString("uz-UZ")}
                    </span>
                  </Link>
                  <span className={`shrink-0 font-semibold ${scoreTone(s.percentage)}`}>
                    {s.correct}/{s.total} · {s.percentage}%
                  </span>
                </div>
                <ScoreBar percentage={s.percentage ?? 0} />
              </div>
            ))}
            {student.sheets.length === 0 && (
              <p className="text-sm text-muted">Hozircha tekshirilgan test yo&apos;q.</p>
            )}
          </div>
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-1 font-display text-base font-bold">Mavzular bo&apos;yicha</h2>
          <p className="mb-4 text-xs text-muted">Barcha testlar jamlanmasi, eng zaif mavzular yuqorida.</p>
          <div className="space-y-3">
            {themes.map((t) => (
              <div key={t.id}>
                <div className="mb-1 flex justify-between gap-3 text-sm">
                  <span>{t.name}</span>
                  <span className={`font-semibold ${scoreTone(t.percentage)}`}>
                    {t.percentage}% <span className="text-xs font-normal text-muted">({t.correct}/{t.total})</span>
                  </span>
                </div>
                <ScoreBar percentage={t.percentage} />
              </div>
            ))}
            {themes.length === 0 && <p className="text-sm text-muted">Ma&apos;lumot yo&apos;q.</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
