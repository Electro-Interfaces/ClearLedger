"""ROOT M09 child adapter: only frozen pure14 subprocesses or PG13 test12 CLI.

The parent validates real caller code identity, original argv/env and count.
This child independently rechecks source/candidate/target/path/argv before real
compile/exec of the requested code or runner CLI. Never executes fake SQL/results.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import pwd
import resource
import signal
import stat
import sys
from types import ModuleType
from urllib.parse import urlsplit

SELF = Path(__file__).resolve()
GATE = SELF.with_name("calendar_protocol_version_approved.py")


def refuse():
    raise RuntimeError("M09 frozen child boundary refused")


def main():
    if (sys.argv[1:] != ["--execute-approved-m09-child"] or sys.version_info[:3] != (3, 13, 7)
            or not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode
            or sys.flags.optimize or any(m in sys.modules for m in ("app", "asyncpg", "pytest", "site"))
            or os.confstr("CS_GNU_LIBC_VERSION") != "glibc 2.36"):
        refuse()
    parent_sha = os.environ.get("M09_RUNNER_SHA256", "")
    if (GATE.is_symlink() or SELF.is_symlink() or hashlib.sha256(GATE.read_bytes()).hexdigest() != parent_sha
            or hashlib.sha256(SELF.read_bytes()).hexdigest() != os.environ.get("M09_CHILD_SHA256")):
        refuse()
    gate = ModuleType("m09_frozen_gate")
    gate.__file__ = str(GATE)
    exec(compile(GATE.read_bytes(), str(GATE), "exec"), gate.__dict__)
    if (set(os.environ) != gate.FROZEN_ENV | {"M09_CHILD_PAYLOAD", "M09_CHILD_SHA256"}
            or any(os.environ[k] != "1" for k in gate.FROZEN_FLAGS)
            or Path(sys.executable).absolute().parent != gate.CANDIDATE / "bin"
            or os.environ["HOME"] != pwd.getpwuid(os.getuid()).pw_dir
            or os.environ["APP_ENV"] != "test" or os.environ["PATH"] != "/usr/bin:/bin"
            or os.environ["LANG"] != "C.UTF-8" or os.environ["LC_ALL"] != "C.UTF-8"
            or os.environ["SECRET_KEY"] != "calendar-protocol-version-synthetic-secret-only"
            or os.environ["SEED_SUPERADMIN_EMAIL"] != "admin@clearledger.ru"
            or os.environ["SEED_SUPERADMIN_PASSWORD"] != "admin123" or os.environ["ECOSYSTEM_COMPANIES"] != ""
            or os.environ["DATABASE_URL"] != os.environ["TEST_DATABASE_URL"]):
        refuse()
    roots = [Path(os.environ[k]) for k in ("M09_EMPTY_CWD", "UPLOAD_DIR", "M09_EVIDENCE_DIR", "M09_SCRATCH_DIR")]
    for root in roots:
        if (not root.is_absolute() or not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents))
                or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077):
            refuse()
        anchor = (root.stat().st_dev, root.stat().st_ino, root.stat().st_uid)
        gate.scratch_bound(root, anchor)
    empty, upload, evidence, scratch = roots
    if (Path.cwd() != empty or any(empty.iterdir()) or os.environ["TMPDIR"] != str(scratch)
            or len(set(roots)) != 4 or any(a != b and a.is_relative_to(b) for a in roots for b in roots)):
        refuse()
    payload = Path(os.environ["M09_CHILD_PAYLOAD"])
    if (not payload.is_relative_to(scratch) or payload.is_symlink() or not stat.S_ISREG(payload.stat().st_mode)
            or payload.stat().st_uid != os.getuid() or payload.stat().st_mode & 0o077 or payload.stat().st_size > 64 * 1024):
        refuse()
    request = json.loads(payload.read_bytes())
    if set(request) != {"phase", "origin", "argv", "environment"} or request["phase"] != os.environ["M09_PHASE"]:
        refuse()
    target = urlsplit(os.environ["TEST_DATABASE_URL"])
    if (target.scheme != "postgresql+asyncpg" or target.hostname != "127.0.0.1" or target.port != gate.PORT
            or target.path != "/" + gate.DATABASE or target.username != "clearledger" or target.password != "api_test_only"
            or target.query or target.fragment or os.environ["M09_PG_PORT"] != str(gate.PORT)
            or not gate.sources_unchanged()):
        refuse()
    installed = gate.inventory()
    gate.validate_child_request(request["phase"], request["origin"], request["argv"], request["environment"], scratch)
    paths = []
    for item in sys.path:
        path = Path(item)
        if path == gate.STDLIB.parent / "python313.zip" and not path.exists() and not path.is_symlink():
            continue
        if not path.is_absolute() or not path.is_dir() or not path.resolve().is_relative_to(gate.STDLIB.resolve()):
            refuse()
        paths.append(str(path))
    sys.path[:] = [str(gate.SITE), str(gate.SERVER), *paths]
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    address_limit = (1 if request["phase"] == "pure" else 8) * 1024 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (address_limit, address_limit))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    signal.alarm(35)
    counters = {"forbidden": [], "pg_connect": 0, "pg_sendmsg": 0, "delivery": {}}
    with ExitStack() as stack:
        gate.install_boundaries(target, counters, stack, (scratch, upload, evidence), sql=request["phase"] == "foundation",
                                environment_values=request["environment"])
        # Restore exactly the original test environment only after approval;
        # absent legacy flags remain absent, including in negative import probes.
        os.environ.clear()
        os.environ.update(request["environment"])
        argv = request["argv"]
        code = 0
        try:
            if argv[2] == "-c":
                sys.argv = ["-c"]
                exec(compile(argv[3], "<frozen-pure-test>", "exec"), {"__name__": "__main__"})
            else:
                script = Path(argv[2])
                sys.argv = list(argv[2:])
                namespace = {"__name__": "__main__", "__file__": str(script), "__package__": None}
                exec(compile(script.read_bytes(), str(script), "exec"), namespace)
        except SystemExit as stopped:
            code = stopped.code if isinstance(stopped.code, int) else 1
        finally:
            signal.alarm(0)
        if counters["forbidden"] or gate.inventory() != installed or not counters["ipv6_probe_flag_restored"]:
            refuse()
        return code


if __name__ == "__main__":
    raise SystemExit(main())
