"""ClearLedger API — точка входа FastAPI."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, entries, companies, intake, files, connectors, document_links, settings_api, stats, audit
from app.database import async_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


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
