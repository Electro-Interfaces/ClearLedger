# Статус и зарядные агрегаты одного объекта, M08/M09

Slice: `GET /api/v1/objects/{objectId}/monitoring`. Это кандидат внешнего readonly
контракта для `ServiceLocation` компании с `profile_id=energy`. Работа всего
мониторинга и готовность внешнего запуска этим пакетом не заявляются.

## Доступ

Нужны **оба** явно согласованных scope: `objects:read` и `monitoring:read`.
Каталог M10 добавляет описание нового права; пользователь может согласовать его
при текущем полном доступе (`admin`, superadmin с членством, `modules=None`) либо
при `ops`, `ops:ops_state`, `ops:ops_reliability`. `ops:ops_overview` и произвольный
`ops:*` его не дают. `objects:read` остаётся отдельным обязательным правом.
Старые allowlists клиента, установки и grants не дополняются.

Используются настоящий delegated Code+PKCE M10 либо отдельно утверждённый
confidential machine grant. Core Bearer, SSO handoff, ID token, cookie портала
документации и token в query не аутентифицируют продуктовый endpoint. Секрет
machine client предназначен только серверному потребителю, не браузеру.

Canonical M10 `live_grant` повторно проверяет client/install/grant/family/member
и текущие права на каждом GET. Затем `Query.detail("objects", objectId)` проверяет
company, typed `objects` grant, текущий object scope члена и связи с его собственной
организацией через location-scoped договор. Лишь после успешного detail вызываются
session helpers. Чужой/недоступный/отсутствующий объект и неподходящий профиль
дают 404; EMPTY resource grant даёт 403. Неавторизованный объект не запускает
агрегацию сессий.

## Время и определения

Query допускает только `days` (по умолчанию 90, диапазон 1..366) и `asOf`
(необязательная календарная дата строго `YYYY-MM-DD`). `cursor`, `q`, company,
location и прочие неизвестные параметры дают 422. Пагинации у одного агрегата нет.

Граница данных — `max(started_at)` **только разрешённого объекта и его компании**,
а не общая дата компании. События других объектов не двигают окно или lag.
`monitor_context` определяет `asOf`: эта граница либо более ранний конец выбранного
дня `23:59:59.999999` МСК. При отсутствии данных граница/lag равны null, точка
наблюдения берётся из текущего времени с тем же ограничением выбранного дня.

Окно — включительный интервал `[asOf - days × 24 часа, asOf]`, не набор целых
календарных дней. Например, при границе `2026-10-17T12:00:00+03:00`, days=2
начало равно `2026-10-15T12:00:00+03:00`. Все wire timestamps имеют `+03:00`;
`window.timeZone=Europe/Moscow`, `window.interval=inclusive`.

`dataThrough` — последняя наблюдавшаяся сессия объекта во всём доступном журнале,
она может быть позднее исторического `asOf`. Это граница наблюдений, не гарантия
полноты загрузки. `dataLagHours` — реальная давность этой границы относительно
текущего времени; не давность выбранного исторического дня. `lastSeenAt` — последняя
попытка объекта не позднее `asOf`, включая попытки раньше начала окна.

Визит определяется существующим `visit_summary`: одинаковый `visit_key` в рамках
объекта; при отсутствующем ключе каждая сессия — отдельный визит. В рамках окна визит
успешен, если **хотя бы одна попытка имеет energy_kwh > 0**, независимо от текста
CPO result и materialized `visit_charged`. Фильтр location применяется в SQL
`attempts` до GROUP BY/count. Суммируется raw энергия, затем существующий
`decimal_round` округляет до 0.1 кВт·ч (ROUND_HALF_UP). Новых формул успеха нет.

Состав объектов и `operational_status` текущие, даже при историческом asOf;
`provenance.catalogMode=current` и snapshotNote говорят об этом явно. Незнакомый
статус возвращается как `unknown`, сырой vendor status не передаётся.

Ответ содержит только `pointId`, `status`, bounded `window`, `totals`
(sessions/visits/successfulVisits/unsuccessfulVisits/energyKwh), `lastSeenAt` и
`provenance`. Нет имён/телефонов клиентов, session userID, платежей, финансов,
заявок, raw, аудита или состояния company DB. Финансы и tickets остаются GAP:
потребуются отдельные scopes и утверждённые проекции.

## Подключение на синтетике

По умолчанию существующие partner OAuth/API flags выключены. Root wiring и
конфигурация не меняются этим slice. Администратор синтетического пространства
регистрирует клиента с указанными двумя business scopes (и `openid` для delegated
Code+PKCE), включает клиента и явно утверждает установку с typed `objects` scope
`SET` и ID разрешённой точки. Пользователь проходит `/api/oauth2/authorize` с
S256 challenge, consent и одноразовый exchange `/api/oauth2/token` с verifier.
Используйте M10 quickstart; Core token остаётся только в Core transport.

После получения partner access token запрос потребителя:

```http
GET /api/v1/objects/synthetic-point/monitoring?days=2&asOf=2026-10-16 HTTP/1.1
Authorization: Bearer <partner access token in memory>
```

Curated OpenAPI отражает `getObjectMonitoring`, оба security scopes, query,
DTO, Problem responses и runtime registry. Нового публичного raw spec endpoint
нет; UI/spec/assets документации остаются за самостоятельным M11 docs guard.
GET не материализует данные и не делает business DML.

## Проверки и воспроизведение

Pure checks не подключаются к БД и не требуют startup:

```sh
cd clearledger/server
PYTHONPATH=. /path/to/venv/bin/python -m unittest \
  tests.test_product_monitoring_unit tests.test_ops_monitor_unit -v
/path/to/venv/bin/python -m pytest tests/test_partner_monitoring_scope.py -q
```

HTTP/SQL acceptance **opt-in**. Перед destructive conftest setup общий pure guard
`tests.partner_test_safety` требует явные flag/TEST_DATABASE_URL/absolute test
UPLOAD_DIR, loopback либо CI service hostname и отдельное имя БД с сегментом test.
Нет hardcoded host/DB skips; CI задаёт свои изолированные значения. DATABASE_URL
не заменяет TEST_DATABASE_URL. Только владелец выделенной БД запускает команды:

```sh
RUN_MONITORING_SQL_TESTS=1 \
TEST_DATABASE_URL=postgresql+asyncpg://test_user:test_password@localhost:5432/monitoring_ci_test \
UPLOAD_DIR=/absolute/path/monitoring_test_uploads \
/path/to/venv/bin/python -m pytest \
  tests/test_product_monitoring.py tests/test_ops_monitor_scope.py -q
```

Фактический локальный прогон использует только `api_monitoring_test` контейнера
`api-modernization-test-20261029` на 127.0.0.1:33546 с синтетической ролью
clearledger. Другие DB и параметры кластера не меняются. Каждый прогон conftest
удаляет тестовые схемы, создаёт их и seed, затем удаляет при teardown.

Acceptance вызывает реальные локальные ASGI endpoints, M10 login/Code+PKCE,
согласие, JWT verification, machine credentials/grant и SQL. HTTP responses и
verifier не подменяются; только внешняя доставка email/notify отключена. Это
серверный HTTP/SQL acceptance, браузерный end-to-end этим пакетом не заявляется.
Проверяются scopes, revoke, member/own-org constraints, отсутствие PII/DML,
чужие данные/границы, EMPTY, профиль, неизвестные query, округление/окно и старый
company-wide helper contract. PostgreSQL параметры и БД не входят в исходники
как условие skip.

## Фактический результат проверки 30.10.2026

Основа — integration `9a4a5aee`; dependency root `fee09ac3` перенесена отдельным
cherry-pick `c0f94af2` (только scope catalog/mapping и его pure tests).

- Первый прогон `test_product_monitoring.py` + `test_ops_monitor_scope.py`: **38 PASS**.
- После замены сценария пустого объекта на настоящий approve ALL installation:
  изменённый HTTP/SQL тест + `test_product_monitoring_unit.py`,
  `test_ops_monitor_unit.py`, `test_partner_monitoring_scope.py`,
  `test_api_contracts_context.py`, `test_api_contracts_http.py`: **115 PASS,
  10 subtests PASS**. Одно предупреждение существующего Starlette/AnyIO API
  (`BlockingPortal` alias deprecated).
- Отдельный portable unittest до SQL: **10 PASS** (текущий набор затем расширен
  guard/defaultoff проверками и включён в финальный pytest).
- Python compileall/AST и `git diff --check`: PASS.

Frontend/config/main/grant models и зарегистрированный identity protocol не
меняются. TypeScript typecheck не запускался: этот slice меняет только Python и
документацию. Живых API, VM, рабочих данных и credentials в проверках нет; выпуска
и PR нет. SQL окно освобождено после завершения всех pytest/teardown.
