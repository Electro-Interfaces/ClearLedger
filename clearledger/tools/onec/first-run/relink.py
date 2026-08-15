# -*- coding: utf-8 -*-
"""Свести документы компании с карточками контрагентов и договоров.

Тот же код, что за ручкой `POST /api/books/relink`: пока связь существует только
строкой, «его документы», «его долг» и «его договоры» — три списка, которые между
собой не сходятся, потому что юрлицо приезжает в разном написании.

Порядок ключей: ИНН → точное имя → нормализованное имя; договор ищется по названию
внутри контрагента.
"""
import asyncio
import os

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company
from app.services.books_links import relink

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан')


async def main():
    async with async_session_factory() as s:
        cid = (await s.execute(select(Company.id).where(Company.slug == SLUG))).scalar_one()
        # reset=True — пересобрать связи целиком: после перезалива справочников старые
        # ссылки указывают на карточки, которых больше нет.
        res = await relink(s, cid, reset=True)
        await s.commit()
        for k, v in res.items():
            print('  %-28s %s' % (k, v))


asyncio.run(main())
