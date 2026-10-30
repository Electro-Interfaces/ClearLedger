# M02/M15: synthetic baseline продуктовых read queries, 30.10.2026

Статус: **первый approved run FAIL на ошибочном ожидании теста; source correction
готова, повторный SQL GO ещё не получен**. Полный scaling baseline не завершён.
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
После поправки root требуется свежий CREATE и отдельный literal GO на новый SHA;
SQL/collect/optout повторно не запускались. Full CI и M00–M19 не закрыты.

После approved run сюда добавляются фактический SHA, PASS/FAIL/SKIP, размеры,
sample aggregates, ограничения и private evidence paths. Только после реальных
данных формулируется минимальное evidence-backed optimization proposal для
отдельного root решения; пока оснований менять runtime/индексы нет.
