# M02/M15: synthetic baseline продуктовых read queries, 30.10.2026

Статус: **author baseline PASS: 3 cases / 237 HTTP samples**, точный source
`bdeae257`, test SHA ниже. Первый FAIL сохранён отдельно. Root independent
repeat ещё не выполнен; это отдельный этап, не часть author PASS.
Общая модернизация M00–M19 не завершена; PR остаётся draft. Merge/deploy,
runtime optimization, индексы и EXPLAIN не входят в разрешённый состав.

База исходников: `59e6822b1ca483de23c6173aa47b9c08541ec2de`.
Ветка: `agent/api-product-query-scaling-20261030` в собственном чистом worktree
`/home/mag/orca/workspaces/ledger-app/api-contract-manual-serialization-20261030`.
Ownership: только этот документ и `server/tests/test_product_query_scaling.py`.
SHA-256 теста после поправки machine403/unused SET validation:
`054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2`.

## Что именно измеряется

Настоящие `product_api.Query.listing/detail/project` вызываются HTTP-запросами
через `ASGITransport` и штатный `create_product_api`. Используются существующие
`budget`, `signing_pem`, `profiles`, `db`, `setup_database` fixtures из
`test_partner_resource_query_budget.py` и `conftest.py`. JWT подписывается
локальным синтетическим RSA-ключом; verifier настоящий. Это query baseline,
не повторная приёмка OAuth issuance/PKCE: полный protocol flow уже принадлежит
`test_partner_product_integration.py`.

Действуют `CompanyRole`, `UserCompany`, stored resource profiles/items,
`ContractLocation`, `DocAccessGrant` и штатная `_readable_doc_clause`.
Перед каждым profile только synthetic token/family/payload expiry обновляется
до now+25 минут, JWT подписывается реальным fixture RSA-ключом. Это покрывает
20-минутный outer bound; действующий verifier и настоящие часы не подменяются.
ORM listeners из `auth.py`, `scope.py`, `task_assignments.py`, `file_store.py`
сохраняются. Дополнительные event handlers только наблюдают запросы/гидратацию
и выставляют согласованные `SET LOCAL` timeouts в отдельном runner process;
это не глобальная настройка приложения/остальных тестов. Не используется fake verifier,
выключение ACL/listeners, подмена `Query` или ручная копия SQL приложения.

Existing resource-budget tests уже доказали снижение SQL при batch loading
resource profiles и неизменное число statements для pageSize 1/50/200.
Эти утверждения не считаются новым измерением. Новый результат: изменение
кардинальности при росте синтетического каталога, объём реально загруженных
ORM строк, размер ответа и SQL shape count/page/detail с пересечением ACL.

## Детерминированный набор и bounded cases

Три pytest cases: `scale=100`, `1000`, `5000`. Один dataset каждого масштаба,
без повторного построения на каждый endpoint/page. На N создаются:

| Строки | Количество | Условия |
|---|---:|---|
| ServiceLocation | N | `type=ezs`, фиксированные имена и timestamp |
| Contract | N | `scope_type=locations`, две организации |
| ContractLocation | N | одна связь договора с одноимённым объектом |
| DocCard | N | ограниченные поля, без файлов/версий/blob |
| DocAccessGrant | 2N/5 | private allow и company explicit read deny |
| Organization | 1 | второе юрлицо той же компании |

Штатный budget fixture дополнительно создаёт небольшие собственные/чужие
контрольные ресурсы всех пяти типов и реальную permission/token цепочку.
Синтетические UUID и object IDs выводятся из UUIDv5(namespace, scale, ordinal),
не из случайных UUID fixture. Все N строк имеют одинаковый `created_at`;
ожидаемый порядок задаётся native ID. UUID компаний/token цепочки случайные,
их значения не сохраняются в evidence.

Пять равных классов документов по `i % 5`: company-visible, private с явным
user allow, private без allow, company с явным user deny, strict без allow.
Автор/ответственный/подписант не предоставляют случайного обхода этим классам.
ALL user видит ровно `2N/5` документов. Вторая организация назначается нечётным
ordinal; object membership исключает `i % 3 == 0`; resource SET для договоров
и документов исключает `i % 4 == 0`, для объектов исключает `i % 7 == 0`.
Counterparty SET разрешает одного из двух связанных контрагентов: доступны
карточки с редактированными ссылками, а скрытые ID не выдаются.

На каждом масштабе:

| Профиль | Измеряемые ресурсы | Ожидаемая граница |
|---|---|---|
| user-all | objects/contracts/documents | tenant + документная ACL |
| user-intersection | objects/contracts/documents | tenant ∩ resource SET ∩ membership ∩ organization ∩ doc ACL |
| service-all | objects/contracts | tenant; user membership не заимствуется |
| service-intersection | objects/contracts | tenant ∩ собственный resource SET |

Это 10 resource/profile групп × pageSize 1/50/200 × 3 scales = **90 list samples**.
Дополнительно 30 вторых cursor pages, 30 успешных details, 81 отрицательная
detail-проверка и 6 service-document 403: всего **237 HTTP samples**, 3 test cases.
В каждой группе positive detail соответствует первому projected item списка.
Чужие searchable строки имеют более ранний timestamp: утечка tenant ломает и
`total`, и первую страницу. Для SET/member/organization выбирается negative row,
проходящая остальные измеряемые условия, чтобы проверка имела отдельную причину
отказа. Private/deny/strict controls отдельно проверяются на user-all; повторные
отказы на user-intersection могут иметь несколько причин.

Сравниваются точные разрешённые ID, `total`, page length, nextCursor, вторая
страница при равных timestamps, независимая redaction object/counterparty links.
SQL shape проверяет tenant/resource/user/document predicates непосредственно в
COUNT и limited SELECT, а не только фильтрацию готового ответа. Скрытые карточки
не должны гидратироваться. Lookahead ограничен `min(visible_total, pageSize+1)`.
Verifier-валидация SET ID остаётся включённой и учитывается в числе SQL.
В частности, machine-document 403 не запрещает scalar SELECT document IDs
для tenant-проверки неиспользуемого stored document SET. Тест отдельно учитывает
эти statements, проверяет tenant/ID predicates и запрещает domain COUNT/page/
entity SELECT, document hydration и выдачу карточек. Это сохранение действующей
проверки verifier, уже известной existing resource-budget tests.

## Метрики и пределы интерпретации

На каждый HTTP sample сохраняются фактическое число SQL statements (включая
transaction-local guards), cursor rowcount либо null при unknown, гидратация ORM
по таблицам, visible total/response rows, фактические HTTP response bytes,
SHA-256 нормализованных SQL shapes, wall seconds и tracemalloc peak bytes.
Сырые bind parameters, токены, ключи, персональные данные и SQL с literal values
не сохраняются в structured metrics. Приватный pytest/httpx log может содержать
синтетические resource IDs/cursors. Count-result rowcount равен числу возвращённых scalar rows,
**не** числу просмотренных PostgreSQL строк. ORM hydration тоже не измеряет
heap/index rows examined. Для этих величин нет claims без отдельного EXPLAIN GO.

Walltime включает ASGI/client/verifier/query/projection/serialization, SQL event
наблюдение и tracemalloc overhead. Memory — peak Python allocations одного
request, не RSS, не память PostgreSQL и не стоимость seed/import. Нет warmup,
повторов, p95, QPS или production SLO: это описательные single-run числа общей
VM, где параллельно root выполняет Node/TypeScript. Сравнение page sizes внутри
одного набора также зависит от прогретого кеша.

Максимум новых catalog/ACL/link строк за все масштабы: `4.4×6100 = 26840`,
плюс небольшие fixtures и SET items. Последние одновременно ограничены примерно
`(6/7 + 3/4 + 3/4)×N+1`; переходы profiles оставляют обычные MVCC dead tuples.
**Own DB ceiling 256 MiB**, проверяется после общего seed, перед dataset, после
dataset, перед каждым profile и после запросов. Нельзя расширять scale при
достижении ceiling. `pg_database_size` не включает общий WAL/tmpfs overhead:
root отдельно проверяет свободный PGDATA перед grant. Контейнер имеет общий
tmpfs 1 GiB; прежний снимок root не заменяет проверку перед запуском.

При превышении/таймауте — fail-fast, обычный shared-conftest teardown только
своих `public`/`edge` schemas и checkpoint. Если outer kill оборвал teardown,
root получает failed/unknown cleanup; запрещено удалять чужие DB/WAL или
менять контейнер/настройки. Внутри каждой транзакции `statement_timeout=15s`,
`lock_timeout=1s` через SET LOCAL, включая shared fixture DDL. Runner alarm
1150s оставляет время для teardown; внешний timeout TERM=1200s/KILL=1210s.

## Точный guarded runner после отдельного root GO

Цель только `127.0.0.1:33546`, PG16, user `clearledger`, synthetic password
`api_test_only`, own database `api_product_query_scaling_test`. Базу подготавливает
root отдельным grant. Runner не создаёт БД, не использует admin connection,
не меняет maxlocks/config и не обращается к реальным URL/env/данным.
Без opt-in обычный pytest import заканчивается module SKIP до app/DB imports;
в режиме `__main__` отсутствие opt-in остаётся строгим отказом. Module opt-out
первого approved run: **1 SKIP / EXIT 5** с `--noconftest`, без DB fixtures.
Новый opt-out после source correction без отдельного GO не запускать.

Runner — сам owned test file в режиме `__main__`; лог/evidence приватны, не Git.
Команда ниже только спецификация до root GO. Она не меняет HOME, передаёт
только унаследованные HOME/PATH/LANG плюс явный synthetic env, запускает Python
с `-I`, требует пустой cwd без `.env`. Обе exact URI проверяются до первого
connect и до pytest. Общий `partner_test_safety_error` вызывается до импорта
pytest/приложения; preflight подключается только к own DB, проверяет current
database/user, PG16, maxlocks64, other client backends=0, own size<256MiB.

```bash
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I - <<'PY'
import hashlib, os
from pathlib import Path
root = Path('/home/mag/orca/workspaces/ledger-app/api-contract-manual-serialization-20261030')
test = root / 'clearledger/server/tests/test_product_query_scaling.py'
assert hashlib.sha256(test.read_bytes()).hexdigest() == '054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2'
runtime = Path('/srv/projects/api-modernization-test-env-20261029')
cwd = runtime / 'product-query-scaling-empty-test'
upload = runtime / 'product-query-scaling-test-uploads'
evidence = runtime / 'private-product-query-scaling-20261030'
for path in (cwd, upload, evidence):
    path.mkdir(mode=0o700, exist_ok=True)
assert not any(cwd.iterdir())
env = {key: os.environ[key] for key in ('HOME', 'PATH', 'LANG') if key in os.environ}
target = 'postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_product_query_scaling_test'
env.update(APP_ENV='test', TEST_DATABASE_URL=target, DATABASE_URL=target,
    UPLOAD_DIR=str(upload), RUN_PRODUCT_QUERY_SCALING_TESTS='1',
    RUN_PARTNER_RESOURCE_TESTS='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
    PYTHONDONTWRITEBYTECODE='1', SECRET_KEY='synthetic-product-query-scaling-only')
os.chdir(cwd)
fd = os.open(evidence / 'run.log', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
python = str(runtime / '.venv/bin/python')
os.execve('/usr/bin/timeout', ['timeout', '--signal=TERM', '--kill-after=10s',
    '1200s', python, '-I', str(test), '--execute-approved-baseline'], env)
PY
```

Внутренние pytest flags: один абсолютный test path, `-c server/pytest.ini`,
`-p pytest_asyncio.plugin`, `-p no:cacheprovider`, `-q -ra --maxfail=1`,
`--confcutdir=<server>`, private `--basetemp`, `-o junit_family=legacy`,
private `--junitxml`. JUnit содержит structured `product_query_scaling` property
для каждого scale; `preflight.json` и `run.log` лежат рядом в private evidence.
Completed samples дополнительно дописываются в private `samples-scale-N.jsonl`
вне измеряемого request. Перед отдельным retry старые current artifacts нужно
сохранить в `attempt-N`; первый run уже сохранён в `attempt-1`.
Collect/optout/SQL до root GO не запускать. Размер/планы latency не выдаются
за source proof. Любая правка test после согласования требует нового hash и
root checkpoint перед следующим запуском.

## Проверки и дальнейшее решение

AST/compile corrected test и diff-check пройдены без импорта модуля/SQL.
Root выдал первый GO на `b6a955f9`, test SHA
`692f3f825d8ef1cb0c4f4791c06c555b860c77a127091ec912365da7dce2d208`.
Preflight: PG `160015`, maxlocks64, otherclients0, fresh own DB 7 765 015 bytes.
Первый runner: **EXIT 1, 1 FAILED за 37,23 s**. На scale100 выполнены 79 HTTP
requests (30 list, 10 cursor, 10 positive detail, 27 negative detail, 2 service403).
Последний assertion ошибочно запрещал обязательный scalar ID validation в
unused document SET на service403; это defect нового expected-policy assertion,
а не доказанный runtime defect. Проверки до него не равны PASS всего baseline.
Scales1000/5000 **NOT RUN**; structured sample metrics до FAIL первоначальная
версия не успела сохранить, их нельзя восстановить из одних HTTP logs.

Child EXIT/reap подтверждены, shared-conftest teardown без ошибки. После
SQL_SLOT_RELEASED root отдельно проверил `public/edge tables0`, `conns0`, сделал
обычный DROP own DB и подтвердил DBexists0/otherclients0/maxlocks64. Worker не
использовал admin/CREATE/DROP. Первый private evidence:
`/srv/projects/api-modernization-test-env-20261029/private-product-query-scaling-20261030/attempt-1/`
(`run.log`, `results.xml`, `preflight.json`, `optout.log`).
Root отдельно выдал retry GO на `bdeae257` / test
`054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2`
и заново созданную own DB. Guard/состав/наборы/timeouts/ceiling не менялись.
Opt-out повторно не запускался по решению root: guard после проверки не менялся.

## Фактический approved baseline

**EXIT 0/reaped, 3 PASS / 0 FAIL / 0 ERROR / 0 SKIP, 227,392 s** по JUnit.
На каждом масштабе записано ровно 79 samples, всего 237: 90 listing,
30 cursor, 30 detail, 81 negative-detail, 6 service-denied. HTTP statuses:
150×200, 81×404, 6×403. Все запланированные масштабы и page sizes выполнены.
Private JSONL и JUnit совпадают по числу samples; после PASS SQL/тесты не повторялись.

Точные visible totals и фактическое число statements для listing. Число включает
verifier, живые permissions, projection и transaction-local guards, не только
Query. Каждый указанный SQL count наблюдался на всех трёх page sizes/scales;
таблица фиксирует этот run, не новое A/B-доказательство старого batch loader.

| Профиль | Ресурс | N100 | N1000 | N5000 | SQL/request |
|---|---|---:|---:|---:|---:|
| user-all | objects | 100 | 1000 | 5000 | 26 |
| user-all | contracts | 100 | 1000 | 5000 | 27 |
| user-all | documents | 40 | 400 | 2000 | 31 |
| user-intersection | objects | 28 | 285 | 1428 | 30 |
| user-intersection | contracts | 17 | 167 | 833 | 31 |
| user-intersection | documents | 6 | 66 | 333 | 35 |
| service-all | objects | 100 | 1000 | 5000 | 19 |
| service-all | contracts | 100 | 1000 | 5000 | 20 |
| service-intersection | objects | 85 | 857 | 4285 | 22 |
| service-intersection | contracts | 75 | 750 | 3750 | 23 |

User-all, pageSize200: фактические возвращённые/гидратированные карточки,
wire bytes, single traced request walltime и Python peak. Time не SQL latency.

| N | Ресурс | Response rows | Hydrated cards | Response bytes | Wall ms | Python peak KiB |
|---:|---|---:|---:|---:|---:|---:|
| 100 | objects | 100 | 100 | 19341 | 193,45 | 597,1 |
| 100 | contracts | 100 | 100 | 19441 | 191,67 | 682,3 |
| 100 | documents | 40 | 40 | 10120 | 219,22 | 662,8 |
| 1000 | objects | 200 | 201 | 38902 | 255,31 | 1081,7 |
| 1000 | contracts | 200 | 201 | 39209 | 217,78 | 970,9 |
| 1000 | documents | 200 | 201 | 50570 | 736,36 | 1322,9 |
| 5000 | objects | 200 | 201 | 38902 | 225,59 | 1081,2 |
| 5000 | contracts | 200 | 201 | 38971 | 262,16 | 969,4 |
| 5000 | documents | 200 | 201 | 50843 | 5375,24 | 1335,2 |

Во всех 90 lists hydration равна `min(visible_total,pageSize+1)`; ни одна
отрицательная detail-проверка не гидратировала карточку скрытого ресурса.
Tenant/resource/member/organization и document allow/deny фильтруют count и
limited SELECT; link redaction и cursor tie-break прошли. Обязательная scalar
validation unused document SET наблюдалась по одному statement на каждом
service-intersection 403; service-all 403 — без неё. В обоих случаях нет
document domain COUNT/page/entity/hydration/выдачи карточек.

У 936 cursor observations rowcount неизвестен (null), в том числе у control
statements; unknown не подменялся нулём. Hydrated/response cardinalities выше
измерены отдельно. Во всех samples SQL-count диапазон 15–35, в lists 19–35.

| Scale | DB bytes после dataset | DB bytes после queries |
|---:|---:|---:|
| 100 | 28318743 | 28458007 |
| 1000 | 29981719 | 30663183 |
| 5000 | 38937103 | 42359831 |

Максимум own DB 42 359 831 bytes (40,40 MiB), ниже 256 MiB. Это размер текущей
собственной DB до teardown, не shared PGDATA/WAL. Shared-conftest teardown
завершён без ошибки; EXIT0/reap закрыл connections процесса. После нового
SQL_SLOT_RELEASED root отдельно подтвердил fresh `public/edge tables0/conns0`,
normal DROP и `DBexists0/otherclients0/maxlocks64`. Admin/CREATE/DROP worker
не использовал. Старый grant завершён, дальнейшего SQL разрешения нет.

Текущие private artifacts в
`/srv/projects/api-modernization-test-env-20261029/private-product-query-scaling-20261030/`:
`preflight.json`, `run.log`, `results.xml`, `samples-scale-100.jsonl`,
`samples-scale-1000.jsonl`, `samples-scale-5000.jsonl`, `summary.json`.
`attempt-1/` содержит исходный FAIL и opt-out. Raw artifacts в Git не входят.
Source test после measured run не менялся; final report commit содержит только
сводку. Full CI, M00–M19, production QPS/SLO и root independent repeat не закрыты.

## Адресное предложение root, без runtime/index правок

1. **Document COUNT/ACL.** При N5000 user-all documents page1/50/200 заняли
   5236,79/5263,51/5375,24 ms, сохранив 31 statement и bounded hydration.
   При N1000 — 627,42/730,74/736,36 ms. Source `Query.listing` выполняет exact
   COUNT до limited SELECT; `_readable_doc_clause` содержит correlated EXISTS
   для allow/deny/назначений. Это кандидат для диагностики, не доказанный
   PostgreSQL bottleneck или отсутствующий индекс. Минимальный следующий
   experiment по отдельному root grant: новая own synthetic DB, тот же N5000
   user-all document dataset; реальные ORM count/page statements с неизменными
   predicates, по одному `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` для count и
   pageSize200. Сохранить plan rows/loops/buffers отдельно от HTTP latency,
   предварительно/после сверить golden totals/IDs/deny/link redaction/cursor.
   Только после плана обсуждать точечный способ ускорить ACL-доступ/count.
2. **Grant-set validation/binding.** На N5000 intersection page200 walltime
   1902,83–3268,22 ms и Python peak примерно 5,6–6,9 MiB; user/service ALL
   objects/contracts — 198,56–262,16 ms с peak около 1 MiB. Source verifier
   проверяет live SET IDs всех профилей, а `Query.binding` сортирует/кодирует
   scope IDs. Эти операции и ACL остаются обязательными. Предложение отдельной
   стадии: измерить их CPU/allocation contribution с тем же golden output,
   без caching/reuse authority между запросами и без ослабления unused-profile
   validation. Текущие данные не разделяют их стоимость с остальным request.
3. **Instrumentation overhead.** SQL hooks вызывают `get_final_froms`, считают
   hydration; tracemalloc активен на каждом запросе. Single run на общей VM
   с параллельной root Node/TypeScript работой не позволяет вычесть этот overhead.
   Контроль без tracing требует нового согласованного bounded experiment и
   не заменяет текущую SQL/ACL evidence. Ни число statements, ни walltime сами
   по себе не доказывают конкретный plan/index/CPU cause.

Никаких EXPLAIN, индексов, runtime changes или новых benchmark repeats в этой
задаче после PASS не выполнялось. Следующее root решение должно выбрать одну
адресную диагностику; оптимизация потребует отдельного разрешения и golden
equivalence с текущим baseline, включая отрицательные controls.


## Независимый повтор координатора

Source chain d179295f/b6a955f9/bdeae257/095d36c5 перенесён без runtime delta;
интеграционный HEAD перед проверкойb2a287d7. Тест сохранён с тем же SHA054f2c99.
Координатор создал свежую собственную canonical `api_product_query_scaling_test`
и выполнил тот же guarded runner: **3 PASS, 237 HTTP samples, 230,677с**,
0FAIL/ERROR/SKIP, child EXIT0/reaped. После fresh public/edge tables0/conns0
выполнен ordinary DROP; fresh DBexists0/otherclients0/maxlocks64, admin закрыт.

Все237sample records сверены с сохранённым авторским запуском: SQL shapes/counts,
cursor rowcounts, hydration, HTTP statuses, response cardinalities/bytes и остальные
deterministic fields совпали. Walltime/peak Python allocations измеряются заново
и не требуются побайтово равными. Это не новый A/B-тест runtime оптимизации.

Перед повтором11авторских artifact files скопированы с побайтовой SHA-проверкой
в private `.artifacts/private/product-query-scaling-author-095d36c5/`. Manifest:
`.artifacts/private/product-query-scaling-author-manifest.json`. Текущий fixed
private-product-query-scaling-20261030 содержит root-run; attempt-1 сохранён
отдельно и в архиве. Root runner/proof: `.artifacts/root-product-query-scaling-repeat.py`
и `.artifacts/root-product-query-scaling-proof.json`. Raw evidence не публикуется.

Адресная диагностика двух document SQL plans готовится отдельно; EXPLAIN,
runtime/index changes и production performance этим baseline не выполнены.
