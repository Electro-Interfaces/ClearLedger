# M15: actual document COUNT/page plans, 30.10.2026

Статус: **author plan run PASS: 1 case, 16 golden HTTP, 2 actual EXPLAIN**.
Measured source `7a663599`, test SHA ниже. Root independent acceptance этого
нового slice ещё не выполнен. M00–M19 открыта, PR draft; merge/deploy,
реальные SQL/данные, runtime/index/schema changes не выполнялись.

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

AST/compile своего test и diff-check пройдены. Root прочитал точный source/MD,
отдельно завершил приоритетный independent baseline и его fresh normal DROP,
затем создал fresh canonical DB и выдал literal GO этому Dispatch на один run.
Opt-out `--noconftest`: **1 SKIP / EXIT5**, без DB fixtures. После grant выполнен
один actual case, без FAIL/retry и без изменения измеренного test source.

## Фактический результат

**EXIT0/reaped, 1 PASS / 0 FAIL / 0 ERROR / 0 SKIP, JUnit53,657s**.
Выполнены ровно16 HTTP: 6×200, 8×404, 2×403. Все8 deterministic HTTP records
до/после совпадают по status/SQL counts/hydration/response bytes/domain kinds;
walltime из сравнения исключён. Внутри теста также совпали целиком page payloads,
точные разрешённые IDs, link redaction, cursor tie-break и original driver
SQL/typed binds до/после. `safe-summary.json` полностью совпал с JUnit property.

Preflight: PG160015, maxlocks64, otherclients0, fresh DB7 765 015bytes.
Размер после dataset35 994 647bytes, после запросов36 314 135bytes (34,63MiB),
ниже256MiB. Read-only control вернул `on`; оба actual EXPLAIN выполнены в одной
own read-only transaction с исходными statements и typed params, по одному разу.

| Actual statement | Planning ms | Execution ms | Root rows | Узлов | Root shared hits | Shared reads | Temp reads/writes |
|---|---:|---:|---:|---:|---:|---:|---:|
| COUNT | 1,945 | 2404,896 | 1 | 13 | 166921 | 0 | 0/0 |
| Page LIMIT201 | 0,903 | 2531,699 | 201 | 14 | 166921 | 0 | 0/0 |

Обе planning buffer sections: 31 shared hit, 0 read/temp. Это показатели двух
конкретных тёплых synthetic plans, не production latency/SLO и не cold-I/O test.
Parent/child buffers не суммировались. Root shared writes/dirtied также0.

Bounded source/plan fingerprints без raw conditions и synthetic IDs:

| Statement | SQL SHA256 | Raw-plan SHA256 |
|---|---|---|
| COUNT | `f69e3a5950d17390c1921deeb728a3a58a9b1356607cc3725bcb474696178f29` | `abccf6e59c35f43a816097ecf9e0d3fc9840f049d858e376e39dbd83356fe1c6` |
| Page | `4d28a1084a39f7ec1cda9bd81b50a95a69f23a2e8da96d51d6aeb9d5e9c13172` | `9185ccff12f6dfe0b08d26378054aa2c32fa77a70d5316c77515f7eef0a1c1a5` |

Для HTTP page200 до/после: 31 SQL statements, 201 hydrated cards, 50843 bytes,
total2000/returned200. Cursor page200: 31 SQL, 201 cards, 50945bytes. Positive
detail: 31 SQL/1 card/308bytes; каждый negative detail28 SQL/0 cards/159bytes;
service403: 15 SQL/0 cards/157bytes, domain SELECT отсутствует. Итого440 SQL
statements внутри16 HTTP, включая verifier/permissions/link projection/SET LOCAL.
Два EXPLAIN и metadata checks учитываются отдельно, это не HTTP SQL-count.

HTTP page walltime 4656,77ms до и4480,95ms после; cursor4243,65/4235,80ms.
Эти числа содержат capture/hydration hooks и не являются SQL executiontime.
Сумму EXPLAIN execution нельзя автоматически подставлять вместо HTTP latency:
EXPLAIN и HTTP выполнены в разных фазах, с иным instrumentation/cache state.
Никакого speedup относительно прежних traced5,375s этим run не доказано.

## Что показали планы и где это в source

[`Query.listing`](../../server/app/product_api/queries.py#L135) делает exact
COUNT на строке146, затем page SELECT с LIMIT pageSize+1 на строке154.
Оба используют действующую
[`_readable_doc_clause`](../../server/app/services/doc_access.py#L389).
Её deny EXISTS на строке446 объединяет doc/kind scope через OR и возвращается
как `~denied` на строке458. Tenant и user/role/department subject predicates
остаются частью общего условия; grant SET/query binding сюда не подменялись.

В обоих measured plans PostgreSQL превратил deny EXISTS в **Nested Loop Anti**.
Для outer `doc_cards` Index Scan: 3000 actual rows, 2003 rows removed by filter,
estimated rows1. Anti join возвращает2000 разрешённых строк, estimate1.
Intermediate plan rows не равны разрешённой кардинальности API.

| Узел | COUNT | Page |
|---|---|---|
| doc_cards Index Scan | total41,613ms, loops1 | total46,773ms, loops1 |
| Allow doc_access_grants Bitmap Heap Scan subplan | loops3000, avg0,007ms | loops3000, avg0,008ms |
| Deny inner doc_access_grants Bitmap Heap Scan | loops3000, avg834 returned/834 removed, avg0,677ms | loops3000, avg834 returned/834 removed, avg0,710ms |
| Deny inner shared hits | 153745 | 153745 |
| Deny Bitmap Index branch | loops3000, avg2000 rows | loops3000, avg2000 rows |
| Nested Loop Anti total | 2403,505ms | 2525,216ms |

`Actual Rows`, removed rows и times у повторяемых узлов — округлённые средние
на loop, не точные суммарные количества; parent times включают child work.
Это actual evidence повторной работы deny scan внутри этих двух plans.
Page дополнительно делает in-memory top-N heapsort, 115KiB, после2000 rows
от Anti join; LIMIT201 не устранил эту upstream ACL-работу. Temp spill не наблюдался.

В private raw plan у allow subplan scope_id участвует в index/recheck conditions;
у deny inner индексные branches используют company_id/scope_type, а соответствие
scope_id doc/kind остаётся Join Filter Anti join. Здесь публикуются только имена
колонок/структура, без полных Filter/Index Cond/значений.
У модели уже есть индекс
[`idx_doc_access_scope(company_id,scope_type,scope_id)`](../../server/app/models.py#L13398)
и unique grant key; вывод «нет индекса» из этих двух plans не следует.

## Минимальный следующий шаг для отдельного root решения

Наблюдаемая область затрат стала уже: deny Anti join с3000 repeated ACL scans,
а не только неопределённый HTTP/tracing overhead. Но оценка1 строка против
actual3000/2000 требует отдельно учесть статистику fresh synthetic DB. По
текущему grant standalone ANALYZE запрещён и не выполнялся; autovacuum/analyze
statistics counters не читались, их состояние этим отчётом не установлено.

Минимальный **кандидат отдельного source A/B для решения root** — только deny
часть `_readable_doc_clause`: эквивалентное разделение doc-deny и inherited-kind-
deny EXISTS с теми же tenant, subject и denied-read conditions. Цель experiment —
проверить, попадёт ли scope_id раньше Join Filter и исчезнет ли broad repeated
deny scan при уже существующем индексе. Allow branch сейчас существенно дешевле,
её изменение не требуется для первого адресного кандидата. Это гипотеза, не
выбранный fix; никакой runtime change в этом Dispatch не выполнен.

Логическая граница: существующий deny — наличие doc-deny **или** kind-deny
при `inherit_kind_acl IS TRUE`. Разделённая форма должна сохранить doc-deny
всегда, а inherited-kind-deny только для TRUE; FALSE/NULL не наследуют его.
Не заменять эту проверку обычным nullable NOT, не убирать company/subject
predicates и не менять allow/edit/read, empty-subject или delegation ветви.

Для отдельного A/B нужны actual statements обеих source версий на том же
synthetic N5000, golden equivalence и расширенные целевые controls: kind
inheritance TRUE/FALSE/NULL, user/role/department subjects, explicit deny поверх
allow, allow-edit/read, strict/admin/superadmin и действующие break-glass,
empty subjects/delegation. Текущие16 controls не заменяют эту ACL-матрицу.
План/loops/buffers измеряются отдельно от HTTP latency; без нужных controls
кандидат не считается допустимой оптимизацией даже при лучшем timing.

Отдельный вопрос root — statistics control перед/после A/B: estimates1 против
actual тысяч могут влиять на join choice. Обновление статистики **только own**
`doc_cards`/`doc_access_grants` и повтор двух unchanged plans возможно лишь если
следующий grant специально разрешит это; текущий standalone ANALYZE запрещал.
Не смешивать statistics change с source A/B и не приписывать ему production
эффект. Здесь дополнительных SQL/ANALYZE/EXPLAIN не выполнялось и не разрешено.
GrantSET CPU/cache и сравнительный instrumentation control в этот шаг не входят.

## Cleanup и артефакты

Child EXIT0/reap и shared-conftest teardown завершились без ошибок, connections
процесса закрыты, SQL_SLOT_RELEASED передан root. Root затем подтвердил fresh
public/edge tables0/conns0, normal DROP canonical own DB, после него
DBexists0/otherclients0/maxlocks64/adminclosed. Worker admin/CREATE/DROP не использовал.
Старый grant завершён, повторов/SQL после PASS нет.

Все private raw/summary artifacts находятся только в отдельном
`/srv/projects/api-modernization-test-env-20261029/private-product-document-plans-20261030/`:
`optout.log`, `preflight.json`, `run.log`, `results.xml`, `http-samples.jsonl`,
`count-statement.json`, `page-statement.json`, `count-plan.json`, `page-plan.json`,
`safe-summary.json`. В Git идут только эти два согласованных source/report файла,
raw artifacts не копируются в public. Baseline files/current EVIDENCE/immutable
author archive не менялись этим run. Root independent acceptance plans остаётся
отдельным этапом; M00–M19/full CI/production performance этим PASS не закрыты.
