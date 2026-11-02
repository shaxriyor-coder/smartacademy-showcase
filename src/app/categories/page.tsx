"use client";

import { useEffect, useState, FormEvent } from "react";
import { useDialog } from "@/components/DialogProvider";

type SubTheme = { id: string; name: string };
type Theme = { id: string; name: string; subThemes: SubTheme[] };
type DifficultyLevel = { id: string; name: string; order: number };
type Subject = {
  id: string;
  name: string;
  themes: Theme[];
  difficultyLevels: DifficultyLevel[];
};
type Skill = { id: string; name: string };

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ? JSON.stringify(body.error) : "Xatolik yuz berdi");
  }
  return res.json();
}

export default function CategoriesPage() {
  const dialog = useDialog();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function loadAll() {
    setLoading(true);
    try {
      const [subj, sk] = await Promise.all([
        jsonFetch<Subject[]>("/api/subjects"),
        jsonFetch<Skill[]>("/api/skills"),
      ]);
      setSubjects(subj);
      setSkills(sk);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate fetch-on-mount
    loadAll();
  }, []);

  async function handle(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await loadAll();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function addSubject(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const name = (new FormData(form).get("name") as string) ?? "";
    if (!name.trim()) return;
    await handle(() =>
      jsonFetch("/api/subjects", { method: "POST", body: JSON.stringify({ name }) }),
    );
    form.reset();
  }

  async function deleteSubject(id: string) {
    if (!(await dialog.confirm("Fanni o'chirishni tasdiqlaysizmi? Unga bog'liq mavzu va savollar ham ta'sirlanishi mumkin."))) return;
    await handle(() => jsonFetch(`/api/subjects/${id}`, { method: "DELETE" }));
  }

  async function addSkill(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const name = (new FormData(form).get("name") as string) ?? "";
    if (!name.trim()) return;
    await handle(() =>
      jsonFetch("/api/skills", { method: "POST", body: JSON.stringify({ name }) }),
    );
    form.reset();
  }

  async function deleteSkill(id: string) {
    if (!(await dialog.confirm("Mahorat tegini o'chirasizmi?"))) return;
    await handle(() => jsonFetch(`/api/skills/${id}`, { method: "DELETE" }));
  }

  if (loading) return <p className="text-muted">Yuklanmoqda...</p>;

  return (
    <div className="space-y-8">
      <h1 className="font-display text-2xl font-bold">Kategoriyalar</h1>

      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <section className="glass-panel p-5">
        <h2 className="mb-4 font-display text-base font-bold">Fanlar</h2>

        <form onSubmit={addSubject} className="mb-4 flex gap-2">
          <input name="name" placeholder="Yangi fan nomi" className="input-field flex-1" />
          <button className="btn-gold">Qo&apos;shish</button>
        </form>

        <div className="space-y-2">
          {subjects.map((s) => (
            <SubjectRow
              key={s.id}
              subject={s}
              expanded={expandedId === s.id}
              onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
              onDelete={() => deleteSubject(s.id)}
              onChanged={loadAll}
              onError={setError}
            />
          ))}
          {subjects.length === 0 && (
            <p className="text-sm text-muted">Hozircha fanlar yo&apos;q.</p>
          )}
        </div>
      </section>

      <section className="glass-panel p-5">
        <h2 className="mb-4 font-display text-base font-bold">Talab qilinadigan mahorat teglari</h2>

        <form onSubmit={addSkill} className="mb-4 flex gap-2">
          <input
            name="name"
            placeholder="Masalan: muammoli, matematik"
            className="input-field flex-1"
          />
          <button className="btn-gold">Qo&apos;shish</button>
        </form>

        <div className="flex flex-wrap gap-2">
          {skills.map((sk) => (
            <span key={sk.id} className="tag border border-white/10 bg-white/[0.06] py-1.5">
              {sk.name}
              <button
                onClick={() => deleteSkill(sk.id)}
                className="ml-1 text-muted hover:text-red-300"
                aria-label="O'chirish"
              >
                ×
              </button>
            </span>
          ))}
          {skills.length === 0 && (
            <p className="text-sm text-muted">Hozircha mahorat teglari yo&apos;q.</p>
          )}
        </div>
      </section>
    </div>
  );
}

function SubjectRow({
  subject,
  expanded,
  onToggle,
  onDelete,
  onChanged,
  onError,
}: {
  subject: Subject;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onChanged: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const dialog = useDialog();

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      await onChanged();
    } catch (e) {
      onError((e as Error).message);
    }
  }

  async function addTheme(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const name = (new FormData(form).get("name") as string) ?? "";
    if (!name.trim()) return;
    await run(() =>
      jsonFetch("/api/themes", {
        method: "POST",
        body: JSON.stringify({ subjectId: subject.id, name }),
      }),
    );
    form.reset();
  }

  async function deleteTheme(id: string) {
    if (!(await dialog.confirm("Mavzuni o'chirasizmi?"))) return;
    await run(() => jsonFetch(`/api/themes/${id}`, { method: "DELETE" }));
  }

  async function addSubTheme(themeId: string, name: string) {
    if (!name.trim()) return;
    await run(() =>
      jsonFetch("/api/subthemes", {
        method: "POST",
        body: JSON.stringify({ themeId, name }),
      }),
    );
  }

  async function deleteSubTheme(id: string) {
    if (!(await dialog.confirm("Ichki mavzuni o'chirasizmi?"))) return;
    await run(() => jsonFetch(`/api/subthemes/${id}`, { method: "DELETE" }));
  }

  async function addDifficulty(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const name = (data.get("name") as string) ?? "";
    const order = Number(data.get("order") ?? subject.difficultyLevels.length);
    if (!name.trim()) return;
    await run(() =>
      jsonFetch("/api/difficulty-levels", {
        method: "POST",
        body: JSON.stringify({ subjectId: subject.id, name, order }),
      }),
    );
    form.reset();
  }

  async function deleteDifficulty(id: string) {
    if (!(await dialog.confirm("Qiyinchilik darajasini o'chirasizmi?"))) return;
    await run(() => jsonFetch(`/api/difficulty-levels/${id}`, { method: "DELETE" }));
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.03]">
      <div className="flex items-center justify-between px-4 py-3">
        <button onClick={onToggle} className="flex-1 text-left text-sm font-semibold">
          <span className="text-gold">{expanded ? "▾" : "▸"}</span> {subject.name}
          <span className="ml-2 text-xs font-normal text-muted">
            {subject.themes.length} mavzu, {subject.difficultyLevels.length} daraja
          </span>
        </button>
        <button onClick={onDelete} className="text-xs font-semibold text-red-300 hover:underline">
          O&apos;chirish
        </button>
      </div>

      {expanded && (
        <div className="grid grid-cols-1 gap-6 border-t border-white/10 p-4 md:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              Umumiy mavzular / ichki mavzular
            </h3>
            <form onSubmit={addTheme} className="mb-3 flex gap-2">
              <input name="name" placeholder="Yangi mavzu" className="input-field flex-1 !py-1.5" />
              <button className="btn-gold !px-3 !py-1.5 text-xs">+</button>
            </form>
            <div className="space-y-3">
              {subject.themes.map((t) => (
                <ThemeRow
                  key={t.id}
                  theme={t}
                  onDeleteTheme={() => deleteTheme(t.id)}
                  onAddSubTheme={(name) => addSubTheme(t.id, name)}
                  onDeleteSubTheme={deleteSubTheme}
                />
              ))}
              {subject.themes.length === 0 && (
                <p className="text-sm text-muted">Mavzular yo&apos;q.</p>
              )}
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              Qiyinchilik darajalari
            </h3>
            <form onSubmit={addDifficulty} className="mb-3 flex gap-2">
              <input name="name" placeholder="Masalan: Oson" className="input-field flex-1 !py-1.5" />
              <input name="order" type="number" placeholder="Tartib" className="input-field w-20 !py-1.5" />
              <button className="btn-gold !px-3 !py-1.5 text-xs">+</button>
            </form>
            <ul className="space-y-1.5">
              {[...subject.difficultyLevels]
                .sort((a, b) => a.order - b.order)
                .map((d) => (
                  <li
                    key={d.id}
                    className="flex items-center justify-between rounded-lg bg-white/[0.05] px-3 py-1.5 text-sm"
                  >
                    <span>
                      {d.order}. {d.name}
                    </span>
                    <button
                      onClick={() => deleteDifficulty(d.id)}
                      className="text-muted hover:text-red-300"
                    >
                      ×
                    </button>
                  </li>
                ))}
              {subject.difficultyLevels.length === 0 && (
                <p className="text-sm text-muted">Darajalar yo&apos;q.</p>
              )}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function ThemeRow({
  theme,
  onDeleteTheme,
  onAddSubTheme,
  onDeleteSubTheme,
}: {
  theme: Theme;
  onDeleteTheme: () => void;
  onAddSubTheme: (name: string) => void;
  onDeleteSubTheme: (id: string) => void;
}) {
  const [newSubTheme, setNewSubTheme] = useState("");

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-semibold">{theme.name}</span>
        <button onClick={onDeleteTheme} className="text-xs text-red-300 hover:underline">
          o&apos;chirish
        </button>
      </div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {theme.subThemes.map((st) => (
          <span
            key={st.id}
            className="flex items-center gap-1 rounded-full bg-white/[0.08] px-2.5 py-1 text-xs text-muted ring-1 ring-white/10"
          >
            {st.name}
            <button
              onClick={() => onDeleteSubTheme(st.id)}
              className="text-muted hover:text-red-300"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onAddSubTheme(newSubTheme);
          setNewSubTheme("");
        }}
        className="flex gap-2"
      >
        <input
          value={newSubTheme}
          onChange={(e) => setNewSubTheme(e.target.value)}
          placeholder="Ichki mavzu qo'shish"
          className="input-field flex-1 !py-1 text-xs"
        />
        <button className="btn-ghost !px-2 !py-1 text-xs">+</button>
      </form>
    </div>
  );
}
