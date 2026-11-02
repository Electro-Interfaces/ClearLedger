#!/usr/bin/env python3
"""Bounded source-only package comparison; never imports/runs Node or application code."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess

BASELINE = '09c221c4b5135984173e3a924fd38f65cc208637'
CANDIDATE = 'a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df'
EXPECTED = {'package.json': (10730, '3c344dec6cfe8217f8d43385652a1536024d268f9b0e0e835ce82226bde4a9e4'),
            'package-lock.json': (460435, 'ad7ae28502e1fdf93541bb313ea13f0b946f6db53219099360f8a01c42cabf96')}
INPUT_LIMIT, FILE_LIMIT, OUTPUT_LIMIT = 2 * 1024 * 1024, 512 * 1024, 1024 * 1024
SNAPSHOT_SHA = '8f25dc18c789d279e73ec1028cde775bfbfef3f64a133338d60c43f285865fa8'
PROCESS_SHA = 'fa48fd24136c18ea12298d01698d92c036f46f5b101de5077e076b6df1ba75cd'
RELEASE_SHA = '5730221f4e47a8e9786ed734299e7789130c10c3372aed964f20c312ee4b859f'
REVIEW_FILES = {
    'scripts/server.js': [1, 158, 193, 227, 300, 315, 430, 440, 514, 590],
    'scripts/lib/env.js': [5, 6], 'scripts/lib/db.js': [12, 17, 39, 57],
    'scripts/lib/ssh-execute.js': [11, 13, 16, 17], 'scripts/lib/rate-limiter.js': [9, 17],
    'scripts/routes/ai.js': [20, 34, 41, 391], 'scripts/routes/ai-audit.js': [24, 38, 45, 207],
    'scripts/lib/terminal-manager.js': [31, 70, 152, 153, 214, 223],
    'scripts/lib/live-session.js': [181, 193], 'scripts/lib/ws-manager.js': [30, 78],
    'scripts/lib/core-identity.js': [111, 116, 118],
    'scripts/lib/support-context-entry.js': [12, 24, 32], 'scripts/routes/v1/support-context.js': [30, 58, 104, 115],
    'scripts/lib/support-context.js': [440, 444],
    'scripts/routes/ssh.js': [67], 'scripts/routes/diagnostics.js': [109],
    'scripts/routes/knowledge.js': [5], 'scripts/routes/notifications.js': [7],
    'scripts/routes/v1/eco.js': [53, 54, 55, 56, 57],
    'scripts/routes/v1/voice-context.js': [8], 'scripts/routes/v1/ticket-communications.js': [5],
    'scripts/routes/v1/voice-knowledge.js': [10], 'scripts/routes/v1/voice-connections.js': [7],
    'vite.config.ts': [7, 14], 'Dockerfile': [5, 10, 52, 53, 75],
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def read(path, limit=INPUT_LIMIT):
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    require(len(raw) <= limit, 'input_byte_limit')
    return raw


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('nonfinite_json_number')
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
                       parse_int=Decimal, parse_float=Decimal, parse_constant=nonfinite)
    count = 0
    def bound(node, depth=0):
        nonlocal count
        count += 1
        require(depth <= 64 and count <= 200000, 'json_structure_limit')
        for child in node.values() if isinstance(node, dict) else node if isinstance(node, list) else ():
            bound(child, depth + 1)
    bound(value)
    return value


def number_key(value):
    sign, digits, exponent = value.as_tuple()
    digits = list(digits)
    if not any(digits):
        return [0, [0], 0]
    while digits and digits[-1] == 0:
        digits.pop(); exponent += 1
    return [sign, digits, exponent]


def tree(value):
    if isinstance(value, Decimal):
        return ['number', number_key(value)]
    if isinstance(value, dict):
        return ['object', [[key, tree(value[key])] for key in sorted(value)]]
    if isinstance(value, list):
        return ['array', [tree(child) for child in value]]
    return [type(value).__name__, value]


def semantic_sha(value):
    return sha(json.dumps(tree(value), ensure_ascii=False, separators=(',', ':')).encode())


def public(value):
    result = {'type': 'number' if isinstance(value, Decimal) else type(value).__name__, 'semanticSha256': semantic_sha(value)}
    if value is None or isinstance(value, (bool, Decimal)):
        result['value'] = str(value) if isinstance(value, Decimal) else value
    elif isinstance(value, str):
        result['characters'] = len(value)
        # Versions are public metadata. No scripts, URLs, credentials or raw bodies are emitted.
        if re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', value):
            result['value'] = value
    elif isinstance(value, (dict, list)):
        result['entries'] = len(value)
    return result


def differences(left, right, path=()):
    rows = []
    def add(kind, parts, before=None, after=None):
        pointer = '/' + '/'.join(p.replace('~', '~0').replace('/', '~1') for p in parts)
        rows.append({'pointer': pointer, 'path': list(parts), 'kind': kind,
                     'before': public(before), 'after': public(after)})
        require(len(rows) <= 10000, 'semantic_diff_limit')
    def walk(a, b, parts):
        if type(a) is not type(b):
            add('type_changed', parts, a, b)
        elif isinstance(a, dict):
            for key in sorted(a.keys() | b.keys()):
                if key not in a:
                    add('added', (*parts, key), None, b[key])
                elif key not in b:
                    add('removed', (*parts, key), a[key], None)
                else:
                    walk(a[key], b[key], (*parts, key))
        elif isinstance(a, list):
            if len(a) != len(b):
                add('array_length_changed', parts, Decimal(len(a)), Decimal(len(b)))
            for index in range(max(len(a), len(b))):
                if index >= len(a):
                    add('array_item_added', (*parts, str(index)), None, b[index])
                elif index >= len(b):
                    add('array_item_removed', (*parts, str(index)), a[index], None)
                else:
                    walk(a[index], b[index], (*parts, str(index)))
        elif a != b:
            add('value_changed', parts, a, b)
    walk(left, right, path)
    return rows


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=True, timeout=30)
    require(len(result.stdout) <= 4 * INPUT_LIMIT, 'git_output_limit')
    return result.stdout


def blob(repo, pin, file):
    value = git(repo, 'show', pin + ':' + file)
    require(len(value) <= FILE_LIMIT, 'source_blob_limit')
    return value


def byte_facts(raw):
    trailing = len(raw) - len(raw.rstrip(b'\r\n'))
    return {'bytes': len(raw), 'sha256': sha(raw),
            'gitBlobSha1': hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest(),
            'crlf': raw.count(b'\r\n'), 'lf': raw.count(b'\n') - raw.count(b'\r\n'),
            'loneCr': raw.count(b'\r') - raw.count(b'\r\n'), 'utf8Bom': raw.startswith(b'\xef\xbb\xbf'),
            'trailingNewlineBytes': trailing, 'trailingNewlineHex': raw[-trailing:].hex() if trailing else '',
            'semanticSha256': semantic_sha(parse(raw))}


def compare(left_raw, right_raw, lock=False):
    left, right = parse(left_raw), parse(right_raw)
    diff = differences(left, right)
    result = {'bytesEqual': left_raw == right_raw, 'semanticEqual': not diff, 'differences': diff,
              'changedLineCount': sum(a != b for a, b in zip(left_raw.splitlines(), right_raw.splitlines()))
                                  + abs(len(left_raw.splitlines()) - len(right_raw.splitlines()))}
    if isinstance(left.get('version'), str) and isinstance(right.get('version'), str):
        old = json.dumps(left['version']).encode(); new = json.dumps(right['version']).encode()
        result['onlyRootVersionTokenReplacementReproducesBytes'] = left_raw.replace(old, new) == right_raw
    if lock:
        a, b = left['packages'], right['packages']
        require(len(a) <= 10000 and len(b) <= 10000, 'lock_entry_limit')
        changed, fields = [], Counter()
        for key in sorted(a.keys() | b.keys()):
            delta = differences(a.get(key), b.get(key))
            if delta:
                changed.append({'packagePath': key, 'differences': delta})
                fields.update(d['path'][0] if d['path'] else '<entry>' for d in delta)
        result['everyPackageEntry'] = {'leftEntries': len(a), 'rightEntries': len(b),
            'packagePathSetEqual': a.keys() == b.keys(), 'changedEntries': changed,
            'equalNonRootEntries': sum(key != '' and key in b and not differences(value, b[key]) for key, value in a.items()),
            'changedFieldCounts': dict(sorted(fields.items())),
            'resolvedChanged': sum(any(d['path'] and d['path'][0] == 'resolved' for d in entry['differences']) for entry in changed),
            'integrityChanged': sum(any(d['path'] and d['path'][0] == 'integrity' for d in entry['differences']) for entry in changed),
            'dependenciesChanged': sum(any(d['path'] and d['path'][0] in ['dependencies', 'optionalDependencies', 'peerDependencies', 'devDependencies'] for d in entry['differences']) for entry in changed)}
    return result


def decode_file(record, size, digest):
    require(record['bytes'] == size and record['sha256'] == digest, 'snapshot_file_metadata_drift')
    require(isinstance(record['base64'], str) and len(record['base64']) <= 4 * FILE_LIMIT, 'base64_limit')
    body = base64.b64decode(record['base64'], validate=True)
    require(len(body) == size and sha(body) == digest, 'decoded_file_hash_or_size_mismatch')
    parse(body)
    return body


def load_live(snapshot, process):
    raw, process_raw = read(snapshot), read(process)
    require(sha(raw) == SNAPSHOT_SHA and sha(process_raw) == PROCESS_SHA, 'snapshot_or_process_pin_drift')
    data, receipt = parse(raw), parse(process_raw)
    require(data.get('readOnly') is True and data.get('containerStable') is True and data.get('twoReadsEqual') is True,
            'snapshot_readonly_stability_required')
    require(receipt.get('exit') == 0 and receipt.get('reaped') is True and receipt.get('readOnly') is True, 'snapshot_process_receipt_required')
    require(data['source']['appImported'] is False and data['source']['databaseAccess'] is False, 'source_only_snapshot_required')
    require(set(data['source']['files']) == set(EXPECTED), 'exact_two_files_required')
    result = {}
    for file, (size, digest) in EXPECTED.items():
        result[file] = decode_file(data['source']['files'][file], size, digest)
    return result, {'snapshotFile': snapshot.name, 'snapshotSha256': sha(raw), 'processFile': process.name,
                    'processSha256': sha(process_raw), 'observedUTC': data['observedUTC'],
                    'container': {key: data['container'][key] for key in ['id', 'image', 'started']},
                    'node': data['source']['node'], 'scope': data['scope']}


def history(repo, manifest, live):
    raw = read(manifest)
    refs = parse(raw)['refs']
    require(0 < len(refs) <= 2048 and all(re.fullmatch('[a-f0-9]{40}', r['object']) for r in refs), 'bounded_history_roots_required')
    heads = sorted({r['object'] for r in refs})
    commits = git(repo, 'log', '--format=%H', *heads, '--', *EXPECTED).decode().splitlines()
    objects = git(repo, 'rev-list', '--objects', *heads, '--', *EXPECTED).decode().splitlines()
    require(len(commits) <= 4096 and len(objects) <= 65536, 'history_result_limit')
    object_ids = {line.split(' ', 1)[0] for line in objects}
    live_version = parse(live['package.json'])['version']
    matching_versions = []
    for commit in commits:
        if parse(blob(repo, commit, 'package.json')).get('version') == live_version:
            matching_versions.append(commit)
    return {'scope': 'Only frozen examined local refs/object roots; no fetch/network, not all Git repositories or unreferenced objects',
            'refManifestSha256': sha(raw), 'examinedRefs': len(refs), 'uniqueObjectRoots': len(heads),
            'packageHistoryCommits': len(commits), 'pathObjects': len(objects),
            'liveVersionMatchingCommits': matching_versions,
            'exactLiveBlobReachable': {file: byte_facts(body)['gitBlobSha1'] in object_ids for file, body in live.items()}}


def selected_coverage(args, live_evidence):
    raw, parity_raw, process_raw = (read(p) for p in [args.selected_snapshot, args.selected_parity, args.selected_process])
    snapshot, expected, process = parse(raw), parse(parity_raw), parse(process_raw)
    require(snapshot.get('readOnly') is True and snapshot.get('containerStable') is True
            and snapshot.get('twoSourceReadsEqual') is True and process.get('exit') == 0
            and process.get('reaped') is True, 'selected_source_receipt_invalid')
    require(all(snapshot['container'][k] == live_evidence['container'][k] for k in ['id', 'image', 'started']), 'selected_source_container_drift')
    files = snapshot['source']['files']
    require(len(files) <= 1000 and snapshot['source']['selectedOnly'] is True
            and snapshot['source']['appImported'] is False and snapshot['source']['databaseAccess'] is False
            and snapshot['source']['selectedCount'] == len(files), 'selected_source_scope_invalid')
    require(sum(r.get('bytes', 0) for r in files.values() if r['exists']) == snapshot['source']['totalBytes']
            <= 32 * 1024 * 1024, 'selected_source_byte_limit_or_sum')
    for file, (size, digest) in EXPECTED.items():
        require(files[file]['exists'] is True and files[file]['bytes'] == size and files[file]['sha256'] == digest,
                'selected_package_body_digest_drift')
    actual = {}
    for pin in [BASELINE, CANDIDATE]:
        entry = {'equal': 0, 'different': [], 'missingOrNotInReference': []}
        for path, record in sorted(files.items()):
            require(path in EXPECTED or (path.startswith('scripts/') and Path(path).suffix in {'.js', '.mjs', '.cjs'}), 'selected_path_outside_scope')
            require('..' not in Path(path).parts, 'selected_path_invalid')
            if not record['exists']:
                entry['missingOrNotInReference'].append(path)
                continue
            try:
                reference = blob(args.support_repo, pin, path)
            except subprocess.CalledProcessError:
                entry['missingOrNotInReference'].append(path)
                continue
            if sha(reference) == record['sha256']:
                entry['equal'] += 1
            else:
                entry['different'].append(path)
        actual[pin] = entry
    require(actual == expected, 'selected_source_parity_drift')
    delta = git(args.support_repo, 'diff', '--name-status', BASELINE, CANDIDATE).decode().splitlines()
    require(len(delta) <= 1000, 'candidate_delta_limit')
    return {'selectedPaths': len(files), 'existingPaths': sum(r['exists'] for r in files.values()),
            'totalBytes': int(snapshot['source']['totalBytes']), 'observedUTC': snapshot['observedUTC'],
            'recomputedParity': actual,
            'fullCandidateGitDelta': [{'status': line.split('\t')[0], 'paths': line.split('\t')[1:]} for line in delta],
            'proofs': [{'file': p.name, 'sha256': sha(v)} for p, v in zip(
                [args.selected_snapshot, args.selected_parity, args.selected_process], [raw, parity_raw, process_raw])],
            'coverage': 'Selected tracked scripts JS/MJS/CJS and package files only; shared/frontend/runtime-only/untracked and installed dependencies unknown'}


def report(args):
    live, evidence = load_live(args.snapshot, args.process)
    require(git(args.support_repo, 'rev-parse', 'HEAD').decode().strip() == CANDIDATE, 'support_head_drift')
    versions = {'live': live, 'baseline': {}, 'candidate': {}}
    for label, pin in [('baseline', BASELINE), ('candidate', CANDIDATE)]:
        versions[label] = {file: blob(args.support_repo, pin, file) for file in EXPECTED}
    packages = {}
    for file in EXPECTED:
        packages[file] = {'sources': {label: byte_facts(values[file]) for label, values in versions.items()},
            'comparisons': {a + '_to_' + b: compare(versions[a][file], versions[b][file], file == 'package-lock.json')
                            for a, b in [('baseline', 'live'), ('candidate', 'live'), ('baseline', 'candidate')]}}
    metadata = {}
    for label, values in versions.items():
        package, lock = parse(values['package.json']), parse(values['package-lock.json'])
        metadata[label] = {'version': public(package['version']), 'lockVersion': public(lock.get('lockfileVersion')),
            'fields': {key: {'present': key in package, **public(package.get(key))}
                       for key in ['name', 'scripts', 'dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies', 'overrides', 'engines']},
            'lockRootMetadata': public({key: value for key, value in lock.items() if key != 'packages'}),
            'lockPackages': len(lock['packages']), 'nonRootPackages': len(lock['packages']) - 1,
            'withResolved': sum('resolved' in value for value in lock['packages'].values()),
            'withIntegrity': sum('integrity' in value for value in lock['packages'].values())}
    source_evidence = [{'file': file, 'sourceRevision': CANDIDATE, 'sha256': sha(blob(args.support_repo, CANDIDATE, file)),
                        'reviewLines': lines, 'evidenceClass': 'manual_source_review_not_runtime'} for file, lines in REVIEW_FILES.items()]
    release = read(args.release_script)
    require(sha(release) == RELEASE_SHA and b'npm version patch --no-git-tag-version' in release, 'release_mechanism_source_drift')
    return {'schemaVersion': 1, 'kind': 'source-only-support-package-baseline', 'date': '2026-10-31',
            'sourcePins': {'baseline': BASELINE, 'candidate': CANDIDATE}, 'liveEvidence': evidence,
            'generator': {'file': 'clearledger/scripts/compare-support-source-packages.py', 'sha256': sha(Path(__file__).read_bytes())},
            'comparisonRules': 'Object keys unordered; arrays ordered; bool distinct from number; exact decimal numeric equality; duplicate keys/nonfinite rejected; raw bytes/EOL/version changes preserved separately',
            'limits': {'inputBytes': INPUT_LIMIT, 'sourceFileBytes': FILE_LIMIT, 'outputBytes': OUTPUT_LIMIT,
                       'jsonDepth': 64, 'jsonNodes': 200000, 'semanticDiffRows': 10000, 'lockEntries': 10000,
                       'gitSeconds': 30, 'wallSeconds': 60},
            'files': packages, 'rootMetadata': metadata, 'examinedHistory': history(args.support_repo, args.history_refs, live),
            'selectedSourceCoverage': selected_coverage(args, evidence),
            'compositionSourceEvidence': source_evidence,
            'releaseMechanismEvidence': {'file': 'elsy-deploy/scripts/ship-support.sh', 'sha256': sha(release), 'lines': [43, 46],
                'observedCommand': 'npm version patch --no-git-tag-version',
                'assessment': 'Matching mechanism, execution provenance unproven; no ship command executed'},
            'unknowns': ['Installed node_modules/dependency behavior unknown; lock is source evidence only',
                         'Selected scripts/package proof excludes shared/frontend/runtime-only files; not full Support correspondence',
                         'No app/server/router imported; actual composition/ACL/WS/SSE conformance remains unknown',
                         'Future release must reconcile live higher version baseline explicitly; no manifest/source rewrite here',
                         'M00/M13/M01/fullCI/release and full M00-M19+11 criteria remain open']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['support-repo', 'snapshot', 'process', 'history-refs', 'release-script',
                 'selected-snapshot', 'selected-parity', 'selected-process', 'output']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    def expired(signum, frame):
        raise TimeoutError('source_comparison_wall_limit')
    signal.signal(signal.SIGALRM, expired); signal.alarm(60)
    value = report(args)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    require(len(raw) <= OUTPUT_LIMIT, 'report_output_limit')
    if args.check:
        require(read(args.output) == raw, 'source_report_drift')
    else:
        args.output.write_bytes(raw)
    signal.alarm(0)
    print(json.dumps({'status': 'checked' if args.check else 'written', 'bytes': len(raw), 'sha256': sha(raw)}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        reason = str(error) if type(error) is ValueError and re.fullmatch('[a-z_]{1,80}', str(error)) else 'omitted'
        print(json.dumps({'status': 'blocked', 'errorType': type(error).__name__, 'reason': reason}))
        raise SystemExit(2)
