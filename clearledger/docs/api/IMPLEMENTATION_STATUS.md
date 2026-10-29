# Партнёрский API: интеграционный кандидат

Версионированный child API подключён к `/api/v1`. Он использует отдельный
партнёрский verifier; Core session, SSO handoff и ID Token не заменяют access
token API. Реестр child проверяется явно при сборке приложения: parent mount
сам по себе не запускает его lifespan. Ключ cursor стабилен между workers и
рестартами и выведен из серверного секрета с отдельным назначением HMAC.

По умолчанию `PARTNER_OAUTH_ENABLED`, `PARTNER_API_ENABLED` и
`PARTNER_DOCS_ENABLED` выключены. Для Swagger зарезервированы настройки
`PARTNER_DOCS_CLIENT_ID`, `PARTNER_DOCS_ENVIRONMENT=unconfigured`,
`PARTNER_DOCS_SANDBOX_API_URL`. Портал подключён к Core; его UI, raw OpenAPI
и локальные Swagger assets требуют отдельной короткой docs-сессии.
Business scopes выдаются отдельным Code+PKCE, Try it out — только на песочнице.
`SOURCE_REVISION` используется как идентификатор состава при экспорте;
значение `unverified` не подтверждает готовность публикации.

Независимая интеграционная проверка: 52 identity и 57 product тестов PASS;
19 тестов настоящей цепочки Core login → consent → code/PKCE → mounted API
PASS. Без подмены verifier проверены SQL scope/total/detail/pagination,
редакция полей, token confusion, живой отзыв client/installation/account,
изменение object scope и привязки cursor, отдельные default-off gates.
Typecheck и 296 frontend unit тестов PASS. Экспортированный curated OpenAPI
прошёл общий offline design gate, runtime readiness остаётся candidate.

При независимом review исходного OAuth-патча обнаружено, что сохранённый
development callback не классифицировался повторно после смены конфигурации.
Canonical exact-match теперь также проверяет действующую URI policy перед
authorize/consent, а token endpoint закрывает непогашенный code с запрещённым
теперь redirect. Regression проверяет dev → prod и выключение loopback flag;
раньше согласованная конфигурация не остаётся бессрочным исключением.

Также issuer проверяется до записей в реестр: порт обязан быть допустимым,
а исходная строка не может содержать control/whitespace/backslash, которые
URL parser способен нормализовать или проверить позднее. Проверено отсутствие
новой регистрации при отказе 503; discovery и curated OpenAPI также закрыты
при непригодном origin. Повторены восемь изменённых issuer/exporter случаев.

Удалённый workflow `.github/workflows/checks.yml` имеет состояние
`disabled_manually`; его не включали. Отсутствие GitHub checks не означает
прохождение CI: приведённые выше результаты относятся к локальным прогонам.

Identity/product тесты переведены на явный opt-in с общим pure safety guard,
без жёсткой привязки к машине/порту/имени БД. На одном интеграционном составе
128 identity/product/полных-chain тестов PASS. Schema suite запускается
отдельным процессом/job: у исполнителя 25 fresh/upgrade/repeat/guard проверок
PASS с настоящими предыдущими исходниками. Автор подтвердил 31 Core/public case и 2 финальные проверки индексов
с неизменными public sentinels. Манифест новой таблицы уточнён по фактическому
immutable M11 `partner_docs_sessions`; финальный portal gate и schema прогон координатора завершены: 31 PASS на immutable ef5f6ee2, 295.47 с.

Это часть программы модернизации. Write API, все уровни объектов, общий
идентификатор предметных команд, события, оптимизация и перевод всех старых
потребителей ещё не завершены. Локальные тесты не подтверждают независимую
приёмку всей программы, совместимость всех клиентов или рабочий выпуск.


Дополнительная приёмка координатора: M05 команды и прежние объектные сценарии
**84 + 39 = 123 PASS**, отдельный monitoring policy mapping **12 PASS**.
M11 HTTP/SQL **21 PASS**; первая browser-проверка остановилась на гонке теста:
удаление nginx gate до загрузки private consent chunk давало ожидаемый 403.
Тест исправлен (`ef5f6ee2`): gate удаляется после отрисовки согласия перед
отправкой, чтобы проверить именно public callback. Повтор browser на том же executable/test составе завершён: PASS за111.44с, реальные main/public build, HTTPS, native Swagger Authorize/Try SQL/logout/revoke.
Эта запись не переносит авторские 22 PASS на непроверенный общий состав.


Продолжение 30.10.2026, кандидат28f6b7e2. Общий PostgreSQL/HTTP набор identity,
product, resource budgets SQL-count, ObjectId, monitoring и docs portal: **296 PASS
за268.31с**, без SKIP/DESELECTED. Старый identity table recreation manifest теперь
включает partner_docs_sessions; ошибка DROP не скрыта исключением теста.
Пакетная загрузка live resource profiles/items уменьшает число statements на4–8
при pageSize1/50/200, права продолжают перечитываться. Кириллица/пробелы
ServiceLocation IDs сохраняются во внешнем контракте, ACL и cursor.

M09 центральный Problem formatter сохраняет status-specific protocol headers;
curated OpenAPI описывает actual 12operations/errors/header examples. Root:
20PASS+36subtests,28schemaPASS+132subtests. Это ASGI с synthetic verifier/domain
seams, не повтор настоящей OAuth/SQL цепочки на этом patch. Официальный
openapi-typescript7.10.1 с изолированным lock генерирует wiretypes реального
curated exporter:6generation/parity/drift/negative PASS, consumer/check/typecheck
PASS. Прямая сеть/.env в exporter запрещены; transport/refresh в types не входят.

M14 root61mock-transportPASS: подпись каждой попытки свежая, ID/time факта
сохранены; невозможность расшифровать signing secret запрещает URL-доставку
до сети. DNS/SSRF и полныйchangefeed ещё не закрыты.

M16 root independently **12 real PostgreSQL PASS за229.213с** на28f6b7e2:
guard выполняется до DDL/functions, не позволяет принять public tables за Core,
сохраняет public/Core/explicitEdge/oldORM compatibility и не блокирует чужие
INDEX/SEQUENCE, которые SQLAlchemyhas_table не считает таблицами. Foreign
TABLE/partitionedTABLE/VIEW/MATVIEW отклоняются раньше изменений. Read-only
preflight фактического rushydro по333modelnames: currentSchema core,
transactionReadOnly on, visibleForeignRelations=[]; это не backup/restore
или release validation. Старый initialRuntime snapshot требует fresh сверки
перед будущим выпуском.

M18 standalone synthetic HTTPS sandbox и официальныеopenid-client клиенты
подготовлены отдельно, actualHTTPpilots ещё не приняты. M15distributedquota
implementation идёт отдельно, ни ratebudget/SLO, ни productionreadiness этим
отчётом не заявлены. Все изменения остаются draft без merge/выкатки.
