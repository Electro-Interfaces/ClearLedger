"""ROOT-only frozen native CREATE test gate; no app/driver/pytest before approval."""
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import pwd
import sys
from urllib.parse import urlsplit

SERVER = Path(__file__).resolve().parents[1]
BASE_COMMIT = "8197c96b52aa6a1aeed23252f8cbcf585ea28731"
APP_DIGEST = '5dac9d07dbfe9079dc03f765c21ecd105bbf5542c4b9ff49b62533aa05e8bd84'
TESTS_DIGEST = '761b83210b77c31d7cde07233d829821cc19d8e7503883fe0644c7b4b40f445a'
SCHEMA_DIGEST = '51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d'
APP_COUNT = 492
TESTS_COUNT_WITHOUT_SELF = 336
SCHEMA_COUNT = 16
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601'}
SELECTION = [
    "tests/test_native_contract_create.py",
    "tests/test_contract_creation_replay.py",
    "tests/test_reference_identity_api.py::test_duplicate_contract_post_concurrent_and_different_date_or_party",
    "tests/test_reference_identity_api.py::test_contract_checks_both_sides_on_create_and_update",
    "tests/test_reference_identity_api.py::test_patch_marks_only_fields_that_changed",
]


def refuse(message):
    raise RuntimeError(message)


def tree_digest(path, *, count, exclude_self=False):
    entries = [p for p in path.rglob("*") if "__pycache__" not in p.parts]
    if any(p.is_symlink() for p in entries):
        refuse("source symlinks are not part of the frozen tree")
    files = sorted(p for p in entries if p.is_file() and not (exclude_self and p == Path(__file__)))
    if len(files) != count or sum(p.stat().st_size for p in files) > 64 * 1024 * 1024:
        refuse("immutable source bounds differ")
    manifest = [[str(p.relative_to(SERVER)), hashlib.sha256(p.read_bytes()).hexdigest()] for p in files]
    return hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()


def private_empty(value):
    path = Path(value)
    if (not path.is_absolute() or not path.is_dir() or path.is_symlink()
            or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077
            or "test" not in path.name.lower() or any(path.iterdir())):
        refuse("separate private owned empty test directories required")
    return path


def verify_approval():
    if sys.argv[1:] != ["--execute-approved-native-contract-create-tests"]:
        refuse("exact ROOT execution argument required")
    if sys.version_info[:2] != (3, 13) or sys.flags.optimize:
        refuse("unoptimized Python 3.13 required")
    flags = ("ROOT_APPROVED_NATIVE_CONTRACT_CREATE_TESTS", "RUN_NATIVE_CONTRACT_CREATE_TESTS",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(flag) != "1" for flag in flags):
        refuse("explicit ROOT and test opt-ins required")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY",
               "DATABASE_URL", "TEST_DATABASE_URL", "UPLOAD_DIR", "NATIVE_CONTRACT_PG_PORT",
               "NATIVE_CONTRACT_EMPTY_CWD", "NATIVE_CONTRACT_EVIDENCE_DIR", "NATIVE_CONTRACT_RUNNER_SHA256"}
    if set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir:
        refuse("clean allowlisted synthetic environment and preserved HOME required")
    if os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != "native-contract-create-synthetic-secret-only":
        refuse("synthetic native test settings required")
    expected_self = os.environ.get("NATIVE_CONTRACT_RUNNER_SHA256", "")
    if len(expected_self) != 64 or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != expected_self:
        refuse("ROOT-reviewed immutable runner hash required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("DATABASE_URL") != raw:
        refuse("explicit matching database URLs required")
    target = urlsplit(raw)
    if (target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or not ip_address(target.hostname).is_loopback
            or not target.username or not target.password
            or target.path != "/api_native_contract_create_test_20261030"
            or not target.port or str(target.port) != os.environ.get("NATIVE_CONTRACT_PG_PORT")):
        refuse("exact approved disposable native contract database required")
    empty = private_empty(os.environ.get("NATIVE_CONTRACT_EMPTY_CWD", ""))
    upload = private_empty(os.environ.get("UPLOAD_DIR", ""))
    evidence = private_empty(os.environ.get("NATIVE_CONTRACT_EVIDENCE_DIR", ""))
    if Path.cwd() != empty or len({p.resolve() for p in (empty, upload, evidence)}) != 3:
        refuse("separate cwd/upload/evidence required")
    if (tree_digest(SERVER / "app", count=APP_COUNT) != APP_DIGEST
            or tree_digest(SERVER / "tests", count=TESTS_COUNT_WITHOUT_SELF, exclude_self=True) != TESTS_DIGEST
            or tree_digest(SERVER / "schema_migrations", count=SCHEMA_COUNT) != SCHEMA_DIGEST):
        refuse("full app/tests/schema source differs from approval")
    if any(hashlib.sha256((SERVER / path).read_bytes()).hexdigest() != expected
           for path, expected in SUPPORT_FILES.items()):
        refuse("approved test configuration/dependency source differs")
    sys.path.insert(0, str(SERVER))
    from tests.partner_test_safety import partner_test_safety_error
    if partner_test_safety_error(os.environ, flag="RUN_NATIVE_CONTRACT_CREATE_TESTS"):
        refuse("common pre-import safety guard refused")
    os.umask(0o077)
    return evidence


def main():
    try:
        evidence = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "phase": "native_source_environment_approval"}))
        return 2
    import pytest
    return pytest.main(["-c", str(SERVER / "pytest.ini"), "-p", "pytest_asyncio.plugin",
                        "-p", "no:cacheprovider", "-vv", "--tb=short",
                        "--junitxml=" + str(evidence / "native-contract-create.xml"),
                        *(str(SERVER / item) for item in SELECTION)])


if __name__ == "__main__":
    raise SystemExit(main())
