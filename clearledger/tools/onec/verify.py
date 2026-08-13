# -*- coding: utf-8 -*-
"""Сходится ли новая аналитика с уже выверенным ядром слоя."""
import asyncio

from sqlalchemy import func, select

from app.database import async_session_factory
from app.models import AccountingDoc, Company, GlBalance, GlEntry, GlTurnover, InvoicePayment, VatEntry


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == 'promizol'))).scalar_one()

        ent = dict((y, float(a or 0)) for y, a in (await s.execute(
            select(GlEntry.period_year, func.sum(GlEntry.amount))
            .where(GlEntry.company_id == cid).group_by(GlEntry.period_year))).all())
        trn = dict((y, float(a or 0)) for y, a in (await s.execute(
            select(GlTurnover.period_year, func.sum(GlTurnover.amount))
            .where(GlTurnover.company_id == cid).group_by(GlTurnover.period_year))).all())

        print('%-6s %18s %18s %12s' % ('год', 'проводки', 'обороты', 'расхождение'))
        bad = 0
        for y in sorted(set(ent) | set(trn)):
            diff = round(ent.get(y, 0) - trn.get(y, 0), 2)
            bad += bool(diff)
            print('%-6d %18.2f %18.2f %12.2f' % (y, ent.get(y, 0), trn.get(y, 0), diff))
        print('итог по годам:', 'сходится' if not bad else 'РАСХОЖДЕНИЕ')

        # Долг покупателей: сальдо 62 против того, что видно в оборотах.
        deb = (await s.execute(
            select(func.sum(GlBalance.debit), func.sum(GlBalance.credit), func.count())
            .where(GlBalance.company_id == cid, GlBalance.account.like('62%')))).one()
        print('\n62-е счета: дебет %.2f, кредит %.2f, строк %d' % (float(deb[0] or 0), float(deb[1] or 0), deb[2]))
        top = (await s.execute(
            select(GlBalance.sub1, func.sum(GlBalance.debit))
            .where(GlBalance.company_id == cid, GlBalance.account.like('62%'))
            .group_by(GlBalance.sub1).order_by(func.sum(GlBalance.debit).desc()).limit(5))).all()
        for name, amount in top:
            print('   %-42s %14.2f' % ((name or '—')[:42], float(amount or 0)))

        # Оплата счетов: сколько счетов закрыто и на какую долю.
        inv = (await s.execute(select(func.count(), func.sum(AccountingDoc.amount))
                               .where(AccountingDoc.company_id == cid,
                                      AccountingDoc.doc_type == 'invoice_out'))).one()
        pay = (await s.execute(select(func.count(func.distinct(InvoicePayment.invoice_doc_id)),
                                      func.sum(InvoicePayment.amount))
                               .where(InvoicePayment.company_id == cid))).one()
        print('\nсчетов покупателям: %d на %.2f' % (inv[0], float(inv[1] or 0)))
        print('из них с оплатой:   %d на %.2f' % (pay[0], float(pay[1] or 0)))
        orphan = (await s.execute(select(InvoicePayment.invoice_title)
                                  .where(InvoicePayment.company_id == cid,
                                         InvoicePayment.invoice_doc_id.is_(None)))).scalars().all()
        print('оплаты без счёта в реестре:', orphan or 'нет')

        # НДС: книга продаж и книга покупок.
        for kind in ('issued', 'received', 'claimed'):
            row = (await s.execute(select(func.count(), func.sum(VatEntry.amount), func.sum(VatEntry.vat))
                                   .where(VatEntry.company_id == cid, VatEntry.kind == kind))).one()
            print('НДС %-9s %5d док. · сумма %14.2f · налог %12.2f'
                  % (kind, row[0], float(row[1] or 0), float(row[2] or 0)))


asyncio.run(main())
