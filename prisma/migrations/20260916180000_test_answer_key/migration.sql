-- Testning kaliti va varaqdagi variantlar soni (DECISIONS.md #32): smartbot
-- javob varag'ini shu ustunlardan sozlaydi. Eski testlarda bo'sh — ular Word
-- eksporti paytida to'ldiriladi (yoki scripts bilan bir marta backfill).
ALTER TABLE "Test" ADD COLUMN "answerKey" TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE "Test" ADD COLUMN "choiceCount" INTEGER;
