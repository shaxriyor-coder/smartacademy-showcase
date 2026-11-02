"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
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

type QuestionItem = {
  id: string;
  text: string;
  imageUrl: string | null;
  subject: { name: string };
  themes: { name: string }[];
  difficulty: { name: string };
  focus: "ABITURIENT" | "PMT";
  skills: { name: string }[];
  createdAt: string;
  createdBy: { name: string };
  // Teachers change only the questions they added (docs/DECISIONS.md #20).
  canEdit: boolean;
};

const PAGE_SIZES = [15, 30, 50, 100];

export default function QuestionsPage() {
  const dialog = useDialog();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);

  const [subjectId, setSubjectId] = useState("");
  const [themeIds, setThemeIds] = useState<string[]>([]);
  const [subThemeIds, setSubThemeIds] = useState<string[]>([]);
  const [difficultyId, setDifficultyId] = useState("");
  const [focus, setFocus] = useState("");
  const [skillIds, setSkillIds] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  const [items, setItems] = useState<QuestionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/subjects").then((r) => r.json()),
      fetch("/api/skills").then((r) => r.json()),
    ]).then(([s, sk]) => {
      setSubjects(s);
      setSkills(sk);
    });
  }, []);

  const subject = useMemo(() => subjects.find((s) => s.id === subjectId), [subjects, subjectId]);
  const availableSubThemes = useMemo(
    () =>
      (subject?.themes ?? []).filter((t) => themeIds.includes(t.id)).flatMap((t) => t.subThemes),
    [subject, themeIds],
  );

  async function loadQuestions() {
    setLoading(true);
    setError(null);
    const sp = new URLSearchParams();
    if (subjectId) sp.set("subjectId", subjectId);
    if (themeIds.length) sp.set("themeIds", themeIds.join(","));
    if (subThemeIds.length) sp.set("subThemeIds", subThemeIds.join(","));
    if (difficultyId) sp.set("difficultyId", difficultyId);
    if (focus) sp.set("focus", focus);
    if (skillIds.length) sp.set("skillIds", skillIds.join(","));
    if (dateFrom) sp.set("dateFrom", dateFrom);
    if (dateTo) sp.set("dateTo", dateTo);
    sp.set("page", String(page));
    sp.set("pageSize", String(pageSize));

    try {
      const res = await fetch(`/api/questions?${sp.toString()}`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Xatolik");
      setItems(body.items);
      setTotal(body.total);
      setTotalPages(body.totalPages);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate refetch-on-filter-change
    loadQuestions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subjectId, themeIds, subThemeIds, difficultyId, focus, skillIds, dateFrom, dateTo, page, pageSize]);

  function toggle(list: string[], id: string, setter: (v: string[]) => void) {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
    setPage(1);
  }

  async function deleteQuestion(id: string) {
    if (!(await dialog.confirm("Savolni o'chirasizmi?"))) return;
    const res = await fetch(`/api/questions/${id}`, { method: "DELETE" });
    if (res.ok) loadQuestions();
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-bold">Savollar</h1>
        <Link href="/questions/new" className="btn-gold">
          + Savol qo&apos;shish
        </Link>
      </div>

      <div className="glass-panel mb-6 grid grid-cols-1 gap-4 p-4 md:grid-cols-4">
        <div>
          <label className="label-field">Fan</label>
          <select
            value={subjectId}
            onChange={(e) => {
              setSubjectId(e.target.value);
              setThemeIds([]);
              setSubThemeIds([]);
              setDifficultyId("");
              setPage(1);
            }}
            className="input-field"
          >
            <option value="">Barchasi</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="label-field">Qiyinchilik</label>
          <select
            value={difficultyId}
            onChange={(e) => {
              setDifficultyId(e.target.value);
              setPage(1);
            }}
            className="input-field"
            disabled={!subject}
          >
            <option value="">Barchasi</option>
            {(subject?.difficultyLevels ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="label-field">Focus</label>
          <select
            value={focus}
            onChange={(e) => {
              setFocus(e.target.value);
              setPage(1);
            }}
            className="input-field"
          >
            <option value="">Barchasi</option>
            <option value="ABITURIENT">Abiturient</option>
            <option value="PMT">PMT</option>
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label-field">Sanadan</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
              className="input-field"
            />
          </div>
          <div>
            <label className="label-field">Sanagacha</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
              className="input-field"
            />
          </div>
        </div>

        {subject && (
          <div className="md:col-span-2">
            <label className="label-field">Umumiy mavzu</label>
            <div className="flex flex-wrap gap-1.5">
              {subject.themes.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggle(themeIds, t.id, setThemeIds)}
                  className={`pill ${themeIds.includes(t.id) ? "is-active" : ""}`}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {availableSubThemes.length > 0 && (
          <div className="md:col-span-2">
            <label className="label-field">Ichki mavzu</label>
            <div className="flex flex-wrap gap-1.5">
              {availableSubThemes.map((st) => (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => toggle(subThemeIds, st.id, setSubThemeIds)}
                  className={`pill ${subThemeIds.includes(st.id) ? "is-active" : ""}`}
                >
                  {st.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {skills.length > 0 && (
          <div className="md:col-span-4">
            <label className="label-field">Talab qilinadigan mahorat</label>
            <div className="flex flex-wrap gap-1.5">
              {skills.map((sk) => (
                <button
                  key={sk.id}
                  type="button"
                  onClick={() => toggle(skillIds, sk.id, setSkillIds)}
                  className={`pill ${skillIds.includes(sk.id) ? "is-active" : ""}`}
                >
                  {sk.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="mb-3 flex items-center justify-between text-sm text-muted">
        <span>{total} ta savol topildi</span>
        <div className="flex items-center gap-2">
          <span>Sahifada:</span>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
            className="rounded-lg border border-white/15 bg-white/[0.05] px-2 py-1 text-ivory"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <p className="text-muted">Yuklanmoqda...</p>
      ) : (
        <div className="space-y-3">
          {items.map((q) => (
            <div key={q.id} className="glass-panel flex items-start justify-between gap-4 p-4">
              <div className="min-w-0 flex-1">
                <p className="mb-1.5 line-clamp-2 text-sm font-semibold">{q.text}</p>
                <div className="flex flex-wrap gap-1.5">
                  <span className="tag bg-white/10 text-muted">{q.subject.name}</span>
                  <span className="tag tag-gold">{q.difficulty.name}</span>
                  <span className="tag tag-glow">
                    {q.focus === "ABITURIENT" ? "Abiturient" : "PMT"}
                  </span>
                  {q.themes.map((t) => (
                    <span key={t.name} className="tag border border-white/10 text-muted">
                      {t.name}
                    </span>
                  ))}
                </div>
              </div>
              {q.canEdit ? (
                <div className="flex shrink-0 gap-2">
                  <Link href={`/questions/${q.id}/edit`} className="btn-ghost !px-3 !py-1.5 text-xs">
                    Tahrirlash
                  </Link>
                  <button onClick={() => deleteQuestion(q.id)} className="btn-danger-ghost">
                    O&apos;chirish
                  </button>
                </div>
              ) : (
                <span className="shrink-0 text-xs text-muted">{q.createdBy.name}</span>
              )}
            </div>
          ))}
          {items.length === 0 && (
            <p className="text-sm text-muted">Filtrlarga mos savol topilmadi.</p>
          )}
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-5 flex items-center justify-center gap-3">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="btn-ghost !px-3 !py-1.5 text-xs disabled:opacity-30"
          >
            Oldingi
          </button>
          <span className="text-sm text-muted">
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            className="btn-ghost !px-3 !py-1.5 text-xs disabled:opacity-30"
          >
            Keyingi
          </button>
        </div>
      )}
    </div>
  );
}
