"""Read-only pre-use catalogue boundary; never provisions or stamps a schema."""
import asyncio


def namespace_path_is_explicit(namespace, configured_path):
    """Bounded legacy-public admission, not a general search_path parser.

    An effective Core/custom namespace retains bootstrap ownership semantics.
    Effective public is admitted only for the two known explicit legacy forms;
    missing Core, quoted ambiguity and other paths cannot prove that intent.
    """
    if namespace != "public":
        return namespace is not None
    if not isinstance(configured_path, str) or len(configured_path) > 128:
        return False
    known = {'public': 'public', '"public"': 'public', '$user': '$user', '"$user"': '$user'}
    tokens = tuple(known.get(part.strip()) for part in configured_path.split(','))
    return tokens in (("public",), ("$user", "public"))


async def require_connection(connection):
    """Borrow the caller's transaction and options; no DDL/lock/commit/rollback."""
    try:
        async with asyncio.timeout(3):
            from sqlalchemy import text
            from schema_migrations.manifest import PULSE_ID, load
            from schema_migrations.revisions.catalog_pulse_view_role_grants_v1 import inspect_pulse

            package=load(revision=PULSE_ID)
            identity=(await connection.execute(text("SELECT current_schema() AS namespace, current_user AS owner, current_setting('search_path') AS configured_path"))).mappings().one()
            if (identity['namespace'] not in ('core','public')
                    or not namespace_path_is_explicit(identity['namespace'],identity['configured_path'])):
                raise RuntimeError('Unsupported Pulse namespace')
            raw=await connection.get_raw_connection()
            if not raw.driver_connection.is_in_transaction():
                raise RuntimeError('Pulse catalogue transaction missing')
            table=await inspect_pulse(raw.driver_connection,package.contract,identity['owner'],namespace=identity['namespace'])
            if table is None:
                raise RuntimeError('Pulse audience schema is missing')
    except Exception:
        raise RuntimeError('Pulse audience schema is not ready') from None
