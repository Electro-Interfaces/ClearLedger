#!/usr/bin/env python3
"""Подготовка и offline-проверка файлов; не resolver, installer или build backend.

fetch: только version JSON PyPI и объявленные HTTPS-файлы pythonhosted.
verify: строго чтение. Ничего из wheel/sdist не импортируется и не извлекается.
Python >=3.11, только stdlib. Область целевой совместимости — заявленная политика.
"""
from __future__ import annotations

import argparse
import ast
import email.parser
import hashlib
import itertools
import json
import re
import ssl
import stat
import struct
import sys
import tarfile
import time
import tomllib
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

MIB = 1024 * 1024
MAX_TOTAL = 256 * MIB
MAX_METADATA = 4 * MIB
MAX_LOG = 2 * MIB
MAX_FILE = 64 * MIB
MAX_MEMBERS = 10000
MAX_EXPANDED = 128 * MIB
RECEIPT_SHA256 = '68f0231bed370837a1489b1be85b9e452d45ffce2d7e4d9be7d5f4503bdb1a10'
REQUIREMENTS_SHA256 = 'f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0'
SOURCE_COMMIT = '88fdef78bab8c8ced97b29d6d24c2a47c472799a'
TARGET = {'python': '3.13.18', 'implementation': 'cpython', 'abi': 'cp313',
          'platform': 'linux/amd64', 'glibc_ceiling': [2, 41],
          'basis': 'declared-debian-trixie-policy-not-target-runtime-certificate'}
# Явные кандидаты, не запрос latest; click/packaging взяты из receipt.
TOOLING = {'pip': '26.2.2', 'pip-tools': '7.6.2', 'build': '1.3.0',
           'click': '8.5.0', 'packaging': '26.3', 'pyproject-hooks': '1.2.0',
           'setuptools': '80.9.0', 'wheel': '0.45.1'}
MARKER_ENV = {'python_version': '3.13', 'python_full_version': '3.13.18',
              'implementation_name': 'cpython', 'implementation_version': '3.13.18',
              'platform_python_implementation': 'CPython', 'os_name': 'posix',
              'sys_platform': 'linux', 'platform_machine': 'x86_64',
              'platform_system': 'Linux', 'extra': ''}
MARKER_NAMES = set(MARKER_ENV) | {'platform_release', 'platform_version'}


class Rejected(ValueError):
    """Данные не удовлетворяют ограниченному контракту; обхода нет."""


def need(condition, message):
    if not condition:
        raise Rejected(message)


def canonical(name):
    need(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name),
         'invalid distribution name')
    return re.sub(r'[-_.]+', '-', name).lower()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_bounded(path, limit=MAX_METADATA):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit,
         'input file outside size/type contract')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    need(len(data) <= limit, 'input file exceeds budget')
    return data


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def parse_json(data):
    need(len(data) <= MAX_METADATA, 'JSON metadata too large')
    return json.loads(data, object_pairs_hook=no_duplicate_keys)


def safe_member(name):
    need(isinstance(name, str) and 0 < len(name) <= 512, 'invalid archive path')
    need(not any(c in name for c in ('\\', '\x00', ':')), 'unsafe archive path')
    parts = name.rstrip('/').split('/')
    need(not name.startswith('/') and all(x not in ('', '.', '..') for x in parts),
         'unsafe archive path')
    need(len(parts) <= 32, 'archive path too deep')
    return name.rstrip('/')


def local_file(root, relative, limit=MAX_FILE):
    safe_member(relative)
    path = root / relative
    need(root.is_dir() and not root.is_symlink(), 'invalid artifact root')
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        need(not cursor.is_symlink(), 'symlink artifact path')
    need(path.is_file() and path.stat().st_nlink == 1, 'missing or linked artifact')
    need(path.stat().st_size <= limit, 'file exceeds size limit')
    return path


def check_url(url, host):
    parsed = urllib.parse.urlsplit(url)
    need(parsed.scheme == 'https' and parsed.hostname == host and
         parsed.netloc == host and not parsed.username and not parsed.password and
         not parsed.query and not parsed.fragment and parsed.port is None,
         'URL outside exact HTTPS allowlist')
    need(parsed.path.startswith('/') and not any(x in parsed.path for x in ('\\', '\x00')),
         'invalid URL path')
    return url


def release_url(name, version):
    canonical(name)
    need(re.fullmatch(r'\d+(?:\.\d+)*', version) is not None, 'unsupported pinned version')
    return f'https://pypi.org/pypi/{canonical(name)}/{version}/json'


def numeric_version(value):
    need(re.fullmatch(r'\d+(?:\.\d+)*', value) is not None, 'unsupported version semantics')
    values = tuple(int(x) for x in value.split('.'))
    return values + (0,) * max(0, 5 - len(values))


def spec_parts(spec):
    if not spec:
        return []
    result = []
    for item in spec.split(','):
        match = re.fullmatch(r'\s*(~=|==|!=|<=|>=|<|>)\s*([A-Za-z0-9][A-Za-z0-9.!+*_\-]*)\s*', item)
        need(match is not None, 'unsupported version specifier')
        result.append(match.groups())
    return result


def satisfies(version, spec):
    """Только numeric release subset; неизвестная семантика отклоняется."""
    current = numeric_version(version)
    for op, other in spec_parts(spec):
        if other.endswith('.*'):
            need(op in ('==', '!='), 'unsupported wildcard operator')
            prefix = tuple(int(x) for x in other[:-2].split('.'))
            equal = current[:len(prefix)] == prefix
            ok = equal if op == '==' else not equal
        else:
            candidate = numeric_version(other)
            if op == '~=':
                pieces = [int(x) for x in other.split('.')]
                need(len(pieces) >= 2, 'invalid compatible release')
                upper = pieces[:-1]
                upper[-1] += 1
                ok = current >= candidate and current < numeric_version('.'.join(map(str, upper)))
            else:
                ok = {'==': current == candidate, '!=': current != candidate,
                      '>=': current >= candidate, '<=': current <= candidate,
                      '>': current > candidate, '<': current < candidate}[op]
        if not ok:
            return False
    return True


class Marker:
    """Ограниченная грамматика PEP 508, без eval и исполнения кода."""
    TOKEN = re.compile(r'''\s*(?:(?P<string>"[^"\\]*"|'[^'\\]*')|(?P<op>==|!=|<=|>=|~=|<|>)|(?P<word>[A-Za-z_][A-Za-z_0-9]*)|(?P<paren>[()]))''')

    def __init__(self, source):
        need(len(source) <= 4096, 'marker too large')
        self.tokens = []
        cursor = 0
        while cursor < len(source):
            match = self.TOKEN.match(source, cursor)
            need(match is not None, 'unsupported marker syntax')
            self.tokens.append((match.lastgroup, match.group(match.lastgroup)))
            cursor = match.end()
        self.index = 0
        self.tree = self.expression('or')
        need(self.index == len(self.tokens), 'trailing marker tokens')

    def take(self, value=None):
        if self.index < len(self.tokens) and (value is None or self.tokens[self.index][1] == value):
            token = self.tokens[self.index]
            self.index += 1
            return token
        return None

    def expression(self, level):
        lower = (lambda: self.expression('and')) if level == 'or' else self.atom
        result = lower()
        while self.take(level):
            result = (level, result, lower())
        return result

    def atom(self):
        if self.take('('):
            tree = self.expression('or')
            need(self.take(')') is not None, 'unclosed marker')
            return tree
        left = self.take()
        operator = self.take()
        need(left is not None and operator is not None, 'incomplete marker')
        op = operator[1]
        if op == 'not':
            need(self.take('in') is not None, 'unsupported marker operator')
            op = 'not in'
        need(op in ('==', '!=', '<=', '>=', '<', '>', '~=', 'in', 'not in'),
             'unsupported marker operator')
        right = self.take()
        need(right is not None, 'incomplete marker')
        need({left[0], right[0]} == {'word', 'string'}, 'unsupported marker operands')
        variable = left[1] if left[0] == 'word' else right[1]
        need(variable in MARKER_NAMES, 'unsupported marker variable')
        return (op, left, right)

    def evaluate(self, env):
        def walk(tree):
            op, a, b = tree
            if op in ('and', 'or'):
                # Проверяем обе ветки: неизвестное окружение не должно скрыться short circuit.
                x, y = walk(a), walk(b)
                return (x and y) if op == 'and' else (x or y)
            values = []
            variable = None
            for kind, token in (a, b):
                if kind == 'word':
                    need(token in env, 'marker environment unavailable')
                    variable = token
                    values.append(env[token])
                else:
                    values.append(token[1:-1])
            x, y = values
            if op == 'in':
                return x in y
            if op == 'not in':
                return x not in y
            if variable in ('python_version', 'python_full_version', 'implementation_version'):
                x, y = numeric_version(x), numeric_version(y)
            need(op != '~=', 'unsupported marker compatible-release evaluation')
            return {'==': x == y, '!=': x != y, '<=': x <= y,
                    '>=': x >= y, '<': x < y, '>': x > y}[op]
        return walk(self.tree)


def requirement(raw):
    need(isinstance(raw, str) and len(raw) <= 8192, 'invalid dependency declaration')
    pieces = raw.split(';', 1)
    match = re.fullmatch(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[([^\]]+)\])?\s*(.*?)\s*', pieces[0])
    need(match is not None, 'unsupported dependency declaration')
    name, extras, spec = match.groups()
    if spec.startswith('(') and spec.endswith(')'):
        spec = spec[1:-1].strip()
    spec_parts(spec)
    extras_list = [canonical(x.strip()) for x in extras.split(',')] if extras else []
    need(len(extras_list) == len(set(extras_list)), 'duplicate dependency extra')
    marker = pieces[1].strip() if len(pieces) == 2 else None
    if marker is not None:
        Marker(marker)
    return {'name': canonical(name), 'extras': sorted(extras_list), 'specifier': spec,
            'marker': marker}


def wheel_tags(filename, name, version):
    safe_member(filename)
    need('/' not in filename and filename.endswith('.whl'), 'invalid wheel filename')
    parts = filename[:-4].split('-')
    need(len(parts) in (5, 6), 'invalid wheel filename structure')
    need(canonical(parts[0]) == canonical(name) and parts[1] == version,
         'wheel filename identity mismatch')
    if len(parts) == 6:
        need(re.fullmatch(r'\d[A-Za-z0-9_]*', parts[2]) is not None, 'invalid wheel build tag')
    need(all(re.fullmatch(r'[A-Za-z0-9_.]+', x) for x in parts[-3:]), 'invalid wheel tags')
    return sorted('-'.join(t) for t in itertools.product(*(x.split('.') for x in parts[-3:])))


def tag_score(tag):
    py, abi, platform = tag.split('-')
    if py == 'cp313' and abi == 'cp313':
        interpreter = 300
    elif re.fullmatch(r'cp3\d+', py) and abi == 'abi3' and 32 <= int(py[2:]) <= 313:
        interpreter = 200 + int(py[2:])
    elif py in ('py3', 'py313', 'cp313') and abi == 'none':
        interpreter = 100
    else:
        return None
    if platform == 'any' and abi == 'none':
        return interpreter, 0, 0
    legacy = {'manylinux1_x86_64': (2, 5), 'manylinux2010_x86_64': (2, 12),
              'manylinux2014_x86_64': (2, 17)}
    match = re.fullmatch(r'manylinux_(\d+)_(\d+)_x86_64', platform)
    glibc = tuple(map(int, match.groups())) if match else legacy.get(platform)
    if glibc is None or glibc[0] != 2 or glibc > tuple(TARGET['glibc_ceiling']):
        return None
    return interpreter, *glibc


def advertised_record(data, name, version):
    need(isinstance(data, dict) and canonical(data['info']['name']) == canonical(name) and
         data['info']['version'] == version, 'release JSON identity mismatch')
    need(isinstance(data['urls'], list) and len(data['urls']) <= MAX_MEMBERS,
         'invalid release file list')
    names = set()
    records = []
    for item in data['urls']:
        filename = item['filename']
        safe_member(filename)
        need('/' not in filename and filename not in names, 'duplicate or unsafe advertised filename')
        names.add(filename)
        check_url(item['url'], 'files.pythonhosted.org')
        need(urllib.parse.unquote(urllib.parse.urlsplit(item['url']).path.rsplit('/', 1)[-1]) == filename,
             'URL filename mismatch')
        need(isinstance(item['size'], int) and not isinstance(item['size'], bool) and
             0 < item['size'] <= MAX_FILE, 'invalid advertised size')
        sha = item['digests']['sha256']
        need(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{64}', sha), 'invalid advertised digest')
        if item.get('yanked'):
            continue
        records.append({'filename': filename, 'url': item['url'], 'size': item['size'],
                        'sha256': sha, 'packagetype': item['packagetype'],
                        'requires_python': item.get('requires_python') or ''})
    return records


def select_artifact(data, name, version):
    records = advertised_record(data, name, version)
    candidates = []
    for record in records:
        if record['packagetype'] != 'bdist_wheel':
            continue
        tags = wheel_tags(record['filename'], name, version)
        scores = [tag_score(t) for t in tags if tag_score(t) is not None]
        if scores and satisfies(TARGET['python'], record['requires_python']):
            candidates.append((max(scores), record['filename'], record, tags))
    if candidates:
        # Явный детерминированный выбор; это не обещание выбора pip в целевой среде.
        _, _, record, tags = sorted(candidates, key=lambda x: (x[0], x[1]))[-1]
        return record, tags
    sources = [r for r in records if r['packagetype'] == 'sdist']
    need(len(sources) == 1 and canonical(name) == 'http-ece' and version == '1.2.1',
         'no compatible wheel; unapproved source-only fallback')
    need(sources[0]['filename'] == 'http_ece-1.2.1.tar.gz', 'unexpected source archive')
    return sources[0], []


def parsed_metadata(raw, name, version):
    need(len(raw) <= MAX_METADATA, 'archive metadata too large')
    msg = email.parser.BytesParser().parsebytes(raw)
    need(not msg.defects, 'malformed package metadata')
    for field in ('Name', 'Version', 'Metadata-Version'):
        need(len(msg.get_all(field, [])) == 1, 'missing or duplicate metadata identity')
    need(canonical(msg['Name']) == canonical(name) and msg['Version'] == version,
         'archive metadata identity mismatch')
    need(len(msg.get_all('Requires-Python', [])) <= 1, 'duplicate Requires-Python')
    rp = msg.get('Requires-Python', '')
    need(satisfies(TARGET['python'], rp), 'Requires-Python excludes declared target')
    deps = msg.get_all('Requires-Dist', [])
    for dep in deps:
        requirement(dep)
    return {'name': canonical(name), 'version': version, 'requires_python': rp,
            'requires_dist': deps, 'provides_extra': sorted(msg.get_all('Provides-Extra', []))}


def inspect_wheel(path, name, version):
    tags = wheel_tags(path.name, name, version)
    need(any(tag_score(t) is not None for t in tags), 'unsupported wheel target')
    # Ограничиваем central directory до его разбора zipfile; ZIP64 не нужен
    # для разрешённых небольших артефактов и отклоняется.
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65557))
        tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    need(offset >= 0 and len(tail) - offset >= 22, 'missing wheel ZIP directory')
    _, disk, start_disk, disk_count, count, size, _, comment = struct.unpack(
        '<4s4H2LH', tail[offset:offset+22])
    need(disk == start_disk == 0 and disk_count == count and count <= MAX_MEMBERS and
         size <= MAX_METADATA and len(tail) - offset == 22 + comment,
         'unsupported or oversized wheel ZIP directory')
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        need(len(members) <= MAX_MEMBERS, 'too many wheel members')
        names, expanded = set(), 0
        for member in members:
            key = safe_member(member.filename)
            need(key not in names, 'duplicate archive member')
            names.add(key)
            mode = member.external_attr >> 16
            need(not stat.S_ISLNK(mode) and not member.flag_bits & 1, 'linked or encrypted wheel member')
            need(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'special wheel member')
            expanded += member.file_size
            need(expanded <= MAX_EXPANDED, 'wheel expanded budget exceeded')
        dist_dirs = {x.split('/')[0] for x in names if x.split('/')[0].endswith('.dist-info')}
        need(len(dist_dirs) == 1, 'ambiguous wheel dist-info')
        folder = next(iter(dist_dirs))
        stem = folder[:-10].rsplit('-', 1)
        need(len(stem) == 2 and canonical(stem[0]) == canonical(name) and stem[1] == version,
             'dist-info identity mismatch')
        selected = [folder + '/METADATA', folder + '/WHEEL']
        need(all(x in names for x in selected), 'missing wheel metadata')
        need(size + sum(archive.getinfo(x).file_size for x in selected) <= MAX_METADATA,
             'archive metadata budget exceeded')
        blobs = {x.rsplit('/', 1)[-1]: archive.read(x) for x in selected}
    metadata = parsed_metadata(blobs['METADATA'], name, version)
    wheel = email.parser.BytesParser().parsebytes(blobs['WHEEL'])
    need(not wheel.defects and wheel.get_all('Wheel-Version') == ['1.0'], 'unsupported WHEEL version')
    declared_tags = wheel.get_all('Tag', [])
    need(len(declared_tags) == len(set(declared_tags)), 'duplicate WHEEL tag')
    expanded_tags = []
    for value in declared_tags:
        groups = value.split('-')
        need(len(groups) == 3, 'invalid WHEEL tag')
        expanded_tags.extend('-'.join(t) for t in itertools.product(*(x.split('.') for x in groups)))
    need(set(expanded_tags) == set(tags), 'WHEEL tags mismatch filename')
    metadata.update({'kind': 'wheel', 'tags': tags,
                     'metadata_sha256': {k: digest(v) for k, v in blobs.items()},
                     'declaration_validation': 'supported-subset-syntax-only-not-resolution'})
    return metadata


def inspect_sdist(path, name, version):
    selected, seen, roots, expanded = {}, set(), set(), 0
    with tarfile.open(path, mode='r|gz') as archive:
        for index, member in enumerate(archive):
            need(index < MAX_MEMBERS, 'too many sdist members')
            key = safe_member(member.name)
            need(key not in seen, 'duplicate archive member')
            seen.add(key)
            roots.add(key.split('/')[0])
            need(member.isfile() or member.isdir(), 'linked or special sdist member')
            expanded += member.size
            need(expanded <= MAX_EXPANDED, 'sdist expanded budget exceeded')
            parts = key.split('/')
            if member.isfile() and len(parts) == 2 and parts[-1] in ('PKG-INFO', 'pyproject.toml', 'setup.py', 'setup.cfg'):
                need(sum(map(len, selected.values())) + member.size <= MAX_METADATA,
                     'archive metadata budget exceeded')
                reader = archive.extractfile(member)
                need(reader is not None, 'unreadable sdist metadata')
                selected[parts[-1]] = reader.read(MAX_METADATA + 1)
    need(len(roots) == 1 and 'PKG-INFO' in selected, 'invalid sdist root or metadata')
    metadata = parsed_metadata(selected['PKG-INFO'], name, version)
    if 'pyproject.toml' in selected:
        project = tomllib.loads(selected['pyproject.toml'].decode('utf-8'))
        system = project.get('build-system')
        need(isinstance(system, dict) and isinstance(system.get('requires'), list),
             'unsupported build-system declaration')
        requires = system['requires']
        backend = system.get('build-backend', 'setuptools.build_meta:__legacy__')
        need(not system.get('backend-path'), 'in-tree backend requires separate review')
        basis = 'static-pyproject-only-dynamic-hooks-not-run'
    else:
        requires, backend = ['setuptools>=40.8.0'], 'setuptools.build_meta:__legacy__'
        basis = 'pip-implicit-legacy-backend-proposal-not-build-proof'
    for raw in requires:
        requirement(raw)
    literals = {}
    if 'setup.py' in selected:
        tree = ast.parse(selected['setup.py'].decode('utf-8'), filename='untrusted-setup.py')
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'setup':
                for kw in call.keywords:
                    if kw.arg in ('setup_requires', 'install_requires'):
                        try:
                            value = ast.literal_eval(kw.value)
                        except (ValueError, TypeError):
                            value = None
                        need(value is not None and isinstance(value, (list, tuple)),
                             'dynamic setup requirements need separate review')
                        need(kw.arg not in literals, 'duplicate setup declaration')
                        for raw in value:
                            requirement(raw)
                        literals[kw.arg] = list(value)
    metadata.update({'kind': 'sdist', 'metadata_sha256': {k: digest(v) for k, v in selected.items()},
                     'build_system': {'requires': requires, 'backend': backend, 'basis': basis,
                                      'setup_literals': literals, 'hooks_executed': False},
                     'blocker': 'source-only-runtime-wheel-must-be-built-and-hashed-by-root'})
    return metadata


def inspect_artifact(root, record, name, version):
    path = local_file(root, 'files/' + record['filename'])
    need(path.stat().st_size == record['size'], 'artifact size mismatch')
    need(digest(path.read_bytes()) == record['sha256'], 'artifact digest mismatch')
    if record['packagetype'] == 'bdist_wheel':
        return inspect_wheel(path, name, version)
    need(record['packagetype'] == 'sdist' and canonical(name) == 'http-ece' and version == '1.2.1',
         'unapproved source artifact')
    return inspect_sdist(path, name, version)


def require_wheels(entries):
    need(all(e['inspection']['kind'] == 'wheel' for e in entries if 'runtime' in e['roles']),
         'source-only runtime: complete wheel lock unavailable')


def source_inputs(receipt_path, requirements_path, baseline_path):
    raw = read_bounded(receipt_path)
    need(digest(raw) == RECEIPT_SHA256, 'frozen receipt checksum mismatch')
    receipt = parse_json(raw)
    need(receipt['sourceCommit'] == SOURCE_COMMIT and receipt['probe']['python'] == TARGET['python'],
         'frozen source or Python mismatch')
    observed = {}
    for name, version in receipt['probe']['dependencies']:
        name = canonical(name)
        need(name not in observed, 'duplicate observed distribution')
        numeric_version(version)
        observed[name] = version
    need(len(observed) == 60 and observed.get('pip') == TOOLING['pip'], 'unexpected observed inventory')
    requirements_data = read_bounded(requirements_path)
    need(len(requirements_data) == 530 and digest(requirements_data) == REQUIREMENTS_SHA256,
         'requirements input mismatch')
    declared = [requirement(s) for s in requirements_data.decode('utf-8').splitlines() if s and not s.startswith('#')]
    need(len(declared) == len({x['name'] for x in declared}) == 22 and
         sum(bool(x['extras']) for x in declared) == 3, 'direct requirements mismatch')
    need(all(x['name'] in observed and satisfies(observed[x['name']], x['specifier'])
             for x in declared), 'observed inventory excludes direct requirement')
    baseline_data = read_bounded(baseline_path)
    baseline = {}
    for line in baseline_data.decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        row = requirement(line)
        need(row['specifier'].startswith('==') and not row['extras'] and not row['marker'],
             'baseline must contain exact simple pins')
        need(row['name'] not in baseline, 'duplicate baseline distribution')
        baseline[row['name']] = row['specifier'][2:]
    need(baseline == {n: v for n, v in observed.items() if n != 'pip'}, 'baseline inventory mismatch')
    return observed, {'git_source': SOURCE_COMMIT, 'receipt_sha256': RECEIPT_SHA256,
                      'requirements_sha256': REQUIREMENTS_SHA256, 'requirements_bytes': 530,
                      'baseline_sha256': digest(baseline_data), 'runtime_distributions': 59,
                      'observed_distributions_including_pip': 60, 'direct_requirements': 22,
                      'declared_extras': 3}


def tooling_declarations(entries):
    lookup = {x['name']: x for x in entries}
    edges = []
    for name, version in sorted(TOOLING.items()):
        need(name in lookup and lookup[name]['version'] == version, 'missing pinned tooling artifact')
        for raw in lookup[name]['inspection']['requires_dist']:
            req = requirement(raw)
            active = not req['marker'] or Marker(req['marker']).evaluate(MARKER_ENV)
            if active:
                need(req['name'] in TOOLING and not req['extras'], 'tooling dependency plan incomplete')
                need(satisfies(TOOLING[req['name']], req['specifier']), 'tooling pin excludes declaration')
                edges.append({'from': name, 'to': req['name'], 'requirement': raw})
    return {'pins': TOOLING, 'active_metadata_edges': edges,
            'status': 'numeric-declarations-only-no-resolver-or-runtime-compatibility-pass',
            'activation': 'separate-clean-target-tooling-environment-required'}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, urllib.parse.urlsplit(req.full_url).hostname)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Fetcher:
    def __init__(self, root, deadline_seconds=900):
        need(root.name == 'dependency-artifacts' and root.parent.name == '.artifacts',
             'fetch output must be .artifacts/dependency-artifacts')
        need(not root.exists(), 'fetch directory exists; preserve prior evidence')
        need(1 <= deadline_seconds <= 900, 'deadline outside preparation budget')
        root.mkdir(parents=True, mode=0o700)
        self.root = root
        self.deadline = time.monotonic() + deadline_seconds
        self.opener = urllib.request.build_opener(SafeRedirect(),
                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self.log = root / 'download-events.jsonl'
        self.requests = 0

    def used(self):
        return sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())

    def event(self, value):
        data = (json.dumps(value, sort_keys=True) + '\n').encode()
        need((self.log.stat().st_size if self.log.exists() else 0) + len(data) <= MAX_LOG,
             'log budget exceeded')
        need(self.used() + len(data) <= MAX_TOTAL - MAX_METADATA, 'total budget exceeded')
        with self.log.open('ab') as stream:
            stream.write(data)

    def download(self, url, relative, limit, expected_size=None, expected_sha256=None):
        host = 'pypi.org' if relative.startswith('metadata/') else 'files.pythonhosted.org'
        check_url(url, host)
        need(time.monotonic() < self.deadline and self.requests < 160, 'request/deadline budget exceeded')
        self.requests += 1
        safe_member(relative)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        need(not path.exists() and not path.with_suffix(path.suffix + '.part').exists(), 'duplicate destination')
        partial = path.with_suffix(path.suffix + '.part')
        remaining = MAX_TOTAL - MAX_METADATA - self.used()
        need(remaining > 0 and (expected_size is None or expected_size <= remaining), 'total budget exceeded')
        bound = min(limit, remaining)
        data_hash, count = hashlib.sha256(), 0
        request = urllib.request.Request(url, headers={'User-Agent': 'dependency-artifact-preparation/1',
                                                       'Accept-Encoding': 'identity'})
        try:
            with self.opener.open(request, timeout=min(20, max(1, self.deadline-time.monotonic()))) as response:
                check_url(response.url, host)
                need(response.status == 200 and response.headers.get('Content-Encoding', 'identity') == 'identity',
                     'unexpected HTTP response')
                length = response.headers.get('Content-Length')
                if length is not None:
                    need(length.isdigit() and int(length) <= bound, 'HTTP size budget exceeded')
                    need(expected_size is None or int(length) == expected_size, 'advertised HTTP size mismatch')
                with partial.open('xb') as stream:
                    while True:
                        need(time.monotonic() < self.deadline, 'download deadline exceeded')
                        block = response.read(min(65536, bound-count+1))
                        if not block:
                            break
                        count += len(block)
                        need(count <= bound, 'download size limit exceeded')
                        data_hash.update(block)
                        stream.write(block)
            sha = data_hash.hexdigest()
            need(expected_size is None or count == expected_size, 'download size mismatch')
            need(expected_sha256 is None or sha == expected_sha256, 'download digest mismatch')
            partial.rename(path)
            self.event({'url': url, 'file': relative, 'bytes': count, 'sha256': sha, 'status': 'downloaded'})
            return {'path': relative, 'url': url, 'size': count, 'sha256': sha}
        except Exception as exc:
            self.event({'url': url, 'file': relative, 'status': 'failed', 'error_type': type(exc).__name__})
            raise


def prepare(args):
    observed, source = source_inputs(args.receipt, args.requirements, args.baseline)
    expected_root = Path.cwd() / '.artifacts/dependency-artifacts'
    need(args.root.absolute() == expected_root and expected_root.parent.resolve() == expected_root.parent,
         'fetch output outside workspace private artifact directory')
    pins = dict(observed)
    for name, version in TOOLING.items():
        need(name not in pins or pins[name] == version, 'tooling conflicts with observed pin')
        pins[name] = version
    fetcher = Fetcher(args.root, args.deadline_seconds)
    entries = []
    for name, version in sorted(pins.items()):
        meta = fetcher.download(release_url(name, version), f'metadata/{name}-{version}.json', MAX_METADATA)
        release = parse_json((args.root / meta['path']).read_bytes())
        record, _ = select_artifact(release, name, version)
        fetcher.download(record['url'], 'files/' + record['filename'], MAX_FILE,
                         record['size'], record['sha256'])
        inspection = inspect_artifact(args.root, record, name, version)
        roles = (['runtime'] if name in observed and name != 'pip' else [])
        if name == 'pip':
            roles.append('bootstrap')
        if name in TOOLING:
            roles.append('tooling')
        if name in ('setuptools', 'wheel', 'build', 'pyproject-hooks', 'packaging'):
            roles.append('source-build-plan')
        entries.append({'name': name, 'version': version, 'roles': roles,
                        'release_metadata': meta, 'artifact': record, 'inspection': inspection})
    plan = tooling_declarations(entries)
    log = fetcher.log.read_bytes()
    manifest = {'schema_version': 1, 'kind': 'dependency-artifact-preparation-not-lock',
                'target': TARGET, 'source': source, 'artifacts': entries, 'tooling_plan': plan,
                'limits': {'total_bytes': MAX_TOTAL, 'metadata_bytes_per_archive': MAX_METADATA,
                           'log_bytes': MAX_LOG, 'deadline_seconds': args.deadline_seconds},
                'evidence': {'download_log': {'path': fetcher.log.name, 'size': len(log), 'sha256': digest(log)},
                             'downloaded_files_and_metadata_bytes': fetcher.used(),
                             'requests': fetcher.requests},
                'not_run': ['resolver', 'build-backend', 'wheel-build', 'target-runtime',
                            'offline-install', 'pip-check', 'image-build', 'security-audit', 'exact-rebuild'],
                'blockers': [e['name'] + ': ' + e['inspection']['blocker'] for e in entries
                             if e['inspection']['kind'] == 'sdist']}
    output = args.root / 'manifest-proposal.json'
    data = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    need(len(data) <= MAX_METADATA and fetcher.used() + len(data) <= MAX_TOTAL, 'manifest budget exceeded')
    output.write_bytes(data)
    print(json.dumps({'status': 'preparation-only', 'artifacts': len(entries),
                      'bytes': fetcher.used(), 'manifest_sha256': digest(data),
                      'download_log_sha256': digest(log), 'blockers': manifest['blockers']}, ensure_ascii=False))


def verify(args):
    manifest_path = args.manifest
    need(manifest_path.stat().st_size <= MAX_METADATA, 'manifest too large')
    manifest = parse_json(manifest_path.read_bytes())
    observed, source = source_inputs(args.receipt, args.requirements, args.baseline)
    need(manifest['schema_version'] == 1 and manifest['kind'] == 'dependency-artifact-preparation-not-lock',
         'unsupported manifest schema or claim')
    need(manifest['source'] == source and manifest['target'] == TARGET, 'manifest source/target mismatch')
    need(set(manifest['not_run']) == {'resolver', 'build-backend', 'wheel-build', 'target-runtime',
                                     'offline-install', 'pip-check', 'image-build', 'security-audit', 'exact-rebuild'},
         'unsupported verification scope claim')
    pins = dict(observed, **TOOLING)
    entries = manifest['artifacts']
    seen = set()
    for entry in entries:
        name, version = entry['name'], entry['version']
        need(name == canonical(name) and name not in seen, 'duplicate or noncanonical distribution')
        seen.add(name)
        need(pins.get(name) == version, 'artifact pin mismatch')
        expected_roles = (['runtime'] if name in observed and name != 'pip' else [])
        if name == 'pip':
            expected_roles.append('bootstrap')
        if name in TOOLING:
            expected_roles.append('tooling')
        if name in ('setuptools', 'wheel', 'build', 'pyproject-hooks', 'packaging'):
            expected_roles.append('source-build-plan')
        need(entry['roles'] == expected_roles, 'artifact role mismatch')
        meta = entry['release_metadata']
        need(meta['path'] == f'metadata/{name}-{version}.json' and meta['url'] == release_url(name, version),
             'release metadata provenance mismatch')
        path = local_file(args.root, meta['path'], MAX_METADATA)
        raw = path.read_bytes()
        need(len(raw) == meta['size'] and digest(raw) == meta['sha256'], 'release metadata digest/size mismatch')
        record, _ = select_artifact(parse_json(raw), name, version)
        need(record == entry['artifact'], 'manifest selection differs from official metadata')
        need(inspect_artifact(args.root, record, name, version) == entry['inspection'],
             'artifact inspection mismatch')
    need(seen == set(pins), 'missing or additional artifact distribution')
    need(tooling_declarations(entries) == manifest['tooling_plan'], 'tooling declaration plan mismatch')
    blockers = [e['name'] + ': ' + e['inspection']['blocker'] for e in entries if e['inspection']['kind'] == 'sdist']
    need(manifest['blockers'] == blockers, 'missing preparation blocker')
    evidence = manifest['evidence']['download_log']
    need(evidence['path'] == 'download-events.jsonl', 'unexpected log path')
    log = local_file(args.root, evidence['path'], MAX_LOG).read_bytes()
    need(len(log) == evidence['size'] and digest(log) == evidence['sha256'], 'download log mismatch')
    expected_events = {}
    for entry in entries:
        meta, artifact = entry['release_metadata'], entry['artifact']
        for path, record in ((meta['path'], meta), ('files/' + artifact['filename'], artifact)):
            need(path not in expected_events, 'duplicate artifact file')
            expected_events[path] = {'file': path, 'url': record['url'], 'bytes': record['size'],
                                     'sha256': record['sha256'], 'status': 'downloaded'}
    actual_events = {}
    for line in log.splitlines():
        event = parse_json(line)
        need(event['status'] == 'downloaded' and event['file'] not in actual_events,
             'failed or duplicate download in preparation evidence')
        actual_events[event['file']] = event
    need(actual_events == expected_events, 'download log differs from selected artifacts')
    need(manifest['evidence']['requests'] == len(expected_events) and
         manifest['evidence']['downloaded_files_and_metadata_bytes'] ==
         sum(e['bytes'] for e in expected_events.values()) + len(log),
         'download accounting mismatch')
    limits = manifest['limits']
    need(limits['total_bytes'] == MAX_TOTAL and limits['metadata_bytes_per_archive'] == MAX_METADATA and
         limits['log_bytes'] == MAX_LOG and 1 <= limits['deadline_seconds'] <= 900,
         'manifest budget contract mismatch')
    size = 0
    for path in args.root.rglob('*'):
        need(not path.is_symlink(), 'symlink in private evidence')
        if path.is_file():
            size += path.stat().st_size
            if path.suffix in ('.log', '.jsonl'):
                need(path.stat().st_size <= MAX_LOG, 'private log budget exceeded')
    need(size <= MAX_TOTAL, 'private evidence total exceeds budget')
    if args.require_wheels:
        require_wheels(entries)
    print(json.dumps({'status': 'offline-artifact-inspection-only', 'artifacts': len(entries),
                      'runtime_wheels': sum('runtime' in e['roles'] and e['inspection']['kind'] == 'wheel' for e in entries),
                      'source_only': blockers, 'private_evidence_bytes': size}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('fetch', 'verify'):
        child = sub.add_parser(command)
        child.add_argument('--receipt', type=Path, required=True)
        child.add_argument('--requirements', type=Path, required=True)
        child.add_argument('--baseline', type=Path, required=True)
        child.add_argument('--root', type=Path, required=True)
        if command == 'fetch':
            child.add_argument('--deadline-seconds', type=int, default=900)
        else:
            child.add_argument('--manifest', type=Path, required=True)
            child.add_argument('--require-wheels', action='store_true')
    args = parser.parse_args()
    try:
        (prepare if args.command == 'fetch' else verify)(args)
    except (Rejected, OSError, ValueError, KeyError, TypeError, RecursionError,
            zipfile.BadZipFile, tarfile.TarError) as exc:
        # Не печатаем путь, credentials, HTTP body или содержимое недоверенного файла.
        print(json.dumps({'status': 'rejected', 'error_type': type(exc).__name__,
                          'reason': str(exc) if isinstance(exc, Rejected) else 'invalid input or transport failure'}))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
