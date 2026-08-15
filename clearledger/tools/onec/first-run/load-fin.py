# -*- coding: utf-8 -*-
"""Финальный добор: учётная политика с параметрами, книги НДС, остатки по счетам,
контактные лица, счета учёта номенклатуры.

Всё это — свойства учёта и справочные срезы, а не сущности пространства, поэтому
ложатся в `gl_references` своими видами. Книги НДС — регистр налогового учёта, их
держим строками с суммой в `meta`: отдельная таблица оправдана, когда по ним начнут
строить декларацию, а не показывать состав среза.
"""
import asyncio
import json

from sqlalchemy import delete, select

from app.database import async_session_factory
from app.models import Company, GlReference

SRC = '/tmp/onec-fin.json'


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    d = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()

        seen: set = set()

        def ref(kind, code, name, meta=None):
            key = (kind, (code or '')[:100], (name or '')[:500])
            if not name or key in seen:
                return False
            seen.add(key)
            s.add(GlReference(company_id=cid, kind=kind, code=key[1], name=key[2], meta=meta))
            return True

        for kind in ('accounting_policy', 'vat_sales', 'vat_purchases',
                     'contact_persons', 'nom_accounts', 'balances'):
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))

        # ── учётная политика: теперь с параметрами, а не одним фактом
        for r in d['01-policy']:
            since = (r.get('Период') or '')[:10]
            params = {k: v for k, v in r.items() if k not in ('Период', 'Организация')
                      and v not in (None, '')}
            ref('accounting_policy', since, 'Учётная политика с %s' % since,
                {'since': since, 'organization': r.get('Организация'), **params})
        print('политика: параметров %d' % len(
            [k for k, v in d['01-policy'][0].items() if v not in (None, '')]))

        # ── книги НДС: строка = запись книги
        n_s = n_p = 0
        for i, r in enumerate(d['02-vat-sales']):
            date = (r.get('Период') or '')[:10]
            n_s += ref('vat_sales', date,
                       '%s · %s · %s · #%d' % (date, r.get('Покупатель') or '—',
                                               r.get('Ставка') or '', i),
                       {'date': date, 'party': r.get('Покупатель'), 'rate': r.get('Ставка'),
                        'net': r.get('СуммаБезНДС'), 'vat': r.get('НДС'),
                        'event': r.get('Событие'), 'n': i})
        for i, r in enumerate(d['03-vat-purchases']):
            date = (r.get('Период') or '')[:10]
            n_p += ref('vat_purchases', date,
                       '%s · %s · %s · #%d' % (date, r.get('Поставщик') or '—',
                                               r.get('Ставка') or '', i),
                       {'date': date, 'party': r.get('Поставщик'), 'rate': r.get('Ставка'),
                        'net': r.get('СуммаБезНДС'), 'vat': r.get('НДС'),
                        'event': r.get('Событие'), 'n': i})
        print('книга продаж %d, книга покупок %d' % (n_s, n_p))

        # ── остатки по счетам на конец периода данных
        for r in d['06-balances']:
            code = (r.get('Счет') or '').strip()
            dt = r.get('ОстатокДт') or 0
            kt = r.get('ОстатокКт') or 0
            ref('balances', code, '%s — %s' % (code, r.get('Наименование') or ''),
                {'debit': dt, 'credit': kt})
        print('остатков по счетам: %d' % len(d['06-balances']))

        # ── контактные лица контрагентов и счета учёта номенклатуры
        for r in d['04-contact-persons']:
            ref('contact_persons', '', r.get('Наименование'),
                {'position': r.get('Должность'), 'owner': r.get('Владелец'),
                 'role': r.get('Роль')})
        for r in d['05-nom-accounts']:
            ref('nom_accounts', (r.get('СчетУчета') or '')[:100],
                '%s → %s' % (r.get('ВидНоменклатуры') or '—', r.get('СчетУчета') or ''),
                {'kind': r.get('ВидНоменклатуры'), 'account': r.get('СчетУчета'),
                 'income': r.get('СчетДоходов'), 'expense': r.get('СчетРасходов'),
                 'vat_mode': r.get('СпособУчетаНДС')})
        print('контактных лиц %d, счетов учёта %d'
              % (len(d['04-contact-persons']), len(d['05-nom-accounts'])))

        await s.commit()
        print('финальный добор завершён')


asyncio.run(main())
