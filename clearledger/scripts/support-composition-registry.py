#!/usr/bin/env python3
"""ROOT-only, stdlib reconciliation of eight immutable Express registration captures.

No application import, JS evaluation, request, dependency traversal or discovery.
Full readable composition trees are retained; coordinates are ordinary JSON index
paths, not a serialization codec. Request dispatch and ACL conformance are unknown.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import signal
import subprocess
import sys


CONTRACT_SHA256 = "b158fb5afe427282b746891593316201a498fe75b6d3e3f657c620194806e9ba"
PLAN = Path(__file__).resolve().parents[1] / "docs/api/SUPPORT_ACTUAL_SURFACES_20261031.json"
ROOT_REPO = Path("/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029")
SUPPORT_REPO = Path("/home/mag/orca/workspaces/tsupport/api-support-app-composition-20261031")
EVIDENCE = ROOT_REPO / ".artifacts/root-support-surface-reconciliation-20261031"
HEX = re.compile(r"[0-9a-f]{64}\Z")
HTTP = frozenset("acl bind checkout connect copy delete get head link lock m-search merge mkactivity mkcalendar mkcol move notify options patch post propfind proppatch purge put query rebind report search source subscribe trace unbind unlink unlock unsubscribe".split())
LAYER_KEYS = {"index", "registrationOrdinal", "path", "mountChain", "routePath", "methods", "keys", "slash", "handler", "children"}
HANDLER_KEYS = {"name", "arity", "sha256", "registrationSource", "definitionSource", "definitionCandidates", "unresolved"}
REG_KEYS = {"ordinal", "method", "layerKind", "path", "source", "added"}
LEAF_KEYS = {"schemaVersion", "status", "variant", "sourceIdentity", "nodeIdentity", "registrations", "stack", "totalLayers", "intrinsicLayers", "receiverCount", "reads", "loaded", "denied", "readFD", "environmentAudit", "limitations"}


def require(test, reason):
    if not test:
        raise ValueError(reason)


def encoded(value):
    # Field insertion order is part of the frozen artifact; arrays are never sorted.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    require(isinstance(value, str) and HEX.fullmatch(value), "sha256")
    return value


def integer(value, minimum=0, maximum=12000):
    require(type(value) is int and minimum <= value <= maximum, "integer")


def keys(value, expected, reason):
    require(type(value) is dict and set(value) == set(expected), reason)


def relative(value):
    require(type(value) is str and 0 < len(value) <= 512, "relative_path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and p.as_posix() == value and not any(x in (".", "..") or x.startswith(".") for x in p.parts), "relative_path")
    require("\\" not in value and "\x00" not in value and ":" not in value, "relative_path")
    return value


def no_duplicate_keys(pairs):
    out = {}
    for name, value in pairs:
        require(name not in out, "duplicate_json_key")
        out[name] = value
    return out


def decode(raw):
    return json.loads(raw, object_pairs_hook=no_duplicate_keys,
                      parse_constant=lambda _: require(False, "nonfinite_json"))


def read_exact(root, entry, limit):
    name = entry["path"]
    # Artifact dot-directory is a literal reviewed prefix, not arbitrary glob input.
    require(type(name) is str and name.startswith(".artifacts/") and ".." not in PurePosixPath(name).parts, "artifact_path")
    path = root / name
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), "artifact_file")
    size = path.stat().st_size
    require(path.stat().st_uid == os.getuid(), "input_owner")
    require(size == entry["bytes"] and size <= limit, "input_bytes")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) == size and sha(raw) == digest(entry["sha256"]), "input_sha256")
    return decode(raw)


def git(repo, *arguments, input_bytes=None):
    # Read-only builtins only. No inherited Git config, aliases, pager, fsmonitor,
    # alternates supplied by environment, hooks, shell or credential helper.
    require(arguments[0] in {"show", "cat-file"}, "git_operation")
    result = subprocess.run(
        ["/usr/bin/git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *arguments],
        input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=20, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-support-registry", "LANG": "C.UTF-8",
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"})
    require(len(result.stdout) <= 64 * 1024 * 1024 and len(result.stderr) <= 65536, "git_output")
    return result.stdout


def blobs(repo, pin, files, contents=None):
    require(re.fullmatch(r"[0-9a-f]{40}", pin), "git_pin")
    names = list(files)
    raw = git(repo, "cat-file", "--batch", input_bytes="".join(f"{pin}:{relative(p)}\n" for p in names).encode())
    offset, out = 0, {}
    for name in names:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        require(len(header) == 3 and header[1] == b"blob", "git_blob")
        size = int(header[2])
        require(0 <= size <= 4 * 1024 * 1024, "git_blob_size")
        start = end + 1
        content = raw[start:start + size]
        require(len(content) == size and raw[start + size:start + size + 1] == b"\n", "git_blob_frame")
        oid = hashlib.sha1(b"blob " + str(size).encode() + b"\0" + content).hexdigest()
        require(oid == header[0].decode(), "git_blob_oid")
        out[name] = {"gitBlobSHA1": oid, "bytes": size, "sha256": sha(content)}
        if contents is not None:
            contents[name] = content
        offset = start + size + 1
    require(offset == len(raw), "git_batch_tail")
    return out


def path_value(value, depth=0):
    require(type(value) is dict and depth <= 8, "typed_path")
    kind = value.get("kind")
    if kind == "string":
        keys(value, {"kind", "value"}, "string_path_keys")
        require(type(value["value"]) is str and len(value["value"]) <= 4096 and "\x00" not in value["value"], "string_path")
    elif kind == "array":
        keys(value, {"kind", "values"}, "array_path_keys")
        require(type(value["values"]) is list and 0 < len(value["values"]) <= 32, "array_path")
        for item in value["values"]:
            path_value(item, depth + 1)
    elif kind == "regexp":
        keys(value, {"kind", "source", "flags"}, "regexp_keys")
        require(type(value["source"]) is str and len(value["source"]) <= 4096 and type(value["flags"]) is str and len(value["flags"]) <= 16, "regexp_path")
    elif kind == "undefined":
        keys(value, {"kind"}, "undefined_keys")
    elif kind == "unresolved":
        keys(value, {"kind", "type"}, "unresolved_keys")
        require(type(value["type"]) is str and 0 < len(value["type"]) <= 80, "unresolved_path")
    else:
        require(False, "typed_path_kind")


def frame_sources(value):
    require(type(value) is list and len(value) <= 32, "frame_sources")
    for frame in value:
        require(type(frame) is str and len(frame) <= 4096 and "\x00" not in frame, "frame_source")
        require("/work/source/" in frame or "/work/node_modules/" in frame, "frame_scope")
        found = re.search(r"/work/(?:source|node_modules)/([^\s():]+):(\d+):(\d+)", frame)
        require(found is not None, "frame_coordinate")
        relative(found[1])
        integer(int(found[2]), 1, 1000000)
        integer(int(found[3]), 1, 1000000)


def definition(value, source_files, dependencies):
    keys(value, {"file", "line", "fileSHA256", "match"}, "definition_keys")
    file = value["file"]
    integer(value["line"], 1, 1000000)
    digest(value["fileSHA256"])
    require(value["match"] == "exact Function.toString source text", "definition_match")
    require(type(file) is str, "definition_file")
    if file.startswith("/work/source/"):
        name = relative(file.removeprefix("/work/source/"))
        require(name in source_files and source_files[name]["sha256"] == value["fileSHA256"], "definition_source_sha")
    elif file.startswith("/work/node_modules/"):
        name = relative(file.removeprefix("/work/node_modules/"))
        require(dependencies.get(name) == value["fileSHA256"], "definition_dependency_sha")
    else:
        require(False, "definition_scope")


def validate_tree(stack, registrations, source_files, dependencies):
    require(type(registrations) is list and 0 < len(registrations) <= 12000, "registrations")
    for i, reg in enumerate(registrations):
        keys(reg, REG_KEYS, "registration_keys")
        integer(reg["ordinal"])
        require(reg["ordinal"] == i, "registration_ordinal")
        kind = reg["layerKind"]
        require((kind == "mount" and reg["method"] == "use") or (kind == "route" and reg["method"] == "route") or
                (kind == "routeHandler" and reg["method"] in HTTP | {"all"}), "registration_method")
        integer(reg["added"], 1, 12000)
        path_value(reg["path"])
        frame_sources(reg["source"])
    total, seen = 0, set()

    def walk(layers, chain, indices):
        nonlocal total
        require(type(layers) is list and len(indices) <= 32, "stack")
        for i, layer in enumerate(layers):
            total += 1
            require(total <= 12000, "layer_limit")
            keys(layer, LAYER_KEYS, "layer_keys")
            integer(layer["index"])
            require(layer["index"] == i, "layer_index")
            ordinal = layer["registrationOrdinal"]
            integer(ordinal)
            require(ordinal < len(registrations), "layer_ordinal")
            seen.add(ordinal)
            reg = registrations[ordinal]
            require(layer["path"] == reg["path"] and layer["mountChain"] == chain, "layer_path_chain")
            path_value(layer["path"])
            require(type(layer["methods"]) is list and len(layer["methods"]) == len(set(layer["methods"])) and all(m in HTTP | {"_all"} for m in layer["methods"]), "layer_method")
            if layer["routePath"] is not None:
                path_value(layer["routePath"])
                require(reg["layerKind"] == "route" and layer["routePath"] == reg["path"] and len(layer["methods"]) > 0, "route_layer")
            elif reg["layerKind"] == "routeHandler":
                # Route.all records an undefined intrinsic layer.method, hence
                # raw methods=[]; the registration record supplies symbolic all.
                require(layer["methods"] == ([] if reg["method"] == "all" else [reg["method"]]), "handler_method")
            else:
                require(reg["layerKind"] == "mount" and layer["methods"] == [], "mount_method")
            require(type(layer["keys"]) is list and (layer["slash"] is None or type(layer["slash"]) is bool), "layer_intrinsics")
            h = layer["handler"]
            keys(h, HANDLER_KEYS, "handler_keys")
            require(h["name"] is None or type(h["name"]) is str, "handler_name")
            integer(h["arity"], 0, 64)
            digest(h["sha256"])
            frame_sources(h["registrationSource"])
            require(h["registrationSource"] == reg["source"], "handler_registration_provenance")
            require(type(h["definitionCandidates"]) is list and len(h["definitionCandidates"]) <= 17, "definition_candidates")
            if h["definitionSource"] is not None:
                require(h["definitionCandidates"] == [] and h["unresolved"] is None, "known_definition")
                definition(h["definitionSource"], source_files, dependencies)
            else:
                require(h["unresolved"] == "definition text missing or ambiguous; registration frame is not definition location" and len(h["definitionCandidates"]) != 1, "unknown_definition")
            for candidate in h["definitionCandidates"]:
                definition(candidate, source_files, dependencies)
            children = layer["children"]
            if type(children) is list:
                walk(children, chain + [reg["path"]], indices + [i])
                if layer["routePath"] is not None:
                    require(all(c["routePath"] is None and registrations[c["registrationOrdinal"]]["layerKind"] == "routeHandler" for c in children), "route_children")
                    require(set(layer["methods"]) == {m for c in children for m in (c["methods"] or ["_all"])}, "route_methods_children")
            elif children is not None:
                require(children == {"unresolved": "cycle"}, "children_unknown")
    walk(stack, [], [])
    require(seen == set(range(len(registrations))), "registration_coverage")
    return total


def admit_manifest(entries):
    require(type(entries) is list and len(entries) == 8, "manifest_eight")
    for i, e in enumerate(entries):
        require(type(e["originalId"]) is int and e["originalId"] == i, "manifest_original_id")
        require(e["series"] == ("V10" if i < 6 else "V12"), "manifest_series")
        require(e["variant"] == {"context": bool(i & 2), "dist": bool(i & 1), "identity": "local" if i < 4 else "core"}, "manifest_variant")
        require(all(type(e["variant"][k]) is bool for k in ("context", "dist")), "manifest_boolean")
        digest(e["sha256"])
        integer(e["bytes"], 1, 4194304)
    require(len({e["sha256"] for e in entries}) == 8 and sum(e["bytes"] for e in entries) <= 33554432, "manifest_distinct_budget")


def admit_leaf(d, entry, source_files, dependencies):
    keys(d, LEAF_KEYS, "leaf_keys")
    require(d["schemaVersion"] == 1 and d["status"] == "EXPORTED_REGISTRATION_ONLY", "leaf_status")
    for name in ("variant", "sourceIdentity", "nodeIdentity", "environmentAudit", "readFD"):
        require(d[name] == entry[name], "leaf_" + name)
    require(d["denied"] == [] and d["readFD"]["active"] == 0 and d["environmentAudit"]["unchanged"] is True and d["environmentAudit"]["objectIdentityPreserved"] is True, "leaf_boundary")
    require(d["totalLayers"] == entry["layerCount"] and d["intrinsicLayers"] == entry["intrinsicLayers"] and d["receiverCount"] == entry["receiverCount"], "leaf_counts")
    require(len(d["registrations"]) == entry["registrationCount"] and sha(encoded(d["stack"])) == entry["stackSHA256"] and sha(encoded(d["registrations"])) == entry["registrationsSHA256"], "leaf_tree_identity")
    require(sum(r["added"] for r in d["registrations"]) == d["intrinsicLayers"], "leaf_intrinsic_coverage")
    count = validate_tree(d["stack"], d["registrations"], source_files, dependencies)
    require(count == d["totalLayers"], "leaf_total")
    require(type(d["reads"]) is list and type(d["loaded"]) is list and type(d["limitations"]) is list, "leaf_proof_lists")
    require(entry["proof"] == {"status": d["status"], "denied": d["denied"], "readsCount": len(d["reads"]), "readsSHA256": sha(encoded(d["reads"])), "loadedCount": len(d["loaded"]), "loadedSHA256": sha(encoded(d["loaded"])), "limitations": d["limitations"]}, "leaf_proof_identity")


def alternatives(path):
    if path["kind"] == "array":
        return [v for item in path["values"] for v in alternatives(item)]
    return [path]


def patterns(parts):
    # String concatenation at mount boundaries only; no regex parsing, URL
    # normalization, parameter renaming, case folding or overlap inference.
    choices = list(itertools.product(*(alternatives(p) for p in parts)))
    require(len(choices) <= 256, "pattern_alternatives")
    result = []
    for choice in choices:
        if all(x["kind"] == "string" for x in choice):
            path = ""
            for item in choice:
                path = path.rstrip("/") + "/" + item["value"].lstrip("/")
            result.append({"kind": "string", "value": path or "/"})
        else:
            result.append({"kind": "composition", "parts": list(choice), "unresolved": "no_safe_string_comparison"})
    return result


def route_views(stack):
    def walk(layers, indices, contexts):
        for layer in layers:
            address = indices + [layer["index"]]
            prefix = contexts + [{"stackAt": indices, "beforeIndex": layer["index"]}]
            if layer["routePath"] is not None:
                children = layer["children"]
                for method in layer["methods"]:
                    handlers = ([address + [c["index"]] for c in children if method in c["methods"] or c["methods"] == []]
                                if type(children) is list else None)
                    for pattern in patterns(layer["mountChain"] + [layer["routePath"]]):
                        yield method, pattern, layer, address, prefix, handlers
            if type(layer["children"]) is list:
                yield from walk(layer["children"], address, prefix)
    yield from walk(stack, [], [])


def layers(stack, indices=()):
    for layer in stack:
        address = [*indices, layer["index"]]
        yield address, layer
        if type(layer["children"]) is list:
            yield from layers(layer["children"], address)


def method_key(method):
    return {"kind": "symbolicALL", "token": "ALL", "observedToken": "_all"} if method == "_all" else {"kind": "HTTP", "token": method.upper(), "observedToken": method}


def row_key(method, pattern):
    return encoded([method_key(method)["kind"], method_key(method)["token"], pattern]).decode()


def coordinates_source(layer):
    # Registration frames are candidate declaration coordinates, never a function
    # definition or proof that the old source behaved like the current factory.
    found = []
    for frame in layer["handler"]["registrationSource"]:
        match = re.search(r"/work/source/([^\s():]+):(\d+):(\d+)", frame)
        if match:
            found.append({"file": match[1], "line": int(match[2]), "column": int(match[3])})
    return found


def reconcile(old, rows, compositions, source_manifest):
    static = [e for e in old["endpoints"] if e["resolution"] == "static"]
    unknown = [e for e in old["endpoints"] if e["resolution"] != "static"]
    require(len(static) == 737 and len(unknown) == 3 and len(old["unattached_routes"]) == 27, "historical_counts")
    raw_matches, aliases, matched_old = [], [], set()
    matched_rows = set()
    for i, e in enumerate(static):
        for row in rows:
            if row["pattern"] != {"kind": "string", "value": e["path"]}:
                continue
            if row["method"]["kind"] == "HTTP" and row["method"]["token"] == e["method"]:
                raw_matches.append({"oldEndpointIndex": i, "declarationId": e["declaration_id"], "rowId": row["id"], "basis": "exact_method_string_pattern_candidate"})
            elif row["method"]["kind"] == "symbolicALL" and e["method"] == "*":
                anchors = [a for a in source_manifest.get(e["file"], {}).get("historicalDeclarationAnchors", []) if a["historicalLine"] == e["line"] and a["symbolicAllDeclared"]]
                require(len(anchors) == 1, "historical_all_source_evidence")
                aliases.append({"oldEndpointIndex": i, "declarationId": e["declaration_id"], "rowId": row["id"], "oldToken": "*", "observedToken": "_all", "logicalToken": "ALL", "basis": "symbolic_all_alias_not_concrete_methods", "sourceEvidence": {"file": e["file"], **anchors[0]}})
            else:
                continue
            matched_old.add(i)
            matched_rows.add(row["id"])
    prior_unknown = []
    unattached = []
    for category, entries, output in (("old_unresolved", unknown, prior_unknown), ("old_unattached", old["unattached_routes"], unattached)):
        for e in entries:
            candidates = []
            declared = e.get("declared_path", e.get("path"))
            for row in rows:
                for occurrence in row["occurrences"]:
                    layer = at(compositions[occurrence["compositionId"]]["stack"], occurrence["indices"])
                    locs = coordinates_source(layer)
                    exact_declaration = source_manifest.get(e["file"], {}).get("sourceDrift") == "byte_equal" and any(l["file"] == e["file"] and l["line"] == e["line"] for l in locs)
                    anchors = [a for a in source_manifest.get(e["file"], {}).get("historicalDeclarationAnchors", []) if a["historicalLine"] == e["line"] and len(a["currentCandidateLines"]) == 1]
                    shifted_declaration = any(l["file"] == e["file"] and l["line"] in a["currentCandidateLines"] for l in locs for a in anchors)
                    typed_declared = layer["routePath"] == {"kind": "string", "value": declared} if declared is not None else False
                    method_matches = e["method"] in (None, "*") or row["method"]["token"] == e["method"]
                    if method_matches and (exact_declaration or shifted_declaration or (e["file"] == "scripts/server.js" and typed_declared)):
                        basis = "exact_registration_coordinate_candidate" if exact_declaration else ("unique_stripped_declaration_line_candidate_changed_file" if shifted_declaration else "same_declared_string_pattern_candidate_changed_server_to_factory")
                        candidates.append({"rowId": row["id"], "compositionId": occurrence["compositionId"], "indices": occurrence["indices"], "basis": basis})
            output.append({"category": category, "historicalDeclaration": e, "registrationCandidates": candidates,
                           "status": "previous_unknown_has_actual_registration_candidates" if candidates else "remaining_unknown",
                           "semanticEquivalence": "UNKNOWN"})
    raw_old = {x["oldEndpointIndex"] for x in raw_matches}
    raw_rows = {x["rowId"] for x in raw_matches}
    return {"scope": "historical a6 versus current e3; candidates only, not behavioral equivalence",
            "rawExactCandidates": raw_matches, "symbolicAliasCandidates": aliases,
            "rawOnlyActual": [r["id"] for r in rows if r["id"] not in raw_rows],
            "rawOnlyStatic": [e for i, e in enumerate(static) if i not in raw_old],
            "logicalOnlyActual": [r["id"] for r in rows if r["id"] not in matched_rows],
            "logicalOnlyStatic": [e for i, e in enumerate(static) if i not in matched_old],
            "previousUnknown": prior_unknown, "previousUnattached": unattached,
            "historicalDiagnostics": old["unresolved"],
            "remainingUnknowns": ["function definition ambiguity remains explicit in full trees", "pattern overlaps not analyzed", "effective middleware dispatch, ACL, domain and human owners UNKNOWN", "runtime/WS/PTY/ingress/bootstrap/live/consumer behavior UNKNOWN"]}


def at(stack, address):
    require(type(address) is list and 0 < len(address) <= 32, "coordinate")
    layer = None
    for i in address:
        integer(i)
        require(type(stack) is list and i < len(stack), "coordinate_index")
        layer = stack[i]
        stack = layer["children"]
    return layer


def compose(contract, captures, old, source_manifest, dependencies):
    groups, compositions = {}, []
    for entry, leaf in zip(contract["captures"], captures, strict=True):
        group = int(entry["variant"]["dist"])
        if group not in groups:
            groups[group] = len(compositions)
            compositions.append({"id": groups[group], "dist": bool(group), "configurationIds": [], "registrations": leaf["registrations"], "stack": leaf["stack"]})
        composition = compositions[groups[group]]
        require(encoded(leaf["stack"]) == encoded(composition["stack"]) and encoded(leaf["registrations"]) == encoded(composition["registrations"]), "configuration_composition_identity")
        composition["configurationIds"].append(entry["originalId"])
    rows, index = [], {}
    summaries, repeats = [], []
    for composition in compositions:
        addresses = defaultdict(list)
        for address, layer in layers(composition["stack"]):
            addresses[layer["registrationOrdinal"]].append(address)
        for ordinal, occurrences in addresses.items():
            if len(occurrences) > 1:
                repeats.append({"compositionId": composition["id"], "registrationOrdinal": ordinal, "indices": occurrences,
                                "kind": "same_physical_registration_visible_at_repeated_mounts_not_pattern_overlap"})
        counts = Counter()
        physical_rows, logical_keys = 0, []
        for method, pattern, layer, address, contexts, handlers in route_views(composition["stack"]):
            key = row_key(method, pattern)
            if key not in index:
                index[key] = len(rows)
                rows.append({"id": f"SUPPORT-{len(rows):04d}", "method": method_key(method), "pattern": pattern, "occurrences": [], "observations": []})
            row = rows[index[key]]
            occurrence = {"compositionId": composition["id"], "indices": address, "registrationOrdinal": layer["registrationOrdinal"], "mountChain": layer["mountChain"], "declaredPath": layer["routePath"], "orderedPrefixContexts": contexts, "orderedRouteHandlerIndices": handlers}
            row["occurrences"].append(occurrence)
            for config_id in composition["configurationIds"]:
                entry = contract["captures"][config_id]
                row["observations"].append({"originalId": config_id, "captureSHA256": entry["sha256"], "compositionId": composition["id"], "indices": address, "registrationOrdinal": layer["registrationOrdinal"]})
            physical_rows += 1
            logical_keys.append(key)
            counts["symbolicALL" if method == "_all" else method.upper()] += 1
        route_count = sum(l["routePath"] is not None for _, l in layers(composition["stack"]))
        summaries.append({"compositionId": composition["id"], "configurationIds": composition["configurationIds"], "layers": sum(1 for _ in layers(composition["stack"])), "routeLayers": route_count, "methodPatternRows": physical_rows, "concreteHTTPMethodPatternRows": physical_rows - counts["symbolicALL"], "symbolicALLRows": counts["symbolicALL"], "methodCounts": dict(counts), "duplicateMethodPatternKeys": len(logical_keys) - len(set(logical_keys)), "patternOverlaps": "UNKNOWN_not_checked"})
    require(len(rows) <= 5000, "row_limit")
    definitions = {}
    for composition in compositions:
        for _, layer in layers(composition["stack"]):
            h = layer["handler"]
            for d in ([h["definitionSource"]] if h["definitionSource"] else h["definitionCandidates"]):
                definitions[d["file"]] = d["fileSHA256"]
    source_definitions = []
    for name, file_sha in sorted(definitions.items()):
        if name.startswith("/work/source/"):
            relative_name = name.removeprefix("/work/source/")
            source_definitions.append({"captureFile": name, "provenance": "Support_immutable_git_file_not_business_owner", "gitPin": contract["supportPin"], "file": relative_name, **source_manifest[relative_name]})
        else:
            relative_name = name.removeprefix("/work/node_modules/")
            require(dependencies[relative_name] == file_sha, "dependency_provenance")
            source_definitions.append({"captureFile": name, "provenance": "dependency_source_not_business_owner", "file": relative_name, "sha256": file_sha, "manifestSHA256": contract["dependencyManifest"]["sha256"]})
    return {"status": "ROOT_GENERATED_REGISTRATION_REGISTRY", "service": "Support", "authority": "support-service-local_no_publication_decision", "summary": summaries,
            "sourceManifest": source_manifest, "definitionFiles": source_definitions,
            "compositions": compositions, "canonicalRows": rows, "repeatedPhysicalRegistrations": repeats,
            "reconciliation": reconcile(old, rows, compositions, source_manifest),
            "unknown": {"humanOwner": "UNKNOWN", "domainOwner": "UNKNOWN", "externalDecision": "UNKNOWN", "authACLConformance": "UNKNOWN", "effectiveExecutionChains": "UNKNOWN", "patternOverlap": "UNKNOWN", "HTTPRequests": "not_performed", "liveCorrespondence": "UNKNOWN"}}


def controls():
    """Small explicit independent fixtures; no app, imports, IO or generated golden."""
    passed = []

    def denied(name, action, expected):
        try:
            action()
        except (ValueError, TypeError, KeyError) as exc:
            require(str(exc) == expected, "control_reason_" + name)
            passed.append(name)
        else:
            require(False, "control_not_denied_" + name)

    s = lambda value: {"kind": "string", "value": value}
    a = {"kind": "array", "values": [s("/one"), s("/two")]}
    require(patterns([s("/api"), a]) == [s("/api/one"), s("/api/two")], "control_array_expected")
    passed.append("explicit_array_alternatives")
    regex = {"kind": "regexp", "source": "^/x$", "flags": "i"}
    path_value(regex)
    require(patterns([regex]) == [{"kind": "composition", "parts": [regex], "unresolved": "no_safe_string_comparison"}], "control_regex_expected")
    passed.append("regex_preserved_unknown")
    require(method_key("_all") == {"kind": "symbolicALL", "token": "ALL", "observedToken": "_all"} and method_key("get")["token"] == "GET", "control_symbolic_expected")
    passed.append("symbolic_all_no_method_expansion")
    denied("duplicate_json_keys", lambda: decode(b'{"x":1,"x":2}'), "duplicate_json_key")
    denied("nonfinite_json", lambda: decode(b'{"x":NaN}'), "nonfinite_json")
    denied("malformed_hash", lambda: digest("a" * 63), "sha256")
    denied("foreign_path", lambda: relative("../outside.js"), "relative_path")
    denied("unknown_path_type", lambda: path_value({"kind": "guessed", "value": "/"}), "typed_path_kind")
    denied("typed_array_empty", lambda: path_value({"kind": "array", "values": []}), "array_path")
    denied("extra_path_key", lambda: path_value({"kind": "string", "value": "/", "guess": True}), "string_path_keys")
    denied("boolean_ordinal", lambda: integer(True), "integer")
    denied("foreign_frame", lambda: frame_sources(["at /home/unknown.js:1:1"]), "frame_scope")
    denied("manifest_missing_configuration", lambda: admit_manifest([]), "manifest_eight")
    manifest = [{"originalId": i, "series": "V10" if i < 6 else "V12", "variant": {"context": bool(i & 2), "dist": bool(i & 1), "identity": "local" if i < 4 else "core"}, "sha256": str(i + 1) * 64, "bytes": 100} for i in range(8)]
    admit_manifest(manifest)
    passed.append("eight_literal_configuration_identities")
    bad = decode(encoded(manifest))
    bad[6]["originalId"] = 0
    denied("manifest_duplicate_id", lambda: admit_manifest(bad), "manifest_original_id")
    bad_variant = decode(encoded(manifest))
    bad_variant[7]["variant"]["identity"] = "local"
    denied("manifest_variant_corruption", lambda: admit_manifest(bad_variant), "manifest_variant")
    bad_hash = decode(encoded(manifest))
    bad_hash[3]["sha256"] = "z" * 64
    denied("manifest_hash_corruption", lambda: admit_manifest(bad_hash), "sha256")
    bad_size = decode(encoded(manifest))
    bad_size[0]["bytes"] = 4194305
    denied("manifest_size_corruption", lambda: admit_manifest(bad_size), "integer")
    # Fixture fields and expected coordinates are literal, not built by compose().
    reg = {"ordinal": 0, "method": "route", "layerKind": "route", "path": s("/a"), "source": ["at /work/source/x.js:1:1"], "added": 1}
    handler_reg = {"ordinal": 1, "method": "all", "layerKind": "routeHandler", "path": s("/a"), "source": ["at /work/source/x.js:2:1"], "added": 1}
    h = {"name": None, "arity": 2, "sha256": "a" * 64, "registrationSource": handler_reg["source"], "definitionSource": None, "definitionCandidates": [], "unresolved": "definition text missing or ambiguous; registration frame is not definition location"}
    child = {"index": 0, "registrationOrdinal": 1, "path": s("/a"), "mountChain": [s("/a")], "routePath": None, "methods": [], "keys": [], "slash": False, "handler": h, "children": None}
    top_h = {**h, "registrationSource": reg["source"]}
    top = {"index": 0, "registrationOrdinal": 0, "path": s("/a"), "mountChain": [], "routePath": s("/a"), "methods": ["_all"], "keys": [], "slash": False, "handler": top_h, "children": [child]}
    require(validate_tree([top], [reg, handler_reg], {}, {}) == 2, "control_tree_expected")
    view = list(route_views([top]))
    require(len(view) == 1 and view[0][0] == "_all" and view[0][1] == s("/a") and view[0][3:] == ([0], [{"stackAt": [], "beforeIndex": 0}], [[0, 0]]), "control_walk_expected")
    passed.append("literal_tree_order_unknown_definition_and_all")
    denied("registration_wrong_ordinal", lambda: validate_tree([top], [{**reg, "ordinal": 4}, handler_reg], {}, {}), "registration_ordinal")
    denied("route_wrong_method", lambda: validate_tree([{**top, "methods": ["invented"]}], [reg, handler_reg], {}, {}), "layer_method")
    denied("route_method_child_mismatch", lambda: validate_tree([{**top, "methods": ["get"]}], [reg, handler_reg], {}, {}), "route_methods_children")
    denied("handler_provenance_corruption", lambda: validate_tree([{**top, "handler": {**top_h, "registrationSource": []}}], [reg, handler_reg], {}, {}), "handler_registration_provenance")
    denied("unknown_erased", lambda: validate_tree([{**top, "handler": {**top_h, "unresolved": None}}], [reg, handler_reg], {}, {}), "unknown_definition")
    denied("ambiguous_guessed_single_definition", lambda: validate_tree([{**top, "handler": {**top_h, "definitionCandidates": [{}]}}], [reg, handler_reg], {}, {}), "unknown_definition")
    denied("physical_layer_reindexed", lambda: validate_tree([{**top, "index": 1}], [reg, handler_reg], {}, {}), "layer_index")
    denied("physical_mount_chain_changed", lambda: validate_tree([{**top, "mountChain": [s("/foreign")]}], [reg, handler_reg], {}, {}), "layer_path_chain")
    denied("definition_outside_source", lambda: definition({"file": "/secret.js", "line": 1, "fileSHA256": "a" * 64, "match": "exact Function.toString source text"}, {}, {}), "definition_scope")
    candidates = [{"file": "/work/source/x.js", "line": 1, "fileSHA256": "b" * 64, "match": "exact Function.toString source text"}, {"file": "/work/source/y.js", "line": 2, "fileSHA256": "c" * 64, "match": "exact Function.toString source text"}]
    ambiguous = {**top, "handler": {**top_h, "definitionCandidates": candidates}}
    require(validate_tree([ambiguous], [reg, handler_reg], {"x.js": {"sha256": "b" * 64}, "y.js": {"sha256": "c" * 64}}, {}) == 2 and ambiguous["handler"]["definitionSource"] is None, "control_ambiguity_expected")
    passed.append("ambiguous_two_candidates_remain_unknown")
    # Two mount locations of one physical route registration must both survive.
    mount_reg = {"ordinal": 2, "method": "use", "layerKind": "mount", "path": s("/"), "source": ["at /work/source/x.js:3:1"], "added": 2}
    nested_child = {**child, "mountChain": [s("/"), s("/a")]}
    nested_top = {**top, "mountChain": [s("/")], "children": [nested_child]}
    mount = {"index": 0, "registrationOrdinal": 2, "path": s("/"), "mountChain": [], "routePath": None, "methods": [], "keys": [], "slash": True, "handler": {**h, "registrationSource": mount_reg["source"]}, "children": [nested_top]}
    physical = [mount, {**mount, "index": 1}]
    require(validate_tree(physical, [reg, handler_reg, mount_reg], {}, {}) == 6, "control_duplicate_expected")
    walked = list(route_views(physical))
    require([v[3] for v in walked] == [[0, 0], [1, 0]] and [v[4] for v in walked] == [[{"stackAt": [], "beforeIndex": 0}, {"stackAt": [0], "beforeIndex": 0}], [{"stackAt": [], "beforeIndex": 1}, {"stackAt": [1], "beforeIndex": 0}]], "control_ordered_prefix_expected")
    passed.append("physical_duplicate_mounts_and_ordered_prefix_siblings")
    return {"status": "CONTROLS_PASS", "count": len(passed), "cases": passed, "scope": "explicit parser fixtures only; not runtime/security/request proof"}


def admission(root, support, contract):
    admit_manifest(contract["captures"])
    acceptance = read_exact(root, contract["acceptance"], 65536)
    require(acceptance["status"] == "ROOT_SCOPED_EIGHT_DISTINCT_TWO_SERIES_PASS" and acceptance["single8Green"] is False, "acceptance_scope")
    read_exact(root, contract["independentSixSummary"], 65536)
    boundary_raw = git(root, "show", f'{contract["ledgerPin"]}:{contract["boundaryPath"]}')
    require(sha(boundary_raw) == contract["boundarySHA256"], "boundary_sha")
    boundary = decode(boundary_raw)
    require(boundary["fullNodes"] == contract["sourceFiles"], "source_manifest_boundary")
    dep = read_exact(root, contract["dependencyManifest"], 8388608)
    dependencies = {relative(name): digest(file_sha) for name, _, file_sha in dep["files"] if not name.startswith(".") and "/." not in name}
    require(len(contract["sourceFiles"]) == 289 and sum(e["bytes"] for e in contract["sourceFiles"].values()) <= 67108864, "source_budget")
    current_contents = {}
    source_manifest = blobs(support, contract["supportPin"], contract["sourceFiles"], current_contents)
    for name, entry in source_manifest.items():
        require({k: entry[k] for k in ("bytes", "sha256")} == contract["sourceFiles"][name], "source_git_identity")
    old_raw = git(root, "show", f'{contract["historicalLedgerPin"]}:{contract["historicalPath"]}')
    require(len(old_raw) == contract["historicalBytes"] and sha(old_raw) == contract["historicalSHA256"], "historical_identity")
    old_full = decode(old_raw)
    require(old_full["sourcePins"]["Support"] == contract["historicalSupportPin"], "historical_support_pin")
    old = next(s for s in old_full["sources"] if s["name"] == "Support")
    previous_files = {e["file"]: e for e in old["files"]}
    names = [name for name in source_manifest if name in previous_files]
    previous_contents = {}
    previous_git = blobs(support, contract["historicalSupportPin"], names, previous_contents)
    for name in source_manifest:
        before = previous_git.get(name)
        if before:
            require(before["sha256"] == previous_files[name]["sha256"], "historical_source_sha")
        source_manifest[name]["historical"] = before
        source_manifest[name]["sourceDrift"] = "added_since_a6" if before is None else ("byte_equal" if before["sha256"] == source_manifest[name]["sha256"] else "changed_since_a6_no_semantic_equivalence_claim")
    anchors = [e for e in old["endpoints"] if e["resolution"] != "static" or e["method"] == "*"] + old["unattached_routes"]
    seen_anchors = set()
    for e in anchors:
        name = e["file"]
        coordinate = (name, e["line"])
        if coordinate in seen_anchors or name not in previous_contents or name not in current_contents:
            continue
        seen_anchors.add(coordinate)
        old_lines = previous_contents[name].splitlines()
        require(type(e["line"]) is int and 1 <= e["line"] <= len(old_lines), "historical_declaration_line")
        declaration = old_lines[e["line"] - 1].strip()
        matching = [i + 1 for i, line in enumerate(current_contents[name].splitlines()) if line.strip() == declaration]
        source_manifest[name].setdefault("historicalDeclarationAnchors", []).append({"historicalLine": e["line"], "strippedLineSHA256": sha(declaration), "currentCandidateLines": matching, "symbolicAllDeclared": bool(re.search(rb"\.all\s*\(", declaration)), "basis": "exact_stripped_line_not_semantic_or_function_identity"})
    captures = []
    for entry in contract["captures"]:
        leaf = read_exact(root, entry, 4194304)
        admit_leaf(leaf, entry, source_manifest, dependencies)
        captures.append(leaf)
    return captures, old, source_manifest, dependencies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-ledger", type=Path)
    parser.add_argument("--support-repo", type=Path)
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--controls", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1073741824, 1073741824))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    signal.alarm(90)
    if args.controls:
        print(encoded(controls()).decode())
        return
    require(args.root_ledger is not None and args.support_repo is not None and args.output is not None, "paths_required")
    require(args.root_ledger.resolve() == ROOT_REPO and args.support_repo.resolve() == SUPPORT_REPO, "closed_repository_paths")
    require(args.output.parent.resolve() == EVIDENCE and args.output.name in {"first.json", "second.json"} and EVIDENCE.is_dir() and not EVIDENCE.is_symlink() and EVIDENCE.stat().st_uid == os.getuid(), "owned_output_path")
    require(not args.output.is_symlink() and (not args.output.exists() or args.output.stat().st_uid == os.getuid()), "output_owner")
    raw = PLAN.read_bytes()
    require(len(raw) <= 8388608, "plan_budget")
    plan = decode(raw)
    keys(plan, {"schemaVersion", "contract", "registry"}, "plan_keys")
    require(plan["schemaVersion"] == 1 and sha(encoded(plan["contract"])) == CONTRACT_SHA256, "frozen_contract")
    contract = plan["contract"]
    captures, old, source_manifest, dependencies = admission(args.root_ledger, args.support_repo, contract)
    registry = compose(contract, captures, old, source_manifest, dependencies)
    out = encoded({"schemaVersion": 1, "contract": contract, "registry": registry}) + b"\n"
    require(len(out) <= 8388608, "output_budget")
    # Immutable blobs and all admitted raw inputs must still match after projection.
    again, _, source_after, dependencies_after = admission(args.root_ledger, args.support_repo, contract)
    require(source_after == source_manifest and dependencies_after == dependencies and all(encoded(a) == encoded(b) for a, b in zip(captures, again, strict=True)), "source_after")
    if args.check:
        require(args.output.is_file() and args.output.stat().st_size == len(out) and args.output.read_bytes() == out, "check_bytes")
    else:
        require(args.output.parent.is_dir() and not args.output.is_symlink(), "output_parent")
        # Exclusive writes: ROOT chooses a new owned artifact path; an existing
        # checked-in registry is replaced only by ROOT after independent review.
        with args.output.open("xb") as stream:
            stream.write(out)
    print(encoded({"status": "CHECK_PASS" if args.check else "GENERATED", "bytes": len(out), "sha256": sha(out), "canonicalRows": len(registry["canonicalRows"]), "summary": registry["summary"], "sourceAfter": "equal", "scope": "registration_only_no_app_execution"}).decode())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        # Input contains only admitted source evidence; do not echo arbitrary data.
        print(encoded({"status": "BLOCKED", "reason": type(error).__name__, "detail": str(error)[:160]}).decode(), file=sys.stderr)
        sys.exit(1)
