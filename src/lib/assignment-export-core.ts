// Online (va offline) topshiriq natijalarini yuklab olish uchun ma'lumot
// shakli va HTML ko'rinishi (docs/DECISIONS.md #34).
//
// Bu fayl bazaga tegmaydi: qatorlarni yig'ish va HTML yasash shu yerda,
// shuning uchun ikkalasi ham testdan o'tadi (tests/assignment-export.test.ts).
// Excel esa src/lib/assignment-export.ts da.

export type ExportAnswer = {
  n: number;
  given: string;
  key: string;
  ok: boolean;
  text: string;
  themes: string[];
};

export type ExportStudent = {
  n: number;
  name: string;
  status: string;
  correct: number | null;
  total: number | null;
  percentage: number | null;
  startedAt: string | null;
  submittedAt: string | null;
  // Boshlagandan topshirgangacha, daqiqada (online testda).
  minutes: number | null;
  answers: ExportAnswer[];
  weakThemes: { name: string; correct: number; total: number }[];
};

export type ExportQuestion = {
  n: number;
  key: string;
  text: string;
  themes: string[];
  correct: number;
  answered: number;
  percentage: number | null;
};

export type ExportTheme = { name: string; correct: number; total: number; percentage: number };

export type ExportData = {
  title: string;
  subject: string;
  classroom: string;
  mode: "ONLINE" | "OFFLINE";
  createdAt: string;
  generatedAt: string;
  questionCount: number;
  summary: {
    checked: number;
    students: number;
    average: number | null;
    best: number | null;
    worst: number | null;
  };
  students: ExportStudent[];
  questions: ExportQuestion[];
  themes: ExportTheme[];
};

export function percent(correct: number, total: number): number | null {
  return total > 0 ? Math.round((correct / total) * 1000) / 10 : null;
}

// Bitta o'quvchining eng past mavzulari — HTML'da ism bosilganda shular
// ko'rinadi. Faqat kamida bitta xatosi borlari, eng pastidan boshlab.
export function weakThemesOf(answers: ExportAnswer[]): ExportStudent["weakThemes"] {
  const acc = new Map<string, { name: string; correct: number; total: number }>();
  for (const a of answers) {
    for (const name of a.themes) {
      const row = acc.get(name) ?? { name, correct: 0, total: 0 };
      row.total += 1;
      if (a.ok) row.correct += 1;
      acc.set(name, row);
    }
  }
  return [...acc.values()]
    .filter((t) => t.correct < t.total)
    .sort((a, b) => a.correct / a.total - b.correct / b.total || b.total - a.total);
}

const ESCAPE: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPE[c]);
}

function tone(p: number | null): string {
  if (p == null) return "muted";
  if (p >= 80) return "good";
  if (p >= 60) return "ok";
  return "bad";
}

function answerCell(a: ExportAnswer): string {
  const given = a.given === "" ? "—" : a.given === "*" ? "ko'p" : a.given;
  return `<span class="ans ${a.ok ? "good" : given === "—" ? "muted" : "bad"}" title="${escapeHtml(
    a.text,
  )}">${a.n}<b>${escapeHtml(given)}</b></span>`;
}

function studentDetail(s: ExportStudent): string {
  if (!s.answers.length) {
    return `<p class="muted">Bu o'quvchi testni topshirmagan — javoblar yo'q.</p>`;
  }
  const rows = s.answers
    .map(
      (a) => `<tr class="${a.ok ? "" : "wrong"}">
        <td>${a.n}</td>
        <td class="q">${escapeHtml(a.text)}</td>
        <td class="mono">${escapeHtml(a.given === "" ? "—" : a.given)}</td>
        <td class="mono">${escapeHtml(a.key)}</td>
        <td>${a.ok ? "✓" : "✗"}</td>
        <td class="muted">${escapeHtml(a.themes.join(", "))}</td>
      </tr>`,
    )
    .join("");
  const weak = s.weakThemes.length
    ? `<p class="weak">Qayta ishlash kerak: ${s.weakThemes
        .map((t) => `${escapeHtml(t.name)} (${t.correct}/${t.total})`)
        .join(" · ")}</p>`
    : `<p class="weak good">Barcha mavzular bo'yicha xatosiz.</p>`;
  const vaqt = [
    s.startedAt ? `boshlagan: ${escapeHtml(s.startedAt)}` : null,
    s.submittedAt ? `topshirgan: ${escapeHtml(s.submittedAt)}` : null,
    s.minutes != null ? `davomiyligi: ${s.minutes} daqiqa` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return `${vaqt ? `<p class="muted">${vaqt}</p>` : ""}
    ${weak}
    <div class="grid">${s.answers.map(answerCell).join("")}</div>
    <table class="detail">
      <thead><tr><th>№</th><th>Savol</th><th>Javobi</th><th>To'g'ri</th><th></th><th>Mavzu</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// Bitta faylda ochiladigan hisobot: tashqi fayl, shrift yoki internet
// kerak emas — o'qituvchi uni saqlab qo'yadi, ochadi va chop etadi.
// Ism bosilganda o'sha o'quvchining tafsiloti ochiladi/yopiladi.
export function renderResultsHtml(data: ExportData): string {
  const rows = data.students
    .map(
      (s) => `<tr class="row" data-id="s${s.n}">
        <td>${s.n}</td>
        <td><button class="name" type="button" data-target="s${s.n}">${escapeHtml(s.name)}</button></td>
        <td>${escapeHtml(s.status)}</td>
        <td class="mono">${s.correct == null ? "—" : `${s.correct}/${s.total}`}</td>
        <td class="${tone(s.percentage)} mono">${s.percentage == null ? "—" : `${s.percentage}%`}</td>
        <td class="muted">${escapeHtml(s.submittedAt ?? "—")}</td>
      </tr>
      <tr class="detail-row" id="s${s.n}" hidden><td colspan="6">${studentDetail(s)}</td></tr>`,
    )
    .join("");

  const questions = data.questions
    .map(
      (q) => `<tr class="${q.percentage != null && q.percentage < 50 ? "wrong" : ""}">
        <td>${q.n}</td>
        <td class="q">${escapeHtml(q.text)}</td>
        <td class="mono">${escapeHtml(q.key)}</td>
        <td class="mono">${q.percentage == null ? "—" : `${q.percentage}%`}</td>
        <td class="mono">${q.correct}/${q.answered}</td>
        <td class="muted">${escapeHtml(q.themes.join(", "))}</td>
      </tr>`,
    )
    .join("");

  const themes = data.themes
    .map(
      (t) => `<tr><td>${escapeHtml(t.name)}</td><td class="mono">${t.correct}/${t.total}</td>
        <td class="${tone(t.percentage)} mono">${t.percentage}%</td>
        <td class="bar"><i style="width:${t.percentage}%"></i></td></tr>`,
    )
    .join("");

  const cards = [
    ["Topshirgan", `${data.summary.checked}/${data.summary.students}`],
    ["O'rtacha", data.summary.average == null ? "—" : `${data.summary.average}%`],
    ["Eng yuqori", data.summary.best == null ? "—" : `${data.summary.best}%`],
    ["Eng past", data.summary.worst == null ? "—" : `${data.summary.worst}%`],
  ]
    .map(([label, value]) => `<div class="card"><span>${label}</span><b>${value}</b></div>`)
    .join("");

  return `<!doctype html>
<html lang="uz">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(data.title)} — natijalar</title>
<style>
  :root { color-scheme: light; --line: #e5e7eb; --muted: #6b7280; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 24px; background: #f6f7f9; color: #111827;
         font: 14px/1.5 system-ui, "Segoe UI", Roboto, sans-serif; }
  .wrap { max-width: 1040px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 28px 0 10px; }
  .sub { color: var(--muted); margin: 0 0 18px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .card { background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
  .card span { display: block; color: var(--muted); font-size: 12px; }
  .card b { font-size: 20px; }
  table { width: 100%; border-collapse: collapse; background: #fff;
          border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { background: #f3f4f6; font-size: 12px; color: #374151; }
  tr:last-child td { border-bottom: 0; }
  .mono { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .muted { color: var(--muted); }
  .good { color: #047857; } .ok { color: #b45309; } .bad { color: #b91c1c; }
  tr.wrong td { background: #fef2f2; }
  .name { background: none; border: 0; padding: 0; font: inherit; color: #1d4ed8;
          cursor: pointer; text-align: left; text-decoration: underline; }
  .name:hover { color: #1e40af; }
  .detail-row td { background: #fafafa; }
  .grid { display: flex; flex-wrap: wrap; gap: 4px; margin: 10px 0; }
  .ans { display: inline-flex; gap: 4px; align-items: baseline; border: 1px solid var(--line);
         border-radius: 6px; padding: 2px 6px; font-size: 12px; background: #fff; }
  .ans.good { border-color: #a7f3d0; background: #ecfdf5; }
  .ans.bad { border-color: #fecaca; background: #fef2f2; }
  .ans b { font-weight: 700; }
  table.detail { margin-top: 8px; }
  table.detail .q { max-width: 420px; }
  .weak { margin: 6px 0; }
  .bar { width: 160px; } .bar i { display: block; height: 8px; border-radius: 4px; background: #2563eb; }
  footer { color: var(--muted); font-size: 12px; margin-top: 28px; }
  @media print { body { background: #fff; padding: 0; } .detail-row { display: table-row !important; } }
</style>
<div class="wrap">
  <h1>${escapeHtml(data.title)}</h1>
  <p class="sub">${escapeHtml(data.classroom)} · ${escapeHtml(data.subject)} ·
     ${data.mode === "ONLINE" ? "online" : "qog'ozda"} · ${data.questionCount} savol ·
     ${escapeHtml(data.createdAt)}</p>
  <div class="cards">${cards}</div>

  <h2>Natijalar</h2>
  <p class="muted">Ism ustiga bosing — o'sha o'quvchining har bir javobi, vaqti va
     qayta ishlash kerak bo'lgan mavzulari ochiladi.</p>
  <table>
    <thead><tr><th>№</th><th>O'quvchi</th><th>Holat</th><th>To'g'ri</th><th>Foiz</th><th>Topshirgan</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>

  <h2>Savollar bo'yicha</h2>
  <table>
    <thead><tr><th>№</th><th>Savol</th><th>Kalit</th><th>To'g'ri (%)</th><th>Nechta</th><th>Mavzu</th></tr></thead>
    <tbody>${questions}</tbody>
  </table>

  ${
    data.themes.length
      ? `<h2>Mavzular bo'yicha</h2>
  <table>
    <thead><tr><th>Mavzu</th><th>To'g'ri</th><th>Foiz</th><th></th></tr></thead>
    <tbody>${themes}</tbody>
  </table>`
      : ""
  }

  <footer>SmartAcademy · ${escapeHtml(data.generatedAt)} da tayyorlandi</footer>
</div>
<script>
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".name");
    if (!btn) return;
    var row = document.getElementById(btn.dataset.target);
    if (row) row.hidden = !row.hidden;
  });
</script>
</html>`;
}
