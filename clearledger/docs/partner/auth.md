# Вход, согласие и токены

[Начало](onboarding.md) · [Словарь](data-dictionary.md) · [Ошибки](errors.md) ·
[Каталоги](recipes/read-catalogs.md) · [Договоры](recipes/contracts.md) ·
[Мониторинг](recipes/monitoring.md) · [Документы](recipes/documents.md)

Candidate, default-off; source pin
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Все requests ниже вымышлены,
HTTP/OAuth library/runtime **NOTRUN**. Они описывают подключение после отдельного
допуска, не включают функции и не выдают учётные данные.

## Выбор клиентской библиотеки

Для этого walkthrough выбран generic OAuth2/OIDC client **Authlib**. Используйте
его клиентский Code+PKCE/OIDC flow с discovery и JWT/JWKS validation, а не
самописный обмен или серверные классы Core. Здесь библиотека не устанавливалась
и её клиентская интеграция не запускалась: совместимую версию и адаптер к вашему
framework нужно закрепить и проверить в отдельном пилоте. HTTP ниже остаётся
контрактом для клиента на другом языке.

Настройте у клиента точный выданный issuer, client ID и redirect URI, проверку
state/nonce/PKCE, алгоритм ID token `RS256` и доверенный `jwks_uri` из проверенного
discovery. Не принимайте issuer или JWKS URL из непроверенного токена, callback
или параметров посетителя. Для confidential клиента секрет хранится только на
сервере, client authentication задаётся как `client_secret_basic`.

## Core login и discovery

Core login создаёт сессию сотрудника в пространстве. Сотрудник вводит пароль на
странице Core; ваше приложение перенаправляет браузер и не собирает этот пароль.
Core JWT, SSO handoff и токены Support не подходят Product API. OAuth password
grant, implicit flow и публичная динамическая регистрация не опубликованы.

Прочитайте discovery и сравните `issuer` побайтно с выданным HTTPS origin:

```http
GET /.well-known/openid-configuration HTTP/1.1
Host: sandbox.example.invalid
Accept: application/json
```

Авторизация для этого discovery GET не требуется; при выключенном OAuth запрос
не означает доступность metadata. В кандидате endpoints задаются так:

| Назначение | URL |
|---|---|
| issuer | `https://sandbox.example.invalid` |
| authorization_endpoint | `https://sandbox.example.invalid/api/oauth2/authorize` |
| token_endpoint | `https://sandbox.example.invalid/api/oauth2/token` |
| userinfo_endpoint | `https://sandbox.example.invalid/api/oauth2/userinfo` |
| jwks_uri | `https://sandbox.example.invalid/api/oauth2/jwks` |
| revocation_endpoint | `https://sandbox.example.invalid/api/oauth2/revoke` |

В реальном подключении берите URL из проверенного metadata. Product audience
передаёт владелец отдельно; не выводите его из client ID или issuer.

## Delegated: Code + PKCE S256

Создайте одноразовую ограниченную по времени транзакцию: криптографически случайные
`state`, `nonce`, `code_verifier`; сохраните их на своей стороне вместе с client,
issuer и callback. Challenge = base64url(SHA256(verifier)) без padding. В примере
ниже verifier/challenge взяты как публичный учебный вектор; **для каждого настоящего
входа генерируйте новую пару**, новый state и nonce. `FIXTURE_*` и `PLACEHOLDER_*`
никогда не являются рабочими значениями.

Полный authorization request для read walkthrough:

```http
GET /api/oauth2/authorize?response_type=code&client_id=PLACEHOLDER_PUBLIC_CLIENT_ID&redirect_uri=https%3A%2F%2Fapp.example.invalid%2Fcallback&scope=openid%20offline_access%20objects%3Aread%20equipment%3Aread%20counterparties%3Aread%20contracts%3Aread%20monitoring%3Aread%20documents%3Aread%20documents.files%3Adownload&state=FIXTURE_STATE_NOT_FOR_USE&nonce=FIXTURE_NONCE_NOT_FOR_USE&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&code_challenge_method=S256&prompt=consent HTTP/1.1
Host: sandbox.example.invalid
Accept: text/html, application/json
```

Это навигация браузера; partner Bearer не требуется. Core открывает собственную
страницу согласия, при необходимости предлагает вход, затем выбор доступной
компании и подтверждение scopes. Не добавляйте `companyId` в authorization query.
Владелец должен заранее разрешить запрошенные scopes клиенту и installation;
сотрудник может согласовать только доступное ему пересечение.

Callback имеет вид `https://app.example.invalid/callback?code=PLACEHOLDER_CODE&state=FIXTURE_STATE_NOT_FOR_USE`.
До token exchange библиотека обязана проверить точное совпадение state,
одноразовость и срок локальной транзакции. При callback с `error=access_denied`
проверьте state, завершите попытку и покажите отказ. Не обменивайте отсутствующий
code и не возобновляйте использованную транзакцию.

Public client обменивает code без secret и без Basic header:

```http
POST /api/oauth2/token HTTP/1.1
Host: sandbox.example.invalid
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=authorization_code&client_id=PLACEHOLDER_PUBLIC_CLIENT_ID&redirect_uri=https%3A%2F%2Fapp.example.invalid%2Fcallback&code=PLACEHOLDER_CODE&code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
```

Иллюстративный успешный OAuth response (значения токенов намеренно невалидны):

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
Pragma: no-cache
```

```json
{
  "access_token": "<PARTNER_ACCESS_TOKEN_PLACEHOLDER>",
  "token_type": "Bearer",
  "expires_in": 299,
  "scope": "contracts:read counterparties:read documents.files:download documents:read equipment:read monitoring:read objects:read offline_access openid",
  "refresh_token": "<ROTATING_REFRESH_TOKEN_PLACEHOLDER>",
  "id_token": "<OIDC_ID_TOKEN_PLACEHOLDER>"
}
```

Это OAuth envelope со snake_case; product DTO используют camelCase. Refresh
выдаётся только для согласованного `offline_access`, ID token относится к
`openid`. Успех обмена ещё требует проверки ID token выбранной OIDC-библиотекой:

- RS256 signature и подходящий ключ доверенного JWKS; неизвестный `kid` не повод
  отключать проверку, разрешать `none` или доверять ключу из токена.
- Точный `iss`, `aud` вашего client ID, актуальный `exp` и допустимые временные
  claims; при необходимости OIDC-проверки `azp` по правилам библиотеки.
- `nonce` исходной одноразовой транзакции, а также `at_hash`, связывающий ID token
  с выданным access token, когда он присутствует в ответе этого профиля.

ID token подтверждает identity в вашем приложении и имеет `token_use=partner_id`.
Pairwise `sub` стабилен в пределах client, не равен email или Core user ID;
не склеивайте пользователей разных client по предположению о `sub`. `profile`
и `email` дают соответствующие claims только по отдельному согласию. Если нужен
UserInfo, используйте `GET /api/oauth2/userinfo` с partner access Bearer и `openid`;
проверяйте совпадение его `sub` с проверенным ID token. Machine UserInfo недоступен.

Для `GET /api/v1/...` передавайте только `access_token` в единственном
`Authorization: Bearer ...`. Он выдан для product audience и имеет
`token_use=partner_access`; ID token не является Bearer для бизнес-методов.
Клиент не должен самостоятельно выводить право доступа из декодированного JWT:
сервис проверяет актуальные grants и ограничения заново.

## Refresh и revoke public client

Access token живёт **не более 300 секунд**, может закончиться раньше. Code
одноразовый, не более 120 секунд и не дольше родительской сессии; запрос согласия
имеет отдельный пятиминутный срок. Refresh family ограничена исходной Core-сессией
и её семидневным пределом, не продлевается бесконечно.

Для одного подключения сериализуйте refresh: только один процесс/запрос получает
право обновить пару; остальные используют атомарно сохранённый результат. После
успеха замените access и refresh вместе. Повтор старого refresh отзывает **всё
семейство**, включая только что полученный конкурентным запросом access token.

```http
POST /api/oauth2/token HTTP/1.1
Host: sandbox.example.invalid
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=refresh_token&client_id=PLACEHOLDER_PUBLIC_CLIENT_ID&refresh_token=PLACEHOLDER_CURRENT_REFRESH_TOKEN
```

Обработайте новый `access_token`, `expires_in`, `scope` и новый `refresh_token`;
не рассчитывайте на обязательный новый ID token. После потери ответа не повторяйте
обмен старого refresh вслепую: результат неизвестен, восстановите согласованное
состояние или начните новый вход. Для отзыва public client:

```http
POST /api/oauth2/revoke HTTP/1.1
Host: sandbox.example.invalid
Content-Type: application/x-www-form-urlencoded
Accept: application/json

client_id=PLACEHOLDER_PUBLIC_CLIENT_ID&token=PLACEHOLDER_CURRENT_REFRESH_TOKEN&token_type_hint=refresh_token
```

При успехе revoke возвращает 200; не ожидайте token DTO. Отзыв известного токена
закрывает семейство, а не только локальную запись клиента. Удалите свои сохранённые
токены. Для confidential Code/refresh/revoke применяется Basic вместо `client_id`
в body; одновременно два способа аутентификации не передавайте.

## Machine: confidential client credentials

Используйте отдельный confidential client и явно одобренный machine grant.
`grant_id` — обязательное прикладное расширение token request: настройте его
передачу в generic OAuth client, стандартный flow без него не достаточен.

```http
POST /api/oauth2/token HTTP/1.1
Host: sandbox.example.invalid
Authorization: Basic <BASE64_FORM_ENCODED_CLIENT_ID_COLON_SECRET_PLACEHOLDER>
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=client_credentials&grant_id=PLACEHOLDER_APPROVED_MACHINE_GRANT_UUID&scope=objects%3Aread%20equipment%3Aread%20counterparties%3Aread%20contracts%3Aread%20monitoring%3Aread
```

Basic формирует OAuth-библиотека из client ID и secret по правилам client auth.
Не вставляйте placeholder буквально; не добавляйте `client_id/client_secret`
в body при Basic. Ответ без refresh и ID token:

```json
{
  "access_token": "<MACHINE_ACCESS_TOKEN_PLACEHOLDER>",
  "token_type": "Bearer",
  "expires_in": 299,
  "scope": "contracts:read counterparties:read equipment:read monitoring:read objects:read"
}
```

Этот профиль не получает identity, документы, файлы или docs session. Он может
читать 11 user/service методов в пределах независимых resource grants; secret
хранится на сервере и не попадает в браузер, Swagger, URL или логи. После expiry
получайте новый machine token только пока credential/grant действуют. Отзыв
credential/grant/installation/client закрывает следующий API-вызов.

## Docs: отдельный public grant и cookie

Откройте `https://sandbox.example.invalid/developer/api`, войдите в Core и
подтвердите **отдельному настроенному public docs client** `openid docs:read`
через тот же Code+PKCE. Callback docs client —
`https://sandbox.example.invalid/developer/api/callback`; Swagger business callback
— `https://sandbox.example.invalid/api/developer/docs/oauth2-redirect`.
Не подставляйте вместо него client вашего приложения.

После docs code exchange портал создаёт короткую docs session:

```http
POST /api/developer/docs/session HTTP/1.1
Host: sandbox.example.invalid
Origin: https://sandbox.example.invalid
Authorization: Bearer <DOCS_PUBLIC_CLIENT_ACCESS_TOKEN_PLACEHOLDER>
X-Docs-CSRF: bootstrap
Accept: application/json
Content-Length: 0
```

В ответе `expiresAt`, `csrfToken` и cookie `__Secure-elsy_docs`: Secure,
HttpOnly, SameSite=Strict, Path=`/api/developer/docs`. Срок — не более 180 секунд
и не дольше исходного access token. Для запроса схемы нужен этот cookie; одного
Bearer вместо session недостаточно:

```http
GET /api/developer/docs/openapi.server.json HTTP/1.1
Host: sandbox.example.invalid
Cookie: __Secure-elsy_docs=<DOCS_SESSION_COOKIE_PLACEHOLDER>
Accept: application/json
```

`/api/developer/docs/openapi.server.json` описывает оба профиля, включая confidential
client credentials с `grant_id`; используйте его для серверного SDK.
`/api/developer/docs/openapi.json` — browser projection для Swagger, только public
Code+PKCE. Оба содержат те же **15 GET** и предметные политики. Assets и UI также
защищены docs session. Docs cookie не открывает business API; в Swagger Authorize
нужно отдельно согласовать business scopes. Try it out разрешён только для явно
настроенной песочницы; server secret в browser spec не вводится.

При завершении docs session портал передаёт `DELETE /api/developer/docs/session`
с тем же cookie, точным Origin и `X-Docs-CSRF: <csrfToken>`; успешный ответ 204,
docs family отзывается. Это lifecycle документации, не новый business write API.

## Отказы OAuth и безопасный следующий шаг

Token/revoke используют OAuth JSON, например:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json
Cache-Control: no-store
Pragma: no-cache
```

```json
{"error":"invalid_grant"}
```

| error / ситуация | Что делать |
|---|---|
| `invalid_request` | Проверить form content type, обязательные параметры, отсутствие query и дублей |
| `invalid_client` (в том числе 401 с Basic challenge) | Проверить client/auth method, серверный secret у владельца; не менять на Core token |
| `invalid_grant` | Code/refresh/grant непригоден; остановить повтор старого значения, начать новый вход либо сверить machine grant |
| `invalid_scope` | Сузить запрос до одобренного пересечения; новые права согласовать с владельцем |
| `unsupported_grant_type` | Выбрать опубликованный flow, не password или implicit |
| Callback `access_denied` | После проверки state завершить локальную транзакцию и показать отказ |
| Feature gate, throttle, docs deny | Проверить status/media/envelope по [правилам ошибок](errors.md); это не всегда `{error}` |

Form requests не принимают query, дубли и смешанную client auth; ограничены
16 KiB и 24 параметрами. Это ограничения OAuth parser, не квоты Product API.
Не журналируйте Authorization, cookie, code, state, nonce, verifier, token bodies
или callback query. При 401 допустим один управляемый refresh/повтор входа,
затем остановка; бесконечный refresh не восстанавливает отозванное разрешение.

## Свидетельства исходников

Точный source commit для всех позиций:
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`.

- `clearledger/server/app/routers/partner_oauth_router.py:64–185`: form parsing, discovery, OAuth envelopes и UserInfo.
- `clearledger/server/app/services/partner_identity.py:435–603`: S256, code lifetime, nonce, refresh reuse, machine grant и revoke.
- `clearledger/server/app/services/partner_identity.py:636–755`: access/ID separation, family expiry и live verification.
- `clearledger/server/app/auth.py:46–57`: семидневный предел исходной сессии.
- `clearledger/server/app/routers/docs_portal_router.py:73–115` и `clearledger/server/app/services/docs_portal.py:76–179`: cookie, CSRF, expiry и две схемы.
- `clearledger/server/app/product_api/app.py:399–513`: server/browser OpenAPI profiles.

Далее: [первое чтение каталогов](recipes/read-catalogs.md).
