"""Компания Поддержки для компании пространства — фильтр витрин заявок.

Ядро читает `public.tickets` прямым SQL: базы сведены, и это дешевле проекции.
Но `company_id` у Поддержки СВОЙ — приложение ведёт собственную таблицу компаний,
поэтому фильтровать по `cid` Ядра нельзя, а не фильтровать вовсе — значит в
мультикомпанийном контейнере показать компании А заявки компании Б.

Пара «наша компания — его компания» ведётся картой `eco_app_company_links`
(docs/SPACE.md §9). Здесь она читается один раз на запрос и подставляется в SQL.

**Нет карты — нет выдачи.** Пустой ответ честнее, чем чужие заявки: карта
заводится при онбординге приложения компании, и её отсутствие означает, что
приложение этой компании ещё не подключено.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import App, AppCompanyLink

SUPPORT_APP_CODE = "support"


async def support_company_id(db: AsyncSession, company_id) -> str | None:
    """Идентификатор этой компании на стороне Поддержки, либо None."""
    return await db.scalar(
        select(AppCompanyLink.external_company_id)
        .join(App, App.id == AppCompanyLink.app_id)
        .where(App.code == SUPPORT_APP_CODE, AppCompanyLink.company_id == company_id)
        .limit(1)
    )
