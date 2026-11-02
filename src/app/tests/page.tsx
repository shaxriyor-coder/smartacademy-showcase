import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { testScope } from "@/lib/access";
import { staffPageSession } from "@/lib/page-auth";
import { isTeacher } from "@/lib/roles";

// Teachers see the tests they built; admins see every test.
export default async function TestsPage() {
  const session = await staffPageSession();
  const teacher = isTeacher(session.user.role);
  const tests = await prisma.test.findMany({
    where: testScope(session.user),
    include: { subject: true, createdBy: { select: { name: true } } },
    orderBy: { createdAt: "desc" },
    take: 200,
  });

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-bold">{teacher ? "Testlarim" : "Testlar tarixi"}</h1>
        <Link href="/tests/new" className="btn-gold">
          + Yangi test tayyorlash
        </Link>
      </div>

      <div className="space-y-3">
        {tests.map((t) => (
          <div
            key={t.id}
            className="glass-panel flex flex-wrap items-center justify-between gap-3 p-4"
          >
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-semibold">{t.title}</p>
                {t.isOlympiad && (
                  <span className="tag tag-gold">🏆 {t.olympiadName}</span>
                )}
              </div>
              <p className="text-xs text-muted">
                {t.subject.name} &middot; {t.questionIds.length} ta savol &middot;{" "}
                {t.createdBy.name} &middot; {new Date(t.createdAt).toLocaleDateString("uz-UZ")}
              </p>
            </div>
            <div className="flex gap-2">
              {teacher && (
                <Link href="/classrooms" className="btn-ghost !px-3 !py-1.5 text-xs">
                  Guruhga biriktirish
                </Link>
              )}
              <a
                href={`/api/tests/${t.id}/export`}
                className="btn-ghost !px-3 !py-1.5 text-xs"
              >
                Yuklab olish (Word)
              </a>
            </div>
          </div>
        ))}
        {tests.length === 0 && (
          <p className="text-sm text-muted">Hozircha testlar yaratilmagan.</p>
        )}
      </div>
    </div>
  );
}
