"""Приёмка приёма реестра рынка на стенде (docs/MARKET-ROADMAP.md §9, этап 1).

Отвечает на пять вопросов, по которым виден результат загрузки, и на два, по которым
видно, что загрузка не соврала:

  1. сколько точек рынка и в каких классах;
  2. сколько срезов и на какие даты;
  3. сколько операторов (без площадок-агрегаторов);
  4. какая медиана рублёвого тарифа и по скольким точкам она посчитана;
  5. сколько точек живых по последней зарядке;
  6. нет ли дублей по ключу источника (повторная загрузка не должна плодить точки);
  7. не попали ли наши станции в конкуренты.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_registry.py
"""
import asyncio

from sqlalchemy import func, select

from app.database import async_session_factory
from app.models import (Company, MarketObservation, MarketOperator, MarketSite,
                        MarketSiteSnapshot)


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
        if company is None:
            print("компаний в базе нет")
            return
        cid = company.id
        print(f"пространство: {company.name}\n")

        rows = (await db.execute(
            select(MarketSite.site_class, MarketSite.status, func.count())
            .where(MarketSite.company_id == cid)
            .group_by(MarketSite.site_class, MarketSite.status))).all()
        total = sum(int(c) for _, _, c in rows)
        print(f"1. точек рынка: {total}")
        for klass, status, count in sorted(rows, key=lambda r: -r[2]):
            print(f"   {klass or '—':>10} · {status:<8} {int(count):>6}")

        snaps = (await db.execute(
            select(MarketSiteSnapshot.snapshot_date, func.count())
            .where(MarketSiteSnapshot.company_id == cid)
            .group_by(MarketSiteSnapshot.snapshot_date)
            .order_by(MarketSiteSnapshot.snapshot_date.desc()))).all()
        print(f"\n2. срезов: {len(snaps)}")
        for date, count in snaps[:8]:
            print(f"   {date}: {int(count)} точек")

        ops = (await db.execute(
            select(MarketOperator.relation, func.count())
            .where(MarketOperator.company_id == cid)
            .group_by(MarketOperator.relation))).all()
        print("\n3. операторы:", ", ".join(f"{r}: {int(c)}" for r, c in ops) or "нет")
        top = (await db.execute(
            select(MarketOperator.name, func.count(MarketSite.id))
            .join(MarketSite, MarketSite.operator_id == MarketOperator.id)
            .where(MarketOperator.company_id == cid)
            .group_by(MarketOperator.name)
            .order_by(func.count(MarketSite.id).desc()).limit(8))).all()
        for name, count in top:
            print(f"   {name}: {int(count)} точек")

        prices = [float(p) for (p,) in (await db.execute(
            select(MarketObservation.price_per_kwh)
            .where(MarketObservation.company_id == cid,
                   MarketObservation.kind == "price",
                   MarketObservation.price_per_kwh.is_not(None)))).all()]
        median = sorted(prices)[len(prices) // 2] if prices else None
        conflicts = int((await db.execute(
            select(func.count()).select_from(MarketObservation)
            .where(MarketObservation.company_id == cid,
                   MarketObservation.confidence == "conflict"))).scalar() or 0)
        print(f"\n4. цен сравнимых: {len(prices)}, медиана: {median} ₽/кВт·ч, "
              f"спорных (вне диапазона): {conflicts}")

        alive = int((await db.execute(
            select(func.count()).select_from(MarketSite)
            .where(MarketSite.company_id == cid,
                   MarketSite.last_session_at.is_not(None)))).scalar() or 0)
        print(f"\n5. точек с датой последней зарядки: {alive}")

        dup = (await db.execute(
            select(MarketSite.external_id, func.count())
            .where(MarketSite.company_id == cid, MarketSite.external_id.is_not(None))
            .group_by(MarketSite.external_id)
            .having(func.count() > 1).limit(5))).all()
        print(f"\n6. дублей по ключу источника: {len(dup)}"
              + ("" if not dup else f" ← ПЛОХО: {[d[0] for d in dup]}"))

        ours = int((await db.execute(
            select(func.count()).select_from(MarketSite)
            .join(MarketOperator, MarketSite.operator_id == MarketOperator.id)
            .where(MarketSite.company_id == cid,
                   MarketOperator.relation == "own"))).scalar() or 0)
        print(f"7. наших точек в рынке (оператор own, конкурентами не считаются): {ours}")


asyncio.run(main())
