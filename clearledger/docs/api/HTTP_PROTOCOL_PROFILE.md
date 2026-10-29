# M09: ограниченный HTTP-профиль product API

Проверенная база: `e8e26853da3957f568e1f6c9582c7f2d309decdf`, ветка
`agent/api-http-profile-20261030`. Ниже номера строк исходников относятся к этой
базе, кроме явно указанного нового форматтера. Пути начинаются от
`clearledger/server/app/`. Исходные требования сопоставлены с deploy-документами
`docs/API-PLATFORM.md` и `docs/api/PROTOCOLS-AND-SWAGGER.md`.

Подтверждены и исправлены потери заголовков в `product_api/app.py::_problem`:
параметры Bearer challenge, `Allow`, заданный upstream `Retry-After`, а также
`no-store` и корреляция у необработанного 500. Статусы, безопасные тела Problem,
решения доступа и все 12 GET-операций сохранены. Это проверка ASGI-формата с
синтетическим серверным verifier, не сертификация M10, SQL или всего HTTP-стека.

## Обязательные требования и выбранный профиль

| Основание | Уровень | Применение |
| --- | --- | --- |
| [RFC 6750 §3](https://www.rfc-editor.org/rfc/rfc6750.html#section-3) | MUST | Защищённый ресурс без разрешающих credentials возвращает `WWW-Authenticate`; схема Bearer содержит хотя бы один auth-param. Используем `realm="product-api"`, когда источник не передал точный challenge. |
| [RFC 6750 §3.1](https://www.rfc-editor.org/rfc/rfc6750.html#section-3.1) | SHOULD / MAY | `invalid_token` обычно соответствует 401, `insufficient_scope` 403; конкретный `error` рекомендуется, требуемый `scope` необязателен. Без credentials error раскрывать не рекомендуется. Форматтер не выводит причину из текста generic denial. |
| [RFC 9110 §15.5.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.6) | MUST | У 405 сохраняется фактический `Allow`, полученный от маршрутизатора. |
| [RFC 9457 §3.1.2](https://www.rfc-editor.org/rfc/rfc9457.html#section-3.1.2) | MUST | Поле `status` совпадает с HTTP-статусом. Тело имеет media type `application/problem+json`. |
| [RFC 9457 §3.2, §4.2.1](https://www.rfc-editor.org/rfc/rfc9457.html#section-3.2) | Допустимые extensions / SHOULD | `code` и `requestId` являются extensions. Для `about:blank` title соответствует HTTP-фразе. В detail нет исключений и validation input. |
| [RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3) | MAY | `Retry-After` на 503 необязателен. Если доверенный источник его задал, форматтер сохраняет значение; сам задержку не придумывает. |
| Контракт приложения | Локальное требование | `Cache-Control: no-store`, новый серверный `X-Request-Id`, совпадение с `requestId` Problem, безопасный detail. Это не универсальный MUST перечисленных RFC для всех resource responses. |

Обязательность challenge и рекомендация выбрать статус 403 при недостаточных
полномочиях различаются. Добавление realm к уже принятому решению 403 не меняет
его причину на `insufficient_scope`: отказ может относиться к principal kind,
membership или resource grant.

## 12 операций: реестр, схема и HTTP

Пути ниже относительно `/api/v1`; фабрика child app использует те же пути без
mount prefix. Источник операций: `product_api/app.py:106–169`, политики
`app.py:55–62`, проверка scopes `product_api/access.py:97–103`.

| GET path | operationId | Необходимые scopes, AND | Успех |
| --- | --- | --- | --- |
| `/objects` | `listObjects` | `objects:read` | 200 Page JSON |
| `/objects/{objectId}` | `getObject` | `objects:read` | 200 Object JSON |
| `/objects/{objectId}/monitoring` | `getObjectMonitoring` | `objects:read`, `monitoring:read` | 200 Monitoring JSON |
| `/equipment` | `listEquipment` | `equipment:read` | 200 Page JSON |
| `/equipment/{equipmentId}` | `getEquipment` | `equipment:read` | 200 Equipment JSON |
| `/counterparties` | `listCounterparties` | `counterparties:read` | 200 Page JSON |
| `/counterparties/{counterpartyId}` | `getCounterparty` | `counterparties:read` | 200 Counterparty JSON |
| `/contracts` | `listContracts` | `contracts:read` | 200 Page JSON |
| `/contracts/{contractId}` | `getContract` | `contracts:read` | 200 Contract JSON |
| `/documents` | `listDocuments` | `documents:read` | 200 Page JSON |
| `/documents/{docId}` | `getDocument` | `documents:read` | 200 DocumentDetail JSON |
| `/documents/{docId}/versions/{versionId}/content` | `downloadDocumentVersion` | `documents:read`, `documents.files:download` | 200 octet-stream |

Все operationId уникальны и совпадают с `policy-runtime-registry`. В каждой
операции ровно один Security Requirement `ProductOAuth` со всеми требуемыми
scopes. В [OpenAPI 3.1.1 Security Requirement Object](https://spec.openapis.org/oas/v3.1.1.html#security-requirement-object)
этот список требует все scopes; альтернативы в массиве security имели бы другую
семантику. Для каждого обязательного scope каждой операции HTTP-тест удаляет
только его: результат 403, доменный обработчик не вызван. Все 11 JSON handlers
также возвращают typed 200 через синтетические проекции; файл читается настоящим
StreamingResponse из временного каталога.

Curated schema проходит установленный `OpenAPIV31SpecValidator` офлайн, без
удалённых `$ref`. Успешные media types совпадают с HTTP. Общие schema responses
400/401/403/404/422/503 ссылаются на Problem через `application/problem+json`
(`app.py:97–104, 197–203`). Ни HTTP endpoint raw OpenAPI, ни новая публичная
операция этой работой не добавлены.

## Контрпримеры и положительные контроли

Новый тест: `clearledger/server/tests/test_product_http_profile.py`. Первая
серия из девяти тестов запущена на неизменённом production source указанной базы:
3 PASS, 2 FAIL и 4 ERROR из-за отсутствующих заголовков. После исправления
добавлены ещё три проверки: 400, положительные JSON-операции и status-specific
allowlist. Контроли доступа выполняют настоящий resolver/PolicyRoute, но токен
подтверждает доверенный синтетический verifier.

| Граница и trace базы | Воспроизведённый контрпример | Контроль после исправления |
| --- | --- | --- |
| `access.py:72–77` → HTTPException → `app.py:84–86` → `_problem:44–46` | GET без Authorization: 401 с голым `Bearer`, без обязательного auth-param | Тот же 401 с `Bearer realm="product-api"`, без error; session factory и домен не вызваны |
| Инъецированный verifier → `access.py:80` → `app.py:86` | Источник передаёт 401 `Bearer error="invalid_token"`, форматтер теряет параметр | Точный challenge сохранён, debug detail скрыт; канонический 403 `insufficient_scope` с scope также сохраняется |
| `access.py:98–103` → `app.py:86` | Валидный fixture token без нужного scope: 403 вообще без challenge | 403 с realm, без угаданного error/scope; отказ до домена на всех 12 операциях |
| Framework method dispatch → `app.py:84–86` | POST `/objects`: 405 теряет `Allow: GET` | 405 сохраняет `Allow: GET`; verifier/session/domain не вызваны |
| Инъецированный verifier 503 → `app.py:86` | Переданный `Retry-After: 17` исчезает | Значение сохранено; одновременно переданные Set-Cookie, Location, X-Debug отброшены |
| Домен RuntimeError → outer ServerErrorMiddleware → `app.py:92–94`; user middleware `app.py:76–82` не получает response | Problem 500 содержит requestId, но ответ без X-Request-Id/no-store | Formatter непосредственно ставит оба заголовка; id совпадает с телом, входной attacker id не используется, exception text отсутствует |

Новый центральный formatter находится в `product_api/app.py:35–56`, передача
exception headers в `app.py:94–96`. Allowlist привязан к статусу: challenge
только 401/403, Allow только 405, Retry-After только 429/503. Другие заголовки
не переносятся; отдельный 404-контроль отбрасывает даже имена из allowlist
других статусов. Код не разбирает URL для вывода ACL или error-кода.

Независимые контроли: неизвестный путь 404; неизвестный query, pageSize 0 или
нечисловое значение, literal date `null`, objectId длиной 41 дают безопасный 422;
synthetic domain 400 сохраняет `invalid_cursor`; query token запрещён 401 даже
при наличии Bearer. Flag off даёт 503 до открытия session factory и verifier.
Эти проверки подтверждают формат и порядок отказа, а не SQL-фильтрацию.

## Binary GET и необязательные возможности

Источник без изменений: `product_api/files.py:39–70` проверяет цепочку
doc/version/source и download policy до открытия файла; `files.py:73–84`
передаёт байты и заголовки. В тесте native download ACL и результаты запросов
подменены transport fixtures; это не повторная проверка реальной ACL/SQL.

Синтетический файл с нулевым и не-UTF8 байтом возвращается точно, status 200,
`application/octet-stream`, `nosniff`, `no-store`. Это объявленное opaque binary
представление, MIME по расширению не угадывается. Filename `../Скан 1.pdf`
превращается в basename и UTF-8 `filename*`; формат соответствует
[RFC 6266 §4.3](https://www.rfc-editor.org/rfc/rfc6266.html#section-4.3).
ASCII fallback полезен для старых клиентов, но не обязателен.

При `Range: bytes=0-2` возвращается 200 с полным файлом и без Content-Range:
[RFC 9110 §14.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-14.2)
разрешает игнорировать Range. Это не частичная выдача 206. Поддержка Range и
ETag этим профилем не обещана. `Accept: application/json` также получает
заявленное default binary representation; из отсутствия 406 нарушения не следует
([RFC 9110 §15.5.7](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.7)).
HEAD не объявлен, и новая операция HEAD не вводится.

## Проверка и оставшиеся границы

Из `clearledger/server` выполнено:

```sh
DATABASE_URL='postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/http_profile_test' \
SECRET_KEY='http-profile-only' PYTHONPATH="$PWD" \
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python \
  -m unittest tests.test_product_http_profile tests.test_product_monitoring_unit -v
```

Итог: **20 PASS за 1.636 s** (12 новых protocol tests, 8 существующих monitoring
unit/seam tests). Внутренние subTest по операциям/scopes не посчитаны отдельными тестами.
`unittest` не загружает опасный pytest conftest. Ни engine, ни соединение с БД,
ни lifespan главного приложения для запросов не используются. Импорт ORM
создаёт глобальный engine object из `app/database.py`, но не открывает соединение;
DATABASE_URL здесь только синтетический import-time placeholder с нерабочим портом. Файлы временные,
токены и principal синтетические. Baseline/final журналы остаются локально в
`.artifacts/http-profile-baseline.log` и `.artifacts/http-profile-tests.log`.

Оставшиеся ограничения:

- Настоящий `configured_verifier` (`access.py:44–53`) преобразует PartnerProblem
  в generic HTTPException и не передаёт точный Bearer error. Formatter теперь
  сохраняет предоставленный challenge, но fake verifier не доказывает такое
  поведение M10. Полный диагностический профиль RFC 6750 для настоящего
  invalid_token/insufficient_scope потребует отдельного изменения адаптера;
  угадывать причину по общим 401/403 в этой работе запрещено.
- Схема пока не описывает общие framework 405, внутренние 500 и response headers.
  Это пробел полноты документации, не ошибка JSON schema. Основные объявленные
  error media types проверены; exporter здесь не меняется.
- Проба ASGI не подтверждает TLS, server/proxy Date, wire transfer headers,
  отключение клиента или ошибку после начала streaming response. Требование Date
  относится к фактическому HTTP origin
  ([RFC 9110 §6.6.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-6.6.1));
  отсутствие заголовка в isolated ASGI не доказывает нарушение опубликованного сервера.
- Нет нового прогона JWT/OIDC, SQL isolation, сетевого стенда, remote CI или
  нагрузки. Main mount, tenant/grants, query predicates, cursor, DTO allowlists,
  identity и файловая policy не изменены. Вся M09 и программа этим slice не закрыты.

## Дополнение от 30.10.2026: error/header contract curated OpenAPI

Отдельный metadata-only slice после immutable `e8ffb9ffda0a401039f8cb5d9bcf2daf785bbfd3`.
Предыдущие результаты выше относятся к исходному formatter slice и сохранены.
Теперь его gap по 500/response headers закрыт в **curated exporter**; 405 описан
общим профилем путей. Форматтер, handlers, scopes, DTO, SQL, files и main не менялись.
M12 необходимо перегенерировать типы из нового curated export после интеграции
этого отдельного коммита; main OpenAPI этой работой не подменяется.

Источник новой metadata: `product_api/app.py::_describe_http_responses:192–274`,
вызов из `curated_openapi:317`. `_problem:35–56`, exception handlers и middleware
сохранены из `e8ffb9ff`. Тест: `tests/test_product_openapi_http_contract.py`.

| Наблюдаемое ASGI-поведение | Новое описание в schema | Основание |
| --- | --- | --- |
| 200 JSON/binary и Problem ошибки имеют no-store | Reusable `ProductCacheControl`, const `no-store`, required | Выбор приложения; значение имеет cache-семантику [RFC 9111 §5.2.2.5](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.2.2.5), но RFC не требует посылать его на любой GET |
| Сервер выдаёт X-Request-Id; в Problem он совпадает с requestId | `ProductRequestId`, string/uuid, required | Собственный контракт приложения; не универсальный HTTP-заголовок |
| 401/403 имеют параметризованный Bearer challenge; точные доверенные параметры сохраняются | `ProductBearerChallenge`, required, generic и trusted-verifier examples | [RFC 6750 §3](https://www.rfc-editor.org/rfc/rfc6750.html#section-3); пример invalid_token условный, не обещание текущего M10 adapter |
| Необработанный RuntimeError до начала response даёт safe Problem 500 | Явный response 500 на всех 12 GET, пример status/code/detail | Тот же formatter; тело соответствует [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html#section-3), diagnostic text скрыт |
| Download 200 содержит только octet-stream, attachment filename* и nosniff | Required `ProductContentDisposition`, `ProductNoSniff` на binary 200 | Имя по [RFC 6266 §4.3](https://www.rfc-editor.org/rfc/rfc6266.html#section-4.3); значение nosniff по [Fetch §3.6](https://fetch.spec.whatwg.org/#x-content-type-options-header), отправка здесь является выбором приложения |
| 503 может содержать заданный trusted HTTPException Retry-After или не содержать его при flag off | Optional `ProductRetryAfter`; string допускает delay/HTTP-date | [RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3), не обещание retry delay у каждого отказа |
| POST на любом известном пути получает 405 и Allow GET до handler | `ProductMethodNotAllowed` через shared `x-elsy-http-profile.knownPaths` | [RFC 9110 §15.5.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.6); POST-операция, новый scope и GET response 405 не добавлены |

Header components используются через локальные `$ref`. Content-Type представлен
через `content`, а не как игнорируемый response Header; это соответствует
[OpenAPI 3.1.1 Response/Header Objects](https://spec.openapis.org/oas/v3.1.1.html#response-object).
Все примеры Problem содержат type/title/status/code/requestId/detail; тест
проверяет JSON Schema и совпадение полей примера с фактическим безопасным телом,
исключая динамический requestId. Заголовок UUID проверяется отдельно и совпадает
с requestId тела. Примеры не содержат настоящие токены, ID пользователей или
прикладные данные.

### 429 и граница приложения

`ProductInjectedRateLimit` описывает **только** явно брошенный application
HTTPException(429), через `x-elsy-http-profile.injectedApplicationRateLimit`.
Тест доверенного verifier fixture воспроизводит 429 с Retry-After 17. Текущий
formatter сохраняет status 429 и отдаёт generic `code=internal_error`; пример
честно отражает это поведение. Новый встроенный limiter не появился, 429 не
объявлен гарантированным ответом каждого GET.

Ответы nginx/proxy, включая HTML 429, находятся вне этого контракта; edge-профиль
пока не унифицирован и здесь не проверялся. Default response намеренно не добавлен,
чтобы не обещать Problem и заголовки для всех внешних отказов. Уже начавшийся
stream также нельзя заменить Problem 500. Range/ETag/206 не добавлены и не обещаны.

### Проверки дополнения

Первый прогон нового набора на неизменённом `e8ffb9ff`: 7 тестов,
`FAILED (errors=99)`, включая subTest по операциям, из-за отсутствующих
headers/500/shared profile; контроль registry/security/readiness проходил.
Это 99 отдельных ошибок проверок, не 99 независимых тестов. Затем добавлен
отдельный контроль optional Retry-After и точных trusted challenges.

Итоговый запуск из `clearledger/server`, с теми же синтетическими import-time
DATABASE_URL/SECRET_KEY и без pytest conftest:

```sh
DATABASE_URL='postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/http_profile_test' \
SECRET_KEY='http-profile-only' PYTHONPATH="$PWD" \
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -m unittest \
  tests.test_product_openapi_http_contract \
  tests.test_product_http_profile tests.test_product_monitoring_unit -v
```

Результат: **28 PASS за 3.480 s** (8 новых contract tests и прежние 20 offline controls).
Новый набор проверяет положительные ответы всех 12 handlers, 401/403/422/503
до доменного эффекта, synthetic domain 400/404/500 на каждой операции, binary
bytes, shared 405, optional 503 Retry-After и injected 429. Это реальные ASGI
запросы через настоящий resolver/PolicyRoute с fake verifier и domain fixtures;
monitoring aggregation/native download ACL/SQL подменены явно. Никакой проверки
JWT, реальной БД или TLS этим не заявляется.

Офлайн-gate проверяет OpenAPI 3.1, все локальные `$ref`, actual JSON и примеры
через Draft 2020-12 с FormatChecker. Внешний `$ref`/`$dynamicRef` и неизвестный format `uuuid`
отклоняются до validator resolution; неверный UUID примера и строковый status
Problem также отклоняются. Это строгий локальный gate: базовая
[JSON Schema format vocabulary](https://json-schema.org/draft/2020-12/json-schema-validation#section-7.2)
не обязана сама отвергать неизвестные formats. `binary` разрешён как известная
OpenAPI-аннотация; байты проверяет отдельный transport assertion.

Registry по-прежнему содержит ровно 12 операций, прежние operationId/owner,
`kind=policy-runtime-registry`, переданный sourceRevision и readiness `candidate`.
Security Requirement со всеми scopes в одном AND-списке сохранён. Ни нового
публичного schema endpoint, ни runtime-verified флага нет. Локальные журналы:
`.artifacts/http-contract-baseline.log`, `.artifacts/http-contract-tests.log`.
В серии 500 наблюдались AnyIO ResourceWarning о незакрытых memory streams;
предупреждения не скрывались, причины и wire/runtime последствия этим slice
не устанавливались. Edge errors, M10 diagnostics, streaming failures, remote CI
и нагрузка остаются отдельными проверками.

Дополнительно AST-сравнение с `e8ffb9ff` подтвердило неизменность Settings,
`_problem`, query dependency, `_policy`, `create_product_api` и runtime registry
exporter. Прежний текст отчёта сохранён побайтно как prefix этого документа;
`git diff --check` проходит. Изменение схемы сообщено координатору до коммита.


Дополнение M15, composed21e60c76: появился отключённый по умолчанию общий
PostgreSQL budget после live identity/ACL и до domain/parameter validation.
Его собственный BudgetExceeded возвращает429 code=rate_limited и integer
Retry-After>=1; generic injected HTTPException429 сохраняет internal_error.
Curated schema содержит оба условия/примера и общий429 на12операциях;
приведённые выше baseline строки относятся к исходному M09. Fail-closed503
при недоступности quota store не заменяет401/403 проверки до него.
Точный алгоритм, ограничения и evidence: [product-budget-20261030.md](product-budget-20261030.md).
Это request admission, не квота байтов/одновременных streaming downloads и не
периметровый лимит неавторизованных запросов. Координатор независимо повторил41offline,12SQL/process и31Core/public schema
проверок — PASS. Это не приёмка производственной нагрузки.
