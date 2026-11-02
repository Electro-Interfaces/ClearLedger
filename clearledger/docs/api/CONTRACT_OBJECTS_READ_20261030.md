# NEXT-R1: явные связи договора с доступными ЭЗС

**Статус: реализация и локальная приёмка ROOT завершены отдельными сериями;
выпуска и включения внешнего доступа не было.**
Добавлен один candidate GET `/api/v1/contracts/{contractId}/objects`,
`operationId=listContractObjects`. Он возвращает только текущие явные
`ContractLocation` связи доступного договора с независимо доступными
`ServiceLocation`. Наличие company-договора не разворачивается во всю сеть.
Это проекция связей точек обслуживания, не юридическое заключение о площадке,
не история действия договора и не доступ к его бумагам.

Основа ветки `agent/api-contract-objects-read-20261030`:
`5670731b5814471a75e443ddf477024e70eb5be3`, содержащая принятый source analysis
на `07f12c6575cbb397e9945c7f9efda724445615c2`. Оба
`PARTNER_APPLICATION_READINESS_20261030` файла сохранены побайтно: их 12 маршрутов
остаются неизменным историческим снимком. Текущий код добавляет тринадцатую
GET-операцию: 10 user/service и три только user-documents. Отдельная контейнерная
приёмка исходного 07f не включает эту новую функцию.

## Контракт и допуск

Scopes обязательны одновременно: **`contracts:read` и `objects:read`**. Принимаются
существующий delegated partner user access token и отдельно утверждённый machine
access token; Core/ID token и docs cookie их не заменяют. Новых scopes, типов
токенов, grants или прав администратора не вводится.

В существующем `access.resolve` проверяются primary resource grant и grants
каждого read-ресурса, явно требуемого route policy. Для прежних 12 политик это
тот же единственный primary grant; для новой политики это contracts **и** objects.
Missing/EMPTY любого из них даёт 403 до `Query.detail` и связи; owner/admin не
обходит проверку. Это не дополнительный verifier или quota call: остаётся одна
прежняя последовательность live identity → grants/current user/org → quota.
Scopes и grants токена не наследуются друг от друга.

Далее `Query.contract_objects` использует прежний
`Query.detail("contracts", contractId)` с его tenant/own-org/object ceiling и
одинаковым 404 для недоступного/отсутствующего родителя. Для связей применяются
прежние `Query.conditions("objects")` плюс correlated EXISTS по
`ContractLocation.company_id`, разрешённому `contract_id` и `location_id`.
EXISTS не размножает строки; те же predicates используются до count и limit.
Скрытые/чужие IDs и их количество не попадают в ответ, даже если отдельные FK
допустили несогласованную по tenant строку связи.

| Часть | Точный allowlist |
|---|---|
| Path | `contractId` по существующему `dto.Id` |
| Query | `pageSize` 1..200, default 50; `cursor` 1..4096 символов либо отсутствие |
| Body | Отсутствует; непустой stream отклоняется 422 до detail без накопления body |
| Response | `contractId, scopeType, items[].objectId, total, nextCursor` |

Никаких q/date/company/object selectors, raw/attrs/notes, relation IDs,
организаций, файлов или скрытых totals. `objectId` использует существующий
opaque `ObjectId`, включая пробелы/кириллицу, без trim и переименования.
Company/unassigned при успешном parent admission возвращает пустой список
явных связей и исходный scopeType. Это не утверждение об отсутствии юридического
действия договора на объект.

## Cursor и отсутствие записи

Используются прежние HMAC encode/decode primitives, стабильный порядок
`ServiceLocation.created_at,id` и прежний binding primitive с новым ресурсным
именем `contract-objects:<canonical-parent-id>`. Поэтому binding включает kind
отношения, договор, tenant, subject/client/installation/grant, scopes,
все typed grants, текущие object/own-org ceilings и page size. Прежние методы
Query и binding старых маршрутов не менялись. Cursor другого договора,
клиента/компании или после изменения ceiling/page size даёт безопасный 400;
отказ живой авторизации сохраняет прежний приоритет.

Это live pagination, не snapshot при конкурентном изменении связей. GET не
выполняет flush/commit, не материализует и не меняет бизнес-данные/файлы.
Read session остаётся у `query_dependency`; auth/quota принадлежат прежним
владельцам. Idempotency-Key/creationKey и write conflict 409 не требуются.
Null-intent отсутствует: пропущенный cursor начинает обход, строка `null`
не очищает связь и даёт invalid cursor. Пустой items не различает отсутствующие
и полностью скрытые связи.

Canonical OpenAPI содержит оба OAuth-профиля новой операции, browser projection
оставляет только Code+PKCE. `_canonical_object_id_paths` и две прежние ObjectId
path-схемы не менялись. Ни native handler, ни `contract_usage`, ни service→router
вызов не добавлены.

## Проверки и границы исполнения

Автор выполнял только чтение исходников, AST, compile в памяти и Git/hash checks;
сам не импортировал app/tests/runner и не запускал pytest/collect/SQL/codegen.
Фактическое исполнение и генерацию выполнил ROOT отдельно.
Сохранены private `.artifacts/contract-objects-read/`:
`existing-test-allowlist.json`, полный `existing-tests.diff`, `source-proof.json`,
`ast-case-counts.json` и frozen proposal. Прежние test expectations изменены
только в согласованных пяти файлах/семи AST nodes: 12→13, 9+3→10+3,
небинарные 11→12 и новый Domain callable существующей transport fixture.
Прежние ACL/HTTP assertions не удалялись и не ослаблялись.

Source proof подтверждает полный AST прежнего app.py без нового handler,
старые Query methods/binding и DTO без новых определений, точную единственную
замену admission в access.py и прежние resource sets всех 12 политик.
Остальные **488 app blobs** равны основе. Все native handlers, auth, модели,
DDL/migrations, старые runners/gates, requirements/locks/Dockerfile/CI, версии,
два readiness reports не менялись.

Все **69 новых** actual HTTP/PG сценариев с литеральными synthetic goldens
прошли в первом запуске ROOT. Они используют настоящие Core login, admin client/installation,
Code+PKCE consent/token или machine credentials/grant, verifier и SQL.
Verifier/Query bodies не подменяются; counters оборачивают настоящий вызов.
Каждая fixture получает отдельный synthetic ASGI peer; security counters не
сбрасываются. Файлы и независимые persisted fingerprints проверяются отдельно
от точного списка auth/registry таблиц; при disabled quota повторные GET не
должны менять ни одну из этих частей.

| Группа | Новые случаи |
|---|---:|
| User/machine literal golden, повтор и persisted business/auth/files equality | 1 |
| Ровно один реальный verifier и quota call | 1 |
| Contracts/objects: каждый ALL/SET/EMPTY/MISSING отдельно для user и machine | 16 |
| Каждый обязательный OAuth scope отдельно для user и machine | 4 |
| Missing/malformed/foreign/ungranted parent 404 | 4 |
| Employee с одним объектом и admin с узким SET | 1 |
| Две own-org, смена организации, скрытый parent | 1 |
| Второй tenant: своё чтение, чужой parent, чужой cursor | 1 |
| Чужая собственная организация до detail | 1 |
| Реальные несогласованные tenant relations без утечки IDs/total | 1 |
| Company/unassigned/empty locations/полностью скрытые objects | 4 |
| Равные timestamps, три страницы, opaque ID без потерь/дублей | 1 |
| Cursor: другой parent/page size/grants/member/install/own-org | 7 |
| Отзыв membership/install/grant/client/credential/роли | 6 |
| Unknown query и границы pageSize/cursor | 8 |
| Непустой GET body до detail | 3 |
| Нет token/Core/ID/docs cookie | 4 |
| Default OFF, строка cursor=null, EMPTY employee ceiling | 3 |
| Прежний native GET: literal response и отказ partner bearer | 1 |
| Canonical/browser profiles и прежние ObjectId refs | 1 |

Первоначальная выборка V2 — новые 69, прежние `test_product_api` 57,
`test_product_http_profile` 12, `test_product_openapi_http_contract` 8,
`test_product_service_openapi` 7, ObjectId compatibility 13 и один прежний
pure ObjectId schema control: **167 случаев**. В этом запуске 110 прошли,
а 57 получили setup errors; отдельный V3 повторил только эти 57, все прошли.
Текущий frozen runner выбирает исключительно `test_product_api.py` 57,
используя новый модуль только как fixture plugin, без его повторной collection.
Это две серии, не один зелёный прогон 167. Полный 376/main/monitoring CI не повторялся.
Изменение числа маршрутов в historical main test проверено по source;
его старый frozen main runner не выдаётся за действующий gate новой функции.

## ROOT-only запуск

Новый `product_contract_objects_approved.py` начинает только со stdlib и
отказывается без всех opt-ins, exact argv, ROOT-reviewed self SHA, полного
app/tests/schema manifest и support hashes. Используется прежний принятый
host candidate Python **3.13.7/glibc 2.36**, runtime 61 + test tools 16 без pip
install. Inventory и source проверяются до app imports и после прогона.
Окружение allowlisted, настоящий HOME сохранён, `.env`/secret paths закрыты.

Единственная SQL-цель — **`api_contract_objects_test_20261030` на
`127.0.0.1:33546`**, созданная ROOT свежей и пустой. TEST_DATABASE_URL и
DATABASE_URL совпадают побайтно; credentials ROOT передаёт через чистую среду,
без вывода. В тесте `--noconftest`: новый opt-in fixture plugin проверяет exact
database, пустые public/edge relations и отсутствие иных client connections,
затем вызывает штатную `database.create_all`. Нет DROP SCHEMA/DATABASE или
production seed. ROOT независимо проверяет завершение connections, relations,
обычный DROP DATABASE, отсутствие БД после удаления и прежние параметры PG.

Запуск из отдельного пустого owned cwd, только после ROOT review:

```text
/srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/product_contract_objects_approved.py --execute-approved-product-contract-objects-tests
```

Flags со значением 1: `RUN_PRODUCT_CONTRACT_OBJECTS_TESTS`,
`ROOT_APPROVED_PRODUCT_CONTRACT_OBJECTS`, `RUN_PRODUCT_API_TESTS`,
`RUN_PRODUCT_OBJECT_ID_TESTS`, `RUN_PRODUCT_OBJECTID_SCHEMA_COMPATIBILITY`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTHONDONTWRITEBYTECODE`. APP_ENV=test,
SECRET_KEY — отдельное synthetic значение runner. `R1_RUNNER_SHA256` ROOT
берёт из frozen proposal. Cwd/upload/evidence/scratch — четыре разные пустые
owned 0700 папки с test в имени; `R1_EMPTY_CWD`, `UPLOAD_DIR`,
`R1_EVIDENCE_DIR`, `R1_SCRATCH_DIR`, TMPDIR=scratch задаёт ROOT.

Внешние сеть/процессы/listeners запрещены; asyncpg target проверяется повторно,
SQL timeouts 20/2/30 секунд. Единственный sendmsg допуск — owned connected
IPv4 TCP stream точного PG peer, прежний FD, без ancillary/flags/address,
с ContextVar capability и audit caller check. IPv6 capability probe urllib3
подавлен только в импортной группе, исходный flag восстанавливается; bind
не разрешён. Email/notify доставки перехватываются до HTTP routers, schedulers
и main не импортируются. Quota/managed/docs flags не активируются.

Внутренний wall deadline 540 секунд, CPU 480/500, AS 3 GiB, файл/log 2 MiB,
scratch 64 MiB/4096 entries; ROOT также обязан ограничить внешний wall/log и
reap child. Pytest capture=sys, без общего conftest, tb и captured stdout не
печатаются; bounded redacted failures сохраняются отдельно. Selection counts
точные, skip/xfail не принимаются; JUnit и boundary.json отражают реальные
outcomes, forbidden attempts, delivery counts и source/inventory после прогона.
В V3 проверены setup/ready/finalized counters: схема один раз, db и api по 57,
env и password_hash ноль; уведомлений ноль. Sessionfinish выполняет проверку
после штатного teardown. Правила допуска, приложение и тела fixtures не менялись.

## SDK и пример

ROOT отдельно разрешил минимально изменить два tooling файла: exporter ожидает
13 candidate operations, официальный generator manifest добавляет только
`listContractObjects`, сохраняя strict validation и negative controls.
Сгенерированный `.d.ts` автор **не редактировал**: после source review ROOT
выполнил официальную generation/freshness, прежний consumer TypeScript check
и неизменённые `generation.test.mjs` **6/6 PASS**, 23,8797 секунды. Пройдены
real-module schema parity без подключения к БД, детерминизм, drift и отрицательные
schema/ref/export controls. Tool node_modules ROOT материализовал из прежней
точной pinned среды; npm install и сеть не использовались.

ROOT отдельно добавил `contract-objects-consumer.ts` в существующий tsconfig:
совместный TypeScript check прежнего и нового consumers — PASS. Новый пример
использует operation/path/query/response из generated types, Unicode ObjectId
и пять отрицательных compile checks: company override, выдуманный POST, body,
отсутствующий contractId и отсутствующий nextCursor. Прежний consumer.ts
сохранён. Canonical schema SHA-256 из generated header:
`b1cb847e1e3327ceaadcc78b0b1f52be6f701840f78474c881271dbd2e26427e`.
Это проверки SDK-контракта, не HTTP-пилот и не полный app TypeScript/build.

Вымышленный вызов в отдельно разрешённой sandbox после выдачи user/machine
access token с обоими scopes/grants; здесь не исполнялся:

```sh
curl --fail-with-body -sS \
  "$BASE/api/v1/contracts/00000000-0000-4000-8000-000000000101/objects?pageSize=50" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
{"contractId":"00000000-0000-4000-8000-000000000101","scopeType":"locations","items":[{"objectId":"synthetic-point"}],"total":1,"nextCursor":null}
```

Это контрактный пример, не сохранённый runtime response. Второй скрытый объект
не увеличивает total. Следующая страница повторяет pageSize и передаёт
непрозрачный nextCursor. Чужой parent даёт 404, отсутствующий objects grant
403, неизвестный company selector 422.

## Фактические ROOT результаты и сохранённая история

| Состав | Наблюдавшийся результат |
|---|---|
| V1, source `b863e1064184bb3077b48627758ac116e826d692` | Только source review: до исполнения ROOT обнаружил, что pytest FileHandler мог открыть `/dev/null`, запрещённый write guard. Добавлен явный owned `pytest.log`, без допуска `/dev/null` |
| V2, source `991127b02318b900e0382ee5484f2215b4a1f249` | **110 PASS** (69 новых + 41 прежний), **57 setup errors**, 132 успешных subtests; pytest 158,22 с, outer 163,3464 с, exit 1, child reaped |
| V3, source `bb09029eb73b55280dec81e03ab13c065637fbe8` | Только прежние 57, затронутые setup: **57 PASS / 0 FAIL / 0 ERROR / 0 SKIP**, pytest 23,20 с, outer 28,4079055181 с, exit 0, child reaped |
| SDK, отдельная ROOT фаза | Официальные generation/freshness, два consumer checks PASS, 5 negative compile checks и 6/6 неизменённых generator cases PASS |

V2 одновременно загрузил `test_product_contract_objects` как глобальный fixture
plugin и собрал его как test module. В pytest 9.2 это два набора FixtureDef с
разными cache/visibility. Новые 69 успешно использовали локальный session setup;
затем старые product API cases запросили глобальный plugin setup, чей preflight
снова ожидал пустую БД и получил **334 существующие relations**. Это ошибка
оснастки, не дефект business query. V3 не собирает модуль plugin как тестовый,
поэтому exact fresh-schema setup происходит один раз. Никакой DROP внутри
fixtures, очистки assertion или изменения app/test bodies не добавлено.

Первые 110 PASS не повторялись. Успешные наблюдения покрывают 167 различных
cases **по двум сериям**, не один непрерывный full167 и не CI всего API.
JUnit V2 имеет tests=299 с учётом 132 subtests; отдельных testcase элементов
167, из них 110 PASS и 57 setup errors. Сохранено одно нефатальное предупреждение
`record_property` при xunit2; ради его удаления frozen tests не менялись.
ROOT также исправил свой внешний scratch monitor: intentional symlink/FIFO
прежних negative fixtures учитываются через bounded no-follow inode traversal.

В обеих сериях forbidden attempts пусты, source/inventory после исполнения
PASS. V2 зарегистрировал 207 перехваченных login notifications, две PG socket
connections и один строго допущенный PG sendmsg. V3: deliveries 0, одна PG
connection, sendmsg 0; lifecycle counters совпали с точными ожиданиями.
Ни main/lifespan/seed/jobs, ни внешние отправки не выполнялись. Runtime и
test bytes между V2/V3 не менялись; изменён только runner selection/lifecycle.

По независимому контролю ROOT после завершения процессов:
V2 — 339 synthetic relations, connections 0; V3 — **338 relations**, connections 0.
После каждого выполнен обычный DROP DATABASE, existsAfter 0,
`max_locks_per_transaction=64` сохранён. Внешний process receipt V3 первоначально
ошибочно записал имя fixture-файла в поле database из-за переиспользованной
переменной monitor loop. Исходный receipt сохранён, отдельный
`receipt-database-label-correction.json` связывает create/env/runner/drop с точной
`api_contract_objects_test_20261030`; фактическая SQL-цель была правильной.
Автор эти SQL-контроли не выполнял.

## Frozen source и проверяемые receipts

Общие app/tests/schema pins обоих исполнений, формат digest: SHA-256 compact
JSON отсортированных `[relative-to-server path, fileSHA256]`, без `__pycache__`;
в tests self-referencing runner исключён и закреплён отдельно.

| Состав | Count | SHA-256 |
|---|---:|---|
| app | 492 | `4d290f519709a185c633f0f59c0145a4898cff0cb9ea9cdad1efbe35896d5d7e` |
| tests без runner | 350 | `c300ad882f7292f3a93d59ac0629d674638c4f39d90666a2696b6de55bc8d97b` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |
| runner V2 | 1 | `a6b4fd5aa5344c6be3992cebfdb9c75662bef04336b0f4c603b83faa8fb5b259` |
| runner V3 | 1 | `4f48de90e1a5b69bb03a98c4a6b7d5dfe7d35670d8740e22fb810a4e81bc1a82` |

Source owners относительно `server/app/product_api`:
`app.py:create_product_api.contract_objects`, `access.py:resolve`,
`queries.py:Query.contract_objects`, `dto.py:ContractObjectsQuery/ContractObject/ContractObjects`.
Их точные blobs доступны в обоих frozen Git commits; SHA-256 файлов:

| Файл | SHA-256 |
|---|---|
| app.py | `e8eb031a2d587b53e59a2d43413ecf86ec6e9c03867a0c83564ec2fb3ee3c0ba` |
| access.py | `f6014e3cda1561da640ebd66b8a46ad63830660baa2581a4b605d880dc890ed2` |
| dto.py | `c40f473afdc13b06cddd74234fa09138a3dffa8fc10563d16ea6e04fb0de496c` |
| queries.py | `49ea5445b69ce01eb2d572e9d14dde6e4211eee54c63beb6f9967a9e9a4fdd47` |

Private ROOT evidence — `.artifacts/root-contract-objects-review-20261030/`
в integration worktree. Автор прочитал уже существующие JUnit/boundary/process,
SDK receipt и исправление label, проверил outcomes и хеши трёх ROOT SDK файлов;
это чтение evidence, не новый runtime прогон.

| ROOT artifact относительно evidence root | SHA-256 |
|---|---|
| `process.json` | `162a05f6bbd1bd14d540afd0848df600d0f836773f92f22a2441a0637cb61098` |
| `r1-evidence-test/boundary.json` | `cf4d45057888ec3bc9f7f1007e7f379fcaf8a6565c768d106a4ddf4ca681b3e3` |
| `r1-evidence-test/contract-objects.xml` | `ea0b3c7855fa93da9f1685a594d92f08478c4bea5314418a6d2481eefd78d387` |
| `r1-evidence-test/failures.json` | `b88337bca2fc9c49f1e74cc5b6d338caddaf868833c121db45258156f667825f` |
| `affected57/process.json` | `c6e7fbe4b6e27c325f90ea15cf018f2091a9d1d0ed6e56e54825b49ccbd06959` |
| `affected57/receipt-database-label-correction.json` | `b9740caafffdb5018e2c6013c82160a7833bf2bb28444ba78fcef94cae7bd961` |
| `affected57/r1-evidence-test/boundary.json` | `afd72be9572b652a5affe09f7c639b9fe176e4b5756d8011b3282473ea3de4aa` |
| `affected57/r1-evidence-test/contract-objects.xml` | `de72de77a42e760263a18fb4bc3fd896e5edfa993af042c727d05bebf2b81a13` |
| `sdk-result.json` | `9c9ab95c2e3f76a0403ba15814a56bb6c9f1e96e6da03fe4e47379c14d2c5990` |

| ROOT SDK-файл относительно clearledger | SHA-256 |
|---|---|
| `src/generated/partner-api.d.ts` | `b76760f044eecea4a42f23829bff3b51f8c5ac86fe90724b01c0458e09477714` |
| `tools/partner-api-types/contract-objects-consumer.ts` | `c17746e21cc13a996eca173f6adbe3be7ebc96ad5cddff6511eec1215bfb0ba0` |
| `tools/partner-api-types/tsconfig.json` | `349613fe76bae30f92c37bed2adb6567820926efe5a2a83124ec61ee24e28126` |

## Результат и границы

NEXT-R1 реализован, локальные scoped HTTP/PG и SDK проверки приняты указанными
сериями. Финализация меняет только документацию и включает три точных
ROOT-generated/consumer файла; app/tests/runner/tooling после PASS не меняются.
Оба readiness reports и чужой Docker baseline 07f остаются frozen.

**NOT RUN:** реальный партнёр, nginx/SSO browser, full main, полный 376/CI,
полный app TypeScript/build, нагрузка/SLO, deploy/activation. Legal site/temporal
coverage, contract→DocCard и любые writes вне NEXT-R1. Завершение пакета не
закрывает M00–M19 и не означает готовность рабочего релиза.
