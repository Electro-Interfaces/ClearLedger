"""Current member/role policy for monitoring; no database fixture or network."""
from types import SimpleNamespace
import uuid

import pytest
from app.models import CompanyRole, UserCompany
from app.services import partner_identity as identity


@pytest.mark.parametrize("modules,expected", [
    (None, True), ([], False), (["ops"], True), (["ops:ops_state"], True),
    (["ops:ops_reliability"], True), (["ops:ops_overview"], False),
    (["ops:contracts"], False), (["equipment"], False), (["developer"], False),
])
def test_monitoring_scope_requires_current_operational_right(monkeypatch, modules, expected):
    company = uuid.uuid4()
    member = SimpleNamespace(role="user", role_id=None, modules=modules)
    user = SimpleNamespace(id=uuid.uuid4(), is_superadmin=False, mail_only=False,
        password_hash="synthetic", locked_until=None)
    monkeypatch.setattr(identity, "fresh", lambda db, model, key: member if model is UserCompany else None)
    allowed = identity.eligible_scopes(None, user, company)
    assert ("monitoring:read" in allowed) is expected
    # The second required scope is independent: ops permission cannot silently
    # grant access to the object catalogue or widen resource identifiers.
    assert ("objects:read" in allowed) is (modules is None or "equipment" in modules)


def test_monitoring_scope_reloads_company_role_and_rejects_foreign_role(monkeypatch):
    company = uuid.uuid4()
    member = SimpleNamespace(role="user", role_id=uuid.uuid4(), modules=["ops"])
    role = SimpleNamespace(company_id=company, modules=["ops:ops_overview"])
    user = SimpleNamespace(id=uuid.uuid4(), is_superadmin=False, mail_only=False,
        password_hash="synthetic", locked_until=None)
    monkeypatch.setattr(identity, "fresh", lambda db, model, key: member if model is UserCompany else role)
    assert "monitoring:read" not in identity.eligible_scopes(None, user, company)
    role.modules = ["ops:ops_state"]
    assert "monitoring:read" in identity.eligible_scopes(None, user, company)
    role.company_id = uuid.uuid4()
    assert identity.eligible_scopes(None, user, company) == set()


@pytest.mark.parametrize("superadmin", [False, True])
def test_monitoring_scope_never_bypasses_membership_or_disabled_account(monkeypatch, superadmin):
    company = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superadmin=superadmin, mail_only=False,
        password_hash="synthetic", locked_until=None)
    monkeypatch.setattr(identity, "fresh", lambda *args: None)
    assert identity.eligible_scopes(None, user, company) == set()
    member = SimpleNamespace(role="admin", role_id=None, modules=[])
    monkeypatch.setattr(identity, "fresh", lambda *args: member)
    assert "monitoring:read" in identity.eligible_scopes(None, user, company)
    user.mail_only = True
    assert identity.eligible_scopes(None, user, company) == set()
