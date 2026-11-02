-- 1-bosqich: o'qituvchi kiritadigan o'quvchilar, Telegram akkaunt ulash,
-- guruhga biriktirilgan offline topshiriqlar va varaq natijalari.
-- `prisma migrate diff` chiqargan SQL + mavjud Student qatorlarini ko'chirish
-- (qo'lda qo'shilgan qadamlar "Ma'lumot:" deb belgilangan).

-- CreateEnum
CREATE TYPE "AssignmentMode" AS ENUM ('OFFLINE', 'ONLINE');

-- CreateTable
CREATE TABLE "TelegramAccount" (
    "id" TEXT NOT NULL,
    "firstName" TEXT NOT NULL,
    "lastName" TEXT,
    "username" TEXT,
    "photoUrl" TEXT,
    "lastLoginAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TelegramAccount_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StudentTelegramLink" (
    "id" TEXT NOT NULL,
    "studentId" TEXT NOT NULL,
    "telegramAccountId" TEXT NOT NULL,
    "linkedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "StudentTelegramLink_pkey" PRIMARY KEY ("id")
);

-- Ma'lumot: eski modelda Student = Telegram akkaunt edi. Telegram orqali
-- haqiqatan kirganlar (lastLoginAt epoch emas) akkauntga aylanadi va o'z
-- Student yozuviga ulanadi; o'qituvchi qo'shgan o'rinbosar yozuvlar
-- (lastLoginAt = 1970-01-01) oddiy o'quvchi bo'lib qoladi.
INSERT INTO "TelegramAccount" ("id", "firstName", "lastName", "username", "photoUrl", "lastLoginAt", "createdAt")
SELECT "id", "firstName", "lastName", "username", "photoUrl", "lastLoginAt", "createdAt"
FROM "Student" WHERE "lastLoginAt" > TIMESTAMP '1970-01-02';

INSERT INTO "StudentTelegramLink" ("id", "studentId", "telegramAccountId")
SELECT 'mig_' || "id", "id", "id"
FROM "Student" WHERE "lastLoginAt" > TIMESTAMP '1970-01-02';

-- AlterTable
ALTER TABLE "Student" ADD COLUMN     "birthDate" DATE,
ADD COLUMN     "createdById" TEXT,
ADD COLUMN     "grade" TEXT,
ADD COLUMN     "linkCode" TEXT;

-- Ma'lumot: mavjud o'quvchilarga ulash kodi.
UPDATE "Student" SET "linkCode" = upper(substr(md5(random()::text || "id"), 1, 8));
ALTER TABLE "Student" ALTER COLUMN "linkCode" SET NOT NULL;

ALTER TABLE "Student" DROP COLUMN "lastLoginAt",
DROP COLUMN "photoUrl",
DROP COLUMN "username";

-- CreateTable
CREATE TABLE "Assignment" (
    "id" TEXT NOT NULL,
    "seq" SERIAL NOT NULL,
    "classroomId" TEXT NOT NULL,
    "testId" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "mode" "AssignmentMode" NOT NULL DEFAULT 'OFFLINE',
    "subjectName" TEXT NOT NULL,
    "questionIds" TEXT[],
    "answerKey" TEXT[],
    "createdById" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "archived" BOOLEAN NOT NULL DEFAULT false,
    "sheetBlankPdf" BYTEA,
    "sheetFieldBoxes" TEXT,
    "sheetBubbleBoxes" TEXT,

    CONSTRAINT "Assignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AssignmentSheet" (
    "id" TEXT NOT NULL,
    "seq" SERIAL NOT NULL,
    "assignmentId" TEXT NOT NULL,
    "studentId" TEXT NOT NULL,
    "ticketNo" TEXT NOT NULL,
    "answers" TEXT[],
    "correct" INTEGER,
    "total" INTEGER,
    "percentage" DOUBLE PRECISION,
    "checkedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AssignmentSheet_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "StudentTelegramLink_telegramAccountId_idx" ON "StudentTelegramLink"("telegramAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "StudentTelegramLink_studentId_telegramAccountId_key" ON "StudentTelegramLink"("studentId", "telegramAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "Assignment_seq_key" ON "Assignment"("seq");

-- CreateIndex
CREATE INDEX "Assignment_classroomId_idx" ON "Assignment"("classroomId");

-- CreateIndex
CREATE UNIQUE INDEX "AssignmentSheet_seq_key" ON "AssignmentSheet"("seq");

-- CreateIndex
CREATE UNIQUE INDEX "AssignmentSheet_ticketNo_key" ON "AssignmentSheet"("ticketNo");

-- CreateIndex
CREATE INDEX "AssignmentSheet_studentId_idx" ON "AssignmentSheet"("studentId");

-- CreateIndex
CREATE UNIQUE INDEX "AssignmentSheet_assignmentId_studentId_key" ON "AssignmentSheet"("assignmentId", "studentId");

-- CreateIndex
CREATE UNIQUE INDEX "Student_linkCode_key" ON "Student"("linkCode");

-- AddForeignKey
ALTER TABLE "Student" ADD CONSTRAINT "Student_createdById_fkey" FOREIGN KEY ("createdById") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StudentTelegramLink" ADD CONSTRAINT "StudentTelegramLink_studentId_fkey" FOREIGN KEY ("studentId") REFERENCES "Student"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StudentTelegramLink" ADD CONSTRAINT "StudentTelegramLink_telegramAccountId_fkey" FOREIGN KEY ("telegramAccountId") REFERENCES "TelegramAccount"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Assignment" ADD CONSTRAINT "Assignment_classroomId_fkey" FOREIGN KEY ("classroomId") REFERENCES "Classroom"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Assignment" ADD CONSTRAINT "Assignment_testId_fkey" FOREIGN KEY ("testId") REFERENCES "Test"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Assignment" ADD CONSTRAINT "Assignment_createdById_fkey" FOREIGN KEY ("createdById") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssignmentSheet" ADD CONSTRAINT "AssignmentSheet_assignmentId_fkey" FOREIGN KEY ("assignmentId") REFERENCES "Assignment"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssignmentSheet" ADD CONSTRAINT "AssignmentSheet_studentId_fkey" FOREIGN KEY ("studentId") REFERENCES "Student"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
