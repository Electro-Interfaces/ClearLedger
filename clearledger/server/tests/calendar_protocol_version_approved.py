"""ROOT-only M09-C2 frozen native/SQL/pure stage gate; never run by workers."""
from contextlib import ExitStack
import contextvars
import importlib.abc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import signal
import resource
import runpy
import socket
import stat
import subprocess
import sys
from urllib.parse import urlsplit
import weakref
from types import CodeType, ModuleType

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "ba9fc30be815a554cb0c646a6c75f59e17c19fb0"
CANDIDATE = Path("/srv/projects/api-modernization-upgrade-test-env-20261030/.venv")
SITE = CANDIDATE / "lib/python3.13/site-packages"
STDLIB = Path("/home/mag/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu/lib/python3.13")
BASELINE_MODEL_SHA = "f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e"
PORT = 33546
DATABASE = "api_calendar_protocol_version_test_20261031"
RUNTIME = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}

APP_DIGEST = '247876a7d8be6c4aa31e71b508d1fce581021dfa71bc1a95186ef743fc12ad95'
TESTS_DIGEST = '0f2a89debf5895ae1efb8ff38fd6183402f0110db1df6d2ba547df548bb8b8f0'
SCHEMA_DIGEST = '145c7feedb786d3df47d00c826b26c48ad666cd52bc60d381a4cad10ba265372'
APP_COUNT = 499
TESTS_COUNT_WITHOUT_SELF = 373
SCHEMA_COUNT = 21
SUPPORT_FILES = {
    'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0',
    'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601',
    'Dockerfile': 'aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d',
    '../scripts/export-partner-openapi.py': 'b5d52daca7220a523b4c5edc85852de39b0b921e5c033a86029b2f92040abd51',
    '../tools/partner-api-types/generate.mjs': '549d7f05625af2906b4cd44b44f571b5c935ea195490d52d530da5e08fe53817',
    '../tools/partner-api-types/package.json': '900597c5e189affc56dc83b662a84e77b149de8177302ebe07b05954bf61f380',
    '../tools/partner-api-types/package-lock.json': 'c7f9ba06a2e02383cc7409b071fea099a03df4ad796287de249d9250a0d292ac',
    '../tools/partner-api-types/generation.test.mjs': 'af7e5a544a2247ef0269fae323c928d411e0d89166f85113d71099204a599266',
    '../tools/partner-api-types/consumer.ts': '28b26158dbd0c8e6054cae74db3927210031d0dea695107537cc431bde7bc047',
}
TOOL_TREES = {
    'sqlalchemy': (268, 'a6476b4195ce507ae5c42a7dbcfec0ee256935ea27ae60e6047799e56f010beb'),
    'asyncpg': (81, 'c716bdbecb918d51e57aa934cc19cbcf67963d4147bde7f1a428ea8b3bfca3d1'),
}
TOOL_MAX_BLOB = 16 * 1024 * 1024
TOOL_SOURCE_FILES = {
    '_pytest/pathlib.py': '514a634ce07ff8f773e5951b47cd321e18699b8616ec8cc3a5bf6978615e3655',
    '_pytest/tmpdir.py': '5834124a28502a4cbea5a98370c32eb023359163a42b491a7d7ef46c2dec459a',
    '_pytest/monkeypatch.py': '4e9fcbb78e492e24db6ce88ab76e155194119716ff051be93f854b9b9d51468a',
}
MANAGEMENT_FIXTURE_SHA = 'cf0a2d05e21970fce0a1404ea6220dab5614efffa7a9f1226d26ab698e2884e5'
CORRECTIVE_NODEIDS = (
    'tests/test_calendar_query_owner.py::test_sql_fixed_ids_owner_is_participation_not_company_or_date_acl',
    'tests/test_calendar_query_owner.py::test_native_list_keeps_company_period_visibility_and_no_duplicates[mine-False-expected0]',
    'tests/test_calendar_query_owner.py::test_native_list_keeps_company_period_visibility_and_no_duplicates[company-False-expected1]',
    'tests/test_calendar_query_owner.py::test_native_list_keeps_company_period_visibility_and_no_duplicates[mine-True-expected2]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[organizer-200]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[attendee-200]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[both-200]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[declined-200]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[public-200]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[hidden-403]',
    'tests/test_calendar_query_owner.py::test_native_detail_keeps_existing_http_acl[foreign-404]',
    'tests/test_calendar_query_owner.py::test_management_uses_direct_owner_without_native_hook_or_writes',
    'tests/test_calendar_query_owner.py::test_management_http_golden_utc_and_limit',
    'tests/test_calendar_query_owner.py::test_admin_nonparticipant_keeps_personal_calendar_and_detail_private[False]',
    'tests/test_calendar_query_owner.py::test_admin_nonparticipant_keeps_personal_calendar_and_detail_private[True]',
    'tests/test_calendar_query_owner.py::test_existing_caller_membership_modules_and_legacy_profile_split[disabled-profile]',
    'tests/test_calendar_query_owner.py::test_existing_caller_membership_modules_and_legacy_profile_split[membership]',
    'tests/test_calendar_query_owner.py::test_existing_caller_membership_modules_and_legacy_profile_split[modules]',
    'tests/test_calendar_query_owner.py::test_token_feed_preserves_separate_cross_company_trust_and_window',
)
SELECTION = list(CORRECTIVE_NODEIDS)
EXPECTED_COUNTS = [1] * 19
EXPECTED_CASES = 19
MAX_FILES = 4000
MAX_BLOB = 8 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_SECONDS = 600
MAX_CAPTURE_EVENTS = 4000
LIMIT_SCRATCH = 128 * 1024 * 1024
CHILD = SERVER / "tests/calendar_protocol_child_approved.py"
FROZEN_FLAGS = ("ROOT_APPROVED_CALENDAR_PROTOCOL_VERSION_TESTS", "RUN_CALENDAR_QUERY_OWNER_TESTS",
                "RUN_CALENDAR_PROTOCOL_VERSION_TESTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
FROZEN_ENV = {*FROZEN_FLAGS, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY",
              "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "M09_PG_PORT",
              "SEED_SUPERADMIN_EMAIL", "SEED_SUPERADMIN_PASSWORD", "ECOSYSTEM_COMPANIES",
              "M09_EMPTY_CWD", "M09_EVIDENCE_DIR", "M09_RUNNER_SHA256", "TMPDIR", "M09_SCRATCH_DIR",
              "M09_PHASE", "M09_BASELINE_BLOB"}
PURE_FUNCTIONS = {
    "test_real_offline_cli_with_minimal_environment", "test_imports_do_not_load_driver_or_app",
    "test_changed_verifier_is_rejected_before_its_import_marker_executes",
    "test_unittest_and_preflight_paths_refuse_before_driver_without_flag",
    "test_approval_wrapper_checks_harness_hash_before_running_it",
}


def validate_child_request(phase, origin, argv, environ, scratch):
    """Only the five frozen pure subprocess sites and old PG13 test12 CLI."""
    if not isinstance(argv, (list, tuple)) or len(argv) < 3 or argv[0] != sys.executable or argv[1] != "-I":
        refuse("child interpreter/argv")
    if phase == "foundation":
        raw = "postgresql://clearledger:api_test_only@127.0.0.1:33546/" + DATABASE
        for mode in ("apply", "check"):
            expected = [sys.executable, "-I", str(SERVER / "schema_migrations/runner.py"), mode,
                        "--dsn-env", "SCHEMA_MIGRATION_TEST_DSN", "--database", DATABASE,
                        "--user", "clearledger", "--namespace", "core"]
            if (origin == "test_12_actual_cli_apply_and_check_no_secret_output" and list(argv) == expected
                    and environ == {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
                                    "HOME": os.environ["HOME"], "SCHEMA_MIGRATION_TEST_DSN": raw}):
                return
        refuse("only actual frozen test12 CLI is authorized")
    if phase != "pure" or origin not in PURE_FUNCTIONS:
        refuse("unapproved subprocess caller")
    if environ not in ({}, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}):
        refuse("pure subprocess environment")
    if argv[2] == "-c":
        import ast
        if len(argv) != 4:
            refuse("pure code argv")
        first = ("import sys; sys.path.insert(0," + repr(str(SERVER)) + "); "
                 "import schema_migrations.runner; "
                 "assert not any(k=='app' or k.startswith('app.') or k=='asyncpg' or k=='schema_migrations.revisions.catalog_v1' for k in sys.modules)")
        parsed = ast.parse((SERVER / "schema_migrations/tests/test_pure.py").read_bytes())
        cls = next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == "PureFoundation")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == "test_unittest_and_preflight_paths_refuse_before_driver_without_flag")
        assignment = next(n for n in fn.body if isinstance(n, ast.Assign) and n.targets[0].id == "code")
        raw = assignment.value.func.value
        if not isinstance(raw, ast.Constant) or not isinstance(raw.value, str):
            refuse("frozen pure source shape")
        second = raw.value.replace("SERVER", repr(str(SERVER)))
        if (origin, argv[3]) not in {
            ("test_imports_do_not_load_driver_or_app", first),
            ("test_unittest_and_preflight_paths_refuse_before_driver_without_flag", second),
        }:
            refuse("unapproved pure code")
        return
    script = Path(argv[2])
    if script.is_symlink() or not script.is_absolute() or not script.is_file():
        refuse("pure script path")
    if script == SERVER / "schema_migrations/runner.py" or (
            script.is_relative_to(scratch) and script.parts[-2:] == ("schema_migrations", "runner.py")):
        source = SERVER / "schema_migrations/runner.py"
        tail = ["plan"]
    elif (script.is_relative_to(scratch)
          and script.parts[-3:] == ("schema_migrations", "tests", "approved_postgres.py")):
        source = SERVER / "schema_migrations/tests/approved_postgres.py"
        tail = ["--execute-approved-contract-tests"]
    else:
        refuse("pure script allowlist")
    if list(argv[3:]) != tail or hashlib.sha256(script.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
        refuse("pure script bytes/selection")


def bind_subprocesses(phase, stack, counters, capability, scratch):
    from unittest.mock import patch
    native = subprocess.Popen
    if phase == "pure":
        from schema_migrations.tests.test_pure import PureFoundation
        codes = {getattr(PureFoundation, name).__code__: name for name in PURE_FUNCTIONS}
        limit = 5
    elif phase == "foundation":
        from schema_migrations.tests.run_postgres import ActualFoundation
        method = ActualFoundation.test_12_actual_cli_apply_and_check_no_secret_output
        codes = {method.__code__: method.__name__}
        limit = 2
    else:
        return
    launched = []
    def start(argv, *args, **kwargs):
        frame = sys._getframe(1)
        origin = None
        while frame is not None:
            if frame.f_code in codes:
                origin = codes[frame.f_code]
                break
            frame = frame.f_back
        permitted = {"env", "stdin", "stdout", "stderr", "text", "encoding", "errors", "bufsize",
                     "universal_newlines", "close_fds", "restore_signals", "start_new_session", "cwd", "shell"}
        if (origin is None or args or set(kwargs) - permitted or kwargs.get("cwd") is not None
                or kwargs.get("stdin") is not None or kwargs.get("stdout") != subprocess.PIPE
                or kwargs.get("stderr") != subprocess.PIPE or kwargs.get("close_fds", True) is not True
                or kwargs.get("restore_signals", True) is not True or kwargs.get("start_new_session", False)
                or kwargs.get("shell", False) is not False
                or len(launched) >= limit):
            refuse("subprocess options/caller/count")
        requested_env = kwargs.get("env")
        validate_child_request(phase, origin, argv, requested_env, scratch)
        payload = scratch / f"approved-child-test-{len(launched)}.json"
        raw = json.dumps({"phase": phase, "origin": origin, "argv": list(argv), "environment": requested_env}).encode()
        if len(raw) > 64 * 1024:
            refuse("child payload bound")
        with payload.open("xb") as output:
            output.write(raw)
        child_env = {**os.environ, "M09_CHILD_PAYLOAD": str(payload),
                     "M09_CHILD_SHA256": hashlib.sha256(CHILD.read_bytes()).hexdigest()}
        command = [sys.executable, "-I", "-S", "-B", str(CHILD), "--execute-approved-m09-child"]
        kwargs["env"] = child_env
        token = capability.set((sys.executable, command, None, child_env))
        try:
            process = native(command, **kwargs)
            launched.append({"origin": origin, "pid": process.pid, "payload_sha256": hashlib.sha256(raw).hexdigest()})
            return process
        finally:
            capability.reset(token)
    stack.enter_context(patch.object(subprocess, "Popen", start))
    counters["children"] = launched


def refuse(message="calendar protocol immutable approval boundary refused"):
    raise RuntimeError(message)


def current_test_phase():
    value = os.environ.get("PYTEST_CURRENT_TEST", "")
    node, separator, phase = value.rpartition(" (")
    return (node, phase[:-1]) if separator and phase.endswith(")") else ("", "")


def selection_allowed(nodes):
    return len(nodes) == 19 and len(set(nodes)) == 19 and set(nodes) == set(CORRECTIVE_NODEIDS)


def fixture_metadata_allowed(caller, expected, node, phase, key, path_owned, contents_expected):
    return (caller == expected and node in CORRECTIVE_NODEIDS and phase == "setup"
            and key == "MANAGEMENT_CONFIG_PATH" and path_owned is True and contents_expected is True)


def symlink_metadata_allowed(caller, expected, node, phase, root_exact, target_exact, path_owned):
    return (caller == expected and node in CORRECTIVE_NODEIDS and phase == "setup"
            and root_exact is True and target_exact is True and path_owned is True)


def unbind_metadata_allowed(caller, expected, node, phase, key, binding_exists, current_matches):
    return (caller == expected and node in CORRECTIVE_NODEIDS and phase == "teardown"
            and key == "MANAGEMENT_CONFIG_PATH" and binding_exists is True and current_matches is True)


def fixture_metadata_controls():
    good = dict(caller=("pinned",), expected=("pinned",), node=CORRECTIVE_NODEIDS[0], phase="setup",
                key="MANAGEMENT_CONFIG_PATH", path_owned=True, contents_expected=True)
    result = {"management_positive": fixture_metadata_allowed(**good)}
    for name, key, bad in (("foreign_caller", "caller", ("foreign",)), ("foreign_node", "node", "other"),
                           ("wrong_key", "key", "OTHER"), ("outside_path", "path_owned", False),
                           ("wrong_contents", "contents_expected", False), ("wrong_phase", "phase", "call")):
        result["management_" + name] = not fixture_metadata_allowed(**{**good, key: bad})
    link = dict(caller=("pinned",), expected=("pinned",), node=CORRECTIVE_NODEIDS[0], phase="setup",
                root_exact=True, target_exact=True, path_owned=True)
    result["symlink_positive"] = symlink_metadata_allowed(**link)
    for name, key, bad in (("foreign_caller", "caller", ("foreign",)), ("foreign_node", "node", "other"),
                           ("wrong_root", "root_exact", False), ("wrong_target", "target_exact", False),
                           ("outside_path", "path_owned", False), ("wrong_phase", "phase", "call")):
        result["symlink_" + name] = not symlink_metadata_allowed(**{**link, key: bad})
    result.update(selection_positive=selection_allowed(CORRECTIVE_NODEIDS),
                  extra_selector=not selection_allowed((*CORRECTIVE_NODEIDS, "extra")),
                  duplicate_selector=not selection_allowed((*CORRECTIVE_NODEIDS[:-1], CORRECTIVE_NODEIDS[0])),
                  missing_selector=not selection_allowed(CORRECTIVE_NODEIDS[:-1]))
    unbind = dict(caller=("pinned",), expected=("pinned",), node=CORRECTIVE_NODEIDS[0], phase="teardown",
                  key="MANAGEMENT_CONFIG_PATH", binding_exists=True, current_matches=True)
    result["unbind_positive"] = unbind_metadata_allowed(**unbind)
    for name, key, bad in (("foreign_caller", "caller", ("foreign",)), ("foreign_node", "node", "other"),
                           ("wrong_key", "key", "OTHER"), ("wrong_phase", "phase", "setup"),
                           ("missing_binding", "binding_exists", False), ("wrong_value", "current_matches", False)):
        result["unbind_" + name] = not unbind_metadata_allowed(**{**unbind, key: bad})
    return result


def code_metadata(code):
    return (code.co_filename, code.co_qualname, code.co_firstlineno, code.co_argcount,
            hashlib.sha256(code.co_code).hexdigest())


def frozen_code(path, qualname):
    code = compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
    pending = [code]
    while pending:
        item = pending.pop()
        if item.co_qualname == qualname:
            return code_metadata(item)
        pending.extend(value for value in item.co_consts if isinstance(value, CodeType))
    refuse("pinned source function missing")


class CorrectiveFixturePolicy:
    def __init__(self, scratch, counters):
        self.counters = counters
        self.root = scratch / "pytest-test"
        self.expected_contents = json.dumps({"enabled": True, "hub_enabled": True, "code": "desk",
                                             "name": "Управляющее пространство"}).encode()
        self.fixture = frozen_code(SERVER / "tests/test_management_api.py", "management_data")
        self.undo = frozen_code(SITE / "_pytest/monkeypatch.py", "MonkeyPatch.undo")
        self.link = frozen_code(SITE / "_pytest/pathlib.py", "_force_symlink")
        self.link_caller = frozen_code(SITE / "_pytest/tmpdir.py", "TempPathFactory._make_counted_dir")
        self.bindings = {}
        self.tmpdirs = {}
        self.record = {"management_sets": [], "management_unsets": [], "symlink_suppressed": [],
                       "metadata_controls": fixture_metadata_controls()}
        counters["fixture_admission"] = self.record
        if not all(self.record["metadata_controls"].values()) or "MANAGEMENT_CONFIG_PATH" in os.environ:
            refuse("corrective fixture controls/ambient config")

    def stack_caller(self, expected):
        frame = sys._getframe(1)
        while frame is not None:
            actual = code_metadata(frame.f_code)
            if actual == expected:
                return actual
            frame = frame.f_back
        return None

    def set_management(self, key, value):
        node, phase = current_test_phase()
        path = Path(value)
        owned = (path.is_absolute() and path.parent.parent == self.root and path.parent == self.tmpdirs.get(node)
                 and path.name == "management.json"
                 and not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file()
                 and stat.S_ISREG(path.stat().st_mode) and path.stat().st_uid == os.getuid()
                 and path.stat().st_mode & 0o777 == 0o600 and path.stat().st_size <= 512)
        contents = owned and path.read_bytes() == self.expected_contents
        if (not fixture_metadata_allowed(self.stack_caller(self.fixture), self.fixture, node, phase, key, owned, contents)
                or node in self.bindings or node in self.record["management_sets"] or len(self.record["management_sets"]) >= 19):
            refuse("unapproved management fixture binding")
        self.bindings[node] = value
        self.record["management_sets"].append(node)

    def unset_management(self):
        node, phase = current_test_phase()
        if (not unbind_metadata_allowed(self.stack_caller(self.undo), self.undo, node, phase, "MANAGEMENT_CONFIG_PATH",
                                        node in self.bindings, self.bindings.get(node) == os.environ.get("MANAGEMENT_CONFIG_PATH"))
                or node in self.record["management_unsets"]):
            refuse("unapproved management fixture unbinding")
        self.bindings.pop(node)
        self.record["management_unsets"].append(node)

    def install_symlink_suppression(self, patch):
        import _pytest.pathlib as paths
        import _pytest.tmpdir as tmpdir
        original = paths._force_symlink
        if original is not tmpdir._force_symlink or code_metadata(original.__code__) != self.link:
            refuse("pinned pytest symlink alias metadata")
        def suppressed(root, target, link_to):
            node, phase = current_test_phase()
            prefix = re.sub(r"\W", "_", node.split("::")[-1])[:30]
            path = Path(link_to)
            owned = (path.parent == self.root and path.is_dir() and not path.is_symlink()
                     and path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0
                     and re.fullmatch(re.escape(prefix) + r"[0-9]+", path.name) is not None)
            if (not symlink_metadata_allowed(self.stack_caller(self.link_caller), self.link_caller, node, phase,
                                            Path(root) == self.root, str(target) == prefix + "current", owned)
                    or node in self.record["symlink_suppressed"] or len(self.record["symlink_suppressed"]) >= 19):
                if len(self.counters["forbidden"]) < MAX_CAPTURE_EVENTS:
                    self.counters["forbidden"].append({"category": "pytest-symlink-suppression-metadata",
                                                       "nodeid": node if node in CORRECTIVE_NODEIDS else "unknown"})
                refuse("unapproved pytest current symlink suppression")
            self.record["symlink_suppressed"].append(node)
            self.tmpdirs[node] = path
        patch.setattr(paths, "_force_symlink", suppressed)
        patch.setattr(tmpdir, "_force_symlink", suppressed)

    def complete(self):
        return (not self.bindings and all(self.record["metadata_controls"].values())
                and all(selection_allowed(self.record[key]) for key in
                        ("management_sets", "management_unsets", "symlink_suppressed")))


def tree_digest(path, *, count, exclude_self=False):
    entries = list(path.rglob("*"))
    if path.is_symlink() or len(entries) > 2 * MAX_FILES or any(p.is_symlink() for p in entries):
        refuse("source symlinks/count differ from approval")
    files = sorted(p for p in entries if "__pycache__" not in p.parts and p.is_file()
                   and not (exclude_self and p == Path(__file__).resolve()))
    if (len(files) != count or len(files) > MAX_FILES
            or any(p.stat().st_size > MAX_BLOB for p in files)
            or sum(p.stat().st_size for p in files) > MAX_TREE
            or any(not stat.S_ISREG(p.stat().st_mode) for p in files)):
        refuse("frozen source count/bytes/type differ")
    manifest = [[str(p.relative_to(SERVER)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files]
    return hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()


def private_empty(value):
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or not path.is_dir()
            or any(p.is_symlink() for p in [path, *path.parents])
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077
            or "test" not in path.name.lower() or any(path.iterdir())):
        refuse("four separate private owned empty test directories required")
    return path


def verify_approval():
    if sys.argv[1:] != ["--execute-approved-calendar-protocol-version-tests"]:
        refuse("exact ROOT execution argument required")
    if (sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize or not sys.dont_write_bytecode
            or not sys.flags.isolated or not sys.flags.no_site
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"
            or Path(sys.executable).absolute().parent != CANDIDATE / "bin"
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)
            or any(m in sys.modules for m in ("pytest", "app", "site"))):
        refuse("unoptimized Python 3.13 with bytecode writes disabled required")
    flags = FROZEN_FLAGS
    if any(os.environ.get(flag) != "1" for flag in flags):
        refuse("explicit ROOT/test opt-ins required")
    allowed = FROZEN_ENV
    if set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("clean allowlisted environment and preserved actual HOME required")
    if os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != "calendar-protocol-version-synthetic-secret-only":
        refuse("synthetic test settings required")
    if (os.environ.get("SEED_SUPERADMIN_EMAIL") != "admin@clearledger.ru"
            or os.environ.get("SEED_SUPERADMIN_PASSWORD") != "admin123"
            or os.environ.get("ECOSYSTEM_COMPANIES") != ""):
        refuse("explicit synthetic conftest seed required before cached Settings import")
    expected_self = os.environ.get("M09_RUNNER_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_self) or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected_self:
        refuse("ROOT-reviewed immutable runner SHA required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching database URLs required")
    target = urlsplit(raw)
    port = os.environ.get("M09_PG_PORT", "")
    if (not re.fullmatch(r"[1-9][0-9]{0,4}", port) or not 1024 <= int(port) <= 65535
            or target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or not target.username or not target.password
            or target.path != "/" + DATABASE or target.port != PORT or int(port) != PORT
            or target.username != "clearledger" or target.password != "api_test_only"
            or "@" in target.username or ":" in target.username):
        refuse("exact ROOT-approved numeric loopback PostgreSQL disposable database required")
    empty = private_empty(os.environ.get("M09_EMPTY_CWD", ""))
    upload = private_empty(os.environ.get("UPLOAD_DIR", ""))
    evidence = private_empty(os.environ.get("M09_EVIDENCE_DIR", ""))
    scratch = private_empty(os.environ.get("M09_SCRATCH_DIR", ""))
    directories = [p.resolve() for p in (empty, upload, evidence, scratch)]
    if (Path.cwd() != empty or os.environ.get("TMPDIR") != str(scratch) or len(set(directories)) != 4
            or any(a != b and (a.is_relative_to(b) or b.is_relative_to(a))
                   for a in directories for b in directories)
            or any(p.is_relative_to(SERVER / "app") or p.is_relative_to(SERVER / "tests")
                   or p.is_relative_to(SERVER / "schema_migrations") for p in directories)):
        refuse("separate non-nested cwd/upload/evidence/scratch directories required")
    for origin in (empty, SERVER):
        if any((path / ".env").exists() or (path / ".env").is_symlink() for path in (origin, *origin.parents)):
            refuse("dotenv ancestor")
    if (tree_digest(SERVER / "app", count=APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full app/tests/schema differs from approval")
    if any((SERVER / path).is_symlink() or hashlib.sha256((SERVER / path).read_bytes()).hexdigest() != expected
           for path, expected in SUPPORT_FILES.items()):
        refuse("test configuration/dependency source differs")
    os.umask(0o077)
    installed = inventory()
    blob = Path(os.environ.get("M09_BASELINE_BLOB", ""))
    if (os.environ.get("M09_PHASE") != "native"
            or not blob.is_absolute() or not blob.is_file() or blob.is_symlink()
            or blob.stat().st_uid != os.getuid() or blob.stat().st_mode & 0o077
            or blob.stat().st_size > MAX_BLOB or any(p.is_symlink() for p in blob.parents)
            or hashlib.sha256(blob.read_bytes()).hexdigest() != BASELINE_MODEL_SHA):
        refuse("exact ROOT-owned legacy model blob and phase required")
    paths = []
    for entry in sys.path:
        path = Path(entry)
        if path == STDLIB.parent / "python313.zip" and not path.exists() and not path.is_symlink():
            continue
        if not path.is_dir() or not path.is_absolute() or not path.resolve().is_relative_to(STDLIB.resolve()):
            refuse("unknown interpreter search path")
        paths.append(str(path))
    sys.path[:] = paths
    return evidence, scratch, upload, target, installed


def inventory():
    if not SITE.is_dir() or SITE.is_symlink() or not CANDIDATE.is_dir():
        refuse()
    cfg = (CANDIDATE / "pyvenv.cfg").read_text()
    if not re.search(r"^include-system-site-packages\s*=\s*false\s*$", cfg, re.M):
        refuse()
    if any(p.is_symlink() or p.suffix == ".pth" or p.name in {"sitecustomize.py", "usercustomize.py"}
           for p in SITE.rglob("*")):
        refuse()
    installed = {}
    for dist in importlib.metadata.distributions(path=[str(SITE)]):
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name in installed:
            refuse()
        installed[name] = dist.version
    if len(RUNTIME) != 61 or len(TOOLS) != 16 or set(RUNTIME) & set(TOOLS) or installed != {**RUNTIME, **TOOLS}:
        refuse()
    if (any(hashlib.sha256((SITE / name).read_bytes()).hexdigest() != digest
            for name, digest in TOOL_SOURCE_FILES.items())
            or hashlib.sha256((SERVER / "tests/test_management_api.py").read_bytes()).hexdigest() != MANAGEMENT_FIXTURE_SHA):
        refuse("exact corrective fixture/pytest sources required")
    for name, (count, digest) in TOOL_TREES.items():
        files = sorted(p for p in (SITE / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        if (len(files) != count or any(p.stat().st_size > TOOL_MAX_BLOB for p in files)
                or sum(p.stat().st_size for p in files) > MAX_TREE):
            refuse("tool source bounds")
        manifest = [[str(p.relative_to(SITE)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files]
        if hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest() != digest:
            refuse("tool source hashes")
    return installed

def pg_sendmsg_metadata_allowed(family, socktype, protocol, owned_fd, current_fd,
                               peer_exact, extra_args, extra_kwargs):
    """Pure metadata policy; no data buffers, addresses, sockets or I/O inspected."""
    return (family == socket.AF_INET and socktype == socket.SOCK_STREAM
            and protocol in (0, socket.IPPROTO_TCP)
            and type(owned_fd) is int and owned_fd >= 0
            and type(current_fd) is int and current_fd >= 0 and current_fd == owned_fd
            and peer_exact is True and not extra_args and not extra_kwargs)

def sendmsg_metadata_controls():
    """One positive and exact negative source matrix; no live socket/probe is created."""
    good = dict(family=socket.AF_INET, socktype=socket.SOCK_STREAM,
                protocol=socket.IPPROTO_TCP, owned_fd=17, current_fd=17,
                peer_exact=True, extra_args=(), extra_kwargs={})
    bad = {
        'unowned': {'owned_fd': None}, 'closed': {'current_fd': -1},
        'fd_reused_or_detached': {'current_fd': 18}, 'wrong_peer_or_unconnected': {'peer_exact': False},
        'datagram': {'socktype': socket.SOCK_DGRAM}, 'unix': {'family': socket.AF_UNIX},
        'ipv6': {'family': socket.AF_INET6}, 'raw': {'socktype': socket.SOCK_RAW},
        'other_protocol': {'protocol': 132}, 'ancillary': {'extra_args': ((('forbidden',),),)},
        'explicit_flags_even_zero': {'extra_args': ((), 0)},
        'explicit_address': {'extra_args': ((), 0, ('forbidden', 1))},
        'keyword_flags': {'extra_kwargs': {'flags': 0}},
        'keyword_ancillary': {'extra_kwargs': {'ancdata': ()}},
        'keyword_address': {'extra_kwargs': {'address': None}},
    }
    checks = {'owned_connected_pg_stream_only': pg_sendmsg_metadata_allowed(**good)}
    checks.update({name: not pg_sendmsg_metadata_allowed(**{**good, **changed}) for name, changed in bad.items()})
    if not all(checks.values()):
        raise RuntimeError('PG sendmsg metadata source controls failed')
    return checks

def install_boundaries(target, counters, stack, writable, *, sql=True, child_capability=None, environment_values=None,
                       fixture_policy=None):
    owned = weakref.WeakKeyDictionary()
    active_sendmsg = contextvars.ContextVar("r1_pg_sendmsg", default=None)
    native_sendmsg = socket.socket.sendmsg
    native_fileno, native_peer, native_type = socket.socket.fileno, socket.socket.getpeername, socket.socket.getsockopt
    environment = {**os.environ, **(environment_values or {})}

    def owned_path(value, dir_fd=-1):
        if type(value) is int:
            path = Path(os.readlink(f"/proc/self/fd/{value}"))
        else:
            path = Path(os.fsdecode(value))
            if not path.is_absolute() and isinstance(dir_fd, int) and dir_fd >= 0:
                path = Path(os.readlink(f"/proc/self/fd/{dir_fd}")) / path
        resolved = path.resolve()
        return any(resolved.is_relative_to(root) for root in writable)

    def allowed(sock, args=(), kwargs=None):
        try:
            return pg_sendmsg_metadata_allowed(
                sock.family, native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE), sock.proto,
                owned.get(sock), native_fileno(sock), native_peer(sock) == ("127.0.0.1", PORT),
                args, {} if kwargs is None else kwargs)
        except (OSError, TypeError, AttributeError):
            return False

    def deny(event):
        if len(counters["forbidden"]) < MAX_CAPTURE_EVENTS:
            frames = []
            frame = sys._getframe(1)
            while frame is not None and len(frames) < 6:
                module = frame.f_globals.get("__name__", "unknown")
                frames.append({"module": module[:96] if isinstance(module, str) else "unknown",
                               "function": frame.f_code.co_name[:96], "line": frame.f_lineno})
                frame = frame.f_back
            node, phase = current_test_phase()
            counters["forbidden"].append({"category": event, "stack": frames,
                                          "nodeid": node if node in CORRECTIVE_NODEIDS else "unknown", "when": phase})
        refuse()

    def audit(event, args):
        if event == "socket.connect":
            sock, address = args
            if (not sql or address != ("127.0.0.1", PORT) or sock.family != socket.AF_INET
                    or native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                    or sock.proto not in (0, socket.IPPROTO_TCP) or native_fileno(sock) < 0):
                deny(event)
            owned[sock] = native_fileno(sock)
            counters["pg_connect"] += 1
        elif event == "socket.sendmsg":
            active = active_sendmsg.get()
            if (active is None or len(args) != 2 or args[0] is not active[0] or args[1] is not None
                    or sys._getframe(1).f_code is not exact_sendmsg.__code__ or not allowed(args[0])
                    or native_fileno(args[0]) != active[1]):
                deny(event)
            counters["pg_sendmsg"] += 1
        elif event == "socket.getaddrinfo":
            if not sql or args[0] != "127.0.0.1" or int(args[1]) != PORT:
                deny(event)
        elif event == "subprocess.Popen":
            permitted = child_capability.get() if child_capability is not None else None
            if (permitted is None or args[0] != permitted[0] or list(args[1]) != permitted[1]
                    or args[2] != permitted[2] or args[3] != permitted[3]):
                deny(event)
            counters["child_processes"] = counters.get("child_processes", 0) + 1
        elif event in {"socket.bind", "socket.sendto", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
                       "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty", "os.link", "os.symlink", "os.chown"}:
            deny(event)
        elif event == "os.rename":
            if not owned_path(args[0], args[2]) or not owned_path(args[1], args[3]):
                deny("rename-outside-owned-roots")
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
            index = {"os.mkdir": 2, "os.remove": 1, "os.rmdir": 1, "os.chmod": 2, "os.utime": 3}.get(event)
            fd = args[index] if index is not None and len(args) > index else -1
            if not owned_path(args[0], fd):
                deny("mutation-outside-owned-roots")
        elif event == "os.putenv":
            key, value = (os.fsdecode(v) for v in args)
            if key == "MANAGEMENT_CONFIG_PATH" and fixture_policy is not None:
                try:
                    fixture_policy.set_management(key, value)
                except Exception:
                    deny("management-fixture-binding")
                return
            pytest_value = (key == "PYTEST_VERSION" and value == TOOLS["pytest"]) or (
                key == "PYTEST_CURRENT_TEST" and len(value) < 2048
                and value.endswith((" (setup)", " (call)", " (teardown)"))
                and value.rpartition(" (")[0] in CORRECTIVE_NODEIDS)
            if environment.get(key) != value and not pytest_value:
                deny("unapproved-environment-value")
        elif event == "os.unsetenv":
            key = os.fsdecode(args[0])
            if key == "MANAGEMENT_CONFIG_PATH" and fixture_policy is not None:
                try:
                    fixture_policy.unset_management()
                except Exception:
                    deny("management-fixture-unbinding")
                return
            if key not in environment and key not in {"PYTEST_VERSION", "PYTEST_CURRENT_TEST"}:
                deny("unapproved-environment-removal")
        elif event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            if (path.name in {".env", ".netrc", ".pgpass", ".git-credentials"} or path.name.startswith(".env.")
                    or {".ssh", ".vault", ".claude", ".postgresql", ".aws", ".azure", ".kube", ".gnupg"} & set(path.parts)):
                deny(event)
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                absolute = path.resolve()
                if not any(absolute.is_relative_to(root) for root in writable):
                    deny("write-outside-owned-test-roots")

    def exact_sendmsg(sock, buffers, *args, **kwargs):
        if not allowed(sock, args, kwargs):
            deny("sendmsg-metadata")
        capability = active_sendmsg.set((sock, native_fileno(sock)))
        try:
            return native_sendmsg(sock, buffers)
        finally:
            active_sendmsg.reset(capability)

    sys.addaudithook(audit)
    from unittest.mock import patch
    stack.enter_context(patch.object(socket.socket, "sendmsg", exact_sendmsg))
    stack.enter_context(patch.object(socket.socket, "listen", lambda *a, **k: deny("socket.listen")))
    # Reviewed import-only urllib3 IPv6 probe suppression; no bind is permitted.
    old_ipv6 = socket.has_ipv6
    try:
        socket.has_ipv6 = False
        import aiohttp
        import aiosmtplib
        import httpx
        import pywebpush
        import requests
    finally:
        socket.has_ipv6 = old_ipv6
    counters["ipv6_probe_flag_restored"] = socket.has_ipv6 is old_ipv6
    if sql:
        import asyncpg
        original_connect = asyncpg.connect
        expected = dict(host="127.0.0.1", port=PORT, database=DATABASE, user=target.username, password=target.password)
        async def connect(dsn=None, **kwargs):
            if dsn is not None:
                parsed = urlsplit(dsn)
                if (parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname != expected["host"]
                        or parsed.port != PORT or parsed.path != "/" + DATABASE or parsed.query or parsed.fragment
                        or parsed.username != target.username or parsed.password != target.password):
                    deny("sql-target")
            if any((key not in kwargs and dsn is None) or (key in kwargs and kwargs[key] != value) for key, value in expected.items()):
                deny("sql-override")
            limits = {"statement_timeout": 20000, "lock_timeout": 2000, "idle_in_transaction_session_timeout": 30000}
            settings = dict(kwargs.get("server_settings") or {})
            for key, cap in limits.items():
                value = int(settings.get(key, cap))
                settings[key] = str(min(value if value > 0 else cap, cap))
            kwargs["server_settings"] = settings
            # The owned numeric-loopback fixture has no TLS/credential-file
            # profile; never consult ~/.postgresql while testing this domain.
            kwargs["ssl"] = False
            kwargs["timeout"] = min(kwargs.get("timeout", 10) or 10, 10)
            kwargs["command_timeout"] = min(kwargs.get("command_timeout", 30) or 30, 30)
            return await original_connect(dsn, **kwargs)
        stack.enter_context(patch.object(asyncpg, "connect", connect))
    async def no_external(*args, **kwargs):
        deny("external-http")
    def no_external_sync(*args, **kwargs):
        deny("external-http")
    stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", no_external))
    stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", no_external_sync))
    stack.enter_context(patch.object(requests.sessions.Session, "request", no_external_sync))
    stack.enter_context(patch.object(aiohttp.ClientSession, "_request", no_external))

    return counters



def scratch_bound(root, anchor):
    now = root.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_uid)
    if identity(now) != anchor or not stat.S_ISDIR(now.st_mode) or now.st_mode & 0o077:
        refuse()
    size = count = 0
    for path in root.rglob("*"):
        count += 1
        try:
            info = path.lstat()
        except FileNotFoundError:
            # Only transient descendants under the unchanged owned root may vanish.
            if not path.is_relative_to(root) or path == root:
                refuse()
            continue
        if stat.S_ISREG(info.st_mode):
            size += info.st_size
        if count > 4096 or size > LIMIT_SCRATCH:
            refuse()
    if identity(root.lstat()) != anchor:
        refuse()
    return size

def sources_unchanged():
    return (tree_digest(SERVER / "app", count=APP_COUNT) == APP_DIGEST
            and tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) == TESTS_DIGEST
            and tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) == SCHEMA_DIGEST
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == os.environ["M09_RUNNER_SHA256"]
            and all(hashlib.sha256((SERVER / path).read_bytes()).hexdigest() == expected
                    for path, expected in SUPPORT_FILES.items()))


def unittest_phase(phase, evidence, scratch, upload, target, installed, counters, controls, stack, capability):
    import ast
    import unittest
    class NoAppRuntime(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("app.") and fullname not in sys.modules:
                refuse("application runtime forbidden in migration/pure stage")
            return None
    sys.meta_path.insert(0, NoAppRuntime())
    bindings = []
    if phase == "pure":
        from schema_migrations.tests.test_pure import PureFoundation
        from schema_migrations.tests.test_calendar_protocol_pure import CalendarPure
        classes, expected = (PureFoundation, CalendarPure), 20
    elif phase == "foundation":
        from schema_migrations import runner
        from schema_migrations.tests import run_postgres as old
        old.RAW = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg:", "postgresql:", 1)
        old.TARGET = os.environ["TEST_DATABASE_URL"]
        old.BASE, old.EMPTY, old.UPLOAD, old.EVIDENCE = scratch, Path.cwd(), upload, evidence
        def guard():
            if (os.environ.get("M09_PHASE") != "foundation" or not sources_unchanged()
                    or inventory() != installed or counters["forbidden"]):
                refuse("PG13 replacement guard refused")
        old.guard = guard
        old.config = lambda **kw: runner.Config(old.RAW, DATABASE, "clearledger", "core", **kw)
        bindings = ["RAW", "TARGET", "BASE", "EMPTY", "UPLOAD", "EVIDENCE", "config", "guard"]
        classes, expected = (old.ActualFoundation,), 13
    else:
        from schema_migrations.tests.calendar_protocol_cases import ProtocolMigration
        classes, expected = (ProtocolMigration,), 9
    bind_subprocesses(phase, stack, counters, capability, scratch)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in classes)
    if suite.countTestCases() != expected:
        refuse("frozen unittest selection changed")
    with (evidence / (phase + ".log")).open("x") as output:
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    source_after = sources_unchanged()
    ok = (result.wasSuccessful() and not result.skipped and result.testsRun == expected and source_after
          and not counters["forbidden"] and all(controls.values()) and inventory() == installed
          and counters["ipv6_probe_flag_restored"])
    if phase in {"pure", "foundation"}:
        ok = ok and len(counters.get("children", [])) == (5 if phase == "pure" else 2)
    old_source = SERVER / "schema_migrations/tests/run_postgres.py"
    parsed = ast.parse(old_source.read_bytes())
    old_guard = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == "guard")
    old_guard_sha = hashlib.sha256(ast.get_source_segment(old_source.read_text(), old_guard).encode()).hexdigest()
    payload = {"ok": bool(ok), "phase": phase, "cases": expected, "run": result.testsRun,
               "skips": len(result.skipped), "errors": len(result.errors), "failures": len(result.failures),
               "source_after": source_after, "candidate_distributions": len(installed),
               "boundary": counters, "sendmsg_controls": controls, "legacy_binding_names": bindings,
               "old_guard_source_sha256": old_guard_sha,
               "new_guard_runner_sha256": os.environ["M09_RUNNER_SHA256"]}
    with (evidence / (phase + "-receipt.json")).open("x") as output:
        json.dump(payload, output, sort_keys=True, indent=2)
    return 0 if ok else 1


def main():
    try:
        evidence, scratch, upload, target, installed = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "calendar_query_source_environment_approval"}))
        return 2
    anchors = {p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_uid) for p in (scratch, upload, evidence)}
    counters = dict(forbidden=[], pg_connect=0, pg_sendmsg=0, delivery={})
    blocked = counters["forbidden"]
    controls = sendmsg_metadata_controls()
    stack = ExitStack()
    phase = os.environ["M09_PHASE"]
    resource.setrlimit(resource.RLIMIT_CPU, (480, 480))
    address_limit = (1 if phase == "pure" else 8) * 1024 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (address_limit, address_limit))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    capability = contextvars.ContextVar("m09_frozen_child", default=None)
    fixture_policy = CorrectiveFixturePolicy(scratch, counters) if phase == "native" else None
    sys.path[:0] = [str(SITE), str(SERVER)]
    install_boundaries(target, counters, stack, (scratch, upload, evidence), sql=phase != "pure",
                       child_capability=capability, fixture_policy=fixture_policy)
    signal.signal(signal.SIGALRM, lambda *_: refuse("calendar protocol execution time bound exceeded"))
    signal.alarm(MAX_SECONDS)
    if phase != "native":
        try:
            return unittest_phase(phase, evidence, scratch, upload, target, installed, counters, controls, stack, capability)
        finally:
            signal.alarm(0)
            stack.close()
            for path, anchor in anchors.items():
                scratch_bound(path, anchor)
    # Observe actual transaction/audit/auth setup writes before app.database,
    # routers or fixtures can create an engine. No SQL text/parameters retained.
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    counters["transactions"] = {"commit": 0, "rollback": 0}
    counters["sql_verbs"] = {}
    def statement(_conn, _cursor, text, _params, _context, _many):
        verb = text.lstrip().split(None, 1)[0].upper() if text.strip() else "EMPTY"
        if verb not in {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "SET", "DO", "WITH"}:
            verb = "OTHER"
        counters["sql_verbs"][verb] = counters["sql_verbs"].get(verb, 0) + 1
    def committed(_conn):
        counters["transactions"]["commit"] += 1
    def rolled_back(_conn):
        counters["transactions"]["rollback"] += 1
    event.listen(Engine, "before_cursor_execute", statement)
    event.listen(Engine, "commit", committed)
    event.listen(Engine, "rollback", rolled_back)
    # First pytest/app/ORM imports occur only beyond every approval check.
    import pytest

    class DeliveryBoundary:
        def __init__(self):
            self.patch = pytest.MonkeyPatch()
            fixture_policy.install_symlink_suppression(self.patch)
            self.capture = []
            self.collected = []
            self.started = []
            self.outcomes = []
            self.installed = False

        def pytest_configure(self, config):
            config._calendar_query_boundary = self

        def record(self, name):
            if len(self.capture) >= MAX_CAPTURE_EVENTS:
                refuse("delivery capture count bound exceeded")
            # Deliberately no recipients, credentials, content or argument repr.
            self.capture.append(name)

        def pytest_load_initial_conftests(self, early_config, parser, args):
            import aiosmtplib
            import smtplib

            def sync_capture(name):
                def captured(*args, **kwargs):
                    self.record(name)
                    return True
                return captured

            def async_capture(name):
                async def captured(*args, **kwargs):
                    self.record(name)
                    return True
                return captured

            # Terminal captures precede every application service/router import.
            self.patch.setattr(aiosmtplib, "send", async_capture("aiosmtplib.send"))
            for name in ("connect", "sendmail", "send_message"):
                self.patch.setattr(aiosmtplib.SMTP, name, async_capture("aiosmtplib.SMTP." + name))
                self.patch.setattr(smtplib.SMTP, name, sync_capture("smtplib.SMTP." + name))
            from app.config import settings
            if (settings.database_url != os.environ["TEST_DATABASE_URL"]
                    or any((settings.partner_oauth_enabled, settings.partner_api_enabled, settings.partner_docs_enabled,
                            settings.partner_api_budget_enabled, settings.managed_core_budget_enabled))):
                refuse("synthetic singleton settings and OFF feature flags required")
            from app.services import chat_mail, chat_ws, email_service, meeting_notice, notify, task_mail, web_push

            for module, names in (
                (email_service, ("send_invite", "send_access_invite", "_deliver", "send_notice",
                                 "send_password_reset")),
                (notify, ("notify_person", "tell", "dispatch", "post_alert")),
                (chat_mail, ("send_notice",)),
                (task_mail, ("send_notice", "send_notice_checked")),
                (meeting_notice, ("в_личку",)),
            ):
                for name in names:
                    self.patch.setattr(module, name, async_capture(module.__name__ + "." + name))
            from app.routers import conf_router
            self.patch.setattr(conf_router, "_закрыть_комнату", async_capture("conference.close"))
            for module, names in (
                (notify, ("dispatch_async",)), (chat_mail, ("push_room_mail_async",)),
                (task_mail, ("send_delegation_async", "send_notice_async")),
                (web_push, ("push_room_async", "_send_one")),
            ):
                for name in names:
                    self.patch.setattr(module, name, sync_capture(module.__name__ + "." + name))
            for name in ("broadcast", "_publish", "_broadcast_local"):
                self.patch.setattr(chat_ws.manager, name, async_capture("chat_ws." + name))
            self.installed = True

        def pytest_collection_modifyitems(self, session, config, items):
            actual = {}
            for item in items:
                key = item.nodeid
                actual[key] = actual.get(key, 0) + 1
            if (not self.installed or actual != dict(zip(SELECTION, EXPECTED_COUNTS))
                    or not selection_allowed([item.nodeid for item in items])):
                raise pytest.UsageError("exact frozen calendar protocol cases and delivery stubs required")
            self.collected = [item.nodeid for item in items]

        def pytest_runtest_setup(self, item):
            if not self.installed:
                refuse("delivery stubs must precede every fixture setup")
            self.started.append(item.nodeid)

        def pytest_runtest_logreport(self, report):
            self.outcomes.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome})

        def pytest_runtest_teardown(self, item, nextitem):
            for path, anchor in anchors.items():
                scratch_bound(path, anchor)

        def pytest_sessionfinish(self, session, exitstatus):
            source_after = sources_unchanged()
            calls = [r for r in self.outcomes if r["when"] == "call"]
            if (blocked or not counters["ipv6_probe_flag_restored"] or not all(controls.values())
                    or inventory() != installed or not source_after or len(calls) != EXPECTED_CASES or any(r["outcome"] != "passed" for r in calls)
                    or len(self.started) != EXPECTED_CASES or not fixture_policy.complete()):
                session.exitstatus = 1
            payload = {"network_attempts_blocked": blocked, "network_boundary": counters,
                       "source_after": source_after, "sendmsg_metadata_controls": controls, "verified_inventory_count": len(installed), "delivery_capture": self.capture,
                       "external_delivery_stubbed_before_conftest": self.installed,
                       "collected": self.collected, "results": self.outcomes,
                       "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       "app_sha256": APP_DIGEST, "tests_without_runner_sha256": TESTS_DIGEST,
                       "schema_sha256": SCHEMA_DIGEST, "expected_cases": EXPECTED_CASES,
                       "exitstatus": int(session.exitstatus)}
            raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            if len(raw) > 1024 * 1024:
                refuse("evidence size bound exceeded")
            with (evidence / "calendar-protocol-boundary.json").open("xb") as output:
                output.write(raw)

        def pytest_unconfigure(self, config):
            self.patch.undo()

    try:
        return pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
                            "-p", "no:cacheprovider", "-vv", "--tb=short", "--capture=sys", "--basetemp=" + str(scratch / "pytest-test"),
                            "--log-file=" + str(evidence / "pytest.log"),
                            "--junitxml=" + str(evidence / "calendar-protocol.xml"),
                            *(str(SERVER / item) for item in SELECTION)], plugins=[DeliveryBoundary()])
    finally:
        signal.alarm(0)
        stack.close()
        for path, anchor in anchors.items():
            scratch_bound(path, anchor)


if __name__ == "__main__":
    raise SystemExit(main())
