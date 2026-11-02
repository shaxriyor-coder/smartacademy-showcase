import mammoth from "mammoth";

export type ParsedQuestion = {
  text: string;
  imageDataUri: string | null;
  options: string[];
};

function stripTags(html: string): string {
  return html
    .replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .trim();
}

const QUESTION_START = /^(\d+)[.)]\s*(.*)$/;
const OPTION_START = /^([A-E])[.)]\s*(.*)$/i;
// Matches every "A) "/"b) " style option marker anywhere in a line, not just
// at the start — some source documents cram all options onto one paragraph
// ("A) Eight   B) Seven   C) Ten   D) Eleven") instead of one per line.
const OPTION_MARKER = /(^|\s)([A-E])[.)]\s*/gi;

// Splits a single paragraph into multiple option texts when it contains more
// than one option marker. Returns null when there's at most one marker, so
// the caller falls back to its normal single-option handling.
function splitCrammedOptions(text: string): string[] | null {
  const matches = [...text.matchAll(OPTION_MARKER)];
  if (matches.length < 2) return null;
  const parts: string[] = [];
  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].index! + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index! : text.length;
    const part = text.slice(start, end).trim();
    if (part) parts.push(part);
  }
  return parts.length > 1 ? parts : null;
}

export async function parseQuestionsFromDocx(buffer: Buffer): Promise<ParsedQuestion[]> {
  const { value: html } = await mammoth.convertToHtml({ buffer });

  // mammoth emits clean <p>...</p> blocks (one per paragraph) in document order,
  // with images inlined as base64 <img> tags where they appear in the source.
  const paragraphs = Array.from(html.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/g)).map((m) => m[1]);

  const questions: ParsedQuestion[] = [];
  let current: ParsedQuestion | null = null;

  for (const raw of paragraphs) {
    const imgMatch = raw.match(/<img[^>]*src="([^"]+)"/);
    const text = stripTags(raw);

    const qMatch = text.match(QUESTION_START);
    const optMatch = text.match(OPTION_START);

    if (qMatch) {
      if (current && (current.text || current.options.length)) questions.push(current);
      current = { text: qMatch[2].trim(), imageDataUri: null, options: [] };
    } else if (optMatch && current) {
      const crammed = splitCrammedOptions(text);
      if (crammed) {
        current.options.push(...crammed);
      } else {
        current.options.push(optMatch[2].trim());
      }
    } else if (current) {
      if (current.options.length === 0 && text) {
        current.text = current.text ? `${current.text}\n${text}` : text;
      } else if (current.options.length > 0 && text) {
        // wrapped continuation of the previous option's text
        const last = current.options.length - 1;
        current.options[last] = `${current.options[last]} ${text}`;
      }
    }

    if (imgMatch && current && current.options.length === 0 && !current.imageDataUri) {
      current.imageDataUri = imgMatch[1];
    }
  }
  if (current && (current.text || current.options.length)) questions.push(current);

  return questions.filter((q) => q.text.trim().length > 0);
}
