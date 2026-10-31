"""Offline verification of one allowlisted frozen revision, independent of registry append."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from schema_migrations.errors import MigrationError

ROOT = Path(__file__).resolve().parent
ID = "0001_product_api_budgets"
CALENDAR_ID = "0002_calendar_protocol_sequence"
FILES = ("revisions/0001_product_api_budgets.sql", "revisions/journal_v1.sql",
    "revisions/0001_contract.json", "revisions/catalog_v1.py")
CALENDAR_FILES = ("revisions/0002_calendar_protocol_sequence.sql", "revisions/journal_v1.sql",
    "revisions/0002_calendar_contract.json", "revisions/catalog_v2.py")
ALLOWLIST = ((ID, FILES, None), (CALENDAR_ID, CALENDAR_FILES, ID))
V1_ARTIFACT = "301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def artifact_digest(entry, payloads):
    # Hash this revision only. Never hash the outer registry or future entries.
    metadata = {key: value for key, value in entry.items() if key != "artifact_sha256"}
    pieces = [canonical(metadata)] + [payloads[path] for path in sorted(entry["files"])]
    return hashlib.sha256(b"".join(len(piece).to_bytes(8, "big") + piece for piece in pieces)).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(2, "manifest")
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


@dataclass(frozen=True)
class Package:
    entry: dict
    contract: dict
    sql: str
    journal_sql: str
    parent: "Package | None" = None

    @property
    def contract_file(self):
        return FILES[2] if self.entry["id"] == ID else CALENDAR_FILES[2]


def load(root=ROOT, *, revision=ID):
    try:
        registry = decode((root / "manifest.json").read_bytes())
        if (set(registry) != {"format", "revisions"} or registry["format"] != 1
                or len(registry["revisions"]) not in (1, 2) or revision not in {ID, CALENDAR_ID}):
            raise MigrationError(2, "manifest")
        expected_keys = {"id", "ordinal", "parent", "namespace", "runner_format", "source_commit", "files", "artifact_sha256"}
        packages = []
        for position, entry in enumerate(registry["revisions"]):
            wanted, files, parent = ALLOWLIST[position]
            if (set(entry) != expected_keys or entry["id"] != wanted or type(entry["ordinal"]) is not int
                    or entry["ordinal"] != position + 1 or entry["parent"] != parent or entry["namespace"] != "core"
                    or entry["runner_format"] != 1 or not re.fullmatch(r"[a-f0-9]{40}", entry["source_commit"])
                    or set(entry["files"]) != set(files)):
                raise MigrationError(2, "manifest")
            payloads = {}
            for path, digest in entry["files"].items():
                target = root / path
                if target.is_symlink() or not re.fullmatch(r"[a-f0-9]{64}", digest):
                    raise MigrationError(2, "manifest")
                raw = target.read_bytes()
                if len(raw) > 256_000 or b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
                    raise MigrationError(2, "artifact")
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise MigrationError(2, "integrity")
                payloads[path] = raw
            if artifact_digest(entry, payloads) != entry["artifact_sha256"]:
                raise MigrationError(2, "integrity")
            if position == 0 and entry["artifact_sha256"] != V1_ARTIFACT:
                raise MigrationError(2, "integrity")
            contract = decode(payloads[files[2]])
            if contract["format"] != 1 or contract["namespace"] != "core":
                raise MigrationError(2, "contract")
            packages.append(Package(entry, contract, payloads[files[0]].decode(), payloads[files[1]].decode(),
                                    packages[0] if position else None))
        return next(package for package in packages if package.entry["id"] == revision)
    except MigrationError:
        raise
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, AttributeError, StopIteration):
        raise MigrationError(2, "manifest") from None
