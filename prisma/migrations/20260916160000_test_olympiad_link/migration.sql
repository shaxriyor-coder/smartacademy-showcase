-- Test "olimpiada uchun" bo'lsa, botdagi olimpiadaning id'si (DECISIONS.md #31).
-- Eski yozuvlarda NULL bo'lib qoladi: ularning nomi qo'lda yozilgan edi.
ALTER TABLE "Test" ADD COLUMN "smartbotOlympiadId" INTEGER;
