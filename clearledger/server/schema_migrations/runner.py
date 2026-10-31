"""Explicit, not startup-enabled PG16 migration foundation. Offline plan has no DB imports."""
# Direct file execution under python -I; importing the package never edits sys.path.
if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import re
from urllib.parse import unquote, urlsplit

from schema_migrations import catalog, journal
from schema_migrations.errors import MigrationError
from schema_migrations.manifest import CALENDAR_ID, ID, PULSE_ID, load

LOCK = (434532, 1)


@dataclass(frozen=True)
class Config:
    dsn: str = field(repr=False)
    database: str
    user: str
    namespace: str
    lock_seconds: float = 2.0
    total_seconds: float = 20.0

    def validate(self):
        try:
            uri = urlsplit(self.dsn)
            if (uri.scheme != "postgresql" or uri.query or uri.fragment or not uri.hostname
                    or uri.port is None or not 1 <= uri.port <= 65535 or not uri.password
                    or unquote(uri.username or "") != self.user or unquote(uri.path) != "/" + self.database
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.database)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.user)
                    or not 0.05 <= self.lock_seconds <= 10 or not 1 <= self.total_seconds <= 120):
                raise MigrationError(3, "target")
        except (ValueError, TypeError):
            raise MigrationError(3, "target") from None
        if self.namespace != "core":
            raise MigrationError(3, "namespace")


async def identity(conn, config):
    row = await conn.fetchrow("""SELECT pg_catalog.current_database() AS db,
        current_user AS usr, pg_catalog.current_schema() AS ns,
        pg_catalog.current_setting('server_version_num')::int AS version,
        pg_catalog.current_setting('session_replication_role') AS replication_role,
        pg_catalog.pg_get_userbyid(n.nspowner) AS owner,
        pg_catalog.has_schema_privilege(current_user,n.oid,'USAGE') AS usage,
        pg_catalog.has_schema_privilege(current_user,n.oid,'CREATE') AS can_create
        FROM pg_catalog.pg_namespace n WHERE n.nspname='core'""")
    if (row is None or row["db"] != config.database or row["usr"] != config.user
            or row["ns"] != "core" or row["owner"] != config.user or not row["usage"]
            or not row["can_create"] or row["replication_role"] != "origin" or not 160000 <= row["version"] < 170000):
        raise MigrationError(3, "identity")


async def state(conn, config, package):
    await identity(conn, config)
    if package.entry["id"] == PULSE_ID:
        foundation = package.parent.parent
        parent = await catalog.inspect_prerequisites(conn, foundation.contract, config.user)
        budget = await catalog.verify_budget(conn, foundation.contract, config.user, parent)
        ledger = await catalog.verify_journal(conn, foundation.contract, config.user)
        if budget is None or ledger is None:
            raise MigrationError(4, "parent_unapplied")
        calendar = await catalog.inspect_calendar(conn, package.parent.contract, config.user)
        if not calendar["present"]:
            raise MigrationError(4, "parent_unapplied")
        complete = await journal.read_verified_history(conn, package, config.user, True)
        pulse = await catalog.inspect_pulse(conn, package.contract, config.user)
        if complete and pulse is None:
            raise MigrationError(4, "missing_applied_table")
        return pulse, budget, ledger, complete
    if package.parent is not None:
        parent_package = package.parent
        parent = await catalog.inspect_prerequisites(conn, parent_package.contract, config.user)
        budget = await catalog.verify_budget(conn, parent_package.contract, config.user, parent)
        ledger = await catalog.verify_journal(conn, parent_package.contract, config.user)
        if budget is None or ledger is None:
            raise MigrationError(4, "parent_unapplied")
        complete = await journal.read_verified_history(conn, package, config.user, True)
        calendar = await catalog.inspect_calendar(conn, package.contract, config.user)
        if complete and not calendar["present"]:
            raise MigrationError(4, "missing_applied_column")
        return calendar, budget, ledger, complete
    parent = await catalog.inspect_prerequisites(conn, package.contract, config.user)
    budget = await catalog.verify_budget(conn, package.contract, config.user, parent)
    ledger = await catalog.verify_journal(conn, package.contract, config.user)
    await catalog.verify_unoccupied_names(conn, budget, ledger)
    complete = await journal.read_verified_history(conn, package, config.user, ledger is not None)
    if complete and budget is None:
        raise MigrationError(4, "missing_applied_table")
    return parent, budget, ledger, complete


async def require_applied_prefix(conn, config, known_head, *, required_revision=ID):
    """Read-only borrowed connection API; caller owns snapshot and lifecycle.

    Validate every applied known catalogue, never require an unapplied source
    successor, and never accept unknown future history. No BEGIN/SET/lock/write.
    """
    from schema_migrations.manifest import load_known_head
    head = load_known_head()
    if known_head != head:
        raise MigrationError(2, "known_head")
    packages = {1: head.parent.parent, 2: head.parent, 3: head}
    required = [p.entry["ordinal"] for p in packages.values() if p.entry["id"] == required_revision]
    if len(required) != 1:
        raise MigrationError(2, "required_revision")
    config.validate()
    await identity(conn, config)
    foundation = packages[1]
    ledger = await catalog.verify_journal(conn, foundation.contract, config.user)
    if ledger is None:
        raise MigrationError(4, "unapplied")
    rows = await conn.fetch("""SELECT revision, ordinal, parent_revision, artifact_sha256,
        contract_sha256, predecessor_sha256, action, applied_by, app_commit, runner_format
        FROM core.core_schema_versions ORDER BY ordinal LIMIT 4""")
    if not rows or len(rows) > 3:
        raise MigrationError(4, "history")
    journal.validate_history(rows, packages[len(rows)], config.user)
    if required[0] > len(rows):
        raise MigrationError(4, "unapplied")
    parent = await catalog.inspect_prerequisites(conn, foundation.contract, config.user)
    budget = await catalog.verify_budget(conn, foundation.contract, config.user, parent)
    if budget is None:
        raise MigrationError(4, "missing_applied_table")
    if len(rows) >= 2:
        calendar = await catalog.inspect_calendar(conn, packages[2].contract, config.user)
        if not calendar["present"]:
            raise MigrationError(4, "missing_applied_column")
    if len(rows) == 3 and await catalog.inspect_pulse(conn, head.contract, config.user) is None:
        raise MigrationError(4, "missing_applied_table")


async def _apply_owned(connection, config, package, legacy_sent_before):
    """Shared mutation body; caller already owns one connection, lock and transaction."""
    parent, budget, ledger, complete = await state(connection, config, package)
    if complete:
        return {"ok": True, "action": "verified", "revision": package.entry["id"]}
    if package.entry["id"] == PULSE_ID:
        await connection.execute("LOCK TABLE core.pulse_views, core.company_roles IN SHARE ROW EXCLUSIVE MODE")
        if parent is not None:
            await connection.execute("LOCK TABLE core.pulse_view_role_grants IN SHARE ROW EXCLUSIVE MODE")
        pulse, _, _, complete = await state(connection, config, package)
        if complete:
            return {"ok": True, "action": "verified", "revision": package.entry["id"]}
        action = "adopted" if pulse is not None else "created"
        if pulse is None:
            await connection.execute(package.sql)
        if await catalog.inspect_pulse(connection, package.contract, config.user) is None:
            raise MigrationError(6, "postcondition")
        await journal.append_applied(connection, package, config.user, action)
        await journal.read_verified_history(connection, package, config.user, True)
        return {"ok": True, "action": action, "revision": package.entry["id"]}
    if package.parent is not None:
        # Application writers need not take the migration owner lock.
        # Hold the relation lock through cutover, catalog checks and history.
        await connection.execute("LOCK TABLE core.calendar_events IN ACCESS EXCLUSIVE MODE")
        calendar, _, _, complete = await state(connection, config, package)
        if complete:
            return {"ok": True, "action": "verified", "revision": package.entry["id"]}
        await catalog.verify_calendar_cutover(connection, package.contract, legacy_sent_before)
        action = "adopted" if calendar["present"] else "created"
        if not calendar["present"]:
            await connection.execute(package.sql)
        after = await catalog.inspect_calendar(connection, package.contract, config.user)
        if not after["present"]:
            raise MigrationError(6, "postcondition")
        await catalog.verify_calendar_preserved(calendar, after)
        await journal.append_applied(connection, package, config.user, action)
        await journal.read_verified_history(connection, package, config.user, True)
        return {"ok": True, "action": action, "revision": package.entry["id"]}
    # Invalid prerequisites/catalog/history have already refused before first DDL.
    if ledger is None:
        await connection.execute(package.journal_sql)
    action = "adopted" if budget else "created"
    if budget is None:
        await connection.execute(package.sql)
    if await catalog.verify_budget(connection, package.contract, config.user, parent) is None:
        raise MigrationError(6, "postcondition")
    if await catalog.verify_journal(connection, package.contract, config.user) is None:
        raise MigrationError(6, "postcondition")
    await journal.append_applied(connection, package, config.user, action)
    await journal.read_verified_history(connection, package, config.user, True)

    return {"ok": True, "action": action, "revision": package.entry["id"]}


async def execute(config, mode, *, revision=ID, legacy_sent_before=None):
    """Return a safe receipt; never retries. check takes no advisory lock or write transaction."""
    package = load(revision=revision)
    if mode not in {"check", "apply"}:
        raise MigrationError(2, "mode")
    config.validate()
    if legacy_sent_before is not None and (package.entry["id"] != CALENDAR_ID or mode != "apply"):
        raise MigrationError(2, "arguments")
    if package.entry["id"] == CALENDAR_ID and mode == "apply" and (
            type(legacy_sent_before) is not int or legacy_sent_before != package.contract["legacy_sent_before"]):
        raise MigrationError(2, "legacy_acknowledgement")
    # Import only after explicit invocation, offline integrity and target checks.
    import asyncpg
    connection = None
    try:
        async with asyncio.timeout(config.total_seconds):
            connection = await asyncpg.connect(config.dsn, timeout=5, command_timeout=10,
                server_settings={"search_path": "core", "statement_timeout": "10000",
                    "lock_timeout": "2000", "idle_in_transaction_session_timeout": "5000",
                    "application_name": "schema-migration-foundation"})
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                *_, complete = await state(connection, config, package)
                if mode == "check":
                    if not complete:
                        raise MigrationError(4, "unapplied")
                    return {"ok": True, "action": "verified", "revision": package.entry["id"]}
            # One connection owns this session lock, all DDL and journal writes.
            try:
                async with asyncio.timeout(config.lock_seconds):
                    await connection.fetchval("SELECT pg_catalog.pg_advisory_lock($1::int,$2::int)", *LOCK)
            except Exception:
                raise MigrationError(5, "owner_lock") from None
            async with connection.transaction():
                return await _apply_owned(connection, config, package, legacy_sent_before)
    except MigrationError:
        raise
    except TimeoutError:
        raise MigrationError(5, "deadline") from None
    except Exception:
        raise MigrationError(6, "database") from None
    finally:
        if connection is not None:
            # Closing the dedicated connection releases its advisory lock even after rollback/cancel.
            await asyncio.shield(connection.close(timeout=2))


# Pinned after all three prerequisite payloads have been authored; not a registry revision.
PARTNER_MANIFEST_SHA256 = 'b9629be565781def7d486b7fd3813761041c980cc31bd9684e798b60b8c1e1a5'
BOOTSTRAP_MANIFEST_SHA256 = 'c13b0bc5d5162fd38449f4b3541265a5eef78518be616cb93bd26f36bbb482b2'


def _bootstrap_source():
    """Verify bytes before importing the new catalogue verifier; no DB imports."""
    from pathlib import Path
    import hashlib
    from schema_migrations.manifest import unique_object
    directory=Path(__file__).resolve().parent/'bootstrap'
    try:
        p=directory/'core_prerequisites_v1.manifest.json'
        b=p.read_bytes()
        if directory.is_symlink() or p.is_symlink() or len(b)>65536 or hashlib.sha256(b).hexdigest()!=BOOTSTRAP_MANIFEST_SHA256:
            raise MigrationError(2,'bootstrap_source')
        m=json.loads(b,object_pairs_hook=unique_object)
        names={'core_prerequisites_v1.sql','core_prerequisites_v1.contract.json','core_prerequisites.py'}
        if set(m)!={'format','name','files'} or m['format']!=1 or m['name']!='core_prerequisites_v1' or set(m['files'])!=names:
            raise MigrationError(2,'bootstrap_source')
        for name in names:
            p=directory/name
            if p.is_symlink():
                raise MigrationError(2,'bootstrap_source')
            b=p.read_bytes()
            if len(b)>512000 or hashlib.sha256(b).hexdigest()!=m['files'][name]:
                raise MigrationError(2,'bootstrap_source')
    except MigrationError:
        raise
    except (OSError,ValueError,KeyError,TypeError):
        raise MigrationError(2,'bootstrap_source') from None
    from schema_migrations.bootstrap import core_prerequisites as verifier
    return verifier.load(BOOTSTRAP_MANIFEST_SHA256),verifier


def _partner_source():
    from pathlib import Path
    import hashlib
    from schema_migrations.manifest import unique_object
    directory=Path(__file__).resolve().parent/'bootstrap'
    try:
        p=directory/'core_partner_prerequisites_v1.manifest.json';raw=p.read_bytes()
        if directory.is_symlink() or p.is_symlink() or len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=PARTNER_MANIFEST_SHA256:
            raise MigrationError(2,'partner_prerequisite_source')
        m=json.loads(raw,object_pairs_hook=unique_object)
        names={'core_partner_prerequisites_v1.contract.json','core_prerequisites_v1.sql','core_prerequisites_v1.contract.json','core_prerequisites.py'}
        if set(m)!={'format','name','files'} or m['format']!=1 or m['name']!='core_partner_prerequisites_v1' or set(m['files'])!=names:
            raise MigrationError(2,'partner_prerequisite_source')
        for name in names:
            p=directory/name;b=p.read_bytes()
            if p.is_symlink() or len(b)>512000 or hashlib.sha256(b).hexdigest()!=m['files'][name]:
                raise MigrationError(2,'partner_prerequisite_source')
    except MigrationError:
        raise
    except (OSError,ValueError,KeyError,TypeError):
        raise MigrationError(2,'partner_prerequisite_source') from None
    from schema_migrations.bootstrap import core_prerequisites as verifier
    return verifier.load_partner(PARTNER_MANIFEST_SHA256)


def preflight_bootstrap_source():
    """Public offline source integrity receipt; no target/catalogue/driver imports."""
    from schema_migrations.manifest import load_known_head
    load_known_head()
    source, _ = _bootstrap_source()
    _partner_source()
    return source.digest


def _sequence_source(target_revision, fresh_prerequisites, legacy_sent_before, upgrade_prerequisites=None, predecessor_source=None):
    from schema_migrations.manifest import load_known_head
    if target_revision!=PULSE_ID or fresh_prerequisites not in (None,'core_prerequisites_v1'):
        raise MigrationError(2,'explicit_target')
    head=load_known_head()
    if type(legacy_sent_before) is not int or legacy_sent_before!=head.parent.contract['legacy_sent_before']:
        raise MigrationError(2,'legacy_acknowledgement')
    source,verifier=_bootstrap_source()
    checked_partner=_partner_source()
    partner=None
    if upgrade_prerequisites is not None:
        if upgrade_prerequisites!='core_partner_prerequisites_v1' or fresh_prerequisites is not None:
            raise MigrationError(2,'partner_prerequisite_arguments')
        partner=checked_partner
        if predecessor_source not in partner.contract['profiles']:
            raise MigrationError(2,'partner_predecessor_source')
    elif predecessor_source is not None:
        raise MigrationError(2,'partner_prerequisite_arguments')
    return head,source,verifier,partner


async def _sequence_catalogue(conn, config, head, source, verifier, fresh, partner=None, predecessor_source=None):
    await identity(conn,config)
    await verifier.prerequisites(conn,config.user)
    if await verifier.empty(conn):
        if not fresh:
            raise MigrationError(4,'bootstrap_unapplied')
        return 0,True,None,False
    foundation=head.parent.parent
    ledger=await catalog.verify_journal(conn,foundation.contract,config.user)
    count=0
    if ledger is not None:
        rows=await conn.fetch('''SELECT revision,ordinal,parent_revision,artifact_sha256,
            contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format
            FROM core.core_schema_versions ORDER BY ordinal LIMIT 4''')
        if len(rows)>3:
            raise MigrationError(4,'history')
        if rows:
            await require_applied_prefix(conn,config,head,required_revision=ID)
            count=len(rows)
    if partner is not None and count!=3:
        if count!=0:
            raise MigrationError(4,'partner_upgrade_history')
        old_profile=await verifier.old_partner_profile(conn,source,partner,config.user,predecessor_source)
        return 0,False,old_profile,True
    if fresh and count!=3:
        # A previous atomic fresh attempt cannot leave a partial prefix behind.
        raise MigrationError(4,'bootstrap_not_empty')
    calendar=await catalog.inspect_calendar(conn,head.parent.contract,config.user)
    await catalog.inspect_pulse(conn,head.contract,config.user)
    parent=await catalog.inspect_prerequisites(conn,foundation.contract,config.user)
    budget=await catalog.verify_budget(conn,foundation.contract,config.user,parent)
    await catalog.verify_unoccupied_names(conn,budget,ledger)
    profile=await verifier.profile(conn,source,config.user,calendar_present=calendar['present'])
    return count,False,profile,False


async def execute_sequence(config, *, target_revision, fresh_prerequisites=None, legacy_sent_before=None,
                           upgrade_prerequisites=None, predecessor_source=None):
    """Explicit one-owner Core prerequisite/upgrade transaction; never called by startup.

    Default execute/check/apply still target0001. All history is verified before
    choosing only missing known successors. Literal fresh SQL never repairs Core.
    """
    config.validate()
    head,source,verifier,partner=_sequence_source(target_revision,fresh_prerequisites,legacy_sent_before,upgrade_prerequisites,predecessor_source)
    import asyncpg
    connection=None
    try:
        async with asyncio.timeout(config.total_seconds):
            connection=await asyncpg.connect(config.dsn,timeout=5,command_timeout=10,
                server_settings={'search_path':'core','statement_timeout':'10000','lock_timeout':'2000',
                    'idle_in_transaction_session_timeout':'5000','application_name':'schema-migration-foundation'})
            async with connection.transaction(isolation='repeatable_read',readonly=True):
                await _sequence_catalogue(connection,config,head,source,verifier,fresh_prerequisites is not None,partner,predecessor_source)
            try:
                async with asyncio.timeout(config.lock_seconds):
                    await connection.fetchval('SELECT pg_catalog.pg_advisory_lock($1::int,$2::int)',*LOCK)
            except TimeoutError:
                raise MigrationError(5,'owner_lock') from None
            async with connection.transaction():
                count,is_empty,before,partner_pending=await _sequence_catalogue(connection,config,head,source,verifier,fresh_prerequisites is not None,partner,predecessor_source)
                if is_empty:
                    await connection.execute(source.sql)
                    await verifier.profile(connection,source,config.user,calendar_present=False,allow_prepared=False)
                elif partner_pending:
                    await connection.execute(partner.sql)
                    await verifier.profile(connection,source,config.user,calendar_present=False)
                actions=[]
                for package in (head.parent.parent,head.parent,head):
                    if package.entry['ordinal']>count:
                        actions.append(await _apply_owned(connection,config,package,legacy_sent_before))
                await require_applied_prefix(connection,config,head,required_revision=PULSE_ID)
                after=await verifier.profile(connection,source,config.user,calendar_present=True)
                receipt={'ok':True,'revision':PULSE_ID,'prefix_before':count,'fresh_created':is_empty,
                    'profile_before':before,'profile_after':after,'actions':actions,
                    'partner_prerequisites_created':partner_pending,'predecessor_source':predecessor_source,
                    'partner_artifact_sha256':partner.digest if partner else None,
                    'artifact_sha256':source.digest,'owner_backend_pid':connection.get_server_pid()}
            return receipt
    except MigrationError:
        raise
    except TimeoutError:
        raise MigrationError(5,'deadline') from None
    except Exception:
        raise MigrationError(6,'database') from None
    finally:
        if connection is not None:
            closing=asyncio.create_task(connection.close(timeout=2))
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await closing
                raise


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal diagnostic echoes unknown arguments, potentially a pasted DSN.
        raise MigrationError(2, "arguments")


def main(argv=None, environ=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("mode", choices=("plan", "check", "apply", "bootstrap"))
        parser.add_argument("--dsn-env")
        parser.add_argument("--database")
        parser.add_argument("--user")
        parser.add_argument("--namespace")
        parser.add_argument("--revision", choices=(ID, CALENDAR_ID, PULSE_ID), default=ID)
        parser.add_argument("--legacy-sent-before", type=int)
        parser.add_argument("--fresh-prerequisites", choices=("core_prerequisites_v1",))
        parser.add_argument('--upgrade-prerequisites', choices=('core_partner_prerequisites_v1',))
        parser.add_argument('--predecessor-source', choices=('ce94e2bf30c0676208b1d70c5c135fe91d1a23f2','5ce5779b20151a8d04de7d3a1681d1862a80d9dd'))
        args = parser.parse_args(argv)
        package = load(revision=args.revision)
        if any((args.fresh_prerequisites,args.upgrade_prerequisites,args.predecessor_source)) and args.mode != 'bootstrap':
            raise MigrationError(2, 'arguments')
        if args.mode == 'bootstrap':
            if args.revision != PULSE_ID:
                raise MigrationError(2, 'explicit_target')
            _sequence_source(args.revision, args.fresh_prerequisites, args.legacy_sent_before, args.upgrade_prerequisites, args.predecessor_source)
        if args.legacy_sent_before is not None and args.mode != 'bootstrap' and (args.revision != CALENDAR_ID or args.mode != "apply"):
            raise MigrationError(2, "arguments")
        if args.mode == "plan":
            if any((args.dsn_env, args.database, args.user, args.namespace, args.legacy_sent_before)):
                raise MigrationError(2, "arguments")
            print(json.dumps({"ok": True, "foundation_only": True, "namespace": "core",
                "revision": package.entry["id"], "artifact_sha256": package.entry["artifact_sha256"]}, sort_keys=True))
            return 0
        if (not args.dsn_env or not re.fullmatch(r"SCHEMA_MIGRATION_[A-Z0-9_]+", args.dsn_env)
                or not args.database or not args.user or not args.namespace):
            raise MigrationError(2, "arguments")
        if environ is None:
            import os
            environ = os.environ
        dsn = environ.get(args.dsn_env)
        if not dsn:
            raise MigrationError(2, "credential_input")
        cfg = Config(dsn, args.database, args.user, args.namespace)
        if args.mode == 'bootstrap':
            receipt = asyncio.run(execute_sequence(cfg, target_revision=args.revision,
                fresh_prerequisites=args.fresh_prerequisites, legacy_sent_before=args.legacy_sent_before,
                upgrade_prerequisites=args.upgrade_prerequisites, predecessor_source=args.predecessor_source))
        else:
            receipt = asyncio.run(execute(cfg, args.mode,
                revision=args.revision, legacy_sent_before=args.legacy_sent_before))
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except MigrationError as error:
        print(json.dumps({"ok": False, "code": error.code, "phase": error.phase}, sort_keys=True))
        return error.code
    except Exception:
        print(json.dumps({"ok": False, "code": 6, "phase": "internal"}, sort_keys=True))
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
