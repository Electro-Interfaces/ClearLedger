from dataclasses import FrozenInstanceError, replace

import pytest

from app.api_contracts import (
    AccessContext, Principal, PrincipalKind, ResourcePermission, ResourceScope, ScopeMode,
)


def context(*, kind=PrincipalKind.PARTNER, resources=None, fields=None, scopes=None, valid=True):
    principal = (Principal(kind, "subject", "client", "installation", "grant")
                 if kind is not PrincipalKind.PUBLIC else Principal(kind))
    return AccessContext(
        principal, "company-a", "policy-1", scopes if scopes is not None else {"documents.read"},
        (ResourcePermission("document", "read", resources or ResourceScope.all(),
                            fields or ResourceScope.all()),), valid=valid,
    )


@pytest.mark.parametrize("left", list(ScopeMode))
@pytest.mark.parametrize("right", list(ScopeMode))
def test_scope_intersection_never_widens(left, right):
    a = ResourceScope(left, {"a", "b"} if left is ScopeMode.SET else frozenset())
    b = ResourceScope(right, {"b", "c"} if right is ScopeMode.SET else frozenset())
    result = a.intersect(b)
    assert result == b.intersect(a)
    if ScopeMode.UNINITIALIZED in (left, right):
        assert result.mode is ScopeMode.UNINITIALIZED
    elif ScopeMode.EMPTY in (left, right):
        assert result.mode is ScopeMode.EMPTY
    else:
        for identifier in ("a", "b", "c", "outside"):
            assert result.contains([identifier]) == (a.contains([identifier]) and b.contains([identifier]))


def test_selected_empty_is_explicit_empty_not_unbounded():
    assert ResourceScope.selected([]) == ResourceScope.empty()
    assert ResourceScope.selected([]) != ResourceScope.all()
    assert ResourceScope.selected([]) != ResourceScope()
    assert not ResourceScope.empty().contains([])
    assert not ResourceScope().contains([])


@pytest.mark.parametrize("ids", ["a,b", b"a", [""], [" "], [1], [None], None])
def test_invalid_selection_is_not_an_all_fallback(ids):
    with pytest.raises((ValueError, TypeError)):
        ResourceScope.selected(ids)


def test_all_context_components_are_immutable_and_copy_input_collections():
    scopes, ids = {"documents.read"}, {"a"}
    value = context(scopes=scopes, resources=ResourceScope.selected(ids))
    scopes.add("documents.write")
    ids.add("b")
    assert value.scopes == {"documents.read"}
    assert value.permissions[0].resources.ids == {"a"}
    for instance, field, replacement in (
        (value, "valid", False), (value.principal, "kind", PrincipalKind.USER),
        (value.permissions[0], "action", "write"),
        (value.permissions[0].resources, "mode", ScopeMode.ALL),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field, replacement)


def test_context_intersection_preserves_resource_action_field_and_scope_limits():
    broad = context()
    narrow = context(resources=ResourceScope.selected(["a"]),
                     fields=ResourceScope.selected(["title"]), scopes={"documents.read", "unused"})
    narrowed = broad.intersect(narrow)
    assert narrowed == narrow.intersect(broad)
    assert narrowed.scopes == {"documents.read"}
    permission = narrowed.permission("document", "read")
    assert permission.resources == ResourceScope.selected(["a"])
    assert permission.fields == ResourceScope.selected(["title"])
    assert narrowed.permission("document", "edit").resources == ResourceScope()
    assert narrowed.permission("source_file", "read").resources == ResourceScope()
    assert not broad.intersect(replace(narrow, valid=False)).valid


@pytest.mark.parametrize("change", [
    {"company_id": "company-b"}, {"policy_version": "policy-2"},
    {"principal": Principal(PrincipalKind.USER, "admin")},
    {"principal": Principal(PrincipalKind.PARTNER, "subject", "client", "installation", "other-grant")},
])
def test_different_identity_tenant_version_or_grant_cannot_be_merged(change):
    value = context()
    with pytest.raises(ValueError):
        value.intersect(replace(value, **change))


def test_select_always_intersects_and_does_not_mutate_original():
    value = context(resources=ResourceScope.selected(["a"]))
    narrowed = value.select("document", "read", ResourceScope.selected(["outside"]))
    assert narrowed.permission("document", "read").resources.mode is ScopeMode.EMPTY
    assert value.permission("document", "read").resources.ids == {"a"}
    assert value.select("document", "read", ResourceScope.all()) == value


@pytest.mark.parametrize("kind", [PrincipalKind.PARTNER, PrincipalKind.SERVICE])
def test_machine_identity_requires_client_and_grant(kind):
    with pytest.raises(ValueError):
        Principal(kind, "subject")


def test_user_is_not_a_principal_and_duplicate_permissions_are_rejected():
    with pytest.raises(ValueError):
        AccessContext({"id": "admin", "is_superadmin": True}, "company-a", "policy-1")
    with pytest.raises(ValueError):
        replace(context(), permissions=context().permissions * 2)
    with pytest.raises(ValueError):
        Principal("user", "subject")
    with pytest.raises(ValueError):
        Principal(PrincipalKind.PUBLIC, "admin")
