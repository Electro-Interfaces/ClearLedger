"""Meaningful offline CLI/artifact/history checks; direct unittest entrypoint, no pytest/app."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

SERVER = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER))
from schema_migrations import journal, manifest, runner
from schema_migrations.errors import MigrationError
from schema_migrations.revisions.catalog_v1 import normalize_check


class PureFoundation(unittest.TestCase):
    def test_real_offline_cli_with_minimal_environment(self):
        process = subprocess.run([sys.executable, "-I", str(SERVER/'schema_migrations/runner.py'), 'plan'],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stdout)
        value = json.loads(process.stdout)
        self.assertTrue(value['foundation_only'])
        self.assertEqual(value['revision'], manifest.ID)
        self.assertEqual(process.stderr, '')

    def test_imports_do_not_load_driver_or_app(self):
        code = ("import sys; sys.path.insert(0," + repr(str(SERVER)) + "); "
            "import schema_migrations.runner; "
            "assert not any(k=='app' or k.startswith('app.') or k=='asyncpg' or k=='schema_migrations.revisions.catalog_v1' for k in sys.modules)")
        p = subprocess.run([sys.executable, '-I', '-c', code], env={}, capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_frozen_artifacts_and_revision_hash_independent_of_registry_append(self):
        package = manifest.load()
        payloads = {name:(manifest.ROOT/name).read_bytes() for name in manifest.FILES}
        outer = {'revisions': [copy.deepcopy(package.entry)]}
        before = manifest.artifact_digest(outer['revisions'][0], payloads)
        outer['revisions'].append({'id':'0002_future', 'parent':manifest.ID})
        self.assertEqual(before, manifest.artifact_digest(outer['revisions'][0], payloads))
        self.assertEqual(before, package.entry['artifact_sha256'])

    def test_changed_sql_contract_and_verifier_refuse_offline(self):
        for name in manifest.FILES:
            with self.subTest(artifact=name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(manifest.ROOT/'revisions', root/'revisions')
                shutil.copy(manifest.ROOT/'manifest.json', root/'manifest.json')
                with (root/name).open('ab') as out:
                    out.write(b'\n')
                with self.assertRaises(MigrationError) as err:
                    manifest.load(root)
                self.assertEqual(err.exception.code, 2)

    def test_unrecognized_revision_path_and_duplicate_json_refuse(self):
        for mutation in ('id', 'path', 'duplicate'):
            with self.subTest(mutation=mutation), TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(manifest.ROOT/'revisions', root/'revisions')
                value = json.loads((manifest.ROOT/'manifest.json').read_text())
                if mutation == 'id': value['revisions'][0]['id'] = 'unknown'
                if mutation == 'path': value['revisions'][0]['files']['../../outside'] = '0'*64
                raw = json.dumps(value) if mutation != 'duplicate' else '{"format":1,"format":1,"revisions":[]}'
                (root/'manifest.json').write_text(raw)
                with self.assertRaises(MigrationError): manifest.load(root)

    def test_explicit_target_and_no_fallback_before_driver_import(self):
        secret = 'postgresql://actor:PRIVATE@127.0.0.1:33546/owned_test'
        for argv, env in ((['apply'], {'DATABASE_URL':secret}),
                (['check','--dsn-env','DATABASE_URL','--database','owned_test','--user','actor','--namespace','core'], {'DATABASE_URL':secret}),
                (['apply',secret], {})):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(argv, env), 2)
            self.assertNotIn('PRIVATE', output.getvalue())
        self.assertNotIn('asyncpg',sys.modules)

    def test_config_refuses_redirects_namespace_and_target_mismatch(self):
        good='postgresql://actor:PRIVATE@127.0.0.1:33546/owned_test'
        for value,db,user,ns in ((good+'?host=elsewhere','owned_test','actor','core'),
                (good,'different_test','actor','core'),(good,'owned_test','other','core'),
                (good,'owned_test','actor','public'),(good.replace(':33546',''),'owned_test','actor','core')):
            with self.subTest(db=db,user=user,ns=ns), self.assertRaises(MigrationError):
                runner.Config(value,db,user,ns).validate()
        self.assertNotIn('PRIVATE',repr(runner.Config(good,'owned_test','actor','core')))

    def test_history_tampering_unknown_revision_and_gap_refuse(self):
        package = manifest.load()
        row = dict(revision=manifest.ID, ordinal=1, parent_revision=None,
            artifact_sha256=package.entry['artifact_sha256'],contract_sha256=package.entry['files'][manifest.FILES[2]],
            predecessor_sha256=None,runner_format=1,app_commit=package.entry['source_commit'],
            applied_by='actor',action='created')
        self.assertTrue(journal.validate_history([row], package,'actor'))
        self.assertFalse(journal.validate_history([], package,'actor'))
        for field,value in [('revision','newer'),('ordinal',2),('parent_revision','unknown'),
                ('artifact_sha256','0'*64),('contract_sha256','0'*64),('predecessor_sha256','1'*64),
                ('runner_format',2),('app_commit','0'*40),('applied_by','other'),('action','repaired')]:
            with self.subTest(field=field), self.assertRaises(MigrationError):
                journal.validate_history([{**row,field:value}],package,'actor')
        with self.assertRaises(MigrationError): journal.validate_history([row,row],package,'actor')

    def test_check_normalization_is_narrow_not_a_looser_policy(self):
        expected='used >= 1 AND used <= request_limit + 1'
        self.assertEqual(normalize_check('((used >= 1) AND (used <= (request_limit + 1)))'),normalize_check(expected))
        for changed in ['used >= 0 AND used <= request_limit + 1','used >= 1 OR used <= request_limit + 1',
                'used >= 1 AND used < request_limit + 1','used >= 1']:
            self.assertNotEqual(normalize_check(changed), normalize_check(expected))

    def test_action_string_literals_preserve_case_whitespace_and_parentheses(self):
        expected = "action = 'created'::text OR action = 'adopted'::text"
        for literal in ['CREATED', 'cre ated', 'cre\tat ed', 'cre(ated)']:
            with self.subTest(literal=literal):
                self.assertNotEqual(normalize_check(expected.replace("'created'", repr(literal))), normalize_check(expected))
        self.assertEqual(normalize_check("((action = 'created'::text) OR (action = 'adopted'::text))"), normalize_check(expected))

    def test_changed_verifier_is_rejected_before_its_import_marker_executes(self):
        with TemporaryDirectory() as tmp:
            copied = Path(tmp)/'schema_migrations'
            shutil.copytree(manifest.ROOT, copied, ignore=shutil.ignore_patterns('__pycache__'))
            marker = Path(tmp)/'must-not-exist'
            with (copied/'revisions/catalog_v1.py').open('a') as out:
                out.write("\nfrom pathlib import Path\nPath("+repr(str(marker))+").write_text('EXECUTED')\n")
            process = subprocess.run([sys.executable,'-I',str(copied/'runner.py'),'plan'],
                env={},capture_output=True,text=True,timeout=10)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads(process.stdout)['phase'], 'integrity')
            self.assertFalse(marker.exists())

    def test_plan_never_reads_credential_environment(self):
        class RefuseEnvironment:
            def get(self, key):
                raise AssertionError('environment access')
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(['plan'], RefuseEnvironment()), 0)
        self.assertTrue(json.loads(output.getvalue())['foundation_only'])

    def test_unittest_and_preflight_paths_refuse_before_driver_without_flag(self):
        code = """import sys,asyncio
sys.path.insert(0,SERVER)
from schema_migrations.tests.run_postgres import preflight,ActualFoundation
for fn in [preflight,ActualFoundation('test_01_create_repeat_readonly_check_and_populated_rows').asyncSetUp]:
    try:
        asyncio.run(fn())
    except RuntimeError:
        pass
    else:
        raise AssertionError('guard was bypassed')
assert 'asyncpg' not in sys.modules
assert not any(k=='app' or k.startswith('app.') for k in sys.modules)
""".replace('SERVER',repr(str(SERVER)))
        result=subprocess.run([sys.executable,'-I','-c',code],env={},capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_approval_wrapper_checks_harness_hash_before_running_it(self):
        with TemporaryDirectory() as tmp:
            copied=Path(tmp)/'schema_migrations'
            shutil.copytree(manifest.ROOT,copied,ignore=shutil.ignore_patterns('__pycache__'))
            marker=Path(tmp)/'harness-must-not-run'
            harness=copied/'tests/run_postgres.py'
            harness.write_text("from pathlib import Path\nPath("+repr(str(marker))+").write_text('EXECUTED')\n"+harness.read_text())
            result=subprocess.run([sys.executable,'-I',str(copied/'tests/approved_postgres.py'),
                '--execute-approved-contract-tests'],env={},capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,2)
            self.assertEqual(json.loads(result.stdout)['phase'],'source_approval')
            self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
