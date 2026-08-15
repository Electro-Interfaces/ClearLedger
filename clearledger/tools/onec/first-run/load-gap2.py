# -*- coding: utf-8 -*-
"""Добор второй волны: агентская схема, НДС, кадры.

Нашлось переписью базы НПК: у компании-агента 2876 проводок отчётов комиссионера
не находили документа-основания, потому что таких документов не забирал ни один
набор — у первых двух компаний их нет вовсе.

Данные читает из /tmp/onec-gap2.json (набор `queries-gap2`).
"""
import asyncio
import json
import os

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company, GlReference
from resolve_org import org_id, org_map

SRC = '/tmp/onec-gap2.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, npk)')

# Набор → (вид документа у нас, поле суммы, поле контрагента).
DOCS = {
    '01-commission-report': ('commission_report', 'Сумма', 'Контрагент'),
    '03-committent-report': ('committent_report', 'Сумма', 'Контрагент'),
    '07-vat-writeoff': ('vat_writeoff', None, None),
    '08-vat-distribution': ('vat_distribution', 'ВыручкаБезНДС', None),
    '09-goods-intake': ('goods_intake', 'Сумма', None),
    '10-ens-operation': ('ens_operation', 'Сумма', None),
    '11-services': ('services', 'Сумма', None),
    '12-dismissal': ('dismissal', 'Начислено', 'Сотрудник'),
    '13-payroll-sheet-old': ('payroll_sheet', 'Сумма', None),
    '14-szv-m': ('szv_m', None, None),
}

# Движения регистров — справочными наборами, как книги НДС у первой компании.
REFS = {
    '04-committent-goods': 'committent_goods',
    '05-vat-incoming': 'vat_incoming',
    '06-vat-charged': 'vat_charged',
}

SERVICE = ('Организация1С', 'Проведен', 'Удален')


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        # Строки отчёта комиссионера — в состав своего документа.
        lines_by_key = {}
        for r in data.get('02-commission-lines') or []:
            key = ((r.get('Номер') or '').strip(), str(r.get('Дата') or '')[:10])
            lines_by_key.setdefault(key, []).append({
                'kind': 'goods', 'name': r.get('Номенклатура'),
                'qty': r.get('Количество'), 'price': r.get('Цена'),
                'amount': r.get('Сумма') or 0, 'vat': r.get('СуммаНДС') or 0,
                'commission': r.get('Вознаграждение') or 0,
            })

        for block, (kind, amount_field, party_field) in DOCS.items():
            rows = data.get(block) or []
            await s.execute(delete(AccountingDoc).where(
                AccountingDoc.company_id == cid, AccountingDoc.doc_type == kind))
            for i, r in enumerate(rows):
                num = str(r.get('Номер') or '').strip() or 'б/н'
                date = str(r.get('Дата') or '')[:10]
                inn = str(r.get('КонтрагентИНН') or '').strip()
                s.add(AccountingDoc(
                    company_id=cid,
                    external_id='1c:%s:%s:%s:%d' % (kind, num, date, i),
                    doc_type=kind, number=num, date=date,
                    counterparty_name=(r.get(party_field) or '')[:500] if party_field else None,
                    counterparty_inn=inn[:20] or None,
                    organization_name=(r.get('Организация1С') or '')[:500] or None,
                    organization_id=org_id(orgs, r.get('Организация1С')),
                    amount=(r.get(amount_field) or 0) if amount_field else 0,
                    lines=lines_by_key.get((num, date), []) if kind == 'commission_report' else [],
                    match_status='pending', period_status='open',
                    status_1c='Проведён' if r.get('Проведен') else 'Не проведён',
                    doc_meta={k: v for k, v in r.items()
                              if v not in (None, '') and k not in SERVICE},
                ))
            if rows:
                print('%-20s %6d' % (kind, len(rows)))

        for block, kind in REFS.items():
            rows = data.get(block) or []
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))
            seen = set()
            for i, r in enumerate(rows):
                # Имя движения регистра собирается из периода и регистратора: своего
                # наименования у него нет, а уникальный индекс требует различимости.
                name = ('%s · %s · %s' % (str(r.get('Период') or '')[:10],
                                          r.get('Регистратор') or '',
                                          r.get('Номенклатура') or r.get('СчетФактура')
                                          or r.get('Покупатель') or ''))[:500]
                code = ''
                if (code, name) in seen:
                    n = 2
                    while (code, '%s (%d)' % (name[:490], n)) in seen:
                        n += 1
                    name = '%s (%d)' % (name[:490], n)
                seen.add((code, name))
                s.add(GlReference(
                    company_id=cid, kind=kind, code=code, name=name,
                    is_deleted=False,
                    meta={k: v for k, v in r.items() if v not in (None, '')}))
            if rows:
                print('%-20s %6d' % (kind, len(seen)))

        await s.commit()
        print('добор второй волны завершён')


asyncio.run(main())
