import { randomInt } from "crypto";

// No 0/O or 1/I — the code is read off a screen or a note and typed by a
// parent on a phone.
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const LENGTH = 8; // 32^8 ≈ 1.1e12 — not guessable, even without rate limiting

export function generateLinkCode(): string {
  let code = "";
  for (let i = 0; i < LENGTH; i++) code += ALPHABET[randomInt(ALPHABET.length)];
  return code;
}

// Accepts what people actually type: lowercase, spaces, the dash we display.
export function normalizeLinkCode(input: string): string {
  return input.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function formatLinkCode(code: string): string {
  return `${code.slice(0, 4)}-${code.slice(4)}`;
}
