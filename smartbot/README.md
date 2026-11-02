# SmartAcademy Telegram Bot

Python Telegram bot for school assessments, student registration, online
tests, results, certificates, and answer-sheet workflows. The bot can also
open the platform's student cabinet as a Telegram Mini App.

O'quvchi ro'yxatdan o'tadi, olimpiadaga yoziladi, javob varaqasi OpenCV
bilan o'qiladi yoki online test botning o'zida ishlanadi, natijalar sinf
bo'yicha reytingga tushadi va sertifikat beriladi.

---

## Tez boshlash

```bash
cd smartbot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env      # BOT_TOKEN, DATABASE_URL va QR_SECRET ni sozlang
.venv/bin/python bot.py
```

PostgreSQL kerak. Jadvallar birinchi ishga tushishda avtomatik yaratiladi
(`database/db.py` → `init_db()`). `BOT_TOKEN`, `DATABASE_URL` yoki `QR_SECRET`
sozlanmagan bo'lsa bot ishga tushmaydi. Lokal ishlab chiqishda production bot
tokenini ishlatmang.

Ruxsatnoma (WeasyPrint) uchun tizim paketlari kerak — Linux'da
`libpango-1.0-0 libpangoft2-1.0-0 libcairo2 poppler-utils fonts-noto`
(qarang: [checker/README.md](../checker/README.md)). Bu paketlarsiz bot ishga
tushadi, faqat ruxsatnoma generatsiyasi ishlamaydi.

---

## Texnik asos

| | |
|---|---|
| Til | Python 3.12 |
| Freymvork | aiogram 3.29 (polling) |
| Baza | PostgreSQL 16 + SQLAlchemy 2.0 (async, asyncpg) |
| Rasm | OpenCV (headless), PyMuPDF, Pillow |
| Excel | openpyxl |
| Ish muhiti | Python 3.12+ |

Bot **polling** rejimida — port ochish, nginx, domen, SSL kerak emas.

---

## Papkalar

```
bot.py                  kirish nuqtasi
config.py               .env dan sozlamalarni o'qiydi

database/
  db.py                 engine, sessiya, init_db() — MIGRATSIYALAR SHU YERDA
  models.py             SQLAlchemy modellari

handlers/
  user.py               o'quvchi: ro'yxat, olimpiada, online test, natijalar
  admin.py              admin: javob varag'i, olimpiada, Excel import, OMR
  superadmin.py         xodimlarni boshqarish

services/               murakkab mantiq (handlerlardan ajratilgan)
  name_matching.py      ism normalizatsiya va moslashtirish
  ranking.py            o'rin hisoblash
  excel_import.py       Excel parser
  ticket_service.py     ruxsatnoma PDF/PNG generatsiyasi (Jinja2+WeasyPrint+pdftoppm):
                        ro'yxatdan o'tganda (A5) va qabulda rasm bilan (A4)
  answer_sheet_service.py  javob varag'i PDF generatsiyasi (shablon + shtamplash)
  omr_checker.py        javob varag'ini avtomatik tekshirish (ArUco + doira o'qish)
  test_sheet_excel.py   olimpiadadan tashqari varaq uchun ishtirokchilar Excel'i
  platform_tests.py     platformadan o'qish: test (varaq sozlamasi) va guruhlar (o'quvchilar)

utils/
  utility.py            sana parseri, baholash mezoni, ism/kod yordamchilari
  certificate.py        sertifikat generatori
  qr_payload.py         ruxsatnoma ticket_no/QR yasash va tekshirish (OMR ham import qiladi)
  participant_photo.py  qabulda yuklangan rasmni 3x4 ga keltirish
  roles.py              rollar
  assets/ruxsatnoma/    ruxsatnoma.html (A5), kirish_ruxsatnomasi.html (A4) va logo_brend.png
  assets/answer_sheet/  answer_sheet.html, ArUco belgilari, logo, QR o'rni
  assets/fonts/         sertifikat uchun DejaVu shriftlari

tests/
  test_qr_payload.py    python -m unittest discover -s tests
  test_participant_photo.py

scripts/
  gen_aruco_markers.py  burchak ArUco rasmlarini qayta yasash (kamdan-kam)
  localtest_pdf.py      PDF generatsiyasini Docker ichida lokal sinash

Dockerfile.localtest    Windows'da WeasyPrint'ni sinash uchun (production'ga aloqasi yo'q)
```

---

## Rollar

| Rol | Qayerdan | Nima qila oladi |
|---|---|---|
| **SuperAdmin** | `.env` dagi `SUPERADMIN_IDS` | hammasi + xodim qo'shish/o'chirish |
| **Admin** | `admins` jadvali, `role='admin'` | test, olimpiada, Excel import, PDF checker, user boshqaruvi |
| **O'qituvchi** | `role='teacher'` | test qo'shish va tekshirish |
| **SMM menejer** | `role='smm_manager'` | reklama tarqatish |
| **O'quvchi** | `users` jadvali | olimpiada, online test, natijalar, sertifikat |

`.env` dagi superadminlar `admins` jadvalida bo'lmasa ham to'liq huquqqa ega —
buni `is_admin_or_superadmin()` va `is_superadmin()` ta'minlaydi.

---

## Asosiy oqimlar

### O'quvchi ro'yxati (`/start`)

Faqat botga kerakli ma'lumot so'raladi:

```
telefon → ism familiya → tug'ilgan sana → tayyor
```

Chat ID Telegramdan avtomatik olinadi. **Maktab, sinf, o'qituvchi bu yerda
so'ralmaydi** — ular olimpiadaga xos.

### Olimpiadaga yozilish

```
🏆 Olimpiadalar → olimpiada → maktab → sinf → sinf rahbari → yozildi
```

Ro'yxatdan o'tishda farzandning ism-familiyasi ham alohida so'raladi.

Sinf faqat **o'sha olimpiadaga biriktirilgan** sinflardan tanlanadi
(`olympiad_grades` jadvali). Hech qayerda qattiq yozilmagan.

Ma'lumot `olympiad_results` ga yoziladi, foydalanuvchi profiliga emas —
sinf har yili oshadi, maktab almashishi mumkin.

Ro'yxatdan o'tish tugashi bilan **ruxsatnoma** (PNG + PDF) avtomatik
yuboriladi — QR kod, ID (`ticket_no`) va telefon bilan. O'quvchi uni
istalgan vaqtda "🏆 Olimpiadalar → olimpiada" orqali qayta so'ray oladi
("🎫 Ruxsatnomani olish" tugmasi). Batafsil: [docs/DECISIONS.md](docs/DECISIONS.md#18-ruxsatnoma-hech-narsa-diskda-saqlanmaydi).

### Ishtirokchini qabul qilish (qabulxona)

```
✅ Ishtirokchini qabul qilish → olimpiada → ID → vaqt → xona → 📷 rasm
  → qabul saqlanadi + kirish ruxsatnomasi (PNG va A4 PDF) shu chatga
```

Rasm bazada faqat Telegram `file_id` sifatida turadi; ID qayta kiritilsa avvalgi rasm bilan
davom etish mumkin. Batafsil: DECISIONS.md #26, #39.

### Javob varag'i (admin)

```
📋 Olimpiadalarni boshqarish → olimpiada → 📝 Javob varag'i sozlash
  → platformada shu olimpiada uchun test bo'lsa: 📥 testdan olish (fan, savol soni,
    variant soni va javob kaliti o'zi to'ladi) yoki ✍️ qo'lda sozlash
  → qo'lda: necha fan (1-3) → har fan uchun: nomi → savol soni → variant soni (4/5) → tasdiq
  → 📄 Javob varaqlari (ZIP) — har ro'yxatdan o'tgan uchun shaxsiylashtirilgan
    PDF (ruxsatnomadagi bilan bir xil QR), bitta ZIP qilib
```

Varaq QR-asosli: har sahifada ishtirokchining ticket_no si va burchaklarda
ArUco belgilari bor, shuning uchun uni bot o'zi avtomatik tekshira oladi
("📷 Varaqni tekshirish"). Olimpiadadan tashqarida ham xuddi shu
varaq ishlaydi — "📝 Testlarni tekshirish" bo'limidagi
"🆕 Javob varag'i yaratish" va "✅ Javob varag'ini tekshirish".

"🆕 Javob varag'i yaratish" da ishtirokchilar so'ralganda ("Ha") o'zingizning
platformadagi guruhlaringiz chiqadi — bittasini tanlasangiz o'quvchilarning
ism, familiya, sana va sinfi o'zi olinadi (DECISIONS.md #45). Excel orqali
qo'lda kiritish ham o'z o'rnida turibdi.

Bitta varaq bir nechta guruhga ishlaydi: «✅ Javob varag'ini tekshirish» →
varaq → «📄 Varaqni qayta yuklab olish» kim uchun chiqarishni so'raydi —
avvalgi ro'yxat, boshqa guruh yoki bo'sh varaq (DECISIONS.md #47). Guruh
ikkinchi marta tanlansa nusxa ko'paymaydi, faqat yangi o'quvchilar qo'shiladi.
Batafsil: [docs/DECISIONS.md](docs/DECISIONS.md).

### Olimpiada yaratish (admin)

```
🏆 Olimpiada qo'shish → nom → sinflarni belgilash (multi-select) → sana → tasdiq
```

### Excel orqali natija yuklash (admin)

```
📋 Olimpiadalarni boshqarish → olimpiada → 📥 Natijalarni Excel orqali yuklash
  → sinf → Excel fayl → tahlil (preview) → tasdiq
  → takrorlar siyosati → noaniq nomzodlar → qo'lda qidirish → hisobot
```

Batafsil: [docs/EXCEL_IMPORT.md](docs/EXCEL_IMPORT.md)

### Javob varag'ini tekshirish (admin)

Olimpiada ichida:

```
📋 Olimpiadalarni boshqarish → olimpiada → 🔑 Javob kaliti (+ baholash mezoni)
  → 📷 Varaqni tekshirish → skan/rasm (bir nechta varaq bitta PDF da ham bo'ladi)
```

Olimpiadadan tashqarida:

```
📝 Testlarni tekshirish → ✅ Javob varag'ini tekshirish → varaqni tanlash
  → 🔑 Javob kaliti → 📷 Varaqni tekshirish → skan/rasm
```

Natija QR dagi `ticket_no` bo'yicha topilgan yozuvga yoziladi. Bir varaq
ikki marta tekshirilsa natija **qayta yozilmaydi**. Javobi belgilangan
PDF har doim qaytariladi (🟢 to'g'ri, 🔴 noto'g'ri,
🔵 to'g'ri javob qayerda edi).

### Online test

```
Admin:   🧩 Test savol yaratish → raqam → muqova rasmi (ixtiyoriy) → javob kaliti
O'quvchi: 🧩 Online test → raqam → javoblar → natija
Admin:   📊 Online testlar tarixi (Excel) → test ID → o'sha testning natijalari + Excel
```

Savollar botda tarqatilmaydi — ular kanaldagi e'londa turadi, bot faqat
javobni tekshiradi (DECISIONS.md #46). Muqova (reklama) rasmi qo'yilsa,
o'quvchi raqamni kiritganda shuni ko'radi; qo'yilmasa ham test ishlayveradi.
Rasm serverda saqlanmaydi — Telegram `file_id` bazaga yoziladi.
Har test bir marta ishlanadi (imtihon tartibi).
Tarix faylida ikki varaq: har bir urinish va har bir test bo'yicha yig'ma
(DECISIONS.md #43).

---

## Muhim qoidalar

1. **`.env` hech qachon GitHub'ga tushmasin** — `.gitignore` da to'silgan;
   deploy'da faqat secret manager yoki serverdagi himoyalangan `.env` ishlating.
2. **`drop_all` yoki `DROP COLUMN` ishlatilmasin.** Migratsiyalar faqat
   qo'shuvchi bo'lishi kerak — `database/db.py` dagi namunaga qarang.
3. **Olimpiada va online test o'chirilmaydi, arxivlanadi** — o'quvchilar
   natijalari yo'qolmasligi uchun.
4. **`MemoryMax=700M` cheklovi o'chirilmasin** (systemd unit) — 1 GB RAM'da
   OpenCV ishlaganda mashinani qotib qolishdan saqlaydi.
5. **Og'ir CPU ishi `asyncio.to_thread` ichida bo'lsin** — aks holda bot
   butun tekshiruv davomida hech kimga javob bermaydi.

Sabablari: [docs/DECISIONS.md](docs/DECISIONS.md)

---

## Hujjatlar

| Fayl | Mazmuni |
|---|---|
| [../docs/DEPLOY.md](../docs/DEPLOY.md) | self-hosting and production checklist |
| [docs/DATABASE.md](docs/DATABASE.md) | jadvallar, migratsiya qoidalari |
| [docs/EXCEL_IMPORT.md](docs/EXCEL_IMPORT.md) | Excel parser va ism moslashtirish |
| [docs/DECISIONS.md](docs/DECISIONS.md) | qabul qilingan qarorlar va topilgan nosozliklar |
