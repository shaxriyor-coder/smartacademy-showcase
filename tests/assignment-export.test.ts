import { test } from "node:test";
import assert from "node:assert/strict";
import {
  escapeHtml,
  percent,
  renderResultsHtml,
  weakThemesOf,
  type ExportAnswer,
  type ExportData,
} from "../src/lib/assignment-export-core";

const answer = (n: number, ok: boolean, themes: string[], given = ok ? "A" : "B"): ExportAnswer => ({
  n,
  given,
  key: "A",
  ok,
  text: `${n}-savol matni`,
  themes,
});

function data(): ExportData {
  const answers = [
    answer(1, true, ["Present simple"]),
    answer(2, false, ["Present simple", "Articles"]),
    answer(3, false, ["Articles"], ""),
  ];
  return {
    title: "Grammar Time 2 — Unit 3",
    subject: "Ingliz tili",
    classroom: "smart-51",
    mode: "ONLINE",
    createdAt: "12.10.2026 14:00",
    generatedAt: "20.10.2026 09:00",
    questionCount: 3,
    summary: { checked: 1, students: 2, average: 33.3, best: 33.3, worst: 33.3 },
    students: [
      {
        n: 1,
        name: "Valiyev Ali",
        status: "topshirgan",
        correct: 1,
        total: 3,
        percentage: 33.3,
        startedAt: "12.10.2026 14:05",
        submittedAt: "12.10.2026 14:21",
        minutes: 16,
        answers,
        weakThemes: weakThemesOf(answers),
      },
      {
        n: 2,
        name: "Karimova <Malika>",
        status: "topshirmadi",
        correct: null,
        total: null,
        percentage: null,
        startedAt: null,
        submittedAt: null,
        minutes: null,
        answers: [],
        weakThemes: [],
      },
    ],
    questions: [
      { n: 1, key: "A", text: "1-savol matni", themes: ["Present simple"], correct: 1, answered: 1, percentage: 100 },
      { n: 2, key: "A", text: "2-savol matni", themes: ["Present simple", "Articles"], correct: 0, answered: 1, percentage: 0 },
      { n: 3, key: "A", text: "3-savol matni", themes: ["Articles"], correct: 0, answered: 1, percentage: 0 },
    ],
    themes: [
      { name: "Articles", correct: 0, total: 2, percentage: 0 },
      { name: "Present simple", correct: 1, total: 2, percentage: 50 },
    ],
  };
}

test("percentage is rounded to one decimal, and empty totals give nothing", () => {
  assert.equal(percent(1, 3), 33.3);
  assert.equal(percent(3, 3), 100);
  assert.equal(percent(0, 0), null);
});

test("a student's weak topics are the ones they got wrong, worst first", () => {
  const weak = weakThemesOf([
    answer(1, true, ["Present simple"]),
    answer(2, false, ["Present simple", "Articles"]),
    answer(3, false, ["Articles"]),
  ]);
  assert.deepEqual(weak, [
    { name: "Articles", correct: 0, total: 2 },
    { name: "Present simple", correct: 1, total: 2 },
  ]);
});

test("a topic answered correctly every time is not listed as weak", () => {
  assert.deepEqual(weakThemesOf([answer(1, true, ["Articles"])]), []);
});

test("names and question text are escaped, so a stray < cannot break the page", () => {
  assert.equal(escapeHtml(`<b>"x" & 'y'</b>`), "&lt;b&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/b&gt;");
  const html = renderResultsHtml(data());
  assert.ok(html.includes("Karimova &lt;Malika&gt;"));
  assert.ok(!html.includes("Karimova <Malika>"));
});

test("the report opens on its own: one file, no external script or style", () => {
  const html = renderResultsHtml(data());
  assert.ok(html.startsWith("<!doctype html>"));
  assert.ok(!/<(script|link)[^>]+(src|href)=/i.test(html));
});

test("every student is a row, and clicking the name opens their own detail", () => {
  const html = renderResultsHtml(data());
  assert.ok(html.includes(`data-target="s1"`));
  assert.ok(html.includes(`id="s1"`));
  assert.ok(html.includes(`data-target="s2"`));
  // Javoblari har bir savol uchun, to'g'ri javob bilan yonma-yon
  assert.ok(html.includes("1-savol matni"));
  assert.ok(html.includes("Qayta ishlash kerak:"));
  assert.ok(html.includes("16 daqiqa"));
  // Topshirmagan o'quvchida javob yo'qligi aytiladi
  assert.ok(html.includes("testni topshirmagan"));
});

test("the summary, question table and topic table all make it in", () => {
  const html = renderResultsHtml(data());
  assert.ok(html.includes("Grammar Time 2 — Unit 3"));
  assert.ok(html.includes("smart-51"));
  assert.ok(html.includes("33.3%"));
  assert.ok(html.includes("Savollar bo&#39;yicha") || html.includes("Savollar bo'yicha"));
  assert.ok(html.includes("Mavzular bo'yicha"));
  assert.ok(html.includes("Articles"));
});

test("with no topics tagged, the topic table is left out instead of empty", () => {
  const html = renderResultsHtml({ ...data(), themes: [] });
  assert.ok(!html.includes("Mavzular bo'yicha"));
});
