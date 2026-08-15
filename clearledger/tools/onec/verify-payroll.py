# -*- coding: utf-8 -*-
"""Зарплатный слой против регистра: аванс проводок не делает, остальное обязано сойтись."""
import asyncio
from sqlalchemy import func, select, text
from app.database import async_session_factory
from app.models import AccountingDoc, Company, PayrollEntry


def n(v):
    return float(v or 0)


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        cid = str((await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one())

        # Документы-авансы помечены в реквизитах: их суммы в регистр не попадают.
        adv = (await s.execute(text("""
            SELECT count(*), coalesce(sum(amount),0) FROM accounting_docs
             WHERE company_id = :cid AND doc_type='payroll_accrual'
               AND details->>'Расчёт' IS NOT NULL"""), {'cid': cid})).one()
        fin = (await s.execute(text("""
            SELECT count(*), coalesce(sum(amount),0) FROM accounting_docs
             WHERE company_id = :cid AND doc_type='payroll_accrual'
               AND details->>'Расчёт' IS NULL"""), {'cid': cid})).one()
        print('начисления: итоговых %d на %.2f · авансовых %d на %.2f'
              % (fin[0], n(fin[1]), adv[0], n(adv[1])))

        book = dict((k, (c, n(a))) for k, c, a in (await s.execute(text("""
            SELECT 'Кт70', count(*), sum(amount) FROM gl_entries
              WHERE company_id=:cid AND account_kt LIKE '70%'
            UNION ALL SELECT 'Кт68.01', count(*), sum(amount) FROM gl_entries
              WHERE company_id=:cid AND account_kt LIKE '68.01%'
            UNION ALL SELECT 'Кт69', count(*), sum(amount) FROM gl_entries
              WHERE company_id=:cid AND account_kt LIKE '69%'
                AND doc_kind = 'Начисление зарплаты'
        """), {'cid': cid})).all())

        layer = dict((k, (c, n(a))) for k, c, a in (await s.execute(text("""
            SELECT kind, count(*), sum(amount) FROM payroll_entries
             WHERE company_id=:cid GROUP BY 1"""), {'cid': cid})).all())

        print('\n%-26s %16s %16s %14s' % ('показатель', 'слой', 'регистр', 'разница'))
        pairs = [
            ('начислено (итоговое)', n(fin[1]), book['Кт70'][1]),
            ('НДФЛ', layer.get('ndfl', (0, 0))[1], book['Кт68.01'][1]),
            ('взносы', layer.get('contribution', (0, 0))[1], book['Кт69'][1]),
        ]
        for label, a, b in pairs:
            print('%-26s %16.2f %16.2f %14.2f' % (label, a, b, a - b))
        print('\nвыплачено по ведомостям: %.2f' % layer.get('payment', (0, 0))[1])

        # НДФЛ и взносы авансовых документов — они тоже не в регистре.
        rows = (await s.execute(text("""
            SELECT p.kind, sum(p.amount) FROM payroll_entries p
              JOIN accounting_docs d ON d.id = p.doc_id
             WHERE p.company_id=:cid AND d.details->>'Расчёт' IS NOT NULL
             GROUP BY 1"""), {'cid': cid})).all()
        print('в т.ч. приходится на авансовые документы:',
              {k: round(n(v), 2) for k, v in rows} or 'нет')


asyncio.run(main())
