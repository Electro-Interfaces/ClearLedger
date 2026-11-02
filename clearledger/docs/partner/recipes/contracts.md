# Договор: создание и чтение связей

[Начало](../onboarding.md) · [Вход](../auth.md) · [Словарь](../data-dictionary.md) ·
[Ошибки](../errors.md) · [Каталоги](read-catalogs.md) · [Мониторинг](monitoring.md) · [Документы](documents.md)

Candidate/default-off; source pin
`9eb236a4d69f0452208857ac603fd1da515f52d8`. Здесь шесть GET и один POST:
шесть операций user/service и одна user-only. Полный состав — в
[единой таблице 17 операций](../../PARTNER_QUICKSTART.md#current-source-contract-20261101).
Примеры fictional; HTTP/schema/runtime **NOTRUN**.
Все запросы идут по HTTPS к `sandbox.example.invalid`, GET body отсутствует.
Для READ без документов допустим User или machine partner access token;
для documents relation требуется **delegated User**, не machine.
CREATE/options имеют самостоятельный текущий CREATE-профиль.

Этот read walkthrough подходит для разрешённой витрины договорных карточек.
Полные rental/energy/operations процессы, деньги, условия расчётов, изменения,
согласование и SLA не входят в текущий DTO. Type code и ссылки не заменяют
юридическое толкование и не доказывают историческое действие договора.

## Создание договора

GET вариантов и POST требуют `contracts:create` и текущий CREATE-профиль
установки: разрешённого пользователя либо явно approved machine grant
confidential client с включённым user/service разрешением профиля. Разрешённые
organization/counterparty/location и активный typeCode пересекаются с текущими
resource grants и пользовательскими ограничениями. `contracts:read` не требуется
и не является CREATE authority. Успех не выдаёт READ, document/file ACL или
доступ к внутренним операциям. Сначала согласуйте этот профиль с владельцем.

<!-- operation:getContractCreateOptions -->
### getContractCreateOptions: advisory варианты

```http
GET /api/v1/contracts/create-options?resource=type&pageSize=50 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <CREATE_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "resource": "type",
  "items": [{"value": "fictional-type"}],
  "selectionVersion": "fictional-opaque-version",
  "nextCursor": null
}
```

Это полный вымышленный DTO, не результат выполнения. Обязательный `resource` —
`organization`, `counterparty`, `location` или `type`; `pageSize` 1..100, default 50.
Для следующей страницы передайте полученный непрозрачный cursor (1..2048),
сохранив resource/pageSize. Request cursor optional nullable в схеме, response
`nextCursor` обязателен и nullable; новый обход начинают **без cursor**, literal
`cursor=null` не является null. Не передавайте q, typeCode или tenant override.
`items[].value` — точное значение без label/internal authority ID; UUID
канонические, opaque location/type сохраняют строковую идентичность.
Не изменяйте value/selectionVersion/cursor и не выводите из них разрешения.
Для каждого resource нужен свой обход; законный пустой набор даёт 200.

Cursor связан со всем текущим профилем, токеном и контекстом страницы, TTL до
300 секунд. После текущей авторизации изменённый/просроченный cursor даёт:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Bad Request","status":400,"code":"invalid_cursor","requestId":"80000000-0000-4000-8000-000000000001","detail":"Cursor is invalid or belongs to another query"}
```

Следующий шаг: начать новый обход без cursor, не трактовать 400 как конец списка.
Профиль и choices одного GET читаются в одном read-only REPEATABLE READ snapshot
t0 после отдельного preflight и квоты. Отзыв до t0 учитывается, после t0 может
не попасть в ответ; canonical verifier проверяет expiry/process gates ещё раз
перед DTO, DB-чтения всё ещё на t0. Общий deadline 10 секунд или переполнение
closure даёт общий 503 без partial response. Это не SLA и не snapshot между
страницами. Choices могут измениться: selectionVersion не receipt,
резервирование или admission и не поле POST. POST заново проверяет authority.

<!-- /operation:getContractCreateOptions -->

<!-- operation:createContract -->
### createContract: строгое тело и безопасный replay

```http
POST /api/v1/contracts HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <CREATE_ACCESS_TOKEN_PLACEHOLDER>
Content-Type: application/json
Accept: application/json
```

```json
{
  "kind": "contract-card",
  "creationKey": "90000000-0000-4000-8000-000000000001",
  "number": "FICTIONAL-CREATE-1",
  "date": "2026-11-01",
  "type": "Fictional agreement",
  "typeCode": "fictional-type",
  "organizationId": "10000000-0000-4000-8000-000000000001",
  "counterpartyId": "40000000-0000-4000-8000-000000000001",
  "coverage": {
    "kind": "locations",
    "locationIds": ["20000000-0000-4000-8000-000000000001"]
  },
  "validUntil": null,
  "comment": null
}
```

Пример предполагает разрешённые вымышленные ссылки и активный typeCode; сами
значения ничего не разрешают. Тело ограничено **16384 фактическими байтами**,
независимо от Content-Length. Только один Content-Type application/json
(допустим charset=utf-8); Content-Encoding отсутствует либо identity. Gzip и
другие media дают 415, превышение тела — 413. Невалидный UTF-8/JSON, дубли
ключей, лишние поля и coercion типов не принимаются (422).

Все поля обязательны, кроме optional nullable `comment` до 2000 символов.
`validUntil` **обязателен**, но nullable: строка до 20 символов, не гарантированная
ISO date. Number/type — непустые, не пробельные строки до 100 символов;
typeCode — до 256, без trim/case folding. Date — calendar `YYYY-MM-DD`,
creationKey/organizationId/counterpartyId — UUID в формате с дефисами.
Coverage только locations, 1..100 уникальных точных locationIds длиной 1..40,
без NUL. Number/type/typeCode/locationIds сохраняют пробелы и регистр;
NUL запрещён во всех текстовых полях. CompanyId, arbitrary attrs, selectionVersion, If-Match и
Idempotency-Key как часть CREATE-контракта не объявлены.

Новый результат (полный DTO):

```http
HTTP/1.1 201 Created
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"contractId":"50000000-0000-4000-8000-000000000001","replayed":false}
```

Авторизованный повтор сохранённого намерения:

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"contractId":"50000000-0000-4000-8000-000000000001","replayed":true}
```

Ответ не содержит читаемую карточку и не обещает Location. Для дальнейшего
GET нужны отдельные `contracts:read`, typed contracts grant и current actor.
Карточка, связи, intent и аудит сохраняются атомарно. При потере ответа исход
неизвестен: сохраните исходное тело и creationKey, выполните ограниченный новый
запрос с текущей авторизацией исходного grant/actor/CREATE-профиля и ссылок.
Не меняйте ключ из-за timeout. Replay не обходит отзыв или текущие ограничения.
Тот же ключ с другим содержимым либо конфликт идентичности после полной
текущей CREATE-авторизации даёт общий отказ без чужих ID:

```http
HTTP/1.1 409 Conflict
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Conflict","status":409,"code":"conflict","requestId":"80000000-0000-4000-8000-000000000001","detail":"Request conflicts with current state"}
```

Следующий шаг: остановить автоматические повторы и согласовать намерение;
новый ключ не является способом обхода конфликта. При отказе текущих прав
действуют 401/403, а не гарантированный replay/409. Остальные отказы, quota 429
и ограниченные повторы описаны в [ошибках](../errors.md).

<!-- /operation:createContract -->

<!-- operation:listContracts -->
## listContracts: текущие доступные договоры

Требуются `contracts:read`, typed contracts grant и current actor. Чтобы получить
ненулевой counterpartyId в примере, также нужен независимый доступ к стороне
(`counterparties:read` и её grant). `q` ищет номер; даты фильтруют UTC created_at,
а не contract.date. `typeCode` — exact source, без trim/case folding.

```http
GET /api/v1/contracts?pageSize=50&typeCode=fictional-type&dateFrom=2026-10-01&dateTo=2026-10-31 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "items": [
    {
      "id": "50000000-0000-4000-8000-000000000001",
      "number": "FICTIONAL-1",
      "date": "2026-10-01",
      "title": "Fictional agreement",
      "isClosed": false,
      "scopeType": "locations",
      "counterpartyId": "40000000-0000-4000-8000-000000000001",
      "typeCode": "fictional-type",
      "validUntil": null
    }
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ, например добавлен неподдерживаемый `counterpartyId` или неверная дата:

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Unprocessable Entity","status":422,"code":"invalid_request","requestId":"80000000-0000-4000-8000-000000000001","detail":"Request parameters are invalid"}
```

Следующий шаг: исправить query по [словарю](../data-dictionary.md); не переносить
фильтры внутренних экранов на partner API. После 200 продолжать с теми же
typeCode/dateFrom/dateTo/pageSize и cursor либо читать карточку. Null validUntil
сохранять неизвестным: это не «бессрочно», а ненулевое значение было бы исходной
строкой до 20 символов без гарантии ISO date.

<!-- /operation:listContracts -->

<!-- operation:getContract -->
## getContract: карточка договора

`contracts:read`, typed contracts grant, current actor. Query пустой. Связь
counterpartyId остаётся nullable и проверяется независимо.

```http
GET /api/v1/contracts/50000000-0000-4000-8000-000000000001 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "id": "50000000-0000-4000-8000-000000000001",
  "number": "FICTIONAL-1",
  "date": "2026-10-01",
  "title": "Fictional agreement",
  "isClosed": false,
  "scopeType": "locations",
  "counterpartyId": "40000000-0000-4000-8000-000000000001",
  "typeCode": "fictional-type",
  "validUntil": null
}
```

Отказ для отсутствующего или независимо недоступного договора:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: сверить ID с доступным списком и owner grant. После 200 можно
получить подпись exact typeCode, объекты и документы, не выводя разрешения этих
ресурсов из самого факта доступности договора.

<!-- /operation:getContract -->

<!-- operation:getContractTypeMetadata -->
## getContractTypeMetadata: подпись исходного кода

`contracts:read`, typed contracts grant и видимый договор с **точно таким**
`typeCode`. Только query `typeCode` (1..256 символов, без NUL), GET без body.
Это не enumeration глобального справочника. `fictional-type` специально выбран
как вымышленный код видимого договора, для которого metadata неизвестны.

```http
GET /api/v1/contract-types?typeCode=fictional-type HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "typeCode": "fictional-type",
  "label": null,
  "gkBasis": null,
  "direction": null,
  "isActive": null
}
```

Отказ для кода, не используемого независимо доступным договором:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: взять exact code из текущего доступного contract DTO; не угадывать
чужие классификаторы. После 200 отобразить исходный код с неизвестной подписью,
сохранив все null. Если metadata известны, inactive `isActive: false` сохраняет
историческую подпись; это не автоматическое закрытие договора. Пустой source code
в contract DTO не делает допустимым пустой query. TypeCode, direction, gkBasis
не превращаются в клиентский юридический enum.

<!-- /operation:getContractTypeMetadata -->

<!-- operation:listContractObjects -->
## listContractObjects: явные текущие объекты

Требуются **`contracts:read` AND `objects:read`**, два независимых typed grants
и current actor. Видимость договора не даёт права на все объекты компании.
Query принимает **только** pageSize (1..200, default 50) и cursor.

```http
GET /api/v1/contracts/50000000-0000-4000-8000-000000000001/objects?pageSize=50 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "contractId": "50000000-0000-4000-8000-000000000001",
  "scopeType": "locations",
  "items": [
    {"objectId": "20000000-0000-4000-8000-000000000001"}
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ при отсутствии одного из scopes или одного typed grant:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
WWW-Authenticate: Bearer realm="product-api"
```

```json
{"type":"about:blank","title":"Forbidden","status":403,"code":"access_denied","requestId":"80000000-0000-4000-8000-000000000001","detail":"Access is denied"}
```

Следующий шаг: сверить оба набора разрешений у владельца. После 200 прочитать
`GET /api/v1/objects/{objectId}` для каждого разрешённого ID и продолжить relation
cursor с тем же pageSize. Не переносить date/q/typeCode из contracts list.
При scopeType company/unassigned или любом режиме без locations список пуст,
он не разворачивается на всю сеть. Пустой items не доказывает отсутствие
юридической связи или исторического покрытия. Данные и count live.

<!-- /operation:listContractObjects -->

<!-- operation:listContractDocuments -->
## listContractDocuments: явные документы, только User

Требуются delegated User, **`contracts:read` AND `documents:read`**, отдельные
typed grants contracts/documents и актуальный native document ACL. Связи
subject/graph проверяются в текущей компании; документы фильтруются независимо
до count/page. Query — только pageSize/cursor, GET без body.

```http
GET /api/v1/contracts/50000000-0000-4000-8000-000000000001/documents?pageSize=50 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <DELEGATED_USER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "contractId": "50000000-0000-4000-8000-000000000001",
  "items": [
    {"documentId": "60000000-0000-4000-8000-000000000001"}
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ, например machine principal либо отсутствующий необходимый scope/grant:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
WWW-Authenticate: Bearer realm="product-api"
```

```json
{"type":"about:blank","title":"Forbidden","status":403,"code":"access_denied","requestId":"80000000-0000-4000-8000-000000000001","detail":"Access is denied"}
```

Следующий шаг: использовать самостоятельное delegated согласие с достаточными
текущими правами; machine token нельзя превратить в User добавлением заголовка.
Ветвь 403 с machine иллюстрирует проверку principal; более ранний verifier может
отклонить непригодный machine grant иначе. После 200 пройти
[document detail → versions → content](documents.md) и все страницы relation.
Чтение связи не выдаёт download scope или file ACL; отсутствующий/недоступный
договор по-прежнему может дать 404, а пустая relation не является глобальным
поиском документов договора.

<!-- /operation:listContractDocuments -->

## Свидетельства исходников

Текущие свидетельства на `9eb236a4d69f0452208857ac603fd1da515f52d8`:

- `clearledger/server/app/product_api/app.py:528–586`: CREATE/options policies, candidate metadata и status.
- `clearledger/server/app/product_api/contract_create_body.py:ContractCreateBody, parse_contract_create_body`: единственный strict wire body.
- `clearledger/server/app/product_api/contract_create_options.py:request_lifetime, options`: t0, cursor, deadline и advisory boundary.
- `clearledger/server/app/services/partner_contract_authority.py:_require_coarse_create, select_create_domains, CreateOperation.policy` и `clearledger/server/app/services/partner_contract_commands.py:create_partner_contract`: current authority, replay и conflict.

Принятые серии ограничены своими pins/suites:
[HTTP CREATE](../../api/CONTRACT_CREATE_HTTP_ROOT_VERIFICATION_20261101.md),
[options](../../api/PARTNER_CREATE_OPTIONS_ROOT_VERIFICATION_20261101.md),
[405/SDK](../../api/PARTNER_OPENAPI_405_SDK_ROOT_VERIFICATION_20261101.md).
Здесь они не исполнялись заново; whole M09/SDK, final CI, ingress и production
этой редакцией не принимаются. Исходная программа M00–M19 и 11 gates остаётся OPEN.

История: пять READ-методов этой страницы относились к срезу 15 GET на
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`; номера строк ниже относятся к нему:

- `clearledger/server/app/product_api/app.py:171–214`: пять методов, scopes, kinds и запрет body у metadata/relations.
- `clearledger/server/app/product_api/dto.py:57–120,202–212`: exact code, relation DTO, raw validUntil.
- `clearledger/server/app/product_api/queries.py:174–236`: independently visible classifier, явные object и subject/graph document links.
- `clearledger/server/app/product_api/queries.py:238–278`: redaction и source-value projection.
- `clearledger/server/app/product_api/access.py:98–151`: AND scopes, independent grants, current actor.

Далее: [документы, версии и файл](documents.md) · [мониторинг объектов](monitoring.md).
