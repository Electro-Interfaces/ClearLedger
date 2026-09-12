"""Проверка К7: вердикт не выдаётся по незавершённому окну и малым данным."""
import asyncio, uuid as _uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select
from app.database import async_session_factory
from app.models import ChargeSession, Company, MarketScenario, MarketScenarioMeasure, User
from app.routers.market_router import ScenarioIn, create_scenario, measure_scenario


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        busiest = (await db.execute(
            select(ChargeSession.location_id, func.count())
            .where(ChargeSession.company_id == company.id,
                   ChargeSession.location_id.is_not(None))
            .group_by(ChargeSession.location_id)
            .order_by(func.count().desc()).limit(4))).all()
        locs = [str(x) for x, _ in busiest]

        cases = [
            ("окно после ещё не закрылось",
             dict(scope=locs[:2], control=locs[2:4],
                  started_on=(datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat())),
            ("группы пересекаются",
             dict(scope=locs[:2], control=locs[1:3],
                  started_on=(datetime.now(timezone.utc) - timedelta(weeks=9)).date().isoformat())),
            ("контроля нет",
             dict(scope=locs[:2], control=[],
                  started_on=(datetime.now(timezone.utc) - timedelta(weeks=9)).date().isoformat())),
        ]
        for label, kw in cases:
            created = await create_scenario(
                company_id=cid,
                body=ScenarioIn(title=f"(проверка) {label}", action_kind="tariff", **kw),
                user=user, db=db)
            res = await measure_scenario(scenario_id=_uuid.UUID(created["id"]),
                                         company_id=cid, weeks=8, user=user, db=db)
            print(f"{label:<32} вердикт: {res['verdict']:<9} причины: "
                  + "; ".join(res.get("reasons") or ["—"]))
            await db.execute(delete(MarketScenarioMeasure).where(
                MarketScenarioMeasure.scenario_id == _uuid.UUID(created["id"])))
            await db.execute(delete(MarketScenario).where(
                MarketScenario.id == _uuid.UUID(created["id"])))
            await db.commit()
        print("\nтестовые сценарии удалены")


asyncio.run(main())
