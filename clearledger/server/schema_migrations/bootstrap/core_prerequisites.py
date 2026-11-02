"""Explicit owner's literal prerequisite source and bounded PG16 catalogue profiles.

No application/ORM imports, connections, transactions, locks or mutations here.
The runner verifies this module's bytes before import and owns every mutation.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from schema_migrations.errors import MigrationError

ROOT = Path(__file__).resolve().parent
NAME = 'core_prerequisites_v1'
FILES = (NAME+'.sql', NAME+'.contract.json', 'core_prerequisites.py')


def require(value, phase='bootstrap_catalogue'):
    if not value:
        raise MigrationError(4, phase)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(2, 'bootstrap_source')
        result[key] = value
    return result


@dataclass(frozen=True)
class Source:
    sql: str
    contract: dict
    digest: str


def load(expected_manifest_sha256):
    try:
        p = ROOT/(NAME+'.manifest.json')
        raw = p.read_bytes()
        if (ROOT.is_symlink() or p.is_symlink() or len(raw)>65536
                or hashlib.sha256(raw).hexdigest()!=expected_manifest_sha256):
            raise MigrationError(2, 'bootstrap_source')
        m = json.loads(raw, object_pairs_hook=unique)
        if set(m)!= {'format','name','files'} or m['format']!=1 or m['name']!=NAME or set(m['files'])!=set(FILES):
            raise MigrationError(2, 'bootstrap_source')
        data = {}
        for name in FILES:
            p=ROOT/name
            if p.is_symlink():
                raise MigrationError(2, 'bootstrap_source')
            b=p.read_bytes()
            if len(b)>512000 or hashlib.sha256(b).hexdigest()!=m['files'][name] or b'\r' in b:
                raise MigrationError(2, 'bootstrap_source')
            data[name]=b
        c=json.loads(data[NAME+'.contract.json'], object_pairs_hook=unique)
        if c['format']!=1 or c['name']!=NAME or c['namespace']!='core' or len(c['tables'])!=10:
            raise MigrationError(2, 'bootstrap_source')
        return Source(data[NAME+'.sql'].decode(),c,expected_manifest_sha256)
    except MigrationError:
        raise
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        raise MigrationError(2, 'bootstrap_source') from None


def expression(value):
    """Only discard PG16 deparser parentheses/outer whitespace; quoted bytes survive."""
    if value is None:
        return None
    tokens=re.findall(r"'(?:[^']|'')*'|\s+|[()]|[^\s()']+|.",value)
    return ''.join(t for t in tokens if not t.isspace() and t not in {'(',')'})


async def prerequisites(conn, owner):
    row=await conn.fetchrow("""SELECT pg_catalog.pg_get_userbyid(n.nspowner) AS owner,
        pg_catalog.has_schema_privilege(current_user,n.oid,'USAGE') AS usage,
        pg_catalog.has_schema_privilege(current_user,n.oid,'CREATE') AS can_create
        FROM pg_catalog.pg_namespace n WHERE n.nspname='edge'""")
    require(row is not None and row['owner']==owner and row['usage'] and row['can_create'],'bootstrap_admin_prerequisite')
    require(await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_extension e
        JOIN pg_catalog.pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname='btree_gist' AND n.nspname <> 'core')"""),'bootstrap_admin_prerequisite')
    # Compare effective global+schema defaults with PG's canonical defaults. This
    # admits redundant owner grants without admitting missing owner privileges,
    # extra grantees/grant options or a changed function PUBLIC-EXECUTE policy.
    require(not await conn.fetchval("""WITH owner AS (
            SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user),
        kinds(kind) AS (VALUES ('r'::"char"),('f'::"char"),('S'::"char"),('T'::"char")),
        effective AS (
            SELECT k.kind,a.grantor,a.grantee,a.privilege_type,a.is_grantable
            FROM owner o CROSS JOIN kinds k CROSS JOIN LATERAL pg_catalog.aclexplode(
                coalesce((SELECT d.defaclacl FROM pg_catalog.pg_default_acl d
                  WHERE d.defaclrole=o.oid AND d.defaclnamespace=0 AND d.defaclobjtype=k.kind),pg_catalog.acldefault(k.kind,o.oid))) a
            UNION
            SELECT d.defaclobjtype,a.grantor,a.grantee,a.privilege_type,a.is_grantable
            FROM pg_catalog.pg_default_acl d CROSS JOIN owner o
            CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a
            WHERE d.defaclrole=o.oid AND d.defaclnamespace=(SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='core')
              AND d.defaclobjtype IN ('r','f','S','T')),
        canonical AS (
            SELECT k.kind,a.grantor,a.grantee,a.privilege_type,a.is_grantable
            FROM owner o CROSS JOIN kinds k CROSS JOIN LATERAL pg_catalog.aclexplode(pg_catalog.acldefault(k.kind,o.oid)) a)
        SELECT EXISTS((SELECT * FROM effective EXCEPT SELECT * FROM canonical)
                      UNION ALL (SELECT * FROM canonical EXCEPT SELECT * FROM effective))"""),'bootstrap_default_acl')



async def empty(conn):
    return not await conn.fetchval("""SELECT
        EXISTS(SELECT 1 FROM pg_catalog.pg_depend d WHERE d.refclassid='pg_namespace'::regclass AND d.classid<>'pg_default_acl'::regclass AND d.refobjid=(SELECT oid FROM pg_catalog.pg_namespace WHERE nspname='core'))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='core')
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='core')
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='core')
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_collation c JOIN pg_catalog.pg_namespace n ON n.oid=c.collnamespace WHERE n.nspname='core')
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_operator o JOIN pg_catalog.pg_namespace n ON n.oid=o.oprnamespace WHERE n.nspname='core')""")


async def phone(conn, source, owner):
    rows=await conn.fetch("""SELECT p.prosrc,p.provolatile::text AS volatility,p.proparallel::text AS parallel,
        p.prosecdef,p.proisstrict,p.proretset,p.prokind::text AS kind,p.pronargs,p.pronargdefaults,
        p.proargtypes::oid[] AS args,p.prorettype,p.proargnames,p.proacl IS NULL AS default_acl,
        p.proconfig,pg_catalog.pg_get_userbyid(p.proowner) AS owner,l.lanname
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE n.nspname='core' AND p.proname='phone_to_e164'""")
    require(len(rows)==1,'bootstrap_phone')
    p=rows[0];body=source.contract['phone_sql'].split('$fn$')[1]
    require(p['prosrc']==body and p['owner']==owner and p['lanname']=='plpgsql'
        and p['volatility']=='i' and p['parallel']=='s' and p['kind']=='f'
        and not p['prosecdef'] and not p['proisstrict'] and not p['proretset']
        and p['pronargs']==1 and p['pronargdefaults']==0 and list(p['args'])==[25]
        and p['prorettype']==1043 and list(p['proargnames'])==['raw']
        and p['default_acl'] and p['proconfig'] is None,'bootstrap_phone')


def expected_check(spec):
    if spec['name']=='ck_partner_client_auth':
        return {expression("auth_method::text = ANY (ARRAY['none'::character varying, 'client_secret_basic'::character varying]::text[])"),
                expression("auth_method::text = ANY (ARRAY['none'::text, 'client_secret_basic'::text])")}
    return {expression(spec['expression'])}


async def profile(conn, source, owner, *, calendar_present, allow_prepared=True, old_eight=False):
    """Match whole fresh or whole prepared profile; never mix per-table wildcard deltas."""
    from schema_migrations.revisions.catalog_v1 import columns, constraints, constraint_flags, indexes
    await phone(conn, source, owner)
    tables=source.contract['tables']
    if old_eight:tables={name:spec for name,spec in tables.items() if name not in {'partner_clients','partner_installations'}}
    headers={}; shapes={}; prepared_possible=allow_prepared
    fresh_possible=True
    for name, spec in tables.items():
        h=await conn.fetchrow("""SELECT c.oid,c.relkind::text AS kind,c.relpersistence::text AS persistence,
            pg_catalog.pg_get_userbyid(c.relowner) AS owner,c.relacl IS NULL AS default_acl,
            c.relrowsecurity,c.relforcerowsecurity,
            EXISTS(SELECT 1 FROM pg_catalog.pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS inherits
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='core' AND c.relname=$1""",name)
        require(h is not None and h['kind']=='r' and h['persistence']=='p' and h['owner']==owner
            and h['default_acl'] and not h['relrowsecurity'] and not h['relforcerowsecurity'] and not h['inherits'])
        headers[name]=h
        require(await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_type t
            WHERE t.typrelid=$1 AND t.typtype='c' AND t.typisdefined AND t.typacl IS NULL
              AND pg_catalog.pg_get_userbyid(t.typowner)=current_user)""",h['oid']),'bootstrap_composite_type')
        actual=await columns(conn,h['oid']);expected=list(spec['columns'])
        if name=='calendar_events' and calendar_present:
            expected.append({'name':'protocol_sequence','sql_type':'integer','not_null':True,'default':'2000000000','generated':None})
        require(len(actual)==len(expected),'bootstrap_columns')
        for num,(a,e) in enumerate(zip(actual,expected),1):
            ty=await conn.fetchval('SELECT pg_catalog.format_type($1::oid,$2::int)',
                await conn.fetchval("SELECT atttypid FROM pg_catalog.pg_attribute WHERE attrelid=$1 AND attnum=$2",h['oid'],num),a['typmod'])
            want=e['generated'] if e['generated'] else e['default']
            if e['generated']:
                want=e['generated'].replace('(phone_mobile)','(phone_mobile::text)').replace('(phone_office)','(phone_office::text)')
            require(a['attnum']==num and a['name']==e['name'] and ty==e['sql_type']
                and a['type_schema']=='pg_catalog' and a['not_null']==e['not_null']
                and expression(a['default_expr'])==expression(want) and a['identity']==''
                and a['generated']==('s' if e['generated'] else '') and not a['dropped'] and a['default_collation'],'bootstrap_columns')
        names={a['attnum']:a['name'] for a in actual};shapes[name]=names
        # Column-level ACL or custom policies/triggers are never a named legacy delta.
        require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute WHERE attrelid=$1 AND attnum>0 AND attacl IS NOT NULL)
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid=$1)
            OR EXISTS(SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid=$1 AND NOT tgisinternal)""",h['oid']))
        ix=await indexes(conn,h['oid']);wantix=list(spec['indexes'])
        for k in spec['constraints']:
            if k['kind'] in ('p','u'):
                wantix.append({'name':k['name'],'columns':k['columns'],'unique':True,'predicate':None,'primary':k['kind']=='p'})
        extra=source.contract['prepared_extra_indexes'].get(name,[])
        gotnames={i['name'] for i in ix}
        fresh_possible &= gotnames=={i['name'] for i in wantix}
        prepared_possible &= gotnames=={i['name'] for i in wantix+extra}
        byname={i['name']:i for i in wantix+extra}
        require(len(ix)==len(gotnames) and gotnames<=set(byname),'bootstrap_indexes')
        for i in ix:
            e=byname[i['name']];pred=await conn.fetchval('SELECT pg_catalog.pg_get_expr(indpred,indrelid,false) FROM pg_catalog.pg_index WHERE indexrelid=$1',i['oid'])
            opclasses=['pg_catalog.'+{'uuid':'uuid_ops','varchar':'text_ops','timestamptz':'timestamptz_ops'}[actual[next(n for n,a in enumerate(actual) if a['name']==col)]['type']] for col in e['columns']]
            # The only indexed prerequisite types are UUID, varchar and timestamptz.
            require(i['namespace']=='core' and i['owner']==owner and i['method']=='btree'
                and i['kind']=='i' and i['persistence']=='p' and i['default_acl']
                and i['valid'] and i['ready'] and i['live'] and not i['exclusion']
                and i['immediate'] and not i['nulls_not_distinct'] and i['no_expression']
                and i['default_collations'] and i['key_count']==i['total_count']==len(e['columns'])
                and i['options']==[0]*len(e['columns']) and i['opclasses']==opclasses
                and i['unique']==e['unique'] and i['primary']==e.get('primary',False)
                and [names.get(n) for n in i['keys']]==e['columns']
                and expression(pred)==expression(e['predicate']),'bootstrap_indexes')
    require(fresh_possible or prepared_possible,'bootstrap_profile')
    for name,spec in tables.items():
        actual=await constraints(conn,headers[name]['oid']);wanted=list(spec['constraints'])
        if name=='calendar_events' and calendar_present:
            wanted.append({'kind':'c','name':'ck_calendar_event_protocol_sequence','expression':'protocol_sequence >= 0 AND protocol_sequence <= 2147483647'})
        require(len(actual)==len(wanted),'bootstrap_constraints')
        for a in actual:
            constraint_flags(a)
            matches=[e for e in wanted if e['kind']==a['kind'] and
                (e['name']==a['name'] if e['kind']=='c' else e['columns']==[shapes[name].get(k) for k in a['keys']])]
            require(len(matches)==1,'bootstrap_constraints');e=matches[0]
            if 'name' in e:
                require(a['name']==e['name'],'bootstrap_constraint_name')
            if a['kind']=='c':require(expression(a['expression']) in expected_check(e),'bootstrap_check')
            elif a['kind']=='f':
                target=headers[e['target_table']]
                require(a['target_oid']==target['oid'] and [shapes[e['target_table']].get(k) for k in a['target_keys']]==e['target_columns']
                    and a['delete_action']=={'CASCADE':'c','NO ACTION':'a'}[e['delete']]
                    and a['update_action']=='a' and a['match']=='s','bootstrap_fk')
                ts=await conn.fetch("""SELECT t.tgrelid,t.tgconstrrelid,t.tgenabled::text AS enabled,t.tgisinternal,t.tgdeferrable,t.tginitdeferred,
                    t.tgqual IS NULL AS no_qualifier,t.tgtype AS trigger_type,p.proname,n.nspname FROM pg_catalog.pg_trigger t
                    JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                    WHERE t.tgconstraint=$1""",a['oid'])
                require(len(ts)==4 and {(t['tgrelid'],t['tgconstrrelid'],t['trigger_type']) for t in ts}=={(headers[name]['oid'],target['oid'],5),(headers[name]['oid'],target['oid'],17),(target['oid'],headers[name]['oid'],9),(target['oid'],headers[name]['oid'],17)}
                    and {t['proname'] for t in ts}=={'RI_FKey_check_ins','RI_FKey_check_upd','RI_FKey_noaction_upd','RI_FKey_'+('cascade_del' if e['delete']=='CASCADE' else 'noaction_del')}
                    and all(t['enabled']=='O' and t['tgisinternal'] and not t['tgdeferrable'] and not t['tginitdeferred'] and t['no_qualifier'] and t['nspname']=='pg_catalog' for t in ts),'bootstrap_fk_trigger')
    return source.contract['profiles']['fresh' if fresh_possible else 'prepared']


def load_partner(expected_manifest_sha256):
    """Two fixed literal ranges of the canonical SQL, not another DDL definition/parser."""
    try:
        p=ROOT/'core_partner_prerequisites_v1.manifest.json';raw=p.read_bytes()
        if p.is_symlink() or len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=expected_manifest_sha256:
            raise MigrationError(2,'partner_prerequisite_source')
        m=json.loads(raw,object_pairs_hook=unique)
        wanted={'core_partner_prerequisites_v1.contract.json','core_prerequisites_v1.sql','core_prerequisites_v1.contract.json','core_prerequisites.py'}
        if set(m)!={'format','name','files'} or m['format']!=1 or m['name']!='core_partner_prerequisites_v1' or set(m['files'])!=wanted:
            raise MigrationError(2,'partner_prerequisite_source')
        data={}
        for name in wanted:
            f=ROOT/name;b=f.read_bytes()
            if f.is_symlink() or len(b)>512000 or hashlib.sha256(b).hexdigest()!=m['files'][name]:
                raise MigrationError(2,'partner_prerequisite_source')
            data[name]=b
        c=json.loads(data['core_partner_prerequisites_v1.contract.json'],object_pairs_hook=unique)
        if (c['format']!=1 or c['name']!='core_partner_prerequisites_v1' or c['namespace']!='core'
                or c['repair_existing'] or c['new_registry_revision']
                or c['base_contract_sha256']!=m['files']['core_prerequisites_v1.contract.json']
                or c['base_sql_sha256']!=m['files']['core_prerequisites_v1.sql']
                or [s['table'] for s in c['literal_sections']]!=['partner_clients','partner_installations']):
            raise MigrationError(2,'partner_prerequisite_source')
        pieces=[];last=0
        for section in c['literal_sections']:
            start,end=section['start_byte'],section['end_byte'];b=data['core_prerequisites_v1.sql']
            if (section['file']!='core_prerequisites_v1.sql' or type(start) is not int or type(end) is not int
                    or not last<=start<end<=len(b) or hashlib.sha256(b[start:end]).hexdigest()!=section['sha256']):
                raise MigrationError(2,'partner_prerequisite_source')
            pieces.append(b[start:end]);last=end
        return Source(b''.join(pieces).decode(),c,expected_manifest_sha256)
    except MigrationError:
        raise
    except (OSError,ValueError,KeyError,TypeError,UnicodeError):
        raise MigrationError(2,'partner_prerequisite_source') from None


async def old_partner_profile(conn, base, partner, owner, predecessor_source):
    """Exactly eight known old parents and exactly two absent partner parents."""
    require(predecessor_source in partner.contract['profiles'],'partner_predecessor_source')
    spec=partner.contract['profiles'][predecessor_source]
    absent=partner.contract['required_absent']
    # Reserve table/type/index/constraint names before any partner or managed DDL.
    reserved=list(absent)
    for table in ('partner_clients','partner_installations'):
        for key in base.contract['tables'][table]['constraints']:
            if 'name' in key:reserved.append(key['name'])
        reserved.extend(i['name'] for i in base.contract['tables'][table]['indexes'])
    reserved.extend(['product_api_budgets_pkey','ix_product_api_budgets_reset','core_schema_versions_pkey','core_schema_versions_ordinal_key','pulse_view_role_grants_pkey'])
    require(not await conn.fetchval("""SELECT
        EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='core' AND c.relname=ANY($1::text[]))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='core' AND t.typname=ANY($1::text[]))
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='core' AND c.conname=ANY($1::text[]))""",reserved),'partner_prerequisite_occupied')
    actual=await profile(conn,base,owner,calendar_present=False,old_eight=True)
    require(actual==base.contract['profiles'][spec['expected_profile']],'partner_predecessor_profile')
    return spec['name']
