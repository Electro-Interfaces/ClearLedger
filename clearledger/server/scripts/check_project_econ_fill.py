"""Заполненность полей экономики в «Проектах» — есть ли на что опираться."""
import asyncio
from sqlalchemy import func, select
from app.database import async_session_factory
from app.models import Company, EzsSite


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        total, tp, term, free, rent, smr, planned = (await db.execute(
            select(func.count(), func.count(EzsSite.tp_cost),
                   func.count(EzsSite.tp_term_months), func.count(EzsSite.free_power_num),
                   func.count(EzsSite.rent_cost_month), func.count(EzsSite.smr_cost),
                   func.count(EzsSite.planned_power_kwt))
            .where(EzsSite.company_id == company.id))).one()
        print(f"площадок всего: {total}")
        for label, value in (("стоимость ТП", tp), ("срок ТП", term),
                             ("свободная мощность", free), ("аренда", rent),
                             ("СМР", smr), ("плановая мощность", planned)):
            print(f"   {label:<22}{value:>6}  ({round(value / total * 100) if total else 0} %)")


asyncio.run(main())
