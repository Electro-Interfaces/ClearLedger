"""Seed: создание начального admin + 5 компаний при первом запуске."""

import asyncio

from passlib.hash import bcrypt
from sqlalchemy import select

from app.database import engine, async_session, Base
from app.models.models import User, Company


COMPANIES = [
    {"id": "npk", "name": "ООО НПК", "short_name": "НПК", "profile_id": "fuel", "color": "#3b82f6"},
    {"id": "rti", "name": "ООО РТИ", "short_name": "РТИ", "profile_id": "trade", "color": "#10b981"},
    {"id": "ts94", "name": "ООО ТС-94", "short_name": "ТС-94", "profile_id": "fuel", "color": "#f59e0b"},
    {"id": "ofptk", "name": "АО ОФ ПТК", "short_name": "ОФ ПТК", "profile_id": "retail", "color": "#ef4444"},
    {"id": "rushydro", "name": "ПАО РусГидро", "short_name": "РусГидро", "profile_id": "energy", "color": "#8b5cf6"},
]


async def seed():
    async with async_session() as db:
        # Admin
        exists = await db.execute(select(User).where(User.email == "admin@clearledger.ru"))
        if not exists.scalar_one_or_none():
            admin = User(
                email="admin@clearledger.ru",
                name="Администратор",
                password_hash=bcrypt.hash("admin"),
                role="admin",
            )
            db.add(admin)
            print("  [seed] Создан admin: admin@clearledger.ru / admin")

        # Компании
        for c in COMPANIES:
            exists = await db.execute(select(Company).where(Company.id == c["id"]))
            if not exists.scalar_one_or_none():
                db.add(Company(**c))
                print(f"  [seed] Создана компания: {c['short_name']}")

        await db.commit()
        print("  [seed] Готово.")


if __name__ == "__main__":
    asyncio.run(seed())
