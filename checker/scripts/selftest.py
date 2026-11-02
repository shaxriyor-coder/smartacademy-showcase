"""Servisni boshidan oxirigacha sinaydi (HTTP orqali, haqiqiy port ochmasdan).

shablon -> 3 ta ishtirokchiga shtamplash -> sun'iy to'ldirilgan skan ->
tekshirish -> o'qilgan javoblar kutilgani bilan AYNAN mos kelishi.

    cd checker && python scripts/selftest.py

Muvaffaqiyatda 0 bilan, birorta farqda 1 bilan chiqadi.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiohttp import FormData  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from config import CHECKER_TOKEN  # noqa: E402
from fake_scan import make_scan  # noqa: E402
from omr.qr_payload import build_ticket_no  # noqa: E402
from server import create_app  # noqa: E402

SUBJECT = "Matematika"
QUESTIONS = 30
LETTERS = "ABCDE"
HEADERS = {"X-Checker-Token": CHECKER_TOKEN}


async def main() -> int:
    rnd = random.Random(42)
    async with TestClient(TestServer(create_app())) as client:
        resp = await client.post("/templates", json={"title": "x", "subjects": []})
        assert resp.status == 401, f"tokensiz so'rov o'tib ketdi: {resp.status}"

        t0 = time.perf_counter()
        resp = await client.post(
            "/templates",
            headers=HEADERS,
            json={
                "title": "Selftest",
                "subjects": [{"name": SUBJECT, "question_count": QUESTIONS, "choice_count": 5}],
            },
        )
        assert resp.status == 200, await resp.text()
        template = await resp.json()
        print(f"shablon: {time.perf_counter() - t0:.1f}s")

        tickets = [build_ticket_no(2026, "CR1", seq) for seq in (1, 2, 3)]
        participants = [
            {"ism": f"Ism{i}", "familiya": f"Familiya{i}", "kun": "01", "oy": "02",
             "yil": "2012", "sinf": "7-A", "ticket_no": t}
            for i, t in enumerate(tickets, start=1)
        ]
        resp = await client.post(
            "/stamp",
            headers=HEADERS,
            json={"blank_pdf": template["blank_pdf"], "field_boxes": template["field_boxes"],
                  "participants": participants},
        )
        assert resp.status == 200, await resp.text()
        sheets_pdf = await resp.read()

        bad = await client.post(
            "/stamp",
            headers=HEADERS,
            json={"blank_pdf": template["blank_pdf"], "field_boxes": template["field_boxes"],
                  "participants": [{**participants[0], "ticket_no": "SA-2026-CR1-0000010"}]},
        )
        assert bad.status == 400, "buzuq nazorat raqamli ticket rad etilmadi"

        key = [rnd.choice(LETTERS) for _ in range(QUESTIONS)]
        expected: list[list[str | None]] = []
        expected_multi: list[list[int]] = []
        marks = []
        for page in range(len(tickets)):
            per_q, exp, multi = [], [], []
            for qn in range(1, QUESTIONS + 1):
                if qn == 5 + page:        # bo'sh qoldirilgan savol
                    per_q.append([]); exp.append(None)
                elif qn == 10 + page:     # ikki doira bo'yalgan
                    per_q.append(["A", "C"]); exp.append(None); multi.append(qn)
                else:
                    letter = rnd.choice(LETTERS)
                    per_q.append([letter]); exp.append(letter)
            marks.append({SUBJECT: per_q})
            expected.append(exp)
            expected_multi.append(multi)

        scan = make_scan(sheets_pdf, template["bubble_boxes"], marks)

        form = FormData()
        form.add_field(
            "meta",
            json.dumps({"field_boxes": template["field_boxes"],
                        "bubble_boxes": template["bubble_boxes"],
                        "answer_keys": {SUBJECT: key}}),
            content_type="application/json",
        )
        form.add_field("file", scan, filename="scan.pdf", content_type="application/pdf")
        t0 = time.perf_counter()
        resp = await client.post("/check", headers=HEADERS, data=form)
        assert resp.status == 200, await resp.text()
        result = await resp.json()
        print(f"tekshiruv: {result['page_count']} sahifa, {time.perf_counter() - t0:.1f}s")

    failures = 0
    for i, page in enumerate(result["pages"]):
        if not page["ok"]:
            print(f"  {i + 1}-sahifa XATO: {page['error']}")
            failures += 1
            continue
        subject = page["subjects"][0]
        ok = (
            page["ticket_no"] == tickets[i]
            and subject["answers"] == expected[i]
            and subject["multi"] == expected_multi[i]
        )
        print(f"  {i + 1}-sahifa {page['ticket_no']}: {'OK' if ok else 'FARQ BOR'}")
        if not ok:
            failures += 1
            diff = [
                (qn, want, got)
                for qn, (want, got) in enumerate(zip(expected[i], subject["answers"]), start=1)
                if want != got
            ]
            print(f"    farqlar (savol, kutilgan, o'qilgan): {diff}; multi={subject['multi']}")

    annotated = base64.b64decode(result["annotated_pdf"] or "")
    if annotated[:5] != b"%PDF-":
        print("  belgilangan PDF qaytmadi")
        failures += 1

    print("NATIJA:", "HAMMASI TO'G'RI" if failures == 0 else f"{failures} ta xato")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
