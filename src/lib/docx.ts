import { readFile } from "fs/promises";
import path from "path";
import { imageSize, disableTypes } from "image-size";
import {
  Document,
  Packer,
  Paragraph,
  Tab,
  TabStopType,
  TextRun,
  ImageRun,
  HeadingLevel,
} from "docx";
import { seededShuffle } from "./shuffle";

// image-size has known DoS bugs (infinite loops, GHSA-w3rx-r6r6-pgpr /
// GHSA-5p2g-fcmc-qvqq) in its icns/jxl/heif parsers, with no fix released
// as of this writing. Since those loops are synchronous, a timeout can't
// interrupt them — the only real mitigation is never letting those parsers
// run at all. We only ever need the handful of formats our own upload
// endpoint accepts, so disable everything else at module load.
disableTypes([
  "cur",
  "dds",
  "heif",
  "icns",
  "ico",
  "j2c",
  "jp2",
  "jxl",
  "jxl-stream",
  "ktx",
  "pnm",
  "psd",
  "svg",
  "tga",
  "tiff",
]);

const LETTERS = ["A", "B", "C", "D", "E"];

type DocxImageType = "png" | "jpg" | "gif" | "bmp";

const SUPPORTED_IMAGE_TYPES: Record<string, DocxImageType> = {
  png: "png",
  jpg: "jpg",
  jpeg: "jpg",
  gif: "gif",
  bmp: "bmp",
};

const MAX_IMAGE_WIDTH = 380;
const MAX_IMAGE_HEIGHT = 280;

async function loadImage(url: string | null) {
  if (!url || !url.startsWith("/uploads/")) return null;
  try {
    const filePath = path.join(process.cwd(), "public", url);
    const buffer = await readFile(filePath);
    const dims = imageSize(buffer);
    const type = SUPPORTED_IMAGE_TYPES[dims.type ?? ""];
    // Word's ImageRun only supports png/jpg/gif/bmp — other formats (e.g. webp)
    // are skipped rather than corrupting the document.
    if (!type) return null;

    const scale = Math.min(MAX_IMAGE_WIDTH / dims.width, MAX_IMAGE_HEIGHT / dims.height, 1);
    return {
      buffer,
      type,
      width: Math.max(1, Math.round(dims.width * scale)),
      height: Math.max(1, Math.round(dims.height * scale)),
    };
  } catch {
    return null;
  }
}

export type ExportQuestion = {
  index: number;
  questionId: string;
  text: string;
  image: { buffer: Buffer; type: DocxImageType; width: number; height: number } | null;
  options: { letter: string; text: string; isCorrect: boolean }[];
};

// `testId` seeds the option shuffle so it's the SAME every time this test is
// exported — the printed question paper (this file) and an assignment's frozen
// answer key (src/lib/answer-key.ts) must agree on option order, otherwise a
// student's bubbled answer wouldn't match the stored key.
export async function buildExportQuestions(
  testId: string,
  questions: {
    id: string;
    text: string;
    imageUrl: string | null;
    correctAnswer: string;
    wrongAnswers: string[];
  }[],
): Promise<ExportQuestion[]> {
  const result: ExportQuestion[] = [];
  for (let i = 0; i < questions.length; i++) {
    const q = questions[i];
    const rawOptions = seededShuffle(`${testId}:${q.id}`, [
      { text: q.correctAnswer, isCorrect: true },
      ...q.wrongAnswers.map((text) => ({ text, isCorrect: false })),
    ]);
    result.push({
      index: i + 1,
      questionId: q.id,
      text: q.text,
      image: await loadImage(q.imageUrl),
      options: rawOptions.map((o, idx) => ({ letter: LETTERS[idx], ...o })),
    });
  }
  return result;
}

// Variantlar qog'ozni tejash uchun bitta qatorga, tab bilan ustunma-ustun
// tekislab chiqariladi ("A) 135   B) 315   C) 531   D) 351"). Uzun variantlar
// bir-biriga kirib ketmasligi uchun: sig'sa — bitta qator, o'rtacha uzunlikda
// — ikkitadan, juda uzun bo'lsa — avvalgidek har biri alohida qatorda.
const OPTION_INDENT = 300; // twip
const CONTENT_WIDTH = 9000; // A4, standart hoshiyalar orasidagi kenglik (twip)
const ONE_LINE_CHARS = 74; // "A) ..." larning umumiy uzunligi
const TWO_COLUMN_CHARS = 34; // bitta variantning uzunligi

function optionParagraphs(options: ExportQuestion["options"]): Paragraph[] {
  const labels = options.map((o) => `${o.letter}) ${o.text}`);
  const total = labels.reduce((n, l) => n + l.length, 0);
  const longest = Math.max(...labels.map((l) => l.length));
  const perLine = total <= ONE_LINE_CHARS ? labels.length : longest <= TWO_COLUMN_CHARS ? 2 : 1;

  if (perLine <= 1) {
    return labels.map(
      (label) =>
        new Paragraph({
          indent: { left: OPTION_INDENT },
          spacing: { after: 40 },
          children: [new TextRun({ text: label })],
        }),
    );
  }

  const step = Math.floor((CONTENT_WIDTH - OPTION_INDENT) / perLine);
  const paragraphs: Paragraph[] = [];
  for (let i = 0; i < labels.length; i += perLine) {
    const row = labels.slice(i, i + perLine);
    paragraphs.push(
      new Paragraph({
        indent: { left: OPTION_INDENT },
        spacing: { after: 60 },
        tabStops: row
          .slice(1)
          .map((_, idx) => ({ type: TabStopType.LEFT, position: OPTION_INDENT + step * (idx + 1) })),
        children: row.flatMap((label, idx) =>
          idx === 0
            ? [new TextRun({ text: label })]
            : [new TextRun({ children: [new Tab()] }), new TextRun({ text: label })],
        ),
      }),
    );
  }
  return paragraphs;
}

// Questions are numbered straight through 1..N under the test's one subject —
// the same numbering the answer sheet's single subject block uses
// (checker/omr/answer_sheet_service.py).
export async function generateTestDocx(
  title: string,
  subjectName: string,
  questions: ExportQuestion[],
  // The student copy of a classroom assignment is printed WITHOUT the key.
  options: { includeKey?: boolean } = {},
): Promise<Buffer> {
  const children: Paragraph[] = [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      children: [new TextRun({ text: title, bold: true })],
    }),
    new Paragraph({
      spacing: { after: 300 },
      children: [
        new TextRun({ text: subjectName, bold: true }),
        new TextRun({
          text: `  ·  ${new Date().toLocaleDateString("uz-UZ")}`,
          italics: true,
          color: "666666",
        }),
      ],
    }),
  ];

  for (const q of questions) {
    children.push(
      new Paragraph({
        spacing: { before: 140, after: 60 },
        children: [
          new TextRun({ text: `${q.index}. `, bold: true }),
          new TextRun({ text: q.text }),
        ],
      }),
    );

    if (q.image) {
      children.push(
        new Paragraph({
          spacing: { after: 100 },
          children: [
            new ImageRun({
              type: q.image.type,
              data: q.image.buffer,
              transformation: { width: q.image.width, height: q.image.height },
            }),
          ],
        }),
      );
    }

    children.push(...optionParagraphs(q.options));
  }

  if (options.includeKey ?? true) {
    const keyLine = questions
      .map((q) => {
        const correct = q.options.find((o) => o.isCorrect);
        return `${q.index}-${correct?.letter ?? "-"}`;
      })
      .join("  ");

    children.push(
      new Paragraph({
        spacing: { before: 400 },
        children: [
          new TextRun({ text: "Kalitlar: ", bold: true }),
          new TextRun({ text: keyLine }),
        ],
      }),
    );
  }

  const doc = new Document({ sections: [{ properties: {}, children }] });
  return Packer.toBuffer(doc);
}
