import { test } from "node:test";
import assert from "node:assert/strict";
import { verifyWebAppInitData, webAppHash } from "../src/lib/telegram-webapp";

const TOKEN = "123456:TEST-token";
const NOW = Date.parse("2026-09-13T10:00:00Z");

// Builds initData the way Telegram does: every field signed, hash appended.
function initData(fields: Record<string, string>, token = TOKEN) {
  const dataCheckString = Object.keys(fields)
    .sort()
    .map((key) => `${key}=${fields[key]}`)
    .join("\n");
  return new URLSearchParams({ ...fields, hash: webAppHash(dataCheckString, token) }).toString();
}

const fresh = {
  auth_date: String(NOW / 1000 - 60),
  query_id: "AAHdF6IQAAAAAN0XohDhrOrc",
  user: JSON.stringify({ id: 777000111, first_name: "Madina", last_name: "Karimova", username: "madina" }),
  signature: "abc",
};

test("accepts data signed with the bot token", () => {
  assert.deepEqual(verifyWebAppInitData(initData(fresh), TOKEN, NOW), {
    id: "777000111",
    first_name: "Madina",
    last_name: "Karimova",
    username: "madina",
  });
});

test("rejects a tampered user", () => {
  const data = new URLSearchParams(initData(fresh));
  data.set("user", JSON.stringify({ id: 1, first_name: "Boshqa" }));
  assert.equal(verifyWebAppInitData(data.toString(), TOKEN, NOW), null);
});

test("rejects data signed for another bot", () => {
  assert.equal(verifyWebAppInitData(initData(fresh, "999:other"), TOKEN, NOW), null);
});

test("rejects stale data", () => {
  const old = { ...fresh, auth_date: String(NOW / 1000 - 2 * 24 * 60 * 60) };
  assert.equal(verifyWebAppInitData(initData(old), TOKEN, NOW), null);
});

test("rejects a missing hash, user, or token", () => {
  assert.equal(verifyWebAppInitData(`auth_date=${fresh.auth_date}&user=%7B%7D`, TOKEN, NOW), null);
  assert.equal(verifyWebAppInitData(initData({ auth_date: fresh.auth_date }), TOKEN, NOW), null);
  assert.equal(verifyWebAppInitData(initData(fresh), "", NOW), null);
});
