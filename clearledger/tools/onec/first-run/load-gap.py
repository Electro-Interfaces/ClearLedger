# -*- coding: utf-8 -*-
"""Добор того, чего не было в слое: УСН, кадры, НМА, уставный капитал, справочники.

Набор появился после переписи базы (`census.ps1`): она показала непустые объекты 1С,
которых не касался ни один прежний запрос. Для компании на ОСНО их нет вовсе, поэтому
первые волны их и не знали — а у компании на УСН в них лежит главная книга учёта.

Данные читает из /tmp/onec-gap.json (набор `queries-gap`).
"""
import asyncio
import json
import os
import re

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company, GlReference
from resolve_org import org_id, org_map

SRC = '/tmp/onec-gap.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')

# Набор запроса → (вид документа у нас, поле суммы).
DOCS = {
    '03-usn-notice': ('usn_notice', None),
    '04-nma-intake': ('nma_intake', 'СтоимостьБУ'),
    '05-capital': ('capital', 'УставныйКапитал'),
    '07-payroll-base': ('payroll_base', 'СуммаОблагаемойБазы'),
    '08-vacation': ('vacation', 'Начислено'),
    '09-hire': ('hire', None),
    '10-transfer': ('transfer', None),
    '11-sfr-stazh': ('sfr_stazh', None),
    '12-sfr-td': ('sfr_td', None),
}

# Набор запроса → вид справочника пространства.
REFS = {
    '01-kudir': 'kudir',
    '02-usn-expenses': 'usn_expenses',
    '13-subconto': 'subconto',
    '14-tax-types': 'tax_types',
    '15-ndfl-income': 'ndfl_income',
    '16-ndfl-deduction': 'ndfl_deduction',
}

SERVICE = ('Организация1С', 'Проведен', 'Удален')


def ref_name(kind, row, i):
    """Имя записи справочника. Уникальный индекс — (компания, вид, код, имя), поэтому
    у движений регистра имя собирается из периода и содержания: одного «Содержания»
    на 412 строк КУДиР не хватит."""
    if kind == 'kudir':
        return '%s · %s' % (str(row.get('Период') or '')[:10],
                            (row.get('Содержание') or row.get('Регистратор') or 'запись'))
    if kind == 'usn_expenses':
        return '%s · %s · %s' % (str(row.get('Период') or '')[:10],
                                 row.get('ВидРасхода') or 'расход',
                                 row.get('Регистратор') or '')
    return row.get('Наименование') or row.get('Полное') or row.get('Код') or 'запись %d' % i


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        # ── документы ──
        for block, (kind, amount_field) in DOCS.items():
            rows = data.get(block) or []
            await s.execute(delete(AccountingDoc).where(
                AccountingDoc.company_id == cid, AccountingDoc.doc_type == kind))
            for i, r in enumerate(rows):
                num = str(r.get('Номер') or '').strip() or 'б/н'
                date = str(r.get('Дата') or '')[:10]
                s.add(AccountingDoc(
                    company_id=cid,
                    # Номера у части этих документов нет вовсе (уставный капитал), поэтому
                    # в ключ идёт и порядковый номер строки — иначе две записи одного дня
                    # затрут друг друга.
                    external_id='1c:%s:%s:%s:%d' % (kind, num, date, i),
                    doc_type=kind, number=num, date=date,
                    counterparty_name=(r.get('Сотрудник') or r.get('Учредитель') or '')[:500] or None,
                    organization_name=(r.get('Организация1С') or '')[:500] or None,
                    organization_id=org_id(orgs, r.get('Организация1С')),
                    amount=r.get(amount_field) or 0 if amount_field else 0,
                    lines=[], match_status='pending', period_status='open',
                    status_1c='Проведён' if r.get('Проведен') else 'Не проведён',
                    doc_meta={k: v for k, v in r.items()
                              if v not in (None, '') and k not in SERVICE},
                ))
            if rows:
                print('%-16s %5d' % (kind, len(rows)))

        # Учредители — строками документа уставного капитала.
        founders = data.get('06-capital-founders') or []
        if founders:
            caps = (await s.execute(select(AccountingDoc).where(
                AccountingDoc.company_id == cid, AccountingDoc.doc_type == 'capital'))).scalars().all()
            for doc in caps:
                doc.lines = [{'kind': 'founder', 'name': f.get('Учредитель'),
                              'amount': f.get('СуммаВзноса') or 0}
                             for f in founders if str(f.get('Дата') or '')[:10] == (doc.date or '')[:10]]
            print('%-16s %5d' % ('учредители', len(founders)))

        # ── справочники и движения регистров ──
        for block, kind in REFS.items():
            rows = data.get(block) or []
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))
            seen = set()
            for i, r in enumerate(rows):
                name = str(ref_name(kind, r, i))[:500]
                code = str(r.get('Код') or r.get('КБК') or '')[:100]
                if (code, name) in seen:
                    n = 2
                    while (code, '%s (%d)' % (name[:490], n)) in seen:
                        n += 1
                    name = '%s (%d)' % (name[:490], n)
                seen.add((code, name))
                s.add(GlReference(
                    company_id=cid, kind=kind, code=code, name=name,
                    is_deleted=bool(r.get('Удален')),
                    meta={k: v for k, v in r.items() if v not in (None, '')}))
            if rows:
                print('%-16s %5d' % (kind, len(seen)))

        # ── реквизиты первичных документов в шапку ──
        # «Данные первичных документов» несут номер и дату бумажного оригинала: без них
        # в реестре виден только внутренний номер 1С, а сверяются с контрагентом по его.
        primary = data.get('17-primary-docs') or []
        by_key = {}
        for r in primary:
            # «Реализация (акт, накладная, УПД) 0000-000123 от 01.02.2026 12:00:00».
            # Дата в представлении русская, а в слое ISO — без разворота ключ не сходится
            # ни разу, и обогащение молча даёт ноль.
            m = re.search(r'(\S+)\s+от\s+(\d{2})\.(\d{2})\.(\d{4})', r.get('Документ') or '')
            if not m:
                continue
            by_key[(m.group(1), '%s-%s-%s' % (m.group(4), m.group(3), m.group(2)))] = r
        touched = ambiguous = 0
        if by_key:
            docs = (await s.execute(select(AccountingDoc).where(
                AccountingDoc.company_id == cid))).scalars().all()
            # Номер с датой не уникальны: счёт, реализация и счёт-фактура одной сделки
            # часто совпадают. Реквизиты первички относятся к ОДНОМУ документу, поэтому
            # там, где ключ ведёт к нескольким, лучше не проставить ничего.
            counts = {}
            for d in docs:
                counts[((d.number or '').strip(), (d.date or '')[:10])] = \
                    counts.get(((d.number or '').strip(), (d.date or '')[:10]), 0) + 1
            for d in docs:
                key = ((d.number or '').strip(), (d.date or '')[:10])
                r = by_key.get(key)
                if not r:
                    continue
                if counts.get(key, 0) > 1:
                    ambiguous += 1
                    continue
                meta = dict(d.doc_meta or {})
                meta['Номер первичного'] = r.get('НомерПервичного')
                meta['Дата первичного'] = str(r.get('ДатаПервичного') or '')[:10]
                d.doc_meta = meta
                touched += 1
        print('%-16s %5d из %d · неоднозначных %d' % ('первичка', touched, len(primary), ambiguous))

        await s.commit()
        print('добор завершён')


asyncio.run(main())
