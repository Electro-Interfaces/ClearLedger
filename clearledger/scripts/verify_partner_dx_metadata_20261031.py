"""Source-only metadata proof. Standard library; never imports application code.

Run with Python 3.11+: python3 <this file> [--write-proof] [--scope own|metadata].
Only git show/ls-files, source reads, AST/literal parsing, hashing and in-memory
compile are used. This does not export OpenAPI or execute/collect tests.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess


BASE = "cec2c9845431a0bc07e4b4f115eb21eed8d5caa9"
ROOT = Path(__file__).resolve().parents[2]
DTO = "clearledger/server/app/product_api/dto.py"
APP = "clearledger/server/app/product_api/app.py"
TOOL = "clearledger/scripts/verify_partner_dx_metadata_20261031.py"
TESTS = (
    "clearledger/server/tests/test_partner_dx_metadata_20261031.py",
    "clearledger/server/tests/test_partner_dx_examples_20261031.py",
)
PROOF = "clearledger/docs/api/PARTNER_DX_METADATA_SOURCE_20261031"
ALLOWED = {DTO, APP, TOOL, *TESTS, PROOF + ".json", PROOF + ".md"}
EXPECTED_OPERATIONS = {
    "listObjects": ("/objects", "objects"),
    "getObject": ("/objects/{objectId}", "objects"),
    "getObjectMonitoring": ("/objects/{objectId}/monitoring", "objects"),
    "listEquipment": ("/equipment", "equipment"),
    "getEquipment": ("/equipment/{equipmentId}", "equipment"),
    "listCounterparties": ("/counterparties", "counterparties"),
    "getCounterparty": ("/counterparties/{counterpartyId}", "counterparties"),
    "listContracts": ("/contracts", "contracts"),
    "getContractTypeMetadata": ("/contract-types", "contracts"),
    "getContract": ("/contracts/{contractId}", "contracts"),
    "listContractObjects": ("/contracts/{contractId}/objects", "contracts"),
    "listContractDocuments": ("/contracts/{contractId}/documents", "documents"),
    "listDocuments": ("/documents", "documents"),
    "getDocument": ("/documents/{docId}", "documents"),
    "downloadDocumentVersion": (
        "/documents/{docId}/versions/{versionId}/content", "documents"),
}


def git(*args):
    """Fixed, read-only Git commands; never a shell or application helper."""
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def base_source(path):
    return git("show", BASE + ":" + path).decode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def dump(node):
    return ast.dump(node, include_attributes=False)


def field_call(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Field"


def strip_field_docs(node, location, changes):
    """Only an explicitly selected field call; nested arbitrary calls stay intact."""
    assert field_call(node), location
    assert len({k.arg for k in node.keywords}) == len(node.keywords), location
    kept = []
    for keyword in node.keywords:
        if keyword.arg in {"description", "examples"}:
            value = ast.literal_eval(keyword.value)
            assert (isinstance(value, str) and value.strip() if keyword.arg == "description"
                    else isinstance(value, list) and bool(value)), location
            json.dumps(value, ensure_ascii=False, allow_nan=False)
            changes.append(location + "." + keyword.arg)
        else:
            kept.append(keyword)
    node.keywords = kept


def normalize_dto(base, current):
    """Preserve annotations, required/None distinctions, defaults and validators.

    A new Field with just docs is equivalent to a bare required AnnAssign.
    A new Field(default=<old value>, docs) is equivalent to that exact old value.
    No default_factory, alias, annotation or other keyword is discarded.
    """
    base_tree, tree = ast.parse(base), ast.parse(current)
    changes = []
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    for old_class in [n for n in base_tree.body if isinstance(n, ast.ClassDef)]:
        new_class = classes[old_class.name]
        fields = {n.target.id: n for n in new_class.body
                  if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        for old_field in [n for n in old_class.body if isinstance(n, ast.AnnAssign)]:
            new_field = fields[old_field.target.id]
            location = old_class.name + "." + old_field.target.id
            old_is_field = field_call(old_field.value)
            if old_is_field:
                strip_field_docs(old_field.value, location, [])
            if field_call(new_field.value):
                strip_field_docs(new_field.value, location, changes)
                if not old_is_field:
                    call = new_field.value
                    if old_field.value is None and not call.args and not call.keywords:
                        new_field.value = None
                    elif (old_field.value is not None and not call.args
                          and len(call.keywords) == 1 and call.keywords[0].arg == "default"):
                        # Keep the actual candidate default for the final AST equality.
                        new_field.value = call.keywords[0].value
    old_aliases = {n.targets[0].id: n for n in base_tree.body if isinstance(n, ast.Assign)
                   and isinstance(n.targets[0], ast.Name) and n.targets[0].id in {"Id", "ObjectId"}}
    aliases = {n.targets[0].id: n for n in tree.body if isinstance(n, ast.Assign)
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id in old_aliases}
    for name, old_alias in old_aliases.items():
        old_calls = [n for n in ast.walk(old_alias.value) if field_call(n)]
        calls = [n for n in ast.walk(aliases[name].value) if field_call(n)]
        assert len(old_calls) == len(calls) == 1, name
        strip_field_docs(old_calls[0], name, [])
        strip_field_docs(calls[0], name, changes)
    assert dump(tree) == dump(base_tree), "DTO runtime/wire AST changed outside Field description/examples"
    return {"normalizedSha256": digest(dump(tree).encode()), "whitelistLocations": changes,
            "requiredAndDefaultPreserved": True, "allOtherAstIdentical": True}


def operations(tree):
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_product_api")
    found = {}
    for handler in [n for n in factory.body if isinstance(n, ast.AsyncFunctionDef)]:
        for decorator in handler.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "operation"):
                name = ast.literal_eval(decorator.args[2])
                assert name not in found, name
                found[name] = (decorator, handler)
    assert set(found) == set(EXPECTED_OPERATIONS), "15 operation IDs must remain exact"
    for name, (call, _) in found.items():
        assert tuple(ast.literal_eval(n) for n in call.args[:2]) == EXPECTED_OPERATIONS[name], name
    return found


def keyword(call, name):
    values = [k for k in call.keywords if k.arg == name]
    assert len(values) <= 1, name
    return values[0] if values else None


def strip_success_docs(responses, *, binary, location, changes):
    """Remove only 200.description and 200.content.application/json.examples.

    Schema, headers, other statuses/media types and unknown keys remain in the
    AST comparison. Empty containers are removed only along this exact added
    JSON-examples path; binary schema is never removed or reconstructed here.
    """
    assert isinstance(responses, dict) and all(type(k) is int for k in responses), location
    if 200 not in responses:
        return responses
    success = responses[200]
    assert isinstance(success, dict), location
    if "description" in success:
        assert isinstance(success["description"], str) and success["description"].strip(), location
        del success["description"]
        changes.append(location + ".responses.200.description")
    content = success.get("content")
    if isinstance(content, dict) and "application/json" in content:
        assert not binary, "binary success must not have JSON metadata"
        media = content["application/json"]
        assert isinstance(media, dict), location
        if "examples" in media:
            examples = media.pop("examples")
            assert isinstance(examples, dict) and examples, location
            for example in examples.values():
                assert isinstance(example, dict) and set(example) <= {"summary", "description", "value"}, location
                assert isinstance(example.get("value"), dict), location
                assert all(isinstance(v, str) for k, v in example.items() if k != "value"), location
            json.dumps(examples, ensure_ascii=False, allow_nan=False)
            changes.append(location + ".responses.200.content.application/json.examples")
            if not media:
                del content["application/json"]
            if not content:
                del success["content"]
    if not success:
        del responses[200]
    return responses


def normalize_app(base, current):
    old_tree, tree = ast.parse(base), ast.parse(current)
    old_ops, new_ops = operations(old_tree), operations(tree)
    changes, inventory = [], []
    for name, (call, handler) in new_ops.items():
        old_call, old_handler = old_ops[name]
        old_body = deepcopy(old_handler)
        body = deepcopy(handler)
        old_body.decorator_list = body.decorator_list = []
        assert dump(old_body) == dump(body), "handler changed: " + name
        for selected, log in ((old_call, []), (call, changes)):
            kept = []
            for kw in selected.keywords:
                if kw.arg in {"summary", "description"}:
                    value = ast.literal_eval(kw.value)
                    assert isinstance(value, str) and value.strip(), name
                    log.append(name + "." + kw.arg)
                elif kw.arg == "responses":
                    values = strip_success_docs(ast.literal_eval(kw.value),
                        binary=name == "downloadDocumentVersion", location=name, changes=log)
                    if values:
                        kw.value = ast.parse(repr(values), mode="eval").body
                        kept.append(kw)
                else:
                    kept.append(kw)
            selected.keywords = kept
        resource = EXPECTED_OPERATIONS[name][1]
        inventory.append({"operationId": name, "path": EXPECTED_OPERATIONS[name][0],
            "method": "GET", "resource": resource,
            "principalRule": "PARTNER" if resource == "documents" else "PARTNER|SERVICE",
            "routeAndPolicyAstPreserved": True, "handlerAstPreserved": True,
            "handlerSha256": digest(dump(body).encode())})
    assert dump(old_tree) == dump(tree), "App AST changed outside exact operation documentation whitelist"
    return {"normalizedSha256": digest(dump(tree).encode()), "whitelistLocations": changes,
            "allOtherAstIdentical": True, "operations": inventory}


def response_examples(source):
    result = {}
    for name, (call, _) in operations(ast.parse(source)).items():
        response = ast.literal_eval(keyword(call, "responses").value)[200]
        result[name] = response
        assert ast.literal_eval(keyword(call, "summary").value).strip(), name
        assert ast.literal_eval(keyword(call, "description").value).strip(), name
        if name == "downloadDocumentVersion":
            assert response["content"] == {"application/octet-stream": {"schema": {
                "type": "string", "format": "binary"}}}, name
            assert "15 bytes" in response["description"] and "Fictional file +LF" in response["description"]
            for header in ("Content-Type", "Content-Disposition", "X-Content-Type-Options", "Cache-Control", "X-Request-Id"):
                assert header in response["description"], header
        else:
            assert set(response["content"]) == {"application/json"}, name
            examples = response["content"]["application/json"]["examples"]
            assert "fictional" in examples and isinstance(examples["fictional"]["value"], dict), name
    return result


def package_scope():
    """Separate strict seven-file scope check for this worker's own branch.

    Integrated source consumers can use source_evidence(scope="metadata") while
    their coordinator independently verifies its exact, larger package list.
    No broad docs glob or implicit acceptance of other runtime files is used.
    """
    changed = set(git("diff", "--name-only", BASE).decode().splitlines())
    untracked = set(git("ls-files", "--others", "--exclude-standard").decode().splitlines())
    assert changed | untracked <= ALLOWED, "Files outside exclusive ownership: " + repr(sorted((changed | untracked) - ALLOWED))
    return {"status": "PASS_OWN_EXACT_SEVEN_PATHS", "allowedFiles": sorted(ALLOWED),
            "changedOrNewFiles": sorted(changed | untracked)}


def source_evidence(*, scope="own"):
    assert scope in {"own", "metadata"}, scope
    current = {p: (ROOT / p).read_text(encoding="utf-8") for p in (DTO, APP)}
    baseline = {p: base_source(p) for p in (DTO, APP)}
    report = {"kind": "source-only-partner-dx-metadata", "baseCommit": BASE,
              "status": "SOURCE_ONLY", "runtimeAcceptance": "NOTRUN"}
    report["dtoAstProof"] = normalize_dto(baseline[DTO], current[DTO])
    report["operationAstProof"] = normalize_app(baseline[APP], current[APP])
    responses = response_examples(current[APP])
    report["exampleCoverage"] = {"json200Operations": sorted(set(responses) - {"downloadDocumentVersion"}),
        "binary200Operations": ["downloadDocumentVersion"],
        "futureDtoAndOpenapiValidation": "WRITTEN_NOTRUN"}
    report["files"] = {}
    for path in (DTO, APP, TOOL, *TESTS):
        raw = (ROOT / path).read_bytes()
        compile(raw, path, "exec", dont_inherit=True)  # syntax only, never executed
        report["files"][path] = {"sha256": digest(raw), "inMemorySyntaxCompile": "PASS"}
        if path in baseline:
            report["files"][path]["baseSourceSha256"] = digest(baseline[path].encode())
    # Protect the whole runtime implementation, including helpers and policy.
    protected = git("ls-files", "clearledger/server/app/product_api", "clearledger/server/app/api_contracts").decode().splitlines()
    report["protectedSources"] = {}
    for path in protected:
        if path in (DTO, APP):
            continue
        old = git("show", BASE + ":" + path)
        now = (ROOT / path).read_bytes()
        assert old == now, "Protected runtime source changed: " + path
        report["protectedSources"][path] = {"sha256": digest(now), "baseSourceSha256": digest(old), "byteIdentical": True}
    # Includes committed changes and untracked paths, separate from AST proof.
    report["scope"] = package_scope() if scope == "own" else {
        "status": "NOT_CHECKED_INTEGRATED_PACKAGE", "metadataAndProtectedSourcesChecked": True,
        "note": "Coordinator must check its own exact package allowlist separately."}
    report["writtenNotRunTests"] = {}
    for path in TESTS:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        report["writtenNotRunTests"][path] = [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    report["limitations"] = [
        "Application, helpers and frameworks were not imported or executed.",
        "No pytest execution/collection, OpenAPI export, generated types, Node, codegen or dependency changes.",
        "No HTTP, SQL, Docker, SSH, browser, pilots, flags, workflows, billing or deployment.",
        "DTO/schema validation tests are written for a future separately approved ROOT run, NOTRUN here.",
        "All 20 modernization milestones and 11 gates remain unproven outside this source package.",
        "Examples are fictional source documentation, not recorded server responses or evidence of file availability.",
        "Proof JSON/Markdown hashes are intentionally excluded from their own recursive manifest; Git commit identifies them.",
    ]
    return report


def write_proof(report):
    (ROOT / (PROOF + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = """# Partner DX: доказательство по исходникам, 31.10.2026

Статус: **SOURCE_ONLY**, runtime-приёмка **NOTRUN**. База: `{base}`.
Изменены только Field descriptions/examples и documentation metadata 15 существующих GET.
14 JSON 200 имеют полные вымышленные примеры; download описывает 15 ASCII bytes
`Fictional file` + LF, application/octet-stream и пример заголовков без JSON body.

AST-сравнение сохраняет все аннотации, aliases, required/nullable/default, min/max,
regex, validators, operation IDs, paths, response_model, schemas, response headers,
principals, scopes, grants, tenant/file policy, обработчики и общий operation helper.
Нормализуются только конкретные Field description/examples и summary/description,
200.description и 200.content.application/json.examples конкретных операций.
Остальные ключи responses/kwargs не исключаются из сравнения. Required AnnAssign
без default отличается от default=None. Всё вне whitelist совпадает по AST;
защищённые product_api/api_contracts исходники совпадают побайтно.

Новые тесты проверяют сохранение runtime/wire/policy по базе, отрицательные мутации
normalizer, будущую валидацию полных examples действительными DTO и OpenAPI schemas,
required-nullable поля, типы, ограничения ID и provenance. Тесты **WRITTEN_NOTRUN**;
pytest и collection не запускались. Выполнены только stdlib source checker,
AST/literal/hash-анализ и in-memory compile без исполнения компилированного кода.

Точные SHA-256 новых/изменённых Python-файлов, base source SHA, whitelist locations,
15 operation IDs/правила principals и hashes protected sources: соседний JSON.
Сами proof-файлы исключены из рекурсивного hash manifest; их фиксирует Git commit.

Повторить source proof в собственной ветке: `python3
clearledger/scripts/verify_partner_dx_metadata_20261031.py --write-proof`.
По умолчанию отдельно проверяются ровно семь разрешённых путей всей дельты к базе.
В общей ветке `--scope metadata` сохраняет AST/hash-проверку runtime и сообщает
`NOT_CHECKED_INTEGRATED_PACKAGE`; точный общий состав отдельно проверяет координатор.
Тесты нормализации вызывают AST proof отдельно от проверки состава пакета.

Все 20M и 11 gates остаются unproven вне этого пакета. Приложение, helpers и
frameworks не импортировались; OpenAPI exporter/types/Node/codegen, HTTP/SQL,
Docker/SSH/browser, pilots/deps/flags/workflows/billing/deploy не запускались.
Публикация, push, PR и merge не выполнялись. Примеры вымышлены и не доказывают
доступность API, файлов, прав или какой-либо рабочей среды.
""".format(base=BASE)
    (ROOT / (PROOF + ".md")).write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-proof", action="store_true")
    parser.add_argument("--scope", choices=("own", "metadata"), default="own")
    args = parser.parse_args()
    report = source_evidence(scope=args.scope)
    if args.write_proof:
        # Include the two proof paths consistently on the first and later run.
        if args.scope == "own":
            report["scope"]["changedOrNewFiles"] = sorted(set(report["scope"]["changedOrNewFiles"]) | {PROOF + ".json", PROOF + ".md"})
        write_proof(report)
    print(json.dumps({"status": "PASS_SOURCE_ONLY", "baseCommit": BASE,
        "operations": len(report["operationAstProof"]["operations"]),
        "documentedFieldsAndAliases": len(report["dtoAstProof"]["whitelistLocations"]) // 2,
        "syntaxCompile": "PASS", "scope": report["scope"]["status"],
        "tests": "WRITTEN_NOTRUN", "runtime": "NOTRUN"}))


if __name__ == "__main__":
    main()
