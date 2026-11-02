"""Root-only real PG16/AsyncSession tests; external ABI in P1D-SOURCE.md.

Run only under external admission and --noconftest. No target selection, driver
creation, approval issuance, fake identity/facts or metadata projection here.
REAL frozen0db native baseline, corrected6 and candidate7 use separate processes.
Original5141 create_all refusal at prefix3 is retained externally, never repaired.
"""
import sys
from uuid import UUID

import pytest

_admission = sys.modules.get("rushydro_doc_site_root_admission")
if _admission is None:
    pytest.skip("Root-owned running admission required", allow_module_level=True)
_admission.require_running_approval()

from fastapi import HTTPException
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.auth import decode_token, native_claims_context, native_user_from_claims
from app.models import (
    Company, Contract, Counterparty, DocAccessGrant, DocApproval, DocCard, DocInboxItem,
    DocKind, DocVersion, EzsSite, OpsContractTerm, OpsCostItem, Organization,
    ServiceLocation, SourceFile, User, UserCompany,
)
from app.models_site_authority import SiteAuthorityContext, SiteUserPermission
from app.services.doc_access import (
    _archiveable_doc_clause, _can_doc, _readable_doc_clause, _readable_docs,
    assert_fresh_doc_edit, authorize_docs_file_download, authorize_docs_file_egress,
)
from app.services.doc_notice_access import authorized_doc_notice
from app.services.space_documents import space_documents
from schema_migrations.errors import MigrationError
from schema_migrations.manifest import DOC_SITE_BUSINESS_ID, load_known_head
from schema_migrations.runner import execute_sequence, require_applied_prefix, require_site_prefix

pytestmark = pytest.mark.asyncio
BASE = "46566816f59e0d65f61b5426842d6a496e8fc13c"
NATIVE_BASE_SOURCE = "0db9a97e2f6b86f2307cfa5abefb1a32982d37ec"
INITIAL_SOURCE = "5141d7e2521d5b3526f6313d40b06afdea3d36ac"
A, B, ORG, OTHER_ORG, UID, SITE, OTHER_SITE, DOC, LEGACY, KIND, CP, CONTRACT, FILE, VERSION = (
    UUID("70000000-0000-4000-8000-" + f"{n:012d}") for n in range(1, 15))
LOCATION = "Site UUID is not ObjectId"
PERMISSIONS = ("read", "edit", "download", "print", "export", "send", "approve", "sign", "archive", "manage_acl")

# Finite literal inventory, stable external collection/controller ABI.
CASES = (
    "fresh3_to7_repeat", "upgrade6_to7_repeat", "old6_pre_orm_denial", "standalone6_rejects7", "site_uuid_not_object",
    "unrecorded7_denial", "drift_column_default", "drift_context_unique",
    "drift_doc_fk", "drift_term_index", "drift_history", "legacy_null_preserved",
    "date_null_legacy", "date_unknown_legacy", "date_open_ended", "date_until_leap",
    "date_bad_leap", "date_bad_month", "date_bad_day", "date_year_zero",
    "date_reversed", "date_missing", "date_non_iso", "date_unknown_kind", "date_open_with_end",
    "term_site_axis", "term_legacy_axis", "term_foreign_site", "term_site_location", "term_non_site",
    "doc_foreign_site", "doc_wrong_org", "doc_null_org", "doc_object_and_site", "doc_context_delete",
    "native_user_read", "native_admin_read", "native_superadmin_read", "native_author_read",
    "native_edit", "native_download", "native_print", "native_export", "native_send",
    "native_approve", "native_sign", "native_archive", "native_manage_acl",
    "deny_default", "deny_revoked", "deny_unapproved", "deny_assignment", "deny_member",
    "deny_org", "deny_empty_objects", "deny_location_mismatch", "deny_superadmin_revoked",
    "deny_admin_empty_objects", "deny_author_assignment", "deny_action",
    "list_count_limit", "superadmin_list", "archive_sql", "space_documents", "notice", "notice_revoked",
    "file", "file_revoked", "egress", "egress_revoked", "version_tombstone", "linked_inbox", "linked_inbox_revoked",
    "docgrant_deny", "strict_download", "retention_download", "approval_deny",
    "dirty_card_denial", "dirty_user_denial", "dirty_site_pointer", "dirty_doc_company", "dirty_doc_org", "queued_doc_delete", "read_only_revoke",
    "partner_empty_site", "partner_site_set", "partner_revoke_site", "partner_grant_revoke",
    "partner_bound_empty_objects", "partner_file", "partner_file_revoked",
    "partner_doc_set_mid_request", "partner_site_set_mid_request", "partner_action_mid_request", "partner_grant_mid_request",
    "partner_file_doc_set_mid_request", "partner_file_site_set_mid_request",
    "partner_file_action_mid_request", "partner_file_grant_mid_request",
    "native_dirty_title_preserved", "native_dirty_username_preserved",
    "native_pending_site_draft", "native_transient_site_draft",
    "native_pending_null_draft", "native_transient_null_draft",
    "partner_pending_user", "partner_dirty_user", "partner_deleted_user",
    "partner_pending_card", "partner_dirty_card", "partner_deleted_card",
)


async def sql(pg, statement, **params):
    return await pg.session.execute(text(statement), params)


async def upgraded(pg, prefix=6):
    await pg.baseline(prefix=prefix, source=BASE)
    return await execute_sequence(pg.config, target_revision=DOC_SITE_BUSINESS_ID, legacy_sent_before=2000000000)


async def predecessor_rows(pg):
    """Nonempty real schema6 history, using only old columns and literal SQL."""
    await sql(pg, "INSERT INTO core.companies(id,name,slug,profile_id) VALUES (:id,'Synthetic legacy','p1d-legacy','energy')", id=A)
    await sql(pg, "INSERT INTO core.organizations(id,company_id,inn,name) VALUES (:id,:cid,'0000000000','Synthetic legacy org')", id=ORG, cid=A)
    await sql(pg, """INSERT INTO core.counterparties(id,company_id,name,type,aliases,is_group)
        VALUES (:id,:cid,'Synthetic legacy counterparty','ЮЛ','{}',false)""", id=CP, cid=A)
    await sql(pg, """INSERT INTO core.contracts(id,company_id,number,date,valid_until,counterparty_id,organization_id,type)
        VALUES (:id,:cid,'Synthetic legacy','legacy bad date','also historic',:cp,:org,'Synthetic')""",
        id=CONTRACT, cid=A, cp=CP, org=ORG)
    await sql(pg, """INSERT INTO core.ops_cost_items(code,label,sort_order,is_active)
        VALUES ('p1d_legacy','Synthetic legacy',100,true)""")
    for index, scope in ((91, "unsupported"), (92, "site")):
        await sql(pg, """INSERT INTO core.ops_contract_terms
            (id,company_id,contract_id,cost_item,scope_type,location_id,periodicity,valid_from)
            VALUES (:id,:cid,:contract,'p1d_legacy',:scope,NULL,'monthly',:start)""",
            id=UUID("70000000-0000-4000-8000-"+f"{index:012d}"), cid=A, contract=CONTRACT,
            scope=scope, start="2026-01-01" if index == 91 else "2026-02-01")
    await pg.publish()


async def seed(pg, *, authority=True):
    db = pg.session
    db.add_all([Company(id=A, name="Synthetic Site A", slug="p1d-a", profile_id="energy"),
                Company(id=B, name="Synthetic Site B", slug="p1d-b", profile_id="energy")])
    await db.flush()
    db.add_all([Organization(id=ORG, company_id=A, inn="0000000000", name="Synthetic org"),
                Organization(id=OTHER_ORG, company_id=B, inn="0000000000", name="Foreign org"),
                User(id=UID, company_id=A, email="p1d@example.invalid", name="Synthetic user",
                     password_hash="!synthetic-disabled-password", role="user"),
                EzsSite(id=SITE, company_id=A, kind="new_build", stage="lead", title="Synthetic Site"),
                EzsSite(id=OTHER_SITE, company_id=B, kind="new_build", stage="lead", title="Foreign Site"),
                ServiceLocation(id=LOCATION, company_id=A, code="P1D", name="Synthetic point",
                                type="ev_charging", status="active", source_bindings=[]),
                Counterparty(id=CP, company_id=A, name="Synthetic counterparty"),
                OpsCostItem(code="p1d_test", label="Synthetic cost item")])
    await db.flush()
    db.add_all([UserCompany(user_id=UID, company_id=A, own_organization_id=ORG),
                Contract(id=CONTRACT, company_id=A, number="Synthetic", date="old legacy date",
                         counterparty_id=CP, organization_id=ORG, type="Synthetic"),
                DocKind(id=KIND, company_id=A, code="p1d", name="Synthetic kind"),
                SourceFile(id=FILE, company_id=A, file_name="synthetic.txt", purpose="attachment",
                           size=22, storage_path=str(pg.upload_path)),
                SiteAuthorityContext(company_id=A, site_id=SITE, organization_id=ORG,
                                     approved=authority, revoked=not authority)])
    await db.flush()
    db.add_all([SiteUserPermission(company_id=A, site_id=SITE, user_id=UID,
                                  action="document."+p, approved=authority) for p in PERMISSIONS])
    db.add_all([DocCard(id=DOC, company_id=A, kind_id=KIND, title="Synthetic Site document",
                       site_id=SITE, organization_id=ORG, author_id=UID, signatory_id=UID),
                DocCard(id=LEGACY, company_id=A, kind_id=KIND, title="Synthetic legacy document",
                        organization_id=ORG, author_id=UID)])
    await db.flush()
    db.add_all([DocApproval(company_id=A, doc_id=DOC, assignee_id=UID, round=0, status="pending"),
                DocAccessGrant(company_id=A, scope_type="doc", scope_id=DOC,
                               subject_type="user", subject_id=UID, permissions=list(PERMISSIONS)),
                DocVersion(id=VERSION, company_id=A, doc_id=DOC, revision=1, role="body", file_id=FILE,
                           file_name="synthetic.txt", size_bytes=22, sha256="0"*64, is_current=True)])
    await db.flush()
    return await db.get(DocCard, DOC)


async def native_user(pg):
    bearer = await pg.native_bearer(UID, A)
    claims = decode_token(bearer)
    return claims, await native_user_from_claims(claims, pg.session)


async def site_set(pg, iid):
    await sql(pg, """INSERT INTO core.partner_resource_scopes(installation_id,kind,mode)
        VALUES (:iid,'sites','SET') ON CONFLICT (installation_id,kind) DO UPDATE SET mode='SET'""", iid=iid)
    await sql(pg, """INSERT INTO core.partner_resource_items(id,installation_id,kind,site_id)
        VALUES ('70000000-0000-4000-8000-000000000099',:iid,'sites',:site)""", iid=iid, site=SITE)


@pytest.mark.parametrize("case", CASES)
async def test_doc_site_business_native(doc_site_pg, case):
    pg = doc_site_pg
    if case in {"fresh3_to7_repeat", "upgrade6_to7_repeat"}:
        prefix = 3 if case.startswith("fresh") else 6
        result = await upgraded(pg, prefix)
        assert result["prefix_before"] == prefix
        assert result["actions"][-1]["revision"] == DOC_SITE_BUSINESS_ID
        assert await require_applied_prefix(pg.connection, pg.config, load_known_head(), required_revision=DOC_SITE_BUSINESS_ID) == 7
        repeat = await execute_sequence(pg.config, target_revision=DOC_SITE_BUSINESS_ID, legacy_sent_before=2000000000)
        assert repeat["prefix_before"] == 7 and repeat["actions"] == []
        return
    if case in {"old6_pre_orm_denial", "unrecorded7_denial", "legacy_null_preserved"}:
        await pg.baseline(prefix=6, source=BASE)
        if case == "old6_pre_orm_denial":
            from app.database import _require_site_schema, create_all
            with pytest.raises((MigrationError, RuntimeError)):
                await _require_site_schema(await pg.session.connection())
            with pytest.raises((MigrationError, RuntimeError)):
                await create_all()
            assert await pg.connection.fetchval("SELECT count(*) FROM core.core_schema_versions") == 6
            assert not await pg.connection.fetchval("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='core' AND table_name='doc_cards' AND column_name='site_id')")
            return
        if case == "unrecorded7_denial":
            await pg.connection.execute("ALTER TABLE core.doc_cards ADD COLUMN site_id uuid")
            with pytest.raises(MigrationError):
                await execute_sequence(pg.config, target_revision=DOC_SITE_BUSINESS_ID, legacy_sent_before=2000000000)
            assert await pg.connection.fetchval("SELECT count(*) FROM core.core_schema_versions") == 6
            return
        # Raw predecessor columns only, never candidate ORM on schema6.
        await predecessor_rows(pg)
        before = await pg.connection.fetch("SELECT id,date,valid_until FROM core.contracts ORDER BY id")
        terms = await pg.connection.fetch("SELECT id,scope_type,location_id FROM core.ops_contract_terms ORDER BY id")
        assert len(before) == 1 and before[0]["date"] == "legacy bad date"
        assert len(terms) == 2 and {r["scope_type"] for r in terms} == {"unsupported", "site"}
        await execute_sequence(pg.config, target_revision=DOC_SITE_BUSINESS_ID, legacy_sent_before=2000000000)
        assert before == await pg.connection.fetch("SELECT id,date,valid_until FROM core.contracts ORDER BY id")
        assert terms == await pg.connection.fetch("SELECT id,scope_type,location_id FROM core.ops_contract_terms ORDER BY id")
        assert await pg.connection.fetchval("SELECT count(*) FROM core.contracts WHERE validity_kind IS NOT NULL") == 0
        return
    await upgraded(pg)
    if case == "standalone6_rejects7":
        from schema_migrations.catalog import inspect_site_authority
        from schema_migrations.manifest import SITE_AUTHORITY_ID, load
        assert await require_applied_prefix(pg.connection, pg.config, load_known_head(), required_revision=SITE_AUTHORITY_ID) == 7
        with pytest.raises(MigrationError):
            await inspect_site_authority(pg.connection, load(revision=SITE_AUTHORITY_ID).contract, pg.config.user, applied=True)
        return
    if case == "site_uuid_not_object":
        assert await pg.connection.fetchval("SELECT data_type FROM information_schema.columns WHERE table_schema='core' AND table_name='ops_contract_terms' AND column_name='site_id'") == "uuid"
        assert await pg.connection.fetchval("SELECT data_type FROM information_schema.columns WHERE table_schema='core' AND table_name='doc_cards' AND column_name='object_id'") == "character varying"
        return
    if case.startswith("drift_"):
        statement = {
            "drift_column_default": "ALTER TABLE core.doc_cards ALTER COLUMN site_id SET DEFAULT '70000000-0000-4000-8000-000000000006'::uuid",
            "drift_context_unique": "ALTER TABLE core.site_authority_contexts DROP CONSTRAINT uq_site_context_organization CASCADE",
            "drift_doc_fk": "ALTER TABLE core.doc_cards DROP CONSTRAINT fk_doc_cards_site_context",
            "drift_term_index": "DROP INDEX core.uq_ops_term_site",
            "drift_history": "DELETE FROM core.core_schema_versions WHERE ordinal=7",
        }[case]
        await pg.connection.execute(statement)
        with pytest.raises(MigrationError):
            await require_site_prefix(pg.connection)
        return
    doc = await seed(pg, authority=case != "deny_default")
    if case.startswith("date_"):
        kind, start, end, valid = {
            "date_null_legacy": (None, "historic", "not a date", True),
            "date_unknown_legacy": ("unknown", "historic", "not a date", True),
            "date_open_ended": ("openEnded", "historic", None, True),
            "date_until_leap": ("until", "2024-02-29", "2024-03-01", True),
            "date_bad_leap": ("until", "2023-02-29", "2024-03-01", False),
            "date_bad_month": ("until", "2024-13-01", "2025-01-01", False),
            "date_bad_day": ("until", "2024-04-31", "2025-01-01", False),
            "date_year_zero": ("until", "0000-01-01", "2025-01-01", False),
            "date_reversed": ("until", "2025-01-01", "2024-12-31", False),
            "date_missing": ("until", "2024-01-01", None, False),
            "date_non_iso": ("until", "2024-1-01", "2024-12-31", False),
            "date_unknown_kind": ("openended", "2024-01-01", None, False),
            "date_open_with_end": ("openEnded", "2024-01-01", "2025-01-01", False),
        }[case]
        async def update():
            await sql(pg, "UPDATE core.contracts SET validity_kind=:kind,date=:start,valid_until=:end WHERE id=:id",
                      kind=kind, start=start, end=end, id=CONTRACT)
        if valid:
            await update()
        else:
            with pytest.raises(IntegrityError):
                async with pg.session.begin_nested():
                    await update()
        return
    if case.startswith("term_"):
        async def term(site=SITE, scope="site", location=None):
            row = OpsContractTerm(company_id=A, contract_id=CONTRACT, cost_item="p1d_test",
                                  scope_type=scope, site_id=site, location_id=location, valid_from="2026-01-01")
            pg.session.add(row)
            await pg.session.flush()
        if case == "term_site_axis":
            await term()
            await term(None, "unsupported")
            with pytest.raises(IntegrityError):
                async with pg.session.begin_nested():
                    await term()
        elif case == "term_legacy_axis":
            await term(None, "site")
            with pytest.raises(IntegrityError):
                async with pg.session.begin_nested():
                    await term(None, "unsupported")
        else:
            with pytest.raises(IntegrityError):
                async with pg.session.begin_nested():
                    await term(OTHER_SITE if case == "term_foreign_site" else SITE,
                               "company" if case == "term_non_site" else "site",
                               LOCATION if case == "term_site_location" else None)
        return
    if case.startswith("doc_") and case != "docgrant_deny":
        statement, params = {
            "doc_foreign_site": ("UPDATE core.doc_cards SET site_id=:value WHERE id=:id", {"value": OTHER_SITE}),
            "doc_wrong_org": ("UPDATE core.doc_cards SET organization_id=:value WHERE id=:id", {"value": OTHER_ORG}),
            "doc_null_org": ("UPDATE core.doc_cards SET organization_id=NULL WHERE id=:id", {}),
            "doc_object_and_site": ("UPDATE core.doc_cards SET object_id=:value WHERE id=:id", {"value": LOCATION}),
            "doc_context_delete": ("DELETE FROM core.site_authority_contexts WHERE site_id=:id", {}),
        }[case]
        with pytest.raises(IntegrityError):
            async with pg.session.begin_nested():
                await sql(pg, statement, id=SITE if case == "doc_context_delete" else DOC, **params)
        return
    if case.startswith("partner_"):
        bearer, iid = await pg.partner_bearer(UID, A)
        if case != "partner_empty_site":
            await site_set(pg, iid)
        if case == "partner_bound_empty_objects":
            await sql(pg, "UPDATE core.ezs_sites SET location_id=:loc WHERE id=:id", loc=LOCATION, id=SITE)
            await sql(pg, "UPDATE core.user_companies SET object_scope='[]'::jsonb WHERE user_id=:uid", uid=UID)
        await pg.publish()
        if case in {"partner_pending_user", "partner_dirty_user", "partner_deleted_user",
                    "partner_pending_card", "partner_dirty_card", "partner_deleted_card"}:
            path = f"/api/v1/documents/{DOC}"
            assert (await pg.product_get(bearer, path)).status_code == 200
            target = query_db = None
            before_calls = after_calls = 0
            observations = {}
            user_case = case in {"partner_pending_user", "partner_dirty_user", "partner_deleted_user"}
            pending = case in {"partner_pending_user", "partner_pending_card"}
            deleting = case in {"partner_deleted_user", "partner_deleted_card"}
            field = "name" if user_case else "title"
            def snapshot(db):
                # Only bounded primitive observations leave the actual Query
                # Session. No SQL, refresh, flush or lazy attribute loads here.
                state = inspect(target)
                history = state.attrs[field].history
                return (
                    tuple(sorted((key, str(value)) for key, value in state.dict.items()
                                 if key != "_sa_instance_state")),
                    tuple(str(value) for value in history.added),
                    tuple(str(value) for value in history.unchanged),
                    tuple(str(value) for value in history.deleted),
                    state.pending, state.persistent, state.deleted, state.transient,
                    state.detached, state.modified, state.session is db.sync_session,
                    target in db.new, target in db.dirty, target in db.deleted,
                )
            async def before_query(db):
                nonlocal target, query_db, before_calls
                before_calls += 1
                assert before_calls == 1
                query_db = db
                with db.no_autoflush:
                    if pending:
                        if user_case:
                            target = User(id=UUID("70000000-0000-4000-8000-000000000096"),
                                          company_id=A, email="pending-p1d@example.invalid",
                                          name="Pending product user", role="user",
                                          password_hash="!synthetic-disabled-password")
                        else:
                            target = DocCard(id=UUID("70000000-0000-4000-8000-000000000096"),
                                             company_id=A, kind_id=KIND, site_id=SITE,
                                             organization_id=ORG, author_id=UID,
                                             title="Pending product card")
                        db.add(target)
                        assert target in db.new and inspect(target).pending
                    else:
                        target = await db.get(User if user_case else DocCard, UID if user_case else DOC)
                        assert target is not None and inspect(target).persistent
                        if deleting:
                            await db.delete(target)
                            assert target in db.deleted
                        else:
                            setattr(target, field, "Dirty product user" if user_case else "Dirty product card")
                            assert target in db.dirty and inspect(target).modified
                observations["before"] = snapshot(db)
            async def after_query(db):
                nonlocal after_calls, target, query_db
                after_calls += 1
                assert after_calls == 1 and before_calls == 1 and db is query_db
                # Root-approved observer C: after original awaited conditions
                # (also on exception), before unchanged dependency finally.
                observations["after"] = snapshot(db)
                target = query_db = None
            denied = await pg.product_get(bearer, path, before_query=before_query, after_query=after_query)
            assert denied.status_code == 409
            assert before_calls == after_calls == 1
            assert observations["after"] == observations["before"]
            assert b"Synthetic Site document" not in denied.content
            return
        file_case = case in {
            "partner_file", "partner_file_revoked", "partner_file_doc_set_mid_request",
            "partner_file_site_set_mid_request", "partner_file_action_mid_request",
            "partner_file_grant_mid_request",
        }
        path = f"/api/v1/documents/{DOC}" + (f"/versions/{VERSION}/content" if file_case else "")
        # Read the actual seeded sort values with the same ordering as Query;
        # bulk INSERT timestamps need not put the Site card on page one.
        # Observe ordering through the admitted raw connection; keep fixture
        # ORM Session settled before the independent real HTTP request.
        expected_first = await pg.connection.fetchval(
            "SELECT id FROM core.doc_cards WHERE company_id=$1 ORDER BY created_at,id LIMIT 1", A)
        async def assert_listing(*, visible, grant_revoked=False, documents_revoked=False):
            listing = await pg.product_get(bearer, "/api/v1/documents?pageSize=1")
            if grant_revoked:
                assert listing.status_code in {401, 403}
                assert b"Synthetic Site document" not in listing.content
                return
            if documents_revoked:
                # This is a NEW resolver after documents EMPTY: unlike the
                # already-resolved mid-request path it denies before Query.
                assert listing.status_code == 403
                assert b"Synthetic Site document" not in listing.content
                return
            assert listing.status_code == 200
            payload = listing.json()
            assert payload["total"] == (2 if visible else 1)
            assert [item["id"] for item in payload["items"]] == [str(expected_first if visible else LEGACY)]
            if visible:
                positive_listing = await pg.product_get(bearer, "/api/v1/documents?pageSize=2")
                assert positive_listing.status_code == 200
                assert positive_listing.json()["total"] == 2
                assert {item["id"] for item in positive_listing.json()["items"]} == {str(DOC), str(LEGACY)}
            else:
                assert str(DOC) not in {item["id"] for item in listing.json()["items"]}
        mid_request = case.endswith("_mid_request")
        initially_visible = case not in {"partner_empty_site", "partner_bound_empty_objects"}
        await assert_listing(visible=initially_visible)
        if mid_request:
            positive = await pg.product_get(bearer, path)
            assert positive.status_code == 200
            if file_case:
                assert positive.content == b"Site document fixture\n"
        callback_calls = 0
        async def after_resolve():
            # The REAL resolver has closed its identity Session; original Query
            # and file delivery have not run. Only actual committed rows change.
            nonlocal callback_calls
            callback_calls += 1
            assert callback_calls == 1
            if case in {"partner_doc_set_mid_request", "partner_file_doc_set_mid_request"}:
                await sql(pg, "UPDATE core.partner_resource_scopes SET mode='EMPTY' WHERE installation_id=:iid AND kind='documents'", iid=iid)
            elif case in {"partner_site_set_mid_request", "partner_file_site_set_mid_request"}:
                await sql(pg, "UPDATE core.partner_resource_scopes SET mode='EMPTY' WHERE installation_id=:iid AND kind='sites'", iid=iid)
                await sql(pg, "DELETE FROM core.partner_resource_items WHERE installation_id=:iid AND kind='sites'", iid=iid)
            elif case in {"partner_action_mid_request", "partner_file_action_mid_request"}:
                await sql(pg, "UPDATE core.site_user_permissions SET approved=false WHERE site_id=:id", id=SITE)
            elif case in {"partner_grant_mid_request", "partner_file_grant_mid_request"}:
                await sql(pg, "UPDATE core.partner_grants SET approved=false WHERE installation_id=:iid", iid=iid)
            await pg.publish()
        before = await pg.product_get(bearer, path, after_resolve=after_resolve) if mid_request else await pg.product_get(bearer, path)
        assert callback_calls == (1 if mid_request else 0)
        expected = 404 if case in {"partner_empty_site", "partner_bound_empty_objects"} or mid_request else 200
        grant_revoked = case in {"partner_grant_mid_request", "partner_file_grant_mid_request"}
        if grant_revoked:
            assert before.status_code in {401, 403}
        else:
            assert before.status_code == expected
        if file_case:
            if before.status_code == 200:
                assert before.content == b"Site document fixture\n"
            else:
                assert b"Site document fixture" not in before.content
                assert "content-disposition" not in before.headers
                assert before.headers.get("content-type", "").split(";")[0] != "application/octet-stream"
        if case in {"partner_revoke_site", "partner_file_revoked", "partner_grant_revoke"}:
            if case == "partner_grant_revoke":
                await sql(pg, "UPDATE core.partner_grants SET approved=false WHERE installation_id=:iid", iid=iid)
            else:
                await sql(pg, "UPDATE core.partner_resource_scopes SET mode='EMPTY' WHERE installation_id=:iid AND kind='sites'", iid=iid)
                await sql(pg, "DELETE FROM core.partner_resource_items WHERE installation_id=:iid AND kind='sites'", iid=iid)
            await pg.publish()
            revoked = await pg.product_get(bearer, path)
            grant_revoked = case == "partner_grant_revoke"
            if grant_revoked:
                assert revoked.status_code in {401, 403}
            else:
                assert revoked.status_code == 404
            if file_case:
                assert b"Site document fixture" not in revoked.content
                assert "content-disposition" not in revoked.headers
                assert revoked.headers.get("content-type", "").split(";")[0] != "application/octet-stream"
        await assert_listing(
            visible=initially_visible and not mid_request and case not in {
                "partner_revoke_site", "partner_file_revoked", "partner_grant_revoke"},
            grant_revoked=grant_revoked,
            documents_revoked=case in {"partner_doc_set_mid_request", "partner_file_doc_set_mid_request"},
        )
        return
    claims, user = await native_user(pg)
    if case in {"native_admin_read", "deny_admin_empty_objects"}:
        await sql(pg, "UPDATE core.user_companies SET role='admin' WHERE user_id=:uid", uid=UID)
    if case in {"native_superadmin_read", "deny_superadmin_revoked", "superadmin_list"}:
        user.is_superadmin = True
        await pg.session.flush()
    if case in {"deny_revoked", "deny_superadmin_revoked", "notice_revoked", "file_revoked", "egress_revoked", "read_only_revoke", "linked_inbox_revoked"}:
        await sql(pg, "UPDATE core.site_authority_contexts SET revoked=true WHERE site_id=:id", id=SITE)
    if case == "deny_unapproved":
        await sql(pg, "UPDATE core.site_authority_contexts SET approved=false WHERE site_id=:id", id=SITE)
    if case in {"deny_assignment", "deny_author_assignment", "dirty_card_denial", "dirty_user_denial", "list_count_limit", "superadmin_list", "archive_sql", "space_documents"}:
        await sql(pg, "UPDATE core.site_user_permissions SET approved=false WHERE site_id=:id", id=SITE)
    if case == "deny_member":
        await sql(pg, "DELETE FROM core.user_companies WHERE user_id=:uid AND company_id=:cid", uid=UID, cid=A)
    if case == "deny_org":
        await sql(pg, "UPDATE core.user_companies SET own_organization_id=NULL WHERE user_id=:uid", uid=UID)
    if case in {"deny_empty_objects", "deny_admin_empty_objects", "deny_location_mismatch"}:
        await sql(pg, "UPDATE core.ezs_sites SET location_id=:loc WHERE id=:id", loc=LOCATION, id=SITE)
        await sql(pg, "UPDATE core.user_companies SET object_scope=CAST(:scope AS jsonb) WHERE user_id=:uid",
                  scope='["other point"]' if case == "deny_location_mismatch" else '[]', uid=UID)
    if case == "deny_action":
        await sql(pg, "UPDATE core.site_user_permissions SET approved=false WHERE site_id=:id AND action='document.edit'", id=SITE)
    if case in {"docgrant_deny", "approval_deny"}:
        await sql(pg, "UPDATE core.doc_access_grants SET denied_permissions=CAST(:deny AS jsonb) WHERE scope_id=:id",
                  deny='["approve"]' if case == "approval_deny" else '["read"]', id=DOC)
    if case == "strict_download":
        doc.confidentiality = "strict"
        await sql(pg, "DELETE FROM core.doc_access_grants WHERE scope_id=:id", id=DOC)
        await pg.session.flush()
    if case == "retention_download":
        doc.retention_state = "destruction_authorized"
        await pg.session.flush()
    if case == "version_tombstone":
        await sql(pg, "UPDATE core.doc_versions SET tombstoned_at=now() WHERE id=:id", id=VERSION)
    with native_claims_context(claims, None):
        if case in {"native_dirty_title_preserved", "native_dirty_username_preserved"}:
            # Approved Site and assignment: pending presentation fields alone
            # must not inherit the unrelated assignment denial of old cases.
            assert await _can_doc(pg.session, A, doc, user, "read", record_break_glass_use=False)
            target, field, pending = (
                (doc, "title", "Pending approved title") if case == "native_dirty_title_preserved"
                else (user, "name", "Pending approved username"))
            original = getattr(target, field)
            target_id = target.id
            setattr(target, field, pending)
            history = inspect(target).attrs[field].history
            assert target in pg.session.dirty and inspect(target).modified
            assert tuple(history.deleted) == (original,) and tuple(history.added) == (pending,)
            assert await _can_doc(pg.session, A, doc, user, "read", record_break_glass_use=False)
            await assert_fresh_doc_edit(pg.session, A, doc, user)
            assert getattr(target, field) == pending
            assert target in pg.session.dirty and inspect(target).modified
            assert inspect(target).attrs[field].history == history
            # Scalar projections prove neither refresh nor autoflush consumed
            # the user's pending edit; no helper interception is used.
            with pg.session.no_autoflush:
                column = DocCard.title if target is doc else User.name
                model = DocCard if target is doc else User
                assert await pg.session.scalar(select(column).where(model.id == target_id)) == original
            return
        if case in {"native_pending_site_draft", "native_transient_site_draft",
                    "native_pending_null_draft", "native_transient_null_draft"}:
            site_draft = case in {"native_pending_site_draft", "native_transient_site_draft"}
            pending = case in {"native_pending_site_draft", "native_pending_null_draft"}
            draft = DocCard(id=UUID("70000000-0000-4000-8000-000000000097"),
                            company_id=A, kind_id=KIND, title="Unwritten synthetic draft",
                            site_id=SITE if site_draft else None, organization_id=ORG,
                            author_id=UID, status="draft", confidentiality="company",
                            retention_state="active", inherit_kind_acl=False)
            if pending:
                pg.session.add(draft)
            assert inspect(draft).pending is pending
            assert inspect(draft).transient is (not pending)
            assert (await _can_doc(pg.session, A, draft, user, "read",
                                   record_break_glass_use=False)) is (not site_draft)
            assert inspect(draft).pending is pending
            assert inspect(draft).transient is (not pending)
            assert (draft in pg.session.new) is pending
            assert draft.title == "Unwritten synthetic draft"
            assert draft.site_id == (SITE if site_draft else None)
            with pg.session.no_autoflush:
                assert await pg.session.scalar(select(func.count()).select_from(DocCard).where(
                    DocCard.id == draft.id)) == 0
            return
        if case in {"linked_inbox", "linked_inbox_revoked"}:
            inbox_file = UUID("70000000-0000-4000-8000-000000000098")
            pg.session.add(DocInboxItem(company_id=A, doc_id=DOC, file_id=inbox_file,
                                       file_name="Synthetic inbox.txt", source_path=str(pg.upload_path), sha256="1"*64))
            await pg.session.flush()
            if case == "linked_inbox":
                await authorize_docs_file_download(pg.session, user, inbox_file)
            else:
                with pytest.raises(HTTPException) as error:
                    await authorize_docs_file_download(pg.session, user, inbox_file)
                assert error.value.status_code == 404
            return
        if case in {"file", "file_revoked", "version_tombstone"}:
            if case == "file":
                await authorize_docs_file_download(pg.session, user, FILE)
            else:
                with pytest.raises(HTTPException) as error:
                    await authorize_docs_file_download(pg.session, user, FILE)
                assert error.value.status_code == 404
            return
        if case in {"egress", "egress_revoked"}:
            if case == "egress":
                assert [d.id for d in await authorize_docs_file_egress(pg.session, user, [FILE])] == [DOC]
            else:
                with pytest.raises(HTTPException):
                    await authorize_docs_file_egress(pg.session, user, [FILE])
            return
        if case in {"notice", "notice_revoked"}:
            notice = await authorized_doc_notice(pg.session, A, DOC, UID)
            assert (notice is not None) is (case == "notice")
            return
        if case in {"list_count_limit", "superadmin_list", "archive_sql"}:
            clause = await (_archiveable_doc_clause(pg.session, A, user) if case == "archive_sql"
                            else _readable_doc_clause(pg.session, A, user))
            ids = list(await pg.session.scalars(select(DocCard.id).where(DocCard.company_id == A, clause).order_by(DocCard.id).limit(1)))
            assert DOC not in ids
            count = await pg.session.scalar(select(func.count()).select_from(DocCard).where(DocCard.company_id == A, clause))
            assert count == (0 if case == "archive_sql" else 1)
            assert DOC not in {d.id for d in await _readable_docs(pg.session, A, [doc, await pg.session.get(DocCard, LEGACY)], user)}
            return
        if case == "space_documents":
            assert "doc-"+str(DOC) not in {row["id"] for row in await space_documents(pg.session, A, user)}
            return
        if case in {"dirty_card_denial", "dirty_user_denial", "dirty_site_pointer", "dirty_doc_company", "dirty_doc_org", "queued_doc_delete"}:
            if case == "queued_doc_delete":
                await pg.session.delete(doc)
                assert doc in pg.session.deleted
                assert not await _can_doc(pg.session, A, doc, user, "read", record_break_glass_use=False)
                assert doc in pg.session.deleted
                with pg.session.no_autoflush:
                    assert (await sql(pg, "SELECT count(*) FROM core.doc_cards WHERE id=:id", id=DOC)).scalar_one() == 1
                return
            if case == "dirty_user_denial":
                user.name = "Pending synthetic user"
            else:
                doc.title = "Pending synthetic title"
            if case == "dirty_site_pointer":
                doc.site_id = None
            if case == "dirty_doc_company":
                doc.company_id = B
            if case == "dirty_doc_org":
                doc.organization_id = OTHER_ORG
            target = user if case == "dirty_user_denial" else doc
            state = inspect(target)
            assert target in pg.session.dirty and state.modified
            assert not await _can_doc(pg.session, A, doc, user, "read", record_break_glass_use=False)
            assert target in pg.session.dirty and inspect(target).modified
            if case == "dirty_user_denial":
                assert user.name == "Pending synthetic user"
            else:
                assert doc.title == "Pending synthetic title"
            return
        if case == "read_only_revoke":
            await pg.publish()
            await sql(pg, "SET TRANSACTION READ ONLY")
            assert not await _can_doc(pg.session, A, doc, user, "read", record_break_glass_use=False)
            assert (await sql(pg, "SHOW transaction_read_only")).scalar_one() == "on"
            return
        permission = case.removeprefix("native_")
        if permission in {"user_read", "admin_read", "superadmin_read", "author_read"}:
            permission = "read"
        if case == "deny_action":
            permission = "edit"
        elif case == "approval_deny":
            permission = "approve"
        elif case in {"strict_download", "retention_download"}:
            permission = "download"
        elif case.startswith("deny_") or case == "docgrant_deny":
            permission = "read"
        assert permission in PERMISSIONS
        allowed = await _can_doc(pg.session, A, doc, user, permission, record_break_glass_use=False)
        assert allowed is case.startswith("native_")
        if case == "native_edit":
            await assert_fresh_doc_edit(pg.session, A, doc, user)
