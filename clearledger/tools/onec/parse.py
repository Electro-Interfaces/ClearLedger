# -*- coding: utf-8 -*-
"""Разбор выгрузки 1С в нормализованный вид и сборка загрузчика для контейнера.

Даты 1С приезжают как /Date(ms)/, где ms отсчитаны от эпохи UTC, а само время в базе
московское: без tz=+3 всё, что лежит в 00:00–02:59, уезжает на предыдущий день.
"""
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

SP = os.path.dirname(os.path.abspath(__file__))  # каталог коннектора: pull.out.txt, pull.json, load-pull.py
# Пояс с историей переходов: до 26.10.2014 Москва была на UTC+4.
MSK = ZoneInfo('Europe/Moscow')


def d(v):
    """/Date(ms)/ → 'ГГГГ-ММ-ДД' московского времени."""
    if not isinstance(v, str):
        return None
    m = re.match(r'^/Date\((-?\d+)\)/$', v)
    if not m:
        return None
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=MSK).strftime('%Y-%m-%d')


def num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def s(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def read_dump(path):
    """Файл q1c.ps1: строки '#### имя total=N' и JSON следом."""
    out = {}
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('{'):
                obj = json.loads(line)
                out[obj['query']] = obj['rows']
    return out



def org(r):
    """Организация записи — всегда последняя колонка выгрузки.

    По `r[-1]`, а не по индексу: запросы дополняются полями, и позиционный разбор
    иначе поедет молча, на всех наборах разом.
    """
    return s(r[-1]) if r else None


raw = read_dump(os.path.join(SP, 'pull.out.txt'))
print({k: len(v) for k, v in raw.items()})

data = {}

# turnovers: Период, СчетДт, СчетКт, СубДт1, СубДт2, СубКт1, СубКт2, Сумма, КолДт, КолКт
data['turnovers'] = []
for r in raw.get('turnovers', []):
    day = d(r[0])
    if not day:
        continue
    data['turnovers'].append({
        'year': int(day[:4]), 'month': int(day[5:7]),
        'dt': s(r[1]), 'kt': s(r[2]),
        'dt1': s(r[3]), 'dt2': s(r[4]), 'kt1': s(r[5]), 'kt2': s(r[6]),
        'amount': num(r[7]), 'qty_dt': num(r[8]) or None, 'qty_kt': num(r[9]) or None,
        'org': org(r),
    })

# balances: Счет, СчетИмя, Суб1..3, Дт, Кт, КолДт, КолКт
data['balances'] = [{
    'account': s(r[0]) or '', 'account_name': s(r[1]),
    'sub1': s(r[2]), 'sub2': s(r[3]), 'sub3': s(r[4]),
    'debit': num(r[5]), 'credit': num(r[6]),
    'qty_debit': num(r[7]) or None, 'qty_credit': num(r[8]) or None,
    'org': org(r),
} for r in raw.get('balances', [])]

# invoice_payments: Счет, Сумма, НДС, Период, Регистратор
data['payments'] = [{
    'invoice': s(r[0]) or '', 'amount': num(r[1]), 'vat': num(r[2]),
    'paid_at': d(r[3]), 'payment': s(r[4]), 'org': org(r),
} for r in raw.get('invoice_payments', [])]

# vat_invoices: Контрагент, ИНН, КПП, Номер, Дата, Сумма, НДС, Часть, СФ, КодОперации
PART = {'Выставленные счета-фактуры': 'issued', 'Полученные счета-фактуры': 'received'}
data['vat'] = []
for r in raw.get('vat_invoices', []):
    part = s(r[7]) or ''
    data['vat'].append({
        'kind': PART.get(part, 'issued' if 'ыстав' in part else 'received'),
        'counterparty': s(r[0]), 'inn': s(r[1]), 'kpp': s(r[2]),
        'number': s(r[3]), 'doc_date': d(r[4]),
        'amount': num(r[5]), 'vat': num(r[6]),
        'invoice_title': s(r[8]), 'operation_code': s(r[9]), 'rate': None, 'registrar': None,
        'org': org(r),
    })

# vat_claimed: СФ, Поставщик, Ставка, Без, НДС, Период, Регистратор
for r in raw.get('vat_claimed', []):
    data['vat'].append({
        'kind': 'claimed',
        'counterparty': s(r[1]), 'inn': None, 'kpp': None,
        'number': None, 'doc_date': d(r[5]),
        'amount': num(r[3]), 'vat': num(r[4]),
        'invoice_title': s(r[0]), 'operation_code': None,
        'rate': s(r[2]), 'registrar': s(r[6]), 'org': org(r),
    })

for k, v in data.items():
    print('%-12s %5d' % (k, len(v)))

with open(os.path.join(SP, 'pull.json'), 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False)
print('размер pull.json:', os.path.getsize(os.path.join(SP, 'pull.json')) // 1024, 'КБ')

# Контрольные суммы — их же проверим после загрузки в пространство.
print('оборот всего:', round(sum(t['amount'] for t in data['turnovers']), 2))
print('оплат счетов:', round(sum(p['amount'] for p in data['payments']), 2))
print('НДС issued:', round(sum(v['vat'] for v in data['vat'] if v['kind'] == 'issued'), 2))
print('НДС received:', round(sum(v['vat'] for v in data['vat'] if v['kind'] == 'received'), 2))
print('годы оборотов:', sorted({t['year'] for t in data['turnovers']}))
