# Baza

PostgreSQL 16, SQLAlchemy 2.0 async (asyncpg).

---

## Jadvallar

```
users
  id              BIGINT PK        Telegram Chat ID
  phone           VARCHAR(20)      normalize_phone() bilan tozalanadi
  full_name       VARCHAR(150)
  birth_date      DATE
  school          VARCHAR(150)     eski yozuvlar uchun, endi so'ralmaydi
  grade           INTEGER          eski yozuvlar uchun
  teacher_name    VARCHAR(150)     eski yozuvlar uchun
  registered_at   TIMESTAMP

olympiads
  id, name (unique), exam_date, is_active, created_at
  code            VARCHAR(10)      ruxsatnoma ticket_no ichiga tushadi (masalan "MATH"),
                                    nomdan avtomatik hosil qilinadi

olympiad_grades                    olimpiada QAYSI SINFLAR uchun
  id, olympiad_id FK, grade
  UNIQUE(olympiad_id, grade)

olympiad_results                   ishtirok + natija
  id, olympiad_id FK, user_id FK
  full_name, school, grade, teacher_name    yozilish paytidagi holat
  first_name, last_name                     ism/familiya alohida (ruxsatnoma uchun);
                                             eski yozuvlarda bo'sh, full_name'dan taxminan ajratiladi
  birth_date DATE                           ishtirokchining tug'ilgan sanasi (javob varag'i uchun);
                                             users.birth_date'dan farqli — akkaunt egasi boshqa odam bo'lishi mumkin
  ticket_no VARCHAR(40) UNIQUE               ruxsatnoma ID'si, bir marta beriladi, o'zgarmaydi
  time_slot_id INTEGER            FK EMAS (qarang: DECISIONS.md #26) -> olympiad_time_slots.id
  room_id INTEGER                 FK EMAS (qarang: DECISIONS.md #26) -> olympiad_rooms.id
  attended_at TIMESTAMP           reception qabul qilgan vaqt = "Ishtirokchi"; checked_at'dan BUTUNLAY BOSHQA narsa
  photo_file_id VARCHAR(255)      qabulda yuklangan rasm — faqat Telegram file_id (DECISIONS.md #39)
  score DOUBLE PRECISION, percentage DOUBLE PRECISION, place INTEGER
  math_correct, math_total, english_correct, english_total
  registered_at, checked_at
  UNIQUE(olympiad_id, user_id)     bir olimpiadaga bir marta

answer_sheets                      bitta olimpiadaning javob varag'i konfiguratsiyasi
  id, olympiad_id FK (UNIQUE), created_at
  marking_area_png BYTEA          ESKI, ISHLATILMAYDI (DECISIONS.md #25 -> #27)
  blank_pdf BYTEA                 oldindan chizilgan BO'SH varaq (1 sahifa PDF), DECISIONS.md #27
  field_boxes TEXT                shtamplash uchun maydon koordinatalari (JSON), blank_pdf bilan juft

answer_sheet_subjects              javob varag'idagi bitta fan bloki
  id, answer_sheet_id FK, position, name, question_count, choice_count (4 yoki 5)

olympiad_time_slots                 qabul qilishda tanlanadigan vaqt oralig'i (DECISIONS.md #26)
  id, olympiad_id FK, position, label VARCHAR(50)

olympiad_rooms                      qabul qilishda tanlanadigan xona (DECISIONS.md #26)
  id, olympiad_id FK, room_number, capacity   sig'im HAR (xona, vaqt) juftligi uchun alohida
  UNIQUE(olympiad_id, room_number)

online_tests                       botda ishlanadigan testlar
  id PK (admin tanlaydi), title, image_file_id, file_type
  answers TEXT, created_by, created_at, archived

online_test_results
  id, online_test_id FK, user_id FK
  given_answers, correct, total, checked_at
  UNIQUE(online_test_id, user_id)  bir marta ishlanadi

admins
  id BIGINT PK, role, username, added_at

test_sheets                        olimpiadadan tashqari javob varag'i (DECISIONS.md #34)
  id, name VARCHAR(150), with_participants BOOLEAN
  created_by BIGINT, created_at
  blank_pdf BYTEA, field_boxes TEXT, bubble_boxes TEXT   AnswerSheet'dagi bilan bir xil ma'no

test_sheet_subjects                varaqdagi fan bloki
  id, test_sheet_id FK, position, name, question_count, choice_count
  answer_key TEXT, rubric TEXT

test_sheet_participants            Excel orqali kiritilgan ishtirokchi + natijasi
  id, test_sheet_id FK, row_no, ism, familiya, birth_date, sinf
  ticket_no VARCHAR(40)            QR uchun, kodi TS{sheet_id}
  score, percentage, detail TEXT, checked_at
  users ga BOG'LANMAYDI — bu odamlar botda ro'yxatdan o'tmagan bo'lishi mumkin
```

### Bog'lanishlar

```
User ──< OlympiadResult >── Olympiad ──< OlympiadGrade
  └──< OnlineTestResult >── OnlineTest

TestSheet ──< TestSheetSubject          (User bilan bog'liq emas)
    └──< TestSheetParticipant
```

Barcha tashqi kalitlar `ON DELETE CASCADE`.

> **`tests` va `test_results` jadvallari.** Eski, bubble-ID ga asoslangan
> tekshiruvchi olib tashlandi (DECISIONS.md #35), shuning uchun bu ikki
> jadval endi kodda YO'Q. Postgres'dagi jadvallarning o'zi va ulardagi
> eski natijalar ATAYLAB o'chirilmadi — "hech qachon DROP qilinmaydi"
> qoidasi (pastda) ularga ham tegishli. Ular shunchaki hech kim
> ishlatmaydigan jadval bo'lib qoladi.

---

## Migratsiya qoidalari

Alembic ishlatilmaydi. Migratsiyalar `database/db.py` → `init_db()` ichida,
bot har ishga tushganda bajariladi.

### Qat'iy qoidalar

1. **`drop_all()` ISHLATILMAYDI.** Bazada jonli ma'lumot bor.
2. **`DROP COLUMN` / `DROP TABLE` yozilmasin.** Ustun kerak bo'lmasa —
   uni shunchaki ishlatmaslik kifoya, ma'lumot joyida qolsin.
3. Faqat **qo'shuvchi va bo'shatuvchi** amallar:
   - `ADD COLUMN IF NOT EXISTS`
   - `ALTER COLUMN ... DROP NOT NULL`
   - `ALTER COLUMN ... TYPE <kengroq tur>` (INTEGER → DOUBLE PRECISION)
   - `CREATE INDEX IF NOT EXISTS`
4. Yangi jadval `Base.metadata.create_all` orqali o'zi yaratiladi.

### Namuna

```python
# database/db.py ichida, init_db() da
await conn.execute(
    text("ALTER TABLE olympiad_results "
         "ADD COLUMN IF NOT EXISTS percentage DOUBLE PRECISION;")
)
```

### O'zgarishdan keyin tekshirish

```sql
-- Yozuvlar soni o'zgarmaganini tasdiqlang
SELECT count(*) FROM users;

-- Nazorat summasi (migratsiyadan oldin va keyin bir xil bo'lishi kerak)
SELECT md5(string_agg(id::text||full_name||phone, '|' ORDER BY id)) FROM users;
```

---

## Indekslar

PostgreSQL tashqi kalit ustunlariga indeksni **avtomatik yaratmaydi**.
Ularsiz har "natijalarim" so'rovi butun jadvalni skanlaydi.

`init_db()` quyidagilarni yaratadi:

```
ix_online_test_results_user_id
ix_online_test_results_test_id
ix_olympiad_grades_olympiad_id
ix_olympiad_results_olympiad_id
ix_olympiad_results_user_id
ux_olympiad_results_ticket_no   (UNIQUE — NULL bir nechta bo'lishi mumkin)
ix_answer_sheet_subjects_sheet_id
ix_olympiad_time_slots_olympiad_id
ix_olympiad_rooms_olympiad_id
ix_olympiad_results_time_slot_id
ix_olympiad_results_room_id
ix_test_sheet_subjects_sheet_id
ix_test_sheet_participants_sheet_id
ux_test_sheet_participants_ticket   (UNIQUE — NULL bir nechta bo'lishi mumkin)
```

Yangi tashqi kalit qo'shsangiz — indeksni ham qo'shing.

---

## Ulanishlar havzasi

`create_async_engine(DATABASE_URL)` — standart: 5 + 10 overflow = **15 ulanish**.

Muhim: **sessiyani uzoq sikl ichida ushlab turmang.** Ilgari PDF tekshiruvi
butun skan davomida (12+ sekund) bitta ulanishni band qilardi. Endi har
sahifa uchun alohida ochilib yopiladi.

```python
# YOMON — ulanish uzoq band bo'ladi
async with async_session() as session:
    for page in pages:
        await og'ir_ish(page)
        session.add(...)

# YAXSHI
for page in pages:
    natija = await og'ir_ish(page)
    async with async_session() as session:
        session.add(natija)
        await session.commit()
```

---

## Sanash

Faqat sonini bilish uchun butun jadvalni yuklamang:

```python
# YOMON — hamma qator xotiraga olinadi
soni = len((await session.execute(select(OlympiadResult).where(...))).scalars().all())

# YAXSHI
soni = (await session.execute(
    select(func.count()).select_from(OlympiadResult).where(...)
)).scalar_one()
```
