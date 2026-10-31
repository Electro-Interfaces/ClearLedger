"""Applied-history validation; all durable writes belong to the runner's transaction."""
from schema_migrations.errors import MigrationError
from schema_migrations.manifest import FILES


def validate_history(rows, package, owner):
    e = package.entry
    if package.parent is not None:
        if len(rows) < e["ordinal"] - 1 or len(rows) > e["ordinal"]:
            raise MigrationError(4, "parent_history")
        validate_history(rows[:e["ordinal"] - 1], package.parent, owner)
        if len(rows) == e["ordinal"] - 1:
            return False
        row = rows[e["ordinal"] - 1]
        if (row["ordinal"] != e["ordinal"] or row["revision"] != e["id"] or row["parent_revision"] != package.parent.entry["id"]
                or row["artifact_sha256"] != e["artifact_sha256"]
                or row["contract_sha256"] != e["files"][package.contract_file]
                or row["predecessor_sha256"] != package.parent.entry["artifact_sha256"]
                or row["runner_format"] != e["runner_format"] or row["app_commit"] != e["source_commit"]
                or row["applied_by"] != owner or row["action"] not in {"created", "adopted"}):
            raise MigrationError(4, "history")
        return True
    if len(rows) > 1:
        raise MigrationError(4, "history")
    for row in rows:
        if (row["ordinal"] != 1 or row["revision"] != e["id"] or row["parent_revision"] is not None
                or row["artifact_sha256"] != e["artifact_sha256"]
                or row["contract_sha256"] != e["files"][FILES[2]]
                or row["predecessor_sha256"] is not None or row["runner_format"] != e["runner_format"]
                or row["app_commit"] != e["source_commit"] or row["applied_by"] != owner
                or row["action"] not in {"created", "adopted"}):
            raise MigrationError(4, "history")
    return bool(rows)


async def read_verified_history(conn, package, owner, exists):
    if not exists:
        return False
    # Bounded: any second row is already an unknown/newer/history mismatch.
    limit = package.entry["ordinal"] + 1
    rows = await conn.fetch("""SELECT revision, ordinal, parent_revision, artifact_sha256,
        contract_sha256, predecessor_sha256, action, applied_by, app_commit, runner_format
        FROM core.core_schema_versions ORDER BY ordinal LIMIT $1""", limit)
    return validate_history(rows, package, owner)


async def append_applied(conn, package, owner, action):
    if action not in {"created", "adopted"}:
        raise MigrationError(6, "append")
    e = package.entry
    await conn.execute("""INSERT INTO core.core_schema_versions
        (revision,ordinal,parent_revision,artifact_sha256,contract_sha256,
         predecessor_sha256,action,applied_by,app_commit,runner_format)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
        e["id"], e["ordinal"], e["parent"], e["artifact_sha256"], e["files"][package.contract_file],
        package.parent.entry["artifact_sha256"] if package.parent is not None else None,
        action, owner, e["source_commit"], e["runner_format"])
