# -*- coding: utf-8 -*-
"""Виды субконто по счетам — карта, без которой аналитика оборотов остаётся строкой.

В обороте (`gl_turnovers`) субконто приходят ПРЕДСТАВЛЕНИЯМИ: «АЗИМУТ ООО»,
«Основной договор», «40702810327980001235, Филиал…». Что именно записано в первой
позиции, зависит от СЧЁТА: у 62.01 это контрагент, у 20.01 — номенклатурная группа,
у 51 — банковский счёт. Знание живёт в плане счетов 1С (табличная часть
«ВидыСубконто»), и без него сведение аналитики невозможно в принципе.

Данные читает из /tmp/onec-subconto.json (набор `queries-subconto`).
"""
import asyncio
import json
import os

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company

SRC = '/tmp/onec-subconto.json'

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан: укажи slug компании (promizol, rti, ...)')


async def main():
    data = json.load(open(SRC, encoding='utf-8'))
    rows = data['01-account-subconto']
    async with async_session_factory() as s:
        company = (await s.execute(
            select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if company is None:
            print('НЕТ компании', SLUG, 'в пространстве — сначала завести её')
            return
        cid = company.id

        # Порядок субконто у счёта — не украшение: по нему определяется, что лежит в
        # dt1, а что в dt2. Сортируем сами, на порядок строк выгрузки не полагаясь.
        by_account: dict[str, list[tuple[int, str]]] = {}
        for r in rows:
            code = (r.get('КодСчета') or '').strip()
            kind = (r.get('ВидСубконто') or '').strip()
            if not code or not kind:
                continue
            by_account.setdefault(code, []).append((int(r.get('Порядок') or 0), kind))

        updated = 0
        for code, items in by_account.items():
            kinds = [k for _, k in sorted(items)]
            res = await s.execute(text(
                "UPDATE gl_accounts SET subconto = CAST(:v AS jsonb)"
                " WHERE company_id = :c AND code = :code"),
                {"v": json.dumps(kinds, ensure_ascii=False), "c": str(cid), "code": code})
            updated += res.rowcount or 0
        await s.commit()

        total = (await s.execute(text(
            "SELECT count(*) FROM gl_accounts WHERE company_id = :c"),
            {"c": str(cid)})).scalar_one()
        with_sub = (await s.execute(text(
            "SELECT count(*) FROM gl_accounts WHERE company_id = :c AND subconto IS NOT NULL"),
            {"c": str(cid)})).scalar_one()
        print('счетов с субконто в 1С: %d · проставлено у нас: %d из %d счетов'
              % (len(by_account), with_sub, total))
        if not with_sub:
            print('  [!] ни одного совпадения по коду счёта — проверить, что план счетов загружен')


asyncio.run(main())
