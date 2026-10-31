# M16: изолированное доказательство dump/restore, 30.10.2026

Финальный bounded результат: **ROOT ATTEMPT5: 1 item / 1 PASS / 0 FAIL /
0 ERROR / 0 SKIP, 55.475807138718665s**. Четыре предыдущих actual failures
сохранены ниже с причинами и evidence; они не переписаны в PASS.
Автор выполнял чтение файлов, AST/compile и отдельно разрешённые ROOT
stdlib-only pure controls без app/driver/pytest imports.
App/driver imports, collect, подключения, SQL и Docker автором не выполнялись.
Только ROOT создавал/удалял две БД и исполнял каждый отдельно согласованный прогон.
После финального PASS тестовые source bytes заморожены; повторов не выполнялось.
Это не production restore tool и не завершение M16 или M00–M19.

## Источник и сохранённые границы

Предыдущие clean HEAD и origin авторской cutover-ветки совпадали:
`f6588d191a3e81b431cdda42d039df4fa33bc419`.
Новая ветка `agent/api-schema-restore-proof-20261030` создана в том же изолированном
worktree от EXACT integration
`2578ec8fbef3c8a21fa274df72f96b86cd3e06af`;
integration cutover `46c0b531` — его предок. Pull, новые worktrees и изменения
общих веток не выполнялись.

Ownership ограничен этим отчётом и двумя новыми isolated файлами:

| Файл относительно clearledger/ | SHA256 перед root review |
|---|---|
| server/tests/run_schema_restore_proof.py | 784b38d10f389d24389432a234dce6af77409884e5057eb5754e8207ae779831 |
| server/tests/schema_restore_proof_approved.py | 8f3c1ddeba0497257c7b91004cd7441a9a6313825d53d49ecf1c9ab77510f619 |

Повторно измерены по sorted relative path + NUL + SHA256(file), LF/final LF:

| Frozen source | Файлов / bytes | Tree SHA256 |
|---|---|---|
| server/app | 489 / 17114637 | 8e002e545929bc08c6034818c1921a828092dc48195074e8e5ea101796cb8236 |
| server/schema_migrations | 16 / 66799 | c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e |

Runtime/config/main/database, Dockerfile, Foundation manifest/V1 verifier/SQL,
старые тесты и отчёты не изменяются. Default managed flag остаётся OFF.
Проверяется доставленный текущий app, без fake policy/catalog/advisory/SQL.

## Pre-import guards и root-only запуск

Wrapper сначала требует ровно `--execute-approved-restore-tests` и dedicated
`RUN_SCHEMA_RESTORE_PROOF=1`. Opt-out возвращает exit2 до импорта harness/app/driver.
Root отдельно pin-ит SHA wrapper; wrapper pin-ит harness, requirements, Dockerfile,
общий pure partner guard, все app bytes и frozen package. Проверяется наличие
immutable integration commit и его ancestry относительно HEAD.

До app/driver imports обязательны Python3.13.7 и exact executable, исходный HOME
из passwd текущего uid, точное clean environment без дополнительных ключей,
APP_ENV=test, synthetic hostname/secret/company, равные source DATABASE_URL и
TEST_DATABASE_URL, отдельный exact target URL без query/fragment и только
127.0.0.1:33546. Все значения заданы в `verify_approval`; URL/credentials не печатаются.
Существующий `partner_test_safety_error` вызывается до app/driver imports;
pytest и разрушительный server/tests/conftest.py не используются.

ROOT заранее готовит три пустых каталога с owner uid запуска и mode0700:

```text
/srv/projects/api-modernization-test-env-20261029/schema-restore-proof-empty-test
/srv/projects/api-modernization-test-env-20261029/schema-restore-proof-test-uploads
/srv/projects/api-modernization-test-env-20261029/private-schema-restore-proof-20261030
```

Точный argv запуска (из первого пустого cwd, env строго из wrapper; HOME исходный):

```text
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I -B /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/schema_restore_proof_approved.py --execute-approved-restore-tests
```

Wrapper не доказывает сам факт выдачи ROOT разрешения: это отдельный review и
ownership serial SQL window. Автор не запускает даже opt-out до этого review.
ROOT создаёт и позже удаляет только `api_schema_restore_source_test` и
`api_schema_restore_target_test`; harness не содержит CREATE/DROP DATABASE.

## Контейнер, TCP, место и дочерние процессы

До первого app import harness требует mapping контейнера
`api-modernization-test-20261029`: только 127.0.0.1:33546 на 5432/tcp;
pg_dump/pg_restore16.15; TCP pg_isready. Затем на обеих host TCP БД проверяются
actual name/user, owner clearledger, PG160015, maxlocks64, data_directory,
нулевые другие клиенты и отсутствие user relations/functions/types/extensions.
Host TCP system_identifier обеих БД сопоставляется с результатом TCP psql внутри
этого же контейнера. Default UNIX init-сокет не используется. Control preflight
ROOT к служебной БД остаётся отдельной операцией ROOT, не скрыт в harness.
Новые readonly native controls в SOURCE и restored TARGET требуют точные
pg_catalog types16/25/1043 (bool/text/varchar), cast1043→25 method=b/context=i/
castfunc0, standard_conforming_strings=on; internal immutable strict text equality/
inequality operators с проверкой argument/result types, namespaces и negator/
commutator links; effective database/default collation и actual version identity
между БД. Они проверяют ARRAY cast distribution, ANY/=ALL/<>ALL true/false/NULL,
AND/OR nullable guards и несовпадение при перестановке элементов.
Оба набора SELECT выполнены ROOT в attempt5; их private receipts byte-identical.

Docker client использует только локальный unix:///var/run/docker.sock и отдельный
пустой DOCKER_CONFIG в private evidence, без наследования context/proxy/credentials.
Каждый argv проверяется по literal allowlist; shell не используется. Пароль
передаётся в environment, Docker `--env PGPASSWORD` содержит только имя.

Основные literal argv (каждая строка — отдельный процесс):

```text
docker inspect --format {{json .NetworkSettings.Ports}} api-modernization-test-20261029
docker exec api-modernization-test-20261029 df -P -B1 /var/lib/postgresql/data
docker exec api-modernization-test-20261029 pg_dump --version
docker exec api-modernization-test-20261029 pg_restore --version
docker exec --env PGPASSWORD api-modernization-test-20261029 pg_isready -h 127.0.0.1 -p 5432 -U clearledger -d api_schema_restore_source_test
docker exec --env PGPASSWORD api-modernization-test-20261029 timeout -s TERM -k 5 5 psql -X -w -h 127.0.0.1 -p 5432 -U clearledger -d api_schema_restore_source_test -Atc "SELECT system_identifier FROM pg_control_system()"
docker exec --env PGPASSWORD api-modernization-test-20261029 timeout -s TERM -k 5 60 pg_dump -w -h 127.0.0.1 -p 5432 -U clearledger --format=custom --dbname=api_schema_restore_source_test
docker exec --interactive api-modernization-test-20261029 timeout -s TERM -k 5 20 pg_restore --list --format=custom
docker exec --interactive --env PGPASSWORD api-modernization-test-20261029 timeout -s TERM -k 5 90 pg_restore -w -h 127.0.0.1 -p 5432 -U clearledger --format=custom --exit-on-error --dbname=api_schema_restore_target_test
```

ROOT source checkpoint подтвердил BusyBox1.37.0 timeout с `-s/-k`; GNU long
options не используются. Потоки передаются без shell и без архива в контейнере.
Archive stdout ограничен64MiB; stderr1MiB, остальные stdout2MiB. Inner timeout
завершает PG child, host deadline больше; при stream failure/cancellation harness
ждёт inner deadline с запасом прежде чем kill/wait Docker client. Все stream
tasks cancel/await, процессы wait/reap; killing client не выдаётся за остановку
server-side exec. Общий run deadline420s + отдельный cleanup deadline120s.

Свежий df проверяется перед работой и вокруг bootstrap/dump/restore:
PGDATA total=1GiB, initial free>=384MiB, до dump/restore>=256MiB, после>=128MiB.
Каждая БД<=128MiB, user tablelike/sequences<=420, ожидаются >300 registered tables;
snapshot<=50000 rows/32MiB logical payload. Host evidence free>=128MiB.
Это abort bounds, не capacity/SLO обещание. При нехватке места нет изменения
GUC/maxlocks/container/image/network, автоматического retry или расширения scope.

## Один actual сценарий и независимые controls

| Этап | Наблюдаемое доказательство | Итог attempt5 |
|---|---|---|
| P0 | Guards, exact container TCP/cluster/PG version/owner/empty DB/space | PASS |
| P0a | Native types/cast/operators/effective collation, =ANY/=ALL/<>ALL true/false/NULL/Boolean/order controls в обеих БД | PASS |
| R1 | Actual зарегистрированная metadata в fresh Core, legacy create_all; реальные static company/app/client/company_app/installation и budget; public same-name sentinel | PASS |
| R2 | Frozen runner explicit adopt, managed preparation с настоящим seed и completed marker; native readiness | PASS |
| R3 | Dispose всех source app pools, others0, logical baseline, закрытие host controls; actual custom-format pg_dump | PASS, exit0 |
| R4 | Fresh target без app bootstrap; actual pg_restore --exit-on-error, затем equality source/restored catalog/data/sequence state/journal | PASS, exit0; logical equality |
| R5 | Независимые fixture UUID/parent join/budget7values/sentinel/adopted revision/completed marker goldens; отсутствие public journal | PASS SOURCE+TARGET |
| R6 | Gate на настоящем target app connection: readonly/repeatable read/driver transaction; frozen runner readonly check | PASS |
| R7 | Два managed preparation через прежний startup lock и восстановленный marker; native readiness; unchanged target budget OID и полная logical snapshot | PASS |
| R8 | Настоящий ORM UUID lookup/update/flush/rollback; полная logical snapshot возвращена | PASS |
| N1 | Только target: повредить artifact checksum журнала; startup отказывает ДО marker write, readiness503; наблюдаемых DDL/DML0 | PASS |
| P1 | Восстановить точное прежнее checksum значение; gate/check/preparation/readiness и все logical hashes вновь положительны; source неизменён | PASS |
| C0 | Serial bounded cleanup обеих own DB: relations/sequences0, otherclients0, maxlocks64, no child processes | PASS; ROOT independent normal DROP |

Это один сквозной item с отдельными названными этапами, а не повтор старой PASS
suite. Summary отдельно содержит items/passes/failures/errors/skips/seconds;
NOT RUN не считается PASS или SKIP. Elapsed не является SLO.

Два независимых физических источника snapshot сравниваются по нормализованным
каталожным признакам: schemas/owners/ACL, tables/columns/default/nullability,
constraints/FK, indexes, triggers с семантикой без новых internal trigger names,
functions, enums, sequences, views, extensions, policies и inheritance. Данные
каждой таблицы сравниваются как sorted canonical JSON row hashes с counts;
sequence last_value/is_called сохраняются. OID/xmin/ctid/physical sizes не входят
в cross-DB equality. Отдельные статические fixture goldens исключают ситуацию,
когда потеря одной и той же fixture остаётся незамеченной только snapshot helper.
Внутри target repeat дополнительно проверяется сохранение его budget OID.

TOC читается лишь для совместимости fresh public namespace: если архив содержит
явный SCHEMA public, harness удаляет только пустой public в проверенной fresh
target перед его реальным восстановлением; иначе сохраняет template public.
Нет --clean, --create, --disable-triggers, фильтрации TOC или пропуска dump errors.
Ownership/ACL не отбрасываются через --no-owner/--no-acl. Listing не заменяет R4.

## Evidence, cleanup и ограничения

Archive `synthetic.dump` создаётся mode0600 только в private0700 evidence вне Git,
не в preview. Сохраняются SHA256 и size; dump и raw rows не публикуются.
Summary содержит безопасные phase/type/фиксированные harness reasons, counts,
hashes, argv без credentials и return codes. Driver traceback/SQL/URI не выводятся.
Baseline failures будут записаны только при фактическом появлении.

В finally закрываются app pools, streams/tasks/children, затем own controls.
Повторная identity проверка отказывает при неожиданном клиенте/owner/namespace.
Views/materialized/foreign relations удаляются отдельно; tables группами<=8 за
одну транзакцию, оставшиеся sequences по одной. Core/edge functions/types удаляются
после таблиц. Проверяются все non-system tablelike+sequences, а не только budget.
ROOT затем независимо проверяет обе БД/clients/locks и выполняет обычный DROP;
FORCE/terminate, role/server GUC и чужие объекты не используются.

Автор выполнил AST/compile обоих новых файлов без exec, source checks отсутствие
top-level app/driver imports и shell=True, измерение frozen tree pins. Никакие
старые suite не запускались. Actual действия ROOT перечислены ниже.

Доказательство относится к текущим source bytes, одному PG16 synthetic container
и bounded dataset. Full lifespan/background jobs, ASGI/HTTP/browser, старый binary,
CI, Docker build, production backup/restore, outage/RPO/RTO, deploy/merge и включение
managed mode не проверяются. Исторический bootstrap не объявляется versioned;
владельцы остальных legacy DDL и режим эксплуатации не меняются.

## Actual baseline failure и исправление до повторного review

ROOT принял первый source snapshot: harness
`c4f13738d449a9d96daa05bec0cd597a3ba14495e06da7c4d80c1d4b2a13dbb3`,
wrapper `b243b4246143732ad87bf39abb2fda2fbba41ba73f84620f260220abd269e3a4`.
Первый actual ROOT run завершился exit1/reaped: **1 item, 0 PASS, 1 FAIL,
0 ERROR, 0 SKIP, 29.53350363392383s**; outer31.834693412s.
На phase application-bootstrap получен UndefinedTableError в independent golden
parent join. Автор ошибочно указал core.apps/core.company_apps. В immutable app
App.__tablename__=`eco_apps` ([models.py:8233](../../server/app/models.py#L8233)),
CompanyApp.__tablename__=`eco_company_apps`
([models.py:8270](../../server/app/models.py#L8270)). Это ошибка тестового query.

ROOT разрешил bounded source correction: только две ссылки в новом harness,
обновлённый harness pin и новые phase checkpoints вокруг metadata/fixture/adopt/
managed preparation/native readiness/independent goldens. Runtime/Foundation
сохранены. Добавлена AST-проверка трёх fixture table references против настоящих
`__tablename__` исходников без ORM импорта; AST/compile PASS без exec. Повтор
обоснован исправлением фактически упавшего теста, автоматических retries нет.

Attempt1 private evidence: `private-schema-restore-proof-20261030-attempt1-bootstrap-golden-failure`.
Summary SHA256 `e8f7c8027347509388e8780b428bf78f956f9d373ded3184844f34d7f96108c1`;
root log SHA256 `5b261258d8737fe7ec1e661855e947d95c8858d7a94a333fd6cc5a3bbd6674cd`.
Summary отдельно подтвердил identity/space и cleanup PASS обеих БД:
ALL non-system tablelike/sequences0, otherclients0, maxlocks64, livechildren0.
ROOT независимо проверил и обычным DROP удалил обе БД: DBexists0/ownconns0/
otherclients0/max64, SQL slot released. Dump/restore/target gates/negative control
не достигнуты; это NOT REACHED, а не SKIP/PASS. P0/C0 выполнены, матрица R1–P1
в полном объёме остаётся неподтверждённой.

Проверены только filesystem старых cwd/uploads: оба uid1000, mode02700 (setgid,
права0700), symlinkFalse, entries0. Ничего не удалялось. ROOT создаёт fresh private
evidence после нового review; worker по-прежнему не имеет SQL/import/Docker grant.

## Attempt2: действительное восстановление и отказ строгого сравнения

ROOT принял correction source harness
`a78ccb9f2bce4e789dbdc8d5341c7c75e65aa72c28fbe505e810ada822f505f4`,
wrapper `dca0685ac6e5cb8027a50d2c7cf4f1490cf3be384cc2059e610fb929df939e1b`.
Результат: **1 item, 0 PASS, 1 FAIL, 0 ERROR, 0 SKIP, 45.1783497845754s**,
exit1/reaped; outer47.571777007s. Source metadata/fixture/adopt/managed preparation/
readiness/independent goldens прошли. Настоящие pg_dump и pg_restore --exit-on-error
завершились exit0/stderr0. Archive1656611 bytes, SHA256
`f43d0b840dd59cce11625ac766e5e26271c4c5ee3681598c81d58e409df2b6dc`.

Следующая проверка отказала: ProofRefused, phase actual-restore,
`restored logical catalog/data differ`. Текущий снимок не сохранял сравниваемые
структуры, поэтому конкретное расхождение пока **НЕ УСТАНОВЛЕНО**. Exit0 утилиты
не считается успешной приёмкой восстановления. Никакой runtime/production диагноз
из этого результата не следует. Все последующие target gate/marker/readiness/
ORM/negative/recovery этапы — NOT REACHED, harness skips0.

Private evidence `private-schema-restore-proof-20261030-attempt2-catalog-comparison-failure`:
summary SHA256 `cc2b69a2a2228ef1bd3ff40c51b4d1b5e2c4fcbf1d8404e699f58d18b61357bf`,
log SHA256 `a2f0118fabbaa509535d6ca1fc8b7a38150b16c649bc154087a966c46ea99328`.
Cleanup PASS: обе БД ALL non-system tablelike/sequences0, otherclients0, max64,
children0. ROOT fresh postcheck и normal DROP: exists0/ownconns0/otherclients0/max64.

Следующая source correction **только diagnostic**, с отдельным review до SQL:
до comparison сохраняются source-before/target-after snapshot JSON (counts/hashes,
<=1MiB каждый) и canonical catalog metadata lists (<=16MiB каждый) в private0700
evidence; restore-diff.json<=16MiB указывает category/table/count/hash differences
и bounded metadata samples. Business row values не сохраняются. Hash calculation,
строгое `before == after`, SQL/goldens/bounds/cleanup не менялись; ожидания не
подгонялись. AST/compile новых bytes PASS без exec. Новый actual run нужен только
для разрешения наблюдённого failure, после отдельного root review.

## Attempt3: раннее закрытие stdin TOC reader

Диагностический snapshot был принят ROOT с harness
`f1d65e3d492fef09f85a206265a7a40c5da817fa1f3fcf050f4d32a3a5297dbb`,
wrapper `1b8e35cc071bbef097e1965b6e310b0964c82190874448480e89c9ae075cb272`.
Attempt3: **1 item, 0 PASS, 1 FAIL, 0 ERROR, 0 SKIP, 32.79945514816791s**;
outer35.179094355s, exit1/reaped. После source phases/goldens и actual custom dump
exit0 процесс TOC pg_restore --list раньше закрыл stdin: feeder получил
BrokenPipeError, phase quiesce-and-dump. Actual restore/target snapshot/diff не
достигнуты; причина несовпадения из attempt2 по-прежнему неизвестна.

Private evidence `private-schema-restore-proof-20261030-attempt3-pipe-failure`:

| Artifact | Bytes | SHA256 |
|---|---|---|
| summary.json | 5034 | f458685e74cd1fc3aa1425e85ad8f734f21c781d0ed60fa2e963d1cae3b570d6 |
| source-before.snapshot.json | 49545 | 88d7ab11a3e1bf5218c5b506fe36dfbdf9ad97dfea09b5b6d9f1ac68985f85c4 |
| source-before.catalog.json | 1586715 | c1418b2f630ff68fcf7d6fc5812aa74e27014af9e56004130dfd2ccd30f956ee |
| synthetic.dump | 1656590 | 74ade870ef6886750344757177d6cc3609f8b6fa414b30cd27da732fe4008571 |

Cleanup PASS, ROOT fresh postcheck/normal DROP обеих БД:
relations/sequences0, DBexists0/ownconns0/otherclients0/max64, children0.

ROOT разрешил минимальную source correction feeder: обрабатывать только ожидаемые
BrokenPipeError/ConnectionResetError в write/drain и wait_closed. Это соответствует
поведению input early-close, описанному в [Python3.13 Process.communicate](https://docs.python.org/3.13/library/asyncio-subprocess.html#asyncio.subprocess.Process.communicate)
(reference предоставлен ROOT). Bounded stdout/stderr по-прежнему полностью
drain/await, child returncode обязан быть0; nonzero, timeout, output limits и
cancellation не подавляются. В finally теперь сохраняется каждый child rc/phase/
early-close flag, включая failure. Unbounded communicate buffer не используется.
Strict snapshot comparison и goldens не менялись, каталог не нормализовался.
Новый root run требует отдельного review исправленных SHA; blind retry отсутствует.

## Attempt4: raw diff локализован до представления casts

ROOT принял feeder correction SHA из верхней таблицы. Attempt4:
**1 item, 0 PASS, 1 FAIL, 0 ERROR, 0 SKIP, 45.322103673s**,
outer47.648629067s, exit1/reaped. Dump и restore --exit-on-error exit0/stderr0;
early-close feeder issue устранён. Strict raw comparison снова отказал, но
диагностические snapshots сохранили точную причину:

- data/totals differences:0; 11 остальных catalog categories полностью равны;
- из1322 constraints отличаются только45 CHECK definition strings;
- из1192 indexes отличаются только5 definition strings;
- ROOT сопоставил все50 по schema/table/name: остальные fields/flags равны;
- source ARRAY of unbounded varchar literals с общим cast к text[] после
  restore deparse превращается в ARRAY of per-element varchar→text casts;
  index deparser дополнительно расставляет скобки этих же cast expressions.

Target managed/ORM/negative/recovery stages пока NOT REACHED. Этот результат
ещё не означает успешную приёмку restore. Категории/данные не исключались из
сравнения и raw metadata не отбрасывались.

Private evidence `private-schema-restore-proof-20261030-attempt4-cast-representation-diff`:

| Artifact | Bytes | SHA256 |
|---|---|---|
| summary.json | 7875 | 50e5696b4e82500a2163fab19f0d0c8b6b3a697e00615a37b713efef704e7590 |
| restore-diff.json | 11142 | 9f5bfc46c61e7769ee59c5174bb530fc6c0b80c4ca6367826b47f8b747abcd9a |
| source-before.catalog.json | 1586715 | c1418b2f630ff68fcf7d6fc5812aa74e27014af9e56004130dfd2ccd30f956ee |
| target-after.catalog.json | 1587545 | 60411bb9f794e314f8510e79f5814432abf14a8484cdd66fab24e8c470c49faa |
| synthetic.dump | 1656650 | 29f048d26ecd165e9bb93d955181328551765015272c2a41f100e0909d80bb92 |

Root log SHA256 `9605098ab6dbcdecf7b518082fb2406fb6a40b72b90cc5d0f3953960337fd264`.
Cleanup/fresh postcheck/normal DROP обеих БД PASS: relations/sequences0,
exists0/ownconns0/otherclients0/max64, no worker grants.

ROOT сверил primary PG16 [§4.2.12 Array Constructors](https://www.postgresql.org/docs/16/sql-expressions.html#SQL-SYNTAX-ARRAY-CONSTRUCTORS),
[varchar/text binary compatibility](https://www.postgresql.org/docs/16/typeconv-func.html)
и [pg_cast.castmethod](https://www.postgresql.org/docs/16/catalog-pg-cast.html).
На этом основании ROOT затем принял bounded source proposal и разрешил автору
только stdlib pure execution. SQL/Docker/app/driver grant автору не выдавался.

## Узкая semantic representation и pure evidence

Реализован test-only lexer/token parser четырёх **exact** PG deparse templates:

```text
ARRAY[L::character varying, ...]::text[]
(ARRAY[L::character varying, ...])::text[]
ARRAY[L::character varying::text, ...]
ARRAY[(L::character varying)::text, ...]
```

L — plain single-quoted literal с сохранёнными doubled quotes либо exact NULL.
NULL и строка 'NULL' — разные typed nodes. Полный выбранный fragment разбирается
и сверяется с exact reconstructed template; whitespace/case/formatting за его
границами сохраняются. Tokens несут offsets и raw text; внешний SQL не пересобирается.
Только complete supported cast fragment становится typed tuple с ordered literal
nodes. Это не строковый marker и не SQL для выполнения.

Typmods, qualifiers, mixed/неизвестные forms, comments, E/U&/dollar ambiguity,
backslash и соседние concat literals остаются raw. Lexer не разбирает содержимое
quoted identifier как SQL. Скобки поглощаются только как часть этих четырёх forms.
Нет общего lowercase, strip casts/parentheses, boolean rewrite, catalog ignore
или expected object/pairs lookup. Только definition cell CHECK constraint либо
index получает representation; все остальные fields/flags и11 иных категорий exact.
UNKNOWN не получает семантическую эквивалентность другой строке.

Strict `before == after` сравнивает полный logical catalog/data snapshot формата
`varchar_text_array_deparse_v1`. Raw catalog row lists остаются в *.catalog.json;
отдельные *.raw-catalog-hashes.json<=1MiB сохраняют прежние raw hashes.
restore-diff.json разделяет raw representation и logical differences.
Созданные harness archive/summary/JSON явно fchmod0600: umask сам по себе не гарантирует
это при default ACL родительского каталога. Все остаются внутри private0700.

После AST/source check ROOT разрешил автору stdlib-only исполнение:

```text
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I -B -S -
```

Stdin launcher проверил exact harness SHA, загрузил только inert harness module
через runpy.run_path с не-__main__ именем, вызвал pure_canonical_controls и проверил
отсутствие app/asyncpg/sqlalchemy/pytest в sys.modules. App/settings/driver/collect/
SQL/Docker/network не вызывались. Первая pure receipt на source c79acf3d...:
4 positive,22 negative,14 raw-unknown,50 changed pairs/2514 metadata rows;
0.20349273923784494s. После новых обязательных замечаний рецензента код расширен
отдельными NULL/quote/outer boolean negatives и явным backslash отказом.

Вторая pure receipt на snapshot921eab31: **20 positive,28 negative,
17 unknown-raw controls PASS; все2514 metadata rows logical equal, включая50
изменённых pairs/53 array fragments/205 elements; 0.18263450916856527s**.
Объекты сопоставлялись по настоящей metadata identity, не по allowlist ожидаемых
имён. Corpus bytes pinned на два SHA attempt4; flags/outer logic/literal changes
проверяются отдельными controls. Counts — типы assertions, не число pytest items.

Negative controls сохраняют различия case/spaces/values/order/NULL-vs-stringNULL,
doubled quotes, types/typmods/qualification/collation, ANY/ALL/operators,
NULL guards/AND/OR, outer parentheses и всех constraint/index flags.
Quoted identifier/embedded ARRAY literal/typed marker collision и unknown syntax
не становятся supported fragment. На этом source этапе native SELECT были NOT RUN;
их финальный actual результат указан ниже.

Private вторая receipt:
`private-schema-restore-pure-20261030-reviewer-controls/pure-receipt.json`,
SHA256 `e52fc8e25b7af9fff802ef76436bd6534e8a96d73ee1afabb28b9de4e1294416`.
Первая receipt сохранена отдельно:
`private-schema-restore-pure-20261030/pure-receipt.json`,
SHA256 `2fb026bbdda47cbd306cbcb8ab8ba7c8534666e79e8ea4b06236f6789fc5efad`.
Затем требовались независимый ROOT pure/source review и новое exact approval
до actual run. Ни один из четырёх предыдущих failures не переписан в PASS.

## Source reviewer concern: nested scope и новая pure receipt

ROOT независимо воспроизвёл исходный pure snapshot c79acf3d...:
4 positive/22 negative/14 raw-unknown,50 pairs/2514 rows PASS,0.191978740s;
отдельный reviewer проверял этот immutable snapshot. Рецензент нашёл конкретный
scope gap: после отказа внешнему nested ARRAY старый scan продолжал поиск и
нормализовал внутренний ARRAY. Это не затронуло observed50 и не доказало ложную
семантику, но нарушало обещанный unknown/nested raw-or-refuse.

ROOT разрешил снять freeze только для этого исправления и расширения readonly
native prerequisites/matrix. Новый canonical_sql сначала проверяет **все**
ARRAY constructors, включая case-варианты для обнаружения отказа. Любой unknown/
nested outer ARRAY оставляет **весь SQL raw**, без поиска внутренних supported
fragments. Mixed/lowercase constructor не становится supported формой.
Добавлены парные controls: nested/mixed-case/NULL-containing outer constructors,
valid+unknown fragments в одном SQL, соседние/с newline concat literals и
backslash ambiguity. Обе стороны пары обязаны остаться raw и различными.
Четыре supported templates и outer SQL/flags не расширялись.

На текущем exact source SHA после AST/source check выполнен один разрешённый
worker stdlib-only pure run: **20 positive,38 negative,37 raw-unknown controls
PASS; 2514 rows/50 changed pairs/53 fragments/205 elements; 0.24559069331735373s**.
App/driver/pytest/settings/SQL/Docker/network отсутствовали. Повтор обоснован
новым concern/source fix, предыдущие receipts сохранены без перезаписи.

Private latest receipt:
`private-schema-restore-pure-20261030-nested-controls/pure-receipt.json`,
SHA256 `061993a5b2e51080a1a4819e668d1dbe024110503ab325d5e8029ee1bebbc05e`, mode0600.
Предыдущие20/28/17 counts относятся к snapshot921eab31, а не к текущей версии.

Будущие native controls теперь выполняются readonly в обеих БД; explicit
`<> ALL` true/false/NULL и12 nullable/AND/OR inputs добавлены к прежним9 truth
cases и order-negative. Private *.native-prerequisites.json<=1MiB каждый хранит
type/cast/operator/collation receipts без credentials. Host evidence cap с двумя
такими файлами<=118MiB при free>=128MiB. На момент freeze SQL controls были
**NOT RUN**; последовавшие ROOT review/approval/actual result перечислены ниже.

## Финальный ROOT attempt5: полный bounded PASS

ROOT независимо измерил exact верхние harness/wrapper SHA и unchanged app489/
Foundation16, проверил полный source delta и исправление nested scope/native
prerequisites. Его pure run на final784b38d1:20 positive/38 negative/37 raw-unknown,
2514 rows/50 pairs/53 fragments/205 elements PASS,0.208363465s; app/driver/pytest/
SQL/Docker/network отсутствовали. Отдельный reviewer проверял **c79acf3d**, не
final784; его source-only заключение не приписывается финальному снимку. R1/native
fixes финального снимка проверены ROOT источником, pure controls и actual run.

После отдельного exact approval ROOT исполнил attempt5:
**1 item / 1 PASS / 0 FAIL / 0 ERROR / 0 SKIP за55.475807138718665s**,
outer57.92776507046074s, exit0/reaped. Все child commands exit0, livechildren0.
Actual pg_dump custom + actual pg_restore --exit-on-error действительно выполнились;
archive1656587 bytes. TOC public SCHEMA entry=False: target template public
сохранился, ветка условного DROP пустого public **не исполнялась**.

SOURCE/TARGET содержали одинаковые **347 relations и943 rows**; full logical
catalog/data snapshots byte-identical. Diff: logical catalog0/data0/totals0;
raw catalog отличается только прежними45 CHECK/5index cast deparse strings.
Все11 иных raw категорий exact equal; raw rows/hashes обеих сторон сохранены.
Native prerequisites/cast/operator/collation/ANY/ALL/<>ALL/NULL/Boolean/order
controls в обеих БД PASS, receipts1613 bytes byte-identical.

Restored actual app connection gate, frozen runner readonly check, два managed
preparation/marker repeats/native readiness, сохранение target budget OID/данных,
настоящий ORM flush+rollback — PASS. Checksum negative на restored journal
отказал startup до marker/DDL/DML и readiness503; восстановление точного checksum,
positive gate/check/preparation/readiness и полная logical snapshot — PASS.
SOURCE остался неизменным. Пулы, streams/tasks, own controls и child processes
закрыты; нет скрытых skip либо подменённого verifier.

Измеренные PGDATA free bytes: initial638382080, после bootstrap618672128,
до dump/restore615608320, после restore593661952. Total1073741824;
все reserve/DB<=128MiB/archive<=64MiB guards прошли, maxlocks64 не менялся.
Elapsed не SLO и не RTO/RPO.

ROOT отдельно новым подключением подтвердил обе БД ALL non-system tablelike/
sequences0/otherclients0, выполнил обычный DROP обеих и fresh final check:
**DBexists0 / ownconns0 / otherclients0 / maxlocks64**. SQL slot released,
БД не существуют, FORCE/terminate/role/server GUC не применялись.
Final result передан durable Orca message `msg_6aae7b4854cc` для текущего Dispatch.

Private final evidence root:
`/srv/projects/api-modernization-test-env-20261029/private-schema-restore-proof-20261030/`.
Автор независимо прочитал только filesystem JSON/hash/mode после root результата:

| Artifact | Bytes | SHA256 |
|---|---|---|
| run.log (ROOT launcher) | 97 | 2689cf02403a11b4643981ca54f9f6d5e02f8998ff7f93fd597cacb7c5f6733b |
| summary.json | 9402 | 9b11ea3222d855182b435b8229634f782d33d465a32152faa877662eb714f9d2 |
| synthetic.dump | 1656587 | 092e91ba051639553cd1eaeb1bb8d56d5ec8c48a5acc746114533f5d34021717 |
| source-before.snapshot.json | 49598 | a79620f894d117a87e9b632c5b1d0fe7d6c056b2e5684885bfb6483ae01e04ac |
| target-after.snapshot.json | 49598 | a79620f894d117a87e9b632c5b1d0fe7d6c056b2e5684885bfb6483ae01e04ac |
| source-before.raw-catalog-hashes.json | 1555 | 46db19489674d587a264b6860ebe5dd71239cc057501e25a5adc8134e0ea28b0 |
| target-after.raw-catalog-hashes.json | 1555 | bdcd0c1538e945124184ffa503a9f21827009302dc8cf8d4bf3d0edfd1680715 |
| restore-diff.json | 663 | b4f988007f18e3a830c6a2236119b6c54447510a4718d2830575f7c8d27fa3a2 |
| SOURCE native-prerequisites.json | 1613 | 1094d99e7d02df2de8751712b413e3b1cc970656dddb6bab1a5935981dde6280 |
| TARGET native-prerequisites.json | 1613 | 1094d99e7d02df2de8751712b413e3b1cc970656dddb6bab1a5935981dde6280 |

Raw full catalog lists совпадают с artifact hashes attempt4, приведёнными выше.
Aggregate logical catalog SHA256
`3120f2dac73a1650d94929f2266e56f1aaa20de971e8f6b430ee67d1d6db1d6f`,
data SHA256 `53a7b190ed05fcbd466f4d32ee53f6621e8b5c98500b9081df81f7236c9a7f1c`.
Все созданные harness JSON/archive имеют mode0600 внутри private directory;
dump/raw rows/metadata lists в Git/preview не переносились.

После PASS изменён только этот отчёт. Test/runtime/package bytes не менялись,
pure/SQL/старые accepted suites не повторялись. Production restore, Docker build,
full lifespan/ASGI/HTTP/browser, старые binary, CI, merge/deploy/release и активация
managed mode **NOT RUN**. Вся M16/M00–M19 и рабочая миграция остаются открыты.


## Интеграционная приёмка координатора

Source `4a963a5cfe1e7f123446226d918783a875377dd8` перенесён как
`88fdef78bab8c8ced97b29d6d24c2a47c472799a`. Проверены exact base, три новых
файла, clean source HEAD=origin и совпадение integration bytes. Оба файла
тестов сохранили SHA состава единственного успешного attempt5; существующие
app489 и frozen package16 не менялись. Повторных SQL или pure после переноса
не было. После PASS обновлён только отчёт.

Независимые source-only semantic и implementation reviews сохранены отдельно;
второй относится к c79, а исправление R1 и final784 проверял ROOT. Все четыре
неудачные actual попытки сохранены отдельно. Тестовые БД штатно удалены;
результат не подтверждает рабочий backup/restore, Docker build или выпуск.
