# -*- coding: utf-8 -*-
"""Банковские документы: 562 списания и 259 поступлений.

Проводки по 51 счёту были, а документов не было — участок «Деньги» пустовал, и часть
проводок цеплялась к чужим документам с совпавшим номером.
"""
import asyncio
import json

import os

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company
from resolve_org import org_id, org_map

SRC = '/tmp/onec-bank.json'


# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    d = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())
        for kind in ('bank_out', 'bank_in'):
            await s.execute(delete(AccountingDoc).where(
                AccountingDoc.company_id == cid, AccountingDoc.doc_type == kind))
        n = {'bank_out': 0, 'bank_in': 0}
        for r in d['01-bank-docs']:
            kind = 'bank_in' if r.get('Направление') == 'Поступление' else 'bank_out'
            num = (r.get('Номер') or '').strip()
            date = (r.get('Дата') or '')[:10]
            inn = (r.get('КонтрагентИНН') or '').strip()
            s.add(AccountingDoc(
                company_id=cid,
                # ИНН в ключе: номер с датой не уникальны даже внутри вида.
                external_id='1c:%s:%s:%s:%s' % (kind, num, date, inn),
                doc_type=kind, number=num or 'б/н', date=date,
                counterparty_name=(r.get('Контрагент') or '')[:500],
                counterparty_inn=inn[:20] or None,
                organization_name=(r.get('Организация1С') or '')[:500] or None,
                organization_id=org_id(orgs, r.get('Организация1С')),
                amount=r.get('Сумма') or 0, lines=[],
                match_status='pending', period_status='open',
                doc_meta={'purpose': (r.get('Назначение') or '')[:1000],
                          'proved': r.get('Проведен')}))
            n[kind] += 1
        await s.commit()
        print('списаний %d, поступлений %d' % (n['bank_out'], n['bank_in']))
asyncio.run(main())
