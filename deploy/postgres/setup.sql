-- docs/DEPLOY.md, 6-qadam. Serverdagi PostgreSQL'da BIR MARTA, postgres foydalanuvchisi bilan:
--
--   sudo -u postgres psql \
--     -v platform_pw="$(openssl rand -hex 24)" \
--     -v reader_pw="$(openssl rand -hex 24)" \
--     -v ON_ERROR_STOP=1 -f deploy/postgres/setup.sql
--
-- Parollarni o'sha zahoti .env ga yozib qo'ying (psql ularni ekranga chiqarmaydi —
-- avval `openssl rand -hex 24` bilan hosil qilib, qiymatni ikkala joyga qo'yish qulayroq).

-- Platformaning o'z bazasi.
CREATE ROLE smartacademy LOGIN PASSWORD :'platform_pw';
CREATE DATABASE smartacademy_platform OWNER smartacademy;

-- smartbot bazasini FAQAT O'QISH: faqat admins jadvalining id va role ustunlari
-- (docs/DECISIONS.md #23). Boshqa hech narsaga ruxsat yo'q.
CREATE ROLE smartbot_reader LOGIN PASSWORD :'reader_pw';
ALTER ROLE smartbot_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE testbot_db TO smartbot_reader;

\connect testbot_db
GRANT USAGE ON SCHEMA public TO smartbot_reader;
GRANT SELECT (id, role) ON TABLE admins TO smartbot_reader;
-- Test "olimpiada uchun" bo'lsa, ro'yxat shu jadvaldan olinadi (DECISIONS.md #31).
GRANT SELECT (id, name, code, exam_date, is_active) ON TABLE olympiads TO smartbot_reader;
-- Mini App ochilganda botdagi farzandlar ro'yxati ko'rinadi (DECISIONS.md #33).
-- Bu ikki qator BOT KAMIDA BIR MARTA ISHGA TUSHGANDAN KEYIN ishlaydi: `children`
-- jadvali va `olympiad_results.child_id` ustunini bot o'zi yaratadi
-- (smartbot/database/db.py -> init_db). Bo'lmasa xato beradi — shunda ularni
-- keyinroq, docs/DEPLOY.md dagi bir martalik qadamlar bilan bajaring.
GRANT SELECT (id, user_id, first_name, last_name, birth_date, school, grade, grade_year, archived_at)
  ON TABLE children TO smartbot_reader;
GRANT SELECT (child_id, olympiad_id, grade, score, place)
  ON TABLE olympiad_results TO smartbot_reader;

-- Teskari yo'nalish: bot javob varag'ini platformadagi testdan sozlaydi
-- (DECISIONS.md #32, smartbot/docs/DECISIONS.md #40) va varaqqa o'qituvchining
-- guruhidagi o'quvchilarni bosadi (smartbot/docs/DECISIONS.md #45). Bu yerda
-- faqat rol yaratiladi — jadvallarga SELECT migratsiyalardan KEYIN beriladi
-- (docs/DEPLOY.md, 10-qadam), chunki hozir ular hali mavjud emas.
-- DIQQAT: "Student" va "User" da USTUN bo'yicha ruxsat beriladi — o'quvchining
-- ulanish kodi (linkCode) va xodimning parol xeshi botga ko'rinmasin.
\connect postgres
CREATE ROLE platform_reader LOGIN PASSWORD :'platform_reader_pw';
ALTER ROLE platform_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE smartacademy_platform TO platform_reader;
