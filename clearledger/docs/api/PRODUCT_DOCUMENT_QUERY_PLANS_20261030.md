# M15: actual document COUNT/page plans, 30.10.2026

Статус: **source-only preparation; SQL/collect/opt-out/EXPLAIN NOT RUN**.
Root independent baseline имеет первый приоритет SQL; этот runner ждёт
отдельного literal GO, fresh canonical DB и exclusive window. M00–M19 открыта,
PR draft; merge/deploy, реальные SQL/данные, runtime/index/schema changes запрещены.

Own branch `agent/api-product-document-plans-20261030`, база
`095d36c5491159c6e55932bf729a0611891f8110`, тот же worktree
`/home/mag/orca/workspaces/ledger-app/api-contract-manual-serialization-20261030`.
Ownership только два новых файла: этот документ и
`server/tests/test_product_document_query_plans.py`. Исходные baseline test/MD
не меняются. Test SHA-256:
`eeae2aed0780bab54fcd8e92de29cdb721093ef848dbf9ca597d44a6e454a2cf`.

## Slice и golden controls

Один pytest case, один synthetic N5000 dataset через неизменённые baseline
`dataset`/`policy` helpers и существующие `budget`/`signing_pem` fixtures.
Baseline module импортируется namespace, его parametrized test не импортируется
как test function и не собирается. SHA helper source проверяется до импорта:
`054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2`.
Его строгие exact DB/cwd/UPLOAD guards и transaction-local timeouts сохраняются.
Не вызываются baseline `observations`, `evidence`, runner или прежние 237 samples.

Синтетические 5000 объектов/договоров/документов, 5000 ContractLocation и
2000 DocAccessGrant соответствуют принятому dataset. User-all видит 2000
документов; конфиденциальность и явный deny остаются. Counterparty SET из
одного связанного контрагента сохраняет проверку link redaction; это не новый
grant-set performance slice. Реальные verifier, ACL и ORM listeners включены.

Две одинаковые golden фазы: до и после планов, по **8 HTTP requests**:

1. `/documents?q=Scaling&pageSize=200`: total2000, точные первые200 IDs,
   201 hydrated rows с lookahead, object links и counterparty redaction.
2. Следующая cursor page200: total2000, точные IDs201–400, следующий cursor,
   201 hydrated rows, tie-break при одинаковых timestamps.
3. Positive detail первой карточки: одна hydrated row, projection совпадает
   с первой строкой списка.
4. Foreign tenant detail404, без document hydration.
5. Private без allow detail404, без hydration.
6. Company с explicit read deny detail404, без hydration.
7. Strict без allow detail404, без hydration.
8. Настоящий synthetic machine document403, без domain COUNT/page/entity
   SELECT и без hydration. Scalar unused-profile ID validation остаётся
   разрешённой и отдельно учитывается; документный SET для этого slice не вводится.

Перед service control сохраняются synthetic grant kind/user_id/scopes,
family token_version/auth_time/expiry, token digest/scope/expiry, membership
object_scope/organization, payload целиком (sub/scope/exp), raw token/header.
После control всё это восстанавливается и commit завершается до следующего
user HTTP или планов. Не предполагается, что `policy(machine=False)` сама
восстановит user: в baseline helper такого перехода нет. Verifier и часы
не подменяются; исходный user expiry now+25min покрывает outer300s.

Ожидается **16 HTTP requests**: 6×200, 8×404, 2×403. Приложение выполняет
18 document-domain SELECT суммарно: COUNT+page первой страницы и cursor,
positive detail и четыре negative detail в каждой фазе. Identity/permission/
link SQL тоже выполняются и считаются, их итог фиксируется фактически.
Полные page payloads до/после, SQL и typed params выбранных statements должны
совпасть; IDs/headers/cursors не попадают в публичную сводку.

## Два фактических SQL statements и read-only execution

SQLAlchemy `before_cursor_execute` наблюдает реальный HTTP path в неизменённом
`product_api.Query`. Из первого page200 извлекаются ровно два driver statements:
actual COUNT и entity page SELECT с ORDER BY/LIMIT201. Полный SQL и исходный
typed bind tuple сохраняются в памяти; private JSON предназначен для evidence,
выполнение не восстанавливает типы из JSON и не literalizes параметры.
Query/ACL clauses не копируются вручную. Tenant/allow/deny shape и hydration
проверяются на реальных statements.

В собственном engine connection начинается отдельная transaction; первым
transaction-mode command идёт `SET TRANSACTION READ ONLY` **до любого SELECT**.
Штатный imported test listener выставляет только SET LOCAL15s/1s на begin.
Один control SELECT проверяет `current_setting('transaction_read_only')='on'`.
Далее по одному разу выполняются:

```text
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <exact captured COUNT> + original typed params
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <exact captured page>  + original typed params
```

Итого **ровно 2 EXPLAIN SELECT**, без retry и без отдельного ANALYZE/VACUUM,
planner switches, enable_seqscan, индексов или config changes. Root plan actual
rows ожидаются 1 для COUNT и 201 для page. Размеры БД проверяют существующие
helpers: 6 bounded own-size SELECT за dataset/policy/final; один preflight
SELECT плюс один read-only control SELECT. Setup/seed и shared teardown
используют штатные fixtures в собственной DB; число их SQL не подменяется
искусственной константой. Никаких admin/CREATE DATABASE/DROP DATABASE у worker.

## Evidence, интерпретация и пределы

Отдельная private директория:
`/srv/projects/api-modernization-test-env-20261029/private-product-document-plans-20261030`.
Baseline fixed EVIDENCE и его author archive/root repeat не читаются/не меняются
этим runner. При наличии прежних current outputs runner отказывает, не смешивает
попытки. Raw SQL, binds, full plans (включая literalized Filter/Index Cond) только
private: `count-statement.json`, `page-statement.json`, `count-plan.json`,
`page-plan.json`. Private `http-samples.jsonl` содержит только безопасные
числа/метки, без URL resource IDs, токенов/cursors/ключей. Pytest/httpx log может
содержать только синтетические ID/cursors и тоже остаётся private.

`safe-summary.json`/JUnit: planning/execution ms, actual root rows, SQL/plan
SHA256, до128 узлов с Node Type/Relation Name и numeric rows/loops/time/buffers.
Filter/Index Cond, keys/binds, output columns, aliases и synthetic IDs исключены.
Для buffers сохраняются значения каждого узла, не некорректная сумма parent+
children. Rows removed/actual loops и estimate rows помогают локализовать
работу, не доказывают производственный SLO.

HTTP walltime записывается отдельно от EXPLAIN execution/planningtime.
Tracemalloc не включается; capture/hydration hooks остаются. Это минимальное
извлечение actual SQL, не дополнительный comparative benchmark control.
Прежние traced5,375s не сравниваются с новым planning/execution как speedup:
нет runtime change, dataset/cache/measurement phase отличаются, общая VM.
Отдельный instrumentation control пока не нужен для вопроса о фактическом plan;
grantSET CPU/cache диагностика не входит в задачу.

Пределы: own DB256MiB, statement15s, lock1s, alarm270s, outer TERM300s/KILL310s.
N5000 и количество запросов не увеличиваются при FAIL. Сначала child EXIT/reap
и shared-conftest teardown, затем SQL_SLOT_RELEASED; root проверяет tables0/
conns0 и делает normal DROP. При failed teardown root получает unknown cleanup,
worker не чистит чужие DB/WAL и не меняет container/maxlocks.

## Точный runner после отдельного root GO

Canonical target сохраняется ради строгого helper guard:
`postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test`.
Root independent baseline первым завершает свой lifecycle; затем root создаёт
fresh own DB того же имени для этого Dispatch. Совпадение имени/свободный PG
не являются grant. До literal GO команду ниже не выполнять.

```bash
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I - <<'PY'
import hashlib, os
from pathlib import Path
root = Path('/home/mag/orca/workspaces/ledger-app/api-contract-manual-serialization-20261030')
test = root / 'clearledger/server/tests/test_product_document_query_plans.py'
assert hashlib.sha256(test.read_bytes()).hexdigest() == 'eeae2aed0780bab54fcd8e92de29cdb721093ef848dbf9ca597d44a6e454a2cf'
runtime = Path('/srv/projects/api-modernization-test-env-20261029')
cwd = runtime / 'product-query-scaling-empty-test'
upload = runtime / 'product-query-scaling-test-uploads'
evidence = runtime / 'private-product-document-plans-20261030'
for path in (cwd, upload, evidence):
    path.mkdir(mode=0o700, exist_ok=True)
assert not any(cwd.iterdir())
env = {key: os.environ[key] for key in ('HOME', 'PATH', 'LANG') if key in os.environ}
target = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test'
env.update(APP_ENV='test', TEST_DATABASE_URL=target, DATABASE_URL=target,
    UPLOAD_DIR=str(upload), RUN_PRODUCT_DOCUMENT_QUERY_PLANS_TESTS='1',
    RUN_PRODUCT_QUERY_SCALING_TESTS='1', RUN_PARTNER_RESOURCE_TESTS='1',
    PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONDONTWRITEBYTECODE='1',
    SECRET_KEY='synthetic-document-plans-only')
os.chdir(cwd)
fd = os.open(evidence / 'run.log', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
python = str(runtime / '.venv/bin/python')
os.execve('/usr/bin/timeout', ['timeout', '--signal=TERM', '--kill-after=10s',
    '300s', python, '-I', str(test), '--execute-approved-document-plans'], env)
PY
```

Runner: обе exact equal URIs до первого connect, shared safety predicate до
pytest/app/baseline imports, APP_ENVtest/emptycwd/testUPLOAD, explicit parent
opt-ins и async plugin, HOME унаследован. `__main__` без opt-in строго отказывает;
обычный module import без own flag делает SKIP до app/DB imports. Preflight
проверяет current DB/user, PG16/maxlocks64/otherclients0/own size<256MiB через
обычный own connection; admin не используется. Pytest flags: один absolute
test path, `-c server/pytest.ini -p pytest_asyncio.plugin -p no:cacheprovider
-q -ra --maxfail=1`, own `--confcutdir`, private `--basetemp`,
`-o junit_family=legacy`, private `--junitxml`.

AST/compile своего test выполнены без module import и SQL. Opt-out/collection,
HTTP/EXPLAIN, plan numbers и cleanup этого Dispatch пока NOT RUN; root review
и separate SQL GO обязательны. После run публикуется bounded aggregate/report,
raw artifacts остаются private; даже два actual plans не разрешают runtime fix.
