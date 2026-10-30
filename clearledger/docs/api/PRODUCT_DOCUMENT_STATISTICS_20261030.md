# M15: document statistics control, 30.10.2026

Статус: **source-only; SQL/collect/opt-out/ANALYZE/EXPLAIN NOT RUN**.
Standalone ANALYZE требует отдельного literal root GO. Свободный synthetic PG
и предыдущие grants разрешением не являются. M00–M19 открыта, PR draft;
runtime/query rewrite/index/schema/config/merge/deploy в этот slice не входят.

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
AST/compile и diff-check PASS. Плановые metadata/HTTP/ANALYZE/EXPLAIN и cleanup
этого Dispatch пока NOT RUN. После approved run сюда добавляется фактический
результат и source SHA; source/runtime speedup не объявляется.
