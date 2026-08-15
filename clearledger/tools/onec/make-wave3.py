# -*- coding: utf-8 -*-
"""Волна 3: недостающие виды документов, честная номенклатура, услуги со счётом затрат.

Закрывает находки ревизии: 471 документ 23 видов не был загружен (в том числе книга
покупок — вычет НДС), 39 групп справочника лежали как товары, ставка НДС 20 % стояла
у всех по умолчанию, 400 строк услуг приехали без счёта затрат и статьи.
"""
import base64
import gzip
import json
import os
import re
from datetime import datetime, timedelta, timezone

SP = os.path.dirname(os.path.abspath(__file__))
MSK = timezone(timedelta(hours=3))


def d(v):
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
for name in ('w3.out.txt', 'w3b.out.txt'):
    with open(os.path.join(SP, name), encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            if line.startswith('{'):
                o = json.loads(line)
                raw[o['query']] = o['rows']
print({k: len(v) for k, v in raw.items()})

data = {'docs': [], 'lines': [], 'nomenclature': [], 'cp_groups': [], 'services': []}

def head(rows, doc_type, *, party=None, inn=None, amount=None, details=None):
    """Шапки нового вида: индексы полей у каждого запроса свои."""
    for r in rows:
        data['docs'].append({
            'type': doc_type, 'number': s(r[0]), 'date': d(r[1]),
            'posted': bool(r[2]), 'deleted': bool(r[3]),
            'party': s(r[party]) if party is not None else None,
            'inn': s(r[inn]) if inn is not None else None,
            'amount': num(r[amount]) if amount is not None else 0.0,
            'details': {k: s(r[i]) for k, i in (details or {}).items() if s(r[i])},
            # Организация — последняя колонка выгрузки (правило README): берём по r[-1],
            # чтобы разбор пережил добавление полей в середину запроса.
            'org': s(r[-1]) if r else None,
        })

head(raw.get('vat_book_in', []), 'vat_book_in', details={'Организация': 4})
head(raw.get('vat_book_out', []), 'vat_book_out', details={'Организация': 4})
head(raw.get('purchase_correction', []), 'purchase_correction', party=4, inn=5, amount=6)
head(raw.get('cash_in', []), 'cash_in', party=4, inn=5, amount=6, details={'Вид операции': 7})
head(raw.get('cash_out', []), 'cash_out', party=4, inn=5, amount=6, details={'Вид операции': 7})
head(raw.get('advance_report', []), 'advance_report', party=4, amount=5, details={'Вид операции': 6})
head(raw.get('payment_order', []), 'payment_order', party=4, inn=5, amount=6)
head(raw.get('demand_note', []), 'demand_note', details={'Склад': 4, 'Счёт затрат': 5, 'Статья затрат': 6})
head(raw.get('goods_writeoff', []), 'goods_writeoff', details={'Склад': 4, 'Вид операции': 5})
head(raw.get('tax_notice', []), 'tax_notice')

# Корректировка долга: две стороны, сумма своя у каждой.
for r in raw.get('debt_correction', []):
    data['docs'].append({
        'type': 'debt_correction', 'number': s(r[0]), 'date': d(r[1]),
        'posted': bool(r[2]), 'deleted': bool(r[3]),
        'party': s(r[4]) or s(r[5]), 'inn': None,
        'amount': num(r[6]) or num(r[7]),
        'details': {k: v for k, v in (('Дебитор', s(r[4])), ('Кредитор', s(r[5])),
                                      ('Вид операции', s(r[8]))) if v},
    })

# Строки складских документов.
for r in raw.get('demand_note_lines', []):
    data['lines'].append({'type': 'demand_note', 'number': s(r[0]), 'date': d(r[1]),
                          'name': s(r[2]), 'code': s(r[3]), 'qty': num(r[4]),
                          'amount': num(r[5]), 'account': s(r[6]),
                          'cost_account': s(r[7]), 'item': s(r[8])})
for r in raw.get('goods_writeoff_lines', []):
    data['lines'].append({'type': 'goods_writeoff', 'number': s(r[0]), 'date': d(r[1]),
                          'name': s(r[2]), 'code': s(r[3]), 'qty': num(r[4]),
                          'amount': 0.0, 'account': s(r[5]),
                          'cost_account': None, 'item': None})

# Услуги поступлений: счёт затрат и статья — 3 млн ₽ расходов были без разреза.
for r in raw.get('purchase_services', []):
    data['services'].append({'number': s(r[0]), 'date': d(r[1]), 'name': s(r[2]),
                             'code': s(r[3]), 'qty': num(r[4]), 'price': num(r[5]),
                             'amount': num(r[6]), 'vat': num(r[7]),
                             'cost_account': s(r[8]), 'item': s(r[9])})

# Номенклатура: группы, ставка, артикул, вид, единица.
RATE = {'Без НДС': 0, '0%': 0, '10%': 10, '20%': 20, '22%': 22, 'Общая': 20}
for r in raw.get('nomenclature', []):
    kind_rate = s(r[4])
    data['nomenclature'].append({
        'code': s(r[0]), 'name': s(r[1]), 'is_group': bool(r[2]),
        'parent': s(r[3]), 'vat_kind': kind_rate,
        'vat_rate': RATE.get(kind_rate, 20),
        'article': s(r[5]), 'deleted': bool(r[6]),
        'kind': s(r[7]), 'unit': s(r[8]),
    })

for r in raw.get('counterparties', []):
    if bool(r[2]):
        data['cp_groups'].append({'code': s(r[0]), 'name': s(r[1])})

print('документов новых видов:', len(data['docs']),
      {t: sum(1 for x in data['docs'] if x['type'] == t) for t in {x['type'] for x in data['docs']}})
print('строк складских:', len(data['lines']), '· услуг:', len(data['services']))
print('номенклатура:', len(data['nomenclature']),
      '· групп:', sum(1 for x in data['nomenclature'] if x['is_group']),
      '· помечено:', sum(1 for x in data['nomenclature'] if x['deleted']),
      '· ставок не 20:', sum(1 for x in data['nomenclature'] if x['vat_rate'] != 20))
print('папок контрагентов:', len(data['cp_groups']))

packed = base64.b64encode(gzip.compress(json.dumps(data, ensure_ascii=False).encode('utf-8'), 9)).decode()

BODY = '''# -*- coding: utf-8 -*-
"""Применение волны 3."""
import base64
import gzip
import json
from collections import defaultdict

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company, Counterparty, NomenclatureItem, Period

DATA = json.loads(gzip.decompress(base64.b64decode(PACKED)).decode('utf-8'))
NEW_TYPES = ('vat_book_in', 'vat_book_out', 'debt_correction', 'purchase_correction',
             'cash_in', 'cash_out', 'advance_report', 'payment_order', 'demand_note',
             'goods_writeoff', 'tax_notice')


def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


from resolve_org import org_id, org_map

import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        closed = {(p.year, p.month) for p in (await s.execute(
            select(Period).where(Period.company_id == cid, Period.status == 'closed'))).scalars()}

        # 1. Новые виды документов. Перезаливаем свои виды целиком — они производные.
        await s.execute(delete(AccountingDoc).where(
            AccountingDoc.company_id == cid, AccountingDoc.doc_type.in_(NEW_TYPES)))
        await s.flush()

        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        by_key = {}
        for doc in DATA['docs']:
            y, m = (int(doc['date'][:4]), int(doc['date'][5:7])) if doc['date'] else (0, 0)
            row = AccountingDoc(
                company_id=cid,
                external_id='1c:%s:%s:%s' % (doc['type'], doc['number'], doc['date']),
                doc_type=doc['type'], number=doc['number'] or '', date=doc['date'] or '',
                counterparty_name=doc['party'] or '', counterparty_inn=doc['inn'],
                # Имя организации приходит из 1С: зашитая строка у второго клиента
                # подписала бы его документы чужим юрлицом.
                organization_name=doc.get('org') or '',
                organization_id=org_id(orgs, doc.get('org')),
                amount=doc['amount'], vat_amount=0,
                status_1c=('Помечен на удаление' if doc['deleted']
                           else 'Проведён' if doc['posted'] else 'Не проведён'),
                period_status='closed' if (y, m) in closed else 'open',
                lines=[], details=doc['details'] or None,
            )
            s.add(row)
            by_key[(doc['type'], doc['number'], doc['date'])] = row
        await s.flush()

        # 2. Строки складских документов.
        lines = defaultdict(list)
        for ln in DATA['lines']:
            lines[(ln['type'], ln['number'], ln['date'])].append(ln)
        for key, rows in lines.items():
            doc = by_key.get(key)
            if doc is None:
                continue
            doc.lines = [{
                'name': r['name'], 'code': r['code'], 'kind': 'goods',
                'qty': r['qty'], 'amount': r['amount'], 'account': r['account'],
                'cost_account': r['cost_account'], 'article': r['item'],
            } for r in rows]
            doc.amount = round(sum(r['amount'] for r in rows), 2) or doc.amount

        # 3. Услуги поступлений: у 400 строк не было ни кода, ни счёта затрат.
        docs = (await s.execute(select(AccountingDoc).where(
            AccountingDoc.company_id == cid,
            AccountingDoc.doc_type == 'purchase'))).scalars().all()
        index = defaultdict(list)
        for doc in docs:
            index[((doc.number or '').strip(), (doc.date or '')[:10])].append(doc)
        svc = defaultdict(list)
        for r in DATA['services']:
            svc[((r['number'] or '').strip(), r['date'] or '')].append(r)
        enriched = 0
        for key, rows in svc.items():
            found = index.get(key, [])
            if len(found) != 1:
                continue
            doc = found[0]
            by_name = {(r['name'] or '').strip().lower(): r for r in rows}
            changed = False
            new_lines = []
            for line in (doc.lines or []):
                r = by_name.get((line.get('name') or '').strip().lower())
                if r and line.get('kind') == 'service':
                    line = {**line, 'code': line.get('code') or r['code'],
                            'account': r['cost_account'], 'article': r['item']}
                    changed = True
                new_lines.append(line)
            if changed:
                doc.lines = new_lines
                enriched += 1

        # 4. Номенклатура: группы, ставка из источника, артикул, вид, единица.
        items = {(n.code or '').strip(): n for n in (await s.execute(
            select(NomenclatureItem).where(NomenclatureItem.company_id == cid))).scalars()}
        upd = added = 0
        for rec in DATA['nomenclature']:
            code = (rec['code'] or '').strip()
            item = items.get(code)
            if item is None:
                item = NomenclatureItem(
                    company_id=cid, code=code, name=rec['name'] or code,
                    unit=rec['unit'] or '', external_ref='1c:%s' % code)
                s.add(item)
                added += 1
            item.is_group = rec['is_group']
            item.parent_name = rec['parent']
            item.vat_kind = rec['vat_kind']
            item.vat_rate = rec['vat_rate']
            item.article = rec['article']
            item.is_deleted = rec['deleted']
            item.kind = rec['kind']
            # Единица снова стала единицей: вид номенклатуры уехал в своё поле.
            if rec['unit']:
                item.unit_label = rec['unit']
            upd += 1

        # 5. Папка справочника контрагентов — не контрагент.
        names = {(g['name'] or '').strip().lower() for g in DATA['cp_groups']}
        groups = 0
        for k in (await s.execute(select(Counterparty)
                                  .where(Counterparty.company_id == cid))).scalars():
            if (k.name or '').strip().lower() in names:
                k.is_group = True
                groups += 1

        await s.commit()
        print('новых документов :', len(by_key))
        print('со строками      :', sum(1 for r in by_key.values() if r.lines))
        print('услуг обогащено  :', enriched, 'документов')
        print('номенклатура     :', upd, 'обновлено ·', added, 'добавлено')
        print('папок контрагента:', groups)


import asyncio
asyncio.run(main())
'''

with open(os.path.join(SP, 'load-wave3.py'), 'w', encoding='utf-8') as f:
    f.write('PACKED = "%s"\n\n%s' % (packed, BODY))
print('load-wave3.py:', os.path.getsize(os.path.join(SP, 'load-wave3.py')) // 1024, 'КБ')
