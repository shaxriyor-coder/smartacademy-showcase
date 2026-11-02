import Link from "next/link";
import type { ReactNode } from "react";
import { prisma } from "@/lib/prisma";
import { formatTashkentDate } from "@/lib/online-core";
import { staffPageSession } from "@/lib/page-auth";
import { hasTeacherAccess, isManager } from "@/lib/roles";

const DIFFICULTY_CLASS = "tag tag-gold";
const FOCUS_CLASS = "tag tag-glow";

export default async function HomePage() {
  const session = await staffPageSession();
  const { id, name, role, canTeach } = session.user;
  const teaches = hasTeacherAccess({ role, canTeach });

  // Ikkala ishni ham qiladigan xodim (DECISIONS.md #30): avval markaz
  // manzarasi, keyin o'zining guruhlari.
  if (teaches && isManager(role)) {
    return (
      <div>
        <ManagerHome name={name ?? ""} superAdmin={role === "SUPER_ADMIN"} />
        <div className="mt-10 border-t border-white/10 pt-8">
          <h2 className="mb-4 font-display text-lg font-bold">O&apos;qituvchi sifatida</h2>
          <TeacherHome id={id} name={name ?? ""} greeting={false} />
        </div>
      </div>
    );
  }

  return teaches ? (
    <TeacherHome id={id} name={name ?? ""} />
  ) : (
    <ManagerHome name={name ?? ""} superAdmin={role === "SUPER_ADMIN"} />
  );
}

function Greeting({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="mb-1 font-display text-2xl font-bold sm:text-3xl">Xayrli kun, {name}</h1>
      <p className="max-w-prose text-sm text-muted">{children}</p>
    </div>
  );
}

function Stats({ items }: { items: { label: string; value: number }[] }) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3.5 lg:grid-cols-4">
      {items.map((s) => (
        <div key={s.label} className="glass-panel p-[18px]">
          <div className="font-display text-2xl font-bold tabular-nums">{s.value}</div>
          <div className="mt-1 text-xs text-muted">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

async function TeacherHome({
  id,
  name,
  greeting = true,
}: {
  id: string;
  name: string;
  greeting?: boolean;
}) {
  const mine = { classroom: { teacherId: id, archived: false } };
  const [classroomCount, studentCount, testCount, questionCount, recent] = await Promise.all([
    prisma.classroom.count({ where: { teacherId: id, archived: false } }),
    prisma.student.count({ where: { memberships: { some: mine } } }),
    prisma.test.count({ where: { createdById: id } }),
    prisma.question.count({ where: { createdById: id } }),
    prisma.assignment.findMany({
      where: { archived: false, ...mine },
      orderBy: { createdAt: "desc" },
      take: 5,
      select: {
        id: true,
        title: true,
        mode: true,
        createdAt: true,
        classroom: { select: { id: true, name: true } },
        sheets: { select: { checkedAt: true } },
      },
    }),
  ]);

  return (
    <div>
      {greeting && (
        <Greeting name={name}>
          Savollar bazasidan filtr bilan test yig&apos;ing, guruhlaringizga online yoki qog&apos;ozda
          biriktiring va har bir guruh tahlilini kuzating.
        </Greeting>
      )}
      <Stats
        items={[
          { label: "Guruhlarim", value: classroomCount },
          { label: "O'quvchilarim", value: studentCount },
          { label: "Testlarim", value: testCount },
          { label: "Men qo'shgan savollar", value: questionCount },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className="glass-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-display text-base font-bold">So&apos;nggi topshiriqlar</h3>
            <Link href="/classrooms" className="text-xs font-semibold text-gold">
              guruhlarim →
            </Link>
          </div>
          <div className="divide-y divide-white/10">
            {recent.map((a) => (
              <Link
                key={a.id}
                href={`/classrooms/${a.classroom.id}/assignments/${a.id}`}
                className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0 hover:text-ivory"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">{a.title}</span>
                  <span className="text-xs text-muted">
                    {a.classroom.name} · {a.mode === "ONLINE" ? "online" : "qog'ozda"} ·{" "}
                    {formatTashkentDate(a.createdAt)}
                  </span>
                </span>
                <span className="shrink-0 text-xs tabular-nums text-muted">
                  {a.sheets.filter((s) => s.checkedAt).length}/{a.sheets.length} tekshirilgan
                </span>
              </Link>
            ))}
            {recent.length === 0 && (
              <p className="py-3 text-sm text-muted">
                Hali topshiriq yo&apos;q — guruh oching va test biriktiring.
              </p>
            )}
          </div>
        </div>

        <QuickActions>
          <Link href="/tests/new" className="btn-ghost justify-start">
            <FilterIcon /> Filtr orqali test yig&apos;ish
          </Link>
          <Link href="/questions/new" className="btn-ghost justify-start">
            <PlusIcon /> Yangi savol qo&apos;shish
          </Link>
          <Link href="/classrooms" className="btn-ghost justify-start">
            <UsersIcon /> Guruhlarim
          </Link>
          <Link href="/tests" className="btn-ghost justify-start">
            <DownloadIcon /> Testlarim
          </Link>
        </QuickActions>
      </div>
    </div>
  );
}

async function ManagerHome({ name, superAdmin }: { name: string; superAdmin: boolean }) {
  const [questionCount, testCount, teacherCount, studentCount, recentQuestions] = await Promise.all([
    prisma.question.count(),
    prisma.test.count(),
    prisma.user.count({ where: { role: "TEACHER" } }),
    prisma.student.count({ where: { memberships: { some: { classroom: { archived: false } } } } }),
    prisma.question.findMany({
      take: 4,
      orderBy: { createdAt: "desc" },
      include: { difficulty: true },
    }),
  ]);

  return (
    <div>
      <Greeting name={name}>
        Savollar bazasini boshqaring va markaz bo&apos;yicha o&apos;quvchilar, savollar hamda
        o&apos;qituvchilar tahlilini kuzating. Guruhlar ichi o&apos;qituvchilarniki.
      </Greeting>
      <Stats
        items={[
          { label: "Jami savollar", value: questionCount },
          { label: "Yaratilgan testlar", value: testCount },
          { label: "O'qituvchilar", value: teacherCount },
          { label: "O'quvchilar", value: studentCount },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
        <div className="glass-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-display text-base font-bold">So&apos;nggi qo&apos;shilgan savollar</h3>
            <Link href="/questions" className="text-xs font-semibold text-gold">
              barchasi →
            </Link>
          </div>
          <div className="divide-y divide-white/10">
            {recentQuestions.map((q) => (
              <div key={q.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-white/[0.08] text-gold">
                  <BookIcon />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{q.text}</p>
                  <div className="mt-1 flex gap-1.5">
                    <span className={DIFFICULTY_CLASS}>{q.difficulty.name}</span>
                    <span className={FOCUS_CLASS}>
                      {q.focus === "ABITURIENT" ? "Abiturient" : "PMT"}
                    </span>
                  </div>
                </div>
              </div>
            ))}
            {recentQuestions.length === 0 && (
              <p className="py-3 text-sm text-muted">Hozircha savollar yo&apos;q.</p>
            )}
          </div>
        </div>

        <QuickActions>
          <Link href="/analytics" className="btn-ghost justify-start">
            <ChartIcon /> Markaz tahlili
          </Link>
          <Link href="/analytics/questions" className="btn-ghost justify-start">
            <BookIcon /> Savollar bazasi tahlili
          </Link>
          <Link href="/analytics/teachers" className="btn-ghost justify-start">
            <UsersIcon /> O&apos;qituvchilar tahlili
          </Link>
          <Link href="/questions/new" className="btn-ghost justify-start">
            <PlusIcon /> Yangi savol qo&apos;shish
          </Link>
          {superAdmin && (
            <>
              <Link href="/categories" className="btn-ghost justify-start">
                <GridIcon /> Kategoriyalarni boshqarish
              </Link>
              <Link href="/admins" className="btn-ghost justify-start">
                <UsersIcon /> Xodimlar
              </Link>
            </>
          )}
        </QuickActions>
      </div>
    </div>
  );
}

function QuickActions({ children }: { children: ReactNode }) {
  return (
    <div className="glass-panel p-5">
      <h3 className="mb-4 font-display text-base font-bold">Tezkor amallar</h3>
      <div className="flex flex-col gap-2.5">{children}</div>
    </div>
  );
}

function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <path
        d="M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="M6 3v18" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
function FilterIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <path
        d="M4 5h16M7 12h10M10 19h4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <path
        d="M4 19h16M7 16v-5M12 16V7M17 16v-8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <path
        d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function UsersIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <circle cx="9" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M3.5 19c0-3 2.5-5.5 5.5-5.5S14.5 16 14.5 19"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <circle cx="17" cy="9" r="2.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M15.2 13.2c2.6.2 4.5 2.4 4.5 5.3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
function GridIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4 text-gold">
      <rect x="3" y="3" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="13" y="3" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <rect x="13" y="13" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
