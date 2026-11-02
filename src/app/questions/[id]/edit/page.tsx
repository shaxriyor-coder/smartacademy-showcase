import Link from "next/link";
import { notFound } from "next/navigation";
import { prisma } from "@/lib/prisma";
import { canEditQuestion } from "@/lib/access";
import { staffPageSession } from "@/lib/page-auth";
import QuestionForm from "@/components/QuestionForm";

export default async function EditQuestionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await staffPageSession();

  const [question, subjects, skills] = await Promise.all([
    prisma.question.findUnique({
      where: { id },
      include: { themes: true, subThemes: true, skills: true, createdBy: { select: { name: true } } },
    }),
    prisma.subject.findMany({
      include: { themes: { include: { subThemes: true } }, difficultyLevels: true },
      orderBy: { name: "asc" },
    }),
    prisma.skill.findMany({ orderBy: { name: "asc" } }),
  ]);

  if (!question) notFound();

  if (!canEditQuestion(question, session.user)) {
    return (
      <div className="glass-panel mx-auto max-w-lg p-8 text-center">
        <h1 className="mb-2 font-display text-xl font-bold">Tahrirlab bo&apos;lmaydi</h1>
        <p className="mb-6 text-sm text-muted">
          Bu savolni {question.createdBy.name} qo&apos;shgan. O&apos;qituvchi faqat o&apos;zi qo&apos;shgan
          savollarni o&apos;zgartiradi — xato bo&apos;lsa, adminga ayting.
        </p>
        <Link href="/questions" className="btn-ghost">
          Savollarga qaytish
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-6 font-display text-2xl font-bold">Savolni tahrirlash</h1>
      <QuestionForm subjects={subjects} skills={skills} initialData={question} />
    </div>
  );
}
