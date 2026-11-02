// Answer-sheet ID (ticket_no), identical to checker/omr/qr_payload.py
// build_ticket_no / is_valid_ticket_no:
//
//   SA-{year}-{code}-{seq, 6+ digits}{Luhn check digit}   e.g. SA-2026-CR12-0000457
//
// The platform mints tickets here, but the checker signs them into the QR and
// re-validates the format + check digit before stamping (checker/server.py
// /stamp). If this file and the Python side ever disagree, sheets are refused
// before printing instead of becoming unreadable after — scripts/e2e-offline.ts
// exercises that round trip.

const PREFIX = "SA";
const TICKET_RE = /^SA-(\d{4})-([A-Z0-9]{2,10})-(\d{6,})(\d)$/;

function luhnCheckDigit(digits: string): string {
  let total = 0;
  const reversed = digits.split("").reverse();
  for (let i = 0; i < reversed.length; i++) {
    let d = Number(reversed[i]);
    if (i % 2 === 0) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    total += d;
  }
  return String((10 - (total % 10)) % 10);
}

function sanitizeCode(code: string): string {
  const cleaned = code.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10);
  return cleaned || "GEN";
}

export function buildTicketNo(year: number, code: string, seq: number): string {
  const yearTxt = String(year).padStart(4, "0");
  const seqTxt = String(seq).padStart(6, "0");
  const check = luhnCheckDigit(`${yearTxt}${seqTxt}`);
  return `${PREFIX}-${yearTxt}-${sanitizeCode(code)}-${seqTxt}${check}`;
}

export function isValidTicketNo(ticketNo: string): boolean {
  const m = TICKET_RE.exec(ticketNo.trim().toUpperCase());
  if (!m) return false;
  const [, year, , seq, check] = m;
  return luhnCheckDigit(`${year}${seq}`) === check;
}

// Every assignment gets its own code, so a ticket also tells a teacher at a
// glance which assignment a stray sheet belongs to.
export function assignmentTicketCode(assignmentSeq: number): string {
  return `CR${assignmentSeq}`;
}
