# M12: wire types внешнего product API

30.10.2026. База этого slice — `e94427bf6af8bbb84206dfc7f982bd7718ff0c52`,
ветка `agent/api-wire-types-20261030`. Генерируемый файл:
`src/generated/partner-api.d.ts`. Он экспортирует `paths`, `components`,
`operations` реальных **12 candidate GET operations** curated product API.
Это типы wire contract; они не включают transport, token storage, refresh,
permission checks или ORM implementation types. Core `apiClient`, его trust
boundaries и авторизация UI не меняются.

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

Adapter дополнительно проверен **semantic parity**: отдельный hermetic процесс
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
import type { components, operations } from "./partner-api";

type ObjectWire = components["schemas"]["Object"];
type ObjectPage = operations["listObjects"]["responses"][200]["content"]["application/json"];
type ObjectsQuery = NonNullable<operations["listObjects"]["parameters"]["query"]>;

const query: ObjectsQuery = { pageSize: 50, dateFrom: "2026-01-02" };
const label = (point: ObjectWire) => point.name;
```

Compile fixture также проверяет required nullable fields, numeric pageSize,
отсутствие companyId override, write operation и JSON у binary download через
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

## Результат и границы

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
