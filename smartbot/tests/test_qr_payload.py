"""utils/qr_payload.py uchun testlar.

Ishga tushirish:  python -m unittest tests.test_qr_payload -v
"""

import unittest

from utils.qr_payload import (
    build_qr_payload,
    build_ticket_no,
    is_valid_ticket_no,
    sign_ticket_no,
    verify_qr_payload,
)

SECRET = "sinov-uchun-maxfiy-kalit"


class BuildTicketNoTest(unittest.TestCase):
    def test_natija_formatga_mos(self):
        ticket_no = build_ticket_no(2026, "math", 4187)
        self.assertEqual(ticket_no[:12], "SA-2026-MATH")
        self.assertTrue(is_valid_ticket_no(ticket_no))

    def test_kod_katta_harflarga_otkaziladi_va_tozalanadi(self):
        ticket_no = build_ticket_no(2026, "ing liz-2", 1)
        # bo'sh joy va chiziqcha olib tashlanadi, katta harfga o'tadi
        self.assertIn("INGLIZ2", ticket_no)

    def test_bosh_kod_uchun_zaxira_qiymat(self):
        ticket_no = build_ticket_no(2026, "", 1)
        self.assertIn("-GEN-", ticket_no)

    def test_tartib_raqam_oltita_nol_bilan_toldiriladi(self):
        ticket_no = build_ticket_no(2026, "IT", 7)
        self.assertIn("-000007", ticket_no)

    def test_ketma_ket_seq_turli_ticket_no_beradi(self):
        a = build_ticket_no(2026, "IT", 1)
        b = build_ticket_no(2026, "IT", 2)
        self.assertNotEqual(a, b)


class IsValidTicketNoTest(unittest.TestCase):
    def test_togri_ticket_no_qabul_qilinadi(self):
        self.assertTrue(is_valid_ticket_no(build_ticket_no(2026, "MATH", 4187)))

    def test_kichik_harf_bilan_ham_ishlaydi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        self.assertTrue(is_valid_ticket_no(ticket_no.lower()))

    def test_notogri_nazorat_raqami_rad_etiladi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        buzilgan = ticket_no[:-1] + str((int(ticket_no[-1]) + 1) % 10)
        self.assertFalse(is_valid_ticket_no(buzilgan))

    def test_tartib_raqamida_bitta_xato_raqam_rad_etiladi(self):
        # Operator "4187" o'rniga "4197" deb xato tersa
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        buzilgan = ticket_no.replace("004187", "004197")
        self.assertFalse(is_valid_ticket_no(buzilgan))

    def test_notogri_format_rad_etiladi(self):
        self.assertFalse(is_valid_ticket_no("XATO-FORMAT"))
        self.assertFalse(is_valid_ticket_no(""))
        self.assertFalse(is_valid_ticket_no(None))


class QrPayloadTest(unittest.TestCase):
    def test_togri_payload_tasdiqlanadi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        payload = build_qr_payload(ticket_no, SECRET)
        self.assertTrue(verify_qr_payload(payload, SECRET))

    def test_notogri_kalit_bilan_rad_etiladi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        payload = build_qr_payload(ticket_no, SECRET)
        self.assertFalse(verify_qr_payload(payload, "boshqa-kalit"))

    def test_ozgartirilgan_imzo_rad_etiladi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        payload = build_qr_payload(ticket_no, SECRET)
        soxta = payload[:-6] + "abcdef"
        self.assertFalse(verify_qr_payload(soxta, SECRET))

    def test_boshqa_ticket_noga_signaturani_kochirib_bolmaydi(self):
        """Soxta ruxsatnoma: haqiqiy imzoni boshqa ticket_no bilan ishlatish."""
        haqiqiy = build_qr_payload(build_ticket_no(2026, "MATH", 1), SECRET)
        _, _, imzo = haqiqiy.partition("|")
        soxta_payload = f"{build_ticket_no(2026, 'MATH', 2)}|{imzo}"
        self.assertFalse(verify_qr_payload(soxta_payload, SECRET))

    def test_notogri_nazorat_raqamli_ticket_imzosi_togri_bolsa_ham_rad_etiladi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        imzo = sign_ticket_no(ticket_no, SECRET)
        buzilgan_ticket = ticket_no[:-1] + str((int(ticket_no[-1]) + 1) % 10)
        self.assertFalse(verify_qr_payload(f"{buzilgan_ticket}|{imzo}", SECRET))

    def test_ajratuvchisiz_payload_rad_etiladi(self):
        self.assertFalse(verify_qr_payload("SA-2026-MATH-0004187", SECRET))

    def test_bosh_kalit_xato_kotaradi(self):
        ticket_no = build_ticket_no(2026, "MATH", 4187)
        with self.assertRaises(ValueError):
            sign_ticket_no(ticket_no, "")


if __name__ == "__main__":
    unittest.main()
