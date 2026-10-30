"""Explicit v1 facade; no dynamic plugin discovery or ORM metadata registration."""


async def verify_budget(conn, contract, owner, parent):
    from schema_migrations.revisions.catalog_v1 import verify_table
    return await verify_table(conn, contract["budget"], owner, parent=parent)


async def verify_journal(conn, contract, owner):
    from schema_migrations.revisions.catalog_v1 import verify_table
    return await verify_table(conn, contract["journal"], owner)


async def verify_unoccupied_names(conn, budget, ledger):
    names = []
    if budget is None:
        names += ["product_api_budgets_pkey", "ix_product_api_budgets_reset"]
    if ledger is None:
        names += ["core_schema_versions_pkey", "core_schema_versions_ordinal_key"]
    if names and await conn.fetchval("""SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='core' AND c.relname=ANY($1::text[]))""", names):
        from schema_migrations.errors import MigrationError
        raise MigrationError(4, "reserved_name")


async def inspect_prerequisites(conn, contract, owner):
    # Called only after manifest.load() succeeds in the explicit runner.
    from schema_migrations.revisions.catalog_v1 import inspect_prerequisites as v1
    return await v1(conn, contract, owner)
