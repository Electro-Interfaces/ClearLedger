"""ROOT-only writer harness. Workers review source; all runtime remains NOTRUN.

Provision and actual80 require separate fresh guarded processes and ROOT receipts.
"""
from __future__ import annotations

import ast
import asyncio
from contextlib import ExitStack
import contextvars
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import stat
import sys
import sysconfig
from urllib.parse import urlsplit
import weakref
import uuid
from datetime import datetime

SERVER = Path(__file__).absolute().parents[1]
ROOT_LEASE_RUN_ID = "run_19ce21b41b2c"
BASE_COMMIT = "3ffe5ba27e694da4924df3a360fbb9bb02f9bb76"
PORT = 33547
DATABASE = "api_service_location_writer_test_20261031"
DATABASE_USER = "clearledger"
DATABASE_PASSWORD = "api_test_only"
FIXTURE = "tests/service_location_writer_schema_fixture_20261031.py"
FIXTURE_SHA256 = "339bb21bf463d65a747e6a9fb34f4c8b94d30c1caf3fc826baf0624a4b4f4130"
SELF_NAME = "tests/service_location_writer_convergence_approved.py"
TEST_FILE = "tests/test_service_location_writer_convergence_20261031.py"
ORIGINAL_JSON = "../docs/api/SERVICE_LOCATION_WRITER_CONVERGENCE_20261031.json"
DESCRIBE_OPTIN = "ROOT_APPROVED_SERVICE_LOCATION_WRITER_SOURCE_DESCRIBE"
ROOT_OPTIN = "ROOT_APPROVED_SERVICE_LOCATION_WRITER_HARNESS"
TEST_OPTIN = "RUN_SERVICE_LOCATION_WRITER_CONVERGENCE_TESTS"
READY_OPTIN = "SERVICE_LOCATION_WRITER_SCHEMA_READY"
MAX_FILES = 12000
MAX_BLOB = 32 * 1024 * 1024
MAX_TREE = 128 * 1024 * 1024
MAX_SECONDS = 600
MAX_CAPTURE_EVENTS = 4000
LIMIT_SCRATCH = 128 * 1024 * 1024
MAX_CONNECTIONS = 4
MAX_CONNECTIONS_TOTAL = 320
RUNTIME = {'aiofiles': '24.1.0', 'aiohappyeyeballs': '2.7.1', 'aiohttp': '3.14.5', 'aiosignal': '1.4.0', 'aiosmtplib': '5.1.3', 'annotated-doc': '0.0.2', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'asyncpg': '0.30.0', 'attrs': '26.1.0', 'authlib': '1.9.1', 'bcrypt': '4.2.1', 'certifi': '2026.10.23', 'cffi': '2.1.1', 'charset-normalizer': '3.5.2', 'click': '8.5.0', 'cryptography': '50.0.2', 'dnspython': '2.9.1', 'email-validator': '2.3.0', 'et-xmlfile': '2.0.0', 'fastapi': '0.133.0', 'frozenlist': '1.8.0', 'greenlet': '3.5.6', 'gunicorn': '23.0.0', 'h11': '0.16.0', 'http-ece': '1.2.1', 'httpcore': '1.0.9', 'httptools': '0.9.0', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'lxml': '6.1.3', 'multidict': '7.2.1', 'openpyxl': '3.1.5', 'packaging': '26.3', 'passlib': '1.7.4', 'pip': '26.2.2', 'propcache': '0.5.4', 'py-vapid': '1.9.6', 'pycparser': '3.12', 'pydantic': '2.14.2', 'pydantic-core': '2.50.2', 'pydantic-settings': '2.7.1', 'pyjwt': '2.15.0', 'pypdf': '6.21.2', 'python-docx': '1.1.2', 'python-dotenv': '1.2.2', 'python-multipart': '0.0.31', 'pywebpush': '2.5.0', 'pyyaml': '6.0.3', 'requests': '2.34.2', 'sqlalchemy': '2.0.36', 'starlette': '1.3.1', 'typing-extensions': '4.16.0', 'typing-inspection': '0.4.4', 'urllib3': '2.8.0', 'uvicorn': '0.34.0', 'uvloop': '0.23.0', 'watchfiles': '1.3.0', 'websockets': '17.3', 'yarl': '1.25.1'}
TOOLS = {'iniconfig': '2.3.1', 'jsonschema': '4.26.0', 'jsonschema-path': '0.5.0', 'jsonschema-specifications': '2025.9.1', 'lazy-object-proxy': '1.13.0', 'openapi-schema-validator': '0.9.0', 'openapi-spec-validator': '0.9.0', 'pathable': '0.6.0', 'pluggy': '1.7.0', 'pygments': '2.21.0', 'pytest': '9.2.0', 'pytest-asyncio': '1.4.1', 'referencing': '0.37.0', 'rfc3339-validator': '0.1.4', 'rpds-py': '2026.9.1', 'six': '1.17.0'}
SOURCE_TREES = {'app': {'count': 504, 'sha256': 'c98ef752e2946578108abd83dd47eab3b48f01f43ae2684f7e7653e466c802ce'}, 'tests': {'count': 396, 'sha256': '2a0c6851e534fe27b3b628810c30a34122e8e28196006945bcb2cf19b9817bda'}, 'schema_migrations': {'count': 24, 'sha256': '36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165'}}
SUPPORT_FILES = {'requirements.txt': 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0', 'pytest.ini': 'bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601', '../docs/api/SERVICE_LOCATION_WRITER_CONVERGENCE_20261031.json': '8629c09c9c01c06c84639b7fc432591b010e01bbc8e3d19612e2ecb2d61f25f7', '../docs/api/SERVICE_LOCATION_WRITER_CONVERGENCE_20261031.md': '0a7aae3566c2d64613a01f8adb2bc2d5823fdccdfa00d58c0488fb99e83b5729'}
EXPECTED_IDS = [
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[working]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[no_link]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[disabled]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[not_working]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[on_repair]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[maintenance]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[unknown]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_status_and_noop_preserve_audit_projection_and_outer_commit[decommissioned]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_invalid_status_precedes_target_admission[0]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_invalid_status_precedes_target_admission[2]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_invalid_status_precedes_target_admission[None]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_projection_returned_failure_vs_exception_rollback[False]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_projection_returned_failure_vs_exception_rollback[True]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_foreign_company_no_audit_or_effect",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[False-operational]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[False-rename]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[False-close]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[False-delete]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[True-operational]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[True-rename]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[True-close]",
    "tests/test_service_location_writer_convergence_20261031.py::test_existing_object_ceiling_before_mutation_even_warm[True-delete]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_effective_context_ceiling_is_checked_even_with_unrestricted_membership[False]",
    "tests/test_service_location_writer_convergence_20261031.py::test_op_effective_context_ceiling_is_checked_even_with_unrestricted_membership[True]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[foreign-rename]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[foreign-close]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[foreign-delete]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[wrong_type-rename]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[wrong_type-close]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[wrong_type-delete]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[no_membership-rename]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[no_membership-close]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_tenant_type_and_member_denial[no_membership-delete]",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_partial_patch_preserves_subtrees_identity_and_null_rules",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_details_autoflush_before_real_mol_lookup_preserves_old_phase",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_helper_lookup_is_not_form_create_or_metadata_update",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_create_exact_trimmed_identity_and_outer_rollback",
    "tests/test_service_location_writer_convergence_20261031.py::test_warehouse_create_late_validation_failure_rolls_back_new_row_and_pending_work",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_form_warehouse_legacy_scope_exception_does_not_admit_later_existing_edit",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_cannot_cross_root_or_session[commit_new_root]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_cannot_cross_root_or_session[rollback_new_root]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_cannot_cross_root_or_session[cross_session]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_is_not_an_existing_object_permission[consumed]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_is_not_an_existing_object_permission[card_before_details]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_is_not_an_existing_object_permission[existing_entry]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_is_not_an_existing_object_permission[different_loaded_target]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_never_bypasses_other_commands[operational]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_never_bypasses_other_commands[lifecycle]",
    "tests/test_service_location_writer_convergence_20261031.py::test_new_warehouse_initialization_never_bypasses_other_commands[delete]",
    "tests/test_service_location_writer_convergence_20261031.py::test_renamed_warehouse_original_name_keeps_pk_collision_and_outer_rollback",
    "tests/test_service_location_writer_convergence_20261031.py::test_known_opaque_history_blocks_delete_without_touching_link_or_zero_stock[False-parent]",
    "tests/test_service_location_writer_convergence_20261031.py::test_known_opaque_history_blocks_delete_without_touching_link_or_zero_stock[False-child]",
    "tests/test_service_location_writer_convergence_20261031.py::test_known_opaque_history_blocks_delete_without_touching_link_or_zero_stock[True-parent]",
    "tests/test_service_location_writer_convergence_20261031.py::test_known_opaque_history_blocks_delete_without_touching_link_or_zero_stock[True-child]",
    "tests/test_service_location_writer_convergence_20261031.py::test_foreign_tenant_opaque_link_is_neither_disclosed_nor_deleted[parent]",
    "tests/test_service_location_writer_convergence_20261031.py::test_foreign_tenant_opaque_link_is_neither_disclosed_nor_deleted[child]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[unit]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[spares]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[equipment_movement]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[spare_movement]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[equipment_doc]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[spare_doc]",
    "tests/test_service_location_writer_convergence_20261031.py::test_delete_each_usage_guard_preserves_real_rows[supply_doc]",
    "tests/test_service_location_writer_convergence_20261031.py::test_close_stock_guards_and_reopen_history_contract[unit-True]",
    "tests/test_service_location_writer_convergence_20261031.py::test_close_stock_guards_and_reopen_history_contract[spares-True]",
    "tests/test_service_location_writer_convergence_20261031.py::test_close_stock_guards_and_reopen_history_contract[zero-False]",
    "tests/test_service_location_writer_convergence_20261031.py::test_close_stock_guards_and_reopen_history_contract[terminal-False]",
    "tests/test_service_location_writer_convergence_20261031.py::test_close_stock_guards_and_reopen_history_contract[equipment_doc-False]",
    "tests/test_service_location_writer_convergence_20261031.py::test_zero_stock_delete_is_atomic_and_has_exactly_one_outer_audit[None]",
    "tests/test_service_location_writer_convergence_20261031.py::test_zero_stock_delete_is_atomic_and_has_exactly_one_outer_audit[after_cleanup]",
    "tests/test_service_location_writer_convergence_20261031.py::test_zero_stock_delete_is_atomic_and_has_exactly_one_outer_audit[outer_audit]",
    "tests/test_service_location_writer_convergence_20261031.py::test_common_owner_rejection_cannot_be_bypassed[operational-set_operational_status]",
    "tests/test_service_location_writer_convergence_20261031.py::test_common_owner_rejection_cannot_be_bypassed[rename-update_warehouse_card]",
    "tests/test_service_location_writer_convergence_20261031.py::test_common_owner_rejection_cannot_be_bypassed[rename-update_warehouse_details]",
    "tests/test_service_location_writer_convergence_20261031.py::test_common_owner_rejection_cannot_be_bypassed[close-set_warehouse_status]",
    "tests/test_service_location_writer_convergence_20261031.py::test_common_owner_rejection_cannot_be_bypassed[delete-delete_unused_warehouse]",
    "tests/test_service_location_writer_convergence_20261031.py::test_common_owner_rejection_cannot_be_bypassed[create-create_warehouse]",
    "tests/test_service_location_writer_convergence_20261031.py::test_selected_organization_is_preserved_without_new_native_join_policy",
    "tests/test_service_location_writer_convergence_20261031.py::test_empty_legacy_context_keeps_existing_unrestricted_semantics[operational]",
    "tests/test_service_location_writer_convergence_20261031.py::test_empty_legacy_context_keeps_existing_unrestricted_semantics[warehouse]"
]


def refuse(message="service-location ROOT approval refused"):
    raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def no_links(path):
    if (not path.is_absolute() or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents))
            or any(part == ".env" or part.startswith(".env.") for part in path.parts)
            or {".ssh", ".vault", ".claude", ".aws", ".gnupg", ".postgresql", ".pgpass", ".config"} & set(path.parts)):
        refuse("absolute path without ANY symlink required")
    return path


def bounded_tree(root, *, exclude=(), max_files=MAX_FILES, max_bytes=MAX_TREE, return_files=False):
    no_links(root)
    files, count, size = [], 0, 0
    # Do not suppress symlinks in __pycache__, excluded files or ancestors.
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            path = no_links(Path(directory) / name)
            # Reject credential/dotenv components before ANY content read,
            # including unexpected entries which will fail the final freeze.
            info = path.lstat()
            count += 1
            if count > max_files * 2 or stat.S_ISLNK(info.st_mode):
                refuse("tree entry/symlink bound")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BLOB or info.st_nlink != 1:
                refuse("regular single-link bounded files required")
            size += info.st_size
            if size > max_bytes:
                refuse("tree byte bound")
            if path not in exclude:
                files.append(path)
    if len(files) > max_files:
        refuse("tree file bound")
    files = tuple(sorted(files))
    manifest = [[str(p.relative_to(root)), sha(no_links(p))] for p in files]
    freeze = {"count": len(files), "bytes": size, "sha256": canonical_sha(manifest)}
    return (freeze, files) if return_files else freeze


def source_tree(root, exclude=()):
    # PR83 uses paths relative to SERVER and JSON without sorted keys.
    _, files = bounded_tree(root, exclude=exclude, return_files=True)
    # Reuse exactly the checked entries; no second unguarded rglob/read set.
    manifest = [[str(p.relative_to(SERVER)), sha(no_links(p))] for p in files]
    return {"count": len(files), "sha256": hashlib.sha256(
        json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()}


def sources_unchanged(expected_self):
    no_links(SERVER)
    if sha(no_links(Path(__file__).absolute())) != expected_self:
        refuse("runner changed")
    for name, expected in SOURCE_TREES.items():
        exclude = (SERVER / SELF_NAME, SERVER / FIXTURE) if name == "tests" else ()
        if source_tree(SERVER / name, exclude) != expected:
            refuse("full frozen PR83 app/tests/schema changed")
    if not re.fullmatch(r"[0-9a-f]{64}", FIXTURE_SHA256) or sha(no_links(SERVER / FIXTURE)) != FIXTURE_SHA256:
        refuse("fixture freeze changed or missing")
    for path, expected in SUPPORT_FILES.items():
        # The sole allowed .. component is this compile-time report path.
        target = SERVER.parent / path[3:] if path.startswith("../") else SERVER / path
        if sha(no_links(target)) != expected:
            refuse("configuration/original PR83 report changed")
    return True


def private_directory(value, *, empty=True):
    path = no_links(Path(value))
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o700 or (empty and any(path.iterdir()))):
        refuse("owned empty 0700 directory required")
    return path


def private_json(value, expected):
    path = no_links(Path(value))
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 2 * 1024 * 1024
            or not re.fullmatch(r"[0-9a-f]{64}", expected) or sha(path) != expected):
        refuse("ROOT pinned private JSON required")
    parent = path.parent.lstat()
    if parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) != 0o700:
        refuse("ROOT-owned0700 control/input directory required")
    return path, json.loads(path.read_bytes())


def inventory(candidate, expected_files):
    candidate = no_links(Path(candidate))
    site = no_links(candidate / "lib/python3.13/site-packages")
    cfg = no_links(candidate / "pyvenv.cfg")
    if not re.search(r"^include-system-site-packages\s*=\s*false\s*$", cfg.read_text(), re.M):
        refuse("system site-packages denied")
    # Full RECORD/module/native-extension bytes pinned by ROOT, before AND after.
    freeze = bounded_tree(site, max_files=100000, max_bytes=1024 * 1024 * 1024)
    if freeze != expected_files:
        refuse("ROOT dependency RECORD/module inventory differs")
    if any(p.suffix == ".pth" or p.name in {"sitecustomize.py", "usercustomize.py"} for p in site.rglob("*")):
        refuse("site hooks denied")
    installed = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        if name in installed:
            refuse("duplicate distribution")
        installed[name] = distribution.version
    if len(RUNTIME) != 61 or len(TOOLS) != 16 or set(RUNTIME) & set(TOOLS) or installed != {**RUNTIME, **TOOLS}:
        refuse("original77 exact distributions required")
    return site, installed, freeze


def verify_approval():
    mode = sys.argv[1:] or []
    if mode not in (["--provision-approved-service-location-writer-schema"],
                    ["--execute-approved-service-location-writer-actual80"]):
        refuse("exact unique ROOT mode required")
    stage = "provision" if mode[0].startswith("--provision") else "actual80"
    if (os.getuid() != 0 or os.geteuid() != 0 or sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize or not sys.dont_write_bytecode
            or not sys.flags.isolated or not sys.flags.no_site or sys.implementation.name != "cpython"
            or any(m in sys.modules for m in ("pytest", "app", "site", "sqlalchemy", "asyncpg"))
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)):
        refuse("fresh unoptimized CPython3.13.7 -I -S -B required")
    # ROOT must launch with foreign descriptors closed; proc directory scan's
    # own transient descriptor may already have disappeared by fstat.
    for entry in os.listdir("/proc/self/fd"):
        fd = int(entry)
        if fd > 2:
            try:
                os.fstat(fd)
            except OSError:
                continue
            refuse("inherited foreign descriptor present")
    flags = (ROOT_OPTIN, "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    if any(os.environ.get(name) != "1" for name in flags):
        refuse("ROOT unique opt-in required")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "APP_ENV", "SECRET_KEY", "DATABASE_URL",
               "TEST_DATABASE_URL", "UPLOAD_DIR", "TMPDIR", "SLW_CWD", "SLW_EVIDENCE", "SLW_SCRATCH",
               "SLW_APPROVAL", "SLW_APPROVAL_SHA256", "SLW_RUNNER_SHA256", "SLW_SCHEMA_RECEIPT",
               "SLW_SCHEMA_RECEIPT_SHA256"}
    if (set(os.environ) - allowed or os.environ.get("HOME") != pwd.getpwuid(os.getuid()).pw_dir
            or os.environ.get("APP_ENV") != "test" or os.environ.get("SECRET_KEY") != "service-location-writer-synthetic-secret-only"):
        refuse("minimal explicit synthetic environment required; no pre-set test/ready flags")
    self_sha = os.environ.get("SLW_RUNNER_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", self_sha):
        refuse("ROOT runner SHA required")
    approval_path, approval = private_json(os.environ["SLW_APPROVAL"], os.environ["SLW_APPROVAL_SHA256"])
    if (approval.get("authority") != "ROOT" or approval.get("stage") != stage or approval.get("mode") != stage
            or approval.get("base_commit") != BASE_COMMIT or approval.get("runner_sha256") != self_sha
            or approval.get("fixture_sha256") != FIXTURE_SHA256
            or approval.get("database") != DATABASE or approval.get("database_owner") != DATABASE_USER
            or approval.get("host") != "127.0.0.1" or approval.get("port") != PORT
            or not re.fullmatch(r"[a-zA-Z0-9_-]{16,128}", approval.get("lease_id", ""))
            or any(type(approval.get(k)) is not int or approval[k] < 1 for k in ("database_oid", "owner_oid"))):
        refuse("exact ROOT stage/source/database/lease approval required")
    lease_path, external_lease = private_json(approval["lease_path"], approval["lease_sha256"])
    lease = approval.get("lease", {})
    expected_lease = {"lease_id": approval["lease_id"], "run_id": approval.get("run_id"),
                      "database": DATABASE, "database_oid": approval["database_oid"],
                      "role": DATABASE_USER, "role_oid": approval["owner_oid"], "host": "127.0.0.1",
                      "port": PORT, "synthetic": True}
    if (lease != expected_lease or approval.get("run_id") != ROOT_LEASE_RUN_ID
            or not isinstance(approval.get("approval_id"), str) or not approval["approval_id"]
            or approval.get("actor_profile") != "PR83_world_synthetic_two_companies_one_ordinary_admin_membership"
            or approval.get("models_sha256") != "ffd2c8a1231ca306bf5d569481d3c8e13b81e8a13ce312f8d39978da0e682682"):
        refuse("exact ROOT synthetic actor/company/source/lease profile required")
    external_expected = {"format": 1, "kind": "service_location_writer_root_lease",
        "run_id": ROOT_LEASE_RUN_ID, "lease_uuid": lease["lease_id"],
        "database_name": DATABASE, "database_oid": lease["database_oid"],
        "owner_role": DATABASE_USER, "owner_role_oid": lease["role_oid"],
        "pg_container_id": external_lease.get("pg_container_id"), "pg_port": PORT,
        "created_utc": external_lease.get("created_utc")}
    if (external_lease != external_expected or str(uuid.UUID(lease["lease_id"])) != lease["lease_id"]
            or uuid.UUID(lease["lease_id"]).int == 0
            or not re.fullmatch(r"[0-9a-f]{64}", external_lease.get("pg_container_id", ""))
            or datetime.fromisoformat(external_lease["created_utc"].replace("Z", "+00:00")).utcoffset().total_seconds() != 0):
        refuse("exact ROOT external lease file/plan required; no invented DB marker")
    # Disk floor/reserve, bounded DB/WAL budget and no foreign clients are ROOT
    # external-verifier responsibilities. A boolean in this file is never proof.
    _, resource = private_json(approval["resource_receipt_path"], approval["resource_receipt_sha256"])
    if (resource.get("authority") != "ROOT_EXTERNAL_VERIFIER" or resource.get("stage") != "before_" + stage
            or resource.get("lease") != lease or resource.get("lease_sha256") != approval["lease_sha256"]
            or resource.get("free_bytes", 0) < 8 * 1024**3 or resource.get("reserved_bytes", 0) < 1024**3
            or resource.get("foreign_clients") != [] or resource.get("foreign_locks") != []
            or resource.get("budget") != {"database_growth_bytes": 64 * 1024**2, "wal_growth_bytes": 128 * 1024**2,
                                          "selected_rows": 2000, "duration_seconds": MAX_SECONDS}):
        refuse("ROOT external capacity/ownership proof required")
    raw = os.environ.get("TEST_DATABASE_URL", "")
    target = urlsplit(raw)
    if (os.environ.get("DATABASE_URL") != raw or target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or target.hostname != "127.0.0.1" or target.port != PORT or target.path != "/" + DATABASE
            or target.username != DATABASE_USER or target.password != DATABASE_PASSWORD):
        refuse("dedicated NEW synthetic database only")
    directories = [private_directory(os.environ[n]) for n in ("SLW_CWD", "UPLOAD_DIR", "SLW_EVIDENCE", "SLW_SCRATCH")]
    if (Path.cwd() != directories[0] or os.environ.get("TMPDIR") != str(directories[3])
            or any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
                   for i, a in enumerate(directories) for b in directories[i+1:])
            or any(p.is_relative_to(SERVER) or SERVER.is_relative_to(p) for p in directories)
            or any(approval_path.is_relative_to(p) for p in directories)):
        refuse("four distinct nonnested fresh private roots outside frozen source required")
    if "test" not in directories[1].name.lower():
        refuse("original test safety UPLOAD_DIR naming required")
    candidate = Path(approval["python_environment"])
    interpreter = no_links(Path(sys.executable).absolute())
    if (str(interpreter) != approval["interpreter_path"] or sha(interpreter) != approval["interpreter_sha256"]
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"):
        refuse("ROOT reviewed canonical physical interpreter SHA/libc required")
    sources_unchanged(self_sha)
    site, installed, deps = inventory(candidate, approval["dependency_files"])
    inputs = {str(approval_path): sha(approval_path), approval["resource_receipt_path"]: approval["resource_receipt_sha256"],
              str(lease_path): approval["lease_sha256"], str(interpreter): approval["interpreter_sha256"],
              str(candidate / "pyvenv.cfg"): sha(candidate / "pyvenv.cfg")}
    receipt = None
    if stage == "actual80":
        receipt_path, receipt = private_json(os.environ["SLW_SCHEMA_RECEIPT"], os.environ["SLW_SCHEMA_RECEIPT_SHA256"])
        inputs[str(receipt_path)] = sha(receipt_path)
        if (approval.get("schema_receipt_sha256") != inputs[str(receipt_path)]
                or receipt.get("stage") != "provision_schema_ready" or receipt.get("schema_ready") is not True
                or receipt.get("lease") != lease or receipt.get("lease_sha256") != approval["lease_sha256"]
                or receipt.get("runner_sha256") != self_sha or receipt.get("fixture_sha256") != FIXTURE_SHA256
                or receipt.get("dependency_files") != deps or receipt.get("source_trees") != SOURCE_TREES
                or receipt.get("forbidden") != [] or receipt.get("cleanup_ok") is not True):
            refuse("actual80 requires exact prior successful provision receipt")
    elif "SLW_SCHEMA_RECEIPT" in os.environ or "SLW_SCHEMA_RECEIPT_SHA256" in os.environ:
        refuse("provision must not reuse schema-ready receipt")
    os.umask(0o077)
    return dict(stage=stage, approval=approval, target=target, directories=directories,
                site=site, installed=installed, dependencies=deps, inputs=inputs, receipt=receipt, self_sha=self_sha,
                external_lease=external_lease)


def pg_sendmsg_metadata_allowed(family, socktype, protocol, owned_fd, current_fd,
                               peer_exact, extra_args, extra_kwargs):
    """Reference policy: one buffers argument, no flags/ancillary/address."""
    return (family == socket.AF_INET and socktype == socket.SOCK_STREAM
            and protocol in (0, socket.IPPROTO_TCP)
            and type(owned_fd) is int and owned_fd >= 0
            and type(current_fd) is int and current_fd == owned_fd
            and peer_exact is True and not extra_args and not extra_kwargs)


def install_boundaries(context, counters, stack):
    """Deny external effects; actual application/auth/query/audit paths stay real."""
    roots = context["directories"][1:]
    native_fileno = socket.socket.fileno
    native_peer = socket.socket.getpeername
    native_type = socket.socket.getsockopt
    native_sendmsg = socket.socket.sendmsg
    owned = weakref.WeakKeyDictionary()
    connecting = contextvars.ContextVar("slw_owned_pg_connect", default=False)
    sending = contextvars.ContextVar("slw_owned_pg_sendmsg", default=None)

    def deny(event):
        if len(counters["forbidden"]) >= MAX_CAPTURE_EVENTS:
            refuse("guard capture overflow")
        counters["forbidden"].append(event)
        refuse("closed process/network/write boundary")

    def writable(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            deny("fd-or-relative-mutation")
        path = Path(os.path.abspath(os.fsdecode(value)))
        no_links(path)
        if not any(path.is_relative_to(root) and path != root for root in roots):
            deny("write-outside-owned-roots")
        return path

    def allowed_sendmsg(sock, args=(), kwargs=None):
        try:
            return pg_sendmsg_metadata_allowed(sock.family, native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE),
                sock.proto, owned.get(sock), native_fileno(sock), native_peer(sock) == ("127.0.0.1", PORT),
                args, {} if kwargs is None else kwargs)
        except (OSError, TypeError, AttributeError):
            return False

    def exact_sendmsg(sock, buffers, *args, **kwargs):
        if not allowed_sendmsg(sock, args, kwargs):
            deny("sendmsg-metadata")
        token = sending.set((sock, native_fileno(sock)))
        try:
            return native_sendmsg(sock, buffers)
        finally:
            sending.reset(token)

    def audit(event, args):
        if event == "socket.connect":
            sock, address = args
            if (not connecting.get() or address != ("127.0.0.1", PORT) or sock.family != socket.AF_INET
                    or native_type(sock, socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                    or sock.proto not in (0, socket.IPPROTO_TCP) or native_fileno(sock) < 0):
                deny(event)
            owned[sock] = native_fileno(sock)
            counters["pg_connect"] += 1
        elif event == "socket.sendmsg":
            active = sending.get()
            if (active is None or len(args) != 2 or args[0] is not active[0] or args[1] is not None
                    or sys._getframe(1).f_code is not exact_sendmsg.__code__ or not allowed_sendmsg(args[0])
                    or native_fileno(args[0]) != active[1]):
                deny(event)
            counters["pg_sendmsg"] += 1
        elif event == "socket.getaddrinfo":
            if not connecting.get() or args[0] != "127.0.0.1" or int(args[1]) != PORT:
                deny(event)
        elif event in {"socket.bind", "socket.sendto", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
                       "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty",
                       "os.kill", "os.killpg", "os.symlink", "os.link", "os.truncate", "os.chown", "os.chmod", "os.chdir"}:
            deny(event)
        elif event == "open":
            value = args[0]
            flags = args[2] if len(args) > 2 and type(args[2]) is int else 0
            if isinstance(value, (str, bytes, os.PathLike)):
                path = Path(os.path.abspath(os.fsdecode(value)))
                if (path.name == ".env" or path.name.startswith(".env.")
                        or {".ssh", ".vault", ".claude", ".aws", ".gnupg", ".postgresql", ".pgpass", ".config"} & set(path.parts)):
                    deny("secret-or-dotenv-read")
                no_links(path)
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                writable(value)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.utime"}:
            # dir_fd mutations are forbidden; no ambient relative capabilities.
            signatures = {"os.mkdir": (3, 2), "os.remove": (2, 1), "os.rmdir": (2, 1), "os.utime": (4, 3)}
            length, fd_index = signatures[event]
            if len(args) != length or args[fd_index] != -1:
                deny("dir-fd-mutation")
            writable(args[0])
        elif event == "os.rename":
            if any(v != -1 for v in args[2:]):
                deny("dir-fd-rename")
            writable(args[0])
            writable(args[1])

    sys.addaudithook(audit)
    from unittest.mock import patch
    # Low-level descriptor operations have no complete Python audit coverage.
    # Capture capabilities only on files this process opens inside owned roots;
    # inherited/duplicated descriptors never acquire write permission.
    import builtins
    import io
    fd_caps = {}
    native_os_open, native_os_close, native_fstat = os.open, os.close, os.fstat
    native_builtin_open, native_io_open = builtins.open, io.open

    def register(fd, path):
        info = native_fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            deny("unowned-write-descriptor")
        fd_caps[fd] = (info.st_dev, info.st_ino, str(path))

    def check_fd(fd):
        try:
            info = native_fstat(fd)
            cap = fd_caps.get(fd)
            if cap is None or cap[:2] != (info.st_dev, info.st_ino):
                deny("inherited-or-reused-write-fd")
            writable(cap[2])
        except (OSError, TypeError):
            deny("closed-write-fd")

    def guarded_os_open(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is not None:
            deny("dir-fd-open")
        writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        if writing:
            writable(path)
        fd = native_os_open(path, flags, mode)
        if writing:
            register(fd, Path(os.path.abspath(os.fsdecode(path))))
        return fd

    def guarded_file_open(native):
        def opened(file, mode="r", *args, **kwargs):
            writing = any(char in mode for char in "wax+")
            if type(file) is int:
                # Reject even fd reads: no ambient inherited file capability.
                check_fd(file)
            elif writing:
                writable(file)
            stream = native(file, mode, *args, **kwargs)
            if writing and type(file) is not int:
                register(stream.fileno(), Path(os.path.abspath(os.fsdecode(file))))
            return stream
        return opened

    def guarded_os_close(fd):
        fd_caps.pop(fd, None)
        return native_os_close(fd)

    def guarded_fd_write(native):
        def write(fd, *args, **kwargs):
            check_fd(fd)
            return native(fd, *args, **kwargs)
        return write

    def denied_fd_operation(*args, **kwargs):
        deny("unapproved-fd-mutation-or-duplication")

    stack.enter_context(patch.object(os, "open", guarded_os_open))
    stack.enter_context(patch.object(os, "close", guarded_os_close))
    stack.enter_context(patch.object(builtins, "open", guarded_file_open(native_builtin_open)))
    stack.enter_context(patch.object(io, "open", guarded_file_open(native_io_open)))
    for name in ("write", "writev", "pwrite", "pwritev", "ftruncate"):
        if hasattr(os, name):
            stack.enter_context(patch.object(os, name, guarded_fd_write(getattr(os, name))))
    for name in ("dup", "dup2", "fchmod", "fchown", "sendfile", "copy_file_range", "splice"):
        if hasattr(os, name):
            stack.enter_context(patch.object(os, name, denied_fd_operation))
    stack.enter_context(patch.object(socket.socket, "sendmsg", exact_sendmsg))
    stack.enter_context(patch.object(socket.socket, "listen", lambda *a, **k: deny("socket.listen")))
    # Same reviewed import-only urllib3 probe suppression as both references.
    # It only prevents a prohibited bind during import; no HTTP success stub.
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
    import asyncpg
    original_connect = asyncpg.connect
    expected = dict(host="127.0.0.1", port=PORT, database=DATABASE,
                    user=DATABASE_USER, password=DATABASE_PASSWORD)

    async def connect(dsn=None, **kwargs):
        if dsn is not None:
            target = urlsplit(dsn)
            if (target.scheme not in {"postgres", "postgresql"} or target.hostname != "127.0.0.1"
                    or target.port != PORT or target.path != "/" + DATABASE or target.query or target.fragment
                    or target.username != DATABASE_USER or target.password != DATABASE_PASSWORD):
                deny("sql-target")
        if any((dsn is None and key not in kwargs) or (key in kwargs and kwargs[key] != value)
               for key, value in expected.items()):
            deny("sql-override")
        if set(kwargs) - {*expected, "timeout", "command_timeout", "server_settings", "ssl"} or kwargs.get("ssl") not in (None, False):
            deny("asyncpg-connection-override")
        if kwargs.get("server_settings") not in (None, {}):
            deny("unapproved-session-settings")
        connections = counters["connections"]
        if len(connections) >= MAX_CONNECTIONS_TOTAL or sum(not c.is_closed() for c in connections) >= MAX_CONNECTIONS:
            deny("owned-connection-budget")
        kwargs.update(timeout=10, command_timeout=30, ssl=False, server_settings={
            "statement_timeout": "20000", "lock_timeout": "2000",
            "idle_in_transaction_session_timeout": "30000", "application_name": "slw-" + context["approval"]["lease_id"]})
        token = connecting.set(True)
        connection = None
        try:
            connection = await original_connect(dsn, **kwargs)
            connections.append(connection)  # retain before ownership query can fail
            row = await connection.fetchrow("SELECT d.oid AS database_oid, d.datdba AS owner_oid, "
                "r.oid AS role_oid, owner.rolname AS owner_role, current_database() AS database, "
                "current_user AS role FROM pg_database d JOIN pg_roles r ON r.rolname=current_user "
                "JOIN pg_roles owner ON owner.oid=d.datdba WHERE d.datname=current_database()")
            peer = connection._transport.get_extra_info("peername")
            if not isinstance(peer, tuple) or peer[:2] != ("127.0.0.1", PORT):
                deny("actual-tcp-peer-mismatch")
            lease = context["approval"]["lease"]
            if (row is None or row["database_oid"] != lease["database_oid"] or row["role_oid"] != lease["role_oid"]
                    or row["owner_oid"] != lease["role_oid"] or row["owner_role"] != lease["role"]
                    or row["database"] != DATABASE or row["role"] != lease["role"]):
                deny("database-lease-oid-mismatch")
            return connection
        except BaseException:
            if connection is not None and not connection.is_closed():
                try:
                    await asyncio.wait_for(connection.close(timeout=5), 6)
                except BaseException:
                    connection.terminate()  # only this newly owned connection
                    counters["cleanup_failures"].append("connect-failure-close")
            raise
        finally:
            connecting.reset(token)

    stack.enter_context(patch.object(asyncpg, "connect", connect))

    async def no_external(*args, **kwargs):
        deny("external-delivery")

    def no_external_sync(*args, **kwargs):
        deny("external-delivery")

    stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", no_external))
    stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", no_external_sync))
    stack.enter_context(patch.object(requests.sessions.Session, "request", no_external_sync))
    stack.enter_context(patch.object(aiohttp.ClientSession, "_request", no_external))
    stack.enter_context(patch.object(aiosmtplib, "send", no_external))
    return deny


def install_import_boundary(site):
    from importlib.machinery import PathFinder
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    roots = (SERVER / "app", SERVER / "tests", SERVER / "schema_migrations", site, stdlib)

    class FrozenImports:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "app.main" or fullname.endswith("conftest") or fullname.startswith("app.main."):
                refuse("app.main/global conftest imports forbidden")
            spec = PathFinder.find_spec(fullname, path)
            if spec is not None:
                locations = list(spec.submodule_search_locations or ())
                if spec.origin and spec.origin not in {"built-in", "frozen"}:
                    locations.append(spec.origin)
                for value in locations:
                    origin = no_links(Path(value).absolute())
                    if not any(origin.is_relative_to(root) for root in roots):
                        refuse("import outside exact frozen source/dependencies/stdlib")
            return None  # preserve pytest assertion rewriting
    sys.meta_path.insert(0, FrozenImports())


def guard_private_roots(context, anchors):
    for root in context["directories"]:
        info = root.lstat()
        if ((info.st_dev, info.st_ino, info.st_uid) != anchors[root]
                or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700):
            refuse("private root identity/mode changed")
        bounded_tree(root, max_files=4096, max_bytes=LIMIT_SCRATCH)


def verify_inputs(context):
    sources_unchanged(context["self_sha"])
    inventory(context["approval"]["python_environment"], context["dependencies"])
    if any(sha(no_links(Path(p))) != digest for p, digest in context["inputs"].items()):
        refuse("approval/resource/schema receipt changed")
    return True


def load_fixture(context):
    # Execute only this separately source-reviewed exact-byte helper, after fences.
    if sha(SERVER / FIXTURE) != FIXTURE_SHA256:
        refuse("fixture changed before guarded import")
    spec = importlib.util.spec_from_file_location("tests.service_location_writer_schema_fixture_20261031", SERVER / FIXTURE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    manifest = module.static_schema_manifest(SERVER.parent.parent)
    digest = module.manifest_sha256(manifest)
    if digest != context["approval"]["selected_manifest_sha256"]:
        refuse("ROOT selected schema manifest differs")
    bootstrap = manifest["bootstrap"]
    extra_ddl = [op["sha256"] for op in bootstrap["before_tables"]]
    extra_ddl.append(hashlib.sha256(bootstrap["required_extension"]["sql"].encode()).hexdigest())
    extra_ddl.extend(op["sha256"] for op in bootstrap["after_tables"])
    if bootstrap["extra_ddl_sha256"] != extra_ddl or len(extra_ddl) != 24:
        refuse("fixture supplemental DDL source order mismatch")
    if (context["approval"].get("extra_ddl_sha256") != extra_ddl
            or context["approval"].get("required_schema") != "public"
            or context["approval"].get("required_extension") != "btree_gist"):
        refuse("exact ROOT supplemental DDL/extension hashlist required")
    if context["stage"] == "actual80":
        if context["approval"].get("fixture_receipt_sha256") != canonical_sha(context["receipt"]["fixture_receipt"]):
            refuse("ROOT-approved inner fixture receipt canonical SHA required")
    return module, manifest, digest


def fixture_approval(context, manifest_sha, *, stage):
    approval = context["approval"]
    return {"approved_by": "ROOT", "approval_id": approval["approval_id"], "stage": stage,
            "fixture_sha256": FIXTURE_SHA256, "manifest_sha256": manifest_sha,
            "harness_sha256": context["self_sha"], "lease": approval["lease"],
            "root_extra_ddl_approval": approval["extra_ddl_sha256"],
            "external_lease_path": approval["lease_path"],
            "external_lease_sha256": approval["lease_sha256"],
            "external_lease": context["external_lease"],
            **({"receipt_sha256": approval["fixture_receipt_sha256"]} if stage == "verify" else {}),
            "boundary": {"harness_sha256": context["self_sha"], "isolated_process": True,
                         "import_fence_installed": True, "sanitized_environment": True, "no_live_dsn": True}}


def async_schema_stage(context, fixture, manifest_sha):
    async def stage():
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                if connection.in_transaction():
                    refuse("fresh inactive schema connection required")
                if context["stage"] == "provision":
                    return await fixture.provision_selected_schema(connection, fixture_approval(context, manifest_sha, stage="provision"))
                return await fixture.verify_schema(connection, context["receipt"]["fixture_receipt"],
                    fixture_approval(context, manifest_sha, stage="verify"))
        finally:
            await asyncio.wait_for(engine.dispose(), 10)
    with asyncio.Runner() as runner:
        return runner.run(stage())


def run_actual80(context):
    if any(name in sys.modules for name in ("app.config", "app.main")):
        refuse("verify_schema must remain ORM/app-import-free before original test import")
    # A successful source/receipt/catalog preflight precedes BOTH original flags.
    os.environ[TEST_OPTIN] = "1"
    os.environ[READY_OPTIN] = "1"
    import pytest
    evidence, scratch = context["directories"][2:]

    class Exact80:
        def __init__(self):
            self.collected, self.started, self.records = [], [], []

        def pytest_collection_modifyitems(self, session, config, items):
            actual = ["tests/" + Path(str(item.path)).name + "::" + item.nodeid.split("::", 1)[1] for item in items]
            if actual != EXPECTED_IDS or len(items) != 80 or len(set(actual)) != 80:
                raise pytest.UsageError("exact AST-frozen80 parameter IDs/order required")
            self.collected = actual

        def pytest_runtest_setup(self, item):
            if context.get("timed_out"):
                refuse("expired execution budget; no further fixture setup")
            self.started.append("tests/" + Path(str(item.path)).name + "::" + item.nodeid.split("::", 1)[1])

        def pytest_runtest_logreport(self, report):
            if len(self.records) >= MAX_CAPTURE_EVENTS:
                refuse("pytest phase evidence cap")
            self.records.append({"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome,
                                 "wasxfail": hasattr(report, "wasxfail")})

        def pytest_runtest_teardown(self, item, nextitem):
            guard_private_roots(context, context["anchors"])

    plugin = Exact80()
    code = int(pytest.main(["--noconftest", "--rootdir=" + str(SERVER), "-c", str(SERVER / "pytest.ini"),
        "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "-vv", "--tb=short", "--capture=sys",
        "--basetemp=" + str(scratch / "pytest-test"), "--log-file=" + str(evidence / "pytest.log"),
        "--junitxml=" + str(evidence / "service-location-writer-actual80.xml"), str(SERVER / TEST_FILE)], plugins=[plugin]))
    from xml.etree import ElementTree
    xml = evidence / "service-location-writer-actual80.xml"
    cases = list(ElementTree.parse(xml).getroot().iter("testcase")) if xml.is_file() else []
    records = {}
    for record in plugin.records:
        # With explicit SERVER rootdir these nodeids must be the frozen IDs.
        records.setdefault(record["nodeid"], []).append(record)
    complete = (code == 0 and plugin.collected == EXPECTED_IDS and plugin.started == EXPECTED_IDS
                and set(records) == set(EXPECTED_IDS) and len(cases) == 80
                and all([r["when"] for r in records.get(nodeid, [])] == ["setup", "call", "teardown"]
                        and all(r["outcome"] == "passed" and not r["wasxfail"] for r in records[nodeid])
                        for nodeid in EXPECTED_IDS)
                and all(not list(case.iter("failure")) and not list(case.iter("error"))
                        and not list(case.iter("skipped")) for case in cases))
    return {"pytest_exitstatus": code, "complete80": complete, "expected_ids": EXPECTED_IDS,
            "collected": plugin.collected, "started": plugin.started, "phase_records": plugin.records,
            "junit_sha256": sha(xml) if xml.is_file() else None,
            "not_executed": [n for n in EXPECTED_IDS if not any(r["when"] == "call" for r in records.get(n, []))]}


def cleanup_owned(counters):
    async def close():
        for connection in counters["connections"]:
            if not connection.is_closed():
                try:
                    await asyncio.wait_for(connection.close(timeout=5), 6)
                except BaseException:
                    counters["cleanup_failures"].append("owned-close-unproved")
                    # No pg_terminate_backend, process kill or foreign cleanup.
                    connection.terminate()
    with asyncio.Runner() as runner:
        runner.run(close())
    return not counters["cleanup_failures"] and all(c.is_closed() for c in counters["connections"])


def save_evidence(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 2 * 1024 * 1024:
        refuse("evidence cap")
    with path.open("xb") as stream:
        stream.write(raw)


def main():
    if sys.argv[1:] == ["--describe-approved-service-location-writer-schema"]:
        return describe_main()
    # Nothing from app/helper/framework/fixtures can execute before this guard.
    try:
        context = verify_approval()
    except Exception:
        print(json.dumps({"ok": False, "stage": "source_environment_approval", "runtime": "NOT_STARTED"}))
        return 2
    context["anchors"] = {p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_uid) for p in context["directories"]}
    counters = {"forbidden": [], "pg_connect": 0, "pg_sendmsg": 0,
                "connections": [], "cleanup_failures": [], "ipv6_probe_flag_restored": False}
    stack = ExitStack()
    result, stage_result, manifest, manifest_sha, local_ok = {}, None, None, None, False
    def execution_deadline(*_):
        context["timed_out"] = True
        refuse("600s bounded execution exceeded")
    signal.signal(signal.SIGALRM, execution_deadline)
    signal.alarm(MAX_SECONDS)
    try:
        sys.path[:0] = [str(context["site"]), str(SERVER)]
        install_import_boundary(context["site"])
        install_boundaries(context, counters, stack)
        fixture, manifest, manifest_sha = load_fixture(context)
        stage_result = async_schema_stage(context, fixture, manifest_sha)
        if not isinstance(stage_result, dict) or stage_result.get("schema_ready") is not True:
            refuse("actual catalog schema-ready proof required")
        if context["stage"] == "provision":
            if stage_result.get("stage") != "schema-provisioned":
                refuse("provision receipt stage mismatch")
            local_ok = True
        else:
            if context["receipt"]["selected_manifest_sha256"] != manifest_sha:
                refuse("provision selected manifest changed")
            result = run_actual80(context)
            local_ok = result["complete80"]
    except BaseException as error:
        # Exception class only: DSNs/content/credentials never enter evidence.
        result["failure_class"] = type(error).__name__
        local_ok = False
    finally:
        cleanup_ok = False
        try:
            cleanup_ok = cleanup_owned(counters)
            verify_inputs(context)
            guard_private_roots(context, context["anchors"])
        except BaseException as error:
            result["postflight_failure_class"] = type(error).__name__
            local_ok = False
        local_ok = (local_ok and cleanup_ok and not counters["forbidden"] and not context.get("timed_out")
                    and counters["ipv6_probe_flag_restored"])
        payload = {"stage": ("provision_schema_ready" if context["stage"] == "provision" and local_ok
                              else "actual80_local_complete_external_pending" if local_ok else "failed"),
                   "schema_ready": bool(local_ok and context["stage"] == "provision"),
                   "local_ok": local_ok, "global_acceptance": "PENDING_ROOT_EXTERNAL_VERIFIER",
                   "green": False, "runner_sha256": context["self_sha"], "fixture_sha256": FIXTURE_SHA256,
                   "source_trees": SOURCE_TREES, "dependency_files": context["dependencies"],
                   "original77": context["installed"], "base_commit": BASE_COMMIT,
                   "approval_id": context["approval"]["approval_id"],
                   "lease_id": context["approval"]["lease_id"], "lease": context["approval"]["lease"],
                   "external_lease": context["external_lease"], "lease_sha256": context["approval"]["lease_sha256"],
                   "database_oid": context["approval"]["database_oid"],
                   "selected_manifest_sha256": manifest_sha, "selected_table_manifest": manifest,
                   "fixture_receipt": stage_result, "cleanup_ok": cleanup_ok,
                   "forbidden": counters["forbidden"], "owned_connection_count": len(counters["connections"]),
                   "owned_connections_closed": all(c.is_closed() for c in counters["connections"]),
                   "cleanup_failures": counters["cleanup_failures"], "timed_out": bool(context.get("timed_out")),
                   "network": {k: counters[k] for k in ("pg_connect", "pg_sendmsg", "ipv6_probe_flag_restored")},
                   "before_inputs": context["inputs"], "results": result,
                   "external_required": ["8GiB floor/reserve before-and-after", "bounded DB/WAL/rows",
                                         "final PG clients/locks", "harness PID absence", "source/deps postflight"]}
        try:
            filename = "schema-ready.json" if context["stage"] == "provision" else "actual80-boundary.json"
            save_evidence(context["directories"][2] / filename, payload)
            guard_private_roots(context, context["anchors"])
        except BaseException:
            local_ok = False
        signal.alarm(0)
        stack.close()
    return 0 if local_ok else 1


def verify_describe_approval():
    """Separate sealed source plan: no DSN, lease, known manifest or test flags."""
    if (sys.argv[1:] != ["--describe-approved-service-location-writer-schema"]
            or os.getuid() != 0 or os.geteuid() != 0 or sys.implementation.name != "cpython"
            or sys.version_info[:3] != (3, 13, 7) or sys.flags.optimize
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or any(m in sys.modules for m in ("app", "pytest", "sqlalchemy", "asyncpg", "site"))
            or any("site-packages" in p or p in {"", str(SERVER)} for p in sys.path)):
        refuse("separate source-describe ROOT process required")
    flags = (DESCRIBE_OPTIN, "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE")
    allowed = {*flags, "HOME", "PATH", "LANG", "LC_ALL", "SLW_CWD", "SLW_EVIDENCE",
               "SLW_APPROVAL", "SLW_APPROVAL_SHA256", "SLW_RUNNER_SHA256"}
    if (set(os.environ) - allowed or any(os.environ.get(k) != "1" for k in flags)
            or os.environ.get("HOME") != pwd.getpwuid(0).pw_dir):
        refuse("source-describe unique opt-in/minimal environment required")
    for entry in os.listdir("/proc/self/fd"):
        fd = int(entry)
        if fd > 2:
            try:
                os.fstat(fd)
            except OSError:
                continue
            refuse("source-describe inherited foreign FD")
    path, approval = private_json(os.environ["SLW_APPROVAL"], os.environ["SLW_APPROVAL_SHA256"])
    expected_self = os.environ["SLW_RUNNER_SHA256"]
    if (approval.get("authority") != "ROOT" or approval.get("mode") != "describe"
            or approval.get("stage") != "describe" or approval.get("base_commit") != BASE_COMMIT
            or approval.get("run_id") != ROOT_LEASE_RUN_ID or not approval.get("approval_id")
            or approval.get("fixture_sha256") != FIXTURE_SHA256 or approval.get("runner_sha256") != expected_self
            or any(k in approval for k in ("lease", "database", "schema_receipt_sha256", "selected_manifest_sha256"))):
        refuse("sealed source-describe plan; no provision/test bypass or circular manifest pin")
    directories = [private_directory(os.environ[k]) for k in ("SLW_CWD", "SLW_EVIDENCE")]
    if (Path.cwd() != directories[0] or directories[0] == directories[1]
            or any(a.is_relative_to(b) for a in directories for b in directories if a != b)
            or any(p.is_relative_to(SERVER) or SERVER.is_relative_to(p) or path.is_relative_to(p) for p in directories)):
        refuse("source-describe fresh cwd and evidence only")
    interpreter = no_links(Path(sys.executable).absolute())
    if (str(interpreter) != approval["interpreter_path"] or sha(interpreter) != approval["interpreter_sha256"]
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"):
        refuse("source-describe physical interpreter freeze")
    sources_unchanged(expected_self)
    candidate = Path(approval["python_environment"])
    site, installed, files = inventory(candidate, approval["dependency_files"])
    inputs = {str(path): sha(path), str(interpreter): approval["interpreter_sha256"],
              str(candidate / "pyvenv.cfg"): sha(candidate / "pyvenv.cfg")}
    os.umask(0o077)
    return dict(stage="describe", approval=approval, self_sha=expected_self, directories=directories,
                site=site, installed=installed, dependencies=files, inputs=inputs)


def install_describe_boundaries(context, counters, stack):
    """Stdlib-only path: ALL network closed, including the provision PG port."""
    from importlib.machinery import PathFinder
    from unittest.mock import patch
    target = context["directories"][1] / "source-description.json"
    stdlib = no_links(Path(sysconfig.get_paths()["stdlib"]))

    def deny(event):
        if len(counters) < MAX_CAPTURE_EVENTS:
            counters.append(event)
        refuse("source-describe closed network/process/import/write boundary")

    class DescribeImports:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in {"app", "pytest", "pytest_asyncio", "sqlalchemy", "asyncpg", "aiohttp",
                                          "aiosmtplib", "httpx", "requests", "pywebpush"}:
                deny("describe-framework-import")
            spec = PathFinder.find_spec(fullname, path)
            if spec is not None:
                origins = list(spec.submodule_search_locations or ())
                if spec.origin and spec.origin not in {"built-in", "frozen"}:
                    origins.append(spec.origin)
                if any(not no_links(Path(value).absolute()).is_relative_to(stdlib) for value in origins):
                    deny("describe-nonstdlib-import")
            return None

    def audit(event, args):
        if event.startswith("socket.") and event != "socket.__new__":
            deny("describe-network:" + event)
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork", "os.forkpty",
                     "os.kill", "os.killpg", "os.chdir", "os.mkdir", "os.remove", "os.rmdir", "os.rename",
                     "os.link", "os.symlink", "os.truncate", "os.chown", "os.chmod", "os.utime"}:
            deny("describe-process-or-mutation:" + event)
        if event == "open":
            value = args[0]
            flags = args[2] if len(args) > 2 and type(args[2]) is int else 0
            if not isinstance(value, (str, bytes, os.PathLike)):
                deny("describe-file-descriptor-open")
            path = no_links(Path(os.path.abspath(os.fsdecode(value))))
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if path != target or not flags & os.O_EXCL:
                    deny("describe-write-outside-exclusive-evidence-file")

    def forbidden(*args, **kwargs):
        deny("describe-network-or-fd-operation")

    sys.meta_path.insert(0, DescribeImports())
    sys.addaudithook(audit)
    for name in ("send", "sendall", "sendmsg", "sendto", "recv", "recv_into", "recvfrom", "recvmsg", "listen"):
        if hasattr(socket.socket, name):
            stack.enter_context(patch.object(socket.socket, name, forbidden))
    for name in ("write", "writev", "pwrite", "pwritev", "ftruncate", "dup", "dup2", "fchmod", "fchown",
                 "sendfile", "copy_file_range", "splice"):
        if hasattr(os, name):
            stack.enter_context(patch.object(os, name, forbidden))


def describe_main():
    # Deliberately does not call verify_approval/install_boundaries/load_fixture:
    # those are provision/test paths and may import framework/driver code.
    try:
        context = verify_describe_approval()
    except Exception:
        print(json.dumps({"ok": False, "stage": "source_describe_approval", "runtime": "NOT_STARTED"}))
        return 2
    context["anchors"] = {p: (p.stat().st_dev, p.stat().st_ino, p.stat().st_uid) for p in context["directories"]}
    stack, forbidden, result, ok = ExitStack(), [], {}, False
    signal.signal(signal.SIGALRM, lambda *_: refuse("source-describe time bound"))
    signal.alarm(MAX_SECONDS)
    try:
        install_describe_boundaries(context, forbidden, stack)
        # Sole nonstdlib source execution is the exact reviewed fixture module;
        # only its stdlib AST/hash description functions are called in this mode.
        spec = importlib.util.spec_from_file_location("_slw_source_description_fixture", SERVER / FIXTURE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        manifest = module.static_schema_manifest(SERVER.parent.parent)
        result = {"manifest": manifest, "manifest_sha256": module.manifest_sha256(manifest),
                  "extra_ddl_sha256": manifest["bootstrap"]["extra_ddl_sha256"]}
        if (manifest["table_count"] != 21 or manifest["column_count"] != 458
                or len(result["extra_ddl_sha256"]) != 24):
            refuse("source description selected closure differs")
        ok = True
    except BaseException as error:
        result = {"failure_class": type(error).__name__}
    finally:
        try:
            verify_inputs(context)
            guard_private_roots(context, context["anchors"])
        except BaseException as error:
            result["postflight_failure_class"] = type(error).__name__
            ok = False
        ok = ok and not forbidden
        payload = {"stage": "source_described" if ok else "failed", "mode": "describe", "source_only": True,
                   "local_description_complete": ok, "runtime_acceptance": "NOTRUN", "green": False,
                   "schema_ready": False, "runner_sha256": context["self_sha"], "fixture_sha256": FIXTURE_SHA256,
                   "source_trees": SOURCE_TREES, "dependency_files": context["dependencies"],
                   "original77": context["installed"], "before_inputs": context["inputs"],
                   "forbidden": forbidden, "no_PG_or_driver_or_ORM_or_pytest": True, "result": result}
        try:
            save_evidence(context["directories"][1] / "source-description.json", payload)
            guard_private_roots(context, context["anchors"])
        except BaseException:
            ok = False
        signal.alarm(0)
        stack.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
