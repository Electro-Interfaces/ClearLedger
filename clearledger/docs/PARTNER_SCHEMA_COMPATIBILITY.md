# M16: переносимость тестов и совместимость схемы partner identity

29.10.2026. Изменения только в тестах и этом документе. Runtime M10
`f609a3831892993b339289d54fa8586075ef580c` не менялся; review и исправления
runtime в интеграционной ветке принадлежат координатору. Этот результат не
объявляет всю программу API, продуктив или интеграцию M03 принятыми.

## Guard и переносимость

Команды и ограничение окружения ниже заменяют прежнюю локальную команду из
`PARTNER_IDENTITY.md`: без нового явного opt-in identity suite теперь SKIP.

Чистая функция `tests.partner_test_safety.partner_test_safety_error(environ,
flag="RUN_PARTNER_IDENTITY_TESTS")` возвращает безопасную причину отказа либо
`None`. Импорт helper не читает окружение, не импортирует pytest/ORM, не читает
файлы, не обращается к DNS/сети/БД. Другие suites могут передать собственное имя
flag, например `RUN_PRODUCT_API_TESTS`; product tests этим коммитом не меняются.

Перед destructive DB fixtures обязательны все условия:

- Явный opt-in со значением строго `1`. Identity suite использует
  `RUN_PARTNER_IDENTITY_TESTS`, отдельный schema suite — `RUN_PARTNER_SCHEMA_TESTS`.
- Явный `TEST_DATABASE_URL`, схема только `postgresql+asyncpg`, указаны username
  и hostname. `DATABASE_URL` не используется как fallback.
- Имя БД — до 63 символов, строчные ASCII буквы/цифры/подчёркивание, начинается
  буквой и содержит отдельный сегмент `test`: `partner_ci_test`, `test_partner`,
  `api_schema_test`. `elsyplus`, `contest`, `postgres` не подходят.
- Host — `localhost` или числовой loopback, включая `::1`; либо одиночный service
  hostname вида `postgres`/`postgres-16` только при явном `CI=1` или `CI=true`.
  Удалённые числовые IP и DNS-имена с точкой запрещены и при `CI=true`.
- Query/fragment в URL запрещены: ими нельзя переопределить host, порт,
  search_path или другие параметры подключения. Некорректный/нулевой порт запрещён;
  конкретный номер порта не закреплён, стандартный порт без указания допускается.
- `UPLOAD_DIR` задан явно, путь абсолютный, имя каталога содержит `test`.
  Общий/default upload directory не подставляется.

Без opt-in модуль пропускается явно. При opt-in с неподходящим target collection
завершается ошибкой до запроса DB fixtures. `conftest.py` при импорте всё ещё
настраивает engine, но guard не позволяет перейти к удалению схем ради этих
suites. Сам общий conftest и остальные тесты не менялись: guard защищает только
потребителей, которые явно его вызывают.

Это проверка намерения и конфигурации, а не доказательство владения БД: имя с
`test`, локальный IP или CI alias сами по себе не доказывают отсутствие ценных
данных. Выделенная БД и каталог загрузок должны действительно принадлежать
только этому прогону; процессы с одной БД нельзя запускать одновременно.

Schema suite имеет отдельный flag и запускается отдельной командой/CI job:
её fresh/upgrade сценарии пересоздают схемы и несовместимы с живой session-scoped
фикстурой identity/product в том же pytest-процессе. Обычный CI с одним
`RUN_PARTNER_IDENTITY_TESTS=1` не включает schema reset автоматически.

## Что проверяет схема

Проверяются реальные предыдущие исходники:

| Baseline | Полный commit |
|---|---|
| Интеграционная база | `ce94e2bf30c0676208b1d70c5c135fe91d1a23f2` |
| Подтверждённый Core source | `5ce5779b20151a8d04de7d3a1681d1862a80d9dd` |

Test извлекает `clearledger/server` каждого commit через `git archive` во временный
каталог. В архиве не должно быть `.env`; subprocess получает минимальное явно
составленное окружение: синтетическая тестовая БД/секрет, отдельные uploads,
выключенные partner flags. Пользовательские env, keys, seed passwords и настройки
коннекторов не наследуются. Выполняется настоящий старый `database.create_all`;
импорт старого `main` регистрирует именно старые модели. Удаление новых таблиц
из текущей metadata не считается построением исторической схемы.

Порядок для каждого baseline:

1. На выделенной пустой БД старый bootstrap создаёт прежний Core; старые модели
   записывают синтетические company/user/membership/organization/counterparty/
   contract/object/equipment/document kind/document/App/CompanyApp. Повтор старого
   bootstrap завершает его собственные backfills перед снимком.
2. Сохраняется семантический каталог старых таблиц: колонки, типы, nullable,
   defaults/generated/identity, PK/FK/unique/check с validation state, определения
   индексов и пользовательских триггеров.
3. Новый штатный bootstrap добавляет **ровно 12** таблиц `partner_*`. Ни одна
   прежняя таблица не исчезает; её перечисленные определения обязаны совпасть
   с baseline. Повтор нового bootstrap должен оставить весь каталог тем же.
4. Фактические PK/FK/unique/check/indexes новых таблиц сверяются с ORM metadata;
   у индексов проверяются `indisvalid`/`indisready`, у constraints — validation.
5. Новый HTTP registration/activation/installation привязывается к старой компании
   и тем же App/CompanyApp masters. Проверяются пять типизированных SET resource
   profiles по старым объекту, оборудованию, контрагенту, договору и документу;
   установка сама не создаёт пользовательский grant. Прежний native App/CompanyApp
   остаётся включённым и связанным с прежними UUID.
6. Тот же старый subprocess снова выполняет свой bootstrap поверх новой схемы,
   читает прежние модели и пишет object/contract/document/App через старый ORM.
   Старый HTTP выполняет auth/me, список контрагентов, PATCH прежнего контрагента
   и POST нового. Текущий код читает сохранённые изменения; partner installation
   и регистрация переживают старый bootstrap. Каталог остаётся тем же.

Отдельный сценарий создаёт схему текущим bootstrap с нуля и проверяет повтор.
В identity suite прежний тест назван `test_partner_table_recreation_and_repeat_bootstrap_preserve_core`:
он проверяет только пересоздание собственных новых таблиц и сохранение Core rows;
исторический upgrade доказывает новый subprocess suite.

M10 не добавляет `ALTER` прежних таблиц и не вводит migration runner. Штатный
bootstrap уже содержит исторические идемпотентные ALTER/DROP/CREATE/backfill
операции; этот тест их не отключает. Каталог сравнивается по определениям, а не
по OID и не по отсутствию SQL ALTER statements. Проверка не является аудитом
всех старых migrations, измерением lock time на большом объёме или проверкой
реального customer dump.

## Переносимые команды CI

Рабочая папка `clearledger/server`, отдельная venv с текущими
`requirements-test.txt`; новых runtime dependencies/upgrades нет. CI checkout
должен содержать оба baseline commit (`fetch-depth: 0` либо явное получение
нужных объектов до теста). Отсутствие baseline — FAIL, не молчаливый SKIP.

`TEST_DATABASE_URL` предоставляет CI для отдельной synthetic DB. Для service
hostname задаётся `CI=true`; для loopback это не требуется. Ни имя БД, ни порт
не зашиты в команды:

```sh
# TEST_DATABASE_URL уже явно задан CI для своей БД с сегментом test.
export CI=true
export UPLOAD_DIR="${RUNNER_TEMP:-/tmp}/partner-ci-test-uploads"
RUN_PARTNER_IDENTITY_TESTS=1 ../../.venv/bin/python -m pytest \
  tests/test_partner_identity.py -q

# Отдельный процесс/job и своя свободная БД; не объединять suites одной командой.
RUN_PARTNER_SCHEMA_TESTS=1 ../../.venv/bin/python -m pytest \
  tests/test_partner_schema_compatibility.py -q \
  --junitxml=partner-schema-test-results.xml -o junit_family=xunit1
```

Для product suite координатор может использовать тот же pure helper с
`flag="RUN_PRODUCT_API_TESTS"`; этот документ не подменяет его admission policy.
Реальный CI pipeline и сетевое разрешение CI service alias этим локальным
прогоном не подтверждаются: alias acceptance проверяется чистыми guard cases.

## Локальная проверка и границы

Для этой задачи создана только собственная `api_schema_test` в локальном
`api-modernization-test-20261029` (PostgreSQL 16). Обе команды выполнялись
последовательно на ней, uploads — `/tmp/partner-schema-test-uploads`.
Занятая координатором `api_identity_test`, `api_integrated_test`, VM, customer DB,
customer dumps и продуктивные `.env` не использовались.

Итоговый schema suite: **25 PASS**, 153.68 с, Python 3.13.15. На каждом baseline
было **325** таблиц Core; новый bootstrap дал **337** (добавлены ровно 12), повтор
и запуск прежнего bootstrap/HTTP/ORM оставили определения прежних таблиц теми же.
Числа и полные baseline SHA записываются также в JUnit properties. Проверены
PK/FK/unique/check/indexes новых таблиц, validation state и новая регистрация
с пятью типизированными ресурсными профилями поверх старых masters.

Итоговый portable identity suite после переноса guard в общий helper:
**52 PASS**, 64.98 с, на собственной `api_schema_test` с явным opt-in. В нём нет
привязки к имени этой БД или номеру порта. `compileall` трёх тестовых модулей и
`git diff --check` — PASS; runtime diff относительно `f609a383` отсутствует.

Два настоящих negative pytest subprocess используют только заведомо недоступный loopback
порт и запрещённое имя БД: opt-out даёт SKIP, unsafe opt-in — collection ERROR;
проверка guard не пытается подключаться к существующей БД. Отдельный запуск
schema suite только с identity opt-in дал **1 SKIP**, exit 5 за 0.06 с, подтвердив
независимость flags до попытки подключения/запроса fixture.

Профиль этой проверки — `public`/`edge` штатного test bootstrap. Внешнее
provisioning `edge.item`, отдельный production search_path `core`, большие
данные и полная матрица старых бизнес-операций не проверялись. Привязка CI service
host проверена чистыми положительными/отрицательными guard cases; реальный CI
runner и его сеть здесь не запускались.

## Откат

Выключение `partner_oauth_enabled` и независимого `partner_api_enabled` закрывает
новые возможности на runtime boundary; таблицы и записи остаются. Feature off
сам по себе не удаляет и не отзывает persisted grants/families: перед повторным
включением нужно проверить их состояние, срок и при необходимости явно отозвать.
Это временное закрытие входа, а не очистка истории доступа.

Возврат предыдущего Core binary оставляет additive schema на месте. Тесты
подтверждают перечисленные старые HTTP/ORM операции и повтор его bootstrap;
отдельный destructive downgrade/DROP partner tables не нужен и не предусмотрен.
Полный rollback реального выпуска, все legacy endpoints/процессы, Support runtime,
нагрузка, browser, SDK и внешний OIDC conformance этим результатом не приняты.
