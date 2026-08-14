# -*- coding: utf-8 -*-
"""Собрать загрузчик для контейнера: данные едут внутри скрипта, сжатыми."""
import base64
import gzip
import os

SP = os.path.dirname(os.path.abspath(__file__))  # каталог коннектора: pull.out.txt, pull.json, load-pull.py

with open(os.path.join(SP, 'pull.json'), 'rb') as f:
    packed = base64.b64encode(gzip.compress(f.read(), 9)).decode()
print('в base64:', len(packed) // 1024, 'КБ')

BODY = '''# -*- coding: utf-8 -*-
"""Загрузка аналитического слоя ПРОМИЗОЛ: обороты с субконто, сальдо, НДС, оплата счетов.

Наборы производные: повторный заход стирает свой source и грузит заново — так
идемпотентность не зависит от того, совпали ли ключи с прошлой выгрузкой.
"""
import base64
import gzip
import json
import re
from datetime import date

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import (AccountingDoc, Company, Counterparty, GlBalance, GlTurnover,
                        InvoicePayment, VatEntry)

DATA = json.loads(gzip.decompress(base64.b64decode(PACKED)).decode('utf-8'))
SRC = '1c_dt'
AS_OF = date(2026, 8, 13)

# «Счет покупателю ХАРД-000123 от 01.02.2024 12:00:00» → номер и дата.
TITLE_RE = re.compile(r'^(?P<kind>.+?)\\s+(?P<number>\\S+)\\s+от\\s+(?P<date>\\d{2}\\.\\d{2}\\.\\d{4})')


def parse_title(t):
    m = TITLE_RE.match(t or '')
    if not m:
        return None, None
    dd, mm, yy = m.group('date').split('.')
    return m.group('number'), '%s-%s-%s' % (yy, mm, dd)


from resolve_org import org_id, org_map

async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == 'promizol'))).scalar_one()

        # Реестры для связей: счета покупателям по «номер|дата», контрагенты по ИНН и имени.
        docs = (await s.execute(select(AccountingDoc.id, AccountingDoc.number, AccountingDoc.date)
                                .where(AccountingDoc.company_id == cid,
                                       AccountingDoc.doc_type == 'invoice_out'))).all()
        by_key = {}
        for did, number, ddate in docs:
            by_key.setdefault('%s|%s' % ((number or '').strip(), (ddate or '')[:10]), did)

        # Организации компании: имя из 1С сводится к ссылке один раз на загрузку.
        # Без этого ось юрлица заполняется только разовой простановкой задним числом,
        # и первая же перезаливка слоя её обнуляет.
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        cps = (await s.execute(select(Counterparty.id, Counterparty.inn, Counterparty.name)
                               .where(Counterparty.company_id == cid))).all()
        by_inn, by_name = {}, {}
        for pid, inn, name in cps:
            if inn:
                by_inn.setdefault(inn.strip(), pid)
            if name:
                by_name.setdefault(name.strip().lower(), pid)

        for model in (GlTurnover, GlBalance, VatEntry, InvoicePayment):
            await s.execute(delete(model).where(model.company_id == cid, model.source == SRC))

        for i, t in enumerate(DATA['turnovers']):
            s.add(GlTurnover(
                company_id=cid, period_year=t['year'], period_month=t['month'],
                account_dt=t['dt'], account_kt=t['kt'],
                dt1=t['dt1'], dt2=t['dt2'], kt1=t['kt1'], kt2=t['kt2'],
                amount=t['amount'], qty_dt=t['qty_dt'], qty_kt=t['qty_kt'], source=SRC,
                organization_id=org_id(orgs, t.get('org')),
                # Ключ по позиции в выгрузке: осмысленный ключ пришлось бы собирать из
                # шести субконто, а идемпотентность и так держит перезалив своего source.
                external_key='t|%d' % i,
            ))

        bal_linked = 0
        for i, b in enumerate(DATA['balances']):
            # У счетов расчётов первое субконто — контрагент; у прочих (склад, статья) связи нет.
            pid = by_name.get((b['sub1'] or '').strip().lower())
            if pid:
                bal_linked += 1
            s.add(GlBalance(
                company_id=cid, as_of=AS_OF, account=b['account'], account_name=b['account_name'],
                counterparty_id=pid,
                sub1=b['sub1'], sub2=b['sub2'], sub3=b['sub3'],
                debit=b['debit'], credit=b['credit'],
                organization_id=org_id(orgs, b.get('org')),
                qty_debit=b['qty_debit'], qty_credit=b['qty_credit'], source=SRC,
                external_key='b|%d' % i,
            ))

        linked = 0
        for i, p in enumerate(DATA['payments']):
            number, ddate = parse_title(p['invoice'])
            doc_id = by_key.get('%s|%s' % (number, ddate)) if number else None
            if doc_id:
                linked += 1
            s.add(InvoicePayment(
                company_id=cid, invoice_title=p['invoice'], payment_title=p['payment'],
                invoice_doc_id=doc_id, paid_at=p['paid_at'],
                amount=p['amount'], vat=p['vat'], source=SRC,
                organization_id=org_id(orgs, p.get('org')),
                external_key='p|%d|%s' % (i, (p['invoice'] or '')[:120]),
            ))

        vat_linked = 0
        for i, v in enumerate(DATA['vat']):
            pid = None
            if v['inn']:
                pid = by_inn.get(v['inn'].strip())
            if not pid and v['counterparty']:
                pid = by_name.get(v['counterparty'].strip().lower())
            if pid:
                vat_linked += 1
            s.add(VatEntry(
                company_id=cid, kind=v['kind'], doc_date=v['doc_date'], number=v['number'],
                counterparty_name=v['counterparty'], counterparty_inn=v['inn'],
                counterparty_kpp=v['kpp'], counterparty_id=pid,
                amount=v['amount'], vat=v['vat'], rate=v['rate'],
                invoice_title=v['invoice_title'], registrar=v['registrar'],
                operation_code=v['operation_code'], source=SRC,
                organization_id=org_id(orgs, v.get('org')),
                external_key='v|%s|%d' % (v['kind'], i),
            ))

        await s.commit()

        with_org = sum(1 for grp in ('turnovers', 'balances', 'payments', 'vat')
                       for x in DATA[grp] if org_id(orgs, x.get('org')))
        total = sum(len(DATA[g]) for g in ('turnovers', 'balances', 'payments', 'vat'))
        print('организация опознана у %d из %d записей' % (with_org, total))
        print('обороты   :', len(DATA['turnovers']))
        print('сальдо    :', len(DATA['balances']), '· контрагент опознан:', bal_linked)
        print('оплаты    :', len(DATA['payments']), '· связано со счетами:', linked)
        print('НДС       :', len(DATA['vat']), '· контрагент опознан:', vat_linked)


import asyncio
asyncio.run(main())
'''

out = 'PACKED = "%s"\n\n%s' % (packed, BODY)
with open(os.path.join(SP, 'load-pull.py'), 'w', encoding='utf-8') as f:
    f.write(out)
print('load-pull.py:', os.path.getsize(os.path.join(SP, 'load-pull.py')) // 1024, 'КБ')
