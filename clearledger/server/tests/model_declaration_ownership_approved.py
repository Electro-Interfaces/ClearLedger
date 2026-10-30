"""ROOT-only M16-C1 full metadata/PG DDL/curated API export; never run by worker.

One invocation is one fresh process and one immutable model blob. ROOT compares
baseline twice and candidate twice byte for byte. No pytest, SQL, engine,
configuration, network, subprocess, filesystem writes, or default invocation.
"""
import ast
import hashlib
import importlib.abc
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import pwd
import resource
import signal
import stat
import sys
import types

SELF = Path(__file__).resolve()
SERVER = SELF.parents[1]
REPO = SERVER.parents[1]
BASE = "81a8e516c3037bd507e35de05e806138b8961c77"
BASE_MODEL = "6aef22c515d013e282e02f39bde3431d94d45fb25077d056144250b606b509a1"
CANDIDATE_MODEL = "f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e"
CANDIDATE = Path("/srv/projects/api-modernization-upgrade-test-env-20261030/.venv")
SITE = CANDIDATE / "lib/python3.13/site-packages"
STDLIB = Path("/home/mag/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu/lib/python3.13")
MODELS = ("app.models", "app.models_dedup", "app.models_partner",
          "app.models_docs_portal", "app.models_product_budget")
EXPECTED_CLASSES = (315, 1, 12, 1, 1)
COUNTS = {"app": 498, "tests": 368, "schema_migrations": 16}
DIGESTS = {"app": "03ebbf3edacef2eee1f5f8cd815ecb5add677ba313c09dce66f26a87bd78b8a9",
           "tests": "e7083210c983b0769d0ce1e34009a3d4171cc788b050f1c172879c789cc9f524",
           "schema_migrations": "51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d"}
SUPPORT = {
    "clearledger/server/requirements.txt": "f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0",
    "clearledger/server/pytest.ini": "bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601",
    "clearledger/server/Dockerfile": "aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d",
    "clearledger/scripts/export-partner-openapi.py": "b5d52daca7220a523b4c5edc85852de39b0b921e5c033a86029b2f92040abd51",
    "clearledger/tools/partner-api-types/generate.mjs": "549d7f05625af2906b4cd44b44f571b5c935ea195490d52d530da5e08fe53817",
    "clearledger/tools/partner-api-types/package.json": "900597c5e189affc56dc83b662a84e77b149de8177302ebe07b05954bf61f380",
    "clearledger/tools/partner-api-types/package-lock.json": "c7f9ba06a2e02383cc7409b071fea099a03df4ad796287de249d9250a0d292ac",
    "clearledger/tools/partner-api-types/generation.test.mjs": "af7e5a544a2247ef0269fae323c928d411e0d89166f85113d71099204a599266",
    "clearledger/tools/partner-api-types/consumer.ts": "28b26158dbd0c8e6054cae74db3927210031d0dea695107537cc431bde7bc047",
}
SQLALCHEMY_TREE = "a6476b4195ce507ae5c42a7dbcfec0ee256935ea27ae60e6047799e56f010beb"
RUNTIME = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}
MAX_OUTPUT = 16 * 1024 * 1024
MAX_FILES = 20000
MAX_FILE = 16 * 1024 * 1024
MAX_TREE = 128 * 1024 * 1024
BLOCKED = {"app.main", "app.config", "app.auth", "app.services.partner_identity"}


def refuse(reason):
    raise RuntimeError("M16-C1 boundary refused: " + reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root, *, relative, exclude_self=False):
    entries = list(root.rglob("*"))
    if root.is_symlink() or len(entries) > MAX_FILES * 2 or any(p.is_symlink() for p in entries):
        refuse("tree entries/symlink")
    files = sorted(p for p in entries if p.is_file() and "__pycache__" not in p.parts
                   and not (exclude_self and p == SELF))
    if (len(files) > MAX_FILES or any(not stat.S_ISREG(p.stat().st_mode) or p.stat().st_size > MAX_FILE for p in files)
            or sum(p.stat().st_size for p in files) > MAX_TREE):
        refuse("tree bounds")
    manifest = [[str(p.relative_to(relative)), sha(p.read_bytes())] for p in files]
    return len(files), sha(json.dumps(manifest, separators=(",", ":")).encode())


def approval():
    expected_env = {"HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "PYTHONDONTWRITEBYTECODE",
                    "ROOT_APPROVED_MODEL_DECLARATION", "M16_RUNNER_SHA256", "M16_MODE",
                    "M16_BASELINE_BLOB", "M16_EMPTY_CWD"}
    if (set(os.environ) != expected_env
            or os.environ["HOME"] != pwd.getpwuid(os.getuid()).pw_dir
            or os.environ["PATH"] != "/usr/bin:/bin"
            or any(os.environ[k] != "C.UTF-8" for k in ("LANG", "LC_ALL"))
            or os.environ["APP_ENV"] != "test"
            or any(os.environ[k] != "1" for k in ("PYTHONDONTWRITEBYTECODE", "ROOT_APPROVED_MODEL_DECLARATION"))
            or sys.argv[1:] != ["--export-approved-model-metadata"]
            or sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"
            or Path(sys.executable).absolute().parent != CANDIDATE / "bin"
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)
            or any(k in sys.modules for k in ("site", "sqlalchemy", "pytest", "app"))):
        refuse("argv/environment/interpreter")
    if sha(SELF.read_bytes()) != os.environ["M16_RUNNER_SHA256"]:
        refuse("runner hash")
    cwd = Path(os.environ["M16_EMPTY_CWD"])
    blob = Path(os.environ["M16_BASELINE_BLOB"])
    for path in (cwd, blob):
        if (not path.is_absolute() or ".." in path.parts
                or any(p.is_symlink() for p in (path, *path.parents))
                or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077
                or path.is_relative_to(REPO) or "test" not in str(path)):
            refuse("owned external test paths")
    if (not cwd.is_dir() or any(cwd.iterdir()) or Path.cwd() != cwd or not blob.is_file()
            or not stat.S_ISREG(blob.stat().st_mode) or blob.stat().st_size > MAX_FILE
            or cwd in blob.parents):
        refuse("empty cwd/baseline blob")
    for origin in (cwd, SERVER):
        if any((p / ".env").exists() or (p / ".env").is_symlink() for p in (origin, *origin.parents)):
            refuse("dotenv ancestor")
    if set(COUNTS) != {"app", "tests", "schema_migrations"} or set(COUNTS) != set(DIGESTS):
        refuse("unfrozen source")
    for name in COUNTS:
        if tree(SERVER / name, relative=SERVER, exclude_self=True) != (COUNTS[name], DIGESTS[name]):
            refuse("source tree " + name)
    if any((REPO / name).is_symlink() or not stat.S_ISREG((REPO / name).stat().st_mode)
           or sha((REPO / name).read_bytes()) != digest for name, digest in SUPPORT.items()):
        refuse("support source")
    if sha((SERVER / "app/models.py").read_bytes()) != CANDIDATE_MODEL or sha(blob.read_bytes()) != BASE_MODEL:
        refuse("exact model blobs")
    if (not SITE.is_dir() or SITE.is_symlink()
            or "include-system-site-packages = false" not in (CANDIDATE / "pyvenv.cfg").read_text()
            or any(p.is_symlink() or p.suffix == ".pth" or p.name in {"sitecustomize.py", "usercustomize.py"}
                   for p in SITE.rglob("*"))):
        refuse("candidate site isolation")
    installed = {}
    for dist in importlib.metadata.distributions(path=[str(SITE)]):
        name = dist.metadata["Name"].lower().replace("_", "-").replace(".", "-")
        if name in installed:
            refuse("duplicate distribution")
        installed[name] = dist.version
    if len(RUNTIME) != 61 or len(TOOLS) != 16 or installed != {**RUNTIME, **TOOLS}:
        refuse("exact candidate77")
    if tree(SITE / "sqlalchemy", relative=SITE)[1] != SQLALCHEMY_TREE:
        refuse("SQLAlchemy sources")
    mode = os.environ["M16_MODE"]
    if mode not in {"baseline", "candidate"}:
        refuse("selection")
    return blob if mode == "baseline" else SERVER / "app/models.py", mode, cwd


def boundary(blob):
    denied = []
    roots = (SERVER / "app", SITE, STDLIB)
    exporter = REPO / "clearledger/scripts/export-partner-openapi.py"

    def audit(event, args):
        reason = None
        if (event.startswith(("socket.", "subprocess.", "ctypes."))
                or event in {"os.system", "os.fork", "os.forkpty", "os.exec", "os.posix_spawn", "os.posix_spawnp",
                             "os.mkdir", "os.rmdir", "os.remove", "os.rename", "os.link", "os.symlink", "os.truncate",
                             "os.chmod", "os.chown", "os.utime", "os.putenv", "os.unsetenv"}):
            # The official schema exporter clears its environment to these two
            # inert values. It cannot add configuration or inherit credentials.
            if event == "os.unsetenv":
                return
            if event == "os.putenv" and args in {(b"LANG", b"C.UTF-8"), (b"PYTHONDONTWRITEBYTECODE", b"1")}:
                return
            reason = event
        elif event == "open":
            if not isinstance(args[0], (str, bytes, os.PathLike)):
                reason = "file descriptor open"
            else:
                path = Path(os.fsdecode(args[0])).absolute()
                flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
                if (path.name == ".env" or path.name.startswith(".env.")
                        or {".ssh", ".vault", ".claude"} & set(path.parts)
                        or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                    reason = "secret/write open"
                elif path not in (blob, exporter) and not any(path.is_relative_to(p) for p in roots):
                    reason = "read outside approved sources"
        if reason:
            if len(denied) < 16:
                frames = []
                frame = sys._getframe(1)
                while frame is not None and len(frames) < 8:
                    module = frame.f_globals.get("__name__", "unknown")
                    module = module if isinstance(module, str) and all(c.isalnum() or c in "._" for c in module) else "unknown"
                    frames.append({"module": module[:96], "function": frame.f_code.co_name[:96], "line": frame.f_lineno})
                    frame = frame.f_back
                denied.append({"reason": reason, "event": event, "stack": frames})
            refuse(reason)

    sys.addaudithook(audit)
    return denied


class ModelBlob(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, source):
        self.raw = source.read_bytes()

    def find_spec(self, fullname, path=None, target=None):
        if fullname in BLOCKED or fullname == "app.database" and fullname not in sys.modules:
            refuse("runtime import " + fullname)
        if fullname == "app.models":
            return importlib.util.spec_from_loader(fullname, self, origin=str(SERVER / "app/models.py"))
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = str(SERVER / "app/models.py")
        exec(compile(self.raw, module.__file__, "exec"), module.__dict__)


def snapshot():
    """Explicit schema contract, deliberately fails on unknown nonprimitive data."""
    from datetime import date, datetime, time, timedelta
    from decimal import Decimal
    import enum
    import uuid
    from sqlalchemy import CheckConstraint, Computed, ForeignKeyConstraint, Identity, Sequence
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import CreateEnumType
    from sqlalchemy.orm import ColumnProperty
    from sqlalchemy.schema import (AddConstraint, ColumnDefault, CreateIndex, CreateSequence,
                                   CreateTable, DefaultClause, FetchedValue)
    from sqlalchemy.sql.elements import ClauseElement, quoted_name
    from sqlalchemy.sql.type_api import ExternalType, TypeEngine
    from sqlalchemy.util import get_cls_kwargs

    dialect = postgresql.dialect()

    def kind(value):
        cls = type(value)
        return cls.__module__ + "." + cls.__qualname__

    def code(value):
        # File names/line tables locate source; they are not callable semantics.
        return {"bytecode": value.co_code.hex(), "constants": normal(value.co_consts),
                "names": value.co_names, "varnames": value.co_varnames,
                "freevars": value.co_freevars, "cellvars": value.co_cellvars,
                "argcount": value.co_argcount, "posonly": value.co_posonlyargcount,
                "kwonly": value.co_kwonlyargcount, "flags": value.co_flags,
                "exceptiontable": value.co_exceptiontable.hex()}

    def function(value, depth=0):
        if depth > 12:
            refuse("callable recursion")
        result = {"kind": kind(value), "module": value.__module__, "qualname": value.__qualname__}
        if isinstance(value, types.FunctionType):
            result.update(code=code(value.__code__), defaults=normal(value.__defaults__),
                          kwdefaults=normal(value.__kwdefaults__),
                          closure=[function(c.cell_contents, depth + 1) if callable(c.cell_contents)
                                   else normal(c.cell_contents) for c in (value.__closure__ or ())])
            if hasattr(value, "__wrapped__"):
                result["wrapped"] = function(value.__wrapped__, depth + 1)
        elif isinstance(value, (types.BuiltinFunctionType, types.BuiltinMethodType)):
            bound = getattr(value, "__self__", None)
            if bound is not None and not isinstance(bound, types.ModuleType):
                result["bound_to"] = normal(bound)
        elif not isinstance(value, type):
            refuse("unknown callable " + kind(value))
        return result

    def normal(value):
        if isinstance(value, quoted_name):
            return {"quoted_name": str(value), "quote": value.quote}
        if value is None or type(value) in (str, bool, int, float):
            return value
        if value is Ellipsis:
            return {"ellipsis": True}
        if isinstance(value, bytes):
            return {"bytes": value.hex()}
        if isinstance(value, enum.Enum):
            return {"enum": kind(value), "name": value.name, "value": normal(value.value)}
        if isinstance(value, (tuple, list)):
            return {"tuple" if isinstance(value, tuple) else "list": [normal(v) for v in value]}
        if isinstance(value, (set, frozenset)):
            return {"unordered": sorted((normal(v) for v in value), key=encoded)}
        if isinstance(value, dict):
            # Dict insertion order can matter for naming/defaults: retain it.
            return {"dict": [[normal(k), normal(v)] for k, v in value.items()]}
        if isinstance(value, (date, datetime, time)):
            return {"kind": kind(value), "iso": value.isoformat()}
        if isinstance(value, (Decimal, uuid.UUID, timedelta)):
            return {"kind": kind(value), "value": str(value)}
        if isinstance(value, types.CodeType):
            return {"code": code(value)}
        if isinstance(value, TypeEngine):
            return type_info(value)
        if isinstance(value, ClauseElement):
            return {"kind": kind(value), "sql": str(value.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))}
        if callable(value):
            return function(value)
        refuse("unknown normalizer input " + kind(value))

    def encoded(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def type_cache(value):
        # TypeEngine builds this keyword-state tail by iterating the set from
        # get_cls_kwargs. Only that proven unordered construct is canonicalized.
        cls = type(value)
        descriptor = next((base.__dict__["_static_cache_key"] for base in cls.__mro__
                           if "_static_cache_key" in base.__dict__), None)
        if isinstance(value, ExternalType) or descriptor is not TypeEngine.__dict__["_static_cache_key"]:
            refuse("unknown type cache descriptor")
        raw = value._static_cache_key
        if type(raw) is not tuple or not raw or raw[0] is not cls:
            refuse("unknown type cache shape/sentinel")
        names = get_cls_kwargs(cls)
        if type(names) is not set:
            refuse("constructor keyword set")
        expected = {k for k in names if k in value.__dict__ and not k.startswith("_") and value.__dict__[k] is not None}
        state = {}
        for row in raw[1:]:
            if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                    or row[0] not in expected or row[0] in state):
                refuse("type cache keyword shape/key")
            key, cached = row
            actual = value.__dict__[key]
            original = actual._static_cache_key if isinstance(actual, TypeEngine) else actual
            if cached is not original:
                refuse("type cache constructor value identity")
            state[key] = type_cache(actual) if isinstance(actual, TypeEngine) else normal(cached)
        if set(state) != expected:
            refuse("type cache constructor key coverage")
        return {"class": function(cls), "keyword_state": [[key, state[key]] for key in sorted(state)]}

    def type_info(value):
        attributes = ("length", "collation", "precision", "scale", "decimal_return_scale", "asdecimal",
                      "timezone", "as_uuid", "native_uuid", "none_as_null", "dimensions", "zero_indexes",
                      "as_tuple", "item_type", "enums", "name", "schema", "native_enum", "create_constraint",
                      "validate_strings", "inherit_schema", "create_type", "should_evaluate_none")
        return {"kind": kind(value), "pg": str(value.compile(dialect=dialect)),
                "cache_key": type_cache(value),
                "options": {k: normal(getattr(value, k)) for k in attributes if hasattr(value, k)},
                "variants": normal(value._variant_mapping)}

    def options(value):
        return normal(dict(value.dialect_kwargs))

    def identity(value):
        keys = ("always", "on_null", "start", "increment", "minvalue", "maxvalue", "nominvalue", "nomaxvalue",
                "cycle", "cache", "order", "optional", "data_type", "schema", "name", "quote", "column")
        return {k: normal(getattr(value, k)) for k in keys if hasattr(value, k) and k != "column"}

    def default(value):
        if value is None:
            return None
        result = {"kind": kind(value)}
        if hasattr(value, "for_update"):
            result["for_update"] = value.for_update
        result["flags"] = {k: getattr(value, k) for k in
                           ("is_scalar", "is_callable", "is_clause_element", "is_sequence", "is_server_default", "reflected")
                           if hasattr(value, k)}
        if isinstance(value, Computed):
            result.update(sqltext=normal(value.sqltext), persisted=value.persisted)
        elif isinstance(value, (Identity, Sequence)):
            result["options"] = identity(value)
        elif isinstance(value, (ColumnDefault, DefaultClause, FetchedValue)):
            if hasattr(value, "arg"):
                result["arg"] = normal(value.arg)
        else:
            refuse("unknown default " + kind(value))
        return result

    def foreign(value):
        return {"target": value.target_fullname, "name": normal(value.name), "ondelete": value.ondelete,
                "onupdate": value.onupdate, "deferrable": value.deferrable, "initially": value.initially,
                "use_alter": value.use_alter, "match": value.match, "link_to_name": value.link_to_name,
                "info": normal(value.info)}

    def constraint(value):
        result = {"kind": kind(value), "name": normal(value.name),
                  "columns": [c.key for c in value.columns], "deferrable": value.deferrable,
                  "initially": value.initially, "info": normal(value.info), "dialect": options(value)}
        if isinstance(value, CheckConstraint):
            result["sqltext"] = normal(value.sqltext)
        if isinstance(value, ForeignKeyConstraint):
            result["elements"] = [foreign(f) for f in value.elements]
        return result

    metadata_base = sys.modules["app.database"].Base
    metadata = metadata_base.metadata
    tables = []
    ddl = []
    for key, table in metadata.tables.items():
        columns = []
        for col in table.columns:
            columns.append({"key": col.key, "name": normal(col.name), "type": type_info(col.type),
                            "nullable": col.nullable, "primary_key": col.primary_key,
                            "declared_nullable": normal(col._user_defined_nullable),
                            "unique": col.unique, "index": col.index, "autoincrement": col.autoincrement,
                            "system": col.system, "comment": col.comment, "doc": col.doc,
                            "default": default(col.default), "onupdate": default(col.onupdate),
                            "server_default": default(col.server_default), "server_onupdate": default(col.server_onupdate),
                            "computed": default(col.computed), "identity": default(col.identity),
                            "foreign_keys": sorted((foreign(f) for f in col.foreign_keys), key=encoded),
                            "constraints": sorted((constraint(c) for c in col.constraints), key=encoded),
                            "dialect": options(col), "info": normal(col.info)})
        indexes = [{"name": normal(i.name), "unique": i.unique, "expressions": [normal(e) for e in i.expressions],
                    "dialect": options(i), "info": normal(i.info)} for i in table.indexes]
        indexes.sort(key=encoded)  # table.indexes is a set; expressions retain order.
        tables.append({"key": key, "name": normal(table.name), "schema": normal(table.schema),
                       "columns": columns, "constraints": [constraint(c) for c in table._sorted_constraints],
                       "indexes": indexes, "comment": table.comment, "prefixes": normal(table._prefixes),
                       "dialect": options(table), "info": normal(table.info), "implicit_returning": table.implicit_returning})
        ddl.append({"table": key, "create": str(CreateTable(table).compile(dialect=dialect)),
                    "indexes": sorted(str(CreateIndex(i).compile(dialect=dialect)) for i in table.indexes),
                    "alter_constraints": [str(AddConstraint(c).compile(dialect=dialect))
                                          for c in table._sorted_constraints if getattr(c, "use_alter", False)]})
    sequences = [{"options": identity(s), "ddl": str(CreateSequence(s).compile(dialect=dialect))}
                 for s in metadata._sequences.values()]
    enums = []
    for table in metadata.tables.values():
        for col in table.columns:
            value = col.type
            while hasattr(value, "item_type"):
                value = value.item_type
            if isinstance(value, postgresql.ENUM):
                entry = {"type": type_info(value), "ddl": str(CreateEnumType(value).compile(dialect=dialect))}
                if entry not in enums:
                    enums.append(entry)
    mappers = []
    for mapper in sorted(metadata_base.registry.mappers, key=lambda m: (m.class_.__module__, m.class_.__qualname__)):
        cls = mapper.class_
        mappers.append({"class": cls.__module__ + "." + cls.__qualname__, "table": mapper.local_table.key,
                        "annotations": [[name, str(value)] for name, value in cls.__annotations__.items()],
                        "attributes": [{"key": prop.key, "kind": kind(prop),
                                        "columns": [c.key for c in prop.columns] if isinstance(prop, ColumnProperty) else None}
                                       for prop in mapper.iterate_properties]})
    return {"metadata": {"schema": normal(metadata.schema), "naming_convention": normal(metadata.naming_convention),
                         "info": normal(metadata.info), "tables": tables, "sequences": sequences, "enums": enums},
            "postgresql_ddl": ddl, "orm": mappers,
            "counts": {"tables": len(tables), "columns": sum(len(t["columns"]) for t in tables),
                       "mappers": len(mappers), "sequences": len(sequences), "enums": len(enums)}}


def main():
    blob, mode, cwd = approval()
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    signal.alarm(120)
    # importlib.metadata may inspect every sys.path entry as a ZIP. Discard only
    # the exact nonexistent interpreter ZIP, never permit an additional read.
    if Path(sys.base_prefix).resolve() != STDLIB.parents[1].resolve():
        refuse("stdlib interpreter prefix")
    stdlib_paths = []
    for entry in sys.path:
        path = Path(entry)
        if path == STDLIB.parent / "python313.zip" and not path.exists() and not path.is_symlink():
            continue
        if (not path.is_absolute() or not path.is_dir() or not path.is_relative_to(STDLIB)
                or not path.resolve().is_relative_to(STDLIB.resolve()) or path.is_symlink()):
            refuse("unapproved interpreter search path")
        stdlib_paths.append(str(path))
    sys.path[:] = [str(SERVER), str(SITE), *stdlib_paths]
    denied = boundary(blob)
    sys.meta_path.insert(0, ModelBlob(blob))
    # Use the official schema-only adapter and actual product factory unchanged.
    # Loading the pinned source directly avoids importlib's speculative read of
    # scripts/__pycache__; no additional read roots or bytecode trust is needed.
    source = REPO / "clearledger/scripts/export-partner-openapi.py"
    exporter = types.ModuleType("m16_official_export")
    exporter.__file__ = str(source)
    exec(compile(source.read_bytes(), str(source), "exec"), exporter.__dict__)
    schema = exporter.export_schema()
    for module, expected in zip(MODELS, EXPECTED_CLASSES, strict=True):
        imported = __import__(module, fromlist=["*"])
        source = blob if module == "app.models" else Path(imported.__file__)
        classes = [n for n in ast.parse(source.read_bytes()).body if isinstance(n, ast.ClassDef)
                   and any(isinstance(b, ast.Name) and b.id == "Base" for b in n.bases)]
        if len(classes) != expected or any(not hasattr(getattr(imported, c.name), "__mapper__") for c in classes):
            refuse("complete declarative source coverage")
    result = snapshot()
    if result["counts"]["tables"] != 330 or result["counts"]["mappers"] != 330:
        refuse("all330 mappings")
    result["curated_openapi"] = schema
    blocked = sorted(name for name in BLOCKED if name in sys.modules)
    if denied or blocked or "pytest" in sys.modules:
        sys.stderr.write(json.dumps({"ok": False, "phase": "final_boundary", "denied": denied,
                                     "blocked_modules": blocked, "pytest_imported": "pytest" in sys.modules,
                                     "counts": result["counts"]}, sort_keys=True) + "\n")
        refuse("runtime modules or forbidden activity")
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_OUTPUT:
        refuse("output bound")
    receipt = {"ok": True, "base": BASE, "mode": mode, "model_sha256": sha(blob.read_bytes()),
               "payload_sha256": sha(raw), "payload_bytes": len(raw), "counts": result["counts"],
               "operations": 15, "candidate_distributions": 77, "forbidden_events": denied,
               "network": 0, "sql": 0, "filesystem_writes": 0, "normalization": "explicit-v2"}
    sys.stdout.buffer.write(raw)
    sys.stderr.write(json.dumps(receipt, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
