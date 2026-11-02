import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { loadStudentAnalytics } from "@/lib/analytics";
import { formatTashkent, type SheetStatus } from "@/lib/online-core";
import { scoreTone } from "@/lib/progress";
import { studentDisplayName } from "@/lib/students";
import { smartbotChildren, type SmartbotChild } from "@/lib/smartbot";
import LinkStudentForm from "@/components/LinkStudentForm";
import ScoreBar from "@/components/ScoreBar";
import NotificationToggle from "@/components/NotificationToggle";

// Tests listed per student here; the rest are on the student's analytics page.
const RECENT = 5;

type CabinetSheet = {
  id: string;
  status: SheetStatus;
  correct: number | null;
  total: number | null;
  percentage: number | null;
  assignment: { opensAt: Date | null };
};

function SheetState({ sheet }: { sheet: CabinetSheet }) {
  switch (sheet.status) {
    case "checked":
      return (
        <Link href={`/classroom-home/results/${sheet.id}`} className="text-right hover:underline">
          <span className={`font-semibold ${scoreTone(sheet.percentage)}`}>
            {sheet.correct}/{sheet.total} · {sheet.percentage}%
          </span>
          <span className="block text-xs text-muted">batafsil →</span>
        </Link>
      );
    case "in_progress":
      return (
        <Link href={`/classroom-home/tests/${sheet.id}`} className="text-xs font-semibold text-gold hover:underline">
          yechilmoqda — davom ettirish →
        </Link>
      );
    case "available":
      return (
        <Link href={`/classroom-home/tests/${sheet.id}`} className="text-xs font-semibold text-gold hover:underline">
          boshlash →
        </Link>
      );
    case "not_open":
      return (
        <span className="text-xs text-muted">
          ochiladi: {sheet.assignment.opensAt ? formatTashkent(sheet.assignment.opensAt) : "—"}
        </span>
      );
    case "missed":
      return <span className="text-xs text-red-300">topshirilmadi</span>;
    case "awaiting_scan":
      return <span className="text-xs text-muted">hali tekshirilmagan</span>;
  }
}

// Home for a logged-in Telegram account — a student or a parent, on the site
// or inside Telegram as the Mini App: open online tests first, then a summary
// per linked student with a link to their full analytics.
export default async function ClassroomHomePage() {
  const session = await auth();
  if (session?.user.kind !== "student") redirect("/login/student");

  const links = await prisma.studentTelegramLink.findMany({
    where: { telegramAccountId: session.user.id },
    orderBy: { linkedAt: "asc" },
    select: { studentId: true },
  });
  const account = await prisma.telegramAccount.findUnique({
    where: { id: session.user.id },
    select: { notifyEnabled: true, botUnreachableAt: true },
  });
  const cards = await Promise.all(
    links.map((l) => loadStudentAnalytics(l.studentId, { accountId: session.user.id })),
  );
  // Telegram botdagi "Farzandlarim" ro'yxati (docs/DECISIONS.md #33). Faqat
  // o'qish: farzand botda qo'shiladi. Bot bazasi sozlanmagan yoki javob
  // bermasa kabinet baribir ochiladi — ro'yxat ko'rsatilmaydi, xolos.
  let children: SmartbotChild[] = [];
  try {
    children = (await smartbotChildren(session.user.id)) ?? [];
  } catch (e) {
    console.error("smartbot children", e);
  }

  const actionable = cards.flatMap(({ student, sheets }) =>
    sheets
      .filter((s) => s.status === "available" || s.status === "in_progress")
      .map((sheet) => ({ student, sheet })),
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold">Salom, {session.user.name}!</h1>
        <p className="text-sm text-muted">
          {cards.length
            ? "Ulangan o'quvchilarning testlari va natijalari."
            : "Natijalarni ko'rish uchun o'qituvchi bergan ulash kodini kiriting."}
        </p>
      </div>

      {cards.length > 0 && account && (
        <NotificationToggle enabled={account.notifyEnabled} unreachable={account.botUnreachableAt != null} />
      )}

      {children.length > 0 && (
        <section className="glass-panel p-5">
          <h2 className="font-display text-base font-bold">Farzandlarim</h2>
          <p className="mb-3 text-xs text-muted">
            Telegram botdagi ro&apos;yxat. Qo&apos;shish, tahrirlash va olimpiadaga yozdirish
            botning «Farzandlarim» bo&apos;limida.
          </p>
          <div className="space-y-2">
            {children.map((c) => (
              <div key={c.id} className="rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">
                    {c.lastName} {c.firstName}
                    <span className="ml-2 text-xs font-normal text-muted">
                      {c.grade}-sinf
                      {c.school && ` · ${c.school}`}
                    </span>
                  </p>
                  <span className="text-xs text-muted">
                    {c.olympiads.length
                      ? `${c.olympiads.length} ta olimpiada`
                      : "olimpiadaga yozilmagan"}
                  </span>
                </div>
                {c.olympiads.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {c.olympiads.map((o, i) => (
                      <li key={i} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span>
                          {o.name}
                          {o.grade != null && ` · ${o.grade}-sinf`}
                        </span>
                        <span className={o.score == null ? "text-muted" : "font-semibold"}>
                          {o.score == null
                            ? "natija kutilmoqda"
                            : `${o.score} ball${o.place ? ` · ${o.place}-o'rin` : ""}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {actionable.length > 0 && (
        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">Hozir yechish mumkin</h2>
          <div className="space-y-2">
            {actionable.map(({ student, sheet }) => (
              <Link
                key={sheet.id}
                href={`/classroom-home/tests/${sheet.id}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gold/30 bg-gold/10 px-3.5 py-3 transition hover:bg-gold/15"
              >
                <div>
                  <p className="text-sm font-semibold">{sheet.assignment.title}</p>
                  <p className="text-xs text-muted">
                    {studentDisplayName(student)} · {sheet.assignment.classroom.name}
                    {sheet.assignment.closesAt && ` · ${formatTashkent(sheet.assignment.closesAt)} gacha`}
                    {sheet.assignment.timeLimitMinutes && ` · ${sheet.assignment.timeLimitMinutes} daqiqa`}
                  </p>
                </div>
                <span className="btn-gold !px-3 !py-1.5 text-xs">
                  {sheet.status === "in_progress" ? "Davom ettirish" : "Boshlash"}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {cards.map(({ student, sheets, analytics: a }) => (
        <section key={student.id} className="glass-panel p-5">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-display text-lg font-bold">{studentDisplayName(student)}</h2>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {student.memberships.map((m) => (
                  <span key={m.id} className="tag">
                    {m.classroom.name}
                  </span>
                ))}
              </div>
            </div>
            <Link href={`/classroom-home/students/${student.id}`} className="btn-ghost !px-3 !py-1.5 text-xs">
              To&apos;liq tahlil →
            </Link>
          </div>

          {a.counts.checked > 0 && (
            <dl className="mb-4 grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-white/[0.04] px-2 py-2">
                <dt className="text-[11px] text-muted">O&apos;rtacha</dt>
                <dd className="text-lg font-semibold">{a.average}%</dd>
              </div>
              <div className="rounded-xl bg-white/[0.04] px-2 py-2">
                <dt className="text-[11px] text-muted">Oxirgi test</dt>
                <dd className="text-lg font-semibold">
                  {a.last?.percentage}%
                  {a.change != null && a.change !== 0 && (
                    <span className={`ml-1 text-xs ${a.change > 0 ? "text-emerald-300" : "text-red-300"}`}>
                      <span aria-hidden>{a.change > 0 ? "▲" : "▼"}</span>
                      {a.change > 0 ? "+" : "−"}
                      {Math.abs(a.change)}
                    </span>
                  )}
                </dd>
              </div>
              <div className="rounded-xl bg-white/[0.04] px-2 py-2">
                <dt className="text-[11px] text-muted">Topshirilgan</dt>
                <dd className="text-lg font-semibold">
                  {a.counts.checked}/{a.counts.assigned}
                </dd>
              </div>
            </dl>
          )}

          {a.focus.length > 0 && (
            <p className="mb-4 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">
              Ko&apos;proq e&apos;tibor kerak: {a.focus.map((t) => `${t.name} (${t.percentage}%)`).join(", ")}
            </p>
          )}

          <div className="space-y-3">
            {sheets.slice(0, RECENT).map((s) => (
              <div key={s.id} className="rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold">
                      {s.assignment.title}
                      <span className="ml-2 text-xs font-normal text-muted">
                        {s.assignment.mode === "ONLINE" ? "online" : "qog'ozda"}
                      </span>
                    </p>
                    <p className="text-xs text-muted">
                      {s.assignment.classroom.name} · {formatTashkent(s.assignment.createdAt)}
                    </p>
                  </div>
                  <SheetState sheet={s} />
                </div>
                {s.checkedAt && (
                  <div className="mt-2">
                    <ScoreBar percentage={s.percentage ?? 0} label={`${s.assignment.title}: ${s.percentage}%`} />
                  </div>
                )}
              </div>
            ))}
            {sheets.length === 0 && (
              <p className="text-sm text-muted">Hozircha biriktirilgan test yo&apos;q.</p>
            )}
            {sheets.length > RECENT && (
              <Link href={`/classroom-home/students/${student.id}`} className="block text-center text-xs text-muted hover:text-ivory hover:underline">
                Barcha testlar ({sheets.length}) va to&apos;liq tahlil →
              </Link>
            )}
          </div>
        </section>
      ))}

      <section className="glass-panel p-5">
        <h2 className="mb-1 font-display text-base font-bold">
          {cards.length ? "Yana o'quvchi ulash" : "O'quvchini ulash"}
        </h2>
        <p className="mb-3 text-xs text-muted">
          Kodni o&apos;qituvchidan oling. Bir nechta farzandingiz bo&apos;lsa, har birining kodini
          alohida kiriting.
        </p>
        <LinkStudentForm />
      </section>
    </div>
  );
}
