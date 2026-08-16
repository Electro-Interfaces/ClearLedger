# -*- coding: utf-8 -*-
"""Примет ли слой предпринимателя: заводим ИП в песочнице, читаем, убираем.

Запуск: exec-py.sh <стек> server/scripts/probe_ip_layer.py

Настоящей базы ИП у нас нет, а отвечать «подойдёт» без проверки нельзя. Поэтому
создаётся временная компания с юрлицом-ИП и проводками, характерными именно для
предпринимателя: НДФЛ с доходов (68.10), налог при УСН (68.12), патент (68.45),
взносы «за себя» (69.06.5), выручка и оплата. Затем читаются те же функции, что
работают на экранах, и всё удаляется.
"""
import asyncio
import uuid

from sqlalchemy import text

from app.database import async_session_factory
from app.services.tax_mode import tax_mode

SLUG = 'ip-probe-tmp'


async def cleanup(s, cid):
    for t in ('gl_entries', 'gl_accounts', 'organizations', 'periods',
              'accounting_docs', 'counterparties', 'company_roles', 'user_companies'):
        try:
            await s.execute(text("DELETE FROM %s WHERE company_id = CAST(:c AS uuid)" % t),
                            {"c": str(cid)})
        except Exception:
            await s.rollback()
    await s.execute(text("DELETE FROM companies WHERE id = CAST(:c AS uuid)"), {"c": str(cid)})
    await s.commit()


async def main():
    async with async_session_factory() as s:
        old = (await s.execute(text("SELECT id FROM companies WHERE slug = :s"),
                               {"s": SLUG})).scalar_one_or_none()
        if old:
            await cleanup(s, old)

        cid = uuid.uuid4()
        # profile_id обязателен: берём тот же профиль, что у офисных компаний.
        prof = (await s.execute(text(
            "SELECT profile_id FROM companies WHERE slug = 'rti'"))).scalar_one()
        await s.execute(text("""
            INSERT INTO companies (id, slug, name, inn, profile_id, created_at)
            VALUES (CAST(:id AS uuid), :s, :n, :inn, :p, now())"""),
            {"id": str(cid), "s": SLUG, "n": 'Проверка ИП (временная)',
             "inn": '780000000012', "p": prof})

        oid = uuid.uuid4()
        await s.execute(text("""
            INSERT INTO organizations (id, company_id, name, full_name, inn, kpp, vid, created_at)
            VALUES (CAST(:id AS uuid), CAST(:c AS uuid), :n, :fn, :inn, NULL, :vid, now())"""),
            {"id": str(oid), "c": str(cid), "n": 'ИП Иванов Иван Иванович',
             "fn": 'Индивидуальный предприниматель Иванов Иван Иванович',
             "inn": '780000000012', "vid": 'ИндивидуальныйПредприниматель'})

        for code, name in (('90.01.1', 'Выручка'), ('68.10', 'Прочие налоги и сборы'),
                           ('68.12', 'Налог при УСН'), ('69.06', 'Взносы единый тариф ИП'),
                           ('51', 'Расчётные счета'), ('62.01', 'Расчёты с покупателями'),
                           ('90.02.1', 'Себестоимость продаж')):
            await s.execute(text("""
                INSERT INTO gl_accounts (id, company_id, code, name, kind, off_balance,
                                         quantitative, currency, is_deleted)
                VALUES (gen_random_uuid(), CAST(:c AS uuid), :code, :name, 'АП',
                        false, false, false, false)"""),
                {"c": str(cid), "code": code, "name": name})

        rows = [
            # выручка и оплата
            ('62.01', '90.01.1', 500000, 'Реализация услуг'),
            ('51', '62.01', 500000, 'Оплата от покупателя'),
            ('90.02.1', '20.01', 120000, 'Себестоимость'),
            # налоги предпринимателя
            ('99.01.1', '68.10', 45000, 'НДФЛ предпринимателя'),
            ('68.10', '51', 45000, 'Уплата НДФЛ ИП'),
            ('99.01.1', '68.12', 30000, 'Налог при УСН'),
            ('44.01', '69.06', 49500, 'Взносы ИП за себя'),
        ]
        for dt, kt, amount, content in rows:
            await s.execute(text("""
                INSERT INTO gl_entries (id, company_id, organization_id, entry_date,
                        period_year, period_month, account_dt, account_kt, amount,
                        content, source, external_key)
                VALUES (gen_random_uuid(), CAST(:c AS uuid), CAST(:o AS uuid),
                        DATE '2026-03-31', 2026, 3, :dt, :kt, :a, :txt, 'probe',
                        'probe:' || gen_random_uuid()::text)"""),
                {"c": str(cid), "o": str(oid), "dt": dt, "kt": kt, "a": amount, "txt": content})
        await s.commit()

        print('== что слой понял про предпринимателя')
        m = await tax_mode(s, cid)
        for k in ('label', 'ip', 'osno', 'osnoIp', 'usn', 'patent', 'vat',
                  'cashBasis', 'ownContributions', 'organizations', 'ipOrganizations'):
            print('   %-18s %s' % (k, m[k]))

        ok = m['ip'] and m['osnoIp'] and m['usn'] and m['cashBasis'] and not m['osno']
        print('\n   режим прочитан верно:', 'ДА' if ok else 'НЕТ')

        # Проверяем то, ради чего всё: налог считается по НАЧИСЛЕНИЮ, а не ставкой 25 %.
        tax = (await s.execute(text("""
            SELECT coalesce(sum(amount) FILTER (
                     WHERE account_kt LIKE '68.12%' OR account_kt LIKE '68.45%'
                        OR account_kt LIKE '68.10%'), 0)
                 - coalesce(sum(amount) FILTER (
                     WHERE (account_dt LIKE '68.12%' OR account_dt LIKE '68.45%'
                         OR account_dt LIKE '68.10%')
                       AND account_kt NOT LIKE '51%' AND account_kt NOT LIKE '68.90%'), 0)
              FROM gl_entries WHERE company_id = CAST(:c AS uuid)"""), {"c": str(cid)})).scalar_one()
        profit = 500000 - 120000
        print('   налог по начислению: %s ₽ (ставка 25 %% от прибыли дала бы %s ₽)'
              % (tax, round(profit * 0.25)))

        await cleanup(s, cid)
        print('\nпесочница убрана')


asyncio.run(main())
