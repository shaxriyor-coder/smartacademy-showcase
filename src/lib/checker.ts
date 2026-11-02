// Client for the answer-sheet / OMR service in checker/ (Python). The service
// does the heavy lifting — WeasyPrint template, PyMuPDF stamping, OpenCV
// reading — and never touches the database; grading and storing results stay
// here. See checker/server.py for the endpoint contract.

import { HttpError } from "./http-error";

// Status 422 carries a message written for the teacher (e.g. "the test doesn't
// fit on one sheet"); anything else is an operational failure.
export class CheckerError extends HttpError {}

export type SheetTemplate = {
  blankPdf: Buffer;
  fieldBoxes: string;
  bubbleBoxes: string;
};

export type StampParticipant = {
  ism: string;
  familiya: string;
  kun: string;
  oy: string;
  yil: string;
  sinf: string;
  ticket_no: string;
};

export type CheckedPage =
  | { page: number; ok: false; error: string }
  | {
      page: number;
      ok: true;
      ticket_no: string;
      subjects: { name: string; answers: (string | null)[]; multi: number[] }[];
    };

export type CheckResponse = {
  page_count: number;
  pages: CheckedPage[];
  annotated_pdf: string | null; // base64
};

function config() {
  const url = process.env.CHECKER_URL;
  const token = process.env.CHECKER_TOKEN;
  if (!url || !token) {
    throw new CheckerError("CHECKER_URL / CHECKER_TOKEN .env'da sozlanmagan", 500);
  }
  return { url: url.replace(/\/$/, ""), token };
}

async function call(path: string, init: RequestInit): Promise<Response> {
  const { url, token } = config();
  let res: Response;
  try {
    res = await fetch(`${url}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), "X-Checker-Token": token },
    });
  } catch {
    throw new CheckerError(
      "Checker servisi ishlamayapti — checker/ papkasida `python server.py` ni ishga tushiring.",
      503,
    );
  }
  if (res.status === 401) {
    throw new CheckerError(
      "Platforma va checker'dagi CHECKER_TOKEN bir xil emas (.env fayllarini tekshiring).",
      500,
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new CheckerError(body.error ?? `Checker xatosi (${res.status})`, res.status);
  }
  return res;
}

export type OcrQuestion = {
  number: number;
  text: string;
  options: string[];
  options_are_images: boolean;
  image: string | null; // PNG base64 — tozalangan chizma
  source: string | null; // JPEG base64 — savolning asl rasmdagi bo'lagi
  needs_review: boolean;
  notes: string[];
  uncertain: string[];
};

export type OcrResponse = {
  title: string;
  pages: { page: number; questions: number; figures: number }[];
  questions: OcrQuestion[];
};

export async function readQuestionImages(
  pages: { bytes: Uint8Array; name: string; type: string }[],
): Promise<OcrResponse> {
  const form = new FormData();
  for (const page of pages) {
    form.append("file", new Blob([new Uint8Array(page.bytes)], { type: page.type }), page.name);
  }
  const res = await call("/ocr", { method: "POST", body: form });
  return (await res.json()) as OcrResponse;
}

export async function createTemplate(
  title: string,
  subjects: { name: string; question_count: number; choice_count: number }[],
): Promise<SheetTemplate> {
  const res = await call("/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, subjects }),
  });
  const body = (await res.json()) as {
    blank_pdf: string;
    field_boxes: string;
    bubble_boxes: string;
  };
  return {
    blankPdf: Buffer.from(body.blank_pdf, "base64"),
    fieldBoxes: body.field_boxes,
    bubbleBoxes: body.bubble_boxes,
  };
}

export async function stampSheets(
  template: { blankPdf: Uint8Array; fieldBoxes: string },
  participants: StampParticipant[],
): Promise<Buffer> {
  const res = await call("/stamp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      blank_pdf: Buffer.from(template.blankPdf).toString("base64"),
      field_boxes: template.fieldBoxes,
      participants,
    }),
  });
  return Buffer.from(await res.arrayBuffer());
}

export async function checkScan(
  template: { fieldBoxes: string; bubbleBoxes: string },
  answerKeys: Record<string, string[]>,
  file: { bytes: Uint8Array; name: string; type: string },
): Promise<CheckResponse> {
  const form = new FormData();
  form.append(
    "meta",
    JSON.stringify({
      field_boxes: template.fieldBoxes,
      bubble_boxes: template.bubbleBoxes,
      answer_keys: answerKeys,
    }),
  );
  // Copy into a plain ArrayBuffer-backed view — Blob won't take a view that
  // may sit on a SharedArrayBuffer.
  form.append("file", new Blob([new Uint8Array(file.bytes)], { type: file.type }), file.name);
  const res = await call("/check", { method: "POST", body: form });
  return (await res.json()) as CheckResponse;
}
