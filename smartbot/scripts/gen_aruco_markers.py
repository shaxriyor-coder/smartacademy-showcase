"""Javob varag'ining burchak markerlarini (ArUco) qayta yaratish.

Markerlar `utils/assets/answer_sheet/` ichida statik fayl sifatida yotadi —
ular har render'da qayta chizilmaydi. Shu skript ularni qayta yaratish
uchun (masalan lug'at o'zgarsa yoki fayl yo'qolsa).

Ishga tushirish (loyiha papkasidan):
    python scripts/gen_aruco_markers.py

DIQQAT: lug'at yoki ID lar o'zgarsa, AVVAL BOSIB CHIQARILGAN varaqlar
o'qilmay qoladi — tekshiruvchi dastur eski markerlarni topa olmaydi.
Qiymatlar `services/answer_sheet_service.py` dagi ARUCO_* konstantalari
bilan bir xil bo'lishi shart.
"""

import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.answer_sheet_service import (  # noqa: E402
    ARUCO_DICT_ID,
    ARUCO_CORNER_IDS,
)

# Bosishda aniq chiqishi uchun katta o'lchamda saqlanadi (varaqda 7mm).
PIXELS = 400


def main() -> None:
    out_dir = PROJECT_ROOT / "utils" / "assets" / "answer_sheet"
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_ID)

    for corner, marker_id in ARUCO_CORNER_IDS.items():
        img = cv2.aruco.generateImageMarker(dictionary, marker_id, PIXELS)
        path = out_dir / f"aruco_{corner}.png"
        cv2.imwrite(str(path), img)
        print(f"  {path.name}  (id={marker_id}, {PIXELS}x{PIXELS})")

    print(f"\n{len(ARUCO_CORNER_IDS)} ta marker yaratildi: {out_dir}")


if __name__ == "__main__":
    main()
