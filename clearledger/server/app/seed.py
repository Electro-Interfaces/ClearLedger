"""
Начальные данные: 5 компаний + демо-пользователь.
Запускается при старте приложения (идемпотентно).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import Company, User

logger = logging.getLogger("clearledger.seed")

# 5 компаний — данные совпадают с config/companies.ts (defaultCompanies)
COMPANIES = [
    {"slug": "npk", "name": "НПК", "short_name": "НПК", "profile_id": "fuel", "color": "#3b82f6"},
    {"slug": "rti", "name": "РТИ", "short_name": "РТИ", "profile_id": "fuel", "color": "#8b5cf6"},
    {"slug": "ts94", "name": "ТС-94", "short_name": "ТС-94", "profile_id": "trade", "color": "#10b981"},
    {"slug": "ofptk", "name": "ОФ ПТК", "short_name": "ОФПТК", "profile_id": "retail", "color": "#f59e0b"},
    {"slug": "rushydro", "name": "РусГидро", "short_name": "РусГидро", "profile_id": "energy", "color": "#ef4444"},
]

DEMO_USER = {
    "email": "admin@clearledger.ru",
    "password": "admin123",
    "name": "Администратор",
    "role": "admin",
}


async def seed_data(db: AsyncSession) -> None:
    """Создаёт начальные компании и демо-пользователя (если отсутствуют)."""

    # --- Компании ---
    existing = await db.execute(select(Company))
    existing_slugs = {c.slug for c in existing.scalars().all()}

    created_companies: list[Company] = []
    for comp in COMPANIES:
        if comp["slug"] not in existing_slugs:
            company = Company(**comp)
            db.add(company)
            created_companies.append(company)
            logger.info("Создана компания: %s (%s)", comp["name"], comp["slug"])

    if created_companies:
        await db.flush()  # получить ID

    # --- Демо-пользователь ---
    result = await db.execute(
        select(User).where(User.email == DEMO_USER["email"])
    )
    if result.scalar_one_or_none() is None:
        # Привязываем к первой компании (НПК)
        first_company = await db.execute(
            select(Company).where(Company.slug == "npk")
        )
        company = first_company.scalar_one_or_none()
        if company:
            user = User(
                email=DEMO_USER["email"],
                password_hash=hash_password(DEMO_USER["password"]),
                name=DEMO_USER["name"],
                role=DEMO_USER["role"],
                company_id=company.id,
            )
            db.add(user)
            logger.info(
                "Создан демо-пользователь: %s / %s",
                DEMO_USER["email"],
                DEMO_USER["password"],
            )

    await db.commit()
    logger.info("Seed завершён")
