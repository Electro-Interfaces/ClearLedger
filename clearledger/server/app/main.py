"""
Точка входа TradeLedger Server.
FastAPI приложение с CORS, роутерами, startup seed.
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import get_current_user
from app.config import get_settings
from app.database import async_session_factory, create_all
from app.routers import (
    accounting_docs_router,
    audit_data_router,
    audit_router,
    auth_router,
    companies_router,
    connectors_router,
    roles_router,
    document_links_router,
    entries_router,
    export_router,
    fuel_router,
    fuel_mappings_router,
    online_orders_router,
    invitations_router,
    export_packets_router,
    intake_router,
    mappings_router,
    meetings_router,
    ocr_router,
    analytics_router,
    charge_sessions_router,
    corporate_router,
    retail_router,
    tariff_router,
    overview_router,
    store_router,
    onec_router,
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
    metrika_router,
    netservice_router,
    references_router,
    reports_router,
    settings_router,
    source_types_router,
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: создание таблиц + seed данных."""
    logger.info("Запуск TradeLedger Server...")

    # Безопасность: секрет JWT не должен оставаться дефолтным на проде —
    # иначе токены подделываются публично известным ключом.
    if settings.secret_is_insecure:
        logger.critical(
            "SECRET_KEY не задан — используется небезопасный дефолт! "
            "JWT можно подделать. Задайте SECRET_KEY (или JWT_SECRET) в окружении."
        )

    # Создание таблиц
    await create_all()
    logger.info("Таблицы БД созданы/проверены")

    # Seed начальных данных
    async with async_session_factory() as session:
        await seed_data(session)

    # Сброс зависших прогонов: при рестарте фоновые задачи прерываются, их
    # ChannelSyncLog остаётся в 'running' навсегда — помечаем как прерванные.
    async with async_session_factory() as session:
        from sqlalchemy import text
        await session.execute(text(
            "UPDATE channel_sync_logs SET status='error', finished_at=now(), "
            "events='[{\"level\":\"error\",\"event\":\"run\",\"message\":\"прогон прерван перезапуском сервера\"}]'::jsonb "
            "WHERE status='running'"
        ))
        await session.commit()

    logger.info("TradeLedger Server запущен")
    yield
    logger.info("TradeLedger Server остановлен")


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TradeLedger API",
    description="Бэкенд системы приёма, классификации и верификации документов",
    version="0.5.0",
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

# Роутеры — все под /api
API_PREFIX = "/api"

app.include_router(auth_router.router, prefix=API_PREFIX)
app.include_router(users_router.router, prefix=API_PREFIX)
app.include_router(roles_router.router, prefix=API_PREFIX)
app.include_router(invitations_router.router, prefix=API_PREFIX)
app.include_router(companies_router.router, prefix=API_PREFIX)
app.include_router(entries_router.router, prefix=API_PREFIX)
app.include_router(audit_router.router, prefix=API_PREFIX)
app.include_router(connectors_router.router, prefix=API_PREFIX)
app.include_router(document_links_router.router, prefix=API_PREFIX)
app.include_router(export_router.router, prefix=API_PREFIX)
app.include_router(reports_router.router, prefix=API_PREFIX)
app.include_router(stats_router.router, prefix=API_PREFIX)
app.include_router(settings_router.router, prefix=API_PREFIX)
app.include_router(intake_router.router, prefix=API_PREFIX)
app.include_router(references_router.router, prefix=API_PREFIX)
app.include_router(accounting_docs_router.router, prefix=API_PREFIX)
app.include_router(reconciliation_router.router, prefix=API_PREFIX)
app.include_router(reconciliation_proxy_router.router, prefix=API_PREFIX)  # прокси «Сверки»: /api/tradecorp/*, /api/msto/*
app.include_router(audit_data_router.router, prefix=API_PREFIX)
app.include_router(ocr_router.router, prefix=API_PREFIX)
app.include_router(fuel_router.router, prefix=API_PREFIX)
app.include_router(fuel_mappings_router.router, prefix=API_PREFIX)
app.include_router(online_orders_router.router, prefix=API_PREFIX)
app.include_router(ops_router.router, prefix=API_PREFIX)  # управленческий кокпит ЭЗС
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
app.include_router(overview_router.router, prefix=API_PREFIX)
app.include_router(store_router.router, prefix=API_PREFIX)
app.include_router(netservice_router.router, prefix=API_PREFIX)
app.include_router(meetings_router.router, prefix=API_PREFIX)
app.include_router(metrika_router.router, prefix=API_PREFIX)


@app.get("/api/health")
async def health_check():
    """Проверка работоспособности сервера."""
    return {
        "status": "ok",
        "version": "0.7.0",
        "service": "TradeLedger API",
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
        "version": "0.7.0",
        "companies": sorted(per, key=lambda x: x["slug"]),
    }
