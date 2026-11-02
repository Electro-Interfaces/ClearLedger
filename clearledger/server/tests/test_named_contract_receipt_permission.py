"""H01 source-authored contracts; execution belongs to ROOT's isolated runner."""
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api_contracts import (
    PolicyConfigurationError, PrincipalKind, ResourcePermission, ResourceScope, ScopeMode, authorize,
)
from app.api_contracts.context import (
    DatabaseAuthorityKind, DatabaseResourcePermission, PartnerContractReceiptBinding,
    PartnerContractReceiptEvidence,
)
from tests.test_api_contracts_context import context
from tests.test_api_contracts_http import URL, contract, fixture_api

NAMED_KIND = DatabaseAuthorityKind.PARTNER_CONTRACT_RECEIPT_V1
EXISTS = PartnerContractReceiptEvidence.CURRENT_ELIGIBLE_RECEIPT_EXISTS
APP_ID = UUID("00000000-0000-0000-0000-000000000101")
PROFILE_ID = UUID("00000000-0000-0000-0000-000000000201")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000999")


def receipt_policy(**overrides):
    values = dict(owner="contracts", accepted_kinds={PrincipalKind.PARTNER, PrincipalKind.SERVICE},
                  resource_type="contracts", action="read", required_scopes={"contracts:read"},
                  accepted_database_authority_kinds={NAMED_KIND})
    values.update(overrides)
    return contract(**values)


def receipt_context(*, kind=PrincipalKind.PARTNER, resources=None, fields=None):
    # Reuse the current pure context factory; this is synthetic server evidence,
    # not a SQL receipt issuer or a verifier substitute.
    binding = PartnerContractReceiptBinding(APP_ID, PROFILE_ID, 7)
    value = replace(context(kind=kind, scopes={"contracts:read"}),
                    permissions=(ResourcePermission("contracts", "read",
                        ResourceScope.empty() if resources is None else resources,
                        ResourceScope.all() if fields is None else fields),),
                    receipt_read_binding=binding)
    evidence = DatabaseResourcePermission(NAMED_KIND, value.company_id, value.principal,
                                          value.policy_version, binding, EXISTS)
    return replace(value, database_permissions=[evidence])


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("resources,allowed", [
    (ResourceScope.all(), True), (ResourceScope.selected(["a"]), True),
    (ResourceScope.empty(), False), (ResourceScope(), False),
])
def test_default_empty_policies_preserve_historical_resource_gate(kind, resources, allowed):
    value = context(kind=kind, resources=resources)
    policy = contract(accepted_kinds={kind})
    assert value.database_permissions == ()
    assert value.receipt_read_binding is None
    assert policy.accepted_database_authority_kinds == frozenset()
    if allowed:
        assert authorize(value, policy) is None
    else:
        with pytest.raises(HTTPException) as error:
            authorize(value, policy)
        assert (error.value.status_code, error.value.detail) == (403, "Resource access is not granted")


def test_historical_metadata_literal_is_unchanged_and_opt_in_is_explicit():
    assert contract().metadata() == {
        "owner": "documents", "principalKinds": ["partner"], "resourceType": "document",
        "action": "read", "scopes": ["documents.read"], "policyVersion": "policy-1",
        "tenantRequired": True, "fields": [], "securityScheme": "ProductOAuth",
    }
    assert receipt_policy().metadata()["databaseAuthorityKinds"] == ["partner-contract-receipt-v1"]


@pytest.mark.parametrize("change", [
    {"accepted_database_authority_kinds": {"partner-contract-receipt-v1"}},
    {"accepted_database_authority_kinds": {True}},
    {"accepted_database_authority_kinds": {"other-authority"}},
    {"resource_type": "documents"}, {"resource_type": "objects"},
    {"resource_type": "counterparties"}, {"resource_type": "equipment"},
    {"resource_type": "contract_types"}, {"resource_type": "source_file"},
    {"action": "download"}, {"action": "create"}, {"action": "metadata"},
    {"accepted_kinds": {PrincipalKind.USER}}, {"accepted_kinds": {PrincipalKind.PUBLIC}},
    {"tenant_required": False}, {"required_scopes": {"documents.read"}},
])
def test_named_kind_cannot_be_declared_for_other_resources_actions_or_actors(change):
    with pytest.raises(PolicyConfigurationError):
        receipt_policy(**change)


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("resources", [ResourceScope.empty(), ResourceScope()])
def test_declaration_without_evidence_preserves_empty_resource_denial(kind, resources):
    value = replace(context(kind=kind, scopes={"contracts:read"}), permissions=(
        ResourcePermission("contracts", "read", resources, ResourceScope.all()),))
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy())
    assert (error.value.status_code, error.value.detail) == (403, "Resource access is not granted")


def test_defaults_preserve_immutable_copies_and_existing_selection_identity():
    value = context(resources=ResourceScope.selected(["a"]))
    assert value.select("document", "read", ResourceScope.all()) == value
    assert value.intersect(value) == value
    assert value.permission("missing", "read").resources.mode is ScopeMode.UNINITIALIZED
    with pytest.raises(FrozenInstanceError):
        value.database_permissions = ()
    with pytest.raises(FrozenInstanceError):
        receipt_policy().accepted_database_authority_kinds = frozenset()


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("resources", [ResourceScope.empty(), ResourceScope()])
def test_only_matching_named_opt_in_evidence_admits_synthetic_empty_read(kind, resources):
    value = receipt_context(kind=kind, resources=resources)
    original = value.permission("contracts", "read")
    assert authorize(value, receipt_policy()) is None
    assert value.permission("contracts", "read") == original
    assert original.resources == resources and not original.resources.contains(["arbitrary-contract"])
    assert value.permission("documents", "read").resources.mode is ScopeMode.UNINITIALIZED
    assert type(value.database_permissions) is tuple


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
def test_evidence_without_policy_declaration_and_r3_metadata_policy_deny(kind):
    value = receipt_context(kind=kind)
    # Current metadata and every existing contracts policy use this default.
    base_only = receipt_policy(accepted_database_authority_kinds=frozenset())
    for policy in (base_only, replace(base_only, owner="contract-type-metadata")):
        with pytest.raises(HTTPException) as error:
            authorize(value, policy)
        assert (error.value.status_code, error.value.detail) == (403, "Resource access is not granted")


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("dimension", [
    "tenant", "principal", "actor-kind", "client", "install", "grant", "app", "profile",
    "generation", "policy", "missing-binding", "missing-evidence", "scopes", "invalid-context",
])
def test_every_current_binding_dimension_is_independent_and_cannot_be_substituted(kind, dimension):
    value = receipt_context(kind=kind)
    principal_fields = {"principal": "subject", "client": "client_id", "install": "installation_id",
                        "grant": "grant_id"}
    if dimension in principal_fields:
        value = replace(value, principal=replace(value.principal, **{principal_fields[dimension]: "other"}))
    elif dimension == "actor-kind":
        other_kind = PrincipalKind.SERVICE if kind is PrincipalKind.PARTNER else PrincipalKind.PARTNER
        value = replace(value, principal=replace(value.principal, kind=other_kind))
    elif dimension in ("app", "profile", "generation"):
        field, replacement = {"app": ("app_id", OTHER_ID), "profile": ("create_profile_id", OTHER_ID),
                              "generation": ("policy_generation", 8)}[dimension]
        value = replace(value, receipt_read_binding=replace(value.receipt_read_binding, **{field: replacement}))
    elif dimension == "tenant":
        value = replace(value, company_id="company-b")
    elif dimension == "policy":
        value = replace(value, policy_version="other-policy")
    elif dimension == "missing-binding":
        value = replace(value, receipt_read_binding=None)
    elif dimension == "missing-evidence":
        value = replace(value, database_permissions=())
    elif dimension == "scopes":
        value = replace(value, scopes=frozenset())
    elif dimension == "invalid-context":
        value = replace(value, valid=False)
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy())
    assert error.value.status_code == (401 if dimension in ("policy", "invalid-context") else 403)


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
def test_current_policy_version_match_does_not_hide_stale_evidence(kind):
    value = replace(receipt_context(kind=kind), policy_version="policy-2")
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy(policy_version="policy-2"))
    assert (error.value.status_code, error.value.detail) == (403, "Resource access is not granted")


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("fields,allowed", [
    (ResourceScope.all(), True), (ResourceScope.selected(["number"]), True),
    (ResourceScope.selected(["secret"]), False), (ResourceScope.empty(), False), (ResourceScope(), False),
])
def test_named_evidence_never_replaces_field_gate(kind, fields, allowed):
    value = receipt_context(kind=kind, fields=fields)
    if allowed:
        assert authorize(value, receipt_policy(required_fields={"number"})) is None
    else:
        with pytest.raises(HTTPException) as error:
            authorize(value, receipt_policy(required_fields={"number"}))
        assert (error.value.status_code, error.value.detail) == (403, "Field access is not granted")


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
def test_route_kind_gate_is_not_replaced_by_matching_evidence(kind):
    value = receipt_context(kind=kind)
    other_kind = PrincipalKind.SERVICE if kind is PrincipalKind.PARTNER else PrincipalKind.PARTNER
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy(accepted_kinds={other_kind}))
    assert (error.value.status_code, error.value.detail) == (403, "Principal kind is not accepted")


@pytest.mark.parametrize("resource", ["objects", "equipment", "counterparties", "documents", "source_file",
                                       "contract_types", "foreign-counterparty"])
def test_receipt_evidence_does_not_extend_any_other_resource(resource):
    value = receipt_context()
    policy = contract(resource_type=resource, required_scopes={"contracts:read"})
    with pytest.raises(HTTPException) as error:
        authorize(value, policy)
    assert (error.value.status_code, error.value.detail) == (403, "Resource access is not granted")


@pytest.mark.parametrize("action", ["create", "edit", "download", "metadata"])
def test_receipt_evidence_cannot_authorize_other_contract_actions(action):
    with pytest.raises(HTTPException) as error:
        authorize(receipt_context(), contract(resource_type="contracts", action=action,
                                              required_scopes={"contracts:read"}))
    assert error.value.status_code == 403


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("resources", [ResourceScope.empty(), ResourceScope()])
def test_selector_cannot_spend_receipt_authority(kind, resources):
    value = receipt_context(kind=kind, resources=resources)
    app, state = fixture_api(value, policy=receipt_policy(),
                             selector=lambda request: ResourceScope.selected(["a"]))
    with TestClient(app) as client:
        response = client.post(URL, json={"title": "must not execute"})
    assert response.status_code == 403 and not state["calls"]
    assert response.json()["detail"] == "Resource selection is not granted"


@pytest.mark.parametrize("resources,identifier,allowed", [
    (ResourceScope.all(), "a", True), (ResourceScope.selected(["a"]), "a", True),
    (ResourceScope.selected(["a"]), "outside", False),
])
def test_existing_selector_remains_limited_by_base_scope_with_evidence_present(resources, identifier, allowed):
    app, state = fixture_api(receipt_context(resources=resources), policy=receipt_policy(),
                             selector=lambda request: ResourceScope.selected([identifier]))
    with TestClient(app) as client:
        response = client.post(URL, json={"title": "base selection"})
    assert response.status_code == (200 if allowed else 403)
    assert bool(state["calls"]) is allowed


def test_context_selection_and_intersection_never_transfer_receipt_authority():
    value = receipt_context()
    selected = value.select("contracts", "read", ResourceScope.selected(["arbitrary-contract"]))
    assert selected.database_permissions == ()
    with pytest.raises(HTTPException):
        authorize(selected, receipt_policy())
    assert value.intersect(value) == value
    for other in (replace(value, database_permissions=()), replace(value, receipt_read_binding=None),
                  replace(value, receipt_read_binding=replace(value.receipt_read_binding, policy_generation=8))):
        left, right = value.intersect(other), other.intersect(value)
        assert left == right and left.database_permissions == ()
        with pytest.raises(HTTPException):
            authorize(left, receipt_policy())


def test_exact_frozen_receipt_classes_and_copied_collections():
    value = receipt_context()
    evidence = value.database_permissions[0]
    for instance, field, replacement in (
        (evidence, "company_id", "other"), (evidence, "evidence", True),
        (value.receipt_read_binding, "app_id", OTHER_ID),
        (value.receipt_read_binding, "create_profile_id", OTHER_ID),
        (value.receipt_read_binding, "policy_generation", 8),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field, replacement)
    mutable = [evidence]
    copied = replace(value, database_permissions=mutable)
    mutable.clear()
    assert copied.database_permissions == (evidence,)
    with pytest.raises(ValueError):
        replace(value, database_permissions=(evidence, evidence))


@pytest.mark.parametrize("change", [
    {"app_id": str(APP_ID)}, {"app_id": None}, {"create_profile_id": str(PROFILE_ID)},
    {"create_profile_id": None}, {"policy_generation": True}, {"policy_generation": False},
    {"policy_generation": 0}, {"policy_generation": -1}, {"policy_generation": "7"},
    {"policy_generation": 7.0},
])
def test_binding_malformed_values_are_not_coerced(change):
    with pytest.raises(ValueError):
        replace(receipt_context().receipt_read_binding, **change)


@pytest.mark.parametrize("change", [
    {"authority_kind": "partner-contract-receipt-v1"}, {"authority_kind": "other-kind"},
    {"authority_kind": True}, {"evidence": True}, {"evidence": "current-eligible-receipt-exists"},
    {"evidence": None}, {"resource_type": "documents"}, {"resource_type": "contract"},
    {"action": "download"}, {"action": "create"}, {"company_id": ""}, {"policy_version": ""},
    {"binding": None}, {"binding": {"app_id": APP_ID}},
    {"principal": {"subject": "subject"}},
])
def test_permission_malformed_values_and_untyped_evidence_fail_closed(change):
    with pytest.raises(ValueError):
        replace(receipt_context().database_permissions[0], **change)


def test_permission_binding_principal_and_evidence_subclasses_fail_closed():
    value = receipt_context()
    evidence = value.database_permissions[0]

    class DerivedPermission(DatabaseResourcePermission):
        pass

    class DerivedBinding(PartnerContractReceiptBinding):
        pass

    class DerivedPrincipal(type(value.principal)):
        pass

    with pytest.raises(ValueError):
        replace(value, database_permissions=(DerivedPermission(**vars(evidence)),))
    derived_binding = DerivedBinding(APP_ID, PROFILE_ID, 7)
    with pytest.raises(ValueError):
        replace(value, receipt_read_binding=derived_binding)
    with pytest.raises(ValueError):
        replace(evidence, binding=derived_binding)
    with pytest.raises(ValueError):
        replace(evidence, principal=DerivedPrincipal(**vars(value.principal)))
    for untyped in (True, {}, SimpleNamespace(**vars(evidence)), None):
        with pytest.raises(ValueError):
            replace(value, database_permissions=(untyped,))


@pytest.mark.parametrize("kind", [PrincipalKind.USER, PrincipalKind.PUBLIC])
def test_native_or_public_principal_cannot_be_receipt_evidence(kind):
    with pytest.raises(ValueError):
        replace(receipt_context().database_permissions[0], principal=context(kind=kind).principal)


def test_uuid_subclass_and_resource_permission_substitution_are_rejected():
    class DerivedUUID(UUID):
        pass

    value = receipt_context()
    with pytest.raises(ValueError):
        replace(value.receipt_read_binding, app_id=DerivedUUID(str(APP_ID)))
    with pytest.raises(ValueError):
        ResourcePermission("contracts", "read", value.database_permissions[0], ResourceScope.all())
    with pytest.raises(ValueError):
        replace(value, permissions=value.database_permissions)


@pytest.mark.parametrize("field", ["client_id", "installation_id", "grant_id"])
def test_incomplete_principal_cannot_produce_receipt_evidence(field):
    value = receipt_context()
    with pytest.raises(ValueError):
        replace(value.database_permissions[0], principal=replace(value.principal, **{field: None}))


def test_malformed_exact_class_object_cannot_pass_the_named_guard():
    # Frozen dataclasses prevent ordinary mutation; explicitly corrupt a server
    # object to ensure bool/string masquerading still fails at the final gate.
    value = receipt_context()
    evidence = replace(value.database_permissions[0])
    object.__setattr__(evidence, "evidence", True)
    object.__setattr__(value, "database_permissions", (evidence,))
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy())
    assert error.value.status_code == 403


def test_empty_exact_class_object_and_malformed_current_generation_fail_closed():
    value = receipt_context()
    object.__setattr__(value, "database_permissions", (object.__new__(DatabaseResourcePermission),))
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy())
    assert error.value.status_code == 403
    value = receipt_context()
    object.__setattr__(value.receipt_read_binding, "policy_generation", True)
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy())
    assert error.value.status_code == 403


class _HashableEqualText(str):
    """Authored malformed-server input; instantiated only by ROOT-run tests."""
    __hash__ = str.__hash__

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("field", [
    "company_id", "policy_version", "subject", "client_id", "installation_id", "grant_id",
])
def test_named_match_rejects_hostile_current_identity_text(kind, field):
    value = receipt_context(kind=kind)
    evidence = value.database_permissions[0]
    changed = _HashableEqualText("different-current-text")
    if field in ("company_id", "policy_version"):
        value = replace(value, **{field: changed})
    else:
        value = replace(value, principal=replace(value.principal, **{field: changed}))
    assert evidence.matches(value, "contracts", "read") is False
    with pytest.raises(HTTPException) as error:
        authorize(value, receipt_policy())
    assert (error.value.status_code, error.value.detail) == (403, "Resource access is not granted")


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
def test_named_match_keeps_benign_exact_current_strings(kind):
    value = receipt_context(kind=kind)
    assert all(type(item) is str for item in (
        value.company_id, value.policy_version, value.principal.subject, value.principal.client_id,
        value.principal.installation_id, value.principal.grant_id,
    ))
    assert value.database_permissions[0].matches(value, "contracts", "read") is True
    assert authorize(value, receipt_policy()) is None


@pytest.mark.parametrize("field,text", [
    ("resource_type", "contracts"), ("resource_type", "documents"),
    ("action", "read"), ("action", "create"),
])
def test_named_policy_rejects_hashable_hostile_scalar_labels(field, text):
    with pytest.raises(PolicyConfigurationError):
        receipt_policy(**{field: _HashableEqualText(text)})


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("field,text", [
    ("resource_type", "contracts"), ("resource_type", "documents"),
    ("action", "read"), ("action", "create"),
])
def test_direct_named_match_rejects_hashable_hostile_scalar_labels(kind, field, text):
    value = receipt_context(kind=kind)
    labels = {"resource_type": "contracts", "action": "read"}
    labels[field] = _HashableEqualText(text)
    assert value.database_permissions[0].matches(value, **labels) is False


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("field,text", [("resource_type", "document"), ("action", "read")])
def test_default_empty_policy_keeps_legacy_scalar_label_validation(kind, field, text):
    policy = contract(accepted_kinds={kind}, **{field: _HashableEqualText(text)})
    assert policy.accepted_database_authority_kinds == frozenset()
    assert type(getattr(policy, field)) is _HashableEqualText
    assert authorize(context(kind=kind), policy) is None


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
@pytest.mark.parametrize("field", [
    "company_id", "policy_version", "subject", "client_id", "installation_id", "grant_id",
])
def test_default_empty_policy_keeps_legacy_current_identity_validation(kind, field):
    value = context(kind=kind)
    changed = _HashableEqualText("different-current-text")
    if field in ("company_id", "policy_version"):
        value = replace(value, **{field: changed})
    else:
        value = replace(value, principal=replace(value.principal, **{field: changed}))
    assert value.database_permissions == ()
    assert authorize(value, contract(accepted_kinds={kind})) is None
