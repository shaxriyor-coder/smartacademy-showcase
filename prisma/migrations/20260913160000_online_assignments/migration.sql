-- 2-bosqich: online topshiriqlar — ochilish/yopilish vaqti, vaqt chegarasi,
-- aralashtirish, javoblarni ko'rsatish siyosati va urinish boshlangan vaqt.
-- CreateEnum
CREATE TYPE "RevealPolicy" AS ENUM ('IMMEDIATELY', 'AFTER_CLOSE', 'NEVER');

-- AlterTable
ALTER TABLE "Assignment" ADD COLUMN     "closesAt" TIMESTAMP(3),
ADD COLUMN     "opensAt" TIMESTAMP(3),
ADD COLUMN     "revealAnswers" "RevealPolicy" NOT NULL DEFAULT 'IMMEDIATELY',
ADD COLUMN     "shuffle" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "timeLimitMinutes" INTEGER;

-- AlterTable
ALTER TABLE "AssignmentSheet" ADD COLUMN     "startedAt" TIMESTAMP(3);

