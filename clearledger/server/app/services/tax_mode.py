# -*- coding: utf-8 -*-
"""Налоговый режим компании — ОДНО определение на всё пространство.

Режим читается по НАЧИСЛЕННОМУ налогу с дохода, а не по галочке в настройках:
галочку забывают переключить, а проводка есть или её нет. 68.04 — налог на прибыль
(ОСНО), 68.12 — налог при УСН, 68.45 — патент; режимы совмещаются (на УСН докупают
патенты под отдельные виды деятельности).

Функция живёт отдельно, потому что от неё зависят три разных экрана — «Налоги»,
«Пульс» и паспорт компании. Пока определение было скопировано в каждый, любая
правка расходилась по продукту: один экран уже знал про патент, другой ещё нет.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SQL = """
    SELECT count(*) FILTER (WHERE account_dt LIKE '68.04%' OR account_kt LIKE '68.04%'),
           count(*) FILTER (WHERE account_dt LIKE '68.12%' OR account_kt LIKE '68.12%'),
           count(*) FILTER (WHERE account_dt LIKE '68.45%' OR account_kt LIKE '68.45%'),
           count(*) FILTER (WHERE account_dt LIKE '68.02%' OR account_kt LIKE '68.02%'),
           count(*) FILTER (WHERE account_kt LIKE '004%')
      FROM gl_entries
     WHERE company_id = CAST(:cid AS uuid)
       AND (CAST(:org AS uuid) IS NULL OR organization_id IS NULL
            OR organization_id = CAST(:org AS uuid))
"""


async def tax_mode(db: AsyncSession, cid, org=None) -> dict[str, Any]:
    """Режим компании: `{osno, usn, patent, vat, commission, label}`.

    `commission` здесь же не случайно: комиссионная торговля (списание с
    забалансового 004) меняет чтение выручки так же сильно, как режим — чтение
    налогов, и спрашивают об этом в тех же местах.
    """
    row = (await db.execute(text(SQL), {"cid": str(cid), "org": str(org) if org else None})).one()
    osno, usn, patent, vat, commission = (bool(x) for x in row)
    names = [n for n, on in (("ОСНО", osno), ("УСН", usn), ("патент", patent)) if on]
    return {
        "osno": osno, "usn": usn, "patent": patent,
        "vat": vat, "commission": commission,
        "label": " + ".join(names) if names else None,
    }
