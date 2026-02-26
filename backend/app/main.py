"""ClearLedger API — точка входа FastAPI."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, entries, companies, intake, files


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


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.3.0"}
