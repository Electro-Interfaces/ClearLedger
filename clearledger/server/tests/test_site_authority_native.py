"""SOURCE ONLY: real PG16/AsyncSession/canonical identities; execution NOTRUN.

External controller supplies `site_authority_pg`, never this module. Protocol:
* baseline(prefix=0|3|5|6, site_prerequisites=True) provisions a disposable, externally admitted native Core
  schema, actual old artifacts and native resource tables, with no business data;
  Full-native prefix3/5 MUST be built from the REAL frozen predecessor Source
  0db9a97e2f6b86f2307cfa5abefb1a32982d37ec, not candidate metadata. Close its
  pools before candidate6. Fresh6 means full-native3 -> explicit4+5+6;
  upgrade6 means native5 -> explicit6. Never project/drop future columns.
  Root historical expectations at5 are 343 registered/349 physical; candidate
  expectations at6 are 345/351, to be independently measured by Root, NOTRUN here.
  The candidate Source is this author's final frozen commit, supplied externally.
  site_prerequisites=False selects the minimal old Core prerequisite profile
  without any Site/resource native parents, only for oldtarget3 compatibility;
* connection is its actual asyncpg migration connection; config is its admitted
  Config, session is the actual AsyncSession on that SAME isolated database;
* native_bearer(uid,cid) issues through app.auth's real signing/session owner;
* partner_bearer(uid,cid) runs the real canonical issuer and returns (bearer,iid),
  with the real canonical issuer actually enabled/configured on the isolated
  target BEFORE app imports, approved actual app/client/installation/user grant, existing read scopes,
  objects ALL/location ALL and sites EMPTY, not a VerifiedPartnerToken/fake;
* legacy_resources(cid) creates native rows with the literal IDs 51..55 below
  using their real owners; it confers no Site permissions or resource items.
Both identity methods MUST use pg.session and its same actual transaction:
seed(pg) is intentionally uncommitted and there is no independent issuer session.
Controller owns target admission, credentials, fixture lifetime and teardown.
Before collection it injects rushydro_site_authority_root_admission with its
require_running_approval() guard, and EXCLUDES ordinary server/conftest.py,
which imports the app and drops schemas before module guards. This source never
issues admission, signs leases, selects an environment or imports a provider.
No engine, provider, bootstrap fixture, mock identity, SQL compiler or containers
are defined here. Each baseline and each case has an independent actual target.
"""
import sys
from uuid import UUID

import pytest

_admission = sys.modules.get('rushydro_site_authority_root_admission')
if _admission is None:
    pytest.skip('ROOT-owned Site authority admission required before collection', allow_module_level=True)
_admission.require_running_approval()

# Only after the externally validated live lease; AUTHOR never imports these.
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.auth import decode_token, native_claims_context
from app.models import User
from app.services.partner_identity import verify_partner_access_token
from app.services.site_authority import native_site_allowed, partner_site_allowed
from schema_migrations.errors import MigrationError
from schema_migrations.manifest import PULSE_ID, SITE_AUTHORITY_ID, load_known_head
from schema_migrations.runner import execute_sequence, require_applied_prefix, require_site_prefix

pytestmark = pytest.mark.asyncio

A = UUID('00000001-0000-4000-8000-000000000001')
B = UUID('00000002-0000-4000-8000-000000000002')
ORG_A = UUID('00000003-0000-4000-8000-000000000003')
ORG_B = UUID('00000004-0000-4000-8000-000000000004')
USER_A = UUID('00000005-0000-4000-8000-000000000005')
USER_B = UUID('00000006-0000-4000-8000-000000000006')
SITE_A = UUID('00000007-0000-4000-8000-000000000007')
SITE_B = UUID('00000008-0000-4000-8000-000000000008')
LOCATION_A = 'Учебная точка 1'
LOCATION_B = 'Учебная точка 2'


async def sql(pg, statement, **params):
    return await pg.session.execute(text(statement), params)


async def seed(pg):
    # Own synthetic rows, with native required values explicitly supplied.
    for cid, org, uid, sid, loc, label in (
        (A, ORG_A, USER_A, SITE_A, LOCATION_A, 'A'),
        (B, ORG_B, USER_B, SITE_B, LOCATION_B, 'B'),
    ):
        await sql(pg, """INSERT INTO core.companies(id,name,slug,profile_id)
            VALUES (:cid,:name,:slug,'energy')""", cid=cid, name='Synthetic '+label, slug='site-source-'+label.lower())
        await sql(pg, """INSERT INTO core.organizations(id,company_id,inn,name)
            VALUES (:org,:cid,'0000000000',:name)""", org=org, cid=cid, name='Synthetic organization '+label)
        await sql(pg, """INSERT INTO core.users(id,company_id,email,password_hash,name,role)
            VALUES (:uid,:cid,:email,'!synthetic-disabled-password','Synthetic user','user')""",
            uid=uid, cid=cid, email='site-'+label.lower()+'@example.invalid')
        await sql(pg, """INSERT INTO core.user_companies(user_id,company_id,own_organization_id)
            VALUES (:uid,:cid,:org)""", uid=uid, cid=cid, org=org)
        await sql(pg, """INSERT INTO core.ezs_sites(id,company_id,kind,stage,title)
            VALUES (:sid,:cid,'new_build','lead','Synthetic Site')""", sid=sid, cid=cid)
        await sql(pg, """INSERT INTO core.service_locations
            (id,company_id,code,name,type,status,source_bindings)
            VALUES (:loc,:cid,:code,:loc,'ev_charging','active','[]'::jsonb)""",
            loc=loc, cid=cid, code='SYN-'+label)


async def approved(pg, action='site.read'):
    await sql(pg, """INSERT INTO core.site_authority_contexts
        (company_id,site_id,organization_id,approved,revoked)
        VALUES (:cid,:sid,:org,true,false)""", cid=A, sid=SITE_A, org=ORG_A)
    await sql(pg, """INSERT INTO core.site_user_permissions
        (company_id,site_id,user_id,action,approved)
        VALUES (:cid,:sid,:uid,:action,true)""", cid=A, sid=SITE_A, uid=USER_A, action=action)


async def native(pg, *, action='site.read', site=SITE_A, org=ORG_A, actor=USER_A, bearer=None):
    # Real signed native identity, then the actual canonical current-auth owner.
    bearer = bearer or await pg.native_bearer(USER_A, A)
    user = (await pg.session.execute(select(User).where(User.id == actor))).scalar_one()
    with native_claims_context(decode_token(bearer), None):
        return await native_site_allowed(pg.session, user, company_id=A,
            site_id=site, organization_id=org, action=action)


async def site_set(pg, installation):
    await sql(pg, """INSERT INTO core.partner_resource_scopes(installation_id,kind,mode)
        VALUES (:iid,'sites','SET') ON CONFLICT (installation_id,kind) DO UPDATE SET mode='SET'""", iid=installation)
    await sql(pg, """INSERT INTO core.partner_resource_items(id,installation_id,kind,site_id)
        VALUES ('00000009-0000-4000-8000-000000000009',:iid,'sites',:sid)""", iid=installation, sid=SITE_A)


@pytest.mark.parametrize('prefix', (3, 5))
async def test_fresh_or_upgrade_and_repeat(site_authority_pg, prefix):
    pg = site_authority_pg
    await pg.baseline(prefix=prefix)
    first = await execute_sequence(pg.config, target_revision=SITE_AUTHORITY_ID, legacy_sent_before=2000000000)
    assert first['prefix_before'] == prefix
    expected_actions = {
        3: ['0004_partner_contract_create', '0005_partner_contract_cycle_receipts', '0006_site_authority'],
        5: ['0006_site_authority'],
    }
    assert [a['revision'] for a in first['actions']] == expected_actions[prefix]
    assert await pg.connection.fetchval('SELECT count(*) FROM core.core_schema_versions') == 6
    second = await execute_sequence(pg.config, target_revision=SITE_AUTHORITY_ID, legacy_sent_before=2000000000)
    assert second['prefix_before'] == 6 and second['actions'] == []
    assert await require_applied_prefix(pg.connection, pg.config, load_known_head(), required_revision=SITE_AUTHORITY_ID) == 6
    assert await pg.connection.fetchval('SELECT count(*) FROM core.site_authority_contexts') == 0
    assert await pg.connection.fetchval('SELECT count(*) FROM core.site_user_permissions') == 0


@pytest.mark.parametrize('prefix', (0, 3))
async def test_old_target3_minimal_does_not_require_site_parents(site_authority_pg, prefix):
    pg = site_authority_pg
    await pg.baseline(prefix=prefix, site_prerequisites=False)
    result = await execute_sequence(pg.config, target_revision=PULSE_ID, legacy_sent_before=2000000000)
    assert result['prefix_before'] == prefix
    assert await pg.connection.fetchval('SELECT count(*) FROM core.core_schema_versions') == 3
    assert await pg.connection.fetchval("SELECT to_regclass('core.ezs_sites')") is None
    with pytest.raises(MigrationError):
        await execute_sequence(pg.config, target_revision=SITE_AUTHORITY_ID, legacy_sent_before=2000000000)
    assert await pg.connection.fetchval('SELECT count(*) FROM core.core_schema_versions') == 3


@pytest.mark.parametrize('drift', (
    'ALTER TABLE core.site_authority_contexts ALTER COLUMN approved SET DEFAULT true',
    'ALTER TABLE core.site_user_permissions DROP CONSTRAINT fk_site_permission_membership',
    'ALTER TABLE core.partner_resource_scopes DROP CONSTRAINT ck_partner_sites_mode',
    'ALTER TABLE core.partner_resource_items DROP CONSTRAINT ck_partner_resource_one_id',
))
async def test_catalogue_drift_denies(site_authority_pg, drift):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await pg.connection.execute(drift)
    with pytest.raises(MigrationError):
        await require_site_prefix(pg.connection)


async def test_partial_unrecorded6_refuses_without_journal_append(site_authority_pg):
    pg = site_authority_pg
    await pg.baseline(prefix=5)
    await pg.connection.execute('ALTER TABLE core.partner_resource_items ADD COLUMN site_id uuid')
    with pytest.raises(MigrationError):
        await execute_sequence(pg.config, target_revision=SITE_AUTHORITY_ID, legacy_sent_before=2000000000)
    assert await pg.connection.fetchval('SELECT count(*) FROM core.core_schema_versions') == 5
    assert await pg.connection.fetchval("SELECT to_regclass('core.site_authority_contexts')") is None


async def test_prefix5_and_foreign_namespace_gate_before_identity(site_authority_pg):
    pg = site_authority_pg
    await pg.baseline(prefix=5)
    with pytest.raises(HTTPException) as error:
        await verify_partner_access_token('not-a-token', pg.session)
    assert error.value.status_code == 503
    await pg.session.rollback()
    await pg.baseline(prefix=6)
    # With schema6 ready and the real issuer configured/enabled, bad JWT is the
    # canonical 401, proving the schema guard does not permanently block auth.
    with pytest.raises(HTTPException) as error:
        await verify_partner_access_token('not-a-token', pg.session)
    assert error.value.status_code == 401
    await pg.session.rollback()
    await sql(pg, 'SET LOCAL search_path=public')
    with pytest.raises(HTTPException) as error:
        await verify_partner_access_token('not-a-token', pg.session)
    assert error.value.status_code == 503


async def test_defaults_are_not_authority(site_authority_pg):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    assert not await native(pg)
    await sql(pg, """INSERT INTO core.site_authority_contexts(company_id,site_id,organization_id)
        VALUES (:cid,:sid,:org)""", cid=A, sid=SITE_A, org=ORG_A)
    await sql(pg, """INSERT INTO core.site_user_permissions(company_id,site_id,user_id,action)
        VALUES (:cid,:sid,:uid,'site.read')""", cid=A, sid=SITE_A, uid=USER_A)
    row = (await sql(pg, 'SELECT approved,revoked,policy_generation FROM core.site_authority_contexts')).one()
    assert tuple(row) == (False, True, 1)
    assert (await sql(pg, 'SELECT approved FROM core.site_user_permissions')).scalar_one() is False
    assert not await native(pg)


@pytest.mark.parametrize('case', ('foreign_site', 'foreign_org', 'foreign_membership', 'zero_generation', 'unknown_action'))
async def test_tenant_fks_generation_action_checks(site_authority_pg, case):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    if case in ('foreign_site', 'foreign_org', 'zero_generation'):
        with pytest.raises(IntegrityError):
            async with pg.session.begin_nested():
                await sql(pg, """INSERT INTO core.site_authority_contexts(company_id,site_id,organization_id,policy_generation)
                    VALUES (:cid,:sid,:org,:generation)""", cid=A,
                    sid=SITE_B if case == 'foreign_site' else SITE_A,
                    org=ORG_B if case == 'foreign_org' else ORG_A,
                    generation=0 if case == 'zero_generation' else 1)
    else:
        await sql(pg, """INSERT INTO core.site_authority_contexts(company_id,site_id,organization_id)
            VALUES (:cid,:sid,:org)""", cid=A, sid=SITE_A, org=ORG_A)
        with pytest.raises(IntegrityError):
            async with pg.session.begin_nested():
                await sql(pg, """INSERT INTO core.site_user_permissions(company_id,site_id,user_id,action)
                    VALUES (:cid,:sid,:uid,:action)""", cid=A, sid=SITE_A,
                    uid=USER_B if case == 'foreign_membership' else USER_A,
                    action='unknown' if case == 'unknown_action' else 'site.read')


@pytest.mark.parametrize('action', (
    'site.read', 'site.link_edit', 'contract.create', 'document.create',
    'document.read', 'document.edit', 'document.download', 'document.print',
    'document.export', 'document.send', 'document.approve', 'document.sign',
    'document.archive', 'document.manage_acl',
))
async def test_exact_actions_and_current_revocation(site_authority_pg, action):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    await approved(pg, action)
    assert await native(pg, action=action)
    assert not await native(pg, action='unknown')
    assert not await native(pg, action='document.edit' if action == 'site.read' else 'site.read')
    await sql(pg, 'UPDATE core.site_user_permissions SET approved=false')
    assert not await native(pg, action=action)
    await sql(pg, 'UPDATE core.site_user_permissions SET approved=true')
    await sql(pg, 'UPDATE core.site_authority_contexts SET revoked=true')
    assert not await native(pg, action=action)
    await sql(pg, 'UPDATE core.site_authority_contexts SET revoked=false,approved=false')
    assert not await native(pg, action=action)


@pytest.mark.parametrize('case', ('org_null', 'org_foreign', 'member_deleted', 'admin_without_assignment', 'superadmin_without_assignment'))
async def test_membership_org_and_no_role_shortcuts(site_authority_pg, case):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    await approved(pg)
    if case == 'org_null':
        await sql(pg, 'UPDATE core.user_companies SET own_organization_id=NULL WHERE user_id=:uid', uid=USER_A)
    elif case == 'org_foreign':
        await sql(pg, 'UPDATE core.user_companies SET own_organization_id=:org WHERE user_id=:uid', org=ORG_B, uid=USER_A)
    elif case == 'member_deleted':
        await sql(pg, 'DELETE FROM core.user_companies WHERE user_id=:uid', uid=USER_A)
        assert (await sql(pg, 'SELECT count(*) FROM core.site_user_permissions')).scalar_one() == 0
    else:
        await sql(pg, 'DELETE FROM core.site_user_permissions')
        if case == 'admin_without_assignment':
            await sql(pg, "UPDATE core.user_companies SET role='admin' WHERE user_id=:uid", uid=USER_A)
        else:
            await sql(pg, 'UPDATE core.users SET is_superadmin=true WHERE id=:uid', uid=USER_A)
    assert not await native(pg)


async def test_native_spoof_and_current_session_revoke(site_authority_pg):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    await approved(pg)
    current = (await pg.session.execute(select(User).where(User.id == USER_A))).scalar_one()
    assert not await native_site_allowed(pg.session, current, company_id=A,
        site_id=SITE_A, organization_id=ORG_A, action='site.read')
    bearer_b = await pg.native_bearer(USER_B, B)
    assert not await native(pg, actor=USER_A, bearer=bearer_b)
    bearer_a = await pg.native_bearer(USER_A, A)
    assert await native(pg, bearer=bearer_a)
    await sql(pg, 'UPDATE core.users SET token_version=token_version+1 WHERE id=:uid', uid=USER_A)
    with pytest.raises(HTTPException) as error:
        await native(pg, bearer=bearer_a)
    assert error.value.status_code == 401


@pytest.mark.parametrize('case', ('empty', 'wrong_location', 'exact_location', 'null_all', 'project_conflict'))
async def test_distinct_site_location_and_strict_native_ceiling(site_authority_pg, case):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    await approved(pg)
    # Same-tenant second station, never use a UUID as its ObjectId.
    await sql(pg, """INSERT INTO core.service_locations
        (id,company_id,code,name,type,status,source_bindings)
        VALUES ('Учебная точка 3',:cid,'SYN-C','Synthetic third','ev_charging','active','[]'::jsonb)""", cid=A)
    await sql(pg, 'UPDATE core.ezs_sites SET location_id=:loc WHERE id=:sid', loc=LOCATION_A, sid=SITE_A)
    scopes = {'empty': '[]', 'wrong_location': '["Учебная точка 3"]',
        'exact_location': '["Учебная точка 1"]', 'null_all': None, 'project_conflict': '["Учебная точка 1"]'}
    await sql(pg, 'UPDATE core.user_companies SET object_scope=CAST(:scope AS jsonb),role=\'admin\' WHERE user_id=:uid', scope=scopes[case], uid=USER_A)
    if case == 'project_conflict':
        await sql(pg, """INSERT INTO core.ezs_projects(id,company_id,site_id,location_id,kind,stage)
            VALUES ('00000040-0000-4000-8000-000000000040',:cid,:sid,'Учебная точка 3','relocation','lead')""", cid=A, sid=SITE_A)
    assert await native(pg) is (case in ('exact_location', 'null_all'))
    assert not await native(pg, site=SITE_B)


async def test_fresh_partner_site_set_and_independent_native_action(site_authority_pg):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    await approved(pg)
    bearer, iid = await pg.partner_bearer(USER_A, A)
    assert not await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='site.read')
    await site_set(pg, iid)
    assert await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='site.read')
    assert not await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='document.download')
    await sql(pg, 'UPDATE core.site_user_permissions SET approved=false')
    assert not await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='site.read')
    await sql(pg, 'UPDATE core.site_user_permissions SET approved=true')
    await sql(pg, 'UPDATE core.ezs_sites SET location_id=:loc WHERE id=:sid', loc=LOCATION_A, sid=SITE_A)
    assert await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='site.read')
    await sql(pg, "UPDATE core.partner_resource_scopes SET mode='EMPTY' WHERE installation_id=:iid AND kind='objects'", iid=iid)
    assert not await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='site.read')
    await sql(pg, "UPDATE core.partner_resource_scopes SET mode='ALL' WHERE installation_id=:iid AND kind='objects'", iid=iid)

    with pytest.raises(IntegrityError):
        async with pg.session.begin_nested():
            await sql(pg, "UPDATE core.partner_resource_scopes SET mode='ALL' WHERE installation_id=:iid AND kind='sites'", iid=iid)
    with pytest.raises(IntegrityError):
        async with pg.session.begin_nested():
            await sql(pg, "UPDATE core.partner_resource_items SET object_id=:loc WHERE installation_id=:iid AND kind='sites'", iid=iid, loc=LOCATION_A)
    with pytest.raises(IntegrityError):
        async with pg.session.begin_nested():
            await sql(pg, "UPDATE core.partner_resource_items SET object_id=:loc,site_id=NULL WHERE installation_id=:iid AND kind='sites'", iid=iid, loc=LOCATION_A)
    await sql(pg, "DELETE FROM core.partner_resource_items WHERE installation_id=:iid AND kind='sites'", iid=iid)
    assert not await partner_site_allowed(pg.session, bearer, site_id=SITE_A, organization_id=ORG_A, action='site.read')


@pytest.mark.parametrize('kind,resource_id', (
    ('equipment', '00000051-0000-4000-8000-000000000051'),
    ('counterparties', '00000052-0000-4000-8000-000000000052'),
    ('contracts', '00000053-0000-4000-8000-000000000053'),
    ('documents', '00000054-0000-4000-8000-000000000054'),
    ('objects', 'Учебная точка 1'),
))
async def test_original_five_resource_modes(site_authority_pg, kind, resource_id):
    pg = site_authority_pg
    await pg.baseline(prefix=6)
    await seed(pg)
    await pg.legacy_resources(A)
    bearer, iid = await pg.partner_bearer(USER_A, A)
    columns = {'equipment': 'equipment_id', 'counterparties': 'counterparty_id',
        'contracts': 'contract_id', 'documents': 'document_id', 'objects': 'object_id'}
    for mode, expected_mode, expected_ids in (
        ('ALL', 'ALL', frozenset()), ('EMPTY', 'EMPTY', frozenset()),
        ('SET', 'SET', frozenset({resource_id})),
    ):
        await sql(pg, """INSERT INTO core.partner_resource_scopes(installation_id,kind,mode)
            VALUES (:iid,:kind,:mode) ON CONFLICT (installation_id,kind) DO UPDATE SET mode=EXCLUDED.mode""", iid=iid, kind=kind, mode=mode)
        if mode == 'SET':
            await sql(pg, 'INSERT INTO core.partner_resource_items(id,installation_id,kind,'+columns[kind]+') VALUES (:id,:iid,:kind,:rid)',
                id=UUID('00000055-0000-4000-8000-000000000055'), iid=iid, kind=kind,
                rid=resource_id if kind == 'objects' else UUID(resource_id))
        current = await verify_partner_access_token(bearer, pg.session)
        assert (current.resource_scopes[kind].mode, current.resource_scopes[kind].ids) == (expected_mode, expected_ids)


# Frozen fixture-controller discovery ABI: test symbol, parameter names, literal value.
CASES = (('test_fresh_or_upgrade_and_repeat', 'prefix', 3),
 ('test_fresh_or_upgrade_and_repeat', 'prefix', 5),
 ('test_old_target3_minimal_does_not_require_site_parents', 'prefix', 0),
 ('test_old_target3_minimal_does_not_require_site_parents', 'prefix', 3),
 ('test_catalogue_drift_denies',
  'drift',
  'ALTER TABLE core.site_authority_contexts ALTER COLUMN approved SET DEFAULT true'),
 ('test_catalogue_drift_denies',
  'drift',
  'ALTER TABLE core.site_user_permissions DROP CONSTRAINT fk_site_permission_membership'),
 ('test_catalogue_drift_denies',
  'drift',
  'ALTER TABLE core.partner_resource_scopes DROP CONSTRAINT ck_partner_sites_mode'),
 ('test_catalogue_drift_denies',
  'drift',
  'ALTER TABLE core.partner_resource_items DROP CONSTRAINT ck_partner_resource_one_id'),
 ('test_partial_unrecorded6_refuses_without_journal_append', None, None),
 ('test_prefix5_and_foreign_namespace_gate_before_identity', None, None),
 ('test_defaults_are_not_authority', None, None),
 ('test_tenant_fks_generation_action_checks', 'case', 'foreign_site'),
 ('test_tenant_fks_generation_action_checks', 'case', 'foreign_org'),
 ('test_tenant_fks_generation_action_checks', 'case', 'foreign_membership'),
 ('test_tenant_fks_generation_action_checks', 'case', 'zero_generation'),
 ('test_tenant_fks_generation_action_checks', 'case', 'unknown_action'),
 ('test_exact_actions_and_current_revocation', 'action', 'site.read'),
 ('test_exact_actions_and_current_revocation', 'action', 'site.link_edit'),
 ('test_exact_actions_and_current_revocation', 'action', 'contract.create'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.create'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.read'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.edit'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.download'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.print'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.export'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.send'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.approve'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.sign'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.archive'),
 ('test_exact_actions_and_current_revocation', 'action', 'document.manage_acl'),
 ('test_membership_org_and_no_role_shortcuts', 'case', 'org_null'),
 ('test_membership_org_and_no_role_shortcuts', 'case', 'org_foreign'),
 ('test_membership_org_and_no_role_shortcuts', 'case', 'member_deleted'),
 ('test_membership_org_and_no_role_shortcuts', 'case', 'admin_without_assignment'),
 ('test_membership_org_and_no_role_shortcuts', 'case', 'superadmin_without_assignment'),
 ('test_native_spoof_and_current_session_revoke', None, None),
 ('test_distinct_site_location_and_strict_native_ceiling', 'case', 'empty'),
 ('test_distinct_site_location_and_strict_native_ceiling', 'case', 'wrong_location'),
 ('test_distinct_site_location_and_strict_native_ceiling', 'case', 'exact_location'),
 ('test_distinct_site_location_and_strict_native_ceiling', 'case', 'null_all'),
 ('test_distinct_site_location_and_strict_native_ceiling', 'case', 'project_conflict'),
 ('test_fresh_partner_site_set_and_independent_native_action', None, None),
 ('test_original_five_resource_modes',
  'kind,resource_id',
  ('equipment', '00000051-0000-4000-8000-000000000051')),
 ('test_original_five_resource_modes',
  'kind,resource_id',
  ('counterparties', '00000052-0000-4000-8000-000000000052')),
 ('test_original_five_resource_modes',
  'kind,resource_id',
  ('contracts', '00000053-0000-4000-8000-000000000053')),
 ('test_original_five_resource_modes',
  'kind,resource_id',
  ('documents', '00000054-0000-4000-8000-000000000054')),
 ('test_original_five_resource_modes', 'kind,resource_id', ('objects', 'Учебная точка 1')))
