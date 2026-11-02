"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

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
  subject: { name: string };
  difficulty: { name: string };
  focus: "ABITURIENT" | "PMT";
  olympiadUsage: { olympiadName: string; testTitle: string }[];
};

// /api/olympiads — smartbot bazasidagi olimpiadalar (faqat o'qish).
type BotOlympiad = {
  id: number;
  name: string;
  code: string | null;
  examDate: string | null;
  isActive: boolean;
};

const PAGE_SIZES = [15, 30, 50, 100];

export default function NewTestPage() {
  // Only teachers have classrooms to assign the new test to.
  const [canAssign, setCanAssign] = useState(false);
  useEffect(() => {
    fetch("/api/auth/session")
      .then((r) => r.json())
      .then((session) => setCanAssign(session?.user?.role === "TEACHER"))
      .catch(() => {});
  }, []);
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdTestId, setCreatedTestId] = useState<string | null>(null);
  const [isOlympiad, setIsOlympiad] = useState(false);
  // Olimpiadalar smartbot'da yaratiladi, bu yerda faqat tanlanadi (#31).
  const [olympiads, setOlympiads] = useState<BotOlympiad[]>([]);
  const [olympiadId, setOlympiadId] = useState<number | null>(null);
  const [olympiadsProblem, setOlympiadsProblem] = useState<string | null>("Olimpiadalar yuklanmoqda...");
  const olympiadName = olympiads.find((o) => o.id === olympiadId)?.name ?? "";

  useEffect(() => {
    fetch("/api/olympiads")
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error ?? "Xatolik");
        return body as { configured: boolean; olympiads: BotOlympiad[] };
      })
      .then((body) => {
        setOlympiads(body.olympiads);
        setOlympiadsProblem(
          !body.configured
            ? "Bot bazasi ulanmagan — .env dagi SMARTBOT_* sozlamalarini tekshiring."
            : body.olympiads.length === 0
              ? "Botda hali olimpiada yaratilmagan — avval botda yarating."
              : null,
        );
      })
      .catch((e) => setOlympiadsProblem(`Olimpiadalar ro'yxati o'qilmadi: ${(e as Error).message}`));
  }, []);

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

  useEffect(() => {
    if (!subjectId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate reset when filter clears
      setItems([]);
      setTotal(0);
      setTotalPages(1);
      return;
    }
    setLoading(true);
    setError(null);
    const sp = new URLSearchParams();
    sp.set("subjectId", subjectId);
    if (themeIds.length) sp.set("themeIds", themeIds.join(","));
    if (subThemeIds.length) sp.set("subThemeIds", subThemeIds.join(","));
    if (difficultyId) sp.set("difficultyId", difficultyId);
    if (focus) sp.set("focus", focus);
    if (skillIds.length) sp.set("skillIds", skillIds.join(","));
    if (dateFrom) sp.set("dateFrom", dateFrom);
    if (dateTo) sp.set("dateTo", dateTo);
    sp.set("page", String(page));
    sp.set("pageSize", String(pageSize));

    fetch(`/api/questions?${sp.toString()}`)
      .then((r) => r.json())
      .then((body) => {
        setItems(body.items);
        setTotal(body.total);
        setTotalPages(body.totalPages);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [subjectId, themeIds, subThemeIds, difficultyId, focus, skillIds, dateFrom, dateTo, page, pageSize]);

  function toggleFilter(list: string[], id: string, setter: (v: string[]) => void) {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
    setPage(1);
  }

  function toggleSelected(id: string) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function createTest() {
    if (!subjectId) return setError("Avval fan tanlang");
    if (isOlympiad && !olympiadId) return setError("Olimpiadani ro'yxatdan tanlang");
    if (!isOlympiad && !title.trim()) return setError("Test nomini kiriting");
    if (selected.length === 0) return setError("Kamida bitta savol tanlang");

    const effectiveTitle = isOlympiad ? olympiadName : title.trim();

    setCreating(true);
    setError(null);
    try {
      const res = await fetch("/api/tests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: effectiveTitle,
          subjectId,
          questionIds: selected,
          isOlympiad,
          smartbotOlympiadId: isOlympiad ? olympiadId : undefined,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ? JSON.stringify(body.error) : "Xatolik");
      setTitle(effectiveTitle);
      setCreatedTestId(body.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  if (createdTestId) {
    return (
      <div className="glass-panel mx-auto max-w-lg p-8 text-center">
        <h1 className="mb-2 font-display text-xl font-bold">Test tayyor!</h1>
        <p className="mb-6 text-sm text-muted">
          &quot;{title}&quot; nomli test {selected.length} ta savol bilan yaratildi.
          {isOlympiad && olympiadName && (
            <>
              {" "}
              (<span className="text-gold">{olympiadName}</span> olimpiadasi uchun)
            </>
          )}
        </p>
        <div className="flex flex-col gap-3">
          <a href={`/api/tests/${createdTestId}/export`} className="btn-gold">
            Testni yuklab olish (Word)
          </a>
          {canAssign && (
            <Link href="/classrooms" className="btn-ghost">
              Guruhga biriktirish (javob varaqlari shu yerda)
            </Link>
          )}
          <button
            onClick={() => {
              setCreatedTestId(null);
              setSelected([]);
              setTitle("");
              setIsOlympiad(false);
              setOlympiadId(null);
            }}
            className="mt-2 text-sm text-muted hover:text-ivory hover:underline"
          >
            Yangi test tayyorlash
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-bold">Test tayyorlash</h1>
        {canAssign && (
          <Link href="/tests/suggest" className="btn-ghost !px-3 !py-1.5 text-xs">
            ✨ O&apos;quvchiga qarab avtomatik test
          </Link>
        )}
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="glass-panel mb-6 p-4">
        <label className="label-field">Bu test olimpiada uchunmi?</label>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setIsOlympiad(false)}
            className={`pill ${!isOlympiad ? "is-active" : ""}`}
          >
            Yo&apos;q, oddiy test
          </button>
          <button
            type="button"
            onClick={() => setIsOlympiad(true)}
            className={`pill ${isOlympiad ? "is-active" : ""}`}
          >
            Ha, olimpiada uchun
          </button>
          {isOlympiad &&
            (olympiads.length > 0 ? (
              <select
                value={olympiadId ?? ""}
                onChange={(e) => setOlympiadId(e.target.value ? Number(e.target.value) : null)}
                aria-label="Olimpiada"
                className="input-field min-w-[280px] flex-1"
              >
                <option value="">Botdagi olimpiadani tanlang...</option>
                {olympiads.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                    {o.examDate ? ` — ${o.examDate}` : ""}
                    {o.isActive ? "" : " (yopiq)"}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-sm text-muted">{olympiadsProblem}</span>
            ))}
        </div>
        {isOlympiad && (
          <p className="mt-2 text-xs text-muted">
            Olimpiadalar smartbot&apos;da yaratiladi — bu yerda faqat tanlanadi, test o&apos;sha nom
            bilan saqlanadi. Quyidagi savollar ro&apos;yxatida bu savol avval qaysi olimpiadada
            ishlatilgani ko&apos;rsatiladi — bir xil savolni qayta tanlamaslik uchun shunga qarab
            tanlang.
          </p>
        )}
      </div>

      <div className="glass-panel mb-6 grid grid-cols-1 gap-4 p-4 md:grid-cols-4">
        <div>
          <label className="label-field">Fan (majburiy)</label>
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
            <option value="">Tanlang...</option>
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
            disabled={!subject}
            className="input-field"
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

        {subject && subject.themes.length > 0 && (
          <div className="md:col-span-2">
            <label className="label-field">Mavzu</label>
            <div className="flex flex-wrap gap-1.5">
              {subject.themes.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => toggleFilter(themeIds, t.id, setThemeIds)}
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
                  onClick={() => toggleFilter(subThemeIds, st.id, setSubThemeIds)}
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
                  onClick={() => toggleFilter(skillIds, sk.id, setSkillIds)}
                  className={`pill ${skillIds.includes(sk.id) ? "is-active" : ""}`}
                >
                  {sk.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {!subjectId ? (
        <p className="text-sm text-muted">Savollarni ko&apos;rish uchun avval fanni tanlang.</p>
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between text-sm text-muted">
            <span>
              {total} ta savol topildi &middot; <span className="text-gold">{selected.length} ta tanlangan</span>
            </span>
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
            <div className="space-y-2">
              {items.map((q) => {
                const usedInOlympiads = isOlympiad ? q.olympiadUsage : [];
                const alreadyUsed = usedInOlympiads.length > 0;
                return (
                  <label
                    key={q.id}
                    className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-3.5 transition ${
                      selected.includes(q.id)
                        ? "border-gold/50 bg-gold/[0.08]"
                        : alreadyUsed
                          ? "border-red-400/30 bg-red-400/[0.06] hover:bg-red-400/[0.1]"
                          : "border-white/10 bg-white/[0.04] hover:bg-white/[0.07]"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(q.id)}
                      onChange={() => toggleSelected(q.id)}
                      className="mt-1 accent-[#F2B035]"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm">{q.text}</p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        <span className="tag tag-gold">{q.difficulty.name}</span>
                        <span className="tag tag-glow">
                          {q.focus === "ABITURIENT" ? "Abiturient" : "PMT"}
                        </span>
                        {alreadyUsed && (
                          <span className="tag bg-red-400/20 text-red-300">
                            ⚠ Oldin ishlatilgan:{" "}
                            {usedInOlympiads.map((u) => u.olympiadName).join(", ")}
                          </span>
                        )}
                      </div>
                    </div>
                  </label>
                );
              })}
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

          <div className="glass-panel-strong sticky bottom-4 mt-8 flex flex-wrap items-center gap-3 p-4">
            {isOlympiad ? (
              <p className="flex-1 text-sm text-muted">
                Test nomi sifatida olimpiada nomi ishlatiladi:{" "}
                <span className="font-semibold text-ivory">
                  {olympiadName.trim() || "—"}
                </span>
              </p>
            ) : (
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Test nomi"
                className="input-field flex-1"
              />
            )}
            <button
              onClick={createTest}
              disabled={creating || selected.length === 0}
              className="btn-gold"
            >
              {creating ? "Yaratilmoqda..." : `Testni yaratish (${selected.length})`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
