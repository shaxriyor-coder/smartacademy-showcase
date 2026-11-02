# checker — javob varag'i va OMR servisi

Platforma uchun og'ir ishni bajaradigan kichik HTTP servis (aiohttp):

- `POST /templates` — bo'sh javob varag'i shabloni (WeasyPrint) va uning
  maydon/doira koordinatalari;
- `POST /stamp` — shablon ustiga har o'quvchining ismi va QR kodi (PyMuPDF);
- `POST /check` — skan (PDF yoki rasm) → har sahifadagi ticket_no va javoblar,
  hamda belgilangan varaqlar PDF'i (OpenCV);
- `POST /ocr` — test sahifasi rasm(lar)i → savollar, variantlar, kesilgan
  chizmalar va "tekshirish kerak" izohlari (Tesseract, `ocr/`).

To'liq shartnoma `server.py` boshida yozilgan. Servis bazaga tegmaydi va
hech narsani diskda saqlamaydi.

`omr/` — smartbot'dan (`services/answer_sheet_service.py`,
`services/omr_checker.py`, `utils/qr_payload.py`, commit `38373cf`)
**o'zgarishsiz** nusxa, faqat importlar moslangan. Geometriya va qaror
qoidalarini o'zgartirishdan oldin `smartbot/docs/DECISIONS.md` #27-#37 ni
o'qing: chop etilgan varaqlar shu koordinatalarga bog'liq.

## O'rnatish

```bash
pip install -r requirements.txt
cp .env.example .env    # CHECKER_TOKEN, QR_SECRET
```

WeasyPrint tizim kutubxonalariga tayanadi:

- **Linux:** `apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 fonts-noto`
- **Windows:** [MSYS2](https://www.msys2.org/) → `pacman -S mingw-w64-x86_64-pango`,
  `.env` ga `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin`

Shrift farqi "lokalda ishlaydi, serverda yo'q" xatosini berishi mumkin —
smartbot DECISIONS.md #36.

## Rasmdan savol o'qish (Tesseract)

`ocr/`: `preprocess.py` (rangli sarlavha va suv belgisini ajratish) →
`tesseract.py` → `layout.py` (chizmalar, qatorlar) → `parse.py` (savollar,
variantlar — rasmsiz, unit test bilan) → `pipeline.py` (chizma va asl rasm
bo'laklari). Qarorlar: `docs/DECISIONS.md` #28.

- **Linux:** `apt-get install -y tesseract-ocr tesseract-ocr-uzb tesseract-ocr-eng`
- **Windows:** [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) o'rnatuvchisi,
  `uzb.traineddata` — [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) dan.
  Til fayllari (uzb, eng) bitta papkada bo'lsin; `.env` ga `TESSERACT_CMD` va `TESSDATA_DIR`
  (`.env.example` ga qarang).

`tessdata_best`'dagi uzb modeli `uzb_cyrl` ni ham yuklashga urinib, stderr'ga
ogohlantirish yozadi — zararsiz.

## Ishga tushirish va sinash

```bash
python server.py                                  # http://127.0.0.1:8090
python -m unittest discover -s tests -t .         # QR / ticket_no, savollarni ajratish
python scripts/selftest.py                        # shablon -> shtamp -> sun'iy skan -> OMR
python scripts/ocr_selftest.py                    # sun'iy test sahifasi -> /ocr -> savollar
python scripts/ocr_sample.py sahifa.jpg -o out    # haqiqiy rasmni o'qib, natijani papkaga yozadi
```

`scripts/fake_scan.py` — shtamplangan PDF'dan "to'ldirilgan, qiyshiq,
shovqinli skan" yasaydi (qog'ozsiz sinov uchun).
