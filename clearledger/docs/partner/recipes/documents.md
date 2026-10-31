# Документ → текущие версии → разрешённые bytes

[Начало](../onboarding.md) · [Вход](../auth.md) · [Словарь](../data-dictionary.md) ·
[Ошибки](../errors.md) · [Каталоги](read-catalogs.md) · [Договоры](contracts.md) · [Мониторинг](monitoring.md)

Candidate/default-off; source pin
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Здесь три из 15 GET, **все
user-only**. Вместе с documents relation договора это четыре user-only метода.
HTTP/schema/runtime **NOTRUN**, все данные вымышлены. HTTPS origin
`https://sandbox.example.invalid`, GET без body.

Нужен delegated partner access token сотрудника. Machine token, Core token,
ID token, docs-only token/cookie не заменяют это согласие. `docs:read` относится
к инструкции/Swagger, а **`documents:read`** — к бизнес-документам. Дополнительно
нужны independent typed documents grant, текущие пользовательские модули и native
document ACL. Доступ к связанному договору сам по себе документов не выдаёт.

<!-- operation:listDocuments -->
## 13. listDocuments: доступные карточки

Требуются `documents:read`, User, typed documents grant и current actor.
Для ненулевых objectId/counterpartyId ниже предполагается независимая видимость
объекта и стороны с их read scopes и grants. Иначе ссылки nullable/redacted.
Список можно получить напрямую либо перейти от
[явных документов договора](contracts.md).

```http
GET /api/v1/documents?pageSize=50&q=Fictional&dateFrom=2026-10-01&dateTo=2026-10-31 HTTP/1.1
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
  "items": [
    {
      "id": "60000000-0000-4000-8000-000000000001",
      "title": "Fictional document",
      "status": "draft",
      "registrationNumber": null,
      "registrationDate": null,
      "currentRevision": 1,
      "objectId": "20000000-0000-4000-8000-000000000001",
      "counterpartyId": "40000000-0000-4000-8000-000000000001"
    }
  ],
  "total": 1,
  "nextCursor": null
}
```

Отказ, например нет documents scope/grant или User principal:

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

Следующий шаг: сверить delegated согласие, documents grant и актуальные права
с владельцем; не получать machine token с попыткой обойти User policy. Ранний
verifier может отклонить непригодный grant до этой ветви. После 200 сохранить ID,
продолжить все страницы с теми же q/dateFrom/dateTo/pageSize и открыть detail.
`q` ищет title, даты — UTC created_at, не registrationDate.
<!-- /operation:listDocuments -->

<!-- operation:getDocument -->
## 14. getDocument: карточка и текущие версии

Те же `documents:read`, User, typed grant и document ACL. Query пустой; версии
включены в detail, отдельного `GET /documents/{id}/versions` нет.

```http
GET /api/v1/documents/60000000-0000-4000-8000-000000000001 HTTP/1.1
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
  "id": "60000000-0000-4000-8000-000000000001",
  "title": "Fictional document",
  "status": "draft",
  "registrationNumber": null,
  "registrationDate": null,
  "currentRevision": 1,
  "objectId": "20000000-0000-4000-8000-000000000001",
  "counterpartyId": "40000000-0000-4000-8000-000000000001",
  "versions": [
    {
      "id": "70000000-0000-4000-8000-000000000001",
      "revision": 1,
      "role": "main",
      "fileName": "example.txt",
      "mimeType": "text/plain",
      "sizeBytes": 15
    }
  ],
  "versionsTruncated": false
}
```

Отказ для отсутствующего либо недоступного документа:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: перечитать разрешённый list/relation и сверить текущий document
ACL, не различать по 404 чужой документ и отсутствующий. После 200 берите versionId
из `versions`. Это до 200 текущих, не tombstoned и не purged версий, отсортированных
по revision/id; не полная история. При `versionsTruncated: true` полнота неизвестна:
нет опубликованной пагинации истории, согласуйте дальнейшую потребность с владельцем.
Metadata `mimeType` и `sizeBytes` не являются разрешением скачивания.
<!-- /operation:getDocument -->

<!-- operation:downloadDocumentVersion -->
## 15. downloadDocumentVersion: содержимое конкретной версии

Требуются **`documents:read` AND `documents.files:download`**, User, typed documents
grant и native document/download/file ACL. Doc, version и source должны образовать
разрешённую цепочку одной компании. Shared source bytes из task/chat/conference/
store закрыты этим профилем до общей файловой политики. Query пустой.

```http
GET /api/v1/documents/60000000-0000-4000-8000-000000000001/versions/70000000-0000-4000-8000-000000000001/content HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <DELEGATED_USER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/octet-stream
```

Полный пример HTTP response: body — ASCII `Fictional file` с завершающим LF,
**15 байт**, согласованный с sizeBytes вымышленной версии. Fenced block ниже
показывает payload, транспортное framing зависит от HTTP-сервера и здесь не
обещается. Content-Length/checksum/Range в контракт не добавляются.

```http
HTTP/1.1 200 OK
Content-Type: application/octet-stream
Content-Disposition: attachment; filename*=UTF-8''example.txt
X-Content-Type-Options: nosniff
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001

Fictional file
```

Отказ до начала потока, например version/source недоступны, удалены или download
право не проходит скрывающую проверку. Даже при `Accept: application/octet-stream`
ошибка имеет Problem media type:

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Not Found","status":404,"code":"not_found","requestId":"80000000-0000-4000-8000-000000000001","detail":"Resource was not found"}
```

Следующий шаг: сверить актуальные doc/version IDs и разрешённый download у
владельца; не пытаться прямой `/api/files/...` или storage URL. Отсутствующий
scope может дать 403 раньше файловой проверки. После 200 читайте bytes до
завершения stream, проверяйте статус/representation и только затем публикуйте
локальный файл как завершённый.
<!-- /operation:downloadDocumentVersion -->

## Обработка bytes и прерывания

Content всегда `application/octet-stream`: metadata MIME не меняет wire type.
Не вызывайте JSON parser/text decoder для этого 200. Attachment filename* —
закодированный UTF-8 basename, но локальное безопасное имя и место сохранения
выбирает ваше приложение; серверное имя не должно стать произвольным путём.

Сначала сохраняйте в incomplete файл с собственным byte cap/deadline. Ошибка
после headers может оставить status 200 и частичный body: новый Problem уже
не гарантирован. Удалите или явно пометьте incomplete результат; не принимайте
разрыв за успешное скачивание. DTO sizeBytes помогает обнаружить несоответствие
ожидаемого размера, но общий checksum/Content-Length/ETag/resume контракт не
опубликован. Не заявляйте криптографическую целостность по одному размеру.

Ограниченный повтор безопасного GET возможен по [правилам ошибок](../errors.md),
но не означает ranged continuation или ту же snapshot версии источника. Полная
история, upload/register/approve/decline и машинная файловая политика — будущие
возможности с отдельным допуском; текущий walkthrough их не выполняет.

## Свидетельства исходников

Commit `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`:

- `clearledger/server/app/product_api/app.py:203–237`: четыре user-only метода с contract relation, detail versions limit и binary route.
- `clearledger/server/app/product_api/dto.py:214–237`: полный Document/Version/DocumentDetail DTO.
- `clearledger/server/app/product_api/queries.py:87–101,238–278`: native ACL и redacted links.
- `clearledger/server/app/product_api/files.py:38–84`: doc/version/source chain, shared bytes deny, download ACL и streaming headers.
- `clearledger/server/app/product_api/access.py:98–151`: independent documents grant и current actor.

Вернуться к [маршруту подключения](../onboarding.md) · [договорным связям](contracts.md).
