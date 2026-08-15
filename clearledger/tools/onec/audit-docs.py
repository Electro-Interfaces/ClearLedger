# -*- coding: utf-8 -*-
"""Ревизия документов: что заполнено в шапке, что в строках и где шапка беднее состава."""
import asyncio
from collections import Counter, defaultdict

from sqlalchemy import select

from app.database import async_session_factory
from app.models import AccountingDoc, Company
from app.routers.books_router import DOC_LABELS


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        docs = (await s.execute(select(AccountingDoc)
                                .where(AccountingDoc.company_id == cid))).scalars().all()

        by_type = defaultdict(list)
        for d in docs:
            by_type[d.doc_type].append(d)

        print('%-22s %5s %6s %6s %7s %7s %6s %6s %7s' % (
            'вид', 'шт', 'НДС≠0', 'строк', 'вхНом', 'вхДата', 'склад', 'опер', 'договор'))
        for t, items in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            n = len(items)
            print('%-22s %5d %6d %6d %7d %7d %6d %6d %7d' % (
                DOC_LABELS.get(t, t)[:22], n,
                sum(1 for d in items if num(d.vat_amount)),
                sum(1 for d in items if d.lines),
                sum(1 for d in items if d.external_number),
                sum(1 for d in items if d.external_date),
                sum(1 for d in items if d.warehouse_code),
                sum(1 for d in items if d.operation_type),
                sum(1 for d in items if d.contract_id),
            ))

        print('\n── где шапка беднее состава (НДС есть в строках, в шапке нет) ──')
        for t, items in sorted(by_type.items()):
            bad = [d for d in items if not num(d.vat_amount)
                   and sum(num(l.get('vat')) for l in (d.lines or [])) > 0]
            if bad:
                lost = sum(sum(num(l.get('vat')) for l in (d.lines or [])) for d in bad)
                print('  %-24s %4d док. · НДС в строках на %.2f ₽' %
                      (DOC_LABELS.get(t, t)[:24], len(bad), lost))

        print('\n── сумма шапки против суммы строк ──')
        for t, items in sorted(by_type.items()):
            diff = [d for d in items if d.lines
                    and abs(num(d.amount) - sum(num(l.get('amount')) for l in d.lines)) > 0.01]
            if diff:
                print('  %-24s %4d док. расходятся, пример: %s № %s (шапка %.2f, строки %.2f)' % (
                    DOC_LABELS.get(t, t)[:24], len(diff), diff[0].date, diff[0].number,
                    num(diff[0].amount), sum(num(l.get('amount')) for l in diff[0].lines)))

        print('\n── ключи строк по видам ──')
        for t, items in sorted(by_type.items()):
            keys = Counter()
            for d in items:
                for l in (d.lines or []):
                    keys.update(l.keys())
            if keys:
                print('  %-24s %s' % (DOC_LABELS.get(t, t)[:24], ', '.join(sorted(keys))))

        print('\n── пустые поля шапки (сколько документов без значения) ──')
        fields = ['counterparty_name', 'counterparty_inn', 'organization_name', 'operation_type']
        for f in fields:
            miss = sum(1 for d in docs if not getattr(d, f))
            print('  %-20s %5d из %d' % (f, miss, len(docs)))


asyncio.run(main())
