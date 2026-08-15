# -*- coding: utf-8 -*-
"""Добор потерянного: полные справочники, недостающие документы и табличные части.

Закрывает находки проверки: банки 62→64, счета 325→332, номенклатура без признаков
и с коллизиями кодов, группы наравне с элементами, услуги поступлений (−158 899 ₽),
строки счетов покупателю (132 млн ₽), счета поставщиков, расшифровки платежей,
статусы и сроки оплаты, акты сверки, единицы измерения, пользователи и подписанты.
"""
import asyncio
import json

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import AccountingDoc, Company, Counterparty, GlReference, NomenclatureItem
from resolve_org import org_id, org_map

SRC = '/tmp/onec-refs.json'


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
        # Юрлицо документа — из самой выгрузки: константа в коде подписала бы документы
        # второй компании чужой организацией.
        orgs = org_map((await s.execute(text(
            "SELECT id::text, name, inn FROM organizations WHERE company_id = :c"),
            {"c": str(cid)})).all())

        seen_ref: set = set()

        def ref(kind, code, name, meta=None, is_deleted=False):
            key = (kind, (code or '')[:100], (name or '')[:500])
            if not name or key in seen_ref:
                return
            seen_ref.add(key)
            s.add(GlReference(company_id=cid, kind=kind, code=key[1], name=key[2],
                              is_deleted=is_deleted, meta=meta))


        # ── номенклатура: признаки, артикул, группа; ключ с кодом ГРУППЫ отдельно,
        #    иначе коды групп и элементов сталкиваются (9 коллизий было).
        await s.execute(delete(NomenclatureItem).where(NomenclatureItem.company_id == cid))
        n_items = n_groups = 0
        for r in d['02-nomenclature']:
            if r.get('Удален'):
                continue
            is_group = bool(r.get('ЭтоГруппа'))
            code = (r.get('Код') or '').strip()
            s.add(NomenclatureItem(
                company_id=cid, code=code[:100], name=(r.get('Наименование') or '')[:500],
                unit=(r.get('Единица') or 'шт')[:20],
                # unit_label несёт вид номенклатуры и признак услуги — по ним разрезы.
                unit_label=('услуга' if r.get('Услуга') else (r.get('ВидНоменклатуры') or ''))[:100],
                external_ref=('1c:grp:' if is_group else '1c:') + code,
            ))
            n_groups += is_group
            n_items += not is_group
        print('номенклатура: элементов %d, групп %d' % (n_items, n_groups))

        # ── контрагенты: догружаем пропущенных и помечаем группы
        have = {c.external_ref: c for c in (await s.execute(
            select(Counterparty).where(Counterparty.company_id == cid))).scalars()}
        added = 0
        for r in d['03-counterparties']:
            # НЕ `ref`: так называется функция вставки справочной записи выше.
            ext_ref = '1c:' + (r.get('Код') or '')
            cp = have.get(ext_ref)
            if cp is None:
                s.add(Counterparty(
                    company_id=cid, inn=(r.get('ИНН') or '').strip() or '0',
                    kpp=(r.get('КПП') or '').strip() or None,
                    name=(r.get('Наименование') or '')[:500], full_name=r.get('Полное'),
                    type='ФЛ' if 'Физическое' in str(r.get('Вид')) else 'ЮЛ',
                    external_ref=ext_ref, kind='external', lifecycle_status='verified'))
                added += 1
            elif r.get('ЭтоГруппа'):
                # Группа справочника — не контрагент: помечаем архивной, чтобы не
                # попадала в выборки как сторона сделки.
                cp.lifecycle_status = 'archived'
        print('контрагентов добавлено: %d' % added)

        # ── справочники: перезаливаем полностью, с кодами и без потерь
        for kind in ('banks', 'bank_accounts', 'units'):
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))
        seen = set()
        for r in d['04-banks']:
            key = ('banks', r.get('БИК') or '', r.get('Наименование') or '')
            if key in seen:
                continue
            seen.add(key)
            ref('banks', r.get('БИК'), r.get('Наименование'),
                {'corr': r.get('КоррСчет'), 'city': r.get('Город')}, bool(r.get('Удален')))
        for r in d['05-bank-accounts']:
            key = ('bank_accounts', r.get('НомерСчета') or '', r.get('Наименование') or '')
            if key in seen:
                continue
            seen.add(key)
            ref('bank_accounts', r.get('НомерСчета'), r.get('Наименование'),
                {'bank': r.get('Банк'), 'bik': r.get('БИК')}, bool(r.get('Удален')))
        for r in d['06-units']:
            key = ('units', r.get('Код') or '', r.get('Наименование') or '')
            if key in seen:
                continue
            seen.add(key)
            ref('units', r.get('Код'), r.get('Наименование'), {'full': r.get('Полное')})
        print('банки %d, счета %d, единицы %d' % (len(d['04-banks']), len(d['05-bank-accounts']),
                                                  len(d['06-units'])))

        # ── организация, пользователи, подписанты, статусы и сроки — справочными видами
        for kind in ('organizations', 'users', 'signers', 'doc_status', 'pay_terms'):
            await s.execute(delete(GlReference).where(
                GlReference.company_id == cid, GlReference.kind == kind))
        for r in d['01-org']:
            ref('organizations', r.get('ИНН'), r.get('Полное') or r.get('Наименование'),
                {k: v for k, v in r.items() if v not in (None, '')})
        for r in d['02-users']:
            ref('users', '', r.get('Наименование'))
        for r in d['05-signers']:
            ref('signers', '', r.get('ФИО'), {'organization': r.get('Организация')})
        # Статусы и сроки — по документу; ключ = представление документа.
        seen_st = set()
        for r in d['02-doc-status']:
            key = (r.get('Документ') or '')[:480]
            if not key or key in seen_st:
                continue
            seen_st.add(key)
            ref('doc_status', r.get('Статус'), key, {'doc_kind': r.get('ВидДокумента')})
        seen_pt = set()
        for r in d['03-pay-terms']:
            key = (r.get('Документ') or '')[:480]
            if not key or key in seen_pt:
                continue
            seen_pt.add(key)
            ref('pay_terms', r.get('СрокОплаты'), key)
        print('организация 1, пользователи %d, подписанты %d, статусы %d, сроки %d'
              % (len(d['02-users']), len(d['05-signers']), len(seen_st), len(seen_pt)))

        # ── документы: счета поставщику, акты сверки; строки счетов покупателю и
        #    услуги поступлений — как самостоятельные виды, чтобы суммы не смешивались.
        for kind in ('invoice_in', 'act_recon', 'purchase_services'):
            await s.execute(delete(AccountingDoc).where(
                AccountingDoc.company_id == cid, AccountingDoc.doc_type == kind))

        # Строки счетов покупателю — в lines уже существующих документов invoice_out.
        lines_by_doc: dict[tuple, list] = {}
        for r in d['01-invoice-lines']:
            key = ((r.get('Номер') or '').strip(), (r.get('Дата') or '')[:10],
                   (r.get('КонтрагентИНН') or '').strip())
            lines_by_doc.setdefault(key, []).append({
                'name': r.get('Номенклатура'), 'code': r.get('НоменклатураКод'),
                'qty': r.get('Количество'), 'price': r.get('Цена'),
                'amount': r.get('Сумма'), 'vat': r.get('СуммаНДС')})
        touched = 0
        for doc in (await s.execute(select(AccountingDoc).where(
                AccountingDoc.company_id == cid,
                AccountingDoc.doc_type == 'invoice_out'))).scalars():
            key = (doc.number, (doc.date or '')[:10], doc.counterparty_inn or '')
            rows = lines_by_doc.get(key)
            if rows:
                doc.lines = rows
                touched += 1
        print('счетов покупателю дополнено строками: %d (строк %d)'
              % (touched, len(d['01-invoice-lines'])))

        # Счета поставщику: шапки + строки.
        sup_lines: dict[tuple, list] = {}
        for r in d['03-supplier-lines']:
            key = ((r.get('Номер') or '').strip(), (r.get('Дата') or '')[:10],
                   (r.get('КонтрагентИНН') or '').strip())
            sup_lines.setdefault(key, []).append({
                'name': r.get('Номенклатура'), 'qty': r.get('Количество'),
                'price': r.get('Цена'), 'amount': r.get('Сумма'), 'vat': r.get('СуммаНДС')})
        for r in d['02-supplier-invoice']:
            num = (r.get('Номер') or '').strip()
            date = (r.get('Дата') or '')[:10]
            inn = (r.get('КонтрагентИНН') or '').strip()
            s.add(AccountingDoc(
                company_id=cid, external_id='1c:invoice_in:%s:%s:%s' % (num, date, inn),
                doc_type='invoice_in', number=num or 'б/н', date=date,
                counterparty_name=(r.get('Контрагент') or '')[:500],
                counterparty_inn=inn[:20] or None,
                organization_name=(r.get('Организация1С') or '')[:500] or None,
                organization_id=org_id(orgs, r.get('Организация1С')),
                amount=r.get('Сумма') or 0, lines=sup_lines.get((num, date, inn), []),
                match_status='pending', period_status='open',
                doc_meta={'proved': r.get('Проведен')}))
        print('счетов поставщику: %d (строк %d)' % (len(d['02-supplier-invoice']),
                                                    len(d['03-supplier-lines'])))

        # Услуги поступлений — вид `purchase_services`: раньше 158 899 ₽ не попадали никуда.
        srv: dict[tuple, dict] = {}
        for r in d['04-purchase-services']:
            if not r.get('Проведен'):
                continue
            num = (r.get('Номер') or '').strip()
            date = (r.get('Дата') or '')[:10]
            inn = (r.get('КонтрагентИНН') or '').strip()
            doc = srv.setdefault((num, date, inn), {
                'cp': r.get('Контрагент') or '', 'org': r.get('Организация1С'),
                'total': 0.0, 'vat': 0.0, 'lines': []})
            amount = r.get('Сумма') or 0
            vat = r.get('СуммаНДС') or 0
            doc['total'] += amount if r.get('НДСВключен') else amount + vat
            doc['vat'] += vat
            doc['lines'].append({'name': r.get('Номенклатура'), 'qty': r.get('Количество'),
                                 'price': r.get('Цена'), 'amount': amount, 'vat': vat})
        # Услуги поставщиков дописываются В СУЩЕСТВУЮЩИЙ документ поступления, если он
        # есть: один документ 1С — одна запись у нас. Отдельной записью остаются только
        # те, у кого товарной части нет вовсе.
        existing = {}
        for doc in (await s.execute(select(AccountingDoc).where(
                AccountingDoc.company_id == cid,
                AccountingDoc.doc_type == 'purchase'))).scalars():
            existing[(doc.number, (doc.date or '')[:10], doc.counterparty_inn or '')] = doc
        merged = 0
        for key in list(srv):
            doc0 = existing.get(key)
            if doc0 is None:
                continue
            data0 = srv.pop(key)
            lines = list(doc0.lines or [])
            for ln in data0['lines']:
                ln['kind'] = 'service'
                lines.append(ln)
            doc0.lines = lines
            doc0.amount = float(doc0.amount or 0) + data0['total']
            doc0.vat_amount = float(doc0.vat_amount or 0) + data0['vat']
            merged += 1
        print('услуг влито в поступления: %d' % merged)

        # Поступления, где есть ТОЛЬКО услуги, остаются документом `purchase` — вид
        # один на весь поступивший документ, а тип строки различает товар и услугу.
        for (num, date, inn), doc in srv.items():
            for ln in doc['lines']:
                ln['kind'] = 'service'
            s.add(AccountingDoc(
                company_id=cid, external_id='1c:purchase:%s:%s:%s' % (num, date, inn),
                doc_type='purchase', number=num or 'б/н', date=date,
                counterparty_name=doc['cp'][:500], counterparty_inn=inn[:20] or None,
                organization_name=(doc['org'] or '')[:500] or None,
                organization_id=org_id(orgs, doc['org']),
                amount=round(doc['total'], 2), vat_amount=round(doc['vat'], 2),
                lines=doc['lines'], match_status='pending', period_status='open'))
        print('услуг поставщиков: %d документов, %.2f ₽'
              % (len(srv), sum(x['total'] for x in srv.values())))

        for r in d['05-acts']:
            num = (r.get('Номер') or '').strip()
            date = (r.get('Дата') or '')[:10]
            inn = (r.get('КонтрагентИНН') or '').strip()
            s.add(AccountingDoc(
                company_id=cid, external_id='1c:act_recon:%s:%s:%s' % (num, date, inn),
                doc_type='act_recon', number=num or 'б/н', date=date,
                counterparty_name=(r.get('Контрагент') or '')[:500],
                counterparty_inn=inn[:20] or None,
                organization_name=(r.get('Организация1С') or '')[:500] or None,
                organization_id=org_id(orgs, r.get('Организация1С')),
                amount=0, lines=[], match_status='pending', period_status='open'))
        print('актов сверки: %d' % len(d['05-acts']))

        # ── расшифровки платежей: платёж ↔ договор ↔ статья ДДС
        await s.execute(delete(GlReference).where(
            GlReference.company_id == cid, GlReference.kind == 'payment_split'))
        for i, r in enumerate(d['01-pay-split']):
            ref('payment_split', r.get('Номер'),
                '%s %s %s — %s' % (r.get('Направление'), (r.get('Дата') or '')[:10],
                                   r.get('КонтрагентИНН') or '', r.get('Договор') or 'без договора'),
                {'direction': r.get('Направление'), 'date': (r.get('Дата') or '')[:10],
                 'inn': r.get('КонтрагентИНН'), 'contract': r.get('Договор'),
                 'cashflow_item': r.get('СтатьяДДС'), 'amount': r.get('Сумма')})
        print('расшифровок платежей: %d' % len(d['01-pay-split']))

        await s.commit()
        print('добор завершён')


asyncio.run(main())
