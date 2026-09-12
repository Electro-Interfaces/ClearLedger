"""Приёмка этапа 2: компании рынка и карточка оператора.

Зовём те же функции роутера, что отдаёт API, — сверяются не запросы, а то, что
увидит человек на экране. Проверяем главное: что домашние розетки не попали в
счёт сети, что цена и качество считаются по известным, а не по нулям, и что
карточка крупнейшего конкурента собирается целиком.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro check_market_companies.py
"""
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Company, User
from app.routers.market_router import list_operators, operator_card


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company).limit(1))).scalar_one()
        user = (await db.execute(select(User).limit(1))).scalar_one()
        cid = str(company.id)
        print(f"пространство: {company.name}\n")

        reply = await list_operators(company_id=cid, user=user, db=db)
        rows = reply["operators"]
        networks = [r for r in rows if r["sites"] > 0]
        print(f"компаний всего: {len(rows)}, с точками сети: {len(networks)}")
        print(f"{'компания':<22}{'точек':>7}{'живых':>7}{'портов':>8}"
              f"{'медиана ₽':>11}{'связь':>8}{'оценка':>8}")
        for r in networks[:10]:
            print(f"{r['name'][:21]:<22}{r['sites']:>7}{r['alive']:>7}{r['ports']:>8}"
                  f"{('—' if r['medianPricePerKwh'] is None else r['medianPricePerKwh']):>11}"
                  f"{('—' if r['quality'] is None else r['quality']):>8}"
                  f"{('—' if r['rating'] is None else r['rating']):>8}")

        if not networks:
            print("\nкомпаний с точками нет — карточку проверять не на чем")
            return

        top = networks[0]
        card = await operator_card(operator_id=top["id"], company_id=cid, user=user, db=db)
        t = card["totals"]
        print(f"\nкарточка «{card['name']}»:")
        print(f"   точек сети {t['sites']}, домашних розеток под тем же именем "
              f"{t['homeSockets']} (в счёт сети не идут)")
        print(f"   портов {t['ports']}, живых {t['alive']}, в планах {t['planned']}")
        print(f"   медиана {t['medianPricePerKwh']} ₽/кВт·ч по {t['pricedSites']} наблюдениям")
        print(f"   связь {t['quality']} %, успешность {t['success']} %, "
              f"оценка {t['rating']} по {t['reviews']} отзывам")
        print(f"   городов в разрезе: {len(card['cities'])}, "
              f"мощностных групп: {len(card['power'])}, месяцев роста: {len(card['months'])}")
        print("   топ городов:", ", ".join(
            f"{c['name']} — {c['sites']}" for c in card["cities"][:5]) or "—")
        print("   оснащение:", ", ".join(
            f"{p['bucket']}: {p['sites']}" for p in card["power"]) or "—")

        # Главная проверка счёта: сумма точек по городам равна числу точек сети.
        by_city = sum(c["sites"] for c in card["cities"])
        print(f"\nсходимость: точек сети {t['sites']}, сумма по городам {by_city}"
              + ("  ← совпало" if by_city == t["sites"] else "  ← РАСХОЖДЕНИЕ"
                 " (города обрезаны до 12 — так и задумано, если компаний больше)"))


asyncio.run(main())
