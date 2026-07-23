"""
Начальные данные: 5 компаний + демо-пользователь.
Запускается при старте приложения (идемпотентно).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.config import get_settings
from app.fuel_mapping_defaults import (
    GIG_FUEL_MAPPINGS,
    GIG_PAYMENT_CHANNELS,
    GIG_PAYMENT_MAPPINGS,
)
from app.location_type_defaults import BUILTIN_LOCATION_TYPES
from app.models import (
    Channel,
    ChannelStream,
    Company,
    FuelMapping,
    LocationTypeDef,
    PaymentChannel,
    PaymentMapping,
    PostingTemplate,
    Source,
    SourceCredentials,
    ServiceLocation,
    User,
    UserCompany,
)

logger = logging.getLogger("clearledger.seed")

GIG_MSTO_STATION_IDS = {
    "1": 212,
    "2": 238,
    "3": 245,
    "4": 251,
    "5": 253,
    "6": 268,
}

# Компании — данные совпадают с config/companies.ts (defaultCompanies).
# Активные направления GIG Ledger: gig (ООО ГИГ / ГазИнвестГрупп) и rushydro.
# Legacy-компании (НПК, РТИ, ТС-94, ОФ ПТК) удалены 2026-06-27 — больше не
# сидятся, чтобы не воскресать при рестарте после ручной чистки в БД.
COMPANIES = [
    {"slug": "gig", "name": "ООО ГИГ (ГазИнвестГрупп)", "short_name": "ГИГ", "profile_id": "fuel", "color": "#3b82f6", "inn": "7839124578"},
    {"slug": "rushydro", "name": "РусГидро", "short_name": "РусГидро", "profile_id": "energy", "color": "#ef4444"},
]


def companies_to_seed() -> list[dict]:
    """Какие компании заводить в этой БД.

    Без `ECOSYSTEM_COMPANIES` — встроенный каталог (мультитенант-прод как был).
    С переменной — только перечисленные: у изолированного стека компании своей
    экосистемы, чужих он не видит (ecosystem-deploy/docs/CORE.md §1). Slug из
    каталога подтягивает готовые реквизиты, незнакомый — описывается полями."""
    raw = get_settings().ecosystem_companies.strip()
    if not raw:
        return COMPANIES

    catalog = {c["slug"]: c for c in COMPANIES}
    out: list[dict] = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split("|")]
        slug = parts[0]
        if len(parts) == 1:
            known = catalog.get(slug)
            if known is None:
                logger.warning(
                    "ECOSYSTEM_COMPANIES: '%s' нет во встроенном каталоге — "
                    "создаётся с именем по slug; задай поля через '|'", slug,
                )
            out.append(known or {"slug": slug, "name": slug, "short_name": slug})
            continue
        comp = {"slug": slug, "name": parts[1] or slug}
        if len(parts) > 2 and parts[2]:
            comp["short_name"] = parts[2]
        if len(parts) > 3 and parts[3]:
            comp["profile_id"] = parts[3]
        if len(parts) > 4 and parts[4]:
            comp["color"] = parts[4]
        if len(parts) > 5 and parts[5]:
            comp["inn"] = parts[5]
        out.append(comp)
    return out


async def seed_data(db: AsyncSession) -> None:
    """Создаёт начальные компании и (опционально) суперадмина."""

    # --- Компании ---
    existing = await db.execute(select(Company))
    existing_slugs = {c.slug for c in existing.scalars().all()}

    created_companies: list[Company] = []
    for comp in companies_to_seed():
        if comp["slug"] not in existing_slugs:
            company = Company(**comp)
            db.add(company)
            created_companies.append(company)
            logger.info("Создана компания: %s (%s)", comp["name"], comp["slug"])

    if created_companies:
        await db.flush()  # получить ID

    # --- Суперадмин ---
    await _seed_superadmin(db)

    # --- Шаблоны проводок (глобальные, company_id=NULL) ---
    await _seed_posting_templates(db)

    # --- Встроенные типы точек (company_id=NULL) ---
    await _seed_builtin_location_types(db)

    # --- Маппинги топливных каналов STS → 1С (компания ГИГ) ---
    await _seed_gig_fuel_mappings(db)

    # --- Источник онлайн-заказов MSTO (только источник, без канала) ---
    await _seed_gig_msto_source(db)

    # --- Источник STS-транзакций (отдельный, для разрезов сверки) ---
    await _seed_gig_sts_transactions_source(db)

    # --- Достройка предустановленных разрезов учёта каналов (из шаблонов) ---
    await _backfill_channel_cuts(db)

    # --- Системные роли доступа (RBAC) для всех компаний ---
    await _seed_system_roles(db)

    await db.commit()
    logger.info("Seed завершён")


async def _seed_system_roles(db: AsyncSession) -> None:
    """Идемпотентно создаёт системные роли доступа в каждой компании."""
    from app.access_catalog import SYSTEM_ROLES
    from app.models import CompanyRole

    companies = (await db.execute(select(Company.id))).scalars().all()
    for cid in companies:
        existing = (await db.execute(
            select(CompanyRole.name).where(
                CompanyRole.company_id == cid, CompanyRole.is_system.is_(True)
            )
        )).scalars().all()
        have = set(existing)
        for role in SYSTEM_ROLES:
            if role["name"] not in have:
                db.add(CompanyRole(
                    company_id=cid, name=role["name"],
                    modules=role["modules"], is_system=True,
                ))


async def _seed_gig_msto_source(db: AsyncSession) -> None:
    """Источник «MSTO Онлайн-заказы» (source_type=msto) для ГИГ — ВНЕШНИЙ источник
    для сверки онлайн-канала смены. Отдельного канала у онлайн-заказов НЕТ: разрез
    online_orders «Сменного отчёта» подключается к этому источнику. Креды MSTO — в
    settings (MSTO_API_URL/USERNAME/PASSWORD), как у TradeFrame.
    Если ранее был заведён отдельный канал msto_online — удаляем (legacy)."""
    gig = (
        await db.execute(select(Company).where(Company.slug == "gig"))
    ).scalar_one_or_none()
    if gig is None:
        return

    # Источник MSTO — ключ (company_id, source_type=msto)
    src = (
        await db.execute(
            select(Source).where(
                Source.company_id == gig.id, Source.source_type == "msto"
            )
        )
    ).scalars().first()
    if src is None:
        db.add(Source(
            company_id=gig.id,
            source_type="msto",
            name="MSTO Онлайн-заказы",
            description="Заказы агрегаторов (Я.Заправки/Benzuber/FuelUp) через MSTO IntegratorService",
            status="active",
            connection_config={"base_url": "http://46.229.214.21:3000", "login": "tf-integration"},
        ))
        logger.info("ГИГ: источник «MSTO Онлайн-заказы»")

    # Внешние коды перенесены из рабочего монитора TradeFrame. Храним их в
    # паспорте точки, чтобы выбор АЗС всегда ограничивал запрос MSTO по ID.
    locations = (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.company_id == gig.id,
            ServiceLocation.code.in_(GIG_MSTO_STATION_IDS),
        )
    )).scalars().all()
    for location in locations:
        msto_id = GIG_MSTO_STATION_IDS[location.code]
        metadata = dict(location.extra_metadata or {})
        if metadata.get("mstoServicePointId") != msto_id:
            metadata["mstoServicePointId"] = msto_id
            location.extra_metadata = metadata

    # Legacy: онлайн-заказы — это ИСТОЧНИК, а не канал. Удаляем отдельный канал,
    # если он был заведён ранее (потоки удалятся каскадом).
    for ch in (await db.execute(
        select(Channel).where(
            Channel.company_id == gig.id, Channel.template_id == "msto_online"
        )
    )).scalars().all():
        await db.delete(ch)
        logger.info("ГИГ: удалён legacy-канал «Онлайн-заказы (MSTO)»")


async def _seed_gig_sts_transactions_source(db: AsyncSession) -> None:
    """Источник «STS Транзакции» (source_type=sts_transactions) для ГИГ — отдельный,
    переиспользуемый разрезами сверки НЕЗАВИСИМО от канала смен (онлайн/корп-карты/
    эквайринг сверяются с этими транзакциями). Подключение переиспользует основной
    STS-источник, если он заведён."""
    gig = (
        await db.execute(select(Company).where(Company.slug == "gig"))
    ).scalar_one_or_none()
    if gig is None:
        return
    sts = (await db.execute(select(Source).where(
        Source.company_id == gig.id, Source.source_type == "sts"
    ))).scalars().first()
    cfg = dict(sts.connection_config) if sts and sts.connection_config else {
        "base_url": "https://pos.autooplata.ru/tms", "default_system_ids": "65,15",
    }
    # Переиспользуем РАБОЧЕЕ подключение основного STS (вкл. зашифрованный пароль —
    # тот же Fernet-ключ): транзакции тянутся из той же STS-системы.
    sts_cr = None
    if sts is not None:
        sts_cr = (await db.execute(select(SourceCredentials).where(
            SourceCredentials.source_id == sts.id
        ))).scalars().first()
    has_sts_creds = bool(sts_cr and sts_cr.encrypted_values)
    connected = sts is not None and sts.status == "connected" and has_sts_creds

    src = (await db.execute(select(Source).where(
        Source.company_id == gig.id, Source.source_type == "sts_transactions"
    ))).scalars().first()
    if src is None:
        src = Source(
            company_id=gig.id, source_type="sts_transactions",
            name="STS Транзакции (отпуск)",
            description="Пооперационные транзакции отпуска (STS /v2/transactions) — зерно сверки разрезов. Независимый источник.",
            status="connected" if connected else "draft",
            connection_config=cfg,
        )
        db.add(src)
        await db.flush()
        logger.info("ГИГ: источник «STS Транзакции» создан (%s)", src.status)

    # Докопировать креды/подключение с основного STS, если у источника их ещё нет.
    own_cr = (await db.execute(select(SourceCredentials).where(
        SourceCredentials.source_id == src.id
    ))).scalars().first()
    if has_sts_creds and not (own_cr and own_cr.encrypted_values):
        db.add(SourceCredentials(
            source_id=src.id,
            encrypted_values=dict(sts_cr.encrypted_values),
            cipher_version=sts_cr.cipher_version,
        ))
        if not src.connection_config:
            src.connection_config = cfg
        if connected and src.status != "connected":
            src.status = "connected"
        logger.info("ГИГ: «STS Транзакции» — креды скопированы с STS (%s)", src.status)


async def _backfill_channel_cuts(db: AsyncSession) -> None:
    """Достраивает каналам предустановленные разрезы учёта из шаблона: проставляет
    роль существующим потокам и ДОБАВЛЯЕТ недостающие (источник может быть не
    подключён — source_id=NULL, enabled=False). Канал несёт весь свой набор разрезов."""
    from app.channel_catalog import get_channel_template

    channels = (
        await db.execute(select(Channel).where(Channel.template_id.isnot(None)))
    ).scalars().all()
    for ch in channels:
        tpl = get_channel_template(ch.template_id or "")
        if tpl is None:
            continue
        streams = (
            await db.execute(select(ChannelStream).where(ChannelStream.channel_id == ch.id))
        ).scalars().all()
        by_doc = {s.doc_type_id: s for s in streams}
        for decl in tpl.streams:
            existing = by_doc.get(decl.doc_type)
            if existing is not None:
                if existing.role != decl.role:
                    existing.role = decl.role
                continue
            ids = (await db.execute(select(Source.id).where(
                Source.company_id == ch.company_id,
                Source.source_type == decl.source_type,
            ))).scalars().all()
            src_id = ids[0] if len(ids) == 1 else None
            db.add(ChannelStream(
                channel_id=ch.id, source_id=src_id,
                doc_type_id=decl.doc_type, name=decl.label, role=decl.role,
                enabled=src_id is not None,
            ))
            logger.info("Канал %s: + разрез %s (%s, %s)", ch.name, decl.doc_type,
                        decl.role, "подключён" if src_id else "не подключён")


async def _seed_gig_fuel_mappings(db: AsyncSession) -> None:
    """Идемпотентно заполняет каналы оплаты, маппинг оплат и маппинг топлива
    для компании ГИГ из эталона расширения TradeLedger.cfe.

    Не перетирает существующие записи (ручные правки сохраняются) — добавляет
    только отсутствующие по натуральному ключу."""
    gig = (
        await db.execute(select(Company).where(Company.slug == "gig"))
    ).scalar_one_or_none()
    if gig is None:
        return

    # PaymentChannel — ключ (company_id, code)
    existing_codes = {
        c.code for c in (
            await db.execute(
                select(PaymentChannel).where(PaymentChannel.company_id == gig.id)
            )
        ).scalars().all()
    }
    for i, ch in enumerate(GIG_PAYMENT_CHANNELS):
        if ch["code"] in existing_codes:
            continue
        db.add(PaymentChannel(company_id=gig.id, sort_order=i, **ch))
        logger.info("ГИГ: канал оплаты %s", ch["code"])

    # PaymentMapping — ключ (company_id, pattern)
    existing_patterns = {
        m.pattern for m in (
            await db.execute(
                select(PaymentMapping).where(PaymentMapping.company_id == gig.id)
            )
        ).scalars().all()
    }
    for i, mp in enumerate(GIG_PAYMENT_MAPPINGS):
        if mp["pattern"] in existing_patterns:
            continue
        db.add(PaymentMapping(company_id=gig.id, sort_order=i, **mp))

    # FuelMapping — ключ (company_id, service_code)
    existing_codes_f = {
        f.service_code for f in (
            await db.execute(
                select(FuelMapping).where(FuelMapping.company_id == gig.id)
            )
        ).scalars().all()
    }
    for fm in GIG_FUEL_MAPPINGS:
        if fm["service_code"] in existing_codes_f:
            continue
        db.add(FuelMapping(company_id=gig.id, sort_order=fm["service_code"], **fm))


async def _seed_superadmin(db: AsyncSession) -> None:
    """Создаёт суперадмина ТОЛЬКО при заданных SEED_SUPERADMIN_EMAIL +
    SEED_SUPERADMIN_PASSWORD. Без них на старте суперадмин не создаётся —
    раньше тут хардкодился admin@clearledger.ru/admin123 (постоянный бэкдор)
    и любой пользователь с этим email втихую повышался до суперадмина.

    Идемпотентно: существующему пользователю пароль НЕ перезаписываем; только
    проставляем флаг is_superadmin (для чистой тестовой БД без DDL-миграции).
    Авто-повышения чужого аккаунта больше нет — повышаем лишь свой сид-email."""
    settings = get_settings()
    email = settings.seed_superadmin_email.strip().lower()
    password = settings.seed_superadmin_password
    if not email or not password:
        logger.info("Сид суперадмина отключён (SEED_SUPERADMIN_* не заданы)")
        return

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.is_superadmin:
            existing.is_superadmin = True
            logger.info("Сид-суперадмин %s: проставлен флаг is_superadmin", email)
        return

    # Компания по умолчанию — ПЕРВАЯ компания этой экосистемы (членство суперадмину
    # не обязательно). Раньше здесь был жёсткий 'gig' — в стеке другой компании это
    # сажало владельца в чужую компанию.
    default_slug = companies_to_seed()[0]["slug"]
    company = (
        await db.execute(select(Company).where(Company.slug == default_slug))
    ).scalar_one_or_none()
    user = User(
        email=email,
        password_hash=hash_password(password),
        name="Администратор",
        role="admin",
        company_id=company.id if company else None,
        is_superadmin=True,
    )
    db.add(user)
    await db.flush()
    if company:
        db.add(UserCompany(user_id=user.id, company_id=company.id))
    logger.info("Создан сид-суперадмин: %s", email)


async def _seed_builtin_location_types(db: AsyncSession) -> None:
    """Встроенные типы точек (company_id=NULL, is_builtin) — UPSERT из кода.
    Дублирует миграцию v2.4 (database.py) для пути ORM create_all (тесты)."""
    res = await db.execute(
        select(LocationTypeDef).where(LocationTypeDef.company_id.is_(None))
    )
    existing = {t.code: t for t in res.scalars().all()}
    for t in BUILTIN_LOCATION_TYPES:
        cur = existing.get(t["code"])
        if cur is None:
            db.add(LocationTypeDef(
                company_id=None, code=t["code"], name=t["name"], icon=t["icon"],
                unit=t["unit"], nomenclature_kind=t["nomenclature_kind"],
                fields=t["fields"], is_builtin=True, sort_order=t["sort_order"],
            ))
        else:
            cur.name = t["name"]; cur.icon = t["icon"]; cur.unit = t["unit"]
            cur.nomenclature_kind = t["nomenclature_kind"]
            cur.fields = t["fields"]; cur.sort_order = t["sort_order"]


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
