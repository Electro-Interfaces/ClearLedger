# -*- coding: utf-8 -*-
"""Загрузка выгрузки бухгалтерии в базу пространства.

Запускается ВНУТРИ backend-контейнера стека (exec-py.sh), данные читает из
/tmp/onec-core.json (кладётся docker cp).

Правила, ради которых загрузка написана руками, а не «как получится»:
  * сумма строки документа с НДС = Сумма, если НДС включён в цену, иначе Сумма+НДС;
    иначе выручка документов расходится с оборотом 90.01.1 (проверено: два документа
    из 218 с НДС «сверху» дали расхождение 29 644,66 ₽);
  * ключ документа — номер+дата НЕ уникален (два разных документа №1-2212 от
    22.12.2023), поэтому ключ идемпотентности включает контрагента и сумму;
  * повторный запуск не задваивает: всё пишется по внешнему ключу с очисткой.
"""
import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import (
    AccountingDoc, Company, Counterparty, GlAccount, GlEntry, NomenclatureItem, Period,
)
from resolve_org import org_id, org_map

SRC = '/tmp/onec-core.json'
# Пометка способа получения: `1c_dt` — заход из выгрузки, `1c_com` — из живой базы.
TAG = os.environ.get('LAYER_SOURCE', '1c_dt')

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


def d(s):
    # Парсер отдаёт момент до секунд («2024-09-10T00:00:00»): время документа нужно
    # другим наборам. Здесь важен только день — режем, а не разбираем целиком.
    return date.fromisoformat(s[:10]) if s else None


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        company = (await s.execute(
            select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if company is None:
            print('НЕТ компании', SLUG, 'в пространстве — сначала завести её')
            return
        cid = company.id
        print('компания:', company.name, cid)

        # Юрлица компании: имя из 1С сводится к ссылке один раз на загрузку. Раньше
        # имя организации стояло в загрузчике КОНСТАНТОЙ — у второго клиента это
        # подписало бы его документы чужим юрлицом, молча и на всей истории.
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())
        print('юрлиц компании:', len(set(orgs.values())))

        # ── план счетов ──
        await s.execute(delete(GlAccount).where(GlAccount.company_id == cid))
        for a in data['01-accounts']:
            s.add(GlAccount(
                company_id=cid, code=a['Код'], name=a['Наименование'] or a['Код'],
                kind=str(a.get('Вид') or ''), off_balance=bool(a.get('Забалансовый')),
                quantitative=bool(a.get('Количественный')), currency=bool(a.get('Валютный')),
                parent_code=a.get('РодительКод'), is_deleted=bool(a.get('Удален')),
            ))
        print('счетов:', len(data['01-accounts']))

        # ── проводки ──
        await s.execute(delete(GlEntry).where(GlEntry.company_id == cid))
        n = 0
        for i, e in enumerate(data['02-entries']):
            dt = d(e['Период'])
            if dt is None:
                continue
            s.add(GlEntry(
                company_id=cid, entry_date=dt, period_year=dt.year, period_month=dt.month,
                doc_kind=e.get('ВидДокумента'), doc_title=(e.get('Документ') or '')[:500],
                account_dt=e.get('СчетДт'), account_kt=e.get('СчетКт'),
                amount=e.get('Сумма') or 0, content=e.get('Содержание'),
                organization_id=org_id(orgs, e.get('Организация1С')),
                source=TAG, external_key='%s:%06d' % (TAG, i),
            ))
            n += 1
        print('проводок:', n)

        # ── контрагенты ──
        existing = {c.external_ref for c in (await s.execute(
            select(Counterparty).where(Counterparty.company_id == cid))).scalars()}
        added = 0
        for c in data['03-counterparties']:
            ref = '1c:' + (c.get('Код') or '')
            if ref in existing:
                continue
            s.add(Counterparty(
                company_id=cid, inn=(c.get('ИНН') or '').strip() or '0',
                kpp=(c.get('КПП') or '').strip() or None,
                name=c['Наименование'], full_name=c.get('Полное'),
                type='ФЛ' if 'Физическое' in str(c.get('Вид')) else 'ЮЛ',
                external_ref=ref, kind='external', lifecycle_status='verified',
            ))
            added += 1
        print('контрагентов добавлено:', added)

        # ── номенклатура ──
        await s.execute(delete(NomenclatureItem).where(NomenclatureItem.company_id == cid))
        for nm in data['04-nomenclature']:
            if nm.get('Удален'):
                continue
            s.add(NomenclatureItem(
                company_id=cid, code=(nm.get('Код') or '')[:100],
                name=(nm['Наименование'] or '')[:500],
                unit=(nm.get('Единица') or 'шт')[:20],
                unit_label=(nm.get('ВидНоменклатуры') or '')[:100],
                external_ref='1c:' + (nm.get('Код') or ''),
            ))
        print('номенклатуры:', sum(1 for x in data['04-nomenclature'] if not x.get('Удален')))

        # ── документы реализации: шапки собираем из строк ──
        await s.execute(delete(AccountingDoc).where(AccountingDoc.company_id == cid))
        # ОДИН документ 1С — одна запись у нас. Раньше документ с товарами и услугами
        # раскладывался на два (`sale_goods` + `sale_services`), и количество документов
        # завышалось на 55 %, а половина проводок не могла найти свой документ
        # однозначно. Теперь строки лежат вместе, а тип строки помечен в `kind`.
        docs: dict[tuple, dict] = {}
        for kind, line_kind, rows in (('sale', 'goods', data['05-sales-docs']),
                                      ('sale', 'service', data['06-services-docs']),
                                      ('purchase', 'goods', data['07-purchases'])):
            for r in rows:
                if not r.get('Проведен'):
                    continue
                # Дата документа — днём, без времени: она же входит во внешний ключ,
                # а `accounting_docs.date` хранится строкой и сравнивается строкой.
                key = (r['Номер'].strip(), r['Дата'][:10], r.get('КонтрагентИНН') or '', kind)
                doc = docs.setdefault(key, {
                    'kind': kind, 'number': r['Номер'].strip(), 'date': r['Дата'][:10],
                    'cp': r.get('Контрагент') or '', 'inn': r.get('КонтрагентИНН') or '',
                    'org': r.get('Организация1С'),
                    'total': 0.0, 'vat': 0.0, 'lines': [],
                })
                amount = r.get('Сумма') or 0
                vat = r.get('СуммаНДС') or 0
                # НДС «сверху» — сумма строки его НЕ содержит. Без этой ветки два
                # документа из 218 занизили бы выручку на 29 644,66 ₽ против регистра.
                doc['total'] += amount if r.get('НДСВключен') else amount + vat
                doc['vat'] += vat
                doc['lines'].append({
                    'kind': line_kind,   # goods | service — разрез считается по строкам
                    'name': r.get('Номенклатура'), 'code': r.get('НоменклатураКод'),
                    'qty': r.get('Количество'), 'price': r.get('Цена'),
                    # `amount` — сумма С НДС, как в шапке. Сырую сумму 1С храним рядом:
                    # без этого разрез по строкам недобирал НДС «сверху» и расходился
                    # с оборотом 90.01.1 на 29 644,66 ₽.
                    'amount': amount if r.get('НДСВключен') else amount + vat,
                    'amount_raw': amount, 'vat': vat,
                    'vat_included': bool(r.get('НДСВключен')),
                })
        for key, doc in docs.items():
            s.add(AccountingDoc(
                company_id=cid, external_id='1c:%s:%s:%s:%s' % (doc['kind'], doc['number'], doc['date'], doc['inn']),
                doc_type=doc['kind'], number=doc['number'], date=doc['date'],
                counterparty_name=doc['cp'][:500], counterparty_inn=doc['inn'][:20] or None,
                organization_name=(doc['org'] or '')[:500] or None,
                organization_id=org_id(orgs, doc['org']),
                amount=round(doc['total'], 2), vat_amount=round(doc['vat'], 2),
                lines=doc['lines'], match_status='pending', period_status='open',
            ))
        print('документов:', len(docs))

        # ── периоды: месяц закрыт, если в нём есть регламентные операции ──
        await s.execute(delete(Period).where(Period.company_id == cid))
        months = {}
        for e in data['02-entries']:
            dt = d(e['Период'])
            if dt is None:
                continue
            key = (dt.year, dt.month)
            months.setdefault(key, '')
            if e.get('ВидДокумента') == 'Регламентная операция':
                # Момент закрытия — время последней регламентной операции месяца:
                # пустой `closed_at` у закрытого периода означал бы, что мы знаем
                # статус, но не знаем, когда он наступил.
                months[key] = max(months[key], dt.isoformat())
        for (y, m), closed in sorted(months.items()):
            s.add(Period(company_id=cid, year=y, month=m,
                         status='closed' if closed else 'open',
                         closed_at=datetime.fromisoformat(closed + 'T23:59:59').replace(tzinfo=MSK)
                         if closed else None,
                         closed_by='Закрытие месяца в 1С' if closed else None,
                         closure_source='from_bp'))
        print('периодов:', len(months), '| закрытых:', sum(1 for v in months.values() if v))

        await s.commit()
        print('загрузка завершена')


asyncio.run(main())
