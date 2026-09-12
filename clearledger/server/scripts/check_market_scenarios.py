"""Приёмка этапа 5: сквозной прогон сценария от гипотезы до замера.

Проверяем ровно то, ради чего продукт и строится: подбирается ли контрольная
группа, ловится ли непараллельность трендов ДО действия, и считается ли эффект
разностью разностей, а не «было/стало».

Тестовый сценарий после прогона удаляется — на боевом стенде мусора не оставляем.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_scenarios.py
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.database import async_session_factory
from app.models import (ChargeSession, Company, MarketScenario, MarketScenarioMeasure,
                        User)
from app.routers.market_router import (create_scenario, measure_scenario,
                                       suggest_control)
from app.routers.market_router import ScenarioIn


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        print(f"пространство: {company.name}\n")

        # Берём три объекта с реальным потоком сессий — иначе проверять нечего.
        since = (datetime.now(timezone.utc) - timedelta(weeks=16)).replace(tzinfo=None)
        busiest = (await db.execute(
            select(ChargeSession.location_id, func.count())
            .where(ChargeSession.company_id == company.id,
                   ChargeSession.started_at >= since,
                   ChargeSession.location_id.is_not(None))
            .group_by(ChargeSession.location_id)
            .order_by(func.count().desc()).limit(3))).all()
        scope = [str(loc) for loc, _ in busiest]
        print("объекты действия:", ", ".join(f"{loc} ({cnt} сессий)" for loc, cnt in busiest))
        if not scope:
            print("сессий нет — сценарий проверять не на чем")
            return

        suggestion = await suggest_control(
            company_id=cid, scope=",".join(scope), radius_km=5.0, weeks=8,
            user=user, db=db)
        parallel = suggestion["parallel"]
        print(f"\n1. подбор контроля: кандидатов {len(suggestion['candidates'])}, "
              f"взято {len(suggestion['control'])}")
        print(f"   профиль цели: соседей {suggestion['targetProfile']['rivals']}, "
              f"сессий {suggestion['targetProfile']['sessions']}")
        print(f"   тренды до действия: действие {parallel['scopeTrendPct']} %, "
              f"контроль {parallel['controlTrendPct']} %, расхождение {parallel['gapPct']} п.п.")
        print(f"   вывод проверки: {'ГОДЕН' if parallel['ok'] else 'НЕ ГОДЕН'} — {parallel['note']}")

        created = await create_scenario(
            company_id=cid,
            body=ScenarioIn(
                title="(проверка) тариф +1,5 ₽ на трёх объектах",
                action_kind="tariff",
                description="Тестовый сценарий приёмки, удаляется сразу после замера.",
                scope=scope, control=suggestion["control"],
                started_on=(datetime.now(timezone.utc) - timedelta(weeks=8)).date().isoformat(),
                status="running"),
            user=user, db=db)
        print(f"\n2. сценарий заведён: {created['id']}")

        import uuid as _uuid
        result = await measure_scenario(
            scenario_id=_uuid.UUID(created["id"]), company_id=cid, weeks=8,
            user=user, db=db)
        fact = result["fact"]
        print(f"\n3. замер: вердикт «{result['verdict']}»")
        print(f"   объекты действия: сессии {fact['scope']['sessionsPct']} %, "
              f"выручка {fact['scope']['revenuePct']} % ({fact['scope']['objects']} объектов)")
        print(f"   контроль:        сессии {fact['control']['sessionsPct']} %, "
              f"выручка {fact['control']['revenuePct']} % ({fact['control']['objects']} объектов)")
        print(f"   разность разностей: выручка {result['didRevenue']} п.п., "
              f"сессии {result['didSessions']} п.п.")
        print("   (эффектом считается именно разница, а не изменение самих объектов)")

        await db.execute(delete(MarketScenarioMeasure).where(
            MarketScenarioMeasure.scenario_id == _uuid.UUID(created["id"])))
        await db.execute(delete(MarketScenario).where(
            MarketScenario.id == _uuid.UUID(created["id"])))
        await db.commit()
        print("\nтестовый сценарий удалён")


asyncio.run(main())
