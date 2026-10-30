"""Pure ASGI introspection and real audit denials; never imports app.main here."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'export-runtime-inventory.py'
spec = importlib.util.spec_from_file_location('runtime_inventory', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

from fastapi import Depends, FastAPI
from starlette.routing import Mount


async def handler():
    return None


def nested_dependency(secret='DO_NOT_EMIT_DEFAULT'):
    pass


def parent_dependency(value=Depends(nested_dependency)):
    pass


class TreeTests(unittest.TestCase):
    def export(self, app, **kw):
        return m.inventory(app, revision='a' * 40, **kw)

    def bare(self):
        return FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    def test_nested_repeat_factory_dynamic_and_ws(self):
        app, child, leaf = self.bare(), self.bare(), self.bare()
        for name in ['one', 'two']:
            leaf.add_api_route('/' + name, handler)
        leaf.add_api_websocket_route('/socket', handler)
        child.mount('/leaf', leaf)
        app.mount('/first', child)
        app.mount('/second', child)
        data = self.export(app)
        self.assertEqual(data['statistics']['operations'], 6)
        self.assertEqual(data['statistics']['websocketOperations'], 2)
        self.assertEqual({r['path'] for r in data['operations']},
                         {'/first/leaf/one', '/first/leaf/two', '/first/leaf/socket',
                          '/second/leaf/one', '/second/leaf/two', '/second/leaf/socket'})
        self.assertEqual(data, self.export(app))
        self.assertEqual(data['operations'][0]['mountChain'], ['/first', '/first/leaf'])

    def test_recursive_deps_are_names_without_args_or_acl_inference(self):
        app = self.bare()
        app.add_api_route('/internal-name-is-not-proof', handler, dependencies=[Depends(parent_dependency)])
        row = self.export(app)['operations'][0]
        self.assertEqual(row['dependencies'], sorted([m.qualified(parent_dependency), m.qualified(nested_dependency)]))
        self.assertNotIn('DO_NOT_EMIT_DEFAULT', json.dumps(row))
        self.assertIsNone(row['policy'])
        self.assertTrue(row['manualReview'])
        self.assertEqual(row['authAssessment'], 'not_proven_by_dependency_names')

    def test_duplicates_shapes_and_methods_keep_registration_order(self):
        app = self.bare()
        app.add_api_route('/same', handler, methods=['GET'])
        app.add_api_route('/same', handler, methods=['GET', 'POST'])
        app.add_api_route('/item/{one}', handler)
        app.add_api_route('/item/{two}', handler)
        data = self.export(app)
        self.assertEqual(data['duplicates'][0]['operations'], [0, 1])
        self.assertEqual(data['parameterCollisions'][0]['operations'], [3, 4])
        self.assertEqual(data['sharedPaths'][0]['path'], '/same')
        self.assertEqual(data['operations'][1]['order'], [1])

    def test_opaque_cycle_and_unknown_are_reported(self):
        app = self.bare()
        app.mount('/opaque', handler)
        app.mount('/cycle', app)
        class Unknown:
            path = '/unknown'
        app.routes.append(Unknown())
        data = self.export(app)
        self.assertEqual({r['kind'] for r in data['unresolved']},
                         {'opaque_or_empty_mount', 'mount_cycle', 'unknown_route'})

    def test_literal_parameter_overlap_is_candidate_with_mount_prefix(self):
        app, child = self.bare(), self.bare()
        child.add_api_route('/items/{identifier}', handler)
        child.add_api_route('/items/current', handler)
        app.mount('/prefix', child)
        report = self.export(app)
        self.assertEqual(report['literalParameterOverlaps'], [
            {'kind': 'literal_parameter_overlap_candidate', 'operations': [0, 1]}])

    def test_real_policy_binding_only_not_openapi_extra(self):
        sys.path.insert(0, str(m.SERVER))
        from app.api_contracts.routing import PolicyRoute, PolicyRouter, RoutePolicy
        from app.api_contracts.context import PrincipalKind
        child, app = self.bare(), self.bare()
        router = PolicyRouter(context_resolver=handler)
        policy = RoutePolicy(owner='synthetic', accepted_kinds=frozenset({PrincipalKind.PUBLIC}),
            resource_type='test', action='read', required_scopes=frozenset(), policy_version='v1', tenant_required=False)
        router.operation('/curated', policy=policy, methods=['GET'])(handler)
        child.include_router(router)
        app.mount('/api', child)
        app.add_api_route('/pretend', handler, openapi_extra={'x-access-policy': policy.metadata()})
        data = self.export(app, policy_type=PolicyRoute, product_app=child)
        self.assertEqual(data['statistics']['curatedOperations'], 1)
        self.assertEqual(data['operations'][0]['policy'], policy.metadata())
        self.assertIsNone(data['operations'][1]['policy'])

    def test_static_comparison_preserves_unresolved_not_auth_parity(self):
        app = self.bare()
        app.add_api_route('/dynamic', handler)
        report = self.export(app)
        result = m.compare_static(report, {'sources': [{'name': 'Core', 'git': {'head': 'b' * 40},
            'endpoints': [{'method': 'GET', 'path': '/old'}, {'method': 'GET', 'path': None}],
            'unresolved': [{'kind': 'unsupported_asgi_mount'}]}]})
        self.assertEqual(result['runtimeOnly'], [{'method': 'GET', 'path': '/dynamic'}])
        self.assertEqual(result['staticOnly'], [{'method': 'GET', 'path': '/old'}])
        self.assertEqual(result['staticUnresolvedCount'], 1)
        self.assertFalse(result['sourceRevisionMatches'])

    def test_inventory_does_not_execute_endpoint_or_lifespan(self):
        async def forbidden(*args):
            raise AssertionError('MUST_NOT_RUN')
        app = FastAPI(lifespan=forbidden, openapi_url=None)
        app.add_api_route('/x', forbidden)
        self.assertEqual(self.export(app)['statistics']['operations'], 1)


class GuardTests(unittest.TestCase):
    def probe(self, operation):
        code = '''import importlib.util, json, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('inventory',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
guard=m.OfflineGuard();guard.install()
try:
    exec(sys.argv[2])
except m.OfflineViolation:
    print(json.dumps({'denied':guard.denied}))
else:
    raise AssertionError('guard did not deny I/O')
'''
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '.env').write_text('DO_NOT_LEAK=synthetic')
            Path(directory, 'private.key').write_text('DO_NOT_LEAK')
            result = subprocess.run([sys.executable, '-B', '-c', code, str(SCRIPT), operation], cwd=directory,
                                    env=m.synthetic_environment('a' * 40), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('DO_NOT_LEAK', result.stdout)
        return json.loads(result.stdout)['denied']

    def test_real_file_reads_and_writes_denied(self):
        for operation, category in [("Path('.env').read_text()", 'secret_file'),
                                    ("Path('private.key').read_bytes()", 'secret_file'),
                                    ("Path('output.txt').write_text('x')", 'filesystem_write'),
                                    ("Path('/usr/share/zoneinfo/Europe/London').read_bytes()", 'unapproved_file'),
                                    ("Path('/etc/hosts').read_bytes()", 'unapproved_file')]:
            with self.subTest(operation=operation):
                self.assertEqual(self.probe(operation), [category])

    def test_exact_public_timezone_validated_and_readable(self):
        # Probe fails deliberately after the real permitted read; no broad timezone allowlist.
        self.assertEqual(self.probe("assert Path('/usr/share/zoneinfo/Europe/Moscow').read_bytes()[:4]==b'TZif';guard.deny('validated')"), ['validated'])

    def test_exact_mime_resource_has_digest_and_sibling_denied(self):
        self.assertEqual(self.probe("assert Path('/etc/mime.types').read_bytes();assert len(guard.resources[1]['sha256'])==64;guard.deny('validated')"), ['validated'])

    def test_response_class_is_registry_fact_not_streaming_classification(self):
        from starlette.responses import StreamingResponse
        app = FastAPI(openapi_url=None)
        app.add_api_route('/stream', handler, response_class=StreamingResponse, name='declared-stream')
        data = m.inventory(app, revision='a' * 40)
        self.assertEqual(data['operations'][0]['responseClass'], 'starlette.responses.StreamingResponse')
        self.assertEqual(data['operations'][0]['name'], 'declared-stream')
        self.assertEqual(data['operations'][0]['protocol'], 'http')

    def test_real_dns_socket_and_subprocess_denied(self):
        for operation, category in [("import socket;socket.getaddrinfo('example.invalid',443)", 'network'),
                                    ("import socket;socket.socket()", 'network'),
                                    ("import os;os.execv(sys.executable,[sys.executable,'-c','pass'])", 'process'),
                                    ("import subprocess;subprocess.run([sys.executable,'-c','pass'])", 'process')]:
            with self.subTest(operation=operation):
                self.assertEqual(self.probe(operation), [category])

    def test_real_engine_denied_before_dbapi_connect(self):
        self.assertEqual(self.probe("from sqlalchemy import create_engine,event;engine=create_engine('sqlite://');event.listen(engine,'do_connect',guard.sql_connect);engine.connect()"), ['sql_connect'])
        self.assertEqual(self.probe("import sqlite3;sqlite3.connect(':memory:')"), ['sql_connect'])

    def test_failure_trace_omits_exception_text_and_absolute_paths(self):
        guard = m.OfflineGuard()
        try:
            raise RuntimeError('sensitive-path-and-state')
        except RuntimeError as error:
            report = m.safe_failure(error, guard)
        encoded = json.dumps(report)
        self.assertNotIn('sensitive-path-and-state', encoded)
        self.assertNotIn(str(SCRIPT.parent), encoded)
        self.assertEqual(report['status'], 'blocked')


class LauncherTests(unittest.TestCase):
    def test_timeout_and_start_failure_never_serialize_process_args_or_streams(self):
        for error, reason in [(subprocess.TimeoutExpired(['/private/DO_NOT_LEAK'], 120, output='DO_NOT_LEAK', stderr='DO_NOT_LEAK'), 'hermetic_child_timeout'),
                              (OSError('DO_NOT_LEAK'), 'hermetic_child_start_failed')]:
            def fail(*args, **kwargs):
                raise error
            report = m.launch_export('a' * 40, runner=fail)
            self.assertEqual(report['status'], 'blocked')
            self.assertEqual(report['kind'], reason)
            self.assertNotIn('DO_NOT_LEAK', json.dumps(report))

    def test_nonzero_even_with_parseable_success_is_blocked(self):
        def child(*args, **kwargs):
            return subprocess.CompletedProcess(['DO_NOT_LEAK'], 7,
                json.dumps({'kind':'actual-core-runtime-route-inventory', 'secret':'DO_NOT_LEAK'}), 'DO_NOT_LEAK')
        report = m.launch_export('a' * 40, runner=child)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['kind'], 'hermetic_child_nonzero')
        self.assertEqual(report['exitCode'], 7)
        self.assertNotIn('DO_NOT_LEAK', json.dumps(report))

    def test_child_failure_extra_fields_and_private_frame_paths_are_not_forwarded(self):
        payload = {'status': 'blocked', 'kind': 'actual-core-import-failed', 'secret': 'DO_NOT_LEAK',
                   'exceptionText': 'DO_NOT_LEAK', 'frames': [{'file': '/private/DO_NOT_LEAK', 'line': 1}],
                   'deniedCategories': ['secret_file'], 'guardDenials': []}
        report = m.launch_export('a' * 40, runner=lambda *a, **kw: subprocess.CompletedProcess([], 2, json.dumps(payload), 'DO_NOT_LEAK'))
        self.assertEqual(report['status'], 'blocked')
        self.assertNotIn('DO_NOT_LEAK', json.dumps(report))

    def test_malformed_and_wrong_envelope_json_are_blocked_without_raw_streams(self):
        for output in ('not JSON DO_NOT_LEAK', '["DO_NOT_LEAK"]', '{"secret":"DO_NOT_LEAK"}',
                       '{"status":"blocked","kind":"actual-core-import-failed","guardDenials":null}'):
            report = m.launch_export('a' * 40, runner=lambda *a, **kw: subprocess.CompletedProcess([], 0, output, 'DO_NOT_LEAK'))
            self.assertEqual(report['status'], 'blocked')
            self.assertNotIn('DO_NOT_LEAK', json.dumps(report))


@unittest.skipUnless(os.environ.get('RUN_CORE_RUNTIME_INVENTORY_TESTS') == '1', 'Explicit actual Core export opt-in')
class ActualCoreTests(unittest.TestCase):
    def test_hermetic_actual_core_repeat_and_real_static_gaps(self):
        static = Path(os.environ['RUNTIME_INVENTORY_STATIC_JSON']).resolve()
        revision = json.loads(static.read_text())['sources'][0]['git']['head']
        env = {'LANG': 'C.UTF-8', 'DATABASE_URL': 'AMBIENT_MUST_NOT_LEAK', 'SECRET_KEY': 'AMBIENT_MUST_NOT_LEAK',
               'RUNTIME_INVENTORY_CALLER_SENTINEL': 'AMBIENT_MUST_NOT_LEAK'}
        outputs = []
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '.env').write_text('SECRET_KEY=AMBIENT_MUST_NOT_LEAK')
            for _ in range(2):
                result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--source-revision', revision,
                    '--static-json', str(static)], cwd=directory, env=env, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(result.stderr, '')
                outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])
        data = json.loads(outputs[0])
        self.assertEqual(data['kind'], 'actual-core-runtime-route-inventory')
        self.assertEqual(data['statistics']['curatedOperations'], 12)
        self.assertGreater(data['statistics']['websocketOperations'], 0)
        self.assertEqual(data['provenance']['guard']['deniedAttempts'], 0)
        self.assertTrue(data['provenance']['realDatabaseBase'])
        self.assertEqual(data['provenance']['appEnv'], 'dev')
        self.assertFalse(data['provenance']['lifespanExecuted'])
        self.assertFalse(data['provenance']['requestsExecuted'])
        self.assertFalse(data['provenance']['openapiGenerated'])
        comparison = data['staticComparison']
        self.assertTrue(comparison['sourceRevisionMatches'])
        curated = {(r['method'], r['path']) for r in data['operations'] if r['category']=='curated_policy'}
        gaps = {(r['method'], r['path']) for r in comparison['runtimeOnly']}
        self.assertTrue(curated <= gaps)
        for forbidden in ('AMBIENT_MUST_NOT_LEAK', str(SCRIPT.parent), '/home/mag', '/srv/projects'):
            self.assertNotIn(forbidden, outputs[0])


if __name__ == '__main__':
    unittest.main()
