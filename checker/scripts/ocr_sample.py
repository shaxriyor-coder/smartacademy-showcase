"""Test sahifasi rasm(lar)idan savollarni o'qib, natijani ko'rish uchun papkaga yozadi.

    cd checker && python scripts/ocr_sample.py sahifa1.jpg sahifa2.jpg -o ocr-out

ocr-out/ ichida: result.json (rasmlarsiz), har savol uchun NN-image.png
(tozalangan chizma) va NN-source.jpg (asl rasmdagi bo'lagi). Qisqa xulosa
ekranga chiqadi. Tesseract sozlamalari checker/.env dan olinadi.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import OCR_LANG, TESSDATA_DIR, TESSERACT_CMD  # noqa: E402
from ocr.pipeline import extract_questions  # noqa: E402
from ocr.tesseract import TesseractSettings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("-o", "--out", type=Path, default=Path("ocr-out"))
    args = parser.parse_args()

    settings = TesseractSettings(cmd=TESSERACT_CMD, tessdata_dir=TESSDATA_DIR, lang=OCR_LANG)
    started = time.time()
    result = extract_questions([p.read_bytes() for p in args.images], settings)
    elapsed = time.time() - started

    args.out.mkdir(parents=True, exist_ok=True)
    for q in result["questions"]:
        stem = f"{q['number']:02d}"
        for key, ext in (("image", "png"), ("source", "jpg")):
            if q[key]:
                (args.out / f"{stem}-{key}.{ext}").write_bytes(base64.b64decode(q[key]))
                q[key] = f"{stem}-{key}.{ext}"
    (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{len(args.images)} sahifa, {len(result['questions'])} savol, {elapsed:.1f} s — {args.out}")
    print(f"Sarlavha: {result['title']}")
    for q in result["questions"]:
        flag = "!" if q["needs_review"] else " "
        print(f"\n{flag} {q['number']}. {q['text']}")
        letters = "ABCDE"
        print("    " + "   ".join(f"{letters[i]}) {o}" for i, o in enumerate(q["options"])))
        if q["image"]:
            print(f"    rasm: {q['image']}")
        for note in q["notes"]:
            print(f"    - {note}")
        if q["uncertain"]:
            print(f"    - noaniq: {', '.join(q['uncertain'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
