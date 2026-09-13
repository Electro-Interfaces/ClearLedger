"""Приёмка: что известно о компаниях рынка и что из этого доходит до экрана.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_companies_full.py
"""
import asyncio

from sqlalchemy import select, text

from app.database import async_session_factory
from app.models import Company, MarketOperator, User
from app.routers.market_router import list_operators, operator_card


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)

        ops = (await list_operators(company_id=cid, user=user, db=db))["operators"]
        print(f"компаний: {len(ops)}")

        def have(field: str) -> int:
            return sum(1 for o in ops if o.get(field) not in (None, "", 0))

        print("\nчто известно и о скольких:")
        for field, label in (
            ("class", "модель бизнеса"), ("baseCity", "город базирования"),
            ("platformCode", "платформа"), ("roaming", "роуминг известен"),
            ("appName", "приложение"), ("publicRating", "публичная оценка"),
            ("inn", "ИНН"), ("ogrn", "ОГРН"), ("director", "руководитель"),
            ("legalStatus", "статус юрлица"), ("phone", "телефон"),
            ("siteUrl", "сайт"), ("sourceCount", "число источников"),
            ("pointsOsm", "точки из OSM"), ("cardsYandex", "карточки справочника"),
        ):
            print(f"   {label:<24}{have(field):>4} из {len(ops)}")

        print("\nмодели бизнеса:")
        by_class: dict[str, int] = {}
        for o in ops:
            by_class[o.get("class") or "— не определена"] = \
                by_class.get(o.get("class") or "— не определена", 0) + 1
        for cls, n in sorted(by_class.items(), key=lambda kv: -kv[1]):
            print(f"   {cls[:36]:<38}{n}")

        print("\nподтверждённые реквизиты:")
        for o in [x for x in ops if x.get("legalTrusted")][:10]:
            print(f"   {o['name'][:22]:<24}{(o.get('legalName') or '')[:34]:<36}"
                  f"ИНН {o.get('inn')}, {o.get('legalStatus') or 'статус неизвестен'}")

        print("\nнайдены несколькими источниками:")
        multi = sorted((o for o in ops if (o.get("sourceCount") or 0) > 1),
                       key=lambda o: -(o.get("sourceCount") or 0))[:8]
        for o in multi:
            print(f"   {o['name'][:22]:<24}источников {o['sourceCount']} ({o.get('sources')}), "
                  f"точек всего {o.get('pointsTotal')}")

        big = (await db.execute(select(MarketOperator).where(
            MarketOperator.company_id == company.id,
            MarketOperator.points_total.is_not(None))
            .order_by(MarketOperator.points_total.desc()).limit(1))).scalar_one_or_none()
        if big:
            card = await operator_card(operator_id=big.id, company_id=cid,
                                       user=user, db=db)
            print(f"\nкарточка «{card['name']}»:")
            print(f"   модель: {card.get('class')} "
                  f"({'проверена' if card.get('classChecked') else 'не проверена'})")
            print(f"   база: {card.get('baseCity')}, городов {card.get('cities')}, "
                  f"округов {card.get('districts')}")
            print(f"   платформа: {card.get('platformCode')} "
                  f"(владелец {card.get('platformOwner') or 'неизвестен'}), "
                  f"роуминг: {card.get('roaming')}")
            print(f"   юрлицо: {card.get('legalName') or 'не найдено'} "
                  f"[{card.get('legalConfidence') or 'нет пометки'}]")
            print(f"   ИНН {card.get('inn') or '—'}, телефон {card.get('phone') or '—'}, "
                  f"сайт {card.get('siteUrl') or '—'}")
            print(f"   точек: всего {card.get('pointsTotal')}, в реестре "
                  f"{card.get('pointsRegistry')}, из OSM {card.get('pointsOsm')}, "
                  f"карточек справочника {card.get('cardsYandex')}")
            print(f"   в нашей базе точек: {card['totals']['sites']}, "
                  f"городов в разрезе: {len(card.get('cities') or [])}")

        gap = (await db.execute(text("""
            select count(*) from core.market_operators
            where points_osm is not null and points_registry is null"""))).scalar_one()
        print(f"\nкомпаний, которых видит только внешний источник: {gap}")


asyncio.run(main())
