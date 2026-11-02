"""Default-off, read-only version gate on the application's actual connection.

No apply/stamp/owner-lock acquisition. Frozen Foundation artifacts stay unchanged.
Borrowed connections keep their transaction, search_path and connection options.
"""
import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class GateReceipt:
    read_only: bool
    isolation: str
    driver_in_transaction: bool


def _config(settings):
    from sqlalchemy.engine import make_url
    from schema_migrations.runner import Config

    url = make_url(settings.database_url)
    # Foundation v1 does not support query overrides. Refuse only this opt-in
    # mode rather than silently discarding TLS/options or affecting legacy.
    if url.drivername != "postgresql+asyncpg" or url.query:
        raise RuntimeError("Unsupported managed database configuration")
    raw = url.set(drivername="postgresql", port=5432 if url.port is None else url.port)
    config = Config(raw.render_as_string(hide_password=False),
        settings.managed_core_budget_expected_database,
        settings.managed_core_budget_expected_user, "core")
    config.validate()
    return config


async def require_connection(connection, settings):
    """Read only; never begin/finish a transaction or change options on a borrowed connection."""
    if not settings.managed_core_budget_enabled:
        return None
    try:
        async with asyncio.timeout(10):
            from sqlalchemy import text
            from schema_migrations.manifest import load
            from schema_migrations.runner import state

            config = _config(settings)
            package = load()  # Verify frozen artifacts before executing their verifier.
            # SQLAlchemy's begin object is lazy. Execute through its adapter
            # first so the raw driver participates in the actual caller PG txn.
            probe = (await connection.execute(text("""SELECT
                pg_catalog.current_database() AS database,
                current_user AS username, pg_catalog.current_schema() AS namespace,
                pg_catalog.current_setting('transaction_read_only') AS read_only,
                pg_catalog.current_setting('transaction_isolation') AS isolation"""))).mappings().one()
            if (probe["database"], probe["username"], probe["namespace"]) != (
                    config.database, config.user, "core"):
                raise RuntimeError("Managed application namespace mismatch")
            raw = await connection.get_raw_connection()
            driver = raw.driver_connection
            if not driver.is_in_transaction():
                raise RuntimeError("Managed application transaction missing")
            *_, complete = await state(driver, config, package)
            if not complete:
                raise RuntimeError("Managed schema revision is unapplied")
            return GateReceipt(probe["read_only"] == "on", probe["isolation"], True)
    except Exception:
        # Never expose DSN, catalog contents, driver SQL or tenant identifiers.
        raise RuntimeError("Managed Core budget schema is not ready") from None


async def require_engine(engine, settings):
    """Own a bounded read-only snapshot before any startup marker/DDL/seed path."""
    if not settings.managed_core_budget_enabled:
        return None
    try:
        async with asyncio.timeout(15):
            async with engine.connect() as connection:
                connection = await connection.execution_options(
                    isolation_level="REPEATABLE READ", postgresql_readonly=True)
                async with connection.begin():
                    return await require_connection(connection, settings)
    except Exception:
        raise RuntimeError("Managed Core budget schema is not ready") from None
