# M15: распределённая квота продуктового API, 30.10.2026

Кандидат поверх composed Ledger `28f6b7e2`, ветка `MagLook/harlequin`.
Изменение выключено по умолчанию; на пространства не выпускалось. Root согласовал
алгоритм и ownership через Orca `msg_6261a84c618d`, schema-harness правки через
`msg_884f2679539e`, отдельное SQL-окно через `msg_62cea7427a65`.

## Поведение

Baseline не имеет продуктовой квоты: `access.resolve` выполняет live verifier и
ACL, затем передаёт AccessContext запросам. Formatter сохраняет Retry-After у
generic HTTP429, но его code остаётся `internal_error`. До правок offline baseline:
HTTP profile 12 PASS и OpenAPI HTTP contract 8 PASS.

Теперь все зарегистрированные product GET используют один бюджет для verified
`(company_id UUID, installation_id UUID, client_id OAuth string)` независимо от
grant, user, access token и маршрута. Заголовки компании, адрес клиента и поля
запроса ключ не задают. Квота идёт после прежних live verifier, membership,
module, resource-scope и organization проверок. Исходные policies, identity grants,
tenant predicates и legacy limiter не изменялись. Соединение проверки identity
освобождается до отдельной короткой quota transaction.

Считаются допущенные к зарегистрированной операции запросы, включая последующие
validation422, domain404 и domain500. Unknown route404 и method405 до resolve
не считаются. Verifier и неавторизованный трафик этой квотой не защищены.
Admission commit независим от последующего domain/validation результата.

PostgreSQL хранит одну строку `product_api_budgets` на ключ. INSERT/ON CONFLICT
UPDATE сериализуется по этому ключу, а correlated UPDATE subselect вычисляет
`clock_timestamp()` после получения conflict row lock. Новый интервал начинается
с первого запроса после истечения предыдущего. `used` ограничен `L+1`, переполнение
исключено ограничениями 1..1000000. Различающиеся limit/window у процессов при
активном окне дают503; после истечения окна вступает текущая настройка.
Изменение timeout не переоткрывает окно.

При исчерпании возвращается HTTP429 `application/problem+json`, `code=rate_limited`,
`Retry-After=ceil(reset_at-DBclock)` в целых секундах минимум1, `Cache-Control=no-store`
и server-generated `X-Request-Id`, равный body.requestId. Generic injected429
сохраняет `internal_error`; curated schema содержит оба примера и условия.
Ошибки SQL, checkout, lock/statement timeout и drift активной политики закрывают
доступ безопасным Problem503 `api_unavailable` без текста исключения. Для503
новый Retry-After не выдумывается. Это соответствует форме Problem из
[RFC9457](https://www.rfc-editor.org/rfc/rfc9457.html), запрету кеширования429 из
[RFC6585 §4](https://www.rfc-editor.org/rfc/rfc6585.html#section-4) и delay-seconds
из [RFC9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3).
Атомарность UPSERT опирается на
[PostgreSQL INSERT](https://www.postgresql.org/docs/16/sql-insert.html).

## Настройки и стоимость

| Настройка | Default | Допустимое значение |
|---|---:|---|
| PARTNER_API_BUDGET_ENABLED | false | bool |
| PARTNER_API_BUDGET_LIMIT | 120 | int 1..1000000 |
| PARTNER_API_BUDGET_WINDOW_SECONDS | 60 | int 1..3600 |
| PARTNER_API_BUDGET_TIMEOUT_MS | 1000 | int 50..5000 |

Config принимает десятичные строки из окружения, отклоняет bool/fractional inputs
числовых параметров. Дополнительно frozen Policy строго проверяет границы.
Изменения реальных env/Compose/VM отсутствуют. При disabled нет quota session,
quota SQL, DBclock lookup или cleanup; прежние identity/domain SQL сохраняются.

На enabled запрос: отдельные BEGIN, установка LOCAL statement_timeout/lock_timeout
одним SQL, один UPSERT RETURNING и COMMIT. Отказ429 тоже записывает capped counter;
это WAL/dead-tuple нагрузка, а не бесплатный read. Периодически, с вероятностью
1/128, добавляется DELETE максимум64 строк, чей reset старше24часов, через
индекс reset_at и SELECT LIMIT64 FOR UPDATE SKIP LOCKED. Stable statement_timestamp
делает порог пригодным для index scan. Очистка входит в ту же timeout transaction;
её ошибка тоже приводит к503/rollback. Число просмотренных index entries при
множестве locked rows не ограничено64, время SQL ограничено timeout.
При отсутствии трафика idle строки остаются до следующих sampled вызовов.
Новых workers/таймеров нет. FK на authoritative installation tuple имеет CASCADE,
новых RESTRICT барьеров master-delete не появляется.

Fixed window допускает burst до2L около границы. Ограничивается admission count,
а не число одновременно работающих запросов, bytes или стоимость экспорта.
Требуется одинаковая limit/window конфигурация всех процессов; toggle off/on
не удаляет прежние окна. Сбой связи после server COMMIT может дать503 при уже
израсходованном слоте. Таймауты не являются обещанием максимальной end-to-end
задержки. Production latency/WAL/autovacuum/capacity/SLO не измерялись.

## Проверки и точный статус

| Проверка | Результат |
|---|---|
| Baseline offline HTTP + schema, до изменений | PASS 20 (12+8) |
| New budget config/wiring + inherited HTTP profile | PASS 21 |
| Existing HTTP/OpenAPI после runtime изменений | PASS 20 (12+8) |
| Final aggregate budget + HTTP + OpenAPI | PASS 41, FAIL0, SKIP0, 5.648s |
| Budget + monitoring offline seam | PASS 29 (21+8), FAIL0, SKIP0 |
| Standalone synthetic PostgreSQL suite, final | PASS 12, FAIL0, SKIP0, 7.942s |
| Без DB opt-in: guard и отказ SQL suite | PASS1, SKIP11 |
| Hermetic OpenAPI schema-only adapter и real-module parity | PASS, JSON byte-identical, zero connections; offline не импортирует engine/config |
| Full fresh/old Core/public schema и identity recreation | SKIP здесь, root integration/repeat |
| Независимый root review/repeat | Pending, передано координатору |
| Production/VM/HTTPS/load/SLO | SKIP, не входят в slice |

Final SQL suite использовала только отдельную локальную `api_product_budget_test`
на PostgreSQL33546 с синтетической ролью в выделенном окне. Оснастка создаёт
реальную ProductAPIBudget ORM table и минимальный synthetic contract parent;
это не полный Core bootstrap. Критерии:

- hit/exhaust, capL+1 и reset по DBclock;
- два приложения, 40 конкурентных вызовов: ровно9x200 и31x429;
- три отдельных Python-процесса с независимыми engine/app: 36 вызовов,
  ровно7x200 и29x429 на общем PostgreSQL;
- независимость company/installation/client, новые grant/token на каждый вызов;
- live verifier denial до store и authenticated422 расходует слот;
- disabled успешно работает при скрытой quota table; enabled получает безопасный503;
- удержанный conflict row lock0.45s, expiry во время ожидания:200 и новое окно
  отсчитывается после lock release, а не до ожидания;
- lock timeout и policy drift дают503 без выдачи domain;
- очистка удаляет ровно64 из70 expired строк, пропускает locked row, сохраняет
  active row; EXPLAIN подтверждает использование индекса;
- parent installation DELETE каскадно удаляет budget row;
- Problem429/503, requestId, no-store, Retry-After checked on actual ASGI responses.

Начальный SQL-прогон имел7FAIL: synthetic Domain fixture не возвращал обязательное
`total` поля Page. Исправлен только fixture; последующие два прогона12PASS.
SAWarning лишнего rollback в lock test исправлен; final run без неё.
Логи в owned worktree: `.artifacts/product-budget-db-initial-fixture-failure.log`,
`.artifacts/product-budget-db.log`, `.artifacts/product-budget-db-final.log`,
`.artifacts/product-budget-pure-final.log` (не коммитятся).

После final run обе synthetic fixture tables удалены, public table count0;
engine disposed, три дочерних процесса reaped, финальное соединение закрыто.
База оставлена пустой для независимого repeat. SQL-window release отправлен
координатору `msg_2a519b71a83d`; после release SQL не выполнялся.

Воспроизведение из пустого cwd без `.env`, с PYTHONPATH абсолютным путём server,
тем же virtualenv `/srv/projects/api-modernization-test-env-20261029/.venv/bin/python`:

```sh
python -m unittest tests.test_product_budget_unit tests.test_product_http_profile tests.test_product_openapi_http_contract -v
# Только с отдельным SQL-окном и явной synthetic URL/absolute test UPLOAD_DIR:
RUN_PRODUCT_BUDGET_DB_TESTS=1 python -m unittest tests.test_product_budget_db -v
```

Fullschema harness manifest делает budget model обязательной и проверяет точный
набор таблиц; require_portal и unknown-table fail-closed сохранены. Identity
recreation включает новый FK child в dependency-ordered drop. Hermetic exporter
подключает декларацию модели через schema-only Base без runtime engine.
Root владеет интеграцией, generated wire types/OpenAPI artifacts/package locks,
полной schema matrix, независимым repeat и решением о дальнейшей поставке.


## Независимая проверка интеграционного кандидата

Координатор перенёс patch в21e60c76. В собственном процессе из пустого cwd
с явным абсолютным PYTHONPATH:41offline tests PASS за6.262с; отдельные12
PostgreSQL/HTTP/process tests PASS за7.677с, включая три независимых процесса.
Первый запуск координатора из server без PYTHONPATH дал11PASS/1FAIL: дочерний
script не нашёл app. Это ошибка конфигурации запуска; повтор выполнен ровно
по описанному выше admission, без изменения runtime/test expectations.

Полный отдельный schema suite наapi_schema_final_test, profile=both,
require_portal=1 и обязательной бюджетной моделью:31PASS за301.22с. Проверены
fresh/upgrade/repeat, Core/public, FK/defaults/indexes и настоящие прежние
исходники; роль менялась только DB-local внутри owned synthetic DB с
восстановлением исходного search_path. Это не восстановление рабочего dump.

Типы12операций заново сгенерированы по текущему curated schema; свежие
partner:types:check и consumer compilation PASS. Удалённый CI, нагрузка
и эксплуатационные пороги по-прежнему не подтверждены.
