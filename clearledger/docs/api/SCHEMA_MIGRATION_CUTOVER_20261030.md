# M16: default-off managed Core budget cutover, 30.10.2026

Статус: **IMPLEMENTED + INDEPENDENT ROOT SYNTHETIC VERIFIED: 2 PASS,
0 FAIL/ERROR/SKIP за73,352878565 с**. Author выполнил только source/AST/compile;
app-import/SQL выполнял исключительно ROOT один раз после review/freeze.
Изменения не включены ни в каком окружении; merge/deploy/Docker build/production
activation/restore/full CI не выполнялись. M00–M19 остаётся открытой.

## Источник и ownership

Immutable основа: `0f847b6f9bd94e1faff1476913ace2219749ced4`.
Ветка `agent/api-schema-migration-cutover-20261030`, существующее изолированное
worktree; no pull/new worktrees/shared-branch changes. Прочитаны canon/CLAUDE,
принятый SCHEMA_MIGRATION_DESIGN и SCHEMA_MIGRATION_RUNNER, реальные bootstrap,
startup marker/lifespan/readiness и preparation/seed sources.

Разрешённые изменения: app/config.py, app/database.py, app/main.py, новый
app/services/schema_version_gate.py, два новых isolated harness/wrapper и этот
отчёт. Root расширил scope на server/Dockerfile после independent source review:
он ранее не доставлял schema_migrations; добавлена одна COPY строка. Это source
packaging gap для default-off feature, не production incident.

**Frozen Foundation 16 файлов неизменен**:
`c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e`.
Manifest/V1 verifier/SQL/старые tests/requirements/Foundation report не менялись.
Другие lazy/seed DDL owners и существующий startup lock не переделывались.

## Новый режим и точные guard paths

Config по умолчанию:

```text
managed_core_budget_enabled = False
managed_core_budget_expected_database = ""
managed_core_budget_expected_user = ""
```

Expected DB/user обязательны только при включении. Namespace фиксирован core.
Никакого переключения режима в конфигурации стенда/Compose/environment не было.
Legacy standalone public/Core остаётся прежним default: при off не импортируется
новый helper/frozen verifier в этих branches и не добавляется SQL gate.

1. `_prepare_database_once`: read-only engine gate перед instance_id, **до**
   app_startup_runs CREATE/lookup и completed-marker return. Существующая отметка
   контейнера не разрешает обход head/schema проверки.
2. `create_all`: gate на **его фактическом AsyncConnection** до прежнего namespace
   guard/PHONE/metadata DDL. Exact budget Table object исключён из table subset
   только в managed mode; модель зарегистрирована и остаётся в ORM/namespace
   metadata. Остальные tables/DDL order не перепроектируются. При off остаётся
   прежний `conn.run_sync(Base.metadata.create_all)`.
3. `/api/ready`: gate на `await db.connection()` до прежних archive/catalog/storage
   checks; failure даёт прежний generic 503. /health и /live не менялись, readiness
   не заменена SELECT1 и не выдаёт новые DB/schema/user details.

Helper не вызывает runner.execute/check/apply, не создаёт forced-core connection,
не apply/stamp/repair и не берёт owner advisory lock. Он использует frozen
manifest.load/Config.validate/state на raw driver **того же app connection**.

Перед raw fetch обязательно выполняется SQLAlchemy identity/probe: current_database,
current_user,current_schema, transaction_read_only/isolation. Так SQLAlchemy lazy
begin действительно начинает PG transaction. Затем проверяется реальный
`driver.is_in_transaction()` и frozen catalog/history. App path public отвергается,
даже если отдельный forced-core Foundation check успешен.

Engine helper перед begin задаёт только connection execution options repeatable-read
+readonly; timeout15s включает checkout, внутренний verifier timeout10s. На borrowed
create_all/readiness connection helper **не** begin/commit/rollback, не меняет
readonly/isolation/path/GUC, продолжает старый write workflow после SELECT gate.
SQLAlchemy/asyncpg transaction не вкладывается в ещё одну raw transaction.

Default PostgreSQL port при отсутствии явно нормализуется к5432. Реальный app URL
не используется для нового подключения и не теряет query/TLS options скрыто:
Foundation v1 не поддерживает URL query overrides, поэтому managed mode с такими
options safe-refuse; legacy off не меняется. Передача пароля/URL в сообщения
ошибок исключена — один generic RuntimeError/503, Config.dsn скрыт в repr.

Lifecycle lock A остаётся прежним pair(434532,1). Gate B readonly без повторного
lock, поэтому нет self-wait A→B. Это не делает direct create_all/manual/lazy DDL
owners cooperative и не отзывает их DDL privileges; единственный owner всей
legacy schema не заявляется. Конкурентный manual DDL и мутация connection options
другими владельцами требуют отдельного операционного контроля.

## Provisioning и packaging

Прагматичный порядок выбран root: **явный legacy bootstrap в Core → отдельный
frozen runner exact adopt → только затем явное включение managed flag с expected
DB/user**. Все исторические DDL от этого не становятся versioned. Не добавлен
скрытый filtered/bootstrap bypass/gate-disable parameter в публичный create_all.

Dockerfile теперь копирует app и schema_migrations в /app. Root отдельно source
проверил, что deployment pack уже отправляет server целиком; whitelist/skills/VM
не менялись. Runtime helper использует только существующие dependencies.

Harness проверяет Docker COPY layout и моделирует копирование app+frozen package
в временный runtime directory: child Python -I импортирует main/config/database/
helper из копии, проверяет default-off и frozen manifest, не запускает lifespan.
Copied-runtime import/default-off/frozen artifact probe прошёл ROOT. Это **не
actual Docker build/install/health**, который здесь NOT RUN. Source
app copy содержит прежние templates/assets; env/.env и рабочие данные не копируются.

## Выполненные source-only checks

```sh
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I \
  clearledger/server/tests/run_managed_schema_cutover.py --source-check
```

PASS: при AST-исключении только новых managed guards/трёх settings fields **целые
модули config/database/main совпадают с immutable baseline AST**, default flag
False; frozen16 digest совпадает; COPY lines/.dockerignore и kwargs ORM fixture
конструкторов сверены с actual model declarations. Все новые/изменённые Python
файлы скомпилированы через AST без app-import/DB/pytest collection.

App source насчитывает 334 literal declarative table names; это статическая
оценка, **не** измерение зарегистрированного metadata либо живого каталога.
App COPY source closure — 489 files / 17 114 637 bytes, frozen16 отдельный digest.
Approval wrapper ограничивает tree до1024 files/32MiB до чтения bytes.

## Пройденная actual matrix: один independent ROOT run

2 unittest items с последовательными профилями, оба PASS; named controls/variants
ниже являются частями этих items, не отдельными pytest/unittest counts.
SQLAlchemy observer видит только adapter statements, не все raw frozen SELECT;
никаких fake verifiers/metadata/seed/SQL counts. Негативы требуют actual persisted
bad state + ноль наблюдаемых DDL/DML и unchanged budget/journal snapshots.
Full ce94/5ce old binaries сейчас не требуются root и не заявляются проверенными.

| Control | Actual acceptance |
|---|---|
| P | copied runtime COPY layout/import/default-off/frozen artifacts, отдельный child |
| L1 | legacy public fresh+repeat; budget создаётся, journal не создаётся, gate probes0 |
| L2 | legacy Core fresh+repeat; gate probes0, реальная registered metadata |
| G1 | real App/Company/CompanyApp/PartnerClient/Installation+quota row; standalone exact adopt |
| G2 | actual engine helper receipt PG readonly/on+repeatable read+driver txn true |
| G3 | borrowed engine.begin receipt readonly/off+read committed; raw is_in_transaction true, workflow продолжается |
| G4 | unapplied head до первого marker: отказ без marker CREATE |
| G5 | managed direct create_all excludes budget has_table probe; budget OID/xmin/ctid/rows/journal unchanged |
| G6 | real _prepare_database_once + seed/preparation под существующим lock; marker1, readiness ready |
| G7 | existing completed marker всё равно выполняет gate и не повторяет legacy ALTER |
| N1 | 4 persisted variants: bad checksum / unknown revision / empty head / catalog default drift; startup+direct+ready reject |
| N2 | missing journal: reject до marker/metadata, без rename/index collision, real fixture recreate afterwards |
| N3 | wrong expected DB/user и unsupported URL query: managed-only refusal; absent port normalization5432 |
| N4 | valid forced-core check + app engine public: startup/direct/ready reject, public same-name sentinel preserved |
| N5 | journal applied, budget отсутствует: no automatic recreate ни marker bypass, ни direct metadata |

Ready negatives используют app_env=test и0 legacy archive probes, чтобы prod
storage mount refusal не маскировал gate failure. Старые rows/OID сравниваются
между действиями приложения; intentional fixture journal mutations/restoration
не выдаются за runtime row writes. Missing relations snapshot явный None.

Перед positive prepare прочитаны реальные seed/preparation sources: SQL/DML,
статические каталоги/карты/пакеты; outbound clients и scheduler/lifespan не вызываются.
ECOSYSTEM_COMPANIES задаётся только synthetic company; встроенные working connector
records не запрашиваются/не выполняются. Test fixtures не заменяют реальные seed.

## Выполненный root runner/guard/footprint/cleanup (повтор требует нового GO)

Использовалась только own api_managed_schema_cutover_test на synthetic127.0.0.1:33546,
PG16, clearledger/api_test_only. Root CREATE/DROP и единственный serial SQL owner;
author не подключался/не collect/app-import вообще; source/runner/matrix review
и единственный SQL run выполнены ROOT, worker SQL grant не выдавался.

Wrapper до исполнения harness сверяет весь app tree, frozen16, Dockerfile/
.dockerignore/requirements/pure safety helper/actual harness; wrapper hash root
измеряет отдельно (без self-hash recursion). Main/preflight/asyncSetUp/packaging
повторяют guard до первого app import/connection: own common safety flag1,
exact two URLs/raw specialized DSN, APP_ENVtest, scrubbed env allowlist, original
HOME, explicit synthetic SECRET/HOSTNAME/company, Python3.13.7, empty cwd,
testUPLOAD/privateEVIDENCE0700. No pytest/conftest import.

Preflight actual DB/user/DB owner, PG16/maxlocks64/otherclients0/DB<256MiB.
Бюджет: два full fresh profiles, четыре repeats (включая managed direct и startup),
один настоящий seed/preparation, serial <=400 tables/profile, DB<256MiB,
internal300s/outer330s+kill-after10s. Pool3 +control1 (обычно максимум3 активных),
оригинальный engine dispose; никаких parallel schema suites.

Teardown сначала закрывает все собственные app pools/sessions, затем DROP owned
views/materialized/foreign tables и batches **по8 tables** с CASCADE только в
свежей assigned DB/core/public/edge. После table batches удаляет пустые namespace
functions/types и восстанавливает public; root независимо сверяет все non-system
relations/sequences и0conns, затем normal DROP DB. Нет FORCE/terminate/role-wide
GUC/maxlocks изменений. Private run.log/summary/preflight/packaging-import.log
остаются вне Git; при FAIL failfast/cleanup и новый review, без auto retry.

```sh
cd /srv/projects/api-modernization-test-env-20261029/managed-schema-cutover-empty-test
timeout --signal=TERM --kill-after=10s 330s \
  env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 RUN_MANAGED_SCHEMA_CUTOVER_TESTS=1 APP_ENV=test \
  SECRET_KEY=managed-cutover-synthetic-secret-key-only HOSTNAME=managed-cutover-test \
  ECOSYSTEM_COMPANIES='managed-test|Synthetic company|Synthetic|energy' \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_managed_schema_cutover_test \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_managed_schema_cutover_test \
  SCHEMA_MIGRATION_TEST_DSN=postgresql://clearledger:api_test_only@127.0.0.1:33546/api_managed_schema_cutover_test \
  UPLOAD_DIR=/srv/projects/api-modernization-test-env-20261029/managed-schema-cutover-test-uploads \
  /srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I \
  /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/managed_schema_cutover_approved.py \
  --execute-approved-cutover-tests \
  > /srv/projects/api-modernization-test-env-20261029/private-managed-schema-cutover-20261030/run.log 2>&1
```

## Exact source checkpoint

App tree SHA256: `8e002e545929bc08c6034818c1921a828092dc48195074e8e5ea101796cb8236`.
Tree digest: sorted relative file paths excluding __pycache__, name+NUL+fileSHA,
joined LF/final LF, then SHA256. Frozen tree digest отдельно указан выше.

```text
aaa894b69a30d8e9253bf3759ea627cb2d6a8709ed2046b7e7abf20e4e25d09d  server/Dockerfile
90c5da106f20fe90e31c899a88018ef741e6b3207a555fedbd58bafaa61780e8  server/app/config.py
ee4633ecc50be527ccb15eda8a53633b9129bb97daac4ed8f4aa751a57c0b0a6  server/app/database.py
8a4f76e9ef8fe4c27418d8617b5d98b18d75ffbae2e6bbd24ac2994e9b488637  server/app/main.py
6e51660673e40188705e243c34de61c2e7b1f2cf9c93811bea476839460ba7e4  server/app/services/schema_version_gate.py
188a4b52a3baa47db6a405a7bc854539b8a893ece334909fd5cb8532e04fd447  server/tests/run_managed_schema_cutover.py
9ddb84c05921ceee195590f97ae1093888c2d265a6f86811c751d325c1fa886f  server/tests/managed_schema_cutover_approved.py
```

Actual результат: 2 PASS/0FAIL/0ERROR/0SKIP в независимом ROOT run; новая
проверка/author repeat после PASS не запускались. Настройки рабочих окружений
не менялись.


## Independent ROOT результат, private artifacts и завершение

Root независимо прочитал final source/guards, сверил AppTree489files/17 114 637
bytes, frozen16, wrapper/harness и5 explicit FILES pins +4 runtime review hashes,
воспроизвёл source-check без app/DB. После принятия матрицы **только ROOT** создал
own DB и выполнил approved wrapper; author SQL/connect/app-import не выполнял.

| Evidence | Actual ROOT результат |
|---|---|
| Unittest items | 2 PASS / 0 FAIL / 0 ERROR / 0 SKIP, 73,352878565 с |
| Legacy profiles | public fresh/repeat, Core fresh/repeat/default-off gate probes0 — PASS |
| Managed workflow | real full registered metadata, exact adoption, preserved budget rows/OID/head, engine/borrowed PG txn controls, startup seed/preparation/marker — PASS |
| Native readiness | прямой вызов реальной readiness function: ready и HTTPException503 на negatives — PASS; это не ASGI HTTP/browser e2e |
| Negative paths | before-first-marker, completed-marker, direct metadata, journal/head/catalog/config and actual app public namespace refusals — PASS |
| Packaging | source COPY layout + copied runtime imports/defaultOFF/frozen artifacts — PASS; Docker build NOT RUN |
| Preflight | PG160015, intended DB/user + DB ownership matched, 7 765 015 bytes, maxlocks64, otherclients0 |
| Process | outer EXIT0/reaped, all own pools/control/child closed |
| Independent post-teardown | fresh root connection: ВСЕ non-system tablelike relations/sequences0 |
| Root normal DROP | DBexists0 / ownconns0 / otherclients0 / maxlocks64, SQL_SLOT_RELEASED |

Логи содержат asyncio debug slow-task diagnostics и ожидаемые readiness refusal
warnings. Их наличие не объявляется новой production ошибкой; 73с — время
bounded synthetic suite, не production latency/SLO. Нулевые warnings не заявляются.

Приватные artifacts вне Git:
`/srv/projects/api-modernization-test-env-20261029/private-managed-schema-cutover-20261030/`.
Автор прочитал их только через filesystem и подтвердил SHA256:

```text
8f17e8800d59fb190e9b151d1eda23cd6cb9bdff1267b666c2a166d9c2d4ff57  run.log
65bf257f8f692ce69076b6591d14af52234cea47d04e659c530a2d6c2c2a336d  summary.json
334156624f9385cafcc8ef65ac4b88e346010678d303d4d65d9bcc7713650ecd  preflight.json
6566b1e83ce0d6b757d81d106dba8741e16754d1cdbbc24c5054ea87dcc0cec7  packaging-import.log
```

Source fixes (Docker COPY delivery и корректные missing-object snapshots/fixtures)
выполнены **до первого SQL**; baseline production failures не было. После PASS
семь runtime/test/Dockerfile source bytes/pins не менялись, обновлён только отчёт.
Все environment/Compose/service flags остаются default-off и не переключались.

Actual Docker build, full lifespan/background services, HTTP/browser e2e,
ce94/5ce archive execution, production backup/restore/permissions/activation,
полный CI и ownership остальных legacy/lazy DDL owners **NOT RUN / OPEN**.
Полный runtime DDL privilege withdrawal не входит в пакет. Общая программа
M00–M19 не объявляется завершённой.


## Интеграционная приёмка координатора

Source commit `f6588d191a3e81b431cdda42d039df4fa33bc419` перенесён в
integration как `46c0b53169d9a353c277c18962106e13bee76d74`. Проверены ровно восемь
файлов изменения, source HEAD=origin и отсутствие незакоммиченных правок.
Все восемь integration files совпали с исходным коммитом по SHA256; семь
runtime/test/Dockerfile файлов — с составом единственного ROOT SQL-прогона.
Frozen Foundation из 16 файлов также неизменён. После переноса повторного SQL
не было: исходники проверенного пакета не менялись. Обновлён только этот отчёт.

Независимый source review обнаружил недоставленный `schema_migrations` в
прежнем Dockerfile. Исправление COPY и copied-runtime import проверены до
прогона. Actual Docker build, полный lifespan, исторические архивы и рабочий
backup/restore остаются непроверенными. Новый режим выключен по умолчанию,
рабочие настройки и сервисы не менялись; M16 целиком не закрыта.
