"""Pure safety predicate shared by opt-in partner/product/schema test suites.

Importing this module does not read environment variables, import pytest/ORM,
open files, resolve DNS or connect to a database. Callers decide SKIP versus
collection error before requesting any destructive conftest database fixture.
"""
from ipaddress import ip_address
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlsplit


def partner_test_safety_error(environ: Mapping[str, str], flag: str = "RUN_PARTNER_IDENTITY_TESTS") -> str | None:
    """Return a safe explanation or None; never echo a credential-bearing URL.

    A CI service alias is accepted only with an explicit CI flag; public DNS
    names, remote numeric IPs and URL connection overrides are rejected. This
    is an explicit intent/target guard, not proof of database ownership.
    """
    if environ.get(flag) != "1":
        return flag + "=1 is required"
    raw = environ.get("TEST_DATABASE_URL", "")
    if not raw:
        return "explicit TEST_DATABASE_URL is required (DATABASE_URL is ignored)"
    try:
        target = urlsplit(raw)
        port = target.port
    except ValueError:
        return "invalid TEST_DATABASE_URL"
    if (target.scheme != "postgresql+asyncpg" or target.query or target.fragment
            or not target.username or not target.hostname or port == 0):
        return "use postgresql+asyncpg without query/fragment connection overrides"
    name = target.path.removeprefix("/")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) or "test" not in name.split("_"):
        return "database name must contain an explicit test segment, e.g. partner_ci_test"
    host = target.hostname
    try:
        loopback = ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    ci = environ.get("CI", "").lower() in {"1", "true"}
    ci_service = ci and bool(re.fullmatch(r"[a-z][a-z0-9-]{0,62}", host))
    if not loopback and not ci_service:
        return "database host must be loopback, or a single service hostname with CI=1/true"
    upload = Path(environ.get("UPLOAD_DIR", ""))
    if not upload.is_absolute() or "test" not in upload.name.lower():
        return "explicit absolute test UPLOAD_DIR is required"
    return None
