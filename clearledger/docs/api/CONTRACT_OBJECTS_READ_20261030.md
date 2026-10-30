# NEXT-R1: явные связи договора с доступными ЭЗС

**Статус: реализация и source preparation; фактическая приёмка ROOT ещё не выполнена.**
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

## Подготовленные проверки и границы исполнения

Автор выполнял только чтение исходников, AST, compile в памяти и Git/hash checks;
app/tests/runner не импортировались, pytest/collect/SQL/codegen не запускались.
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

Подготовлено **69 новых** actual HTTP/PG сценариев с литеральными synthetic
goldens. Они используют настоящие Core login, admin client/installation,
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

Выборка runner — новые 69, прежние `test_product_api` 57,
`test_product_http_profile` 12, `test_product_openapi_http_contract` 8,
`test_product_service_openapi` 7, ObjectId compatibility 13 и один прежний
pure ObjectId schema control: **167 предложенных случаев**, не фактический
результат collect или PASS. Полный 376/main/monitoring CI не повторяется.
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
Эти ограничения — оснастка будущего запуска, не доказательство его выполнения.

## SDK и пример

ROOT отдельно разрешил минимально изменить два tooling файла: exporter ожидает
13 candidate operations, официальный generator manifest добавляет только
`listContractObjects`, сохраняя strict validation и negative controls.
Сгенерированный `.d.ts` автор **не редактировал**. После source review ROOT
выполняет существующие `partner:types`, `partner:types:check`,
`partner:types:consumer`, `partner:types:test` и нужный TypeScript check в
утверждённой среде без установки новых зависимостей. До receipt генерации
наличие старого SDK не считается поддержкой нового operation.

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

## Результат и что остаётся

На момент подготовки подтверждены только source/AST/compile/hash/diff checks.
**Actual HTTP/SQL/167-case execution и официальный SDK codegen: NOT RUN.**
ROOT review, независимый запуск и receipts ожидаются; после них этот раздел
дополняется точными результатами, source pins и историей отказов без переписывания
неудачных evidence. Реальный партнёр, nginx/SSO browser, release/activation,
производительность, legal site/temporal coverage, contract→DocCard и любые
writes остаются вне NEXT-R1. Завершение этого пакета не закрывает M00–M19.
