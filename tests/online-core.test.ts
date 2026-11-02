import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SAVE_GRACE_MS,
  attemptDeadline,
  canonicalOptions,
  isPastDeadline,
  letterIndex,
  optionOrder,
  questionOrder,
  revealAllowed,
  sheetStatus,
  windowState,
} from "../src/lib/online-core";
import { correctLetter } from "../src/lib/answer-key";

const t0 = new Date("2026-09-13T10:00:00Z");
const at = (minutes: number) => new Date(t0.getTime() + minutes * 60_000);
const noLimits = { opensAt: null, closesAt: null, timeLimitMinutes: null };

test("the deadline is the earlier of the time limit and the closing time", () => {
  assert.equal(attemptDeadline(noLimits, t0), null);
  assert.deepEqual(attemptDeadline({ ...noLimits, timeLimitMinutes: 30 }, t0), at(30));
  assert.deepEqual(attemptDeadline({ ...noLimits, closesAt: at(10), timeLimitMinutes: 30 }, t0), at(10));
  assert.deepEqual(attemptDeadline({ ...noLimits, closesAt: at(90), timeLimitMinutes: 30 }, t0), at(30));
  assert.deepEqual(attemptDeadline({ ...noLimits, closesAt: at(45) }, t0), at(45));
});

test("answers within the grace period still count", () => {
  const deadline = at(30);
  assert.equal(isPastDeadline(deadline, new Date(deadline.getTime() + SAVE_GRACE_MS)), false);
  assert.equal(isPastDeadline(deadline, new Date(deadline.getTime() + SAVE_GRACE_MS + 1)), true);
  assert.equal(isPastDeadline(null, at(100_000)), false);
});

test("window and sheet status", () => {
  const w = { opensAt: at(0), closesAt: at(60), timeLimitMinutes: null };
  assert.equal(windowState(w, at(-1)), "not_open");
  assert.equal(windowState(w, at(0)), "open");
  assert.equal(windowState(w, at(60)), "closed");

  const online = { ...w, mode: "ONLINE" as const };
  const fresh = { startedAt: null, checkedAt: null };
  assert.equal(sheetStatus(online, fresh, at(-5)), "not_open");
  assert.equal(sheetStatus(online, fresh, at(5)), "available");
  assert.equal(sheetStatus(online, fresh, at(61)), "missed");
  assert.equal(sheetStatus(online, { startedAt: at(1), checkedAt: null }, at(5)), "in_progress");
  assert.equal(sheetStatus(online, { startedAt: at(1), checkedAt: at(2) }, at(5)), "checked");
  assert.equal(sheetStatus({ ...w, mode: "OFFLINE" }, fresh, at(5)), "awaiting_scan");
});

test("per-student orders are complete, stable, and differ between students", () => {
  const all = Array.from({ length: 30 }, (_, i) => i);
  const order = questionOrder("sheet-a", 30, true);
  assert.deepEqual([...order].sort((x, y) => x - y), all);
  assert.deepEqual(questionOrder("sheet-a", 30, true), order);
  assert.notDeepEqual(questionOrder("sheet-b", 30, true), order);
  assert.deepEqual(questionOrder("sheet-a", 5, false), [0, 1, 2, 3, 4]);

  const options = optionOrder("sheet-a", "q1", 5, true);
  assert.deepEqual([...options].sort((x, y) => x - y), [0, 1, 2, 3, 4]);
  assert.deepEqual(optionOrder("sheet-a", "q1", 5, false), [0, 1, 2, 3, 4]);
});

test("canonical options put the correct answer under the answer-key letter", () => {
  for (let i = 0; i < 100; i++) {
    const q = { id: `q${i}`, correctAnswer: "TO'G'RI", wrongAnswers: ["a", "b", "c", "d"] };
    const options = canonicalOptions("test-1", q);
    assert.equal(options[letterIndex(correctLetter("test-1", q))], "TO'G'RI");
  }
});

test("answers are revealed according to the policy", () => {
  assert.equal(revealAllowed("IMMEDIATELY", null, t0), true);
  assert.equal(revealAllowed("AFTER_CLOSE", at(10), at(9)), false);
  assert.equal(revealAllowed("AFTER_CLOSE", at(10), at(10)), true);
  assert.equal(revealAllowed("AFTER_CLOSE", null, at(10)), false);
  assert.equal(revealAllowed("NEVER", at(10), at(20)), false);
});
