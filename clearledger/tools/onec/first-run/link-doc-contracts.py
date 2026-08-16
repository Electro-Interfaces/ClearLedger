# -*- coding: utf-8 -*-
"""Связать документы с договорами по ПРЕДСТАВЛЕНИЮ договора из реквизитов.

Документ несёт договор строкой в `details->>'Договор'` («№ 06/21 от 22.06.2021»),
а `enrich-contracts` положил ту же строку в `contracts.title`. До этого документы
связывались по наименованию договора и ловили далеко не всё: у НПК ссылка стояла
у 6047 документов из 18 324, а договор в реквизитах был ещё у 4479.

Идемпотентен: ставит ссылку только там, где её нет, и только внутри своей компании
и своего контрагента — договор с тем же номером у другого клиента не подхватится.
"""
import asyncio
import os

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        company = (await s.execute(
            select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if company is None:
            print('НЕТ компании', SLUG, 'в пространстве')
            return
        cid = str(company.id)

        before = (await s.execute(text(
            "SELECT count(*) FILTER (WHERE contract_id IS NOT NULL), count(*)"
            "  FROM accounting_docs WHERE company_id = CAST(:c AS uuid)"), {"c": cid})).one()

        # Ключ — «контрагент + представление договора». Без контрагента связывать
        # нельзя: «Основной договор» есть у половины клиентов, и документ уехал бы
        # к чужому договору молча.
        res = await s.execute(text("""
            UPDATE accounting_docs d SET contract_id = c.id
              FROM contracts c
             WHERE d.company_id = CAST(:c AS uuid) AND c.company_id = d.company_id
               AND d.contract_id IS NULL AND d.counterparty_id IS NOT NULL
               AND c.counterparty_id = d.counterparty_id
               AND c.title IS NOT NULL
               AND lower(btrim(c.title)) = lower(btrim(d.details->>'Договор'))"""),
            {"c": cid})
        linked = res.rowcount or 0

        # Второй заход — по наименованию договора: у части документов в реквизите
        # стоит не представление, а имя («Основной договор»).
        res = await s.execute(text("""
            UPDATE accounting_docs d SET contract_id = c.id
              FROM contracts c
             WHERE d.company_id = CAST(:c AS uuid) AND c.company_id = d.company_id
               AND d.contract_id IS NULL AND d.counterparty_id IS NOT NULL
               AND c.counterparty_id = d.counterparty_id
               AND lower(btrim(c.type)) = lower(btrim(d.details->>'Договор'))"""),
            {"c": cid})
        linked_by_name = res.rowcount or 0
        await s.commit()

        after = (await s.execute(text(
            "SELECT count(*) FILTER (WHERE contract_id IS NOT NULL), count(*),"
            " count(*) FILTER (WHERE contract_id IS NULL"
            "                    AND coalesce(details->>'Договор','') <> '')"
            "  FROM accounting_docs WHERE company_id = CAST(:c AS uuid)"), {"c": cid})).one()
        print('связано: по представлению %d, по наименованию %d' % (linked, linked_by_name))
        print('документов с договором: было %d, стало %d из %d · осталось с именем '
              'договора без ссылки: %d' % (before[0], after[0], after[1], after[2]))


asyncio.run(main())
