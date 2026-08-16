# -*- coding: utf-8 -*-
"""Прибрать за загрузкой: вернуть место и обновить статистику планировщика.

Загрузка слоя идёт `delete` + `insert` целыми таблицами, и после каждого захода
остаются мёртвые строки — на стенде их набралось 19 % в `accounting_docs` и
`gl_entries`. Дело не только в месте: планировщик считает по СТАТИСТИКЕ, а она
после массовой заливки описывает прошлую жизнь таблицы, и запрос, который должен
идти по индексу, уходит в полный скан.

`VACUUM` без `FULL` намеренно: `FULL` переписывает таблицу под эксклюзивной
блокировкой, а стенд рабочий. Обычный возвращает место под переиспользование и
обновляет статистику — этого достаточно.
"""
import asyncio

from app.database import engine

TABLES = [
    'gl_entries', 'gl_turnovers', 'gl_balances', 'gl_accounts', 'gl_references',
    'accounting_docs', 'counterparties', 'contracts', 'nomenclature', 'periods',
    'invoice_payments', 'vat_entries', 'payroll_entries', 'organizations',
]


async def main():
    # VACUUM нельзя выполнить внутри транзакции — нужен autocommit-режим соединения.
    async with engine.connect() as conn:
        raw = await conn.get_raw_connection()
        drv = raw.driver_connection
        for t in TABLES:
            try:
                await drv.execute('VACUUM (ANALYZE) core.%s' % t)
                print('  прибрано:', t)
            except Exception as e:
                print('  [!] %s: %s' % (t, str(e)[:80]))
    print('статистика планировщика обновлена')


asyncio.run(main())
