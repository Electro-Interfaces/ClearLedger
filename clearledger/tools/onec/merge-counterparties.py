# -*- coding: utf-8 -*-
"""Слияние карточек одного юрлица по ИНН.

Дубли ищутся среди ВСЕХ карточек, включая помеченные архивом прошлым прогоном: пока
условие было `NOT is_group`, повторная загрузка заводила карточку с тем же ИНН заново,
архивная (а на ней все документы) из поиска выпадала, и у ВТБ 71 документ остался на
«[слит с основной карточкой]», тогда как «основной» числилась пустая новая. Папки
справочника (`inn = '0'`) дублями не считаются: их в 1С много по природе.

Ревизия показала закономерность: у всех семи пар документы лежат на одной карточке,
а договоры, счета-фактуры и сальдо — на другой. Открыв «Мейсак Павел Юрьевич», человек
видит долг 524 079 ₽ и ноль документов; открыв «ИП Мейсак» — 61 документ и −5 050 ₽.
Ни одна карточка не отвечает на вопрос «что с этим контрагентом».

Главной становится карточка с наибольшим числом связей. Дубль не удаляется: он
помечается группой-архивом и получает ссылку на главную в `aliases` — данные клиента
не выбрасываем, но из работы убираем.
"""
import asyncio
from collections import defaultdict

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company, Counterparty

# Куда ведут ссылки на карточку (по внешним ключам схемы).
REFS = [
    ('accounting_docs', 'counterparty_id'), ('gl_balances', 'counterparty_id'),
    ('vat_entries', 'counterparty_id'), ('corporate_clients', 'counterparty_id'),
    ('counterparty_emails', 'counterparty_id'), ('intake_items', 'counterparty_id'),
    ('mail_messages', 'counterparty_id'), ('mail_threads', 'counterparty_id'),
    ('mail_rules', 'set_counterparty_id'), ('store_receipts', 'supplier_id'),
]


import os

# Какой компании грузим. Дефолта нет намеренно: забытая переменная подписала бы
# данные одной компании другой — молча и без следа в цифрах.
SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()

        rows = (await s.execute(text("""
            SELECT inn, array_agg(id::text) FROM core.counterparties
             WHERE company_id = :cid AND coalesce(inn,'') NOT IN ('', '0')
             GROUP BY inn HAVING count(*) > 1"""), {'cid': str(cid)})).all()
        print('групп дублей по ИНН:', len(rows))

        moved_total = 0
        for inn, ids in rows:
            # Вес карточки — сколько на неё ссылаются документы, договоры и НДС.
            weight = {}
            for cp_id in ids:
                docs = (await s.execute(text(
                    "SELECT count(*) FROM core.accounting_docs WHERE counterparty_id = :i"),
                    {'i': cp_id})).scalar_one()
                cons = (await s.execute(text(
                    "SELECT count(*) FROM core.contracts WHERE counterparty_id::text = :i"),
                    {'i': cp_id})).scalar_one()
                vat = (await s.execute(text(
                    "SELECT count(*) FROM core.vat_entries WHERE counterparty_id = :i"),
                    {'i': cp_id})).scalar_one()
                weight[cp_id] = (docs * 10 + cons * 3 + vat, docs, cons, vat)
            main_id = max(weight, key=lambda k: weight[k][0])
            names = {r[0]: r[1] for r in (await s.execute(text(
                "SELECT id::text, name FROM core.counterparties WHERE id::text = ANY(:ids)"),
                {'ids': ids})).all()}
            print('\nИНН %s → главная «%s» (док %d, дог %d, НДС %d)'
                  % (inn, names[main_id], weight[main_id][1], weight[main_id][2], weight[main_id][3]))

            # Главной могла оказаться карточка, помеченная архивом прошлым прогоном:
            # связи-то на ней. Возвращаем её в работу и снимаем пометку.
            await s.execute(text("""
                UPDATE core.counterparties
                   SET is_group = false,
                       name = replace(name, ' [слит с основной карточкой]', '')
                 WHERE id = :main"""), {'main': main_id})

            for cp_id in ids:
                if cp_id == main_id:
                    continue
                moved = 0
                for table, col in REFS:
                    res = await s.execute(text(
                        f"UPDATE core.{table} SET {col} = :main WHERE {col} = :dup"),
                        {'main': main_id, 'dup': cp_id})
                    moved += res.rowcount or 0
                # Договоры хранят ссылку строкой — свой UPDATE.
                res = await s.execute(text(
                    "UPDATE core.contracts SET counterparty_id = :main "
                    "WHERE counterparty_id::text = :dup"), {'main': main_id, 'dup': cp_id})
                moved += res.rowcount or 0

                # Реквизиты: переносим то, чего у главной нет.
                await s.execute(text("""
                    UPDATE core.counterparties m SET
                      kpp = coalesce(m.kpp, d.kpp), okpo = coalesce(m.okpo, d.okpo),
                      full_name = coalesce(m.full_name, d.full_name),
                      legal_address = coalesce(m.legal_address, d.legal_address),
                      actual_address = coalesce(m.actual_address, d.actual_address),
                      phone = coalesce(m.phone, d.phone), email = coalesce(m.email, d.email),
                      raw = coalesce(m.raw, d.raw),
                      aliases = (SELECT array_agg(DISTINCT x) FROM unnest(
                                   m.aliases || ARRAY[d.name]) AS x)
                      FROM core.counterparties d
                     WHERE m.id = :main AND d.id = :dup"""),
                    {'main': main_id, 'dup': cp_id})

                # Дубль не удаляем: помечаем архивом с указанием, куда он слит.
                await s.execute(text("""
                    UPDATE core.counterparties SET is_group = true,
                           name = name || ' [слит с основной карточкой]'
                     WHERE id = :dup AND name NOT LIKE '%[слит%'"""), {'dup': cp_id})
                moved_total += moved
                print('   «%s» → перенесено связей: %d' % (names[cp_id], moved))

        await s.commit()
        print('\nвсего перенесено связей:', moved_total)

        left = (await s.execute(text("""
            SELECT count(*) FROM (SELECT inn FROM core.counterparties
             WHERE company_id = :cid AND coalesce(inn,'') NOT IN ('', '0') AND NOT is_group
             GROUP BY inn HAVING count(*) > 1) t"""), {'cid': str(cid)})).scalar_one()
        print('дублей по ИНН осталось:', left)


asyncio.run(main())
