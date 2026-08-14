# -*- coding: utf-8 -*-
"""Разбор зарплатного блока 1С и сборка загрузчика.

Порядок тот же, что у остальной первички: сначала нормализованный слой (документы,
сотрудники, строки расчёта), витрины — от него.
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
    if not m or int(m.group(1)) < 0:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=MSK).strftime('%Y-%m-%d')


def s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def read(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            if line.startswith('{'):
                o = json.loads(line)
                out[o['query']] = o['rows']
    return out


raw = {}
for name in ('zpull.out.txt', 'zfix.out.txt', 'zved.out.txt', 'zbin.out.txt',
             'zav.out.txt', 'zvz.out.txt'):
    raw.update(read(os.path.join(SP, name)))
print({k: len(v) for k, v in raw.items()})

data = {'docs': [], 'entries': [], 'employees': []}

# Физлица — источник реквизитов; сотрудник ссылается на физлицо по имени.
persons = {}
for r in raw.get('persons', []):
    name = s(r[0])
    if not name:
        continue
    persons[name] = {'inn': s(r[1]), 'snils': s(r[2]), 'birth': d(r[3]),
                     'deleted': bool(r[4])}

emp_names = set()
for r in raw.get('employees', []):
    name = s(r[0])
    if not name:
        continue
    emp_names.add(name)
    p = persons.get(s(r[1]) or name, {})
    data['employees'].append({
        'name': name, 'person': s(r[1]),
        'inn': p.get('inn'), 'snils': p.get('snils'), 'birth': p.get('birth'),
        'deleted': bool(r[2]) or bool(p.get('deleted')),
    })

# Проведённость начислений — отдельным запросом (f1: Номер, Проведен, Удален).
flags = {}
for r in raw.get('f1', []):
    flags[s(r[0]) or ''] = {'posted': bool(r[1]), 'deleted': bool(r[2])}

# Аванс (первая половина месяца) — отдельная выгрузка: в основном запросе поля нет.
advance = {}
for r in raw.get('avans-doc', []):
    advance[(s(r[0]) or '', d(r[1]) or '')] = bool(r[2])

# Начисление зарплаты: Номер, Дата, Месяц, Начислено, Удержано, Проведен, Удален,
# Подразделение, Комментарий.
for r in raw.get('accrual', []):
    number, date = s(r[0]), d(r[1])
    f = flags.get(number or '', {})
    data['docs'].append({
        'type': 'payroll_accrual', 'number': number, 'date': date,
        'month': (d(r[2]) or '')[:7] or None,
        'amount': num(r[3]), 'deducted': num(r[4]),
        'posted': bool(r[5]) if r[5] is not None else f.get('posted', True),
        'deleted': bool(r[6]) if r[6] is not None else f.get('deleted', False),
        'department': s(r[7]), 'comment': s(r[8]),
        'advance': advance.get((number or '', date or ''), False),
    })

# Ведомость: Номер, Дата, Месяц, Сумма, ДатаВыплаты, Проведен, Удален.
for r in raw.get('payment', []):
    data['docs'].append({
        'type': 'payroll_payment', 'number': s(r[0]), 'date': d(r[1]),
        'month': (d(r[2]) or '')[:7] or None,
        'amount': num(r[3]), 'deducted': 0.0,
        'paid_at': d(r[4]),
        'posted': bool(r[5]) if len(r) > 5 and r[5] is not None else True,
        'deleted': bool(r[6]) if len(r) > 6 and r[6] is not None else False,
        'department': None, 'comment': None,
    })

# Строки расчёта. Ключ документа — вид + номер + дата, как во всём слое.
for r in raw.get('accrual-lines', []):
    data['entries'].append({
        'kind': 'accrual', 'doc_type': 'payroll_accrual',
        'number': s(r[0]), 'date': d(r[1]),
        'employee': s(r[2]), 'name': s(r[3]), 'amount': num(r[4]),
        'days': num(r[5]) or None, 'hours': num(r[6]) or None,
        'department': s(r[7]), 'month': None,
    })
for r in raw.get('accrual-hold', []):
    data['entries'].append({
        'kind': 'deduction', 'doc_type': 'payroll_accrual',
        'number': s(r[0]), 'date': d(r[1]),
        'employee': s(r[2]), 'name': s(r[3]), 'amount': num(r[4]),
        'days': None, 'hours': None, 'department': None, 'month': None,
    })
for r in raw.get('accrual-ndfl', []):
    data['entries'].append({
        'kind': 'ndfl', 'doc_type': 'payroll_accrual',
        'number': s(r[0]), 'date': d(r[1]),
        'employee': s(r[2]), 'name': s(r[5]) or 'НДФЛ', 'amount': num(r[4]),
        'days': None, 'hours': None, 'department': None,
        'month': (d(r[3]) or '')[:7] or None,
    })
for r in raw.get('payment-lines', []):
    data['entries'].append({
        'kind': 'payment', 'doc_type': 'payroll_payment',
        'number': s(r[0]), 'date': d(r[1]),
        'employee': s(r[2]), 'name': 'К выплате', 'amount': num(r[3]),
        'days': None, 'hours': None, 'department': None,
        'month': (d(r[4]) or '')[:7] or None,
    })

# Взносы: одна строка ТЧ несёт суммы сразу по нескольким фондам — разворачиваем в
# отдельные записи, иначе «сколько ушло в ФСС» отвечается только чтением колонок.
FUNDS = [(4, 'Взносы ПФР (единый тариф)'), (5, 'Взносы ПФР'), (6, 'Взносы ФФОМС'),
         (7, 'Взносы ФСС'), (8, 'Взносы ФСС (несчастные случаи)')]
for r in raw.get('vznosy', []):
    for idx, label in FUNDS:
        amount = num(r[idx])
        if not amount:
            continue
        data['entries'].append({
            'kind': 'contribution', 'doc_type': 'payroll_accrual',
            'number': s(r[0]), 'date': d(r[1]),
            'employee': s(r[2]), 'name': label, 'amount': amount,
            'days': None, 'hours': None, 'department': None,
            'month': (d(r[3]) or '')[:7] or None,
        })

# Сотрудники, встреченные в строках, но отсутствующие в справочнике (расчёты по
# договорам ГПХ идут физлицом, а не сотрудником).
known = {e['name'] for e in data['employees']}
for e in data['entries']:
    n = e['employee']
    if n and n not in known:
        known.add(n)
        p = persons.get(n, {})
        data['employees'].append({
            'name': n, 'person': n, 'inn': p.get('inn'), 'snils': p.get('snils'),
            'birth': p.get('birth'), 'deleted': bool(p.get('deleted')),
        })

print('документов:', len(data['docs']), '· строк расчёта:', len(data['entries']),
      '· сотрудников:', len(data['employees']))
by_kind = {}
for e in data['entries']:
    by_kind[e['kind']] = by_kind.get(e['kind'], 0) + 1
print('по видам строк:', by_kind)
print('начислено по шапкам: %.2f' % sum(x['amount'] for x in data['docs'] if x['type'] == 'payroll_accrual'))
print('начислено по строкам: %.2f' % sum(e['amount'] for e in data['entries'] if e['kind'] == 'accrual'))
print('НДФЛ по строкам:     %.2f' % sum(e['amount'] for e in data['entries'] if e['kind'] == 'ndfl'))
print('выплачено по строкам: %.2f' % sum(e['amount'] for e in data['entries'] if e['kind'] == 'payment'))
print('взносы по строкам:   %.2f' % sum(e['amount'] for e in data['entries'] if e['kind'] == 'contribution'))

packed = base64.b64encode(gzip.compress(json.dumps(data, ensure_ascii=False).encode('utf-8'), 9)).decode()

BODY = '''# -*- coding: utf-8 -*-
"""Загрузка зарплатного блока: документы в общий реестр, сотрудники и строки расчёта.

Наборы производные: повторный заход стирает свой source и грузит заново.
"""
import base64
import gzip
import json
from datetime import date

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company, Employee, PayrollEntry, Period

DATA = json.loads(gzip.decompress(base64.b64decode(PACKED)).decode('utf-8'))
SRC = '1c_dt'


from resolve_org import org_id, org_map

async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == 'promizol'))).scalar_one()

        # Статус периода — как у остальной первички: закрытый месяц неизменяем.
        closed = {(p.year, p.month) for p in (await s.execute(
            select(Period).where(Period.company_id == cid, Period.status == 'closed'))).scalars()}

        await s.execute(delete(PayrollEntry).where(
            PayrollEntry.company_id == cid, PayrollEntry.source == SRC))
        await s.execute(delete(Employee).where(
            Employee.company_id == cid, Employee.source == SRC))
        await s.execute(delete(AccountingDoc).where(
            AccountingDoc.company_id == cid,
            AccountingDoc.doc_type.in_(('payroll_accrual', 'payroll_payment'))))
        await s.flush()

        emp_by_name = {}
        for e in DATA['employees']:
            row = Employee(
                company_id=cid, name=e['name'], inn=e['inn'], snils=e['snils'],
                birth_date=e['birth'], is_deleted=e['deleted'], source=SRC,
                external_key='e|%s' % e['name'][:200],
            )
            s.add(row)
            emp_by_name[e['name']] = row

        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        doc_by_key = {}
        for i, doc in enumerate(DATA['docs']):
            y, m = (int(doc['date'][:4]), int(doc['date'][5:7])) if doc['date'] else (0, 0)
            row = AccountingDoc(
                company_id=cid,
                external_id='1c:%s:%s:%s' % (doc['type'], doc['number'], doc['date']),
                doc_type=doc['type'], number=doc['number'] or '', date=doc['date'] or '',
                counterparty_name='',
                organization_name=doc.get('org') or '',
                organization_id=org_id(orgs, doc.get('org')),
                amount=doc['amount'], vat_amount=0,
                # Помеченный на удаление и непроведённый документ обязан отличаться от
                # действующего: иначе аудитор считает его нормальным.
                status_1c=('Помечен на удаление' if doc['deleted']
                           else 'Проведён' if doc['posted'] else 'Не проведён'),
                period_status='closed' if (y, m) in closed else 'open',
                lines=[],
                details={k: v for k, v in (
                    ('Месяц начисления', doc.get('month')),
                    ('Подразделение', doc.get('department')),
                    ('Дата выплаты', doc.get('paid_at')),
                    ('Удержано', ('%.2f' % doc['deducted']) if doc.get('deducted') else None),
                    ('Комментарий', doc.get('comment')),
                    # Аванс проводок не делает — без пометки его сумма читается как
                    # расхождение слоя с регистром бухгалтерии.
                    ('Расчёт', 'аванс за первую половину месяца' if doc.get('advance') else None),
                ) if v},
            )
            s.add(row)
            doc_by_key[(doc['type'], doc['number'], doc['date'])] = row

        await s.flush()

        linked = 0
        for i, e in enumerate(DATA['entries']):
            doc = doc_by_key.get((e['doc_type'], e['number'], e['date']))
            if doc is not None:
                linked += 1
            emp = emp_by_name.get(e['employee']) if e['employee'] else None
            s.add(PayrollEntry(
                company_id=cid, kind=e['kind'],
                doc_id=doc.id if doc is not None else None,
                employee_id=emp.id if emp is not None else None,
                employee_name=e['employee'], name=e['name'],
                period_month=e['month'] or (e['date'] or '')[:7],
                doc_date=e['date'], amount=e['amount'],
                days=e['days'], hours=e['hours'], department=e['department'],
                source=SRC, external_key='p|%d' % i,
            ))

        # Состав документа — строки его расчёта: карточка обязана показывать, из чего
        # сложилась сумма, тем же способом, что у накладной.
        for (dtype, number, ddate), doc in doc_by_key.items():
            doc.lines = [{
                'name': e['employee'] or e['name'], 'kind': e['kind'],
                'article': e['name'], 'amount': e['amount'],
                'qty': e['days'], 'hours': e['hours'],
            } for e in DATA['entries']
                if e['doc_type'] == dtype and e['number'] == number and e['date'] == ddate]

        await s.commit()
        print('документов:', len(doc_by_key), '· сотрудников:', len(emp_by_name),
              '· строк расчёта:', len(DATA['entries']), '· со связью на документ:', linked)


import asyncio
asyncio.run(main())
'''

with open(os.path.join(SP, 'load-payroll.py'), 'w', encoding='utf-8') as f:
    f.write('PACKED = "%s"\n\n%s' % (packed, BODY))
print('load-payroll.py:', os.path.getsize(os.path.join(SP, 'load-payroll.py')) // 1024, 'КБ')
