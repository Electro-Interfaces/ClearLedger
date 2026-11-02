# M11: ordinary employee → защищённая документация

Статус: **AUTHOR / NOTRUN**. Ни collection, ни imports, ни тесты этого пакета
не выполнялись. Runtime всех 24 случаев — **UNKNOWN**. Исходная точка:
`c67b49f94918a3c72faaabc60e814060c7d54af4`, tree
`5c917073f18af7bedccb7bcdf6fb2e57ce083dfb`. Коммит кандидата и SHA-256 файлов
фиксируются отдельно при передаче. Изменены только новый тестовый модуль и этот план.

Пакет использует `tests/partner_contract_issuer_fixture.py:issuer_world`, которому
вызывающая сторона передаёт **реальную** `partner_contract_issuer_factory`.
В репозитории определения этой фабрики нет: запуск без внешней admission и фабрики
не поддерживается. `issuer_world` создаёт synthetic Core/company/references и
настоящие Authlib user/machine grants; не содержит собственного teardown.
Вызывающая сторона обязана владеть его lifecycle и очисткой. Новый `native_docs`
добавляет своего обычного сотрудника (User и membership role=user, superadmin=false,
CompanyRole с developer:docs/equipment/references), два App/client/installation,
confidential credential/machine grant и отдельный канонический CREATE profile.
Одобренные строки — явный SQL setup; это не проверка HTTP-админского согласования.

Реальные компоненты: `app.auth.token_for`, native `get_current_user`/session checks,
`partner_oauth_router` authorize/consent/token и Authlib CodeGrant/S256/OpenID,
`docs_portal_router`/`services.docs_portal`, M10 live_grant/verifier, canonical models,
product child с исходным verifier и policy registry. Подмена только `get_db` на
реальную factory и тестовая конфигурация; решений auth/ACL, SQL и обработчиков
не подменяем. Настоящий native JWT здесь создаётся программным `token_for`.
Парольный вход, почта, браузер, Swagger JS execution, ingress, CORS и SSO этим
пакетом не проверяются; защищённые байты и ASGI-вызовы не доказывают Try it out.

Путь: public authorize с точным callback, state/nonce и RFC7636 S256 → consent GET
с ordinary bearer → approve выбранных company/scopes → code в callback с исходным
state → exchange исходного code/verifier/redirect → подпись/nonce ID token и live
SQL token/grant → POST docs/session с Origin/bootstrap → HttpOnly/Secure/Strict
cookie. На каждом защищённом GET действует исходный live authority; logout требует
той же Origin и CSRF, отзывает связанную family. Новые state/nonce и UUID на случай.

| Определение `test_…` | Параметры / число | Запрос → assertion / данные |
|---|---:|---|
| native_employee_code_pkce_cookie_and_exact_product_projection | 1 | Реальный flow → ordinary rows, consumed code, проверенный ID-token nonce, cookie/TTL; все 8 surfaces дают 200; точное отображение 17 path/method/operationId в обоих OpenAPI, ProductOAuth-only browser и сохранённый server profile |
| bearers_cannot_replace_docs_cookie | native, product / 2 | Все surfaces с native или настоящим objects:read bearer без cookie → 401 |
| public_authorize_rejects_invalid_protocol_inputs | redirect, state, nonce, pkce, scope / 5 | Невалидный authorize → 400 OAuth error без redirect/code rows |
| code_exchange_rejects_wrong_binding_without_consumption | verifier, redirect / 2 | Ошибочный exchange → invalid_grant, code не consumed; исходная пара затем даёт 200 |
| consent_rechecks_employee_authority_after_page_open | member, role / 2 | После GET удалено owned membership или очищена owned CompanyRole → approve 422 INVALID_AUTHORIZATION_SELECTION, grant не создан |
| current_authority_closes_existing_cookie_and_new_issuance | grant, member, client, installation, actor_mail_only, actor_tv / 6 | Реальный отзыв owned rows → все защищённые bytes/session GET 401 и повторный bootstrap прежнего access 401 без Set-Cookie |
| docs_capabilities_grant_no_product_read_or_write | cookie/GET, cookie/POST, docs/GET, docs/POST / 4 | GET objects и POST contracts с явно переданной cookie либо docs-only Bearer
и валидным synthetic body → точные 401/403 Problem, без изменений Contract/ContractLocation/Intent/IntentLocation/AuditEvent |
| real_machine_docs_scope_cannot_bootstrap_browser_session | 1 | Реальный client_credentials token с docs:read и user=null → bootstrap 403, UI bearer-only 401 |
| employee_logout_with_origin_csrf_closes_next_access | 1 | Корректный DELETE → 204, cookie expiry и revoked SQL rows; stale cookie GET и новый bootstrap прежнего access → 401 |

Отрицательные product cases сначала проверяют настоящий objects:read token →
200 с собственным opaque object ID. Также отдельно выдаётся настоящий
contracts:create token того же сотрудника и выполняется исходный read-only
`require_coarse_create` против собственного включённого profile/principal.
POST использует валидированное тело существующего canonical synthetic fixture,
его organization/counterparty/location/type; без вызова успешного POST.
Это исключает выключенный API, отсутствующий profile или malformed body как
объяснение отрицательного результата. Предварительный coarse check не является
полной положительной CREATE-приёмкой и не доказывает запись.

Существующий `test_docs_portal_logout_scoped_locks_pg.py` остаётся без изменений:
порядок typed/row locks, ожидания, drift, rollback/cancel/commit failure, cascade,
dirty-entry и family isolation здесь не повторяются. Старый `test_docs_portal.py`
пересекается по surfaces/revocation, но создаёт admin membership через HTTP admin
registration; новый пакет проверяет ordinary employee и отдельный lifecycle.
Старые отчёты не дают новым определениям runtime PASS.

Admission перед любым collection выполняет вызывающая сторона: точный source
commit/tree и diff, guard-safe isolated target, явные существующие opt-ins,
отдельные TEST_DATABASE_URL и matching DATABASE_URL (значения здесь не хранятся),
выделенный test UPLOAD_DIR, реальные Core schema/revision0004 и все FK, async
PostgreSQL factory с search_path=core и READ COMMITTED. Роль для утверждённого
lifecycle должна иметь нужные schema/bootstrap права и права на synthetic rows;
обычное приложение или рабочая БД не подходят. Parent conftest импортирует engine
и имеет destructive setup: module guards не заменяют внешнюю preimport admission.
Наследуемый issuer_world проверяет isolation/schema, но не предоставляет admission.

Один случай — одна последовательная composition; фоновых задач/серверов/сетевого
HTTP нет. ASGI client timeout=5s и явный asyncio timeout=8s на каждый реальный
ASGI-запрос (httpx timeout сам по себе не ограничивает ASGI), отдельный 20s timeout
на cleanup. Для actual SQL role/session нужны утверждённые конечные
statement/lock timeouts. Тесты не меняют настройки роли и не допускают параллельный
запуск с общими settings/cache. OAuth cache очищает существующий issuer_world;
новые clients/state/nonce исключают пересечение собственных случаев.

`native_docs` выполняет finally даже при сбое setup/assertion: закрывает HTTP и
sessions, удаляет только новые ресурсы по точным owned IDs. Порядок: Docs sessions →
tokens → families → codes → grants → auth requests/subjects/credentials → CREATE
profile (FK CASCADE к principal/ref/type) → resource scopes → installations →
CompanyApp → clients → apps → membership → user → role; отдельный fresh reader
проверяет отсутствие owned parents. Всё это происходит **до** teardown
`issuer_world` и его внешнего lifecycle. Его company/org/cp/location/type и
унаследованные grants не удаляются новым fixture. DROP/reset/broad deletes нет.

Source-проверки: stdlib Python 3.13 `-I -S`, AST и compile без исполнения; literal
manifest, diff, pins, ровно два новых пути и parity остальных объектов с baseline.
Неизвестны фактические collection/fixture resolution, driver UUID типы, SQL/FK и
handler outcomes, cleanup после cancellation/сбоя и время исполнения. Изученный
source обещает перечисленные запреты; это ожидания новых тестов, не обнаруженные
runtime-уязвимости. Известное ограничение источника — внешняя factory/lifecycle,
не отсутствующий auth helper. Корректность браузерного callback/state handling
требует отдельной браузерной проверки.

Вызывающая сторона отдельно утверждает будущий collect/run, фиксирует точные
source pins, имена/параметры 24 случаев, command/exit code, PASS/FAIL/SKIP,
санитизированные результаты и fresh-reader cleanup evidence. Любой source gap или
неожиданный ответ сохраняется как FAIL/UNKNOWN; production fix и ослабление oracle
в этот пакет не входят. M11, остальные M00–M19 и 11 общих условий остаются OPEN /
unproven; completion=false.


## 01.11.2026 — первый фактический setup ERROR и узкая правка seed

Первый отдельный запуск исходника
`68155454d849331d4c8bd46edd363beadc43004a` выбрал 1 happy-path случай:
selectedCases=1, testsRun=0, setupErrors=1. До вызова теста INSERT в
`core.eco_apps` завершился `StringDataRightTruncationError`, SQLSTATE 22001:
seed передавал `machine-docs-<32 hex>` длиной 45 в `App.code` с лимитом 40.
OAuth flow и защищённые surfaces не выполнялись. Это дефект тестового seed;
результат не является обнаружением ошибки production auth. Первый ERROR
сохраняется как отдельный фактический результат и не переобозначается в PASS.

Узкая правка только в `native_docs`: отдельный owned `App.code` по формуле
`nd-{index}-{suffix}` имеет длину 37 для каждого из двух приложений и уникален
по index при общем UUID suffix. Client IDs `docs-<32 hex>` (37) и
`machine-docs-<32 hex>` (45) сохранены целиком: оба укладываются в собственный
лимит `PartnerClient.id` 64. Схема, связи App/client/installation, config,
grants, OAuth/native JWT, cleanup, 9 определений и 24 случая не изменены.

Правка проверяется только статически: AST, compile без исполнения, обратная
подстановка исходного тела `native_docs`, parity остального файла и дерева.
Нового collection/run или runtime PASS здесь нет; исторические source pins
выше сохранены. Следующий шаг вызывающей стороны — admission точного нового
source и повтор только happy-path (1); после его фактического успеха — остальные
23 случая с отдельными результатами и cleanup evidence. Все M00–M19 и 11 общих
условий остаются OPEN / unproven; completion=false.
