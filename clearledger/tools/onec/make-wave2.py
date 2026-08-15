# -*- coding: utf-8 -*-
"""Волна 2 по документам: настоящий статус, НДС счетов-фактур из реквизита,
расшифровка платежа с НДС и договором, входящий платёжный документ, акт сверки.

Всё, что здесь чинится, ревизия назвала прямо: статус «Проведён» стоял у всех 3256
документов, включая 485 регламентных операций, которые в 1С не проведены; НДС
счетов-фактур считался эвристикой при наличии готового реквизита; у 821 банковского
документа не было ни строк, ни НДС, ни договора; акт сверки был пуст.
"""
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
    """Дата 1С. Пустая приезжает годом 0100 — отличаем по году, а не по знаку."""
    if not isinstance(v, str):
        return None
    m = re.match(r'^/Date\((-?\d+)\)/$', v)
    if not m:
        return None
    try:
        dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=MSK)
    except (OSError, OverflowError, ValueError):
        return None
    return dt.strftime('%Y-%m-%d') if dt.year >= 1900 else None


def s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


raw = {}
with open(os.path.join(SP, 'w2.out.txt'), encoding='utf-8-sig', errors='replace') as f:
    for line in f:
        if line.startswith('{'):
            o = json.loads(line)
            raw[o['query']] = o['rows']
print({k: len(v) for k, v in raw.items()})

data = {'status': [], 'sfvat': [], 'split': [], 'bankhead': [], 'act': [], 'actlines': []}

for r in raw.get('status', []):
    data['status'].append({'type': s(r[0]), 'number': s(r[1]), 'date': d(r[2]),
                           'posted': bool(r[3]), 'deleted': bool(r[4])})
for r in raw.get('sf-vat', []):
    data['sfvat'].append({'type': s(r[0]), 'number': s(r[1]), 'date': d(r[2]),
                          'inn': s(r[3]), 'amount': num(r[4]), 'vat': num(r[5])})
for r in raw.get('bank-split', []):
    data['split'].append({'type': s(r[0]), 'number': s(r[1]), 'date': d(r[2]),
                          'contract': s(r[3]), 'amount': num(r[4]), 'rate': s(r[5]),
                          'vat': num(r[6]), 'item': s(r[7]), 'invoice': s(r[8])})
for r in raw.get('bank-head', []):
    data['bankhead'].append({'type': s(r[0]), 'number': s(r[1]), 'date': d(r[2]),
                             'ext_number': s(r[3]), 'ext_date': d(r[4])})
for r in raw.get('act-head', []):
    data['act'].append({'number': s(r[0]), 'date': d(r[1]), 'inn': s(r[2]),
                        'open_own': num(r[3]), 'open_party': num(r[4]),
                        'diff': num(r[5]), 'has_diff': bool(r[6])})
for r in raw.get('act-lines', []):
    data['actlines'].append({'number': s(r[0]), 'date': d(r[1]), 'line_date': d(r[2]),
                             'title': s(r[3]), 'debit': num(r[4]), 'credit': num(r[5]),
                             'kind': s(r[6])})

print({k: len(v) for k, v in data.items()})
notposted = [x for x in data['status'] if not x['posted']]
print('не проведено в 1С:', len(notposted), {t: sum(1 for x in notposted if x['type'] == t)
                                             for t in {x['type'] for x in notposted}})
print('помечено на удаление:', sum(1 for x in data['status'] if x['deleted']))
print('НДС по счетам-фактурам из реквизита: %.2f' % sum(x['vat'] for x in data['sfvat']))
print('расшифровка платежа: строк %d, НДС %.2f' % (len(data['split']),
                                                   sum(x['vat'] for x in data['split'])))

packed = base64.b64encode(gzip.compress(json.dumps(data, ensure_ascii=False).encode('utf-8'), 9)).decode()

BODY = '''# -*- coding: utf-8 -*-
"""Применение волны 2 к документам слоя."""
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

        index = defaultdict(list)
        for doc in docs:
            index[(doc.doc_type, (doc.number or '').strip(), (doc.date or '')[:10])].append(doc)

        def find(rec):
            found = index.get((rec['type'], (rec['number'] or '').strip(), rec['date'] or ''), [])
            if len(found) > 1 and rec.get('inn'):
                found = [d for d in found if (d.counterparty_inn or '') == rec['inn']]
            return found[0] if len(found) == 1 else None

        # 1. Настоящий статус документа. Непроведённый и помеченный на удаление обязаны
        #    отличаться от действующего: на них строится готовность периода.
        st = miss = 0
        for rec in DATA['status']:
            doc = find(rec)
            if doc is None:
                miss += 1
                continue
            want = ('Помечен на удаление' if rec['deleted']
                    else 'Проведён' if rec['posted'] else 'Не проведён')
            if doc.status_1c != want:
                doc.status_1c = want
                st += 1

        # 2. НДС счетов-фактур — готовым реквизитом «СуммаНДСДокумента», без эвристик.
        vat = 0
        for rec in DATA['sfvat']:
            doc = find(rec)
            if doc is not None and abs(num(doc.vat_amount) - rec['vat']) > 0.004:
                doc.vat_amount = round(rec['vat'], 2)
                vat += 1

        # 3. Расшифровка платежа: строки банковского документа с НДС, договором и статьёй.
        contracts = {}
        for c in (await s.execute(select(Contract).where(Contract.company_id == cid))).scalars():
            contracts.setdefault((str(c.counterparty_id), (c.type or '').strip().lower()), c.id)

        by_doc = defaultdict(list)
        for rec in DATA['split']:
            doc = find(rec)
            if doc is not None:
                by_doc[doc.id].append((doc, rec))
        split_docs = 0
        for rows in by_doc.values():
            doc = rows[0][0]
            doc.lines = [{
                'name': r['item'] or r['contract'] or 'Платёж',
                'article': r['item'], 'kind': 'payment',
                'amount': r['amount'], 'vat': r['vat'], 'vat_rate': r['rate'],
                'invoice': r['invoice'],
            } for _, r in rows]
            doc.vat_amount = round(sum(r['vat'] for _, r in rows), 2)
            name = rows[0][1]['contract']
            if name and not doc.contract_id and doc.counterparty_id:
                doc.contract_id = contracts.get((str(doc.counterparty_id), name.strip().lower()))
            if name:
                doc.details = {**(doc.details or {}), 'Договор': name}
            split_docs += 1

        # 4. Входящий документ банковской операции — номер и дата платёжного поручения.
        bank_ext = 0
        for rec in DATA['bankhead']:
            doc = find(rec)
            if doc is None:
                continue
            if rec['ext_number'] and not doc.external_number:
                doc.external_number = rec['ext_number'][:200]
                doc.external_date = rec['ext_date']
                bank_ext += 1

        # 5. Акт сверки: сальдо, расхождение и строки — до сих пор акт был пуст.
        lines_by_act = defaultdict(list)
        for r in DATA['actlines']:
            lines_by_act[((r['number'] or '').strip(), r['date'] or '')].append(r)
        acts = 0
        for rec in DATA['act']:
            doc = find({**rec, 'type': 'act_recon'})
            if doc is None:
                continue
            rows = lines_by_act.get(((rec['number'] or '').strip(), rec['date'] or ''), [])
            dt = sum(r['debit'] for r in rows)
            kt = sum(r['credit'] for r in rows)
            doc.amount = round(rec['open_own'] + dt - kt, 2)
            doc.lines = [{
                'name': r['title'] or r['kind'] or 'Операция', 'kind': 'recon',
                'article': r['kind'], 'amount': r['debit'] - r['credit'],
                'debit': r['debit'], 'credit': r['credit'], 'date': r['line_date'],
            } for r in rows]
            doc.details = {**(doc.details or {}),
                           'Сальдо на начало': '%.2f' % rec['open_own'],
                           'Сальдо на начало по данным контрагента': '%.2f' % rec['open_party'],
                           'Оборот дебет': '%.2f' % dt, 'Оборот кредит': '%.2f' % kt,
                           'Сальдо на конец': '%.2f' % (rec['open_own'] + dt - kt),
                           'Расхождение': ('есть' if rec['has_diff'] else 'нет')}
            acts += 1

        await s.commit()
        print('статус исправлен у   :', st, '· не сопоставлено:', miss)
        print('НДС счетов-фактур    :', vat)
        print('расшифровка платежа  :', split_docs, 'документов')
        print('входящий документ    :', bank_ext, 'банковских')
        print('акт сверки заполнен  :', acts)

        left = (await s.execute(select(AccountingDoc.status_1c, AccountingDoc.doc_type)
                                .where(AccountingDoc.company_id == cid))).all()
        bad = {}
        for stt, t in left:
            if stt != 'Проведён':
                bad[stt] = bad.get(stt, 0) + 1
        print('после правки статусов:', bad or 'все проведены')


import asyncio
asyncio.run(main())
'''

with open(os.path.join(SP, 'load-wave2.py'), 'w', encoding='utf-8') as f:
    f.write('PACKED = "%s"\n\n%s' % (packed, BODY))
print('load-wave2.py:', os.path.getsize(os.path.join(SP, 'load-wave2.py')) // 1024, 'КБ')
