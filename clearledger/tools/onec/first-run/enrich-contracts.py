# -*- coding: utf-8 -*-
"""Дописать договорам представление 1С и срок действия — БЕЗ перезагрузки.

`load-contracts` стирает договоры и заводит заново, а на них уже стоят ссылки
документов (`accounting_docs.contract_id`, у НПК их шесть тысяч): перезагрузка их
обнулит молча. Поэтому добор реквизитов идёт обновлением по ключу
«контрагент + номер + дата», а не через delete/insert.

Данные читает из /tmp/onec-core.json (ключ `08-contracts`).
"""
import asyncio
import json
import os

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company

SRC = '/tmp/onec-core.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    rows = data.get('08-contracts') or []
    if not rows:
        print('в выгрузке нет договоров — нечего дописывать')
        return

    async with async_session_factory() as s:
        company = (await s.execute(
            select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if company is None:
            print('НЕТ компании', SLUG, 'в пространстве')
            return
        cid = str(company.id)

        by_inn = {(r[1] or '').strip(): r[0] for r in (await s.execute(text(
            "SELECT id::text, inn FROM counterparties WHERE company_id = :c"),
            {"c": cid})).all() if (r[1] or '').strip() not in ('', '0')}

        updated = missed = 0
        for c in rows:
            if c.get('Удален'):
                continue
            cp = by_inn.get((c.get('КонтрагентИНН') or '').strip())
            if not cp:
                missed += 1
                continue
            p = {"c": cid, "cp": cp,
                 "num": (c.get('Номер') or '').strip()[:100] or 'б/н',
                 "dt": (c.get('Дата') or ''),
                 "name": (c.get('Наименование') or '')[:100],
                 "title": ((c.get('Договор') or c.get('Наименование') or '').strip() or None),
                 "term": ((c.get('СрокДействия') or '') or None)}
            # Ключ — НАИМЕНОВАНИЕ договора (в слое оно лежит в `type`): у клиентов
            # половина договоров без номера и без даты, и ключ «номер + дата» бьёт по
            # всем «б/н» разом — одному достаётся чужое представление, остальным ничего.
            res = await s.execute(text("""
                UPDATE contracts SET title = :title, valid_until = :term
                 WHERE company_id = :c AND counterparty_id = CAST(:cp AS uuid)
                   AND type = :name"""), p)
            if not res.rowcount:
                res = await s.execute(text("""
                    UPDATE contracts SET title = :title, valid_until = :term
                     WHERE company_id = :c AND counterparty_id = CAST(:cp AS uuid)
                       AND number = :num AND date = :dt"""), p)
            if res.rowcount:
                updated += res.rowcount
            else:
                missed += 1
        await s.commit()

        have = (await s.execute(text(
            "SELECT count(*) FILTER (WHERE title IS NOT NULL),"
            " count(*) FILTER (WHERE valid_until IS NOT NULL), count(*)"
            "  FROM contracts WHERE company_id = :c"), {"c": cid})).one()
        print('обновлено строк: %d · не нашли пары: %d' % (updated, missed))
        print('в слое: с представлением %d, со сроком действия %d, всего %d' % tuple(have))


asyncio.run(main())
