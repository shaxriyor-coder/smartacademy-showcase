"use client";

import { useEffect, useState, FormEvent } from "react";
import { apiErrorMessage } from "@/lib/fetch-error";
import { ROLE_LABELS, STAFF_ROLES, type StaffRole } from "@/lib/roles";
import { useDialog } from "@/components/DialogProvider";

type Staff = {
  id: string;
  name: string;
  email: string | null;
  role: StaffRole;
  // Admin/SuperAdmin o'qituvchi ishini ham qiladi (docs/DECISIONS.md #30).
  canTeach: boolean;
  telegramChatId: string | null;
  createdAt: string;
  _count: { classrooms: number; tests: number; questions: number };
};

const ROLE_TAG: Record<StaffRole, string> = {
  SUPER_ADMIN: "tag-gold",
  ADMIN: "tag-glow",
  TEACHER: "bg-emerald-400/10 text-emerald-300",
};

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(apiErrorMessage(body));
  return body as T;
}

export default function StaffPage() {
  const dialog = useDialog();
  const [staff, setStaff] = useState<Staff[]>([]);
  const [meId, setMeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    try {
      setStaff(await jsonFetch<Staff[]>("/api/admins"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate fetch-on-mount
    load();
    fetch("/api/auth/session")
      .then((r) => r.json())
      .then((s) => setMeId(s?.user?.id ?? null))
      .catch(() => {});
  }, []);

  async function run(action: () => Promise<string | void>) {
    setError(null);
    setNotice(null);
    try {
      const message = await action();
      if (message) setNotice(message);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function addStaff(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    void run(async () => {
      await jsonFetch("/api/admins", {
        method: "POST",
        body: JSON.stringify({
          name: data.get("name"),
          email: data.get("email"),
          password: data.get("password"),
          role: data.get("role"),
          telegramChatId: (data.get("telegramChatId") as string) || null,
        }),
      });
      form.reset();
      return "Xodim qo'shildi.";
    });
  }

  const update = (id: string, patch: Partial<Pick<Staff, "role" | "canTeach" | "telegramChatId">>) =>
    run(async () => {
      await jsonFetch(`/api/admins/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
    });

  const remove = async (s: Staff) => {
    if (!(await dialog.confirm(`${s.name} o'chirilsinmi?`))) return;
    void run(async () => {
      await jsonFetch(`/api/admins/${s.id}`, { method: "DELETE" });
      return "Xodim o'chirildi.";
    });
  };

  async function transfer(from: Staff, e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const toUserId = data.get("toUserId") as string;
    const to = staff.find((s) => s.id === toUserId);
    if (!to) return;
    if (!(await dialog.confirm(`${from.name}ning barcha guruhlari ${to.name}ga o'tkazilsinmi?`))) return;
    void run(async () => {
      const result = await jsonFetch<{ classrooms: number; tests: number }>(
        `/api/admins/${from.id}/transfer`,
        { method: "POST", body: JSON.stringify({ toUserId, includeTests: data.get("includeTests") === "on" }) },
      );
      return `${to.name}ga ${result.classrooms} ta guruh${result.tests ? ` va ${result.tests} ta test` : ""} o'tkazildi.`;
    });
  }

  if (loading) return <p className="text-muted">Yuklanmoqda...</p>;

  // Guruhlarni qabul qila oladiganlar: o'qituvchilar va o'qituvchi huquqi
  // berilgan xodimlar (docs/DECISIONS.md #30).
  const teachers = staff.filter((s) => s.role === "TEACHER" || s.canTeach);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold">Xodimlar</h1>
        <p className="mt-1 max-w-prose text-sm text-muted">
          O&apos;qituvchi — o&apos;z guruhlari, o&apos;quvchilari va testlari bilan ishlaydi. Admin va
          SuperAdmin guruhlarni ochmaydi: savollar bazasi, testlar va markaz tahlilini boshqaradi.
        </p>
        <p className="mt-2 max-w-prose text-xs text-muted">
          Smartbot orqali (Open App yoki Telegram tugmasi) kirgan xodimning roli botdagi rolidan olinadi va
          har kirishda yangilanadi — bu yerda qo&apos;lda qo&apos;shish faqat email bilan kirish uchun.
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">{error}</p>
      )}
      {notice && (
        <p className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-300">
          {notice}
        </p>
      )}

      <section className="glass-panel p-5">
        <h2 className="mb-4 font-display text-base font-bold">Yangi xodim qo&apos;shish</h2>
        <form onSubmit={addStaff} className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <input name="name" placeholder="Ism" required className="input-field" />
          <input name="email" type="email" placeholder="Email" required className="input-field" />
          <input name="password" type="password" placeholder="Parol" required className="input-field" />
          <select name="role" className="input-field" defaultValue="TEACHER">
            {STAFF_ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
          <input
            name="telegramChatId"
            placeholder="Telegram ID (ixtiyoriy — 2FA uchun)"
            className="input-field md:col-span-2"
          />
          <button className="btn-gold md:col-span-2">Qo&apos;shish</button>
        </form>
        <p className="mt-3 text-xs text-muted">
          Telegram ID&apos;ni xodim o&apos;zi <code>npm run bot</code> orqali ishlaydigan botga yozib,
          o&apos;ziga qaytgan raqamdan oladi.
        </p>
      </section>

      <section className="glass-panel p-5">
        <h2 className="mb-4 font-display text-base font-bold">Ro&apos;yxat</h2>
        <div className="space-y-2">
          {staff.map((s) => {
            const isMe = s.id === meId;
            const targets = teachers.filter((t) => t.id !== s.id);
            return (
              <div key={s.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{s.name}</span>
                      <span className={`tag ${ROLE_TAG[s.role]}`}>{ROLE_LABELS[s.role]}</span>
                      {s.canTeach && s.role !== "TEACHER" && (
                        <span className={`tag ${ROLE_TAG.TEACHER}`}>+ o&apos;qituvchi</span>
                      )}
                      {isMe && <span className="text-xs text-muted">(siz)</span>}
                    </div>
                    <p className="text-xs text-muted">
                      {s.email ?? "faqat Telegram orqali"} · {s._count.classrooms} ta guruh · {s._count.tests} ta test ·{" "}
                      {s._count.questions} ta savol
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label={`${s.name} roli`}
                      value={s.role}
                      disabled={isMe}
                      onChange={(e) => void update(s.id, { role: e.target.value as StaffRole })}
                      className="input-field w-36 !py-1.5 text-xs"
                    >
                      {STAFF_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </option>
                      ))}
                    </select>
                    {s.role !== "TEACHER" && (
                      <label
                        className="flex items-center gap-1.5 text-xs text-muted"
                        title="Guruh ochish va topshiriq biriktirish — roli o'zgarmaydi"
                      >
                        <input
                          type="checkbox"
                          checked={s.canTeach}
                          onChange={(e) => void update(s.id, { canTeach: e.target.checked })}
                        />
                        O&apos;qituvchi huquqi
                      </label>
                    )}
                    <input
                      defaultValue={s.telegramChatId ?? ""}
                      placeholder="Telegram ID"
                      aria-label={`${s.name} Telegram ID`}
                      className="input-field w-36 !py-1.5 text-xs"
                      onBlur={(e) => {
                        const value = e.target.value.trim();
                        if (value !== (s.telegramChatId ?? "")) void update(s.id, { telegramChatId: value || null });
                      }}
                    />
                    {!isMe && (
                      <button onClick={() => void remove(s)} className="btn-danger-ghost">
                        O&apos;chirish
                      </button>
                    )}
                  </div>
                </div>

                {s._count.classrooms > 0 && (
                  <form
                    onSubmit={(e) => void transfer(s, e)}
                    className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/10 pt-3 text-xs"
                  >
                    <span className="text-muted">
                      {s.role === "TEACHER"
                        ? "Guruhlarini boshqa o'qituvchiga berish:"
                        : "Bu guruhlar o'qituvchi rolidan oldin ochilgan — o'qituvchiga o'tkazing:"}
                    </span>
                    {targets.length > 0 ? (
                      <>
                        <select name="toUserId" required className="input-field w-44 !py-1.5 text-xs" defaultValue="">
                          <option value="" disabled>
                            O&apos;qituvchini tanlang
                          </option>
                          {targets.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                        <label className="flex items-center gap-1.5 text-muted">
                          <input type="checkbox" name="includeTests" /> testlari bilan
                        </label>
                        <button className="btn-ghost !px-3 !py-1.5 text-xs">O&apos;tkazish</button>
                      </>
                    ) : (
                      <span className="text-muted">avval o&apos;qituvchi qo&apos;shing.</span>
                    )}
                  </form>
                )}
              </div>
            );
          })}
          {staff.length === 0 && <p className="text-sm text-muted">Xodimlar yo&apos;q.</p>}
        </div>
      </section>
    </div>
  );
}
