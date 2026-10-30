"""ROOT-only immutable source/environment gate, before pytest/app/driver imports.

This script is prepared by the worker and must not be executed by that worker.
ROOT provisions the exact disposable DB and supplies synthetic credentials.
"""
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import pwd
import sys
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "1c9ea350fff4502c5e0abdcb4b8b0eef65cc0e38"
APP_DIGEST = 'beb45c71788be8c6d9b016fed04abab60079a7598b8a634c0c464886abb60184'
SCHEMA_DIGEST = '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'
FILES = {'tests/test_contract_import_create.py': '93690b8bca0a3870a53bd9262140602fdef868d684e1bfb7dad19ed68d9aa20c', 'tests/test_corporate_counterparty_commands.py': '73f25eccb83e6cae327283fef8e11f2f9c36ac6e005a7a373361b74bdeece05f', 'tests/test_counterparty_commands.py': '11dcd10fdfdb420a59775b54882150b6645b1f1f9326ab9b3e48482c3241ea5e', 'tests/test_reference_identity_api.py': 'f3ba7173f4fb885fff9c469989518ee2beca0bee4c2e009fecb8b0ef1248827b', 'tests/partner_test_safety.py': '43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1', 'tests/conftest.py': '32ea55b426d111d8615e0f85ac7561a55ec802ee98a2b59a336405205ab1f57b', 'tests/helpers.py': 'edaf0741b6c562dfa46d04b79789abf34ff2cb560fa13f42f184b970903d5a31', 'tests/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
SELECTION = [
    "tests/test_contract_import_create.py",
    "tests/test_corporate_counterparty_commands.py",
    "tests/test_counterparty_commands.py::test_import_replay_keeps_manual_fields_and_source",
    "tests/test_counterparty_commands.py::test_import_accumulates_roles_and_caller_can_roll_back",
    "tests/test_counterparty_commands.py::test_ambiguous_import_rolls_back_without_choosing_a_party",
    "tests/test_counterparty_commands.py::test_l2_known_inn_company_scope_and_incomplete_identity",
    "tests/test_reference_identity_api.py::test_registry_and_l2_reuse_real_orm_uuid",
    "tests/test_reference_identity_api.py::test_legacy_reestr_same_run_and_repeat_reuse_contract",
    "tests/test_reference_identity_api.py::test_corporate_missing_organization_is_explicit",
    "tests/test_reference_identity_api.py::test_corporate_reimport_orm_uuid_and_pinned_source_identity",
]


def refuse(message):
    raise RuntimeError(message)


def tree_digest(path, count):
    files = sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    if (len(files) != count or any(p.is_symlink() for p in files)
            or sum(p.stat().st_size for p in files) > 32 * 1024 * 1024):
        refuse("source tree bounds differ")
    entries = [[str(p.relative_to(SERVER)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files]
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def private_directory(value, *, empty):
    path = Path(value)
    if (not path.is_absolute() or not path.is_dir() or path.is_symlink()
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077
            or "test" not in path.name.lower()):
        refuse("fresh private owned test directories required")
    if empty and any(path.iterdir()):
        refuse("test directory is not empty")
    return path


def verify_approval():
    if sys.argv[1:] != ["--execute-approved-contract-create-tests"]:
        refuse("exact ROOT execution argument required")
    if sys.version_info[:2] != (3, 13) or sys.flags.optimize:
        refuse("unoptimized Python 3.13 required")
    required_flags = ("ROOT_APPROVED_CONTRACT_CREATE_TESTS", "RUN_CONTRACT_IMPORT_CREATE_TESTS",
                      "RUN_CORPORATE_COUNTERPARTY_COMMAND_TESTS", "RUN_COUNTERPARTY_COMMAND_TESTS",
                      "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(flag) != "1" for flag in required_flags):
        refuse("explicit ROOT/test opt-ins required")
    allowed = {*required_flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY",
               "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "CONTRACT_CREATE_PG_PORT",
               "CONTRACT_CREATE_EMPTY_CWD", "CONTRACT_CREATE_EVIDENCE_DIR"}
    if set(os.environ) - allowed:
        refuse("requires a clean allowlisted synthetic environment")
    if os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("HOME must be preserved")
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("SECRET_KEY") != "contract-create-synthetic-secret-only"):
        refuse("synthetic test settings required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching URLs required")
    target = urlsplit(raw)
    if (target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or not ip_address(target.hostname).is_loopback
            or not target.username or not target.password
            or target.path != "/api_contract_create_test_20261030"
            or not target.port or str(target.port) != os.environ.get("CONTRACT_CREATE_PG_PORT")):
        refuse("exact approved loopback database target required")
    empty = private_directory(os.environ.get("CONTRACT_CREATE_EMPTY_CWD", ""), empty=True)
    upload = private_directory(os.environ.get("UPLOAD_DIR", ""), empty=True)
    evidence = private_directory(os.environ.get("CONTRACT_CREATE_EVIDENCE_DIR", ""), empty=True)
    if len({empty.resolve(), upload.resolve(), evidence.resolve()}) != 3 or Path.cwd() != empty:
        refuse("separate empty cwd/upload/evidence required")
    if tree_digest(SERVER / "app", 490) != APP_DIGEST or tree_digest(SERVER / "schema_migrations", 16) != SCHEMA_DIGEST:
        refuse("immutable approved runtime source differs")
    for name, expected in FILES.items():
        if hashlib.sha256((SERVER / name).read_bytes()).hexdigest() != expected:
            refuse("immutable approved test/guard source differs")
    sys.path.insert(0, str(SERVER))
    from tests.partner_test_safety import partner_test_safety_error
    if partner_test_safety_error(os.environ, flag="RUN_CONTRACT_IMPORT_CREATE_TESTS"):
        refuse("common pre-import safety guard refused")
    os.umask(0o077)
    return evidence


def main():
    try:
        evidence = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "source_environment_approval"}))
        return 2
    # The first pytest/application/driver import is beyond every approval gate.
    import pytest
    return pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
                        "-p", "no:cacheprovider", "-vv", "--tb=short",
                        "--junitxml=" + str(evidence / "contract-create.xml"),
                        *(str(SERVER / item) for item in SELECTION)])


if __name__ == "__main__":
    raise SystemExit(main())
