"""
Начальные данные: 5 компаний + демо-пользователь.
Запускается при старте приложения (идемпотентно).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import Company, PostingTemplate, User

logger = logging.getLogger("clearledger.seed")

# Компании — данные совпадают с config/companies.ts (defaultCompanies).
# Для GIG Ledger основная — gig (ООО ГИГ / ГазИнвестГрупп). Остальные — legacy.
COMPANIES = [
    {"slug": "gig", "name": "ООО ГИГ (ГазИнвестГрупп)", "short_name": "ГИГ", "profile_id": "fuel", "color": "#3b82f6", "inn": "7839124578"},
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

    # --- Шаблоны проводок (глобальные, company_id=NULL) ---
    await _seed_posting_templates(db)

    await db.commit()
    logger.info("Seed завершён")


# Типовые шаблоны проводок БП 3.0 — глобальные (company_id=NULL).
# Применяются всем компаниям как fallback. Компания может переопределить
# собственным шаблоном с тем же (doc_type, operation_type).
# Формула 'СуммаДок' раскрывается калькулятором в policy_router.
POSTING_TEMPLATES_GLOBAL = [
    # Розничная ОРП (ВидОперации=ОтчетККМОПродажах) — модель v3 после фикса
    # «розничная модель ≠ B2B»: 90.01.1 = вся выручка С НДС, выделение НДС
    # через 90.03/68.02, баланс через 62.Р.
    {
        "doc_type": "ОРП",
        "operation_type": "ОтчетККМОПродажах",
        "name": "Розничная продажа АЗС (стандарт БП 3.0)",
        "expected": [
            {"dt": "90.02.1", "kt": "41.02", "formula": None,
             "comment": "Списание себестоимости товара (на каждую SKU отдельной строкой)"},
            {"dt": "62.Р", "kt": "90.01.1", "formula": "СуммаДок",
             "comment": "Выручка с НДС"},
            {"dt": "57.03", "kt": "62.Р", "formula": None,
             "comment": "Оплата картами (доля СуммаДок)"},
            {"dt": "50.01", "kt": "62.Р", "formula": None,
             "comment": "Оплата наличными (доля СуммаДок)"},
            {"dt": "90.03", "kt": "68.02", "formula": "СуммаДок * 22 / 122",
             "comment": "Выделение НДС из выручки"},
        ],
        "notes": "См. memory project_orp_retail_vat_model и Срез 2 (project_srez2_implemented).",
    },
    # ПТУ — покупка топлива или товаров
    {
        "doc_type": "ПТУ",
        "operation_type": "Покупка",
        "name": "Поступление товаров (стандарт БП 3.0)",
        "expected": [
            {"dt": "41.01", "kt": "60.01", "formula": None,
             "comment": "Оприходование товара на оптовый склад (тонны)"},
            {"dt": "41.02", "kt": "60.01", "formula": None,
             "comment": "Оприходование товара на розничный склад (литры) — если ТТН на АЗС"},
            {"dt": "10.09", "kt": "60.01", "formula": None,
             "comment": "Инвентарь/тара/услуги (опционально)"},
            {"dt": "19.03", "kt": "60.01", "formula": None,
             "comment": "Входящий НДС"},
        ],
        "notes": "Зависит от вида товара и склада. См. memory project_srez1.",
    },
    # ПТУ без operation_type — общий fallback
    {
        "doc_type": "ПТУ",
        "operation_type": None,
        "name": "Поступление товаров и услуг (общий)",
        "expected": [
            {"dt": "41.01", "kt": "60.01", "formula": None, "comment": "Товары"},
            {"dt": "19.03", "kt": "60.01", "formula": None, "comment": "Входящий НДС"},
        ],
        "notes": "Fallback для ПТУ без указанного ВидОперации.",
    },
    # ОПЗС — выпуск продукции (общепит)
    {
        "doc_type": "ОПЗС",
        "operation_type": "ОтчетПроизводстваЗаСмену",
        "name": "Выпуск продукции общепита",
        "expected": [
            {"dt": "41.02", "kt": "44.01", "formula": None,
             "comment": "Оприходование готовой продукции (11 Продукция)"},
            {"dt": "44.01", "kt": "41.02", "formula": None,
             "comment": "Списание материалов (51 Материалы)"},
        ],
        "notes": "Срез 3 — production_release. См. project_srez3_implemented.",
    },
    # КорректировкаПоступления — возврат поставщику
    {
        "doc_type": "КорректировкаПоступления",
        "operation_type": "СогласованноеИзменение",
        "name": "Возврат поставщику (корректировка)",
        "expected": [
            {"dt": "60.01", "kt": "41.02", "formula": None,
             "comment": "Возврат товара поставщику"},
            {"dt": "60.01", "kt": "19.03", "formula": None,
             "comment": "Сторно входящего НДС"},
        ],
        "notes": "Срез 4 — return_purchase. См. project_srez4_implemented.",
    },
]


async def _seed_posting_templates(db: AsyncSession) -> None:
    """Идемпотентно: вставляет глобальные шаблоны, если по (doc_type,
    operation_type, company_id=NULL) ещё нет записи."""
    import uuid
    existing = await db.execute(
        select(PostingTemplate).where(PostingTemplate.company_id.is_(None))
    )
    existing_keys = {
        (t.doc_type, t.operation_type) for t in existing.scalars().all()
    }
    for tpl in POSTING_TEMPLATES_GLOBAL:
        key = (tpl["doc_type"], tpl["operation_type"])
        if key in existing_keys:
            continue
        db.add(PostingTemplate(
            id=uuid.uuid4(),
            company_id=None,
            doc_type=tpl["doc_type"],
            operation_type=tpl["operation_type"],
            name=tpl["name"],
            expected=tpl["expected"],
            notes=tpl.get("notes"),
        ))
        logger.info("Создан шаблон проводок: %s/%s", tpl["doc_type"], tpl["operation_type"] or "—")
