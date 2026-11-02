"""utils/participant_photo.py uchun testlar.

Ishga tushirish:  python -m unittest tests.test_participant_photo -v
"""

import io
import unittest

from PIL import Image

from utils.participant_photo import PhotoError, prepare_participant_photo


def _jpeg(width: int, height: int, orientation: int | None = None) -> bytes:
    image = Image.new("RGB", (width, height), (120, 90, 200))
    buf = io.BytesIO()
    if orientation is None:
        image.save(buf, "JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


class PrepareParticipantPhotoTest(unittest.TestCase):
    def test_keng_rasm_3x4_ga_keltiriladi(self):
        self.assertEqual(_size(prepare_participant_photo(_jpeg(1600, 1200))), (600, 800))

    def test_baland_rasm_3x4_ga_keltiriladi(self):
        self.assertEqual(_size(prepare_participant_photo(_jpeg(900, 2000))), (600, 800))

    def test_kichik_rasm_kattalashtirilmaydi(self):
        self.assertEqual(_size(prepare_participant_photo(_jpeg(300, 400))), (300, 400))

    def test_baland_rasm_yuqoriroqdan_kesiladi(self):
        # Yuqori yarmi qizil, pastki yarmi ko'k: kesilgan rasmning tepasi qizil,
        # pasti ko'k bo'lishi kerak (yuz odatda rasmning yuqori qismida).
        image = Image.new("RGB", (600, 1600), (0, 0, 255))
        image.paste((255, 0, 0), (0, 0, 600, 800))
        buf = io.BytesIO()
        image.save(buf, "PNG")
        result = Image.open(io.BytesIO(prepare_participant_photo(buf.getvalue())))
        top, bottom = result.getpixel((300, 20)), result.getpixel((300, 780))
        self.assertGreater(top[0], 200)
        self.assertGreater(bottom[2], 200)

    def test_exif_burilishi_hisobga_olinadi(self):
        # 1000x600 fayl, lekin EXIF "90° burilgan" deydi — aslida tik rasm.
        # Burilish e'tiborsiz qolsa natija 450x600 bo'lardi.
        self.assertEqual(_size(prepare_participant_photo(_jpeg(1000, 600, orientation=6))), (600, 800))

    def test_rasm_bolmasa_xato(self):
        with self.assertRaises(PhotoError):
            prepare_participant_photo(b"bu rasm emas")

    def test_juda_kichik_rasm_rad_etiladi(self):
        with self.assertRaises(PhotoError):
            prepare_participant_photo(_jpeg(120, 160))


if __name__ == "__main__":
    unittest.main()
