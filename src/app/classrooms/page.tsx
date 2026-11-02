"use client";

import { useEffect, useState, FormEvent } from "react";
import Link from "next/link";
import { useDialog } from "@/components/DialogProvider";

type Subject = { id: string; name: string };
type Classroom = {
  id: string;
  name: string;
  subject: Subject | null;
  teacher: { name: string };
  _count: { members: number };
  createdAt: string;
};

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

export default function ClassroomsPage() {
  const dialog = useDialog();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [c, s] = await Promise.all([
        jsonFetch<Classroom[]>("/api/classrooms"),
        jsonFetch<Subject[]>("/api/subjects"),
      ]);
      setClassrooms(c);
      setSubjects(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deliberate fetch-on-mount
    load();
  }, []);

  async function addClassroom(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const name = (data.get("name") as string)?.trim();
    const subjectId = (data.get("subjectId") as string) || null;
    if (!name) return;
    setError(null);
    try {
      await jsonFetch("/api/classrooms", {
        method: "POST",
        body: JSON.stringify({ name, subjectId }),
      });
      form.reset();
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function archiveClassroom(id: string) {
    if (!(await dialog.confirm("Guruhni arxivlaysizmi? O'quvchilar ro'yxati saqlanib qoladi, lekin ro'yxatda ko'rinmay qoladi."))) return;
    setError(null);
    try {
      await jsonFetch(`/api/classrooms/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (loading) return <p className="text-muted">Yuklanmoqda...</p>;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-bold">Guruhlarim</h1>

      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-400/10 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <section className="glass-panel p-5">
        <h2 className="mb-4 font-display text-base font-bold">Yangi guruh</h2>
        <form onSubmit={addClassroom} className="flex flex-wrap gap-2">
          <input
            name="name"
            placeholder="Guruh nomi (masalan: 8-A, Matematika)"
            required
            className="input-field min-w-[220px] flex-1"
          />
          <select name="subjectId" className="input-field w-auto">
            <option value="">Fan tanlanmagan (umumiy)</option>
            {subjects.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <button className="btn-gold">Yaratish</button>
        </form>
      </section>

      <div className="space-y-2">
        {classrooms.map((c) => (
          <div
            key={c.id}
            className="glass-panel flex flex-wrap items-center justify-between gap-3 p-4"
          >
            <div>
              <div className="flex items-center gap-2">
                <Link href={`/classrooms/${c.id}`} className="font-semibold hover:underline">
                  {c.name}
                </Link>
                {c.subject && <span className="tag tag-gold">{c.subject.name}</span>}
              </div>
              <p className="text-xs text-muted">
                {c._count.members} ta o&apos;quvchi &middot; {c.teacher.name}
              </p>
            </div>
            <div className="flex gap-2">
              <Link href={`/classrooms/${c.id}`} className="btn-ghost !px-3 !py-1.5 text-xs">
                Boshqarish
              </Link>
              <button onClick={() => archiveClassroom(c.id)} className="btn-danger-ghost">
                Arxivlash
              </button>
            </div>
          </div>
        ))}
        {classrooms.length === 0 && (
          <p className="text-sm text-muted">Hozircha guruhlar yo&apos;q.</p>
        )}
      </div>
    </div>
  );
}
