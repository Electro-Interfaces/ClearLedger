# M12: wire types внешнего product API

## Текущий Source-контракт · 01.11.2026

На базе `24af3535565381d46f9e51c2841c2feb80b1c8f3` DX manifest содержит
**18 операций: 17 GET и один POST на 17 путях**. Единая
[таблица method, public path, operationId, scopes и principal profiles](PARTNER_QUICKSTART.md#current-source-contract-20261101)
находится в quickstart. Прежние 11 read GET и новый network-state допускают user/service, четыре
документных GET — только delegated user consent. GET `/contracts/create-options`
и POST `/contracts` требуют `contracts:create` и текущего CREATE-профиля
пользователя либо approved machine grant; `contracts:read` их не разрешает
и для них не требуется. Resource grants проверяются отдельно от OAuth scopes.
Source declarations и SDK manifest сверены статически; генерация, freshness,
typecheck, тесты и runtime для этой редакции документа не выполнялись.

`src/generated/partner-api.d.ts` содержит wire types `paths`, `components`,
`operations`. Это определения HTTP-контракта; transport, хранение/refresh токенов,
авторизация пользователя и повторы запросов реализуются клиентом отдельно.
Принятый [канонический отчёт 405/SDK](api/PARTNER_OPENAPI_405_SDK_ROOT_VERIFICATION_20261101.md)
([точные pins и ограничения](api/PARTNER_OPENAPI_405_SDK_ROOT_VERIFICATION_20261101.json))
фиксирует отдельный компонент: формальные 405 всех 17 операций и wire types
на `f196f8aa`, сохранённые generate/freshness, шесть generator tests и компиляцию
шести consumers. Отдельные schema/HTTP-проверки на `13790dc6` — 27 основных и
177 подпроверок, DPL — 14 проверок/42 фазы. Рецензент сверил Source и сохранённый
вывод без повторного исполнения; отдельного argv-receipt TSC в SDK bundle нет.
READ positive fixtures используют fake verifier/domain/ACL, новые 405/404 —
падающие verifier/session guards; реальных SQL/PG/OAuth, positive POST или
передачи данных сетевым SDK они не подтверждают. Whole M09, final CI,
публикация схемы, ingress и production не приняты этим отчётом.
Readiness остаётся `candidate`; документация не включает feature gates
и не проверяет состояние пространства.

`getContractCreateOptions` описывает advisory choices для `organization`,
`counterparty`, `location`, `type`: обязательный resource, `items[].value`,
`selectionVersion`, обязательный nullable `nextCursor`; request cursor optional
nullable. Полный профиль и данные читаются в одном read-only snapshot t0,
cursor связан с профилем/токеном/страницей. Это не receipt, резервирование или
admission. `createContract` заново проверяет текущие CREATE authority/profile
и ссылки: 201 возвращает `{contractId, replayed: false}`, 200 при авторизованном
replay — тот же ID и `replayed: true`. После неизвестного исхода commit нужны
новый запрос, исходные тело/creationKey и текущая авторизация исходного
grant/actor; тип результата не даёт READ. Точные body/status/cursor semantics
и канонические HTTP/options отчёты — в quickstart по ссылке выше.

### Семь конкретных consumers

Все файлы ниже перечислены в [tsconfig](../tools/partner-api-types/tsconfig.json).
Таблица описывает назначение их исходников; успешная компиляция на текущем pin
здесь не утверждается.

| Файл | Что проверяет исходник примера |
|---|---|
| [consumer.ts](../tools/partner-api-types/consumer.ts) | Object/страницы/Problem; required nullable поля, numeric pageSize, запрет tenant override и POST `/objects`, binary download без JSON |
| [contract-objects-consumer.ts](../tools/partner-api-types/contract-objects-consumer.ts) | Явная связь договора с объектами, path/query/page; обязательные contractId/nextCursor, запрет tenant override, body и POST связи |
| [contract-documents-consumer.ts](../tools/partner-api-types/contract-documents-consumer.ts) | Связь с документами без file bytes; обязательные contractId/nextCursor, запрет tenant override, body и POST связи |
| [contract-classification-consumer.ts](../tools/partner-api-types/contract-classification-consumer.ts) | Required nullable typeCode/validUntil, source strings и scoped metadata; required code, запрет enumeration/search/cursor, tenant override, body и classifier write |
| [contract-create-consumer.ts](../tools/partner-api-types/contract-create-consumer.ts) | CREATE body с creationKey и required nullable validUntil, discriminator coverage; 201/200 result и 403 Problem, запрет tenant override и утечки читаемой карточки |
| [contract-create-options-consumer.ts](../tools/partner-api-types/contract-create-options-consumer.ts) | Четыре resource, required resource/nextCursor, value/selectionVersion, 429 headers; запрет internal ID/body/POST и точные required 405 Allow для GET и коллекции GET/POST |
| [network-state-consumer.ts](../tools/partner-api-types/network-state-consumer.ts) | Точные query/response, пять полей строки, восемь underscore status keys и required nullable; сохранение operation/access boundary, фильтров и pageSize при continuation, restart без cursor; 400/401/403/503, отрицательные financial/query/status/body/POST примеры |

Новый consumer — wire example без сетевых запросов и SDK transport. Строка
`accessBoundary` — локальный маркер вызывающего кода; она не выдаётся API и не
заменяет серверную проверку прав на каждой странице. 400 требует нового обхода
и отбрасывания частичного результата; 401/403 останавливают обход, 503 передаётся
ограниченной политике повторов клиента. Функции не обновляют токены и не выдают
разрешения. TypeScript не проверяет реальный JSON, диапазоны query, подпись cursor
или актуальные права.

Generated `src/generated/partner-api.d.ts` и canonical JSON в этой Source-правке
намеренно оставлены прежними. Седьмой consumer до генерации Root не считается
скомпилированным; новый официальный generator test только написан.
Root далее выполняет конечную [DX-матрицу](api/RUSHYDRO_NETWORK_STATE_DX_PLAN_20261101.md),
включая export/generate/check, Node tests и TSC семи consumers в offline isolation.

### 405, заголовки и границы профиля

Source [HTTP metadata](../server/app/product_api/app.py) объявляет typed **405
Problem** (`application/problem+json`, `method_not_allowed`) и обязательный
`Allow`: **`GET`** для известных путей, включая `/contracts/create-options`,
**`GET, POST`** для `/contracts` у обеих операций `listContracts` и
`createContract`. Шестой consumer содержит отрицательные проверки отсутствующего
Allow, неверного набора методов и lowercase `get`. Правильный Allow описывает
путь; он не выдаёт авторизацию на перечисленные методы.

Application responses содержат `Cache-Control: no-store` и `X-Request-Id`
(равен `requestId` в Problem); 401/403 — Bearer `WWW-Authenticate`.
Quota 429 `rate_limited` несёт `Retry-After`; generic injected 429 использует
`internal_error`, а Retry-After у generic 429/503 присутствует только когда задан.
Binary 200 download имеет `Content-Disposition` и `X-Content-Type-Options:
nosniff`. Это профиль product child application до начала streaming: ошибки
ingress/proxy и ошибки после отправки заголовков находятся за его границей.
Типы и корректные headers не доказывают текущие grants/permissions, доступ
к файлу или авторизацию; TS не валидирует входной JSON и cursor integrity/TTL.

Описания архитектуры и команды ниже сохранены как документация. Исторические
результаты M12/M06-R3 относятся к своим pins, а не к текущим 18 операциям.

## Источник и offline граница

`scripts/export-partner-openapi.py` вызывает настоящие
`app.product_api.curated_openapi(create_product_api(...))`; DTO, handlers,
RoutePolicy и canonical curated exporter не копируются и не подменяются.
Issuer всегда `https://partner-schema.example.invalid`, source revision —
`offline-candidate`, readiness остаётся `candidate`. Генерация ничего не говорит
о включении feature или готовности пространства к внешним вызовам.

По умолчанию tooling adapter даёт реальным ORM declarations только локальную
SQLAlchemy DeclarativeBase вместо импорта `app.database`. Нет engine/sessions,
runtime main/config/auth/identity imports запрещены. Исходные model declarations
нужны для импорта настоящего Query, но в OpenAPI попадают только curated DTO.
Environment очищается, процесс работает в пустой temporary directory;
открытие `.env`/`.env.*` и обращения к sockets запрещены audit hook.
Sessions/verifier передаются как функции, которые выбрасывают ошибку при вызове.
Startup/lifespan, SQL/DDL, HTTP и скачивание remote schema не выполняются.

Историческая проверка M12 на базе `e94427bf` включала **semantic parity**:
отдельный hermetic процесс
с `--runtime-database` импортирует штатный `app.database` с явно synthetic URL
на недоступный loopback port, synthetic config и пустым cwd. Engine создаётся
обычным кодом, но `do_connect` и sockets запрещены; startup/create_all/main не
запускаются. Весь полученный JSON сравнивается с offline adapter, включая
paths/components/required/security и metadata. Parity этого состава — PASS;
это не проверка подключения к БД и не DB test suite.

## Официальный генератор и lock

Используется [openapi-typescript Node API](https://openapi-ts.dev/node),
а не собственный schema-to-TS converter. `astToString()` печатает AST самой
библиотеки; custom transforms для DTO, dates или binary не добавлены.
Options: `alphabetize: true`, `defaultNonNullable: false` — required берётся
из OpenAPI, поле с default не становится обязательным только из-за генератора.
Nullable поля сохраняют `null`; dates остаются JSON strings.

Tool dependencies изолированы в `tools/partner-api-types/package.json` и
`package-lock.json`; root application dependencies/lock не меняются.

| Пакет | Exact version | Лицензия по package metadata |
|---|---|---|
| openapi-typescript | 7.10.1 | MIT |
| @redocly/openapi-core | 1.34.22 | MIT |
| typescript | 5.9.3 | Apache-2.0 |

[MIT license генератора на exact tag](https://github.com/openapi-ts/openapi-typescript/blob/openapi-typescript%407.10.1/packages/openapi-typescript/LICENSE)
проверена вместе с registry metadata. Lock фиксирует resolved URLs и integrity
всех transitive packages. Integrity генератора:
`sha512-rBcU8bjKGGZQT4K2ekSTY2Q5veOQbVG/lTKZ49DeCyT9z62hM2Vj/LLHjDHC9W7LJG8YMHcdXpRZDqC1ojB/lw==`.

Negative control показал: default Node API config может пропускать malformed
schema types/parameters. Поэтому библиотеке передаётся explicit official
Redocly config: `struct`, `operation-operationId-unique`, `no-unresolved-refs`
имеют severity error. Unknown schema type и недопустимый parameter location
теперь дают ошибку; stale output не публикуется. Версия generator проверяется
перед работой, remote/unresolved refs и неожиданная operation manifest запрещены.
Network access Node generator дополнительно блокируется.

## Команды разработчика и CI

Рабочая папка — `clearledger`. Требуются Node 22 и отдельная Python 3.13 venv
с текущими backend requirements. Ни test DB, ни `.env` для этих команд не нужны.
По умолчанию Python берётся из `../.venv/bin/python`; другой executable задаётся
явно `PARTNER_OPENAPI_PYTHON` (в том числе Windows Python). Tool использует
UTF-8/LF, stable JSON ordering и не включает timestamps/абсолютные пути в output.

```sh
# Устанавливать только в свой каталог, не через shared node_modules symlink.
test ! -L tools/partner-api-types/node_modules
npm ci --prefix tools/partner-api-types --ignore-scripts --no-audit --no-fund
npm run partner:types
npm run partner:types:check
npm run partner:types:consumer
npm run partner:types:test
npm run typecheck
```

`partner:types` сначала полностью экспортирует/проверяет schema и генерирует
temporary output, затем атомарно обновляет `.d.ts`. `partner:types:check` делает
тот же свежий экспорт и сравнивает bytes temporary output с файлом checkout;
при drift/отсутствии файла/exporter/generator error возвращает nonzero,
не переписывает файл и не использует сохранённую spec как fallback.
Заголовок содержит exact generator version и SHA256 canonical schema: изменение
schema обнаруживается даже тогда, когда TS primitive type остался тем же.
Проверка не меняет `apiClient` и не делает HTTP запрос к работающему пространству.

В обычном review обновляют `.d.ts` командой generation и коммитят вместе с
изменением contract. Root CI workflow здесь не меняется; команды готовы для
отдельного CI шага, но не объявляются уже подключёнными к workflow.

## Потребитель во внешнем серверном приложении

Компилируемый пример — `tools/partner-api-types/consumer.ts`. Он использует
именно сгенерированные типы, без второго HTTP transport в Core:

```ts
import type { components, operations } from "../../src/generated/partner-api";

type ObjectWire = components["schemas"]["Object"];
type ObjectPage = operations["listObjects"]["responses"][200]["content"]["application/json"];
type ObjectsQuery = NonNullable<operations["listObjects"]["parameters"]["query"]>;

const query: ObjectsQuery = { pageSize: 50, dateFrom: "2026-01-02" };
const label = (point: ObjectWire) => point.name;
```

Compile fixture также проверяет required nullable fields, numeric pageSize,
отсутствие companyId override, POST `/objects` и JSON у binary download через
`@ts-expect-error`; ослабление этих контрактов ломает compile.
Error responses типизируются через `application/problem+json`/Problem.
Download 200 имеет только `application/octet-stream`; default generator
представляет `format: binary` как string marker. Это **не** указание парсить
реальные bytes как JSON/string: внешний transport читает raw bytes/stream/
ArrayBuffer/Blob по своим правилам. Runtime decoder здесь не генерируется.
TS не валидирует входной JSON, UUID/pattern/числовой диапазон и не даёт прав доступа.

После получения защищённой spec внешний разработчик может:

1. Получить её штатным одобренным portal flow с docs consent/session через
   `/api/developer/docs/openapi.server.json`: это canonical contract с пользовательским
   и машинным OAuth-профилями. `/api/developer/docs/openapi.json` — отдельное
   browser execution представление только Code+PKCE; для серверного клиента
   использовать полный server contract. Оба файла защищены docs session.
   Это существующая portal boundary, а не обычный ID-token Authorization header.
2. Сохранить spec в своём private workspace вне Git/публичных артефактов.
   В этом задании production spec/response не запрашивались и не сохранялись.
3. В своём проекте установить exact `openapi-typescript@7.10.1` с собственным
   lock и выполнить [официальный CLI](https://openapi-ts.dev/cli) по локальной
   spec, с теми же options и explicit Redocly structural validation config:

```sh
./node_modules/.bin/openapi-typescript ./private/partner.openapi.json \
  -o ./src/partner-api.d.ts --alphabetize --default-non-nullable=false \
  --redocly ./redocly.yaml
```

```yaml
# redocly.yaml во внешнем проекте
rules:
  struct: error
  operation-operationId-unique: error
  no-unresolved-refs: error
```

Далее `paths` можно применить к своему серверному HTTP adapter или
[официальному openapi-fetch](https://openapi-ts.dev/openapi-fetch/), который
принимает эти types. Это отдельный выбор внешнего проекта; dependency/SDK,
token store и refresh logic не добавляются в Core этим slice. Для product API
нужен partner **access token** соответствующих issuer/audience/scopes, полученный
по штатному OAuth flow; ID token не является API credential. Base URL внешнего
клиента — реальный issuer `/api/v1`, не synthetic `.invalid` из offline export.

## Исторические результаты M12 и границы

На исходниках базы e94427bf: generation twice byte-equal, drift negative control,
export failure без overwrite, malformed type/ref/parameter failures, offline
guards и full actual-factory semantic parity — **6 PASS**, без DB/network.
`partner:types:consumer` и application `npm run typecheck` — PASS.
Чистая переустановка isolated toolenv через `npm ci` проверяет lock/integrity;
`git diff --check` — PASS. Реальные запросы внешнего клиента, OAuth provider
interop, browser/production portal download и live schema не проверялись.

Root сообщил новый ObjectId alias в `e8e26853`. Этот slice не меняет его DTO/
handlers и не подменяет current checkout скопированным DTO. После интеграции
root обязан заново выполнить generation/check/consumer/tests на окончательном
составе, включая ожидаемые M09 500/response headers/examples; новый alias должен
прийти из настоящей curated schema. До этого данная
`.d.ts` подтверждена только для базы e94427bf, не для final integrated candidate.
Откат — удалить отдельные tooling/generated/doc changes и npm commands;
runtime API, credentials и persisted grants при этом не меняются.


## История контрактных срезов

Более поздний исторический [отчёт SDK17 от 01.11.2026](api/PARTNER_SDK17_ROOT_VERIFICATION_20261101.md)
фиксирует exact3 на `6f3f2f87`: Source и сохранённые official generate/check.
Шесть generator tests и TSC шести consumers там — наблюдения Root без отдельного
полного RAW и без независимого повторного исполнения. Он предшествует 405/Allow
и не заменяет отдельный канонический отчёт 405/SDK выше.

M06-R3 от 31.10.2026 содержал **15 GET: 11 user/service и четыре user-only**.
Принятые source/new103/regression84 с 152 subtests, SDK15 generation/freshness,
6 generator checks и 4 consumers относятся к тому срезу;
[канон M06-R3](api/CONTRACT_CLASSIFICATION_READ_20261031.md).
Эти результаты не перенесены на текущие 18 операций или семь consumers.

NEXT-R2 от30.10.2026 добавил `GET /api/v1/contracts/{contractId}/documents`
(`listContractDocuments`): явные subject/graph связи с независимо доступными
документами. Нужны delegated user consent, `contracts:read` **и** `documents:read`,
а также отдельные typed resource grants обоих ресурсов. Machine-профиля нет.
Ответ: `contractId, items[].documentId, total, nextCursor`; query только
`pageSize` (1..200, default 50) и `cursor`. Чтение связи не даёт права на файлы:
для content по-прежнему нужны отдельный download scope, права документа и file policy.
На этом историческом срезе схема содержала 14 GET: 10 user/service и четыре user-only.
ROOT принял 60 новых сценариев и отдельный corrective1, regression84 с 142
subtests, official generation/freshness, 6 generator controls и 3 typed consumers.
Это отдельные локальные серии; выпуска и включения не было. Подробности: [NEXT-R2](api/CONTRACT_DOCUMENTS_READ_20261030.md).

Следующие датированные сведения о NEXT-R1 и M12 сохранены как история срезов.

Дополнение NEXT-R1: actual curated candidate расширен новым
`listContractObjects` до 13 GET, из которых 10 допускают user/service и три
документные требуют пользователя. Exporter и официальный генератор обновляют
точный manifest, сохраняя проверки чужих/лишних/повторных операций. Исходный
срез из 12 операций ниже остаётся историей M12; текущая генерация, проверка
freshness/consumer и её точные результаты фиксируются отдельно в
[отчёте NEXT-R1](api/CONTRACT_OBJECTS_READ_20261030.md). ROOT выполнил официальные
generation/freshness, прежний и новый consumer checks и 6/6 generator controls;
generated файл содержит новый контракт, ручной правки `.d.ts` нет.

30.10.2026. База этого slice — `e94427bf6af8bbb84206dfc7f982bd7718ff0c52`,
ветка `agent/api-wire-types-20261030`. Генерируемый файл:
`src/generated/partner-api.d.ts`. Он экспортирует `paths`, `components`,
`operations` реальных **12 candidate GET operations** curated product API.
Это типы wire contract; они не включают transport, token storage, refresh,
permission checks или ORM implementation types. Core `apiClient`, его trust
boundaries и авторизация UI не меняются.
