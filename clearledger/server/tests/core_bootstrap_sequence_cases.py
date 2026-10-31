"""Native composed cases. Only the independently approved wrapper can invoke these.

No pytest/conftest, reconstructed old models, fake catalogue or fake preparation.
Fixture DDL is labelled separately from the real owner's DDL and native startup.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import uuid

COMPANY=uuid.UUID('c4000000-0000-4000-8000-000000000001')
ROLE=uuid.UUID('c4000000-0000-4000-8000-000000000002')
VIEW=uuid.UUID('c4000000-0000-4000-8000-000000000003')
STAMP=datetime(2026,10,31,tzinfo=timezone.utc)
HISTORY_VARIANTS={
    'REF-unknown-future':('unknown','future','extra-over-bound'),
    'REF-gap-checksum':('gap','ordinal','parent_revision','artifact_sha256','contract_sha256','predecessor_sha256'),
    'REF-owner-actor-action':('owner','applied_by','app_commit','runner_format','action-SQLcheck-and-pure'),
}



def require(value,label):
    if not value:raise AssertionError(label)


def digest(value):
    return hashlib.sha256(json.dumps(value,default=str,sort_keys=True,separators=(',',':')).encode()).hexdigest()


# Closed oracle keys, source-derived from the exact intended refusal branches.
# This table does not turn unrelated source/driver/programming errors into PASS.
SAFE_RUNTIME_MESSAGES={
    'Pulse audience schema is not ready','Pulse audience schema is missing',
    'Managed Core budget schema is not ready','Unsupported managed database configuration',
    'Managed application namespace mismatch',
    'Database schema ownership check failed; review namespace provisioning',
}
MIGRATION_ORACLES={
    'M_BOOT_COLUMNS':(4,'bootstrap_columns','schema_migrations/bootstrap/core_prerequisites.py','require'),
    'M_BOOT_CATALOGUE':(4,'bootstrap_catalogue','schema_migrations/bootstrap/core_prerequisites.py','require'),
    'M_PARTNER_OCCUPIED':(4,'partner_prerequisite_occupied','schema_migrations/bootstrap/core_prerequisites.py','require'),
    'M_PARTNER_SOURCE':(2,'partner_predecessor_source','schema_migrations/runner.py','_sequence_source'),
    'M_PARTNER_HISTORY':(4,'partner_upgrade_history','schema_migrations/runner.py','_sequence_catalogue'),
    'M_BOOT_NOT_EMPTY':(4,'bootstrap_not_empty','schema_migrations/runner.py','_sequence_catalogue'),
    'M_BOOT_ADMIN':(4,'bootstrap_admin_prerequisite','schema_migrations/bootstrap/core_prerequisites.py','require'),
    'M_V1_COLUMNS':(4,'columns','schema_migrations/revisions/catalog_v1.py','require'),
    'M_HISTORY':(4,'history','schema_migrations/journal.py','validate_history'),
    'M_HISTORY_BOUND':(4,'history','schema_migrations/runner.py','_sequence_catalogue'),
    'M_BOOT_DEFAULT_ACL':(4,'bootstrap_default_acl','schema_migrations/bootstrap/core_prerequisites.py','require'),
    'M_V1_RELATION':(4,'relation','schema_migrations/revisions/catalog_v1.py','require'),
    'M_UNAPPLIED':(4,'unapplied','schema_migrations/runner.py','require_applied_prefix'),
    'M_TARGET':(3,'target','schema_migrations/runner.py','Config.validate'),
    'M_PULSE_PARENT':(4,'pulse_parent','schema_migrations/revisions/catalog_v1.py','require'),
    'M_SOURCE_COPY':(2,'bootstrap_source','schema_migrations/bootstrap/core_prerequisites.py','load'),
    'M_OWNER_LOCK':(5,'owner_lock','schema_migrations/runner.py','execute_sequence'),
}
PRIMARY_ORACLES={
    'CUR-empty-core-off':'PULSE_PARENT','CUR-empty-core-on':'GATE_ENGINE_UNAPPLIED',
    'OLDUP-wrong-parent-column':'M_BOOT_COLUMNS','OLDUP-wrong-parent-ACL':'M_BOOT_CATALOGUE',
    'OLDUP-one-partner-present':'M_PARTNER_OCCUPIED','OLDUP-wrong-profile-source':'M_PARTNER_SOURCE',
    'OLDUP-managed-history-present':'M_PARTNER_HISTORY','FRESH-nonempty-refuse':'M_BOOT_NOT_EMPTY',
    'FRESH-missing-edge-extension':'M_BOOT_ADMIN','UPG-foreign-parent':'M_V1_COLUMNS',
    'UPG-head-repeat':'M_HISTORY','REF-default-acl':'M_BOOT_DEFAULT_ACL',
    'REF-missing-core-public-decoy':'NS_PATH','REF-visible-public':'NS_FOREIGN',
    'REF-catalogue':'M_V1_COLUMNS','REF-wrong-marker':'PULSE_CHILD',
    'CFG-identity':'GATE_ENGINE_CONFIG_TARGET','CFG-url-options':'GATE_ENGINE_UNSUPPORTED_QUERY',
    'CFG-real-path':'GATE_BORROWED_NAMESPACE','TX-owner-contention':'M_OWNER_LOCK',
    'LIFE-rejected-no-seed':'PULSE_PARENT',
}
VARIANT_ORACLES={
    'REF-unknown-future':{'unknown':'M_HISTORY','future':'M_HISTORY_BOUND','extra-over-bound':'M_HISTORY_BOUND'},
    'REF-gap-checksum':{key:'M_HISTORY' for key in ('gap','ordinal','parent_revision','artifact_sha256','contract_sha256','predecessor_sha256')},
    'REF-owner-actor-action':{'owner':'M_V1_RELATION','applied_by':'M_HISTORY','app_commit':'M_HISTORY','runner_format':'M_HISTORY'},
}
# These are requirements, NOT guessed/passed third-party source claims. ROOT must
# read pinned77 source and supply exact reviewed bindings before TX-readonly.
READONLY_LIBRARY_REQUIREMENTS={
    'sqlalchemy':{'version':'2.0.36','files':['sqlalchemy/exc.py','sqlalchemy/engine/base.py','sqlalchemy/dialects/postgresql/asyncpg.py'],
        'symbols':['DBAPIError','Connection._handle_dbapi_exception','AsyncAdapt_asyncpg_connection._handle_exception','AsyncAdapt_asyncpg_dbapi.Error']},
    'asyncpg':{'version':'0.30.0','files':['asyncpg/exceptions/__init__.py','asyncpg/connection.py'],
        'symbols':['ReadOnlySQLTransactionError','Connection.execute'],'SQLSTATE':'25006'},
}
READONLY_LIBRARY_SOURCE_BINDINGS={'root_review': 'msg_df07f98ccfa1', 'root_receipt_sha256': '305b5c4cf7cfe86d5e4366346bf2fee4799e96b676ad2969e846a0fe12de62cc', 'sqlstate': '25006', 'source_files': {'sqlalchemy/dialects/postgresql/asyncpg.py': 'f4fd08b67f5e79206eebb9064ac1eecf1f31778618c1129d899e66edb179a275', 'sqlalchemy/engine/base.py': '7eb592326b777657a7b581f840d3777228dd1b3a7c35bba70a89546705ac5a02', 'sqlalchemy/exc.py': '33ff3e3b585df22ea06f2c7e4daa55e34d29fcbc6ad90a9318c5d400ef988027', 'asyncpg/exceptions/__init__.py': '1575180c5430f60c44de6573f7d166b25758c62bcb50cb532215f3bb9b59ecf9'}, 'outer_type': 'sqlalchemy.exc.DBAPIError', 'adapter_type': 'sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.Error', 'native_type': 'asyncpg.exceptions.ReadOnlySQLTransactionError', 'runtime_chain_measured': False}  # Source facts, never an actual-outcome claim.
_ORIGIN_SITE_CACHE={}


def oracle_key(case,variant=None):
    if variant is not None:return VARIANT_ORACLES[case][variant]
    return PRIMARY_ORACLES[case]


def _known_sources(env):
    sources={str((env.SERVER/name).resolve()):(sha,name) for name,sha in env.FROZEN_MANIFEST}
    for pin,rows in env.ARCHIVE_MANIFEST.items():
        base=Path(env.os.environ['CORE_BOOTSTRAP_ARCHIVES'])/pin/'clearledger/server'
        sources.update({str((base/name).resolve()):(sha,name) for name,sha in rows})
    copy=env.ROOTS.get('scratch')
    if copy is not None:
        name='schema_migrations/bootstrap/core_prerequisites.py'
        sha=dict(env.FROZEN_MANIFEST)[name]
        sources[str((copy/'tampered-source/bootstrap/core_prerequisites.py').resolve())]=(sha,name)
    return sources


def _capture_error(env,error):
    """Capture actual type/cause/source facts; never echo unknown driver messages."""
    from schema_migrations.errors import MigrationError
    trusted=_known_sources(env);seen={};active=set();nodes=[];valid=True
    def visit(exc):
        nonlocal valid
        if exc is None:return None
        if id(exc) in active:valid=False;return None
        if id(exc) in seen:return seen[id(exc)]
        if len(nodes)>=8:valid=False;return None
        index=len(nodes);seen[id(exc)]=index;active.add(id(exc))
        cls=type(exc);name=cls.__module__+'.'+cls.__qualname__
        canonical=(cls in (RuntimeError,MigrationError,TimeoutError,asyncio.CancelledError))
        if name=='fastapi.exceptions.HTTPException':
            from fastapi.exceptions import HTTPException
            canonical=cls is HTTPException
        phase=getattr(exc,'phase',None) if cls is MigrationError else None
        code=getattr(exc,'code',None) if cls is MigrationError else None
        message=exc.args[0] if cls is RuntimeError and len(exc.args)==1 and type(exc.args[0]) is str and exc.args[0] in SAFE_RUNTIME_MESSAGES else None
        origin={'trusted':False,'path':None,'symbol':None,'line':None,'sha256':None,'module':None}
        tb=exc.__traceback__
        if tb is not None:
            while tb.tb_next is not None:tb=tb.tb_next
            codeobj=tb.tb_frame.f_code;filename=str(Path(codeobj.co_filename).resolve())
            origin.update(symbol=codeobj.co_qualname,line=tb.tb_lineno,module=tb.tb_frame.f_globals.get('__name__'))
            if filename in trusted:
                expected,relative=trusted[filename];actual=hashlib.sha256(Path(filename).read_bytes()).hexdigest()
                origin.update(trusted=actual==expected,path=relative,sha256=actual,absolute=filename)
        node={'actual_type':name,'canonical_type':canonical,'code':code if type(code) is int else None,
            'phase':phase if type(phase) is str and phase in {p[1] for p in MIGRATION_ORACLES.values()} else None,
            'args_valid':cls is MigrationError and type(code) is int and type(phase) is str and exc.args==(phase,),
            'message_enum':message,'status_code':getattr(exc,'status_code',None) if name=='fastapi.exceptions.HTTPException' else None,
            'detail_enum':getattr(exc,'detail',None) if name=='fastapi.exceptions.HTTPException' else None,
            'origin':origin,'cause':None,'context':None,'suppress_context':exc.__suppress_context__}
        nodes.append(node);node['cause']=visit(exc.__cause__);node['context']=visit(exc.__context__)
        active.remove(id(exc));return index
    visit(error)
    return {'valid_dag':valid,'nodes':nodes}


def _linear_cause(observation):
    if not observation['valid_dag'] or not observation['nodes']:return None
    nodes=observation['nodes'];line=[];index=0;visited=set()
    while index is not None:
        if index in visited:return None
        visited.add(index);node=nodes[index];line.append(node)
        c,x=node['cause'],node['context']
        if c is not None and x is not None and c!=x:return None
        index=c if c is not None else x
    return line if len(visited)==len(nodes) else None


def _raise_origin(env,node,path,symbol,*,phase=None,message=None,namespace_branch=None,copy=False):
    origin=node['origin']
    if not origin['trusted'] or origin['path']!=path or origin['symbol']!=symbol:return False
    wanted=(env.IMPORT_SERVER/path).resolve()
    if not wanted.is_file():wanted=(env.SERVER/path).resolve()  # Oldce has no framework package.
    if copy:wanted=(env.ROOTS['scratch']/'tampered-source/bootstrap/core_prerequisites.py').resolve()
    if origin.get('absolute')!=str(wanted):return False
    key=(str(wanted),origin['sha256'],symbol,phase,message,namespace_branch)
    if key not in _ORIGIN_SITE_CACHE:
        import ast
        tree=ast.parse(wanted.read_bytes());parts=symbol.split('.')
        body=tree.body
        for part in parts:
            target=next((n for n in body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==part),None)
            if target is None:return False
            body=target.body
        raises=[]
        for raise_node in ast.walk(target):
            if not isinstance(raise_node,ast.Raise) or not isinstance(raise_node.exc,ast.Call):continue
            call=raise_node.exc;name=ast.unparse(call.func)
            if message is not None:
                if name!='RuntimeError' or len(call.args)!=1 or not isinstance(call.args[0],ast.Constant) or call.args[0].value!=message:continue
            elif phase is not None:
                if name!='MigrationError' or len(call.args)<2:continue
                arg=call.args[1]
                if isinstance(arg,ast.Constant) and arg.value!=phase:continue
                if not isinstance(arg,(ast.Constant,ast.Name)):continue
                if isinstance(arg,ast.Name) and arg.id!='phase':continue
            raises.append(raise_node.lineno)
        if namespace_branch is not None:
            # Two identical messages have different source predicates; do not
            # let visible-foreign refusal substitute for a missingCore/path refusal.
            branches=[n for n in ast.walk(target) if isinstance(n,ast.If) and
                (('namespace_path_is_explicit' in ast.unparse(n.test)) if namespace_branch=='path' else ast.unparse(n.test)=='foreign')]
            raises=[n.lineno for branch in branches for n in ast.walk(branch) if isinstance(n,ast.Raise) and n.lineno in raises]
        _ORIGIN_SITE_CACHE[key]=set(raises)
    return origin['line'] in _ORIGIN_SITE_CACHE[key]


def _match_migration(env,node,key,*,copy=False):
    code,phase,path,symbol=MIGRATION_ORACLES[key]
    return (node['canonical_type'] and node['actual_type']=='schema_migrations.errors.MigrationError'
        and node['args_valid'] and node['code']==code and node['phase']==phase
        and _raise_origin(env,node,path,symbol,phase=phase,copy=copy))


def _match_runtime(env,node,path,symbol,message,namespace_branch=None):
    return (node['canonical_type'] and node['actual_type']=='builtins.RuntimeError' and node['message_enum']==message
        and _raise_origin(env,node,path,symbol,message=message,namespace_branch=namespace_branch))


def matches_refusal(env,key,observation):
    line=_linear_cause(observation)
    if line is None:return False
    if key in MIGRATION_ORACLES:
        if key=='M_OWNER_LOCK':
            return (len(line)==3 and _match_migration(env,line[0],key)
                and line[1]['canonical_type'] and line[1]['actual_type']=='builtins.TimeoutError'
                and line[1]['origin']['module']=='asyncio.timeouts' and line[1]['origin']['symbol']=='Timeout.__aexit__'
                and line[2]['canonical_type'] and line[2]['actual_type']=='asyncio.exceptions.CancelledError')
        return len(line)==1 and _match_migration(env,line[0],key,copy=key=='M_SOURCE_COPY')
    pulse='app/services/pulse_view_role_schema.py';gate='app/services/schema_version_gate.py'
    def rt(n,path,symbol,msg,branch=None):return _match_runtime(env,line[n],path,symbol,msg,branch)
    if key=='PULSE_PARENT':return len(line)==2 and rt(0,pulse,'require_connection','Pulse audience schema is not ready') and _match_migration(env,line[1],'M_PULSE_PARENT')
    if key=='PULSE_CHILD':return len(line)==2 and rt(0,pulse,'require_connection','Pulse audience schema is not ready') and rt(1,pulse,'require_connection','Pulse audience schema is missing')
    if key=='GATE_ENGINE_UNAPPLIED':return len(line)==3 and rt(0,gate,'require_engine','Managed Core budget schema is not ready') and rt(1,gate,'require_connection','Managed Core budget schema is not ready') and _match_migration(env,line[2],'M_UNAPPLIED')
    if key in ('NS_PATH','NS_FOREIGN'):return len(line)==1 and rt(0,'app/database.py','_assert_bootstrap_namespace','Database schema ownership check failed; review namespace provisioning','path' if key=='NS_PATH' else 'foreign')
    if key in ('GATE_ENGINE_CONFIG_TARGET','GATE_PREFLIGHT_CONFIG_TARGET'):return len(line)==2 and rt(0,gate,'preflight' if key=='GATE_PREFLIGHT_CONFIG_TARGET' else 'require_engine','Managed Core budget schema is not ready') and _match_migration(env,line[1],'M_TARGET')
    if key=='GATE_ENGINE_UNSUPPORTED_QUERY':return len(line)==2 and rt(0,gate,'require_engine','Managed Core budget schema is not ready') and rt(1,gate,'_config','Unsupported managed database configuration')
    if key=='GATE_BORROWED_NAMESPACE':return len(line)==2 and rt(0,gate,'require_connection','Managed Core budget schema is not ready') and rt(1,gate,'require_connection','Managed application namespace mismatch')
    if key=='READY_PULSE_CHILD':
        node=line[0]
        # Source raises HTTPException explicitly from the Pulse refusal.
        origin=node['origin'];suffix={'valid_dag':True,'nodes':[]}
        import copy
        nodes=copy.deepcopy(observation['nodes'][1:])
        for n in nodes:
            n['cause']=n['cause']-1 if n['cause'] is not None else None
            n['context']=n['context']-1 if n['context'] is not None else None
        suffix['nodes']=nodes
        import ast
        source=(env.IMPORT_SERVER/'app/main.py').resolve()
        if origin.get('absolute')!=str(source):return False
        tree=ast.parse(source.read_bytes());ready=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='readiness_check')
        sites=[n.lineno for n in ast.walk(ready) if isinstance(n,ast.Raise) and isinstance(n.exc,ast.Call) and ast.unparse(n.exc.func)=='HTTPException' and any(k.arg=='detail' and isinstance(k.value,ast.Constant) and k.value.value=='База, схема или файловое хранилище не готовы' for k in n.exc.keywords)]
        return (origin['line'] in sites and node['canonical_type'] and node['actual_type']=='fastapi.exceptions.HTTPException'
            and node['status_code']==503 and node['detail_enum']=='База, схема или файловое хранилище не готовы'
            and origin['trusted'] and origin['path']=='app/main.py' and origin['symbol']=='readiness_check'
            and matches_refusal(env,'PULSE_CHILD',suffix))
    return False


def classify_readonly(env,error):
    """Canonical three-type/source-raise contract from ROOT pinned77 source review.

    Native runtime chain is still unmeasured. A mismatch fails unchanged, never
    broadens the allowlist using the first observed error or SQLSTATE alone.
    """
    b=READONLY_LIBRARY_SOURCE_BINDINGS
    if not b or b['sqlstate']!='25006' or not b['root_review']:return None
    import ast
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
    from asyncpg.exceptions import ReadOnlySQLTransactionError
    for relative,wanted in b['source_files'].items():
        path=env.SITE/relative
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=wanted:return None
    if type(error) is not DBAPIError:return None
    adapter=getattr(error,'orig',None)
    if type(adapter) is not AsyncAdapt_asyncpg_dbapi.Error or error.__cause__ is not adapter:return None
    native=adapter.__cause__
    if type(native) is not ReadOnlySQLTransactionError:return None
    if getattr(adapter,'sqlstate',None)!='25006' or native.sqlstate!='25006':return None
    allowed={id(error),id(adapter),id(native)};seen=set()
    def visit(exc):
        if exc is None:return True
        if id(exc) not in allowed:return False
        if id(exc) in seen:return True
        seen.add(id(exc));return visit(exc.__cause__) and visit(exc.__context__)
    if not visit(error) or seen!=allowed:return None
    def frames(exc):
        rows=[];tb=exc.__traceback__
        while tb is not None:
            rows.append({'file':tb.tb_frame.f_code.co_filename,'symbol':tb.tb_frame.f_code.co_qualname,'line':tb.tb_lineno,'module':tb.tb_frame.f_globals.get('__name__')});tb=tb.tb_next
        return rows
    # Source AST supplies exact translated-error raise line; no guessed line.
    path=env.SITE/'sqlalchemy/dialects/postgresql/asyncpg.py';tree=ast.parse(path.read_bytes())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AsyncAdapt_asyncpg_connection')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_handle_exception')
    sites={n.lineno for n in ast.walk(fn) if isinstance(n,ast.Raise) and isinstance(n.exc,ast.Name) and n.exc.id=='translated_error' and isinstance(n.cause,ast.Name) and n.cause.id=='error'}
    actual_adapter_frames=frames(adapter)
    if not any(Path(v['file'])==path and v['symbol']=='AsyncAdapt_asyncpg_connection._handle_exception' and v['line'] in sites for v in actual_adapter_frames):return None
    if not any(v['module']=='sqlalchemy.engine.base' and v['symbol']=='Connection._handle_dbapi_exception' for v in frames(error)):return None
    if not any(str(v['module']).startswith('asyncpg.') for v in frames(native)):return None
    return {'expected_oracle_key':'ROOT_PINNED_READONLY_25006','actual_type':type(error).__module__+'.'+type(error).__qualname__,
        'actual_sqlstate':native.sqlstate,'actual_adapter_type':type(adapter).__module__+'.'+type(adapter).__qualname__,
        'actual_native_type':type(native).__module__+'.'+type(native).__qualname__,
        'actual_causal_origins':{'outer':frames(error),'adapter':actual_adapter_frames,'native':frames(native)},
        'ROOT_source_review':b['root_review'],'ROOT_source_file_pins':b['source_files']}


def classify_refusal(env,error,key):
    """Return actual facts only for an exact source-backed rule; UNKNOWN is None."""
    observed=_capture_error(env,error)
    if not matches_refusal(env,key,observed):return None
    first=observed['nodes'][0];last=observed['nodes'][-1]
    return {'expected_oracle_key':key,'actual_type':first['actual_type'],'actual_code':first['code'],
        'actual_phase':first['phase'],'actual_message_enum':first['message_enum'],
        'causal_leaf_type':last['actual_type'],'causal_leaf_code':last['code'],'causal_leaf_phase':last['phase'],
        'origin':first['origin'],'causal_DAG':observed}


def classifier_controls(env):
    """12 adversarial classifier controls + genuine frozen journal positive; no SUT mocks/PG."""
    from schema_migrations import journal,manifest
    from schema_migrations.errors import MigrationError
    checks={}
    for label,error in [('directNameError',NameError('classifier-control')),('directTypeError',TypeError('classifier-control')),('directAttributeError',AttributeError('classifier-control')),
                        ('wrongRuntimeOrigin',RuntimeError('Pulse audience schema is not ready')),
                        ('forgedMigrationOrigin',MigrationError(4,'history')),('wrongMigrationCode6',MigrationError(6,'database')),
                        ('wrongMigrationPhase',MigrationError(4,'columns'))]:
        try:raise error
        except BaseException as actual:checks[label]=classify_refusal(env,actual,'M_HISTORY' if isinstance(error,MigrationError) else 'PULSE_PARENT') is None
    for label,error,message in [('hiddenNameError',NameError('classifier-control'),'Pulse audience schema is not ready'),('hiddenTypeError',TypeError('classifier-control'),'Managed Core budget schema is not ready')]:
        try:
            try:raise error
            except BaseException:raise RuntimeError(message) from None
        except BaseException as actual:
            observed=_capture_error(env,actual)
            import copy,ast
            def expected_runtime(path,symbol,message):
                source=(env.IMPORT_SERVER/path).resolve()
                if not source.is_file():source=(env.SERVER/path).resolve()  # Pinned source for synthetic classifier metadata only.
                tree=ast.parse(source.read_bytes());function=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==symbol)
                line=next(n.lineno for n in ast.walk(function) if isinstance(n,ast.Raise) and isinstance(n.exc,ast.Call) and ast.unparse(n.exc.func)=='RuntimeError' and n.exc.args and isinstance(n.exc.args[0],ast.Constant) and n.exc.args[0].value==message)
                node=copy.deepcopy(observed['nodes'][0]);node.update(actual_type='builtins.RuntimeError',canonical_type=True,message_enum=message,cause=None,context=None)
                node['origin']={'trusted':True,'path':path,'symbol':symbol,'line':line,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'absolute':str(source),'module':'classifier_synthetic_origin'}
                return node
            leaf=copy.deepcopy(observed['nodes'][-1]);leaf.update(cause=None,context=None)
            if label=='hiddenNameError':
                outer=expected_runtime('app/services/pulse_view_role_schema.py','require_connection',message);outer['context']=1
                crafted={'valid_dag':True,'nodes':[outer,leaf],'synthetic_classifier_input':True}
                checks[label]=_match_runtime(env,outer,'app/services/pulse_view_role_schema.py','require_connection',message) and not matches_refusal(env,'PULSE_PARENT',crafted)
            else:
                outer=expected_runtime('app/services/schema_version_gate.py','require_engine',message);middle=expected_runtime('app/services/schema_version_gate.py','require_connection',message);outer['context']=1;middle['context']=2
                crafted={'valid_dag':True,'nodes':[outer,middle,leaf],'synthetic_classifier_input':True}
                checks[label]=_match_runtime(env,outer,'app/services/schema_version_gate.py','require_engine',message) and _match_runtime(env,middle,'app/services/schema_version_gate.py','require_connection',message) and not matches_refusal(env,'GATE_ENGINE_UNAPPLIED',crafted)
    class Fake503(Exception):status_code=503
    try:raise Fake503()
    except BaseException as actual:checks['fakeStatus503']=classify_refusal(env,actual,'READY_PULSE_CHILD') is None
    try:raise RuntimeError('unrelated SQLSTATE 42P01')
    except BaseException as actual:checks['unrelatedDriverOrSQL']=classify_refusal(env,actual,'M_HISTORY') is None
    try:raise RuntimeError('Managed Core budget schema is not ready')
    except BaseException as actual:checks['missingCauseLeaf']=classify_refusal(env,actual,'GATE_ENGINE_UNAPPLIED') is None
    require(len(checks)==12 and all(checks.values()),'12classifier negative controls')
    p=manifest.load();entry=p.entry
    row={'revision':'unknown','ordinal':1,'parent_revision':None,'artifact_sha256':entry['artifact_sha256'],
        'contract_sha256':entry['files'][p.contract_file],'predecessor_sha256':None,'action':'created',
        'applied_by':'clearledger','app_commit':entry['source_commit'],'runner_format':1}
    try:journal.validate_history([row],p,'clearledger')
    except MigrationError as actual:positive=classify_refusal(env,actual,'M_HISTORY')
    else:raise AssertionError('genuine frozen journal positive control did not refuse')
    require(positive is not None,'genuine frozen journal error origin accepted')
    return {'negative_count':12,'negative':checks,'genuine_source_positive_count':1,'positive':positive,
        'separate_from57_primary':True,'no_fake_guard_or_DB_success':True}



class Context:
    def __init__(self,envelope):
        require(envelope._ACTIVE,'ROOT envelope before any application/driver imports')
        self.env=envelope;self.phase='fixture';self.trace={};self.engines=[];self.raw=[];self.current='setup';self.closed=False;self.observer_errors=[];self.artifact_sql=None;self.artifact_reached=asyncio.Event();self.journal_reached=asyncio.Event();self.cancel_after_ordinal=None;self.pids=[]

    def observe(self,sql,channel,pid=None):
        if self.artifact_sql is not None and sql==self.artifact_sql:self.artifact_reached.set()
        key=hashlib.sha256(sql.encode()).hexdigest()
        row=self.trace.setdefault(key,{'sql':sql,'channels':{},'phases':{},'bytes':len(sql)})
        row['channels'][channel]=row['channels'].get(channel,0)+1;row['phases'][self.phase]=row['phases'].get(self.phase,0)+1
        if len(self.trace)>40000 or sum(r['bytes'] for r in self.trace.values())>12*1024*1024:self.observer_errors.append('per-case trace cap exceeded')

    def write_attempts(self):
        total=0
        for r in self.trace.values():
            q=re.sub(r'(?m)^\s*--[^\n]*','',r['sql']).lstrip().lower()
            if re.match(r'(create|alter|drop|insert|update|delete|truncate|do|grant|revoke|lock)\b',q):total+=r['phases'].get('tested',0)
        return total

    async def setup(self,namespace='core'):
        import asyncpg
        from sqlalchemy import event,text
        from sqlalchemy.engine import Engine
        from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
        self.text=text;self.asyncpg=asyncpg;self.factory_type=async_sessionmaker
        original=asyncpg.connect
        async def connect(*args,**kwargs):
            c=await original(*args,**kwargs)
            pid=c.get_server_pid();self.pids.append(pid)
            def logged(record):
                self.observe(record.query,'raw',pid)
                args=getattr(record,'args',())
                if self.cancel_after_ordinal is not None and record.query.lstrip().lower().startswith('insert into core.core_schema_versions') and len(args)>1 and args[1]==self.cancel_after_ordinal:self.journal_reached.set()
            c.add_query_logger(logged)
            self.raw.append(c);return c
        self.env_stack=self.env.ExitStack();self.env_stack.enter_context(__import__('unittest.mock',fromlist=['patch']).patch.object(asyncpg,'connect',connect))
        self.listener=lambda conn,cursor,statement,parameters,context,executemany:self.observe(statement,'sqlalchemy')
        event.listen(Engine,'before_cursor_execute',self.listener)
        self.event=event;self.Engine=Engine
        from app import database
        from app import main
        require(Path(main.__file__).resolve()==self.env.IMPORT_SERVER/'app/main.py','exact approved app.main origin')
        require(Path(database.__file__).resolve()==self.env.IMPORT_SERVER/'app/database.py','exact approved database origin')
        self.db,self.main=database,main
        self.old_engine=database.engine;self.old_factory=database.async_session_factory;self.old_main_factory=main.async_session_factory
        self.engine=create_async_engine(self.env.BASE_URL,pool_size=2,max_overflow=0,connect_args={'server_settings':{'search_path':namespace},'timeout':5,'command_timeout':20})
        self.engines.extend([self.engine,self.old_engine]);database.engine=self.engine
        database.async_session_factory=async_sessionmaker(self.engine,expire_on_commit=False)
        main.async_session_factory=database.async_session_factory
        self.settings=main.settings
        self.settings.app_env='test'
        if hasattr(self.settings,'managed_core_budget_enabled'):
            self.settings.managed_core_budget_enabled=False
            self.settings.managed_core_budget_expected_database=self.env.DATABASE;self.settings.managed_core_budget_expected_user='clearledger'
        self.admin=await asyncpg.connect(self.env.RAW_URL,server_settings={'search_path':'core','application_name':'core-bootstrap-root-fixture'},timeout=5,command_timeout=20)
        require((await self.admin.fetchval('select current_database()'))==self.env.DATABASE,'actual target before fixture')
        require(await self.admin.fetchval('select current_user')=='clearledger','actual fixture actor')
        require(160000<=int(await self.admin.fetchval('show server_version_num'))<170000,'PG16')
        require(await self.admin.fetchval("select exists(select 1 from pg_extension where extname='btree_gist')"),'ROOT admin extension precondition, never install')
        self.lease_path=self.env.ROOTS['evidence']/('lease-child-'+str(self.env.os.getpid())+'.json' if self.env.IS_CHILD else 'owned-db-lease.json')
        oid=await self.admin.fetchval('select oid from pg_database where datname=current_database()')
        root_lease=self.env.root_database_lease();require(root_lease['database_oid']==oid,'actual DB identity matches independent ROOT lease')
        if self.env.IS_CHILD:
            parent=json.loads((self.env.ROOTS['evidence']/'owned-db-lease.json').read_text())
            require(parent['database']==self.env.DATABASE and parent['database_oid']==oid,'child exact owned DB lease')
            lease_id=parent['lease_id']
        elif self.env.os.environ['CORE_BOOTSTRAP_RESTORE_ACTION']=='verify':
            parent=json.loads(self.lease_path.read_text());require(parent['status']=='awaiting-root-restore' and parent['database']==self.env.DATABASE
                and parent['source_manifest_sha256']==self.env.FROZEN_MANIFEST_SHA256,'intentional pending lease continuation')
            lease_id=parent['lease_id']
        else:lease_id=root_lease['lease_id']
        require(lease_id==root_lease['lease_id'],'ROOT-owned lease continuity')
        self.lease={'lease_id':lease_id,'database':self.env.DATABASE,'database_oid':oid,'host':'127.0.0.1','port':33547,
            'actor':'clearledger','status':'active','helper_pid':self.env.os.getpid(),'source_manifest_sha256':self.env.FROZEN_MANIFEST_SHA256,
            'wrapper_sha256':self.env.os.environ['CORE_BOOTSTRAP_RUNNER_SHA256'],'task_id':'task_81d451ce13e8','dispatch_id':'ctx_258a83d73654'}
        self.lease_path.write_text(json.dumps(self.lease,indent=2)+'\n')
        self.config=__import__('schema_migrations.runner',fromlist=['Config']).Config(self.env.RAW_URL,self.env.DATABASE,'clearledger','core',total_seconds=120)
        return self

    async def bounds(self,stage):
        require(not self.observer_errors,'query observer failed/cap exceeded')
        small=stage=='characterize_current'
        cap=(48 if small else 2048)*1024*1024
        size=await self.admin.fetchval('select pg_database_size(current_database())')
        require(size<=cap,'stage dedicated database bytes cap')
        limits={'evidence':(8 if small else 64),'scratch':(4 if small else 128),'uploads':(4 if small else 128)}
        actual={}
        for name,mib in limits.items():
            total=0
            for path in self.env.ROOTS[name].rglob('*'):
                require(not path.is_symlink(),'owned root symlink')
                if path.is_file():
                    if name=='evidence' and path.name=='restore-before.dump':
                        require(path.stat().st_size<=2048*1024*1024,'synthetic dump2GiB cap')
                    else:total+=path.stat().st_size
            require(total<=mib*1024*1024,'stage writable root cap:'+name);actual[name]=total
        return {'database_bytes':size,'writable_root_bytes':actual,'WAL_delta':'ROOT supervisor measurement required; not measured by application role'}

    async def reset(self):
        """ROOT-only dedicated-DB fixture administration; production never calls this."""
        self.phase='fixture';self.settings.app_env='test'
        if hasattr(self.settings,'managed_core_budget_enabled'):self.settings.managed_core_budget_enabled=False
        await self.engine.dispose()
        await self.admin.execute('DROP SCHEMA IF EXISTS core CASCADE')
        await self.admin.execute('DROP SCHEMA IF EXISTS edge CASCADE')
        # public contains ROOT-installed extension objects; preserve those exact members.
        rows=await self.admin.fetch("""SELECT c.relname,c.relkind::text AS kind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND pg_get_userbyid(c.relowner)=current_user AND c.relkind IN ('r','p','v','m','S','f')
              AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')""")
        for r in rows:
            require(re.fullmatch('[a-z_][a-z0-9_]*',r['relname']),'owned public fixture identifier')
            keyword={'v':'VIEW','m':'MATERIALIZED VIEW','S':'SEQUENCE','f':'FOREIGN TABLE'}.get(r['kind'],'TABLE')
            await self.admin.execute('DROP '+keyword+' IF EXISTS public."'+r['relname']+'" CASCADE')
        rows=await self.admin.fetch("""SELECT p.proname,pg_get_function_identity_arguments(p.oid) AS args FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind='f' AND pg_get_userbyid(p.proowner)=current_user
              AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')""")
        for r in rows:
            require(re.fullmatch('[a-z_][a-z0-9_]*',r['proname']),'owned public fixture routine')
            await self.admin.execute('DROP FUNCTION IF EXISTS public."'+r['proname']+'"('+r['args']+') CASCADE')
        await self.admin.execute('CREATE SCHEMA core AUTHORIZATION clearledger')
        await self.admin.execute('CREATE SCHEMA edge AUTHORIZATION clearledger')
        self.trace={};self.env.SINKS.clear()

    async def owned(self,fresh=True):
        from schema_migrations.runner import execute_sequence
        self.phase='tested'
        receipt=await execute_sequence(self.config,target_revision='0003_pulse_view_role_grants',
            fresh_prerequisites='core_prerequisites_v1' if fresh else None,legacy_sent_before=2000000000)
        await asyncio.sleep(0);self.phase='fixture';return receipt

    async def upgrade_old(self,pin):
        from schema_migrations.runner import execute_sequence
        self.phase='tested'
        receipt=await execute_sequence(self.config,target_revision='0003_pulse_view_role_grants',
            upgrade_prerequisites='core_partner_prerequisites_v1',predecessor_source=pin,legacy_sent_before=2000000000)
        await asyncio.sleep(0);self.phase='fixture';return receipt

    async def business(self,pin):
        email='c4-old-'+pin[:8]+'@example.invalid'
        company=await self.admin.fetchval("SELECT to_jsonb(t)::text FROM core.companies t WHERE slug='core-bootstrap'")
        user=await self.admin.fetchval('SELECT to_jsonb(t)::text FROM core.users t WHERE email=$1',email)
        event=await self.admin.fetchval("SELECT to_jsonb(t)::text FROM core.calendar_events t WHERE title='Synthetic old migration witness'")
        require(company and user and event,'real old native business witnesses')
        return {'company':json.loads(company),'user':json.loads(user),'event':json.loads(event)}

    async def prefix(self,count,*,managed_counter=False):
        """Exact literal owner source prepares ancestors; never substitute this for fullstartup."""
        from schema_migrations import runner,manifest
        source,verifier=runner._bootstrap_source()
        self.phase='fixture'
        async with self.admin.transaction():
            await self.admin.execute('SELECT pg_advisory_xact_lock(434532,1)')
            await self.admin.execute(source.sql)
        if managed_counter:await self.admin.execute(manifest.load(revision=manifest.CALENDAR_ID).sql)
        for n,p in enumerate((manifest.ID,manifest.CALENDAR_ID,manifest.PULSE_ID),1):
            if n<=count:await runner.execute(self.config,'apply',revision=p,legacy_sent_before=2000000000 if n==2 else None)

    async def prepare(self,*,lifespan=False,managed=False,prod=False):
        if hasattr(self.settings,'managed_core_budget_enabled'):self.settings.managed_core_budget_enabled=managed
        else:require(not managed,'old binary has no managed flag; no synthetic injection')
        self.settings.app_env='prod' if prod else 'test';self.phase='tested'
        if lifespan:
            async with self.main.app.router.lifespan_context(self.main.app):await asyncio.sleep(0)
        else:
            async with self.db.database_startup_lock():await self.main._prepare_database_once(STAMP)
        await asyncio.sleep(0);self.phase='fixture'

    async def ready(self):
        async with self.db.async_session_factory() as db:
            return await self.main.readiness_check(db)

    async def state(self):
        rows=await self.admin.fetch("""SELECT n.nspname,c.relname,c.relkind::text AS kind,c.relacl::text,pg_get_userbyid(c.relowner) AS owner
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('core','edge','public') ORDER BY 1,2""")
        catalog=[dict(r) for r in rows];data={};total=0
        details={}
        for name,sql in {
            'columns':"SELECT n.nspname,c.relname,a.attnum,a.attname,a.atttypid::regtype::text,a.atttypmod,a.attnotnull,a.attisdropped,a.attidentity::text,a.attgenerated::text,a.attacl::text,pg_get_expr(d.adbin,d.adrelid,false) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname IN ('core','edge','public') AND a.attnum>0 ORDER BY 1,2,3",
            'constraints':"SELECT n.nspname,c.relname,k.conname,k.contype::text,k.convalidated,k.condeferrable,k.condeferred,pg_get_constraintdef(k.oid,false) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('core','edge','public') ORDER BY 1,2,3",
            'indexes':"SELECT n.nspname,c.relname,ic.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready,i.indislive FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_class ic ON ic.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('core','edge','public') ORDER BY 1,2,3",
            'routines':"SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.prosrc,p.proacl::text,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('core','edge','public') ORDER BY 1,2,3",
            'triggers':"SELECT n.nspname,c.relname,t.tgname,t.tgtype,t.tgenabled::text,t.tgisinternal,t.tgdeferrable,t.tginitdeferred,pg_get_triggerdef(t.oid,false) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('core','edge','public') ORDER BY 1,2,3"
        }.items():details[name]=[list(row) for row in await self.admin.fetch(sql)]
        for r in rows:
            if r['kind'] not in ('r','p'):continue
            name=r['nspname']+'.'+r['relname'];require(re.fullmatch(r'[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*',name),'snapshot identifier')
            values=await self.admin.fetch('SELECT to_jsonb(t)::text AS value FROM '+name+' t')
            total+=len(values);require(total<=50000,'snapshot row cap')
            data[name]=sorted(r['value'] for r in values)
        return {'catalogue_sha256':digest({'relations':catalog,'details':details}),'data_sha256':digest(data),'relations':len(catalog),'rows':total}

    async def reject(self,operation,*,oracle):
        before=await self.state();self.phase='tested';start=self.write_attempts();classified=None
        try:await operation()
        except BaseException as actual:
            classified=classify_refusal(self.env,actual,oracle)
            if classified is None:raise  # Preserve unexpected actual class/traceback; never a refusal PASS.
            message=str(actual)
        else:raise AssertionError('required refusal did not happen')
        await asyncio.sleep(0);self.phase='fixture';after=await self.state()
        require(not self.observer_errors,'query observer integrity before claiming zero writes')
        require(before==after,'refusal preserved catalogue/data')
        require(self.write_attempts()==start,'refused before first owner/startup DDL/DML attempt')
        require('api_test_only' not in message and self.env.DATABASE not in message,'safe refusal')
        return {'refused':True,'before':before,'after':after,'write_attempts':0,**classified}

    async def populate(self):
        from app.models import Company,CompanyRole,PulseView
        async with self.db.async_session_factory.begin() as db:
            db.add(Company(id=COMPANY,name='Synthetic fixture',slug='c4-fixture',profile_id='energy'));await db.flush()
            db.add(CompanyRole(id=ROLE,company_id=COMPANY,name='Synthetic role'))
            db.add(PulseView(id=VIEW,company_id=COMPANY,name='Synthetic view'));await db.flush()
        return {'company':str(COMPANY),'role':str(ROLE),'view':str(VIEW)}

    async def close(self):
        if self.closed:return
        self.closed=True
        await asyncio.sleep(0)
        for engine in self.engines:await engine.dispose()
        for conn in self.raw:
            if not conn.is_closed():await conn.close(timeout=2)
        self.event.remove(self.Engine,'before_cursor_execute',self.listener);self.env_stack.close()

    def save_trace(self,case):
        raw=json.dumps({'case':case,'queries':self.trace},indent=2).encode()
        require(len(raw)<=16*1024*1024,'per-case trace output cap')
        (self.env.ROOTS['evidence']/(case+'-'+str(self.env.os.getpid())+'.queries.json')).write_bytes(raw)


async def baseline_case(ctx,case):
    """Runs only in immutable e6abf86b archive process, never candidate code."""
    await ctx.reset()
    if case in ('CUR-empty-core-off','CUR-empty-core-on'):
        ctx.settings.managed_core_budget_enabled=case.endswith('-on')
        result=await ctx.reject(lambda:ctx.prepare(managed=ctx.settings.managed_core_budget_enabled),oracle=oracle_key(case))
        require(not ctx.env.SINKS,'no jobs on refusal');return result
    if case=='CUR-public-off':
        await ctx.close();ctx=await Context(ctx.env).setup('public')
        await ctx.prepare();await ctx.prepare();r=await ctx.ready();require(r['status']=='ready','native legacy public ready')
        result={'native_public_full_prepare_repeat':True,'readiness':r};await ctx.close();return result
    if case=='CUR-marker-core-off':
        await ctx.admin.execute('CREATE TABLE core.app_startup_runs(instance_id text PRIMARY KEY,completed_at timestamptz NOT NULL DEFAULT now())')
        await ctx.admin.execute("INSERT INTO core.app_startup_runs(instance_id) VALUES('core-bootstrap-sequence-test')")
        await ctx.prepare(lifespan=True,prod=True)
        require(set(ctx.env.SINKS)==set((*ctx.env.JOBS,'app.services.chat_ws','chat.stop')),'baseline marker allowed external sinks')
        require(await ctx.admin.fetchval("select to_regclass('core.pulse_view_role_grants')") is None,'baseline marker bypass characterized')
        return {'baseline_marker_skipped_pulse':True,'sinks':list(ctx.env.SINKS)}
    if case in ('CUR-template-distinct-grantee','CUR-template-owner-grantee'):
        grantee=ctx.env.os.environ['CORE_BOOTSTRAP_ACL_GRANTEE'] if 'distinct' in case else 'clearledger'
        require(await ctx.admin.fetchval('select exists(select 1 from pg_roles where rolname=$1)',grantee),'ROOT preexisting ACL grantee')
        await ctx.admin.execute('ALTER DEFAULT PRIVILEGES FOR ROLE clearledger IN SCHEMA core GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "'+grantee+'"')
        await ctx.admin.execute('CREATE TABLE core.c4_acl_probe(id integer PRIMARY KEY)')
        acl=await ctx.admin.fetchrow("select relacl::text AS acl,pg_get_userbyid(relowner) AS owner FROM pg_class where oid='core.c4_acl_probe'::regclass")
        require(acl['owner']=='clearledger','actual creator/owner')
        if 'distinct' in case:require(acl['acl'] is not None and grantee in acl['acl'],'distinct inherited table ACL')
        else:require(acl['acl'] is None,'redundant owner grant keeps canonical default ACL')
        return {'executor':'clearledger','for_role':'clearledger','create_role':acl['owner'],'grantee':grantee,'relacl':acl['acl'],'scope':'native PG default-ACL mechanism; not fullbootstrap PASS'}
    raise AssertionError('unknown baseline ID')


async def archive_child(env,pin,case):
    ctx=await Context(env).setup()
    try:
        actual=Path(ctx.main.__file__).resolve();expected=Path(env.os.environ['CORE_BOOTSTRAP_ARCHIVES'])/pin/'clearledger/server/app/main.py'
        require(actual==expected,'real immutable archived app.main')
        if pin==env.ARCHIVE_PINS[0]:return await baseline_case(ctx,case)
        from app.models import Company,User,UserCompany,CalendarEvent
        from sqlalchemy import select
        if case in ('old-bootstrap','old-bootstrap-repeat'):
            if case=='old-bootstrap':await ctx.reset()
            await ctx.prepare(lifespan=True);await ctx.prepare(lifespan=True)
            require((await ctx.ready())['status']=='ready','real archived full bootstrap/readiness')
            require(set(ctx.env.SINKS)==set((*ctx.env.JOBS,'app.services.chat_ws','chat.stop')),'old native entry reached only terminal job sinks')
            return {'old_native_full_lifespan_bootstrap_repeat':True,'snapshot':await ctx.state(),'reset':case=='old-bootstrap'}
        async with ctx.db.async_session_factory.begin() as db:
            company=(await db.execute(select(Company).where(Company.slug=='core-bootstrap'))).scalar_one()
            email='c4-old-'+pin[:8]+'@example.invalid'
            user=(await db.execute(select(User).where(User.email==email))).scalar_one_or_none()
            if user is None:
                user=User(email=email,password_hash='synthetic-no-login',name='Synthetic old user',company_id=company.id,role='user',is_superadmin=False)
                db.add(user);await db.flush();db.add(UserCompany(user_id=user.id,company_id=company.id,role='admin'));await db.flush()
            if case=='old-business-seed':
                ev=CalendarEvent(company_id=company.id,organizer_id=user.id,title='Synthetic old migration witness',starts_at=STAMP,ends_at=STAMP+timedelta(hours=1),all_day=False,tz='UTC',visibility='company',status='planned')
                db.add(ev);await db.flush();eid=ev.id
            elif case=='old-orm-http':
                company.short_name='Written by immutable old ORM'
                from app.auth import token_for
                token=token_for(user)
            elif case=='old-sender':
                from app.services import meeting_notice,ics
                ev=CalendarEvent(company_id=company.id,organizer_id=user.id,title='Synthetic old calendar sender',starts_at=STAMP,ends_at=STAMP+timedelta(hours=1),all_day=False,tz='UTC',visibility='company',status='planned')
                db.add(ev);await db.flush();eid=ev.id
                result=await meeting_notice.известить(db,ev,user,'invite')
                rendered=ics.event_ics(uid=str(eid)+'@trek',title=ev.title,starts_at=ev.starts_at,ends_at=ev.ends_at,sequence=meeting_notice._sequence())
                require('SEQUENCE:' in rendered,'real archived ICS renderer')
                require(await db.scalar(ctx.text('select protocol_sequence from core.calendar_events where id=:id'),{'id':eid})==2000000000,'old ORM gets exact legacy baseline; sender does not overwrite it')
            else:raise AssertionError('old mode')
        if case=='old-business-seed':return {'company':str(company.id),'user':str(user.id),'event':str(eid),'old_native_ORM':True}
        if case=='old-orm-http':
            from httpx import ASGITransport,AsyncClient
            async with AsyncClient(transport=ASGITransport(app=ctx.main.app),base_url='http://synthetic',headers={'Authorization':'Bearer '+token}) as client:
                response=await client.get('/api/auth/me');require(response.status_code==200 and response.json()['email']=='c4-old-'+pin[:8]+'@example.invalid','old native HTTP/ORM coexistence')
            return {'old_ORM_write_and_native_HTTP':True,'archive':pin,'main_path':str(actual)}
        return {'old_sender':result,'event':str(eid),'persisted_counter':2000000000,'ICS_sha256':hashlib.sha256(rendered.encode()).hexdigest(),'archive':pin}
    finally:
        ctx.save_trace(case+'-'+pin[:8]);await ctx.close()


async def candidate_case(ctx,case):
    from schema_migrations import runner,manifest
    from app.services import schema_version_gate as gate
    from sqlalchemy import text
    if case.startswith('OLDUP-'):
        pin=ctx.env.ARCHIVE_PINS[2] if case=='OLDUP-5ce-native-upgrade' else ctx.env.ARCHIVE_PINS[1]
        original=await ctx.env.child(pin,'old-bootstrap')
        witness=await ctx.env.child(pin,'old-business-seed')
        before=await ctx.business(pin)
        if case=='OLDUP-wrong-parent-column':
            await ctx.admin.execute('ALTER TABLE core.companies ALTER COLUMN name TYPE varchar(254)');return await ctx.reject(lambda:ctx.upgrade_old(pin),oracle=oracle_key(case))
        if case=='OLDUP-wrong-parent-ACL':
            grantee=ctx.env.os.environ['CORE_BOOTSTRAP_ACL_GRANTEE'];await ctx.admin.execute('GRANT SELECT ON core.companies TO "'+grantee+'"');return await ctx.reject(lambda:ctx.upgrade_old(pin),oracle=oracle_key(case))
        if case=='OLDUP-one-partner-present':
            source=runner._partner_source();section=source.contract['literal_sections'][0]
            raw=(ctx.env.SERVER/'schema_migrations/bootstrap/core_prerequisites_v1.sql').read_bytes()
            await ctx.admin.execute(raw[section['start_byte']:section['end_byte']].decode());return await ctx.reject(lambda:ctx.upgrade_old(pin),oracle=oracle_key(case))
        if case=='OLDUP-wrong-profile-source':
            count=ctx.env.COUNTERS['pg_connect'];result=await ctx.reject(lambda:ctx.upgrade_old('0'*40),oracle=oracle_key(case));require(count==ctx.env.COUNTERS['pg_connect'],'unknown predecessor refused offline');return result
        receipt=await ctx.upgrade_old(pin)
        require(receipt['partner_prerequisites_created'] and [r['action'] for r in receipt['actions']]==['created']*3,'real old8 plus exactly2 parents/managed1..3 created')
        if case=='OLDUP-managed-history-present':
            await ctx.admin.execute('DELETE FROM core.core_schema_versions WHERE ordinal>=2');return await ctx.reject(lambda:ctx.upgrade_old(pin),oracle=oracle_key(case))
        after_owner=await ctx.business(pin);event=after_owner['event'].copy();counter=event.pop('protocol_sequence')
        require(counter==2000000000 and event==before['event'] and after_owner['user']==before['user'] and after_owner['company']==before['company'],'atomic old business parity plus only managed calendar addition')
        await ctx.prepare(lifespan=True,managed=True);require((await ctx.ready())['status']=='ready','full native current startup/readiness after true old upgrade')
        after=await ctx.business(pin);calendar=after['event'].copy();calendar.pop('protocol_sequence')
        require(calendar==before['event'] and after['company']==before['company'] and after['user']==before['user'],'full preparation preserves real old business witnesses')
        if case=='OLDUP-repeat-no-DDL':
            snap=await ctx.state();start=ctx.write_attempts();repeat=await ctx.upgrade_old(pin)
            require(not repeat['partner_prerequisites_created'] and repeat['actions']==[] and start==ctx.write_attempts() and snap==await ctx.state(),'repeat named full profile, no fresh/partner/managed DDL')
            return {'first':receipt,'repeat':repeat,'old_full_bootstrap':original,'old_ORM':witness}
        return {'old_full_bootstrap':original,'old_ORM':witness,'owner':receipt,'business_before':before,'business_after':after,'native_current_ready':True}
    if case.startswith('FRESH-'):
        if case=='FRESH-nonempty-refuse':
            await ctx.admin.execute('CREATE TABLE core.foreign_owned_sentinel(id integer PRIMARY KEY)');return await ctx.reject(lambda:ctx.owned(),oracle=oracle_key(case))
        if case=='FRESH-missing-edge-extension':
            await ctx.admin.execute('DROP SCHEMA edge');return await ctx.reject(lambda:ctx.owned(),oracle=oracle_key(case))
        if case=='FRESH-artifact-rollback':
            source,_=runner._bootstrap_source();ctx.artifact_sql=source.sql
            task=asyncio.create_task(ctx.owned())
            try:
                await asyncio.wait_for(ctx.artifact_reached.wait(),20)
                require(not task.done(),'cancel after actual prerequisite DDL, before transaction commit')
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
            finally:
                if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
            ctx.artifact_sql=None;ctx.phase='fixture'
            require(not await ctx.admin.fetchval("select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='core')"),'all prerequisite/managed DDL rolled back')
            require(not await ctx.admin.fetchval("select exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='core')"),'phone function rolled back too')
            return {'cancel_after_real_artifact_observed':True,'atomic_rollback':True,'retry':await ctx.owned()}
        receipt=await ctx.owned();require([r['action'] for r in receipt['actions']]==['created']*3,'fresh sole existing0002 creator')
        if case=='FRESH-repeat':
            await ctx.prepare(lifespan=True);before=await ctx.state();repeat=await ctx.owned();require(repeat['actions']==[],'repeat no fresh SQL');require(before==await ctx.state(),'owner repeat invariance');await ctx.prepare();require((await ctx.ready())['status']=='ready','repeat full prepare ready')
            return {'first':receipt,'repeat':repeat}
        if case=='FRESH-canonical-parent-contract':
            require(receipt['profile_after']=='core_prerequisites_v1.fresh_exact','exact full10 fresh profile');return receipt
        await ctx.prepare(lifespan=True,managed=True);ready=await ctx.ready();require(ready['status']=='ready','full native fresh Core')
        return {'owner':receipt,'native_prepare':True,'ready':ready}
    if case.startswith('UPG-'):
        counts={'UPG-unversioned-adopt':0,'UPG-prefix1':1,'UPG-prefix2':2,'UPG-prefix3':3,'UPG-pulse-created':2,'UPG-pulse-adopted':2,'UPG-head-repeat':3,'UPG-calendar-cutover':1,'UPG-foreign-parent':1}
        count=counts[case];await ctx.prefix(count,managed_counter=case=='UPG-unversioned-adopt')
        if case=='UPG-foreign-parent':
            await ctx.admin.execute('ALTER TABLE core.partner_installations ALTER COLUMN client_id TYPE varchar(65)');return await ctx.reject(lambda:ctx.owned(False),oracle=oracle_key(case))
        if case in ('UPG-unversioned-adopt','UPG-pulse-adopted'):
            if count==0:await ctx.admin.execute(manifest.load().sql)
            await ctx.admin.execute(manifest.load(revision=manifest.PULSE_ID).sql)
            await ctx.populate();await ctx.admin.execute('INSERT INTO core.pulse_view_role_grants(view_id,role_id) VALUES($1,$2)',VIEW,ROLE)
        before=await ctx.state();receipt=await ctx.owned(False)
        if case=='UPG-pulse-adopted':require(receipt['actions'][-1]['action']=='adopted','populated canonical adopted0003')
        if case=='UPG-pulse-created':require(receipt['actions'][-1]['action']=='created','explicit0003created')
        if count==3:require(receipt['actions']==[] and before==await ctx.state(),'head verification only')
        if case=='UPG-head-repeat':await ctx.reject(lambda:runner.execute(ctx.config,'check'),oracle=oracle_key(case))
        await ctx.prepare(lifespan=True,managed=True);require((await ctx.ready())['status']=='ready','upgrade full native prepare')
        if case in ('UPG-unversioned-adopt','UPG-pulse-adopted'):require(await ctx.admin.fetchval('SELECT count(*) FROM core.pulse_view_role_grants WHERE view_id=$1 AND role_id=$2',VIEW,ROLE)==1,'association preserved')
        return {'owner':receipt,'full_prepare':True}
    if case.startswith('REF-'):
        if case=='REF-default-acl':
            grantee=ctx.env.os.environ['CORE_BOOTSTRAP_ACL_GRANTEE'];await ctx.admin.execute('ALTER DEFAULT PRIVILEGES FOR ROLE clearledger IN SCHEMA core GRANT SELECT ON TABLES TO "'+grantee+'"');return await ctx.reject(lambda:ctx.owned(),oracle=oracle_key(case))
        if case=='REF-source-drift':return await source_negative(ctx)
        if case=='REF-missing-core-public-decoy':
            await ctx.admin.execute('DROP SCHEMA core');await ctx.admin.execute('CREATE TABLE public.users(id uuid PRIMARY KEY)')
            await ctx.engine.dispose();await change_path(ctx,'core, public');return await ctx.reject(lambda:ctx.prepare(),oracle=oracle_key(case))
        await ctx.owned()
        if case=='REF-visible-public':
            await ctx.admin.execute('CREATE TABLE public.doc_cards(id uuid PRIMARY KEY)');await ctx.engine.dispose();await change_path(ctx,'core, public');return await ctx.reject(lambda:ctx.prepare(),oracle=oracle_key(case))
        await ctx.populate();await ctx.admin.execute('INSERT INTO core.pulse_view_role_grants(view_id,role_id) VALUES($1,$2)',VIEW,ROLE)
        if case in ('REF-unknown-future','REF-gap-checksum','REF-owner-actor-action'):
            from schema_migrations import journal
            original=[dict(row) for row in await ctx.admin.fetch('SELECT revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format FROM core.core_schema_versions ORDER BY ordinal')]
            variants=HISTORY_VARIANTS[case];results=[]
            for label in variants:
                if label=='owner':
                    grantee=ctx.env.os.environ['CORE_BOOTSTRAP_ACL_GRANTEE']
                    await ctx.admin.execute('ALTER TABLE core.partner_installations OWNER TO "'+grantee+'"')
                    result=await ctx.reject(lambda:ctx.owned(False),oracle=oracle_key(case,label));result['variant']=label;results.append(result)
                    await ctx.admin.execute('ALTER TABLE core.partner_installations OWNER TO clearledger')
                    continue
                if label=='action-SQLcheck-and-pure':
                    try:await ctx.admin.execute("UPDATE core.core_schema_versions SET action='unrecognized' WHERE ordinal=3")
                    except ctx.asyncpg.CheckViolationError as actual:
                        require(type(actual) is ctx.asyncpg.CheckViolationError and actual.sqlstate=='23514' and actual.constraint_name=='ck_core_schema_action' and actual.schema_name=='core' and actual.table_name=='core_schema_versions','exact native action CHECK refusal')
                        sql_refusal={'actual_type':type(actual).__module__+'.'+type(actual).__qualname__,'actual_sqlstate':actual.sqlstate,'actual_constraint':actual.constraint_name}
                    else:raise AssertionError('journal CHECK must reject invalid action')
                    bad=[dict(row) for row in original];bad[2]['action']='unrecognized'
                    try:journal.validate_history(bad,manifest.load_known_head(),'clearledger')
                    except __import__('schema_migrations.errors',fromlist=['MigrationError']).MigrationError as actual:
                        pure_refusal=classify_refusal(ctx.env,actual,'M_HISTORY')
                        if pure_refusal is None:raise
                    else:raise AssertionError('pure invalid action accepted')
                    results.append({'variant':label,'SQL_CHECK_refused':True,'pure_validator_refused':True,'persisted_bad_row':False,'sql_refusal':sql_refusal,'pure_refusal':pure_refusal});continue
                if label in ('unknown','future','extra-over-bound'):
                    if label=='unknown':await ctx.admin.execute("UPDATE core.core_schema_versions SET revision='0003_unknown' WHERE ordinal=3")
                    else:await ctx.admin.execute("INSERT INTO core.core_schema_versions(revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format) SELECT '0004_future',4,revision,artifact_sha256,contract_sha256,artifact_sha256,action,applied_by,app_commit,runner_format FROM core.core_schema_versions WHERE ordinal=3")
                    if label=='extra-over-bound':await ctx.admin.execute("INSERT INTO core.core_schema_versions(revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format) SELECT '0005_future',5,revision,artifact_sha256,contract_sha256,artifact_sha256,action,applied_by,app_commit,runner_format FROM core.core_schema_versions WHERE ordinal=4")
                elif label=='gap':await ctx.admin.execute('DELETE FROM core.core_schema_versions WHERE ordinal=2')
                else:
                    value={'ordinal':7,'parent_revision':'0000_unknown','artifact_sha256':'0'*64,'contract_sha256':'0'*64,'predecessor_sha256':'0'*64,'runner_format':2,'app_commit':'0'*40,'applied_by':'foreign_actor'}[label]
                    await ctx.admin.execute('UPDATE core.core_schema_versions SET '+label+'=$1 WHERE ordinal=3',value)
                result=await ctx.reject(lambda:ctx.owned(False),oracle=oracle_key(case,label));result['variant']=label;results.append(result)
                # Restore the exact immutable rows using the ordinary owner fixture,
                # not a verifier bypass or acceptance of the tampered history.
                await ctx.admin.execute('DELETE FROM core.core_schema_versions')
                for row in original:
                    await ctx.admin.execute('INSERT INTO core.core_schema_versions(revision,ordinal,parent_revision,artifact_sha256,contract_sha256,predecessor_sha256,action,applied_by,app_commit,runner_format) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)',*[row[key] for key in ('revision','ordinal','parent_revision','artifact_sha256','contract_sha256','predecessor_sha256','action','applied_by','app_commit','runner_format')])
            return {'variants':results,'variant_count':len(results),'preserved_rows':await ctx.state()}
        if case=='REF-catalogue':await ctx.admin.execute('ALTER TABLE core.product_api_budgets ALTER COLUMN request_limit DROP NOT NULL');return await ctx.reject(lambda:ctx.owned(False),oracle=oracle_key(case))
        if case=='REF-wrong-marker':
            await ctx.prepare(prod=True);await ctx.admin.execute('DROP TABLE core.pulse_view_role_grants');return await ctx.reject(lambda:ctx.prepare(lifespan=True,prod=True),oracle=oracle_key(case))
        raise AssertionError('REF selector')
    if case.startswith('CFG-'):
        if case=='CFG-off':
            before=ctx.env.COUNTERS['pg_connect'];require(await gate.require_engine(None,SimpleNamespace(managed_core_budget_enabled=False)) is None,'OFF noengine');require(ctx.env.COUNTERS['pg_connect']==before,'OFF no IO');return {'off':True}
        if case in ('CFG-url-options','CFG-identity','CFG-source-before-lock'):
            values=dict(database_url=ctx.env.BASE_URL,managed_core_budget_enabled=True,managed_core_budget_expected_database=ctx.env.DATABASE,managed_core_budget_expected_user='clearledger')
            if case=='CFG-url-options':values['database_url']+='?ssl=false'
            else:values['managed_core_budget_expected_database']='wrong_expected'
            if case=='CFG-source-before-lock':
                old=ctx.settings.managed_core_budget_expected_database;ctx.settings.managed_core_budget_expected_database='wrong_expected';ctx.settings.managed_core_budget_enabled=True
                count=ctx.env.COUNTERS['pg_connect']
                try:
                    try:ctx.db.preflight_startup_sources()
                    except BaseException as actual:
                        refusal=classify_refusal(ctx.env,actual,'GATE_PREFLIGHT_CONFIG_TARGET')
                        if refusal is None:raise
                    else:raise AssertionError('offline config accepted')
                    require(ctx.env.COUNTERS['pg_connect']==count,'full startup offline preflight before checkout')
                finally:ctx.settings.managed_core_budget_expected_database=old;ctx.settings.managed_core_budget_enabled=False
                return {'before_socket':True,**refusal}
            count=ctx.env.COUNTERS['pg_connect'];result=await ctx.reject(lambda:gate.require_engine(ctx.engine,SimpleNamespace(**values)),oracle=oracle_key(case));require(ctx.env.COUNTERS['pg_connect']==count,'offline no checkout');return result
        if case=='CFG-no-port':
            values=SimpleNamespace(database_url=ctx.env.BASE_URL.replace(':33547',''),managed_core_budget_enabled=True,managed_core_budget_expected_database=ctx.env.DATABASE,managed_core_budget_expected_user='clearledger');cfg=gate._config(values);require(':5432/' in cfg.dsn,'offline default port normalization');return {'offline_only_no_5432_connect':True}
        if case=='CFG-real-path':
            await ctx.owned();await change_path(ctx,'public');ctx.settings.managed_core_budget_enabled=True;return await ctx.reject(lambda:ctx.prepare(managed=True),oracle=oracle_key(case))
        raise AssertionError('CFG selector')
    if case.startswith('TX-'):
        if case=='TX-readonly':require(bool(READONLY_LIBRARY_SOURCE_BINDINGS),'TX-readonly is unadmitted until ROOT pinned77 library-source bindings are supplied')
        await ctx.owned()
        if case=='TX-owner-contention':
            blocker=await ctx.asyncpg.connect(ctx.env.RAW_URL,server_settings={'search_path':'core'})
            try:await blocker.execute('SELECT pg_advisory_lock(434532,1)');return await ctx.reject(lambda:ctx.owned(False),oracle=oracle_key(case))
            finally:await blocker.close()
        ctx.settings.managed_core_budget_enabled=True
        async with ctx.engine.connect() as connection:
            if case=='TX-readonly':connection=await connection.execution_options(isolation_level='REPEATABLE READ',postgresql_readonly=True)
            trans=await connection.begin()
            try:
                before=(await connection.execute(text("select current_setting('transaction_isolation'),current_setting('transaction_read_only'),current_setting('search_path')"))).one();counter=ctx.env.COUNTERS['pg_connect'];ctx.phase='tested'
                await gate.require_connection(connection,ctx.settings)
                after=(await connection.execute(text("select current_setting('transaction_isolation'),current_setting('transaction_read_only'),current_setting('search_path')"))).one();require(before==after and connection.in_transaction() and counter==ctx.env.COUNTERS['pg_connect'],'borrowed lifecycle/options/socket invariant')
                if case=='TX-readwrite':await connection.execute(text("INSERT INTO core.companies(id,name,slug,profile_id) VALUES(:id,'Synthetic sentinel','tx-sentinel','energy')"),{'id':COMPANY})
                else:
                    try:await connection.execute(text("INSERT INTO core.companies(id,name,slug,profile_id) VALUES(:id,'Synthetic sentinel','tx-sentinel','energy')"),{'id':COMPANY})
                    except BaseException as actual:
                        refusal=classify_readonly(ctx.env,actual)
                        if refusal is None:raise
                    else:raise AssertionError('readonly DML succeeded')
            finally:await trans.rollback();ctx.phase='fixture'
        require(await ctx.admin.fetchval("select count(*) from core.companies where slug='tx-sentinel'")==0,'caller rollback');return {'actual_transaction':list(before),'no_extra_connection':True,'rollback':True,**(refusal if case=='TX-readonly' else {})}
    if case.startswith('LIFE-'):
        if case=='LIFE-rejected-no-seed':return await ctx.reject(lambda:ctx.prepare(lifespan=True),oracle=oracle_key(case))
        await ctx.owned()
        if case=='LIFE-marker-repeat':
            await ctx.prepare(prod=True);before=await ctx.state();await ctx.prepare(prod=True);require(before==await ctx.state(),'native completed marker repeat');return {'marker_rows':await ctx.admin.fetchval('select count(*) from core.app_startup_runs')}
        await ctx.prepare(lifespan=case in ('LIFE-no-jobs','LIFE-full-prepare'))
        if case in ('LIFE-no-jobs','LIFE-full-prepare'):require(set(ctx.env.SINKS)==set((*ctx.env.JOBS,'app.services.chat_ws','chat.stop')),'full lifespan reached only9terminal sinks')
        if case=='LIFE-cleanup':
            await ctx.engine.dispose();require(await ctx.admin.fetchval("select count(*) from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and pid=ANY($1::int[])",ctx.pids)==0,'all owned pool clients disposed');return {'clients_other_than_control':0}
        ready=await ctx.ready();require(ready['status']=='ready','native readiness real catalogue/storage')
        if case=='LIFE-readiness':
            await ctx.admin.execute('DROP TABLE core.pulse_view_role_grants')
            try:await ctx.ready()
            except BaseException as actual:
                refusal=classify_refusal(ctx.env,actual,'READY_PULSE_CHILD')
                if refusal is None:raise
            else:raise AssertionError('missing Pulse ready200')
        return {'native_prepare':True,'readiness':ready,'sinks':list(ctx.env.SINKS),'storage_probe':'actual private file create/delete; prod mount200 not claimed'}
    if case=='REC-old-binaries':
        results=[]
        for pin in ctx.env.ARCHIVE_PINS[1:]:
            await ctx.reset();receipt=await ctx.owned();await ctx.prepare(lifespan=True,managed=True)
            old_bootstrap=await ctx.env.child(pin,'old-bootstrap-repeat')
            old_after=await ctx.env.child(pin,'old-orm-http')
            await ctx.prepare(managed=True);require((await ctx.ready())['status']=='ready','native current ready after old fullbootstrap/ORM/HTTP')
            results.append({'pin':pin,'owner':receipt,'old_bootstrap':old_bootstrap,'old_after':old_after})
        return results
    if case=='REC-old-sender-calendar':
        await ctx.owned();await ctx.prepare();return [await ctx.env.child(pin,'old-sender') for pin in ctx.env.ARCHIVE_PINS[1:]]
    if case=='REC-crash-and-downgrade':
        # Cancel while waiting on the real owner lock, then verify no lasting client/lock and repeat.
        blocker=await ctx.asyncpg.connect(ctx.env.RAW_URL,server_settings={'search_path':'core'})
        await blocker.execute('SELECT pg_advisory_lock(434532,1)');task=asyncio.create_task(ctx.owned())
        try:
            for _ in range(100):
                if await ctx.admin.fetchval("select count(*) from pg_stat_activity where datname=current_database() and wait_event='advisory'"):break
                await asyncio.sleep(.01)
            else:raise AssertionError('real lock wait not observed')
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
            require(await ctx.admin.fetchval("select count(*) from pg_stat_activity where datname=current_database() and wait_event='advisory'")==0,'cancelled owner reaped/connection closed')
        finally:await blocker.close()
        # A second real cancellation occurs after durable-looking journal0002
        # INSERT inside the still uncommitted atomic owner transaction.
        ctx.cancel_after_ordinal=2;ctx.journal_reached.clear();migration=asyncio.create_task(ctx.owned())
        try:
            await asyncio.wait_for(ctx.journal_reached.wait(),30);require(not migration.done(),'observe ordinal2 before atomic commit')
            migration.cancel()
            try:await migration
            except asyncio.CancelledError:pass
        finally:
            if not migration.done():migration.cancel();await asyncio.gather(migration,return_exceptions=True)
            ctx.cancel_after_ordinal=None;ctx.phase='fixture'
        require(not await ctx.admin.fetchval("select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='core')"),'prerequisites and1/2 journal rows rolled back together')
        await ctx.owned();await ctx.prepare();return {'lock_wait_cancel':True,'after_journal2_cancel':True,'old_after':[await ctx.env.child(pin,'old-orm-http') for pin in ctx.env.ARCHIVE_PINS[1:]]}
    if case=='REC-synthetic-restore':return await restore_case(ctx)
    raise AssertionError('unknown case: '+case)


async def change_path(ctx,path):
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    await ctx.engine.dispose();ctx.engine=create_async_engine(ctx.env.BASE_URL,pool_size=2,max_overflow=0,connect_args={'server_settings':{'search_path':path},'timeout':5,'command_timeout':20});ctx.engines.append(ctx.engine);ctx.db.engine=ctx.engine;ctx.db.async_session_factory=async_sessionmaker(ctx.engine,expire_on_commit=False);ctx.main.async_session_factory=ctx.db.async_session_factory


async def source_negative(ctx):
    from schema_migrations import runner
    # Exercise source preflight on a separate owned copy; source tree is immutable.
    import shutil
    dest=ctx.env.ROOTS['scratch']/'tampered-source'
    shutil.copytree(ctx.env.SERVER/'schema_migrations',dest)
    p=dest/'bootstrap/core_prerequisites_v1.sql';p.write_bytes(p.read_bytes()+b'-- changed\n')
    # No mutation of the verifier or framework module globals. The literal reader's
    # own module path points at the tampered copy under an independent module name.
    spec=importlib.util.spec_from_file_location('tampered_prerequisite_reader',dest/'bootstrap/core_prerequisites.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    count=ctx.env.COUNTERS['pg_connect']
    try:module.load(runner.BOOTSTRAP_MANIFEST_SHA256)
    except __import__('schema_migrations.errors',fromlist=['MigrationError']).MigrationError as actual:
        classified=classify_refusal(ctx.env,actual,'M_SOURCE_COPY')
        if classified is None:raise
        require(ctx.env.COUNTERS['pg_connect']==count,'source integrity refusal before socket')
        return {'tampered_owned_copy_refused_before_connect':True,**classified}
    raise AssertionError('tampered artifact accepted')


async def restore_case(ctx):
    """Two explicit ROOT stages around admin DROP/recreate of THE SAME owned database.

    This helper never opens another database or fabricates a restore receipt.
    ROOT owns reviewed dump/restore tool execution and process lifecycle separately.
    """
    action=ctx.env.os.environ['CORE_BOOTSTRAP_RESTORE_ACTION']
    module=ctx.env.load_stdlib_file('immutable_restore_catalogue',ctx.env.SERVER/'tests/run_schema_restore_proof.py');proof=module.Proof()
    path=ctx.env.ROOTS['evidence']/'restore-before.json'
    if action=='prepare':
        await ctx.owned();await ctx.prepare();require((await ctx.ready())['status']=='ready','pre-dump native readiness')
        before=await proof.snapshot(ctx.admin)
        ctx.lease['status']='awaiting-root-restore';ctx.lease['continuation']='ROOT dump/ordinary DROP/recreate SAME DB/restore then verify';ctx.lease_path.write_text(json.dumps(ctx.lease,indent=2)+'\n')
        path.write_text(json.dumps({'lease_id':ctx.lease['lease_id'],'target':ctx.env.DATABASE,'database_oid':await ctx.admin.fetchval('select oid from pg_database where datname=current_database()'),'snapshot':before,'source_manifest':ctx.env.FROZEN_MANIFEST_SHA256},indent=2)+'\n')
        return {'awaiting_ROOT_actual_dump_DROP_recreate_restore':True,'case_not_passed':True,'snapshot':before}
    require(action=='verify' and path.is_file(),'ROOT restore prepare/actual administration before verify')
    before=json.loads(path.read_text());require(before['lease_id']==ctx.lease['lease_id'] and before['target']==ctx.env.DATABASE and before['source_manifest']==ctx.env.FROZEN_MANIFEST_SHA256,'same target/source restore chain')
    actual_receipt=ctx.env.ROOTS['evidence']/'root-restore-process.json';require(actual_receipt.is_file(),'independent ROOT dump/DROP/recreate/restore process receipt required')
    receipt=json.loads(actual_receipt.read_text());require(receipt['lease_id']==ctx.lease['lease_id'] and receipt['database']==ctx.env.DATABASE and receipt['other_database_connections']==0 and receipt['ordinary_drop'] and receipt['recreated_same_database'] and [r['phase'] for r in receipt['processes']]==['pg_dump','ordinary_drop_recreate','pg_restore'] and all(r['exit']==0 and r['reaped'] for r in receipt['processes']),'actual same-DB ROOT tools lifecycle')
    require(before['database_oid']!=await ctx.admin.fetchval('select oid from pg_database where datname=current_database()'),'actual DROP/recreate changed physical DB identity')
    dump=ctx.env.ROOTS['evidence']/'restore-before.dump';require(dump.is_file() and hashlib.sha256(dump.read_bytes()).hexdigest()==receipt['dump_sha256'],'actual dump archive hash')
    after=await proof.snapshot(ctx.admin);require(before['snapshot']==after,'actual restored logical catalogue/data parity')
    await ctx.prepare();require((await ctx.ready())['status']=='ready','restored native full prepare/readiness')
    return {'same_owned_database':True,'before':before['snapshot'],'after':after,'ROOT_process_receipt_sha256':hashlib.sha256(actual_receipt.read_bytes()).hexdigest()}


async def run(env,stage,records):
    require(env._ACTIVE and stage in env.CASE_GROUPS,'explicit approved stage')
    ctx=await Context(env).setup()
    try:
        if stage=='characterize_current':
            for case in env.selected_ids(stage):
                result=await env.child(env.ARCHIVE_PINS[0],case);records.append({'id':case,'outcome':'passed','detail':result,'resource_sample':await ctx.bounds(stage)})
        else:
            selected=env.selected_ids(stage)
            if stage=='recovery_candidate' and env.os.environ['CORE_BOOTSTRAP_RESTORE_ACTION']=='verify':selected=[key for key in selected if key in env.CASE_GROUPS[stage][2:]]
            for case in selected:
                ctx.current=case
                if not (case=='REC-synthetic-restore' and env.os.environ['CORE_BOOTSTRAP_RESTORE_ACTION']=='verify'):await ctx.reset()
                result=await asyncio.wait_for(candidate_case(ctx,case),180);ctx.save_trace(case)
                if isinstance(result,dict) and result.get('case_not_passed'):
                    return {'pending_ROOT_restore':case,'NOT_PASSED':True,'remaining_required':True}
                records.append({'id':case,'outcome':'passed','detail':result,'resource_sample':await ctx.bounds(stage)})
        require([r['id'] for r in records]==([key for key in env.selected_ids(stage) if key in env.CASE_GROUPS[stage][2:]] if stage=='recovery_candidate' and env.os.environ['CORE_BOOTSTRAP_RESTORE_ACTION']=='verify' else env.selected_ids(stage)),'exact stage IDs/count, no dropped failures')
        return {'stage_cases':len(records),'native_pipeline':True}
    except BaseException:
        await asyncio.sleep(0);ctx.save_trace('FAILED-'+ctx.current)
        raise
    finally:
        await ctx.close()
