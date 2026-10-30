# M16: explicit schema migration foundation, 30.10.2026

Статус: **IMPLEMENTED + SYNTHETIC VERIFIED: 14 author pure PASS,
14 independent root pure PASS, 13 independent ROOT PostgreSQL PASS**.
Не ready/enabled для выпуска: startup, managed mode, Compose, существующие
models/database/config/Alembic/requirements/old tests и owner locks не изменены.
Предыдущий принятый design: `SCHEMA_MIGRATION_DESIGN_20261030.md`.

## Состав и база

Immutable base: `b55d99597ae0dbd3986e8cde0469f7e117d18177`.
Ветка `agent/api-schema-migration-runner-20261030`, прежнее own worktree,
без pull/новых worktrees/переключения общих деревьев. Ownership — только новый
`server/schema_migrations/**` и этот отчёт. Ни app/config imports, ни старые
fixture reset/ORM/listener replacements не используются.

- runner.py: explicit CLI plan/check/apply, Config object и async execute API.
  Единственный credential CLI argument — имя specialized env variable
  `--dsn-env SCHEMA_MIGRATION_...`; пароля/DSN в argv нет. DATABASE_URL/.env/Settings
  не используются. Config требует exact intended database/user/core и explicit
  postgres DSN/password/port, отвергает query/fragment overrides и mismatches.
- manifest.py: один allowlisted immutable revision package. Нет directory/plugin
  discovery, autogenerate, branch graph, DOWN или repairs. Exact artifact bytes
  проверяются offline до driver/connect/verifier execution.
- catalog.py: stateless facade, frozen verifier импортируется лениво после load;
  plan и обычный module import не импортируют catalog_v1/asyncpg/app.
- revisions/catalog_v1.py + 0001_contract.json: Core relation/OID/column/typmod/
  nullable/default/generated/identity/collation, constraints, indexes, owner/ACL/
  RLS/user-trigger/inheritance verifier. CHECK grammar ограничена frozen numeric
  bounds и action alternatives, не общий SQL prover.
- journal.py: строгое applied prefix/checksum/parent/ordinal/format/source actor
  validation и только INSERT applied; никакого UPDATE/stamp/repair.
- revisions/*.sql: только первая qualified budget create + existing-contract
  index и transactional Core journal. Parent/role/server/legacy objects не меняются.
- tests/test_pure.py: isolated direct unittest, subprocess import/CLI/artifact
  probes. tests/run_postgres.py: guarded actual harness, один независимый root run **13 PASS**.

`core.product_api_budgets` имеет ровно прежние 7 колонок, composite PK, FK к
core.partner_installations(id,client_id,company_id), CASCADE, три прежних named
CHECK и reset_at BTree index. Parent fixture contract — только три обязательные
колонки и supporting composite UNIQUE; дополнительные реальные parent columns
допустимы. Это не verifier всего partner schema/legacy bootstrap.

Adoption требует ordinary logged Core table, approved owner = intended user,
default ACL (explicit custom grants сейчас fail closed), RLS off/no user triggers,
exact catalog shape и реальный parent OID/schema/ordered attnums. Неправильные
или дополнительные managed indexes/columns/checks/defaults не ремонтируются.
В найденном собственном FK проверяются 4 internal triggers на child/parent:
exact builtin RI functions/tgtype/target identities, enabled origin, nondeferrable.
Target preflight требует session_replication_role=origin; другие FK triggers
всего legacy parent не проверяются и не меняются.
Core reserved index-name collisions отвергаются до первого DDL. Extra parent
fields не становятся объектами этой revision. Ни одна пользовательская строка
при adoption или repeat не изменяется.

## Integrity и owner/transaction semantics

Revision digest — length-delimited hash одного entry metadata (без его digest),
затем frozen file bytes в sorted path order. Он **не зависит от всего outer
registry**: append будущей entry сам по себе не меняет digest старой. Сейчас
loader намеренно принимает только одну известную revision, неизвестный manifest
отказывает до DB. Frozen verifier source входит в artifact; framework/manifest
loader остаются trusted code, защита от владельца изменяемых исходников не заявляется.

Case/whitespace/parentheses **внутри SQL string literals сохраняются**. Только
наружные незначащие whitespace/parentheses и ожидаемый literal ::text cast
нормализуются. Pure negatives CREATED/cre ated/tab/parentheses не совпадают с
разрешённым action contract; общий SQL parser не вводится.

Connection создаётся lazy asyncpg только после offline load и Config validation.
PG16/current database/current user/core schema owner/USAGE/CREATE проверяются
readonly. Конфигурация search_path/statement/lock/idle timeouts принадлежит только
этой connection, роль/БД/кластер не перенастраиваются. Никакого пула/secondary
application connection. Default Config budgets: connect5s, command/statement10s,
lock2s, idle-in-transaction5s, outer20s; bounded Config overrides для tests.

**check**: repeatable-read read-only transaction, без advisory lock/DDL/DML/journal
create; unapplied → code4. Снимок не сериализует внешний manual DDL, и это не
schema ownership proof при некооперирующих writers. Не использовать check как
неявный lock-taking request middleware.

**apply**: readonly preflight → session advisory lock **pair(434532,1)** на одном
dedicated connection → повтор всех предусловий/catalog/history в transaction →
create journal только при отсутствии → create budget либо verified adoption →
полные postconditions → applied INSERT → commit. Failure откатывает transaction,
включая новый journal; ранее applied head не переписывается. После успеха/failure/
cancel dedicated connection закрывается и освобождает lock. Автоматических retries нет.
Повтор verified head не выполняет DDL/DML и не изменяет journal.

CLI не вызывается из lifecycle под его другим locked connection; startup не
подключён. Старый xact owner lock и новый session lock конфликтуют в
одном pair keyspace в пройденном isolated control ниже. Другие schema owners и
manual DDL не становятся cooperative от наличия этого Foundation.

Exit codes: 0 verified/applied; 2 CLI/manifest/integrity; 3 target/namespace/identity;
4 catalog/history/unapplied; 5 owner lock/deadline; 6 DB/apply failure. Public output
— только fixed phase/code или safe receipt, без SQL/URI/driver exception details.
Argparse errors тоже не отражают неизвестные argv (включая случайно вставленный URI).

## Выполненные pure/source проверки

Python 3.13.7 executable:
`/srv/projects/api-modernization-test-env-20261029/.venv/bin/python`.
Путь `bin/python3.13.7` не используется.

```sh
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I \
  clearledger/server/schema_migrations/tests/test_pure.py
```

Последний результат: **14 PASS / 0 FAIL, 0,717 с**. Проверены реальные isolated
CLI/import subprocess, offline plan без env/driver/verifier, changed SQL/contract/
verifier checksums, invalid revision/path/duplicate JSON, отсутствие credential
fallback/echo, intended target, history tampering/gap/newer, per-revision digest
при append registry и narrow CHECK negatives. Copied-package verifier с import
marker отвергнут integrity check **до** исполнения marker. Предыдущие 9 PASS
были промежуточными до source review corrections и не заменяют этот набор.

Весь новый Python package прошёл AST/compile без исполнения actual harness.
Автор не выполнял SQL/connect/app collection; ROOT выполнил один actual run
после review и сам создал/удалил own DB. SSH/browser/restore/EXPLAIN/ANALYZE: **NOT RUN**.
Новых fake DB/catalog/advisory/SQL verifiers в actual harness нет.

## Пройденная independent ROOT матрица actual contract tests

13 unittest items; nested variants указываются отдельно. Root утвердил exact
матрицу/source SHA и сам исполнил единственный serial SQL run; author repeat не
выполнялся. Все 13 items PASS, 0 FAIL/ERROR/SKIP, 14,7611668957 с.
Минимальные реальные parent rows/DDL — synthetic prerequisites; ни full bootstrap,
ни архивы old binaries, ни production/restore этим набором не доказываются.

| Item | Малый actual сценарий | Golden |
|---|---|---|
| 01 | create → 2 quota rows → repeat apply → readonly check | created/verified; OID/MVCC tuple xmin+ctid/rows сохранены |
| 02 | exact preexisting table+2 rows, journal отсутствует | adopted; table OID/rows unchanged, repeat verified |
| 03 | check при unapplied | code4; ни journal, ни budget не создаются |
| 04 | missing parent; namespace public в Config | code4/3, zero managed writes |
| 05 | 7 persisted variants: used bigint, nullable, wrong default, missing CHECK, extra column, missing reset index, extra index | code4 before journal; snapshot unchanged |
| 06 | Core budget FK намеренно указывает на public parent с теми же synthetic PK values | code4 по реальному target OID, public rows unchanged |
| 07 | wrong journal CHECK CREATED/cre ated + journal с неполной структурой | code4 before INSERT, empty journal unchanged |
| 08 | 6 persisted histories: artifact hash, contract hash, unknown id, ordinal gap, parent mismatch, extra newer row | apply/check code4; old rows/xmin/ctid unchanged |
| 09 | другое connection держит parent ACCESS EXCLUSIVE; runner FK creation ждёт и получает настоящий lock timeout | code6, вся revision rollback, journal+budget absent |
| 10 | два настоящих runner connections одновременно apply | один created, второй verified; одна applied row |
| 11 | старый same-pair xact lock против apply; затем тот же lock против check | apply code5 безwrites; check проходит безlock acquisition |
| 12 | настоящие CLI apply/check subprocess со specialized DSN env | exit0, no URI/password output; child reaped |
| 13 | owned budget DISABLE TRIGGER ALL (только при уже имеющемся rolsuper) | code4 до journal; иначе явный SKIP без повышения привилегий |

В 09 before snapshot берётся **до** blocker lock, внутри только runner и catalog
exists, after snapshot **после** blocker close; data SELECT не ждёт собственный
ACCESS EXCLUSIVE. Это source исправление fixture до каких-либо SQL запусков.
Snapshot/MVCC equality — evidence отсутствия row mutations; это не заявляется
отдельным statement-count trace. Fixture13 использовал уже имеющийся synthetic rolsuper=True, независимо
проверенный root, и реально прошёл без SKIP. CREATE/ALTER ROLE/эскалации не было;
при отсутствии заранее provisioned privilege контракт harness остаётся SKIP.
Invalid-index/alternate-role catalog manipulation,
full legacy/old-code bootstrap, restore, managed activation и CI отдельно NOT RUN.

### Own DB, guard, bounded artifacts и cleanup

Использовалась только own `api_schema_migration_runner_test` на synthetic PG16
127.0.0.1:33546, clearledger/api_test_only. Root создаёт/удаляет БД; worker не
получает admin/CREATE DATABASE/DROP DATABASE/FORCE/terminate/global maxlocks права.
Root provisioned свежую БД без core/fixture relations; default public schema
оставалась. Worker к ней не подключался, approved harness исполнил root.

Перед первым driver import/connect: common partner_test_safety_error, own flag1,
оба exact TEST_DATABASE_URL/DATABASE_URL, specialized raw DSN, APP_ENV=test,
точные empty cwd/test UPLOAD/private EVIDENCE0700, Python3.13.7, 15 source pins
(14 other package files + existing pure safety helper), внешний approval wrapper
с 15 exact file hashes, включая actual harness, и manifest integrity. Guards
также вызываются в asyncSetUp/preflight до первого connect, поэтому unittest
loader не обходит opt-in; чистые subprocess negatives это подтвердили.
Preflight: actual DB/user/DB owner, PG16, maxlocks64, otherclients0, DB<64MiB.
Нет app/pytest/conftest import; поэтому explicit pytest plugin не требуется.

Harness 120s internal deadline, outer150s + kill-after10s, failfast на первом
неожиданном FAIL, без repeat/retry. Каждый test имеет 1 control connection,
runner ещё1; concurrency максимум3 client connections. В каждой fixture максимум
4 маленькие tables (parent, budget, journal, public shadow), 2 parent+2 quota+2
public rows и <=2 journal rows. Точное число SQL statements не задаётся как fake budget.

Cleanup только четырёх именованных core/public fixture relations в зависимости
от их реального relkind, затем пустой core без CASCADE; default public не сносится.
Проверяются other client backends=0, затем control закрывается; CLI children reaped,
blocker connections finally closed. Root независимо проверяет **все** non-system
relations/connections после child EXIT/SQL_SLOT_RELEASED и normal DROP own DB.
Private preflight.json/summary.json/run.log — только EVIDENCE вне Git.

### Exact runner, исполненный ROOT (повтор требует отдельного нового GO)

Root готовит directories; HOME передаётся исходный, env очищен. DSN только в
specialized env, не positional CLI credentials; URL ниже исключительно synthetic.

```sh
cd /srv/projects/api-modernization-test-env-20261029/schema-migration-runner-empty-test
timeout --signal=TERM --kill-after=10s 150s \
  env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
  RUN_SCHEMA_MIGRATION_RUNNER_TESTS=1 APP_ENV=test \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_schema_migration_runner_test \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_schema_migration_runner_test \
  SCHEMA_MIGRATION_TEST_DSN=postgresql://clearledger:api_test_only@127.0.0.1:33546/api_schema_migration_runner_test \
  UPLOAD_DIR=/srv/projects/api-modernization-test-env-20261029/schema-migration-runner-test-uploads \
  /srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I \
  /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/schema_migrations/tests/approved_postgres.py \
  --execute-approved-contract-tests \
  > /srv/projects/api-modernization-test-env-20261029/private-schema-migration-runner-20261030/run.log 2>&1
```

## Exact source checkpoint

Package bundle SHA-256 (включая wrapper): `c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e`.
Algorithm: sorted relative paths excluding __pycache__, each `name + NUL + fileSHA`,
joined by LF with final LF; SHA256 UTF-8 payload. Report не входит в bundle.

Approval target bundle (15 файлов, только wrapper исключён для отсутствия
self-hash recursion): `43388867cac2ed59171a32ce7bd6389d3b649017cc5f1eef26c26d007db19e6c`. Root отдельно измеряет wrapper SHA ниже.
Wrapper сверяет exact file set/bytes **до** исполнения harness; harness повторяет
approval check перед каждым connection path. Changed-harness import-marker probe
подтвердил отказ до его выполнения.

Revision artifact digest: `301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1`.
Это отдельный per-revision hash, не directory bundle или whole-registry hash.

```text
e0fef5357ac1b25431474416a569994d118e4907d83fde1e6460bfb334dc7fea  __init__.py
6460f815ecb53436981c3633769a5792642824923197f5cf15277c31f356a242  catalog.py
f746049fc8579a22f3d15c0c0764dc3db30ac74754c43c2851ba75eb6045504b  errors.py
16394ef23a5074c5c42c7780b30e15389c5eb4e6b03fb79a0afc1539db18fe39  journal.py
ef4189a61f162c81dda01b6602eae3a362c242e95ee954c6c971db9ff6404116  manifest.json
55e5d7caca47c6bbd243f1e02e9e8a764b163067b16cd8eb41052967e4c78a09  manifest.py
19450cd978b88df859aa6f4d33ad745f48fb4f0b55a17850aa875e75b66a0194  revisions/0001_contract.json
98da0597f9e4d6a3d21326a310496b790753a5d9e766cfec8005d84641dd2ac9  revisions/0001_product_api_budgets.sql
1a89417e8d0ed0684ad1055568dacea57b108b38b20ba76470871e5faad2c146  revisions/__init__.py
ae3c42d51a7e7e37ee293b2c64f73addd421cf792b63af6bed6c36b1ed5f24f5  revisions/catalog_v1.py
c872f3746c0df17c03bb6c87db8b8bebd22713bc326fca83b43e3aa9f8dfed5a  revisions/journal_v1.sql
375a6f68ca9024895e463584b7f79201b48500ab527d9cdcab16fdc0b2f41504  runner.py
b75801b2fdeac6f92ffe4796227b1c5ea85419d8f938040221e6e3924b492db5  tests/__init__.py
37820f3c76dfb53308496364a29b732831a749756b5944ba9c618b27da11ab93  tests/approved_postgres.py
3f0f1b4081caaf000ec2f30d648080d3012a13ed9f38d3bed41fe9b83b173968  tests/run_postgres.py
635291c1e14b3c6a18ab8371a53d7e7ff63be48e51f0b1cd1b5d2e16bb8722fc  tests/test_pure.py
```

Actual строки матрицы пройдены ROOT один раз на утверждённом package.
Это bounded synthetic contract proof; production migration/полная legacy
compatibility этим результатом не подтверждаются.


## Independent ROOT run, артефакты и cleanup

30.10.2026 координатор независимо прочитал source/guards, измерил все 16 package
files, 15 SOURCE_PINS/approval target/revision и воспроизвёл **14 pure PASS за
0,588 с**. Затем только ROOT создал own DB и исполнил approved wrapper; author
не получал SQL grant и не делал второго одинакового SQL run.

| Evidence | Actual |
|---|---|
| Author source/pure | 14 PASS / 0 FAIL, 0,717 с; no app/driver/connect |
| Independent root source/pure | 14 PASS / 0 FAIL, 0,588 с |
| Independent root actual harness | 13 PASS / 0 FAIL / 0 ERROR / 0 SKIP, 14,7611668957 с |
| Root preflight | PG160015, intended DB/user/DB owner matched; 7 765 015 bytes; maxlocks64; otherclients0 |
| Fixture13 | Предварительно существовавший rolsuper=True, disabled internal trigger negative выполнен; никаких role changes |
| Process | outer EXIT0/reaped; все blocker/runner/control/CLI child connections закрыты |
| Independent post-teardown | fresh root connection: все non-system tablelike relations + sequences=0 |
| Root normal DROP | DBexists0 / ownconns0 / otherclients0 / maxlocks64; SQL_SLOT_RELEASED |

Приватные artifacts (не включены в Git):
`/srv/projects/api-modernization-test-env-20261029/private-schema-migration-runner-20261030/`.
Автор прочитал их только через filesystem и сверил точные SHA256, без DB connect:

```text
08dd9c5e580efb9a2716750a14b78394a53ebb4b65fc4123376956d5c7206512  run.log
87add767de3b3fc9b1065a2b3299ff38767adb38bad4caf4cdb2a4a68f6a0d55  summary.json
4edeac0d373bd39b1f641ac970f338bc3bd950c4f049786fb6bde5d5a890d162  preflight.json
```

Все source review corrections (literal preservation, late verifier import,
guards/approval wrapper, active FK triggers, test09 lock-safe snapshot) выполнены
**до первого SQL**, не являются baseline production failures. После PASS package
16 files не менялся; обновлён только этот report. Полный source bundle повторно
сверен с `c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e`.

Foundation не включён в startup, не меняет Compose/managed mode и не становится
единственным владельцем schema. Отдельные ownership cutover/full bootstrap/real
old binary compatibility, dump/restore, production activation, CI и вся M00–M19
остаются открыты; M16 не объявляется целиком завершённой.
