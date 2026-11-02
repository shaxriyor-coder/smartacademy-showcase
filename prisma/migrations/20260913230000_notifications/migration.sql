-- CreateEnum
CREATE TYPE "NotificationStatus" AS ENUM ('PENDING', 'SENT', 'SKIPPED', 'FAILED');

-- AlterTable
ALTER TABLE "Assignment" ADD COLUMN     "summarySentAt" TIMESTAMP(3);

-- AlterTable
ALTER TABLE "AssignmentSheet" ADD COLUMN     "announcedAt" TIMESTAMP(3),
ADD COLUMN     "resultNotifiedAt" TIMESTAMP(3);

-- AlterTable
ALTER TABLE "TelegramAccount" ADD COLUMN     "botUnreachableAt" TIMESTAMP(3),
ADD COLUMN     "notifyEnabled" BOOLEAN NOT NULL DEFAULT true;

-- CreateTable
CREATE TABLE "Notification" (
    "id" TEXT NOT NULL,
    "chatId" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "dedupeKey" TEXT NOT NULL,
    "text" TEXT NOT NULL,
    "buttonText" TEXT,
    "buttonUrl" TEXT,
    "buttonWebApp" BOOLEAN NOT NULL DEFAULT false,
    "sheetId" TEXT,
    "assignmentId" TEXT,
    "status" "NotificationStatus" NOT NULL DEFAULT 'PENDING',
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "lastError" TEXT,
    "sendAfter" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "sentAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Notification_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Notification_dedupeKey_key" ON "Notification"("dedupeKey");

-- CreateIndex
CREATE INDEX "Notification_status_sendAfter_idx" ON "Notification"("status", "sendAfter");

-- CreateIndex
CREATE INDEX "Notification_chatId_idx" ON "Notification"("chatId");

-- AddForeignKey
ALTER TABLE "Notification" ADD CONSTRAINT "Notification_sheetId_fkey" FOREIGN KEY ("sheetId") REFERENCES "AssignmentSheet"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Notification" ADD CONSTRAINT "Notification_assignmentId_fkey" FOREIGN KEY ("assignmentId") REFERENCES "Assignment"("id") ON DELETE CASCADE ON UPDATE CASCADE;


-- Backfill: what already happened before notifications existed is treated as
-- already notified, so the first sweep doesn't send old results, announce old
-- tests or summarise tests that closed long ago.
UPDATE "AssignmentSheet" SET "resultNotifiedAt" = NOW() WHERE "checkedAt" IS NOT NULL;
UPDATE "AssignmentSheet" SET "announcedAt" = NOW();
UPDATE "Assignment" SET "summarySentAt" = NOW() WHERE "closesAt" IS NOT NULL AND "closesAt" <= NOW();
