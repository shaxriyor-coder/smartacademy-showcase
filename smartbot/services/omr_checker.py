# Bu fayl checker/omr/omr_checker.py bilan BIR XIL bo'lishi kerak — farqi
# faqat import yo'llarida (u yerda: omr/...). Bittasini o'zgartirsangiz,
# ikkinchisiga ham ko'chiring: botning o'z oqimi ham, platformaning checker
# servisi ham shu koddan foydalanadi. Geometriya va OMR qarorlari
# docs/DECISIONS.md #27-#37, #44 da tushuntirilgan.
"""Javob varag'ini avtomatik tekshirish (OMR).

Oqim:
  1. Rasmdan 4 ta ArUco burchak markeri topiladi -> perspektiva
     to'g'rilanadi (homografiya). Shundan keyin rasm bo'sh shablon bilan
     BIR XIL koordinata tizimiga tushadi.
  2. QR kod o'qiladi (uning joyi ham shablondan ma'lum) -> imzo
     tekshiriladi -> qaysi ishtirokchi ekani aniqlanadi.
  3. Doiralar to'ri varaqqa moslanadi: har doira O'Z JOYI atrofidagi
     kichik oynadan topiladi va shablon nuqtalari ular ustiga
     tushiriladi (DECISIONS.md #44). Doiralar butun varaqdan
     QIDIRILMAYDI — ularning taxminiy joyi shablon chizilganda saqlab
     qo'yilgan (qarang: answer_sheet_service.py -> extract_bubble_boxes,
     DECISIONS.md #29).
  4. Har bir javob doirasining qorong'uligi shu aniqlangan markazdan
     o'lchanadi; natija ham o'sha joyga chiziladi.

Nima uchun mashina o'rganish emas: varaqni o'zimiz chizganimiz uchun har
doiraning joyi aniq ma'lum — bu ko'rish emas, geometriya masalasi.
Model o'rgatish kerak emas va natija takrorlanuvchan.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import cv2
import numpy as np

from config import QR_SECRET
from services.answer_sheet_service import ARUCO_DICT_ID, ARUCO_CORNER_IDS
from utils.qr_payload import verify_qr_payload

logger = logging.getLogger(__name__)

# Perspektiva to'g'rilangandan keyingi ish o'lchami. 200 DPI — doira
# diametri ~33 piksel, bu o'lchash uchun yetarli va tez.
WORK_DPI = 200
_PT_TO_PX = WORK_DPI / 72.0

# Doiraning qaysi qismi o'lchanadi: markazdan radiusning shuncha ulushi.
# To'liq radius olinsa, doira CHEGARASI (qora halqa) ham hisobga tushib,
# bo'sh doira ham qora ko'rinardi.
_SAMPLE_RATIO = 0.55

# Doira "belgilangan" hisoblanishi uchun BO'SH doiralar fonidan shuncha
# qorong'iroq bo'lishi kerak.
#
# Nega qat'iy (absolyut) chegara emas: qorong'i skanda qog'ozning o'zi
# ham qorayadi va bo'sh doiralar ko'tariladi. Sinovda aynan shu yiqilgan
# edi — bo'sh doiralar 111 ga chiqib, Otsu chegarasi 113 bo'lgan va
# ba'zi BO'SH doiralar (113.3) "belgilangan" deb topilgan, natijada
# savol "ikki marta belgilangan" bo'lib javob yo'qolgan.
#
# Fon sifatida hamma doiraning MEDIANASI olinadi: javob berilganda ham
# doiralarning ko'pi (4 tadan 3 tasi, 5 tadan 4 tasi) bo'sh qoladi,
# shuning uchun mediana har doim "bo'sh doira" darajasini ko'rsatadi va
# yorug'lik o'zgarishi bilan birga suriladi.
#
# O'lchandi: to'ldirilgan doira fondan ~135 birlik qorong'iroq, bo'sh
# doiralarning o'zaro tarqalishi esa ~8 birlik. 45 — ikkisining
# o'rtasida, shovqindan ~5 sigma uzoqda.
_MIN_CONTRAST = 45.0

# --- Doiralar to'rini varaqqa moslash --------------------------------------
# Markerlar bo'yicha to'g'rilash perspektivani yo'qotadi, lekin KICHIK
# qoldiq siljish qoladi: printer varaqni bir necha promille kichraytirib
# bosadi, skaner/kamera esa cho'zadi, markerning markazi ham bir-ikki
# piksel xato topiladi. Natijada o'lchov nuqtasi va chizilgan doira
# bosilgan doiradan sal chetga tushadi (DECISIONS.md #44).
#
# Shuning uchun bosilgan doiralarning O'ZI topiladi va shablon nuqtalari
# bilan solishtirib kichik tuzatish (burilish + masshtab + siljish)
# hisoblanadi. Doiralar QIDIRILMAYDI — har biri o'z joyi atrofidagi kichik
# oynadan izlanadi, ya'ni bu hamon geometriya masalasi.
# Qidiruv oynasi radiusning shuncha barobari. Siljigan doira BUTUNLAY
# ichida qolishi kerak (siljish 0.7r + doiraning o'zi 1r), aks holda
# uning bir qismi kesilib, markaz noto'g'ri chiqadi. Yondosh doira esa
# ichkariga kirmaydi: varaqda doiralar markazlari orasidagi masofa
# radiusning 2.5 barobaridan kam emas.
_REFINE_WINDOW = 1.9
_REFINE_MAX_SHIFT = 0.70   # markazdan bundan uzoq topilsa — ishonchsiz
_REFINE_MIN_RADIUS = 0.70  # topilgan doira radiusi shablonnikiga nisbatan
_REFINE_MAX_RADIUS = 1.30
_REFINE_MIN_POINTS = 12    # shundan kam doira topilsa tuzatish qilinmaydi
_REFINE_MIN_DARK = 0.08    # og'irlik markazi bo'yicha topishda: qorong'i
_REFINE_MAX_DARK = 0.45    # piksellar ulushi shu oraliqda bo'lsa — bo'sh halqa
_REFINE_NEIGHBOURS = 4     # topilmagan doira shuncha qo'shnisi bo'yicha qo'yiladi
_REFINE_MIN_ROUNDNESS = 0.55  # kontur o'z aylanasining shuncha qismini to'ldirsin
_REFINE_MAX_CORRECTION = 1.5  # radiusning shuncha barobaridan katta
                              # tuzatish — nimadir noto'g'ri, shablonga qaytamiz


class OmrError(Exception):
    """Varaqni o'qib bo'lmaganda ko'tariladi."""


@dataclass(frozen=True)
class SubjectAnswers:
    name: str
    letters: str
    # answers[i] — (i+1)-savolning javobi; belgilanmagan bo'lsa None.
    answers: list[str | None]
    # Bir nechta doira belgilangan savol raqamlari (javob hisoblanmaydi).
    multi: list[int]


# Belgilash ranglari (BGR) — eski tekshiruvchida ham shu ranglar edi,
# admin ko'nikkan ko'rinish ataylab saqlab qolindi.
_C_CORRECT = (0, 170, 0)     # yashil — o'quvchi to'g'ri belgilagan
_C_WRONG = (0, 0, 230)       # qizil — o'quvchi noto'g'ri belgilagan
_C_EXPECTED = (230, 90, 0)   # ko'k — to'g'ri javob qayerda edi

# Belgilangan varaq rasmi shu ulushda kichraytirib saqlanadi (fayl
# hajmini kamaytirish uchun; 200 DPI dan ~150 DPI ga).
_ANNOT_SCALE = 0.75


@dataclass(frozen=True)
class OmrResult:
    ticket_no: str
    subjects: list[SubjectAnswers]
    # Kalit berilgan bo'lsa — ustiga belgilangan varaq (PNG baytlari).
    annotated_png: bytes | None = None

    @property
    def answered_count(self) -> int:
        return sum(
            1 for s in self.subjects for a in s.answers if a is not None
        )

    @property
    def multi_count(self) -> int:
        return sum(len(s.multi) for s in self.subjects)


def _order_corners(points: list[list[float]]) -> dict[str, tuple[float, float]]:
    """4 ta nuqtani joylashuviga qarab tl/tr/bl/br ga ajratadi.

    Shablonda markerlar tartibsiz saqlangan, lekin ular sahifa
    burchaklarida — shuning uchun x+y va x-y bo'yicha ajratish ishonchli.
    """
    if len(points) != 4:
        raise OmrError(f"Shablonda 4 ta marker kerak, {len(points)} ta bor.")
    pts = [(float(x), float(y)) for x, y in points]
    by_sum = sorted(pts, key=lambda p: p[0] + p[1])
    by_diff = sorted(pts, key=lambda p: p[0] - p[1])
    return {
        "tl": by_sum[0],
        "br": by_sum[-1],
        "bl": by_diff[0],
        "tr": by_diff[-1],
    }


def _detect_markers(gray: np.ndarray) -> dict[int, tuple[float, float]]:
    dictionary = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_ID)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return {}
    found: dict[int, tuple[float, float]] = {}
    for marker_corners, marker_id in zip(corners, ids.flatten()):
        c = marker_corners.reshape(4, 2)
        found[int(marker_id)] = (float(c[:, 0].mean()), float(c[:, 1].mean()))
    return found


def _warp_to_template(
    img: np.ndarray, page_wh: tuple[float, float], marker_centers: list[list[float]]
) -> np.ndarray:
    """Rasmni shablon koordinata tizimiga keltiradi (perspektiva bilan)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    found = _detect_markers(gray)

    missing = [c for c, i in ARUCO_CORNER_IDS.items() if i not in found]
    if missing:
        raise OmrError(
            f"Burchak markerlari to'liq topilmadi (yo'q: {', '.join(missing)}). "
            f"Varaqning to'rtala burchagi ham rasmga tushganiga va rasm aniq "
            f"ekaniga ishonch hosil qiling."
        )

    canonical = _order_corners(marker_centers)
    src = np.array(
        [found[ARUCO_CORNER_IDS[c]] for c in ("tl", "tr", "br", "bl")],
        dtype=np.float32,
    )
    dst = np.array(
        [
            (canonical[c][0] * _PT_TO_PX, canonical[c][1] * _PT_TO_PX)
            for c in ("tl", "tr", "br", "bl")
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    size = (int(page_wh[0] * _PT_TO_PX), int(page_wh[1] * _PT_TO_PX))
    return cv2.warpPerspective(
        img, matrix, size, flags=cv2.INTER_AREA, borderValue=(255, 255, 255)
    )


def _read_ticket_no(warped: np.ndarray, qr_box: list[float]) -> str:
    """QR kodni O'ZINING ma'lum joyidan o'qiydi.

    Butun sahifadan qidirishdan ko'ra aniq joyni kesib olish ancha
    ishonchli — atrofdagi matn va doiralar xalaqit bermaydi.
    """
    x0, y0, x1, y1 = (v * _PT_TO_PX for v in qr_box)
    pad = (x1 - x0) * 0.25
    h, w = warped.shape[:2]
    crop = warped[
        max(0, int(y0 - pad)) : min(h, int(y1 + pad)),
        max(0, int(x0 - pad)) : min(w, int(x1 + pad)),
    ]
    if crop.size == 0:
        raise OmrError("QR kod maydoni rasmdan tashqarida qoldi.")

    detector = cv2.QRCodeDetector()
    for candidate in (crop, cv2.resize(crop, None, fx=2.0, fy=2.0)):
        try:
            payload, points, _ = detector.detectAndDecode(candidate)
        except cv2.error:
            payload = ""
        if payload:
            if not verify_qr_payload(payload, QR_SECRET):
                raise OmrError(
                    "QR kod o'qildi, lekin imzosi noto'g'ri — bu varaq shu "
                    "tizimda chiqarilmagan yoki o'zgartirilgan."
                )
            return payload.split("|", 1)[0].strip().upper()

    raise OmrError(
        "QR kod o'qilmadi. Varaqning yuqori o'ng burchagi aniq va soyasiz "
        "tushganiga ishonch hosil qiling."
    )


def _detect_bubble_center(
    gray: np.ndarray, cx: float, cy: float, r: float
) -> tuple[float, float, float] | None:
    """Shablon nuqtasi atrofidan bosilgan doirani topadi: (x, y, radius).

    Bo'yalgan doira odatda halqadan tashqariga chiqib ketadi va radiusi
    chegaradan oshadi — u ataylab rad etiladi. Tuzatish faqat BO'SH
    doiralar bo'yicha hisoblanadi, ular esa varaqda ko'pchilikni tashkil
    qiladi (4 tadan 3 tasi). Topilmasa None.
    """
    win = int(round(r * _REFINE_WINDOW))
    x0, y0 = int(round(cx)) - win, int(round(cy)) - win
    x1, y1 = int(round(cx)) + win + 1, int(round(cy)) + win + 1
    if x0 < 0 or y0 < 0 or x1 > gray.shape[1] or y1 > gray.shape[0]:
        return None

    patch = gray[y0:y1, x0:x1]
    if patch.size == 0 or int(patch.max()) - int(patch.min()) < 40:
        # Faqat qog'oz (yoki qop-qora dog') — ajratadigan narsa yo'q.
        return None
    _, binary = cv2.threshold(patch, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: tuple[float, float, float, float] | None = None  # (masofa, x, y, r)
    for contour in contours:
        (x, y), found_r = cv2.minEnclosingCircle(contour)
        if not (_REFINE_MIN_RADIUS * r <= found_r <= _REFINE_MAX_RADIUS * r):
            continue
        # Doira o'z aylanasini to'ldiradi; yonidagi savol raqami yoki
        # boshqa matn esa yo'q — shu bilan ularni ajratamiz.
        if cv2.contourArea(contour) < _REFINE_MIN_ROUNDNESS * np.pi * found_r**2:
            continue
        # BO'YALGAN doira o'tkazib yuboriladi: ruchka dog'ining markazi
        # bosilgan doiraning markazi EMAS (o'quvchi chetroq bo'yaydi).
        # Uning o'rni qo'shnilari bo'yicha hisoblanadi — belgi shunda
        # dog'ga emas, doiraning ustiga tushadi.
        yy, xx = np.ogrid[0:binary.shape[0], 0:binary.shape[1]]
        core = (xx - x) ** 2 + (yy - y) ** 2 <= (found_r * 0.55) ** 2
        if core.any() and float((binary[core] > 0).mean()) > _REFINE_MAX_DARK:
            continue
        ax, ay = x + x0, y + y0
        dist = float(np.hypot(ax - cx, ay - cy))
        if dist > _REFINE_MAX_SHIFT * r:
            continue
        if best is None or dist < best[0]:
            best = (dist, ax, ay, float(found_r))
    if best is not None:
        return (best[1], best[2], best[3])

    # Halqa butun kontur bo'lib chiqmadi (qog'oz bukilgan joyda chiziq
    # uzilib ketadi yoki ichidagi harfga yopishadi). Bunda qorong'i
    # piksellarning OG'IRLIK MARKAZI olinadi — halqa ham, ichidagi harf ham
    # doira markazi atrofida joylashgani uchun bu markazni beradi.
    # Bo'yalgan doirada esa ruchka markazdan surilgan bo'lishi mumkin,
    # shuning uchun qorong'i ulush juda katta bo'lsa — rad etiladi
    # (uning o'rni qo'shnilari bo'yicha hisoblanadi).
    # Faqat doira o'lchamidagi DUMALOQ soha — burchaklarga tushgan yondosh
    # matn (savol raqami) hisobga olinmasin. Markaz bir necha qadamda
    # aniqlanadi: har qadamda soha o'tgan qadamdagi markaz atrofiga
    # suriladi, aks holda siljigan doiraning yarmi sohadan tashqarida
    # qolib, og'irlik markazi chetga tortilardi.
    yy, xx = np.ogrid[y0:y1, x0:x1]
    ax, ay = cx, cy
    share = 0.0
    for _ in range(4):
        inside = (xx - ax) ** 2 + (yy - ay) ** 2 <= (r * 1.05) ** 2
        dark = (binary > 0) & inside
        count = int(dark.sum())
        if count == 0:
            return None
        share = count / float(max(1, int(inside.sum())))
        ys, xs = np.nonzero(dark)
        nx, ny = float(xs.mean()) + x0, float(ys.mean()) + y0
        if abs(nx - ax) < 0.2 and abs(ny - ay) < 0.2:
            ax, ay = nx, ny
            break
        ax, ay = nx, ny

    if not (_REFINE_MIN_DARK <= share <= _REFINE_MAX_DARK):
        return None
    if float(np.hypot(ax - cx, ay - cy)) > _REFINE_MAX_SHIFT * r:
        return None
    return (ax, ay, r)


@dataclass(frozen=True)
class _Grid:
    """Har bir doiraning VARAQDAGI joyi (piksel) va o'lchangan radiusi."""

    # (fan indeksi, savol) -> harflar tartibidagi markazlar
    centers: dict[tuple[int, int], list[tuple[float, float]]]
    radius_px: float

    def point(self, si: int, qn: int, i: int) -> tuple[float, float]:
        return self.centers[(si, qn)][i]


def _template_grid(boxes: dict, radius_px: float) -> _Grid:
    """Tuzatishsiz to'r — shablonda qanday bo'lsa shunday (zaxira yo'l)."""
    centers = {
        (si, int(qn)): [(c[0] * _PT_TO_PX, c[1] * _PT_TO_PX) for c in pts]
        for si, subject in enumerate(boxes["subjects"])
        for qn, pts in subject["questions"].items()
    }
    return _Grid(centers, radius_px)


def _fit_grid(gray: np.ndarray, boxes: dict, radius_px: float) -> _Grid:
    """Bosilgan doiralarni topib, to'rni ularning ustiga tushiradi.

    Uch qatlam, har biri oldingisining qoldig'ini yo'qotadi:
      1. Butun varaq bo'yicha bitta tuzatish (burilish + masshtab + siljish)
         — printer/skaner keltirgan bir tekis farq.
      2. Har savol qatori uchun alohida siljish — qog'oz bukilganda yoki
         telefonda suratga olinganda siljish varaq bo'ylab o'zgaradi,
         bitta umumiy tuzatish buni yo'qota olmaydi.
      3. Doiraning o'zi topilgan bo'lsa — aynan o'sha nuqta ishlatiladi.

    Bo'yalgan doira (ruchka halqadan chiqib ketadi) topilmaydi — uning
    o'rni qatordagi qo'shnilari bo'yicha hisoblanadi. Yetarli doira
    topilmasa yoki tuzatish shubhali darajada katta bo'lsa, shablon
    koordinatalari o'z holicha qoladi.
    """
    template = _template_grid(boxes, radius_px)
    found: dict[tuple[int, int], list[tuple[float, float, float] | None]] = {}
    src: list[tuple[float, float]] = []
    dst: list[tuple[float, float]] = []
    radii: list[float] = []

    for si, subject in enumerate(boxes["subjects"]):
        for qn_txt in subject["questions"]:
            qn = int(qn_txt)
            row: list[tuple[float, float, float] | None] = []
            for tx, ty in template.centers[(si, qn)]:
                hit = _detect_bubble_center(gray, tx, ty, radius_px)
                row.append(hit)
                if hit is not None:
                    src.append((tx, ty))
                    dst.append((hit[0], hit[1]))
                    radii.append(hit[2])
            found[(si, qn)] = row

    if len(src) < _REFINE_MIN_POINTS:
        logger.info("Doiralar to'ri: %s ta doira topildi, tuzatish qilinmadi", len(src))
        return template

    matrix, inliers = cv2.estimateAffinePartial2D(
        np.array(src, dtype=np.float32),
        np.array(dst, dtype=np.float32),
        method=cv2.RANSAC,
        ransacReprojThreshold=max(2.0, 0.25 * radius_px),
    )
    if matrix is None or inliers is None or int(inliers.sum()) < _REFINE_MIN_POINTS:
        return template

    def base(points: list[tuple[float, float]]) -> np.ndarray:
        arr = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
        return cv2.transform(arr, matrix).reshape(-1, 2)

    # Umumiy tuzatishdan keyin qolgan farq — qog'ozning bukilishi. U varaq
    # bo'ylab silliq o'zgargani uchun topilmagan doira uchun ENG YAQIN
    # topilgan doiralardan (masofaga teskari og'irlik bilan) hisoblanadi.
    known_at = base(src)
    known_delta = np.array(dst, dtype=np.float32) - known_at

    centers: dict[tuple[int, int], list[tuple[float, float]]] = {}
    moved: list[float] = []
    for key, row in found.items():
        based = base(template.centers[key])
        resolved: list[tuple[float, float]] = []
        for hit, b in zip(row, based):
            if hit is not None:
                resolved.append((hit[0], hit[1]))
                continue
            d = np.hypot(known_at[:, 0] - b[0], known_at[:, 1] - b[1])
            near = np.argsort(d)[:_REFINE_NEIGHBOURS]
            weights = 1.0 / (d[near] + 1.0)
            delta = (known_delta[near] * weights[:, None]).sum(0) / weights.sum()
            resolved.append((float(b[0] + delta[0]), float(b[1] + delta[1])))
        centers[key] = resolved
        moved.extend(
            float(np.hypot(c[0] - t[0], c[1] - t[1]))
            for c, t in zip(resolved, template.centers[key])
        )

    shift = float(np.median(moved))
    if shift > _REFINE_MAX_CORRECTION * radius_px:
        logger.warning(
            "Doiralar to'rining tuzatishi juda katta (%.1f px) — shablon holicha qoldi",
            shift,
        )
        return template

    logger.info(
        "Doiralar to'ri: %s/%s doira topildi, siljish %.1f px (eng katta %.1f)",
        len(src), len(moved), shift, max(moved) if moved else 0.0,
    )
    return _Grid(centers, float(np.median(radii)))


def _bubble_darkness(
    gray: np.ndarray, center_px: tuple[float, float], radius_px: float
) -> float:
    """Doira ichidagi o'rtacha qorong'ulik (0 = oppoq, 255 = qop-qora)."""
    cx, cy = center_px
    r = max(2, int(radius_px * _SAMPLE_RATIO))
    h, w = gray.shape[:2]
    x0, x1 = max(0, int(cx) - r), min(w, int(cx) + r + 1)
    y0, y1 = max(0, int(cy) - r), min(h, int(cy) + r + 1)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0

    # Kvadrat emas, DOIRA shaklidagi niqob — burchaklardagi qo'shni
    # piksellar (masalan yondosh doiraning chetlari) hisobga olinmasin.
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    if not mask.any():
        return 0.0
    return float(255.0 - patch[mask].mean())


def _annotate(
    warped: np.ndarray,
    boxes: dict,
    grid: _Grid,
    marks: dict[tuple[int, int], list[int]],
    answer_keys: dict[str, list[str]],
    ticket_no: str,
) -> np.ndarray:
    """Varaq ustiga tekshiruv natijasini chizadi.

    Doiralar shablon nuqtasiga emas, VARAQDAGI joyiga chiziladi (`grid`) —
    aks holda belgi bosilgan doiradan bir necha piksel chetga tushib,
    qaysi javob belgilangani noaniq ko'rinardi.
    """
    img = warped.copy() if warped.ndim == 3 else cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR)
    r = max(6, int(round(grid.radius_px)))
    lines: list[str] = []
    total_correct = total_questions = 0

    for si, subject in enumerate(boxes["subjects"]):
        letters = subject["letters"]
        key = answer_keys.get(subject["name"]) or []
        correct_count = 0
        for qn_txt, centers in subject["questions"].items():
            qn = int(qn_txt)
            marked = marks.get((si, qn), [])
            want = key[qn - 1] if qn - 1 < len(key) else None
            want_idx = letters.index(want) if want in letters else None

            def px(i, _si=si, _qn=qn):
                cx, cy = grid.point(_si, _qn, i)
                return int(round(cx)), int(round(cy))

            if len(marked) == 1 and want_idx is not None and marked[0] == want_idx:
                cv2.circle(img, px(marked[0]), r, _C_CORRECT, 3)
                correct_count += 1
            elif len(marked) == 1:
                cv2.circle(img, px(marked[0]), r, _C_WRONG, 3)
                if want_idx is not None:
                    cv2.circle(img, px(want_idx), r, _C_EXPECTED, 3)
            else:
                # Belgilanmagan yoki bir nechta belgilangan — javob
                # hisoblanmaydi, faqat to'g'risi ko'rsatiladi.
                for i in marked:
                    cv2.circle(img, px(i), r, _C_WRONG, 3)
                if len(marked) > 1:
                    cv2.line(img, px(0), px(len(centers) - 1), _C_WRONG, 2)
                if want_idx is not None:
                    cv2.circle(img, px(want_idx), r, _C_EXPECTED, 3)

        total_correct += correct_count
        total_questions += len(key)
        lines.append(f"{subject['name']}: {correct_count}/{len(key)}")

    lines.append(f"JAMI: {total_correct}/{total_questions}")
    # Bo'sh (QR'siz) varaqda ID yo'q — bo'sh "ID:" yozuvini chiqarmaymiz.
    if ticket_no:
        lines.append(f"ID: {ticket_no}")

    # Sarlavha panelini varaqning yuqori o'ng bo'sh joyiga qo'yamiz.
    x0 = int(img.shape[1] * 0.60)
    y0 = int(img.shape[0] * 0.012)
    pad, lh = 12, 30
    cv2.rectangle(
        img, (x0 - pad, y0), (img.shape[1] - 10, y0 + lh * len(lines) + pad),
        (255, 255, 255), -1,
    )
    cv2.rectangle(
        img, (x0 - pad, y0), (img.shape[1] - 10, y0 + lh * len(lines) + pad),
        (120, 120, 120), 1,
    )
    for i, txt in enumerate(lines):
        color = _C_EXPECTED if i < len(lines) - 2 else (0, 0, 0)
        cv2.putText(
            img, txt, (x0, y0 + lh * (i + 1)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.62, color, 2, cv2.LINE_AA,
        )
    return img


def build_annotated_pdf(pages: list[bytes]) -> bytes:
    """Belgilangan sahifa rasmlarini bitta PDF qilib yig'adi."""
    import fitz

    doc = fitz.open()
    try:
        for data in pages:
            img_doc = fitz.open(stream=data, filetype="jpg")
            rect = img_doc[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, stream=data)
            img_doc.close()
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def check_sheet(
    image: np.ndarray,
    field_boxes_json: str,
    bubble_boxes_json: str,
    answer_keys: dict[str, list[str]] | None = None,
    require_ticket: bool = True,
) -> OmrResult:
    """Bitta varaq rasmini tekshirib, javoblarni qaytaradi.

    `answer_keys` berilsa (fan nomi -> to'g'ri javoblar ro'yxati),
    natijada ustiga belgilangan varaq rasmi ham qaytariladi.

    `require_ticket=False` — varaqda QR umuman YO'Q (bo'sh varaq qo'lda
    to'ldirilgan) degani: bunda `ticket_no` bo'sh qoladi va varaq
    baribir tekshiriladi. Ishtirokchisi ma'lum varaqlar uchun esa QR
    majburiy — u bo'lmasa natijani kimga yozishni bilmaymiz.
    """
    try:
        fields = json.loads(field_boxes_json)
        boxes = json.loads(bubble_boxes_json)
    except Exception as e:
        raise OmrError(f"Shablon ma'lumoti o'qilmadi: {e}") from e

    page_wh = (boxes["page"][0], boxes["page"][1])
    warped = _warp_to_template(image, page_wh, boxes["markers"])
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY) if warped.ndim == 3 else warped

    if require_ticket:
        ticket_no = _read_ticket_no(warped, fields["qr"]["box"])
    else:
        # Bo'sh varaqda QR yo'q — uni qidirib xato berish o'rniga,
        # varaqni egasiz tekshiraveramiz.
        try:
            ticket_no = _read_ticket_no(warped, fields["qr"]["box"])
        except OmrError:
            ticket_no = ""

    radius_px = float(boxes["radius"]) * _PT_TO_PX
    # Shablon to'rini varaqdagi haqiqiy doiralarga moslaymiz — o'lchov ham,
    # keyin chiziladigan belgi ham aynan doira ustiga tushsin.
    grid = _fit_grid(gray, boxes, radius_px)

    # Avval HAMMA doiraning qorong'uligi o'lchanadi — chegara shu
    # taqsimotdan (Otsu) topiladi, ya'ni skan yorug'ligiga moslashadi.
    measured: list[tuple[int, int, float]] = []  # (fan indeksi, savol, qiymat)
    per_question: dict[tuple[int, int], list[float]] = {}
    for si, subject in enumerate(boxes["subjects"]):
        for qn_txt, centers in subject["questions"].items():
            qn = int(qn_txt)
            vals = [
                _bubble_darkness(gray, grid.point(si, qn, i), grid.radius_px)
                for i in range(len(centers))
            ]
            per_question[(si, qn)] = vals
            measured.extend((si, qn, v) for v in vals)

    if not measured:
        raise OmrError("Shablonda javob doiralari yo'q.")

    baseline = float(np.median([v for _, _, v in measured]))
    threshold = baseline + _MIN_CONTRAST

    subjects: list[SubjectAnswers] = []
    marks: dict[tuple[int, int], list[int]] = {}
    for si, subject in enumerate(boxes["subjects"]):
        letters = subject["letters"]
        count = len(subject["questions"])
        answers: list[str | None] = []
        multi: list[int] = []
        for qn in range(1, count + 1):
            vals = per_question[(si, qn)]
            marked = [i for i, v in enumerate(vals) if v >= threshold]
            marks[(si, qn)] = marked
            if len(marked) == 1:
                answers.append(letters[marked[0]])
            else:
                answers.append(None)
                if len(marked) > 1:
                    multi.append(qn)
        subjects.append(
            SubjectAnswers(
                name=subject["name"], letters=letters, answers=answers, multi=multi
            )
        )

    annotated_png = None
    if answer_keys:
        drawn = _annotate(warped, boxes, grid, marks, answer_keys, ticket_no)
        # PNG emas, JPEG: bu rasm faqat ODAM ko'rib chiqishi uchun, va
        # PNG'da bitta varaq ~600KB bo'lib, 100 ta varaqda fayl Telegram
        # chegarasidan (50MB) oshib ketardi. Biroz kichraytirish ham
        # qilinadi — chizilgan doiralar va matn baribir aniq ko'rinadi.
        small = cv2.resize(drawn, None, fx=_ANNOT_SCALE, fy=_ANNOT_SCALE,
                           interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            annotated_png = buf.tobytes()

    return OmrResult(
        ticket_no=ticket_no, subjects=subjects, annotated_png=annotated_png
    )


def sheet_page_count(data: bytes) -> int:
    """Yuborilgan faylda nechta varaq borligini aytadi (rasm bo'lsa — 1)."""
    if data[:5] == b"%PDF-":
        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        try:
            return doc.page_count
        finally:
            doc.close()
    return 1


def sheet_page_image(data: bytes, index: int) -> np.ndarray:
    """Faylning `index`-sahifasini (0 dan) rasmga aylantiradi.

    HAR SAHIFA ALOHIDA o'qiladi — ataylab. 200 DPI da bitta A4 sahifa
    xotirada ~11 MB joy oladi, ya'ni 50 sahifalik skanni bir yo'la
    ro'yxatga yig'ish 0.5 GB dan oshadi va 1 GB li serverda botni
    systemd o'ldirib yuboradi. Sahifani qayta-qayta ochish arzon: og'ir
    qism — rasmga aylantirish, u baribir bir marta bajariladi.
    """
    if data[:5] == b"%PDF-":
        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        try:
            if not (0 <= index < doc.page_count):
                raise OmrError(f"{index + 1}-sahifa faylda yo'q.")
            pix = doc[index].get_pixmap(dpi=WORK_DPI)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            # nusxa: `arr` pixmap buferiga tayanadi, u esa quyida yopiladi
            return (
                cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                if pix.n >= 3
                else arr.copy()
            )
        finally:
            doc.close()

    if index != 0:
        raise OmrError(f"{index + 1}-sahifa faylda yo'q.")
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise OmrError("Fayl rasm sifatida o'qilmadi.")
    return img

