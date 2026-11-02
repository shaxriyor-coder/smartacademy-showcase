"""Doiralar to'rini varaqqa moslash (DECISIONS.md #44).

Sun'iy "varaq" yasaladi: doiralar shablondagi joyidan siljitib chiziladi
(printer/skaner farqi + qog'oz bukilgani). Tekshiriladigan narsa —
hisoblangan markazlar chizilgan doiralarning ustiga tushishi.

    cd checker && python -m unittest tests.test_grid_fit -v
"""

from __future__ import annotations

import math
import unittest

import cv2
import numpy as np

from omr import omr_checker as OC

RADIUS_PT = 6.0
RADIUS_PX = RADIUS_PT * OC._PT_TO_PX
COLUMNS, ROWS = 5, 12
LETTERS = "ABCDE"


def template_boxes() -> dict:
    """Bir fanli soxta shablon: 12 savol, 5 variant."""
    questions = {}
    for row in range(ROWS):
        y = 60 + row * 26
        questions[str(row + 1)] = [[60 + col * 22, y] for col in range(COLUMNS)]
    return {
        "page": [420, 620],
        "radius": RADIUS_PT,
        "markers": [[20, 20], [400, 20], [400, 600], [20, 600]],
        "subjects": [
            {"name": "Fan", "letters": LETTERS[:COLUMNS], "questions": questions}
        ],
    }


def distorted(x: float, y: float) -> tuple[float, float]:
    """Varaqdagi haqiqiy joy: kichik masshtab + siljish + bukilish."""
    sx = x * 0.996 + 5.0 + 3.0 * math.sin(y / 90.0)
    sy = y * 1.003 - 4.0 + 2.0 * math.cos(x / 70.0)
    return sx, sy


def render(boxes: dict, filled: dict[int, int]) -> np.ndarray:
    """Doiralar chizilgan kulrang "skan". `filled`: savol -> bo'yalgan ustun."""
    w = int(boxes["page"][0] * OC._PT_TO_PX)
    h = int(boxes["page"][1] * OC._PT_TO_PX)
    img = np.full((h, w), 245, dtype=np.uint8)
    r = int(round(RADIUS_PX))
    for qn_txt, centers in boxes["subjects"][0]["questions"].items():
        for i, (cx_pt, cy_pt) in enumerate(centers):
            x, y = distorted(cx_pt * OC._PT_TO_PX, cy_pt * OC._PT_TO_PX)
            cv2.circle(img, (int(round(x)), int(round(y))), r, 40, 2, cv2.LINE_AA)
            # Doira ichidagi harf — haqiqiy varaqdagidek
            cv2.putText(img, LETTERS[i], (int(x) - 5, int(y) + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, 90, 1, cv2.LINE_AA)
            if filled.get(int(qn_txt)) == i:
                # Ruchka markazdan sal chetga chiqadi
                cv2.circle(img, (int(round(x)) + 3, int(round(y)) - 2), r - 1, 30, -1,
                           cv2.LINE_AA)
    return img


class GridFitTest(unittest.TestCase):
    def setUp(self):
        self.boxes = template_boxes()
        self.filled = {qn: (qn * 2) % COLUMNS for qn in range(1, ROWS + 1)}
        self.image = render(self.boxes, self.filled)
        self.grid = OC._fit_grid(self.image, self.boxes, RADIUS_PX)

    def _errors(self) -> tuple[list[float], list[float]]:
        """(bo'sh doiralar xatosi, bo'yalganlar xatosi) — piksel."""
        empty, marked = [], []
        for qn_txt, centers in self.boxes["subjects"][0]["questions"].items():
            qn = int(qn_txt)
            for i, (cx_pt, cy_pt) in enumerate(centers):
                real = distorted(cx_pt * OC._PT_TO_PX, cy_pt * OC._PT_TO_PX)
                got = self.grid.point(0, qn, i)
                err = math.hypot(got[0] - real[0], got[1] - real[1])
                (marked if self.filled.get(qn) == i else empty).append(err)
        return empty, marked

    def test_bosh_doiralar_ustiga_tushadi(self):
        empty, _ = self._errors()
        self.assertLess(max(empty), 0.25 * RADIUS_PX, f"eng katta xato: {max(empty):.1f} px")

    def test_boyalgan_doira_qoshnilari_boyicha_qoyiladi(self):
        # Ruchka dog'i markazdan surilgan — belgi baribir DOIRA ustiga tushsin.
        _, marked = self._errors()
        self.assertLess(max(marked), 0.5 * RADIUS_PX, f"eng katta xato: {max(marked):.1f} px")

    def test_shablon_ozi_yetarli_emas(self):
        # Tuzatishsiz xato radiusning yarmidan oshadi — shu sabab kerak.
        template = OC._template_grid(self.boxes, RADIUS_PX)
        worst = 0.0
        for qn_txt, centers in self.boxes["subjects"][0]["questions"].items():
            for i, (cx_pt, cy_pt) in enumerate(centers):
                real = distorted(cx_pt * OC._PT_TO_PX, cy_pt * OC._PT_TO_PX)
                got = template.point(0, int(qn_txt), i)
                worst = max(worst, math.hypot(got[0] - real[0], got[1] - real[1]))
        self.assertGreater(worst, 0.5 * RADIUS_PX)

    def test_radius_olchanadi(self):
        self.assertAlmostEqual(self.grid.radius_px, RADIUS_PX, delta=0.35 * RADIUS_PX)

    def test_bosh_varaqda_shablonga_qaytadi(self):
        """Doira topilmasa (bo'sh yoki buzuq rasm) — eski xatti-harakat."""
        blank = np.full_like(self.image, 245)
        grid = OC._fit_grid(blank, self.boxes, RADIUS_PX)
        template = OC._template_grid(self.boxes, RADIUS_PX)
        self.assertEqual(grid.centers, template.centers)


if __name__ == "__main__":
    unittest.main()
