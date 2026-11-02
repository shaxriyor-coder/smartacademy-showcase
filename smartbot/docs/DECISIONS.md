# Qarorlar va topilgan nosozliklar

Bu fayl kodning **nega shunday** yozilganini tushuntiradi. Bir joyni
o'zgartirishdan oldin shu yerni o'qing — ko'p qaror haqiqiy nosozlikdan
keyin qabul qilingan.

---

## 1. O'chirish emas, arxivlash

**Qaror:** test va online test o'chirilganda yozuv bazadan olib
tashlanmaydi, `archived = TRUE` qo'yiladi.

**Nega:** `test_results` va `olympiad_results` da `ON DELETE CASCADE` bor.
Testni haqiqatan o'chirsak, uni allaqachon yechgan o'quvchilarning
natijalari ham birga ketardi. O'quvchi testni topshirgan — natija uning
mulki, test o'chirilgani unga aloqasi yo'q.

Arxivlangan test ro'yxatlarda ko'rinmaydi, lekin hisobotlar va o'quvchi
tarixida qoladi.

**Tuzoq:** arxivdagi test raqami band bo'lib turadi. Shu raqam bilan
yangi test yaratmoqchi bo'lsangiz "♻️ Arxivdan tiklash" tugmasi chiqadi —
aks holda boshi berk ko'chaga tushib qolinardi.

---

## 2. Yechilgan testni tahrirlab bo'lmaydi

**Qaror:** natijasi bor testning javob kalitini o'zgartirish taqiqlangan.

**Nega:** ballar eski kalit bo'yicha hisoblangan. Kalitni o'zgartirsak,
mavjud natijalar jimgina noto'g'ri bo'lib qoladi. Javob varaqalari
saqlanmagani uchun qayta hisoblab ham bo'lmaydi.

Tekshiruv **ikki joyda**: testni tanlaganda va saqlashdan oldin — orada
kimdir yechib qo'ysa ham kalit o'zgarmaydi.

---

## 3. Fanni `0` bilan o'chirish

**Qaror:** `math_answers = "0"` — fan tekshirilmaydi degani. Bu oddiy
javob emas, maxsus qiymat.

**Amalga oshirish:** `parse_answer_key("0")` **bo'sh ro'yxat** qaytaradi.
Bo'sh ro'yxat `Orm_Scanner` ga berilsa u tabiiy ravishda 0 ball qaytaradi —
maxsus shart yozish shart emas.

```
math_total = len([]) = 0
foiz = to'g'ri / (faqat aktiv fanlar savoli) * 100
```

O'chirilgan fanga varaqada belgi ham chizilmaydi (`math_on` sharti) —
aks holda tekshirilmagan fanga chalg'ituvchi rangli doiralar chizilardi.

Ikkala fan ham `0` bo'lsa — rad etiladi.

---

## 4. Og'ir CPU ishi alohida oqimda

**Muammo edi:** butun OpenCV va PDF ishi async handler ichida
to'g'ridan-to'g'ri chaqirilardi. 50 sahifali PDF tekshirilayotganda bot
**5.8 sekund** davomida hech kimga javob bermasdi.

**O'lchov** (fon vazifasi har 50 ms da "urib" turadi):

| | Eski | Yangi |
|---|---|---|
| Eng uzun muzlash | 5828 ms | **183 ms** |
| Yurak urishlari | 6 | 57 |

**Yechim:** har sahifaning butun OpenCV ishi `_scan_page_sync()` ga
ajratildi — u Telegram'ga xabar yubormaydi, bazaga tegmaydi, faqat
hisoblab natijani qaytaradi. Chaqirilishi `asyncio.to_thread` orqali.

**Qoida:** yangi og'ir ish qo'shsangiz — u ham `to_thread` ichida bo'lsin.

---

## 5. Bir vaqtda 2 ta tekshiruv

`MAX_PARALLEL_SCANS = 2` (semaphore).

**Nega:** har skan ~150 MB oladi. Cheklovsiz qoldirilsa 4-5 admin bir
paytda yuborganda `MemoryMax=700M` ga urilib, systemd **butun botni**
o'ldiradi — o'sha paytdagi hamma skanlar yo'qoladi.

Sinovda 5 ta parallel "admin": navbat bilan 35 sekund, eng yuqori
xotira 347 MB.

Uchinchi admin "navbatga qo'yildingiz" xabarini oladi.

---

## 6. Baza sessiyasi qisqa tutiladi

**Muammo edi:** PDF tekshiruvida `async with async_session()` butun
sahifa siklini o'rab turardi — 50 sahifalik skan bitta ulanishni
12 sekund band qilardi. Pool 15 ta, ya'ni 15 parallel skanda hammasi
tugab, 16-chisi 30 sekund kutib `TimeoutError` olardi.

**Yechim:** sessiya har sahifa uchun alohida ochilib yopiladi.

Batafsil: [DATABASE.md](DATABASE.md#ulanishlar-havzasi)

---

## 7. Telegram xabar toshqini

**Muammo edi:** har muammoli sahifa uchun alohida xabar yuborilardi.
50 sahifalik PDF ning ko'pi noto'g'ri skanlangan bo'lsa — 50+ xabar
ketma-ket. Telegram sekundiga ~30 tadan ko'pini o'tkazmaydi va `429`
qaytaradi.

**Yechim:** xatolar yig'iladi va oxirida **bitta xulosa** yuboriladi
(50 ta xato → 320 belgilik bitta xabar). Muammoli sahifalar rasmi
10 tadan albom qilib yuboriladi.

Reklama tarqatishda ham shu muammo bor edi — cheklovsiz yuborilardi va
`429` "botni bloklagan" deb hisoblanardi. Endi sekundiga 20 ta,
`TelegramRetryAfter` ushlanadi, bloklagan va boshqa xatolar alohida
sanaladi.

---

## 8. Rasm serverda saqlanmaydi

Online test rasmi uchun Telegram bergan `file_id` bazaga yoziladi va
o'quvchiga o'sha id bilan qayta yuboriladi. Disk ham, trafik ham
sarflanmaydi.

`file_type` (`photo` / `document`) ham saqlanadi: Telegram oddiy rasmni
siqadi va test varaqasidagi mayda matn o'qilmay qolishi mumkin, shuning
uchun admin siqilmagan fayl yuborishi mumkin — o'quvchiga aynan shu
ko'rinishda qaytariladi.

---

## 9. O'quvchi javoblarini qat'iy tekshirish

**Sinov topgan nosozlik:** `normalize_answers()` A-E dan tashqari
harflarni **jimgina tashlab yuboradi**:

```
"ABXDE"  →  "A,B,D,E"     ← X yo'qoldi, javoblar siljidi!
```

Kalit uchun bu to'g'ri (admin xato yozsa tozalash foydali), lekin
o'quvchi javoblari uchun **xavfli** — bitta noto'g'ri harf qolgan
javoblarni bir pozitsiyaga siljitardi.

**Yechim:** `parse_student_answers()` — alohida qat'iy parser. Noto'g'ri
belgi rad etiladi va aniq aytiladi: *"Faqat A, B, C, D, E harflari
mumkin. Xato belgi: «X»"*.

---

## 10. `message.text` `None` bo'lishi mumkin

**Topilgan nosozlik:** foydalanuvchi matn o'rniga rasm/stiker/fayl
yuborsa `message.text` `None` bo'ladi va `AttributeError` bilan bot
**jimgina yiqilardi** — foydalanuvchi hech qanday javob olmasdi.

14 ta joyda shu xavf bor edi. Hammasi `(message.text or "")` bilan
himoyalandi.

**Qoida:** `message.text` ni to'g'ridan-to'g'ri ishlatmang.

---

## 11. Telefon uzunligi

**Jonli nosozlik edi:** `phone` ustuni `VARCHAR(20)`, kodda esa faqat
`len(phone) < 7` tekshiruvi bor edi — yuqori chegara yo'q. Kimdir
`"+998 90 123 45 67 (Ali akaning raqami)"` (39 belgi) yozsa bazaga
sig'masdi. Yomoni — `commit()` da xato ushlanmagan edi, ya'ni
**foydalanuvchi hech qanday javob olmay, kiritgan hamma ma'lumoti bilan
qotib qolardi**. Kamida 3 kishiga shu bo'lgan.

**Yechim:** `normalize_phone()` — faqat raqamlar va boshidagi `+`.
Barcha maydonlarga uzunlik chegarasi qo'yildi, `commit()` `try/except`
ichiga olindi.

---

## 12. Superadmin admin ishlarini qila olmasdi

**Topilgan nosozlik:** `is_admin_or_superadmin()` faqat `admins`
jadvaliga qarardi, `.env` dagi `SUPERADMIN_IDS` ni **bilmasdi**.
Superadmin panelni ocha olardi, lekin test qo'sha olmasdi.

Bitta superadmin tasodifan `admins` jadvalida ham bor edi, shuning uchun
sezilmagan. Yangi superadmin qo'shilsa umuman ishlamasdi.

Shu bilan birga **"🔙 Bosh menyu"** hammaga o'quvchi menyusini berardi —
superadmin panelidan chiqqach admin tugmalari yo'qolardi.

---

## 13. Sinf har olimpiadada alohida

**Qaror:** maktab, sinf va o'qituvchi `users` da emas, `olympiad_results`
da saqlanadi.

**Nega:** sinf har yili oshadi, maktab almashishi mumkin. Har olimpiada
uchun o'sha paytdagi holat qayd etilishi kerak.

`users` dagi eski ustunlar **saqlab qolindi** — 340 o'quvchining
ma'lumoti u yerda, yo'qotib bo'lmaydi. Ular endi so'ralmaydi, lekin
eksportda zaxira qiymat sifatida ishlatiladi.

**Sinflar vergulli satr emas, alohida jadval** (`olympiad_grades`) —
shunda sinf bo'yicha filtr, reyting va eksport SQL darajasida ishlaydi.

Hech qayerda `2-4 sinf` qattiq yozilmagan. Olimpiada qaysi sinflar uchun
yaratilgan bo'lsa, aynan o'shalar qo'llanadi.

---

## 14. Reyting bitta joyda

`services/ranking.py` → `recalculate_olympiad_places()`.

Excel import, PDF checker va qo'lda tahrirlash **bir xil** funksiyani
chaqiradi. Scope faqat `olympiad_id + grade`.

**Qoida:** o'rin hisoblash mantiqini handler ichida takrorlab yozmang.

---

## 15. Kanal a'zoligi — fail-open

Bot kanalga a'zolikni tekshira olmasa (masalan admin huquqi olib
qo'yilsa), foydalanuvchi **ichkariga qo'yiladi** va xato logga yoziladi.

**Nega:** sozlamadagi nosozlik tufayli 340 o'quvchi bot'dan butunlay
uzilib qolmasligi kerak.

A'zolik natijasi 10 daqiqaga eslab qolinadi — aks holda har bosilgan
tugma uchun Telegram'ga so'rov ketardi.

---

## 16. Deploy tekshiruvi: nima yetarli emas

**Topilgan nosozlik:** refaktorda `process_pdf_sheets` ikkiga bo'lindi va
`doc` o'zgaruvchisi o'ramda qolib ketdi. Bot **muvaffaqiyatli ishga
tushdi**, deploy "OK" dedi — lekin har PDF tekshiruvi `NameError` bilan
jimgina yiqilardi.

**Xulosa:** ishga tushish tekshiruvi yetarli emas. Deploy'ga
`pyflakes | grep 'undefined name'` qadami qo'shildi — u aynan shu
xatoni topadi va botni qayta ishga tushirmasdan to'xtaydi.

Yana bir nosozlik: deploy'ning log tekshiruvi `--since '1 minute ago'`
ishlatardi va **oldingi** deploy'ning eski `Traceback` larini ko'rib
muvaffaqiyatli deploy'ni rad etardi. Endi `InvocationID` bo'yicha
tekshiradi.

---

## 17. Deploy jarayondagi ishni uzadi

`bot.py` da `drop_pending_updates=True` va FSM `MemoryStorage`.
Bot qayta ishga tushganda kutib turgan so'rovlar tashlanadi va yarim
qolgan jarayonlar bekor bo'ladi.

Tinch paytda deploy qiling.

---

## 18. Ruxsatnoma: hech narsa diskda saqlanmaydi

**Qaror:** QR kod, PDF va PNG bazada ham, diskda ham saqlanmaydi. Har
so'rovda `ticket_no`dan qaytadan hisoblanadi/generatsiya qilinadi
(`utils/qr_payload.py`, `services/ticket_service.py`).

**Nega:** `ticket_no` bir marta beriladi va o'zgarmaydi — demak undan
chiqadigan hamma narsa (QR payload, HMAC imzo, PDF/PNG ko'rinishi)
har doim bir xil bo'ladi. Saqlashning hojati yo'q, faqat sinxronizatsiya
xavfi qo'shardi (masalan shablon yangilansa, eski saqlangan PNG eskirib
qolardi).

`pdftoppm` CLI dastur bo'lgani uchun vaqtinchalik faylsiz ishlay olmaydi —
u `tempfile.TemporaryDirectory()` ichida, funksiya tugashi bilan o'chadi.
Bu "diskka yozilmaydi" qoidasini buzmaydi: natija hech qachon **saqlanmaydi**,
faqat bir lahzalik ichki bosqich sifatida ishlatiladi.

## 19. ticket_no formati va ikki xil tekshiruv

**Format:** `SA-{yil}-{olimpiada kodi}-{OlympiadResult.id, 6 xonali}{Luhn}`.

**Nega aynan `id`:** alohida hisoblagich (counter) kerak emas — Postgres
autoincrement allaqachon to'qnashuvsiz va parallel-xavfsiz.

**Ikki mustaqil tekshiruv bor, ikkalasi ham kerak:**
  - HMAC imzo (QR ichida) — soxta ruxsatnoma yasashning oldini oladi.
  - Luhn nazorat raqami (ticket_no'ning o'zida, ko'zga ko'rinadi) —
    operator qo'lda kiritganda xato qilsa darhol rad etadi.

Bittasi ikkinchisining o'rnini bosolmaydi: imzo qog'ozda yo'q (faqat QR
ichida), nazorat raqami esa soxtalikka qarshi himoya bermaydi (uni ham
"to'g'ri" qilib to'qib chiqarish mumkin — HMAC kaliti kerak).

## 20. Ism/familiya uzunligi — WeasyPrint o'zi piksel o'lchay olmaydi

**Muammo:** `utils/certificate.py`dagi `_fit_font()` shrift o'lchamini
ishga tushirish vaqtida piksel o'lchab tanlaydi (Pillow orqali). WeasyPrint
bunday ishlay olmaydi — u faqat CSS'ga qarab joylashtiradi, JS yo'q.

**Yechim:** `services/ticket_service.py -> _name_size_class()` — uzunlik
bo'yicha oldindan tanlangan 4 ta bosqich (`sz1`–`sz4`). Har bosqichda ham
matn `ruxsatnoma.html`dagi qat'iy balandlikdagi `.zone` ichiga 2 qatordan
oshmay sig'adi — bu brauzerda haqiqiy uzun ismlar (30+ belgi, ikkalasi
ham bir vaqtda) bilan qo'lda sinovdan o'tkazilgan. `.zone{overflow:hidden}`
ehtiyot chorasi sifatida qoldirilgan.

## 21. WeasyPrint import — funksiya ichida, modul boshida emas

`services/ticket_service.py`da `from weasyprint import HTML` modul
boshida emas, `_render_pdf_sync()` ichida. WeasyPrint tizimga o'rnatilgan
`libpango`/`libcairo`ga tayanadi (production serverda apt orqali
o'rnatiladi). Agar import modul boshida bo'lsa, bu kutubxonalar yo'q
muhitda (masalan lokal Windows kompyuterda) `services/ticket_service.py`ni
import qiladigan HAR QANDAY kod — demak butun bot — ishga tushmasdan
yiqilardi, garchi ruxsatnoma bilan aloqasi bo'lmasa ham.

## 22. Javob varag'i — mavjud OMR tizimidan butunlay alohida

**Qaror:** yangi `AnswerSheet`/`AnswerSheetSubject` jadvallari `Test` /
`TestResult` / `Orm_Scanner` (bubble-ID'ga asoslangan eski OMR tizimi,
`utils/utility.py`) bilan HECH QANDAY bog'liq emas — na FK, na umumiy kod.

**Nega:** eski tizim ishlab turgan, 340+ yozuvli production ma'lumotga
ega va `Orm_Scanner`ning butun geometriyasi (kesish, doira aniqlash)
qattiq 5-variantli, 2-fanli qog'oz shabloniga moslangan (tashqi, repoda
yo'q shablon). Uni o'zgaruvchan fan/variant soniga moslashtirish uchun
qayta yozish kerak bo'lardi — bu esa ishlab turgan narsani buzish xavfi.

Yangi yo'l butunlay mustaqil: `AnswerSheet` bevosita `Olympiad`ga
bog'lanadi (Test kabi "tekshiruv paytida qo'lda tanlash" emas), ID uchun
ruxsatnomadagi bilan AYNAN bir xil QR/ticket_no ishlatiladi (qarang:
`utils/qr_payload.py`). Hozircha faqat GENERATSIYA qilinadi — QR orqali
o'qib tekshirish alohida, keyingi bosqich.

## 23. Javob varag'idagi savol ustunlari — kenglik emas, balandlik chegarasi

**Qaror:** `services/answer_sheet_service.py -> _subject_columns()` har
bir fanni ko'pi bilan 22 qatorli sub-ustunlarga bo'ladi (masalan 30
savol -> 15+15). Chegara sinov orqali (brauzerda haqiqiy A4 sahifada)
tanlangan — undan ko'p bo'lsa sahifa balandligidan chiqib ketardi.

**Diqqat:** bu sof ko'rinish masalasi, `utils/qr_payload.py`dagi
hech narsaga bog'liq emas — kelajakdagi skaner kod bilan mos kelishi
uchun bu funksiya alohida hujjatlashtirilgan va sinovdan o'tkazilgan
(chegara holatlari: 1, 22, 23, 44, 45, 100 savol — barchasi to'g'ri
va yo'qotishsiz bo'linadi).

## 24. WeasyPrint va pdftoppm'ni Windows'da lokal ishga tushirish

**Muammo:** production server Linux (apt orqali libpango/libcairo/
poppler-utils o'rnatiladi), lekin ko'p ishlab chiquvchi Windows'da
ishlaydi. Ikkalasi ham Windows uchun alohida-alohida muammo:

- WeasyPrint'ning Windows pip paketi Pango/Cairo'ni o'zi bilan olib
  kelmaydi (opencv/pymupdf'dan farqli) → `cannot load library
  'libgobject-2.0-0'`.
- `pdftoppm` (ruxsatnomaning PDF→PNG bosqichi, faqat individual
  yuborishda ishlatiladi — ommaviy PDF eksportida YO'Q) Windows'da
  umuman o'rnatilmagan bo'ladi → `pdftoppm topilmadi`. Bittasi
  tuzatilgani ikkinchisini tuzatmaydi — ikkalasi mustaqil kutubxona.

**Yechim (rasmiy hujjatlardan, docker/WSL/virtualizatsiya SHART EMAS):**

1. [MSYS2](https://www.msys2.org/) o'rnating (standart sozlamalar bilan).
2. MSYS2 terminalida: `pacman -S mingw-w64-x86_64-pango`
3. `.env` fayliga qo'shing: `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin`
4. `pdftoppm` uchun: [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)
   dan oxirgi relizni yuklab, biror joyga chiqaring (masalan `C:\poppler`).
5. `.env` fayliga qo'shing: `PDFTOPPM_PATH=C:\poppler\Library\bin\pdftoppm.exe`
   (qarang: `config.py` — standart qiymat oddiy `"pdftoppm"`, faqat
   production'da PATH orqali topiladi; Windows'da to'liq yo'l ko'rsatish
   tizim PATH'ini o'zgartirishdan qochadi).

Docker yoki WSL orqali sinash HAM mumkin (qarang: `Dockerfile.localtest`,
production bilan bir xil Linux muhitni beradi) — lekin bu uchun
virtualizatsiya yoqilgan bo'lishi kerak (BIOS/UEFI darajasida), bu esa
har doim ham oson emas (masalan korporativ/cheklangan noutbuklarda).
Yuqoridagi yo'l hech qanday virtualizatsiya yoki admin huquqisiz ishlaydi.

## 25. Javob varag'i: belgilash zonasini rasm qilib keshlash

**Muammo:** ommaviy javob varag'i eksporti amalda ishlatib bo'lmas
darajada sekin edi. O'lchandi: bitta ishtirokchi uchun to'liq sahifani
(bubble to'ri jonli chizilgan holda) WeasyPrint bilan render qilish —
**308.43 soniya**. 23 ta ishtirokchi uchun bu ~2 soatga cho'zilardi (aslida
hech qachon tugallanmadi — sinovlarda 180s dan keyin ham tugamagan).
Sabab aniqlandi: Jinja2+QR generatsiyasining o'zi 23 ta yozuv uchun bor-yo'g'i
0.374s — sekinlik WeasyPrint'ning CSS box-layout dvigateli minglab alohida
uslublangan doiralik `<span>` elementini (bitta javob varag'ida 7000+ bubble)
joylashda "qoqilib qolishi"da edi, Python tomonida emas.

**Qaror:** fan tarkibi (nechta fan, savol/variant soni) bitta olimpiadaning
BARCHA ishtirokchisida bir xil — faqat sarlavhadagi ism/familiya/sana/sinf/QR
har kimda boshqacha. Shuning uchun bubble to'rini ("belgilash zonasi") har
o'quvchi uchun qayta chizish o'rniga, uni fan sozlamasi saqlanganda
(`handlers/admin.py -> as_save`) BIR MARTA PNG rasm qilib chizib, `AnswerSheet.
marking_area_png` ustunida keshlaymiz. Ommaviy eksportda (`export_answer_sheets_
zip`) har bir ishtirokchi shablonda shu tayyor rasmni oladi (`.marking-area.
cached img`) — bubble DOM umuman yaratilmaydi.

**Amalga oshirish:**
- Kesh generatsiyasi izolyatsiya qilingan, sarlavhasiz shablonda bajariladi
  (`marking_area_only.html`, aniq `192mm x 190mm` sahifa, `@page margin:0`) —
  natijada PNG asosiy shablondagi belgilash zonasi joyiga piksma-piksel mos
  tushadi. CSS (`marking_area.css`) va bubble-loop (`_marking_area_content.html`)
  ikkala shablon ("to'liq" va "faqat-kesh") orasida umumiy — ikkalasi bir xil
  chiqishi SHART.
- `.marking-area` balandligi endi QAT'IY `190mm` (avvalgi `flex:1` emas) —
  sarlavha (`.top`...`.footer-note`) hech qachon ~85mm dan oshmasligi
  sinovda tasdiqlangan (279mm - 85mm = 194mm > 190mm, xavfsiz zaxira bilan).
  Balandlik QAT'IY bo'lishi SHART edi — aks holda kesh rasmi har safar
  boshqacha o'lchamda chiqib, joyiga mos tushmasdi.
- `.marking-area.cached` konteynerida chegara (border) YO'Q — u allaqachon
  keshlangan rasmning o'zida chizilgan (chunki `marking_area_only.html`
  butun sahifani egallaydi). Wrapperga yana chegara qo'shish uni ikki marta
  chizardi (bir-birining ustiga to'liq mos tushib, ko'zga unchalik
  ko'rinmasa ham, keraksiz va noaniq edi).
- Kesh yo'q eski yozuvlar uchun (masalan bu ustun qo'shilishidan oldin
  sozlangan) shablon avtomatik eski jonli-chizish yo'liga qaytadi (`{% if r.
  marking_area_image %}...{% else %}...{% endif %}`) — hech narsa buzilmaydi,
  faqat sekinroq bo'ladi. Admin xabar orqali qayta sozlashga undaladi.

**Natija (o'lchandi):**
- Kesh generatsiyasi (bitta olimpiada uchun, sozlash vaqtida, BIR MARTA):
  ~121.78s (3 fan, 30+25+20 savol) — 1 sahifaga sig'ishi tasdiqlandi
  (`pdfinfo`: Pages: 1).
- Ommaviy eksport (kesh bilan), 23 ta ishtirokchi: **128.51s jami**
  (~5.6s/ishtirokchi) — avvalgi ~308s/ishtirokchidan ~55 baravar tezroq.
  Qolgan vaqt asosan har sahifadagi sarlavha/QR/rasm joylashuvi va
  WeasyPrint'ning umumiy hujjat parsing xarajati — bubble DOM endi yo'q.
- Sozlash oqimi (`as_save`) endi menyuni DARHOL qaytaradi (kesh
  generatsiyasi fonda davom etadi, natija alohida xabar bilan keladi) —
  admin ~2 daqiqa kutib turishga majbur emas.

## 26. Ikki bosqichli ro'yxatga olish: Ro'yxatdan o'tgan -> Ishtirokchi

**Qaror:** Olimpiadaga ro'yxatdan o'tish endi YAKUNIY emas — bu faqat
1-bosqich ("Ro'yxatdan o'tgan"). 2-bosqich: o'quvchi ruxsatnoma bilan
Smart Academyga keladi, reception uning ID raqamini (ruxsatnomadagi QR
ostidagi matn, `ticket_no`) botga kiritadi, vaqt va xona tanlaydi —
shundagina u "Ishtirokchi" bo'ladi. **Javob varag'i endi FAQAT
Ishtirokchilar uchun generatsiya qilinadi** (`OlympiadResult.attended_at`
to'ldirilgan qatorlar) — ruxsatnomani esa har bir o'quvchi ro'yxatdan
o'tishi bilan botdan O'ZI oladi (qarang: DECISIONS.md #27), chunki
ruxsatnomasiz reception'ga kelib bo'lmaydi.

**Ma'lumot modeli:** `OlympiadTimeSlot` va `OlympiadRoom` — har ikkalasi
ham olimpiadaga bog'langan, sozlashda (bir marta yoki qayta) kiritiladi.
`OlympiadResult`ga uchta ustun qo'shildi: `time_slot_id`, `room_id`,
`attended_at`. **DIQQAT:** `attended_at` allaqachon mavjud bo'lgan
`checked_at`dan BUTUNLAY BOSHQA narsa — `checked_at` natija TEKSHIRILGAN
vaqt (baholash), `attended_at` esa ishtirokchi FIZIK QABUL QILINGAN vaqt
(reception). Ataylab boshqa nom tanlandi, aralashib ketmasligi uchun.

**Xona sig'imi HAR (xona, vaqt) juftligi uchun alohida hisoblanadi** —
bitta xona kunning turli vaqtlarida turli guruhlarni qabul qilishi mumkin
(masalan 8:00-9:30'da 1-guruh, 10:00-11:30'da 2-guruh, ikkalasi ham
sig'imni to'ldirishi mumkin, bir-biriga aloqasi yo'q). Amalga oshirish:
`checkin_show_rooms` har safar `COUNT(OlympiadResult WHERE room_id=R AND
time_slot_id=T)` ni jonli hisoblaydi (keshlanmagan sonlar — kam yozuv
sonida bu arzon, keshlashga hojat yo'q) va `capacity`dan oshgan xonalarni
inline klaviaturadan chiqarib tashlaydi.

**Qayta belgilash (reassignment):** bitta ID ikkinchi marta kiritilsa
(allaqachon xona/vaqt olgan bo'lsa), joriy taqsimot ko'rsatiladi va admin
xohlasa YANGISINI tanlab qayta saqlashi mumkin. Sig'im hisoblashda
o'zining ESKI yozuvi HISOBGA OLINMAYDI (`OlympiadResult.id != result_id`
shart) — aks holda o'quvchi o'z joyiga qaytishga harakat qilganda "xona
to'lgan" deb noto'g'ri rad etilardi.

**FK EMAS ataylab:** `OlympiadResult.time_slot_id`/`room_id` SQLAlchemy
darajasida `ForeignKey` sifatida e'lon qilinmagan (`ticket_no`dagi kabi —
unique indeks ham modelda emas, faqat `db.py`dagi xom SQL orqali). Sabab:
vaqt/xona sozlamasi qayta kiritilganda (masalan xona soni o'zgarganda)
eski `OlympiadTimeSlot`/`OlympiadRoom` qatorlari o'chiriladi — agar haqiqiy
DB FK bo'lganida, bu o'chirish yo AVTOMATIK CASCADE bilan ishtirokchining
BUTUN yozuvini o'chirib yuborardi (yomon), yoki DB darajasidagi
`ON DELETE SET NULL` sozlashni talab qilardi (bu loyihada hech qachon
ishlatilmagan, murakkab idiom). Buning o'rniga `_save_checkin_config_and_
continue` eski qatorlarni o'chirishdan OLDIN mos `OlympiadResult`
yozuvlarini aniq `UPDATE ... SET time_slot_id = NULL` bilan tozalaydi —
`attended_at` (Ishtirokchi holati) esa TEGILMAYDI, faqat aniq xona/vaqt
ma'lumoti yo'qoladi. Bu DECISIONS.md #1 dagi "o'chirish emas, aniq
boshqarish" falsafasiga mos (garchi bu yerda "o'chirish" chetdan kelayotgan
bo'lsa ham, natija bir xil: hech narsa kutilmaganda yo'qolmaydi).

**Yangi rol: Reception.** Tizimdagi 6-rol — FAQAT ishtirokchini qabul
qilish (`utils/roles.py`). Natijalar, Excel, reklama kabi boshqa hech
narsaga tega olmaydi. `ASSIGNABLE_ROLES`/`ROLE_LABELS`ga qo'shilgani bilan
SuperAdmin panelidagi xodim qo'shish/ro'yxat/o'chirish oqimlarining
BARCHASI avtomatik ishlay boshladi (ular butunlay ma'lumotga asoslangan,
`handlers/superadmin.py`da rolga qarab shart yo'q). Admin/SuperAdmin ham
qabul qilish funksiyasidan foydalana oladi (Olimpiada tafsilotlaridagi
"✅ Ishtirokchini qabul qilish" tugmasi orqali) — Reception esa faqat shu
BITTA tugmani ko'radi va bosganda avval olimpiada tanlash so'raladi
(chunki uning Olimpiada tafsilotlariga umuman kirish huquqi yo'q,
shuning uchun qaysi olimpiada ekanini state orqali bilib bo'lmaydi).

**Tekshirildi:** ticket_no qidiruv (to'g'ri va noto'g'ri olimpiadaga
tegishli holatlar), xona sig'imi to'lganda inline klaviaturadan
chiqarilishi, qayta belgilashda o'z joyiga qaytish bloklanmasligi, javob
varag'i eksporti faqat Ishtirokchilarni olishi, va qayta sozlashda eski
xona/vaqt ma'lumoti tozalanib `attended_at` saqlanib qolishi — barchasi
haqiqiy bazaga qarshi (yozuvlar oxirida orqaga qaytariladigan tranzaksiya
ichida) sinovdan o'tkazilgan.

## 27. Javob varag'i: bo'sh shablon + PyMuPDF shtamplash

**Muammo:** #25 dagi rasm-kesh yordam berdi (308s/o'quvchi -> ~5.6s), lekin
har o'quvchi uchun WeasyPrint baribir butun sahifani qaytadan
joylashtirardi. 200 ta ishtirokchi ~19 daqiqa olardi.

**Qaror:** WeasyPrint per-o'quvchi yo'ldan BUTUNLAY olib tashlandi.

1. **Bo'sh shablon** — fan sozlanganda (`as_save`) yoki eksportda topilmasa,
   WeasyPrint bitta A4 sahifa chizadi: sarlavha, ramkalar, doiralar to'ri —
   hammasi, faqat ishtirokchi maydonlari bo'sh. PDF baytlari
   `AnswerSheet.blank_pdf` da saqlanadi.
2. **Shtamplash** — eksportda PyMuPDF shu sahifani har o'quvchi uchun
   ko'rsatib, ustiga faqat ism/familiya/sana/sinf matni va QR rasmini
   qo'yadi.

`pymupdf` allaqachon `requirements.txt` da bor edi (PDF->rasm uchun), ya'ni
yangi bog'liqlik qo'shilmadi.

**Koordinatalar qayerdan olinadi:** shablonda maydonlar ichida `@I@`, `@F@`,
`@K@`, `@O@`, `@Y@`, `@S@` ko'rinishidagi **oq rangli** (ko'rinmas) orientir
matnlar turadi. PyMuPDF `search_for` bilan ularni topadi, keyin
`get_drawings()` orqali o'rab turgan eng kichik to'rtburchakni (ya'ni
katakchaning o'zini) aniqlaydi — matn shunga qarab chapga tekislanadi yoki
markazlashtiriladi. QR o'rni esa sahifadagi yagona 32mm li rasm bo'yicha
topiladi (logotip 13mm). Natija JSON bo'lib `AnswerSheet.field_boxes` da
`blank_pdf` bilan BIRGA saqlanadi — bittasi eskirsa matn noto'g'ri joyga
tushardi.

**Orientirlar QISQA bo'lishi shart:** dastlab `@@KUN@@` ishlatilgan edi va
10mm li sana katakchasiga sig'may ikki qatorga bo'linib ketdi — `search_for`
uni umuman topa olmadi.

**Shrift:** shtamplashda PyMuPDF ichiga qurilgan Helvetica-Bold (`hebo`)
ishlatiladi — tizim shriftlariga bog'liq emas, Windows va Linux'da bir xil.
Uzun familiya katakchaga sig'masa, shrift o'lchami avtomatik kichraytiriladi
(`get_text_length` bilan o'lchab).

**`show_pdf_page`, `insert_pdf` EMAS:** birinchi variantda har sahifaga bo'sh
sahifaning to'liq nusxasi yozilardi va 200 ta ishtirokchida fayl **32MB**
gacha shishardi (Telegram chegarasi 50MB). `show_pdf_page` hamma sahifani
bitta umumiy XObject'ga havola qiladi — o'sha fayl endi **1.3MB**.

**Zaxira yo'l YO'Q:** shablon topilmasa, eksport uni o'sha yerda majburiy
chizib, saqlab, keyin davom etadi. Avvalgi "sekin-lekin-to'g'ri jonli
chizish" yo'li olib tashlandi — u shunchaki sekin variantni yashirib
qo'yardi.

**Yon natijalar:**
- Doiralar endi **vektor** (avval 200 DPI rasm edi) — chop etishda aniqroq.
- `.marking-area` balandligi endi `flex: 1` (avval qat'iy 190mm edi va
  sarlavha bilan qo'shilib 279mm dan oshib, varaq ikkinchi sahifaga tushib
  ketardi). Endi sahifa har doim bitta.
- Doira o'lchami/oraliqlari fan va variant soniga qarab Python'da
  hisoblanadi (`_compute_layout`) — qat'iy o'lchamda 3 fan x 5 variant
  varaqqa sig'masdi.
- Sub-ustun kengligi ham Python'da hisoblanib CSS'ga qat'iy beriladi:
  WeasyPrint flex elementining ichki kengligini Chrome'dan boshqacha
  hisoblaydi va 2-ustunning savol raqamini 1-ustunning oxirgi doirasi
  USTIGA chiqarib yuborardi.
- `marking_area_png` ustuni endi ishlatilmaydi (o'chirilmadi — qoida
  bo'yicha ustun o'chirilmaydi).

**Natija (o'lchandi, 40+30 savol, 2 fan):**
- Bo'sh shablon: ~90 soniya, olimpiadaga BIR MARTA.
- Shtamplash: **~46 ms/o'quvchi**. 200 ta ishtirokchi — **9.3 soniya, 1.3MB**
  (avval ~19 daqiqa). O'quvchi boshiga ~120 barobar tez.

## 28. Javob varaqlari vaqt va xona bo'yicha beriladi

**Qaror:** "📄 Javob varaqlari" tugmasi endi darhol PDF bermaydi — avval
**vaqt oralig'i**, keyin **xona** so'raladi va faqat o'sha (vaqt, xona)
juftligiga biriktirilgan ishtirokchilar uchun generatsiya qilinadi.

**Nega:** varaqlar amalda xonama-xona tarqatiladi. Butun olimpiada uchun
bitta katta PDF berilsa, nazoratchi uni qo'lda ajratib chiqishi kerak
bo'lardi. Vaqt/xona ma'lumoti Reception qabul qilishda allaqachon
yozilgan (DECISIONS.md #26) — shuni ishlatmaslik ma'nosiz edi.

**Amalga oshirish:** FSM holati ISHLATILMAYDI — tanlov `callback_data`
ichida olib yuriladi (`as_slot:{olympiad_id}:{slot_id}` ->
`as_room:{olympiad_id}:{slot_id}:{room_id}`). Sabab: olimpiada menyusi
`OlympiadDetailStates.viewing` holatida turadi va tanlov uchun holatni
o'zgartirsak, admin tanlovni tashlab ketganda menyu tugmalari ishlamay
qolardi.

**Faqat to'ldirilgan variantlar ko'rsatiladi:** ro'yxatlar `INNER JOIN`
bilan hisoblanadi, shuning uchun ishtirokchisi yo'q vaqt/xona umuman
chiqmaydi va tugmada soni yoziladi ("1-xona — 12 ta"). Bo'sh PDF chiqib
qolishi mumkin emas.

**Belgilanmaganlar:** sozlama qayta kiritilganda ba'zi ishtirokchilarning
vaqt/xonasi tozalanishi mumkin (#26). Ular hech qaysi ro'yxatga
tushmagani uchun vaqt tanlash xabarida ularning soni alohida
ogohlantirish bilan ko'rsatiladi.

## 29. Avtomatik tekshirish (OMR): ML emas, geometriya

**Savol:** javob varaqlarini avtomatik tekshirish uchun tayyor model
(deep learning) ishlatilsinmi?

**Qaror: YO'Q.** ML modellari *noma'lum, har xil formatdagi* varaqlar
uchun yaratilgan (adabiyotda 50–97% aniqlik; CNN+OpenCV gibrid ~98%).
Bizda esa varaqni O'ZIMIZ chizamiz — har doiraning joyi bizga ma'lum,
ya'ni bu ko'rish (perception) masalasi emas, geometriya masalasi.
Ma'lum koordinatadan o'qish ~100% aniqlik beradi, o'rgatish ma'lumoti,
GPU va noaniqlik talab qilmaydi.

**Asosiy g'oya:** ochiq kodli OMR loyihalarining deyarli hammasi
doiralarni RASMDAN QIDIRADI (kontur, o'lcham filtri, saralash) — eng
mo'rt qadam aynan shu. Eski `Orm_Scanner` ham shunday edi
(`area > 470000`, `threshold 150`). Bizga bu qadam KERAK EMAS: bo'sh
shablon chizilganda (#27) har doiraning markazi PDF'dan olinib,
`AnswerSheet.bubble_boxes` da JSON sifatida saqlanadi. Tekshiruvchi
doirani qidirmaydi — ma'lum joydan o'qiydi.

**Koordinatalar qanday olinadi** (`extract_bubble_boxes`):
- Doiralar `get_drawings()` dan o'lchami bo'yicha topiladi. WeasyPrint
  har doirani chegara kengligicha (0.85pt) siljigan IKKI kontur bilan
  chizadi, shuning uchun yaqin markazlar birlashtiriladi.
- Fan bloklari savol raqamlari orqali ajratiladi: har fanda «1» aynan
  bir marta uchraydi. **Chegara «1» ning chap chekkasidan emas, raqam
  USTUNINING chap qirrasidan olinadi** — raqamlar o'ngga tekislangani
  uchun «10» ning x0 si «1» nikidan kichik va aks holda keyingi fanning
  ikki xonali raqamlari oldingi blokka tushib qolardi (sinovda ko'rilgan).
- Har savol raqamidan o'ngdagi eng yaqin `choice_count` ta doira — o'sha
  savolniki (keyingi ustun doiralari o'z raqamidan keyin turadi).
- Har qadam qat'iy tekshiriladi (umumiy son, blok soni, har savoldagi
  doira soni, blok ichida raqam takrorlanmasligi). Jimgina noto'g'ri
  koordinata saqlanib, keyin butun sinf noto'g'ri baholanib ketishidan
  ko'ra xato ko'tarilgani xavfsiz.

**Bosib chiqarishdan OLDIN qilingan ikki tuzatish** (keyin o'zgartirish
qimmat — varaqlar qayta bosilishi kerak bo'lardi):

1. **Doira ichidagi harf och kulrang** (`#6b7078`, avval qora edi).
   O'lchandi: bo'sh doiraning qorong'uligi 21/255, to'ldirilgani ~200 —
   ya'ni ~8 barobar farq. Qora harfda bu farq ancha kichik bo'lardi.
   Undan ham ochroq qilish mumkin edi (10/255), lekin o'shanda o'quvchi
   qaysi doira A, qaysi B ekanini o'qiy olmasdi.
2. **Burchak markerlari — ArUco** (oddiy qora kvadrat emas,
   `DICT_4X4_50`, ID: tl=0, tr=1, bl=2, br=3). Har marker o'z ID'sini
   tashiydi, ya'ni varaq teskari yoki burilgan holda skanerlansa ham
   qaysi burchak ekani aniq. Sinovda 100, 150 va 200 DPI da to'rttasi
   ham topildi.

**Sarlavhaga 9mm chekka bo'shliq** qo'shildi: logotip TL marker ustiga
tushib turgan ekan va ArUco uni umuman topa olmagan (faqat 1, 2, 3
topilgan). Marker atrofida oq "sokin zona" bo'lishi SHART.

**Keyingi qadamlar:** rasmni ArUco markerlar bo'yicha to'g'rilash
(homografiya) → QR o'qib o'quvchini aniqlash (`verify_qr_payload`
tayyor) → har doira markazidagi qorong'ulikni o'lchash. To'g'ri javoblar
kaliti alohida, qo'lda kiritiladigan funksiya bo'ladi.

## 30. Eskirgan shablon va ikkilangan doira

Ikkalasi ham jonli sinovda topildi.

### Eskirgan shablon ishlatilib ketardi

**Muammo:** fan sozlamasi qayta saqlangandan keyin ham javob varaqlari
ESKI shablon asosida chiqardi.

**Sabab:** `as_save` fanlarni yangilardi, lekin `blank_pdf` /
`field_boxes` / `bubble_boxes` ustunlariga TEGMASDI. Yangi shablon fonda
chizilardi — agar u xato bersa (yoki bot qayta ishga tushsa, yoki admin
undan oldin eksport qilsa), bazada eski shablon qolib ketardi va
`has_blank` True bo'lgani uchun eksport uni jimgina ishlatib yuborardi.

**Yechim — ikki qatlam:**
1. `as_save` fanlarni yozadigan TRANZAKSIYANING O'ZIDA uchala ustunni
   `NULL` qiladi. Shundan keyin qayta chizish muvaffaqiyatsiz bo'lsa ham,
   eksport shablonni yo'q deb bilib, qaytadan chizadi.
2. Eksportda shablon BOR bo'lishi yetarli emas — u hozirgi sozlamaga MOS
   kelishi ham tekshiriladi (`blank_matches_subjects`): fanlar soni,
   nomlari, tartibi, savol va variant soni. Mos kelmasa qayta chiziladi.
   Yangi ustun kerak emas — bu ma'lumot `bubble_boxes` JSON ichida
   allaqachon bor.

### Doiralar ikki marta chizilardi

**Muammo:** har doira chegara kengligicha (0.85pt) diagonal siljigan
ikkinchi nusxa bilan chizilardi — ko'zga "ikkilangan/soyali" halqa bo'lib
ko'rinardi.

**Sabab (bisekt bilan topildi): WeasyPrint nosozligi** — flex konteyner
ichidagi `display: inline-flex` element IKKI MARTA chiziladi:

| Holat | Chizma (4 ta doira uchun) |
|---|---|
| Doira flex ichida emas | 4 |
| `inline-flex`, flex ichida | **8** |
| `inline-block`, flex ichida | 4 |

**Yechim:** `.bubble` endi `inline-block`, harf esa `line-height` bilan
markazlashtiriladi (o'lchami `_compute_layout` da hisoblanadi). Bu yerda
`inline-flex` ga qaytmang.

**Yon natija:** WeasyPrint ikki barobar ortiqcha ish qilayotgan ekan —
bo'sh shablonni chizish **126s dan 30s ga** tushdi, fayl 156KB dan
120KB ga.

### Qatorlar siqilib, pastdagi joy ishlatilmasdi

**Muammo:** savol ko'p bo'lganda qatorlar zich chizilib, fan blokining
pastida katta bo'sh joy qolardi (o'lchandi: 60 savolda **35.8mm**).

**Sabab:** vertikal bo'shliq doira o'lchamiga bog'langan qat'iy nisbat
edi (`bubble * 0.42`) va mavjud balandlikni umuman hisobga olmasdi.
Bundan tashqari balandlik cheklovidagi `_AREA_H_MM` taxminiy va haqiqiy
joydan ~15mm katta edi.

**Yechim:** `_ROWS_H_MM = 145.0` — bu taxmin emas, chizilgan PDF'dan
o'lchangan (belgilash zonasi 170.4mm, undan ramka/padding va fan
sarlavhasi ayirilgan). Vertikal bo'shliq endi qatorlarni shu balandlikka
TENG TAQSIMLAYDI: `(_ROWS_H_MM - rows*bubble) / (rows - 1)`, eng ko'p
qatorli fan bo'yicha. Pastdan cheklangan (avvalgi zich ko'rinish) va
yuqoridan (kam savolda doiralar haddan tashqari uzoqlashmasin).

Ustunlar blok ichida markazlashtirildi (`justify-content: center`) —
bitta fan bo'lganda blok ustunlardan ancha keng bo'lib, chapga qisilib
turishi noqulay ko'rinardi.

**Natija:** 60 savolda qatorlar 117.4mm o'rniga 145.0mm ni egallaydi.

### Ustunlar bir-biriga yopishib qolardi

Yuqoridagi tuzatish faqat BALANDLIK bo'yicha edi; kenglik bo'yicha
xuddi shu muammo qoldi. `_COL_GAP_MM = 3.5` qat'iy edi, ustun kengligi
esa faqat kerakligicha hisoblanadi — natijada 1 fan × 40 savol × 5
variantda ikki ustun 66.3mm ni egallab, blokning qolgan 113mm i chap va
o'ng chekkada bo'sh qolardi, ustunlar esa o'rtada bir-biriga tegib
turardi (21-savol raqami 20-savolning E doirasi yonida).

`_COL_GAP_MM` endi — ENG KICHIK bo'shliq, haqiqiysi esa ortgan
kenglikdan taqsimlanadi: `(block_inner - cols*col_w) / (cols - 1)`,
yuqoridan `col_w * _COL_GAP_MAX_RATIO` (0.8) bilan cheklangan — ko'z
bitta qatorni kuzatib bora olishi uchun. Chegara HAR fan bo'yicha
alohida hisoblanib, eng kichigi olinadi: CSS qoidasi bitta va u hamma
blokka sig'ishi shart.

Doira o'lchami avvalgidek ENG KICHIK bo'shliq bo'yicha hisoblanadi,
shuning uchun bo'shliqni keyin kattalashtirish sig'imni kamaytirmaydi.
Joy qolmagan (zich) sozlamalarda `col_gap` avvalgi 3.5mm da qoladi —
ya'ni chizilgan shablon bit-ma-bit o'zgarmaydi va allaqachon bosib
chiqarilgan varaqlar o'qilaveradi. Shu sababli `TEMPLATE_VERSION`
ataylab oshirilmadi.

**Natija (o'lchangan):** 1 fan × 40 × 5 — 66.3mm o'rniga 88.0mm;
2 fan (40×5 + 30×4) — 66.3mm o'rniga blokning to'liq 85.3mm i.
Tekshiruv aniqligi o'zgarmadi (40/40).

### "521 ta doira topildi, kutilgani 520 ta"

**Muammo:** doira koordinatalarini ajratishda umumiy son bitta ortiq
chiqib, shablon umuman yaratilmay qolardi.

**Sabab:** doiralar FAQAT o'lchami bo'yicha (±30%) qidirilardi. Savol
ko'p bo'lganda doira kichrayadi va sahifadagi boshqa kichik bezak
shakllardan biri shu oynaga tushib qolishi mumkin.

**Yechim — uch qatlam:**
1. Doira nomzodlari endi **qora rangli** (fill ≈ 0) bo'lishi ham shart —
   rangli bezaklar chiqib ketadi.
2. Nomzodlar faqat **1-savol qatoridan pastda** qidiriladi — butun
   sarlavha qismi umuman hisobga olinmaydi.
3. Umumiy son endi **qat'iy tenglik emas**: kamlik xato (doira
   topilmagan), ortiqchasi esa faqat ogohlantirish — chunki savol
   raqamiga qarab moslashtirish baribir faqat kerakli doiralarni oladi.
   Asosiy kafolat oxirida: **biriktirilgan** doiralar soni kutilganga
   teng va bironta doira ikki marta ishlatilmagan bo'lishi tekshiriladi.

Ya'ni tekshiruv endi "sahifada nechta o'xshash shakl bor" degan mo'rt
mezondan "har savolga to'g'ri doiralar biriktirildimi" degan haqiqiy
mezonga ko'chdi.

## 31. OMR tekshiruvchisi: qaror qoidasi va oqim

`services/omr_checker.py` — rasm -> javoblar. Uch qadam: ArUco markerlar
bo'yicha perspektivani to'g'rilash, QR'dan ishtirokchini aniqlash
(`verify_qr_payload` bilan imzo tekshiriladi), har doiraning
qorong'uligini ma'lum koordinatadan o'lchash (#29).

**Qaror qoidasi — qat'iy chegara EMAS, fondan nisbiy farq.** Avval Otsu
+ absolyut chegara ishlatilgan edi va qorong'i skanda yiqildi: qog'ozning
o'zi qorayganda bo'sh doiralar 111 gacha ko'tarilgan, Otsu chegarasi 113
chiqqan va ba'zi BO'SH doiralar (113.3) "belgilangan" bo'lib qolgan —
natijada savol "ikki marta belgilangan" deb rad etilgan va javob
yo'qolgan.

Endi fon sifatida barcha doiralar qorong'uligining **medianasi** olinadi
(javob berilganda ham doiralarning ko'pi bo'sh qoladi, shuning uchun
mediana doim "bo'sh doira" darajasini ko'rsatadi va yorug'lik bilan
birga suriladi), doira esa fondan `_MIN_CONTRAST = 45` birlik qorong'i
bo'lsa belgilangan hisoblanadi. O'lchandi: to'ldirilgan doira fondan
~135 birlik qorong'i, bo'sh doiralarning o'zaro tarqalishi ~8 birlik.

Savolda bitta doira belgilangan bo'lsa — javob; bir nechtasi bo'lsa
"ko'p belgilangan" (javob hisoblanmaydi, adminga ogohlantirish);
hech biri bo'lmasa — bo'sh.

**Sinovdan o'tgan holatlar:** toza skan, perspektiva+burilish, qorong'i
+shovqinli, 90° va 180° burilgan varaq, xira qalam, yarim to'ldirilgan
doira, chaplab belgilangan, 0.45x kichraytirilgan rasm — barchasida
100% to'g'ri. Bo'sh varaqda bitta ham soxta javob topilmaydi, markerlar
ko'rinmasa aniq xato beriladi.

**Javob kaliti QO'LDA kiritiladi** — `AnswerSheetSubject.answer_key`,
mavjud `normalize_answers` formatida ("A,B,C,D"). Har fan uchun alohida
so'raladi, uzunligi savol soniga va harflari variant soniga tekshiriladi.

**Ustiga belgilangan varaq** ham qaytariladi (bitta PDF, har varaq alohida
sahifada) — eski tekshiruvchidagi bilan BIR XIL rang konvensiyasi:
🟢 o'quvchi to'g'ri belgilagan, 🔴 noto'g'ri belgilagan, 🔵 to'g'ri javob
qayerda edi; yuqori o'ng burchakda fanlar bo'yicha ball va ID. Rasm PNG
emas, JPEG (0.75x kichraytirilgan) — PNG'da bitta varaq ~600KB bo'lib,
100 ta varaqda fayl Telegram chegarasidan (50MB) oshib ketardi; JPEG
bilan ~300KB, ya'ni 100 varaq ~30MB.

**Natija ESKI tekshiruvchi bilan BIR XIL sxemada yoziladi**, chunki Excel
hisoboti ham, o'quvchiga ko'rsatiladigan natija ham QAT'IY kalitlarga
tayanadi (`detail` ichida "matematika"/"ingliz_tili", hamda
`math_correct`/`math_total`/`english_correct`/`english_total` ustunlari).
Fan nomi erkin matn bo'lgani uchun (masalan "Ingiliz tili" deb xato
yozilishi mumkin) moslashtirish NOM bo'yicha emas, **TARTIB** bo'yicha
qilinadi: 1-fan -> matematika joyi, 2-fan -> ingliz tili joyi. Uchinchi
fan bo'lsa, u faqat `detail` ichida o'z nomi bilan saqlanadi (eski Excel
sxemasida uchinchi fan uchun ustun yo'q).

Tekshiruvdan keyin **o'rinlar qayta hisoblanadi** (`recalculate_olympiad_
places`), har sinf ichida alohida — eski oqimdagi kabi.

**Dublikat himoyasi:** `checked_at` allaqachon to'ldirilgan bo'lsa, natija
QAYTA YOZILMAYDI va adminga "allaqachon tekshirilgan (sana)" deb
ko'rsatiladi. Bitta PDF ichida takrorlangan sahifa ham, faylni qayta
yuborish ham shu bilan qoplanadi — aks holda birinchi tekshiruv jimgina
almashib ketardi.

**Natija** `OlympiadResult` ga yoziladi: `score` (to'g'ri javoblar soni),
`percentage`, `checked_at` va `detail` — mavjud Excel oqimidagi bilan
BIR XIL shaklda (`{fan_slugi: [{range, correct, total, score}]}`),
shuning uchun natijalarni ko'rsatish va eksport qismlari o'zgarishsiz
ishlayveradi.

## 32. QR ostida ishtirokchi raqami + shablon versiyasi

**Qo'shildi:** javob varag'ida QR kod ostida ishtirokchi raqami
(`ticket_no`) ham matn ko'rinishida chiqadi. Sabab: QR dog' tushsa yoki
burchak bukilsa o'qilmay qoladi — o'shanda operator raqamni QO'LDA
kiritib, varaqni o'quvchiga bog'lay oladi (ruxsatnomadagi bilan bir xil
mantiq).

Raqam har o'quvchida boshqacha, shuning uchun u SHTAMPLANADI (#27), ya'ni
shablonda `@ID@` orientiri va o'z katakchasi (`.qr-id`) turadi. Katakcha
KERAK: usiz eng kichik o'rab turgan chizma butun `.info-box` bo'lib
qolardi va matn QR ostiga emas, info-box o'rtasiga markazlashardi. Uzun
raqam 32mm ga sig'masa, shrift avtomatik kichrayadi.

**Shablon versiyasi (`TEMPLATE_VERSION`).** Shablonga yangi MAYDON
qo'shilganda fan sozlamasi o'zgarmaydi, shuning uchun
`blank_matches_subjects` (#30) buni sezmaydi — bazadagi eski shablon
ishlatilaverib, ID umuman chiqmasdi. Endi `field_boxes` ichida versiya
saqlanadi va eksportda `blank_is_current` bilan tekshiriladi: versiya
eski bo'lsa shablon qayta chiziladi. Shablon tarkibi kelajakda
o'zgarganda shu raqamni oshirish kifoya.

## 33. Baholash mezoni va Excel sarlavhalarining ma'lumotdan kelishi

**Mezon.** Javob kaliti kiritilgandan keyin har fan uchun baholash mezoni
ham so'raladi (`AnswerSheetSubject.rubric`). Format `Test.math_rubric`
bilan BIR XIL, shuning uchun `utils/utility.py -> apply_rubric`
o'zgarishsiz ishlatiladi va parser ham mavjud (`_parse_rubric_input`).
Mezon kiritilmasa (`-`) — eskicha: 1 to'g'ri javob = 1 ball.

Oraliqli mezonda savollar TO'LIQ qamrab olinishi tekshiriladi — aks holda
ba'zi savollar ballsiz qolib ketardi va buni keyin sezish qiyin bo'lardi.

Tekshirishda har fan uchun `mask` (savolma-savol to'g'ri/noto'g'ri)
tuziladi va `apply_rubric` og'irlikli ball hamda oraliqlar tafsilotini
qaytaradi. `score` endi og'irlikli ball, `percentage` esa
`ball / maksimal ball`.

**Mezonsiz fanga tafsilot YOZILMAYDI.** Avval sun'iy "1-40" bloki
yozilgan edi va Excel'da mezonsiz fan ham "1-40-savollarga 1 balldan
jami 40 ball" ko'rinishiga o'tib ketardi. Endi eski oqimdagidek oddiy
"To'g'ri / Jami" ustunlari chiqadi. Bitta varaqda mezonli va mezonsiz
fan aralash bo'lishi mumkin.

**Excel sarlavhalari endi olimpiadaning o'z ma'lumotidan keladi:**
- Fan ustunlari sarlavhasi — `AnswerSheetSubject.name` dan
  (`_write_results_sheet(..., subject_labels=...)`). Standart qiymat eski
  Test/Excel oqimlari uchun saqlangan, ya'ni ular o'zgarishsiz ishlaydi.
- Oraliq sarlavhalari ("1-10-savollarga 1,5 balldan jami 15 ball") —
  `_ball_header_text` allaqachon `detail` dagi `points_per_q`/`total` dan
  hisoblaydi, ya'ni mezon o'zgarsa sarlavha ham o'zi o'zgaradi.

## 34. Olimpiadadan tashqari javob varag'i: yaratish va tekshirish

**Muammo.** Javob varag'i (QR + ArUco + avtomatik tekshiruv) faqat
olimpiada ichida ishlardi. "📝 Testlarni tekshirish" bo'limida esa eski,
bubble-ID'ga asoslangan `Orm_Scanner` oqimi turardi — u boshqa shakldagi
varaqni o'qiydi va yangi varaq bilan hech qanday aloqasi yo'q. Oddiy
nazorat ishi uchun olimpiada yaratish esa mantiqsiz.

**Qaror.** Varaqning O'ZI (shablon, koordinatalar, OMR) o'zgarishsiz
qoldirildi — `services/answer_sheet_service.py` va
`services/omr_checker.py` ikkala oqimga ham xizmat qiladi. Yangisi faqat
"egasi" qatlamini almashtiradi: olimpiada/ro'yxat o'rniga o'z nomi bilan
yashaydigan `TestSheet`.

Uchta jadval qo'shildi (`test_sheets`, `test_sheet_subjects`,
`test_sheet_participants`) — `AnswerSheet`/`AnswerSheetSubject` bilan
bir xil ustunlar, farqi ikkitasi:

- `TestSheet.with_participants` — varaq rejimi (pastda);
- `TestSheetParticipant` `users` jadvaliga BOG'LANMAYDI. Bu odamlar
  botda ro'yxatdan o'tmagan bo'lishi mumkin — ular shunchaki qog'ozda
  test yozadi, shuning uchun `user_id` ham, `chat_id` ham yo'q.

### Ikki rejim

**`with_participants = False` — bitta bo'sh varaq.** Ism/familiya/sana/
sinf katakchalari bo'sh, QR o'rnida esa "QR KOD / shu yerda" degan
chiziqli belgi turadi (`utils/assets/answer_sheet/qr_slot.png`). Admin
uni xohlagancha ko'paytirib chop etadi. Tekshirilganda natija hech
kimga yozilmaydi — kim yozgani noma'lum — va faqat ustiga belgilangan
PDF qaytadi. Buning uchun `check_sheet(..., require_ticket=False)`
qo'shildi: QR topilmasa xato bermay, `ticket_no` bo'sh qoladi.

**`with_participants = True` — ishtirokchi bo'yicha.** Ro'yxat Excel
orqali kiritiladi (namuna faylni botning o'zi beradi:
`services/test_sheet_excel.py`, ustunlar № | Ism | Familiya | Tug'ilgan
sana | Sinf — ya'ni varaqdagi maydonlarning o'zi, ortiqchasi emas). Har
kishiga o'z ma'lumoti va QR'i bosilgan alohida sahifa chiqadi.
Tekshirilganda natija `TestSheetParticipant`ga yoziladi va natijalar
Excel'i beriladi.

`ticket_no` olimpiadadagi bilan bir xil formatda
(`utils/qr_payload.py`), lekin kodi `TS{sheet_id}` — shu bilan
olimpiada ID'lari bilan hech qachon to'qnashmaydi.

### Nima QAYTA ISHLATILDI, nima yangi yozildi

Qayta ishlatildi: shablon chizish va shtamplash, doira koordinatalarini
ajratish, OMR qarori, `apply_rubric`, `_subject_blocks`,
`_ball_header_text` va Excel uslub konstantalari, javob kaliti/mezon
kiritish qoidalari (#33).

Yangi yozildi faqat `_ts_write_results_sheet`. Sababi —
`_write_results_sheet` qat'iy IKKI fanga moslangan
(`math_*`/`english_*` ustunlari va "matematika"/"ingliz_tili"
kalitlari) va "Telegram Chat ID" ustuni bor. Mustaqil varaqda fan 1-3 ta
bo'lishi mumkin va chat ID yo'q. Ishlab turgan olimpiada eksportini
umumlashtirib buzish o'rniga, yonига fan soniga befarq ikkinchi yozuvchi
qo'yildi; past qatlam (blok hisobi, sarlavha matni, ranglar) umumiy
qoldi, shuning uchun ikkala Excel bir xil ko'rinadi va #33 dagi qoida —
sarlavhalar ma'lumotdan kelib chiqishi — bu yerda ham amal qiladi.

Shu sababli `TestSheetParticipant.detail` olimpiadadagidan boshqacha
saqlanadi: qat'iy ikki kalit o'rniga fanlar TARTIBI bo'yicha ro'yxat —
`{"subjects": [{"name", "correct", "total", "blocks"}]}`.

### Yo'l-yo'lakay tuzatilgan narsa

`.ph` (ko'rinmas orientir matn) rangi `#ffffff` edi, katakcha foni esa
`#FAFAFE` — olimpiada varag'ida buning ahamiyati yo'q edi, chunki ustiga
ism shtamplanardi. Bo'sh varaqda esa "@I@", "@ID@" kabi belgilar xira
arvoh bo'lib ko'rinib qoldi. Rang aynan fon rangiga tenglashtirildi;
matn qatlamida qolgani uchun `page.search_for()` baribir topadi.

## 35. Eski (bubble-ID) tekshiruvchi butunlay olib tashlandi

Bir vaqtning o'zida ikkita tekshiruv tizimi ishlab turardi:

| | Eski | Yangi |
|---|---|---|
| Varaqni kim chizgan | tashqarida, qo'lda | botning o'zi |
| O'quvchi ID si | doiralar bilan kodlangan | QR (HMAC imzoli) |
| Burchak orientirlari | yo'q (qat'iy kesish) | ArUco 4 ta |
| Fan soni | qat'iy 2 ta (matematika/ingliz) | 1-3 ta, nomi ixtiyoriy |
| Baholash mezoni | bor | bor |
| Kod | `Orm_Scanner` (~300 satr) + ~1400 satr handler | `omr_checker.py` + varaq oqimlari |

Yangi tizim eskisining hamma ishini bajaradi va ustiga qo'shimcha
imkoniyat beradi, eskisi esa kodning beshdan bir qismini egallab turardi.
Ikkisini parallel saqlash hech narsa bermasdi: bir xil menyuda ikki xil
"tekshirish" tugmasi turishi adminni chalg'itardi, har o'zgarish esa ikki
joyda o'ylashni talab qilardi.

**O'chirildi:** `Test`, `TestResult` modellari; `Orm_Scanner`;
`utils/pdf_convertor.py`; `TestCreationStates`/`TestEditingStates`/
`TestCheckingStates` va ular bilan bog'liq hamma handler (javob kaliti
qo'shish/tahrirlash/o'chirish, PDF Scan tekshirish, testlar tarixi
Excel'i, o'quvchidagi "Mening natijalarim"); `_scan_page_sync`,
`_format_problem_report`, `_safe_call`, `_logo_html` kabi faqat shu
oqimga xizmat qilgan yordamchilar. Jami ~2000 satr.

**Saqlab qolindi:** `_parse_rubric_input` va baholash mezoni mantig'i
(yangi oqim ham ishlatadi), `apply_rubric`, natijalar Excel'ining
uslubi va blok hisobi, belgilash ranglari (admin ko'nikkan ko'rinish).

**Bazaga tegilmadi.** `tests` va `test_results` jadvallari Postgres'da
o'z ma'lumoti bilan turibdi — "hech qachon DROP qilinmaydi" qoidasi
(DATABASE.md) ularga ham tegishli. Modellar va migratsiyalar olib
tashlandi, ya'ni bot ularga umuman murojaat qilmaydi; kerak bo'lsa eski
natijalarni SQL bilan o'qib olish mumkin.

**O'qituvchi roli.** O'qituvchining paneli faqat eski tekshiruvchidan
iborat edi. Uning huquq DARAJASI o'zgartirilmadi — aynan o'sha ish
(varaq tayyorlash va tekshirish) endi yangi tugmalar orqali bajariladi,
shuning uchun yangi oqimlar `is_admin_or_superadmin` emas,
`can_manage_tests` (Admin + SuperAdmin + O'qituvchi) bilan qo'riqlanadi.

### Yo'l-yo'lakay topilgan ikki jiddiy xato

Tekshiruv oqimini o'qib chiqishda ikkita ishlab chiqarish xatosi topildi
— ikkalasi ham eski kodda ham, yangisida ham bor edi:

**1. Xotira.** `images_from_bytes` PDF ning HAMMA sahifasini bir yo'la
ro'yxatga yig'ardi. 200 DPI da bitta A4 sahifa ~11 MB, ya'ni 50
sahifalik skan 0.5 GB dan oshadi va 1 GB li serverda systemd botni
o'ldiradi. Endi sahifalar birma-bir o'qiladi (`sheet_page_count` +
`sheet_page_image`), xotirada doim bitta sahifa turadi.

**2. Telegram 50 MB chegarasi.** Belgilangan varaq ~180 KB (JPEG), ya'ni
~280 sahifadan keyin natija fayli chegaradan oshib, jo'natish JIMGINA
yiqilardi. Endi fayl 40 MB dan oshmaydigan bo'laklarga bo'linadi
(`_send_annotated_sheets`).

## 36. "Lokalda ishlaydi, serverda ishlamaydi": shrift va ko'rinmas orientirlar

**Belgi.** Serverda varaq shabloni tayyorlanmadi:

```
Bo'sh shablonda '@K@' orientiri 0 marta topildi (aynan 1 ta bo'lishi kerak).
```

Lokal (Windows) mashinada xuddi shu kod, xuddi shu sozlama bilan
muammosiz ishlaydi.

**Sabab.** Shablon `font-family: 'Noto Sans', sans-serif` so'raydi.
Serverda `fonts-noto` o'rnatilgan, ya'ni HAQIQIY Noto Sans ishlatiladi.
Windows'da esa u yo'q va WeasyPrint `Lucida Sans Unicode`ga tushadi —
u torroq. PDF ichidagi shrift ro'yxati buni ochiq ko'rsatadi:

```
WUUHHU+Lucida-Sans-Unicode-Bold      <- Windows render
```

Sana katakchasi 10mm, `box-sizing: border-box` bilan ichki kengligi
9.4mm. Ko'rinmas orientir `@K@` Lucida'da 8.05mm, `@O@` esa 8.48mm
egallaydi — atigi 10-14% zaxira. `@` belgisi deyarli har shriftda eng
keng glifi (~1 em), shuning uchun uch belgili orientir 9.4mm chegarasiga
JUDA yaqin turgan edi. Noto Sans'da u chegaradan oshadi, `.fval` dagi
`overflow-wrap: anywhere` esa matnni ikki qatorga bo'lib yuboradi:
"@K" + "@". Shundan keyin `page.search_for("@K@")` uni topa olmaydi.

Xato aynan shunday takrorlandi: katakcha 7mm ga toraytirilganda
so'zma-so'z o'sha xabar chiqdi.

**Tuzatish.**

1. `.ph { white-space: nowrap; }` — orientir hech qachon bo'linmaydi,
   shriftdan qat'i nazar. Bu asosiy kafolat.
2. Sana katakchasi 10mm -> 13mm (ichki kenglik 12.4mm) — shrift 45%
   kengroq bo'lsa ham ko'rinmas matn chizilgan katakcha ICHIDA qoladi,
   ya'ni `extract_field_boxes` uni to'g'ri `.fval` bilan bog'laydi
   (u matnni O'RAB turgan eng kichik to'rtburchakni qidiradi).
3. `.q-num { white-space: nowrap; }` — savol raqami ham matn sifatida
   qidiriladi (`extract_bubble_boxes`), ustuni esa 4.2mm. Zaxira 31%
   edi, ya'ni bir xil turdagi kutilayotgan xato.

Sinov: orientir o'lchami sun'iy ravishda +29%, +47% va hatto +100% ga
kattalashtirilganda ham `extract_field_boxes` ishlayveradi.

**Qolgan xavf.** Varaqning ko'rinishi Noto Sans'da lokaldagidan biroz
boshqacha bo'ladi (sarlavhalar, yorliqlar). Ajratish (extraction) endi
shriftga BOG'LIQ EMAS — u faqat chizmalar (doiralar, ramkalar), rasmlar
(ArUco, QR o'rni) va bo'linmaydigan qisqa matnlarga tayanadi. Lekin
"lokalda ishlaydi, serverda yo'q" sinfidagi xatoni butunlay yo'q qilish
uchun shriftni loyihaning o'zi bilan birga jo'natish (`@font-face`)
kerak bo'ladi — bu varaqning ko'rinishini o'zgartirgani uchun alohida
qadam sifatida qoldirildi.

Shu sababli PDF o'zgarishlarini deploy'dan oldin `Dockerfile.localtest`
ichida (serverdagi bilan bir xil Linux + `fonts-noto`) sinab ko'rish
tavsiya etiladi — aynan shu xato o'sha yerda ushlanardi.

**Yon tuzatish.** Shablon chizish bir marta yiqilsa, mustaqil varaq
butunlay yaroqsiz qolib ketardi: uni qaytadan chizadigan yo'l yo'q edi
va adminga varaqni boshqatdan yaratishdan boshqa chora qolmasdi. Endi
"\U0001f4c4 Varaqni qayta yuklab olish" tugmasi shablon yo'qligini
sezsa, uni o'zi qaytadan chizadi (olimpiada oqimida allaqachon shunday
edi), varaq kartochkasi esa shablon tayyor emasligini ochiq yozadi.

## 37. Marker sokin zonasi va raqam ustuni kengligi

100 savolli varaqda ikkita xato bir vaqtda chiqdi. Ikkalasining ildizi
bir xil: **joylashuv kenglikni 100% to'ldirar edi, ya'ni hech qanday
zaxira qolmagan edi** — shuning uchun chizishdagi eng kichik farq
(serverdagi kengroq shrift) ni ham ko'tara olmadi.

### A. Pastki markerlar umuman topilmadi

```
❌ Burchak markerlari to'liq topilmadi (yo'q: bl, br).
```

Belgilash zonasining ramkasi **1.4mm qalin** va u 281.0mm da tugagan —
pastki markerlar ham aynan 281.0mm dan boshlanadi. Ikki qora shakl bitta
konturga qo'shilib ketgan, ArUco esa markerni ALOHIDA turgan qora
kvadrat sifatida ko'rishi shart.

Nega lokalda ishlagan: lokal renderda ramka 280.0mm da tugaydi — atigi
**1mm** bo'shliq. Farq footer matnining balandligidan, u esa shriftga
bog'liq (#36).

**Yechim — sokin zona.** Markerlarga 1.6mm oq hoshiya berildi
(`padding` + `background: #fff`, `box-sizing: content-box`, joyi manfiy
siljish bilan saqlangan). Markerlar `position: absolute` bo'lgani uchun
ular oqimdagi ramkadan KEYIN chiziladi, ya'ni oq hoshiya ramka
chizig'ini ustidan yopadi. Bu joylashuvga ham, shriftga ham bog'liq
emas. Qo'shimcha ravishda belgilash zonasiga 2mm pastki bo'shliq
berildi — bu ko'rinish uchun.

### B. Eng o'ngdagi ustun ramka bilan kesilgan

`_NUM_W_MM = 4.2` qat'iy edi. "100" degan uch xonali raqam 2.6mm
shriftda ~5mm joy oladi va ustundan toshib ketadi — natijada butun
blok kengayib, eng o'ngdagi ustunning "D" doirasi ramka bilan kesilgan.

Bu shunchaki ko'rinish masalasi emas: **kesilgan doira ichidan qalin
qora ramka o'tadi va tekshirishda u "bo'yalgan" deb o'qilishi mumkin**,
ya'ni jimgina noto'g'ri natija beradi.

**Yechim:** `num_w` endi eng katta savol raqamidagi belgilar soniga
qarab hisoblanadi (`max_digits * 0.68em * 2.6mm`). 0.68 em va shriftning
eng katta o'lchami ATAYLAB zaxira bilan olingan. 99 tagacha savolli
sozlamalarda natija o'zgarmaydi (4.2mm), 100+ da 5.6mm bo'ladi.

### C. Ildiz sabab: blok kengligi 2.8mm ortiqcha hisoblanardi

A va B tuzatilgandan keyin ham doiralar ichki maydondan 1.5mm chiqib
turardi. Sabab konstantada edi:

```python
# ESKI — faqat padding ayirilgan
_AREA_W_MM = 192.0 - 6.0          # = 186.0
```

`.marking-area` da `border: 1.4mm` ham bor, ya'ni ikki tomondan yana
2.8mm. Haqiqiy ichki kenglik:

```
192 - 2*1.4 - 2*3 = 183.2     (.marking-area ichi)
183.2 - 2*0.6 - 2*2.5 = 177.0 (.subject-block ichi)
```

Joylashuv esa o'zini 179.8mm deb bilardi — **2.8mm ortiqcha**. Zich
sozlamada aynan shu farq eng o'ngdagi ustunni ramka ustiga chiqarib
yuborardi. Endi konstanta CSS bilan aynan mos:

```python
_AREA_W_MM = 192.0 - 2 * _MARKING_PAD_MM - 2 * _MARKING_BORDER_MM
```

Bu qiymatlar CSS bilan BIR XIL bo'lishi shart; `.marking-area` yoki
`.subject-block` ning ramka/padding qiymati o'zgarsa, bu yerdagisi ham
o'zgarishi kerak.

### Umumiy zaxira va ochiq xato

- `_BLOCK_SAFETY_MM = 1.5` — ustunlar orasidagi bo'shliq taqsimlanganda
  shu qadar joy ataylab bo'sh qoldiriladi. Avval taqsimot kenglikni
  aynan 100% to'ldirardi.
- Sozlama blokka sig'masa endi **ochiq xato** ko'tariladi:

  ```
  «A» fani varaqqa sig'maydi: 60 ta savol × 5 ta variant uchun 63mm
  kerak, bor-yo'g'i 54mm joy bor.
  ```

  Avval bunday sozlama (masalan 3 fan × 60 savol × 5 variant, yoki
  1 fan × 200 savol) jimgina kesilgan varaq chiqarardi. Doira o'lchami
  `_BUBBLE_MIN_MM` dan pastga tushirilmaydi — qalam bilan bo'yab
  bo'lmaydigan doira ma'nosiz — shuning uchun bunday sozlama haqiqatan
  ham imkonsiz va buni adminga aytish kerak.

### Shablon versiyasi

`TEMPLATE_VERSION` 2 -> 3. Bazadagi eski shablonlar shu bilan
eskirgan deb belgilanadi:

- **yangi varaq chiqarishda** ("📄 Varaqni qayta yuklab olish",
  olimpiadada "📄 Javob varaqlari") shablon qaytadan chiziladi;
- **tekshirishda** esa eskirganlik TEKSHIRILMAYDI — ALLAQACHON BOSIB
  CHIQARILGAN qog'oz o'sha eski koordinatalarga mos va uni tekshirish
  ishlayverishi kerak.

Varaq kartochkasi bu holatni ochiq yozadi.

---

## 38. "Open App" — SmartAcademy platformasi (Mini App)

Bot endi SmartAcademy-Platform repozitoriysining `smartbot/` papkasida (platformaning
`docs/DECISIONS.md` #27). `PLATFORM_URL` (https) berilsa:

- ishga tushishda hamma chatlarda menyu tugmasi "Open App" bo'ladi
  (`utils/platform.py`, `set_chat_menu_button`);
- /start salomlashuvidan keyin "📱 Open App" inline tugmasi yuboriladi — xodimlar va
  ro'yxatdan o'tganlarga; ro'yxatdan o'tish jarayoni buzilmasin deb, unda yuborilmaydi.

Platforma kimligini o'zi aniqlaydi: Telegram imzosi va shu botning `admins` jadvali hamda
`SUPERADMIN_IDS` (faqat o'qiladi). Bot tomonidan boshqa hech narsa o'zgarmagan; `PLATFORM_URL`
bo'sh bo'lsa bot avvalgidek ishlaydi. Tugma o'rnatilmasa (tarmoq xatosi) bot baribir ishga tushadi.

## 39. Qabulda ishtirokchi rasmi va kirish ruxsatnomasi (A4)

Foydalanuvchi qarori (2026-09-15): qabul qilishda vaqt va xonadan keyin qabulxona ishtirokchining
rasmini yuklaydi, bot rasmli ruxsatnoma yaratib **o'sha chatning o'ziga** yuboradi. Dizayn 4 ta
variantdan tanlangan "A — rasmiy": Prezident maktabi ruxsatnomasi tuzilishi, Smart Academy nomi va
logotipi bilan. Ishtirokchining Telegramiga yuborilmaydi.

- **Oqim:** ID → Davom etish → vaqt → xona → 📷 rasm → qabul saqlanadi → PNG (ko'rish) va PDF (A4,
  chop etish) → keyingi ID. Vaqt, xona va `attended_at` (#26) endi xona tanlanganda emas, **rasm
  qabul qilinganda** yoziladi: "Ishtirokchi" bo'lgan har kishining ruxsatnomasi bor; rasm bosqichida
  bekor qilinsa qabul saqlanmaydi.
- **Rasm saqlanmaydi (#8):** bazada `olympiad_results.photo_file_id` (Telegram file_id). Baytlar
  xotirada 3×4 ga keltiriladi (`utils/participant_photo.py`): keng rasm markazdan, baland rasm
  yuqoriroqdan kesiladi (telefon suratida yuz odatda tepada), EXIF burilishi hisobga olinadi, 200 px
  dan kichigi rad etiladi. Rasm o'rniga fayl ham yuborsa bo'ladi (siqilmagan), rasm bo'lmagan fayl
  rad etiladi.
- **Qayta qabul:** ID qayta kiritilsa, xonadan keyin "🖼 Avvalgi rasm bilan davom etish" tugmasi
  chiqadi — ruxsatnomani qayta olish yoki xonani almashtirish uchun rasmni qayta olish shart emas.
- **PDF/PNG diskka yozilmaydi (#18).** Generatsiya xatosi qabulni bekor qilmaydi: ishtirokchi qabul
  qilingan bo'ladi, qabulxonaga qayta urinish yo'li aytiladi, superadminlarga xabar ketadi.
- **Shablon:** `utils/assets/ruxsatnoma/kirish_ruxsatnomasi.html`, shrift `utils/assets/fonts/`
  dagi DejaVu Sans `@font-face` bilan — tizim shriftiga tayanmaydi, lokal va serverdagi ko'rinish bir
  xil (#36). Uzun vaqt yozuvi ("10:00 - 11:30") kichikroq shriftda. Ro'yxatdan o'tgandagi A5
  ruxsatnoma (#18) o'zgarmagan.
- **Matnlar namuna:** "30 daqiqa oldin", eslatma va ota-onalar bo'limi markaz tasdiqlagach shablonda
  o'zgartiriladi; manzil A5 ruxsatnomadagi bilan bir xil.
- **Sinov:** handlerlar Telegram'siz (soxta Message/Bot, xotiradagi FSM) haqiqiy bazada orqaga
  qaytariladigan tranzaksiya ichida yurgizildi: rasmgacha qabul saqlanmasligi, matn/PDF rad etilishi,
  PNG + bir sahifali PDF yuborilishi, ustunlar yozilishi, avvalgi rasm bilan qayta qabul, buzuq rasm.

## 40. Javob varag'ini platformadagi testdan sozlash

Foydalanuvchi qarori (2026-09-16): "📝 Javob varag'i sozlash" bosilganda, shu olimpiada uchun
platformada test tuzilgan bo'lsa, bot ro'yxat chiqaradi — testni tanlasangiz fan nomi, savollar soni,
variantlar soni va javob kaliti o'zi to'ldiriladi. "✍️ Qo'lda sozlash" avvalgidek joyida.

- **Faqat o'qish:** `services/platform_tests.py` platforma bazasidan `Test` va `Subject` ni o'qiydi
  (`PLATFORM_DATABASE_URL`, read-only foydalanuvchi; platformaning o'z qarori: `docs/DECISIONS.md`
  #32). Sozlanmagan bo'lsa yoki so'rov xato bersa ro'yxat ko'rsatilmaydi va bot avvalgidek qo'lda
  so'rayveradi — ish to'xtamaydi.
- **Kalit:** platformadagi kalit savollar soniga mos kelsa, `AnswerSheetSubject.answer_key` ga vergul
  bilan yoziladi (o'sha formatda, `parse_answer_key` o'qiydi). Mos kelmasa sozlama baribir saqlanadi,
  kalitni esa admin "🔑 Javob kaliti" orqali kiritadi — jimgina noto'g'ri kalit yozilmaydi.
- **Tugma bosilganda test qayta o'qiladi** (`test_by_id`): ro'yxat ochiq turganda test o'zgargan yoki
  o'chirilgan bo'lishi mumkin.
- **Olimpiada bog'lanishi platformada:** test yaratishda olimpiada botdagi ro'yxatdan tanlanadi,
  platforma uning id'sini saqlaydi. Bot esa shu id bo'yicha testlarni topadi.
- **Sinov:** handlerlar Telegram'siz, orqaga qaytariladigan tranzaksiyada yurgizildi — 100 savolli,
  4 variantli test uchun fan/savol/variant to'ldirilishi va 100 harfli kalit (faqat A-D) bazaga
  yozilishi tekshirildi.

## 41. "Farzandlarim": olimpiadaga farzand nomidan yozilish

Foydalanuvchi qarori (2026-09-16): ota-ona farzandlarini bir marta qo'shsin, olimpiadaga esa shu
ro'yxatdan yozdirsin — bir nechta farzandini ham.

- **Bitta joyda:** `👨‍👩‍👧 Farzandlarim` bo'limida farzand qo'shiladi, tahrirlanadi va o'chiriladi
  (`children` jadvali). Olimpiadada endi faqat **sinf rahbari** so'raladi — familiya, ism, tug'ilgan
  sana, maktab va sinf farzand yozuvidan olinadi. Ilgari bularning hammasi har olimpiadada qaytadan
  so'ralardi.
- **Sinf o'zi oshadi:** ota-ona sinfni faqat bir marta kiritadi; u kiritilgan o'quv yili
  (`grade_year`) bilan saqlanadi va joriy sinf har 1-sentabrda hisoblab chiqiladi
  (`utils/utility.py -> current_grade`, 11-sinfdan oshmaydi). Har yili qo'lda yangilash yo'q.
- **Olimpiadaga mos farzandlar:** ro'yxatda faqat olimpiadaning sinflariga to'g'ri keladigan va hali
  yozilmagan farzandlar tugma bo'ladi; qolganlari nega chiqmagani matnda aytiladi.
- **Sinf yozilish paytida nusxalanadi:** `olympiad_results.grade` — o'sha paytdagi sinf. Farzandning
  sinfi keyin oshsa ham, eski olimpiadadagi natija o'z sinfida qoladi.
- **Yagonalik o'zgardi:** eski `uq_olympiad_user` (bitta akkaunt — bitta yozuv) o'rniga ikkita
  QISMAN unique indeks: `uq_olympiad_child` (farzand bir olimpiadaga bir marta) va
  `uq_olympiad_user_self` (child_id bo'sh, ya'ni eski/import qilingan yozuvlar uchun avvalgidek).
  Excel importi ham shu "farzandsiz" yozuvlar ichida takrorlanishni tekshiradi.
- **O'chirish emas, arxivlash:** farzand `archived_at` bilan yashiriladi — uning olimpiada
  natijalari va ruxsatnomalari tarixda qoladi.
- **Eski yozuvlar:** `child_id` bo'sh qatorlar avvalgidek ishlaydi (natija, ruxsatnoma, qabul).
- **Mini App:** platforma bu ro'yxatni faqat o'qiydi (`docs/DECISIONS.md` #33 platforma tomonida).

## 42. "Open App" tugmasi manzil o'zgarganda har bir chatga qayta beriladi

Muammo (2026-09-18): lokal namoyishda "Open App" ishlamay qolgan tunnel manzilini ochdi
(`ERR_NAME_NOT_RESOLVED`), holbuki bot yangi manzilni o'rnatgan edi — `getChatMenuButton` yangi
manzilni ko'rsatardi. Sabab: umumiy (default) menyu tugmasi o'zgarganda Telegram ilovalari
(ayniqsa Telegram Desktop) buni darhol bilmaydi, eski manzilni keshda saqlab qoladi. Tez tunnel
(`trycloudflare.com`) esa har ishga tushishda yangi manzil oladi.

- **Yechim:** bot ishga tushganda (`bot.py`, fonda) tugmani har bir chatga ALOHIDA o'rnatadi
  (`setChatMenuButton` + `chat_id`) — bunday o'zgarishni Telegram o'sha foydalanuvchining
  ilovasiga darhol yuboradi (`utils/platform.py -> sync_menu_buttons`).
- **Faqat kerak bo'lganda:** har chatga oxirgi berilgan manzil `chat_menu_buttons` jadvalida
  saqlanadi; manzil o'zgarmagan qayta ishga tushishda hech narsa yuborilmaydi. Birinchi marta —
  hammaga bir marta (≈20 chat/sekund, fonda, bot ishlashiga xalaqit bermaydi).
- **Kimga:** ro'yxatdan o'tganlar, `admins` jadvali va SUPERADMIN_IDS. Xodimlar ko'pincha
  ro'yxatdan o'tmaydi (`users` da yo'q), lekin "Open App" ni aynan ular ko'p ochadi — shuning
  uchun jadval `users` ga FK emas.
- **Botni bloklagan / chat yo'q:** qayta-qayta urinilmaydi, manzil keyingi o'zgarishda yana
  yuboriladi. Tarmoq xatosi bo'lsa — keyingi ishga tushishda qayta urinadi.
- **PLATFORM_URL olib tashlansa:** bot o'zi bergan chat tugmalari `MenuButtonDefault` ga
  qaytariladi. Umumiy tugmaga tegilmaydi (BotFather'da qo'lda qo'yilgan bo'lishi mumkin).
- **Oqibat:** chat tugmasi umumiy tugmadan ustun turadi — tugmani BotFather orqali emas, faqat
  `PLATFORM_URL` orqali boshqaring. Eski xabarlardagi "📱 Open App" (inline) tugmalarida manzil
  xabar ichida yozilgan, ularni o'zgartirib bo'lmaydi — yangisi `/start` bilan keladi.
- **Butunlay hal bo'lishi:** doimiy manzil — serverdagi domen (docs/DEPLOY.md). Tunnel faqat
  lokal namoyish uchun.

## 43. Online testlar tarixi — chatda xulosa, Excel'da to'liq

Foydalanuvchi so'rovi (2026-09-23): admin online testlar tarixini ko'ra olsin va tugma bosilganda
Excel fayl kelsin.

- **Har bir test alohida** (2026-09-24 da aniqlashtirildi): tugma bosilganda testlar ro'yxati
  chiqadi (ID, nomi, nechta o'quvchi ishlagani) — bittasini tanlaysiz yoki test ID sini yozasiz,
  javob esa faqat o'sha test bo'yicha bo'ladi. Hammasini bitta faylda olish uchun alohida tugma
  bor.
- **Ikkalasi birga:** avval chatda qisqa xulosa (savollar soni, ishlaganlar, o'rtacha va eng
  yuqori foiz, oxirgi 10 ta natija), keyin Excel — kichik savolga javob olish uchun har safar
  fayl ochish shart emas.
- **Ikki varaq:** «Natijalar» — har bir urinish alohida qator (sana, test, o'quvchi, telefon,
  chat id, to'g'ri/jami, foiz, baho, xato savol raqamlari, berilgan javoblar va kalit);
  «Testlar» — har bir test bo'yicha yig'ma (savollar soni, ishlaganlar, o'rtacha va eng yuqori
  foiz, yaratilgan sana, holati).
- **Arxivlangan testlar ham kiradi:** test "o'chirilganda" faqat `OnlineTest.archived` belgilanadi,
  natijalar saqlanib qoladi — tarix esa aynan o'shanda kerak bo'ladi.
- **Baho bir joyda hisoblanadi:** `services/online_test_excel.py -> grade_label` chegaralari
  (90/70/50) o'quvchiga ko'rsatiladigan xabar bilan bir xil — sinov shuni tekshiradi.
- **Diskka yozilmaydi:** fayl xotirada yig'iladi va `BufferedInputFile` bilan yuboriladi (eski
  Excel eksportlari vaqtinchalik fayl yozadi; yangi kod ruxsatnoma naqshiga o'tdi).
- **Chegara:** bitta faylga eng yangi 20 000 urinish kiradi; oshsa admin buni xabarda ko'radi —
  jimgina qirqilmaydi.
- **Baza so'rovi handlerda, yig'ish xizmatda:** shuning uchun fayl bazasiz sinaladi
  (`tests/test_online_test_excel.py`).

## 44. Doiralar to'ri varaqqa moslanadi (belgi doiraning ustiga tushadi)

Muammo (2026-09-23): tekshirilgan varaqda yashil/qizil/ko'k belgilar bosilgan doiradan bir necha
piksel chetga tushgan — qaysi javob belgilangani ko'rinmay qolgan.

Sabab: ArUco markerlari bo'yicha to'g'rilash perspektivani yo'qotadi, lekin qoldiq farq qoladi —
printer varaqni bir necha promille kichraytirib bosadi, skaner cho'zadi, telefonda suratga olinsa
qog'ozning bukilishi qo'shiladi, markerning markazi ham bir-ikki piksel xato topiladi. Shablondagi
koordinata esa o'zgarmaydi. O'lchovda ham xuddi shu xato bor edi — faqat ko'zga tashlanmagan.

- **Yechim:** har doira O'Z JOYI atrofidagi kichik oynadan topiladi
  (`_detect_bubble_center`), keyin uch qatlam: (1) butun varaq uchun bitta tuzatish
  (burilish+masshtab+siljish, RANSAC), (2) topilmagan doira uchun eng yaqin 4 ta topilgan
  doiraning qoldig'i bo'yicha hisoblash — bukilish varaq bo'ylab silliq o'zgaradi,
  (3) doiraning o'zi topilgan bo'lsa — aynan o'sha nuqta.
- **Bo'yalgan doira ataylab o'tkazib yuboriladi:** ruchka dog'ining markazi bosilgan doiraning
  markazi emas (o'quvchi chetroq bo'yaydi). Uning o'rni qo'shnilari bo'yicha qo'yiladi — shunda
  belgi dog'ga emas, doiraning ustiga tushadi.
- **Yondosh matnni chalkashtirmaslik uchun:** kontur o'z aylanasining kamida 55% ini to'ldirishi
  kerak (savol raqami buni bajarmaydi), markaz esa shablon nuqtasidan 0.7 radiusdan uzoq
  bo'lmasligi kerak.
- **Halqa uzilib ketgan bo'lsa** (bukilgan joyda yoki ichidagi harfga yopishganda) qorong'i
  piksellarning og'irlik markazi olinadi — soha har qadamda topilgan markaz atrofiga suriladi,
  aks holda doiraning yarmi kesilib markaz chetga tortilardi.
- **Xavfsizlik:** doira yetarli topilmasa yoki tuzatish radiusning 1.5 barobaridan katta chiqsa —
  shablon koordinatalari o'z holicha ishlatiladi (eski xatti-harakat), ya'ni yomonlashib
  ketmaydi.
- **O'lchov** (sun'iy bukilgan varaqda, 150 doira): oldin o'rtacha 7.4 px (radiusning 45%),
  keyin 0.06 px; bo'yalganlarida 1.4 px. Sinov: `checker/tests/test_grid_fit.py`.
- **Ikkala nusxa:** `checker/omr/omr_checker.py` va `smartbot/services/omr_checker.py` bir xil
  bo'lishi kerak — bot ham, platforma ham shu koddan foydalanadi.

## 45. Javob varag'iga o'quvchilar o'qituvchining guruhidan olinadi

Foydalanuvchi so'rovi (2026-09-24): varaq yaratishda «Ha» bosilganda o'z guruhlarim chiqsin,
bittasini tanlasam o'quvchilarining ma'lumoti o'zi olinsin; qo'lda kiritish ham qolsin.

- **Manba — platforma, faqat o'qish:** guruhlar `Classroom` (o'qituvchi platformadagi `User` ga
  `telegramChatId` orqali bog'lanadi, #23), o'quvchilar esa `Student` dan olinadi — ism, familiya,
  tug'ilgan sana va sinf aynan varaqqa kerak bo'lgan to'rt maydon (#34).
- **Qaytadan yozish yo'q:** guruh tanlansa Excel to'ldirilmaydi. Excel yo'li **o'chirilmadi** —
  ro'yxatda «📄 Excel orqali kiritish» tugmasi turadi va guruhda o'quvchi bo'lmasa yoki platforma
  javob bermasa, bot o'zi o'sha yo'lga o'tadi.
- **Ikkala yo'l bir xil ko'rinishda:** `classroom_students()` `parse_participants()` bilan bir xil
  kalitlarni qaytaradi, shuning uchun varaq yasash kodi o'quvchilar qayerdan kelganini bilmaydi.
- **Ruxsat ustun darajasida:** `Student` dan faqat ism/familiya/sana/sinf, `User` dan faqat
  id/nom/telegramChatId beriladi — ulanish kodi (`linkCode`) va parol xeshi botga ko'rinmaydi
  (deploy/postgres/setup.sql, docs/DEPLOY.md).
- **Bo'sh guruhlar tugma bo'lib chiqmaydi** — nomi matnda eslatiladi, xolos.

## 46. Online testda savollar rasmi emas, muqova rasmi (u ham ixtiyoriy)

Foydalanuvchi qarori (2026-09-24): savollarni bot tarqatmasin — ular kanalga qo'yilgan e'londa
allaqachon bor. Bot faqat javobni tekshiradi.

- **Rasm endi majburiy emas:** `online_tests.image_file_id` NULL bo'lishi mumkin. Yaratishda
  «⏭ Rasmsiz davom etish» tugmasi bor, ya'ni test ikki qadamda tuziladi: raqam → kalit.
- **Rasm qo'yilsa — muqova:** reklama yoki e'lon rasmi. O'quvchi test raqamini kiritganda uni
  ko'radi, keyin javoblarini yozadi. Rasmsiz testda o'quvchiga faqat sarlavha matni boradi.
- **Eski testlar buzilmaydi:** ularning `image_file_id` sida savollar rasmi turibdi va avvalgidek
  (rasm yoki fayl ko'rinishida) yuboriladi. Rasm yuborilmay qolsa ham test to'xtamaydi — xato
  logga yoziladi, o'quvchi javobini yozaveradi.
- **Nega shunday:** kanalda savol rasmi bor xabarga bir marta joylanadi; botda uni takrorlash
  Telegram trafigini ham, adminning vaqtini ham behuda sarflardi.

## 47. Bitta javob varag'i — bir nechta guruhga (nusxa ko'paymaydi)

Muammo (2026-10-03): varaq bir marta yaratilib, keyin har safar o'sha ishtirokchilar bilan
chiqaverardi. Boshqa guruhga yoki bo'sh varaqqa ehtiyoj tug'ilsa, butun varaqni (shablon, fanlar,
javob kaliti) boshidan yaratishga to'g'ri kelardi — bazada bir xil testning nusxalari ko'payib
ketardi, natijalar esa ular orasida bo'linib ketardi.

- **Varaq = test, ishtirokchi = partiya.** Shablon, fanlar va javob kaliti bitta bo'lib qoladi;
  kim uchun chiqarilayotgani har safar so'raladi. «📄 Varaqni qayta yuklab olish» endi darhol
  fayl bermaydi, balki tanlov beradi: *avvalgi ro'yxat*, *guruhlarim* (platformadan, #45) yoki
  *bo'sh varaq*.
- **Takrorlanmaydi:** guruh ikkinchi marta tanlansa yangi qator yaratilmaydi — o'sha odamlar
  o'sha QR raqamlari bilan qaytadan chiqadi (chop etilgan varaqlar yaroqli qoladi). Guruhga
  yangi o'quvchi qo'shilgan bo'lsa, faqat o'sha qo'shiladi va xabarda aytiladi.
- **Qaysi guruh ekani yoziladi:** `test_sheet_participants.guruh` (nomi, ko'rsatish uchun) va
  `classroom_id` (platformadagi guruh — nomi o'zgarsa ham o'sha guruh ekani bilinadi). Guruhsiz
  qatorlar — varaq yaratilganda Excel orqali kiritilgan birinchi ro'yxat.
- **Natijalar bitta jadvalda, guruh ustuni bilan:** bir xil test bo'yicha guruhlarni solishtirish
  mumkin bo'ladi. O'rin butun ro'yxat bo'yicha hisoblanadi (avvalgidek).
- **Bo'sh varaq har doim mumkin:** ishtirokchili varaqdan ham bo'sh nusxa olinadi (zaxira yoki
  ro'yxatdan tashqari o'quvchi uchun).
- **Varaq tafsiloti** qaysi guruhlarga chiqarilganini ko'rsatadi; «Natijalar (Excel)» tugmasi endi
  `with_participants` bayrog'iga emas, qatorlar soniga qarab chiqadi (bo'sh yaratilgan varaq keyin
  guruh olishi mumkin).

## Sinovlar

Bu qarorlarning ko'pi sinov bilan tasdiqlangan. Sinovlar jonli bazaga
qarshi, yozish amallari **tranzaksiya ichida bajarilib orqaga
qaytariladi** — ma'lumotga tegmaydi.

Namuna:

```python
async with Session() as s:
    try:
        async with s.begin():
            ...  # sinov ma'lumotlari
            assert ...
            raise RB()          # orqaga qaytarish
    except RB:
        pass
```

Har sinovda oxirida nazorat summasi solishtiriladi:

```sql
SELECT md5(string_agg(id::text||full_name||phone, '|' ORDER BY id)) FROM users;
```
