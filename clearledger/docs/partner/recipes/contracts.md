# Договор → классификатор → объекты → документы

[Начало](../onboarding.md) · [Вход](../auth.md) · [Словарь](../data-dictionary.md) ·
[Ошибки](../errors.md) · [Каталоги](read-catalogs.md) · [Мониторинг](monitoring.md) · [Документы](documents.md)

Candidate/default-off; source pin
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Здесь пять из 15 GET: четыре
user/service и один user-only. Примеры fictional; HTTP/schema/runtime **NOTRUN**.
Все запросы идут по HTTPS к `sandbox.example.invalid`, GET body отсутствует.
Для первых четырёх методов допустим User или machine partner access token;
для documents relation требуется **delegated User**, не machine.

Этот read walkthrough подходит для разрешённой витрины договорных карточек.
Полные rental/energy/operations процессы, деньги, условия расчётов, изменения,
согласование и SLA не входят в текущий DTO. Type code и ссылки не заменяют
юридическое толкование и не доказывают историческое действие договора.

<!-- operation:listContracts -->
## 7. listContracts: текущие доступные договоры

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
## 8. getContract: карточка договора

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
## 9. getContractTypeMetadata: подпись исходного кода

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
## 10. listContractObjects: явные текущие объекты

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
## 12. listContractDocuments: явные документы, только User

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

Commit `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`:

- `clearledger/server/app/product_api/app.py:171–214`: пять методов, scopes, kinds и запрет body у metadata/relations.
- `clearledger/server/app/product_api/dto.py:57–120,202–212`: exact code, relation DTO, raw validUntil.
- `clearledger/server/app/product_api/queries.py:174–236`: independently visible classifier, явные object и subject/graph document links.
- `clearledger/server/app/product_api/queries.py:238–278`: redaction и source-value projection.
- `clearledger/server/app/product_api/access.py:98–151`: AND scopes, independent grants, current actor.

Далее: [документы, версии и файл](documents.md) · [мониторинг объектов](monitoring.md).
