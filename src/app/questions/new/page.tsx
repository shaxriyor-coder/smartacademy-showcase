import { prisma } from "@/lib/prisma";
import NewQuestionModeSwitch from "@/components/NewQuestionModeSwitch";

export default async function NewQuestionPage() {
  const [subjects, skills] = await Promise.all([
    prisma.subject.findMany({
      include: { themes: { include: { subThemes: true } }, difficultyLevels: true },
      orderBy: { name: "asc" },
    }),
    prisma.skill.findMany({ orderBy: { name: "asc" } }),
  ]);

  return (
    <div>
      <h1 className="mb-6 font-display text-2xl font-bold">Savol qo&apos;shish</h1>
      <NewQuestionModeSwitch subjects={subjects} skills={skills} />
    </div>
  );
}
