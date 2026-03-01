"""
Точка входа ClearLedger Server.
FastAPI приложение с CORS, роутерами, startup seed.
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import async_session_factory, create_all
from app.routers import (
    accounting_docs_router,
    audit_data_router,
    audit_router,
    auth_router,
    companies_router,
    connectors_router,
    document_links_router,
    entries_router,
    export_router,
    intake_router,
    ocr_router,
    reconciliation_router,
    references_router,
    reports_router,
    settings_router,
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
    logger.info("Запуск ClearLedger Server...")

    # Создание таблиц
    await create_all()
    logger.info("Таблицы БД созданы/проверены")

    # Seed начальных данных
    async with async_session_factory() as session:
        await seed_data(session)

    logger.info("ClearLedger Server запущен")
    yield
    logger.info("ClearLedger Server остановлен")


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ClearLedger API",
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
app.include_router(audit_data_router.router, prefix=API_PREFIX)
app.include_router(ocr_router.router, prefix=API_PREFIX)


@app.get("/api/health")
async def health_check():
    """Проверка работоспособности сервера."""
    return {
        "status": "ok",
        "version": "0.5.0",
        "service": "ClearLedger API",
    }
