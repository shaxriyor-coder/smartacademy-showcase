# Excel import va ism moslashtirish

Olimpiada natijalari Excel'dan yuklanadi. Excel'da Telegram Chat ID ham,
telefon ham bo'lmaydi — yagona bog'lovchi **ism**. Shuning uchun import
ikki qismdan iborat: faylni o'qish va o'quvchini topish.

---

## 1. Excel parser (`services/excel_import.py`)

### Muammo

Haqiqiy fayllarda sarlavha bir qatorda turmaydi. Namunaviy faylda
(`Asaka smart academy 4-sinf.xlsx`) u **uch qatorga tarqalgan**:

```
1-qator:  (bo'sh)
2-qator:  №  │ O'quvchining ismi va familiyasi │ 4-sinf natijalari
3-qator:     │                                 │ Sinf │ Matematika │ … │ umumiy ball │ umumiy foiz (%)
4-qator:     │                                 │      │ 1-12-savollar │ …
5-qator:  1  │ Yusufjonov Iskandar             │ 4-sinf │ 12 │ … │ 71.2 │ 93.33
```

`pd.read_excel(header=0)` buni umuman o'qiy olmaydi.

### Yechim

`_find_header()` birinchi 15 qatorni skanlaydi. Har bir nomzod qator uchun
o'zidan keyingi 3 qatorni ham qo'shib ko'radi va kalit so'zlar bo'yicha
ustunlarni topadi:

| Ustun | Kalit so'zlar |
|---|---|
| `full_name` | `ismi va familiya`, `fish`, `f i sh` |
| `grade` | `sinf` |
| `score` | `umumiy ball`, `jami ball`, `ball` |
| `percentage` | `umumiy foiz`, `foiz`, `%` |
| `math` | `matematika` |
| `english` | `ingliz tili` |

Ism va ball **majburiy**, topilmasa `ExcelStructureError` beriladi va
adminga qaysi ustunlar kerakligi ko'rsatiladi.

### Qabul qilinadigan formatlar

```
Ball:  87    87.5    "87,5"    "87.45%"
Sinf:  "4-sinf"    "4"    4    4.0    "4 sinf"
```

Bo'sh katak, `NaN`, matn, xato qiymat — import yiqilmaydi, o'sha qator
muammoli deb belgilanadi.

### Sinovda tasdiqlangan

Namunaviy fayl: **56/56 o'quvchi to'g'ri o'qildi**, 0 muammo.

---

## 2. Ism moslashtirish (`services/name_matching.py`)

### Normalizatsiya

O'zbek tilida bir xil ism turlicha yoziladi:

```
O'quvchi   O'quvchi   O`quvchi        →  bir xil
G'ulom     G'ulom     Gulom           →  bir xil
MUHAMMAD RIZO   Muhammadrizo          →  o'xshash (0.98)
```

`normalize_name()` quyidagilarni qiladi:

1. Unicode NFKC normalizatsiya
2. Barcha apostrof variantlarini olib tashlash (`' ' ʻ ʼ ′ \` ´ '`)
3. Kirill/lotin ko'rinishdosh harflarni birlashtirish (`А`→`A`, `О`→`O`, …)
4. Kichik harfga o'tkazish
5. Ketma-ket bo'shliqlarni bittaga tushirish
6. Tinish belgilarini bo'shliqqa aylantirish

`name_key()` — qo'shimcha: so'zlarni alifbo tartibida saralaydi, shunda
`Valiyev Ali` va `Ali Valiyev` bir xil kalit beradi.

### Qidirish ustuvorligi

```
1-daraja  normalizatsiya qilingan AYNAN moslik
2-daraja  so'zlar tartibidan qat'i nazar moslik
3-daraja  fuzzy (SequenceMatcher, chegara 0.86)
```

**Sinf ustuvor:** `find(name, grade)` da avval o'sha sinfdagilar
tekshiriladi. 4-sinfdagi `Ali Valiyev` topilsa, 5-sinfdagisi umuman
ko'rsatilmaydi.

### Ish unumdorligi

`NameIndex` ro'yxatni **bir marta** o'qib, xotirada indeks quradi.
5000 qatorli faylda har qator uchun so'rov yuborilsa 10000+ so'rov
bo'lardi. Fuzzy faqat aniq moslik topilmaganda ishlatiladi.

---

## 3. Import oqimi

```
olimpiada → sinf → Excel fayl
    ↓
tahlil (preview):  ✅ topildi   🔄 takror   ⚠️ noaniq   ❌ topilmadi   🚫 sinf mos emas
    ↓
tasdiq → yangi natijalar yoziladi
    ↓
takrorlar siyosati:  [Hammasini yangilash] [Hammasini o'tkazish] [Bittalab]
    ↓
noaniq nomzodlar:  har biri uchun tugmalar (maktab, sinf, telefon, Chat ID)
    ↓
qo'lda qidirish:  topilmaganlarni admin ism yozib qidiradi
    ↓
yakuniy hisobot
```

### Takrorlar

O'quvchida natija allaqachon bo'lsa, admin tanlaydi. "Bittalab" rejimida
eski va yangi ball yonma-yon ko'rsatiladi:

```
⚠️ Ali Valiyev uchun natija allaqachon mavjud.
   Eski: 72.5      Yangi: 81.3
   [🔄 Yangilash] [⏭ O'tkazib yuborish]
   [🔄 Qolganini ham yangilash] [⏭ Qolganini o'tkazib yuborish]
```

### Noaniq nomzodlar

5 tadan sahifalanadi (`◀️ 2/3 ▶️`). Har nomzod uchun ajratuvchi ma'lumot
ko'rsatiladi — maktab, sinf, **maskalangan** telefon (`+99890*****1111`),
Chat ID.

### Topilmasa

Natija **hech qachon noto'g'ri o'quvchiga yozilmaydi**. Admin qo'lda
qidiradi yoki o'tkazib yuboradi.

---

## 4. Reyting (`services/ranking.py`)

`recalculate_olympiad_places(session, olympiad_id, grade)` — **yagona**
funksiya. Excel import, PDF checker va qo'lda tahrirlash shuni chaqiradi.

Scope faqat `olympiad_id + grade`:

```
4-sinf:  95 → 1-o'rin        3-sinf:  99 → 1-o'rin
         92 → 2-o'rin                 70 → 2-o'rin
         92 → 2-o'rin
         89 → 4-o'rin
```

4-sinfdagi 1-o'rin 3-sinfdagi 1-o'ringa **ta'sir qilmaydi**.
Teng ballar teng o'rin oladi, keyingisi sakraydi.
