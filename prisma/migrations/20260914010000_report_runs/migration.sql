-- CreateTable
CREATE TABLE "ReportRun" (
    "id" TEXT NOT NULL,
    "periodKey" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ReportRun_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "ReportRun_periodKey_key" ON "ReportRun"("periodKey");


-- Reports start from now: no report for a period that ended before this.
INSERT INTO "ReportRun" ("id", "periodKey", "createdAt") VALUES ('installed', 'installed', NOW())
ON CONFLICT DO NOTHING;
