"""Справочник МРЦ табака наполняется из НСИ станций, а не руками.

`core.tobacco_mrc` — регуляторный справочник: продажа выше максимальной розничной
цены есть нарушение, и контроль в «Магазине» смотрит именно сюда. Заводился он
ручным импортом CSV — и потому стоял пустым, а контроль молчал, будто нарушений
нет. Молчание пустого справочника неотличимо от молчания чистой сети.

Между тем МРЦ уже приезжает сама: её печатают на пачке, касса читает её из кода
маркировки, агент кладёт в НСИ станции, а пакет НСИ доносит до `edge.item`.
Остаётся перенести значение в регуляторный справочник — источник тот же самый,
только теперь без человека посередине.

CSV-импорт это не отменяет: ручная загрузка остаётся способом завести МРЦ там,
где продаж ещё не было. Но если станция прислала своё значение, побеждает оно:
цена напечатана на пачке, и спорить с ней таблицей нельзя.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("clearledger.tobacco.mrc")


async def синхронизировать_мрц(
    session: AsyncSession, company_id: uuid.UUID,
) -> dict[str, int]:
    """Перенести МРЦ из НСИ станций в регуляторный справочник.

    Ключ — GUID номенклатуры: он общий у станции, центра и бухгалтерии, тогда
    как штрихкод у табака меняется от выпуска к выпуску.
    """
    итог = (await session.execute(text("""
        WITH источник AS (
            SELECT external_uuid AS ref,
                   max(name)     AS name,
                   max(gtin)     AS barcode,
                   max(mrc)      AS mrc
              FROM edge.item
             WHERE coalesce(mrc, 0) > 0 AND NOT coalesce(deleted, false)
             GROUP BY external_uuid
        ), записано AS (
            INSERT INTO tobacco_mrc (id, company_id, nomenclature_ref, name,
                                     barcode, mrc, valid_from, updated_at)
            SELECT gen_random_uuid(), :c, ref, name, barcode, mrc,
                   to_char(now(), 'YYYY-MM-DD'), now()
              FROM источник
            ON CONFLICT (company_id, nomenclature_ref) DO UPDATE
               SET mrc = EXCLUDED.mrc, name = EXCLUDED.name,
                   barcode = EXCLUDED.barcode, updated_at = now()
             WHERE tobacco_mrc.mrc IS DISTINCT FROM EXCLUDED.mrc
            RETURNING (xmax = 0) AS создан
        )
        SELECT count(*) FILTER (WHERE создан)      AS заведено,
               count(*) FILTER (WHERE NOT создан)  AS обновлено
          FROM записано
    """), {"c": str(company_id)})).mappings().first()

    всего = (await session.execute(text(
        "SELECT count(*) FROM tobacco_mrc WHERE company_id = :c"),
        {"c": str(company_id)})).scalar()

    return {
        "Заведено": int(итог["заведено"] or 0),
        "Обновлено": int(итог["обновлено"] or 0),
        "ВсегоВСправочнике": int(всего or 0),
    }
