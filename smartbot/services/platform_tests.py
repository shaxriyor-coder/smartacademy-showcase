"""SmartAcademy platformasidan FAQAT O'QISH (docs/DECISIONS.md #40, #45).

Ikki narsa uchun:
  • javob varag'ini sozlashda platformada tuzilgan test tanlansa, fan nomi,
    savollar soni, variantlar soni va javob kaliti shu yerdan olinadi;
  • varaqqa ishtirokchilar bosilayotganda o'qituvchining o'z guruhlari va
    ulardagi o'quvchilar shu yerdan olinadi (Excel to'ldirish shart emas).

Admin qo'lda kiritmagani uchun varaq va kalit test bilan mos kelmay
qolmaydi, ism-familiyada ham xato bo'lmaydi.

Platforma bazasiga hech narsa YOZILMAYDI: ulanish read-only foydalanuvchi
bilan (deploy/postgres/setup.sql) va so'rovlar faqat SELECT. `PLATFORM_
DATABASE_URL` bo'sh bo'lsa bu imkoniyat butunlay o'chadi — bot avvalgidek
ishlayveradi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg

from config import PLATFORM_DATABASE_URL

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

# Bitta olimpiadaga nechta test ko'rsatiladi (inline tugmalar ro'yxati).
MAX_TESTS = 8

_SELECT = """
    SELECT t.id,
           t.title,
           s.name AS subject_name,
           coalesce(array_length(t."questionIds", 1), 0) AS question_count,
           t."choiceCount" AS choice_count,
           t."answerKey" AS answer_key
      FROM "Test" t
      JOIN "Subject" s ON s.id = t."subjectId"
"""


@dataclass(frozen=True)
class PlatformTest:
    id: str
    title: str
    subject_name: str
    question_count: int
    choice_count: int | None
    answer_key: list[str]

    @property
    def key_matches(self) -> bool:
        """Kalit savollar soniga mos kelsa — javob varag'iga yozsa bo'ladi."""
        return bool(self.answer_key) and len(self.answer_key) == self.question_count


def platform_configured() -> bool:
    return bool(PLATFORM_DATABASE_URL)


async def _pool_or_none() -> asyncpg.Pool | None:
    global _pool
    if not platform_configured():
        return None
    if _pool is None:
        _pool = await asyncpg.create_pool(
            PLATFORM_DATABASE_URL, min_size=0, max_size=2, command_timeout=10
        )
    return _pool


def _row_to_test(row: asyncpg.Record) -> PlatformTest:
    return PlatformTest(
        id=row["id"],
        title=row["title"],
        subject_name=row["subject_name"],
        question_count=row["question_count"] or 0,
        choice_count=row["choice_count"],
        answer_key=list(row["answer_key"] or []),
    )


async def tests_for_olympiad(olympiad_id: int) -> list[PlatformTest]:
    """Shu olimpiadaga biriktirilgan testlar (yangisi birinchi). Xato bo'lsa —
    bo'sh ro'yxat: javob varag'ini qo'lda sozlash yo'li baribir ochiq."""
    pool = await _pool_or_none()
    if pool is None:
        return []
    try:
        rows = await pool.fetch(
            _SELECT + ' WHERE t."smartbotOlympiadId" = $1 ORDER BY t."createdAt" DESC LIMIT $2',
            olympiad_id,
            MAX_TESTS,
        )
    except Exception as e:  # tarmoq/ruxsat xatosi — botni to'xtatmaydi
        logger.warning(f"Platforma testlarini o'qib bo'lmadi (olimpiada={olympiad_id}): {e}")
        return []
    return [_row_to_test(r) for r in rows]


async def test_by_id(test_id: str) -> PlatformTest | None:
    """Tanlangan testni qayta o'qiydi — tugma bosilguncha o'zgargan bo'lishi mumkin."""
    pool = await _pool_or_none()
    if pool is None:
        return None
    try:
        row = await pool.fetchrow(_SELECT + " WHERE t.id = $1", test_id)
    except Exception as e:
        logger.warning(f"Platforma testini o'qib bo'lmadi ({test_id}): {e}")
        return None
    return _row_to_test(row) if row else None


# --- O'qituvchining guruhlari (DECISIONS.md #45) ----------------------------

# Bitta ekranga sig'adigan guruhlar soni.
MAX_CLASSROOMS = 20
# Bitta varaqlar to'plamiga olinadigan eng ko'p o'quvchi (services/
# test_sheet_excel.py -> MAX_PARTICIPANTS bilan bir xil).
MAX_STUDENTS = 500


@dataclass(frozen=True)
class PlatformClassroom:
    id: str
    name: str
    subject_name: str | None
    student_count: int

    @property
    def label(self) -> str:
        fan = f" · {self.subject_name}" if self.subject_name else ""
        return f"{self.name}{fan} ({self.student_count} ta)"


async def classrooms_for(chat_id: int) -> list[PlatformClassroom]:
    """Shu Telegram akkaunti o'qituvchi bo'lgan guruhlar (arxivsiz).

    Bog'lanish platformadagi `User.telegramChatId` orqali: botdagi xodim
    platformada ham o'sha Telegram ID bilan turadi (DECISIONS.md #23).
    Xato yoki sozlanmagan bo'lsa — bo'sh ro'yxat, Excel yo'li ochiq qoladi.
    """
    pool = await _pool_or_none()
    if pool is None:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT c.id,
                   c.name,
                   s.name AS subject_name,
                   count(m.id) AS student_count
              FROM "Classroom" c
              JOIN "User" u ON u.id = c."teacherId"
              LEFT JOIN "Subject" s ON s.id = c."subjectId"
              LEFT JOIN "ClassroomMember" m ON m."classroomId" = c.id
             WHERE u."telegramChatId" = $1 AND c.archived = false
             GROUP BY c.id, c.name, s.name, c."createdAt"
             ORDER BY c."createdAt" DESC
             LIMIT $2
            """,
            str(chat_id),
            MAX_CLASSROOMS,
        )
    except Exception as e:
        logger.warning(f"Platforma guruhlarini o'qib bo'lmadi (chat_id={chat_id}): {e}")
        return []
    return [
        PlatformClassroom(
            id=r["id"],
            name=r["name"],
            subject_name=r["subject_name"],
            student_count=int(r["student_count"] or 0),
        )
        for r in rows
    ]


async def classroom_by_id(classroom_id: str) -> PlatformClassroom | None:
    """Bitta guruh — tugma bosilgandan keyin nomini qayta o'qish uchun."""
    pool = await _pool_or_none()
    if pool is None:
        return None
    try:
        row = await pool.fetchrow(
            """
            SELECT c.id,
                   c.name,
                   s.name AS subject_name,
                   (SELECT count(*) FROM "ClassroomMember" m WHERE m."classroomId" = c.id)
                       AS student_count
              FROM "Classroom" c
              LEFT JOIN "Subject" s ON s.id = c."subjectId"
             WHERE c.id = $1
            """,
            classroom_id,
        )
    except Exception as e:
        logger.warning(f"Guruhni o'qib bo'lmadi ({classroom_id}): {e}")
        return None
    if row is None:
        return None
    return PlatformClassroom(
        id=row["id"],
        name=row["name"],
        subject_name=row["subject_name"],
        student_count=int(row["student_count"] or 0),
    )


async def classroom_students(classroom_id: str) -> list[dict]:
    """Guruhdagi o'quvchilar — javob varag'i kutgan ko'rinishda.

    Kalitlar `services/test_sheet_excel.py -> parse_participants` bilan bir
    xil (ism, familiya, birth_date, sinf), shunda varaq yasash kodiga
    o'quvchilar Excel'dan kelganmi yoki guruhdanmi — farqi yo'q.
    """
    pool = await _pool_or_none()
    if pool is None:
        return []
    try:
        rows = await pool.fetch(
            """
            SELECT st."firstName", st."lastName", st."birthDate", st.grade
              FROM "ClassroomMember" m
              JOIN "Student" st ON st.id = m."studentId"
             WHERE m."classroomId" = $1
             ORDER BY st."lastName" NULLS LAST, st."firstName"
             LIMIT $2
            """,
            classroom_id,
            MAX_STUDENTS,
        )
    except Exception as e:
        logger.warning(f"Guruh o'quvchilarini o'qib bo'lmadi ({classroom_id}): {e}")
        return []
    return [
        {
            "row_no": i,
            "ism": (r["firstName"] or "").strip()[:150],
            "familiya": (r["lastName"] or "").strip()[:150],
            "birth_date": r["birthDate"].isoformat() if r["birthDate"] else None,
            "sinf": (r["grade"] or "").strip()[:50],
        }
        for i, r in enumerate(rows, start=1)
    ]


async def close_platform_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
