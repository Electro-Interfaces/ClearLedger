# -*- coding: utf-8 -*-
"""Разбор обогащения и сборка загрузчика: реквизиты, обязательные для вида документа."""
import base64
import gzip
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SP = os.path.dirname(os.path.abspath(__file__))
# Пояс с ИСТОРИЕЙ переходов: до 26.10.2014 Москва жила на UTC+4, и фиксированные
# +3 уводили документы тех лет на день назад — проводка не находила своего документа.
MSK = ZoneInfo('Europe/Moscow')


def d(v):
    """Пустая дата 1С приезжает как 0001-01-01 (/Date(-62135596800000)/) — это НЕ дата."""
    if not isinstance(v, str):
        return None
    m = re.match(r'^/Date\((-?\d+)\)/$', v)
    if not m:
        return None
    ms = int(m.group(1))
    if ms < 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=MSK).strftime('%Y-%m-%d')


def s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


raw = {}
with open(os.path.join(SP, 'enrich.out.txt'), encoding='utf-8-sig', errors='replace') as f:
    for line in f:
        line = line.strip()
        if line.startswith('{'):
            o = json.loads(line)
            raw[o['query']] = o['rows']
print({k: len(v) for k, v in raw.items()})

# Как поля выгрузки ложатся на документ: (наш вид, разбор строки → набор реквизитов).
out = []


def add(doc_type, rows, fn):
    for r in rows:
        rec = fn(r)
        rec.update({'type': doc_type, 'number': s(r[0]), 'date': d(r[1])})
        out.append(rec)


add('bank_out', raw.get('bank_out', []), lambda r: {
    'inn': s(r[2]), 'operation': s(r[3]),
    'details': {k: v for k, v in (('Вид операции', s(r[4])), ('Счёт организации', s(r[5])),
                                  ('Статья ДДС', s(r[6]))) if v}})
add('bank_in', raw.get('bank_in', []), lambda r: {
    'inn': s(r[2]), 'operation': s(r[3]),
    'details': {k: v for k, v in (('Вид операции', s(r[4])), ('Счёт организации', s(r[5])),
                                  ('Статья ДДС', s(r[6]))) if v}})
add('purchase', raw.get('purchase', []), lambda r: {
    'inn': s(r[2]), 'ext_number': s(r[3]), 'ext_date': d(r[4]), 'warehouse': s(r[5]),
    'operation': s(r[7]),
    'details': {k: v for k, v in (('Договор', s(r[6])), ('Вид операции', s(r[7]))) if v}})
add('sale', raw.get('sale', []), lambda r: {
    'inn': s(r[2]), 'warehouse': s(r[3]), 'operation': s(r[6]),
    'details': {k: v for k, v in (('Договор', s(r[4])), ('Грузополучатель', s(r[5])),
                                  ('Вид операции', s(r[6]))) if v}})
add('invoice_out', raw.get('invoice_out', []), lambda r: {
    'inn': s(r[2]),
    'details': {k: v for k, v in (('Договор', s(r[3])), ('Организация', s(r[4]))) if v}})
add('invoice_in', raw.get('invoice_in', []), lambda r: {
    'inn': s(r[2]), 'details': {k: v for k, v in (('Договор', s(r[3])),) if v}})
add('vat_invoice_out', raw.get('vat_invoice_out', []), lambda r: {
    'inn': s(r[2]), 'amount': r[3] if isinstance(r[3], (int, float)) else None,
    'details': {k: v for k, v in (('Основание', s(r[4])), ('Код вида операции', s(r[5]))) if v}})
add('vat_invoice_in', raw.get('vat_invoice_in', []), lambda r: {
    'inn': s(r[2]), 'amount': r[3] if isinstance(r[3], (int, float)) else None,
    'ext_number': s(r[4]), 'ext_date': d(r[5]), 'details': {}})
add('act_recon', raw.get('act_recon', []), lambda r: {
    'inn': s(r[2]),
    'details': {k: v for k, v in (('Период с', d(r[3])), ('Период по', d(r[4])),
                                  ('Договор', s(r[5]))) if v}})
add('closing_op', raw.get('closing_op', []), lambda r: {
    'inn': None, 'operation': s(r[2]),
    'details': {k: v for k, v in (('Вид операции', s(r[2])),) if v}})

print('всего записей обогащения:', len(out))
by_type = {}
for r in out:
    by_type[r['type']] = by_type.get(r['type'], 0) + 1
print(by_type)

packed = base64.b64encode(gzip.compress(json.dumps(out, ensure_ascii=False).encode('utf-8'), 9)).decode()
print('в base64:', len(packed) // 1024, 'КБ')

BODY = '''# -*- coding: utf-8 -*-
"""Обогащение шапок документов реквизитами их вида + НДС документа из строк."""
import base64
import gzip
import json
from collections import defaultdict

from sqlalchemy import select

from app.database import async_session_factory
from app.models import AccountingDoc, Company, Contract

DATA = json.loads(gzip.decompress(base64.b64decode(PACKED)).decode('utf-8'))


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

        # Ключ — вид + номер + дата + ИНН: пара «номер, дата» в 1С не уникальна.
        index = defaultdict(list)
        for doc in docs:
            index[(doc.doc_type, (doc.number or '').strip(), (doc.date or '')[:10])].append(doc)

        # Наименование договора лежит в `type` (представление 1С), и «Основной договор»
        # есть почти у каждого контрагента — ключ обязан включать самого контрагента.
        contracts = {}
        for c in (await s.execute(select(Contract).where(Contract.company_id == cid))).scalars():
            contracts.setdefault((str(c.counterparty_id), (c.type or '').strip().lower()), c.id)

        hit = miss = 0
        by_type_miss = defaultdict(int)
        for rec in DATA:
            key = (rec['type'], (rec['number'] or '').strip(), rec['date'] or '')
            found = index.get(key, [])
            if len(found) > 1 and rec.get('inn'):
                found = [d for d in found if (d.counterparty_inn or '') == rec['inn']] or found
            if not found:
                miss += 1
                by_type_miss[rec['type']] += 1
                continue
            hit += 1
            doc = found[0]
            if rec.get('operation'):
                doc.operation_type = rec['operation'][:100]
            if rec.get('ext_number'):
                doc.external_number = rec['ext_number'][:200]
            if rec.get('ext_date'):
                doc.external_date = rec['ext_date']
            if rec.get('warehouse'):
                doc.warehouse_code = rec['warehouse'][:100]
            if rec.get('details'):
                doc.details = rec['details']
            # Договор основанием: у счетов он уже проставлен, у реализации и поступления нет.
            name = (rec.get('details') or {}).get('Договор')
            if name and not doc.contract_id and doc.counterparty_id:
                doc.contract_id = contracts.get((str(doc.counterparty_id), name.strip().lower()))

        # НДС документа: в 1С реквизита нет вовсе, он складывается из строк. Без этого
        # шапка счёта показывала «НДС 0» при налоге в каждой строке.
        vat_fixed = 0
        for doc in docs:
            if num(doc.vat_amount) == 0 and doc.lines:
                total = sum(num(l.get('vat')) for l in doc.lines)
                if total > 0:
                    doc.vat_amount = round(total, 2)
                    vat_fixed += 1

        await s.commit()
        print('обогащено   :', hit, '· не сопоставлено:', miss, dict(by_type_miss))
        print('НДС из строк:', vat_fixed, 'документов')
        with_op = sum(1 for d in docs if d.operation_type)
        with_ext = sum(1 for d in docs if d.external_number)
        with_det = sum(1 for d in docs if d.details)
        with_con = sum(1 for d in docs if d.contract_id)
        print('назначение/вид операции:', with_op, '· входящий документ:', with_ext,
              '· реквизиты вида:', with_det, '· договор:', with_con)


import asyncio
asyncio.run(main())
'''

with open(os.path.join(SP, 'load-enrich.py'), 'w', encoding='utf-8') as f:
    f.write('PACKED = "%s"\n\n%s' % (packed, BODY))
print('load-enrich.py:', os.path.getsize(os.path.join(SP, 'load-enrich.py')) // 1024, 'КБ')
