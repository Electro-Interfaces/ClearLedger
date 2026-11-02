"""Один root-only synthetic dump/restore proof; до guard только stdlib.

Это прямой isolated harness, не pytest/conftest и не production restore tool.
Запускается только независимым approval wrapper после отдельного review ROOT.
"""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
import uuid

SERVER = Path(__file__).resolve().parents[1]
BASE = Path('/srv/projects/api-modernization-test-env-20261029')
EVIDENCE = BASE / 'private-schema-restore-proof-20261030'
SOURCE = 'api_schema_restore_source_test'
TARGET = 'api_schema_restore_target_test'
CONTAINER = 'api-modernization-test-20261029'
MIB = 1024 * 1024
DB_LIMIT = 128 * MIB
ARCHIVE_LIMIT = 64 * MIB
COMPANY = uuid.UUID('00000000-0000-4000-8000-000000000001')
APP = uuid.UUID('00000000-0000-4000-8000-000000000002')
INSTALL = uuid.UUID('00000000-0000-4000-8000-000000000003')
CLIENT = 'restore-proof-client'
REVISION = '0001_product_api_budgets'


class ProofRefused(RuntimeError):
    """Только фиксированный безопасный label harness, без driver detail."""


def require(condition, label):
    if not condition:
        raise ProofRefused(label)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def raw_url(name):
    require(name in (SOURCE, TARGET), 'unknown target')
    return 'postgresql://clearledger:api_test_only@127.0.0.1:33546/' + name


def app_url(name):
    return raw_url(name).replace('postgresql:', 'postgresql+asyncpg:', 1)


def guard():
    # Нельзя использовать прямой unittest/pytest loader для обхода wrapper.
    require(sys.argv[1:] == ['--execute-approved-restore-tests'], 'explicit approval argument required')
    sys.path.insert(0, str(SERVER / 'tests'))
    from schema_restore_proof_approved import verify_approval
    verify_approval(require_empty_evidence=False)


def sql_tokens(sql):
    """Узкий lexer: offsets/raw bytes сохраняются; неоднозначность оставляет весь SQL raw."""
    tokens, stack, offset = [], [], 0
    while offset < len(sql):
        start, char = offset, sql[offset]
        if char.isspace():
            offset += 1
            continue
        if sql.startswith(('--','/*'),offset) or char=='$':
            return None
        if char in "'\"":
            # E/U&/bit prefixes не входят в grammar; их escape semantics не угадываем.
            if char=="'" and offset and (sql[offset-1].isalnum() or sql[offset-1] in '_&'):
                return None
            offset += 1
            while offset < len(sql):
                if sql[offset]==char:
                    offset += 1
                    if offset<len(sql) and sql[offset]==char:
                        offset += 1
                        continue
                    break
                offset += 1
            else:
                return None
            kind = 'literal' if char=="'" else 'quoted_identifier'
            if kind=='literal' and '\\' in sql[start:offset]:
                return None  # Непроверенные backslash/escape расширения вне scope.
        elif char.isascii() and (char.isalpha() or char=='_'):
            offset += 1
            while offset<len(sql) and sql[offset].isascii() and (sql[offset].isalnum() or sql[offset]=='_'):
                offset += 1
            kind = 'word'
        elif sql.startswith('::',offset):
            offset += 2
            kind = 'cast'
        else:
            offset += 1
            kind = 'symbol'
            if char in '([':
                stack.append(char)
            elif char in ')]':
                if not stack or stack.pop()!=('(' if char==')' else '['):
                    return None
        tokens.append((kind,sql[start:offset],start,offset))
    return None if stack else tokens


def array_fragment(sql, tokens, start):
    """Только четыре PG deparse формы unbounded varchar literals → text array."""
    index = start
    outer = tokens[index][1]=='('
    if outer:
        index += 1

    def take(value):
        nonlocal index
        if index>=len(tokens) or tokens[index][1]!=value:
            raise ValueError
        index += 1

    try:
        take('ARRAY');take('[')
        literals, rendered, styles = [], [], []
        while True:
            parenthesized = tokens[index][1]=='('
            if parenthesized:
                take('(')
            token = tokens[index]
            if token[0]=='literal':
                node = ('literal',token[1])
            elif token[0]=='word' and token[1]=='NULL':
                node = ('null','NULL')
            else:
                return None
            index += 1
            take('::');take('character');take('varying')
            base = token[1]+'::character varying'
            if parenthesized:
                take(')')
                base = '('+base+')'
            distributed = index<len(tokens) and tokens[index][1]=='::'
            if distributed:
                take('::');take('text')
                base += '::text'
            literals.append(node);rendered.append(base);styles.append((parenthesized,distributed))
            if tokens[index][1]!=',':
                break
            take(',')
        take(']')
        require_same_style = len(set(styles))==1
        if not require_same_style:
            return None
        parenthesized, distributed = styles[0]
        expected = 'ARRAY['+', '.join(rendered)+']'
        if distributed:
            if outer:
                return None
        else:
            if parenthesized:
                return None
            if outer:
                take(')')
                expected = '('+expected+')'
            take('::');take('text');take('[');take(']')
            expected += '::text[]'
        # Не стираем даже произвольное форматирование вне четырёх exact templates.
        if sql[tokens[start][2]:tokens[index-1][3]]!=expected:
            return None
        return index, ('unbounded_varchar_to_text_array',tuple(literals))
    except (ValueError,IndexError):
        return None


def canonical_sql(sql):
    """Typed parts, не переписанный SQL: marker collision с raw SQL невозможен."""
    tokens = sql_tokens(sql)
    if tokens is None:
        return [('raw',sql)]
    # Сначала ВСЕ ARRAY constructors: unsupported outer запрещает поиск inner.
    # Case-insensitive здесь только обнаружение отказа, не folding представления.
    fragments = []
    for index,token in enumerate(tokens):
        if token[0]!='word' or token[1].upper()!='ARRAY':
            continue
        if token[1]!='ARRAY' or (index and tokens[index-1][1]=='.'):
            return [('raw',sql)]
        start = index
        found = array_fragment(sql,tokens,index-1) if index and tokens[index-1][1]=='(' else None
        if found is not None:
            start -= 1
        else:
            found = array_fragment(sql,tokens,index)
        if found is None:
            return [('raw',sql)]
        end,node = found
        if fragments and start<fragments[-1][1]:
            return [('raw',sql)]
        fragments.append((start,end,node))
    parts,position = [],0
    for start,end,node in fragments:
        if tokens[start][2]>position:
            parts.append(('raw',sql[position:tokens[start][2]]))
        parts.append(node)
        position = tokens[end-1][3]
    if position<len(sql) or not parts:
        parts.append(('raw',sql[position:]))
    return parts


def logical_catalog_row(category, row):
    result = list(row)
    field = 7 if category=='constraints' and row[3]=='c' else 3 if category=='indexes' else None
    if field is not None:
        parts = canonical_sql(row[field])
        if parts!=[('raw',row[field])]:
            result[field] = {'representation':'varchar_text_array_deparse_v1','parts':parts}
    return result


def pure_canonical_controls():
    """Stdlib only: static negatives + все observed immutable metadata pairs, без app/DB."""
    counts = {'positive':0,'negative':0,'raw_unknown':0,'observed_pairs':0,'catalog_rows':0,
              'observed_fragments':0,'observed_elements':0}

    def forms(values):
        plain = ', '.join(value+'::character varying' for value in values)
        element = ', '.join(value+'::character varying::text' for value in values)
        grouped = ', '.join('('+value+'::character varying)::text' for value in values)
        return ['ARRAY['+plain+']::text[]','(ARRAY['+plain+'])::text[]',
                'ARRAY['+element+']','ARRAY['+grouped+']']

    values = ["'A'","'a b'",'NULL',"'a''b'"]
    templates = forms(values)
    base = 'CHECK (status::text = ANY ('+templates[0]+'))'
    normalized = canonical_sql(base)
    for template in templates:
        require(canonical_sql('CHECK (status::text = ANY ('+template+'))')==normalized,'pure positive template failed')
        counts['positive'] += 1
    for separate_values in [['NULL',"'NULL'"],["'A''B'","'A''''B'"]]:
        separate_forms = forms(separate_values)
        for template in separate_forms:
            require(canonical_sql(template)==canonical_sql(separate_forms[0]),'pure separate NULL/quote positive failed')
            counts['positive'] += 1
    for template in templates:
        for prefix,suffix in [('CHECK (status IS NULL OR status::text <> ALL (','))'),
            ('CREATE UNIQUE INDEX ix ON core.t USING btree (id) WHERE ((status IS NOT NULL) AND status::text = ANY (','))')]:
            require(canonical_sql(prefix+template+suffix)==canonical_sql(prefix+templates[0]+suffix),'pure outer boolean positive failed')
            counts['positive'] += 1
    negative = [base.replace("'A'","'a'"),base.replace("'a b'","'a  b'"),
        base.replace("'A'","'B'"),base.replace('NULL',"'NULL'"),
        'CHECK (status::text = ANY ('+forms(list(reversed(values)))[0]+'))',
        base.replace('character varying','text'),base.replace('character varying','character varying(1)'),
        base.replace('::text[]','::pg_catalog.text[]'),base.replace('::text[]','::text[] COLLATE "C"'),
        base.replace(' = ANY ',' <> ANY '),base.replace('ANY','ALL'),
        '('+base+')',base.replace('status','other_status'),base.replace('ARRAY[','ARRAY[ ')]
    for value in negative:
        require(canonical_sql(value)!=normalized,'pure semantic mutation lost')
        counts['negative'] += 1
    null_guard = 'CHECK (status IS NULL OR status::text <> ALL ('+templates[0]+'))'
    for value in [null_guard.replace('IS NULL','IS NOT NULL'),null_guard.replace(' OR ',' AND '),
                  null_guard.replace('<> ALL','= ALL'),null_guard.replace('ALL','ANY')]:
        require(canonical_sql(value)!=canonical_sql(null_guard),'pure outer boolean mutation lost')
        counts['negative'] += 1
    require(canonical_sql(forms(["'A''B'"])[0])!=canonical_sql(forms(["'A''''B'"])[0]),'pure escaped quote mutation lost')
    require(canonical_sql(forms(['NULL'])[0])!=canonical_sql(forms(["'NULL'"])[0]),'pure separate NULL mutation lost')
    counts['negative'] += 2
    unknown = ['"ARRAY[embedded]"',"'ARRAY[embedded]'",'$$ARRAY[embedded]$$',
        "ARRAY[E'a'::character varying]::text[]", "ARRAY[U&'a'::character varying]::text[]",
        "ARRAY['a'::character varying /* comment */]::text[]", "ARRAY['a'::character varying]::text[] -- comment",
        "ARRAY['a'::character varying(1)]::text[]", "ARRAY['a'::pg_catalog.varchar]::text[]",
        "ARRAY['a'::character varying]::pg_catalog.text[]", "ARRAY['a'::character varying]::TEXT[]",
        "ARRAY['unterminated]::text[]", 'ARRAY[NULL::character varying]::text[',
        "ARRAY['a'::character varying,'b'::character varying]::text[]",
        "ARRAY['a' 'b'::character varying]::text[]", "ARRAY['a'\n'b'::character varying]::text[]",
        "ARRAY['a\\b'::character varying]::text[]"]
    for value in unknown:
        require(canonical_sql(value)==[('raw',value)],'pure unknown form changed')
        counts['raw_unknown'] += 1
    paired_unknown = []
    for spelling in ['ARRAY','array','aRrAy']:
        paired_unknown.append((spelling+'['+templates[0]+']',spelling+'['+templates[2]+']'))
        paired_unknown.append((spelling+'[NULL, '+templates[0]+']',spelling+'[NULL, '+templates[2]+']'))
    for literal in ["'a' 'b'","'a'\n'b'","'a\\b'"]:
        paired_unknown.append(('ARRAY['+literal+'::character varying]::text[]',
                               'ARRAY['+literal+'::character varying::text]'))
    # Даже независимый valid ARRAY не разрешает частично нормализовать unknown SQL.
    paired_unknown.append((templates[0]+' || ARRAY[ARRAY['+templates[0]+']]',
                           templates[2]+' || ARRAY[ARRAY['+templates[2]+']]'))
    for old,new in paired_unknown:
        require(canonical_sql(old)==[('raw',old)] and canonical_sql(new)==[('raw',new)]
                and canonical_sql(old)!=canonical_sql(new),'pure unsupported outer/paired ambiguity collapsed')
        counts['raw_unknown'] += 2
        counts['negative'] += 1
    marker = canonical(normalized)
    require(canonical_sql("'"+marker.replace("'","''")+"'")!=normalized,'typed marker collision')
    counts['negative'] += 1
    for category,row,flags in [
        ('constraints',['core','t','ck','c',True,False,False,base],[4,5,6]),
        ('indexes',['core','t','ix','CREATE INDEX ix ON core.t USING btree (id) WHERE '+base.removeprefix('CHECK '),True,True,True,False,None],[4,5,6,7]),
    ]:
        for flag in flags:
            modified = list(row);modified[flag] = not row[flag]
            require(logical_catalog_row(category,row)!=logical_catalog_row(category,modified),'pure catalog flag lost')
            counts['negative'] += 1
    directory = BASE/'private-schema-restore-proof-20261030-attempt4-cast-representation-diff'
    corpus = []
    for name,digest in [('source-before.catalog.json','c1418b2f630ff68fcf7d6fc5812aa74e27014af9e56004130dfd2ccd30f956ee'),
                        ('target-after.catalog.json','60411bb9f794e314f8510e79f5814432abf14a8484cdd66fab24e8c470c49faa')]:
        path = directory/name
        require(path.stat().st_size<=16*MIB,'pure corpus bound exceeded')
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest()==digest,'pure immutable corpus mismatch')
        corpus.append(json.loads(data))
    for category in ['constraints','indexes']:
        source = {tuple(json.loads(row)[:3]):json.loads(row) for row in corpus[0][category]}
        target = {tuple(json.loads(row)[:3]):json.loads(row) for row in corpus[1][category]}
        require(source.keys()==target.keys(),'pure corpus object identities differ')
        for key,old in source.items():
            new = target[key]
            require(logical_catalog_row(category,old)==logical_catalog_row(category,new),'pure observed metadata pair differs')
            counts['observed_pairs'] += int(old!=new)
            if old!=new:
                definition = old[7 if category=='constraints' else 3]
                for part in canonical_sql(definition):
                    if part[0]=='unbounded_varchar_to_text_array':
                        counts['observed_fragments'] += 1
                        counts['observed_elements'] += len(part[1])
            counts['catalog_rows'] += 1
    require(counts['observed_pairs']==50 and counts['catalog_rows']==2514,'pure corpus receipt mismatch')
    require(counts['observed_fragments']==53 and counts['observed_elements']==205,'pure fragment coverage mismatch')
    return {'ok':True,'format':'varchar_text_array_deparse_v1',**counts}


class Proof:
    def __init__(self):
        self.connections = {}
        self.engines = []
        self.children = set()
        self.claimed = set()
        self.steps = []
        self.child_records = []
        self.catalog_details = {}
        self.raw_catalog_hashes = {}
        self.collation_identity = None
        self.failure = None
        self.cleanup_error = None
        self.phase = 'guard'

    def record(self, name, **details):
        self.steps.append({'name': name, 'status': 'PASS', **details})

    def private_json(self, name, value, *, limit=16*MIB):
        payload = json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False).encode()+b'\n'
        require(len(payload)<=limit, 'private diagnostic artifact bound exceeded')
        with (EVIDENCE/name).open('xb') as output:
            os.fchmod(output.fileno(),0o600)
            output.write(payload)

    def comparison_diagnostics(self, before, after):
        # Только metadata rows + counts/hashes. Значения business rows не сохраняются.
        differences = {'totals':{},'catalog':{},'data':{},'raw_catalog':{}}
        for key in sorted(self.raw_catalog_hashes['source-before']):
            old,new = self.raw_catalog_hashes['source-before'][key],self.raw_catalog_hashes['target-after'][key]
            if old!=new:
                differences['raw_catalog'][key] = {'source':old,'target':new}
        for key in ['relations','rows']:
            if before[key]!=after[key]:
                differences['totals'][key] = {'source':before[key],'target':after[key]}
        for kind in ['catalog','data']:
            for key in sorted(set(before[kind])|set(after[kind])):
                old,new = before[kind].get(key),after[kind].get(key)
                if old!=new:
                    differences[kind][key] = {'source':old,'target':new}
                    if kind=='catalog':
                        source = Counter(self.catalog_details['source-before'].get(key,[]))
                        target = Counter(self.catalog_details['target-after'].get(key,[]))
                        lost,added = list((source-target).elements()),list((target-source).elements())
                        differences[kind][key].update(only_source_count=len(lost),only_target_count=len(added),
                            source_metadata_samples=[row[:65536] for row in lost[:10]],
                            target_metadata_samples=[row[:65536] for row in added[:10]])
        self.private_json('restore-diff.json',differences)

    async def command(self, args, *, archive_in=None, archive_out=None, timeout=60):
        """Только literal Docker argv; bounded streams, deadline, kill/wait в finally."""
        allowed = [
            ['docker', 'inspect', '--format', '{{json .NetworkSettings.Ports}}', CONTAINER],
            ['docker', 'exec', CONTAINER, 'df', '-P', '-B1', '/var/lib/postgresql/data'],
            ['docker', 'exec', CONTAINER, 'pg_dump', '--version'],
            ['docker', 'exec', CONTAINER, 'pg_restore', '--version'],
            ['docker', 'exec', '--env', 'PGPASSWORD', CONTAINER, 'pg_isready', '-h', '127.0.0.1', '-p', '5432', '-U', 'clearledger', '-d', SOURCE],
            ['docker', 'exec', '--env', 'PGPASSWORD', CONTAINER, 'timeout', '-s', 'TERM', '-k', '5', '5', 'psql', '-X', '-w', '-h', '127.0.0.1', '-p', '5432', '-U', 'clearledger', '-d', SOURCE, '-Atc', 'SELECT system_identifier FROM pg_control_system()'],
            ['docker', 'exec', '--env', 'PGPASSWORD', CONTAINER, 'timeout', '-s', 'TERM', '-k', '5', '60', 'pg_dump', '-w', '-h', '127.0.0.1', '-p', '5432', '-U', 'clearledger', '--format=custom', '--dbname=' + SOURCE],
            ['docker', 'exec', '--interactive', CONTAINER, 'timeout', '-s', 'TERM', '-k', '5', '20', 'pg_restore', '--list', '--format=custom'],
            ['docker', 'exec', '--interactive', '--env', 'PGPASSWORD', CONTAINER, 'timeout', '-s', 'TERM', '-k', '5', '90', 'pg_restore', '-w', '-h', '127.0.0.1', '-p', '5432', '-U', 'clearledger', '--format=custom', '--exit-on-error', '--dbname=' + TARGET],
        ]
        require(args in allowed, 'unapproved child argv')
        # Локальный daemon фиксирован; не наследуем Docker context/proxy/env клиента.
        env = {'PATH': '/usr/bin:/bin', 'HOME': os.environ['HOME'], 'LANG': 'C.UTF-8',
               'DOCKER_HOST': 'unix:///var/run/docker.sock', 'DOCKER_CONFIG': str(EVIDENCE / 'docker-config'),
               'PGPASSWORD': 'api_test_only'}
        process = await asyncio.create_subprocess_exec(*args, env=env,
            stdin=asyncio.subprocess.PIPE if archive_in else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.children.add(process)
        # Убийство Docker client само по себе не останавливает exec-процесс.
        # Внутренний timeout завершает/reap PG child; client ждёт его deadline.
        inner_deadline = None
        if 'timeout' in args:
            index = args.index('timeout')
            inner_deadline = time.monotonic() + int(args[index+5]) + 10
        chunks, errors, size = [], [], [0]
        input_early_closed = False

        async def read(stream, target, limit, file=None):
            count = 0
            while block := await stream.read(65536):
                count += len(block)
                require(count <= limit, 'child output bound exceeded')
                if file:
                    file.write(block)
                    size[0] = count
                else:
                    target.append(block)

        async def feed():
            nonlocal input_early_closed
            if archive_in:
                try:
                    with archive_in.open('rb') as source:
                        while block := source.read(65536):
                            try:
                                process.stdin.write(block)
                                await process.stdin.drain()
                            except (BrokenPipeError,ConnectionResetError):
                                # --list может завершиться после TOC без чтения payload.
                                # Exit status и оба выходных потока всё равно обязательны.
                                input_early_closed = True
                                break
                finally:
                    try:
                        process.stdin.close()
                        await process.stdin.wait_closed()
                    except (BrokenPipeError,ConnectionResetError):
                        input_early_closed = True

        output, tasks = None, []
        try:
            output = archive_out.open('xb') if archive_out else None
            if output:
                os.fchmod(output.fileno(),0o600)
            tasks = [asyncio.create_task(read(process.stdout, chunks, ARCHIVE_LIMIT if output else 2*MIB, output)),
                     asyncio.create_task(read(process.stderr, errors, MIB)), asyncio.create_task(feed()),
                     asyncio.create_task(process.wait())]
            async with asyncio.timeout(timeout):
                await asyncio.gather(*tasks)
            require(process.returncode == 0, 'child command failed')
            return b''.join(chunks).decode('utf-8')
        finally:
            if process.returncode is None:
                if inner_deadline is not None:
                    try:
                        async with asyncio.timeout(max(0.1,inner_deadline-time.monotonic())):
                            await asyncio.shield(process.wait())
                    except TimeoutError:
                        pass
                if process.returncode is None:
                    process.kill()
            await process.wait()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if output:
                output.close()
            self.child_records.append({'argv':args,'phase':self.phase,'returncode':process.returncode,
                                       'input_early_closed':input_early_closed,
                                       'stdout_bytes':size[0] if output else sum(map(len,chunks)),
                                       'stderr_bytes':sum(map(len,errors))})
            self.children.discard(process)

    async def space(self, minimum):
        result = await self.command(['docker', 'exec', CONTAINER, 'df', '-P', '-B1', '/var/lib/postgresql/data'])
        lines = result.strip().splitlines()
        require(len(lines) == 2, 'unexpected df output')
        fields = lines[1].split()
        total, used, free = map(int, fields[1:4])
        require(total == 1024*MIB and free >= minimum, 'PGDATA space bound failed')
        self.steps.append({'name': 'space', 'status': 'PASS', 'total_bytes': total,
                           'used_bytes': used, 'free_bytes': free, 'minimum_bytes': minimum})

    async def connect(self, name):
        connection = await self.asyncpg.connect(raw_url(name), timeout=5, command_timeout=30,
            server_settings={'search_path': 'pg_catalog', 'statement_timeout': '30000',
                             'lock_timeout': '1000', 'application_name': 'synthetic-restore-proof'})
        self.connections[name] = connection
        return connection

    async def close_connections(self):
        for connection in self.connections.values():
            await connection.close(timeout=5)
        self.connections.clear()

    async def dispose(self):
        for engine in self.engines:
            await engine.dispose()
        self.engines.clear()

    async def relations(self, connection):
        return [dict(row) for row in await connection.fetch("""SELECT n.nspname AS schema,c.relname AS name,c.relkind::text AS kind,
            pg_get_userbyid(c.relowner) AS owner FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
              AND n.nspname NOT LIKE 'pg_temp%' AND c.relkind IN ('r','p','v','m','S','f') ORDER BY 1,2""")]

    async def identity(self, name, *, empty=False):
        conn = self.connections[name]
        row = dict(await conn.fetchrow("""SELECT current_database() AS db,current_user AS usr,
            current_setting('server_version_num')::int AS version,current_setting('max_locks_per_transaction')::int AS maxlocks,
            current_setting('data_directory') AS directory,pg_database_size(current_database()) AS bytes,
            (SELECT datdba=(SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_database WHERE datname=current_database()) AS owns,
            (SELECT system_identifier::text FROM pg_control_system()) AS cluster,
            (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND backend_type='client backend' AND pid<>pg_backend_pid()) AS others"""))
        require(row['db'] == name and row['usr'] == 'clearledger' and row['version'] == 160015
                and row['maxlocks'] == 64 and row['directory'] == '/var/lib/postgresql/data'
                and row['owns'] and row['bytes'] <= DB_LIMIT and row['others'] == 0, 'database preflight failed')
        if empty:
            require(await self.relations(conn) == [], 'fresh DB must have no user relations')
            schemas = await conn.fetch("SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public','information_schema','pg_catalog') AND nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_temp%'")
            require(not schemas, 'fresh DB has unexpected namespace')
            require(await conn.fetchval("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'")==0
                    and await conn.fetchval("SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'")==0
                    and await conn.fetchval("SELECT count(*) FROM pg_extension WHERE extname<>'plpgsql'")==0,
                    'fresh DB has unexpected function/type/extension')
        return row

    async def native_cast_controls(self, conn):
        # ROOT-only readonly prerequisites для узкого test-only semantic representation.
        async with conn.transaction(isolation='repeatable_read',readonly=True):
            name = await conn.fetchval('SELECT current_database()')
            require(name in {SOURCE,TARGET},'native control database refused')
            types = [tuple(row) for row in await conn.fetch("""SELECT t.oid::int,n.nspname,t.typname
                FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                WHERE t.oid IN (16,25,1043) ORDER BY t.oid""")]
            require(types==[(16,'pg_catalog','bool'),(25,'pg_catalog','text'),(1043,'pg_catalog','varchar')],
                    'native builtin type identity failed')
            cast = await conn.fetchrow("""SELECT castmethod::text,castcontext::text,castfunc::int FROM pg_cast
                WHERE castsource=1043 AND casttarget=25""")
            require(cast is not None and tuple(cast)==('b','i',0)
                    and await conn.fetchval("SELECT current_setting('standard_conforming_strings')")=='on',
                    'native builtin varchar to text prerequisite failed')
            operators = [tuple(row) for row in await conn.fetch("""SELECT o.oprname,n.nspname,
                o.oprleft::int,o.oprright::int,o.oprresult::int,pn.nspname,p.proname,p.proisstrict,
                p.proretset,p.prokind::text,p.prorettype::int,l.lanname,p.provolatile::text,p.proargtypes::text,
                o.oid::int,o.oprnegate::int,o.oprcom::int
                FROM pg_operator o JOIN pg_namespace n ON n.oid=o.oprnamespace
                JOIN pg_proc p ON p.oid=o.oprcode JOIN pg_namespace pn ON pn.oid=p.pronamespace
                JOIN pg_language l ON l.oid=p.prolang
                WHERE n.nspname='pg_catalog' AND o.oprname IN ('=','<>')
                  AND o.oprleft=25 AND o.oprright=25 ORDER BY o.oprname""")]
            opmap = {row[0]:row for row in operators}
            require(len(operators)==2 and opmap.keys()=={'=','<>'},'native text operator set failed')
            for symbol,function in [('=','texteq'),('<>','textne')]:
                value = opmap[symbol]
                require(value[:14]==(symbol,'pg_catalog',25,25,16,'pg_catalog',function,True,False,'f',16,'internal','i','25 25')
                        and value[16]==value[14] and value[15]==opmap['<>' if symbol=='=' else '='][14],
                        'native text operator identity or strictness failed')
            collation = tuple(await conn.fetchrow("""SELECT d.datlocprovider::text,d.datcollate,d.datctype,
                d.daticulocale,d.datcollversion,pg_database_collation_actual_version(d.oid),
                c.collname,n.nspname,c.collprovider::text,c.collisdeterministic,c.collencoding
                FROM pg_database d JOIN pg_collation c ON c.collname='default'
                JOIN pg_namespace n ON n.oid=c.collnamespace
                WHERE d.datname=current_database() AND n.nspname='pg_catalog'"""))
            require(collation[6:]==('default','pg_catalog','d',True,-1) and collation[4]==collation[5],
                    'native effective database collation prerequisite failed')
            if self.collation_identity is None:
                require(name==SOURCE,'source collation baseline missing')
                self.collation_identity = collation
            else:
                require(collation==self.collation_identity,'restored effective collation differs')
            row = await conn.fetchrow("""WITH arrays AS (SELECT
                ARRAY['A'::character varying, 'a b'::character varying, NULL::character varying]::text[] AS a,
                ARRAY['A'::character varying::text, 'a b'::character varying::text, NULL::character varying::text] AS b,
                ARRAY['A'::character varying, 'a b'::character varying]::text[] AS c,
                ARRAY['A'::character varying::text, 'a b'::character varying::text] AS d,
                ARRAY['A'::character varying, 'A'::character varying]::text[] AS e,
                ARRAY['A'::character varying::text, 'A'::character varying::text] AS f,
                ARRAY['A'::character varying, NULL::character varying]::text[] AS g,
                ARRAY['A'::character varying::text, NULL::character varying::text] AS h)
                SELECT a IS NOT DISTINCT FROM b, c IS NOT DISTINCT FROM d,
                    e IS NOT DISTINCT FROM f, g IS NOT DISTINCT FROM h,
                    a IS DISTINCT FROM ARRAY[NULL::text, 'a b'::text, 'A'::text],
                    ARRAY['A'=ANY(a),'missing'=ANY(c),'missing'=ANY(a),'A'=ALL(e),'A'=ALL(a),'A'=ALL(g)],
                    ARRAY['A'=ANY(b),'missing'=ANY(d),'missing'=ANY(b),'A'=ALL(f),'A'=ALL(b),'A'=ALL(h)],
                    ARRAY['missing'<>ALL(c),'A'<>ALL(a),'missing'<>ALL(a)],
                    ARRAY['missing'<>ALL(d),'A'<>ALL(b),'missing'<>ALL(b)]
                FROM arrays""")
            require(list(row[:5])==[True]*5 and row[5]==row[6]==[True,False,None,True,False,None]
                    and row[7]==row[8]==[True,False,None],
                    'native array cast or ANY ALL NULL truth control failed')
            boolean = await conn.fetchrow("""WITH arrays AS (SELECT
                ARRAY['A'::character varying,'a b'::character varying,NULL::character varying]::text[] a,
                ARRAY['A'::character varying::text,'a b'::character varying::text,NULL::character varying::text] b),
                inputs(position,value) AS (VALUES (1,NULL::text),(2,'A'::text),(3,'missing'::text),(4,'a b'::text))
                SELECT array_agg(value<>ALL(a) ORDER BY position),array_agg(value<>ALL(b) ORDER BY position),
                    array_agg((value IS NULL OR value<>ALL(a)) ORDER BY position),
                    array_agg((value IS NULL OR value<>ALL(b)) ORDER BY position),
                    array_agg((value IS NOT NULL AND value<>ALL(a)) ORDER BY position),
                    array_agg((value IS NOT NULL AND value<>ALL(b)) ORDER BY position)
                FROM inputs CROSS JOIN arrays""")
            require(boolean[0]==boolean[1]==[None,False,None,False]
                    and boolean[2]==boolean[3]==[True,False,None,False]
                    and boolean[4]==boolean[5]==[False,False,None,False],
                    'native direct inequality ALL nullable boolean controls failed')
        self.private_json(name+'.native-prerequisites.json',{'types':types,'cast':list(cast),
            'operators':operators,'effective_collation':collation,'truth':list(row),'boolean':list(boolean)},limit=MIB)
        self.record('native_builtin_varchar_text_cast_and_array_truth_controls',
                    database=name,source_oid=1043,target_oid=25,method='b',context='i',castfunc=0,
                    truth_cases=9,nullable_boolean_cases=12,order_negative=True,collation_sha256=sha(collation))

    async def bind(self, name):
        await self.dispose()
        self.settings.database_url = app_url(name)
        self.settings.managed_core_budget_expected_database = name
        self.settings.managed_core_budget_expected_user = 'clearledger'
        engine = self.create_engine(app_url(name), pool_size=2, max_overflow=0, pool_timeout=5,
            connect_args={'server_settings': {'search_path': 'core,public', 'statement_timeout': '30000', 'lock_timeout': '1000'}})
        self.engines.append(engine)
        self.engine = engine
        self.factory = self.make_factory(engine, expire_on_commit=False)
        self.database.engine = engine
        self.database.async_session_factory = self.factory
        self.main.async_session_factory = self.factory

    async def fixture(self):
        from app.models import App, Company, CompanyApp
        from app.models_partner import PartnerClient, PartnerInstallation
        async with self.factory() as session:
            company = Company(id=COMPANY, name='Synthetic restore company', slug='restore-proof', profile_id='energy')
            app = App(id=APP, code='restore-proof-app', name='Synthetic restore app', kind='partner', is_active=True)
            session.add_all([company, app])
            await session.flush()
            client = PartnerClient(id=CLIENT, app_id=APP, owner_company_id=COMPANY,
                redirect_uris=['https://example.invalid/callback'], allowed_scopes=[], auth_method='client_secret_basic', enabled=True)
            installation = CompanyApp(id=INSTALL, company_id=COMPANY, app_id=APP, enabled=True)
            session.add_all([client, installation])
            await session.flush()
            session.add(PartnerInstallation(id=INSTALL, company_id=COMPANY, client_id=CLIENT,
                approved=True, scopes=[], all_locations=True))
            await session.commit()
        conn = self.connections[SOURCE]
        await conn.execute("INSERT INTO core.product_api_budgets VALUES ($1,$2,$3,1,'2026-10-30T12:00:00+00',10,60)", COMPANY, INSTALL, CLIENT)
        await conn.execute('CREATE TABLE public.product_api_budgets (id integer PRIMARY KEY, marker text NOT NULL)')
        await conn.execute("INSERT INTO public.product_api_budgets VALUES (731,'synthetic-restore-sentinel')")

    async def goldens(self, conn):
        budget = await conn.fetch('SELECT company_id,installation_id,client_id,used,reset_at,request_limit,window_seconds FROM core.product_api_budgets')
        require([tuple(row) for row in budget] == [(COMPANY, INSTALL, CLIENT, 1, datetime(2026,10,30,12,tzinfo=timezone.utc), 10, 60)], 'fixture budget mismatch')
        require([tuple(row) for row in await conn.fetch('SELECT id,marker FROM public.product_api_budgets')] == [(731,'synthetic-restore-sentinel')], 'public sentinel mismatch')
        row = await conn.fetchrow("""SELECT c.id AS company,a.id AS app,ca.id AS installed,pi.id AS installation,pc.id AS client
            FROM core.companies c JOIN core.eco_company_apps ca ON ca.company_id=c.id
            JOIN core.eco_apps a ON a.id=ca.app_id JOIN core.partner_installations pi ON pi.id=ca.id
            JOIN core.partner_clients pc ON pc.id=pi.client_id WHERE c.id=$1 AND a.id=$2 AND ca.id=$3""", COMPANY, APP, INSTALL)
        require(row is not None and tuple(row) == (COMPANY, APP, INSTALL, INSTALL, CLIENT), 'fixture parent/FK mismatch')
        require(await conn.fetchval("SELECT count(*) FROM core.core_schema_versions WHERE revision=$1 AND action='adopted'", REVISION) == 1, 'adoption journal golden mismatch')
        require(await conn.fetchval("SELECT count(*) FROM core.app_startup_runs WHERE instance_id='schema-restore-proof-test'") == 1, 'completed marker not restored')
        require(await conn.fetchval("SELECT to_regclass('public.core_schema_versions')") is None, 'journal leaked to public')

    async def snapshot(self, conn, *, label=None):
        """Два независимых физических DB; нормализуем только логические признаки, не OID/MVCC."""
        objects = await self.relations(conn)
        require(300 < len(objects) <= 420 and all(o['schema'] in {'core','public','edge'} and o['owner']=='clearledger' for o in objects), 'catalog relation bound/ownership failed')
        predicate = "n.nspname IN ('core','public','edge')"
        queries = {
            'schemas': "SELECT jsonb_build_array(nspname,pg_get_userbyid(nspowner),nspacl::text) FROM pg_namespace WHERE nspname IN ('core','public','edge')",
            'relations': f"SELECT jsonb_build_array(n.nspname,c.relname,c.relkind,c.relpersistence,pg_get_userbyid(c.relowner),c.relacl::text,c.relrowsecurity,c.relforcerowsecurity,c.relreplident,c.reloptions) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {predicate} AND c.relkind IN ('r','p','v','m','S','f')",
            'columns': f"SELECT jsonb_build_array(n.nspname,c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,pg_get_expr(d.adbin,d.adrelid),a.attidentity,a.attgenerated,a.attstorage,a.attcompression,a.attacl::text,cn.nspname,co.collname) FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace WHERE {predicate} AND c.relkind IN ('r','p','v','m','f') AND a.attnum>0 AND NOT a.attisdropped",
            'constraints': f"SELECT jsonb_build_array(n.nspname,c.relname,k.conname,k.contype,k.convalidated,k.condeferrable,k.condeferred,pg_get_constraintdef(k.oid,true)) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {predicate}",
            'indexes': f"SELECT jsonb_build_array(n.nspname,c.relname,ic.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready,i.indislive,i.indisreplident,ic.reloptions) FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_class ic ON ic.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {predicate}",
            'triggers': f"SELECT jsonb_build_array(n.nspname,c.relname,t.tgisinternal,t.tgtype,t.tgenabled,pn.nspname,p.proname,k.conname,CASE WHEN NOT t.tgisinternal THEN pg_get_triggerdef(t.oid,true) END) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace LEFT JOIN pg_constraint k ON k.oid=t.tgconstraint WHERE {predicate}",
            'functions': f"SELECT jsonb_build_array(n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),pg_get_userbyid(p.proowner),p.proacl::text,p.proconfig,pg_get_functiondef(p.oid)) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE {predicate} AND p.prokind IN ('f','p')",
            'enums': f"SELECT jsonb_build_array(n.nspname,t.typname,pg_get_userbyid(t.typowner),t.typacl::text,e.enumsortorder,e.enumlabel) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace JOIN pg_enum e ON e.enumtypid=t.oid WHERE {predicate}",
            'sequences': f"SELECT jsonb_build_array(n.nspname,c.relname,format_type(s.seqtypid,NULL),s.seqstart,s.seqincrement,s.seqmax,s.seqmin,s.seqcache,s.seqcycle) FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {predicate}",
            'views': f"SELECT jsonb_build_array(n.nspname,c.relname,pg_get_viewdef(c.oid,true)) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {predicate} AND c.relkind IN ('v','m')",
            'extensions': "SELECT jsonb_build_array(e.extname,e.extversion,n.nspname,pg_get_userbyid(e.extowner),e.extrelocatable) FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace",
            'policies': f"SELECT jsonb_build_array(n.nspname,c.relname,p.polname,p.polcmd,p.polpermissive,ARRAY(SELECT CASE WHEN x=0 THEN 'public' ELSE pg_get_userbyid(x) END FROM unnest(p.polroles) x ORDER BY 1),pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {predicate}",
            'inheritance': f"SELECT jsonb_build_array(n.nspname,c.relname,pn.nspname,parent.relname,i.inhseqno) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_class parent ON parent.oid=i.inhparent JOIN pg_namespace pn ON pn.oid=parent.relnamespace WHERE {predicate}",
        }
        catalog, details, raw_hashes = {}, {}, {}
        for kind, query in queries.items():
            rows = [json.loads(row[0]) for row in await conn.fetch(query)]
            normalized = sorted(map(canonical,rows))
            raw_hashes[kind] = {'count':len(rows),'sha256':sha(normalized)}
            catalog[kind] = {'count':len(rows), 'sha256':sha(sorted(canonical(logical_catalog_row(kind,row)) for row in rows))}
            if label:
                details[kind] = normalized
        data, count, payload = {}, 0, 0
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            for obj in objects:
                name = obj['schema'] + '.' + obj['name']
                qualified = quote(obj['schema']) + '.' + quote(obj['name'])
                if obj['kind'] in {'r','p','m'}:
                    values = []
                    async for row in conn.cursor('SELECT to_jsonb(t)::text FROM ' + qualified + ' t', prefetch=100):
                        value = canonical(json.loads(row[0]))
                        values.append(value)
                        count += 1
                        payload += len(value.encode())
                        require(count <= 50000 and payload <= 32*MIB, 'snapshot data bound exceeded')
                    data[name] = {'rows':len(values), 'sha256':sha(sorted(values))}
                elif obj['kind'] == 'S':
                    data[name] = {'state':list(await conn.fetchrow('SELECT last_value,is_called FROM ' + qualified))}
        result = {'catalog_format':'varchar_text_array_deparse_v1','catalog':catalog, 'data':data, 'relations':len(objects), 'rows':count}
        if label:
            require(label in {'source-before','target-after'}, 'unknown diagnostic snapshot label')
            self.private_json(label+'.snapshot.json',result,limit=MIB)
            self.private_json(label+'.catalog.json',details)
            self.private_json(label+'.raw-catalog-hashes.json',raw_hashes,limit=MIB)
            self.catalog_details[label] = details
            self.raw_catalog_hashes[label] = raw_hashes
        return result

    async def startup(self):
        self.settings.app_env = 'prod'
        try:
            async with self.database.database_startup_lock():
                await self.main._prepare_database_once(datetime(2026,10,30,12,tzinfo=timezone.utc))
        finally:
            self.settings.app_env = 'test'

    async def ready(self):
        async with self.factory() as session:
            require((await self.main.readiness_check(session))['status'] == 'ready', 'native readiness failed')

    async def run(self):
        self.phase = 'container-preflight'
        ports = json.loads(await self.command(['docker','inspect','--format','{{json .NetworkSettings.Ports}}',CONTAINER]))
        require(ports.get('5432/tcp') == [{'HostIp':'127.0.0.1','HostPort':'33546'}], 'container mapping mismatch')
        for tool in ['pg_dump','pg_restore']:
            version = await self.command(['docker','exec',CONTAINER,tool,'--version'])
            require(version.startswith(tool+' (PostgreSQL) 16.15'), 'tool version mismatch')
        await self.space(384*MIB)
        await self.command(['docker','exec','--env','PGPASSWORD',CONTAINER,'pg_isready','-h','127.0.0.1','-p','5432','-U','clearledger','-d',SOURCE])
        self.phase = 'driver-preflight'
        import asyncpg
        self.asyncpg = asyncpg
        first = await self.connect(SOURCE)
        source_identity = await self.identity(SOURCE, empty=True)
        await self.connect(TARGET)
        target_identity = await self.identity(TARGET, empty=True)
        inside = (await self.command(['docker','exec','--env','PGPASSWORD',CONTAINER,'timeout','-s','TERM','-k','5','5','psql','-X','-w','-h','127.0.0.1','-p','5432','-U','clearledger','-d',SOURCE,'-Atc','SELECT system_identifier FROM pg_control_system()'])).strip()
        require(inside == source_identity['cluster'] == target_identity['cluster'], 'host/container cluster identity mismatch')
        self.record('container_tcp_database_identity', version=160015, maxlocks=64)
        await self.native_cast_controls(first)
        # Только после обеих actual preflight: считаем свежие БД собственными fixtures.
        self.claimed.update((SOURCE,TARGET))
        self.phase = 'application-bootstrap'
        logging.disable(logging.CRITICAL)
        sys.path.insert(0,str(SERVER))
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy import event
        from app import database, main
        from app.config import get_settings
        from app.services.schema_version_gate import require_engine
        from schema_migrations.runner import Config, execute
        self.database, self.main = database, main
        self.settings = get_settings()
        self.create_engine, self.make_factory = create_async_engine, async_sessionmaker
        await database.engine.dispose()
        require(self.settings.managed_core_budget_enabled is False, 'default mode changed')
        await first.execute('CREATE SCHEMA core')
        await first.execute('CREATE SCHEMA edge')
        await self.bind(SOURCE)
        await database.create_all()
        require(len(database.Base.metadata.tables)>300, 'registered metadata incomplete')
        require(await first.fetchval('SELECT pg_database_size(current_database())')<=DB_LIMIT, 'bootstrap database size bound exceeded')
        await self.space(256*MIB)
        self.record('source_registered_metadata_bootstrap')
        self.phase = 'source-static-fixture'
        await self.fixture()
        self.record('source_static_fixture_insert')
        self.phase = 'source-frozen-adoption'
        adopted = await execute(Config(raw_url(SOURCE),SOURCE,'clearledger','core'),'apply')
        require(adopted['action']=='adopted', 'budget was not adopted')
        self.record('source_frozen_budget_adoption')
        self.settings.managed_core_budget_enabled = True
        self.phase = 'source-managed-preparation'
        await self.startup()
        self.record('source_managed_preparation_completed_marker')
        self.phase = 'source-native-readiness'
        await self.ready()
        self.record('source_native_readiness')
        self.phase = 'source-independent-goldens'
        await self.goldens(first)
        self.record('actual_core_bootstrap_fixture_adoption_managed_marker')
        self.phase = 'quiesce-and-dump'
        await self.dispose()
        require((await self.identity(SOURCE))['others']==0, 'source writers remain')
        before = await self.snapshot(first,label='source-before')
        await self.close_connections()
        await self.space(256*MIB)
        archive = EVIDENCE/'synthetic.dump'
        await self.command(['docker','exec','--env','PGPASSWORD',CONTAINER,'timeout','-s','TERM','-k','5','60','pg_dump','-w','-h','127.0.0.1','-p','5432','-U','clearledger','--format=custom','--dbname='+SOURCE], archive_out=archive, timeout=90)
        require(archive.stat().st_size<=ARCHIVE_LIMIT, 'archive size bound exceeded')
        with archive.open('rb') as stream:
            require(stream.read(5)==b'PGDMP', 'invalid custom archive')
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        # TOC используется только для совместимости пустого public, не вместо restore.
        toc = await self.command(['docker','exec','--interactive',CONTAINER,'timeout','-s','TERM','-k','5','20','pg_restore','--list','--format=custom'], archive_in=archive)
        public_schema = any(line.split(';',1)[-1].split()[2:5]==['SCHEMA','-','public'] for line in toc.splitlines() if ';' in line)
        target = await self.connect(TARGET)
        await self.identity(TARGET, empty=True)
        if public_schema:
            # Архив явно воссоздаёт public; здесь нет объектов и иных клиентов.
            await target.execute('DROP SCHEMA public')
        await self.close_connections()
        await self.space(256*MIB)
        self.phase = 'actual-restore'
        await self.command(['docker','exec','--interactive','--env','PGPASSWORD',CONTAINER,'timeout','-s','TERM','-k','5','90','pg_restore','-w','-h','127.0.0.1','-p','5432','-U','clearledger','--format=custom','--exit-on-error','--dbname='+TARGET], archive_in=archive, timeout=120)
        await self.space(128*MIB)
        first = await self.connect(SOURCE)
        target = await self.connect(TARGET)
        await self.identity(SOURCE)
        await self.identity(TARGET)
        self.phase = 'restored-native-prerequisites'
        await self.native_cast_controls(target)
        self.phase = 'actual-restore'
        after = await self.snapshot(target,label='target-after')
        self.comparison_diagnostics(before,after)
        require(before == after, 'restored logical catalog/data differ')
        require(before == await self.snapshot(first), 'source changed across dump/restore')
        await self.goldens(target)
        self.record('actual_custom_dump_and_restore_catalog_data', archive_bytes=archive.stat().st_size,
                    archive_sha256=archive_sha, public_schema_in_toc=public_schema,
                    catalog_sha256=sha(before['catalog']), data_sha256=sha(before['data']),
                    relations=before['relations'], rows=before['rows'])
        self.phase = 'restored-managed-repeat'
        await self.bind(TARGET)
        receipt = await require_engine(self.engine,self.settings)
        require(receipt.read_only and receipt.driver_in_transaction and receipt.isolation=='repeatable read', 'actual app connection gate receipt mismatch')
        checked = await execute(Config(raw_url(TARGET),TARGET,'clearledger','core'),'check')
        require(checked['action']=='verified', 'readonly runner check failed')
        oid = await target.fetchval("SELECT 'core.product_api_budgets'::regclass::oid")
        await self.startup()
        await self.startup()
        await self.ready()
        require(oid == await target.fetchval("SELECT 'core.product_api_budgets'::regclass::oid"), 'restored budget recreated')
        require(before == await self.snapshot(target), 'managed marker/repeat changed restored dataset/catalog')
        # Реальная ORM запись в транзакции с rollback; никакого fake verifier.
        from app.models import Company
        async with self.factory() as session:
            company = await session.get(Company, COMPANY)
            require(company.name=='Synthetic restore company', 'restored ORM UUID lookup failed')
            company.name = 'Synthetic rollback only'
            await session.flush()
            await session.rollback()
        require(before == await self.snapshot(target), 'ORM rollback did not preserve dataset')
        self.record('restored_actual_gate_runner_check_marker_repeat_readiness_orm_rollback')
        self.phase = 'restored-negative-and-positive'
        checksum = await target.fetchval('SELECT artifact_sha256 FROM core.core_schema_versions WHERE revision=$1',REVISION)
        await target.execute('UPDATE core.core_schema_versions SET artifact_sha256=$1 WHERE revision=$2','0'*64,REVISION)
        writes = []
        def observe(conn,cursor,statement,parameters,context,executemany):
            keyword = statement.lstrip().split(None,1)[0].lower()
            if keyword in {'create','alter','drop','insert','update','delete','do','truncate'}:
                writes.append(keyword)
        event.listen(self.engine.sync_engine,'before_cursor_execute',observe)
        try:
            try:
                await self.startup()
            except RuntimeError as error:
                require(str(error)=='Managed Core budget schema is not ready', 'unexpected gate rejection')
            else:
                raise RuntimeError('restored corrupted journal accepted by startup')
            from fastapi import HTTPException
            try:
                await self.ready()
            except HTTPException as error:
                require(error.status_code==503, 'unexpected readiness rejection')
            else:
                raise RuntimeError('restored corrupted journal accepted by readiness')
            require(not writes, 'negative gate reached startup/marker write')
        finally:
            event.remove(self.engine.sync_engine,'before_cursor_execute',observe)
            await target.execute('UPDATE core.core_schema_versions SET artifact_sha256=$1 WHERE revision=$2',checksum,REVISION)
        await require_engine(self.engine,self.settings)
        await execute(Config(raw_url(TARGET),TARGET,'clearledger','core'),'check')
        await self.startup()
        await self.ready()
        require(before == await self.snapshot(target), 'positive state not restored after negative control')
        await self.goldens(target)
        require(before == await self.snapshot(first), 'negative control affected source')
        self.record('restored_checksum_negative_before_marker_and_exact_positive_recovery')

    async def cleanup(self):
        await self.dispose()
        for process in list(self.children):
            if process.returncode is None:
                process.kill()
            await process.wait()
            self.children.discard(process)
        await self.close_connections()
        if not hasattr(self,'asyncpg'):
            return
        outcomes = []
        for name in (SOURCE,TARGET):
            if name not in self.claimed:
                continue
            conn = await self.connect(name)
            try:
                await self.identity(name)
                objects = await self.relations(conn)
                require(len(objects)<=420 and all(o['schema'] in {'core','edge','public'} and o['owner']=='clearledger' for o in objects), 'cleanup refuses unexpected relation/owner')
                for kind,noun in [('v','VIEW'),('m','MATERIALIZED VIEW'),('f','FOREIGN TABLE')]:
                    for obj in objects:
                        if obj['kind']==kind:
                            await conn.execute('DROP '+noun+' IF EXISTS '+quote(obj['schema'])+'.'+quote(obj['name'])+' CASCADE')
                tables = [o for o in objects if o['kind'] in {'r','p'}]
                for offset in range(0,len(tables),8):
                    batch = ','.join(quote(o['schema'])+'.'+quote(o['name']) for o in tables[offset:offset+8])
                    await conn.execute('DROP TABLE IF EXISTS '+batch+' CASCADE')
                # Не-owned sequence, если появился, удаляется отдельно, <=1 за транзакцию.
                for obj in await self.relations(conn):
                    require(obj['kind']=='S', 'unexpected leftover relation')
                    await conn.execute('DROP SEQUENCE '+quote(obj['schema'])+'.'+quote(obj['name']))
                for schema in ['edge','core']:
                    await conn.execute('DROP SCHEMA IF EXISTS '+schema+' CASCADE')
                require(await self.relations(conn)==[], 'cleanup relations remain')
                row = await self.identity(name)
                outcomes.append({'database':name,'tablelike_sequences':0,'other_clients':row['others'],'maxlocks':row['maxlocks']})
            finally:
                await conn.close(timeout=5)
                self.connections.pop(name,None)
        self.record('owned_cleanup_no_database_drop', databases=outcomes, children=len(self.children))


async def main():
    guard()
    started = time.monotonic()
    proof = Proof()
    try:
        async with asyncio.timeout(420):
            await proof.run()
    except BaseException as error:
        # Исключение/traceback/SQL/URL/данные никогда не выводятся наружу.
        proof.failure = {'phase':proof.phase,'exception_type':type(error).__name__}
        if isinstance(error,ProofRefused):
            proof.failure['reason'] = str(error)
    finally:
        try:
            async with asyncio.timeout(120):
                await proof.cleanup()
        except BaseException as error:
            proof.cleanup_error = {'exception_type':type(error).__name__}
        finally:
            await proof.close_connections()
    ok = proof.failure is None and proof.cleanup_error is None
    summary = {'items':1,'passes':int(ok),'failures':int(proof.failure is not None),
               'errors':int(proof.cleanup_error is not None),'skips':0,
               'seconds':time.monotonic()-started,'failure':proof.failure,'cleanup_error':proof.cleanup_error,
               'steps':proof.steps,'children':proof.child_records,'live_children':len(proof.children)}
    proof.private_json('summary.json',summary,limit=MIB)
    print(json.dumps({key:summary[key] for key in ['items','passes','failures','errors','skips','seconds']},sort_keys=True))
    return 0 if ok else 1


if __name__ == '__main__':
    guard()
    raise SystemExit(asyncio.run(main()))
