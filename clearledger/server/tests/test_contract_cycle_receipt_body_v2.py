"""Finite E1a SOURCE ONLY / NOTRUN; Root admission and --noconftest required."""
import sys

_guard = sys.modules.get("receipt_envelope_source_admission_v1")
if _guard is None:
    raise RuntimeError("External Root receipt-source admission required")
_guard.require_running_approval()
m = _guard.receipt_body

from copy import deepcopy
from datetime import date, datetime
import json
from uuid import UUID

import pytest
from pydantic import ValidationError


PRIMARY_CASES = (
    "contract_location", "contract_site", "document_location", "document_site_registered",
    "binding_count_boundaries", "version_count_boundaries", "unicode_opaque_order",
    "document_action_order", "strict_format", "generation_int_boundaries",
    "malformed_uuid", "invalid_object_id", "extra_keys_every_layer",
    "duplicate_mixed_vectors", "closed_unique_nonempty_actions", "operation_actions",
    "operation_result_shape", "document_context_match", "document_organization_match",
    "document_text_boundaries", "document_strict_integers", "document_version_fields",
    "document_dates", "public_projection", "mutated_uuid_bytes", "constructed_outer",
    "constructed_nested", "mutated_nested_collections", "missing_and_retained_extra",
    "every_helper_revalidates", "required_operation", "typed_python_roundtrip",
)

ORG = "00000001-0000-4000-8000-000000000001"
OTHER = "00000002-0000-4000-8000-000000000002"
SITE = "00000003-0000-4000-8000-000000000003"
POLICY = "00000004-0000-4000-8000-000000000004"
VERSION = "v1:" + "a" * 64
C = "v2.contract.create"
D = "v2.document.draft.create"


def binding(location=" station A ", *, site=False, policy=POLICY, actions=None):
    context = {"kind": "site", "siteId": SITE, "organizationId": ORG, "generation": 1} if site else {
        "kind": "location", "locationId": location, "organizationId": ORG,
    }
    return {"birthPolicy": {"id": policy, "generation": 1}, "context": context,
            "actions": ["contract.read"] if actions is None else actions}


def envelope(*, document=False, site=False):
    b = binding(site=site, actions=["document.edit"] if document else None)
    context = {k: v for k, v in b["context"].items() if k not in ("organizationId", "generation")}
    result = {
        "docId": OTHER, "context": context, "organizationId": ORG,
        "kindCode": "contract_scan", "title": "Synthetic receipt", "status": "draft",
        "editVersion": VERSION, "currentRevision": 0, "registrationNumber": None,
        "registrationDate": None, "versions": [], "versionsTruncated": False,
    } if document else {"resourceId": OTHER, "editVersion": VERSION}
    return {"formatVersion": 1, "authoritySnapshot": {
        "profile": {"id": ORG, "generation": 1},
        "principal": {"id": OTHER, "generation": 1}, "bindings": [b],
    }, "result": result}


def version(**changes):
    value = {"versionId": POLICY, "role": "body", "revision": 1,
             "sha256": "b" * 64, "sizeBytes": 1}
    value.update(changes)
    return value


def parse(value, operation=C):
    return m.parse_birth_envelope(value, operation=operation)


def deny(value, operation=C):
    with pytest.raises((ValidationError, ValueError)):
        parse(value, operation)


@pytest.mark.parametrize("case", PRIMARY_CASES)
def test_receipt_grammar(case):
    if case == "contract_location":
        raw = envelope()
        assert m.project_birth_result(raw, operation=C) == raw["result"]
        assert json.loads(m.serialize_birth_envelope(raw, operation=C)) == raw
    elif case == "contract_site":
        value = parse(envelope(site=True))
        assert value.authoritySnapshot.bindings[0].context.siteId == UUID(SITE)
        assert type(value.result) is m.ContractBirthResult
    elif case == "document_location":
        raw = envelope(document=True)
        assert m.project_birth_result(raw, operation=D) == raw["result"]
        assert type(parse(raw, D).result) is m.DocumentBirthResult
    elif case == "document_site_registered":
        raw = envelope(document=True, site=True)
        raw["result"].update(status="registered", registrationNumber="R-1", registrationDate="2026-11-01",
                             currentRevision=1, versions=[version(role="signed_scan", sizeBytes=26214400)])
        assert json.loads(m.serialize_birth_envelope(raw, operation=D)) == raw
    elif case == "binding_count_boundaries":
        raw = envelope()
        raw["authoritySnapshot"]["bindings"] = [binding(str(i), policy=str(UUID(int=i + 1))) for i in range(100)]
        assert len(parse(raw).authoritySnapshot.bindings) == 100
        for size in (0, 101):
            bad = deepcopy(raw)
            bad["authoritySnapshot"]["bindings"] = [] if size == 0 else raw["authoritySnapshot"]["bindings"] + [binding("101", policy=str(UUID(int=101)))]
            deny(bad)
        deny(raw, D)
    elif case == "version_count_boundaries":
        raw = envelope(document=True)
        raw["result"]["versions"] = [version(versionId=str(UUID(int=i + 1)), revision=i + 1) for i in range(200)]
        assert len(parse(raw, D).result.versions) == 200
        raw["result"]["versions"].append(version())
        deny(raw, D)
    elif case == "unicode_opaque_order":
        locations = ["😀", "a", " A ", "é", "e\u0301", "A", SITE.upper()]
        raw = envelope()
        raw["authoritySnapshot"]["bindings"] = [binding(loc, policy=str(UUID(int=i + 1))) for i, loc in enumerate(locations)]
        before = deepcopy(raw)
        actual = parse(raw).authoritySnapshot.bindings
        assert [b.context.locationId for b in actual] == sorted(locations)
        assert raw == before  # Original payload order/opaque strings were not rewritten.
    elif case == "document_action_order":
        raw = envelope(document=True)
        actions = ["document.sign", "document.edit", "document.archive"]
        raw["authoritySnapshot"]["bindings"][0]["actions"] = actions
        assert parse(raw, D).authoritySnapshot.bindings[0].actions == sorted(actions)
        assert actions == ["document.sign", "document.edit", "document.archive"]
    elif case == "strict_format":
        for value in (True, False, 0, 2, -1, "1", 1.0, None):
            raw = envelope(); raw["formatVersion"] = value; deny(raw)
    elif case == "generation_int_boundaries":
        for axis in ("profile", "principal", "policy", "site"):
            maximum = 2147483647 if axis == "site" else 9223372036854775807
            for value in (1, maximum, 0, -1, maximum + 1, True, 1.0, "1"):
                raw = envelope(site=True)
                snapshot = raw["authoritySnapshot"]
                target = snapshot[axis] if axis in ("profile", "principal") else snapshot["bindings"][0]["context" if axis == "site" else "birthPolicy"]
                target["generation"] = value
                if type(value) is int and 1 <= value <= maximum: parse(raw)
                else: deny(raw)
    elif case == "malformed_uuid":
        for bad in (ORG.replace("-", ""), "{" + ORG + "}", ORG.encode(), 1, "not-uuid"):
            for path in ("profile", "principal", "policy", "site", "result"):
                raw = envelope(site=True); s = raw["authoritySnapshot"]
                if path in ("profile", "principal"): s[path]["id"] = bad
                elif path == "policy": s["bindings"][0]["birthPolicy"]["id"] = bad
                elif path == "site": s["bindings"][0]["context"]["siteId"] = bad
                else: raw["result"]["resourceId"] = bad
                deny(raw)
    elif case == "invalid_object_id":
        for loc in ("", "x" * 41, "nul\x00", "\ud800", b"bytes", 1):
            raw = envelope(); raw["authoritySnapshot"]["bindings"][0]["context"]["locationId"] = loc; deny(raw)
        for loc in (" ", "x" * 40, "😀" * 40):
            raw = envelope(); raw["authoritySnapshot"]["bindings"][0]["context"]["locationId"] = loc
            assert parse(raw).authoritySnapshot.bindings[0].context.locationId == loc
    elif case == "extra_keys_every_layer":
        for axis in ("outer", "snapshot", "profile", "principal", "binding", "policy", "context", "result", "version", "doccontext"):
            raw = envelope(document=True); s = raw["authoritySnapshot"]; b = s["bindings"][0]
            raw["result"]["versions"] = [version()]
            target = {"outer": raw, "snapshot": s, "profile": s["profile"], "principal": s["principal"],
                      "binding": b, "policy": b["birthPolicy"], "context": b["context"], "result": raw["result"],
                      "version": raw["result"]["versions"][0], "doccontext": raw["result"]["context"]}[axis]
            target["unexpected"] = "synthetic"; deny(raw, D)
        raw = envelope(); raw["authoritySnapshot"]["bindings"][0]["context"]["generation"] = 1; deny(raw)
    elif case == "duplicate_mixed_vectors":
        for variant in ("context", "policy", "mixed", "sites", "org"):
            raw = envelope(); first = raw["authoritySnapshot"]["bindings"][0]
            second = binding("other", policy=OTHER)
            if variant == "context": second["context"] = deepcopy(first["context"])
            elif variant == "policy": second["birthPolicy"]["id"] = POLICY
            elif variant == "mixed": second = binding(site=True, policy=OTHER)
            elif variant == "sites": first.update(binding(site=True)); second = binding(site=True, policy=OTHER); second["context"]["siteId"] = OTHER
            else: second["context"]["organizationId"] = OTHER
            raw["authoritySnapshot"]["bindings"].append(second); deny(raw)
    elif case == "closed_unique_nonempty_actions":
        for actions in ([], ["contract.read", "contract.read"], ["contract.edit"], ["*"], [b"contract.read"], [True]):
            raw = envelope(); raw["authoritySnapshot"]["bindings"][0]["actions"] = actions; deny(raw)
        raw = envelope(document=True); raw["authoritySnapshot"]["bindings"][0]["actions"] = []
        deny(raw, D)
        raw["authoritySnapshot"]["bindings"][0]["actions"] = sorted(m.DOCUMENT_ACTIONS)
        assert len(parse(raw, D).authoritySnapshot.bindings[0].actions) == 10
        for actions in (["document.other"], ["document.edit", "document.other"], [b"document.edit"]):
            raw["authoritySnapshot"]["bindings"][0]["actions"] = actions; deny(raw, D)
    elif case == "operation_actions":
        for document, actions in ((False, ["document.read"]), (True, ["contract.read"]), (True, ["document.read", "document.read"])):
            raw = envelope(document=document); raw["authoritySnapshot"]["bindings"][0]["actions"] = actions
            deny(raw, D if document else C)
    elif case == "operation_result_shape":
        for document in (False, True):
            raw = envelope(document=document); raw["result"] = envelope(document=not document)["result"]
            deny(raw, D if document else C)
        raw = envelope(); raw["result"]["replayed"] = False; deny(raw)
    elif case == "document_context_match":
        for site in (False, True):
            for variant in ("id", "kind"):
                raw = envelope(document=True, site=site)
                if variant == "id": raw["result"]["context"]["siteId" if site else "locationId"] = OTHER
                else: raw["result"]["context"] = {"kind": "location", "locationId": "x"} if site else {"kind": "site", "siteId": SITE}
                deny(raw, D)
        raw = envelope(document=True)
        raw["authoritySnapshot"]["bindings"].append(binding("second", policy=OTHER, actions=["document.edit"]))
        deny(raw, D)
    elif case == "document_organization_match":
        raw = envelope(document=True); raw["result"]["organizationId"] = OTHER; deny(raw, D)
    elif case == "document_text_boundaries":
        for field, maximum in (("title", 500), ("registrationNumber", 60)):
            for value in ("x", "x" * maximum, "", "x" * (maximum + 1), "\x00", "\udfff", b"text"):
                raw = envelope(document=True); raw["result"][field] = value
                if type(value) is str and value in ("x", "x" * maximum): parse(raw, D)
                else: deny(raw, D)
        for field, value in (("kindCode", "other"), ("status", "approved"), ("editVersion", "v1:" + "A" * 64)):
            raw = envelope(document=True); raw["result"][field] = value; deny(raw, D)
    elif case == "document_strict_integers":
        for value in (-1, True, "0", 0.0):
            raw = envelope(document=True); raw["result"]["currentRevision"] = value; deny(raw, D)
        for value in (0, 1, "false", None):
            raw = envelope(document=True); raw["result"]["versionsTruncated"] = value; deny(raw, D)
        raw = envelope(document=True); raw["result"]["versionsTruncated"] = True; parse(raw, D)
    elif case == "document_version_fields":
        invalid = (("versionId", "bad"), ("role", "scan"), ("revision", 0), ("revision", True), ("revision", 1.0),
                   ("sha256", "A" * 64), ("sha256", "a" * 63), ("sha256", "a" * 65),
                   ("sizeBytes", 0), ("sizeBytes", 26214401), ("sizeBytes", True), ("sizeBytes", "1"))
        for field, value in invalid:
            raw = envelope(document=True); raw["result"]["versions"] = [version(**{field: value})]; deny(raw, D)
    elif case == "document_dates":
        for value in ("2026-02-29", "2026-1-01", "2026-11-01T00:00:00", datetime(2026, 11, 1), 1):
            raw = envelope(document=True); raw["result"]["registrationDate"] = value; deny(raw, D)
        raw = envelope(document=True); raw["result"]["registrationDate"] = "2024-02-29"; parse(raw, D)
    elif case == "public_projection":
        forbidden = {"formatVersion", "authoritySnapshot", "replayed", "credential", "storagePath", "storageId"}
        for document in (False, True):
            raw = envelope(document=document); operation = D if document else C
            projected = m.project_birth_result(raw, operation=operation)
            assert projected == raw["result"] and not forbidden.intersection(projected)
            for key in ("replayed", "credential", "storagePath", "storageId"):
                bad = deepcopy(raw); bad["result"][key] = "synthetic"; deny(bad, operation)
            projected.clear()
            assert m.project_birth_result(raw, operation=operation) == raw["result"]
    elif case == "mutated_uuid_bytes":
        value = parse(envelope())
        object.__setattr__(value.authoritySnapshot.profile, "id", ORG.encode())
        deny(value)
        value = parse(envelope(document=True), D)
        object.__setattr__(value.result, "title", b"serializer-would-repair")
        deny(value, D)
    elif case == "constructed_outer":
        raw = envelope(); raw["formatVersion"] = True
        deny(m.BirthReceiptEnvelopeV1.model_construct(**raw))
        valid = m.BirthReceiptEnvelopeV1.model_construct(**envelope())
        assert parse(valid).result.resourceId == UUID(OTHER)
    elif case == "constructed_nested":
        raw = envelope(document=True)
        raw["result"]["versions"] = [m.DocumentBirthVersion.model_construct(**version(sizeBytes=True))]
        deny(raw, D)
        raw = envelope(); raw["authoritySnapshot"]["bindings"][0]["birthPolicy"] = m.BirthGenerationRef.model_construct(id=UUID(POLICY), generation=True)
        deny(raw)
        raw = envelope(document=True)
        raw["result"]["context"] = m.DocumentLocationContext.model_construct(kind="location", locationId=b" station A ")
        deny(raw, D)
    elif case == "mutated_nested_collections":
        value = parse(envelope()); value.authoritySnapshot.bindings[0].actions.append("contract.read"); deny(value)
        value = parse(envelope()); value.authoritySnapshot.bindings.append(value.authoritySnapshot.bindings[0]); deny(value)
        value = parse(envelope(document=True), D); value.result.versions.append(m.DocumentBirthVersion.model_construct(**version(sha256=b"b" * 64))); deny(value, D)
    elif case == "missing_and_retained_extra":
        value = parse(envelope()); del value.authoritySnapshot.profile.__dict__["generation"]; deny(value)
        value = parse(envelope()); value.result.__dict__["replayed"] = True; deny(value)
        value = parse(envelope()); object.__setattr__(value.result, "__pydantic_extra__", {"storagePath": "synthetic"}); deny(value)
    elif case == "every_helper_revalidates":
        for helper in (m.parse_birth_envelope, m.serialize_birth_envelope, m.project_birth_result):
            for document in (False, True):
                value = parse(envelope(document=document), D if document else C)
                object.__setattr__(value.authoritySnapshot.bindings[0].context, "organizationId", OTHER.encode())
                with pytest.raises((ValidationError, ValueError)):
                    helper(value, operation=D if document else C)
            value = parse(envelope(document=True), D)
            object.__setattr__(value.result, "registrationDate", datetime(2026, 11, 1))
            with pytest.raises((ValidationError, ValueError)):
                helper(value, operation=D)
    elif case == "required_operation":
        for operation in (None, "v2.contract.patch", "v2.document.register", True, b"v2.contract.create"):
            deny(envelope(), operation)
        with pytest.raises(ValidationError): m.BirthReceiptEnvelopeV1.model_validate(envelope())
        with pytest.raises(TypeError): m.project_birth_result(envelope())
        raw = envelope(); raw["operation"] = C; deny(raw)
    elif case == "typed_python_roundtrip":
        raw = envelope(document=True, site=True)
        raw["result"]["registrationDate"] = date(2026, 11, 1)
        raw["result"]["docId"] = UUID(OTHER)
        value = parse(raw, D)
        again = parse(value, D)
        assert again is not value and again.result is not value.result
        projected = m.project_birth_result(again, operation=D)
        assert projected["registrationDate"] == "2026-11-01" and projected["docId"] == OTHER
    else:
        raise AssertionError("Unimplemented literal primary case")
