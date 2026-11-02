import { test } from "node:test";
import assert from "node:assert/strict";
import { buildTestKey, correctLetter, testChoiceCount } from "../src/lib/answer-key";
import { seededShuffle } from "../src/lib/shuffle";

const q = (id: string, wrong: number) => ({ id, wrongAnswers: Array.from({ length: wrong }, (_, i) => `w${i}`) });

// docs/DECISIONS.md #32: kalit test bilan saqlanadi va smartbot shuni o'qiydi.
test("test key is the printed paper's letters, in question order", () => {
  const questions = [q("q1", 4), q("q2", 3), q("q3", 4)];
  const key = buildTestKey("t1", questions);

  assert.equal(key.length, 3);
  assert.deepEqual(
    key,
    questions.map((question) => correctLetter("t1", question)),
  );
  // 4 variantli savolda E hech qachon chiqmaydi.
  assert.equal(key[1] === "E", false);
  // Shu bilan varaqdagi variantlar tartibi bir xil urug'dan chiqadi.
  const printed = seededShuffle(`t1:${questions[0].id}`, [0, 1, 2, 3, 4]);
  assert.equal("ABCDE"[printed.indexOf(0)], key[0]);
});

test("the same test always gives the same key, a different test does not", () => {
  const questions = [q("q1", 4), q("q2", 4)];
  assert.deepEqual(buildTestKey("t1", questions), buildTestKey("t1", questions));
  assert.notDeepEqual(buildTestKey("t1", questions), buildTestKey("t2", questions));
});

test("sheet bubbles follow the widest question", () => {
  assert.equal(testChoiceCount([q("a", 3), q("b", 3)]), 4);
  assert.equal(testChoiceCount([q("a", 3), q("b", 4)]), 5);
  assert.equal(testChoiceCount([]), 4);
});
