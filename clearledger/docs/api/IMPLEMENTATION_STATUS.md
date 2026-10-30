# Партнёрский API: интеграционный кандидат

Состав исходников на 30.10.2026: ветка
`MagLook/api-modernization-integration-20261029`, runtime пакеты: WS `e6659c6e`, mapping `45a03b51`, Contract refresh `efd06570`;
Core export consumers `bc24daca`, corporate CP `ffab2a10`,
company-wide occupancy `461c9ed4`, typed history `1f0cf49a`, route triage `18fd90cf`;
инвентаризация Core на `7896039f`.
Изменения находятся в draft PR78. Merge и выпуска на РусГидро нет;
программа M00–M19 продолжается.

## Что реализовано

Child API `/api/v1` содержит 12 GET-операций: объекты ЭЗС, оборудование,
контрагенты, договоры, документы/разрешённые файлы и мониторинг объекта.
SQL-права применяются до count/limit/агрегации; cursor связан с текущими
разрешениями и отбором. Существующие ObjectId с кириллицей и пробелами сохраняются.
Девять операций допускают user/service, три документные требуют пользователя.

OAuth/OIDC на Authlib разделяет Core session, partner access, ID token и machine
grant. Есть Code+PKCE с явным согласием, rotating refresh, installations/resource
grants и живой отзыв. Изменение callback policy перепроверяется до выдачи code
и при обмене; непригодный issuer закрывает регистрацию/discovery/export.
UserInfo использует Bearer challenge для отрицательных ответов. Core login,
SSO handoff и ID token не заменяют access token продуктового API.

Защищённый Swagger выдаёт отдельную короткую docs session; UI/raw JSON/assets
закрыты одним guard. Canonical `/api/developer/docs/openapi.server.json`
описывает оба OAuth-профиля; `/openapi.json` в том же каталоге представляет
browser execution projection Code+PKCE. Шесть предметных групп и мобильные
описания проверены на закреплённом Swagger. Wire types генерируются официальным
openapi-typescript из настоящего curated exporter, без `.env`, сети и HTTP app.

Общие механизмы: document policy, file writer с rollback cleanup, counterparty
matcher и общие команды четырёх импортных путей, ServiceLocation commands, отдельная closing
materialization и чистый основной GET, batch live resource loader, attempt HMAC
Events, schema namespace guard. Новые контрагенты без ИНН используют NULL при
неизменном raw. Импорт 1С обновляет stale manual markers под существующей
блокировкой и сохраняет ручное очищение полей. Исправлены late response/401/login
гонки Core session и выбранные company-context consumers. Два общих binary
метода Core используют тот же error handler, поддерживают caller AbortSignal
и подавляют выдачу устаревших байтов после смены контекста. Прямые fetch
других consumers ещё не переведены. Пять XLSX exports в charge sessions,
corporate billing и sites используют этот общий метод; фильтры и прежние
fallback names сохранены, server filename имеет приоритет.

Общая PostgreSQL-квота считает company/installation/client между workers,
возвращает безопасные429/503 и ограничивает очистку. OAuth/API/docs/quota
выключены по умолчанию. `SOURCE_REVISION=unverified` не подтверждает готовность
публикации; docs environment по умолчанию `unconfigured`.

## Независимые локальные проверки координатора

Полные и последующие целевые прогоны относятся к своим указанным составам.
Их совокупность не объявляется единым полным CI финального HEAD.

| Состав | Результат |
|---|---|
| Identity/product/resources/ObjectId/monitoring/portal на28f6b7e2 | 296 PASS,268.31с, без SKIP/DESELECTED |
| Объектные команды и прежние сценарии | 123 PASS |
| Документы/файлы | 222policy;119writer/archive checks и2HTTP photo cases |
| Closing/payment | 121domain и16browser scenarios |
| Namespace guard на28f6b7e2 | 12real PostgreSQL PASS,229.213с |
| Core/public fresh/upgrade/repeat/old-source с portal+quota model | 31PASS,301.22с |
| Общая quota | 41offline и12SQL/process PASS,7.677с |
| Auth session lifecycle | 15actualReact и17transport/redirect PASS |
| Canonical/browser OpenAPI | 56offline,6pinned Swagger/interceptor,22HTTP/PostgreSQL PASS |
| HTTPS Swagger после auth/service/mobile fixes | PASS110.21с: actual main/public builds, PKCE/Try SQL/logout/revoke/expiredCore recovery |
| Responsive pinned Swagger | 7checks PASS на390/1200px |
| Core binary/session/location на02e6e963 | 151PASS,4.513с; React/Chromium15PASS,12.729с; app/node TypeScript и ESLint PASS |
| Пять Core export consumers наbc24daca | 403actual-service/binary/session/location PASS,4.669с; app/node TypeScript и ESLint PASS |
| Types generation/parity/drift/negative | 6PASS; freshness/consumer/typecheck PASS |
| Оба исправления контрагентов наe1cb1a53 | 52SQL/HTTP PASS,22.55с, прежний explicit-null test сохранён |
| UserInfo на9c33d932 | 70offline PASS,8.140с;FULL89identity/docs SQL/HTTP PASS,117.79с, без SKIP/DESELECTED |
| Events attempt signatures | 61mock-transport PASS; DNS/SSRF не проверены этим набором |
| Corporate CP / четыре импортных пути | 79SQL/HTTP/domain PASS,24.70с, без SKIP |
| Company-wide occupancy и admission | 224SQL/HTTP/domain PASS,37.58с, production listener, без SKIP |
| Route overlap triage | 109firstFULL literal и124source refs PASS,7pure controls;0guard denials |
| Разделение code/number history | 313SQL/HTTP/domain PASS,49.05с;89new+43updated+181unchanged, без SKIP;5pure shape controls PASS |

Внешние synthetic clients на официальном openid-client и публичных types прошли
8machine+6documents cases,89HTTPS requests; пять evidence digests проверены.
Проверены scoped pagination, foreign/ungranted denials, scope escalation,
живой token/grant/membership revoke, Code/PKCE/nonce/signature/UserInfo,
точные bytes/SHA файла и native file denials. Это два отдельных evidence этапа.
Делегированный пользователь — company owner/admin; ordinary employee UI case
SKIP. Server business-row immutability без baseline fingerprint не подтверждена.
Purpose-built local HTTPS fixture не заменяет full production main/nginx/SSO
или реального партнёра. Собственные тестовые процессы остановлены.

GitHub workflow `.github/workflows/checks.yml` имеет состояние
`disabled_manually`; его не включали. Отсутствие checks не означает PASS CI.
Все SQL-проверки используют отдельную синтетическую PostgreSQL, не рабочую БД.

Инструмент guarded runtime inventory прошёл root20PASS22.742с с двумя
byte-identical actual Core экспортами. Он видит1703операции, включая12curated
и1WS; exact duplicates и unresolved0. Все109literal/parameter candidates
независимо проверены через actual route.matches: literal firstFULL,0shadows,
124source refs и7pure controls PASS; это не HTTP/ACL acceptance.
Паспорта44special+31integration операций привязаны
к75registry keys и62source hashes; это source review, не общий ACL acceptance.

WS handshake privacy исправлена отдельно: root25PASS/2wsprotoSKIP1.34с.
Фильтр известных uvicorn.error formats скрывает query authority; exact chat WS
скрывает query целиком, в том числе encoded token key. Отзыв уже accepted WS,
произвольные debug/custom logs и все proxy/root_path compositions этим пакетом
не закрыты.

Native external mapping теперь проверяет общий target admission и bind link
к company/path/type/relation. Root147PASS28.32с. Для договоров1С исправлен
подтверждённый persisted overwrite ручных NULL из stale ORM: company-scoped
Contract SELECT перечитывается после прежнегоflush/lock. Root57PASS35.35с.
Даты mapping/повторное закрытие/собственные commits и остальные writer bypass
этими пакетами не исправлялись.

Общая native/registry команда сохраняет раздельную typed identifierHistory
для code и station_number; legacy numberHistory содержит только фактические
номера. Технический код остаётся занятым, но не становится station alias.
Повторный review исправил ошибку первого пакета; root313PASS49.05с подтвердил
оба actual reader controls, защиту серверной истории, no-reuse и прежние права.
Company-wide Core collision check видит скрытые номера без скрытых ORM entities;
hidden upsert404/new create403 сохранены. Импорты/bulk и valid-time ledger
остаются открытой границей, совместимость отката старого writer требует оценки.

## Что остаётся

Write API, site/EVSE/connector и temporal retirement, shared-file GC, все
reference/contract/lifecycle commands, полный consumer ownership/usage,
SSRF/DNS/change feed/replay, distributed OAuth pre-auth, load/SLO/export/job
budgets, versioned migration runner и реальный dump/restore не завершены.
Физический DELETE ServiceLocation временно возвращает409; прежний
GET closing с expand_all остаётся deprecated write-guarded путём.
Другие reference sync пути и расширенный null-intent требуют отдельной работы.

Read-only runtime baseline РусГидро сверялся до кандидата. Catalog preflight по
333model names подтвердил current_schema=core и отсутствие чужих видимых
relations, но был до quota model. Перед выпуском нужны свежий полный preflight,
backup с фактическим восстановлением, состав релиза и rollback. Локальные PASS
не подтверждают готовность всей программы или рабочего пространства.

Подробности: [quickstart](../PARTNER_QUICKSTART.md),
[types](../PARTNER_SDK_TYPES.md), [OpenAPI profiles](service-openapi-20261030.md),
[пилоты](PARTNER_SYNTHETIC_PILOTS.md), [quota](product-budget-20261030.md),
[контрагенты](counterparty-explicit-null-20261030.md),
[UserInfo](userinfo-protocol-20261030.md),
[binary transport](CORE_BINARY_TRANSPORT_20261030.md),
[WS logging](WS_LOG_PRIVACY_20261030.md),
[export consumers](CORE_EXPORT_CONSUMERS_20261030.md),
[mapping admission](station-mapping-admission-20261030.md),
[Contract manual fields](contract-manual-freshness-20261030.md),
[исторический пакет номеров](location-number-history-20261030.md),
[разделение code/number](location-identifier-history-20261030.md).
Общий план и статус M00–M19 находятся в ecosystem-deploy;
Support create/retry — отдельные draft PR23/24 TSupport.


Корпоративный четвёртый producer CP также переведён на общие create/alias команды
(c45ea290→ffab2a10): исходный baseline4FAIL/19PASS воспроизвёл конфликт второй
unknown-INN карточки; root79PASS24.70с без SKIP подтвердил исправление вместе
с прежними importer/explicit-null/1С identity regressions. Optional KPP различает
omitted и explicitNone, прежние три raw формы не расширены. Схема и старые
данные не переписывались; Contract/phone/matcher/locks/callercommit сохранены.
[Доказательства](corporate-counterparty-commands-20261030.md).


Company-wide occupancy теперь не сужается пользовательским ORM listener:
Core columns с явным tenant predicate проверяют скрытые current/history aliases
без hidden entities и без расширения обычного чтения. Hidden existing upsert
снова даёт404, новый scoped create403. Root224PASS37.58с;
[отчёт](location-number-scope-collision-20261030.md). Разбор109route candidates
также независимо повторён: каждый literal выигрывает firstFULL,0shadows,
124endpoint refs; это match-only proof, не HTTP/ACL acceptance.
[Отчёт](ROUTE_OVERLAP_TRIAGE_20261030.md).


M05-B: принят [план импортных adapters](M05_IMPORT_ADAPTER_DESIGN_20261030.md)
(source11c5a291→e0c30702). Root подтвердил29immutable source blobs, paired
Markdown SHA и26source fact refs;14SQL сценариев пока только запланированы.
Рекомендуется полный sorted-ID set до company barrier с root-T capability
и запретом late extension. Unit/document/session/book writers — обязательные
prerequisites, а не предположения. Реализация foundation начата отдельно,
импорты ещё не подключены. Partial/reconciliation должен доходить до UI
без ложного success toast; текущий UI исправляется отдельным ограниченным пакетом.


M17: два consumer фоновой загрузки показывают partial через warning вместо
success. Root TypeScript app/node PASS; ESLint baseline и candidate совпадают
(7прежнихerrors/3warnings,0новых), полный lint остаётся FAIL. Browser/HTTP
E2E не выполнялся. [Отчёт](channel-partial-notifications-20261030.md).


Foundation M05-B принят: acquire_location_set/LockedLocationSet и admitted lookup
предварительно берут полный sorted-ID set перед company barrier. Root373PASS53с,
включая60новых и313неизменённых; контекст набора связан с root T и не расширяет O/G.
Late extension и потеря dirty target блокируются до SQL. Крупные sets и
подключение import/unit/FK writers остаются gated.
[Отчёт](location-lock-sets-20261030.md).


Scoped Codex Security Standard завершён для трёх файлов api_contracts на
310b31afb263d0ece311094f32e13a8b0cf0383e: findings0/deferred0, canonical sealed
readback PASS у владельца continuation claim. Проверка последовательная без
независимого baseline-агента; supporting auth/product/identity trace-only.
Это не полный аудит API/production/OAuth и не разрешение выпуска.
[Сводка](API_CONTRACTS_SECURITY_REVIEW_20261030.md).


Ручные name edits native PATCH, existing-ID POST/upsert и registry теперь
ставят server-owned provenance, а W10 проверяет manual marker по текущей строке.
Исходный baseline3actualFAIL+2controlPASS, root441PASS61.82с. Это68новых плюс
372прежних expectations и1согласованный strengthened golden; initial create
и W07/W08 не защищены. [Отчёт](location-manual-names-20261030.md).
Existing-only SourcePatch с независимыми column/metadata numbers готовится
отдельно; импорты ещё не активированы.


Загрузка первичных документов использует общий multipart-клиент с сохранением
credentials include; отдельные fetch/auth/error удалены. Разбор файла и ручной
accept остаются разными действиями. Root: 392 transport/session/export PASS
за 4,749 с, app/node TypeScript и targeted ESLint PASS. Реальный CORS/cookie
обмен не проверялся. [Отчёт](INTAKE_UPLOAD_TRANSPORT_20261030.md).


Принят воспроизводимый AST-каталог клиентских обращений: 1147 production files,
1459 shared / 43 native records / 3769 unresolved candidates. Root повторил
9 pure tests и полный scan, сверил все source blobs и побайтовый результат.
Динамические вызовы и внешние партнёры не считаются установленным runtime
ownership. [Отчёт](API_CONSUMER_INVENTORY_20261030.md).


Voice-клиент сохраняет исходный контекст операции через выдачу токена, HTTP,
разовый retry и чтение тела; явный reset прекращает старый SSE. На исходном
сервисе воспроизведены две гонки смены пользователя той же компании. Отдельные
остаточные await-hop случаи первого candidate устранены после review. Root:
415 Node PASS, app/node TypeScript и targeted ESLint PASS. Это synthetic
reset-only proof с сохранением отдельного aud=voice протокола.
[Отчёт](VOICE_CONTEXT_BOUNDARY_20261030.md).



Принята внутренняя команда независимого изменения station_number и metadata.number
существующей точки. Она требует заранее полученный набор блокировок и отсутствие
pending ORM changes; uses current admission/reload и общие freeze/history/no-reuse
guards. Root564PASS72.93с, 13 прежних модулей тестов неизменны. JSONB numeric
round-trip проверен, нормализация ограничена новым source validator. Импорты
ещё не подключены; ограниченный guard ambiguous identity принят отдельно ниже.
[Отчёт](location-source-number-patch-20261030.md).


Импорт W07/W08 различает новую и неоднозначную идентичность. При конфликте
кандидатов строка не меняет point/unit/region/audit, не создаёт дубль и возвращает
partial с ограниченным списком reconciliation. Unique strong matches и прежний
intentional AC/DC split сохранены. Actual baseline24FAIL/13PASS; root608PASS
78.99с без SKIP,20 прежних функций и16модулей тестов неизменны. Полный import
protocol, stale indexes и concurrent/global no-reuse остаются открытыми.
[Отчёт](station-import-ambiguity-20261030.md).


На source pin62bd4a46 разобраны все43native AST records:28keep/13extract/2defer.
Прямые вызовы разделены по Core/Voice/Auditor/vendor/static boundaries,9из43
относятся к реализации apiClient. Root повторил inventory и проверил1147Git
blobs,43AST expression hashes,117immutable snippet refs и MD/JSON agreement.
Это статическая карта, не подтверждение production traffic или server ACL.
[Разбор](NATIVE_CONSUMER_TRIAGE_20261030.md).


Native PATCH договора использует общий с импортом company barrier до autoflush,
после ожидания перечитывает текущий договор и членство перед правкой. Actual
baseline2FAIL/2controlsPASS; root117PASS35.04с без SKIP. Сохранены13прежних
модулей тестов; concurrent manual NULL, stale payload/pending ORM state и
revoke/scope/demotion/move/delete проверены. Все writers модели и live
organization/global/superadmin semantics не объявляются покрытыми.
[Отчёт](contract-manual-serialization-20261030.md).


Отложенные presence и три входа в конференции используют общий context guard.
Для этих callers post передаёт opt-in guard до поздних401effects; обычный401
сохраняет прежний ApiError. Root471PASS73.763с, app/nodeTypeScript и targeted
ESLint PASS; binary/error/setters и9прежних source/test modules сохранены.
Другие unguarded JSON callers и уже отправленные серверные действия этой
гарантией не покрыты. [Отчёт](CONF_CONTEXT_BOUNDARY_20261030.md).


Экспорт наработок Auditor использует тот же context guard и finally cleanup:
после смены контекста старый ответ не инициирует скачивание, временный URL
освобождается при ошибках create/click/remove. Отдельный same-origin proxy,
Bearer, имя архива и Auditor error semantics сохранены. Root509PASS75.638с,
app/nodeTypeScript и targeted ESLint PASS;11прежних runtime/test modules
сохранены. Browser download manager/server ACL/SSE/PTY не проверялись.
[Отчёт](AUDITOR_EXPORT_CONTEXT_20261030.md).


Измерен synthetic scaling объектов/договоров/документов на100/1000/5000: root
3PASS/237HTTPsamples230.677с. SQL shapes/counts, ACL/total/page/detail/cursor,
link redaction, hydration и response bytes всех237records совпали сauthor run.
Page size ограничивает гидратацию карточек; total и проверка больших SET
требуют отдельного анализа. Walltime/peak относятся к traced single run,
не production SLO. [Отчёт](PRODUCT_QUERY_SCALING_20261030.md).
