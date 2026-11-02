"""Online testlar tarixi Excel'i uchun testlar (DECISIONS.md #43).

Ishga tushirish:  python -m unittest tests.test_online_test_excel -v
"""

import io
import unittest
from datetime import datetime

from openpyxl import load_workbook

from services.online_test_excel import (
    build_history_excel,
    grade_label,
    history_filename,
    wrong_questions,
)


class GradeLabelTest(unittest.TestCase):
    def test_chegaralar_botdagidek(self):
        # handlers/user.py dagi natija xabari bilan bir xil bo'lishi shart
        self.assertEqual(grade_label(100), "A'lo")
        self.assertEqual(grade_label(90), "A'lo")
        self.assertEqual(grade_label(89.9), "Yaxshi")
        self.assertEqual(grade_label(70), "Yaxshi")
        self.assertEqual(grade_label(69), "Qoniqarli")
        self.assertEqual(grade_label(50), "Qoniqarli")
        self.assertEqual(grade_label(49), "Yana harakat qiling")


class WrongQuestionsTest(unittest.TestCase):
    def test_xato_savol_raqamlari(self):
        self.assertEqual(wrong_questions("A,B,C", "A,B,C"), "")
        self.assertEqual(wrong_questions("A,X,C,Y", "A,B,C,D"), "2, 4")

    def test_kichik_harf_va_bosh_joy(self):
        self.assertEqual(wrong_questions(" a , b ", "A,B"), "")

    def test_yetmagan_javob_xato_hisoblanadi(self):
        self.assertEqual(wrong_questions("A,B", "A,B,C,D"), "3, 4")

    def test_bosh_javob(self):
        self.assertEqual(wrong_questions("", "A,B"), "1, 2")


class BuildHistoryExcelTest(unittest.TestCase):
    def setUp(self):
        self.results = [
            {
                "checked_at": datetime(2026, 9, 20, 14, 5),
                "test_id": 12,
                "title": "Matematika 5-sinf",
                "full_name": "Ali Valiyev",
                "phone": "+998901234567",
                "chat_id": 555,
                "correct": 3,
                "total": 4,
                "given": "A,X,C,D",
                "key": "A,B,C,D",
            },
            {
                "checked_at": datetime(2026, 9, 19, 9, 30),
                "test_id": 12,
                "title": "Matematika 5-sinf",
                "full_name": "Malika Karimova",
                "phone": "+998907654321",
                "chat_id": 556,
                "correct": 4,
                "total": 4,
                "given": "A,B,C,D",
                "key": "A,B,C,D",
            },
        ]
        self.tests = [
            {
                "test_id": 12,
                "title": "Matematika 5-sinf",
                "questions": 4,
                "solved": 2,
                "avg_percent": 87.5,
                "max_percent": 100.0,
                "created_at": datetime(2026, 9, 18, 8, 0),
                "archived": False,
            },
            {
                "test_id": 11,
                "title": None,
                "questions": 10,
                "solved": 0,
                "avg_percent": None,
                "max_percent": None,
                "created_at": None,
                "archived": True,
            },
        ]

    def _sheets(self):
        wb = load_workbook(io.BytesIO(build_history_excel(self.results, self.tests)))
        return wb["Natijalar"], wb["Testlar"]

    def test_natijalar_varagi(self):
        ws, _ = self._sheets()
        self.assertEqual(ws.cell(1, 1).value, "T/r")
        self.assertEqual(ws.max_row, 3)  # sarlavha + 2 qator

        row = [c.value for c in ws[2]]
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "2026-09-20 14:05")
        self.assertEqual(row[2], 12)
        self.assertEqual(row[4], "Ali Valiyev")
        self.assertEqual(row[7:11], [3, 4, 75.0, "Yaxshi"])
        self.assertEqual(row[11], "2")  # xato savol

    def test_testlar_varagi(self):
        _, ws2 = self._sheets()
        self.assertEqual(ws2.max_row, 3)
        faol = [c.value for c in ws2[2]]
        self.assertEqual(faol[0], 12)
        self.assertEqual(faol[3], 2)
        self.assertEqual(faol[4], 87.5)
        self.assertEqual(faol[7], "Faol")

        arxiv = [c.value for c in ws2[3]]
        self.assertEqual(arxiv[1], "-")  # nomsiz test
        self.assertEqual(arxiv[4], "-")  # hech kim ishlamagan
        self.assertEqual(arxiv[7], "Arxivda")

    def test_bosh_tarix_ham_fayl_beradi(self):
        wb = load_workbook(io.BytesIO(build_history_excel([], [])))
        self.assertEqual(wb["Natijalar"].max_row, 1)
        self.assertEqual(wb["Testlar"].max_row, 1)

    def test_fayl_nomi(self):
        self.assertEqual(
            history_filename(datetime(2026, 9, 23)),
            "online_testlar_tarixi_2026-09-23.xlsx",
        )

    def test_bitta_test_fayl_nomi(self):
        # Test ID bo'yicha so'ralganda fayl nomida ham o'sha ID turadi.
        self.assertEqual(
            history_filename(datetime(2026, 9, 23), test_id=12),
            "online_test_12_natijalar_2026-09-23.xlsx",
        )


if __name__ == "__main__":
    unittest.main()
