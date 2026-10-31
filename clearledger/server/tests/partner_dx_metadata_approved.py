"""SOURCE-ONLY authored; ROOT-only future PR82 metadata/schema proof.

Never execute, import, collect, or even invoke --help as a dispatched worker.
ROOT must review this complete source and supply its SHA256, source HEAD and branch
in a fresh CPython 3.13.7 -I -S -B process. Exact argv: --execute-approved-partner-dx.
The separate --execute-approved-partner-dx-kernel-v1 entry requires seven extra
closed environment keys and sealed A; it always reports EXTERNAL_FINAL_PENDING.
Kernel launch capability/controller implementation remain UNKNOWN/NOTRUN.
First use the separately approved --prepare-approved-partner-dx-cache mode in a
Git checkout; ROOT reviews and SHA-pins its external prepare-cache.json. Execute
accepts that sealed cache through DX_PREPARED_CACHE / DX_PREPARED_CACHE_SHA256,
works on an exact source copy without .git and NEVER invokes Git or a host repo.
All required environment keys are enumerated in approval(); invoke through env -i,
preserving the actual HOME. Four precreated empty owned 0700 directories must be
absolute, separate, nonnested and outside the source. No environment/config files.

Only app.database is adapted: a real SQLAlchemy DeclarativeBase, no engine/session.
Real frozen DTOs/models/routes/policies/normalizers and original tests execute.
The checker Git adapter serves only hash-pinned real Git bytes prefetched before
closure; it changes neither checker.git nor any oracle/DTO/source. All other
processes are forbidden after closure, including any second pytest process.

Exports prove pure in-memory schema/DTO construction only. Synthetic callbacks,
disabled settings and the database import adapter are explicitly NOT runtime
coverage. 20M + 11 gates remain UNPROVEN; SDK generation/freshness remain NOTRUN.
This file was only AST-parsed/in-memory-compiled by its author: runtime=0.
No receipt, a nonzero exit, or a rejected artifact admission is a failed run;
ROOT must census external evidence after a fatal limit/OS termination. Never
interpret a partial output/JUnit/schema artifact alone as a successful run.
"""
from __future__ import annotations

import ast
import base64
import contextlib
import email.parser
import errno
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import posix
import posixpath
import pwd
import re
import resource
import _signal
import signal
import stat
import _thread
import subprocess
import sys
import tempfile
import time
import traceback
import types
import xml.etree.ElementTree as ET
from copy import deepcopy

SELF = Path(__file__).absolute()
SERVER = SELF.parents[1]
REPO = SERVER.parents[1]
BASE = "725bee174f40b7155c87c38493b0581138da3ef0"
CHECKER_BASE = "cec2c9845431a0bc07e4b4f115eb21eed8d5caa9"
PREFIX = Path("/srv/projects/api-modernization-upgrade-test-env-20261030/.venv")
SITE = PREFIX / "lib/python3.13/site-packages"
STDLIB = Path("/home/mag/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu/lib/python3.13")
TESTS = ("test_partner_dx_metadata_20261031", "test_partner_dx_examples_20261031")
MiB = 1024 * 1024
MAX_FILE = 16 * MiB
MAX_OUTPUT = 8 * MiB
MAX_ARTIFACT_BYTES = 64 * MiB
MAX_ENTRIES = 20000
MAX_TREE_BYTES = 256 * MiB
WALL_SECONDS = 180
FREE_FLOOR = 8 * 1024 ** 3
EVIDENCE_NAMES = {"receipt.json", "phases.json", "imports.json", "junit.xml", "pytest-output.txt",
                  "canonical.json", "browser.json", "registry.json", "schema-checks.json", "prepare-cache.json"}
BLOCKED_ROOTS = {"asyncpg", "psycopg", "psycopg2", "aiosqlite", "sqlite3", "smtplib", "aiosmtplib",
                 "requests", "httpx", "httpcore", "aiohttp", "pywebpush", "uvicorn", "gunicorn",
                 "dotenv", "pydantic_settings", "multiprocessing"}

FROZEN = {'app': {'count': 504, 'bytes': 17249730, 'sha256': 'a2766d51aaaa9c684357005e411914b928f508b02d5b1f1da93a9ef77dcaf84f'}, 'tests': {'count': 397, 'bytes': 5741903, 'sha256': 'a78fc8de5d574724cf8da8d8d492315c131245ceca56209fd85aa32e8662d979'}, 'schema_migrations': {'count': 24, 'bytes': 107419, 'sha256': '2fd1936ae592fcd65ca8878e9797c8fb3579aaa77e7f62ee6b0d9db96f6305a4'}}

SUPPORT = {'clearledger/scripts/export-partner-openapi.py': 'b5d52daca7220a523b4c5edc85852de39b0b921e5c033a86029b2f92040abd51', 'clearledger/scripts/verify_partner_dx_metadata_20261031.py': '5f0a5b9c6ebca6aee437d060ac4558eb890be4e9f1cf0de6f6bd05510f8a728b', 'clearledger/server/pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601', 'clearledger/server/requirements-test.txt': 'c08b4e024359be3200ac0c6a56490b795de88ce7f4f812e5b23896ece31dfe0c', 'clearledger/server/requirements-upgrade-20261030.in': '90e92d607c5f3c966f5dca129461d92fdfc2a094e5b3a77e5e211ad5dc4d8caf', 'clearledger/server/requirements.in': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'clearledger/server/requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'clearledger/tools/partner-api-types/consumer.ts': '28b26158dbd0c8e6054cae74db3927210031d0dea695107537cc431bde7bc047', 'clearledger/tools/partner-api-types/contract-classification-consumer.ts': '2efa77f5787fe94c7d7868ac8b9d4aa95e9444dcdb774e5cc7b2000dadab48d6', 'clearledger/tools/partner-api-types/contract-documents-consumer.ts': '9daeb839e1d163dc5fe42dfeede3b1f6ee63854e16ebde3cdb0ce9f2f2150dfe', 'clearledger/tools/partner-api-types/contract-objects-consumer.ts': 'c17746e21cc13a996eca173f6adbe3be7ebc96ad5cddff6511eec1215bfb0ba0', 'clearledger/tools/partner-api-types/generate.mjs': '549d7f05625af2906b4cd44b44f571b5c935ea195490d52d530da5e08fe53817', 'clearledger/tools/partner-api-types/generation.test.mjs': 'af7e5a544a2247ef0269fae323c928d411e0d89166f85113d71099204a599266', 'clearledger/tools/partner-api-types/package-lock.json': 'c7f9ba06a2e02383cc7409b071fea099a03df4ad796287de249d9250a0d292ac', 'clearledger/tools/partner-api-types/package.json': '900597c5e189affc56dc83b662a84e77b149de8177302ebe07b05954bf61f380', 'clearledger/tools/partner-api-types/tsconfig.json': '02f89cf9edfb497dde5d5c8d904de6f4b223e048fad9213c5de9e40edd11998d'}

BINDINGS = {'app': ['clearledger/server/app/__init__.py', 'd84d28eab65da2fab2d297c3060360b230e2464cc4481eae999dfb96a85fd6f9'], 'app.api_contracts': ['clearledger/server/app/api_contracts/__init__.py', '41bacd6a77dfcf24ec096e1c0df8fd8130bdeb4d8a1fc9a35be66a281a45252b'], 'app.api_contracts.context': ['clearledger/server/app/api_contracts/context.py', '050bc438db8bd36794b59cb741000b7745edad2a33787a00a4663f159f467154'], 'app.api_contracts.routing': ['clearledger/server/app/api_contracts/routing.py', '131f3bb5daebfd0631296999aef646449bfd02eddeea7b22e21887e30f2e48c0'], 'app.models': ['clearledger/server/app/models.py', 'ffd2c8a1231ca306bf5d569481d3c8e13b81e8a13ce312f8d39978da0e682682'], 'app.models_product_budget': ['clearledger/server/app/models_product_budget.py', 'ea09966027934d4455770c6fdddc62d6d3ccd943f8923d47e3f1a3c7153de864'], 'app.security_context': ['clearledger/server/app/security_context.py', '84acb1eca49f2a24b34fed48b5fb445dd5271887ef971a042286275c63564e4c'], 'app.product_api': ['clearledger/server/app/product_api/__init__.py', '2f2a457b4d3e891c6de506eea638364f429384fd1f325309feab2edd94b5fb7f'], 'app.product_api.access': ['clearledger/server/app/product_api/access.py', 'f6014e3cda1561da640ebd66b8a46ad63830660baa2581a4b605d880dc890ed2'], 'app.product_api.app': ['clearledger/server/app/product_api/app.py', 'c82da8d35b3ca301a93445a667a44bb861d2f2d2ace9fc3c08aac87a3ccab774'], 'app.product_api.budget': ['clearledger/server/app/product_api/budget.py', 'ad454225d15b1696432c4409886437bfee7d03a66543918006b84a5f0a28eee4'], 'app.product_api.dto': ['clearledger/server/app/product_api/dto.py', '4483753b34db18912cae8102c84550038ddd42c711ffeeac49840ce5764cf94c'], 'app.product_api.files': ['clearledger/server/app/product_api/files.py', 'c8ba2492de431c316bfa3659fc9e6e8187f7c24058483d9fdfb766bf306af958'], 'app.product_api.monitoring': ['clearledger/server/app/product_api/monitoring.py', '9810a3a6b9b24c7d4424676194968d98bd28f9c589e2a12efe6420efd8bda3eb'], 'app.product_api.queries': ['clearledger/server/app/product_api/queries.py', 'cf8757ce4af40410cd5a3fb0c0737d5fffcd3ec2e5e2f866a6234eb328a6a713'], 'app.services': ['clearledger/server/app/services/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'], 'app.services.ops_monitor_context': ['clearledger/server/app/services/ops_monitor_context.py', '385201248f5f4711266034342a0eef8b552b22ece4f0abc05b5445df8cce8625'], 'app.services.session_scope': ['clearledger/server/app/services/session_scope.py', '87df5f6a422680208faaaea051cf134cc3c4d141b1262a6bfc4bbb96227c2a04'], 'test_partner_dx_metadata_20261031': ['clearledger/server/tests/test_partner_dx_metadata_20261031.py', '70d9d6bdaaeb0d7ef2d8fdfe88dc8016e603715307cbe6ef190ec682dea60463'], 'test_partner_dx_examples_20261031': ['clearledger/server/tests/test_partner_dx_examples_20261031.py', 'ed7caa5eeeb38d4ce4cde41557bda5216224fe12217f3e9b366d2f40bd039019'], 'partner_dx_source_checker_20261031': ['clearledger/scripts/verify_partner_dx_metadata_20261031.py', '5f0a5b9c6ebca6aee437d060ac4558eb890be4e9f1cf0de6f6bd05510f8a728b'], 'tests': ['clearledger/server/tests/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855']}

GIT_CACHE_SHA = {('ls-files', 'clearledger/server/app/product_api', 'clearledger/server/app/api_contracts'): '368b1342118ca5251a4a4889bf69de54405b62256ea45b8464b00557a84389f8', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/api_contracts/__init__.py'): '41bacd6a77dfcf24ec096e1c0df8fd8130bdeb4d8a1fc9a35be66a281a45252b', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/api_contracts/context.py'): '050bc438db8bd36794b59cb741000b7745edad2a33787a00a4663f159f467154', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/api_contracts/routing.py'): '131f3bb5daebfd0631296999aef646449bfd02eddeea7b22e21887e30f2e48c0', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/__init__.py'): '2f2a457b4d3e891c6de506eea638364f429384fd1f325309feab2edd94b5fb7f', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/access.py'): 'f6014e3cda1561da640ebd66b8a46ad63830660baa2581a4b605d880dc890ed2', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/app.py'): '863060da6b31c21fc2c34a7340c9a9f6223c955c106dae2a6eb776e385eaa886', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/budget.py'): 'ad454225d15b1696432c4409886437bfee7d03a66543918006b84a5f0a28eee4', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/dto.py'): 'c0dce6e13762d6d51d3f95bffd6d80850463d90f7727b692a0ad51ba55023c98', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/files.py'): 'c8ba2492de431c316bfa3659fc9e6e8187f7c24058483d9fdfb766bf306af958', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/monitoring.py'): '9810a3a6b9b24c7d4424676194968d98bd28f9c589e2a12efe6420efd8bda3eb', ('show', 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9:clearledger/server/app/product_api/queries.py'): 'cf8757ce4af40410cd5a3fb0c0737d5fffcd3ec2e5e2f866a6234eb328a6a713'}

PINNED_DISTRIBUTIONS = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1', 'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}

FROZEN_SITE = {'count': 7245, 'bytes': 169999373, 'sha256': '49071b9c07b1fe65baf287e952e9b3c98907ee92f9434c0f30d151d513f8bec2'}

VENV_CFG_SHA = 'e4664ed8e14b41d8f0e039d00f86c45817af9fc89befc9c6eee8bf1aa5a47db7'

# Preserve the native object: a prebound alias must meet the same c_call gate.
NATIVE_OPEN = posix.open
NATIVE_SIGNAL_CONTROLS = (_signal.signal, _signal.alarm, _signal.setitimer, _signal.pthread_sigmask)
NATIVE_THREAD_STARTS = (_thread.start_new_thread, _thread.start_joinable_thread)
NATIVE_EXIT = posix._exit


def require(value, reason):
    if not value:
        raise RuntimeError("partner-DX ROOT gate: " + reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def lexical(path):
    require(isinstance(path, (str, bytes, os.PathLike)), "path type")
    result = Path(os.path.abspath(os.fsdecode(path)))
    require(not any(p.is_symlink() for p in (result, *result.parents)), "ANY path symlink")
    return result


def bounded_bytes(path, limit=MAX_FILE):
    path = lexical(path)
    require(path.name != ".env" and not path.name.startswith(".env.")
            and not {".ssh", ".vault", ".claude"} & set(path.parts), "never read real config/secrets, including preclosure")
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "regular file/byte bound " + path.name)
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) == info.st_size and len(raw) <= limit, "stable bounded file read")
    return raw


def tree(root, relative, *, exclude_self=False):
    root = lexical(root)
    rows, bindings, count, total = [], {}, 0, 0
    # Walk incrementally; never construct an unbounded rglob list before a guard.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            count += 1
            require(count <= MAX_ENTRIES and not path.is_symlink(), "ANY tree symlink/entry bound")
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), "nonregular tree entry")
        for name in sorted(files):
            path = Path(directory) / name
            if exclude_self and path == SELF:
                continue
            raw = bounded_bytes(path)
            total += len(raw)
            rows.append([str(path.relative_to(relative)), len(raw), sha(raw)])
            bindings[str(path)] = sha(raw)
            require(total <= MAX_TREE_BYTES, "tree aggregate bytes")
    rows.sort()
    return {"count": len(rows), "bytes": sum(row[1] for row in rows),
            "sha256": sha(json.dumps(rows, separators=(",", ":")).encode())}, bindings


def inventory():
    signature, bindings = tree(SITE, SITE)
    require(signature == FROZEN_SITE, "full installed source/native/data bindings")
    require(sha(bounded_bytes(PREFIX / "pyvenv.cfg")) == VENV_CFG_SHA, "venv config binding")
    require("include-system-site-packages = false" in bounded_bytes(PREFIX / "pyvenv.cfg").decode(), "isolated venv")
    installed = {}
    for path in sorted(SITE.glob("*.dist-info/METADATA")):
        msg = email.parser.BytesParser().parsebytes(bounded_bytes(path))
        name = msg["Name"].lower().replace("_", "-").replace(".", "-")
        require(name not in installed, "duplicate distribution")
        installed[name] = msg["Version"]
    require(len(installed) == 77 and installed == PINNED_DISTRIBUTIONS, "exact77 versions")
    require(not any(p.endswith((".pth", "/sitecustomize.py", "/usercustomize.py")) for p in bindings), "no site customization")
    return {"signature": signature, "versions": installed}, bindings


def sources():
    signature, bindings = {}, {}
    for name in FROZEN:
        signature[name], current = tree(SERVER / name, SERVER, exclude_self=True)
        bindings.update(current)
    require(signature == FROZEN, "full base725 app/tests/schema manifest (no extra/missing files)")
    for relative, digest in SUPPORT.items():
        path = REPO / relative
        require(sha(bounded_bytes(path)) == digest, "support hash " + relative)
        bindings[str(path)] = digest
    require(sha(bounded_bytes(SELF)) == os.environ["DX_RUNNER_SHA256"], "self separate hash")
    return signature, bindings


def expected_ids():
    """Derive pytest default string IDs from the frozen original AST, not test counts."""
    result, definitions = [], []
    for module in TESTS:
        path = SERVER / "tests" / (module + ".py")
        require(sha(bounded_bytes(path)) == BINDINGS[module][1], "frozen test source")
        parsed = ast.parse(bounded_bytes(path), filename=str(path))
        for node in parsed.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            definitions.append(module + "::" + node.name)
            require(isinstance(node, ast.FunctionDef), "review synchronous original definitions only")
            params = []
            for decorator in node.decorator_list:
                require(isinstance(decorator, ast.Call) and ast.unparse(decorator.func) == "pytest.mark.parametrize"
                        and len(decorator.args) == 2 and not decorator.keywords, "unreviewed test decorator")
                names = ast.literal_eval(decorator.args[0]).split(",")
                values = ast.literal_eval(decorator.args[1])
                require(isinstance(values, list) and values, "literal parameter cases")
                for row in values:
                    cells = (row,) if len(names) == 1 else row
                    require(isinstance(cells, (tuple, list)) and len(cells) == len(names)
                            and all(type(cell) is str and cell.isascii() and all(c.isalnum() or c == "_" for c in cell)
                                    for cell in cells), "reviewed default string parameter IDs")
                    params.append("-".join(cells))
            require(len(node.decorator_list) <= 1 and len(params) == len(set(params)), "no stacked/duplicate parameter IDs")
            prefix = "tests/" + module + ".py::" + node.name
            result.extend(prefix + "[" + value + "]" for value in params) if params else result.append(prefix)
    require(len(definitions) == 12 and len(result) == 26 and len(set(result)) == 26
            and sum("test_partner_dx_metadata_" in node for node in result) == 19, "frozen12 definitions/26 cases=19+7")
    return result


def private_empty(name):
    path = Path(os.environ[name])
    require(path.is_absolute() and ".." not in path.parts and lexical(path) == path, "literal absolute private directory")
    info = path.stat()
    require(path.is_dir() and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
            and not any(path.iterdir()), "owned empty0700 " + name)
    require(not path.is_relative_to(REPO), "directory outside source")
    return path


def legacy_approval():
    require(sys.argv[1:] in (["--execute-approved-partner-dx"], ["--prepare-approved-partner-dx-cache"]),
            "exact opt-in; no default/help execution")
    mode = "prepare" if sys.argv[1] == "--prepare-approved-partner-dx-cache" else "execute"
    fixed = {"ROOT_APPROVED_PARTNER_DX": "1", "RUN_PARTNER_DX_METADATA": "1",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    variable = {"HOME", "DX_RUNNER_SHA256", "DX_SOURCE_HEAD", "DX_SOURCE_BRANCH",
                "DX_EMPTY_CWD", "DX_EVIDENCE_DIR", "DX_SCRATCH_DIR", "DX_UPLOAD_DIR"}
    if mode == "execute":
        variable |= {"DX_PREPARED_CACHE", "DX_PREPARED_CACHE_SHA256"}
    require(set(os.environ) == set(fixed) | variable and all(os.environ[k] == v for k, v in fixed.items()),
            "exact clean environment (env -i; no real settings/secrets)")
    require(os.environ["HOME"] == pwd.getpwuid(os.getuid()).pw_dir, "actual HOME preserved")
    require(sys.version_info[:3] == (3, 13, 7) and sys.flags.isolated and sys.flags.no_site
            and sys.flags.dont_write_bytecode and not sys.flags.optimize and sys.prefix == sys.base_prefix,
            "CPython3.13.7 -I -S -B no optimization")
    require(sys.executable == str(PREFIX / "bin/python") and Path(sys.executable).resolve() == STDLIB.parents[1] / "bin/python3.13",
            "existing approved native interpreter")
    require(not any(name in sys.modules for name in ("app", "pytest", "site", "pydantic", "sqlalchemy"))
            and not any("site-packages" in path or path == "" for path in sys.path), "stdlib only before gate")
    require(sha(bounded_bytes(SELF)) == os.environ["DX_RUNNER_SHA256"], "ROOT-reviewed full self SHA")
    directories = {name: private_empty(name) for name in
                   ("DX_EMPTY_CWD", "DX_EVIDENCE_DIR", "DX_SCRATCH_DIR", "DX_UPLOAD_DIR")}
    values = list(directories.values())
    require(Path.cwd() == directories["DX_EMPTY_CWD"] and len(set(values)) == 4
            and not any(a != b and a.is_relative_to(b) for a in values for b in values), "four separate nonnested directories")
    for root in (REPO, *values):
        for ancestor in (root, *root.parents):
            require(not (ancestor / ".env").exists() and not (ancestor / ".env").is_symlink(), "no ancestor dotenv")
        require(os.statvfs(root).f_bavail * os.statvfs(root).f_frsize >= FREE_FLOOR, "free floor8GiB")
    require(sys.getprofile() is None and sys.gettrace() is None, "no preexisting tracing hooks")
    os.umask(0o077)
    return mode, directories


# Kernel v1 is an additional SOURCE-only admission path. These Python diagnostics
# are not an OS sandbox or proof of the installed BPF/controller/image. Only the
# trusted external controller can accept safety with F; this candidate emits no F.
KERNEL = None
KERNEL_EXTRA_ENV = frozenset({"DX_EXECUTION_MODE", "DX_ADMISSION_RECEIPT", "DX_ADMISSION_RECEIPT_SHA256",
                              "DX_WORKLOAD_NONCE", "DX_KERNEL_POLICY_SHA256", "DX_EXPECTED_UID", "DX_EXPECTED_GID"})
KERNEL_ADMISSION_PATH = "/inputs/admission/admission.json"
KERNEL_POLICY_PATH = "/inputs/policy/execute-policy.json"
KERNEL_JSON_LIMIT = 65536
KERNEL_PROC_LIMIT = 131072

# Closed literal type grammar, mirrored by PARTNER_DX_KERNEL_ADMISSION_V1.schema.json.
# No third-party validator/import is used before the existing framework boundary.
KERNEL_SHAPES = {
    "A": {
        "format": ("const", "elsy.partner-dx.kernel-admission.v1"), "phase": ("const", "ADMISSION"),
        "clock": ("const", "CLOCK_MONOTONIC_MS"), "nonce": "H", "issued_ms": "N", "expires_ms": "N",
        "candidate": "Candidate", "bindings": "Bindings", "namespaces": "Namespaces",
        "mounts": ("list", "Mount", 12, 12), "quota": "Quota", "host_floor": "HostFloor", "controller": "Controller",
    },
    "Candidate": {
        "uid": "N", "gid": "N", "supplementary_gids": ("list", "N", 0, 0), "home": "P",
        "no_new_privs": ("const", 1), "seccomp_mode": ("const", 2),
        "cap_inh": ("const", "0000000000000000"), "cap_prm": ("const", "0000000000000000"),
        "cap_eff": ("const", "0000000000000000"), "cap_bnd": ("const", "0000000000000000"),
        "cap_amb": ("const", "0000000000000000"),
    },
    "Bindings": {
        "runner_sha256": "H", "source_head": "G", "source_branch": "Branch", "app_sha256": "H",
        "tests_sha256": "H", "migrations_sha256": "H", "support_sha256": "H", "native_site_sha256": "H",
        "versions_sha256": "H", "prepared_cache_sha256": "H", "policy_sha256": "H", "controller_sha256": "H",
        "image_digest": "Image",
    },
    "Namespaces": {
        "mnt": "D", "net": "D", "pid": "D", "ipc": "D", "user": "D", "time": "D",
        "controller_mnt": "D", "controller_net": "D", "controller_pid": "D", "controller_ipc": "D",
        "controller_user": "D", "controller_time": "D", "mountinfo_sha256": "H",
    },
    "Mount": {
        "role": ("enum", ("rootfs", "source", "native_runtime", "venv", "policy", "admission", "cache",
                           "work_pool", "cwd", "upload", "evidence", "scratch")),
        "path": "P", "mount_id": "N", "major": "N", "minor": "N", "root": "P", "mount_point": "P",
        "fs_type": ("ascii", 1, 32), "read_only": "Bool", "owner_uid": "N", "owner_gid": "N", "mode": "O",
    },
    "Quota": {
        "kind": ("const", "shared-tmpfs-v1"), "pool_mount_id": "N", "max_bytes": ("const", 67108864),
        "max_inodes": ("const", 133), "max_regular_entries": ("const", 128),
        "file_max_bytes": ("const", 16777216), "hardlinks": ("const", "DENY_KERNEL_POLICY"),
    },
    "HostFloor": {
        "threshold_bytes": ("const", 8589934592), "before": ("list", "HostSample", 1, 8),
        "monitor_interval_ms": ("const", 1000), "max_sample_gap_ms": ("const", 1500),
        "on_failure": ("const", "KILL_AND_REJECT"), "after_required": ("const", True),
    },
    "HostSample": {"storage_id": ("ascii", 1, 128), "measured_ms": "N", "free_bytes": "N"},
    "Controller": {
        "euid": "N", "policy_path": ("const", "/inputs/policy/execute-policy.json"),
        "admission_sealed": ("const", True), "kernel_policy_loaded": ("const", True),
        "external_watchdog_armed": ("const", True), "wall_ms": ("const", 180000),
        "stdout_stderr_max_bytes": ("const", 8388608), "cpu_hard_seconds": ("const", 150),
        "memory_max_bytes": ("const", 2147483648), "file_hard_bytes": ("const", 16777216),
        "fd_hard_limit": ("const", 96), "pids_max": ("const", 1),
    },
    "F": {
        "format": ("const", "elsy.partner-dx.kernel-final.v1"), "phase": ("const", "FINAL"),
        "clock": ("const", "CLOCK_MONOTONIC_MS"), "nonce": "H", "admission_sha256": "H", "policy_sha256": "H",
        "runner_sha256": "H", "source_head": "G", "exit_code": "N", "termination_signal": "N",
        "host_floor": "FinalHostFloor", "output_bytes": "N", "artifacts_manifest_sha256": "H",
        "source_before_sha256": "H", "source_after_sha256": "H", "runtime_before_sha256": "H",
        "runtime_after_sha256": "H", "decision": ("enum", ("SAFETY_ACCEPTED", "REJECTED")),
    },
    "FinalHostFloor": {
        "storage_results": ("list", "StorageResult", 1, 8), "status": ("enum", ("PASS", "FAIL")),
    },
    "StorageResult": {
        "storage_id": ("ascii", 1, 128), "before_free": "N", "minimum_observed_during_free": "N", "after_free": "N",
        "samples": "N", "max_gap_ms": "N",
    },
}
KERNEL_PATTERNS = {
    "H": "[0-9a-f]{64}", "G": "[0-9a-f]{40}", "D": "[1-9][0-9]*", "O": "[0-7]{4}",
    "P": "/[A-Za-z0-9._/-]*", "Branch": "[A-Za-z0-9._/-]{1,200}", "Image": "sha256:[0-9a-f]{64}",
}


def kernel_canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


def kernel_shape(value, shape):
    if isinstance(shape, tuple):
        kind = shape[0]
        if kind == "const":
            require(type(value) is type(shape[1]) and value == shape[1], "kernel exact typed constant")
        elif kind == "enum":
            require(type(value) is str and value in shape[1], "kernel enum")
        elif kind == "ascii":
            require(type(value) is str and value.isascii() and shape[1] <= len(value) <= shape[2], "kernel ASCII string")
        elif kind == "list":
            require(type(value) is list and shape[2] <= len(value) <= shape[3], "kernel array bound")
            for item in value:
                kernel_shape(item, shape[1])
        else:
            require(False, "unknown kernel grammar")
    elif shape in KERNEL_SHAPES:
        fields = KERNEL_SHAPES[shape]
        require(type(value) is dict and set(value) == set(fields), "kernel closed fields " + shape)
        for name, descriptor in fields.items():
            kernel_shape(value[name], descriptor)
    elif shape == "N":
        require(type(value) is int and 0 <= value <= 2 ** 63 - 1, "kernel integer0..2^63-1 (not bool)")
    elif shape == "Bool":
        require(type(value) is bool, "kernel bool")
    else:
        require(type(value) is str and re.fullmatch(KERNEL_PATTERNS[shape], value, flags=re.ASCII) is not None,
                "kernel string grammar " + shape)
        if shape == "P":
            require(posixpath.normpath(value) == value and not value.startswith("//")
                    and ".." not in value.split("/"), "kernel normalized absolute POSIX path")


def kernel_no_float(value):
    raise RuntimeError("partner-DX ROOT gate: kernel JSON floats/NaN/Infinity forbidden")


def kernel_json(raw, shape):
    require(0 < len(raw) <= KERNEL_JSON_LIMIT, "kernel receipt65536 byte bound")
    value = json.loads(raw.decode("ascii"), object_pairs_hook=unique_object,
                       parse_float=kernel_no_float, parse_constant=kernel_no_float)
    kernel_shape(value, shape)
    require(raw == kernel_canonical(value), "kernel canonical ASCII sorted JSON with exactly one LF")
    return value


def kernel_path(value):
    kernel_shape(value, "P")
    path = Path(value)
    require(lexical(path) == path, "kernel path without ANY symlink")
    return path


class KernelAdmission:
    def __init__(self, directories):
        self.directories = directories
        self.proc_frame = None
        self.proc_function = type(self).proc_bytes
        self.proc_code = self.proc_function.__code__
        self.proc_globals = self.proc_function.__globals__
        self.diagnostic_functions = tuple((name, getattr(type(self), name), getattr(type(self), name).__code__)
                                          for name in ("identity_check", "verify", "mounts_read", "storage_check"))
        self.admission_path = kernel_path(os.environ["DX_ADMISSION_RECEIPT"])
        require(str(self.admission_path) == KERNEL_ADMISSION_PATH, "fixed admission path")
        self.policy_path = kernel_path(KERNEL_POLICY_PATH)
        self.cache_path = kernel_path(os.environ["DX_PREPARED_CACHE"])
        self.pool = next(iter(directories.values())).parent
        self.uid, self.gid = (int(os.environ[key]) for key in ("DX_EXPECTED_UID", "DX_EXPECTED_GID"))
        raw = bounded_bytes(self.admission_path, KERNEL_JSON_LIMIT)
        self.admission_sha256 = sha(raw)
        require(self.admission_sha256 == os.environ["DX_ADMISSION_RECEIPT_SHA256"], "independent raw SHA(A) including LF")
        self.a = kernel_json(raw, "A")
        self.external_state = {str(self.admission_path): self.admission_sha256,
                               str(self.policy_path): os.environ["DX_KERNEL_POLICY_SHA256"]}
        self.bindings_check()
        self.startup_freshness()
        ids = []
        for sample in self.a["host_floor"]["before"]:
            require(sample["free_bytes"] >= FREE_FLOOR
                    and 0 <= self.a["issued_ms"] - sample["measured_ms"] <= 1000,
                    "external physical storage pre-sample floor/freshness1000ms")
            ids.append(sample["storage_id"])
        require(len(ids) == len(set(ids)), "distinct external physical storage IDs")
        self.verify()

    def startup_freshness(self):
        # Startup only, repeated after expensive source/site preflight and before
        # closure/import. Post-run verification deliberately never calls this.
        now_ms = time.monotonic_ns() // 1000000
        require(self.a["issued_ms"] <= now_ms <= self.a["expires_ms"]
                and self.a["expires_ms"] - self.a["issued_ms"] <= 30000, "startup monotonic admission freshness30s")

    def bindings_check(self):
        a, b = self.a, self.a["bindings"]
        for key in ("DX_RUNNER_SHA256", "DX_PREPARED_CACHE_SHA256", "DX_KERNEL_POLICY_SHA256",
                    "DX_ADMISSION_RECEIPT_SHA256", "DX_WORKLOAD_NONCE"):
            kernel_shape(os.environ[key], "H")
        kernel_shape(os.environ["DX_SOURCE_HEAD"], "G")
        kernel_shape(os.environ["DX_SOURCE_BRANCH"], "Branch")
        require(a["nonce"] == os.environ["DX_WORKLOAD_NONCE"] and b["runner_sha256"] == os.environ["DX_RUNNER_SHA256"]
                and b["source_head"] == os.environ["DX_SOURCE_HEAD"] and b["source_branch"] == os.environ["DX_SOURCE_BRANCH"]
                and b["prepared_cache_sha256"] == os.environ["DX_PREPARED_CACHE_SHA256"]
                and b["policy_sha256"] == os.environ["DX_KERNEL_POLICY_SHA256"], "kernel independent launcher pins")
        require(b["app_sha256"] == FROZEN["app"]["sha256"] and b["tests_sha256"] == FROZEN["tests"]["sha256"]
                and b["migrations_sha256"] == FROZEN["schema_migrations"]["sha256"]
                and b["native_site_sha256"] == FROZEN_SITE["sha256"]
                and b["support_sha256"] == sha(kernel_canonical(SUPPORT))
                and b["versions_sha256"] == sha(kernel_canonical(PINNED_DISTRIBUTIONS)), "kernel full frozen manifest bindings")
        # controller_sha256/image_digest are sealed external attestations, NOT a
        # self-proof of controller identity or of the installed seccomp BPF hash.

    def proc_bytes(self, name):
        paths = {"status": "/proc/self/status", "mountinfo": "/proc/self/mountinfo"}
        require(name in paths and self.proc_frame is None, "fixed nonrecursive kernel diagnostic")
        path = paths[name]
        self.proc_frame = sys._getframe()
        try:
            # Proc reports st_size=0: bounded read, never regular-file bounded_bytes.
            with open(path, "rb") as stream:
                raw = stream.read(KERNEL_PROC_LIMIT + 1)
            require(0 < len(raw) <= KERNEL_PROC_LIMIT, "fixed proc read131072 byte bound")
            return raw
        finally:
            self.proc_frame = None

    def diagnostic_open(self, args, boundary):
        frame = sys._getframe(2)  # audit -> diagnostic_open; exact proc_bytes caller.
        exact_reader = (boundary.kernel is self
                and frame is self.proc_frame and frame.f_code is self.proc_code
                and type(self).proc_bytes is self.proc_function and self.proc_function.__code__ is self.proc_code
                and self.proc_function.__globals__ is self.proc_globals and frame.f_globals is self.proc_globals
                and frame.f_locals.get("self") is self and frame.f_locals.get("path") == args[0]
                and type(args[0]) is str and args[0] in ("/proc/self/status", "/proc/self/mountinfo")
                and args[1] == "r" and type(args[2]) is int
                and args[2] == (os.O_RDONLY | os.O_CLOEXEC))
        if not exact_reader or not all(getattr(type(self), name) is function and function.__code__ is code
                                       and function.__globals__ is self.proc_globals
                                       for name, function, code in self.diagnostic_functions):
            return False
        codes = {name: code for name, function, code in self.diagnostic_functions}
        parent = frame.f_back
        if args[0] == "/proc/self/status":
            chain = ("identity_check", "verify")
        else:
            chain = ("mounts_read", "storage_check")
        for name in chain:
            if (parent is None or parent.f_code is not codes[name] or parent.f_globals is not self.proc_globals
                    or parent.f_locals.get("self") is not self):
                return False
            parent = parent.f_back
        if args[0] == "/proc/self/status":
            return boundary.phase == "postcheck"
        # Storage admission also runs from run_pytest/write_json before postcheck.
        # Permit only this exact source chain, not arbitrary proc reads by tests.
        return (parent is not None and parent.f_globals is self.proc_globals and (
            parent.f_code is codes["verify"] and parent.f_locals.get("self") is self and boundary.phase == "postcheck"
            or parent.f_code is artifact_scan.__code__ and parent.f_locals.get("directories") is self.directories
            and boundary.phase in {"pytest", "postcheck"}))

    def identity_check(self):
        fields = {}
        for line in self.proc_bytes("status").decode("ascii").splitlines():
            name, separator, value = line.partition(":")
            require(separator and name not in fields, "unique proc status fields")
            fields[name] = value.strip()
        candidate = self.a["candidate"]
        require(self.uid > 0 and self.gid > 0 and candidate["uid"] == self.uid and candidate["gid"] == self.gid,
                "nonroot exact expected candidate UID/GID")
        require(os.getuid() == os.geteuid() == self.uid and os.getresuid() == (self.uid,) * 3
                and fields["Uid"].split() == [str(self.uid)] * 4, "real/effective/saved/fs UID match")
        require(os.getgid() == os.getegid() == self.gid and os.getresgid() == (self.gid,) * 3
                and fields["Gid"].split() == [str(self.gid)] * 4, "real/effective/saved/fs GID match")
        require(os.getgroups() == [] and fields["Groups"].split() == [] and candidate["supplementary_gids"] == [],
                "no supplementary groups")
        require(str(kernel_path(candidate["home"])) == os.environ["HOME"] == pwd.getpwuid(self.uid).pw_dir,
                "candidate actual HOME without symlinks")
        require(fields["NoNewPrivs"] == "1" and fields["Seccomp"] == "2", "actual NoNewPrivs1/Seccomp2")
        for receipt_key, status_key in (("cap_inh", "CapInh"), ("cap_prm", "CapPrm"), ("cap_eff", "CapEff"),
                                        ("cap_bnd", "CapBnd"), ("cap_amb", "CapAmb")):
            require(fields[status_key] == candidate[receipt_key] == "0000000000000000", "actual zero " + status_key)
        ns = self.a["namespaces"]
        # Fixed readlink names only; no arbitrary proc path or namespace traversal.
        for name, path in (("mnt", "/proc/self/ns/mnt"), ("net", "/proc/self/ns/net"), ("pid", "/proc/self/ns/pid"),
                           ("ipc", "/proc/self/ns/ipc"), ("user", "/proc/self/ns/user"), ("time", "/proc/self/ns/time")):
            actual = os.readlink(path)
            require(actual == name + ":[" + ns[name] + "]", "actual namespace inode " + name)
            require((ns[name] == ns["controller_" + name]) if name in {"user", "time"}
                    else (ns[name] != ns["controller_" + name]), "namespace separation/shared user and monotonic clock domain")

    @staticmethod
    def mount_unescape(value):
        require(re.search(r"\\(?!040|011|012|134)", value) is None, "mountinfo recognized octal escapes")
        return re.sub(r"\\(040|011|012|134)", lambda match: chr(int(match[1], 8)), value)

    def mounts_read(self):
        raw = self.proc_bytes("mountinfo")
        require(sha(raw) == self.a["namespaces"]["mountinfo_sha256"], "entire raw final-namespace mountinfo SHA")
        mounts = {}
        for line in raw.decode("ascii").splitlines():
            cells = line.split(" ")
            require(cells.count("-") == 1, "mountinfo separator")
            split = cells.index("-")
            require(split >= 6 and len(cells) == split + 4 and all(cells), "mountinfo complete fields")
            ids = (cells[0], cells[1], *cells[2].split(":"))
            require(len(ids) == 4 and all(re.fullmatch(r"0|[1-9][0-9]*", value) for value in ids), "mountinfo decimal IDs/device")
            mount_id, parent_id, major, minor = map(int, ids)
            require(mount_id > 0 and mount_id not in mounts, "unique positive mount ID")
            root, point = (self.mount_unescape(value) for value in cells[3:5])
            require(root.startswith("/") and point.startswith("/") and posixpath.normpath(root) == root
                    and posixpath.normpath(point) == point, "mountinfo absolute normalized paths")
            flags = cells[5].split(",")
            require(("ro" in flags) != ("rw" in flags) and len(flags) == len(set(flags)), "mountinfo actual vfs ro/rw flag")
            mounts[mount_id] = {"mount_id": mount_id, "major": major, "minor": minor, "root": root,
                                "mount_point": point, "fs_type": cells[split + 1], "read_only": "ro" in flags,
                                "superoptions": cells[split + 3].split(",")}
        require(mounts, "nonempty kernel mountinfo")
        return mounts

    def input_check(self, path, digest):
        info, parent = path.stat(), path.parent.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == self.uid
                and stat.S_IMODE(info.st_mode) == 0o400 and stat.S_ISDIR(parent.st_mode)
                and parent.st_uid == self.uid and stat.S_IMODE(parent.st_mode) == 0o700,
                "kernel readable owned0400 single-link input in owned0700 parent")
        require(not path.is_relative_to(REPO) and not REPO.is_relative_to(path.parent)
                and not any(path.is_relative_to(root) or root.is_relative_to(path.parent)
                            or path.parent.is_relative_to(root) for root in self.directories.values()),
                "kernel input separate from source/work dirs")
        require(os.statvfs(path).f_flag & os.ST_RDONLY and os.statvfs(path.parent).f_flag & os.ST_RDONLY,
                "kernel input and parent actually read-only")
        require(sha(bounded_bytes(path, KERNEL_JSON_LIMIT if path == self.admission_path else MAX_FILE)) == digest,
                "kernel external input bytes unchanged")

    def storage_check(self):
        mounts = self.mounts_read()
        roles = {row["role"]: row for row in self.a["mounts"]}
        expected = {"rootfs": Path("/"), "source": REPO, "native_runtime": STDLIB.parents[1], "venv": PREFIX,
                    "policy": self.policy_path, "admission": self.admission_path, "cache": self.cache_path,
                    "work_pool": self.pool, "cwd": self.directories["DX_EMPTY_CWD"], "upload": self.directories["DX_UPLOAD_DIR"],
                    "evidence": self.directories["DX_EVIDENCE_DIR"], "scratch": self.directories["DX_SCRATCH_DIR"]}
        require(len(roles) == 12 and set(roles) == set(expected), "exact12 distinct kernel mount roles")
        for role, path in expected.items():
            row = roles[role]
            require(kernel_path(row["path"]) == path, "exact actual path for mount role " + role)
            kernel_path(row["root"])
            kernel_path(row["mount_point"])
            candidates = [entry for entry in mounts.values() if path == Path(entry["mount_point"])
                          or path.is_relative_to(Path(entry["mount_point"]))]
            require(candidates, "mountinfo covering path")
            longest = max(len(entry["mount_point"]) for entry in candidates)
            selected = [entry for entry in candidates if len(entry["mount_point"]) == longest]
            require(len(selected) == 1, "unambiguous most-specific mount (stacked mounts unsupported)")
            actual = selected[0]
            require(all(row[key] == actual[key] for key in ("mount_id", "major", "minor", "root", "mount_point", "fs_type", "read_only")),
                    "actual mount ID/device/root/point/type/flags " + role)
            info = path.stat()
            require(os.major(info.st_dev) == row["major"] and os.minor(info.st_dev) == row["minor"]
                    and info.st_uid == row["owner_uid"] and info.st_gid == row["owner_gid"]
                    and format(stat.S_IMODE(info.st_mode), "04o") == row["mode"], "actual mount role device/owner/mode")
            read_only = role not in {"work_pool", "evidence", "scratch"}
            require(row["read_only"] is read_only and bool(os.statvfs(path).f_flag & os.ST_RDONLY) is read_only,
                    "actual role RO/RW statvfs agrees with mountinfo")
        require(all(path.parent == self.pool for path in self.directories.values())
                and len(set(self.directories.values())) == 4, "four exact sibling pool directories")
        pool_info = kernel_path(str(self.pool)).stat()
        require(stat.S_ISDIR(pool_info.st_mode) and pool_info.st_uid == 0 and stat.S_IMODE(pool_info.st_mode) == 0o755,
                "pool root owned by UID0 mode0755")
        require(set(self.pool.iterdir()) == set(self.directories.values()), "pool root contains exactly four fixed directories")
        pool_row = roles["work_pool"]
        require(pool_row["fs_type"] == "tmpfs" and pool_row["mount_id"] == self.a["quota"]["pool_mount_id"]
                and all(path.stat().st_dev == pool_info.st_dev for path in self.directories.values()), "one shared actual tmpfs quota")
        for role in ("cwd", "upload", "evidence", "scratch"):
            row, path = roles[role], expected[role]
            require(row["fs_type"] == "tmpfs" and (row["major"], row["minor"]) == (pool_row["major"], pool_row["minor"]),
                    "same tmpfs superblock for each work directory")
            if row["mount_id"] != pool_row["mount_id"]:
                require(row["root"] == posixpath.join(pool_row["root"], str(path.relative_to(self.pool)))
                        and row["mount_point"] == str(path), "exact pool-backed per-directory bind mount")
        options = {}
        for option in mounts[pool_row["mount_id"]]["superoptions"]:
            key, separator, value = option.partition("=")
            require(key not in options, "unique tmpfs superoptions")
            options[key] = value if separator else None
        for key, maximum in (("size", MAX_ARTIFACT_BYTES), ("nr_inodes", 133)):
            value = options.get(key)
            require(type(value) is str and re.fullmatch(r"[1-9][0-9]*[kKmMgG]?", value) is not None,
                    "explicit finite tmpfs " + key)
            suffix = value[-1].lower()
            amount = int(value[:-1]) * {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[suffix] if suffix in "kmg" else int(value)
            require(0 < amount <= maximum, "actual tmpfs total superoption bound " + key)
        capacity = os.statvfs(self.pool)
        require(0 < capacity.f_blocks * capacity.f_frsize <= MAX_ARTIFACT_BYTES and 0 < capacity.f_files <= 133,
                "actual tmpfs TOTAL capacity64MiB/inodes133, not free space")
        for path in self.directories.values():
            info = kernel_path(str(path)).stat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == self.uid and stat.S_IMODE(info.st_mode) == 0o700
                    and not path.is_relative_to(REPO) and not REPO.is_relative_to(path), "private pool directories preserved")
        # Five fixed inodes + kernel link/linkat denial is an EXTERNAL policy
        # attestation; Cap/Seccomp status cannot self-prove its BPF byte hash.

    def verify(self):
        self.bindings_check()
        self.identity_check()
        for path, digest in self.external_state.items():
            self.input_check(kernel_path(path), digest)
        parents = (self.admission_path.parent, self.policy_path.parent, self.cache_path.parent)
        require(not any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
                        for index, a in enumerate(parents) for b in parents[index + 1:]), "separate nonnested sealed input parents")
        # Preserve the historical 0600 cache/0700 parent/nlink1 contract exactly.
        sealed_cache(self.directories)
        self.storage_check()
        return {"safety_acceptance": "EXTERNAL_FINAL_PENDING", "clock": "CLOCK_MONOTONIC_MS",
                "admission_sha256": self.admission_sha256, "nonce": self.a["nonce"],
                "host_floor_during_after": "EXTERNAL_CONTROLLER_REQUIRED", "kernel_policy_self_proof": False}


def kernel_approval():
    global KERNEL
    require(sys.argv[1:] == ["--execute-approved-partner-dx-kernel-v1"], "exact kernel v1 opt-in")
    fixed = {"ROOT_APPROVED_PARTNER_DX": "1", "RUN_PARTNER_DX_METADATA": "1",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    variable = {"HOME", "DX_RUNNER_SHA256", "DX_SOURCE_HEAD", "DX_SOURCE_BRANCH", "DX_EMPTY_CWD", "DX_EVIDENCE_DIR",
                "DX_SCRATCH_DIR", "DX_UPLOAD_DIR", "DX_PREPARED_CACHE", "DX_PREPARED_CACHE_SHA256"}
    require(set(os.environ) == set(fixed) | variable | KERNEL_EXTRA_ENV
            and all(os.environ[k] == v for k, v in fixed.items())
            and os.environ["DX_EXECUTION_MODE"] == "kernel-controlled-v1", "exact kernel environment, no fallback")
    for key in ("DX_EXPECTED_UID", "DX_EXPECTED_GID"):
        kernel_shape(os.environ[key], "D")
        require(int(os.environ[key]) <= 2 ** 63 - 1, "expected kernel ID integer bound")
    require(os.environ["HOME"] == pwd.getpwuid(os.getuid()).pw_dir, "actual HOME preserved")
    require(sys.version_info[:3] == (3, 13, 7) and sys.flags.isolated and sys.flags.no_site
            and sys.flags.dont_write_bytecode and not sys.flags.optimize and sys.prefix == sys.base_prefix,
            "CPython3.13.7 -I -S -B no optimization")
    require(sys.executable == str(PREFIX / "bin/python") and Path(sys.executable).resolve() == STDLIB.parents[1] / "bin/python3.13",
            "existing approved native interpreter")
    require(not any(name in sys.modules for name in ("app", "pytest", "site", "pydantic", "sqlalchemy"))
            and not any("site-packages" in path or path == "" for path in sys.path), "stdlib only before gate")
    require(sha(bounded_bytes(SELF)) == os.environ["DX_RUNNER_SHA256"], "ROOT-reviewed full self SHA")
    directories = {name: private_empty(name) for name in
                   ("DX_EMPTY_CWD", "DX_EVIDENCE_DIR", "DX_SCRATCH_DIR", "DX_UPLOAD_DIR")}
    values = list(directories.values())
    require(Path.cwd() == directories["DX_EMPTY_CWD"] and len(set(values)) == 4
            and not any(a != b and a.is_relative_to(b) for a in values for b in values), "four separate nonnested directories")
    for root in (REPO, *values):
        for ancestor in (root, *root.parents):
            require(not (ancestor / ".env").exists() and not (ancestor / ".env").is_symlink(), "no ancestor dotenv")
    require(KERNEL is None, "single kernel startup admission")
    KERNEL = KernelAdmission(directories)
    require(sys.getprofile() is None and sys.gettrace() is None, "no preexisting tracing hooks")
    os.umask(0o077)
    return "kernel-controlled-v1", directories


def approval():
    if sys.argv[1:] == ["--execute-approved-partner-dx-kernel-v1"]:
        return kernel_approval()
    # Old exact argv/closed env rejects unknown modes AND all kernel env keys.
    return legacy_approval()


class AbsoluteDeadline:
    """Pinned Linux kernel timer; fatal expiry cannot be swallowed by check()."""
    def __init__(self, started):
        self.started = started
        self.absolute = started + WALL_SECONDS
        self.post_target = None
        self.work_armed = False
        self.frame = None
        deadline = self
        native_signal, native_alarm, native_timer, native_mask = NATIVE_SIGNAL_CONTROLS
        require(signal.SIGALRM not in native_mask(signal.SIG_BLOCK, []), "SIGALRM must not be inherited blocked")

        def soft_expired(signum, frame):
            # Arm the fatal remainder BEFORE raising the catchable work error.
            deadline.control("hard")
            raise TimeoutError("ROOT harness work150s; absolute180s fatal timer armed")

        def control(stage):
            require(stage in {"work", "hard", "post"}, "trusted deadline stage")
            if stage == "work":
                require(not deadline.work_armed and deadline.post_target is None, "single pre-post work timer")
                deadline.work_armed = True
            if stage == "post" and deadline.post_target is None:
                deadline.post_target = min(deadline.absolute, time.monotonic() + 30)
            target = min(deadline.absolute, deadline.post_target if deadline.post_target is not None else deadline.absolute)
            if stage == "work":
                target = min(target, deadline.started + WALL_SECONDS - 30)
            remaining = target - time.monotonic()
            # Even an already-expired deadline gets an immediate fatal timer,
            # never setitimer(0), which would disable the kernel deadline.
            handler = soft_expired if stage == "work" and remaining > 0 else signal.SIG_DFL
            require(deadline.frame is None, "nonrecursive timer capability")
            deadline.frame = sys._getframe()
            try:
                native_signal(signal.SIGALRM, handler)
                native_timer(signal.ITIMER_REAL, max(0.000001, target - time.monotonic()))
            finally:
                deadline.frame = None

        self.control = control
        self.code = control.__code__
        self.closure = control.__closure__
        self.globals = control.__globals__
        self.closure_values = tuple(cell.cell_contents for cell in self.closure)

    def trusted_call(self, frame):
        return (frame is self.frame and frame.f_code is self.code and self.control.__code__ is self.code
                and self.control.__closure__ is self.closure and self.control.__globals__ is self.globals
                and frame.f_globals is self.globals and frame.f_locals.get("deadline") is self
                and tuple(cell.cell_contents for cell in self.closure) == self.closure_values)

    def intact(self):
        require(self.frame is None and self.control.__code__ is self.code
                and self.control.__closure__ is self.closure and self.control.__globals__ is self.globals
                and tuple(cell.cell_contents for cell in self.closure) == self.closure_values
                and (_signal.signal, _signal.alarm, _signal.setitimer, _signal.pthread_sigmask) == NATIVE_SIGNAL_CONTROLS
                and signal.alarm is NATIVE_SIGNAL_CONTROLS[1] and signal.setitimer is NATIVE_SIGNAL_CONTROLS[2],
                "absolute deadline capability/native identities intact")


def set_limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (150, 150))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE, MAX_FILE))
    resource.setrlimit(resource.RLIMIT_NOFILE, (96, 96))


def git_prefetch(scratch):
    """Only preclosure Git. Test-window bridge has a completely separate exact12 cache."""
    env = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
           "GIT_OPTIONAL_LOCKS": "0"}
    sequence = 0

    def actual(args):
        nonlocal sequence
        sequence += 1
        stdout, stderr = scratch / ("git-%02d.stdout" % sequence), scratch / ("git-%02d.stderr" % sequence)
        command = ["/usr/bin/git", "--no-pager", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                   "-c", "core.untrackedCache=false", "-C", str(REPO), *args]
        with stdout.open("xb") as out, stderr.open("xb") as err:
            completed = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                       timeout=5, check=False, shell=False)
        raw, errors = bounded_bytes(stdout), bounded_bytes(stderr)
        require(completed.returncode == 0 and not errors, "actual read-only git return/stderr")
        return raw

    head = actual(("rev-parse", "HEAD")).decode().strip()
    branch = actual(("branch", "--show-current")).decode().strip()
    require(len(head) == 40 and head == os.environ["DX_SOURCE_HEAD"] and branch
            and branch == os.environ["DX_SOURCE_BRANCH"], "ROOT-reviewed source HEAD/branch")
    require(actual(("merge-base", BASE, head)).decode().strip() == BASE, "base725 ancestry")
    require(actual(("status", "--porcelain=v1", "--untracked-files=all")) == b"", "clean committed source tree")
    cache = {}
    require(len(GIT_CACHE_SHA) == 12, "exact1 ls-files+11 show cache")
    for args, digest in GIT_CACHE_SHA.items():
        raw = actual(args)
        require(sha(raw) == digest and len(raw) <= MAX_FILE, "real original baseline Git stdout SHA")
        cache[("git", "-C", str(REPO), *args)] = raw
    lsargs = ("git", "-C", str(REPO), "ls-files", "clearledger/server/app/product_api", "clearledger/server/app/api_contracts")
    paths = cache[lsargs].decode().splitlines()
    require(len(paths) == 11 and len(set(paths)) == 11, "exact11 protected baseline files")
    for path in paths:
        if path not in {"clearledger/server/app/product_api/dto.py", "clearledger/server/app/product_api/app.py"}:
            require(bounded_bytes(REPO / path) == cache[("git", "-C", str(REPO), "show", CHECKER_BASE + ":" + path)],
                    "actual9 protected original bytes")
    # Freeze exact Git identity files for postcheck without permitting another process.
    marker = REPO / ".git"
    gitdir = marker if marker.is_dir() else lexical(REPO / bounded_bytes(marker).decode().strip().removeprefix("gitdir: "))
    common_marker = gitdir / "commondir"
    common = lexical(gitdir / bounded_bytes(common_marker).decode().strip()) if common_marker.exists() else gitdir
    candidates = [gitdir / "HEAD", gitdir / "index", common / "refs/heads" / branch, common / "packed-refs"]
    if marker.is_file():
        candidates.append(marker)
    if common_marker.exists():
        candidates.append(common_marker)
    git_state = {str(path): sha(bounded_bytes(path)) if path.exists() else None for path in candidates}
    return cache, {"head": head, "branch": branch, "base": BASE,
                   "cache": [{"args": list(args), "sha256": digest} for args, digest in GIT_CACHE_SHA.items()]}, git_state


def inherited_fd_census():
    """Finite Linux preclosure census; no concurrent FD mutation is permitted.

    scandir's own FD may appear in its snapshot, then is closed before fstat.
    Only that single vanished non-stdio entry is tolerated, never a live FD>2.
    This is a source contract for the pinned interpreter, not an OS sandbox.
    """
    descriptors = []
    with os.scandir("/proc/self/fd") as listing:
        for entry in listing:
            require(entry.name.isascii() and entry.name.isdecimal(), "proc FD entry")
            descriptors.append(int(entry.name))
            require(len(descriptors) <= 128, "finite preclosure FD census")
    require(len(descriptors) == len(set(descriptors)), "unique proc FD census")
    vanished, stdio = [], []
    for descriptor in descriptors:
        try:
            info = os.fstat(descriptor)
        except OSError as error:
            require(error.errno == errno.EBADF and descriptor > 2 and not vanished,
                    "only closed transient listing FD may vanish")
            vanished.append(descriptor)
            continue
        require(descriptor <= 2, "inherited non-stdio FD capability")
        require(not stat.S_ISDIR(info.st_mode), "directory stdio FD capability")
        stdio.append(descriptor)
    return {"stdio": sorted(stdio), "closed_listing_entries": len(vanished),
            "live_nonstdio": 0, "entry_bound": 128}


def single_thread_census():
    tasks = []
    with os.scandir("/proc/self/task") as listing:
        for entry in listing:
            require(entry.name.isascii() and entry.name.isdecimal(), "proc task entry")
            tasks.append(entry.name)
            require(len(tasks) <= 2, "bounded single kernel thread census")
    require(len(tasks) == 1, "single kernel thread before closure")
    return {"kernel_threads": 1, "entry_bound": 2}


class Boundary:
    def __init__(self, directories, source_bindings, site_bindings, cache, git_state, deadline):
        self.directories = directories
        self.source_bindings = source_bindings
        self.site_bindings = site_bindings
        self.cache = cache
        self.git_state = git_state
        self.denials = []
        self.imports = []
        self.cache_hits = []
        self.closed = False
        self.calls = 0
        self.pytest_code = None
        self.phase = "install"
        self.expected = expected_ids()
        self.original_spec = importlib.util.spec_from_file_location
        require(os.open is posix.open is NATIVE_OPEN and isinstance(NATIVE_OPEN, types.BuiltinFunctionType)
                and NATIVE_OPEN.__module__ == "posix", "original native open identity")
        self.native_open = NATIVE_OPEN
        self.open_wrapper = None
        self.open_code = None
        self.open_closure = None
        self.open_globals = None
        self.open_frame = None
        self.fd_census = None
        self.thread_census = None
        self.deadline = deadline
        self.kernel = KERNEL
        self.checker_module = None
        self.checker_function = None
        self.checker_code = None
        self.checker_globals = None

    def deny(self, reason):
        if len(self.denials) < 64:
            stack, frame = [], sys._getframe(1)
            while frame is not None and len(stack) < 8:
                stack.append({"file": frame.f_code.co_filename[:240], "function": frame.f_code.co_name[:100],
                              "line": frame.f_lineno})
                frame = frame.f_back
            self.denials.append({"reason": str(reason)[:300], "stack": stack})
        raise RuntimeError("closed partner-DX boundary: " + str(reason))

    def owned_write(self, path):
        evidence, scratch = (self.directories[k] for k in ("DX_EVIDENCE_DIR", "DX_SCRATCH_DIR"))
        return path == evidence or path == scratch or path.is_relative_to(scratch) or (
            path.parent == evidence and path.name in EVIDENCE_NAMES)

    def audit(self, event, args):
        if event.startswith(("socket.", "subprocess.", "ctypes.")) or event in {
            "os.system", "os.fork", "os.forkpty", "os.exec", "os.posix_spawn", "os.posix_spawnp",
            "os.kill", "os.killpg", "os.startfile", "sqlite3.connect", "sqlite3.connect/handle",
            "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.truncate", "os.chown",
            "os.chmod", "os.utime", "shutil.copyfile", "shutil.rmtree"}:
            self.deny(event)
        if event in {"os.putenv", "os.unsetenv"}:
            key = os.fsdecode(args[0])
            if key == "PYTEST_VERSION" and (event == "os.unsetenv" or os.fsdecode(args[1]) == PINNED_DISTRIBUTIONS["pytest"]):
                return
            if key == "PYTEST_CURRENT_TEST" and (event == "os.unsetenv" or os.fsdecode(args[1]) in {
                node + " (" + phase + ")" for node in self.expected for phase in ("setup", "call", "teardown")}):
                return
            self.deny("environment mutation " + key)
        if event in {"sys.setprofile", "sys.settrace"} and self.closed:
            self.deny("boundary hook replacement")
        if event == "os.chdir" and lexical(args[0]) != self.directories["DX_EMPTY_CWD"]:
            self.deny("cwd escape")
        if event == "os.mkdir":
            if len(args) != 3 or args[2] not in (-1, None):
                self.deny("mkdir dir_fd capability")
            if not self.owned_write(lexical(args[0])):
                self.deny("mkdir outside evidence/scratch")
        if event != "open":
            return
        # CPython may clear a profile callback when it raises. A caught native
        # denial must never permit a second open with the c_call gate absent.
        if self.closed and sys.getprofile() != self.profile:
            self.deny("open without native call gate")
        if not isinstance(args[0], (str, bytes, os.PathLike)):
            self.deny("file descriptor open")
        if self.kernel is not None and len(args) == 3 and self.kernel.diagnostic_open(args, self):
            return  # Exact identity/postcheck or storage-admission chain (pytest/postcheck); legacy lexical unchanged.
        path = lexical(args[0])
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
        if flags & (os.O_DIRECTORY | os.O_PATH) or path.is_dir():
            self.deny("directory open capability")
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        writing = writing or isinstance(mode, str) and any(c in mode for c in "wax+")
        if path.name == ".env" or path.name.startswith(".env.") or {".ssh", ".vault", ".claude"} & set(path.parts):
            self.deny("real config/secret input")
        if writing:
            if not self.owned_write(path):
                self.deny("outside write " + str(path))
            return
        # -B alone only prevents writes. Bytecode may be hashed by this helper's
        # bounded tree verifier, never consumed by an import loader/framework.
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            frame, verifier, depth = sys._getframe(1), [], 0
            while frame is not None and depth < 16:
                verifier.append(frame.f_code)
                frame, depth = frame.f_back, depth + 1
            if (self.phase != "postcheck" or writing or str(path) not in self.site_bindings
                    or not all(code in verifier for code in (
                        bounded_bytes.__code__, tree.__code__, inventory.__code__, postcheck.__code__))):
                self.deny("bytecode cache read outside explicit site manifest hashing")
        allowed = str(path) in self.source_bindings or str(path) in self.site_bindings or str(path) in self.git_state
        allowed = allowed or path == SELF or path == PREFIX / "pyvenv.cfg" or path.is_relative_to(STDLIB)
        allowed = allowed or self.owned_write(path)
        if not allowed:
            self.deny("read outside frozen source/site/stdlib/evidence " + str(path))

    def check_output(self, *args, **kwargs):
        caller = sys._getframe(1)
        if (len(args) != 1 or kwargs or type(args[0]) is not list
                or not all(type(cell) is str for cell in args[0])
                or self.checker_function is None or caller.f_code is not self.checker_code
                or caller.f_globals is not self.checker_globals
                or self.checker_module.__dict__ is not self.checker_globals
                or self.checker_globals.get("git") is not self.checker_function
                or self.checker_function.__code__ is not self.checker_code
                or self.checker_function.__globals__ is not self.checker_globals):
            self.deny("unknown subprocess.check_output caller/shape")
        command = tuple(args[0])
        if command not in self.cache:
            self.deny("unknown Git tuple")
        if len(self.cache_hits) >= 256:
            self.deny("Git cache call bound")
        self.cache_hits.append(list(command))
        return self.cache[command]  # Original stdout bytes, including terminal newline.

    def profile(self, frame, event, arg):
        # A profile exception removes CPython's per-thread hook. Never let a
        # caller catch that exception and then cancel the fatal timer/open raw.
        # Fatal refusal cannot promise a receipt; ROOT must census externally.
        try:
            return self.profile_event(frame, event, arg)
        except BaseException:
            NATIVE_EXIT(1)

    def profile_event(self, frame, event, arg):
        if event == "c_call" and any(arg is native for native in NATIVE_THREAD_STARTS):
            self.deny("new Python thread outside single-thread boundary")
        if event == "c_call" and any(arg is native for native in NATIVE_SIGNAL_CONTROLS):
            if not self.deadline.trusted_call(frame):
                self.deny("native timer control outside exact deadline capability")
            return
        if event == "c_call" and arg is self.native_open:
            wrapper = self.open_wrapper
            if (wrapper is None or frame is not self.open_frame or frame.f_code is not self.open_code
                    or wrapper.__code__ is not self.open_code or wrapper.__closure__ is not self.open_closure
                    or frame.f_globals is not self.open_globals or wrapper.__globals__ is not self.open_globals
                    or frame.f_locals.get("boundary") is not self or frame.f_locals.get("native_open") is not self.native_open
                    or tuple(cell.cell_contents for cell in self.open_closure) != (self, self.native_open)):
                self.deny("raw native open outside exact trusted wrapper capability")
            return
        if event != "call":
            return
        module, name = frame.f_globals.get("__name__", ""), frame.f_code.co_name
        is_function = bool(frame.f_code.co_flags & 0x02)  # CO_NEWLOCALS: exclude module/class declarations.
        # The frozen query module declares CONTRACT_TYPES with this one module-
        # level generator (line23). It is real inert SQLAlchemy column metadata,
        # not Query execution. No other generator/callback receives an allowance.
        declaration_generator = (module == "app.product_api.queries" and name == "<genexpr>"
            and frame.f_code.co_filename == str(REPO / BINDINGS[module][0])
            and frame.f_code.co_firstlineno == 23 and frame.f_back is not None
            and frame.f_back.f_globals is frame.f_globals and frame.f_back.f_code.co_name == "<module>")
        if self.pytest_code is not None and frame.f_code is self.pytest_code:
            self.calls += 1
            if self.calls != 1:
                self.deny("nested/repeated pytest.main")
        if module.startswith("app.services") and is_function:
            self.deny("inert service function " + module + "." + name)
        if module in {"app.product_api.queries", "app.product_api.files", "app.product_api.monitoring",
                      "app.product_api.budget", "app.models", "app.models_product_budget"} and is_function and not declaration_generator:
            self.deny("runtime model/query/file/budget function " + module + "." + name)
        if module == "app.product_api.access" and is_function and name.startswith(("configured_", "resolve", "authorize")):
            self.deny("runtime access/config function " + name)
        if module.startswith("app.") and name in {"lifespan", "startup", "shutdown", "query_dependency"}:
            self.deny("main/lifespan/jobs " + name)
        if module.startswith(("fastapi.", "starlette.")) and name in {"__call__", "startup", "shutdown", "lifespan", "handle"}:
            self.deny("framework serving/lifespan")
        if module.startswith(("sqlalchemy.engine", "sqlalchemy.ext.asyncio", "sqlalchemy.orm.session", "sqlalchemy.pool")):
            if name in {"create_engine", "create_async_engine", "connect", "raw_connection", "execute", "exec_driver_sql",
                        "begin", "commit", "flush", "rollback", "get_bind", "_invoke_creator", "_do_get"}:
                self.deny("SQL/engine/session " + name)

    def source_loader(self, fullname, path, digest):
        boundary = self

        class FrozenSource(importlib.machinery.SourceFileLoader):
            def exec_module(self, module):
                if fullname != "partner_dx_source_checker_20261031":
                    return super().exec_module(module)
                require(boundary.checker_function is None, "single actual checker module execution")
                code = self.get_code(fullname)  # Rechecks pinned actual .py bytes.
                candidates = [item for item in code.co_consts if isinstance(item, types.CodeType) and item.co_name == "git"]
                require(len(candidates) == 1, "one actual checker.git code in pinned module constants")
                exec(code, module.__dict__)
                function = module.__dict__.get("git")
                require(isinstance(function, types.FunctionType) and function.__code__ is candidates[0]
                        and function.__globals__ is module.__dict__, "actual checker.git code/globals identity")
                boundary.checker_module = module
                boundary.checker_function = function
                boundary.checker_code = candidates[0]
                boundary.checker_globals = module.__dict__

            def get_code(self, name):
                require(name == fullname, "source loader name")
                raw = bounded_bytes(path)
                require(digest is None or sha(raw) == digest, "typed import path/source SHA " + fullname)
                return compile(raw, str(path), "exec", dont_inherit=True, optimize=0)

            def set_data(self, path, data, **kwargs):
                boundary.deny("bytecode write")

        return FrozenSource(fullname, str(path))

    def spec(self, fullname, location=None, *, loader=None, submodule_search_locations=None):
        """Covers pytest/direct spec_from_file_location too, including the unchanged checker fixture."""
        if location is None:
            self.deny("source spec without path")
        path = lexical(location)
        digest = self.source_bindings.get(str(path), self.site_bindings.get(str(path)))
        aliases = {**BINDINGS, **{"tests." + key: value for key, value in BINDINGS.items() if key in TESTS}}
        if fullname in aliases:
            relative, pinned = aliases[fullname]
            if path != REPO / relative or digest != pinned:
                self.deny("typed app/test/helper binding " + fullname)
        elif path.is_relative_to(SERVER) or fullname == "app" or fullname.startswith(("app.", "tests.", "test_partner_dx_")):
            self.deny("unknown source import " + fullname)
        elif digest is None and not path.is_relative_to(STDLIB):
            self.deny("dependency outside exact verified site/stdlib")
        if path.suffix == ".py":
            loader = self.source_loader(fullname, path, digest)
        elif str(path) in self.site_bindings and any(str(path).endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES):
            require(sha(bounded_bytes(path)) == digest, "native extension source binding")
        elif path.is_relative_to(STDLIB) and any(str(path).endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES):
            pass
        else:
            self.deny("unsupported import source/cache " + str(path))
        if len(self.imports) >= 4096:
            self.deny("import trace bound")
        self.imports.append({"name": fullname, "path": str(path), "sha256": digest, "source_only": path.suffix == ".py"})
        return self.original_spec(fullname, str(path), loader=loader, submodule_search_locations=submodule_search_locations)

    def install(self):
        boundary = self
        native_open = self.native_open

        def guarded_open(path, flags, mode=0o777, *, dir_fd=None):
            # Audit open(path, mode, flags) omits dir_fd. Reject it BEFORE any
            # native call; use a plain absolute string after lexical checks.
            if dir_fd is not None or isinstance(path, int):
                boundary.deny("open dir_fd/int path capability")
            if type(flags) is not int or flags & (os.O_DIRECTORY | os.O_PATH):
                boundary.deny("open directory flags capability")
            path = lexical(path)
            if path.is_dir():
                boundary.deny("open existing directory capability")
            if boundary.open_frame is not None:
                boundary.deny("nested native open capability")
            boundary.open_frame = sys._getframe()
            try:
                return native_open(str(path), flags, mode)
            finally:
                boundary.open_frame = None

        class Imports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                root = fullname.split(".")[0]
                if root in BLOCKED_ROOTS or (fullname == "app" or fullname.startswith("app.")) and fullname not in BINDINGS:
                    boundary.deny("blocked assembly/config/auth/driver/sender import " + fullname)
                if fullname == "app.database":
                    boundary.deny("app.database must already be inert-bound")
                built = importlib.machinery.BuiltinImporter.find_spec(fullname)
                if built is not None:
                    return built
                frozen = importlib.machinery.FrozenImporter.find_spec(fullname)
                if frozen is not None:
                    return frozen
                found = importlib.machinery.PathFinder.find_spec(fullname, path)
                if found is None:
                    return None
                if found.origin is None:
                    if fullname == "tests" and list(found.submodule_search_locations or []) == [str(SERVER / "tests")]:
                        return found
                    boundary.deny("unreviewed namespace package " + fullname)
                return boundary.spec(fullname, found.origin, loader=found.loader,
                                     submodule_search_locations=found.submodule_search_locations)

        require(all(not name.startswith("app") for name in sys.modules), "install before app import")
        self.fd_census = inherited_fd_census()
        self.thread_census = single_thread_census()
        self.open_wrapper = guarded_open
        self.open_code = guarded_open.__code__
        self.open_closure = guarded_open.__closure__
        self.open_globals = guarded_open.__globals__
        require(guarded_open.__code__.co_freevars == ("boundary", "native_open"), "exact open wrapper closure")
        os.open = guarded_open  # posix.open stays native; profile gates aliases.
        subprocess.check_output = self.check_output
        importlib.util.spec_from_file_location = self.spec
        sys.meta_path[:] = [Imports()]
        sys.addaudithook(self.audit)
        sys.setprofile(self.profile)
        self.closed = True


def inert_database(boundary):
    from sqlalchemy.orm import DeclarativeBase

    class SchemaOnlyBase(DeclarativeBase):
        pass

    declarations = types.ModuleType("app.database")
    declarations.Base = SchemaOnlyBase

    def unavailable(name):
        if name.startswith("__"):
            raise AttributeError(name)
        boundary.deny("inert app.database attribute " + name)

    declarations.__getattr__ = unavailable
    require("app.database" not in sys.modules, "single inert database import adapter")
    sys.modules["app.database"] = declarations
    return {"module": "app.database", "exports": ["Base"], "base": "real sqlalchemy.orm.DeclarativeBase",
            "engine": "NOT_CONSTRUCTED", "session": "NOT_CONSTRUCTED", "runtime_coverage": False}


class BoundedOutput(io.TextIOBase):
    def __init__(self, stream):
        self.stream = stream
        self.total = 0

    def writable(self):
        return True

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"

    def write(self, text):
        raw = text.encode("utf-8", "backslashreplace")
        self.total += len(raw)
        require(self.total <= MAX_OUTPUT, "stdout/stderr8MiB bound")
        self.stream.write(raw)
        return len(text)

    def flush(self):
        self.stream.flush()


def run_pytest(boundary, evidence, proof):
    import pytest
    pytest_main_path = SITE / "_pytest/config/__init__.py"
    require(pytest.main.__module__ == "_pytest.config" and pytest.main.__name__ == "main"
            and pytest.main.__code__.co_filename == str(pytest_main_path)
            and sha(bounded_bytes(pytest_main_path)) == boundary.site_bindings[str(pytest_main_path)],
            "actual pinned pytest.main implementation identity")
    boundary.pytest_code = pytest.main.__code__
    boundary.phase = "pytest"

    class Phases:
        def __init__(self):
            self.collected = []
            self.reports = []
            self.issues = []
            self.started = []
            self.finished = []
            self.session_finished = []
            self.report_bytes = 0

        def pytest_collection_finish(self, session):
            self.collected = [item.nodeid for item in session.items]
            require(self.collected == boundary.expected, "exact AST-derived26 collection; no suppressed cases")
            require(not any(mark.name in {"skip", "skipif", "xfail"} for item in session.items for mark in item.iter_markers()),
                    "no skip/xfail markers")

        def pytest_collectreport(self, report):
            if not report.passed:
                self.issues.append({"collection": report.nodeid, "outcome": report.outcome,
                                    "trace": str(report.longrepr)[:65536]})

        def pytest_deselected(self, items):
            self.issues.append({"deselected": [item.nodeid for item in items][:32]})

        def pytest_internalerror(self, excrepr, excinfo):
            self.issues.append({"internalerror": str(excrepr)[:65536]})

        def pytest_keyboard_interrupt(self, excinfo):
            self.issues.append({"interrupt": str(excinfo.value)[:65536]})

        def pytest_runtest_logstart(self, nodeid, location):
            require(len(self.started) < 26, "start phase bound")
            self.started.append(nodeid)

        def pytest_runtest_logfinish(self, nodeid, location):
            require(len(self.finished) < 26, "finish phase bound")
            self.finished.append(nodeid)

        def pytest_runtest_logreport(self, report):
            require(len(self.reports) < 78 and report.nodeid in boundary.expected, "report bound/node ID")
            sections = [[name[:100], text[:2048]] for name, text in report.sections[:8]]
            row = {"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
                   "duration": report.duration, "wasxfail": getattr(report, "wasxfail", None),
                   "trace": str(report.longrepr)[:32768] if report.longrepr else None, "sections": sections}
            self.report_bytes += len(encode(row))
            require(self.report_bytes <= 4 * MiB, "aggregate phase evidence4MiB")
            self.reports.append(row)

        def pytest_sessionfinish(self, session, exitstatus):
            self.session_finished.append(int(exitstatus))

    plugin = Phases()
    proof["pytest"] = plugin.__dict__
    arguments = ["--noconftest", "--rootdir=" + str(SERVER), "-c", str(SERVER / "pytest.ini"),
                 "--confcutdir=" + str(SERVER / "tests"), "--import-mode=prepend", "--assert=plain",
                 "-p", "no:cacheprovider", "-p", "no:faulthandler", "-p", "pytest_asyncio.plugin", "--capture=no", "-q", "--tb=long",
                 "--basetemp=" + str(boundary.directories["DX_SCRATCH_DIR"] / "pytest"),
                 "--junitxml=" + str(evidence / "junit.xml"), "-o", "junit_family=xunit2",
                 "-o", "junit_logging=all", "-o", "addopts=", "-o", "pythonpath=", "-o", "required_plugins="]
    arguments += [str(SERVER / "tests" / (module + ".py")) for module in TESTS]
    proof["pytest_args"] = arguments
    artifact_scan(boundary.directories, reserve_count=2, reserve_bytes=MAX_OUTPUT + MAX_FILE)
    with (evidence / "pytest-output.txt").open("xb") as output:
        sink = BoundedOutput(output)
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            code = pytest.main(arguments, plugins=[plugin])  # Exactly one call, never a nested process.
    proof["pytest_exit"] = int(code)
    require(int(code) == 0 and plugin.session_finished == [0] and not plugin.issues, "pytest return/collection/session issues")
    require(plugin.started == boundary.expected and plugin.finished == boundary.expected, "all26 start/finish phases")
    expected_phases = [(node, phase) for node in boundary.expected for phase in ("setup", "call", "teardown")]
    require([(row["nodeid"], row["when"]) for row in plugin.reports] == expected_phases
            and all(row["outcome"] == "passed" and row["wasxfail"] is None for row in plugin.reports),
            "exact78 passing setup/call/teardown without skips/errors/xfail")
    junit = ET.fromstring(bounded_bytes(evidence / "junit.xml"))
    cases = junit.findall(".//testcase")
    require(len(cases) == 26 and not junit.findall(".//failure") and not junit.findall(".//error")
            and not junit.findall(".//skipped"), "JUnit26 clean outcomes")
    junit_ids = ["tests/" + case.attrib["classname"].split(".")[-1] + ".py::" + case.attrib["name"] for case in cases]
    require(junit_ids == boundary.expected, "JUnit exact case identities")
    suites = junit.findall(".//testsuite")
    require(suites and sum(int(s.attrib.get("tests", "0")) for s in suites) == 26
            and all(int(s.attrib.get(key, "0")) == 0 for s in suites for key in ("errors", "failures", "skipped")),
            "JUnit suite totals")


def write_json(path, value, directories):
    raw = encode(value) + b"\n"
    require(len(raw) <= MAX_FILE and not path.exists(), "bounded new evidence artifact")
    require(path.parent == directories["DX_EVIDENCE_DIR"] and path.name in EVIDENCE_NAMES, "narrow evidence writer")
    # Admission is mandatory even for a FAIL receipt: never create file129 or
    # exceed the aggregate budget while explaining an earlier failed guard.
    artifact_scan(directories, reserve_count=1, reserve_bytes=len(raw))
    with path.open("xb") as stream:
        stream.write(raw)
    info = lexical(path).stat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.getuid() and info.st_nlink == 1 and info.st_size == len(raw),
            "created artifact owner/mode/nlink/bytes")
    return {"sha256": sha(raw), "bytes": len(raw)}


def schema_exports(boundary, evidence, proof):
    """Actual factory/registry/DTO/public projector and real validator, never an HTTP request."""
    from jsonschema import Draft202012Validator, FormatChecker
    from app.api_contracts import policy_registry
    from app.product_api import dto
    from app.product_api.app import create_product_api, curated_openapi, public_client_openapi

    def no_io(*args, **kwargs):
        boundary.deny("synthetic no_io callback unexpectedly invoked")

    product = create_product_api(session_factory=no_io, verifier=no_io, enabled=False,
        cursor_key=b"fictional-root-metadata-schema-key-32bytes",
        upload_dir=boundary.directories["DX_UPLOAD_DIR"], issuer="https://sandbox.example.invalid",
        source_revision=os.environ["DX_SOURCE_HEAD"])
    require(product.state.product_settings.enabled() is False, "synthetic factory disabled")
    canonical = curated_openapi(product)
    frozen_canonical = encode(canonical)
    browser = public_client_openapi(canonical)
    require(encode(canonical) == frozen_canonical, "public projection never mutates actual canonical")
    registry = policy_registry(product)
    expected = next(ast.literal_eval(node.value) for node in ast.parse(bounded_bytes(
        REPO / BINDINGS["partner_dx_source_checker_20261031"][0])).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "EXPECTED_OPERATIONS")
    require(len(expected) == len(registry) == 15, "actual15 registry/operation identities")
    entries = {row["operationId"]: row for row in registry}
    require(set(entries) == set(expected), "actual registry exact names")
    # Use the pinned, installed official OpenAPI3.1 meta-schema as data with the
    # actual Draft202012Validator. No optional validator settings/env/URL loader
    # imports are needed; no replacement validator is installed.
    official_path = SITE / "openapi_spec_validator/resources/schemas/v3.1/schema.json"
    official = json.loads(bounded_bytes(official_path))
    oas_validator = Draft202012Validator(official, format_checker=FormatChecker())
    models = {
        "listObjects": dto.Page[dto.Object], "getObject": dto.Object,
        "getObjectMonitoring": dto.Monitoring, "listEquipment": dto.Page[dto.Equipment],
        "getEquipment": dto.Equipment, "listCounterparties": dto.Page[dto.Counterparty],
        "getCounterparty": dto.Counterparty, "listContracts": dto.Page[dto.Contract], "getContract": dto.Contract,
        "getContractTypeMetadata": dto.ContractTypeMetadata, "listContractObjects": dto.ContractObjects,
        "listContractDocuments": dto.ContractDocuments, "listDocuments": dto.Page[dto.Document],
        "getDocument": dto.DocumentDetail,
    }
    require(set(models) == set(expected) - {"downloadDocumentVersion"}, "actual14 DTO bindings")
    schemas, validation = {}, {}
    for label, schema in (("canonical", canonical), ("browser", browser)):
        require(schema["openapi"].startswith("3.1."), "approved official OAS3.1 validator dialect")
        oas_validator.validate(schema)
        malformed = deepcopy(schema)
        del malformed["openapi"]
        require(not oas_validator.is_valid(malformed), "real OAS validator rejects missing version")
        operations = {}
        refs = []

        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    ref = value["$ref"]
                    require(type(ref) is str and ref.startswith("#/"), "local references only, no remote loader")
                    target = schema
                    for part in ref[2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                    refs.append(ref)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(schema)
        require(set(schema["paths"]) == {path for path, resource in expected.values()}, "exact15 actual schema paths")
        for path, item in schema["paths"].items():
            require(set(item) == {"get"}, "only reviewed GET path methods")
            operation = item["get"]
            name = operation["operationId"]
            require(name not in operations and name in entries and expected[name][0] == path, "schema path/name/registry identity")
            operations[name] = operation
            entry = entries[name]
            resource = expected[name][1]
            scopes = {resource + ":read"}
            if name == "getObjectMonitoring":
                scopes.add("monitoring:read")
            if name == "listContractObjects":
                scopes.add("objects:read")
            if name == "listContractDocuments":
                scopes.add("contracts:read")
            if name == "downloadDocumentVersion":
                scopes.add("documents.files:download")
            kinds = {"partner"} if resource == "documents" else {"partner", "service"}
            require(set(entry["scopes"]) == scopes and set(entry["principalKinds"]) == kinds
                    and entry["methods"] == ["GET"] and entry["path"] == path
                    and entry["tenantRequired"] is True and entry["fields"] == []
                    and entry["owner"] == entry["resourceType"] == resource
                    and entry["action"] == ("download" if name == "downloadDocumentVersion" else "read")
                    and entry["securityScheme"] == "ProductOAuth", "actual exact scope/principal/tenant policy")
            security = [{"ProductOAuth": sorted(scopes)}]
            if label == "canonical" and resource != "documents":
                security.append({"ProductServiceOAuth": sorted(scopes)})
            require(operation["security"] == security, "canonical/public auth alternatives match actual registry")
        require(len(operations) == 15 and sum("service" in e["principalKinds"] for e in entries.values()) == 11
                and sum(expected[name][1] == "documents" for name in entries) == 4, "15=11machine+4user-only")
        schemes = schema["components"]["securitySchemes"]
        require(set(schemes) == ({"ProductOAuth", "ProductServiceOAuth"} if label == "canonical" else {"ProductOAuth"}),
                "exact execution auth schemes")
        require(set(schemes["ProductOAuth"]["flows"]) == {"authorizationCode"}, "public Code+PKCE auth shape")
        if label == "canonical":
            service = schemes["ProductServiceOAuth"]
            request = service["x-elsy-token-request"]
            require(set(service["flows"]) == {"clientCredentials"} and request["browserExecution"] is False
                    and request["clientAuthentication"] == "client_secret_basic"
                    and request["body"]["required"] == ["grant_type", "grant_id", "scope"]
                    and request["refreshTokenIssued"] is False, "machine credentials remain server-only")
        else:
            projection = schema["x-elsy-authentication-projection"]
            require(projection["kind"] == "public-code-pkce" and projection["executionSecuritySchemes"] == ["ProductOAuth"]
                    and projection["serverOnlyProfiles"]["ProductServiceOAuth"] == canonical["components"]["securitySchemes"]["ProductServiceOAuth"],
                    "public schema preserves server-only readable metadata")
        example_count, field_examples = 0, 0
        for name, model in models.items():
            media = operations[name]["responses"]["200"]["content"]["application/json"]
            validator = Draft202012Validator({"allOf": [media["schema"]], "components": schema["components"]},
                                             format_checker=FormatChecker())
            require(set(media["examples"]) == {"fictional"}, "exact fictional JSON example per operation")
            for example in media["examples"].values():
                value = example["value"]
                validator.validate(value)
                parsed = model.model_validate_json(json.dumps(value), strict=True)
                require(parsed.model_dump(mode="json", by_alias=True) == value, "actual DTO roundtrip " + name)
                example_count += 1
        for name, node in schema["components"]["schemas"].items():
            Draft202012Validator.check_schema(node)
            for field in [node, *node.get("properties", {}).values()]:
                for example in field.get("examples", []):
                    Draft202012Validator({"allOf": [field], "components": schema["components"]},
                                         format_checker=FormatChecker()).validate(example)
                    field_examples += 1
        require(example_count == 14 and field_examples > 0, "14 actual JSON and actual field/alias examples")
        binary = operations["downloadDocumentVersion"]["responses"]["200"]
        require(binary["content"] == {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}
                and {"Content-Disposition", "X-Content-Type-Options", "Cache-Control", "X-Request-Id"} <= set(binary["headers"]),
                "binary bytes/header contract preserved")
        for operation in operations.values():
            for status in ("400", "401", "403", "404", "422", "429", "500", "503"):
                response = operation["responses"][status]
                require({"Cache-Control", "X-Request-Id"} <= set(response["headers"]), "problem security headers")
                require(response["content"]["application/problem+json"]["schema"] == {"$ref": "#/components/schemas/Problem"},
                        "problem schema reference")
                if status in {"401", "403"}:
                    require("WWW-Authenticate" in response["headers"], "challenge header")
                if status in {"429", "503"}:
                    require("Retry-After" in response["headers"], "retry header")
        schemas[label] = operations
        validation[label] = {"operations": 15, "machine_capable": 11, "user_only": 4,
                             "json_examples": example_count, "field_examples": field_examples,
                             "local_refs": len(refs), "validator": "actual jsonschema.Draft202012Validator",
                             "official_oas_schema": {"path": str(official_path), "sha256": sha(bounded_bytes(official_path))}}
    for name in expected:
        left, right = deepcopy(schemas["canonical"][name]), deepcopy(schemas["browser"][name])
        left.pop("security")
        right.pop("security")
        require(left == right, "public projection changes only operation security, never examples/headers/binary/schema")
    a, b = deepcopy(canonical["components"]), deepcopy(browser["components"])
    a.pop("securitySchemes")
    b.pop("securitySchemes")
    require(a == b, "public DTO/schema components unchanged")
    proof["exports"] = {"canonical": write_json(evidence / "canonical.json", canonical, boundary.directories),
                        "browser": write_json(evidence / "browser.json", browser, boundary.directories),
                        "registry": write_json(evidence / "registry.json", registry, boundary.directories)}
    proof["schema_checks"] = validation
    write_json(evidence / "schema-checks.json", validation, boundary.directories)


def prepare_cache(evidence, scratch, proof):
    cache, provenance, git_state = git_prefetch(scratch)
    payload = {
        "format": "partner-dx-real-git-cache-v1", "base": BASE, "checker_base": CHECKER_BASE,
        "source": provenance, "runner_sha256": os.environ["DX_RUNNER_SHA256"],
        "frozen": FROZEN, "support": SUPPORT, "bindings": BINDINGS,
        "site": FROZEN_SITE, "versions": PINNED_DISTRIBUTIONS,
        "entries": [{"args": list(command[3:]), "sha256": sha(raw),
                     "stdout_base64": base64.b64encode(raw).decode("ascii")} for command, raw in cache.items()],
        "runtime_execution": 0, "source_checkout": str(REPO),
    }
    # All validations, including postcheck in main(), precede publication of this
    # file. ROOT must review its bytes/hash before a distinct execute invocation.
    proof["source"] = provenance
    proof["git_identity_snapshot"] = git_state
    return payload, git_state


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate sealed JSON field")
        result[key] = value
    return result


def sealed_cache(directories):
    path = Path(os.environ["DX_PREPARED_CACHE"])
    require(path.is_absolute() and ".." not in path.parts and lexical(path) == path, "absolute sealed cache path")
    info, parent = path.stat(), path.parent.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1 and parent.st_uid == os.getuid() and stat.S_IMODE(parent.st_mode) == 0o700
            and not path.is_relative_to(REPO) and not any(path.is_relative_to(root) or root.is_relative_to(path.parent)
                                                        for root in directories.values()),
            "sealed cache owned0600 in separate0700 external directory")
    raw = bounded_bytes(path)
    require(sha(raw) == os.environ["DX_PREPARED_CACHE_SHA256"], "ROOT-reviewed sealed cache SHA")
    payload = json.loads(raw, object_pairs_hook=unique_object)
    require(set(payload) == {"format", "base", "checker_base", "source", "runner_sha256", "frozen", "support", "bindings",
                             "site", "versions", "entries", "runtime_execution", "source_checkout"}, "exact sealed fields")
    require(payload["format"] == "partner-dx-real-git-cache-v1" and payload["base"] == BASE
            and payload["checker_base"] == CHECKER_BASE and payload["runner_sha256"] == os.environ["DX_RUNNER_SHA256"]
            and payload["frozen"] == FROZEN and payload["support"] == SUPPORT and payload["bindings"] == BINDINGS
            and payload["site"] == FROZEN_SITE and payload["versions"] == PINNED_DISTRIBUTIONS
            and payload["runtime_execution"] == 0, "sealed exact source/runtime/self pins")
    provenance = payload["source"]
    require(provenance["head"] == os.environ["DX_SOURCE_HEAD"] and len(provenance["head"]) == 40
            and provenance["branch"] == os.environ["DX_SOURCE_BRANCH"] and provenance["branch"]
            and provenance["base"] == BASE and type(payload["source_checkout"]) is str,
            "sealed actual Git HEAD/branch/base matches explicit ROOT pins")
    require(type(payload["entries"]) is list and len(payload["entries"]) == 12, "exact12 sealed cache entries")
    cache, seen, total = {}, set(), 0
    for row in payload["entries"]:
        require(type(row) is dict and set(row) == {"args", "sha256", "stdout_base64"}
                and type(row["args"]) is list and all(type(cell) is str for cell in row["args"]), "sealed tuple type")
        args = tuple(row["args"])
        require(args in GIT_CACHE_SHA and args not in seen and row["sha256"] == GIT_CACHE_SHA[args], "exact sealed command tuples")
        value = base64.b64decode(row["stdout_base64"], validate=True)
        total += len(value)
        require(sha(value) == GIT_CACHE_SHA[args] and len(value) <= MAX_FILE and total <= MAX_FILE, "actual Git bytes unchanged")
        cache[("git", "-C", str(REPO), *args)] = value
        seen.add(args)
    require(seen == set(GIT_CACHE_SHA) and provenance["cache"] == [
        {"args": list(args), "sha256": digest} for args, digest in GIT_CACHE_SHA.items()], "full cache provenance")
    # The cache uses logical git argument tuples. Render only the original
    # checker's exact local -C argv for the copied tree; never access source_checkout.
    return cache, provenance, {str(path): sha(raw)}


def artifact_scan(directories, *, reserve_count=0, reserve_bytes=0):
    count, total, rows = 0, 0, []
    for name, root in directories.items():
        require(lexical(root) == root and root.stat().st_uid == os.getuid()
                and stat.S_IMODE(root.stat().st_mode) == 0o700, "private directories preserved")
        signature, bindings = tree(root, root)
        if name in {"DX_EMPTY_CWD", "DX_UPLOAD_DIR"}:
            require(signature["count"] == 0 and not any(root.iterdir()), "unused cwd/upload unchanged")
        if name == "DX_EVIDENCE_DIR":
            require(all(Path(path).parent == root and Path(path).name in EVIDENCE_NAMES for path in bindings), "exact evidence paths")
        for path, digest in bindings.items():
            info = Path(path).stat()
            require(info.st_uid == os.getuid() and not info.st_mode & 0o077 and info.st_nlink == 1,
                    "owned private single-link artifact")
            rows.append({"area": name, "path": str(Path(path).relative_to(root)), "sha256": digest, "bytes": info.st_size})
        count += signature["count"]
        total += signature["bytes"]
        require(count + reserve_count <= 128 and total + reserve_bytes <= MAX_ARTIFACT_BYTES,
                "finite128files/64MiB including reserved final receipt")
        if KERNEL is None:
            require(os.statvfs(root).f_bavail * os.statvfs(root).f_frsize >= FREE_FLOOR, "post freefloor8GiB")
        else:
            KERNEL.storage_check()
    return {"files": rows, "count": count, "bytes": total,
            "reserved_count": reserve_count, "reserved_bytes": reserve_bytes}


def postcheck(directories, original_env, proof, boundary, external_state):
    issues, results = [], {}
    if boundary is not None:
        boundary.phase = "postcheck"

    def check(name, operation):
        try:
            results[name] = operation()
        except BaseException as error:
            issues.append({"check": name, "error": type(error).__name__ + ": " + str(error)[:1000]})

    check("sources", lambda: sources()[0])
    check("inventory", lambda: inventory()[0])

    def outside_state():
        for name, digest in external_state.items():
            path = Path(name)
            require((sha(bounded_bytes(path)) if path.exists() else None) == digest, "external seal/Git state unchanged")
        return True

    check("external_seal_or_prepare_git", outside_state)

    def environment():
        require(dict(os.environ) == original_env and Path.cwd() == directories["DX_EMPTY_CWD"], "environment/cwd unchanged")
        return {"HOME_preserved": True, "clean_env_preserved": True, "cwd_preserved": True}

    check("environment", environment)

    if KERNEL is not None:
        check("kernel_admission", KERNEL.verify)  # Startup expiry is deliberately NOT rechecked.
    check("artifacts", lambda: artifact_scan(directories))
    if boundary is not None:
        def closed_state():
            require(sys.getprofile() == boundary.profile and sys.gettrace() is None, "closed tracing hooks intact")
            boundary.deadline.intact()
            require(boundary.checker_function is not None
                    and boundary.checker_module.__dict__ is boundary.checker_globals
                    and boundary.checker_globals.get("git") is boundary.checker_function
                    and boundary.checker_function.__code__ is boundary.checker_code
                    and boundary.checker_function.__globals__ is boundary.checker_globals
                    and subprocess.check_output == boundary.check_output,
                    "actual pinned checker.git and bridge identities intact")
            require(os.open is boundary.open_wrapper and posix.open is boundary.native_open is NATIVE_OPEN
                    and boundary.open_wrapper.__code__ is boundary.open_code
                    and boundary.open_wrapper.__closure__ is boundary.open_closure
                    and boundary.open_wrapper.__globals__ is boundary.open_globals
                    and tuple(cell.cell_contents for cell in boundary.open_closure) == (boundary, boundary.native_open)
                    and boundary.open_frame is None, "trusted open wrapper/native/closure intact")
            require(boundary.fd_census is not None and boundary.fd_census["live_nonstdio"] == 0,
                    "preclosure inherited FD census completed")
            require(boundary.thread_census == {"kernel_threads": 1, "entry_bound": 2}
                    and (_thread.start_new_thread, _thread.start_joinable_thread) == NATIVE_THREAD_STARTS,
                    "single-thread preclosure census/native start identities intact")
            require(not boundary.denials, "guard attempts are failure, even if test caught exception")
            require(boundary.calls == 1, "one actual pytest.main")
            require({tuple(row) for row in boundary.cache_hits} == set(boundary.cache), "all12 exact baseline resolver commands exercised")
            require(not any(name == "conftest" or name.endswith(".conftest") or name in BLOCKED_ROOTS
                            or name == "app.config" or name == "app.main" or name == "app.auth" for name in sys.modules),
                    "no unreviewed config/conftest/main/driver/sender modules")
            actual_app = {name for name in sys.modules if name == "app" or name.startswith("app.")}
            expected_app = {name for name in BINDINGS if name == "app" or name.startswith("app.")} | {"app.database"}
            require(actual_app == expected_app, "exact actual app import closure")
            for name in actual_app - {"app.database"}:
                require(Path(sys.modules[name].__file__) == REPO / BINDINGS[name][0]
                        and sha(bounded_bytes(Path(sys.modules[name].__file__))) == BINDINGS[name][1],
                        "final typed app module origin/hash")
            require(set(sys.modules["app.database"].__dict__) == {
                "__name__", "__doc__", "__package__", "__loader__", "__spec__", "Base", "__getattr__"},
                "inert database exports only real Base")
            return {"attempts": boundary.denials, "pytest_main_calls": boundary.calls,
                    "inherited_fd_census": boundary.fd_census, "trusted_native_open_gate": True,
                    "single_thread_census": boundary.thread_census, "absolute_fatal_deadline": True,
                    "cache_calls": len(boundary.cache_hits), "cache_distinct": len({tuple(row) for row in boundary.cache_hits}),
                    "app_modules": sorted(name for name in sys.modules if name == "app" or name.startswith("app."))}

        check("closed_boundary", closed_state)
    proof["postcheck"] = {"ok": not issues, "results": results, "issues": issues}
    return not issues


def main():
    mode, directories = approval()
    started = time.monotonic()
    original_env = dict(os.environ)
    evidence, scratch = directories["DX_EVIDENCE_DIR"], directories["DX_SCRATCH_DIR"]
    proof = {"mode": mode, "ok": False, "base": BASE, "checker_base": CHECKER_BASE,
             "runner_sha256": os.environ["DX_RUNNER_SHA256"], "expected_nodeids": [],
             "unproven": {"20M": "UNPROVEN", "11_gates": "UNPROVEN", "official_SDK_generation": "NOTRUN",
                          "SDK_freshness": "NOTRUN", "HTTP_SQL_lifespan_jobs_runtime": "NOTRUN"},
             "bounds": {"wall_seconds": WALL_SECONDS, "cpu_seconds": 150, "RAM_bytes": 2 * 1024 ** 3,
                        "file_bytes": MAX_FILE, "stdout_stderr_bytes": MAX_OUTPUT,
                        "artifact_and_scratch_bytes": MAX_ARTIFACT_BYTES, "free_floor_bytes": FREE_FLOOR},
             "adapters": [], "phase": "preflight", "errors": []}
    if KERNEL is not None:
        proof["safety_acceptance"] = "EXTERNAL_FINAL_PENDING"
        proof["admission_sha256"] = KERNEL.admission_sha256
        proof["nonce"] = KERNEL.a["nonce"]
        proof["clock"] = "CLOCK_MONOTONIC_MS"
    boundary, external_state, payload = None, {}, None
    deadline = AbsoluteDeadline(started)
    success = False
    try:
        set_limits()
        deadline.control("work")
        proof["expected_nodeids"] = expected_ids()
        proof["sources_before"], source_bindings = sources()
        proof["inventory_before"], site_bindings = inventory()
        if mode == "prepare":
            payload, external_state = prepare_cache(evidence, scratch, proof)
            success = True
        else:
            cache, proof["source"], external_state = sealed_cache(directories)
            if KERNEL is not None:
                external_state.update(KERNEL.external_state)
                proof["kernel_before"] = KERNEL.verify()
            proof["sealed_cache_sha256"] = os.environ["DX_PREPARED_CACHE_SHA256"]
            require(Path(sys.base_prefix).absolute() == STDLIB.parents[1], "stdlib prefix binding")
            paths = []
            for entry in sys.path:
                path = Path(entry)
                if path == STDLIB.parent / "python313.zip" and not path.exists() and not path.is_symlink():
                    continue
                require(path.is_absolute() and path.is_dir() and lexical(path).is_relative_to(STDLIB), "stdlib-only search roots")
                paths.append(str(path))
            sys.path[:] = [str(SERVER), str(SITE), *paths]
            tempfile.tempdir = str(scratch)
            boundary = Boundary(directories, source_bindings, site_bindings, cache, external_state, deadline)
            proof["phase"] = "install_closed_boundary"
            if KERNEL is not None:
                KERNEL.startup_freshness()
            boundary.install()  # Always before app/framework imports, including package __init__.
            proof["adapters"].append(inert_database(boundary))
            proof["adapters"].extend([
                {"name": "check_output_exact12_real_git_cache", "actual_checker_unchanged": True,
                 "unknown_calls": "DENY_AND_RECORD", "hidden_host_Git_access": False},
                {"name": "typed_source_loader_and_direct_spec", "source_bytes_only": True, "pyc_read": "DENIED"}])
            proof["phase"] = "pytest_original26"
            run_pytest(boundary, evidence, proof)
            proof["phase"] = "actual_canonical_browser_exports"
            schema_exports(boundary, evidence, proof)
            success = True
    except BaseException as error:
        proof["errors"].append({"phase": proof["phase"], "type": type(error).__name__,
                                "trace": "".join(traceback.format_exception(error))[-65536:]})
    finally:
        # Never turn FAIL/guard exceptions/skips/missing collection into success;
        # all feasible source/site/seal/environment/artifact checks run on FAIL.
        proof["phase"] = "postcheck"
        deadline.control("post")  # Fixed min(started+180, first_post_entry+30).
        post_ok = postcheck(directories, original_env, proof, boundary, external_state)
        proof["ok"] = success and post_ok
        proof["elapsed_seconds"] = round(time.monotonic() - started, 6)
        if boundary is not None:
            proof["guard_attempts"] = boundary.denials
            proof["resolver_hits"] = boundary.cache_hits
            write_json(evidence / "phases.json", proof.get("pytest", {"collection": "NOT_REACHED"}), directories)
            write_json(evidence / "imports.json", boundary.imports, directories)
        if mode == "prepare" and proof["ok"]:
            proof["prepared_cache"] = write_json(evidence / "prepare-cache.json", payload, directories)
        # Full final scan includes late phases/imports/prepare-cache artifacts;
        # the narrow writer reserves one file and the actual encoded receipt bytes.
        proof["final_artifacts"] = artifact_scan(directories)
        require(time.monotonic() - started <= WALL_SECONDS, "total wall time including postcheck")
        write_json(evidence / "receipt.json", proof, directories)
        receipt = evidence / "receipt.json"
        receipt_info = lexical(receipt).stat()
        require(stat.S_ISREG(receipt_info.st_mode) and stat.S_IMODE(receipt_info.st_mode) == 0o600
                and receipt_info.st_uid == os.getuid() and receipt_info.st_nlink == 1
                and receipt_info.st_size <= MAX_FILE, "final receipt regular owner/mode/nlink/byte bound")
        # Retain the closed boundary until process exit; do not restore process,
        # network or settings capabilities in a finally block.
    summary = {"ok": proof["ok"], "mode": mode, "receipt": str(evidence / "receipt.json"),
               "receipt_sha256": sha(bounded_bytes(evidence / "receipt.json")),
               "unproven": proof["unproven"]}
    if KERNEL is not None:
        summary.update({"safety_acceptance": "EXTERNAL_FINAL_PENDING", "admission_sha256": KERNEL.admission_sha256,
                        "nonce": KERNEL.a["nonce"], "clock": "CLOCK_MONOTONIC_MS"})
    if proof.get("prepared_cache"):
        summary["prepared_cache"] = proof["prepared_cache"]
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0 if proof["ok"] else 1


if __name__ == "__main__":
    try:
        status = main()
    except BaseException as failure:
        sys.stderr.write("ROOT partner-DX gate failed: " + type(failure).__name__ + ": " + str(failure)[:2000] + "\n")
        status = 1
    raise SystemExit(status)
