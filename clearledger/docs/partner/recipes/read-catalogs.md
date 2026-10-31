# Чтение объектов, оборудования и контрагентов

[Начало](../onboarding.md) · [Вход](../auth.md) · [Словарь](../data-dictionary.md) ·
[Ошибки](../errors.md) · [Договоры](contracts.md) · [Мониторинг](monitoring.md) · [Документы](documents.md)

Candidate/default-off, source-only; pin
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Здесь шесть из 15 GET,
все user/service. HTTP/schema/runtime **NOTRUN**, данные вымышлены.
`<PARTNER_ACCESS_TOKEN_PLACEHOLDER>` заменяется partner access token из
[выбранного flow](../auth.md), User либо machine, с нужными правами.
В GET body отсутствует. `Host` относится к HTTPS origin
`https://sandbox.example.invalid`; tokens не передаются в query.

<!-- operation:listObjects -->
## 1. listObjects: список точек

Требуются `objects:read`, independent typed objects grant и текущие ограничения
актора. Пример получает записи, созданные за октябрь по UTC, с поиском по имени.

```http
GET /api/v1/objects?pageSize=50&q=Fictional&dateFrom=2026-10-01&dateTo=2026-10-31 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

Успех, полный page и полный Object:

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
      "id": "20000000-0000-4000-8000-000000000001",
      "level": "servicePoint",
      "code": "FICTIONAL-POINT-1",
      "name": "Fictional point",
      "type": "ev_charging",
      "status": "active",
      "address": null,
      "latitude": null,
      "longitude": null
    }
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ, например нет пригодного partner Bearer:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
WWW-Authenticate: Bearer realm="product-api"
```

```json
{"type":"about:blank","title":"Unauthorized","status":401,"code":"invalid_credentials","requestId":"80000000-0000-4000-8000-000000000001","detail":"Valid partner Bearer credentials are required"}
```

Следующий шаг: восстановить доступ через [auth](../auth.md), не передавать ID/Core
token вместо access token. После 200 сохранить точный ID и прочитать карточку
ниже. При ненулевом cursor повторять **те же** `q/dateFrom/dateTo/pageSize`, добавив
`cursor=<URL_ENCODED_NEXT_CURSOR>`; завершать только на null.

<!-- /operation:listObjects -->

<!-- operation:getObject -->
## 2. getObject: карточка точки

Те же `objects:read`, typed objects grant и current actor. Query пустой; path ID
берётся из list без нормализации.

```http
GET /api/v1/objects/20000000-0000-4000-8000-000000000001 HTTP/1.1
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
  "id": "20000000-0000-4000-8000-000000000001",
  "level": "servicePoint",
  "code": "FICTIONAL-POINT-1",
  "name": "Fictional point",
  "type": "ev_charging",
  "status": "active",
  "address": null,
  "latitude": null,
  "longitude": null
}
```

Отказ для отсутствующего либо недоступного ID:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: обновить разрешённый каталог и сверить grant с владельцем,
не проверять догадки о чужих IDs. После 200 переходить к оборудованию или
[мониторингу](monitoring.md). Object `status` паспортный, не мониторинговая оценка.

<!-- /operation:getObject -->

<!-- operation:listEquipment -->
## 3. listEquipment: станционное оборудование

Требуются `equipment:read` и самостоятельный typed equipment grant. Для ненулевого
`objectId` в проекции дополнительно нужны `objects:read` и независимая видимость
цели. Пример предполагает оба допуска. Выдача объекта сама не выдаёт equipment.

```http
GET /api/v1/equipment?pageSize=50 HTTP/1.1
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
      "id": "30000000-0000-4000-8000-000000000001",
      "level": "station",
      "vendor": null,
      "model": null,
      "serialNumber": null,
      "powerKw": 22.0,
      "state": "active",
      "objectId": "20000000-0000-4000-8000-000000000001"
    }
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ при отсутствии equipment scope или typed grant:

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

Следующий шаг: согласовать equipment отдельно, не расширять query компанией.
После 200 собрать все страницы с тем же pageSize и соединить по exact objectId
с уже полученными объектами на клиенте. `objectId: null` оставлять неизвестным;
не восстанавливать скрытую ссылку. `q`, если нужен, ищет только serialNumber.
Фильтра `objectId` и `/objects/{id}/equipment` нет.

<!-- /operation:listEquipment -->

<!-- operation:getEquipment -->
## 4. getEquipment: карточка оборудования

`equipment:read` и typed equipment grant; для видимой object ссылки также доступ
к объекту. Query пустой.

```http
GET /api/v1/equipment/30000000-0000-4000-8000-000000000001 HTTP/1.1
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
  "id": "30000000-0000-4000-8000-000000000001",
  "level": "station",
  "vendor": null,
  "model": null,
  "serialNumber": null,
  "powerKw": 22.0,
  "state": "active",
  "objectId": "20000000-0000-4000-8000-000000000001"
}
```

Отказ для недоступной/отсутствующей карточки, включая непригодный native ID:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: сверить ID с текущим equipment list и доступ с владельцем.
После 200 показывать известные поля; мощность в кВт не заменяет отпущенную
энергию в кВт·ч. `station` не содержит самостоятельных site/EVSE/connector DTO.

<!-- /operation:getEquipment -->

<!-- operation:listCounterparties -->
## 5. listCounterparties: доступные контрагенты

Требуются `counterparties:read`, independent counterparties grant и current
actor. `q` — поиск по имени, не по ИНН/КПП. Группы не выдаются как контрагенты.

```http
GET /api/v1/counterparties?pageSize=50&q=Fictional HTTP/1.1
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
      "id": "40000000-0000-4000-8000-000000000001",
      "name": "Fictional partner",
      "inn": null,
      "kpp": null
    }
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ при лишнем фильтре, например добавленном `inn`:

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Unprocessable Entity","status":422,"code":"invalid_request","requestId":"80000000-0000-4000-8000-000000000001","detail":"Request parameters are invalid"}
```

Следующий шаг: удалить неподдерживаемое поле и сверить query со
[словарём](../data-dictionary.md). После 200 продолжать cursor с теми же q/pageSize,
сохранять nullable реквизиты как неизвестные и открывать карточку по ID.

<!-- /operation:listCounterparties -->

<!-- operation:getCounterparty -->
## 6. getCounterparty: карточка контрагента

Те же `counterparties:read`, typed grant и текущие ограничения. Query пустой.

```http
GET /api/v1/counterparties/40000000-0000-4000-8000-000000000001 HTTP/1.1
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
  "id": "40000000-0000-4000-8000-000000000001",
  "name": "Fictional partner",
  "inn": null,
  "kpp": null
}
```

Отказ для недоступной/отсутствующей стороны:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: сверить ID и текущий counterparties grant; автоматически не
повторять 404. После 200 прочитать [договоры](contracts.md); договорная карточка
покажет counterpartyId только при независимой видимости этой стороны.

<!-- /operation:getCounterparty -->

## Свидетельства исходников

Commit `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`:

- `clearledger/server/app/product_api/app.py:137–169`: шесть GET и их response models.
- `clearledger/server/app/product_api/dto.py:172–199`: полные Object/Equipment/Counterparty DTO.
- `clearledger/server/app/product_api/queries.py:18–21,64–101,138–163,238–264`: поиск, фильтры, current grants и redacted links.
- `clearledger/server/app/product_api/access.py:98–151`: required scopes, accepted kinds и current actor.

Далее: [договоры и явные связи](contracts.md).
