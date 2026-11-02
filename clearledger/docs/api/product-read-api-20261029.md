# Versioned product read API — исполняемый кандидат M05–M09

29.10.2026, основа `e3bb61a9`. Новый пакет `server/app/product_api` предоставляет
`create_product_api() -> FastAPI` для будущего mount `/api/v1`. Основной `main`,
legacy routes, auth/config, M10, модели и domain commands не изменены.
Пакет не монтирует себя и не публикует HTTP Swagger/raw spec.

## Операции

Все операции — реальные typed GET handlers с исполняемым `PolicyRoute`.

| Относительный путь | operationId | Обязательные scopes |
|---|---|---|
| `/objects` | `listObjects` | `objects:read` |
| `/objects/{objectId}` | `getObject` | `objects:read` |
| `/equipment` | `listEquipment` | `equipment:read` |
| `/equipment/{equipmentId}` | `getEquipment` | `equipment:read` |
| `/counterparties` | `listCounterparties` | `counterparties:read` |
| `/counterparties/{counterpartyId}` | `getCounterparty` | `counterparties:read` |
| `/contracts` | `listContracts` | `contracts:read` |
| `/contracts/{contractId}` | `getContract` | `contracts:read` |
| `/documents` | `listDocuments` | `documents:read` |
| `/documents/{docId}` | `getDocument` | `documents:read` |
| `/documents/{docId}/versions/{versionId}/content` | `downloadDocumentVersion` | `documents:read`, `documents.files:download` |

Scopes строго совпадают с каталогом M10; dot aliases и wildcard не принимаются.
JSON — camelCase, идентификаторы — opaque strings. DTO содержат явный allowlist:
нет raw/attrs, storage paths, source refs, retention snapshots, токенов, банковских
реквизитов или внутренних полей ORM. Недоступные object/counterparty ссылки
возвращаются как null, включая отсутствие отдельного read scope на целевой ресурс.
Неизвестные координаты, мощность и дата источника сохраняются null, не 0.

`ServiceLocation` выдаётся как `level=servicePoint`; оборудование — только
`EzsEquipmentUnit(kind=station)`, `level=station`. Другие kind не выдаются как станция.
Site, EVSE, connector, CRUD, machine document access и исторический listing версий
не реализованы. Матрица implemented/gap включена в `x-elsy-capabilities` схемы.
Деталь документа содержит только активные current versions, максимум 200,
с явным `versionsTruncated`.

## Серверный контекст и ограничения

Без `partner_api_enabled=True` запрос к операции возвращает 503 до открытия
session, verifier и data queries. Отсутствие поля настроек означает deny.
M10 отдельно владеет `partner_oauth_enabled` и текущей проверкой credentials;
его выключение/отсутствие/неполная конфигурация также не открывает данные.

Default resolver принимает только Authorization Bearer и deferred-вызовом
делегирует `partner_identity.verify_partner_access_token(token, db)`. Собственного
JWT parser/issuer и fallback к Core user/handoff/refresh/id tokens нет.
Verifier получает отдельную управляемую async session, которая закрывается;
read queries работают в другой управляемой session без commit.
HTTPException verifier и PartnerProblem503 переводятся в child Problem Details
без текста исключения и без OAuth error body.

Verified user grant становится PARTNER с настоящим текущим User/UserCompany;
registered machine — SERVICE без фиктивного User. Документы и content принимают
только PARTNER. Missing membership, истёкшие/неполные verified facts, отсутствие
нужного scope/grant/kind отклоняются до handler и resource queries.
Company берётся только из verified token. Headers, query и path не задают tenant;
неизвестные selectors/параметры отклоняются.

Для каждого ресурса требуется его самостоятельный grant из immutable
`resource_scopes`; missing/EMPTY дают 403 до SQL. ALL/SET применяются к id в SQL
до count/limit. Скоуп объектов пользователя и compatibility location ceiling
пересекаются явно: NULL означает ALL, сохранённый пустой список — EMPTY.
Даже admin/superadmin не расширяет partner grant. EMPTY user-object ceiling
даёт пустой список и 404 детали, сохраняя самостоятельный resource grant.

Own organization токена и текущего участника пересекаются; конфликт даёт 403,
чужая Organization не принимается. Contracts/parties не открываются object grant:
им нужен собственный resource grant. При ограниченном user object scope договор
должен иметь `scope_type=locations` и совместимый `contract_locations`, а сторона —
совместимый договор. Company/unassigned scope не считается молчаливым ALL.
Коррелированные EXISTS сохраняют одну строку на сущность. Own-org фильтр применяется
к договорам, сторонам, документам и связанным объектам/оборудованию.

Документы дополнительно используют текущую native readable policy `doc_access`;
для user grant перепроверяется доступ к продукту документов. Чужая или закрытая
деталь имеет одинаковый 404.

## Content

Проверяются отдельный download scope, resource grant, readable doc ACL, native
`_can_doc(download)` и `authorize_docs_file_download`, затем строгая цепочка
company → doc → version → SourceFile той же компании. Tombstone/purge/retention
не обходятся. Содержимое читается настоящими байтами только из UPLOAD_DIR:
openat/dir_fd с O_NOFOLLOW для каждого компонента, запрет выхода из корня,
symlink и не-regular file. Streaming идёт ограниченными блоками; descriptor
закрывается идемпотентно при завершении/отмене. Response — attachment/octet-stream,
no-store/nosniff. Query token не принимается.

SourceFile с task/chat/conf/store привязкой здесь консервативно закрыт 404:
DocVersion link не должен обходить private guard другого домена. Координатор
согласовал этот fail-closed gap до извлечения канонической shared-file policy;
копии ACL из HTTP routers и вызова HTTP handlers нет. Native legacy `/files`
не изменён.

## Фильтры и пагинация

Списки принимают только `pageSize` (1…200, default 50), `cursor`, `q`, `dateFrom`,
`dateTo`. Даты — ISO, по created_at в UTC, обе границы включительны; dateTo
9999-12-31 не переполняется. Invalid/unknown/null-as-string не превращаются в 0
или ALL. Числовые epoch-строки вроде dateFrom=0 и timestamps вместо даты
явно отклоняются, включая неявную конверсию Pydantic. Детали и content
не принимают query-параметры.

Порядок `(created_at, id)` даёт unique tie breaker. HMAC cursor связывает ресурс,
client/subject/installation/grant/company, policy/scopes, current object/own-org
ограничения, resource grants, фильтры и размер страницы. Другой ресурс/фильтр/grant
или новое сужение возвращают safe 400 до count/list. `total` относится ко всему
разрешённому отбору, не оставшейся части после cursor. Это live pagination,
не неизменяемый исторический snapshot при конкурентных правках.
Default signing key — случайный in-memory ключ child app: рестарт инвалидирует
курсоры. Для устойчивости интегратор может передать отдельный server `cursor_key`.

## Ошибки, schema, registry

Child возвращает `application/problem+json`: type/title/status/code/requestId/detail.
RequestId генерирует сервер и дублирует в X-Request-Id. 422 не содержит input,
stacktrace или текста исключения. OAuth endpoints принадлежат M10 и сохраняют
свой RFC error contract; child не является OAuth endpoint.

`curated_openapi(child)` строит свежую OpenAPI 3.1 из фактических typed handlers:
общие Id/Page/Problem, OAuth2/scopes, binary response, x-elsy-owner/access-class/
resource-policy/readiness. Нужен явно переданный настроенный HTTPS space issuer;
authorize/token URL — `/api/oauth2/authorize`, `/api/oauth2/token` этого issuer.
Никакого runtime-verified=true из описания не выставляется.

`export_runtime_registry(child)` возвращает kind=policy-runtime-registry,
sourceRevision, mountPath=/api/v1 и 11 фактических method/path/operationId/owner/accessClass.
Default paths относительны child и совпадают с OpenAPI; explicit prefix позволяет
отдельно получить mounted paths. Access class — partner, grant описывает resource policy.
При интеграции передать реальный build SHA как `source_revision`; default
`unverified` не подтверждает выпуск. Curated exporter рассматривает только child,
не публикует main/legacy schema. Выкатка и защищённый publisher сюда не входят.

## Приёмка

Выделенная локальная PostgreSQL координатора: api-modernization-test-20261029,
127.0.0.1:33546, база `api_product_test`; только явный TEST_DATABASE_URL.
Conftest прочитан до запуска: удаляет public/edge. Новый модуль до fixtures
отказывается запускать SQL acceptance на другом адресе/имени базы. Все данные,
клиенты, пользователи, компании, токены-verifier fixtures и upload roots синтетические.

Из `clearledger/server`, с явными TEST_DATABASE_URL, UPLOAD_DIR и тестовым SECRET_KEY:

```sh
PYTHONPATH="$PWD" /srv/projects/api-modernization-test-env-20261029/.venv/bin/python \
  -m pytest -q tests/test_product_api.py tests/test_api_contracts_context.py tests/test_api_contracts_http.py
```

Результат: **57 product HTTP+SQL + 90 contracts = 147 PASS**, 28.77 с,
без FAIL/SKIP. Одна upstream DeprecationWarning Starlette/anyio BlockingPortal.

Product HTTP+SQL tests проверяют два company/client, ALL/SET/EMPTY, актуальные
object/own-org/modules, 404 isolation, независимые grants/fieldlinks, native strict
ACL и настоящие bytes, цепочки/удаление/purge/path/symlink/shared files, cursor
без потерь при равных timestamp и rebinding, no-secret DTO и safe errors,
guard-before-SQL, schema refs и формальную OpenAPI 3.1 validation.
Формальный validator использует имеющийся `openapi_spec_validator`; при его
отсутствии только отдельная formal validation получает явный SKIP.

Лог: `.artifacts/product-api-pytest.log`. Fake verifier acceptance **не является**
проверкой OIDC цепочки: основной координатор отдельно объединяет M10 и product
и проверяет реальные зарегистрированные credentials/отзыв. Main mount, конфигурация,
release, PR/merge и завершение всех M05–M09 не выполнялись.
