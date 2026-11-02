import { test } from "node:test";
import assert from "node:assert/strict";
import { staffRoleFromBot } from "../src/lib/roles";
import {
  academicYearStart,
  currentGrade,
  parseIds,
  smartbotChildren,
  smartbotDatabaseUrl,
  smartbotRole,
} from "../src/lib/smartbot";

test("bot roles map to platform roles; others get the family cabinet", () => {
  assert.equal(staffRoleFromBot("superadmin"), "SUPER_ADMIN");
  assert.equal(staffRoleFromBot("admin"), "ADMIN");
  assert.equal(staffRoleFromBot("teacher"), "TEACHER");
  assert.equal(staffRoleFromBot("smm_manager"), null);
  assert.equal(staffRoleFromBot("reception"), null);
  assert.equal(staffRoleFromBot(null), null);
});

test("superadmin ids are read like smartbot's SUPERADMIN_IDS", () => {
  assert.deepEqual([...parseIds(" 111, 222,abc,,333 ")], ["111", "222", "333"]);
  assert.equal(parseIds(undefined).size, 0);
});

test("the bot's database address", () => {
  assert.equal(
    smartbotDatabaseUrl({ SMARTBOT_DATABASE_URL: "postgresql+asyncpg://bot:secret@localhost:5432/testbot_db" }),
    "postgresql://bot:secret@localhost:5432/testbot_db",
  );
  assert.equal(
    smartbotDatabaseUrl({
      SMARTBOT_DB_NAME: "smartbot_db",
      DATABASE_URL: "postgresql://app:secret@localhost:5433/smartacademy_platform?schema=public",
    }),
    "postgresql://app:secret@localhost:5433/smartbot_db",
  );
  assert.equal(smartbotDatabaseUrl({}), null);
});

test("superadmins need no database; without one nobody else is staff", async () => {
  assert.equal(await smartbotRole("42", { SMARTBOT_SUPERADMIN_IDS: "7,42" }), "superadmin");
  assert.equal(await smartbotRole("43", { SMARTBOT_SUPERADMIN_IDS: "7,42" }), null);
});

test("a child's grade moves up on 1 September, like in the bot", () => {
  assert.equal(academicYearStart(new Date(2026, 7, 31)), 2025);
  assert.equal(academicYearStart(new Date(2026, 8, 1)), 2026);

  // 2026-yilning sentabrida 5-sinf deb kiritilgan
  assert.equal(currentGrade(5, 2026, new Date(2027, 4, 20)), 5);
  assert.equal(currentGrade(5, 2026, new Date(2027, 8, 1)), 6);
  assert.equal(currentGrade(5, 2026, new Date(2029, 9, 1)), 8);
  // 11-sinfdan oshmaydi va orqaga ketmaydi
  assert.equal(currentGrade(10, 2026, new Date(2030, 8, 1)), 11);
  assert.equal(currentGrade(7, 2026, new Date(2024, 8, 1)), 7);
});

test("without the bot's database there are no children to show", async () => {
  assert.equal(await smartbotChildren("42", {}), null);
});
