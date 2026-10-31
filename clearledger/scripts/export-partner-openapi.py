#!/usr/bin/env python3
"""Export the actual curated product OpenAPI without runtime configuration/I/O.

Only app.database.Base is supplied locally for real ORM declarations. Neither
database.py nor main/config/auth is imported; actual DTOs/handlers/policies are
assembled by create_product_api. No requests, lifespan, database or credentials.
"""
import importlib.abc
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType


def forbidden(*args, **kwargs):
    raise RuntimeError("Runtime I/O is forbidden during offline OpenAPI export")


def offline_audit(event, args):
    if event.startswith("socket.") and event in {
        "socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind", "socket.sendto",
    }:
        forbidden()
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0]).replace("\\", "/").rsplit("/", 1)[-1]
        if name == ".env" or name.startswith(".env."):
            raise RuntimeError("Environment files are forbidden during offline OpenAPI export")


class NoRuntimeImports(importlib.abc.MetaPathFinder):
    def __init__(self, allow_config=False):
        self.allow_config = allow_config

    def find_spec(self, fullname, path=None, target=None):
        blocked = {"app.main", "app.auth", "app.services.partner_identity"}
        if not self.allow_config:
            blocked.add("app.config")
        if fullname in blocked:
            raise RuntimeError("Runtime module is forbidden during offline export: " + fullname)
        return None


def export_schema(*, runtime_database=False):
    # No ambient configuration enters schema construction. Even a direct CLI
    # invocation does not inherit a server DATABASE_URL or production secrets.
    os.environ.clear()
    os.environ.update({"LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
    synthetic_url = "postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/partner_wire_schema_test"
    if runtime_database:
        os.environ.update({"DATABASE_URL": synthetic_url, "SECRET_KEY": "synthetic-schema-only-not-for-auth"})
    sys.addaudithook(offline_audit)
    sys.meta_path.insert(0, NoRuntimeImports(allow_config=runtime_database))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
    from sqlalchemy.orm import DeclarativeBase

    if runtime_database:
        from app import database
        from sqlalchemy import event
        assert database.settings.database_url == synthetic_url
        # Parity control uses the real Base/engine module but cannot connect.
        event.listen(database.engine.sync_engine, "do_connect", forbidden)
    else:
        class SchemaOnlyBase(DeclarativeBase):
            pass

        declarations = ModuleType("app.database")
        declarations.Base = SchemaOnlyBase
        # A future importer cannot quietly use this adapter as a runtime database.
        def unavailable_attribute(name):
            if name.startswith("__"):
                raise AttributeError(name)
            forbidden()
        declarations.__getattr__ = unavailable_attribute
        sys.modules["app.database"] = declarations
    from app.product_api import create_product_api, curated_openapi
    product = create_product_api(session_factory=forbidden, verifier=forbidden, enabled=False,
        upload_dir=Path("/offline-partner-schema-unused"),
        cursor_key=b"synthetic-offline-schema-key-32bytes",
        issuer="https://partner-schema.example.invalid", source_revision="offline-candidate")
    schema = curated_openapi(product)
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    operations = [operation for path in schema["paths"].values()
                  for method, operation in path.items() if method in methods]
    if len(operations) != 15 or any(operation.get("x-elsy-readiness") != "candidate" for operation in operations):
        raise RuntimeError("Expected exactly 15 curated candidate product operations")
    unexpected = {"app.main", "app.auth", "app.services.partner_identity"}
    if not runtime_database:
        unexpected.add("app.config")
    if any(name in sys.modules for name in unexpected):
        raise RuntimeError("Runtime modules unexpectedly imported")
    return schema


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-database", action="store_true", help="Hermetic real-module parity control, never connect")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="partner-offline-schema-") as empty:
        os.chdir(empty)
        data = json.dumps(export_schema(runtime_database=args.runtime_database), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        sys.stdout.buffer.write(data.encode("utf-8"))
