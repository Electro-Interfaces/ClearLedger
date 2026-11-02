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


async def inspect_calendar(conn, contract, owner):
    from schema_migrations.revisions.catalog_v2 import inspect_calendar as v2
    return await v2(conn, contract, owner)


async def verify_calendar_cutover(conn, contract, acknowledgement):
    from schema_migrations.revisions.catalog_v2 import verify_cutover
    await verify_cutover(conn, contract, acknowledgement)


async def verify_calendar_preserved(before, after):
    from schema_migrations.revisions.catalog_v2 import verify_preserved
    await verify_preserved(before, after)


async def inspect_pulse(conn, contract, owner):
    from schema_migrations.revisions.catalog_pulse_view_role_grants_v1 import inspect_pulse as pulse
    return await pulse(conn, contract, owner)


async def inspect_contract_create(conn, contract, owner, *, applied):
    from schema_migrations.revisions.catalog_partner_contract_create_v1 import inspect
    return await inspect(conn, contract, owner, applied=applied)


async def contract_create_prerequisites(conn, contract, owner):
    from schema_migrations.revisions.catalog_partner_contract_create_v1 import prerequisites
    return await prerequisites(conn, contract, owner)


async def inspect_contract_cycle_receipts(conn, contract, owner, *, applied):
    from schema_migrations.revisions.catalog_partner_contract_cycle_receipts_v1 import inspect
    return await inspect(conn, contract, owner, applied=applied)


async def contract_cycle_receipts_prerequisites(conn, contract, owner):
    from schema_migrations.revisions.catalog_partner_contract_cycle_receipts_v1 import prerequisites
    return await prerequisites(conn, contract, owner)


async def inspect_site_authority(conn, contract, owner, *, applied, preparing=False):
    from schema_migrations.revisions.catalog_site_authority_v1 import inspect
    return await inspect(conn, contract, owner, applied=applied, preparing=preparing)


async def site_authority_prerequisites(conn, contract, owner):
    from schema_migrations.revisions.catalog_site_authority_v1 import prerequisites
    return await prerequisites(conn, contract, owner)


async def inspect_doc_site_business(conn, contract, owner):
    from schema_migrations.revisions.catalog_doc_site_business_v1 import inspect
    return await inspect(conn, contract, owner)


async def prepare_doc_site_business(conn, contract, owner):
    from schema_migrations.revisions.catalog_doc_site_business_v1 import prepare
    return await prepare(conn, contract, owner)


async def unrecorded_doc_site_business(conn, contract):
    from schema_migrations.revisions.catalog_doc_site_business_v1 import unrecorded
    return await unrecorded(conn, contract)
