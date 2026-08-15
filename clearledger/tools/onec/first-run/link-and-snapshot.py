# -*- coding: utf-8 -*-
"""Достроить слои: связать проводки с документами, записать приём L1 и снимки L4.

1. `gl_entries.doc_id` — из строки `doc_title` («Реализация (акт, накладная, УПД)
   1-2610 от 26.10.2021 12:00:00») достаём номер и дату и находим документ. Это корень
   измерений «контрагент», «организация», «номенклатура» и разворота оборотки до первички.
2. `SourceFile` — запись о приёме выгрузки: без неё L1 не существует, и нельзя ответить
   «откуда цифра» и «когда это приехало».
3. `ReferenceSnapshot` на каждый закрытый месяц — состав и контрольная сумма. Счётчик
   закрытых месяцев ничего не доказывает; снимок позволяет увидеть, что месяц переписан.
"""
import asyncio
import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from app.database import async_session_factory
from app.models import (
    AccountingDoc, Company, GlEntry, GlReference, Period, ReferenceSnapshot, SourceFile)

# «… 1-2610 от 26.10.2021 12:00:00» → номер и дата
DOC_RE = re.compile(r'(\S+)\s+от\s+(\d{2})\.(\d{2})\.(\d{4})')


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()

        # ── 1. связь проводки с документом ──
        docs = (await s.execute(
            select(AccountingDoc.id, AccountingDoc.number, AccountingDoc.date,
                   AccountingDoc.doc_type, AccountingDoc.details, AccountingDoc.doc_meta)
            .where(AccountingDoc.company_id == cid))).all()
        by_key: dict[tuple, list] = {}
        for did, num, date, dtype, details, meta in docs:
            # Время документа: им разводятся настоящие двойники — два разных документа
            # с одним номером и датой (№1-2212 от 22.12.2023).
            tm = ((details or {}).get('Время документа')
                  or (meta or {}).get('Время документа')
                  or (meta or {}).get('time'))
            by_key.setdefault(((num or '').strip(), (date or '')[:10]), []).append(
                (did, dtype, tm))

        # Вид регистратора 1С → вид документа у нас. Нужен, когда номер+дата ведут к
        # нескольким записям: один документ 1С с товарами и услугами лежит у нас двумя
        # (`sale_goods` + `sale_services`), и без этой карты половина проводок оставалась
        # без ссылки как «неоднозначные».
        KIND_MAP = {
            'Реализация (акт, накладная, УПД)': 'sale',
            'Поступление (акт, накладная, УПД)': 'purchase',
            'Счет-фактура выданный': 'vat_invoice_out',
            'Счет-фактура полученный': 'vat_invoice_in',
            'Списание с расчетного счета': 'bank_out',
            'Поступление на расчетный счет': 'bank_in',
            'Операция': 'manual_entry',
            'Регламентная операция': 'closing_op',
            # Виды наборов уровнем выше (зарплата, волна 3). Их документы могут быть
            # ещё не загружены — тогда проводка остаётся без ссылки, и это правильный
            # исход: связь по номеру и дате уводила зарплату на чужой счёт-фактуру.
            'Начисление зарплаты': 'payroll_accrual',
            'Ведомость на выплату зарплаты через кассу': 'payroll_payment',
            'Ведомость на выплату зарплаты через банк': 'payroll_payment',
            'Ведомость на выплату зарплаты через раздатчика': 'payroll_payment',
            'Авансовый отчет': 'advance_report',
            'Поступление наличных': 'cash_in',
            'Выдача наличных': 'cash_out',
            'Корректировка долга': 'debt_correction',
            'Корректировка поступления': 'purchase_correction',
            # «Расход материалов» — как в этой конфигурации зовётся требование-накладная.
            # Карта ОБЯЗАНА совпадать с `books_links._KIND_TO_TYPE`: там был
            # `demand_note`, здесь `goods_writeoff` — связь ставилась и тут же
            # снималась сведением, 74 проводки оставались без документа.
            'Расход материалов': 'demand_note',
            'Требование-накладная': 'demand_note',
            'Платежное поручение': 'payment_order',
            'Формирование записей книги покупок': 'vat_book_in',
            'Формирование записей книги продаж': 'vat_book_out',
            # Виды набора добора: у компании на ОСНО их нет, у УСН и там, где ведут
            # кадры, — есть.
            'Отпуск': 'vacation',
            'Принятие к учету НМА': 'nma_intake',
            'Регистрация облагаемой базы руководителя': 'payroll_base',
            'Формирование уставного капитала': 'capital',
            'Прием на работу': 'hire',
            'Кадровый перевод': 'transfer',
            # Агентская схема и прочее, что нашлось переписью базы компании-агента.
            'Отчет комиссионера (агента)': 'commission_report',
            'Отчет комитенту': 'committent_report',
            'Оприходование товаров': 'goods_intake',
            'Списание НДС': 'vat_writeoff',
            'Распределение НДС': 'vat_distribution',
            'Операция по единому налоговому счету': 'ens_operation',
            'Оказание услуг': 'services',
            'Увольнение': 'dismissal',
            'Ведомость на выплату зарплаты': 'payroll_sheet',
            'СЗВ-М': 'szv_m',
            'Списание товаров, материалов': 'goods_writeoff',
        }

        linked = ambiguous = missed = 0
        entries = (await s.execute(
            select(GlEntry).where(GlEntry.company_id == cid))).scalars().all()
        # Связи сбрасываем перед проходом: шаг обязан быть идемпотентным. Без этого
        # ссылки, проставленные прошлым — возможно, ошибочным — прогоном, остаются
        # висеть, и исправление правил ничего не чинит.
        for e in entries:
            e.doc_id = None
        for e in entries:
            m = DOC_RE.search(e.doc_title or '')
            if not m:
                missed += 1
                continue
            num, dd, mm, yy = m.group(1), m.group(2), m.group(3), m.group(4)
            date_iso = '%s-%s-%s' % (yy, mm, dd)
            found = by_key.get((num.strip(), date_iso))
            if not found:
                # У документов с выключенной нумерацией представление выглядит как
                # «Формирование уставного капитала от 10.09.2024», и регулярка берёт
                # за номер последнее слово вида. Такой документ ищем по «б/н» и дате —
                # вид всё равно сверяется ниже.
                found = by_key.get(('б/н', date_iso))
            if not found:
                missed += 1
                continue
            # Вид регистратора обязателен: номера в 1С сквозные по префиксу базы, и
            # «Начисление зарплаты ПИБП-000008» находило чужой документ с тем же номером
            # и датой. Неизвестный вид НЕ связываем вовсе — пустая ссылка честнее ложной:
            # на карточке счёта-фактуры висели 29 зарплатных проводок РТИ.
            want = KIND_MAP.get((e.doc_kind or '').strip())
            if want is None:
                missed += 1
                continue
            found = [(d, t, tm) for d, t, tm in found if t == want]
            if not found:
                missed += 1
                continue
            if len(found) > 1:
                # Двойников разводим ВРЕМЕНЕМ: оно есть и в представлении проводки
                # («…от 22.12.2023 12:00:01»), и в реквизитах документа. Без этого
                # семь проводок реализации оставались без первички.
                mt = re.search(r'(\d{2}:\d{2}:\d{2})', e.doc_title or '')
                same = [d for d, _, tm in found if mt and tm and tm == mt.group(1)]
                if len(same) != 1:
                    # Наугад не связываем: карточка документа показала бы чужие деньги.
                    ambiguous += 1
                    continue
                e.doc_id = same[0]
            else:
                e.doc_id = found[0][0]
            linked += 1
        print('проводок связано: %d, неоднозначных: %d, без документа: %d'
              % (linked, ambiguous, missed))

        # ── 2. приём L1 ──
        # Отпечаток снимается с ТОГО ЖЕ файла выгрузки, который сейчас грузили. Раньше
        # имя, размер и sha256 стояли константой от первой компании — и приём второй
        # оказывался подписан чужим файлом: на вопрос «откуда цифра» L1 отвечал неправдой.
        # Файла может не быть: /tmp контейнера живёт до ближайшего выката. Тогда шаг
        # не переписывает L1 и не разваливает остальное — прежняя запись честнее пустой.
        src = '/tmp/onec-core.json'
        if os.path.exists(src):
            blob = open(src, 'rb').read()
            await s.execute(delete(SourceFile).where(SourceFile.company_id == cid))
            s.add(SourceFile(
                company_id=cid,
                file_name=os.environ.get('SOURCE_NAME') or os.path.basename(src),
                mime_type='application/json', size=len(blob),
                storage_path=os.environ.get('SOURCE_PATH') or ('local:' + src),
                fingerprint='sha256:' + hashlib.sha256(blob).hexdigest(),
            ))
            print('приём L1 записан: отпечаток выгрузки', len(blob) // 1024, 'КБ')
        else:
            print('приём L1 пропущен: нет', src, '— прежняя запись оставлена как есть')

        # ── 2а. основание закрытия: дата запрета изменения данных ──
        locks = [
            r.code for r in (await s.execute(select(GlReference).where(
                GlReference.company_id == cid,
                GlReference.kind == 'period_locks'))).scalars()]
        ban = max(locks) if locks else None
        if ban:
            for p in (await s.execute(select(Period).where(
                    Period.company_id == cid, Period.status == 'closed'))).scalars():
                if '%04d-%02d' % (p.year, p.month) <= ban[:7]:
                    p.closed_by = 'Запрет изменения данных до %s' % ban
            print('под датой запрета %s' % ban)

        # ── 3. снимки закрытых периодов (L4) ──
        await s.execute(delete(ReferenceSnapshot).where(ReferenceSnapshot.company_id == cid))
        closed = (await s.execute(
            select(Period).where(Period.company_id == cid, Period.status == 'closed'))).scalars().all()
        made = 0
        for p in closed:
            rows = (await s.execute(
                select(func.count(), func.coalesce(func.sum(GlEntry.amount), 0))
                .where(GlEntry.company_id == cid, GlEntry.period_year == p.year,
                       GlEntry.period_month == p.month))).one()
            n, amount = rows
            doc_refs = [r for (r,) in (await s.execute(
                select(AccountingDoc.external_id)
                .where(AccountingDoc.company_id == cid,
                       AccountingDoc.date.like('%04d-%02d%%' % (p.year, p.month))))).all()]
            checksum = hashlib.sha256(
                ('%d-%02d|%d|%s|%d' % (p.year, p.month, n, amount, len(doc_refs))).encode()).hexdigest()
            s.add(ReferenceSnapshot(
                company_id=cid, period_id=p.id,
                summary={'entries': n, 'amount': float(amount), 'documents': len(doc_refs),
                         'checksum': 'sha256:' + checksum},
                document_refs=doc_refs[:2000],
            ))
            made += 1
        print('снимков эталона: %d' % made)

        await s.commit()
        print('готово')


asyncio.run(main())
