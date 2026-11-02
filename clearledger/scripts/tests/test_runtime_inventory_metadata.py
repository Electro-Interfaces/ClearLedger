"""Current metadata/composition controls; original inventory guard controls remain intact."""
import importlib.util
from copy import deepcopy
from pathlib import Path
import sys
import unittest

from fastapi import FastAPI

SCRIPT = Path(__file__).resolve().parents[1] / 'export-runtime-inventory.py'
SPEC = importlib.util.spec_from_file_location('current_inventory', SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
sys.path.insert(0, str(m.SERVER))
from app.api_contracts.routing import PolicyRoute, PolicyRouter, RoutePolicy
from app.api_contracts.context import PrincipalKind


async def never_execute(*args, **kwargs):
    raise AssertionError('endpoint_executed')


def product():
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    router = PolicyRouter(context_resolver=never_execute)
    policy = RoutePolicy(owner='synthetic', accepted_kinds={PrincipalKind.PUBLIC},
        resource_type='test', action='read', required_scopes=set(), policy_version='v1', tenant_required=False)
    router.operation('/first', policy=policy, methods=['GET'], operation_id='explicitFirst')(never_execute)
    router.operation('/second', policy=policy, methods=['GET', 'POST'])(never_execute)
    app.include_router(router)
    return app


class MetadataControls(unittest.TestCase):
    def export(self, app, child):
        return m.inventory(app, revision='a' * 40, policy_type=PolicyRoute, product_app=child)

    def test_variable_policy_count_and_explicit_vs_generated_id(self):
        child, app = product(), FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        app.mount('/v1', child)
        report = self.export(app, child)
        self.assertEqual(report['statistics']['curatedOperations'], 3)
        self.assertTrue(report['productRegistrationParity']['matches'])
        explicit, generated = report['operations'][0], report['operations'][1]
        self.assertEqual(explicit['operationId'], 'explicitFirst')
        self.assertEqual(explicit['operationIdSource'], 'explicit')
        self.assertIsNone(generated['operationId'])
        self.assertTrue(generated['generatedUniqueId'])
        self.assertEqual(generated['operationIdSource'], 'generated_only')

    def test_missing_product_identity_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity_method_parity'):
            self.export(FastAPI(), product())

    def test_extra_product_identity_registration_rejected(self):
        child, app = product(), FastAPI()
        app.mount('/first', child)
        app.mount('/again', child)
        with self.assertRaisesRegex(ValueError, 'identity_method_parity'):
            self.export(app, child)

    def test_non_policy_product_route_cannot_forge_metadata(self):
        child, app = product(), FastAPI()
        child.add_api_route('/forged', never_execute, openapi_extra={'x-access-policy': {'owner': 'forged'}})
        app.mount('/v1', child)
        with self.assertRaisesRegex(ValueError, 'without_real_policy'):
            self.export(app, child)

    def test_endpoint_source_outside_core_is_explicit_unknown(self):
        cache = {}
        result = m.source_metadata(never_execute, cache)
        self.assertEqual(result['status'], 'outside_core_source')
        self.assertIsNone(result['file'])
        self.assertNotIn(str(Path(__file__).parent), str(result))

    def multi_method_report(self):
        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        app.add_api_route('/items/{item}', never_execute, methods=['GET', 'POST'])
        return m.inventory(app, revision='a' * 40)

    def test_generated_id_approved_suffix_variation_keeps_raw_observations(self):
        before = self.multi_method_report()
        after = deepcopy(before)
        values = m.approved_id_values(before['operations'][0])
        self.assertEqual(len(values), 2)
        for row in before['operations']:
            row['generatedUniqueId'] = values[0]
        for row in after['operations']:
            row['generatedUniqueId'] = values[1]
        result = m.compare_runtime_reports(before, after)
        self.assertTrue(result['equivalent'])
        self.assertTrue(result['allOtherFieldsExact'])
        self.assertFalse(result['rawIdentical'])
        self.assertEqual(len(result['operations']['allowedGeneratedIdVariations']), 2)
        self.assertEqual(before['operations'][0]['generatedUniqueId'], values[0])
        self.assertEqual(after['operations'][0]['generatedUniqueId'], values[1])

    def test_generated_id_rejects_unapproved_variation_and_any_other_drift(self):
        before = self.multi_method_report()
        values = m.approved_id_values(before['operations'][0])
        for row in before['operations']:
            row['generatedUniqueId'] = values[0]
        changes = [
            lambda r: r.update(generatedUniqueId='wrong_prefix_get'),
            lambda r: r.update(generatedUniqueId=values[0].rsplit('_', 1)[0] + '_delete'),
            lambda r: r['generatedUniqueIdBasis'].update(sourceSha256='0' * 64),
            lambda r: r['generatedUniqueIdBasis'].update(generator='custom.generator'),
            lambda r: r.update(operationId='explicit', operationIdSource='explicit'),
            lambda r: r.update(registeredMethods=['GET']),
            lambda r: r.update(method='PUT'),
            lambda r: r.update(order=[99]),
            lambda r: r.update(path='/different'),
            lambda r: r.update(source={'file': 'wrong.py'}),
            lambda r: r.update(policy={'owner': 'changed'}),
        ]
        for mutate in changes:
            after = deepcopy(before)
            for row in after['operations']:
                row['generatedUniqueId'] = values[1]
                mutate(row)
            self.assertFalse(m.compare_runtime_reports(before, after)['equivalent'])
        after = deepcopy(before)
        after['operations'][0]['generatedUniqueId'] = values[1]
        self.assertFalse(m.compare_runtime_reports(before, after)['equivalent'])
        for basis in [None, {**before['operations'][0]['generatedUniqueIdBasis'], 'forged': True}]:
            after = deepcopy(before)
            for row in after['operations']:
                row['generatedUniqueIdBasis'] = basis
                row['generatedUniqueId'] = values[1]
            self.assertFalse(m.compare_runtime_reports(before, after)['equivalent'])
        for kind in ['explicit', 'single_method', 'custom_generator']:
            strict = deepcopy(before)
            if kind == 'single_method':
                strict['operations'] = strict['operations'][:1]
            for row in strict['operations']:
                row['generatedUniqueIdBasis'] = None
                if kind == 'explicit':
                    row.update(operationId='fixed', operationIdSource='explicit', generatedUniqueId='fixed')
                elif kind == 'single_method':
                    row.update(registeredMethods=['GET'], generatedUniqueId=values[0])
                else:
                    row['generatedUniqueId'] = 'custom-observed-id'
            self.assertTrue(m.compare_runtime_reports(strict, deepcopy(strict))['equivalent'])
            changed = deepcopy(strict)
            for row in changed['operations']:
                row['generatedUniqueId'] = 'changed-unapproved-id'
            self.assertFalse(m.compare_runtime_reports(strict, changed)['equivalent'])
        after = deepcopy(before)
        after['provenance']['requestsExecuted'] = True
        self.assertFalse(m.compare_runtime_reports(before, after)['equivalent'])


if __name__ == '__main__':
    unittest.main()
