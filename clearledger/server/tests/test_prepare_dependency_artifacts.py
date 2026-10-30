"""Чистые проверки недоверенных архивов/metadata, без conftest, сети и приложения.

Запуск: python -B -m unittest discover -s clearledger/server/tests
        -p test_prepare_dependency_artifacts.py -v
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools/prepare_dependency_artifacts.py'
SPEC = importlib.util.spec_from_file_location('dependency_artifact_preparation', MODULE_PATH)
dep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dep)
SCRATCH = Path(__file__).resolve().parents[3] / '.artifacts/dependency-artifacts'


class PreparationTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-', dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Любая попытка реального HTTP в тестах — ошибка теста.
        guard = mock.patch.object(dep.urllib.request.OpenerDirector, 'open',
                                  side_effect=AssertionError('network forbidden in pure tests'))
        guard.start()
        self.addCleanup(guard.stop)

    def wheel(self, name='demo-pkg', version='1.0', extra_members=(), metadata=None,
              wheel_header=None, filename=None):
        stem = name.replace('-', '_')
        tag = 'cp313-cp313-manylinux_2_17_x86_64'
        filename = filename or f'{stem}-{version}-{tag}.whl'
        directory = f'{stem}-{version}.dist-info'
        path = self.root / filename
        metadata = metadata if metadata is not None else (
            f'Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n'
            'Requires-Python: >=3.9\nRequires-Dist: helper>=1; python_version >= "3.10"\n\n').encode()
        wheel_header = wheel_header or f'Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {tag}\n\n'.encode()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                z.writestr(directory + '/METADATA', metadata)
                z.writestr(directory + '/WHEEL', wheel_header)
                for member, data in extra_members:
                    z.writestr(member, data)
        return path

    def sdist(self, members=(), setup=None, project=None):
        path = self.root / 'http_ece-1.2.1.tar.gz'
        entries = [('http_ece-1.2.1/PKG-INFO',
                    b'Metadata-Version: 2.1\nName: http-ece\nVersion: 1.2.1\n\n')]
        if setup is not None:
            entries.append(('http_ece-1.2.1/setup.py', setup))
        if project is not None:
            entries.append(('http_ece-1.2.1/pyproject.toml', project))
        entries.extend(members)
        with tarfile.open(path, 'w:gz') as tar:
            for member, data in entries:
                if isinstance(member, str):
                    member = tarfile.TarInfo(member)
                    member.size = len(data)
                tar.addfile(member, io.BytesIO(data) if member.isfile() else None)
        return path

    def record(self, path, kind='bdist_wheel'):
        return {'filename': path.name, 'url': 'https://files.pythonhosted.org/packages/test/' + path.name,
                'size': path.stat().st_size, 'sha256': dep.digest(path.read_bytes()),
                'packagetype': kind, 'requires_python': '>=3.9'}

    def release(self, record, name='demo-pkg', version='1.0'):
        return {'info': {'name': name, 'version': version},
                'urls': [dict(record, digests={'sha256': record['sha256']}, yanked=False)]}

    def test_https_allowlist_rejects_credentials_ports_query_and_redirects(self):
        for url in ('http://pypi.org/pypi/pip/26.2.2/json',
                    'https://user:password@pypi.org/path', 'https://pypi.org:443/path',
                    'https://pypi.org.evil.invalid/path', 'https://pypi.org/path?q=1',
                    'https://pypi.org/path#fragment', 'file:///etc/passwd'):
            with self.subTest(url=url), self.assertRaises(dep.Rejected):
                dep.check_url(url, 'pypi.org')
        request = dep.urllib.request.Request('https://pypi.org/pypi/pip/26.2.2/json')
        with self.assertRaises(dep.Rejected):
            dep.SafeRedirect().redirect_request(request, None, 302, '', {}, 'https://evil.invalid/a')

    def test_release_identity_duplicate_names_and_advertised_limits(self):
        record = self.record(self.wheel())
        release = self.release(record)
        self.assertEqual(dep.select_artifact(release, 'demo-pkg', '1.0')[0], record)
        mutations = []
        bad = copy.deepcopy(release); bad['info']['version'] = '1.1'; mutations.append(bad)
        bad = copy.deepcopy(release); bad['info']['name'] = 'other'; mutations.append(bad)
        bad = copy.deepcopy(release); bad['urls'] *= 2; mutations.append(bad)
        bad = copy.deepcopy(release); bad['urls'][0]['size'] = dep.MAX_FILE + 1; mutations.append(bad)
        bad = copy.deepcopy(release); bad['urls'][0]['digests']['sha256'] = 'x' * 64; mutations.append(bad)
        bad = copy.deepcopy(release); bad['urls'][0]['url'] += '?token=secret'; mutations.append(bad)
        for bad in mutations:
            with self.subTest(bad=bad), self.assertRaises(dep.Rejected):
                dep.select_artifact(bad, 'demo-pkg', '1.0')

    def test_duplicate_json_keys_and_metadata_cap(self):
        with self.assertRaises(dep.Rejected):
            dep.parse_json(b'{"version": "1", "version": "2"}')
        with self.assertRaises(dep.Rejected):
            dep.parse_json(b' ' * (dep.MAX_METADATA + 1))

    def test_path_traversal_absolute_windows_and_symlink_are_rejected(self):
        for name in ('../escape', '/absolute', 'C:/escape', 'a\\b', 'a/../../b', 'a//b', './x'):
            with self.subTest(name=name), self.assertRaises(dep.Rejected):
                dep.safe_member(name)
        outside = self.root / 'outside'
        outside.write_text('data')
        (self.root / 'link').symlink_to(outside)
        with self.assertRaises(dep.Rejected):
            dep.local_file(self.root, 'link')

    def test_exact_cp313_and_abi3_and_universal_tags(self):
        self.assertIsNotNone(dep.tag_score('cp313-cp313-manylinux_2_17_x86_64'))
        self.assertIsNotNone(dep.tag_score('cp311-abi3-manylinux_2_34_x86_64'))
        self.assertIsNotNone(dep.tag_score('py3-none-any'))
        for tag in ('cp313-cp313t-manylinux_2_17_x86_64', 'cp314-abi3-manylinux_2_17_x86_64',
                    'cp313-cp313-manylinux_2_42_x86_64', 'cp313-cp313-manylinux_2_17_aarch64',
                    'cp313-cp313-musllinux_1_2_x86_64', 'cp312-cp312-manylinux_2_17_x86_64',
                    'cp313-cp313-linux_x86_64'):
            with self.subTest(tag=tag):
                self.assertIsNone(dep.tag_score(tag))

    def test_supported_markers_grouping_and_numeric_python(self):
        expression = '(sys_platform != "win32" and python_version >= "3.10") and extra == "standard"'
        self.assertTrue(dep.Marker(expression).evaluate(dict(dep.MARKER_ENV, extra='standard')))
        self.assertFalse(dep.Marker(expression).evaluate(dep.MARKER_ENV))
        self.assertTrue(dep.Marker('python_version < "3.9" or os_name == "posix"').evaluate(dep.MARKER_ENV))
        self.assertTrue(dep.satisfies('3.13.18', '!=3.9.0,!=3.9.1,>=3.9'))
        self.assertFalse(dep.satisfies('3.13.18', '<3.13'))
        self.assertTrue(dep.satisfies('1.7.4', '~=1.7,!=1.8.*'))

    def test_unsupported_marker_url_and_version_semantics_fail_closed(self):
        for raw in ('dep; unknown_variable == "x"', 'dep; extra === "dev"',
                    'dep @ https://example.invalid/a.whl', 'dep; __import__("os")',
                    'dep; python_version == "3.13" trailing'):
            with self.subTest(raw=raw), self.assertRaises(dep.Rejected):
                dep.requirement(raw)
        with self.assertRaises(dep.Rejected):
            dep.Marker('platform_release == "x"').evaluate(dep.MARKER_ENV)
        with self.assertRaises(dep.Rejected):
            dep.satisfies('3.13.18', '>=3.14rc1')

    def test_wheel_inspection_does_not_execute_package_code(self):
        path = self.wheel(extra_members=[('demo_pkg/__init__.py', b'raise RuntimeError("must not import")')])
        result = dep.inspect_wheel(path, 'demo-pkg', '1.0')
        self.assertEqual(result['name'], 'demo-pkg')
        self.assertEqual(len(result['requires_dist']), 1)

    def test_wheel_rejects_paths_duplicates_links_and_metadata_identity(self):
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for members in ([('../escape', b'x')], [('demo_pkg-1.0.dist-info/METADATA', b'duplicate')],
                        [(link, b'/outside')]):
            with self.subTest(members=members):
                path = self.wheel(extra_members=members)
                with self.assertRaises(dep.Rejected):
                    dep.inspect_wheel(path, 'demo-pkg', '1.0')
        for metadata in (b'Metadata-Version: 2.4\nName: wrong\nVersion: 1.0\n\n',
                         b'Metadata-Version: 2.4\nName: demo-pkg\nName: demo-pkg\nVersion: 1.0\n\n',
                         b'Metadata-Version: 2.4\nName: demo-pkg\nVersion: 1.0\nRequires-Python: >=3.14\n\n',
                         b'Metadata-Version: 2.4\nName: demo-pkg\nVersion: 1.0\nRequires-Dist: dep; unknown == "x"\n\n'):
            path = self.wheel(metadata=metadata)
            with self.subTest(metadata=metadata), self.assertRaises(dep.Rejected):
                dep.inspect_wheel(path, 'demo-pkg', '1.0')

    def test_wheel_tag_mismatch_and_metadata_size_and_directory_limit(self):
        path = self.wheel(wheel_header=b'Wheel-Version: 1.0\nTag: py3-none-any\n\n')
        with self.assertRaises(dep.Rejected):
            dep.inspect_wheel(path, 'demo-pkg', '1.0')
        path = self.wheel(metadata=b'x' * (dep.MAX_METADATA + 1))
        with self.assertRaises(dep.Rejected):
            dep.inspect_wheel(path, 'demo-pkg', '1.0')
        path = self.wheel()
        data = bytearray(path.read_bytes())
        offset = data.rfind(b'PK\x05\x06')
        data[offset+12:offset+16] = struct.pack('<L', dep.MAX_METADATA + 1)
        path.write_bytes(data)
        with self.assertRaises(dep.Rejected):
            dep.inspect_wheel(path, 'demo-pkg', '1.0')

    def test_artifact_digest_size_and_name_mismatch(self):
        path = self.wheel()
        record = self.record(path)
        (self.root / 'files').mkdir()
        path.rename(self.root / 'files' / path.name)
        self.assertEqual(dep.inspect_artifact(self.root, record, 'demo-pkg', '1.0')['kind'], 'wheel')
        for changes in ({'size': record['size'] + 1}, {'sha256': '0' * 64}):
            with self.subTest(changes=changes), self.assertRaises(dep.Rejected):
                dep.inspect_artifact(self.root, dict(record, **changes), 'demo-pkg', '1.0')
        with self.assertRaises(dep.Rejected):
            dep.inspect_artifact(self.root, record, 'wrong-name', '1.0')

    def test_source_only_preserved_and_cannot_be_promoted_to_wheel_lock(self):
        setup = b'raise RuntimeError("must not execute")\nsetup(install_requires=["cryptography>=2.5"])\n'
        path = self.sdist(setup=setup)
        inspection = dep.inspect_sdist(path, 'http-ece', '1.2.1')
        self.assertFalse(inspection['build_system']['hooks_executed'])
        self.assertEqual(inspection['build_system']['setup_literals']['install_requires'], ['cryptography>=2.5'])
        self.assertEqual(inspection['build_system']['requires'], ['setuptools>=40.8.0'])
        with self.assertRaises(dep.Rejected):
            dep.require_wheels([{'roles': ['runtime'], 'inspection': inspection}])
        source = self.record(path, 'sdist')
        self.assertEqual(dep.select_artifact(self.release(source, 'http-ece', '1.2.1'),
                                             'http-ece', '1.2.1')[1], [])
        with self.assertRaises(dep.Rejected):
            dep.select_artifact(self.release(source), 'demo-pkg', '1.0')

    def test_sdist_rejects_traversal_links_duplicate_and_dynamic_setup(self):
        link = tarfile.TarInfo('http_ece-1.2.1/link')
        link.type = tarfile.SYMTYPE
        link.linkname = '/outside'
        for members in ([('../escape', b'x')], [(link, b'')],
                        [('http_ece-1.2.1/PKG-INFO', b'duplicate')]):
            with self.subTest(members=members):
                path = self.sdist(members=members)
                with self.assertRaises(dep.Rejected):
                    dep.inspect_sdist(path, 'http-ece', '1.2.1')
        path = self.sdist(setup=b'setup(setup_requires=discover_dependencies())\n')
        with self.assertRaises(dep.Rejected):
            dep.inspect_sdist(path, 'http-ece', '1.2.1')
        path = self.sdist(project=b'[build-system]\nrequires=["setuptools>=40.8"]\nbuild-backend="local"\nbackend-path=["."]\n')
        with self.assertRaises(dep.Rejected):
            dep.inspect_sdist(path, 'http-ece', '1.2.1')

    def test_tooling_plan_rejects_missing_or_incompatible_dependency(self):
        rows = [{'name': n, 'version': v, 'inspection': {'requires_dist': []}}
                for n, v in dep.TOOLING.items()]
        rows[0]['inspection']['requires_dist'] = ['missing-helper>=1']
        with self.assertRaises(dep.Rejected):
            dep.tooling_declarations(rows)
        rows[0]['inspection']['requires_dist'] = ['click>=999']
        with self.assertRaises(dep.Rejected):
            dep.tooling_declarations(rows)

    def verifier_fixture(self):
        name, version = 'pip', '26.2.2'
        path = self.wheel(name=name, version=version,
                          metadata=f'Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nRequires-Python: >=3.9\n\n'.encode())
        record = self.record(path)
        (self.root / 'files').mkdir()
        path.rename(self.root / 'files' / path.name)
        (self.root / 'metadata').mkdir()
        raw = json.dumps(self.release(record, name, version)).encode()
        meta = {'path': f'metadata/{name}-{version}.json', 'url': dep.release_url(name, version),
                'sha256': dep.digest(raw), 'size': len(raw)}
        (self.root / meta['path']).write_bytes(raw)
        entry = {'name': name, 'version': version, 'roles': ['bootstrap', 'tooling'],
                 'release_metadata': meta, 'artifact': record,
                 'inspection': dep.inspect_artifact(self.root, record, name, version)}
        events = [{'file': meta['path'], 'url': meta['url'], 'bytes': meta['size'],
                   'sha256': meta['sha256'], 'status': 'downloaded'},
                  {'file': 'files/' + record['filename'], 'url': record['url'], 'bytes': record['size'],
                   'sha256': record['sha256'], 'status': 'downloaded'}]
        log = b''.join((json.dumps(e) + '\n').encode() for e in events)
        (self.root / 'download-events.jsonl').write_bytes(log)
        manifest = {'schema_version': 1, 'kind': 'dependency-artifact-preparation-not-lock',
                    'source': {}, 'target': dep.TARGET, 'artifacts': [entry],
                    'tooling_plan': {'pins': {name: version}, 'active_metadata_edges': [],
                      'status': 'numeric-declarations-only-no-resolver-or-runtime-compatibility-pass',
                      'activation': 'separate-clean-target-tooling-environment-required'},
                    'blockers': [], 'evidence': {'download_log': {'path': 'download-events.jsonl',
                       'size': len(log), 'sha256': dep.digest(log)}, 'requests': 2,
                       'downloaded_files_and_metadata_bytes': sum(e['bytes'] for e in events) + len(log)},
                    'limits': {'total_bytes': dep.MAX_TOTAL, 'metadata_bytes_per_archive': dep.MAX_METADATA,
                               'log_bytes': dep.MAX_LOG, 'deadline_seconds': 900},
                    'not_run': ['resolver', 'build-backend', 'wheel-build', 'target-runtime',
                                'offline-install', 'pip-check', 'image-build', 'security-audit', 'exact-rebuild']}
        args = argparse.Namespace(manifest=self.root / 'manifest.json', root=self.root,
                                  receipt=None, requirements=None, baseline=None, require_wheels=False)
        return manifest, args

    def test_offline_verifier_is_readonly_and_detects_manifest_duplicates_or_drift(self):
        manifest, args = self.verifier_fixture()
        def run(value):
            args.manifest.write_text(json.dumps(value))
            before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                      for p in self.root.rglob('*') if p.is_file()}
            with mock.patch.object(dep, 'source_inputs', return_value=({'pip': '26.2.2'}, {})), \
                 mock.patch.object(dep, 'TOOLING', {'pip': '26.2.2'}), \
                 contextlib.redirect_stdout(io.StringIO()):
                dep.verify(args)
            after = {p.relative_to(self.root).as_posix(): p.read_bytes()
                     for p in self.root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
        run(manifest)
        mutations = []
        bad = copy.deepcopy(manifest); bad['artifacts'] *= 2; mutations.append(bad)
        bad = copy.deepcopy(manifest); bad['artifacts'][0]['version'] = '0.0'; mutations.append(bad)
        bad = copy.deepcopy(manifest); bad['artifacts'][0]['artifact']['sha256'] = '0' * 64; mutations.append(bad)
        bad = copy.deepcopy(manifest); bad['evidence']['requests'] = 1; mutations.append(bad)
        bad = copy.deepcopy(manifest); bad['target'] = dict(dep.TARGET, abi='cp313t'); mutations.append(bad)
        bad = copy.deepcopy(manifest); bad['not_run'].remove('resolver'); mutations.append(bad)
        for index, bad in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(dep.Rejected):
                run(bad)

    def test_fetch_refuses_existing_directory_and_unbounded_request(self):
        with self.assertRaises(dep.Rejected):
            dep.Fetcher(self.root)
        artifact_root = self.root / '.artifacts/dependency-artifacts'
        with self.assertRaises(dep.Rejected):
            dep.Fetcher(artifact_root, deadline_seconds=901)
        fetcher = dep.Fetcher(artifact_root)
        with self.assertRaises(dep.Rejected):
            fetcher.download('https://files.pythonhosted.org/packages/a.whl', 'files/a.whl',
                             dep.MAX_FILE, expected_size=dep.MAX_TOTAL + 1)

    def test_bounded_transport_rejects_digest_and_preserves_failure_evidence(self):
        fetcher = dep.Fetcher(self.root / '.artifacts/dependency-artifacts')
        class Response(io.BytesIO):
            url = 'https://files.pythonhosted.org/packages/a.whl'
            status = 200
            headers = {'Content-Length': '3'}
        fetcher.opener = mock.Mock()
        fetcher.opener.open.return_value = Response(b'abc')
        with self.assertRaises(dep.Rejected):
            fetcher.download(Response.url, 'files/a.whl', 10, 3, '0' * 64)
        self.assertFalse((fetcher.root / 'files/a.whl').exists())
        self.assertEqual((fetcher.root / 'files/a.whl.part').read_bytes(), b'abc')
        event = json.loads(fetcher.log.read_text())
        self.assertEqual(event['status'], 'failed')
        self.assertNotIn('error', event)
        with self.assertRaises(dep.Rejected):
            fetcher.download(Response.url, 'files/a.whl', 10, 3, dep.digest(b'abc'))

    def test_unannounced_http_body_is_bounded_without_network(self):
        fetcher = dep.Fetcher(self.root / '.artifacts/dependency-artifacts')
        class Response(io.BytesIO):
            url = 'https://files.pythonhosted.org/packages/a.whl'
            status = 200
            headers = {}
        fetcher.opener = mock.Mock()
        fetcher.opener.open.return_value = Response(b'abcdef')
        with self.assertRaises(dep.Rejected):
            fetcher.download(Response.url, 'files/a.whl', 4)
        self.assertLessEqual((fetcher.root / 'files/a.whl.part').stat().st_size, 4)
        self.assertEqual(json.loads(fetcher.log.read_text())['status'], 'failed')

    def test_frozen_source_and_baseline_duplicate_mismatch(self):
        server = MODULE_PATH.parents[1]
        requirements = self.root / 'requirements.in'
        requirements.write_bytes((server / 'requirements.in').read_bytes())
        baseline_data = (server / 'locks/runtime-baseline.constraints.txt').read_bytes()
        baseline = self.root / 'baseline.txt'
        baseline.write_bytes(baseline_data)
        rows = [line.split('==') for line in baseline_data.decode().splitlines()
                if line and not line.startswith('#')]
        rows.append(['pip', '26.2.2'])
        receipt = self.root / 'receipt.json'
        def write_receipt(dependencies):
            raw = json.dumps({'sourceCommit': dep.SOURCE_COMMIT,
                              'probe': {'python': '3.13.18', 'dependencies': dependencies}}).encode()
            receipt.write_bytes(raw)
            return dep.digest(raw)
        sha = write_receipt(rows)
        with mock.patch.object(dep, 'RECEIPT_SHA256', sha):
            self.assertEqual(len(dep.source_inputs(receipt, requirements, baseline)[0]), 60)
            baseline.write_bytes(baseline_data + b'pip==26.2.2\n')
            with self.assertRaises(dep.Rejected):
                dep.source_inputs(receipt, requirements, baseline)
            baseline.write_bytes(baseline_data + b'fastapi==0.115.6\n')
            with self.assertRaises(dep.Rejected):
                dep.source_inputs(receipt, requirements, baseline)
            baseline.write_bytes(baseline_data.replace(b'fastapi==0.115.6', b'fastapi==999.0'))
            with self.assertRaises(dep.Rejected):
                dep.source_inputs(receipt, requirements, baseline)
        baseline.write_bytes(baseline_data)
        sha = write_receipt(rows + [rows[0]])
        with mock.patch.object(dep, 'RECEIPT_SHA256', sha), self.assertRaises(dep.Rejected):
            dep.source_inputs(receipt, requirements, baseline)


if __name__ == '__main__':
    unittest.main()
