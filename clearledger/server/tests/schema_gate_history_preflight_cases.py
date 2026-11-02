"""Draft ROOT-only OFF/preflight cases; importing this file imports only stdlib.

Not a pytest entrypoint. An independently frozen execution helper must validate
its exact source/dependency/target/environment envelope before calling run().
This module does not provision a database or run application startup.
"""
import builtins
import copy
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit


CASE_IDS = (
    "OFF-connection-no-io", "OFF-engine-no-checkout",
    "S-driver", "S-query-TLS", "S-expectedDB", "S-expectedUser",
    "S-empty-identity", "S-source-artifact", "S-registry-unknown",
    "S-source-verifier-marker", "S-default-port",
)


class Untouchable:
    def __init__(self, touches):
        object.__setattr__(self, "touches", touches)

    def __getattribute__(self, name):
        object.__getattribute__(self, "touches").append(name)
        raise AssertionError("OFF/preflight touched connection or engine")


class DisabledSettings:
    managed_core_budget_enabled = False

    def __getattr__(self, name):
        raise AssertionError("OFF touched configuration")


def forbidden(*args, **kwargs):
    raise AssertionError("OFF reached configuration or manifest")


async def run(settings, scratch, progress):
    # There is deliberately no fallback or test-local approval bypass. The
    # helper will be authored/frozen only after ROOT accepts the B source pin.
    from tests.schema_gate_history_compatibility_approved import require_running_approval
    require_running_approval()

    from app.services import schema_version_gate as gate
    from schema_migrations import manifest

    scratch = Path(scratch)
    assert scratch.is_absolute() and scratch.is_dir() and not scratch.is_symlink()
    assert settings.managed_core_budget_enabled is True
    completed = []

    def record(case_id):
        assert case_id in CASE_IDS and case_id not in completed
        completed.append(case_id)
        progress(case_id, {})

    def configured(**changes):
        values = {
            "managed_core_budget_enabled": True,
            "managed_core_budget_expected_database": settings.managed_core_budget_expected_database,
            "managed_core_budget_expected_user": settings.managed_core_budget_expected_user,
            "database_url": settings.database_url,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    async def refused_before_checkout(candidate):
        touches = []
        try:
            await gate.require_engine(Untouchable(touches), candidate)
        except RuntimeError as error:
            assert str(error) == "Managed Core budget schema is not ready"
            assert error.__suppress_context__
        else:
            raise AssertionError("invalid configuration/source reached acceptance")
        # Gate sanitizes ordinary exceptions, including a sentinel exception.
        # Inspect the independent counter so a failed checkout cannot masquerade
        # as the expected preflight refusal.
        assert not touches, "failure occurred after engine access"

    # No usable engine/connection, no usable Config and no manifest operation:
    # OFF must return before any of them. These are I/O sentinels, not mocks of
    # a successful verifier or of database/catalog readiness.
    import_calls = []
    original_import = builtins.__import__

    def no_framework_imports(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"schema_migrations", "sqlalchemy"}:
            import_calls.append(name)
            raise AssertionError("OFF imported framework/driver configuration")
        return original_import(name, *args, **kwargs)

    with (patch.object(gate, "_config", forbidden),
          patch.object(manifest, "load_known_head", forbidden),
          patch.object(builtins, "__import__", no_framework_imports)):
        touches = []
        assert await gate.require_connection(Untouchable(touches), DisabledSettings()) is None
        assert not touches
        record("OFF-connection-no-io")
        assert await gate.require_engine(Untouchable(touches), DisabledSettings()) is None
        assert not touches
        record("OFF-engine-no-checkout")
        assert not import_calls

    gate._config(configured())  # Valid input is required for the source negatives below.

    for case_id, changes in (
        ("S-driver", {"database_url": "sqlite+aiosqlite:///synthetic-test-only"}),
        ("S-query-TLS", {"database_url": settings.database_url + "?ssl=require"}),
        ("S-expectedDB", {"managed_core_budget_expected_database": "wrong_test_database"}),
        ("S-expectedUser", {"managed_core_budget_expected_user": "wrong_test_user"}),
        ("S-empty-identity", {"managed_core_budget_expected_database": "",
                              "managed_core_budget_expected_user": ""}),
    ):
        await refused_before_checkout(configured(**changes))
        record(case_id)

    # Exercise the real loader on corrupted copies. Only its root is redirected;
    # no history/catalog verifier is replaced with a success/failure stub.
    original_loader = manifest.load_known_head
    known_head = original_loader()
    for case_id in ("S-source-artifact", "S-registry-unknown", "S-source-verifier-marker"):
        with TemporaryDirectory(prefix="schema-gate-source-test-", dir=scratch) as temporary:
            copied = Path(temporary) / "schema_migrations"
            shutil.copytree(manifest.ROOT, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            marker = Path(temporary) / "unverified-code-executed"
            if case_id == "S-registry-unknown":
                registry_path = copied / "manifest.json"
                registry = json.loads(registry_path.read_text())
                extra = copy.deepcopy(registry["revisions"][-1])
                extra["id"] = "9999_unknown_source"
                registry["revisions"].append(extra)
                registry_path.write_text(json.dumps(registry) + "\n")
            else:
                extension = ".sql" if case_id == "S-source-artifact" else ".py"
                paths = [name for name in known_head.entry["files"] if name.endswith(extension)]
                assert paths
                artifact = copied / sorted(paths)[0]
                changed = b"\n" if extension == ".sql" else (
                    "\nfrom pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('unexpected')\n"
                ).encode()
                artifact.write_bytes(artifact.read_bytes() + changed)
            loader_calls = []

            def corrupted_loader():
                loader_calls.append(True)
                return original_loader(root=copied)

            with patch.object(manifest, "load_known_head", corrupted_loader):
                await refused_before_checkout(configured())
            assert loader_calls == [True], "source refusal did not execute the real loader"
            assert not marker.exists(), "unverified artifact executed before integrity refusal"
            record(case_id)

    # Normalize only an absent port; do not invent a replacement target/identity.
    from sqlalchemy.engine import URL, make_url
    original = make_url(settings.database_url)
    no_port = URL.create(drivername=original.drivername, username=original.username,
                        password=original.password, host=original.host,
                        database=original.database, query=original.query)
    assert no_port.port is None, "fixture must actually omit the PostgreSQL port"
    result = gate._config(configured(database_url=no_port.render_as_string(hide_password=False)))
    assert urlsplit(result.dsn).port == 5432
    assert (result.database, result.user, result.namespace) == (
        settings.managed_core_budget_expected_database,
        settings.managed_core_budget_expected_user, "core",
    )
    record("S-default-port")
    assert tuple(completed) == CASE_IDS
    return completed


if __name__ == "__main__":
    raise SystemExit("ROOT immutable approval helper required; direct execution is refused")
