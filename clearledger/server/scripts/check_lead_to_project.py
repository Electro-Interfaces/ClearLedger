"""Приёмка К11: кандидат развития доходит до площадки в «Проектах».

Проверяем границу двух продуктов: маркетинг находит и обосновывает, «Проекты»
строят. Обоснование должно переехать целиком, ссылка — встать в обе стороны.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_lead_to_project.py
"""
import asyncio
import uuid as _uuid

from sqlalchemy import delete, select

from app.database import async_session_factory
from app.models import Company, EzsSite, MarketGrowthLead, User
from app.routers.market_router import (GrowthLeadIn, create_growth_lead,
                                       lead_to_project, list_growth_leads)


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        print(f"пространство: {company.name}\n")

        created = await create_growth_lead(
            company_id=cid,
            body=GrowthLeadIn(
                track="build",
                title="(проверка) войти в Архангельск своей станцией",
                subject_kind="territory", subject_ref="Архангельск",
                evidence={"city": "Архангельск", "region": "Архангельская область",
                          "rivalsAlive": 2, "rivalSites": 4,
                          "forecastSessions": 105, "basis": "аналоги, город"},
                note="кандидат заведён приёмкой"),
            user=user, db=db)
        print(f"1. кандидат заведён: {created['id']}")

        result = await lead_to_project(lead_id=_uuid.UUID(created["id"]),
                                       company_id=cid, user=user, db=db)
        print(f"2. {result['message']}")

        site = (await db.execute(select(EzsSite).where(
            EzsSite.id == _uuid.UUID(result["siteId"])))).scalar_one()
        evidence = (site.raw or {}).get("marketLead", {}).get("evidence", {})
        print(f"3. площадка {site.project_no}: стадия «{site.stage}», "
              f"город «{site.city}», регион «{site.region}»")
        print(f"   обоснование переехало: {evidence}")

        leads = await list_growth_leads(company_id=cid, track="build", user=user, db=db)
        mine = next(x for x in leads["leads"] if x["id"] == created["id"])
        print(f"4. кандидат: статус «{mine['status']}», ссылка на площадку "
              f"{'есть' if mine['siteId'] else 'НЕТ'}")

        again = await lead_to_project(lead_id=_uuid.UUID(created["id"]),
                                      company_id=cid, user=user, db=db)
        print(f"5. повторный вызов: создано={again['created']} — {again['message']}")

        await db.execute(delete(MarketGrowthLead).where(
            MarketGrowthLead.id == _uuid.UUID(created["id"])))
        await db.execute(delete(EzsSite).where(EzsSite.id == site.id))
        await db.commit()
        print("\nтестовые записи удалены")


asyncio.run(main())
