"""
Конфигурация тестов ClearLedger Server.

Использует PostgreSQL (clearledger_test) на localhost:5432.
Seed-данные: 5 компаний + демо-пользователь (admin@clearledger.ru / admin123).
"""

import os

# --- Тестовое окружение ---
# Тестовая БД задаётся ТОЛЬКО через TEST_DATABASE_URL (обычный DATABASE_URL из
# окружения намеренно игнорируется — иначе прогон мог бы снести прод/dev-БД,
# conftest делает drop_all). По умолчанию — локальный clearledger_test:5432.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://clearledger:clearledger@localhost:5432/clearledger_test",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Суперадмин для тестов: сид создаёт его только при заданных SEED_SUPERADMIN_*
# (в проде их нет → бэкдор admin@clearledger.ru/admin123 не появляется).
os.environ.setdefault("SEED_SUPERADMIN_EMAIL", "admin@clearledger.ru")
os.environ.setdefault("SEED_SUPERADMIN_PASSWORD", "admin123")
# Каталог компаний в тестах — полный. Стек компании сужает его до своей
# (ECOSYSTEM_COMPANIES=rushydro), и прогон внутри такого контейнера ронял семь
# тестов, которые ждут компанию gig, — падение окружения, а не кода.
os.environ["ECOSYSTEM_COMPANIES"] = ""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy import text as sa_text

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
    """Создаёт схему тем же кодом, что и приложение, плюс seed — раз за сессию.

    Схема поднимается через `app.database.create_all`, а не голым `create_all`
    метаданных: половина правил живёт не в моделях, а в инкрементальных
    миграциях — частичные уникальные индексы, выражения, триггеры
    неизменяемости архива. Тестовая база без них отличается от боевой, и
    проверка готовности (`/ready`) честно отвечала 503: обязательных объектов
    схемы нет. Тест при этом ловил не поломку кода, а разницу окружений.
    """
    async with _test_engine.begin() as conn:
        # Схему сносим целиком, а не `drop_all` по метаданным: миграции заводят
        # таблицы, которых в моделях нет (журнал решений по ревизиям станции), и
        # `drop_all` спотыкается о внешний ключ из такой таблицы. База здесь
        # отдельная (`clearledger_test`), сносить её содержимое безопасно.
        await conn.execute(sa_text("DROP SCHEMA IF EXISTS edge CASCADE"))
        await conn.execute(sa_text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa_text("CREATE SCHEMA public"))
        # Схему `edge` в бою заводит инициализатор базы пространства: у роли
        # приложения нет права CREATE, и само оно её не создаёт.
        await conn.execute(sa_text("CREATE SCHEMA edge"))
    await _db.create_all()

    async with _test_session_factory() as session:
        await seed_data(session)

    yield

    # Чистим тем же способом, что и создавали: `drop_all` по метаданным не знает
    # о таблицах, заведённых миграциями, и падает на их внешних ключах.
    async with _test_engine.begin() as conn:
        await conn.execute(sa_text("DROP SCHEMA IF EXISTS edge CASCADE"))
        await conn.execute(sa_text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa_text("CREATE SCHEMA public"))
    await _test_engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def client(setup_database) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент без авторизации."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Счётчик попыток входа — общий на процесс, а логинится каждый тест.

    Лимит — десять попыток в минуту (`app.rate_limit`), и одиннадцатый тест
    файла падает на 429 — не потому, что сломан, а потому, что защита от
    перебора не отличает прогон набора от подбора пароля. Сам лимит
    проверяется своим тестом (`test_rate_limit.py`), у которого своя такая же чистка.
    """
    import app.rate_limit as rl
    rl._hits.clear()
    rl._reported.clear()
    yield


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
