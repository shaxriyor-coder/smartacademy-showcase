"""Olimpiada o'rinlarini hisoblash.

Reyting HAR SINF UCHUN ALOHIDA hisoblanadi: 4-sinfdagi 1-o'rin
3-sinfdagi 1-o'ringa ta'sir qilmaydi.

Bu mantiq bitta joyda turadi — Excel import, PDF checker va qo'lda
tahrirlash bir xil natijani berishi uchun.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import OlympiadResult

logger = logging.getLogger(__name__)


async def recalculate_olympiad_places(
    session: AsyncSession, olympiad_id: int, grade: int | None = None
) -> int:
    """Bitta olimpiadaning o'rinlarini qayta hisoblaydi.

    `grade` berilsa faqat o'sha sinf, aks holda olimpiadadagi barcha
    sinflar alohida-alohida qayta hisoblanadi.

    Teng ballar bir xil o'rinni oladi, keyingi o'rin esa sakraydi
    ("competition ranking"):

        95 -> 1
        92 -> 2
        92 -> 2
        89 -> 4

    Ball qo'yilmagan (score IS NULL) yozuvlarga o'rin berilmaydi.
    Qaytaradi: o'rni o'zgartirilgan yozuvlar soni.
    """
    if grade is None:
        grades = (
            (
                await session.execute(
                    select(OlympiadResult.grade)
                    .where(
                        OlympiadResult.olympiad_id == olympiad_id,
                        OlympiadResult.score.isnot(None),
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
    else:
        grades = [grade]

    changed = 0
    for g in grades:
        stmt = select(OlympiadResult).where(
            OlympiadResult.olympiad_id == olympiad_id,
            OlympiadResult.score.isnot(None),
        )
        # NULL sinf (eski, sinfsiz yozuvlar) alohida guruh sifatida qaraladi
        stmt = stmt.where(
            OlympiadResult.grade.is_(None) if g is None else OlympiadResult.grade == g
        )
        rows = (
            (await session.execute(stmt.order_by(OlympiadResult.score.desc())))
            .scalars()
            .all()
        )

        place = 0
        prev_score = None
        for idx, r in enumerate(rows, start=1):
            if prev_score is None or r.score != prev_score:
                place = idx
                prev_score = r.score
            if r.place != place:
                r.place = place
                changed += 1

    logger.info(
        "Reyting qayta hisoblandi: olimpiada=%s sinflar=%s o'zgargan=%s",
        olympiad_id,
        grades,
        changed,
    )
    return changed


async def grade_ranking(
    session: AsyncSession, olympiad_id: int, grade: int | None, limit: int | None = None
) -> list[OlympiadResult]:
    """Bir sinfning reyting jadvalini qaytaradi (o'rin bo'yicha tartiblangan)."""
    stmt = select(OlympiadResult).where(
        OlympiadResult.olympiad_id == olympiad_id,
        OlympiadResult.score.isnot(None),
    )
    stmt = stmt.where(
        OlympiadResult.grade.is_(None) if grade is None else OlympiadResult.grade == grade
    )
    stmt = stmt.order_by(
        OlympiadResult.place.asc().nullslast(), OlympiadResult.score.desc()
    )
    if limit:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def grade_counts(session: AsyncSession, olympiad_id: int) -> dict[int | None, int]:
    """Sinf bo'yicha ro'yxatdan o'tganlar soni."""
    rows = (
        await session.execute(
            select(OlympiadResult.grade, func.count())
            .where(OlympiadResult.olympiad_id == olympiad_id)
            .group_by(OlympiadResult.grade)
            .order_by(OlympiadResult.grade)
        )
    ).all()
    return {g: n for g, n in rows}
