# M15: document statistics control, 30.10.2026

Статус: **author statistics control PASS: 1 case /16HTTP /4EXPLAIN /2ANALYZE**.
Measured source `3c090cdc`, test SHA ниже. Выполнен один отдельно разрешённый
run; grant завершён, повторов нет. M00–M19 открыта, PR draft;
runtime/query rewrite/index/schema/config/merge/deploy не выполнялись.

Own branch `agent/api-document-statistics-control-20261030`, база
`f76174c3dcab196bbf381a6e8d955e2b2af00aa0`, тот же worktree
`/home/mag/orca/workspaces/ledger-app/api-contract-manual-serialization-20261030`.
Ownership ONLY2newfiles: этот MD и `server/tests/test_product_document_statistics.py`.
Предыдущие4 baseline/plans source/report файла не меняются. Test SHA256:
`f2e6745d28d9288cf395ffc8db8397416326e32f38b070cc8d88c157d5fa8fbb`.

## Один адресный control, без query change

Один pytest case и один canonical N5000 user-all dataset. Импортируется plans
module как namespace с неизменённым SHA
`eeae2aed0780bab54fcd8e92de29cdb721093ef848dbf9ca597d44a6e454a2cf`,
а его baseline helper pinned на
`054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2`.
Оба source pins проверяются до app/pytest imports. Старые parametrized tests
не импортируются как test functions и повторно не собираются.

В новом процессе только test-harness namespace `plans.EVIDENCE` временно
перенаправляется через monkeypatch в
`/srv/projects/api-modernization-test-env-20261029/private-product-document-statistics-20261030`.
Это не изменение tracked helper/runtime/API. Старые fixed evidence и immutable
author archives не читаются/не меняются runner. Существующие real budget/
signing fixtures, Query, verifier, permission models и ORM listeners сохраняются.

Последовательность:

1. Dataset N5000 и user-all policy теми же helpers; без grantSET CPU/cache slice.
2. **8 golden HTTP BEFORE** через прежний `golden`: page200, cursor200, positive
   detail, tenant/private/explicit-deny/strict404, service403 с полным восстановлением
   synthetic user grant/family/token/header/membership.
3. **2 actual EXPLAIN BEFORE**: исходные captured driver COUNT и page LIMIT201,
   original typed bind tuple. Не ручная копия SQL и не literalization.
4. На connection для maintenance — отдельная read-only transaction с проверкой
   `current_database`, public schema, обоих relation names, ordinary table kind,
   owner clearledger. После её commit на **том же connection** начинается
   writable transaction только с двумя literal commands и inherited local limits:
   `ANALYZE public.doc_cards`, `ANALYZE public.doc_access_grants`.
5. **2 actual EXPLAIN AFTER** с теми же SQL и typed parameters, без query/runtime
   изменения, без добавления индексов, VACUUM, других таблиц или planner switches.
6. **8 golden HTTP AFTER**, полное равенство page payload и actual SQL+typed binds.
   Все8 HTTP deterministic records сравниваются попарно без walltime.

Итого: **16 HTTP**, ожидаемо6×200/8×404/2×403; **4 EXPLAIN**, **2 ANALYZE**.
Visible documents2000, returned200, hydrated201 с lookahead; negative cases не
гидратируют скрытые карточки. Object/counterparty link redaction и cursor при
одинаковых timestamps остаются. Без broad237 повторов и без source speedup claims.

## Metadata, transactions и safety

EXPLAIN и metadata выполняются только в read-only transactions. `SET TRANSACTION
READ ONLY` идёт до любого SELECT; imported listener на begin выставляет только
SET LOCAL statement/lock timeout. Control SELECT подтверждает `read_only=on`.

В каждом plan phase metadata снимается перед2plans, затем после commit — в новой
read-only transaction. Это4 snapshots. Ещё1 snapshot на том же connection перед
maintenance доказывает target ownership. Всего **5 scoped metadata SELECT +
5 read-only control SELECT**. Новые transactions не используют прежний pg_stat
snapshot, но publication lag counters остаётся возможным и не скрывается.

Читаются только safe counters двух собственных tables из pg_stat_all_tables/
pg_class: reltuples/pages/allvisible, live/dead/mod-since-analyze estimates,
analyze/autoanalyze counts и timestamps. Schema/database/owner/kind проверяются
для обеих таблиц. OIDs, pg_statistic/MCV/histogram/literal data не выбираются.
Отличие analyze counters/timestamps внутри phase отмечается отдельно; отсутствие
отличия не доказывает отсутствие async/background activity. pg_class catalog
estimates фиксируются отдельно от асинхронных pg_stat counters.

Дополнительно1 bounded preflight SELECT и6 own database-size checks из unchanged
helpers. Identity/domain/link/setup/seed/teardown SQL выполняются реально; их
фактическое число не заменяется выдуманной константой. Writable maintenance
transaction содержит только2 literal ANALYZE и local timeout commands, без
metadata SELECT, admin/CREATE/DROP, настройки статистических targets или VACUUM.

Обе exact equal canonical URI проверяются до первого connect и до pytest,
перед собственными engine connections проверяется engine URL. Пустой cwd без
`.env`, APP_ENVtest, testUPLOAD, inherited HOME, explicit plugin/opt-ins.
Отсутствие own opt-in при module import даёт SKIP до app/DB imports; main строго
отказывает. Общий partner safety predicate вызывается до pytest imports.

Лимиты: **statement15s/lock1s** transaction-local, в том числе ANALYZE;
**own DB256MiB**, alarm330s, outerTERM360s/KILL370s. Общий PGDATA tmpfs1GiB;
root проверяет свободное место до fresh CREATE/GO. No autoexpand/retry при FAIL.
Сначала child EXIT/reap и shared teardown, затем SQL_SLOT_RELEASED; root отдельно
проверяет tables0/conns0 и делает normal DROP. Worker admin/CREATE/DROP не имеет.

## Private evidence и интерпретация

Новая отдельная private директория содержит: preflight/run/JUnit/HTTP samples,
два raw captured statements, четыре raw plan JSON, before/after safe phases,
ownership metadata, два ANALYZE wall durations и safe-summary. Старые artifacts
не используются как текущий output; runner отказывает при существующих current
outputs. Raw SQL/binds/Filter/Index Cond/plans остаются private.

Для public summary разрешены только bounded node names/counts/SQL+plan hashes,
numeric estimates/actual rows/loops/buffers/time и safe scoped metadata counters.
Сохраняются plan planning/execution отдельно от HTTP walltime и ANALYZE duration;
parent/child buffers/times не складываются. Node Rows/Time при loops>1 — средние,
не точные totals. No production SLO/QPS, no cold/warm speedup conclusion.

Проверяется **statistics effect при неизменном source**, не query rewrite.
Если heavy deny loop исчезнет после статистики, это меняет основания для
следующего source A/B; если сохранится, counters/estimates помогают выбрать
следующий шаг. Автоанализ/публикация counters могут ограничить причинный вывод;
нет обязанности получить ускорение или конкретный plan shape. Query semantics
проверяются golden invariants, не желаемой формой оптимизатора.

## Exact runner — только после нового root GO

Canonical database остаётся `api_product_query_scaling_test` на127.0.0.1:33546,
PG16, clearledger/api_test_only ради строгих parent guards. Root отдельно
подготавливает свежую БД того же имени после cleanup предыдущего owner.

```bash
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I - <<'PY'
import hashlib, os
from pathlib import Path
root = Path('/home/mag/orca/workspaces/ledger-app/api-contract-manual-serialization-20261030')
test = root / 'clearledger/server/tests/test_product_document_statistics.py'
assert hashlib.sha256(test.read_bytes()).hexdigest() == 'f2e6745d28d9288cf395ffc8db8397416326e32f38b070cc8d88c157d5fa8fbb'
runtime = Path('/srv/projects/api-modernization-test-env-20261029')
cwd = runtime / 'product-query-scaling-empty-test'
upload = runtime / 'product-query-scaling-test-uploads'
evidence = runtime / 'private-product-document-statistics-20261030'
for path in (cwd, upload, evidence):
    path.mkdir(mode=0o700, exist_ok=True)
assert not any(cwd.iterdir())
assert not (evidence / 'run.log').exists()
env = {key: os.environ[key] for key in ('HOME', 'PATH', 'LANG') if key in os.environ}
target = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test'
env.update(APP_ENV='test', TEST_DATABASE_URL=target, DATABASE_URL=target,
    UPLOAD_DIR=str(upload), RUN_PRODUCT_DOCUMENT_STATISTICS_TESTS='1',
    RUN_PRODUCT_DOCUMENT_QUERY_PLANS_TESTS='1', RUN_PRODUCT_QUERY_SCALING_TESTS='1',
    RUN_PARTNER_RESOURCE_TESTS='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
    PYTHONDONTWRITEBYTECODE='1', SECRET_KEY='synthetic-document-statistics-only')
os.chdir(cwd)
fd = os.open(evidence / 'run.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
python = str(runtime / '.venv/bin/python')
os.execve('/usr/bin/timeout', ['timeout', '--signal=TERM', '--kill-after=10s',
    '360s', python, '-I', str(test), '--execute-approved-document-statistics'], env)
PY
```

Main preflight: own current DB/user, PG16/maxlocks64/otherclients0, size<256MiB.
Pytest flags: один absolute test path, `-c server/pytest.ini`, explicit
`-p pytest_asyncio.plugin -p no:cacheprovider -q -ra --maxfail=1`, own
`--confcutdir`, private `--basetemp`, `-o junit_family=legacy`, private JUnit.
Parent helpers pins и guards не ослабляются. Разрешение на opt-out также
не подразумевается до GO; при разрешении один `--noconftest` без own flag,
ожидается1SKIP/EXIT5 без DB fixtures.

До grant выполнены только source/AST/compile своего test, без module import;
AST/compile и diff-check PASS. Root отдельно прочитал точный source/MD и выдал
literal GO на fresh canonical own DB, один case и ровно2 targeted ANALYZE.
Opt-out `--noconftest`: **1 module SKIP /EXIT5**, без DB fixtures. После этого
один actual run, без FAIL/retry и без изменения measured test source.

## Фактический result и golden equivalence

**Child EXIT0/reaped, 1 PASS /0FAIL /0ERROR /0SKIP, JUnit45,420s**.
Выполнены16 HTTP (6×200/8×404/2×403),4 actual EXPLAIN и2 literal ANALYZE.
Все metadata/ownership/read-only controls прошли. `safe-summary.json` совпадает
с JUnit property; все8 deterministic HTTP records before/after равны без
walltime. Совпали целиком page payloads, разрешённые IDs, link redaction/cursor
и actual driver SQL+original typed binds. Исходники Query/ACL/verifier/listeners,
индексы и конфигурация не изменялись.

API total2000, page200 возвращает200 cards/гидратирует201/50843bytes; cursor
также201 hydrated cards/50945bytes. Positive detail1card/308bytes, negatives
0cards/159bytes, service403 без domain SELECT/0cards/157bytes. SQL counts
до/после:31 для list/cursor/detail,28 для каждого negative detail,15 для
service403; всего440 statements внутри16 HTTP, включая verifier/SET LOCAL.
Maintenance, metadata и EXPLAIN считаются отдельно от этих HTTP statements.

Preflight: PG160015, maxlocks64, otherclients0, fresh own DB7 765 015bytes.
После dataset36 011 031bytes, после queries36 330 519bytes (34,65MiB), ниже
256MiB. Один и тот же owned connection подтвердил перед maintenance:
current DB=`api_product_query_scaling_test`, schema public, owner clearledger,
relation kind r, ровно doc_cards/doc_access_grants. После commit RO проверки
в отдельной writable transaction выполнены только две ANALYZE и local limits.

## Metadata: статистика действительно изменилась

В BEFORE start/end и ownership snapshot обе таблицы имели reltuples=-1,
relpages0, analyze_count0/autoanalyze_count0, last_analyze/last_autoanalyze NULL.
Это неизвестные catalog estimates, а не нулевое фактическое число строк.
pg_stat live-tuple counters уже показывали5004/2000; их нельзя смешивать с
planner catalog estimates или считать точным API-visible count.

| Таблица | pg_class reltuples before→after | relpages before→after | n_live_tup before/after | n_mod_since_analyze before→after | analyze_count before→after |
|---|---|---|---:|---|---|
| doc_cards | -1→5004 | 0→167 | 5004 | 5005→0 | 0→1 |
| doc_access_grants | -1→2000 | 0→35 | 2000 | 2000→0 | 0→1 |

AFTER start/end counters/timestamps совпадают: обе last_analyze заполнены,
autoanalyze_count0 и last_autoanalyze NULL. Observed counter change внутри
каждой plan phase=false. Snapshots читались в новых RO transactions, поэтому
старый transaction pg_stat snapshot не использовался. Publication lag остаётся
общим ограничением counters, но здесь изменение подтверждено и pg_class,
и analyze_count/last_analyze. OIDs/pg_statistic/MCV/histograms не читались.

ANALYZE command walltime: doc_cards65,86ms, doc_access_grants24,88ms.
Это durations двух разрешённых maintenance commands на данном dataset,
не производственная стоимость обслуживания и не SQL SELECT execution time.

## Два unchanged statements, четыре actual plans

| Фаза | Statement | Planning ms | Execution ms | Root actual rows | Узлов | Root shared hits | Shared reads/temp |
|---|---|---:|---:|---:|---:|---:|---|
| BEFORE | COUNT | 0,803 | 2294,662 | 1 | 13 | 166921 | 0/0 |
| BEFORE | page LIMIT201 | 1,468 | 2365,177 | 201 | 14 | 166921 | 0/0 |
| AFTER | COUNT | 6,499 | 652,845 | 1 | 13 | 27171 | 0/0 |
| AFTER | page LIMIT201 | 2,338 | 43,119 | 201 | 14 | 27179 | 0/0 |

Actual visible intermediate result Anti join2000 rows не изменился. COUNT и
page сохраняют **Nested Loop Anti и3000 loops**; исчез не сам loop, а broad
deny probe внутри него. В private plan структурные условия подтверждают:
раньше deny index branches использовали company_id/scope_type, после ANALYZE
они также используют scope_id для doc/kind correlations. SQL и существующий
индекс при этом те же; здесь не публикуются Filter/Index Cond или их значения.

| Наблюдение | BEFORE | AFTER |
|---|---|---|
| Anti join estimate /actual | 1 /2000 | 3703 /2000 |
| doc_cards scan estimate /actual | 1 /3000 | 4628 /3000 |
| Deny bitmap index branch avg rows /loops | 2000 /3000 | 1 /3000 |
| Deny heap avg rows returned/removed | 834 /834 | 0 /0 (округлено) |
| Deny heap shared hits | 153745 | 14000 |
| Deny heap avg time COUNT/page | 0,649 /0,664ms | 0,006 /0,004ms |

Rows/times повторяемых узлов — округлённые averages per loop. AFTER0 не значит,
что не было deny matches: final actual2000 и golden explicit-deny404 сохранены.
Parent/child buffers/times не суммировались. Allow subplan тоже сохраняет3000
loops и13000 shared hits; это отдельная работа, не broad deny scan.

COUNT AFTER сканирует doc_cards через Seq Scan, page AFTER — Index Scan с
Incremental Sort; эти формы выбраны PostgreSQL без planner switches. Меньшее
число root hits и selective deny index conditions согласуются с улучшением
catalog estimates. Это не утверждение об идеальности новых estimates:4628/3703
по-прежнему отличаются от actual3000/2000.

Raw COUNT AFTER содержит automatic JIT:52 functions, reported timing total
226,377ms; BEFORE COUNT и оба page plans JIT section не имеют. JIT settings
не менялись. Root Actual Total Time COUNT AFTER259,787ms и Execution Time
652,845ms — разные measurements; не складываем root/child/JIT и не приписываем
разность одному компоненту. Без отдельного контроля нельзя делать вывод о
полезности JIT или предлагать его отключение по этим числам.

HTTP walltime отдельно: page2004572,38→344,33ms, cursor4254,01→346,01ms.
Наблюдение single-run общей VM с разным порядком/cache/plan/JIT, без repeat
распределений и p95. **Statistics-only fixture effect, не source speedup и не
production SLO/QPS.** EXPLAIN execution не заменяет HTTP latency.

SQL hashes одинаковы BEFORE/AFTER и соответствуют actual captured statements:

| Statement | SQL SHA256 |
|---|---|
| COUNT | `f69e3a5950d17390c1921deeb728a3a58a9b1356607cc3725bcb474696178f29` |
| Page | `4d28a1084a39f7ec1cda9bd81b50a95a69f23a2e8da96d51d6aeb9d5e9c13172` |

| Фаза/statement | Raw-plan SHA256 |
|---|---|
| BEFORE COUNT | `d643ade12275c545b4f2cd9f59c3043a5ec8b1bd9f0cbaea807eccbbd5826455` |
| BEFORE page | `6eba83dd700c2889870cad6b364fc346ea036f7446d8478ad27ca74d45fbd992` |
| AFTER COUNT | `da6b1802946b0b9199d3ef7928b082aefed48842a32140f8681017111094defe` |
| AFTER page | `6f897102c570412681597d93b6098780001e3a0dbb66b80c9becfecbdf7658f6` |

## Вывод для следующего решения root

Статистика fresh synthetic DB оказалась существенным confounder исходных
медленных plans: broad deny scan исчез при неизменённом SQL/ACL и уже имеющемся
scope index. Поэтому немедленный deny-EXISTS rewrite на основании unanalyzed
plan теперь не обоснован. Следующие performance comparisons должны явно
фиксировать сопоставимое statistics state и actual plan; оригинальный fresh
bootstrap case сохраняется отдельно. Это рекомендация к подготовке будущих
согласованных synthetic experiments, а не поручение менять реальные базы.

Если root всё же выберет source A/B, сравнивать его с analyzed unchanged SQL,
а не с неинициализированными estimates; сначала нужна отдельная ACL-equivalence
матрица и новый scoped grant. Current16 golden controls подтверждают этот
statistics experiment, но не полную матрицу будущего rewrite. Не предлагается
новый индекс, отключение JIT, изменение autovacuum или runtime fix. Работа
другого characterization worker остаётся независимым source-only направлением.

## Cleanup и private artifacts

Child EXIT0/reap/shared teardown завершены без ошибок, connections процесса
закрыты, SQL_SLOT_RELEASED передан root. Root отдельно подтвердил fresh
public/edge tables0/conns0, normal DROP canonical own DB, затем
DBexists0/otherclients0/maxlocks64/adminclosed. Worker admin/CREATE/DROP не
использовал. После PASS новых SQL/ANALYZE/EXPLAIN/повторов нет, старый grant завершён.

Current artifacts только в отдельной
`/srv/projects/api-modernization-test-env-20261029/private-product-document-statistics-20261030/`:
optout/preflight/run/JUnit, `http-samples.jsonl`, count/page raw statements,
`before-count-plan.json`, `before-page-plan.json`, `after-count-plan.json`,
`after-page-plan.json`, before/after phase safe summaries, `analyze.json`,
`safe-summary.json`. Ownership metadata включена в final summary. Raw SQL,
binds/plans/conditions не копируются в public; в Git только2 согласованных
source/report файла. Прежние4files и old evidence/archives не менялись.
Measured testSHA после run неизменен; final commit добавляет только этот отчёт.
Root artifact acceptance отдельно; M00–M19/fullCI/production performance не закрыты.


## Приёмка координатора

Source3c090cdc/d6c3806f перенесён без runtime delta коммитамиa5be62be/4eab37da.
Root сверил immutable testSHAf2e6745d, JUnit1PASS45.420с и safe-summary property,
16HTTP/8before-after deterministic pairs, четыре raw-plan SHA/тайминга/root rows,
оба verified analyze targets и readonly metadata. SQL shapes всех четырёх plans
совпадают с независимо выполненным root scaling baseline. Повторные SQL/ANALYZE
для этой приёмки не запускались. Proof:
`.artifacts/root-product-document-statistics-artifact-proof.json`.

Фиксация process EXIT0/reap и root fresh tables0/conns0→normalDROP→DBexists0/
otherclients0/maxlocks64 завершает отдельное synthetic окно. Эффект статистики
не превращается в разрешение обслуживать рабочую БД или переписывать ACL.
Отдельная ACL characterization готовится и проверяется до будущего выбора
source A/B; немедленная правка deny clause по fresh unanalyzed plan не выбрана.
