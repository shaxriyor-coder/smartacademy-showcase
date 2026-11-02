"""utils/utility.py dagi sinf hisobi uchun testlar (DECISIONS.md #41).

Ishga tushirish:  python -m unittest tests.test_child_grade -v
"""

import unittest
from datetime import date

from utils.utility import academic_year_start, current_grade


class AcademicYearTest(unittest.TestCase):
    def test_sentabrdan_yangi_oquv_yili(self):
        self.assertEqual(academic_year_start(date(2026, 8, 31)), 2025)
        self.assertEqual(academic_year_start(date(2026, 9, 1)), 2026)
        self.assertEqual(academic_year_start(date(2027, 1, 15)), 2026)


class CurrentGradeTest(unittest.TestCase):
    def test_oquv_yili_ichida_ozgarmaydi(self):
        # 2026-09 da 5-sinf deb kiritilgan
        self.assertEqual(current_grade(5, 2026, date(2026, 9, 10)), 5)
        self.assertEqual(current_grade(5, 2026, date(2027, 5, 20)), 5)

    def test_yangi_oquv_yilida_oshadi(self):
        self.assertEqual(current_grade(5, 2026, date(2027, 9, 1)), 6)
        self.assertEqual(current_grade(5, 2026, date(2029, 10, 1)), 8)

    def test_11_sinfdan_oshmaydi(self):
        self.assertEqual(current_grade(10, 2026, date(2030, 9, 1)), 11)

    def test_orqaga_ketmaydi(self):
        # Sana noto'g'ri bo'lsa ham sinf kamaymaydi.
        self.assertEqual(current_grade(7, 2026, date(2024, 9, 1)), 7)


if __name__ == "__main__":
    unittest.main()
