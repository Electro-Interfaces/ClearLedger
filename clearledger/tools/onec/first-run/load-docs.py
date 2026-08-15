# -*- coding: utf-8 -*-
"""Загрузка полного среза бухгалтерии: документы всех видов и справочники.

Дополняет первую загрузку (регистр, реализации, поступления, банк). Данные читает из
/tmp/onec-docs.json.
"""
import asyncio
import json
import os

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company, GlReference
from resolve_org import org_id, org_map

SRC = '/tmp/onec-docs.json'

# Вид документа → как он называется в пространстве. Ключ идемпотентности собираем из
# вида, номера, даты и контрагента: номер в бухгалтерии не уникален даже внутри вида.
DOC_KINDS = {
    '01-invoices': ('invoice_out', 'Счёт покупателю'),
    '02-sf-out': ('vat_invoice_out', 'Счёт-фактура выданный'),
    '03-sf-in': ('vat_invoice_in', 'Счёт-фактура полученный'),
    '04-regops': ('closing_op', 'Регламентная операция'),
    '05-manual': ('manual_entry', 'Операция вручную'),
}

REF_KINDS = {
    '01-warehouses': 'warehouses',
    '02-subdivisions': 'subdivisions',
    '03-cost_items': 'cost_items',
    '04-cashflow_items': 'cashflow_items',
    '05-nomenclature_kinds': 'nomenclature_kinds',
    '06-persons': 'persons',
}


# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        # ── документы прочих видов ──
        added = 0
        for block, (kind, _label) in DOC_KINDS.items():
            rows = data.get(block, [])
            # Строки, добранные позже (счета покупателю), надо сохранить: иначе
            # пересоздание шапок уносит 1153 строки на 132,6 млн ₽.
            keep_lines = {
                (d.number, (d.date or '')[:10], d.counterparty_inn or ''): d.lines
                for d in (await s.execute(select(AccountingDoc).where(
                    AccountingDoc.company_id == cid,
                    AccountingDoc.doc_type == kind))).scalars() if d.lines
            }
            await s.execute(delete(AccountingDoc).where(
                AccountingDoc.company_id == cid, AccountingDoc.doc_type == kind))
            for r in rows:
                dt = (r.get('Дата') or '')[:19]
                num = (r.get('Номер') or '').strip()
                inn = (r.get('КонтрагентИНН') or '').strip()
                s.add(AccountingDoc(
                    company_id=cid,
                    external_id='1c:%s:%s:%s:%s' % (kind, num, dt, inn),
                    doc_type=kind, number=num or 'б/н', date=dt[:10],
                    counterparty_name=(r.get('Контрагент') or '')[:500],
                    counterparty_inn=inn[:20] or None,
                    organization_name=(r.get('Организация1С') or '')[:500] or None,
                    organization_id=org_id(orgs, r.get('Организация1С')),
                    amount=r.get('Сумма') or 0, vat_amount=None,
                    lines=keep_lines.get((num or 'б/н', dt[:10], inn), []),
                    match_status='pending', period_status='open',
                    # Время формирования и прочие реквизиты вида — сюда: по ним и
                    # задают первые вопросы к срезу.
                    doc_meta={k: v for k, v in r.items() if k not in
                              ('Номер', 'Дата', 'Контрагент', 'КонтрагентИНН', 'Сумма')
                              and v not in (None, '')} | {'time': dt[11:19]},
                ))
                added += 1
            print('%-18s %5d' % (kind, len(rows)))
        print('документов добавлено:', added)

        # ── справочники без своей таблицы ──
        # ⚠ Удаляем ТОЛЬКО свои виды: раньше здесь чистились все справочники компании,
        # и прогон после других загрузчиков уносил их данные (единицы измерения,
        # организацию, подписантов, статусы документов, сроки оплаты, расшифровки).
        await s.execute(delete(GlReference).where(
            GlReference.company_id == cid,
            GlReference.kind.in_(tuple(REF_KINDS.values()) + ('banks', 'bank_accounts'))))
        seen: set[tuple] = set()
        total = 0
        for block, kind in REF_KINDS.items():
            for r in data.get(block, []):
                name = (r.get('Наименование') or '').strip()
                if not name:
                    continue
                key = (kind, '', name)
                if key in seen:
                    continue
                seen.add(key)
                s.add(GlReference(company_id=cid, kind=kind, code='', name=name[:500],
                                  is_deleted=bool(r.get('Удален'))))
                total += 1
        # Банки и банковские счета — с реквизитами в meta.
        for r in data.get('02-banks', []):
            name = (r.get('Наименование') or '').strip()
            bik = (r.get('БИК') or '').strip()
            if not name or ('banks', bik, name) in seen:
                continue
            seen.add(('banks', bik, name))
            s.add(GlReference(company_id=cid, kind='banks', code=bik[:100], name=name[:500],
                              meta={'corr': r.get('КоррСчет'), 'city': r.get('Город')}))
            total += 1
        for r in data.get('03-bank-accounts', []):
            name = (r.get('Наименование') or '').strip()
            acc = (r.get('НомерСчета') or '').strip()
            if not name or ('bank_accounts', acc, name) in seen:
                continue
            seen.add(('bank_accounts', acc, name))
            s.add(GlReference(company_id=cid, kind='bank_accounts', code=acc[:100],
                              name=name[:500],
                              meta={'bank': r.get('Банк'), 'bik': r.get('БИК'),
                                    'owner': r.get('Владелец'), 'currency': r.get('Валюта')}))
            total += 1
        print('справочных записей:', total)

        await s.commit()
        print('загрузка полного среза завершена')


asyncio.run(main())
