"""Окружение Alembic для сверки схемы Ядра.

Схему создаёт приложение (create_all плюс ручные операторы в app/database.py) — Alembic
здесь не для выпуска, а чтобы увидеть расхождение моделей и базы: `alembic check`.

Две особенности этой базы:

1. Ядро живёт в схеме `core`, а Поддержка — в `public` ТОЙ ЖЕ базы. Модели Ядра схему
   не указывают и опираются на search_path роли (`core, public`). Поэтому соединение
   здесь явно переводится в `core`: иначе Alembic увидел бы 197 таблиц Поддержки как
   лишние и предложил их удалить.
2. Таблица версий тоже кладётся в `core` — в `public` уже есть журнал миграций
   Поддержки (`schema_migrations`), мешать их в одной схеме незачем.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

# Таблицы объявлены не только в app/models.py: часть живёт в models_dedup,
# support_context_models, space_data_model, space_links, counterparty_usage,
# onec/sync_service и даже в роутерах (pulse_home, books_router). Единственный надёжный
# способ собрать ПОЛНУЮ metadata — поднять импорт приложения: без этого сверка объявляет
# десятки существующих таблиц лишними и предлагает их удалить.
import app.main  # noqa: F401
from app.config import get_settings
from app.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", get_settings().database_url)

CORE_SCHEMA = "core"


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_schema=CORE_SCHEMA,
        include_schemas=False,
        # Тип и значение по умолчанию тоже сравниваем: именно на типах разъехались
        # деньги (double precision против numeric), и такое расхождение должно быть
        # видно сверкой, а не обнаруживаться в сверке актов.
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=CORE_SCHEMA,
        include_schemas=False,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    connection.execute(text(f"SET search_path TO {CORE_SCHEMA}"))
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # commit обязателен: `SET search_path` открывает транзакцию раньше, чем Alembic,
    # поэтому его собственный begin_transaction оказывается вложенным и на выходе
    # ничего не фиксирует — `alembic stamp` молча не сохранял отметку версии.
    async with connectable.connect() as connection:
        await connection.run_sync(_run)
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
