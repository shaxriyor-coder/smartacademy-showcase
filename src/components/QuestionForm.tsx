"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

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

export type QuestionInitialData = {
  id: string;
  subjectId: string;
  text: string;
  imageUrl: string | null;
  correctAnswer: string;
  wrongAnswers: string[];
  themes: { id: string }[];
  subThemes: { id: string }[];
  difficultyId: string;
  focus: "ABITURIENT" | "PMT";
  skills: { id: string }[];
};

const STEP_LABEL =
  "mb-1.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted";
const STEP_NUM =
  "flex h-5 w-5 items-center justify-center rounded-full bg-gold/20 text-[10px] font-bold text-gold";

// Savol 4 yoki 5 variantli (src/lib/answer-key.ts, validation.ts).
const MIN_WRONG = 3;
const MAX_WRONG = 4;

export default function QuestionForm({
  subjects,
  skills,
  initialData,
}: {
  subjects: Subject[];
  skills: Skill[];
  initialData?: QuestionInitialData;
}) {
  const router = useRouter();
  const isEdit = Boolean(initialData);

  const [subjectId, setSubjectId] = useState(initialData?.subjectId ?? subjects[0]?.id ?? "");
  const [text, setText] = useState(initialData?.text ?? "");
  const [imageUrl, setImageUrl] = useState<string | null>(initialData?.imageUrl ?? null);
  const [uploading, setUploading] = useState(false);
  const [correctAnswer, setCorrectAnswer] = useState(initialData?.correctAnswer ?? "");
  const [wrongAnswers, setWrongAnswers] = useState<string[]>(() => {
    const initial = initialData?.wrongAnswers ?? [];
    if (initial.length >= MIN_WRONG) return initial.slice(0, MAX_WRONG);
    return Array.from({ length: MAX_WRONG }, (_, i) => initial[i] ?? "");
  });
  const [themeIds, setThemeIds] = useState<string[]>(
    initialData?.themes.map((t) => t.id) ?? [],
  );
  const [subThemeIds, setSubThemeIds] = useState<string[]>(
    initialData?.subThemes.map((t) => t.id) ?? [],
  );
  const [difficultyId, setDifficultyId] = useState(initialData?.difficultyId ?? "");
  const [focus, setFocus] = useState<"ABITURIENT" | "PMT">(initialData?.focus ?? "ABITURIENT");
  const [skillIds, setSkillIds] = useState<string[]>(
    initialData?.skills.map((s) => s.id) ?? [],
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const subject = useMemo(() => subjects.find((s) => s.id === subjectId), [subjects, subjectId]);
  const availableSubThemes = useMemo(
    () =>
      (subject?.themes ?? []).filter((t) => themeIds.includes(t.id)).flatMap((t) => t.subThemes),
    [subject, themeIds],
  );

  function toggle(list: string[], id: string, setter: (v: string[]) => void) {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  }

  async function handleImageChange(file: File | null) {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: fd });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Rasm yuklashda xatolik");
      setImageUrl(body.url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const cleanedWrong = wrongAnswers.map((w) => w.trim()).filter(Boolean);
    if (!subjectId) return setError("Fan tanlanishi shart");
    if (!text.trim()) return setError("Savol matni majburiy");
    if (!correctAnswer.trim()) return setError("To'g'ri javob majburiy");
    if (cleanedWrong.length < MIN_WRONG || cleanedWrong.length > MAX_WRONG)
      return setError(
        `${MIN_WRONG} yoki ${MAX_WRONG} ta noto'g'ri javob kerak (savol ${MIN_WRONG + 1} yoki ` +
          `${MAX_WRONG + 1} variantli bo'ladi) — hozir ${cleanedWrong.length} ta to'ldirilgan`,
      );
    if (themeIds.length === 0) return setError("Kamida bitta umumiy mavzu tanlanishi kerak");
    if (!difficultyId) return setError("Qiyinlik darajasi tanlanishi shart");

    const payload = {
      subjectId,
      text,
      imageUrl,
      correctAnswer,
      wrongAnswers: cleanedWrong,
      themeIds,
      subThemeIds,
      difficultyId,
      focus,
      skillIds,
    };

    setSaving(true);
    try {
      const res = await fetch(isEdit ? `/api/questions/${initialData!.id}` : "/api/questions", {
        method: isEdit ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ? JSON.stringify(body.error) : "Xatolik yuz berdi");
      router.push("/questions");
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="glass-panel space-y-6 p-6">
      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>1</span> Fan
        </label>
        <select
          value={subjectId}
          onChange={(e) => {
            setSubjectId(e.target.value);
            setThemeIds([]);
            setSubThemeIds([]);
            setDifficultyId("");
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
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>2</span> Savol matni / misol
        </label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          className="input-field"
        />
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>3</span> Savol rasmi (ixtiyoriy)
        </label>
        <input
          type="file"
          accept="image/*"
          onChange={(e) => handleImageChange(e.target.files?.[0] ?? null)}
          className="text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-ivory"
        />
        {uploading && <p className="mt-1 text-xs text-muted">Yuklanmoqda...</p>}
        {imageUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={imageUrl} alt="Savol rasmi" className="mt-2 max-h-40 rounded-lg border border-white/10" />
        )}
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>4</span> To&apos;g&apos;ri javob
        </label>
        <input
          value={correctAnswer}
          onChange={(e) => setCorrectAnswer(e.target.value)}
          className="input-field"
        />
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>5</span> Noto&apos;g&apos;ri javoblar ({MIN_WRONG} yoki{" "}
          {MAX_WRONG} ta)
        </label>
        <div className="space-y-2">
          {wrongAnswers.map((w, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                value={w}
                placeholder={`${i + 1}-noto'g'ri javob`}
                onChange={(e) => {
                  const next = [...wrongAnswers];
                  next[i] = e.target.value;
                  setWrongAnswers(next);
                }}
                className="input-field flex-1"
              />
              {wrongAnswers.length > MIN_WRONG && (
                <button
                  type="button"
                  onClick={() => setWrongAnswers(wrongAnswers.filter((_, idx) => idx !== i))}
                  className="rounded-lg border border-white/15 px-3 text-sm text-muted hover:bg-white/[0.08]"
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
        {wrongAnswers.length < MAX_WRONG && (
          <button
            type="button"
            onClick={() => setWrongAnswers([...wrongAnswers, ""])}
            className="mt-2 text-sm font-semibold text-gold hover:underline"
          >
            + Noto&apos;g&apos;ri javob qo&apos;shish
          </button>
        )}
        <p className="mt-1 text-xs text-muted">
          Savol {MIN_WRONG + 1} yoki {MAX_WRONG + 1} variantli bo&apos;lishi mumkin: 4 variantli
          savolda javob varag&apos;i A&ndash;D bo&apos;lib chiqadi.
        </p>
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>6</span> Umumiy mavzu(lar) (bir nechtasini tanlash mumkin)
        </label>
        <div className="flex flex-wrap gap-2">
          {(subject?.themes ?? []).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => toggle(themeIds, t.id, setThemeIds)}
              className={`pill ${themeIds.includes(t.id) ? "is-active" : ""}`}
            >
              {t.name}
            </button>
          ))}
          {!subject?.themes.length && <p className="text-sm text-muted">Avval fan tanlang.</p>}
        </div>
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>6a</span> Ichki mavzu(lar) (ixtiyoriy)
        </label>
        <div className="flex flex-wrap gap-2">
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
          {!availableSubThemes.length && (
            <p className="text-sm text-muted">Ichki mavzu yo&apos;q.</p>
          )}
        </div>
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>7</span> Qiyinchilik darajasi
        </label>
        <select
          value={difficultyId}
          onChange={(e) => setDifficultyId(e.target.value)}
          className="input-field"
        >
          <option value="">Tanlang...</option>
          {(subject?.difficultyLevels ?? [])
            .slice()
            .sort((a, b) => a.order - b.order)
            .map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
        </select>
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>8</span> Focus
        </label>
        <div className="flex gap-2">
          {(["ABITURIENT", "PMT"] as const).map((f) => (
            <button
              type="button"
              key={f}
              onClick={() => setFocus(f)}
              className={`pill ${focus === f ? "is-active" : ""}`}
            >
              {f === "ABITURIENT" ? "Abiturient" : "PMT"}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className={STEP_LABEL}>
          <span className={STEP_NUM}>9</span> Talab qilinadigan mahorat
        </label>
        <div className="flex flex-wrap gap-2">
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
          {skills.length === 0 && <p className="text-sm text-muted">Mahorat teglari yo&apos;q.</p>}
        </div>
      </div>

      <button type="submit" disabled={saving || uploading} className="btn-gold">
        {saving ? "Saqlanmoqda..." : isEdit ? "Saqlash" : "Savolni qo'shish"}
      </button>
    </form>
  );
}
