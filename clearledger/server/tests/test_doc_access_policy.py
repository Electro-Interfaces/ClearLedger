"""Characterization of the shared policy, using only synthetic principals/files."""
import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import DocAccessGrant, DocCard
from app.routers import docs_router
from app.services import doc_access as policy


@pytest.fixture
def access(monkeypatch):
    cid, uid = uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=uid, is_superadmin=False)
    doc = SimpleNamespace(
        id=uuid.uuid4(), company_id=cid, kind_id=uuid.uuid4(),
        author_id=uuid.uuid4(), responsible_id=None, signatory_id=None,
        confidentiality="company", inherit_kind_acl=True,
        retention_state="active", status="draft", approval_round=1,
        approval_status="none", reg_number=None, case_id=None,
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(
        role="member", role_id=None, department_id=None))
    db.scalar = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(policy.doc_approvals, "active_principals_for",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr(policy.doc_approvals, "active_deputy_for",
                        AsyncMock(return_value=[]))
    monkeypatch.setattr(policy, "_access_rows", AsyncMock(return_value=[]))
    return db, cid, doc, user


@pytest.mark.parametrize("confidentiality,owner,admin,permission,expected", [
    ("company", False, False, "read", True),
    ("company", False, False, "download", True),
    ("company", False, False, "print", True),
    ("company", False, False, "edit", False),
    ("company", False, False, "send", False),
    ("company", False, False, "export", False),
    ("company", False, False, "archive", False),
    ("company", False, False, "manage_acl", False),
    ("private", False, True, "read", False),
    ("private", False, True, "edit", False),
    ("private", True, True, "edit", True),
    ("private", True, False, "send", True),
    ("strict", True, False, "read", True),
    ("strict", True, False, "download", False),
    ("strict", True, False, "print", False),
    ("strict", True, False, "export", False),
    ("strict", True, False, "send", False),
    ("company", False, True, "archive", True),
    ("company", True, False, "unknown_action", False),
])
async def test_action_matrix(access, confidentiality, owner, admin, permission, expected):
    db, cid, doc, user = access
    doc.confidentiality = confidentiality
    if owner:
        doc.author_id = user.id
    db.get.return_value.role = "admin" if admin else "member"
    assert await policy._can_doc(db, cid, doc, user, permission) is expected
    db.commit.assert_not_called()


@pytest.mark.parametrize("subject_type", ["user", "role", "department"])
@pytest.mark.parametrize("permission", sorted(policy._CONTENT_PERMISSIONS))
async def test_deny_read_overrides_owner_admin_and_grant(access, subject_type, permission):
    db, cid, doc, user = access
    doc.author_id = user.id
    membership = db.get.return_value
    membership.role = "admin"
    membership.role_id, membership.department_id = uuid.uuid4(), uuid.uuid4()
    subject_id = {"user": user.id, "role": membership.role_id,
                  "department": membership.department_id}[subject_type]
    policy._access_rows.return_value = [DocAccessGrant(
        subject_type=subject_type, subject_id=subject_id,
        permissions=[permission], denied_permissions=["read"],
    )]
    assert not await policy._can_doc(db, cid, doc, user, permission)


@pytest.mark.parametrize("state", ["destruction_authorized", "primary_purged", "destroyed"])
@pytest.mark.parametrize("permission", ["download", "print", "send", "export"])
async def test_retention_blocks_content_even_for_superadmin(access, state, permission):
    db, cid, doc, user = access
    user.is_superadmin = True
    doc.retention_state = state
    assert not await policy._can_doc(db, cid, doc, user, permission)
    policy._access_rows.assert_not_awaited()


async def test_superadmin_strict_requires_break_glass_and_cannot_archive(access, monkeypatch):
    db, cid, doc, user = access
    user.is_superadmin = True
    doc.confidentiality = "strict"
    grant = AsyncMock(return_value=False)
    monkeypatch.setattr(policy, "_active_break_glass", grant)
    assert not await policy._can_doc(db, cid, doc, user, "read")
    grant.return_value = True
    assert await policy._can_doc(db, cid, doc, user, "download",
                                 record_break_glass_use=False)
    grant.assert_awaited_with(db, cid, doc, user, "download", record_use=False)
    grant.reset_mock()
    assert not await policy._can_doc(db, cid, doc, user, "archive")
    grant.assert_not_awaited()


async def test_break_glass_usage_and_read_only_probe(access, monkeypatch):
    db, cid, doc, user = access
    row = SimpleNamespace(id=uuid.uuid4(), use_count=2, last_used_at=None)
    db.execute.return_value.scalar_one_or_none.return_value = row
    audit = AsyncMock()
    monkeypatch.setattr(policy, "log_audit", audit)
    assert await policy._active_break_glass(db, cid, doc, user, "read", record_use=False)
    assert row.use_count == 2 and row.last_used_at is None
    audit.assert_not_awaited()
    assert await policy._active_break_glass(db, cid, doc, user, "read")
    assert row.use_count == 3 and row.last_used_at is not None
    assert audit.await_args.kwargs["action"] == "doc.break_glass.use"
    assert audit.await_args.kwargs["details"]["permission"] == "read"
    db.execute.reset_mock()
    assert not await policy._active_break_glass(db, cid, doc, user, "send")
    db.execute.assert_not_awaited()


async def test_principal_policy_limits_deputy_signing(access):
    db, cid, doc, user = access
    doc.signatory_id = uuid.uuid4()
    policy.doc_approvals.active_deputy_for.return_value = [user.id]
    # Grant to the deputy does not override a denial for the principal.
    policy._access_rows.return_value = [
        DocAccessGrant(subject_type="user", subject_id=user.id,
                       permissions=["sign"], denied_permissions=[]),
        DocAccessGrant(subject_type="user", subject_id=doc.signatory_id,
                       permissions=[], denied_permissions=["sign"]),
    ]
    assert not await policy._can_doc(db, cid, doc, user, "sign")
    policy._access_rows.return_value.pop()
    # An allow-list for sign exists, and includes only the deputy, not principal.
    assert not await policy._can_doc(db, cid, doc, user, "sign")
    policy._access_rows.return_value = []
    assert await policy._can_doc(db, cid, doc, user, "sign")


@pytest.mark.parametrize("permission,message", [
    ("read", "Документ закрыт"), ("edit", "Недостаточно прав на документ"),
])
async def test_permission_error_contract(access, permission, message):
    db, cid, doc, user = access
    doc.confidentiality = "private"
    with pytest.raises(HTTPException) as error:
        await policy._assert_doc_permission(db, cid, doc, user, permission)
    assert (error.value.status_code, error.value.detail) == (403, message)


def result(rows):
    value = MagicMock()
    value.scalars.return_value.all.return_value = rows
    value.all.return_value = rows
    return value


@pytest.mark.parametrize("removed", ["tombstoned_at", "archive_purged_at"])
async def test_file_download_never_falls_back_from_removed_version_to_inbox(access, monkeypatch, removed):
    db, cid, doc, user = access
    file_id = uuid.uuid4()
    version = SimpleNamespace(doc_id=doc.id, tombstoned_at=None, archive_purged_at=None)
    setattr(version, removed, object())
    db.execute.side_effect = [result([version]), result([doc])]
    can_doc = AsyncMock(return_value=True)
    monkeypatch.setattr(policy, "_can_doc", can_doc)
    with pytest.raises(HTTPException) as error:
        await policy.authorize_docs_file_download(db, user, file_id)
    assert (error.value.status_code, error.value.detail) == (404, "Не найдено")
    can_doc.assert_not_awaited()
    assert db.execute.await_count == 2


async def test_download_and_egress_have_separate_permissions(access, monkeypatch):
    db, cid, doc, user = access
    file_id = uuid.uuid4()
    version = SimpleNamespace(doc_id=doc.id, file_id=file_id,
                              tombstoned_at=None, archive_purged_at=None)
    can_doc = AsyncMock(side_effect=lambda *args: args[-1] == "download")
    monkeypatch.setattr(policy, "_can_doc", can_doc)
    db.execute.side_effect = [result([version]), result([doc])]
    await policy.authorize_docs_file_download(db, user, file_id)
    can_doc.assert_awaited_with(db, cid, doc, user, "download")
    db.execute.side_effect = [result([version]), result([doc])]
    with pytest.raises(HTTPException) as error:
        await policy.authorize_docs_file_egress(db, user, [file_id])
    assert (error.value.status_code, error.value.detail) == (404, "Файл вложения не найден")
    can_doc.assert_awaited_with(db, cid, doc, user, "send")


async def test_unrelated_source_file_is_outside_document_guard(access):
    db, _, _, user = access
    db.execute.side_effect = [result([]), result([]), result([])]
    await policy.authorize_docs_file_download(db, user, uuid.uuid4())
    assert await policy.authorize_docs_file_egress(db, user, [uuid.uuid4()]) == []


@pytest.mark.parametrize("allowed", [True, False])
async def test_inbox_file_needs_incoming_processing_permission(access, monkeypatch, allowed):
    db, cid, _, user = access
    db.execute.side_effect = [result([]), result([SimpleNamespace(company_id=cid, doc_id=None)])]
    process = AsyncMock(return_value=allowed)
    monkeypatch.setattr(policy, "_can_process_inbox", process)
    if allowed:
        await policy.authorize_docs_file_download(db, user, uuid.uuid4())
    else:
        with pytest.raises(HTTPException) as error:
            await policy.authorize_docs_file_download(db, user, uuid.uuid4())
        assert error.value.status_code == 404
    process.assert_awaited_once_with(db, cid, user)


@pytest.mark.parametrize("state", ["destruction_authorized", "primary_purged", "destroyed"])
async def test_egress_rejects_retained_file_before_permission_check(access, monkeypatch, state):
    db, cid, doc, user = access
    doc.retention_state = state
    file_id = uuid.uuid4()
    version = SimpleNamespace(doc_id=doc.id, file_id=file_id,
                              tombstoned_at=None, archive_purged_at=None)
    db.execute.side_effect = [result([version]), result([doc])]
    can_doc = AsyncMock(return_value=True)
    monkeypatch.setattr(policy, "_can_doc", can_doc)
    with pytest.raises(HTTPException) as error:
        await policy.authorize_docs_file_egress(db, user, [file_id])
    assert error.value.status_code == 404
    can_doc.assert_not_awaited()
    query = db.execute.await_args.args[0]
    assert "FOR UPDATE" in str(query.compile(dialect=postgresql.dialect()))


async def test_egress_requires_each_document_file_and_deduplicates(access, monkeypatch):
    db, cid, doc, user = access
    files = [uuid.uuid4(), uuid.uuid4()]
    versions = [SimpleNamespace(doc_id=doc.id, file_id=file_id,
                                tombstoned_at=None, archive_purged_at=None)
                for file_id in files]
    db.execute.side_effect = [result(versions), result([doc])]
    can_doc = AsyncMock(return_value=True)
    monkeypatch.setattr(policy, "_can_doc", can_doc)
    assert await policy.authorize_docs_file_egress(db, user, files + files) == [doc]
    assert can_doc.await_count == 2
    can_doc.side_effect = [True, False]
    db.execute.side_effect = [result(versions), result([doc])]
    with pytest.raises(HTTPException) as error:
        await policy.authorize_docs_file_egress(db, user, files)
    assert error.value.status_code == 404


@pytest.mark.parametrize("role,modules,expected", [
    ("admin", [], True), ("member", None, True), ("member", ["docs"], True),
    ("member", ["docs:incoming"], True), ("member", ["tasks"], False),
    ("member", [], False),
])
async def test_docs_members_requires_document_module(access, monkeypatch, role, modules, expected):
    db, cid, _, user = access
    db.execute.return_value = result([(user, SimpleNamespace(role=role))])
    monkeypatch.setattr(policy, "resolve_member_modules", AsyncMock(return_value=modules))
    members = await policy._docs_members(db, cid)
    assert (user.id in members) is expected
    # SQL also excludes mail-only/service users and binds the selected company.
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "mail_only IS false" in sql and "company_id =" in sql
    db.execute.reset_mock()
    assert await policy._docs_members(db, cid, user_ids=set()) == {}
    db.execute.assert_not_awaited()


async def test_readable_clause_keeps_tenant_scoped_grants_and_kind_inheritance(access):
    db, cid, _, user = access
    clause = await policy._readable_doc_clause(db, cid, user)
    statement = select(DocCard.id).where(DocCard.company_id == cid, clause)
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "doc_cards.company_id =" in sql
    assert "doc_access_grants.company_id =" in sql
    assert "doc_approvals.company_id =" in sql and "doc_acquaints.company_id =" in sql
    assert "inherit_kind_acl IS true" in sql
    assert "denied_permissions @>" in sql and "NOT (EXISTS" in sql
    assert cid in compiled.params.values()


@pytest.mark.parametrize("inherit", [True, False])
async def test_access_rows_keep_company_and_explicit_kind_inheritance(access, inherit):
    db, cid, doc, _ = access
    doc.inherit_kind_acl = inherit
    db.execute.return_value = result([])
    # Exercise the real query, not the decision fixture's replacement.
    original = docs_router._access_rows
    assert await original(db, cid, doc) == []
    query = db.execute.await_args.args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    assert "company_id =" in str(compiled)
    assert cid in compiled.params.values() and doc.id in compiled.params.values()
    assert (doc.kind_id in compiled.params.values()) is inherit


def test_compatibility_exports_are_the_shared_implementations():
    for name, value in vars(policy).items():
        if callable(value) and getattr(value, "__module__", None) == policy.__name__:
            assert getattr(docs_router, name) is value, name
    assert docs_router._CONTENT_PERMISSIONS is policy._CONTENT_PERMISSIONS
    assert docs_router._BREAK_GLASS_PERMISSIONS is policy._BREAK_GLASS_PERMISSIONS


def test_document_services_do_not_import_document_http_router():
    services = Path(policy.__file__).parent
    for name in ("doc_access", "space_documents", "process_documents", "work_links",
                 "acquaint_requests", "ezs_tp_method"):
        tree = ast.parse((services / f"{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "app.routers.docs_router", (name, node.lineno)
                if node.module == "app.routers":
                    assert all(alias.name != "docs_router" for alias in node.names)
                if name == "doc_access":
                    assert not (node.module or "").startswith("app.routers"), node.module
            elif isinstance(node, ast.Import):
                assert all(alias.name != "app.routers.docs_router" for alias in node.names)
