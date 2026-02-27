"""
Конфигурация тестов ClearLedger Server.

Использует PostgreSQL (clearledger_test) на localhost:5432.
Seed-данные: 5 компаний + демо-пользователь (admin@clearledger.ru / admin123).
"""

import os

# --- Тестовое окружение ---
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://clearledger:clearledger@localhost:5432/clearledger_test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base, get_db
from app.main import app
from app.seed import seed_data

# Тестовый engine (отдельная БД clearledger_test)
_test_engine = create_async_engine(
    os.environ["DATABASE_URL"],
    echo=False,
    pool_size=5,
    max_overflow=10,
)
_test_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False,
)

# Подменяем get_db на тестовый
import app.database as _db

_db.engine = _test_engine
_db.async_session_factory = _test_session_factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_database():
    """Создаёт таблицы и seed-данные один раз за сессию."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with _test_session_factory() as session:
        await seed_data(session)

    yield

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def client(setup_database) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент без авторизации."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def auth_client(client: AsyncClient) -> AsyncClient:
    """HTTP-клиент с JWT-токеном (admin@clearledger.ru / admin123)."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": "admin@clearledger.ru", "password": "admin123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    client.headers.pop("Authorization", None)


@pytest_asyncio.fixture(loop_scope="session")
async def db(setup_database) -> AsyncGenerator[AsyncSession, None]:
    """Прямой доступ к тестовой БД."""
    async with _test_session_factory() as session:
        yield session
