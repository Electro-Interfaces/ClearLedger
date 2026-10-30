#!/usr/bin/env python3
"""Bounded composer of existing inventories; Git/AST only unless ROOT supplies an actual receipt.

Does not import applications, start servers, send requests, discover credentials or
invent routes. Reuses the pinned Deploy scanner and the existing Core/consumer
exports. Dated output is deliberately separate from historical canonical reports.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
import types

PINS = {'Core': '264ad50bec46e73f2bb42a2f9c27969ed909314f',
        'Support': 'a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df',
        'Auditor': '6e1d33cceca5d12c5615a301dfc8c16c89fcc92f'}
MAX_BYTES, MAX_FILES, MAX_ROWS = 16 * 1024 * 1024, 10000, 10000
ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = 'clearledger/docs/api/CORE_PROTOCOL_PASSPORTS_20261030.json'
AUTHORITIES = {'Core': 'core-service-local', 'Support': 'support-service-local', 'Auditor': 'auditor-service-local'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=30, check=True)
    require(len(result.stdout) <= 128 * 1024 * 1024, 'git_output_limit')
    return result.stdout


def blob(repo, revision, path):
    value = git(repo, 'show', f'{revision}:{path}')
    require(len(value) <= MAX_BYTES, 'blob_limit')
    return value


def load_json(path, *, receipt=False):
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, 'input_byte_limit')
    value = json.loads(raw)
    return (value, {'sha256': sha(raw), 'bytes': len(raw)}) if receipt else value


def revision(value):
    require(bool(re.fullmatch('[a-f0-9]{40}', value)), 'immutable_revision_required')
    return value


def frozen_files(repo, pin, prefix, scanner):
    """Use only tracked immutable blobs, never another owner's working tree changes."""
    tree = git(repo, 'ls-tree', '-rlz', pin, '--', *([prefix] if prefix else [])).split(b'\0')
    selected, omitted = [], []
    for entry in filter(None, tree):
        header, raw_path = entry.split(b'\t', 1)
        mode, kind, oid, raw_size = header.split()
        path = raw_path.decode('utf-8')
        relative = PurePosixPath(path).relative_to(prefix) if prefix else PurePosixPath(path)
        require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe_git_path')
        if (any(p in scanner.SKIP or p.startswith('.') for p in relative.parts[:-1])
                or relative.name.startswith(('.', 'test_', 'test-', 'check-'))
                or re.search(r'\.(test|spec|check)\.', relative.name)
                or relative.suffix not in scanner.SUFFIXES):
            continue
        if mode != b'100644' and mode != b'100755':
            omitted.append({'file': str(relative), 'reason': 'non_regular_git_entry'})
            continue
        require(kind == b'blob', 'non_blob_source')
        selected.append((str(relative), oid.decode(), int(raw_size)))
    require(len(selected) <= MAX_FILES and sum(s[2] for s in selected) <= 64 * 1024 * 1024, 'source_limit')
    raw = b'' if not selected else subprocess.run(
        ['git', '-C', str(repo), 'cat-file', '--batch'], input=''.join(f'{oid}\n' for _, oid, _ in selected).encode(),
        capture_output=True, check=True, timeout=30).stdout
    position, files = 0, {}
    for path, oid, size in selected:
        end = raw.index(b'\n', position)
        require(raw[position:end] == f'{oid} blob {size}'.encode(), 'git_blob_header_mismatch')
        value = raw[end + 1:end + 1 + size]
        require(len(value) == size and raw[end + 1 + size:end + 2 + size] == b'\n', 'git_blob_size_mismatch')
        require(hashlib.sha1(f'blob {size}\0'.encode() + value).hexdigest() == oid, 'git_blob_digest_mismatch')
        files[path] = value
        position = end + 2 + size
    require(position == len(raw), 'git_batch_trailing_bytes')
    return files, omitted


def scanner_module(deploy, pin):
    path = 'scripts/api_inventory.py'
    raw = blob(deploy, pin, path)
    module = types.ModuleType('pinned_api_inventory')
    module.__file__ = str(deploy / path)
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module, {'file': path, 'sourceRevision': pin, 'sha256': sha(raw)}


def static_source(scanner, name, repo, pin, prefix):
    files, omitted = frozen_files(repo, pin, prefix, scanner)
    with tempfile.TemporaryDirectory(prefix='current-api-static-') as directory:
        target = Path(directory)
        for file, raw in files.items():
            path = target / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        result = scanner.Inventory(name, target).scan()
    result.pop('root')
    result['git'] = {'head': pin, 'origin': 'immutable_git_blobs', 'workingTreeUsed': False}
    result['pythonAstVersion'] = sys.version.split()[0]
    result['excludedGitEntries'] = omitted
    require(result['statistics']['endpoints'] <= MAX_ROWS, 'static_row_limit')
    require({f['file']: f['sha256'] for f in result['files']} == {p: sha(v) for p, v in files.items()},
            'scanner_manifest_mismatch')
    return result, files


def source_ref(file, line, hashes, status='static_source'):
    return {'file': file, 'line': line, 'sha256': hashes.get(file), 'status': status}


def base_row(name, app, method, path, protocol, state, mount, order, source, endpoint, index):
    key = {'service': name, 'authority': AUTHORITIES[name], 'app': app, 'method': method,
           'path': path, 'protocol': protocol, 'mountChain': mount, 'registrationOrder': order,
           'sourceOrdinal': index if order is None else None}
    return {'key': key, 'keySha256': sha(canonical(key).encode()), 'source': source,
            'observation': state, 'actual': state == 'actual_registration',
            'operationId': None, 'generatedUniqueId': None, 'operationIdSource': 'unknown_static',
            'technicalOwner': {'kind': 'implementation_coordinate_not_human_owner', 'endpoint': endpoint, 'file': source['file']},
            'domainOwner': None, 'domainOwnerEvidence': 'unknown_needs_owner_decision',
            'policy': None, 'authAssessment': 'unknown_not_proven_by_names_tags_or_dependencies',
            'executionClass': 'websocket' if protocol == 'websocket' else 'unknown_response_semantics',
            'decision': 'needs-owner-decision', 'decisionEvidence': None, 'consumerRefs': [],
            'consumerStatus': 'unknown_no_proven_match', 'protocolPassportRefs': []}


def static_rows(source):
    name, rows = source['name'], []
    hashes = {f['file']: f['sha256'] for f in source['files']}
    for index, ep in enumerate(source['endpoints']):
        row = base_row(name, ep['app'], ep['method'], ep['path'], 'websocket' if ep['method'] == 'WEBSOCKET' else 'http', 'static_' + ep['resolution'],
                       ep['mount_chain'], None, source_ref(ep['file'], ep['line'], hashes), ep['handler'], index)
        row.update({'declaredPath': ep['declared_path'], 'dependencies': ep['dependencies'],
                    'unresolved': ep['unresolved'], 'sourceDeclarationId': ep['declaration_id']})
        rows.append(row)
    for ep in source['unattached_routes']:
        rows.append(base_row(name, None, ep['method'], ep['path'], 'http', 'unattached_static_declaration',
            [], None, source_ref(ep['file'], ep['line'], hashes), ep.get('handler'), len(rows)))
        rows[-1]['unresolved'] = [ep['reason'], *ep['unresolved']]
    for ep in source['native_http_candidates']:
        rows.append(base_row(name, None, ep['method'], ep['path'], 'http', 'native_condition_candidate_not_route',
            [], None, source_ref(ep['file'], ep['line'], hashes), None, len(rows)))
        rows[-1]['unresolved'] = ['native_condition_may_be_guard_not_dispatch; method/order/fallthrough_unproven']
    return rows


def actual_rows(report, source):
    require(report.get('kind') == 'actual-core-runtime-route-inventory' and report.get('status') != 'blocked', 'actual_receipt_required')
    require(report.get('sourceRevision') == source['git']['head'], 'runtime_revision_drift')
    provenance = report['provenance']
    require(provenance.get('guard', {}).get('deniedAttempts') == 0 and provenance.get('realDatabaseBase') is True
            and provenance.get('pythonIsolated') is True and provenance.get('ambientEnvironment') == 'replaced'
            and provenance.get('appEnv') == 'dev' and provenance.get('entrypoint') == 'app.main.app'
            and all(provenance.get(k) is False for k in ['lifespanExecuted', 'requestsExecuted', 'openapiGenerated']), 'unaccepted_runtime_provenance')
    require(provenance.get('compositionFlags') == {'partner_oauth_enabled': False, 'partner_api_enabled': False, 'partner_docs_enabled': False}, 'runtime_flags_drift')
    parity = report.get('productRegistrationParity', {})
    require(parity.get('matches') is True and parity.get('basis') == 'real_PolicyRoute_product_app_identity_method_multiset'
            and parity.get('expectedOperations') == parity.get('observedOperations')
            == report['statistics']['curatedOperations'], 'runtime_policy_parity_required')
    require(len(report['operations']) <= MAX_ROWS and len(report['operations']) == report['statistics']['operations'], 'runtime_row_limit_or_count')
    hashes = {f['file']: f['sha256'] for f in source['files']}
    expected_manifest = {p: h for p, h in hashes.items() if p.startswith('app/') and p.endswith('.py')}
    actual_manifest = report.get('sourceManifest', {})
    require(actual_manifest.get('files') == expected_manifest and actual_manifest.get('sha256') ==
            sha(json.dumps(expected_manifest, sort_keys=True, separators=(',', ':')).encode()), 'runtime_full_source_manifest_drift')
    rows = []
    for index, ep in enumerate(report['operations']):
        ref = ep['source']
        if ref.get('file') is not None:
            require(hashes.get(ref['file']) == ref['sha256'] and ref['sha256'] is not None, 'runtime_source_hash_drift')
        elif ep['endpoint'].startswith('app.'):
            require(False, 'core_endpoint_source_missing')
        explicit = ep.get('operationId')
        require(ep['operationIdSource'] == ('explicit' if explicit else 'generated_only' if ep.get('generatedUniqueId') else 'none'), 'operation_id_provenance_mismatch')
        row = base_row('Core', 'app.main.app', ep['method'], ep['path'], ep['protocol'], 'actual_registration',
                       ep['mountChain'], ep['order'], ref, ep['endpoint'], index)
        row.update({k: ep[k] for k in ['operationId', 'generatedUniqueId', 'operationIdSource', 'policy', 'dependencies', 'declaredPath']})
        row['generatedUniqueIdBasis'] = ep.get('generatedUniqueIdBasis')
        row['registeredMethods'] = ep.get('registeredMethods')
        row['pathFormat'] = ep.get('pathFormat')
        row['authAssessment'] = ep['authAssessment']
        if ep['policy']:
            row['domainOwner'], row['domainOwnerEvidence'] = ep['policy']['owner'], 'real_PolicyRoute_binding_declaration_not_acl_execution'
        if ep['category'] == 'curated_policy':
            row.update(decision='candidate', decisionEvidence='actual_product_app_identity; default-off composition; not external release')
        rows.append(row)
    require(len({r['keySha256'] for r in rows}) == len(rows), 'duplicate_runtime_identity')
    return rows


def consumer_map(data, rows, ledger, pin):
    require(data['summary']['sourceRevision'] == pin, 'consumer_revision_drift')
    require(len(data['records']) <= MAX_ROWS and data['summary']['counts']['omittedWrappers'] == 0, 'consumer_limit_or_omission')
    producer = {'file': 'scripts/inventory-api-consumers.mjs',
                'sha256': sha(blob(ledger, pin, 'clearledger/scripts/inventory-api-consumers.mjs'))}
    require(data['summary']['generator'] == producer, 'consumer_producer_drift')
    manifest_bytes = (json.dumps(data['manifest'], ensure_ascii=False, indent=2) + '\n').encode()
    expected_source = {'files': len(data['manifest']), 'lines': sum(f['lines'] for f in data['manifest']),
                       'manifestSha256': sha(manifest_bytes)}
    require(data['summary']['source'] == expected_source, 'consumer_manifest_summary_drift')
    records = data['records']
    shared = [r for r in records if r['category'] == 'shared']
    direct = [r for r in records if r['category'] == 'native']
    transport = [*shared, *direct]
    expected_counts = {
        'records': len(records), 'shared': len(shared), 'direct': len(direct),
        'streamConstructors': sum(r['transport'] in ['WebSocket', 'EventSource'] for r in direct),
        'unresolvedWrappers': sum(r['category'] == 'wrapper' for r in records), 'omittedWrappers': 0,
        'syntacticDiagnostics': len(data['diagnostics']),
        'staticTransportPaths': sum(r['pathState'] == 'static' for r in transport),
        'dynamicTransportPaths': sum(r['pathState'] == 'dynamic' for r in transport),
        'unknownTransportPaths': sum(r['pathname'] is None for r in transport),
        'unknownTransportMethods': sum(r['method'] is None for r in transport)}
    require(data['summary']['counts'] == expected_counts and
            len(transport) + expected_counts['unresolvedWrappers'] == len(records), 'consumer_record_summary_drift')
    manifest = {f['file']: f['sha256'] for f in data['manifest']}
    require(len(manifest) == len(data['manifest']) <= MAX_FILES, 'consumer_manifest_duplicate_or_limit')
    for path, digest in manifest.items():
        require(path.startswith('src/') and '..' not in PurePosixPath(path).parts, 'consumer_manifest_path_invalid')
        require(sha(blob(ledger, pin, 'clearledger/' + path)) == digest, 'consumer_manifest_source_drift')
    consumers = []
    for record in data['records']:
        require(manifest.get(record['file']) == record['sourceSha256'], 'consumer_record_source_drift')
        item = {k: record[k] for k in ['file', 'line', 'column', 'category', 'transport', 'method', 'pathname', 'pathState', 'sourceSha256', 'expressionSha256']}
        item['id'] = f'C{len(consumers) + 1:05}'
        # Shared apiClient calls use the Core configured base; physical authority is still unknown.
        # Native origins are redacted by the producer and must never be guessed here.
        item['authority'] = 'core-configured-api-base' if record['category'] == 'shared' else 'unknown_redacted_or_dynamic_authority'
        item['confidence'] = 'source_callsite_only_not_request_or_reachability'
        path = (record['pathname'] or '').split('?', 1)[0].split('#', 1)[0]
        matches = [r for r in rows if r['key']['service'] == 'Core' and record['category'] == 'shared'
                   and record['pathState'] == 'static' and path.startswith('/') and '{' not in path
                   and r['key']['path'] == path and r['key']['method'] == record['method']]
        item['surfaceRefs'] = [r['keySha256'] for r in matches]
        item['matchStatus'] = 'exact_method_path_source_candidate' if matches else 'unknown_no_safe_exact_match'
        for row in matches:
            row['consumerRefs'].append(item['id'])
            row['consumerStatus'] = 'exact_source_candidate_not_runtime_consumer_proof'
        consumers.append(item)
    return {'status': 'current_source_ast', 'producer': data['summary']['generator'],
            'manifestSha256': data['summary']['source']['manifestSha256'], 'records': consumers,
            'limits': data['summary']['limitations'], 'otherApplications': 'Support/Auditor/mobile/external/partners consumers unknown; no absence claim'}


def support_live_evidence(args, pin):
    if not args.support_live_proof:
        return {'status': 'not_supplied'}
    require(args.support_live_parity is not None and args.support_live_process is not None, 'support_live_complete_receipts_required')
    proof, parity, process = (load_json(p) for p in [args.support_live_proof, args.support_live_parity, args.support_live_process])
    require(proof.get('readOnly') is True and proof.get('containerStable') is True and proof.get('twoSourceReadsEqual') is True
            and proof['source']['appImported'] is False and proof['source']['databaseAccess'] is False
            and process.get('exit') == 0 and process.get('reaped') is True, 'support_live_receipt_invalid')
    require(proof['source']['selectedCount'] <= 1000 and proof['source']['totalBytes'] <= 32 * 1024 * 1024
            and pin in parity, 'support_live_limit_or_revision_drift')
    return {'status': 'ROOT_selected_source_hash_proof_not_whole_app_actual', 'observedUTC': proof['observedUTC'],
            'container': {k: proof['container'][k] for k in ['id', 'image', 'started']},
            'node': proof['source']['node'], 'selectedCount': proof['source']['selectedCount'], 'totalBytes': proof['source']['totalBytes'],
            'parityBySourceRevision': parity, 'limitations': proof['limitations'],
            'receipts': [{'file': p.name, 'sha256': sha(p.read_bytes())}
                         for p in [args.support_live_proof, args.support_live_parity, args.support_live_process]]}


def protocol_appendix(ledger, pin, core_files, rows):
    historical_raw = blob(ledger, pin, PROTOCOL)
    historical = json.loads(historical_raw)
    drift = []
    for path, old in historical['sourceHashes'].items():
        try:
            current = sha(blob(ledger, pin, path))
        except subprocess.CalledProcessError:
            current = None
        drift.append({'file': path, 'historicalSha256': old, 'currentSha256': current})
    for record in drift:
        record['matches'] = record['historicalSha256'] == record['currentSha256']
    by_file = {d['file']: d for d in drift}
    passports = []
    for old in [*historical['operations'], *historical['integrationComparators']]:
        evidence = by_file.get(old['source'])
        same = evidence is not None and evidence['matches']
        item = {k: old[k] for k in ['id', 'method', 'path', 'source', 'line', 'endpoint']}
        item.update({'historicalKind': old.get('kind', 'integration_comparator'),
                     'historicalTransport': old['transport'], 'currentSourceMatches': same,
                     'currentSha256': evidence['currentSha256'] if evidence else None,
                     'status': 'unchanged_endpoint_file_source_facts_only' if same else 'source_drift_requires_review',
                     'admissionAndDependencies': 'unknown_current_conformance; historical ACL/selectors not re-certified', 'surfaceRefs': []})
        for row in rows:
            if (row['key']['service'] == 'Core' and row['key']['method'] == old['method'] and row['key']['path'] == old['path']
                    and row['technicalOwner']['endpoint'] == old['endpoint']):
                item['surfaceRefs'].append(row['keySha256'])
                row['protocolPassportRefs'].append(old['id'])
                if same:
                    row['executionClass'] = old.get('kind', 'integration_adapter_source_fact').lower()
        passports.append(item)
    return {'historicalArtifact': {'file': PROTOCOL, 'sha256': sha(historical_raw), 'sourceRevision': historical['sourceRevision'],
                                  'runtimeSourceRevision': historical['runtimeSourceRevision']},
            'sourceDrift': drift, 'passports': passports,
            'limits': 'Unchanged file proves source correspondence only; changed dependency/guard/context and current protocol behavior require characterization. No current OpenAPI/ACL conformance claim.'}


def auditor_protocol_facts(files):
    """Small reviewed source addendum, not an additional route parser or actual exporter."""
    digest = sha(files['server.js'])
    facts = [
        ('A01', 'WEBSOCKET', '/ws/terminal', 'websocket', [2222], 'WebSocketServer path declaration; upgrade/order/admission unexecuted'),
        ('A02', 'POST', '/api/ask', 'sse', [1885, 1916, 2201], 'handleAsk emits text/event-stream and data frames after admission; no request executed'),
        ('A03', 'GET', '/api/export-work', 'binary', [1435, 1450, 2180], 'handleExportWork emits application/gzip attachment; archive process not executed'),
        ('A04', 'POST', '/api/upload', 'multipart', [1543, 1610, 2198], 'readSingleFile boundary parser/handleUpload; no payload or disk write executed'),
        ('A05', 'POST', '/api/knowledge/upload', 'multipart', [1543, 1732, 2184], 'readSingleFile/handleKnowledgeUpload; no payload or disk write executed'),
        ('A06', None, '/health', 'native_method_unspecified', [2115], 'native path condition has no method restriction; not a single proven GET route'),
        ('A07', 'GET', None, 'native_catchall_redirect', [2205], 'non-api GET prefix predicate; unbounded paths, not one enumerated path'),
    ]
    # This manual review is valid only for its reviewed source bytes.
    require(digest == 'a51ba3cd14d5ee220c0e4a01cd863ce4f1aaeb5663f0905ad8e92d7083b7e578', 'auditor_manual_protocol_review_source_drift')
    return [{'id': i, 'service': 'Auditor', 'method': m, 'path': p, 'protocolClass': c,
             'source': {'file': 'services/auditor/server.js', 'sha256': digest, 'lines': lines},
             'observation': 'manual_static_source_fact_not_actual_route', 'evidence': note,
             'decision': 'needs-owner-decision', 'consumerStatus': 'unknown'} for i, m, p, c, lines, note in facts]


def build(args):
    pins = {'Core': revision(args.core_revision), 'Support': revision(args.support_revision), 'Auditor': revision(args.deploy_revision)}
    scanner, producer = scanner_module(args.deploy, pins['Auditor'])
    sources, contents = [], {}
    for name, repo, prefix in [('Core', args.ledger, 'clearledger/server'), ('Support', args.support, ''), ('Auditor', args.deploy, 'services/auditor')]:
        source, contents[name] = static_source(scanner, name, repo, pins[name], prefix)
        sources.append(source)
    # Manifests are also frozen blobs; do not use another owner's current working tree.
    manifests = []
    for path in git(args.deploy, 'ls-tree', '-r', '--name-only', pins['Auditor'], '--', 'apps').decode().splitlines():
        if path.endswith('.yml'):
            manifests.append({'file': path, 'sha256': sha(blob(args.deploy, pins['Auditor'], path)),
                              'status': 'partial_source_only' if Path(path).stem in ['ledger', 'support', 'auditor'] else 'excluded_unknown_shared_backend_or_separate_source_unproven'})
    rows = []
    runtime = load_json(args.runtime) if args.runtime else None
    for source in sources:
        rows += actual_rows(runtime, source) if source['name'] == 'Core' and runtime else static_rows(source)
    native_facts = auditor_protocol_facts(contents['Auditor'])
    for fact in native_facts:
        matches = [r for r in rows if r['key']['service'] == 'Auditor'
                   and r['key']['method'] == fact['method'] and r['key']['path'] == fact['path']]
        if not matches:
            protocol = 'websocket' if fact['protocolClass'] == 'websocket' else 'http'
            row = base_row('Auditor', 'native_httpServer' if protocol == 'http' else 'native_WebSocketServer',
                fact['method'], fact['path'], protocol, 'manual_static_native_declaration_or_predicate', [], None,
                source_ref('server.js', fact['source']['lines'][0], {'server.js': fact['source']['sha256']}), None, len(rows))
            row['unresolved'] = [fact['evidence'], 'not_actual_registration_or_dispatch']
            rows.append(row)
            matches = [row]
        fact['surfaceRefs'] = [r['keySha256'] for r in matches]
        for row in matches:
            row['executionClass'] = fact['protocolClass'] + '_source_fact'
            row.setdefault('nativeProtocolRefs', []).append(fact['id'])
    require(len(rows) <= MAX_ROWS and len({r['keySha256'] for r in rows}) == len(rows), 'surface_limit_or_key_collision')
    if args.consumers:
        consumer_data, consumer_receipt = load_json(args.consumers, receipt=True)
        consumers = consumer_map(consumer_data, rows, args.ledger, pins['Core'])
        consumers['inputReceipt'] = consumer_receipt
    else:
        consumers = {'status': 'unknown_current_consumer_export_not_supplied'}
    protocols = protocol_appendix(args.ledger, pins['Core'], contents['Core'], rows)
    overlap = load_json(args.overlap) if args.overlap else None
    if overlap is not None:
        require(runtime is not None and overlap['sourceRevision'] == pins['Core'], 'overlap_revision_drift')
        require(overlap['artifact']['sha256'] == sha(args.runtime.read_bytes()), 'overlap_actual_artifact_drift')
    return {'schemaVersion': 1, 'kind': 'dated-current-surface-registry', 'date': '2026-10-31', 'sourcePins': pins,
        'scope': 'Core/Support/Auditor selected frozen sources; full M00-M19 and 11 gates remain active',
        'generator': {'file': 'clearledger/scripts/current-surface-registry.py', 'sha256': sha(Path(__file__).read_bytes()), 'staticProducer': producer},
        'limits': {'inputBytes': MAX_BYTES, 'sourceFilesPerService': MAX_FILES, 'sourceBytesPerService': 64 * 1024 * 1024,
                   'surfaceRows': MAX_ROWS, 'consumerRows': MAX_ROWS, 'outputBytes': MAX_BYTES, 'gitCallSeconds': 30,
                   'composerWallSeconds': 240},
        'sources': sources, 'manifestCoverage': manifests, 'surfaces': rows, 'consumers': consumers, 'currentProtocolAppendix': protocols,
        'nativeProtocolAddendum': native_facts,
        'supportLiveEvidence': support_live_evidence(args, pins['Support']),
        'runtimeReceipt': {'status': 'ROOT_supplied_actual_core_only', 'sha256': sha(args.runtime.read_bytes()),
                           'provenance': runtime['provenance'], 'productRegistrationParity': runtime['productRegistrationParity'],
                           'statistics': runtime['statistics'], 'mounts': runtime['mounts'], 'unresolved': runtime['unresolved'],
                           'duplicates': runtime['duplicates'], 'parameterCollisions': runtime['parameterCollisions'],
                           'sharedPaths': runtime['sharedPaths'], 'literalParameterOverlaps': runtime['literalParameterOverlaps'],
                           'staticComparison': runtime.get('staticComparison')} if runtime else {'status': 'not_supplied_source_only'},
        'overlapReceipt': overlap,
        'unknowns': ['Support/Auditor actual whole-app export not available; no server entrypoint executed',
                     'Native conditions may be admission guards, not dispatch; method wildcards/catch-all/fallthrough unresolved',
                     'Dynamic factory/mount/SSE/proxy/middleware/static/industry dispatch outside scanner remains unknown',
                     'Auditor /ws/terminal and /api/ask SSE have manual source evidence; not actual registration/conformance proof',
                     'Binary/multipart/webhook/industry protocol outside current source-corresponding passports requires review',
                     'Physical deployment authority/base URL, live-source correspondence, human/domain owners and external consumers unproven',
                     'Tags/handler names/dependencies/response_class do not prove ACL or protocol semantics',
                     'No supported_external/legacy/internal/integration rollout decision inferred from names; owner decisions remain open'],
        'summary': {'surfaces': len(rows), 'observations': dict(Counter(r['observation'] for r in rows)),
                    'decisions': dict(Counter(r['decision'] for r in rows)), 'domainOwnersUnknown': sum(r['domainOwner'] is None for r in rows),
                    'consumerStatus': dict(Counter(r['consumerStatus'] for r in rows)),
                    'protocolPassportStatus': dict(Counter(p['status'] for p in protocols['passports']))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['ledger', 'support', 'deploy']:
        parser.add_argument('--' + key, type=Path, required=True)
    for key, source in [('core', 'Core'), ('support', 'Support'), ('deploy', 'Auditor')]:
        parser.add_argument('--' + key + '-revision', default=PINS[source])
    for key in ['runtime', 'consumers', 'overlap']:
        parser.add_argument('--' + key, type=Path)
    for key in ['support-live-proof', 'support-live-parity', 'support-live-process']:
        parser.add_argument('--' + key, type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--static-output', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    require(sys.version_info >= (3, 13), 'python_ast_313_or_newer_required')
    def expired(signum, frame):
        raise TimeoutError('registry_wall_time_limit')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(240)
    report = build(args)
    signal.alarm(0)
    raw = canonical(report).encode()
    require(len(raw) <= MAX_BYTES, 'output_byte_limit')
    if args.check:
        require(args.output.read_bytes() == raw, 'registry_drift')
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
    if args.static_output:
        require(not args.check, 'check_must_not_write_static')
        args.static_output.write_text(canonical({'schema_version': 1, 'sources': report['sources']}))
    print(canonical({'status': 'current' if args.check else 'written', 'sha256': sha(raw), 'summary': report['summary']}), end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as error:
        # No arbitrary exception text, local paths or child streams in public output.
        reason = str(error) if type(error) is ValueError and re.fullmatch('[a-z_]{1,80}', str(error)) else 'omitted'
        print(canonical({'status': 'blocked', 'errorType': type(error).__name__, 'reason': reason}), end='')
        raise SystemExit(2)
