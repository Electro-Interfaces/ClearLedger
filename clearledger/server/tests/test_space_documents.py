"""Навигационная projection: реальные связи, ACL и предсказуемый основной файл.

Интеграционные проверки используют штатную SQL-схему из conftest и только
явно выделенную TEST_DATABASE_URL. Никаких физических файлов не создаётся.
"""
import itertools
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import (
    Company, Contract, Counterparty, DocAccessGrant, DocCard, DocKind,
    DocRelation, DocVersion, EzsProject, EzsSite, EzsSiteDoc, Organization,
    SourceFile, User, UserCompany,
)
from app.services.space_documents import _contract_owners, _file_priority, space_documents


def test_unit_contract_owners_are_scoped_complete_and_stable():
    first, second, foreign = [uuid.UUID(int=i) for i in (1, 2, 3)]
    refs = [f"contract:{first}", f"contract:{second}", f"contract:{foreign}",
            "contract:broken", "task:unrelated", f"contract:{first}"]
    for ordered in (refs, list(reversed(refs))):
        assert _contract_owners(f"contract:{second}", ordered, {first, second}) == [second, first]
        assert _contract_owners(f"contract:{foreign}", ordered, {first, second}) == [first, second]
        assert _contract_owners("contract:broken", ordered, {first, second}) == [first, second]
    assert _contract_owners(None, [], {first}) == []


def test_unit_primary_file_does_not_depend_on_query_order():
    versions = [DocVersion(id=uuid.uuid4(), role=role, revision=revision,
                           uploaded_at=datetime(2026, 10, 22, tzinfo=timezone.utc))
                for role, revision in [("body", 5), ("signed_scan", 1),
                                       ("appendix", 20), ("attachment", 30)]]
    for ordered in itertools.permutations(versions):
        assert min(ordered, key=_file_priority).role == "signed_scan"
    assert min([v for v in versions if v.role != "signed_scan"], key=_file_priority).role == "body"
    older = DocVersion(id=uuid.UUID(int=1), role="body", revision=4)
    assert min([older, versions[0]], key=_file_priority) is versions[0]
    early = DocVersion(id=uuid.UUID(int=2), role="body", revision=5,
                       uploaded_at=datetime(2026, 10, 20, tzinfo=timezone.utc))
    same = DocVersion(id=uuid.UUID(int=1), role="body", revision=5,
                      uploaded_at=versions[0].uploaded_at)
    assert min([early, versions[0]], key=_file_priority) is versions[0]
    assert min([same, versions[0]], key=_file_priority) is same


@pytest.fixture
async def context(db):
    cid = (await db.execute(select(Company.id).where(Company.slug == "rushydro"))).scalar_one()
    other = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    user = User(email=f"projection-{uuid.uuid4().hex}@example.test", name="Тест projection",
                password_hash="unused", company_id=cid, is_superadmin=False)
    kind = DocKind(company_id=cid, code=uuid.uuid4().hex, name="Навигация")
    db.add_all([user, kind])
    await db.flush()
    db.add(UserCompany(company_id=cid, user_id=user.id, role="user"))
    await db.commit()
    return cid, other, user, kind


async def _contract(db, cid):
    cp = Counterparty(company_id=cid, inn=str(uuid.uuid4().int)[:10], name="Тест контрагента")
    org = Organization(company_id=cid, inn=str(uuid.uuid4().int)[:10], name="Тест юрлица")
    db.add_all([cp, org])
    await db.flush()
    contract = Contract(company_id=cid, number=uuid.uuid4().hex[:12], date="2026-10-22",
                        type="Прочее", counterparty_id=cp.id, organization_id=org.id)
    db.add(contract)
    await db.flush()
    return contract


async def _file(db, cid, name="body.pdf"):
    file = SourceFile(company_id=cid, file_name=name, size=42, storage_path="synthetic/not-written")
    db.add(file)
    await db.flush()
    return file


@pytest.mark.asyncio(loop_scope="session")
async def test_doc_retains_identity_all_contract_owners_and_one_leaf(db, context, auth_client):
    cid, other, user, kind = context
    contracts = [await _contract(db, owner) for owner in (cid, cid, other)]
    a, b, foreign = contracts
    doc = DocCard(company_id=cid, kind_id=kind.id, title="Одна бумага",
                  subject_ref=f"contract:{b.id}")
    db.add(doc)
    await db.flush()
    db.add_all([DocRelation(company_id=cid, doc_id=doc.id, target_ref=f"contract:{c.id}")
                for c in contracts])
    # Даже существующий договор своей компании не становится владельцем через
    # relation, ошибочно записанную от другой компании.
    ignored = await _contract(db, cid)
    db.add(DocRelation(company_id=other, doc_id=doc.id, target_ref=f"contract:{ignored.id}"))
    await db.commit()
    result = await auth_client.get("/api/references/space-documents", params={"company_id": "rushydro"})
    assert result.status_code == 200, result.text
    leaves = [r for r in result.json() if r.get("docId") == str(doc.id)]
    assert len(leaves) == 1
    leaf = leaves[0]
    assert leaf["id"] == f"doc-{doc.id}" and leaf["fileId"] is None
    assert leaf["contractId"] == str(b.id)
    assert leaf["contractIds"] == [str(b.id), str(a.id)]
    assert str(foreign.id) not in str(result.json())
    assert any(r["id"] == f"contract-{a.id}" and r["contractId"] == str(a.id) for r in result.json())
    assert (await db.execute(select(func.count()).select_from(DocCard).where(DocCard.id == doc.id))).scalar_one() == 1
    # Неверный subject_ref не скрывает настоящую relation; сам документ без
    # договора остаётся открываемым через docId.
    doc.subject_ref = "contract:not-a-uuid"
    await db.commit()
    leaf = next(r for r in await space_documents(db, cid, user) if r.get("docId") == str(doc.id))
    assert leaf["contractIds"] == sorted([str(a.id), str(b.id)])
    assert leaf["contractId"] == leaf["contractIds"][0]
    unbound = DocCard(company_id=cid, kind_id=kind.id, title="Без файла и договора")
    db.add(unbound)
    await db.commit()
    leaf = next(r for r in await space_documents(db, cid, user) if r.get("docId") == str(unbound.id))
    assert leaf["fileId"] is None and leaf["contractId"] is None and leaf["contractIds"] == []


@pytest.mark.asyncio(loop_scope="session")
async def test_primary_file_uses_current_live_scoped_role_not_last_row(db, context):
    cid, other, user, kind = context
    doc = DocCard(company_id=cid, kind_id=kind.id, title="Основная редакция")
    db.add(doc)
    await db.flush()
    versions = []
    for index, (role, current, tombstoned, owner) in enumerate([
        ("body", True, False, cid), ("signed_scan", True, False, cid),
        ("appendix", True, False, cid), ("attachment", True, False, cid),
        ("signed_scan", False, False, cid), ("signed_scan", True, True, cid),
        ("foreign_role", True, False, other),
    ]):
        file = await _file(db, owner, f"{index}-{role}.pdf")
        version = DocVersion(company_id=owner, doc_id=doc.id, role=role, revision=index + 1,
                             file_id=file.id, file_name=file.file_name, sha256=f"{index:064x}",
                             is_current=current,
                             tombstoned_at=datetime.now(timezone.utc) if tombstoned else None)
        versions.append(version)
        db.add(version)
    await db.commit()
    leaf = next(r for r in await space_documents(db, cid, user) if r.get("docId") == str(doc.id))
    assert leaf["fileId"] == str(versions[1].file_id)
    assert leaf["fileName"] == "1-signed_scan.pdf" and leaf["docId"] == str(doc.id)
    versions[1].is_current = False
    await db.commit()
    leaf = next(r for r in await space_documents(db, cid, user) if r.get("docId") == str(doc.id))
    assert leaf["fileId"] == str(versions[0].file_id)
    for version in versions[:4]:
        version.is_current = False
    await db.commit()
    leaf = next(r for r in await space_documents(db, cid, user) if r.get("docId") == str(doc.id))
    assert leaf["fileId"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_projection_preserves_private_and_denied_acl_and_company_scope(db, context):
    cid, other, user, kind = context
    docs = [DocCard(company_id=cid, kind_id=kind.id, title=title, confidentiality=privacy)
            for title, privacy in [("Общий", "company"), ("Закрытый", "private"),
                                   ("Выданный", "private"), ("Запрещённый", "company")]]
    db.add_all(docs)
    foreign_kind = DocKind(company_id=other, code=uuid.uuid4().hex, name="Чужой вид")
    db.add(foreign_kind)
    await db.flush()
    foreign = DocCard(company_id=other, kind_id=foreign_kind.id, title="Чужая бумага")
    db.add(foreign)
    db.add_all([
        DocAccessGrant(company_id=cid, scope_type="doc", scope_id=docs[2].id,
                       subject_type="user", subject_id=user.id, permissions=["read"]),
        DocAccessGrant(company_id=cid, scope_type="doc", scope_id=docs[3].id,
                       subject_type="user", subject_id=user.id, denied_permissions=["read"]),
    ])
    await db.commit()
    visible = {r.get("docId") for r in await space_documents(db, cid, user)}
    assert str(docs[0].id) in visible and str(docs[2].id) in visible
    assert not visible.intersection({str(docs[1].id), str(docs[3].id), str(foreign.id)})


@pytest.mark.asyncio(loop_scope="session")
async def test_site_owners_validate_company_and_site_and_separate_explicit_projects(db, context):
    cid, other, user, _ = context
    sites = [EzsSite(company_id=owner, title="Одинаковая площадка") for owner in (cid, cid, other)]
    db.add_all(sites)
    await db.flush()
    site, unrelated, foreign_site = sites
    projects = [EzsProject(company_id=owner, site_id=sid, title="Одинаковое имя")
                for owner, sid in [(cid, site.id), (cid, site.id), (cid, unrelated.id), (other, foreign_site.id)]]
    db.add_all(projects)
    await db.flush()
    own_file, foreign_file = await _file(db, cid), await _file(db, other, "secret.pdf")
    docs = [EzsSiteDoc(company_id=cid, site_id=site.id, project_id=pid,
                       file_id=own_file.id, kind="other", title="Документ")
            for pid in (projects[0].id, projects[1].id, None, projects[2].id, projects[3].id)]
    # Ошибочная межтенантная площадка не должна раскрыть даже свой ID в navigation.
    bad_site = EzsSiteDoc(company_id=cid, site_id=foreign_site.id, kind="other")
    bad_file = EzsSiteDoc(company_id=cid, site_id=site.id, file_id=foreign_file.id, kind="other")
    foreign_doc = EzsSiteDoc(company_id=other, site_id=foreign_site.id, kind="other")
    db.add_all([*docs, bad_site, bad_file, foreign_doc])
    await db.commit()
    rows = await space_documents(db, cid, user)
    leaves = {r["siteDocId"]: r for r in rows if r.get("siteDocId")}
    for doc in docs:
        assert leaves[str(doc.id)]["siteId"] == str(site.id)
        assert leaves[str(doc.id)]["fileId"] == str(own_file.id)
    assert leaves[str(docs[0].id)]["projectId"] == str(projects[0].id)
    assert leaves[str(docs[1].id)]["projectId"] == str(projects[1].id)
    assert leaves[str(docs[0].id)]["catalog"] != leaves[str(docs[1].id)]["catalog"]
    assert leaves[str(docs[2].id)]["catalog"] == "Проекты/Одинаковая площадка/Прочее"
    for doc in docs[2:]:
        assert leaves[str(doc.id)]["projectId"] is None
    assert str(bad_site.id) not in leaves and str(foreign_doc.id) not in leaves
    assert leaves[str(bad_file.id)]["fileId"] is None
    assert leaves[str(bad_file.id)]["fileName"] is None
    assert str(foreign_site.id) not in str(rows) and str(projects[3].id) not in str(rows)
