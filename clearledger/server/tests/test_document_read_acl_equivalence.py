"""Actual read-ACL goldens; source pin and coverage map in the companion report.

Only execute the guarded entrypoint in the coordinator's serialized SQL window.
No ACL/verifier/query/listener replacement and no candidate rewrite live here.
"""
import hashlib
import os
from pathlib import Path
import sys

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from tests.partner_test_safety import partner_test_safety_error

ROOT = "6e6cf5010919ca7bfbee35c35ac4745b560d1055"
FLAG = "RUN_DOCUMENT_READ_ACL_EQUIVALENCE_TESTS"
TARGET = "postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_document_read_acl_equivalence_test"
RUNTIME = Path("/srv/projects/api-modernization-test-env-20261029")
UPLOAD = RUNTIME / "document-read-acl-test-uploads"
EMPTY_CWD = RUNTIME / "document-read-acl-empty-test"
EVIDENCE = RUNTIME / "private-document-read-acl-20261030"
CEILING = 256 * 1024 * 1024
SOURCE_PINS = {
    "app/services/doc_access.py": "b2f8c364edf7fd84474faf7b49b3e6a4a64c4148123cb9610c2e5a36dfe3fcbd",
    "app/services/doc_approvals.py": "01952021e056ec80a5a7449e67d489225b7cc7463e96cd6199557656f4a8ecac",
    "app/product_api/queries.py": "1f53491a8e8321ae02ddb991d873836b25e7011ec4071f71cc9540dd9ddab046",
    "app/product_api/access.py": "9edd931485539ffd23e696c4a37efad2e1060d1f69f434ce6b592ea1b1f85ebc",
    "app/models.py": "06bfb7c6f7bce8ac345dbcbe23ee642e932ec2a9341673b20a1205c4f3206fee",
    "app/database.py": "be856862b369d89da8c7993fd974b70481260f37f07b7ca5a6d20db6ac077c3c",
    "tests/conftest.py": "32ea55b426d111d8615e0f85ac7561a55ec802ee98a2b59a336405205ab1f57b",
    "tests/partner_test_safety.py": "43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1",
    "tests/test_partner_resource_query_budget.py": "c450c4c8836cbebb2148528ddcdc67ce5ed041ee073cb9ec2951a58e4cadead1",
    "pytest.ini": "bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601",
}

# With opt-in, guard before pytest/conftest/app/ORM/DB imports. Ordinary
# collection without the flag skips this optional suite before app/DB imports.
error = partner_test_safety_error(os.environ, flag=FLAG)
if os.environ.get(FLAG) != "1" and __name__ != "__main__":
    import pytest
    pytest.skip("Opt in with RUN_DOCUMENT_READ_ACL_EQUIVALENCE_TESTS=1", allow_module_level=True)
if error:
    raise RuntimeError("Refusing document ACL run: " + error)
if any(os.environ.get(key) != TARGET for key in ("TEST_DATABASE_URL", "DATABASE_URL")):
    raise RuntimeError("Refusing document ACL run: both exact owned URIs required")
if (os.environ.get("APP_ENV") != "test" or os.environ.get("UPLOAD_DIR") != str(UPLOAD)
        or os.environ.get("RUN_PARTNER_RESOURCE_TESTS") != "1"
        or os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1"
        or sys.version_info[:3] != (3, 13, 7)
        or Path.cwd() != EMPTY_CWD or any(EMPTY_CWD.iterdir())):
    raise RuntimeError("Refusing document ACL run: flags/Python/test upload/empty cwd required")

if any(hashlib.sha256((SERVER / name).read_bytes()).hexdigest() != digest
       for name, digest in SOURCE_PINS.items()):
    raise RuntimeError("Refusing document ACL baseline: immutable source pins changed")

if __name__ == "__main__":
    import asyncio
    import json
    import signal

    if sys.argv[1:] != ["--execute-approved-baseline"]:
        raise RuntimeError("Explicit coordinator SQL grant required before execution")
    signal.signal(signal.SIGALRM, lambda *_: sys.exit("180s document ACL runner bound exceeded"))
    signal.alarm(180)

    async def preflight():
        import asyncpg
        connection = await asyncpg.connect(TARGET.replace("postgresql+asyncpg:", "postgresql:", 1),
            timeout=5, server_settings={"statement_timeout": "15000", "lock_timeout": "1000"})
        try:
            row = dict(await connection.fetchrow("SELECT current_database() AS db, current_user AS usr, "
                "current_setting('server_version_num')::int AS version, "
                "current_setting('max_locks_per_transaction')::int AS maxlocks, "
                "pg_database_size(current_database()) AS bytes, "
                "(SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' "
                "AND pid <> pg_backend_pid()) AS other_clients"))
            if (row["db"] != "api_document_read_acl_equivalence_test" or row["usr"] != "clearledger"
                    or not 160000 <= row["version"] < 170000 or row["maxlocks"] != 64
                    or row["other_clients"] != 0 or row["bytes"] >= CEILING):
                raise RuntimeError("Synthetic preflight refused: " + json.dumps(row, sort_keys=True))
            EVIDENCE.mkdir(mode=0o700, exist_ok=True)
            if EVIDENCE.stat().st_mode & 0o077:
                raise RuntimeError("Private evidence directory must have mode 0700")
            (EVIDENCE / "preflight.json").write_text(json.dumps(row, sort_keys=True) + "\n")
        finally:
            await connection.close()

    asyncio.run(preflight())
    import pytest
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-c", str(SERVER / "pytest.ini"),
        "-p", "pytest_asyncio.plugin", "-p", "no:cacheprovider", "-q", "-ra", "--maxfail=1",
        "--confcutdir=" + str(SERVER), "--basetemp=" + str(EVIDENCE / "pytest-test-tmp"),
        "-o", "junit_family=legacy", "--junitxml=" + str(EVIDENCE / "results.xml")]))

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from app.models import (Department, DocAccessGrant, DocAcquaint, DocApproval,
    DocBreakGlassAccess, DocCard, DocKind, Organization, User, UserCompany, UserSubstitution)
from app.services import doc_access
from app.services.doc_approvals import BUSINESS_TIMEZONE
from tests.test_partner_resource_query_budget import budget, profiles, signing_pem

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Ten named cases, reused for three real persisted subject kinds. Literal
# expected labels follow the existing read-from-edit and explicit-deny contract.
SCOPE_CASES = (
    ("S01", False, ["read"], [], [], []),
    ("S02", True, ["edit"], [], [], []),
    ("S03", True, [], [], ["read"], []),
    ("S04", False, [], [], ["read"], []),
    ("S05", True, ["read"], [], [], ["read"]),
    ("S06", False, ["read"], [], [], ["read"]),
    ("S07", True, [], ["read"], ["edit"], []),
    ("S08", False, [], ["read"], ["edit"], []),
    ("S09", False, [], [], [], []),
    ("S10", True, [], [], ["edit"], []),
)
SCOPE_GOLDEN = {"S01", "S02", "S03", "S06", "S10"}


async def cards(b, labels):
    """One distinct real kind per card: inherited ACLs cannot bleed across cells."""
    result = {}
    for label in labels:
        kind = DocKind(company_id=b.company.id, code="acl-" + uuid.uuid4().hex[:20],
            name="Synthetic ACL kind", fields=[], route=[])
        b.db.add(kind)
        await b.db.flush()
        row = DocCard(company_id=b.company.id, kind_id=kind.id,
            title="ACL-" + b.company.slug + "-" + label, confidentiality="private",
            author_id=None, responsible_id=None, signatory_id=None)
        b.db.add(row)
        await b.db.flush()
        result[label] = row
    return result


def grant(b, row, *, scope="doc", subject="user", subject_id=None, allow=(), deny=()):
    item = DocAccessGrant(company_id=b.company.id, scope_type=scope,
        scope_id=row.id if scope == "doc" else row.kind_id, subject_type=subject,
        subject_id=b.user.id if subject_id is None else subject_id,
        permissions=list(allow), denied_permissions=list(deny))
    b.db.add(item)
    return item


async def assert_reads(b, rows, expected, *, detail_expected=None):
    """Actual DB SQL and per-card policy each checked against explicit goldens."""
    await b.db.commit()
    clause = await doc_access._readable_doc_clause(b.db, b.company.id, b.user)
    found = set((await b.db.scalars(select(DocCard.id).where(
        DocCard.company_id == b.company.id, DocCard.id.in_([row.id for row in rows.values()]),
        clause))).all())
    assert found == {rows[key].id for key in expected}
    detail_expected = expected if detail_expected is None else detail_expected
    for key, row in rows.items():
        assert await doc_access._can_doc(b.db, b.company.id, row, b.user, "read",
            record_break_glass_use=False) is (key in detail_expected), key


def approval(b, row, assignee, *, round_no=1, status="pending"):
    b.db.add(DocApproval(company_id=b.company.id, doc_id=row.id, assignee_id=assignee,
        round=round_no, step_no=1, step_code="acl", step_name="Synthetic ACL step", status=status))


@pytest.mark.parametrize("subject", ["user", "role", "department"])
async def test_scope_subject_precedence(budget, subject):
    b = budget
    department = Department(company_id=b.company.id, name="Synthetic ACL department")
    b.db.add(department)
    await b.db.flush()
    b.member.department_id = department.id
    subject_id = {"user": b.user.id, "role": b.role.id, "department": department.id}[subject]
    rows = await cards(b, [case[0] for case in SCOPE_CASES])
    for label, inherit, direct, direct_deny, inherited, inherited_deny in SCOPE_CASES:
        row = rows[label]
        row.inherit_kind_acl = inherit
        grant(b, row, subject=subject, subject_id=subject_id, allow=direct, deny=direct_deny)
        if inherited or inherited_deny:
            grant(b, row, scope="kind", subject=subject, subject_id=subject_id,
                allow=inherited, deny=inherited_deny)
    await assert_reads(b, rows, SCOPE_GOLDEN)


async def test_read_bases_and_non_read_denials(budget):
    b = budget
    rows = await cards(b, ["company", "author", "responsible", "signatory", "approval", "acquaint"])
    rows["company"].confidentiality = "company"
    rows["author"].author_id = b.user.id
    rows["responsible"].responsible_id = b.user.id
    rows["signatory"].signatory_id = b.user.id
    # A direct addressee keeps read access to an old/completed approval too.
    approval(b, rows["approval"], b.user.id, round_no=2, status="approved")
    b.db.add(DocAcquaint(company_id=b.company.id, doc_id=rows["acquaint"].id, user_id=b.user.id))
    await assert_reads(b, rows, {"company", "author", "responsible", "signatory", "approval", "acquaint"})
    denials = [grant(b, row, deny=["read"]) for row in rows.values()]
    await assert_reads(b, rows, set())
    # Denying edit does not remove read, and edit still confers read even when
    # a different content action is denied. Do not widen deny-read semantics.
    for item in denials:
        item.denied_permissions = ["edit"]
    rows["author"].author_id = None
    denials[1].permissions = ["edit"]
    denials[1].denied_permissions = ["download"]
    await assert_reads(b, rows, {"company", "author", "responsible", "signatory", "approval", "acquaint"})


async def test_nullable_membership_subjects_and_other_subjects(budget):
    b = budget
    department = Department(company_id=b.company.id, name="Synthetic unassigned department")
    b.db.add(department)
    await b.db.flush()
    b.member.role_id = b.member.department_id = None
    rows = await cards(b, ["user", "other-role", "company"])
    rows["company"].confidentiality = "company"
    grant(b, rows["user"], allow=["read"])
    grant(b, rows["other-role"], subject="role", subject_id=b.role.id, allow=["edit"])
    grant(b, rows["company"], subject="department", subject_id=department.id, deny=["read"])
    # Use another actual member, not an invented nullable subject identity.
    other = User(company_id=b.company.id, name="Synthetic other ACL actor",
        email=uuid.uuid4().hex + "@example.invalid", password_hash="!")
    b.db.add(other)
    await b.db.flush()
    b.db.add(UserCompany(user_id=other.id, company_id=b.company.id, role="user", modules=["docs"]))
    grant(b, rows["user"], subject_id=other.id, deny=["read"])
    grant(b, rows["other-role"], subject_id=other.id, allow=["read"])
    await assert_reads(b, rows, {"user", "company"})


async def test_admin_superadmin_and_strict_break_glass_list_contract(budget):
    b = budget
    rows = await cards(b, ["private", "company", "strict"])
    rows["company"].confidentiality = "company"
    rows["strict"].confidentiality = "strict"
    rows["strict"].author_id = b.user.id
    grant(b, rows["private"], deny=["read"])
    grant(b, rows["company"], deny=["read"])
    b.member.role = "admin"
    await assert_reads(b, rows, {"strict"})
    b.user.is_superadmin = True
    await assert_reads(b, rows, {"private", "company"})
    now = datetime.now(timezone.utc)
    access = DocBreakGlassAccess(company_id=b.company.id, doc_id=rows["strict"].id,
        user_id=b.user.id, permissions=["read"], reason="Synthetic characterization control",
        created_at=now, expires_at=now + timedelta(minutes=5), use_count=0)
    b.db.add(access)
    await assert_reads(b, rows, {"private", "company"}, detail_expected={"private", "company", "strict"})
    await b.db.refresh(access)
    assert access.use_count == 0 and access.last_used_at is None


async def test_current_delegation_assignment_and_explicit_deny(budget):
    b = budget
    principal = User(company_id=b.company.id, name="Synthetic ACL principal",
        email=uuid.uuid4().hex + "@example.invalid", password_hash="!")
    b.db.add(principal)
    await b.db.flush()
    b.db.add(UserCompany(user_id=principal.id, company_id=b.company.id, role="user", modules=["docs"]))
    today = datetime.now(BUSINESS_TIMEZONE).date()
    substitution = UserSubstitution(company_id=b.company.id, user_id=principal.id,
        deputy_id=b.user.id, starts_on=today - timedelta(days=1), ends_on=today + timedelta(days=1))
    b.db.add(substitution)
    rows = await cards(b, ["draft", "registered", "archived", "pending", "old-round", "completed", "denied"])
    for label in ("draft", "registered", "archived"):
        rows[label].status = label
        rows[label].signatory_id = principal.id
    # Model default is round 0. Make current=2 and previous=1 explicit.
    for row in rows.values():
        row.approval_round = 2
    approval(b, rows["pending"], principal.id, round_no=2)
    approval(b, rows["old-round"], principal.id, round_no=1)
    approval(b, rows["completed"], principal.id, round_no=2, status="approved")
    approval(b, rows["denied"], principal.id, round_no=2)
    grant(b, rows["denied"], deny=["read"])
    await assert_reads(b, rows, {"draft", "registered", "pending"})
    substitution.is_active = False
    await assert_reads(b, rows, set())


async def test_actual_product_http_acl_and_scope_intersection(budget):
    b = budget
    await profiles(b)
    rows = await cards(b, ["edit", "kind-deny", "inherit-off", "object", "organization", "grant"])
    org = b.data["contracts"][0].organization_id
    other_org = Organization(company_id=b.company.id, name="Synthetic other ACL organization", inn="9999999998")
    b.db.add(other_org)
    await b.db.flush()
    for row in rows.values():
        row.organization_id = org
        row.object_id = b.data["objects"][0].id
        grant(b, row, allow=["edit"])
    for label in ("kind-deny", "inherit-off"):
        grant(b, rows[label], scope="kind", deny=["read"])
    rows["inherit-off"].inherit_kind_acl = False
    rows["object"].object_id = b.data["objects"][1].id
    rows["organization"].organization_id = other_org.id
    prefix = "ACL-" + b.company.slug
    # Make the tenant negative searchable too: q must not mask a tenant leak.
    b.foreign["documents"].title = prefix + "-foreign"
    await b.db.commit()

    async def http_goldens(expected):
        result = await b.http.get("/documents", params={"q": prefix, "pageSize": 50})
        assert result.status_code == 200, result.text
        value = result.json()
        assert value["total"] == len(expected)
        assert {item["id"] for item in value["items"]} == {str(rows[key].id) for key in expected}
        assert value["nextCursor"] is None
        for label, row in rows.items():
            detail = await b.http.get("/documents/" + str(row.id))
            assert detail.status_code == (200 if label in expected else 404), (label, detail.text)
        assert (await b.http.get("/documents/" + str(b.foreign["documents"].id))).status_code == 404
        return value["items"]

    await http_goldens({"edit", "inherit-off", "object", "organization", "grant"})
    # Persist each orthogonal restriction with real token verification intact.
    from app.models_partner import PartnerResourceItem, PartnerResourceScope
    b.member.object_scope = [b.data["objects"][0].id]
    b.member.own_organization_id = org
    document_scope = await b.db.get(PartnerResourceScope, (b.installation.id, "documents"))
    document_scope.mode = "SET"
    b.db.add_all([PartnerResourceItem(installation_id=b.installation.id, kind="documents", document_id=row.id)
        for label, row in rows.items() if label != "grant"])
    # The allowed document remains readable when its related object is outside
    # the object's own resource profile: the DTO redacts the link, not the doc.
    object_scope = await b.db.get(PartnerResourceScope, (b.installation.id, "objects"))
    object_scope.mode = "SET"
    b.db.add(PartnerResourceItem(installation_id=b.installation.id, kind="objects", object_id=b.data["objects"][2].id))
    await b.db.commit()
    items = await http_goldens({"edit", "inherit-off"})
    assert all(item["objectId"] is None for item in items)
