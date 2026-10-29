# Независимая source-only проверка партнёрского API

Дата: 30.10.2026. Предмет: ограниченный читающий API для внешнего разработчика,
его identity/docs/SDK-контракт и состояние программы M00–M19.

## Решение и границы

**Ограниченный source acceptance читающего кандидата допустим с тремя замечаниями
ниже.** В закреплённом коде согласованы 12 операций, разделение user/service,
обязательные scopes, типизированные ресурсные ограничения, SQL-предикаты,
документный download и canonical/browser OpenAPI. Подтверждённого обхода ACL,
раскрытия чужих данных или расширения grants эта проверка не установила.
Это вывод о рассмотренных цепочках исходного кода, не security scan платформы.

Внешний разработчик может подготовить серверное читающее приложение и пройти
выделенную синтетическую песочницу при выдаче client/install/grant владельцем.
Самостоятельный общий production onboarding, полный SDK, все предметные команды
и завершение M00–M19 этим составом не обеспечены. Draft PR #78 остаётся draft;
ни фактический выпуск, ни merge не являются условием этой source-приёмки и не
разрешаются ею. Полную OAuth/OIDC protocol conformance до исправления F03
объявлять нельзя.

### Закреплённые источники

- Ledger: `3bd86c3f4c1e6ddb7a9421851d2d0b6deb54d0e2`, рабочее дерево
  `api-independent-readiness-20261030`, исходно чистая ветка `MagLook/seabiscuit`.
  Ни pull, ни перенос более позднего runtime в этот pin не выполнялись.
- `C:` далее означает путь относительно `clearledger/` этого Ledger pin.
  Пути без префикса в одном абзаце продолжают последнюю названную
  директорию; в таблице M00–M19 имена server-модулей относятся к `server/app`.
- `D:` означает read-only дерево поставки `ecosystem-deploy/partner-api-design-20261029`.
  Наблюдавшийся HEAD: `8a9921931929ee14143fe38fc17dedaafac90435`.
  В нём уже были чужие незакоммиченные изменения `STATUS.md` и служебные pycache.
  Их не изменяли и не включали в свой коммит.
- Канон плана: `D:docs/API-MODERNIZATION-PLAN.md`, SHA256
  `2f0ce3f319b1bbeff98905f2921514b5b722c1c65d4c7c13ca8b344f9e888352`.
  Прочитанный рабочий `D:docs/api/execution-20261029/STATUS.md`, SHA256
  `4b3baf01e808835a55fdaff3153eec0b25c1a903b38a0e79173829dfd0996aae`,
  используется как журнал чужих проверок, не как immutable runtime proof.
- Прочитаны применимые CLAUDE/AGENTS, rushydro-space и orchestration.
  Более поздний M06 shared-import refactor и его исправления находятся вне pin.

Проверка выполнена чтением кода, тестов, публичных repo-отчётов и статическим AST
обходом. AST, без импорта приложения, насчитал 12 operation decorators, 9
service-eligible/3 user-only и присутствие всех 12 operationId в generated types.
Не запускались сервер, pytest/unittest, bootstrap, SDK, exporter, браузер или SQL;
не создавались соединения с API/БД/ВМ. Private `.env`, owner state, manifests,
JWT/code, содержимое рабочих файлов и закрытый proof index не читались.
Официальные спецификации читались по HTTPS только для проверки protocol claims.
Единственный изменённый файл этого worker: настоящий отчёт.

## Findings с воспроизводимой цепочкой

Severity ниже относится к указанному влиянию. Замечания F01/F02 являются
product/documentation/delivery gaps, F03 является protocol defect.
Ни одно не классифицируется здесь как доказанная уязвимость.

### F01. Серверный SDK quickstart направляет к browser projection

**Low, onboarding/documentation gap.** `C:docs/PARTNER_SDK_TYPES.md:126–140`
предлагает внешнему потребителю получить `/api/developer/docs/openapi.json` и
сгенерировать по нему типы/клиент. После M09 это browser projection:
`C:server/app/routers/docs_portal_router.py:105–114` вызывает default
`product_schema(..., browser=True)` для этого URL; сервис
`C:server/app/services/docs_portal.py:157–175` передаёт canonical схему в
`public_client_openapi`. Последняя удаляет ProductServiceOAuth из
`components.securitySchemes` и operation security alternatives,
`C:server/app/product_api/app.py:404–435`.

Контрпример: разработчик серверной автоматизации буквально сохраняет указанный
JSON и использует генератор, читающий стандартные security schemes. Он видит
лишь authorizationCode и не получает machine alternative из стандартного
контракта, хотя runtime принимает service на девяти операциях. Machine metadata
не потеряна полностью: она остаётся в vendor extension и есть ссылка на полный
контракт. Поэтому это поправимый выбор исходного URL, а не отсутствие API или
нарушение границы доступа. Правильный серверный URL уже реализован:
`/api/developer/docs/openapi.server.json`, с тем же docs-session guard.

Рекомендация: явно выбрать canonical URL для server generation и назвать
`openapi.json` исключительно browser execution projection. Координатор сообщил
об исправлении документации в `a6667d59`; это follow-up за пределами проверенного
pin, здесь независимо не переаттестован.

### F02. Новая продуктовая квота не доставляется шаблоном Compose

**Medium operational, deployment configuration gap.**
`C:server/app/config.py:54–80` объявляет default-off budget и три числовых
параметра; `C:server/app/product_api/budget.py:50–54` читает именно их.
В рассмотренном deploy-составе `D:stacks/_template/compose.yml:58–85`
передаёт OAuth/API/docs/issuer/key/SOURCE_REVISION, но не передаёт ни один
`PARTNER_API_BUDGET_*`. В tracked `D:stacks/_template/.env.example:37–60`
эти четыре параметра также отсутствуют. В данном backend service нет общего
`env_file`, который заменял бы явный passthrough.

Контрпример: владелец добавляет `PARTNER_API_BUDGET_ENABLED=true` и LIMIT в
company `.env`, после чего пересоздаёт backend этим шаблоном. Compose использует
файл для interpolation, но отсутствующие environment entries не появляются в
контейнере. Settings сохраняет `partner_api_budget_enabled=False`; `enforce`
возвращает без store I/O (`budget.py:94–96`). Сам механизм квоты в коде есть,
но такой способ включения его не активирует.

Рекомендация: передать все четыре переменные в шаблон, оставить false по
умолчанию, проверить rendered defaults и overrides без настоящего `.env`.
Это не требование включить квоту на рабочем пространстве. Координатор принял
finding и сообщил о подготовке template fix; этот отчёт не проверяет результат
будущего применения и не заявляет, что live quota включена.

### F03. Отказы UserInfo обходят нормализацию Bearer challenge

**Low, protocol interoperability defect; отказ в данных сохранён.**
`C:server/app/routers/partner_oauth_router.py:179–184` возвращает
`protocol_error("insufficient_scope", 403)` для валидного machine token либо
user token без `openid`. Helper `protocol_error`, строки 33–35 того же файла,
добавляет WWW-Authenticate только для 401 и только Basic. Следовательно, этот
403 UserInfo вообще не содержит Bearer challenge.

Дополнительные ветки той же границы:
`C:server/app/services/partner_identity.py:728–740` возвращает 401 для bearer
длиной больше 8192 без challenge, а для отсутствующего bearer ставит голый
`WWW-Authenticate: Bearer`. `PartnerRoute:79–91` добавляет no-store, но не
ремонтирует challenge. Product formatter
`C:server/app/product_api/app.py:49–68` исправляет эти случаи только внутри
`/api/v1`, и на parent `/api/oauth2/userinfo` не распространяется.

Минимальный контрпример по control flow: получить действительный machine access
по approved grant, вызвать GET `/api/oauth2/userinfo` с ним; verification успешна,
затем machine branch возвращает 403 с `error=insufficient_scope` без
WWW-Authenticate. Более простой отрицательный случай: bearer из 8193 символов
доходит до length guard, даёт 401 без challenge. Это source-derived ожидаемые
ответы, самостоятельно HTTP не воспроизводились.

[OIDC Core §5.3.3](https://openid.net/specs/openid-connect-core-1_0.html#UserInfoError)
задаёт профиль ошибок UserInfo через
[RFC 6750 §3](https://www.rfc-editor.org/rfc/rfc6750.html#section-3): отказ при
отсутствующем/недостаточном access token требует WWW-Authenticate с Bearer
parameters. Клиент, извлекающий OAuth resource error из challenge, не получает
нужную информацию. Рекомендация: общий formatter отрицательных ответов UserInfo,
не менять token endpoint на Bearer (там Basic имеет другое назначение);
проверить missing/oversized/invalid token и valid-without-openid отдельными
HTTP negative controls. Новая выдача данных или ослабление guard не нужны.

## Фактический контракт 12 операций

Префикс runtime: `/api/v1`. Principal `P` = delegated PARTNER, `S` = SERVICE.
Набор scopes в каждой строке нужен целиком, плюс актуальные ресурсные/domain
права. Точки регистрации: `C:server/app/product_api/app.py`.

| operationId | Путь GET | Principal | Обязательные scopes | Строка |
|---|---|---|---|---:|
| listObjects | `/objects` | P или S | objects:read | 135 |
| getObject | `/objects/{objectId}` | P или S | objects:read | 139 |
| getObjectMonitoring | `/objects/{objectId}/monitoring` | P или S | objects:read и monitoring:read | 143 |
| listEquipment | `/equipment` | P или S | equipment:read | 153 |
| getEquipment | `/equipment/{equipmentId}` | P или S | equipment:read | 157 |
| listCounterparties | `/counterparties` | P или S | counterparties:read | 161 |
| getCounterparty | `/counterparties/{counterpartyId}` | P или S | counterparties:read | 165 |
| listContracts | `/contracts` | P или S | contracts:read | 169 |
| getContract | `/contracts/{contractId}` | P или S | contracts:read | 173 |
| listDocuments | `/documents` | только P | documents:read | 177 |
| getDocument | `/documents/{docId}` | только P | documents:read | 181 |
| downloadDocumentVersion | `/documents/{docId}/versions/{versionId}/content` | только P | documents:read и documents.files:download | 194 |

`_policy`, строки 88–96, является executable policy, а не только OpenAPI x-полем.
`access.resolve:98–104` проверяет subset scopes, principal и непустой grant;
`api_contracts/routing.py:138–165` запускает resolver/authorize до обычного handler
и его DI/валидации. Registry запрещает неаннотированные и неоднозначные новые
маршруты (`routing.py:238–291`). Parent явно проверяет registry и монтирует child
в `C:server/app/main.py:491–504`. Это относится к новой поверхности, не означает
переход всех legacy роутеров на PolicyRouter.

Canonical exporter строит alternatives из того же registry,
`product_api/app.py:344–385`: отдельные объекты ProductOAuth и ProductServiceOAuth
дают OR, все scopes внутри выбранной альтернативы обязательны. Это соответствует
[OpenAPI 3.1 Security Requirement](https://spec.openapis.org/oas/v3.1.0.html#security-requirement-object).
Пустого anonymous security requirement в этой цепочке нет. Тест
`C:server/tests/test_product_service_openapi.py:32–101` проверяет 9/3,
scope equality, deepcopy и отказ projection для будущего server-only метода.
Его HTTP-часть подменяет DB/live grant; она не является доказательством реальной
OAuth/SQL выдачи.

### Identity, account и ресурсные права

MachineGrant требует Basic confidential client, custom UUID `grant_id` и явный
непустой scope (`C:server/app/services/partner_identity.py:522–533`). Grant должен
принадлежать аутентифицированному client; live_grant не допускает machine identity
scopes и документы (`293–347`). Canonical schema честно описывает custom parameter
через `x-elsy-token-request`, не выдавая его за стандартный OAuth parameter
(`product_api/app.py:354–371`). В
[RFC 6749 §4.4.2](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4.2)
стандартный client credentials запрос не содержит grant_id. Generic SDK должен
передать этот application extension явно; M18 клиент так и делает,
`C:tools/partner-pilots/clients/oauth.ts:19–26`.

Проверка access (`partner_identity.py:687–725`) требует RS256, at+jwt, точные
issuer/audience/kid, token_use, digest persisted token и живое family/grant.
`active_user:174–178`, `eligible_scopes:189–219`, `live_grant:293–347` проверяют
password/mail_only/lock, membership, роль/modules, token_version, parent expiry,
App/CompanyApp/client/install/credential. Core bearer, handoff и ID Token не
становятся API credential из-за общей RSA key. Account/permission данные
перечитываются на каждом вызове; это не offline JWT-only verifier.

Resource profiles независимы для пяти доменов; missing profile = EMPTY.
`resource_scopes:259–290` заново проверяет tenant каждого SET item и возвращает
readonly mapping. `access.py:28–42,105–145` пересекает compatibility location
ceiling с membership object_scope и organization. ALL не отменяет эти потолки,
kind=station и tenant predicate. `locationIds=[]` не равно всей сети. У SERVICE
нет fake User; документы закрыты ещё до domain query.

### List/detail/count/links и cursor

`C:server/app/product_api/queries.py:67–98` ставит tenant/resource/object/org и
document ACL до count/limit. Detail использует те же conditions (`160–168`),
count считает доступный отбор, а не всю компанию. Equipment ограничено station;
counterparty groups исключены. Nested object/counterparty ссылки возвращаются
только при независимом read scope и доступности target (`170–209`).

Cursor HMAC и binding включают principal/client/install/grant/company,
policy/scopes, resource profiles, object/org и все параметры кроме cursor
(`queries.py:100–133`). PageSize тоже входит в binding: менять 1 на 200 внутри
одного обхода нельзя; следует начать новый обход. Порядок `(created_at,id)` и
условие после пары сохраняют записи с одинаковым timestamp (`135–158`).
Parent derives стабильный HMAC key из SECRET_KEY с отдельным purpose,
`main.py:496–500`; default random key standalone factory не означает случайный
ключ у production mount.

Уменьшение прав делает прежний cursor непригодным, если изменился binding;
grant/member revoke закрывает сам token раньше. Document ACL/связи перечитываются
каждым новым SQL запросом, но их полная revision не находится в cursor.
Поэтому не обещается, что любая ACL mutation обязательно даёт 400: часть изменений
просто меняет доступный следующий результат. Cursor не MVCC snapshot, total и
данные при конкурентных изменениях могут расходиться между запросами.
Это ограничение текущей модели, не доказанный обход фильтра.

### Документы и содержимое

Metadata использует `_readable_doc_clause`,
`C:server/app/services/doc_access.py:389–459`, с doc/kind grants, deny rules и
участием. Document resource grant не заменяет этот SQL ACL. Detail возвращает
только current/non-tombstoned/non-purged версии, максимум 200 и
versionsTruncated (`product_api/app.py:181–192`); историческая выдача списка
версий не реализована.

Download заново проверяет доступную карточку, exact doc/version/company,
SourceFile.company и retention, затем запрещает shared task/chat/recording/store
bytes, вызывает native download policy и только после этого открывает файл
(`C:server/app/product_api/files.py:39–70`). Прямой универсальный `/api/files`
партнёру здесь не открывается. `_open_beneath:16–36` проходит путь относительно
upload root через dirfd/O_NOFOLLOW и принимает только regular file; symlink и
выход за корень дают 404. Содержимое идёт chunks по 64 KiB с attachment filename*,
octet-stream/nosniff/no-store (`73–84`). Range/ETag/resumable не обещаны; ошибки
после начала streaming уже нельзя заменить JSON Problem.

### OpenAPI, URL, typed clients и quickstart

Canonical `/api/developer/docs/openapi.server.json` и browser `/openapi.json`
оба требуют отдельную docs session (`docs_portal_router.py:105–156`). Cookie
сопоставляется с live token/family/grant/verification profile; срок не более
180 секунд и token TTL (`services/docs_portal.py:89–131`). Core token или business
Bearer не заменяет cookie. Docs scope не даёт business access. Assets из
allowlist, Swagger bundle/CSS hashes закреплены (`180–195`); generic parent и
child OpenAPI HTTP URLs отключены (`main.py:370`, `routing.py:288`).

Try it out разрешён только при environment=sandbox и точном
issuer+`/api/v1` (`docs_portal.py:47–61`). Browser request interceptor проверяет
same origin, target/method, public Code exchange без secret, live docs session
и отдельный business bearer (`docs_portal_assets/portal-init.js:86–119`).
Canonical schema не превращается в public machine credential widget.

`C:src/generated/partner-api.d.ts` содержит все 12 operationId; заголовок
закрепляет openapi-typescript 7.10.1 и schema SHA256
`712b46f2260c5d5431b736be5535b0fb526e45049490e35ffe00394fc60b1570`.
Это записанное происхождение, не заново вычисленный мной exporter hash.
`scripts/export-partner-openapi.py:21–93` запрещает env/socket I/O и runtime
imports, собирая настоящие DTO/routes; `tools/partner-api-types/generate.mjs`
проверяет 12 IDs, local refs, generator version и свежий byte output.
`consumer.ts` использует operations/components, включая negative compile cases.
Wire declarations не являются transport, runtime decoder или OAuth SDK.

M18 клиент отдельно использует официальный openid-client: discovery/exact issuer,
ClientSecretBasic/None, grant_id, S256/state/nonce, проверку ID token и UserInfo
subject (`clients/oauth.ts:9–56`). Path ID кодируется encodeURIComponent,
cursor строится URLSearchParams, base имеет один `/api/v1`
(`clients/scenarios.ts:27–121`). Download читает bytes и проверяет SHA256, не JSON.
Transport проверяет TLS/hostname, не следует redirect автоматически,
ограничен assigned loopback sandbox, timeout 15 секунд и 8 MiB response
(`clients/transport.ts:17–65`). Это предел тестового клиента, не server file-size
limit. `protocolBody(null)` исправлен явно, TLS/signature checks не отключены.
Некоторые JSON читаются через type assertion с ручными contract checks; полного
runtime schema decoder здесь нет, и это не выдаётся за автоматически generated SDK.

`PARTNER_QUICKSTART.md:25–84` согласуется с двумя flows; scopes мониторинга и
download указаны правильно. ID servicePoint остаётся opaque Unicode String(40),
UUID не требуется; не нормализовать регистр/пробелы. Slash/dot path-addressability
остаётся известным пределом, описанным в `docs/api/PRODUCT_OBJECT_IDS.md`.
Пример `.invalid` относится к offline export, а фактический base берётся у
владельца песочницы. Прямой произвольный cross-origin browser не обещан.

### Default-off, ошибки, нагрузка и доставка конфигурации

OAuth/API/docs и новая quota выключены по умолчанию (`config.py:54–80`).
`require_enabled`, `partner_identity.py:105–129`, проверяет точный HTTPS issuer
без path/controls и пригодный RSA >=2048 до выдачи/registration. Audience отдельный;
поддержан документированный fallback partner key на SSO key. Секреты для этого
review не нужны и не читались. OAuth/API/docs passthrough есть в template,
SOURCE_REVISION default=unverified не является release attestation; quota
passthrough на рассмотренном deploy pin отсутствует, см. F02.

Product Problem formatter (`product_api/app.py:49–83`) даёт безопасное тело,
no-store, generated requestId и status-specific allowlisted challenge/Allow/
Retry-After. Validation/unknown query = 422; foreign/ungranted detail = 404;
недостаточный scope = 403; неправильный cursor = 400; default-off/config = 503.
Generic injected 429 имеет internal_error, настоящий quota exhaustion имеет
rate_limited. OAuth token errors имеют отдельный OAuth error profile; нельзя
требовать product Problem от всех ingress/OAuth ответов. Отрицательный UserInfo
профиль требует F03.

Ключевые пределы:

| Область | Подтверждено исходником | Что этим не доказано |
|---|---|---|
| Pagination | DTO pageSize 1..200/default50; cursor <=4096; q<=100; ISO даты, extra forbid (`dto.py:20–54`) | Max total dataset, bounded count latency, snapshot-consistency |
| Monitoring | days 1..366/default90, asOf date; объектный ACL раньше session helpers (`monitoring.py:20–39`) | Ограничение стоимости boundary scan, исторический паспорт объекта, финансовые/тикетные данные |
| Versions/file | <=200 current versions, truncation flag; bounded streaming chunks | Полный version history, bytes/concurrency quota, Range, post-stream Problem |
| Product quota | Verified company/install/client tuple общий всем routes/grants/tokens; own transaction после identity, до query validation (`access.py:146–149`) | Pre-auth DDoS limiter, fairness между пользователями одной installation, concurrent execution/job/bytes caps |
| Algorithm | PostgreSQL INSERT/ON CONFLICT locked update; first-hit fixed window, burst до 2L на стыке; used<=L+1 (`budget.py:61–81`) | Sliding-window ровный RPS или измеренный production SLO |
| Exhaustion/store failure | 429 + integer Retry-After>=1; pool/SQL/lock/timeout/drift failure = safe503 (`budget.py:94–116`) | Автоматический Retry-After на503; fail-open fallback; защита verifier этими counters |
| Quota storage | Composite PK/FK CASCADE, reset index (`models_product_budget.py:12–28`); cleanup <=64 с sample1/128 (`budget.py:18–19,83–91`) | Жёсткий wall-clock storage bound без трафика, production retention/maintenance SLO |
| OAuth preauth | 120/min/peer/process, <=10000 peers, form<=16KiB/24params; peer из transport, не XFF (`partner_oauth_router.py:47–100`) | Общая distributed preauth quota и verified ingress IP при нескольких workers/proxy |

## Как учитывать прежние проверки

В исходниках retained tests видны подходящие positive и negative expectations:
`test_partner_product_integration.py:109–259` использует real PKCE/verifier и
проверяет token confusion/revoke/member scope/cursor/gates; `test_product_api.py`
проверяет count/detail/links/files и отдельно injected verifier seam.
`test_product_budget_db.py:114` и далее имеет реальную SQL/process fixture;
`test_product_budget_unit.py:43–101` подменяет quota store и проверяет только
HTTP/wiring. Их coverage различается, результаты не взаимозаменяемы.

Публичный `C:docs/api/PARTNER_SYNTHETIC_PILOTS.md:140–207` сохраняет два финальных
этапа M18: 8 machine cases/70 requests и 6 documents cases/19 requests, итого 89
HTTP requests. В нём названы actual backend `71611507`, исправленный UI
`56f7c674`, owner narrowing/revoke, точные bytes и current membership revoke.
Это чужие retained observations на синтетической purpose-built assembly;
не мой повтор на `3bd86c3f`, не full main/nginx, не production и не real partner.
Положительный delegated subject был company owner/admin без superadmin,
не ordinary employee. Неудачные UI/adapter попытки сохранены отдельно.

Тот же отчёт прямо оставляет **server business-row immutability UNVERIFIED**:
нет исходного DB fingerprint. Отсутствие business-write HTTP методов не доказывает
отсутствие SQL side effects; quota admission само является технической записью.
Private evidence hashes в публичном отчёте не равны прочитанным raw ledgers.
Коммит M18 не закрывает quotas/load/CORS/реальные партнёры или весь M18.

`D:docs/api/execution-20261029/STATUS.md` и сообщения координатора содержат результаты SQL/schema/browser
повторов, включая текущие M09 и responsive checks. Они приняты как provenance
чужих проверок с их границами. В частности, old-source schema compatibility не
является backup restore, а локальный PASS не является remote CI:
`C:docs/api/IMPLEMENTATION_STATUS.md` отмечает disabled_manually workflow.

## M00–M19: состояние относительно исходного плана

Критерии взяты из `D:docs/API-MODERNIZATION-PLAN.md:106–133`, а не из числа
коммитов. `completed` ниже относится к названной source-границе; `partial`
означает реализованный полезный slice при незакрытом полном выходе;
`not done` означает отсутствие завершённого пакета, не отсутствие идей.
Состояние других repositories дано только по журналу и явно так обозначено.

| ID | Статус | Evidence и оставшийся конкретный выход |
|---|---|---|
| M00 | partial | D:docs/api/execution-20261029/STATUS.md:7–16 фиксирует actual Core `5ce5779b`/Support `09c221c4`, hashes и baseline checks. Полный реестр active consumers/traffic отсутствует; новый source candidate не равен старому runtime. |
| M01 | partial | D:docs/api/INVENTORY-20261029.md и D:docs/api/analysis-20261029/* дают карту; C:server/app/api_contracts/routing.py:238–291 даёт строгий registry новой поверхности. Dynamic/native/WS/SSE/proxy/files и владельцы всех legacy consumers полностью не закрыты. |
| M02 | partial | Retained identity/product/closing/files characterization tests и SQL-count slice существуют. Нет полного исходного p50/p95/rows/RAM/pool/cache/delivery budget для всех сценариев; сами unit-counts его не заменяют. |
| M03 | completed в новой read-поверхности | C:server/app/api_contracts/context.py, routing.py:88–165, product_api/access.py:67–149 и main.py:491–504 дают immutable verified context, отдельные token kinds, ALL/SET/EMPTY/UNINITIALIZED, closed unknown route policy. Перевод legacy входит в M17, не автоматически выполнен этой строкой. |
| M04 | partial | C:server/app/services/doc_access.py вынесен из router; location_commands.py и file_store.py имеют общие правила/transaction ownership. Все extracted services и старые entrypoints платформы не сведены и не переаттестованы. |
| M05 | partial | C:server/app/services/location_commands.py:60–101,188–245 и locations_router.py:229–290 дают общие create/upsert/update, tenant-first lock и отказ DELETE409. Product capabilities честно показывают servicePoint/station; site/EVSE/connector, полный export population и temporal retire отсутствуют. |
| M06 | partial | C:server/app/services/reference_identity.py:56–160 и ops_payments.py:271 используют CounterpartyIndex/ambiguity. Product read имеет domain scopes. Полные reference/contract write команды и все manual/import paths в этом pin не закрыты; новый parallel refactor исключён. |
| M07 | partial | C:server/app/services/file_store.py:46–108,125–180 объединяет writers/cleanup; services/doc_access.py и product_api/files.py разделяют read/download. Distributed atomicity, orphan GC и общий cross-domain shared-content policy не готовы; partner writes не реализованы. |
| M08 | partial | C:server/app/product_api/monitoring.py:20–39 использует shared ops_monitor_context после ACL и current provenance; ops_router.py:868–891 сохраняет explicit legacy GET expand_all с commit. Общая historical model, все начисления/commands и вывод legacy write-GET не закрыты. |
| M09 | partial | Product 12-operation schema, machine alternatives, DTO и Problem metadata реализованы (app.py:318–435). Canonical read profile согласован; F03 остаётся protocol defect вне child, все WS/SSE/events/legacy protocol passports не сертифицированы. |
| M10 | partial | Authlib PKCE/refresh/machine grant/revoke/live account chain реализована (partner_identity.py:293–347,424–533,687–741). Основной identity slice есть; F03 и отдельная distributed preauth policy остаются, полной OIDC certification не заявлено. |
| M11 | partial | Protected UI/raw canonical/browser/assets, docs session и sandbox-only Try реализованы (docs_portal.py; docs_portal_router.py:105–156). Retained real HTTPS проверки есть, но F01 требует ясной server onboarding инструкции; текущий product gap нельзя скрыть прежним browser PASS. |
| M12 | partial | Official generator/isolated lock/12 wire operations, compile fixture, AuthContext generation/abort и apiClient sent-Bearer comparison есть (AuthContext.tsx:50–119; apiClient.ts:190–217). Общий binary/refresh/error primitive и перевод всех Core/Support consumers не завершены; wire types не full SDK. |
| M13 | partial, по журналу | D:docs/api/execution-20261029/STATUS.md описывает Support create command/replay receipt и draft PR23 на actual Support09c221c4. Support source в этой проверке не ревьюировался; все factories/SLA/parent-session adapters не подтверждены как завершённые. |
| M14 | partial | C:server/app/services/space_events.py:238–266 обновляет attempt signature и отказывает URL до сети без signing secret. Полный change feed, replay cursor/ACL перед выдачей и SSRF/DNS delivery profile остаются явными gap; это не готовый внешний webhook пакет. |
| M15 | partial | C:server/app/services/partner_identity.py:259–290 batching; product_api/budget.py:61–116 реализует shared PostgreSQL quota с503, retained process tests есть. F02, preauth edge policy, rows/RAM/pool/load/SLO и exports/jobs limits не закрыты. |
| M16 | partial | C:server/app/database.py:2206–2241 guard до DDL/create_all, table-like relkind и регистрация quota model; tests/test_schema_namespace_ownership.py, test_partner_schema_compatibility.py содержат harness. Полный versioned migration runner, backup restore и весь old-source lifecycle не заменены одним bootstrap guard. |
| M17 | partial | C:src/contexts/AuthContext.tsx, src/services/apiClient.ts и src/services/locationService.ts содержат targeted migration fixes; Support replay UI по D:docs/api/execution-20261029/STATUS.md. Большинство services ещё использует legacy `/api/*`; полного consumer usage доказательства и регрессии всех workflows нет. |
| M18 | partial | C:tools/partner-pilots/clients/* + публичный PARTNER_SYNTHETIC_PILOTS.md дают три read scenarios, 14 cases/89 requests в двух фазах. Real partner/ordinary employee/command pilots, full production composition и DB business baseline не подтверждены; настоящий отчёт добавляет лишь bounded source review. |
| M19 | not done | Есть план волн A–F и сохранён deprecated expand_all; нет доказанного перевода всех consumers, истечения compatibility window и отдельного retirement PR с rollback. Удалять legacy keys/path/adapters сейчас оснований нет. |

## Следующие конкретные пакеты по приоритету

1. **P0 к protocol/onboarding приёмке: F03 и F01.** Отдельный UserInfo negative
   response patch с missing/oversized/invalid/without-openid HTTP controls;
   SDK/quickstart разделяет canonical и browser URLs. Не расширять это исправление
   до замены всего auth stack. Повтор source review именно нового immutable diff.
2. **P0 к включению лимита: F02.** Четыре budget passthrough/defaults в deploy
   template и env.example, render-test false/default/override. Отдельно выбрать
   план и verified ingress peer policy для distributed OAuth preauth. Приёмка
   шаблона не включает live feature автоматически.
3. **P0 к новым write/domain обещаниям: M05/M06/M07.** Завершать отдельно temporal
   retirement/servicePoint→station→EVSE→connector mapping; shared reference/contract
   commands с ambiguity/null/replay; shared file ACL и GC. Каждый пакет имеет свои
   negative tenant/resource/concurrency cases. M06 parallel worker не включать в
   этот pin без отдельной проверки.
4. **P1: M00/M01/M02/M17 evidence и waves A–F.** Назвать active consumer и owner
   каждого legacy contract, добавить usage counters и characterization outputs;
   сначала generation/signal/error/binary transport primitive, затем references/
   objects, documents, monitoring/export, Support и остальные consumers. Сохранять
   существующие Core/Support trust boundaries и transports; новый внешний
   openid-client pilot не является вторым transport внутри Core.
5. **P1: M15 measurement package.** Реальные rows/count latency, bytes/RAM/pool,
   concurrency/large-export job bounds и quota error/load tests на отдельной
   синтетике с актуальным main assembly. Сейчас pageSize и SQL batching не дают
   upper bound стоимости COUNT или мониторинга, а post-auth quota не защищает
   сам verifier.
6. **P1: M14 внешний delivery/change feed.** SSRF/DNS/redirect policy, secret
   migration/rotation, актуальный access перед выдачей, retry/replay/cursor и
   subscription moment. Свежая HMAC подпись каждой попытки полезна, но всего
   этого не заменяет.
7. **P0 перед будущей рабочей schema migration, не перед source acceptance:**
   fresh backup и реальное restore, актуальный полный namespace/model preflight,
   old/new source compatibility, rollback composition. Guard и public sentinel
   checks сохраняются; source reviewer не требует трогать рабочую БД для отчёта.
8. **P0 к внешнему запуску M18, затем P2 M19.** Новая воспроизводимая fixture
   после destructive revoke controls, owner и ordinary employee positive/negative
   сценарии, реальный партнёр по docs без чтения server source; команды только
   когда опубликованы. Фиксировать business-row baseline отдельно от quota/auth
   metadata. Legacy удалять отдельным PR после usage evidence и compatibility
   window, с понятным откатом; отсутствие клиента в rg не равно отсутствию usage.

Site/EVSE/connector, partner writes, SSRF/changefeed, distributed OAuth preauth,
full consumer usage, real partner pilot и backup restore остаются открытыми.
Уже реализованный shared product budget из этого списка вычёркивать целиком
нельзя: его механизм есть, его доставка/нагрузка/включение требуют своих доказательств.
