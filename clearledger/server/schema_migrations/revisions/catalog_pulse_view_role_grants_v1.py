"""Bounded two-parent catalogue contract for the Pulse audience association.

DDL ownership stays Core-only in the runner. The same read verifier permits
explicit public legacy ORM provisioning, without changing search_path or ACL.
"""
from schema_migrations.revisions.catalog_v1 import (
    columns, constraints, constraint_flags, indexes, require, verify_columns,
    verify_fk_triggers,
)


async def header(conn, namespace, name, owner):
    require(namespace in {'core', 'public'}, 'pulse_namespace')
    row = await conn.fetchrow("""SELECT c.oid,c.relkind::text AS kind,
        c.relpersistence::text AS persistence,pg_catalog.pg_get_userbyid(c.relowner) AS owner,
        c.relrowsecurity,c.relforcerowsecurity,
        NOT EXISTS(SELECT 1 FROM pg_catalog.pg_inherits i WHERE i.inhrelid=c.oid OR i.inhparent=c.oid) AS no_inheritance
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=$1 AND c.relname=$2""", namespace, name)
    if row is None:
        return None
    require(row['kind']=='r' and row['persistence']=='p' and row['owner']==owner
            and not row['relrowsecurity'] and not row['relforcerowsecurity']
            and row['no_inheritance'], 'pulse_relation')
    return dict(row)


async def inspect_pulse(conn, contract, owner, *, namespace='core'):
    """Only catalogue SELECTs. Missing child is returned to the explicit DDL owner."""
    require(namespace in {'core','public'}, 'pulse_namespace')
    parents = {}
    for name in ('pulse_views','company_roles'):
        row = await header(conn, namespace, name, owner)
        require(row is not None, 'pulse_parent')
        attrs = await columns(conn, row['oid'])
        wanted = [{'name':n,'type':'uuid','typmod':-1,'not_null':True,'default':None}
                  for n in ('id','company_id')]
        names = verify_columns(attrs, wanted, exact=False)
        keys = await constraints(conn, row['oid'])
        pk = [key for key in keys if key['kind']=='p']
        require(len(pk)==1 and [names.get(n) for n in pk[0]['keys']]==['id'], 'pulse_parent_key')
        constraint_flags(pk[0])
        parents[name] = {**row, 'attributes':names}
    child = await header(conn, namespace, contract['table'], owner)
    if child is None:
        occupied = await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=$1 AND c.relname=ANY($2::text[]))""", namespace,
            ['pulse_view_role_grants_pkey'])
        require(not occupied, 'pulse_reserved_name')
        return None
    oid = child['oid']
    names = verify_columns(await columns(conn,oid), contract['columns'])
    acl = await conn.fetch("""SELECT pg_catalog.pg_get_userbyid(a.grantor) AS grantor,
        CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(a.grantee) END AS grantee,
        a.privilege_type AS privilege,a.is_grantable
        FROM pg_catalog.pg_class c CROSS JOIN LATERAL
        pg_catalog.aclexplode(coalesce(c.relacl,pg_catalog.acldefault('r',c.relowner))) a
        WHERE c.oid=$1""",oid)
    privileges={'SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'}
    require(len(acl)==7 and {r['privilege'] for r in acl}==privileges
        and all(r['grantee']==owner and r['grantor']==owner and not r['is_grantable'] for r in acl), 'pulse_acl')
    require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_attribute
        WHERE attrelid=$1 AND attnum>0 AND attacl IS NOT NULL)
        OR EXISTS(SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid=$1)""",oid), 'pulse_policy')
    keys=await constraints(conn,oid)
    require(len(keys)==3 and sorted(k['kind'] for k in keys)==['f','f','p'], 'pulse_constraints')
    for key in keys:
        constraint_flags(key)
        if key['kind']=='p':
            require([names.get(n) for n in key['keys']]==contract['primary'], 'pulse_primary')
        else:
            match=[f for f in contract['foreign_keys'] if [names.get(n) for n in key['keys']]==[f['column']]]
            require(len(match)==1,'pulse_fk'); target=parents[match[0]['table']]
            require(key['target_oid']==target['oid']
                and [target['attributes'].get(n) for n in key['target_keys']]==[match[0]['target']]
                and key['delete_action']=='c' and key['update_action']=='a' and key['match']=='s', 'pulse_fk')
            await verify_fk_triggers(conn,key['oid'],oid,target['oid'])
    ix=await indexes(conn,oid)
    require(len(ix)==1,'pulse_indexes'); i=ix[0]
    require(i['namespace']==namespace and i['owner']==owner and i['method']=='btree'
        and i['kind']=='i' and i['persistence']=='p' and i['default_acl']
        and i['valid'] and i['ready'] and i['live'] and i['unique'] and i['primary']
        and not i['exclusion'] and i['immediate'] and not i['nulls_not_distinct']
        and i['no_expression'] and i['no_predicate'] and i['default_collations']
        and i['key_count']==i['total_count']==2 and i['options']==[0,0]
        and [names.get(n) for n in i['keys']]==contract['primary']
        and i['opclasses']==['pg_catalog.uuid_ops','pg_catalog.uuid_ops'], 'pulse_index')
    require(not await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_trigger
        WHERE tgrelid=ANY($1::oid[]) AND NOT tgisinternal)""",[oid,*[p['oid'] for p in parents.values()]]), 'pulse_custom_trigger')
    return child
