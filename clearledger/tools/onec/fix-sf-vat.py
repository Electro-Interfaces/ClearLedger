# -*- coding: utf-8 -*-
"""НДС счетов-фактур — из журнала учёта: в самом документе реквизита нет, есть ставка.

Журнал (`vat_entries`) уже несёт сумму и налог по каждому счёту-фактуре, и он же —
источник книги продаж. Брать оттуда правильнее, чем считать по ставке: у авансовых
счетов-фактур ставка расчётная (20/120), и формула разошлась бы с книгой.
"""
import asyncio
from collections import defaultdict

from sqlalchemy import select

from app.database import async_session_factory
from app.models import AccountingDoc, Company, VatEntry


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == 'promizol'))).scalar_one()

        # Три ключа, потому что «номер» у разных сторон разный: у полученного
        # счёта-фактуры журнал хранит номер ПОСТАВЩИКА (у нас он в external_number),
        # а у авансовых номера расходятся вовсе — там спасает пара «ИНН + сумма».
        journal = defaultdict(list)
        by_inn_amount = defaultdict(list)
        for v in (await s.execute(select(VatEntry).where(
                VatEntry.company_id == cid, VatEntry.kind.in_(('issued', 'received'))))).scalars():
            journal[((v.number or '').strip(), (v.doc_date or '')[:10])].append(v)
            by_inn_amount[((v.counterparty_inn or ''), round(num(v.amount), 2))].append(v)

        docs = (await s.execute(select(AccountingDoc).where(
            AccountingDoc.company_id == cid,
            AccountingDoc.doc_type.in_(('vat_invoice_out', 'vat_invoice_in'))))).scalars().all()

        fixed = miss = 0
        for d in docs:
            if num(d.vat_amount):
                continue
            cands = journal.get(((d.number or '').strip(), (d.date or '')[:10]), [])
            if not cands and d.external_number:
                cands = journal.get(((d.external_number or '').strip(),
                                     (d.external_date or '')[:10]), [])
            if not cands:
                cands = by_inn_amount.get(((d.counterparty_inn or ''), round(num(d.amount), 2)), [])
            if len(cands) > 1 and d.counterparty_inn:
                cands = [c for c in cands if (c.counterparty_inn or '') == d.counterparty_inn] or cands
            if not cands:
                miss += 1
                continue
            d.vat_amount = round(num(cands[0].vat), 2)
            fixed += 1

        await s.commit()
        print('счетов-фактур:', len(docs), '· проставлен НДС:', fixed, '· не нашлись в журнале:', miss)

        for t in ('vat_invoice_out', 'vat_invoice_in'):
            rows = [d for d in docs if d.doc_type == t]
            print('  %-16s НДС заполнен у %d из %d, сумма налога %.2f' % (
                t, sum(1 for d in rows if num(d.vat_amount)), len(rows),
                sum(num(d.vat_amount) for d in rows)))


asyncio.run(main())
