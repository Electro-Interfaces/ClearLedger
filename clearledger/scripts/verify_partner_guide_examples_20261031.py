"""Read guide examples against immutable DTO source; no application imports.

This is a limited source/document checker, NOT Pydantic/OpenAPI validation,
test execution, schema generation or HTTP conformance. Standard library only.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, urlsplit

BASE = 'cec2c9845431a0bc07e4b4f115eb21eed8d5caa9'
ROOT = Path(__file__).resolve().parents[2]
DOCS = (
    'onboarding.md', 'auth.md', 'data-dictionary.md', 'errors.md',
    'recipes/read-catalogs.md', 'recipes/contracts.md',
    'recipes/monitoring.md', 'recipes/documents.md',
)
DTO_PATH = 'clearledger/server/app/product_api/dto.py'
APP_PATH = 'clearledger/server/app/product_api/app.py'


def original(path):
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':' + path]).decode()


def short_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    raise AssertionError('Unsupported type node: ' + ast.dump(node))


def wire_name(name):
    parts = name.split('_')
    return parts[0] + ''.join(x[:1].upper() + x[1:] for x in parts[1:])


class SourceDTO:
    """Explicit limited AST grammar, with no exec/eval/import of source modules."""

    def __init__(self, text):
        tree = ast.parse(text)
        self.classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        self.aliases = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in {'Id', 'ObjectId'}:
                    assert isinstance(node.value, ast.Call)
                    self.aliases[name] = node.value.args[1]

    def fields(self, name):
        cls = self.classes[name]
        result = {}
        for base in cls.bases:
            if isinstance(base, ast.Name) and base.id in self.classes:
                result.update(self.fields(base.id))
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                result[wire_name(node.target.id)] = node
        return result

    def check(self, annotation, value, location='$', bindings=None):
        bindings = bindings or {}
        if isinstance(annotation, ast.Name) and annotation.id in bindings:
            annotation = bindings[annotation.id]
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            errors = []
            for part in (annotation.left, annotation.right):
                try:
                    self.check(part, value, location, bindings)
                    return
                except (AssertionError, ValueError, TypeError) as error:
                    errors.append(str(error))
            raise AssertionError(location + ' does not match union: ' + repr(errors))
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            assert value is None, location + ': expected null'
            return
        if isinstance(annotation, ast.Subscript):
            kind = short_name(annotation.value)
            parts = list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
            if kind == 'Annotated':
                self.check(parts[0], value, location, bindings)
                for constraint in parts[1:]:
                    if isinstance(constraint, ast.Call) and short_name(constraint.func) == 'Field':
                        self.constraints(constraint, value, location)
                return
            if kind == 'Literal':
                literals = [ast.literal_eval(x) for x in parts]
                assert any(type(value) is type(x) and value == x for x in literals), location + ': literal mismatch'
                return
            if kind == 'list':
                assert type(value) is list, location + ': expected array'
                for index, item in enumerate(value):
                    self.check(parts[0], item, f'{location}[{index}]', bindings)
                return
            if kind == 'Page':
                self.model('Page', value, location, {'T': parts[0]})
                return
            raise AssertionError('Unsupported generic: ' + kind)
        name = short_name(annotation)
        if name in self.aliases:
            self.check(self.aliases[name], value, location, bindings)
        elif name in self.classes:
            self.model(name, value, location, bindings)
        elif name == 'str':
            assert type(value) is str, location + ': expected string'
        elif name == 'int':
            assert type(value) is int, location + ': expected integer'
        elif name == 'float':
            assert type(value) in (int, float), location + ': expected JSON number'
        elif name == 'bool':
            assert type(value) is bool, location + ': expected boolean'
        elif name == 'date':
            assert type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), location + ': expected ISO date'
            date.fromisoformat(value)
        elif name == 'datetime':
            assert type(value) is str, location + ': expected datetime string'
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            raise AssertionError('Unsupported annotation: ' + name)

    @staticmethod
    def constraints(call, value, location):
        if value is None:
            return
        for kw in call.keywords:
            if kw.arg not in {'min_length', 'max_length', 'pattern', 'ge', 'le', 'gt', 'lt'}:
                continue
            bound = ast.literal_eval(kw.value)
            if kw.arg == 'min_length':
                assert len(value) >= bound, location + ': min_length'
            elif kw.arg == 'max_length':
                assert len(value) <= bound, location + ': max_length'
            elif kw.arg == 'pattern':
                assert re.search(bound, value), location + ': pattern'
            elif kw.arg == 'ge':
                assert value >= bound, location + ': ge'
            elif kw.arg == 'le':
                assert value <= bound, location + ': le'
            elif kw.arg == 'gt':
                assert value > bound, location + ': gt'
            elif kw.arg == 'lt':
                assert value < bound, location + ': lt'

    def model(self, name, value, location, bindings):
        assert type(value) is dict, location + ': expected object ' + name
        fields = self.fields(name)
        # Guide examples promise complete DTOs, including optional defaulted fields.
        assert set(value) == set(fields), (location, name, 'missing', set(fields)-set(value), 'extra', set(value)-set(fields))
        for key, node in fields.items():
            self.check(node.annotation, value[key], location + '.' + key, bindings)
            if isinstance(node.value, ast.Call) and short_name(node.value.func) == 'Field':
                self.constraints(node.value, value[key], location + '.' + key)


def declarations(text):
    result = {}
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == 'operation':
                path, resource, operation = [ast.literal_eval(x) for x in dec.args[:3]]
                result[operation] = {'path': path, 'resource': resource,
                    'model': dec.args[3] if len(dec.args) > 3 else None, 'line': dec.lineno}
    assert len(result) == 15
    return result


def verify(guide_root):
    dto = SourceDTO(original(DTO_PATH))
    operations = declarations(original(APP_PATH))
    seen, links, json_count = {}, 0, 0
    records = []
    for relative in DOCS:
        path = guide_root / relative
        text = path.read_text()
        for body in re.findall(r'^```json\s*\n(.*?)^```', text, re.M | re.S):
            json.loads(body)
            json_count += 1
        without_fences = re.sub(r'^```.*?^```', '', text, flags=re.M | re.S)
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', without_fences):
            if re.match(r'^(https?://|#|mailto:)', target):
                continue
            assert (path.parent / target.split('#')[0]).exists(), (relative, target)
            links += 1
        regions = re.findall(r'<!-- operation:([A-Za-z0-9]+) -->\s*(.*?)<!-- /operation:\1 -->', text, re.S)
        for operation, region in regions:
            assert operation in operations and operation not in seen, operation
            declaration = operations[operation]
            request = re.search(r'^GET (/api/v1/\S+) HTTP/1\.1$', region, re.M)
            assert request, (operation, 'missing full HTTP GET request')
            uri = urlsplit(request[1])
            pattern = re.sub(r'\{[^}]+\}', '[^/]+', declaration['path'])
            assert re.fullmatch('/api/v1' + pattern, uri.path), (operation, uri.path)
            assert 'Host: sandbox.example.invalid' in region
            assert re.search(r'^Authorization: Bearer <[^>]+PLACEHOLDER>$', region, re.M), operation
            assert re.search(r'^HTTP/1\.1 200 ', region, re.M), operation
            assert re.search(r'^HTTP/1\.1 [45][0-9]{2} ', region, re.M), (operation, 'missing refusal')
            payloads = [json.loads(x) for x in re.findall(r'^```json\s*\n(.*?)^```', region, re.M | re.S)]
            denials = [x for x in payloads if isinstance(x, dict) and type(x.get('status')) is int and x['status'] >= 400]
            assert denials, (operation, 'missing full Problem JSON')
            for denial in denials:
                dto.check(ast.Name(id='Problem'), denial, operation + '.denial')
            successes = [x for x in payloads if x not in denials]
            if declaration['model'] is None:
                assert not successes, (operation, 'binary must not pretend to be a JSON DTO')
                assert 'Content-Type: application/octet-stream' in region
                assert 'Fictional file\n' in region, 'binary illustration expected'
            else:
                assert successes, (operation, 'missing full success JSON')
                for payload in successes:
                    dto.check(declaration['model'], payload, operation + '.success')
            if operation == 'getContractTypeMetadata':
                assert dict(parse_qsl(uri.query)).get('typeCode'), operation
            seen[operation] = relative
            records.append({'operationId': operation, 'guide': relative,
                'source_decorator_line': declaration['line'], 'json_successes': len(successes),
                'problem_examples': len(denials), 'binary': declaration['model'] is None})
    assert set(seen) == set(operations), ('missing guide regions', set(operations)-set(seen))
    return {'kind': 'source/document examples check; no framework/application execution',
        'baseline': BASE, 'guide_pages': len(DOCS), 'operations': len(seen),
        'local_links': links, 'json_blocks': json_count, 'examples': records,
        'limitations': ['limited explicit AST grammar, not Pydantic coercion/schema validation',
            'not OIDC, HTTP, policy execution, binary download or partner acceptance'],
        'files': [{'path': str(Path('clearledger/docs/partner') / x),
                   'sha256': hashlib.sha256((guide_root / x).read_bytes()).hexdigest()} for x in DOCS]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guide-root', type=Path, default=ROOT / 'clearledger/docs/partner')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.guide_root)
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('kind', 'baseline', 'guide_pages', 'operations', 'local_links', 'json_blocks')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
