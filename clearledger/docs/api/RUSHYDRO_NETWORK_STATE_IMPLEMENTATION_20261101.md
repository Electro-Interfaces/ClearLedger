# РусГидро: исходник состояния сети, 01.11.2026

Статус: реализация для прямого review Root, runtime **0**. Тесты написаны,
**NOT COLLECTED / NOT RUN**. Импорты приложения, DTO validation, SQL compilation,
экспорт OpenAPI/SDK, HTTP/SQL, сборка и выпуск автором не выполнялись.
Проверки автора ограничены текстом Git, stdlib AST/hash и compile без исполнения.
Это не Source PASS, не подтверждение нового маршрута и не готовность всего API.

Основание: commit `08b88afcaf0669a3207509543fbb83797ddaae64`, tree
`58e0d03e28eb409c358e9fcc6937f544e9ffd386`; неизменные
`rushydro-network-state-20261101/ROOT-DECISION.md` и `TARGET.md`/`TARGET.json`.
Поручение `task_5a258116c2b9`, Dispatch `ctx_a0ae0f17a082`; единственная копия
`/home/mag/orca/workspaces/ledger-app/rushydro-network-state-code-author-20261101-2`,
ветка `MagLook/thresher-2`. Дополнительные агенты/копии не создавались.

## Состав и Source plan

Ровно шесть разрешённых файлов:

1. `server/app/services/network_state.py`: один общий native mismatch helper,
   отдельная ограниченная операционная проекция владельца.
2. Новый `server/app/product_api/network_state.py`: admission, авторизованный
   selector, транзакция/срок, курсор и DTO; бизнес-формулы остаются у владельца.
3. `server/app/product_api/dto.py`: закрытые query и ответ с allowlist.
4. `server/app/product_api/app.py`: регистрация одного метода с прежней policy.
5. Новый `server/tests/test_rushydro_network_state_native_pg.py`: охраняемые
   реальные SQL/Authlib сценарии для будущего внешнего прогона Root.
6. Этот документ: самостоятельная передача реализации и границ проверки.

Седьмой файл не нужен: используется существующий проверяемый `cursor_key`
приложения и `Query.binding`; старые created_at cursors не меняются.
Все остальные entries BASE заморожены, включая verifier/access, conftest,
providers, модели/схему, конфигурацию/флаги, CI, SDK, OpenAPI bundles, старые
projection/schema count tests, TARGET и ROOT-DECISION. Память не менялась.

## Поведение и ограничения данных

Добавлен `GET /api/v1/monitoring/network-state`, operationId `getNetworkState`.
Сохраняются Product policy: PARTNER user или одобренный SERVICE, одновременно
`monitoring:read` и `objects:read`, energy profile. Канонический verifier,
текущие grants/membership и независимая quota выполняются на каждой странице
до разбора курсора. Facts не берутся из URL/query/tenant/org/header override.

Adapter передаёт владельцу SQL `Query.conditions("objects")`: company, typed
object grant, текущий membership object ceiling и organization SQL EXISTS через
текущие договорные связи. Членство компании само по себе не заменяет org-доступ.
У владельца нет импорта product API и нет вызова полного финансового отчёта.

SQL кандидатов дополнительно ограничен company и общим `station_scope.в_сети()`.
Материализуются максимум **10001** строк нужных скаляров: точный ID, owner,
operational status, нормализованное имя региона и безопасный fallback региона.
Имена регионов ограничены SQL `left(..., 201)` ДО материализации; 201 сохраняет
несовпадение длинного значения с допустимым токеном длиной до 200. JSON fallback
разрешён лишь при `jsonb_typeof == string`; object/list/number не stringify.
Region join дополнительно связан с company, полного каталога регионов нет.
Более 10000 кандидатов → безопасный 503 ДО Python owner/region. Отказ относится
к разрешённой текущей сети, даже если последующий регион/owner дал бы пустой E.
ORM, вся metadata и список сессий целиком в этом пути не материализуются.

E — разрешённые обслуживаемые станции выбранного региона. `обслуживаем` и
`region_matches` прежние; нормализованный регион приоритетнее fallback.
`session_boundary` получает именно E, включая `set()`, до SQL MAX. Второй
session SQL — только MAX последней **положительной энергии**, company AND E,
started_at <= effective point, GROUP BY object. Сессионных выборок две; деньги,
ритм, dry attempts, attention, финансовые состав/порядок не вычисляются.
EMPTY никогда не превращается в None/ALL, company-global watermark отсутствует.

`monitor_context` сохраняет D1: dataThrough — MAX по E, в том числе позже
requestedDate; effective point — min(dataThrough или now MSK, конец asOf MSK).
lastChargeAt — только положительная энергия до effective point, nullable,
явное +03:00. silentDays — прежний календарный `_возраст`, nullable. Паспорт,
состав парка и status текущие и при исторической дате, история статусов не
восстанавливается. availability=observed означает наличие наблюдения E,
не здоровье/полноту источника; иначе unknown, даты/lag null где неизвестны.

M — E после optional onlyProblems, который равен **только** точному native
mismatch. Сводка stations/mismatch/восемь byStatus считается по полному M до
страницы. Публичный unknown fallback не отражает raw status. ID сортируются
по UTF-8/C, без strip/casefold/Unicode normalization/UUID conversion; после
курсора выбираются точные ID больше последнего, pageSize 1..200, default 50.
Ответ имеет только items(objectId/status/lastChargeAt/silentDays/mismatch),
summary, context и nextCursor. Raw metadata/status, labels, человек, деньги,
loss/attention и их производные не входят в поля, отбор или порядок.

## Курсор, HTTP и транзакция

Новая HMAC-SHA256 envelope использует существующий application cursor key,
без новых ключей/fallback; секреты автором не читались. Подпись защищает version
network-state-1, lastId, dataThrough, effective point и `Query.binding`:
principal kind/subject, company/client/install/grant, policy, scopes, все typed
grants, membership object/org ceilings, точные filters и pageSize. namespace
отличается от старого created_at cursor. Изменившиеся binding или boundary →400
invalid_cursor/restart. Отзыв текущего доступа отрабатывает до decode/use.
Для сети без наблюдений подписанный первый effective point сохраняет часы
между страницами; если наблюдение появится, boundary изменится →400.
Каталог и сессии могут меняться; snapshot и постоянная summary не обещаются.

asOf строго YYYY-MM-DD, от 2000-01-01 до текущего дня МСК. region: 1..200
символов, до 20 непустых точных токенов через `|`. onlyProblems принимает
true/false. Неизвестные query →422. Непустой GET body отклоняется по первому
непустому chunk без накопления тела. Существующие Product Problem, no-store,
X-Request-Id, Bearer/challenge, quota429/Retry-After и error handlers сохранены.
CORS, ingress и live здесь неизвестны.

Бизнес-чтение ограничено asyncio deadline 5 секунд, включая получение отдельной
сессии, body admission, запросы и проверку итогового CPU времени проекции/DTO.
Пул identity/quota освобождён до этого чтения прежним access.resolve. Только
собственная новая транзакция: `SET TRANSACTION READ ONLY`,
`SET LOCAL statement_timeout = '5s'`; она всегда rollback, включая успех.
Rollback защищён от отмены и дожидается завершения до закрытия сессии. Уже
активная чужая транзакция отклоняется; её commit/rollback не выполняется этим
кодом. Timeout/DBAPI cancellation/admission дают безопасный 503 без SQL/params;
DBAPI ошибки не сериализуются. LOCAL не должен оставаться в пуле: это требует
реального прогона Root. **10000/5 секунд — инженерный admission, не SLA и не
измеренная ёмкость.** Зависание/сбой транспорта и пула требуют отдельной приёмки.

## Native inverse и уточнение EMPTY

В существующем `network_state` единственное изменение —
`статус == "working" and (дней is None or дней > НЕДЕЛЯ)` заменено вызовом
`_mismatch(статус, дней)`, helper возвращает то же выражение. При удалении нового
блока helper/owner и обратной замене одного callsite весь файл byte-for-byte
равен BASE: SHA256 `bd0483f97cadded4f7e5781691d2f94fc4f5978b8cab190db3e5ea0b9effc9ce`.
AST native function после обратной подстановки также совпадает. Пороги,
контекст, запросы, финансовые формулы, native only_problems/attention и native
порядок остались прежними. Этот Source inverse не заменяет регрессионный прогон.

Явный EMPTY verified typed grant сохраняет канонический 403 до domain — policy
не ослаблена. Точный BASE fixture с `installation.all_locations=True` и
`membership.object_scope=[]` — другой случай: live_grant проверяет этот список
на truthiness и оставляет nonempty typed SET, а access.resolve отдельно
проверяет `is not None`, устанавливает Facts.objects=EMPTY. Ожидание нового
теста для этого **допущенного** SQL-empty selector —200 с пустыми E/M. Нельзя
переносить synthetic200 TARGET на произвольный EMPTY verified grant. Сохранены
оба исходных правила; это уточнение Source должно подтвердиться SQL/HTTP у Root.
Ожидания revoked grant и removed membership в тестах — ровно 401
invalid_credentials с canonical invalid_token challenge: live_grant вызывает
InvalidGrantError, verify_access переводит его в denied401. Они не расширены
до произвольного набора 401/403 ради удобства.

## Написанные проверки и что остаётся Root

Матрица передана координатору до правок (`msg_5847d487bb05`). В новом модуле
12 именованных групп, 50 вариантов по AST; pins — в коротком отчёте автора вне
tracked Source. Внутренние циклы не выдаются за собранные тесты.

| Группа | Будущий фактический сценарий |
|---|---|
| NS01 | Authlib user; literal golden, MSK/asOf/current catalog, SQL scalar/MAX и LOCAL 5s/read-only |
| NS02 | Approved SERVICE: SQL credential/client/install/grant с двумя scopes, actual client_credentials token |
| NS03 | Org-hidden и foreign будущие сессии/metadata/деньги не меняют весь публичный ответ |
| NS04 | Допущенный EMPTY selector, owner/network/region E-empty, отсутствие наблюдений/null |
| NS05 | Два scope независимо; EMPTY typed grant, revoked grant, removed membership; до domain |
| NS06 | Amount/client_amount 0→99999999: полный ответ, onlyProblems, порядок и подписанная страница инвариантны |
| NS07 | object/list/number/null/string/oversized region fallback и unknown status |
| NS08 | UTF-8/C страницы: whitespace/case/NFC/NFD, полная summary; unobserved clock между страницами |
| NS09 | Tamper, filters/pageSize, live typed binding, boundary, revoke до даже плохого cursor |
| NS10 | 10001 авторизованных кандидатов; cap до owner/region; тот же набор скрыт от узкого user |
| NS11 | Реальный nondestructive lock session table: deadline, короткий LOCAL SQL timeout, task cancel, reset/reuse |
| NS12 | Строгие query/date/region/boolean/body, streaming body не читает второй chunk |

Pre-import guard нового модуля требует RUN_RUSHYDRO_NETWORK_SQL_TESTS=1 **и**
RUN_RUSHYDRO_PRODUCT_READS_TESTS=1, ROOT_APPROVED_RUSHYDRO_PRODUCT_READS=1,
APP_ENV=test, TEST_DATABASE_URL==DATABASE_URL и точную цель
127.0.0.1:5432 / api_rushydro_reads25_test_20261101 / clearledger, плюс принятый
partner_test_safety. Никакие реальные env/DSN значения автор не смотрел.
Guard выполняется до app/fixture/helper imports. Внешний Root plugin владеет
`rushydro_read_factory`, схемой, проверкой target/role/OID, пулом и disposal.

Из принятого BASE test module импортируются только `read_world`, `wire`,
`bearer`, без старых test functions. Positive business requests используют
действительные user token и новый actual Authlib approved machine token с
двумя scopes; bootstrap JWT не используется для business GET. Отсутствуют
positive verifier/session/SQL/result mocks, fake receipt и schema DDL. Fixed
clock относится лишь к domain context. Fixture DML ограничен синтетическим
миром; строки/изменения восстанавливаются, credential отключается. NS11 держит
табличный lock только в отдельной Root-owned test DB, не в рабочей БД.

Root предстоит: прочитать конкретный diff и immutable decision; проверить
реальные импорты/DTO/route registration; отдельно допустить и прогнать новый
модуль на настоящем PostgreSQL/Authlib внешним plugin без project conftest;
проверить реальные исключения отмены/пул и права на SQL controls; сверить
literal expectations и EMPTY nuance. Принятый READ25 не подтверждает этот путь.
Флаги не включались, конфигурация не менялась и фактический runtime не читался;
default gates остаются off. Старые schema/projection count tests намеренно
не обновлены до приёмки метода Root; Swagger/SDK bundles, миграция потребителей
и независимая проверка их прежних ожиданий отложены. Коммит локальный, без
push/PR/merge, публикации или выпуска.
