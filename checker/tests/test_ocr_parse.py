"""ocr/parse.py uchun testlar (Tesseract kerak emas).

Ishga tushirish:  python -m unittest tests.test_ocr_parse -v
"""

import unittest

from ocr.parse import Row, normalize, parse_pages, split_options


def rows(*lines: str, step: int = 40) -> list[Row]:
    return [Row(text=t, top=i * step, bottom=i * step + 30, left=0, right=900) for i, t in enumerate(lines)]


class NormalizeTest(unittest.TestCase):
    def test_tutuq_belgisi_bittaga_keltiriladi(self):
        self.assertEqual(normalize("to'g`ri bo’lgan o‘g'il"), "to‘g‘ri bo‘lgan o‘g‘il")

    def test_nuqtaga_oxshab_oqilgan_tutuq(self):
        self.assertEqual(normalize("100 000 so·m"), "100 000 so‘m")

    def test_kopaytirish_belgisi(self):
        self.assertEqual(normalize("8 x 100"), "8 × 100")
        self.assertEqual(normalize("A)8 x1 B)8x10"), "A)8 × 1 B)8 × 10")
        self.assertEqual(normalize("2x + 3"), "2x + 3")

    def test_birlik_va_formula_oraliqlari(self):
        self.assertEqual(normalize("A)3kg B) 15kg"), "A)3 kg B) 15 kg")
        self.assertEqual(normalize("— +192 + 78 = 330"), "— + 192 + 78 = 330")
        self.assertEqual(normalize("5 ta olma +3 ta nok"), "5 ta olma +3 ta nok")

    def test_raqam_yonidagi_at_nol(self):
        self.assertEqual(normalize("D) 3@ E) @5"), "D) 30 E) 05")
        self.assertEqual(normalize("@pmtests kanali"), "@pmtests kanali")


class SplitOptionsTest(unittest.TestCase):
    def test_bir_qatorda_tort_variant(self):
        parts, missing = split_options("A) 135 B) 315 C) 531 D) 351", 0)
        self.assertEqual(parts, ["135", "315", "531", "351"])
        self.assertEqual(missing, [])

    def test_davomi_c_dan(self):
        parts, _ = split_options("C) 25 000 so‘m D) 100 000 so‘m", 2)
        self.assertEqual(parts, ["25 000 so‘m", "100 000 so‘m"])

    def test_adashtirilgan_harflar(self):
        parts, _ = split_options("A) 60 8) 70 (') 58 0) 59", 0)
        self.assertEqual(parts, ["60", "70", "58", "59"])

    def test_qator_variant_bilan_boshlanmasa(self):
        self.assertIsNone(split_options("Unda qancha pul qoldi? A) 5", 0))

    def test_a_oqilmagan(self):
        parts, missing = split_options("B) 315 C) 531", 0)
        self.assertEqual(parts, ["", "315", "531"])
        self.assertEqual(missing, ["A"])

    def test_ortadagi_harf_oqilmagan(self):
        parts, missing = split_options("A) 5 B) 6 D) 8", 0)
        self.assertEqual(parts, ["5", "6", "", "8"])
        self.assertEqual(missing, ["C"])

    def test_gap_ichidagi_kichik_harf_nuqta_bilan_marker_emas(self):
        self.assertIsNone(split_options("a. b bilan c ni toping", 0))


class ParsePagesTest(unittest.TestCase):
    def test_namuna_sahifa(self):
        result = parse_pages(
            [
                rows(
                    "Prezident maktabi testlari kanali @pmtests (10.09.2026)",
                    "Prezident va al-Xorazmiy maktabi matematika imtihoni repetitsion test №1",
                    "1. 3, 5, 1 raqamlarining barchasidan foydalanib tuzish mumkin bo'lgan eng katta butun son",
                    "qaysi?",
                    "A) 135 B) 315 C) 531 D) 351",
                    "2. Otabekda 200 000 so'm pul bor. U har biri",
                    "50 000 so'm turadigan 2 ta o'yinchoq",
                    "A) 50 000 so'm B) 15 000 so'm",
                    "C) 25 000 so'm D) 100 000 so'm",
                    "3. Sonli tenglik to'g'ri bo'lishi uchun bo'sh joyga qaysi son yozilishi kerak?",
                    "___ + 192 + 78 = 330",
                    "A) 60 B) 70 C) 58 D) 59",
                )
            ]
        )
        self.assertEqual(result.title, "Prezident va al-Xorazmiy maktabi matematika imtihoni repetitsion test №1")
        q1, q2, q3 = result.questions
        self.assertEqual(
            q1.text,
            "3, 5, 1 raqamlarining barchasidan foydalanib tuzish mumkin bo‘lgan eng katta butun son qaysi?",
        )
        self.assertEqual(q1.options, ["135", "315", "531", "351"])
        self.assertEqual(q2.text, "Otabekda 200 000 so‘m pul bor. U har biri 50 000 so‘m turadigan 2 ta o‘yinchoq")
        self.assertEqual(q2.options[3], "100 000 so‘m")
        self.assertEqual(q3.text.split("\n"), [
            "Sonli tenglik to‘g‘ri bo‘lishi uchun bo‘sh joyga qaysi son yozilishi kerak?",
            "___ + 192 + 78 = 330",
        ])
        self.assertEqual([q.notes for q in result.questions], [[], [], []])

    def test_matndagi_son_yangi_savol_emas(self):
        result = parse_pages(
            [rows("1. Otabekda pul bor. U har biri", "2) ta mashina oldi.", "A) 1 B) 2 C) 3 D) 4")]
        )
        # "2)" kutilgan raqam (2), shuning uchun yangi savol — lekin bu holda 1-savolda variant yo'q
        self.assertEqual(len(result.questions), 2)
        result = parse_pages(
            [rows("5. Otabekda pul bor. U har biri", "12. ta mashina oldi.", "A) 1 B) 2 C) 3 D) 4")]
        )
        self.assertEqual(len(result.questions), 1)
        self.assertIn("12. ta mashina oldi.", result.questions[0].text)

    def test_bitta_savol_oqilmasa_belgilanadi(self):
        result = parse_pages([rows("1. Birinchi?", "A) 1 B) 2 C) 3 D) 4", "3. Uchinchi?", "A) 1 B) 2 C) 3 D) 4")])
        self.assertEqual([q.number for q in result.questions], [1, 3])
        self.assertIn("2-savol topilmadi — rasmda bormi, tekshiring", result.questions[1].notes)

    def test_rasmli_variantlar(self):
        result = parse_pages([rows("1. Ketma-ketlikni davom ettiring.", "A) B)", "C) D)")])
        q = result.questions[0]
        self.assertTrue(q.options_are_images)
        self.assertEqual(q.options, ["A", "B", "C", "D"])
        self.assertTrue(q.notes)

    def test_savol_keyingi_sahifada_davom_etadi(self):
        page1 = rows("1. Birinchi?", "A) 1 B) 2 C) 3 D) 4", "2. Ikkinchi savol matni")
        page2 = rows("davomi shu yerda?", "A) 5 B) 6", "C) 7 D) 8", "3. Uchinchi?", "A) 1 B) 2 C) 3 D) 4")
        q1, q2, q3 = parse_pages([page1, page2]).questions
        self.assertEqual(q2.text, "Ikkinchi savol matni davomi shu yerda?")
        self.assertEqual(q2.options, ["5", "6", "7", "8"])
        self.assertEqual([(s.page, s.top, s.bottom) for s in q2.segments], [(1, 80, None), (2, 0, 120)])
        self.assertEqual([(s.page, s.top, s.bottom) for s in q1.segments], [(1, 0, 80)])

    def test_yangi_sahifa_yangi_savol_bilan_boshlansa_bosh_bolak_qolmaydi(self):
        page1 = rows("1. Birinchi?", "A) 1 B) 2 C) 3 D) 4")
        page2 = rows("2. Ikkinchi?", "A) 1 B) 2 C) 3 D) 4")
        q1, _ = parse_pages([page1, page2]).questions
        self.assertEqual([s.page for s in q1.segments], [1])

    def test_noaniq_sozlar_yigiladi(self):
        page = rows("1. Birinchi?", "A) 1 B) 2 C) 3 D) 4")
        page[0].uncertain = ["Birinchi?"]
        page[1].uncertain = ["3", "3"]
        self.assertEqual(parse_pages([page]).questions[0].uncertain, ["Birinchi?", "3"])

    def test_kasrli_variantlar_rasm_deb_olinadi(self):
        # namunadagi 6-savol: A) 1/2 B) 5/8 ... kasrlar Tesseract'da shunday chiqdi
        result = parse_pages([rows("1. Shaklning qanday qismi bo'yalgan?", "A); B)? o? D):", "2 8 9 9")])
        q = result.questions[0]
        self.assertTrue(q.options_are_images)
        self.assertEqual(q.options, ["A", "B", "C", "D"])
        self.assertIn("C variant o'qilmadi", q.notes)

    def test_s_raqam_5_deb_oqiladi(self):
        page = rows("4. To'rtinchi?", "A) 1 B) 2 C) 3 D) 4", "S. Beshinchi?", "A) 1 B) 2 C) 3 D) 4")
        self.assertEqual([q.number for q in parse_pages([page]).questions], [4, 5])

    def test_nuqta_bilan_tugagan_qator_davom_etadi(self):
        result = parse_pages([rows("U", "Test №1", "1. Javlon toshcha sotib oldi.", "U aralashtirdi?", "A) 1 B) 2 C) 3 D) 4")])
        self.assertEqual(result.title, "Test №1")
        self.assertEqual(result.questions[0].text, "Javlon toshcha sotib oldi. U aralashtirdi?")

    def test_variantlar_soni(self):
        result = parse_pages([rows("1. Savol?", "A) 1 B) 2 C) 3")])
        self.assertIn("3 ta variant topildi (4 yoki 5 bo'lishi kerak)", result.questions[0].notes)


if __name__ == "__main__":
    unittest.main()
