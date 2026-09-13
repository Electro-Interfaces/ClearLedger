"""Отметить приложения, которых больше нет, хотя они и лежат в магазине.

Приложение в RuStore не значит работающий сервис. У РусГидро в выдаче два: сеть
обслуживает `ru.rushydro.car` (разработчик «РУСГИДРО ИТ СЕРВИС»), а
`com.rucharge.rusgidro` остался от платформы ZEVS, через которую сеть больше не
работает. Пока обе записи считались действующими, одна сеть попадала в разрезы
дважды, её 429 станций складывались сами с собой, и продукт сообщал, что точка
контакта с водителем у нас раздвоена (замечание МАГа 13.09.2026).

Факт закрытия приходит от человека: из магазина этого не видно.

Прогон:  ~/.claude/skills/elsy-deploy/scripts/exec-py.sh rushydro mark_closed_apps.py
"""
import asyncio

from sqlalchemy import select

from app.database import async_session_factory
from app.models import MarketPlayer

# Пакет → чем подтверждено, что приложение не работает.
CLOSED = {
    "com.rucharge.rusgidro":
        "приложение платформы ZEVS: сеть РусГидро через него больше не работает, "
        "обслуживание перешло в «ЭЗС РусГидро» (ru.rushydro.car, РусГидро ИТ Сервис). "
        "Подтверждено МАГом 13.09.2026",
    "com.rucharge.zevs":
        "платформа ZEVS закрыта: приложение остаётся в магазине, но сервиса за ним "
        "нет. Подтверждено МАГом 13.09.2026",
}


async def main() -> None:
    async with async_session_factory() as db:
        rows = (await db.execute(select(MarketPlayer).where(
            MarketPlayer.package.in_(list(CLOSED))))).scalars().all()
        if not rows:
            print("таких приложений в базе нет — возможно, реестр игроков не загружен")
            return
        for row in rows:
            row.is_active = False
            row.status_note = CLOSED[row.package]
            print(f"   {row.app} ({row.package}) — не работает")
        await db.commit()

        active = (await db.execute(select(MarketPlayer).where(
            MarketPlayer.is_active.is_(True)))).scalars().all()
        closed = (await db.execute(select(MarketPlayer).where(
            MarketPlayer.is_active.is_(False)))).scalars().all()
        print(f"\nдействующих приложений {len(active)}, закрытых {len(closed)}")

        # Проверка ради которой всё и делалось: станции сети не считаются дважды.
        ours = [p for p in active if (p.matched_operator or "").lower() == "русгидро"]
        print(f"действующих приложений РусГидро: {len(ours)}"
              + (f" — {ours[0].app} ({ours[0].package})" if len(ours) == 1 else ""))
        assert len(ours) <= 1, "у сети снова больше одного действующего приложения"


asyncio.run(main())
