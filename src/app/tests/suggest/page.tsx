import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { teacherPageSession } from "@/lib/page-auth";
import { studentDisplayName } from "@/lib/students";
import SuggestTestBuilder from "@/components/SuggestTestBuilder";

type Props = { searchParams: Promise<{ classroomId?: string; studentId?: string }> };

// A test built from what a student or a group got wrong (docs/DECISIONS.md #25).
export default async function SuggestTestPage({ searchParams }: Props) {
  const session = await teacherPageSession();
  const { classroomId, studentId } = await searchParams;

  const [classrooms, subjects] = await Promise.all([
    prisma.classroom.findMany({
      where: { teacherId: session.user.id, archived: false },
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        name: true,
        subjectId: true,
        members: { select: { student: { select: { id: true, firstName: true, lastName: true } } } },
      },
    }),
    prisma.subject.findMany({ orderBy: { name: "asc" }, select: { id: true, name: true } }),
  ]);

  const options = classrooms.map((c) => ({
    id: c.id,
    name: c.name,
    subjectId: c.subjectId,
    students: c.members
      .map((m) => ({ id: m.student.id, name: studentDisplayName(m.student) }))
      .sort((a, b) => a.name.localeCompare(b.name)),
  }));
  const initialClassroom = options.find((c) => c.id === classroomId) ?? options[0] ?? null;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/tests/new" className="text-xs text-muted hover:text-ivory hover:underline">
          ← Filtr bilan test yig&apos;ish
        </Link>
        <h1 className="mt-2 font-display text-2xl font-bold">O&apos;quvchiga qarab test</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">
          Tizim o&apos;quvchi yoki guruh natijalariga qarab savol taklif qiladi: zaif mavzulardan ko&apos;proq,
          hali sinalmagan mavzulardan ham, avval berilmagan savollar birinchi, qiyinlik aralash. Savollarni
          almashtirib yoki olib tashlab, testni yarating.
        </p>
      </div>

      {options.length === 0 ? (
        <p className="glass-panel p-5 text-sm text-muted">
          Avval guruh oching va o&apos;quvchi qo&apos;shing —{" "}
          <Link href="/classrooms" className="underline">
            Guruhlarim
          </Link>
          .
        </p>
      ) : (
        <SuggestTestBuilder
          classrooms={options}
          subjects={subjects}
          initialClassroomId={initialClassroom!.id}
          initialStudentId={initialClassroom!.students.some((s) => s.id === studentId) ? studentId! : ""}
        />
      )}
    </div>
  );
}
