# Партнёрский API: интеграционный кандидат

Состав исходников на 30.10.2026: ветка
`MagLook/api-modernization-integration-20261029`, runtime pin `02e6e963`.
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
matcher и три импортные команды, ServiceLocation commands, отдельная closing
materialization и чистый основной GET, batch live resource loader, attempt HMAC
Events, schema namespace guard. Новые контрагенты без ИНН используют NULL при
неизменном raw. Импорт 1С обновляет stale manual markers под существующей
блокировкой и сохраняет ручное очищение полей. Исправлены late response/401/login
гонки Core session и выбранные company-context consumers. Два общих binary
метода Core используют тот же error handler, поддерживают caller AbortSignal
и подавляют выдачу устаревших байтов после смены контекста. Прямые fetch
других consumers ещё не переведены.

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
| Types generation/parity/drift/negative | 6PASS; freshness/consumer/typecheck PASS |
| Оба исправления контрагентов наe1cb1a53 | 52SQL/HTTP PASS,22.55с, прежний explicit-null test сохранён |
| UserInfo на9c33d932 | 70offline PASS,8.140с;FULL89identity/docs SQL/HTTP PASS,117.79с, без SKIP/DESELECTED |
| Events attempt signatures | 61mock-transport PASS; DNS/SSRF не проверены этим набором |

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
[binary transport](CORE_BINARY_TRANSPORT_20261030.md).
Общий план и статус M00–M19 находятся в ecosystem-deploy;
Support create/retry — отдельные draft PR23/24 TSupport.
