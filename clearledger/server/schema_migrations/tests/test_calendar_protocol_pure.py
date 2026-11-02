"""Offline successor-chain negatives; ROOT runs these beside unchanged pure14."""
import asyncio
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest

from schema_migrations import journal, manifest, runner
from schema_migrations.errors import MigrationError


def history(package):
    entry = package.entry
    return dict(revision=entry["id"], ordinal=entry["ordinal"], parent_revision=entry["parent"],
                artifact_sha256=entry["artifact_sha256"], contract_sha256=entry["files"][package.contract_file],
                predecessor_sha256=package.parent.entry["artifact_sha256"] if package.parent else None,
                runner_format=1, app_commit=entry["source_commit"], applied_by="clearledger", action="created")


class CalendarPure(unittest.TestCase):
    def test_01_default_and_explicit_target_preserve_frozen_parent(self):
        first = manifest.load()
        second = manifest.load(revision=manifest.CALENDAR_ID)
        self.assertEqual(first.entry["id"], manifest.ID)
        self.assertIsNone(first.parent)
        self.assertEqual(second.parent.entry, first.entry)
        self.assertEqual(first.entry["artifact_sha256"], "301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1")

    def test_02_unknown_future_and_wrong_successor_parent_refuse_offline(self):
        for mutation in ("extra", "parent", "ordinal", "id"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(manifest.ROOT / "revisions", root / "revisions")
                value = json.loads((manifest.ROOT / "manifest.json").read_text())
                if mutation == "extra":
                    value["revisions"].append(copy.deepcopy(value["revisions"][1]))
                else:
                    value["revisions"][1][mutation] = {"parent": "wrong", "ordinal": 3, "id": "0003_future"}[mutation]
                (root / "manifest.json").write_text(json.dumps(value))
                with self.assertRaises(MigrationError):
                    manifest.load(root, revision=manifest.CALENDAR_ID)

    def test_03_complete_chain_and_default_newer_history_refusal(self):
        package = manifest.load(revision=manifest.CALENDAR_ID)
        one, two = history(package.parent), history(package)
        self.assertFalse(journal.validate_history([one], package, "clearledger"))
        self.assertTrue(journal.validate_history([one, two], package, "clearledger"))
        with self.assertRaises(MigrationError):
            journal.validate_history([one, two], package.parent, "clearledger")
        for values in ([], [two], [one, two, two]):
            with self.assertRaises(MigrationError):
                journal.validate_history(values, package, "clearledger")

    def test_04_every_successor_chain_field_is_verified(self):
        package = manifest.load(revision=manifest.CALENDAR_ID)
        one, two = history(package.parent), history(package)
        for field, value in (("predecessor_sha256", "0" * 64), ("parent_revision", None),
                             ("ordinal", 1), ("artifact_sha256", "0" * 64), ("contract_sha256", "0" * 64),
                             ("app_commit", "0" * 40), ("applied_by", "other"),
                             ("runner_format", 2), ("action", "repaired")):
            with self.subTest(field=field), self.assertRaises(MigrationError):
                journal.validate_history([one, {**two, field: value}], package, "clearledger")

    def test_05_cutover_acknowledgement_is_required_before_driver(self):
        config = runner.Config("postgresql://clearledger:synthetic@127.0.0.1:33546/api_calendar_protocol_version_test_20261031",
                               "api_calendar_protocol_version_test_20261031", "clearledger", "core")
        for value in (None, True, 1_999_999_999):
            with self.subTest(value=value), self.assertRaises(MigrationError) as error:
                asyncio.run(runner.execute(config, "apply", revision=manifest.CALENDAR_ID, legacy_sent_before=value))
            self.assertEqual(error.exception.code, 2)
        self.assertNotIn("asyncpg", sys.modules)

    def test_06_explicit_plan_does_not_read_any_environment(self):
        class RefuseEnvironment:
            def get(self, key):
                raise AssertionError("environment access")
        with redirect_stdout(io.StringIO()) as output:
            result = runner.main(["plan", "--revision", manifest.CALENDAR_ID], RefuseEnvironment())
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["revision"], manifest.CALENDAR_ID)
