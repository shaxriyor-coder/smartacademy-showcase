import { test } from "node:test";
import assert from "node:assert/strict";
import { hasTeacherAccess, isManager, isTeacher } from "../src/lib/roles";

// docs/DECISIONS.md #30: bitta xodim ikkala ishni ham qilishi mumkin —
// roli o'zgarmaydi, ustiga `canTeach` beriladi.
test("teacher access: role or the canTeach flag", () => {
  assert.equal(hasTeacherAccess({ role: "TEACHER" }), true);
  assert.equal(hasTeacherAccess({ role: "ADMIN" }), false);
  assert.equal(hasTeacherAccess({ role: "SUPER_ADMIN" }), false);
  assert.equal(hasTeacherAccess({ role: "ADMIN", canTeach: true }), true);
  assert.equal(hasTeacherAccess({ role: "SUPER_ADMIN", canTeach: true }), true);
  assert.equal(hasTeacherAccess(null), false);
  assert.equal(hasTeacherAccess({}), false);
});

test("the flag does not change the role itself", () => {
  // Admin panelini ochadigan tekshiruvlar o'sha-o'sha qoladi.
  assert.equal(isManager("SUPER_ADMIN"), true);
  assert.equal(isManager("TEACHER"), false);
  assert.equal(isTeacher("ADMIN"), false);
  assert.equal(isTeacher("TEACHER"), true);
});
