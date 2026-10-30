# Совместимость lifecycle PolicyRouter, 30.10.2026

Статус: one-file fix реализован после actual traceback и явного допуска ROOT;
подготовлен source-only кандидат для review, worker ничего не исполнял.
Рабочая ветка `agent/api-lifespan-compatibility-20261030` создана в выделенном
дереве `api-conf-context-20261030` от exact integration base
`850004b35e261b8d9115cc44c414a88d79c3e98e`.
M00–M19 остаются открыты; документ не подтверждает готовность обновления зависимостей.

## Наблюдения и границы вывода

Прямое чтение установленного кода, без импорта пакетов:

| Окружение | FastAPI | Starlette | Выполнение событий по умолчанию |
| --- | --- | --- | --- |
| `/srv/projects/api-modernization-test-env-20261029/.venv` | 0.115.6 | 0.41.3 | Starlette `routing.py:564–578`: связанный с router context вызывает public startup/shutdown |
| `/srv/projects/api-modernization-upgrade-test-env-20261030/.venv` | 0.133.0 | 1.3.1 | FastAPI `routing.py:211–233,990–1030`: собственный context вызывает методы, которыми владеет framework; у Starlette публичные startup/shutdown удалены |

Версии прочитаны из `*.dist-info/METADATA`, код из `lib/python3.13/site-packages`.
`create_policy_app` (`server/app/api_contracts/routing.py:273–292`) напрямую вызывает
`app.router.startup()` и `shutdown()`. Первоначальная гипотеза подтверждена
фактическим первым traceback, переданным ROOT 30.10.2026 в `msg_ae1da7fe11ad`.
Прерванный полный прогон, ранние точки и последующие HTTP failures не считаются
принятыми результатами и сами по себе не доказывают единственную причину.

ROOT diagnostic v4 собрал 56 HTTP случаев и выполнил первый:
`test_missing_invalid_wrong_kind_tenant_scope_resource_or_action_deny_before_handler[None-401]`.
Он завершился FAIL за 0.96 секунды, pytest exit 1. Цепочка:
`TestClient.__enter__ → Starlette.lifespan → FastAPI.merged_lifespan → routing.py:280`.
Наблюдаемое исключение: `AttributeError: 'PolicyRouter' object has no attribute 'startup'`.
Это подтверждает root cause данного первого сбоя; остальные 55 случаев этим
диагностическим запуском не проверены. Полный набор 376 не принят.

Локальное evidence ROOT, прочитаны только ограниченный traceback и имя случая:
`/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/backend-upgrade-functional-execution-20261030-attempt3/evidence/run.log`.
Соседние `outcome-checkpoint.json`, `boundary-proof.json`, `junit.xml` и
`supervisor-proof.json` принадлежат ROOT/DEP. По сообщению ROOT: forbidden attempts 0,
child reaped, штатная очистка disposable DB подтверждена; эти SQL проверки worker
не выполнял и не переносит их статус на новые no-SQL случаи.

Первичный документ, уже прочитанный ROOT:
[FastAPI: lifespan events](https://fastapi.tiangolo.com/advanced/events/).
Новых сетевых запросов worker не выполнял.

## Реализованная минимальная правка

Только `create_policy_app`: создать новый PolicyRouter без custom lifespan,
сохранить его публичный `lifespan_context`, затем установить обёртку,
которая сначала проверяет весь `policy_registry(app)`, после этого входит в
сохранённый context через `async with` и передаёт его state наружу без изменения.
Обёртка устанавливается до любого include_router, чтобы FastAPI сливал contexts
в обычном порядке. Не обращаться к private framework methods, не копировать
executor sync/async событий и не выполнять списки обработчиков вручную.

Сохранённый default обязан принадлежать новому PolicyRouter. Сохранение default
временного `FastAPI.router` потеряет обработчики, зарегистрированные позднее на
PolicyRouter. Сам временный router фабрики не получает пользовательских callbacks:
сигнатура фабрики принимает только resolver/title/version; замену router не расширяем.
Существующие hooks, добавленные на возвращённый app, принадлежат новому router.

`PolicyRouter.include_router` уже переносит исходный `router.lifespan_context`
через proxy, а не копирует оба списка событий. В ветке с Mount маршруты идут
по прежнему порядку, после чего источник lifecycle сливается один раз.
Обе версии FastAPI `_merge_lifespan_context` входят сначала в original, затем
в nested, объединяют state с приоритетом original, выходят в обратном порядке.
Mount проверяется рекурсивно реестром и сохраняет HTTP guard; lifecycle
смонтированного app автоматически не запускается родителем. Эти правила не меняются.

## Подготовленная focused матрица

Новый `server/tests/test_policy_lifespan_compatibility.py`: 12 actual TestClient
ASGI lifespan случаев с буквальными ожидаемыми событиями, ответами и state:

- реестр перед root hooks, sync/async startup/shutdown ровно один раз, повторный lifespan;
- include_router с обычным default и с Mount, отсутствие неявного startup дочернего mount;
- вложенные custom lifespans, state/precedence, обратный cleanup, игнорирование event hooks при custom lifespan;
- поздняя порча root/mounted routes и metadata: ни одного startup/shutdown side effect;
- root startup failure без искусственного shutdown, custom enter/exit failures с cleanup root;
- shutdown exception без повтора и без последующих обработчиков;
- действующий resource guard, DI и OpenAPI внутри настоящего lifecycle.

Существующий `test_api_contracts_http.py` сохранён побайтово; его 56 случаев
проверяют ROOT и DEP worker отдельно. Набор 376 здесь не дублируется.

## Допуск и доказательства

`server/tests/policy_lifespan_compatibility_approved.py` пока не исполнять.
До любого pytest/app import он проверяет точный путь/branch/commit/base ancestry,
полные деревья app/tests/schema (исключая собственный runner, проверяемый отдельным
ROOT SHA), support files, два точных venv и отдельный digest inventories.
Требуются изолированный Python 3.13 `-I -B`, ROOT opt-in, чистое allowlisted env,
фактический HOME, две разные новые пустые owned 0700 директории с `lifespan-test`
в имени. Runner пишет инвентарь, SHA, collection, call/setup/teardown outcomes,
boundary attempts и JUnit в evidence. Outer ROOT supervisor должен ограничить
wall time и размер вывода; runner дополнительно ограничен 180 секундами.

БД этим случаям не нужна: DATABASE_URL/TEST_DATABASE_URL и прочие настройки
не допускаются в окружении, импорты SQLAlchemy/драйверов/engine/assembly/config,
dotenv, отправителей и app.services запрещены до pytest collection.
Все network connect/DNS/listen/sendto и новые процессы после gate запрещены;
обычные httpx transports тоже блокируются. TestClient обращается только к ASGI
в памяти. Общий `conftest.py` не загружается (`--noconftest`), autoload plugins
отключён. Runner не создаёт/не удаляет схемы и не требует PostgreSQL.

На текущем этапе выполнены только AST parse и compile в памяти новых файлов.
pytest/collect/TestClient/app imports/SQL/установка зависимостей/контейнеры не запускались.
AST всего `routing.py` вне `create_policy_app` идентичен exact base; старый HTTP-файл
побайтово идентичен base (SHA256 `f2e14cc84bfc878dd2f12d0174cbb2276f5a0cc6f87746861e45baf1d053edc6`).
После source freeze и русского коммита/push: повторный review ROOT,
затем два отдельных запуска ROOT old/new.
После actual evidence допустимо только обновление отчёта; любые изменения source
после freeze требуют нового review и результатов. Merge/deploy не поручены.

## Frozen source proposal для ROOT

| Состав | Количество файлов | SHA256 |
| --- | ---: | --- |
| app | 492 | `120b78d9052a7a4dc182095638802cd0627443233e50e67f3fd3011a37a98862` |
| tests, без runner | 344 | `1d0852d8ad15522a59b54e16f5c7fafcdd4e5e0f52592cae7c55e5664d027f7d` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |
| runner | 1 | `005cc35ac54a7bdfd2fffa321407d9bf7e4d98fb183ba42d7a8fd8fb2f49d926` |
| old inventory | 79 distributions + 2 routing sources | `e77307d05df3dd628e45dc8062b16a7f309f241eacb9e9a810e2d6a6c9f3e65f` |
| new inventory | 77 distributions + 2 routing sources | `9349a25d76e9b5df09325d74901254f10ed543d6fe8607039759b401281c3a83` |

Manifest rows: `[server-relative path, file SHA256]`, сортировка по пути,
JSON `separators=(",", ":")`, затем SHA256; inventories используют `sort_keys=True`.
ROOT задаёт `LIFESPAN_RUNNER_SHA256` из таблицы и `LIFESPAN_SOURCE_HEAD` из
reviewed frozen commit, `LIFESPAN_RUNTIME=old` либо `new`.
Каждому запуску нужны новые `LIFESPAN_EMPTY_CWD`, `LIFESPAN_EVIDENCE_DIR`;
не использовать evidence или пустые каталоги другого запуска.
Opt-in: `RUN_POLICY_LIFESPAN_COMPATIBILITY=1`,
`ROOT_APPROVED_POLICY_LIFESPAN_COMPATIBILITY=1`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONDONTWRITEBYTECODE=1`.
Интерпретатор: точный `.venv/bin/python -I -B`, один аргумент runner
`--execute-approved-policy-lifespan-compatibility`, cwd равен EMPTY_CWD.
Кроме указанных gate keys allowlist допускает только HOME/PATH/LANG/LC_ALL.
Без opt-in новый тестовый модуль пропускается до FastAPI/app imports, как другие
ROOT-only suites; при approved runner любой SKIP/неполный набор означает FAIL.

Фактические результаты focused old/new: **PENDING ROOT**, PASS не заявлен.
