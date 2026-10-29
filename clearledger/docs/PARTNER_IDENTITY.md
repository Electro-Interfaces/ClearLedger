# Доступ внешних приложений: OAuth/OIDC

M10, 29.10.2026. Backend поверх `ce94e2bf`; включение на стендах и выпуск не выполнялись.
Обычные Core user JWT, SSO handoff и Support не меняются. Пароль вводится только в Core;
password grant, implicit flow и динамическая публичная регистрация отсутствуют.

## Протокол и адаптер

Закреплены `Authlib==1.9.1`, `joserfc==1.7.7`. Authlib выполняет Authorization Code,
PKCE, Refresh Token, Client Credentials, Revocation и генерацию OIDC ID Token через
`AuthorizationServer`, `AuthorizationCodeGrant`, `CodeChallenge`, `OpenIDCode`,
`RefreshTokenGrant`, `ClientCredentialsGrant`, `RevocationEndpoint`.

У Authlib есть готовые серверные интеграции Flask/Django; FastAPI/Starlette раздел
документации описывает OAuth client. Поэтому здесь тонкий серверный адаптер:

- `ProtocolRequest` передаёт разобранные параметры и регистронезависимые Starlette
  Headers в Authlib. Канонический HTTPS URI берётся из настройки issuer, не из Host.
- `PartnerAuthorizationServer` реализует поиск клиента, хранение токена, создание
  запроса и преобразование ответа. HTTP роутер переводит tuple Authlib в JSON/redirect.
- Политика Core и persistence callbacks выполняются через `AsyncSession.run_sync`.
  SQLAlchemy переводит синхронные обращения Session в asyncpg I/O через greenlet;
  другая сессия, поток или отдельная транзакция не создаются. Внутри callbacks нет
  сетевых запросов или блокирующего файлового I/O.
- Погашение кода блокирует строку `FOR UPDATE`. Ротация и отзыв блокируют строку
  семейства refresh, затем перечитывают токен. Повтор использованного refresh
  отзывает всё семейство, включая уже выданный при гонке access token.
- Выдача кода/токена, регистрация и отзыв фиксируют транзакцию до HTTP ответа.
  Ошибка повторного refresh тоже фиксирует отзыв; это не rollback ветка ошибки.

Адаптер сверялся с [Authorization Server Authlib](https://docs.authlib.org/en/stable/oauth2/authorization-server/),
[OIDC Code Flow Authlib](https://docs.authlib.org/en/latest/oauth2/authorization-server/django/openid-connect.html),
[SQLAlchemy run_sync](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#sqlalchemy.ext.asyncio.AsyncSession.run_sync)
и [RFC 7636 Appendix B](https://www.rfc-editor.org/rfc/rfc7636.html#appendix-B).
HTTP тест обменивает код с фиксированным verifier/challenge из RFC, а не только
с парой, сгенерированной собственной реализацией. Сертификация OpenID Foundation
и тестирование сторонним OIDC conformance suite не проводились.

## Настройки

По умолчанию `PARTNER_OAUTH_ENABLED=false`: все partner endpoints закрыты,
регистрации и рабочие grants не создаются. Настройки для будущей приёмки:

| Настройка | Значение |
|---|---|
| `PARTNER_OAUTH_ENABLED` | Явное включение после приёмки |
| `PARTNER_API_ENABLED` | Независимое включение продуктового `/api/v1` в M03; по умолчанию false |
| `PARTNER_OAUTH_ISSUER` | Уникальный HTTPS origin пространства без path/query/fragment и конечного `/` |
| `PARTNER_OAUTH_AUDIENCE` | Отдельный идентификатор API, например `urn:elsyplus:partner-api:<space>` |
| `PARTNER_OAUTH_SIGNING_KEY` | base64 PEM приватного RSA ключа; минимум 2048 бит |
| `PARTNER_OAUTH_KID` | Идентификатор ключа отдельного partner профиля |
| `PARTNER_OAUTH_ALLOW_LOCALHOST` | По умолчанию false; HTTP callback на loopback только при явном включении и `APP_ENV != prod` |

Пустой `PARTNER_OAUTH_SIGNING_KEY` допускает криптографическое использование
`SSO_SIGNING_KEY`. Профили остаются разными: access требует RS256, `typ=at+jwt`,
`token_use=partner_access`, точные `iss`, `aud`, `kid`, обязательные claims и
совпадение digest с записью БД. ID Token имеет `aud=clientId`, `typ=JWT`,
`token_use=partner_id`; handoff и Core user JWT как partner access не принимаются.
Конфигурация без issuer/audience/пригодного ключа закрыта с 503.

## Реестр и grants

Мастера `eco_apps`, `eco_company_apps`, `companies`, `users`, `user_companies`
переиспользуются. При регистрации создаётся приложение `kind=partner` и выключенный
OAuth client; встроенные приложения не преобразуются в partner clients.
OAuth installation ссылается своим PK на существующий CompanyApp.
Новые таблицы `partner_*` создаёт действующий `Base.metadata.create_all` при загрузке
роутеров в `main.py`. Отдельного Alembic migration runner и ALTER старых таблиц нет.

Установка и grant содержат FK компании. Составной FK grant → installation связывает
одновременно installation, client и company. На каждой проверке дополнительно
сверяются CompanyApp company/app, активность App/CompanyApp, client и approvals.
Удаление master User/App/CompanyApp не блокируется новой OAuth-веткой: зависимые
записи каскадно удаляются только в новых таблицах. Отсутствующий principal/grant/
family закрывает проверку; удаление credential оставляет family без рабочего ключа.
Resource items имеют настоящие типизированные FK: строковый ServiceLocation,
UUID EzsEquipmentUnit, Counterparty, Contract, DocCard. Сервер проверяет компанию
каждого ID при записи и повторно при использовании токена. Партнёр не получает
прямого доступа к БД.

Ресурсные профили разделены: `objects`, `equipment`, `counterparties`, `contracts`,
`documents`. Режимы `ALL`, `SET`, `EMPTY` различны; отсутствие профиля означает
`EMPTY`, пустой SET не разрешает все ресурсы. `locationIds=null` означает явный
потолок всей сети, `[]` означает пустой потолок объектов. Для SET нужны IDs;
для ALL/EMPTY IDs запрещены. Поле installation `resourceScopes` задаёт профили
независимо; ограничения действующего членства сужают результат.

Scopes фиксированы в `SCOPE_DESCRIPTIONS`; неизвестные запрещены:
`openid`, `profile`, `email`, `offline_access`, `docs:read`, `objects:read`,
`equipment:read`, `counterparties:read`, `contracts:read`, `documents:read`,
`documents.files:download`. `docs:read` относится к документации API и само по себе
не даёт права на бизнес-документы. Наличие scope не заменяет domain/resource ACL.

Регистрация, включение client, выдача/отзыв credential и установка требуют
обычный Core bearer и проверку действующего администратора соответствующей
компании на сервере. Суперадмин может администрировать реестр, но для выдачи
пользовательского согласия требуется настоящее членство в выбранной компании.
Mail-only, отсутствие пароля, активная блокировка и удаление закрывают выдачу.
Для ограниченной роли неизвестный mapping прав закрыт; текущие modules/role
перечитываются при каждом использовании. Расширение scope catalog требует
явной реализации и проверки M03 domain policy.

## HTTP интерфейсы

Все перечисленные пути имеют префикс `/api`. Администрирование использует
обычный Core bearer; OAuth endpoints используют собственный профиль.

| Метод и путь | Назначение |
|---|---|
| POST `/developer/clients` | `{companyId,name,redirectUris,scopes,authMethod}`; authMethod `none` или `client_secret_basic`; client создаётся выключенным |
| POST `/developer/clients/{clientId}/status` | `{enabled}`; явное включение/отзыв |
| POST `/developer/clients/{clientId}/credentials` | Только confidential client; secret возвращается один раз, в БД только digest; срок 90 дней |
| DELETE `/developer/clients/{clientId}/credentials/{credentialId}` | Отзыв credential |
| POST `/developer/clients/{clientId}/installations` | `{companyId,scopes,locationIds,resourceScopes}`; явное approved разрешение администратора принимающей компании |
| DELETE `/developer/installations/{id}` | Отзыв installation |
| POST `/developer/installations/{id}/machine-grants` | `{scopes}`; отдельное одобрение машинного доступа |
| DELETE `/developer/grants/{id}` | Пользователь отзывает своё согласие; администратор отзывает grant своей компании |
| GET `/oauth2/authorize` | Валидация Authlib, сохранение pending request, redirect на `/developer/authorize?requestId=...` |
| GET `/developer/authorization-requests/{id}` | Core bearer; информация для явного согласия |
| POST `/developer/authorization-requests/{id}/approve` | `{companyId,scopes}` → `{redirectUrl}` |
| POST `/developer/authorization-requests/{id}/deny` | `{redirectUrl}` с `error=access_denied`; grant/code/token не создаются |
| POST `/oauth2/token` | Только form-urlencoded; authorization_code, refresh_token, client_credentials |
| POST `/oauth2/revoke` | RFC 7009, form-urlencoded; отзывает семейство access/refresh |
| GET `/oauth2/userinfo` | Partner bearer с openid, только пользовательский grant |
| GET `/oauth2/jwks` | Только публичный RSA JWK |
| GET `/oauth2/.well-known/openid-configuration` | Metadata URL для явной настройки клиента; существующие guard traps не отключены |

GET consent возвращает `{id,clientName,requestedScopes:[{code,description}],
companies:[{id,name,eligibleScopes}],expiresAt}`. Первое открытие обычным Core
bearer связывает непредсказуемый requestId с пользователем. Согласие одноразовое,
срок 5 минут; чужой requestId недоступен. Установки только active+approved.
Выбранные scopes должны быть подмножеством запрошенных, разрешённых установке,
client и текущему пользователю. Если запрос содержал openid, он обязателен в
явном подтверждении; пустой выбор запрещён.

Consent ошибки — Problem Details с `code`, `requestId`, `detail`:
410 `AUTH_REQUEST_EXPIRED`, 403 `AUTHORIZATION_REVOKED`,
404 `AUTH_REQUEST_NOT_FOUND`, 409 `AUTH_REQUEST_CONSUMED`,
503 `PARTNER_API_DISABLED`, 422 `INVALID_AUTHORIZATION_SELECTION`.
Ошибки token/revoke — безопасные OAuth `error`, без отражения секретов и URI.

Redirect URI сравнивается точно, допускается HTTPS; wildcard, fragment, userinfo,
управляющие символы и динамический callback запрещены. Callback после approve
формирует Authlib только из зарегистрированного URI, code и исходного state;
access/id/refresh tokens в URL не передаются. Все чувствительные ответы no-store.
Authorize требует state и PKCE S256; OIDC требует nonce. Поддержан только явный
prompt=consent; неподдержанные параметры отвергаются, не игнорируются.

Код Authlib (48 случайных символов) хранится digest, живёт до 120 секунд и не
дольше parent session. Access живёт до 300 секунд. Refresh выдаётся только при
явном `offline_access`; непрозрачное значение 48 случайных байт хранится digest.
Семейство не переживает исходный Core JWT expiry или 7-дневный предел от auth_time.
Каждая проверка/refresh перечитывает token_version, учётку, членство, grants,
client, App, CompanyApp, installation и confidential credential. Старые refresh
сохраняются как использованные для обнаружения reuse. Отзыв действует на следующем
вызове; проверка подписи без этой live-проверки не является partner verification.

Client Credentials требует confidential Basic authentication, явный `grant_id`
и scope, входящий в отдельный approved machine grant. Нет User, refresh, id_token
и UserInfo. Машинные documents:read/documents.files:download закрыты до отдельной
безопасной предметной политики. Сервис не выдаёт fake User ради прохождения ACL.

У `/api/v1` отдельный gate `partner_api_enabled`; его handler/policy владеет M03.
Включение OAuth identity не открывает продуктовый API автоматически. Для child
Problem Details seam: верификатор бросает безопасный `HTTPException(401)` при
непригодном токене/live state и `HTTPException(503)` при неполной конфигурации,
либо `PartnerProblem(status=503,code=PARTNER_API_DISABLED,detail=...)` при OAuth off.
Поля `status/code/detail` и `problem_handler(request,error)` доступны для явного
перевода в child API; issuer не скрывает отказ и не возвращает частичную identity.

Token/code endpoints ограничены 120 запросами/мин на транспортного peer в одном
процессе, словарь ограничен 10000 peer. Body читается потоком до 16 КиБ, не более
24 параметров; повторные/query параметры и смешение методов client authentication запрещены.
При нескольких workers точный лимит умножается; нужна дополнительная политика
кромки с проверенным клиентским IP. Library DEBUG logging включать нельзя: Authlib
пишет token responses в DEBUG. Нагрузочный и распределённый rate-limit тест не проводились.

## Интерфейс M03

`await verify_partner_access_token(token: str, db: AsyncSession) -> VerifiedPartnerToken`
либо dependency `get_verified_partner_token` из `services/partner_identity.py`.
Результат frozen: `client_id`, `app_id`, `installation_id`, `company_id`, `grant_id`,
`user_id|None`, `scopes:frozenset[str]`, `subject`, `token_id`, `expires_at`,
`is_machine`, `own_organization_id|None`, `resource_scopes`.

`resource_scopes` — readonly Mapping домена в frozen `VerifiedResourceScope(mode,
ids:frozenset[str])`. Отсутствие домена у потребителя также трактуется EMPTY.
`location_ids` сохранён для совместимости с первым соглашением, но не заменяет
пять независимых доменных профилей. M03 строит собственный AccessContext и сужает
права по текущим domain ACL/organization/object policy; issuer не имитирует новый
AccessContext и не открывает предметные API. В частности, ALL в profile документа
не отменяет DocAccessGrant/участие/конфиденциальность и другие правила документа.

## Воспроизведение проверок

Отдельная `.venv` в корне worktree; общий virtualenv не менялся. Установить из
`clearledger/server/requirements-test.txt`, рабочая папка `clearledger/server`.

```sh
TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_identity_test \
UPLOAD_DIR=/tmp/partner-identity-upload \
../../.venv/bin/python -m pytest tests/test_partner_identity.py -q
```

`conftest.py` удаляет тестовые схемы; URL должен указывать исключительно на эту
изолированную БД. Проверяются реальный HTTP adapter и текущий bootstrap, включая
создание новых таблиц поверх существующего Core и два повторных запуска. Проверка
не является приёмкой на VM, проверкой frontend, Support runtime или стороннего SDK.

Проверено локально на Python 3.13.15, PostgreSQL 16 в контейнере
`api-modernization-test-20261029`, БД `api_identity_test`, схемы `public`/`edge`;
загрузки отдельно в `/tmp/partner-identity-upload`. Suite до запуска DB fixtures
проверяет адрес/порт/имя этой БД и отдельный upload directory; в другом окружении
он пропускается, не запуская очистку схем ради partner тестов.

- Итоговый `test_partner_identity.py`: **52 PASS**, 72.09 с. Проверены HTTP code/PKCE
  с RFC-вектором, nonce/state, exact redirect, one-use/expiry/concurrent consume,
  consent/scope/company/admin запреты, deny без grants, отзыв и удаление пользователя,
  live account/member/client/app/install/grant/credential проверки, refresh rotation/
  reuse/concurrency/parent expiry, разделение JWT профилей, M2M, resource/DB constraints,
  upgrade/repeat bootstrap, malformed inputs, localhost/config/defaultoff и rate/size.
- Более широкий прогон перед последними уточнениями partner boundary: **269 PASS**,
  350.97 с; partner suite плюс `test_auth.py`, `test_security_audit.py`,
  `test_partner_visit_pass.py`, `test_voice_tokens.py`, `test_app_registry_defaults.py`,
  `test_support_context_v1.py`, `test_guard.py`. Два предупреждения deprecation от
  существующего websockets/uvicorn пути Support context; FAIL/SKIP не было.
- `compileall` новых модулей и `git diff --check`: PASS. Полный backend CI и browser/
  SDK/OIDC certification/нагрузочный прогон не выполнялись.
- После добавления независимого `partner_api_enabled=false`: целевые проверки
  defaultoff/неполной issuer configuration **2 PASS**, 50 deselected, 16.23 с.
