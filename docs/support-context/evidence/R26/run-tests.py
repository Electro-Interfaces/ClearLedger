"""Изолированный запуск R26: собственный PG/loopback, удаление в finally."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
label, *pytest_args = sys.argv[1:]
name = "core-support-context-r26-" + uuid.uuid4().hex[:12]
receipt = {"container": name, "database": "core_support_context_r26", "loopback": True,
           "pytest_args": pytest_args, "cleanup": False,
           "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
           "runtime_service_sha256": hashlib.sha256((ROOT / "clearledger/server/app/services/support_context.py").read_bytes()).hexdigest()}
code = 1
try:
    subprocess.run(["docker", "run", "-d", "--name", name, "--tmpfs", "/var/lib/postgresql/data:rw",
                    "-p", "127.0.0.1::5432", "-e", "POSTGRES_USER=r26_test",
                    "-e", "POSTGRES_PASSWORD=synthetic-r26", "-e", "POSTGRES_DB=core_support_context_r26",
                    "postgres:16"], check=True, capture_output=True, text=True)
    for attempt in range(60):
        ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "r26_test",
                                "-d", "core_support_context_r26"], capture_output=True)
        if ready.returncode == 0:
            break
        time.sleep(.25)
    else:
        raise RuntimeError("Own PostgreSQL did not become ready")
    port = json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0][
        "NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
    receipt["port"] = int(port)
    env = {**os.environ, "R26_EVIDENCE_PREFIX": str(EVIDENCE / label), "TEST_DATABASE_URL":
           f"postgresql+asyncpg://r26_test:synthetic-r26@127.0.0.1:{port}/core_support_context_r26"}
    command = [str(ROOT / ".venv/bin/python"), "-m", "pytest", *pytest_args,
               "-q", "--disable-warnings", "--tb=short"]
    with (EVIDENCE / f"{label}.tap").open("w") as output:
        result = subprocess.run(command, cwd=ROOT / "clearledger/server", env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    code = receipt["pytest_exit"] = result.returncode
    print((EVIDENCE / f"{label}.tap").read_text())
finally:
    removed = subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True)
    receipt["cleanup"] = removed.returncode == 0
    (EVIDENCE / f"{label}-resources.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
sys.exit(code)
