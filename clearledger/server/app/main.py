"""
Точка входа TradeLedger Server.
FastAPI приложение с CORS, роутерами, startup seed.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
import uuid

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import (
    async_session_factory,
    create_all,
    database_startup_lock,
    get_db,
)
from app.routers import (
    accounting_adjustments_router,
    accounting_docs_router,
    audit_data_router,
    audit_router,
    auditor_router,
    auth_router,
    books_router,
    intake_docs_router,
    mail_router,
    dedup_ingest_router,
    eco_events_router,
    edge_router,
    companies_router,
    connectors_router,
    roles_router,
    document_links_router,
    entries_router,
    export_router,
    fuel_router,
    fuel_mappings_router,
    online_orders_router,
    online_reconciliation_router,
    invitations_router,
    export_packets_router,
    inbound_keys_router,
    intake_router,
    mappings_router,
    meetings_router,
    chat_router,
    ocr_router,
    analytics_router,
    charge_sessions_router,
    corporate_router,
    departments_router,
    retail_router,
    tariff_router,
    asuim_router,
    overview_router,
    store_router,
    store_documents_router,
    business_access_router,
    station_console_router,
    onec_router,
    equipment_router,
    sites_router,
    info_router,
    sso_router,
    app_registry_router,
    space_events_router,
    space_registry_router,
    core_router,
    matrix_chat_router,
    ops_router,
    periods_router,
    policy_router,
    reconciliation_router,
    reconciliation_proxy_router,
    channel_templates_router,
    channels_router,
    reconcile_router,
    reconcile_rules_router,
    locations_router,
    location_types_router,
    market_router,
    metrika_router,
    netservice_router,
    notifications_router,
    references_router,
    reports_router,
    settings_router,
    source_types_router,
    perimeter_router,
    pulse_router,
    doc_share_router,
    partner_router,
    docs_archive_router,
    docs_router,
    work_router,
    tasks_router,
    tickets_router,
    users_router,
    sources_router,
    stats_router,
)
from app.seed import seed_data

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("clearledger")

settings = get_settings()


async def _prepare_database(started_before: datetime) -> None:
    await create_all()
    logger.info("Таблицы БД созданы/проверены")

    async with async_session_factory() as session:
        await seed_data(session)

    async with async_session_factory() as session:
        try:
            from app.services.tz_offsets import backfill_region_offsets
            n = await backfill_region_offsets(session)
            logger.info(f"Часовые пояса регионов проставлены: {n}")
        except Exception as e:  # noqa: BLE001 — не валим старт из-за НСИ
            logger.warning(f"backfill region offsets пропущен: {e}")

    async with async_session_factory() as session:
        try:
            from app.routers.perimeter_router import ensure_perimeter_schema
            await ensure_perimeter_schema(session)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"схема периметра не дотянута: {e}")

    async with async_session_factory() as session:
        try:
            from app.services.app_registry import seed_apps
            await seed_apps(session)
            logger.info("Каталог приложений экосистемы засеян")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"seed_apps пропущен: {e}")

    async with async_session_factory() as session:
        try:
            from app.services.info_seed import seed_info
            res = await seed_info(session)
            await session.commit()
            logger.info(f"Знание отрасли засеяно: {res}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"seed_info пропущен: {e}")

    async with async_session_factory() as session:
        await session.execute(text(
            "UPDATE channel_sync_logs SET status='error', finished_at=now(), "
            "events='[{\"level\":\"error\",\"event\":\"run\",\"message\":"
            "\"прогон прерван перезапуском сервера\"}]'::jsonb "
            "WHERE status='running' AND started_at < :started_before"
        ), {"started_before": started_before})
        await session.commit()


async def _prepare_database_once(started_before: datetime) -> None:
    """Выполнить DDL/seed один раз на контейнер, а не по разу на worker."""
    instance_id = os.getenv("HOSTNAME", "").strip() if settings.app_env == "prod" else ""
    if not instance_id:
        await _prepare_database(started_before)
        return

    async with async_session_factory() as session:
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS app_startup_runs ("
            " instance_id text PRIMARY KEY, completed_at timestamptz NOT NULL DEFAULT now())"
        ))
        completed = await session.scalar(text(
            "SELECT 1 FROM app_startup_runs WHERE instance_id = :instance_id"
        ), {"instance_id": instance_id})
        await session.commit()
    if completed:
        logger.info("Подготовка БД уже выполнена другим worker этого контейнера")
        return

    await _prepare_database(started_before)
    async with async_session_factory() as session:
        await session.execute(text(
            "INSERT INTO app_startup_runs (instance_id) VALUES (:instance_id) "
            "ON CONFLICT (instance_id) DO NOTHING"
        ), {"instance_id": instance_id})
        await session.execute(text(
            "DELETE FROM app_startup_runs WHERE completed_at < now() - interval '30 days'"
        ))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: создание таблиц + seed данных."""
    logger.info("Запуск TradeLedger Server...")
    started_at = datetime.now(timezone.utc)

    # Скоуп данных по объектам — автоматическое сужение ORM-запросов участника
    # (app/scope.py). Ставится один раз на класс сессии: иначе фильтр приходится
    # помнить в каждой ручке, и он забывается в тех, где нет фильтра станций.
    from app.scope import install_orm_scope
    install_orm_scope()

    # Безопасность: секрет JWT не должен оставаться дефолтным на проде —
    # иначе токены подделываются публично известным ключом.
    if settings.secret_is_insecure:
        logger.critical(
            "SECRET_KEY не задан — используется небезопасный дефолт! "
            "JWT можно подделать. Задайте SECRET_KEY (или JWT_SECRET) в окружении."
        )

    # Gunicorn запускает два процесса. Без общего лока оба одновременно меняют
    # схему и делают check-then-insert seed, что даёт гонки на DDL и unique.
    async with database_startup_lock():
        await _prepare_database_once(started_at)

    from app.services.chat_ws import manager as chat_ws_manager
    await chat_ws_manager.start(settings.database_url)

    # Планировщик каналов приёма: исполняет Channel.schedule (ночные автозапуски).
    # Без него расписание в UI — просто запись в JSON, а данные ждут ручной кнопки.
    scheduler_task: asyncio.Task | None = None
    try:
        from app.services.channel_scheduler import run_forever as _sched
        scheduler_task = asyncio.create_task(_sched())
    except Exception as e:  # noqa: BLE001 — планировщик не критичен для API
        logger.warning(f"Планировщик каналов не запущен: {e}")

    # Утренний дайджест «Пульса»: эскалации идут к человеку, а не ждут, пока он
    # откроет экран. Своё расписание и свой лок — падение одного воркера не
    # трогает другой.
    digest_task: asyncio.Task | None = None
    try:
        from app.services.pulse_digest import run_forever as _digest
        digest_task = asyncio.create_task(_digest())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Дайджест «Пульса» не запущен: {e}")

    # Регламент «Задач»: повторяющиеся работы, напоминания о сроке и эскалация.
    # Без него расписание в карточке — тоже просто запись в JSON, а «нет отклика»
    # обнаруживается уже после провала срока.
    tasks_task: asyncio.Task | None = None
    try:
        from app.services.task_scheduler import run_forever as _tasks_regl
        tasks_task = asyncio.create_task(_tasks_regl())
    except Exception as e:  # noqa: BLE001 — регламент не критичен для API
        logger.warning(f"Регламент задач не запущен: {e}")

    # Почта: регулярный опрос ящиков по их интервалу. Без него коннектор — кнопка,
    # а письма контрагентов ждут, пока кто-нибудь про них вспомнит.
    mail_task: asyncio.Task | None = None
    try:
        from app.services.mail_poller import run_forever as _mail_poll
        mail_task = asyncio.create_task(_mail_poll())
    except Exception as e:  # noqa: BLE001 — почта не критична для API
        logger.warning(f"Опрос почты не запущен: {e}")

    logger.info("TradeLedger Server запущен")
    yield
    if mail_task is not None:
        mail_task.cancel()
    if tasks_task is not None:
        tasks_task.cancel()
    if digest_task is not None:
        digest_task.cancel()
    if scheduler_task is not None:
        scheduler_task.cancel()
    await chat_ws_manager.stop()
    logger.info("TradeLedger Server остановлен")


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

# Единая версия приложения — синхронизирована с src/config/version.ts и package.json
APP_VERSION = "1.2.1"

app = FastAPI(
    title="TradeLedger API",
    description="Бэкенд системы приёма, классификации и верификации документов",
    version=APP_VERSION,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def rate_limit_public(request, call_next):
    """Ограничение частоты на публичных ручках — до всякой работы с базой.

    Стоит перед остальными обработчиками намеренно: смысл лимита в том, чтобы
    перебор не доходил до проверки пароля и до выборки по токену."""
    from app.rate_limit import check

    blocked, event = check(request)
    if blocked is not None:
        if event is not None:
            await _log_security_event(event)
        return blocked
    return await call_next(request)


async def _log_security_event(event: dict) -> None:
    """Записать отбитый перебор. Своя сессия и подавленная ошибка: журнал не
    должен уметь уронить ответ, ради которого он ведётся."""
    from app.database import async_session_factory
    from app.models import SecurityEvent

    try:
        async with async_session_factory() as db:
            db.add(SecurityEvent(**event))
            await db.commit()
    except Exception:  # noqa: BLE001 — запись в журнал не отменяет отказ
        logging.getLogger("clearledger.security").warning(
            "Отбитая попытка не записана: %s", event, exc_info=True)


@app.middleware("http")
async def organization_context(request, call_next):
    """Активная организация запроса — из заголовка `X-Organization-Id`.

    Организация относится к ДАННЫМ, а не к правам: компания решает, к чьему учёту
    есть доступ, организация — на какое юрлицо этого учёта человек сейчас смотрит.
    Заголовок, а не параметр каждой ручки: разрез нужен десяткам выборок, и
    протаскивать его руками — однажды забыть в одной и смешать два налогоплательщика.

    Пустой заголовок означает «все организации компании» — законный сводный режим.
    """
    from app.scope import set_request_organization

    raw = request.headers.get("X-Organization-Id") or ""
    org = None
    if raw.strip():
        try:
            org = uuid.UUID(raw.strip())
        except ValueError:
            org = None      # мусор в заголовке — это «все», а не ошибка запроса
    set_request_organization(org)
    return await call_next(request)


# Роутеры — все под /api
API_PREFIX = "/api"

app.include_router(auth_router.router, prefix=API_PREFIX)
# Рабочее место станции: прокси к вебу агента через хаб TradeLink.
app.include_router(station_console_router.router, prefix=API_PREFIX)
app.include_router(tickets_router.router, prefix=API_PREFIX)
app.include_router(tasks_router.router, prefix=API_PREFIX)  # «Задачи»: свой движок с маршрутами
app.include_router(docs_archive_router.router, prefix=API_PREFIX)
app.include_router(docs_router.router, prefix=API_PREFIX)  # «Трек»: документооборот и работа
app.include_router(work_router.router, prefix=API_PREFIX)  # единый список работы
# Показ документа контрагенту по ссылке: без авторизации, намеренно скупо.
app.include_router(doc_share_router.router, prefix=API_PREFIX)
app.include_router(pulse_router.router, prefix=API_PREFIX)
# Витрина по ссылке: без авторизации, доступ по токену самой ссылки.
app.include_router(pulse_router.public_router, prefix=API_PREFIX)
app.include_router(perimeter_router.router, prefix=API_PREFIX)  # «Периметр»: три слоя вне баланса
app.include_router(departments_router.router, prefix=API_PREFIX)
app.include_router(users_router.router, prefix=API_PREFIX)
app.include_router(roles_router.router, prefix=API_PREFIX)
app.include_router(invitations_router.router, prefix=API_PREFIX)
app.include_router(companies_router.router, prefix=API_PREFIX)
app.include_router(entries_router.router, prefix=API_PREFIX)
app.include_router(audit_router.router, prefix=API_PREFIX)
app.include_router(inbound_keys_router.router, prefix=API_PREFIX)
# connectors_router НЕ подключаем: рудимент третьей модели «подключений» рядом с
# Source и Channel (poll отвечал 501, витрина пространства его не видела). Единая
# модель — docs/CONNECT.md; файл остаётся до переноса полезных типов в В2.
# app.include_router(connectors_router.router, prefix=API_PREFIX)
app.include_router(document_links_router.router, prefix=API_PREFIX)
app.include_router(export_router.router, prefix=API_PREFIX)
app.include_router(reports_router.router, prefix=API_PREFIX)
app.include_router(stats_router.router, prefix=API_PREFIX)
app.include_router(settings_router.router, prefix=API_PREFIX)
app.include_router(intake_router.router, prefix=API_PREFIX)
app.include_router(references_router.router, prefix=API_PREFIX)
app.include_router(accounting_docs_router.router, prefix=API_PREFIX)
app.include_router(accounting_adjustments_router.router, prefix=API_PREFIX)
app.include_router(reconciliation_router.router, prefix=API_PREFIX)
app.include_router(reconciliation_proxy_router.router, prefix=API_PREFIX)  # прокси «Сверки»: /api/tradecorp/*, /api/msto/*
app.include_router(audit_data_router.router, prefix=API_PREFIX)
# Аудитор пространства: настройки агента и след его работы
# (сам агент — сервис стека, ecosystem-deploy/services/auditor).
app.include_router(auditor_router.router, prefix=API_PREFIX)
app.include_router(partner_router.router, prefix=API_PREFIX)  # партнёр согласует документ по именному ключу
app.include_router(dedup_ingest_router.router, prefix=API_PREFIX)  # приём среза дублей 208 по X-Cloud-API-Key
app.include_router(edge_router.router, prefix=API_PREFIX)  # приём пакетов edge-агентов АЗС по X-Cloud-API-Key
app.include_router(eco_events_router.router, prefix=API_PREFIX)  # обратный канал приложений
app.include_router(space_events_router.router, prefix=API_PREFIX)  # подписки на исходящие события и очередь
app.include_router(ocr_router.router, prefix=API_PREFIX)
app.include_router(fuel_router.router, prefix=API_PREFIX)
app.include_router(fuel_mappings_router.router, prefix=API_PREFIX)
app.include_router(online_orders_router.router, prefix=API_PREFIX)
app.include_router(online_reconciliation_router.router, prefix=API_PREFIX)
app.include_router(ops_router.router, prefix=API_PREFIX)  # управленческий кокпит ЭЗС
app.include_router(equipment_router.router, prefix=API_PREFIX)  # складской учёт оборудования ЭЗС
app.include_router(sites_router.router, prefix=API_PREFIX)  # банк ЗУ: площадки под установку ЭЗС
app.include_router(info_router.router, prefix=API_PREFIX)   # «Инфо»: знание пространства
app.include_router(sso_router.router, prefix=API_PREFIX)  # SSO ElsyPlus (Фаза 0): лаунчер + handoff + JWKS
app.include_router(app_registry_router.router, prefix=API_PREFIX)  # ElsyPlus Core: реестр приложений/модулей
app.include_router(space_registry_router.router, prefix=API_PREFIX)  # ElsyPlus Core: реестр объектов пространства
app.include_router(core_router.router, prefix=API_PREFIX)  # ElsyPlus Core: состояние Ядра (Центр управления)
app.include_router(matrix_chat_router.router, prefix=API_PREFIX)  # Чат экосистемы на Matrix (модель Ангара)
app.include_router(source_types_router.router, prefix=API_PREFIX)
app.include_router(sources_router.router, prefix=API_PREFIX)
app.include_router(locations_router.router, prefix=API_PREFIX)
app.include_router(location_types_router.router, prefix=API_PREFIX)
app.include_router(channel_templates_router.router, prefix=API_PREFIX)
app.include_router(channels_router.router, prefix=API_PREFIX)
app.include_router(reconcile_router.router, prefix=API_PREFIX)
app.include_router(reconcile_rules_router.router, prefix=API_PREFIX)
app.include_router(onec_router.router, prefix=API_PREFIX)
app.include_router(periods_router.router, prefix=API_PREFIX)
app.include_router(mappings_router.router, prefix=API_PREFIX)
app.include_router(export_packets_router.router, prefix=API_PREFIX)
app.include_router(policy_router.router, prefix=API_PREFIX)
app.include_router(analytics_router.router, prefix=API_PREFIX)
app.include_router(charge_sessions_router.router, prefix=API_PREFIX)
app.include_router(corporate_router.router, prefix=API_PREFIX)
app.include_router(retail_router.router, prefix=API_PREFIX)
app.include_router(tariff_router.router, prefix=API_PREFIX)
app.include_router(asuim_router.router, prefix=API_PREFIX)
app.include_router(overview_router.router, prefix=API_PREFIX)
# Роутеры с префиксом /store подключаются ДО store_router.
#
# У него на хвосте стоит catch-all `/{report}` с обязательными date_from и
# date_to, и он перехватывает всё, что зарегистрировано после него: запрос
# `/api/store/access-policy` уходил в него и отвечал 422 «нет дат». Наружу это
# выглядело как отказ прав — политика доступа не приезжала, и кнопка «Работать»
# на рабочем месте АЗС гасла у человека, у которого назначение на станцию есть.
app.include_router(business_access_router.router, prefix=API_PREFIX)
app.include_router(store_documents_router.router, prefix=API_PREFIX)
app.include_router(store_router.router, prefix=API_PREFIX)
app.include_router(netservice_router.router, prefix=API_PREFIX)
app.include_router(meetings_router.router, prefix=API_PREFIX)
app.include_router(chat_router.router, prefix=API_PREFIX)
app.include_router(notifications_router.router, prefix=API_PREFIX)  # Оповещения пространства
app.include_router(metrika_router.router, prefix=API_PREFIX)
# Рынок вокруг сети (продукт «Маркетинг», docs/MARKET.md): чужие точки и наблюдения.
app.include_router(market_router.router, prefix=API_PREFIX)
# Бухгалтерия офисного пространства и её разрезы («Продажи», «Услуги»): эталон
# закрытого периода, из которого растут остальные приложения такой компании.
app.include_router(books_router.router, prefix=API_PREFIX)
app.include_router(intake_docs_router.router, prefix=API_PREFIX)
app.include_router(mail_router.router, prefix=API_PREFIX)


@app.get("/api/health")
async def health_check():
    """Liveness: процесс отвечает; зависимости проверяет /api/ready."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        "service": "TradeLedger API",
    }


@app.get("/api/live")
async def live_check():
    return await health_check()


@app.get("/api/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness: рабочая БД, обязательная схема и доступное хранилище файлов."""
    try:
        schema_ready = await db.scalar(text("""
            SELECT count(*) = 20
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = current_schema()
               AND c.relname IN (
                   'doc_cards',
                   'uq_doc_versions_current_role',
                   'idx_doc_versions_text',
                   'uq_doc_cases_index',
                   'uq_doc_cards_mail_source',
                   'uq_mail_messages_company_msgid',
                   'doc_legal_holds',
                   'doc_retention_decisions',
                   'doc_destruction_acts',
                   'doc_destruction_items',
                   'doc_archive_events',
                   'doc_signature_evidence',
                   'doc_break_glass_accesses',
                   'idx_doc_cards_retention',
                   'idx_doc_versions_destruction_act',
                   'idx_doc_legal_holds_active',
                   'uq_doc_destruction_acts_number',
                   'uq_doc_destruction_items_active_doc',
                   'idx_doc_archive_events_company',
                   'idx_doc_break_glass_active'
               )
        """))
        unique_ready = await db.scalar(text("""
            SELECT count(*) = 6
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
              JOIN pg_index AS i ON i.indexrelid = c.oid
             WHERE n.nspname = current_schema()
               AND c.relname IN (
                   'uq_doc_versions_current_role',
                   'uq_doc_cases_index',
                   'uq_doc_cards_mail_source',
                   'uq_mail_messages_company_msgid',
                   'uq_doc_destruction_acts_number',
                   'uq_doc_destruction_items_active_doc'
               )
               AND i.indisunique
               AND i.indisvalid
        """))
        expression_indexes_ready = await db.scalar(text("""
            SELECT count(*) = 2
              FROM pg_class AS c
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
              JOIN pg_index AS i ON i.indexrelid = c.oid
             WHERE n.nspname = current_schema()
               AND c.relname IN (
                   'uq_doc_cases_index',
                   'uq_doc_destruction_acts_number'
               )
               AND i.indisunique
               AND i.indisvalid
               AND pg_get_indexdef(i.indexrelid) ILIKE '%COALESCE(organization_id%'
        """))
        archive_columns_ready = await db.scalar(text("""
            SELECT count(*) = 16
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND (
                   (table_name = 'doc_cards' AND column_name IN (
                       'inherit_kind_acl', 'acl_revision', 'retention_state',
                       'retention_class', 'retention_snapshot',
                       'retention_extended_until', 'archive_accepted_at',
                       'archive_accepted_by', 'primary_purged_at', 'destroyed_at'
                   ))
                   OR (table_name = 'doc_cases' AND column_name IN (
                       'retention_basis', 'retention_class'
                   ))
                   OR (table_name = 'doc_versions' AND column_name IN (
                       'archive_purged_at', 'purge_result', 'destruction_act_id'
                   ))
                   OR (table_name = 'doc_access_grants'
                       AND column_name = 'denied_permissions')
               )
        """))
        archive_evidence_triggers_ready = await db.scalar(text("""
            SELECT count(*) = 3
                FROM pg_trigger AS t
                JOIN pg_class AS table_ref ON table_ref.oid = t.tgrelid
                JOIN pg_namespace AS n ON n.oid = table_ref.relnamespace
               WHERE n.nspname = current_schema()
                 AND (table_ref.relname, t.tgname) IN (
                     ('doc_archive_events', 'doc_archive_events_immutable_trg'),
                     ('doc_destruction_acts', 'doc_destruction_acts_sealed_trg'),
                     ('doc_destruction_items', 'doc_destruction_items_sealed_trg')
                 )
                 AND NOT t.tgisinternal
        """))
        if (not schema_ready or not unique_ready or not expression_indexes_ready
                or not archive_columns_ready or not archive_evidence_triggers_ready):
            raise RuntimeError("обязательные объекты схемы не созданы")

        from app.services import file_store
        root = file_store.upload_dir().resolve()
        if settings.app_env == "prod" and not os.path.ismount(root):
            raise RuntimeError(f"каталог загрузок не смонтирован: {root}")
        probe = root / f".ready-{uuid.uuid4().hex}"
        try:
            with probe.open("x", encoding="ascii") as handle:
                handle.write("ok")
        finally:
            probe.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("readiness: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="База, схема или файловое хранилище не готовы",
        ) from exc
    return {
        "status": "ready",
        "version": APP_VERSION,
        "service": "TradeLedger API",
        "database": "ok",
        "storage": "ok",
    }


def _git_sha_local() -> str:
    """SHA текущего кода из git (dev). В прод-контейнере .git обычно нет → ''."""
    import subprocess
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parents[2]  # …/clearledger
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 — git недоступен → пусто
        return ""


@app.get("/api/_debug/state")
async def debug_state(current_user=Depends(get_current_user)):
    """«Отпечаток среды»: env, git-SHA, БД и счётчики по компаниям.

    Назначение — мгновенно отличать dev от прода и видеть расхождение данных
    (напр. канал сессий есть в проде, но не в dev). Сравни вывод на dev и на
    проде — расхождение видно сразу, без расследования. Требует авторизации;
    отдаёт только агрегаты (без ПДн)."""
    import re
    from sqlalchemy import func, select
    from app.models import Channel, ChargeSession, Company, DataEntry, FuelShift

    s = get_settings()
    m = re.search(r"@([^/]+)/([^?]+)", s.database_url)  # host:port/dbname без логина/пароля
    db_fp = f"{m.group(1)}/{m.group(2)}" if m else "?"

    async with async_session_factory() as db:
        companies = list((await db.execute(
            select(Company.id, Company.slug, Company.name))).all())

        async def _counts(model) -> dict:
            rows = (await db.execute(
                select(model.company_id, func.count()).group_by(model.company_id))).all()
            return {cid: int(n) for cid, n in rows}

        ch, cs, fs, de = (await _counts(Channel), await _counts(ChargeSession),
                          await _counts(FuelShift), await _counts(DataEntry))

    per = [{
        "slug": slug, "name": name,
        "channels": ch.get(cid, 0),
        "charge_sessions": cs.get(cid, 0),
        "fuel_shifts": fs.get(cid, 0),
        "entries": de.get(cid, 0),
    } for cid, slug, name in companies]

    return {
        "env": s.app_env,
        "git_sha": s.git_sha or _git_sha_local() or "unknown",
        "db": db_fp,
        "version": APP_VERSION,
        "companies": sorted(per, key=lambda x: x["slug"]),
    }
