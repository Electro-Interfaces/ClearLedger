# -*- coding: utf-8 -*-
"""Сверка загруженного слоя с ИСТОЧНИКОМ — самой выгрузкой 1С.

Эталон считается из `/tmp/onec-core.json` (то, что отдал регистр бухгалтерии),
а не берётся константами: зашитые числа годятся ровно одной компании и у второй
превращают сверку в театр — она «сходится» с чужими цифрами.

Сверяется то, на чём стоят витрины: план счетов, проводки и их обороты по годам,
ключевые обороты продаж, справочники, документы, периоды.
"""
import asyncio
import json
import os

from sqlalchemy import func, select, text

from app.database import async_session_factory
from app.models import (
    AccountingDoc, Company, Counterparty, GlAccount, GlEntry, NomenclatureItem, Period,
)
from resolve_org import org_id, org_map

SRC = '/tmp/onec-core.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


def line(name, got, want=None):
    if want is None:
        print('  %-32s %15s' % (name, got))
        return True
    ok = abs(float(got) - float(want)) < 0.02
    print('  %-32s %15.2f  источник %15.2f  %s'
          % (name, float(got), float(want), 'СХОДИТСЯ' if ok else 'РАСХОЖДЕНИЕ'))
    return ok


def src_turnover(entries, dt=None, kt=None):
    """Оборот по источнику: сумма проводок с заданной корреспонденцией."""
    total = 0.0
    for e in entries:
        if dt and e.get('СчетДт') != dt:
            continue
        if kt and e.get('СчетКт') != kt:
            continue
        total += e.get('Сумма') or 0
    return total


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    entries = [e for e in data['02-entries'] if e.get('Период')]
    accounts = data['01-accounts']
    cps = data['03-counterparties']

    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        fails = []

        # Файл источника в контейнере ОДИН на все компании: он перезаписывается каждой
        # доставкой. Сверять слой с чужой выгрузкой хуже, чем не сверять вовсе —
        # «расхождение» тогда означает лишь то, что рядом грузили соседа.
        org_in_file = next((e.get('Организация1С') for e in entries if e.get('Организация1С')), None)
        if org_in_file:
            known = org_map((await s.execute(text(
                "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
                {"c": str(cid)})).all())
            if not org_id(known, org_in_file):
                raise SystemExit(
                    'источник %s принадлежит другой компании (%s) — перевезите выгрузку %s'
                    % (SRC, org_in_file, SLUG))


        print('=== состав (слой против выгрузки) ===')
        for name, model, want in (('счетов', GlAccount, len(accounts)),
                                  ('проводок', GlEntry, len(entries)),
                                  ('контрагентов', Counterparty, len(cps))):
            n = (await s.execute(select(func.count()).select_from(model)
                                 .where(model.company_id == cid))).scalar_one()
            if not line(name, n, want):
                fails.append(name)
        nom = (await s.execute(select(func.count()).select_from(NomenclatureItem)
                               .where(NomenclatureItem.company_id == cid))).scalar_one()
        line('номенклатуры', nom)

        async def turnover(dt=None, kt=None):
            q = select(func.coalesce(func.sum(GlEntry.amount), 0)).where(GlEntry.company_id == cid)
            if dt:
                q = q.where(GlEntry.account_dt == dt)
            if kt:
                q = q.where(GlEntry.account_kt == kt)
            return (await s.execute(q)).scalar_one()

        print('\n=== обороты ===')
        # Сумма всех проводок — главная контрольная цифра: она ловит и потерю строк,
        # и задвоение, чего поштучный счёт не всегда показывает.
        if not line('оборот всего', await turnover(), src_turnover(entries)):
            fails.append('оборот всего')
        for name, dt, kt in (('выручка Кт 90.01.1', None, '90.01.1'),
                             ('НДС продаж 90.03-68.02', '90.03', '68.02'),
                             ('себестоимость Дт 90.02.1', '90.02.1', None)):
            got, want = await turnover(dt, kt), src_turnover(entries, dt, kt)
            if not line(name, got, want):
                fails.append(name)

        print('\n=== обороты по годам ===')
        src_years = {}
        for e in entries:
            src_years[e['Период'][:4]] = src_years.get(e['Период'][:4], 0) + (e.get('Сумма') or 0)
        db_years = dict((str(y), float(a or 0)) for y, a in (await s.execute(
            select(GlEntry.period_year, func.sum(GlEntry.amount))
            .where(GlEntry.company_id == cid).group_by(GlEntry.period_year))).all())
        for y in sorted(set(src_years) | set(db_years)):
            if not line(y, db_years.get(y, 0), src_years.get(y, 0)):
                fails.append('год ' + y)

        print('\n=== документы (из accounting_docs) ===')
        rows = (await s.execute(
            select(AccountingDoc.doc_type, func.count(), func.coalesce(func.sum(AccountingDoc.amount), 0))
            .where(AccountingDoc.company_id == cid)
            .group_by(AccountingDoc.doc_type).order_by(func.count().desc()))).all()
        for kind, n, total in rows:
            print('  %-32s %5d док.  %15.2f' % (kind, n, total))

        print('\n=== ось юрлица ===')
        # Пустая организация у документов значит, что разрез по юрлицу их не увидит,
        # а суммы двух налогоплательщиков сложатся в одну цифру.
        for name, model in (('проводок без юрлица', GlEntry), ('документов без юрлица', AccountingDoc)):
            n = (await s.execute(select(func.count()).select_from(model)
                                 .where(model.company_id == cid,
                                        model.organization_id.is_(None)))).scalar_one()
            line(name, n)

        print('\n=== периоды ===')
        line('месяцев в базе', (await s.execute(select(func.count()).select_from(Period)
                                                .where(Period.company_id == cid))).scalar_one())
        line('из них закрытых', (await s.execute(select(func.count()).select_from(Period)
                                                 .where(Period.company_id == cid,
                                                        Period.status == 'closed'))).scalar_one())

        print('\nИТОГ:', 'всё сходится' if not fails else 'расхождения: ' + ', '.join(fails))


asyncio.run(main())
