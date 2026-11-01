"""Написаны, NOT RUN: offline0004 integrity и совместимость с head0006.

Без driver/ORM/application imports. До запуска ROOT проверяет и замораживает
новый source: прежние immutable acceptance helpers его не допускают.
"""
import asyncio
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from schema_migrations import journal, manifest, runner
from schema_migrations.errors import MigrationError
from schema_migrations.revisions.catalog_partner_contract_create_v1 import expression


def row(package):
    e = package.entry
    return dict(revision=e['id'], ordinal=e['ordinal'], parent_revision=e['parent'],
        artifact_sha256=e['artifact_sha256'], contract_sha256=e['files'][package.contract_file],
        predecessor_sha256=package.parent.entry['artifact_sha256'] if package.parent else None,
        action='created', applied_by='clearledger', app_commit=e['source_commit'], runner_format=1)


class PartnerContractCreatePure(unittest.TestCase):
    def test_head6_default1_explicit3_4_5_6_and_frozen_artifact_ids(self):
        self.assertEqual(manifest.load().entry['id'], manifest.ID)
        self.assertEqual(manifest.load_known_head().entry['id'], manifest.SITE_AUTHORITY_ID)
        chain = runner._packages(manifest.load_known_head())
        self.assertEqual(len(chain), 6)
        self.assertEqual([chain[i].entry['artifact_sha256'] for i in (1, 2, 3, 4, 5)], [
            '301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1',
            '203ee350a47fb3e12d2e2fb6d292fc0e1a19b4cd3cd348b507551cf233cae2f0',
            'c98bc5d27c6aa710618bb5d209d0ef0adfd11a6a4825dcd0831c7403e872cc3d',
            '58ff7a0cf33f7fb55fa080e4efe60c1a4aece67588cf1bfe8b44bc75e92c7e31',
            '99d6c539f5a5e4962926e6d8978db3a5487bab0d5fb20531b31cd95daf59d42d'])
        self.assertEqual(chain[6].entry['artifact_sha256'], '94f830704cee4366dfe9565370aac00de74143691e99b9b8f797d48ff51f4b7d')
        for ordinal, target in ((3, manifest.PULSE_ID), (4, manifest.CONTRACT_CREATE_ID),
                (5, manifest.CONTRACT_CYCLE_RECEIPTS_ID), (6, manifest.SITE_AUTHORITY_ID)):
            head, *_ = runner._sequence_source(target, None, 2000000000)
            self.assertEqual(head.entry['id'], target)
            self.assertEqual(head, manifest.load(revision=target))
            self.assertEqual(head, chain[ordinal])
            self.assertEqual(len(runner._packages(head)), ordinal)

    def test_every_old_registry_prefix_loads_its_explicit_revision(self):
        registry = json.loads((manifest.ROOT / 'manifest.json').read_text())
        for count in (1, 2, 3, 4, 5, 6):
            with self.subTest(count=count), TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(manifest.ROOT / 'revisions', root / 'revisions')
                (root / 'manifest.json').write_text(json.dumps({**registry, 'revisions': registry['revisions'][:count]}))
                for entry in registry['revisions'][:count]:
                    self.assertEqual(manifest.load(root, revision=entry['id']).entry, entry)
                if count < 4:
                    with self.assertRaises(MigrationError):
                        manifest.load(root, revision=manifest.CONTRACT_CREATE_ID)
                if count < 5:
                    with self.assertRaises(MigrationError):
                        manifest.load(root, revision=manifest.CONTRACT_CYCLE_RECEIPTS_ID)
                else:
                    self.assertEqual(manifest.load(root, revision=manifest.CONTRACT_CYCLE_RECEIPTS_ID).entry, registry['revisions'][4])
                if count < 6:
                    with self.assertRaises(MigrationError):
                        manifest.load_known_head(root)
                else:
                    self.assertEqual(manifest.load_known_head(root).entry, registry['revisions'][5])

    def test_all_successor_chain_fields_are_checked(self):
        packages = runner._packages(manifest.load(revision=manifest.CONTRACT_CREATE_ID))
        rows = [row(packages[i]) for i in (1, 2, 3, 4)]
        self.assertTrue(journal.validate_history(rows, packages[4], 'clearledger'))
        self.assertFalse(journal.validate_history(rows[:3], packages[4], 'clearledger'))
        for count in (1, 2, 3):
            self.assertTrue(journal.validate_history(rows[:count], packages[count], 'clearledger'))
        for field, value in [('revision', '0004_foreign'), ('ordinal', 5), ('parent_revision', None),
            ('artifact_sha256', '0' * 64), ('contract_sha256', '0' * 64), ('predecessor_sha256', '0' * 64),
            ('app_commit', '0' * 40), ('runner_format', 2), ('applied_by', 'foreign'), ('action', 'repaired')]:
            with self.subTest(field=field), self.assertRaises(MigrationError):
                journal.validate_history(rows[:3] + [{**rows[3], field: value}], packages[4], 'clearledger')
        for bad in [rows + [{**rows[3], 'revision': '0005_future', 'ordinal': 5}], rows[:2] + rows[3:]]:
            with self.assertRaises(MigrationError):
                journal.validate_history(bad, packages[4], 'clearledger')
        known_head = manifest.load(revision=manifest.CONTRACT_CYCLE_RECEIPTS_ID)
        rows5 = rows + [row(known_head)]
        self.assertTrue(journal.validate_history(rows5, known_head, 'clearledger'))
        self.assertFalse(journal.validate_history(rows, known_head, 'clearledger'))
        with self.assertRaises(MigrationError):
            journal.validate_history(rows5, packages[4], 'clearledger')
        with self.assertRaises(MigrationError):
            journal.validate_history(rows5 + [{**rows5[4], 'revision': '0006_future', 'ordinal': 6}],
                known_head, 'clearledger')
        actual_head = manifest.load_known_head()
        rows6 = rows5 + [row(actual_head)]
        self.assertTrue(journal.validate_history(rows6, actual_head, 'clearledger'))
        self.assertFalse(journal.validate_history(rows5, actual_head, 'clearledger'))
        with self.assertRaises(MigrationError):
            journal.validate_history(rows6, known_head, 'clearledger')
        with self.assertRaises(MigrationError):
            journal.validate_history(rows6 + [{**rows6[5], 'revision': '0007_future', 'ordinal': 7}],
                actual_head, 'clearledger')

    def test_tampered_sql_contract_catalog_and_checksum_refuse(self):
        for suffix in ('.sql', '.json', '.py', 'artifact'):
            with self.subTest(suffix=suffix), TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(manifest.ROOT / 'revisions', root / 'revisions')
                registry = json.loads((manifest.ROOT / 'manifest.json').read_text())
                entry = registry['revisions'][3]
                if suffix == 'artifact':
                    entry['artifact_sha256'] = '0' * 64
                else:
                    path = next(p for p in entry['files'] if p.endswith(suffix) and 'journal' not in p)
                    with (root / path).open('ab') as output:
                        output.write(b'\n ')
                (root / 'manifest.json').write_text(json.dumps(registry))
                with self.assertRaises(MigrationError):
                    manifest.load(root, revision=manifest.ID)  # Старый requested package тоже проверяет весь известный source.

    def test_unknown_seventh_unknown_sixth_fifth_names_and_foreign_fourth_refuse(self):
        for mutation in ('seventh', 'sixth_name', 'fifth_name', 'foreign', 'parent'):
            with self.subTest(mutation=mutation), TemporaryDirectory() as temporary:
                root = Path(temporary)
                shutil.copytree(manifest.ROOT / 'revisions', root / 'revisions')
                registry = json.loads((manifest.ROOT / 'manifest.json').read_text())
                (root / 'manifest.json').write_text(json.dumps(registry))
                self.assertEqual(manifest.load(root).entry['id'], manifest.ID)
                self.assertEqual(manifest.load_known_head(root).entry['id'], manifest.SITE_AUTHORITY_ID)
                if mutation == 'seventh':
                    future = copy.deepcopy(registry['revisions'][5])
                    future.update(id='0007_future', ordinal=7, parent=manifest.SITE_AUTHORITY_ID)
                    registry['revisions'].append(future)
                elif mutation == 'sixth_name':
                    registry['revisions'][5]['id'] = '0006_future'
                elif mutation == 'fifth_name':
                    registry['revisions'][4]['id'] = '0005_future'
                else:
                    registry['revisions'][3]['id' if mutation == 'foreign' else 'parent'] = '0004_foreign'
                (root / 'manifest.json').write_text(json.dumps(registry))
                with self.assertRaises(MigrationError):
                    manifest.load(root)

    def test_plan6_plan5_plan4_and_plan3_have_no_environment_access(self):
        class NoEnvironment:
            def get(self, name):
                raise AssertionError('offline plan read credentials')
        for target in (manifest.PULSE_ID, manifest.CONTRACT_CREATE_ID, manifest.CONTRACT_CYCLE_RECEIPTS_ID, manifest.SITE_AUTHORITY_ID):
            with redirect_stdout(io.StringIO()) as output:
                code = runner.main(['plan', '--revision', target], NoEnvironment())
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())['revision'], target)

    def test_apply4_requires_calendar_ack_before_driver_import(self):
        cfg = runner.Config('postgresql://clearledger:api_test_only@127.0.0.1:33546/api_partner_contract_schema_v4_test_20261101',
            'api_partner_contract_schema_v4_test_20261101', 'clearledger', 'core')
        for ack in (None, True, 1999999999):
            with self.subTest(ack=ack), self.assertRaises(MigrationError) as caught:
                asyncio.run(runner.execute(cfg, 'apply', revision=manifest.CONTRACT_CREATE_ID, legacy_sent_before=ack))
            self.assertEqual((caught.exception.code, caught.exception.phase), (2, 'legacy_acknowledgement'))

    def test_boolean_normalization_preserves_parentheses_and_exact_strings(self):
        self.assertEqual(expression("(a = 'UP PER'::text) AND (b IS NOT NULL)"), expression("a='UP PER' AND b IS NOT NULL"))
        self.assertNotEqual(expression('(a OR b) AND c'), expression('a OR (b AND c)'))
        self.assertNotEqual(expression("a='x(y)'"), expression("a='xy'"))
        self.assertNotEqual(expression("a='ABC'"), expression("a='abc'"))

    def test_history_has_only_nullable_current_foreign_keys(self):
        package = manifest.load(revision=manifest.CONTRACT_CREATE_ID)
        spec = package.contract
        intent = spec['tables']['partner_contract_success_intents']
        self.assertEqual({(f['table'], f['delete']) for f in intent['foreign_keys'].values()}, {('users', 'n'), ('contracts', 'n')})
        self.assertEqual(len(intent['foreign_keys']), 2)
        self.assertEqual(spec['tables']['partner_contract_intent_locations']['primary'], ['intent_id', 'location_id'])
        self.assertEqual(len(spec['tables']['partner_contract_intent_locations']['foreign_keys']), 1)
        self.assertEqual(intent['unique']['uq_pc_intent_namespace'], ['company_id','app_id','installation_id','operation','creation_key'])
        self.assertNotIn('INCLUDE', package.sql)
        self.assertNotIn('IF NOT EXISTS', package.sql)
        for body in spec['functions'].values():
            self.assertNotIn('SECURITY DEFINER', body)
