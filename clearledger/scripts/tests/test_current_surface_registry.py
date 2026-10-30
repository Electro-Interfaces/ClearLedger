"""Composer controls use synthetic producer envelopes, not application imports."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('registry_composer', Path(__file__).resolve().parents[1] / 'current-surface-registry.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
PIN = 'a' * 40
DIGEST = hashlib.sha256(b'public source').hexdigest()
PRODUCER = b'pinned producer source'


def consumer_input(record):
    manifest = [{'file': record['file'], 'sha256': DIGEST, 'lines': 1}]
    native, shared = record['category'] == 'native', record['category'] == 'shared'
    return {'manifest': manifest, 'records': [record], 'diagnostics': [],
        'summary': {'sourceRevision': PIN, 'generator': {'file': 'scripts/inventory-api-consumers.mjs', 'sha256': m.sha(PRODUCER)},
            'counts': {'records': 1, 'shared': int(shared), 'direct': int(native), 'streamConstructors': 0,
                'unresolvedWrappers': 0, 'omittedWrappers': 0, 'syntacticDiagnostics': 0,
                'staticTransportPaths': int(record['pathState'] == 'static'),
                'dynamicTransportPaths': int(record['pathState'] == 'dynamic'), 'unknownTransportPaths': 0, 'unknownTransportMethods': 0},
            'source': {'files': 1, 'lines': 1, 'manifestSha256': m.sha((json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode())},
            'limitations': []}}


def consumer_blob(repo, pin, path):
    return PRODUCER if path == 'clearledger/scripts/inventory-api-consumers.mjs' else b'public source'


def inputs():
    files = {'app/example.py': DIGEST}
    source = {'git': {'head': PIN}, 'files': [{'file': p, 'sha256': h} for p, h in files.items()]}
    ep = {'method': 'GET', 'path': '/api/example', 'declaredPath': '/example', 'protocol': 'http',
          'mountChain': ['/api'], 'order': [1, 0], 'endpoint': 'app.example.endpoint',
          'source': {'file': 'app/example.py', 'sha256': DIGEST, 'line': 1, 'status': 'actual_endpoint_source'},
          'operationId': None, 'generatedUniqueId': 'auto_example_get', 'operationIdSource': 'generated_only',
          'policy': None, 'dependencies': [], 'authAssessment': 'unknown', 'category': 'legacy_public_internal_unclassified'}
    report = {'kind': 'actual-core-runtime-route-inventory', 'sourceRevision': PIN, 'operations': [ep],
              'statistics': {'operations': 1, 'curatedOperations': 0},
              'sourceManifest': {'files': files, 'sha256': m.sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())},
              'productRegistrationParity': {'matches': True, 'basis': 'real_PolicyRoute_product_app_identity_method_multiset',
                                            'expectedOperations': 0, 'observedOperations': 0},
              'provenance': {'guard': {'deniedAttempts': 0}, 'realDatabaseBase': True, 'pythonIsolated': True,
                             'ambientEnvironment': 'replaced', 'appEnv': 'dev', 'entrypoint': 'app.main.app',
                             'lifespanExecuted': False, 'requestsExecuted': False, 'openapiGenerated': False,
                             'compositionFlags': {'partner_oauth_enabled': False, 'partner_api_enabled': False, 'partner_docs_enabled': False}}}
    return report, source


class ComposerControls(unittest.TestCase):
    def test_mount_order_and_generated_id_remain_separate(self):
        report, source = inputs()
        row = m.actual_rows(report, source)[0]
        self.assertEqual(row['key']['mountChain'], ['/api'])
        self.assertEqual(row['key']['registrationOrder'], [1, 0])
        self.assertIsNone(row['operationId'])
        self.assertEqual(row['generatedUniqueId'], 'auto_example_get')
        self.assertIsNone(row['domainOwner'])
        self.assertEqual(row['decision'], 'needs-owner-decision')

    def test_revision_and_full_source_drift_rejected(self):
        report, source = inputs()
        report['sourceRevision'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'revision_drift'):
            m.actual_rows(report, source)
        report['sourceRevision'] = PIN
        report['sourceManifest']['files']['app/unexpected.py'] = DIGEST
        with self.assertRaisesRegex(ValueError, 'full_source_manifest_drift'):
            m.actual_rows(report, source)

    def test_endpoint_hash_and_missing_source_rejected(self):
        report, source = inputs()
        report['operations'][0]['source']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source_hash_drift'):
            m.actual_rows(report, source)
        report['operations'][0]['source']['file'] = None
        with self.assertRaisesRegex(ValueError, 'endpoint_source_missing'):
            m.actual_rows(report, source)

    def test_auto_id_forgery_and_duplicate_registration_rejected(self):
        report, source = inputs()
        report['operations'][0]['operationIdSource'] = 'explicit'
        with self.assertRaisesRegex(ValueError, 'operation_id_provenance'):
            m.actual_rows(report, source)
        report['operations'][0]['operationIdSource'] = 'generated_only'
        report['operations'].append(deepcopy(report['operations'][0]))
        report['statistics']['operations'] = 2
        with self.assertRaisesRegex(ValueError, 'duplicate_runtime_identity'):
            m.actual_rows(report, source)

    def test_guard_denial_or_executed_request_cannot_be_actual(self):
        report, source = inputs()
        for field in ['requestsExecuted', 'lifespanExecuted', 'openapiGenerated']:
            changed = deepcopy(report)
            changed['provenance'][field] = True
            with self.assertRaisesRegex(ValueError, 'unaccepted_runtime_provenance'):
                m.actual_rows(changed, source)
        report['provenance']['guard']['deniedAttempts'] = 1
        with self.assertRaisesRegex(ValueError, 'unaccepted_runtime_provenance'):
            m.actual_rows(report, source)

    def test_native_authority_unknown_and_dynamic_path_never_guessed(self):
        report, source = inputs()
        rows = m.actual_rows(report, source)
        base = {'file': 'src/services/example.ts', 'line': 1, 'column': 1, 'category': 'native',
                'transport': 'fetch', 'method': 'GET', 'pathname': '/api/example', 'pathState': 'static',
                'sourceSha256': DIGEST, 'expressionSha256': DIGEST}
        data = consumer_input(base)
        with patch.object(m, 'blob', side_effect=consumer_blob):
            result = m.consumer_map(data, rows, Path('/unused'), PIN)
            self.assertEqual(result['records'][0]['surfaceRefs'], [])
            base['category'] = 'shared'
            data = consumer_input(base)
            self.assertEqual(len(m.consumer_map(data, rows, Path('/unused'), PIN)['records'][0]['surfaceRefs']), 1)
            base.update(pathState='dynamic', pathname='/api/{dynamic}')
            data = consumer_input(base)
            self.assertEqual(m.consumer_map(data, rows, Path('/unused'), PIN)['records'][0]['surfaceRefs'], [])
            base['sourceSha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'record_source_drift'):
                m.consumer_map(data, rows, Path('/unused'), PIN)

    def test_consumer_producer_manifest_and_summary_drift_rejected(self):
        report, source = inputs()
        rows = m.actual_rows(report, source)
        record = {'file': 'src/services/example.ts', 'line': 1, 'column': 1, 'category': 'shared',
                  'transport': 'get', 'method': 'GET', 'pathname': '/api/example', 'pathState': 'static',
                  'sourceSha256': DIGEST, 'expressionSha256': DIGEST}
        data = consumer_input(record)
        mutations = [
            ('consumer_producer_drift', lambda d: d['summary']['generator'].update(file='unreviewed.mjs')),
            ('consumer_producer_drift', lambda d: d['summary']['generator'].update(sha256='0' * 64)),
            ('consumer_manifest_summary_drift', lambda d: d['manifest'][0].update(lines=2)),
            ('consumer_manifest_summary_drift', lambda d: d['summary']['source'].update(manifestSha256='0' * 64)),
            ('consumer_record_summary_drift', lambda d: d['summary']['counts'].update(records=0)),
        ]
        with patch.object(m, 'blob', side_effect=consumer_blob):
            for reason, mutate in mutations:
                changed = deepcopy(data)
                mutate(changed)
                with self.assertRaisesRegex(ValueError, reason):
                    m.consumer_map(changed, rows, Path('/unused'), PIN)


if __name__ == '__main__':
    unittest.main()
