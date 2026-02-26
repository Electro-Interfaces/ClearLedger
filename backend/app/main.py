"""ClearLedger API — точка входа FastAPI."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, entries, companies, intake, files, connectors, document_links, settings_api, stats, audit, export, connector_actions
from app.config import settings as app_settings
from app.database import async_session
from app.services.sync import sync_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: запуск sync worker если облако сконфигурировано
    sync_task = None
    if app_settings.cloud_api_url:
        sync_task = asyncio.create_task(sync_loop())
        logging.info("Sync worker запущен (cloud: %s)", app_settings.cloud_api_url)
    else:
        logging.info("Sync worker не запущен (CLOUD_API_URL не задан)")

    yield

    # Shutdown
    if sync_task:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="ClearLedger API",
    version="0.3.0",
    description="Документооборот: приём, классификация, хранение",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роутеры
app.include_router(auth.router, prefix="/api")
app.include_router(entries.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(intake.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(connectors.router, prefix="/api")
app.include_router(document_links.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(connector_actions.router, prefix="/api")


@app.get("/api/health")
async def health():
    """Health check с проверкой БД."""
    db_ok = False
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        pass

    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "version": "0.3.0",
        "database": "connected" if db_ok else "unavailable",
    }
