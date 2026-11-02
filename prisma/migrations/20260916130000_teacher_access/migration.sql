-- Admin/SuperAdmin o'qituvchi ishini ham qilishi uchun belgi (DECISIONS.md #30).
-- Rol o'zgarmaydi; mavjud xodimlarda false bo'lib qoladi.
ALTER TABLE "User" ADD COLUMN "canTeach" BOOLEAN NOT NULL DEFAULT false;
