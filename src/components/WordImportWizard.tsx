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

// Rasmdan o'qilgan savol uchun (/api/questions/import-images): o'qituvchi
// o'qilgan matnni savolning asl rasmdagi bo'lagi bilan solishtiradi.
type Review = {
  number: number;
  sourceDataUri: string | null;
  notes: string[];
  uncertain: string[];
  needsReview: boolean;
};

type ParsedQuestion = {
  text: string;
  imageDataUri: string | null;
  options: string[];
  review?: Review;
};

type Draft = {
  text: string;
  imageDataUri: string | null;
  options: string[];
  correctIndex: number | null;
  themeIds: string[];
  subThemeIds: string[];
  difficultyId: string;
  focus: "ABITURIENT" | "PMT";
  skillIds: string[];
  review: Review | null;
  reviewed: boolean;
};

type Status = "pending" | "saved" | "skipped" | "error";
type Source = "word" | "images";

// Savol 4 yoki 5 variantli bo'lishi mumkin (src/lib/answer-key.ts, DECISIONS.md #29):
// qog'oz varaq testdagi eng ko'p variantli savolga qarab chiziladi.
const OPTION_COUNTS = [4, 5];

function toDraft(q: ParsedQuestion): Draft {
  const options = q.options.length ? q.options : ["", ""];
  return {
    text: q.text,
    imageDataUri: q.imageDataUri,
    options,
    correctIndex: null,
    themeIds: [],
    subThemeIds: [],
    difficultyId: "",
    focus: "ABITURIENT",
    skillIds: [],
    review: q.review ?? null,
    reviewed: false,
  };
}

async function dataUriToUploadedUrl(dataUri: string): Promise<string> {
  const res = await fetch(dataUri);
  const blob = await res.blob();
  const ext = blob.type.split("/")[1] ?? "png";
  const file = new File([blob], `imported.${ext}`, { type: blob.type });
  const fd = new FormData();
  fd.append("file", file);
  const uploadRes = await fetch("/api/upload", { method: "POST", body: fd });
  const body = await uploadRes.json();
  if (!uploadRes.ok) throw new Error(body.error ?? "Rasm yuklashda xatolik");
  return body.url as string;
}

export default function WordImportWizard({
  subjects,
  skills,
}: {
  subjects: Subject[];
  skills: Skill[];
}) {
  const router = useRouter();

  const [batchSubjectId, setBatchSubjectId] = useState("");
  const batchSubject = useMemo(
    () => subjects.find((s) => s.id === batchSubjectId),
    [subjects, batchSubjectId],
  );

  const [source, setSource] = useState<Source>("word");
  const [file, setFile] = useState<File | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [statuses, setStatuses] = useState<Status[]>([]);
  const [index, setIndex] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [duplicateOf, setDuplicateOf] = useState<string | null>(null);

  const draft = drafts?.[index] ?? null;
  const availableSubThemes = useMemo(
    () =>
      (batchSubject?.themes ?? [])
        .filter((t) => draft?.themeIds.includes(t.id))
        .flatMap((t) => t.subThemes),
    [batchSubject, draft?.themeIds],
  );

  function updateDraft(patch: Partial<Draft>) {
    if (!drafts) return;
    const next = [...drafts];
    next[index] = { ...next[index], ...patch };
    setDrafts(next);
    if ("text" in patch) setDuplicateOf(null);
  }

  function setStatus(i: number, s: Status) {
    setStatuses((prev) => {
      const next = [...prev];
      next[i] = s;
      return next;
    });
  }

  async function handleUpload() {
    if (!batchSubjectId) return;
    const fd = new FormData();
    if (source === "word") {
      if (!file) return;
      fd.append("file", file);
    } else {
      if (files.length === 0) return;
      for (const f of files) fd.append("files", f);
    }
    setParsing(true);
    setParseError(null);
    try {
      const url = source === "word" ? "/api/questions/import" : "/api/questions/import-images";
      const res = await fetch(url, { method: "POST", body: fd });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Xatolik yuz berdi");
      const parsed: ParsedQuestion[] = body.questions;
      setDrafts(parsed.map(toDraft));
      setStatuses(parsed.map(() => "pending"));
      setIndex(0);
    } catch (e) {
      setParseError((e as Error).message);
    } finally {
      setParsing(false);
    }
  }

  function toggle(list: string[], id: string, key: "themeIds" | "subThemeIds" | "skillIds") {
    updateDraft({
      [key]: list.includes(id) ? list.filter((x) => x !== id) : [...list, id],
    } as Partial<Draft>);
  }

  function goNext() {
    setDuplicateOf(null);
    setSaveError(null);
    if (drafts && index < drafts.length - 1) setIndex(index + 1);
    else setIndex((drafts?.length ?? 0));
  }

  function skip() {
    setStatus(index, "skipped");
    goNext();
  }

  async function saveCurrent(forceSave = false) {
    if (!draft) return;
    setSaveError(null);

    const cleanedOptions = draft.options.map((o) => o.trim()).filter(Boolean);
    if (!draft.text.trim()) return setSaveError("Savol matni bo'sh bo'lmasligi kerak");
    if (draft.correctIndex === null || !draft.options[draft.correctIndex]?.trim())
      return setSaveError("To'g'ri javobni belgilang");
    if (!OPTION_COUNTS.includes(cleanedOptions.length))
      return setSaveError(
        `4 yoki 5 ta variant kerak (1 to'g'ri, qolgani noto'g'ri) — hozir ${cleanedOptions.length} ta bor`,
      );
    if (draft.review?.needsReview && !draft.reviewed)
      return setSaveError("Savolni asl rasm bilan solishtiring va \"solishtirdim\" belgisini qo'ying");
    if (draft.themeIds.length === 0) return setSaveError("Kamida bitta umumiy mavzu tanlang");
    if (!draft.difficultyId) return setSaveError("Qiyinchilik darajasini tanlang");

    setSaving(true);
    try {
      if (!forceSave) {
        const dupRes = await fetch("/api/questions/check-duplicate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subjectId: batchSubjectId, text: draft.text.trim() }),
        });
        const dupBody = await dupRes.json();
        if (dupBody.exists) {
          setDuplicateOf(dupBody.existingId);
          setSaving(false);
          return;
        }
      }
      setDuplicateOf(null);

      const correctText = draft.options[draft.correctIndex!].trim();
      const wrongAnswers = draft.options
        .filter((_, i) => i !== draft.correctIndex)
        .map((o) => o.trim())
        .filter(Boolean);

      let imageUrl: string | null = null;
      if (draft.imageDataUri) {
        imageUrl = await dataUriToUploadedUrl(draft.imageDataUri);
      }

      const res = await fetch("/api/questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subjectId: batchSubjectId,
          text: draft.text.trim(),
          imageUrl,
          correctAnswer: correctText,
          wrongAnswers,
          themeIds: draft.themeIds,
          subThemeIds: draft.subThemeIds,
          difficultyId: draft.difficultyId,
          focus: draft.focus,
          skillIds: draft.skillIds,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ? JSON.stringify(body.error) : "Xatolik");
      setStatus(index, "saved");
      goNext();
    } catch (e) {
      setSaveError((e as Error).message);
      setStatus(index, "error");
    } finally {
      setSaving(false);
    }
  }

  // --- Step 0: choose the subject for the whole batch ---
  if (!batchSubjectId) {
    return (
      <div className="glass-panel space-y-4 p-6">
        <p className="text-sm text-muted">
          Avval fanni tanlang — fayldan (Word yoki rasm) chiqariladigan barcha savollarga shu fan
          belgilanadi.
        </p>
        <select
          value={batchSubjectId}
          onChange={(e) => setBatchSubjectId(e.target.value)}
          className="input-field"
        >
          <option value="">Fanni tanlang...</option>
          {subjects.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
    );
  }

  // --- Step 1: upload the docx or page images ---
  if (!drafts) {
    const ready = source === "word" ? Boolean(file) : files.length > 0;
    return (
      <div className="glass-panel space-y-4 p-6">
        <div className="flex items-center justify-between text-sm text-muted">
          <span>
            Fan: <span className="font-semibold text-ivory">{batchSubject?.name}</span>
          </span>
          <button
            type="button"
            onClick={() => setBatchSubjectId("")}
            className="text-xs text-gold hover:underline"
          >
            Fanni o&apos;zgartirish
          </button>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setSource("word")}
            className={`pill ${source === "word" ? "is-active" : ""}`}
          >
            Word (.docx)
          </button>
          <button
            type="button"
            onClick={() => setSource("images")}
            className={`pill ${source === "images" ? "is-active" : ""}`}
          >
            Test rasmi (JPEG, PNG)
          </button>
        </div>
        {source === "word" ? (
          <p className="text-sm text-muted">
            Savollar bilan tayyor Word (.docx) faylini yuklang. Fayldagi raqamlangan savollar
            (masalan &quot;1. ...&quot;) va harfli variantlar (&quot;A) ...&quot;, &quot;b)
            ...&quot; — katta yoki kichik harf farqsiz) avtomatik aniqlanadi, harflar
            o&apos;zi olib tashlanadi, rasmlar ham ko&apos;chirib olinadi. Har bir savol uchun
            keyingi qadamda mavzu va to&apos;g&apos;ri javobni o&apos;zingiz belgilaysiz.
          </p>
        ) : (
          <p className="text-sm text-muted">
            Test sahifalarining rasmlarini yuklang — bir nechta sahifa bo&apos;lsa hammasini
            birga (tartib fayl nomi bo&apos;yicha). Raqamlangan savollar (&quot;1.&quot;),
            harfli variantlar (&quot;A)&quot;) va chizmalar ajratiladi, suv belgisi tozalanadi.
            Rasmdan o&apos;qish xatosiz bo&apos;lmaydi: keyingi qadamda har savolni asl rasm
            bilan solishtirasiz.
          </p>
        )}
        <input
          key={source}
          type="file"
          accept={source === "word" ? ".docx" : "image/jpeg,image/png,image/webp"}
          multiple={source === "images"}
          onChange={(e) => {
            const list = Array.from(e.target.files ?? []);
            if (source === "word") setFile(list[0] ?? null);
            else setFiles(list);
          }}
          className="text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-ivory"
        />
        {source === "images" && files.length > 1 && (
          <p className="text-xs text-muted">{files.length} ta sahifa tanlandi</p>
        )}
        {parseError && (
          <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
            {parseError}
          </p>
        )}
        <button onClick={handleUpload} disabled={!ready || parsing} className="btn-gold">
          {parsing
            ? source === "images"
              ? "O'qilmoqda — har sahifaga bir necha soniya..."
              : "Tahlil qilinmoqda..."
            : "Yuklash va tahlil qilish"}
        </button>
      </div>
    );
  }

  // --- Step 3: done ---
  if (index >= drafts.length) {
    const saved = statuses.filter((s) => s === "saved").length;
    const skipped = statuses.filter((s) => s === "skipped").length;
    return (
      <div className="glass-panel space-y-4 p-6 text-center">
        <h2 className="font-display text-lg font-bold">Import yakunlandi</h2>
        <p className="text-sm text-muted">
          {saved} ta savol saqlandi, {skipped} ta o&apos;tkazib yuborildi ({drafts.length} tadan).
        </p>
        <div className="flex justify-center gap-3">
          <button onClick={() => router.push("/questions")} className="btn-gold">
            Savollar ro&apos;yxatiga o&apos;tish
          </button>
          <button
            onClick={() => {
              setDrafts(null);
              setStatuses([]);
              setFile(null);
              setFiles([]);
              setIndex(0);
              setBatchSubjectId("");
            }}
            className="btn-ghost"
          >
            Yana bir fayl yuklash
          </button>
        </div>
      </div>
    );
  }

  const review = draft!.review;
  const filledOptions = draft!.options.filter((o) => o.trim()).length;

  // --- Step 2: review each parsed question ---
  return (
    <div className="glass-panel space-y-5 p-6">
      <div className="flex items-center justify-between text-sm text-muted">
        <span>
          Fan: <span className="text-ivory">{batchSubject?.name}</span> &middot; Savol{" "}
          <span className="text-ivory">{index + 1}</span> / {drafts.length}
        </span>
        <span>
          Saqlangan: <span className="text-gold">{statuses.filter((s) => s === "saved").length}</span>
        </span>
      </div>

      {saveError && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {saveError}
        </p>
      )}

      {duplicateOf && (
        <div className="space-y-2 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">
          <p>
            Diqqat: bu matnli savol bazada allaqachon mavjud. Baribir saqlaysizmi yoki
            o&apos;tkazib yuborasizmi?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => saveCurrent(true)}
              className="rounded-lg border border-amber-400/40 px-3 py-1 text-xs font-semibold hover:bg-amber-400/20"
            >
              Baribir saqlash
            </button>
            <button
              type="button"
              onClick={skip}
              className="rounded-lg border border-amber-400/40 px-3 py-1 text-xs font-semibold hover:bg-amber-400/20"
            >
              O&apos;tkazib yuborish
            </button>
          </div>
        </div>
      )}

      {review && (
        <div
          className={`space-y-3 rounded-lg border px-3 py-3 text-sm ${
            review.needsReview
              ? "border-amber-400/30 bg-amber-400/10"
              : "border-white/10 bg-white/[0.03]"
          }`}
        >
          <p className="font-semibold text-ivory">Asl rasm — {review.number}-savol</p>
          {review.sourceDataUri && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={review.sourceDataUri}
              alt={`${review.number}-savolning asl rasmi`}
              className="w-full rounded-lg border border-white/10 bg-white"
            />
          )}
          {(review.notes.length > 0 || review.uncertain.length > 0) && (
            <ul className="list-disc space-y-1 pl-5 text-amber-200">
              {review.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
              {review.uncertain.length > 0 && (
                <li>Noaniq o&apos;qilgan: {review.uncertain.join(", ")}</li>
              )}
            </ul>
          )}
          {review.needsReview && (
            <label className="flex items-center gap-2 text-amber-100">
              <input
                type="checkbox"
                checked={draft!.reviewed}
                onChange={(e) => updateDraft({ reviewed: e.target.checked })}
              />
              Matn, variantlar va rasmni asl rasm bilan solishtirdim
            </label>
          )}
        </div>
      )}

      <div>
        <label className="label-field">Savol matni (imloviy xatolarni shu yerda tuzating)</label>
        <textarea
          value={draft!.text}
          onChange={(e) => updateDraft({ text: e.target.value })}
          rows={3}
          className="input-field"
        />
      </div>

      {draft!.imageDataUri && (
        <div>
          <label className="label-field">{review ? "Rasmdan kesilgan chizma" : "Worddan olingan rasm"}</label>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={draft!.imageDataUri}
            alt="Savol rasmi"
            className="max-h-40 rounded-lg border border-white/10 bg-white"
          />
          <button
            type="button"
            onClick={() => updateDraft({ imageDataUri: null })}
            className="mt-1 text-xs text-muted hover:text-red-300"
          >
            Rasmni olib tashlash
          </button>
        </div>
      )}

      <div>
        <label className="label-field">
          Variantlar — to&apos;g&apos;ri javobning ustiga bosing (4 yoki 5 ta)
        </label>
        <div className="space-y-2">
          {draft!.options.map((opt, i) => (
            <div key={i} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => updateDraft({ correctIndex: i })}
                title="To'g'ri javob sifatida belgilash"
                className={`flex h-9 w-9 flex-none items-center justify-center rounded-lg border text-sm font-bold transition ${
                  draft!.correctIndex === i
                    ? "border-gold bg-gold text-gold-ink"
                    : "border-white/15 bg-white/[0.05] text-muted hover:bg-white/[0.1]"
                }`}
              >
                ✓
              </button>
              <input
                value={opt}
                onChange={(e) => {
                  const next = [...draft!.options];
                  next[i] = e.target.value;
                  updateDraft({ options: next });
                }}
                className="input-field flex-1"
              />
              <button
                type="button"
                onClick={() => {
                  const next = draft!.options.filter((_, idx) => idx !== i);
                  const correctIndex =
                    draft!.correctIndex === null
                      ? null
                      : draft!.correctIndex === i
                        ? null
                        : draft!.correctIndex > i
                          ? draft!.correctIndex - 1
                          : draft!.correctIndex;
                  updateDraft({ options: next, correctIndex });
                }}
                className="rounded-lg border border-white/15 px-3 text-sm text-muted hover:bg-white/[0.08]"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => updateDraft({ options: [...draft!.options, ""] })}
          className="mt-2 text-sm font-semibold text-gold hover:underline"
        >
          + Variant qo&apos;shish
        </button>
        {filledOptions === 4 && (
          <p className="mt-1 text-xs text-muted">
            4 variantli savol ham testga tushadi: qog&apos;oz javob varag&apos;ida variantlar
            A&ndash;D bo&apos;lib chiqadi.
          </p>
        )}
      </div>

      <div>
        <label className="label-field">Umumiy mavzu(lar)</label>
        <div className="flex flex-wrap gap-2">
          {(batchSubject?.themes ?? []).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => toggle(draft!.themeIds, t.id, "themeIds")}
              className={`pill ${draft!.themeIds.includes(t.id) ? "is-active" : ""}`}
            >
              {t.name}
            </button>
          ))}
          {!batchSubject?.themes.length && (
            <p className="text-sm text-muted">Bu fanda mavzular yo&apos;q.</p>
          )}
        </div>
      </div>

      {availableSubThemes.length > 0 && (
        <div>
          <label className="label-field">Ichki mavzu(lar) (ixtiyoriy)</label>
          <div className="flex flex-wrap gap-2">
            {availableSubThemes.map((st) => (
              <button
                key={st.id}
                type="button"
                onClick={() => toggle(draft!.subThemeIds, st.id, "subThemeIds")}
                className={`pill ${draft!.subThemeIds.includes(st.id) ? "is-active" : ""}`}
              >
                {st.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <label className="label-field">Qiyinchilik darajasi</label>
        <select
          value={draft!.difficultyId}
          onChange={(e) => updateDraft({ difficultyId: e.target.value })}
          className="input-field"
        >
          <option value="">Tanlang...</option>
          {(batchSubject?.difficultyLevels ?? [])
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
        <label className="label-field">Focus</label>
        <div className="flex gap-2">
          {(["ABITURIENT", "PMT"] as const).map((f) => (
            <button
              type="button"
              key={f}
              onClick={() => updateDraft({ focus: f })}
              className={`pill ${draft!.focus === f ? "is-active" : ""}`}
            >
              {f === "ABITURIENT" ? "Abiturient" : "PMT"}
            </button>
          ))}
        </div>
      </div>

      {skills.length > 0 && (
        <div>
          <label className="label-field">Talab qilinadigan mahorat</label>
          <div className="flex flex-wrap gap-2">
            {skills.map((sk) => (
              <button
                key={sk.id}
                type="button"
                onClick={() => toggle(draft!.skillIds, sk.id, "skillIds")}
                className={`pill ${draft!.skillIds.includes(sk.id) ? "is-active" : ""}`}
              >
                {sk.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex justify-between gap-3 border-t border-white/10 pt-4">
        <button type="button" onClick={skip} className="btn-ghost">
          O&apos;tkazib yuborish
        </button>
        <button
          type="button"
          onClick={() => saveCurrent(false)}
          disabled={saving}
          className="btn-gold"
        >
          {saving ? "Saqlanmoqda..." : "Saqlash va keyingisi →"}
        </button>
      </div>
    </div>
  );
}
