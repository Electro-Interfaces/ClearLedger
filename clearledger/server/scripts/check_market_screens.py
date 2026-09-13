"""Приёмка: ни один экран «Маркетинга» не падает и отвечает за разумное время.

Экран «Компании и расклад сил» молча показывал пустые скелетоны, потому что после
переименования поля в общем helper'е в нём осталась ссылка на старое имя: сервер
падал с KeyError, а человек видел мигающие полосы и думал, что данные считаются.
Ошибка такого рода не ловится ни типами Python, ни проверкой фронта — только
вызовом каждого экрана.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_screens.py
"""
import asyncio
import time
import traceback

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, User
from app.routers import market_router as m


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        common = {"company_id": cid, "user": user, "db": db}

        # Каждый экран рельсы, в порядке разделов меню. Вызовы ленивые: иначе
        # корутины создаются все разом, и первая же ошибка сигнатуры роняет проверку
        # до того, как хоть один экран будет вызван.
        screens = [
            ("Позиция · наши объекты",
             lambda: m.market_position(days=30, radius_km=3.0, **common)),
            ("Позиция · мы глазами рынка",
             lambda: m.market_self_view(match_km=0.3, days=90, **common)),
            ("Карта и точки рынка", lambda: m.list_sites(
                kind=None, city=None, bbox=None, site_class=None, current_type=None,
                operator_id=None, min_power=None, alive=None, search=None,
                limit=500, offset=0, **common)),
            ("Точки · разрезы",
             lambda: m.sites_breakdown(city=None, region=None, operator_id=None, **common)),
            ("Компании · список", lambda: m.list_operators(**common)),
            ("Компании и расклад сил", lambda: m.market_landscape(**common)),
            ("Игроки рынка", lambda: m.market_players(**common)),
            ("Наблюдения", lambda: m.list_observations(site_id=None, limit=100, **common)),
            ("Обеспеченность", lambda: m.market_coverage(**common)),
            ("Территории", lambda: m.market_territories(level="city", days=90, **common)),
            ("Белые пятна", lambda: m.market_whitespots(level="city", **common)),
            ("Оценка площадки", lambda: m.market_site_score(
                lat=55.75, lon=37.62, radius_km=3.0, days=90,
                place="auto", speed_class="auto", **common)),
            ("Ценовой ландшафт", lambda: m.market_price_landscape(days=90, **common)),
            ("Давление конкурента",
             lambda: m.market_pressure(months=24, radius_km=3.0, **common)),
            ("Эластичность", lambda: m.market_elasticity(
                weeks=52, min_change_pct=5, min_sessions=20, **common)),
            ("Направления роста", lambda: m.growth_overview(days=90, **common)),
            ("Присутствие по регионам", lambda: m.growth_presence(days=90, **common)),
            ("Стройка в работе", lambda: m.growth_pipeline(**common)),
            ("Кандидаты", lambda: m.list_growth_leads(track=None, **common)),
            ("Партнёрство и франшиза", lambda: m.market_partners(min_sites=1, **common)),
            ("Сценарии", lambda: m.list_scenarios(**common)),
            ("Источники и свежесть", lambda: m.market_sources(**common)),
            ("Изменения рынка",
             lambda: m.market_changes(base=None, current=None, limit=50, **common)),
        ]

        bad = 0
        slow = []
        for label, call in screens:
            t = time.perf_counter()
            try:
                await call()
                dt = time.perf_counter() - t
                mark = "медленно" if dt > 3 else ""
                if dt > 3:
                    slow.append((label, dt))
                print(f"   {label:<30}{dt:6.2f} с  {mark}")
            except Exception as exc:
                bad += 1
                print(f"   {label:<30}СЛОМАН: {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=3)

        print(f"\nэкранов {len(screens)}, сломано {bad}, дольше 3 с — {len(slow)}")
        for label, dt in slow:
            print(f"   {label}: {dt:.1f} с")
        assert bad == 0, f"сломанных экранов: {bad}"


asyncio.run(main())
