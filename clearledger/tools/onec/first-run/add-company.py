# -*- coding: utf-8 -*-
"""Завести компанию-клиента в пространстве без пересоздания контейнера.

Обычно компании приезжают из `ECOSYSTEM_COMPANIES` при старте backend, но это рестарт
всего пространства. Здесь то же самое делается на живой базе: запись в `companies` плюс
системные роли профиля — тем же кодом сидирования, что и при старте.

⚠ После этого допиши компанию в `ECOSYSTEM_COMPANIES` стека: seed не удаляет лишних,
но при следующем провижининге на чистой базе её иначе не будет.

Параметры — окружением: COMPANY_SLUG, COMPANY_NAME, COMPANY_SHORT, COMPANY_INN,
COMPANY_PROFILE (по умолчанию office), COMPANY_COLOR.
"""
import asyncio
import os

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company
from app.seed import _seed_system_roles

SLUG = os.environ.get('COMPANY_SLUG')
if not SLUG:
    raise SystemExit('COMPANY_SLUG не задан')


async def main():
    async with async_session_factory() as s:
        exists = (await s.execute(select(Company).where(Company.slug == SLUG))).scalar_one_or_none()
        if exists:
            print('компания уже есть:', exists.name, exists.id, '| профиль', exists.profile_id)
        else:
            c = Company(
                slug=SLUG,
                name=os.environ.get('COMPANY_NAME') or SLUG,
                short_name=os.environ.get('COMPANY_SHORT') or SLUG,
                profile_id=os.environ.get('COMPANY_PROFILE', 'office'),
                color=os.environ.get('COMPANY_COLOR') or None,
                inn=os.environ.get('COMPANY_INN') or None,
            )
            s.add(c)
            await s.flush()
            print('создана компания:', c.name, c.id, '| профиль', c.profile_id)
        # Роли профиля досеиваются идемпотентно — тем же кодом, что при старте.
        await _seed_system_roles(s)
        await s.commit()

        rows = (await s.execute(select(Company.slug, Company.name, Company.profile_id, Company.inn)
                                .order_by(Company.slug))).all()
        print('--- компании пространства ---')
        for r in rows:
            print('  %-10s %-24s %-8s %s' % (r[0], r[1], r[2], r[3] or ''))


asyncio.run(main())
