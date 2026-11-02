"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { jsonFetch } from "@/lib/fetch-error";
import { fromLocalInput } from "@/lib/datetime-local";
import { REVEAL_LABELS } from "@/lib/online-core";
import ClassroomAnalytics from "@/components/analytics/ClassroomAnalytics";
import { useDialog } from "@/components/DialogProvider";

type Student = {
  id: string;
  firstName: string;
  lastName: string | null;
  birthDate: string | null;
  grade: string | null;
  linkCode: string;
  _count: { telegramLinks: number };
};
type Member = { id: string; studentId: string; student: Student };
type AssignmentRow = {
  id: string;
  title: string;
  mode: "OFFLINE" | "ONLINE";
  subjectName: string;
  createdAt: string;
  questionCount: number;
  sheetCount: number;
  checkedCount: number;
};
type Classroom = {
  id: string;
  name: string;
  subjectId: string | null;
  subject: { name: string } | null;
  teacher: { name: string };
  members: Member[];
  assignments: AssignmentRow[];
};
type TestOption = {
  id: string;
  title: string;
  subjectId: string;
  subject: { name: string };
  questionIds: string[];
};

type AddMode = "new" | "bulk" | "code";

const ADD_MODES: [AddMode, string][] = [
  ["new", "Bittalab"],
  ["bulk", "Ro'yxat bilan"],
  ["code", "Kod bilan (boshqa guruhdan)"],
];

const formatCode = (code: string) => `${code.slice(0, 4)}-${code.slice(4)}`;
const formatDate = (iso: string | null) =>
  iso ? iso.slice(0, 10).split("-").reverse().join(".") : "—";
const fullName = (s: { firstName: string; lastName: string | null }) =>
  [s.lastName, s.firstName].filter(Boolean).join(" ");

function field(data: FormData, name: string) {
  return ((data.get(name) as string | null) ?? "").trim();
}

export default function ClassroomDetailPage() {
  const dialog = useDialog();
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [tests, setTests] = useState<TestOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [addMode, setAddMode] = useState<AddMode>("new");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [assignMode, setAssignMode] = useState<"OFFLINE" | "ONLINE">("OFFLINE");
  // null = not chosen yet: open on the analytics when there are results.
  const [view, setView] = useState<"analytics" | "manage" | null>(null);

  async function load() {
    try {
      const [c, t] = await Promise.all([
        jsonFetch<Classroom>(`/api/classrooms/${params.id}`),
        jsonFetch<TestOption[]>("/api/tests"),
      ]);
      setClassroom(c);
      setTests(t);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate fetch-on-mount/param-change
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  // A subject classroom only offers tests of its subject.
  const testOptions = classroom?.subjectId
    ? tests.filter((t) => t.subjectId === classroom.subjectId)
    : tests;

  async function run(action: () => Promise<unknown>, success?: string): Promise<boolean> {
    setError(null);
    setNotice(null);
    try {
      await action();
      if (success) setNotice(success);
      await load();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }

  async function addStudents(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const body =
      addMode === "new"
        ? {
            mode: "new",
            student: {
              firstName: field(data, "firstName"),
              lastName: field(data, "lastName") || null,
              birthDate: field(data, "birthDate") || null,
              grade: field(data, "grade") || null,
            },
          }
        : addMode === "bulk"
          ? { mode: "bulk", lines: field(data, "lines"), grade: field(data, "grade") || null }
          : { mode: "code", linkCode: field(data, "linkCode") };

    const ok = await run(async () => {
      const res = await jsonFetch<{ added: number }>(`/api/classrooms/${params.id}/members`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setNotice(`${res.added} ta o'quvchi qo'shildi`);
    });
    if (ok) form.reset();
  }

  async function saveStudent(e: FormEvent<HTMLFormElement>, studentId: string) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const ok = await run(
      () =>
        jsonFetch(`/api/students/${studentId}`, {
          method: "PATCH",
          body: JSON.stringify({
            firstName: field(data, "firstName"),
            lastName: field(data, "lastName") || null,
            birthDate: field(data, "birthDate") || null,
            grade: field(data, "grade") || null,
          }),
        }),
      "Saqlandi",
    );
    if (ok) setEditingId(null);
  }

  async function regenerateCode(student: Student) {
    if (!(await dialog.confirm(`${fullName(student)} uchun yangi ulash kodi yaratilsinmi? Eski kod ishlamay qoladi, allaqachon ulangan akkauntlar ulanganicha qoladi.`))) return;
    await run(
      () => jsonFetch(`/api/students/${student.id}/link-code`, { method: "POST" }),
      "Yangi kod yaratildi",
    );
  }

  async function removeMember(student: Student) {
    if (!(await dialog.confirm(`${fullName(student)} guruhdan chiqarilsinmi? Uning oldingi natijalari saqlanib qoladi.`))) return;
    await run(() =>
      jsonFetch(`/api/classrooms/${params.id}/members?studentId=${student.id}`, {
        method: "DELETE",
      }),
    );
  }

  async function assignTest(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const testId = field(data, "testId");
    if (!testId) return;
    setAssigning(true);
    setError(null);
    try {
      const base = { testId, title: field(data, "title") || undefined, mode: assignMode };
      const body =
        assignMode === "OFFLINE"
          ? base
          : {
              ...base,
              // datetime-local is the browser's wall clock; the API takes instants
              opensAt: fromLocalInput(field(data, "opensAt")),
              closesAt: fromLocalInput(field(data, "closesAt")),
              timeLimitMinutes: field(data, "timeLimitMinutes")
                ? Number(field(data, "timeLimitMinutes"))
                : null,
              shuffle: data.get("shuffle") === "on",
              revealAnswers: field(data, "revealAnswers"),
            };
      const res = await jsonFetch<{ id: string }>(`/api/classrooms/${params.id}/assignments`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      router.push(`/classrooms/${params.id}/assignments/${res.id}`);
    } catch (err) {
      setError((err as Error).message);
      setAssigning(false);
    }
  }

  if (loading) return <p className="text-muted">Yuklanmoqda...</p>;
  if (!classroom) return <p className="text-muted">{error ?? "Guruh topilmadi."}</p>;

  const activeView =
    view ?? (classroom.assignments.some((a) => a.checkedCount > 0) ? "analytics" : "manage");

  return (
    <div className="space-y-6">
      <div>
        <Link href="/classrooms" className="text-xs text-muted hover:text-ivory hover:underline">
          ← Guruhlarim
        </Link>
        <h1 className="mt-2 font-display text-2xl font-bold">{classroom.name}</h1>
        <p className="text-sm text-muted">
          {classroom.subject?.name ?? "Umumiy guruh"} &middot; {classroom.members.length} ta
          o&apos;quvchi &middot; {classroom.teacher.name}
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}
      {notice && (
        <p className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-300">
          {notice}
        </p>
      )}

      <div className="flex flex-wrap gap-2" role="tablist">
        {(
          [
            ["analytics", "Guruh tahlili"],
            ["manage", "Topshiriqlar va o'quvchilar"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeView === key}
            onClick={() => setView(key)}
            className={`pill ${activeView === key ? "is-active" : ""}`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeView === "analytics" && <ClassroomAnalytics classroomId={classroom.id} />}

      {activeView === "manage" && (
        <>
        <section className="glass-panel p-5">
          <h2 className="mb-1 font-display text-base font-bold">Topshiriqlar</h2>
          <p className="mb-4 text-xs text-muted">
            Testni guruhga biriktiring: savollar tartibi va javob kaliti shu paytda muzlatiladi.
            Offline — Word va har o&apos;quvchiga javob varag&apos;i, skan shu yerda tekshiriladi.
            Online — o&apos;quvchilar kabinetida yoki Telegram&apos;da yechadi.
          </p>
          <Link
            href={`/tests/suggest?classroomId=${classroom.id}`}
            className="mb-4 inline-block text-xs font-semibold text-gold hover:underline"
          >
            ✨ Guruhning zaif mavzulari bo&apos;yicha test tuzish →
          </Link>
          <div className="mb-3 flex flex-wrap gap-2">
            {(["OFFLINE", "ONLINE"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setAssignMode(mode)}
                className={`pill ${assignMode === mode ? "is-active" : ""}`}
              >
                {mode === "OFFLINE" ? "Offline (qog'ozda)" : "Online"}
              </button>
            ))}
          </div>
          <form onSubmit={assignTest} className="flex flex-wrap gap-2">
            <select name="testId" required defaultValue="" className="input-field min-w-[240px] flex-1">
              <option value="" disabled>
                {testOptions.length ? "Testni tanlang" : "Mos test yo'q — avval test tayyorlang"}
              </option>
              {testOptions.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title} · {t.subject.name} · {t.questionIds.length} savol
                </option>
              ))}
            </select>
            <input
              name="title"
              placeholder="Topshiriq nomi (ixtiyoriy)"
              className="input-field min-w-[200px] flex-1"
            />
            {assignMode === "ONLINE" && (
              <div className="grid w-full gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <label className="block">
                  <span className="label-field">Ochilish (bo&apos;sh — hozir)</span>
                  <input name="opensAt" type="datetime-local" className="input-field" />
                </label>
                <label className="block">
                  <span className="label-field">Yopilish (bo&apos;sh — muddatsiz)</span>
                  <input name="closesAt" type="datetime-local" className="input-field" />
                </label>
                <label className="block">
                  <span className="label-field">Vaqt chegarasi, daqiqa</span>
                  <input
                    name="timeLimitMinutes"
                    type="number"
                    min={1}
                    max={600}
                    placeholder="cheklanmagan"
                    className="input-field"
                  />
                </label>
                <label className="block">
                  <span className="label-field">To&apos;g&apos;ri javoblar</span>
                  <select name="revealAnswers" defaultValue="AFTER_CLOSE" className="input-field">
                    {Object.entries(REVEAL_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm sm:col-span-2 lg:col-span-4">
                  <input name="shuffle" type="checkbox" defaultChecked />
                  Har o&apos;quvchiga savollar va variantlar tartibini aralashtirish
                </label>
              </div>
            )}
            <button className="btn-gold" disabled={assigning || testOptions.length === 0}>
              {assigning ? "Biriktirilmoqda..." : "Biriktirish"}
            </button>
          </form>

          <div className="mt-4 space-y-2">
            {classroom.assignments.map((a) => (
              <Link
                key={a.id}
                href={`/classrooms/${classroom.id}/assignments/${a.id}`}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 transition hover:bg-white/[0.07]"
              >
                <div>
                  <p className="text-sm font-semibold">{a.title}</p>
                  <p className="text-xs text-muted">
                    {a.subjectName} &middot; {a.questionCount} savol &middot; {formatDate(a.createdAt)}
                  </p>
                </div>
                <span className="flex items-center gap-1.5">
                  <span className="tag">{a.mode === "ONLINE" ? "Online" : "Offline"}</span>
                  <span className="tag">
                    {a.checkedCount}/{a.sheetCount} {a.mode === "ONLINE" ? "topshirgan" : "tekshirilgan"}
                  </span>
                </span>
              </Link>
            ))}
            {classroom.assignments.length === 0 && (
              <p className="text-sm text-muted">Hozircha topshiriq yo&apos;q.</p>
            )}
          </div>
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-3 font-display text-base font-bold">O&apos;quvchi qo&apos;shish</h2>
          <div className="mb-4 flex flex-wrap gap-2">
            {ADD_MODES.map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setAddMode(mode)}
                className={`pill ${addMode === mode ? "is-active" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>

          <form key={addMode} onSubmit={addStudents} className="flex flex-wrap items-start gap-2">
            {addMode === "new" && (
              <>
                <input name="lastName" placeholder="Familiya" className="input-field min-w-[160px] flex-1" />
                <input name="firstName" placeholder="Ism" required className="input-field min-w-[160px] flex-1" />
                <input name="birthDate" type="date" title="Tug'ilgan sana" className="input-field w-auto" />
                <input name="grade" placeholder="Sinf (7-A)" className="input-field w-32" />
              </>
            )}
            {addMode === "bulk" && (
              <>
                <textarea
                  name="lines"
                  required
                  rows={6}
                  placeholder={"Har qatorda bitta o'quvchi: Familiya Ism\nAliyev Vali\nKarimova Madina"}
                  className="input-field w-full font-mono text-sm"
                />
                <input name="grade" placeholder="Sinf (hammasiga, ixtiyoriy)" className="input-field w-60" />
              </>
            )}
            {addMode === "code" && (
              <input
                name="linkCode"
                required
                placeholder="Ulash kodi, masalan K7M2-Q9XP"
                className="input-field min-w-[240px] flex-1 font-mono uppercase"
              />
            )}
            <button className="btn-gold">Qo&apos;shish</button>
          </form>
        </section>

        <section className="glass-panel p-5">
          <h2 className="mb-1 font-display text-base font-bold">
            O&apos;quvchilar ({classroom.members.length})
          </h2>
          <p className="mb-4 text-xs text-muted">
            Ulash kodini o&apos;quvchi yoki ota-onasiga bering: Telegram orqali kirib kodni
            kiritsa, natijalarini o&apos;zi ko&apos;radi. Bitta ota-ona bir nechta farzandini
            ulashi mumkin.
          </p>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs text-muted">
                  <th className="py-2 pr-3 font-semibold">№</th>
                  <th className="py-2 pr-3 font-semibold">Familiya, ism</th>
                  <th className="py-2 pr-3 font-semibold">Sinf</th>
                  <th className="py-2 pr-3 font-semibold">Tug&apos;ilgan sana</th>
                  <th className="py-2 pr-3 font-semibold">Ulash kodi</th>
                  <th className="py-2 pr-3 font-semibold">Telegram</th>
                  <th className="py-2 text-right font-semibold">Amallar</th>
                </tr>
              </thead>
              <tbody>
                {classroom.members.map((m, i) =>
                  editingId === m.studentId ? (
                    <tr key={m.id} className="border-b border-white/5">
                      <td colSpan={7} className="py-2">
                        <form
                          onSubmit={(e) => saveStudent(e, m.studentId)}
                          className="flex flex-wrap gap-2"
                        >
                          <input name="lastName" defaultValue={m.student.lastName ?? ""} placeholder="Familiya" className="input-field min-w-[140px] flex-1" />
                          <input name="firstName" defaultValue={m.student.firstName} placeholder="Ism" required className="input-field min-w-[140px] flex-1" />
                          <input name="birthDate" type="date" defaultValue={m.student.birthDate?.slice(0, 10) ?? ""} className="input-field w-auto" />
                          <input name="grade" defaultValue={m.student.grade ?? ""} placeholder="Sinf" className="input-field w-28" />
                          <button className="btn-gold !px-3 !py-1.5 text-xs">Saqlash</button>
                          <button type="button" onClick={() => setEditingId(null)} className="btn-ghost !px-3 !py-1.5 text-xs">
                            Bekor qilish
                          </button>
                        </form>
                      </td>
                    </tr>
                  ) : (
                    <tr key={m.id} className="border-b border-white/5">
                      <td className="py-2 pr-3 text-muted">{i + 1}</td>
                      <td className="py-2 pr-3 font-semibold">
                        <Link
                          href={`/classrooms/${classroom.id}/students/${m.studentId}`}
                          className="hover:underline"
                        >
                          {fullName(m.student)}
                        </Link>
                      </td>
                      <td className="py-2 pr-3">{m.student.grade ?? "—"}</td>
                      <td className="py-2 pr-3">{formatDate(m.student.birthDate)}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{formatCode(m.student.linkCode)}</td>
                      <td className="py-2 pr-3 text-xs">
                        {m.student._count.telegramLinks > 0 ? (
                          <span className="text-emerald-300">✓ {m.student._count.telegramLinks} ta akkaunt</span>
                        ) : (
                          <span className="text-muted">ulanmagan</span>
                        )}
                      </td>
                      <td className="py-2">
                        <div className="flex justify-end gap-1.5">
                          <button onClick={() => setEditingId(m.studentId)} className="btn-ghost !px-2.5 !py-1 text-xs">
                            Tahrirlash
                          </button>
                          <button onClick={() => regenerateCode(m.student)} className="btn-ghost !px-2.5 !py-1 text-xs">
                            Yangi kod
                          </button>
                          <button onClick={() => removeMember(m.student)} className="btn-danger-ghost">
                            Chiqarish
                          </button>
                        </div>
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
            {classroom.members.length === 0 && (
              <p className="mt-3 text-sm text-muted">Hozircha o&apos;quvchi yo&apos;q.</p>
            )}
          </div>
        </section>
        </>
      )}
    </div>
  );
}
