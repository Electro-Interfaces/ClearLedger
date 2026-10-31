# Общий владелец доступа к чатам, M04-P3 · 30.10.2026

Реализован `services/chat_access.py`: async `is_insider`, `assert_participant`,
`history_from` и foreign-access audit с одним throttle. База:
`bdbd8ccb3798316cd4b6794bdc99ecf10af4101a`, ветка
`agent/api-chat-access-owner-20261030`. Решение согласовано ROOT:
`msg_51363e5feb29` → `msg_a03ee022b141`.

`assert_participant` может вызвать `log_audit`: добавление AuditEvent и
планирование уведомления остаются ожидаемыми эффектами. Сервис сам не вызывает
flush/commit; ими владеет прежний caller. Запросы до отказа, тексты 403/404,
selected company, primary-company вместо membership для insider, task/ticket ACL,
nullable history cutoff и source не изменены. Существующий task_access используется
по месту вызова, без копии его политики. Таблицы, продукты, flags и отправители
сообщений не изменены.

## Привязки и совместимость

| Исходный edge | После извлечения |
|---|---|
| E06 context_chats.ensure_room → _assert_participant | Прямой import chat_access.assert_participant |
| E07 context_chats.ensure_room → _is_insider | Прямой import chat_access.is_insider |
| E17 management_local._chats → _assert_participant | Сохранён late-bound router adapter по решению ROOT |
| E20 ProjectsContext.resolve → _is_insider | Прямой import chat_access.is_insider |
| E29 work_links.origin → _history_from | Прямой import chat_access.history_from |

Числа E относятся к исходному SERVICE_ROUTER_BOUNDARIES, а не нумерации нового
снимка. Остаток management `_chat_scope` + `_assert_participant` намеренный:
`test_management_runtime_compat` требует original runtime hooks, в том числе
удалённый/отказавший `_chat_scope` и source error/forbidden без утечки диагностики.
Не заменять их на chat_scope_of напрямую. Старые imports в intake_router,
work_contexts_router, project_workspace_router и локальные вызовы chat_router
идут через сохранённые адаптеры; эти файлы вне состава данной правки.

Карта сохранённых hooks:

- `_assert_participant`: при каждом вызове передаёт текущие async `_company_of`,
  `_chat_scope`, `_audit_foreign_access` общему owner.
- `_is_insider`, `_history_from`: async wrappers, делегируют owner при вызове.
- `_audit_foreign_access`: делегирует owner с текущим router `log_audit`,
  `_FOREIGN_SEEN`, `_FOREIGN_QUIET`; `_FOREIGN_SEEN is chat_access.FOREIGN_SEEN`,
  clear действует для обоих путей. Default owner использует тот же throttle.
- task_access.assert_task_room и ticket_communications.assert_staff_room остаются
  локальными service imports, их ACL не заменены callbacks.

## Проверка исходников

Выполнены только чтение/Git/AST/compile без импорта приложения. Старые тесты не
изменены. AST тел `is_insider` и `history_from` совпадает с базой; для
`assert_participant` совпадает после нормализации трёх имён callbacks и удаления
трёх строк выбора default callbacks. `git diff --check` PASS.

Исходный inventory tool на базовом SHA: 492 файла, 482 Python parsed,
0 parse_unknown, 23 service→router bindings / 19 import sites. Локальные
before/after evidence: `.artifacts/chat-access-owner-20261030/`, исходники
приложения не исполняются. Syntactic call candidates сохраняют локальные и
условные imports; это не runtime call graph, computed loaders/monkeypatch
разбираются отдельной картой hooks и тестами.

После извлечения тем же анализатором: 493 файла / 483 Python parsed,
0 parse_unknown, 19 service→router bindings / 16 import sites. Удалены четыре
bindings в трёх import sites, два management chat hooks остаются. AST обход всех
app-модулей дал 51 syntactic policy call candidate (включая три адаптера и audit).
Полный список scopes/targets/lines в `after/policy-call-candidates.json`;
краткая карта замыкания:

| Caller | Сохранённые вызовы/новый target |
|---|---|
| `routers/chat_router.py` | `app.routers.chat_router._assert_participant` × 28 |
| `routers/chat_router.py` | `app.routers.chat_router._history_from` × 5 |
| `routers/chat_router.py` | `app.routers.chat_router._is_insider` × 2 |
| `routers/chat_router.py` | `app.services.chat_access.assert_participant` × 1 |
| `routers/chat_router.py` | `app.services.chat_access.audit_foreign_access` × 1 |
| `routers/chat_router.py` | `app.services.chat_access.history_from` × 1 |
| `routers/chat_router.py` | `app.services.chat_access.is_insider` × 1 |
| `routers/intake_router.py` | `app.routers.chat_router._assert_participant` × 1 |
| `routers/intake_router.py` | `app.routers.chat_router._history_from` × 1 |
| `routers/project_workspace_router.py` | `app.routers.chat_router._assert_participant` × 1 |
| `routers/project_workspace_router.py` | `app.routers.chat_router._history_from` × 1 |
| `routers/work_contexts_router.py` | `app.routers.chat_router._assert_participant` × 1 |
| `routers/work_contexts_router.py` | `app.routers.chat_router._history_from` × 1 |
| `services/context_chats.py` | `app.services.chat_access.assert_participant` × 1 |
| `services/context_chats.py` | `app.services.chat_access.is_insider` × 2 |
| `services/management_local.py` | `app.routers.chat_router._assert_participant` × 1 |
| `services/project_work_context.py` | `app.services.chat_access.is_insider` × 1 |
| `services/work_links.py` | `app.services.chat_access.history_from` × 1 |

## Frozen proposal V3: ROOT runtime gate

Workers этот runner не запускают. ROOT сначала проверяет патч и замороженные
источники, затем сам создаёт выделенный PostgreSQL с синтетическими данными и
четыре новые раздельные каталога mode 0700. Никаких installer/codegen/dependency
updates не требуется. Старые ignored artifacts сохраняются.

| Источник относительно server | SHA-256 V3 |
|---|---|
| `app/services/chat_access.py` | `971bb3589969a35d9df2ba90c29d7895396a4d3d1a19926f57c4ca4ebec2cbc4` |
| `app/routers/chat_router.py` | `5a7d046cfd958a6c17ee7bfc0f95579d5934224621c5e8a89b1bb367ae91e58e` |
| `app/services/context_chats.py` | `36282895660680de93e68f4c265c39fcca56155dd00db81120b40b19ff8d7769` |
| `app/services/project_work_context.py` | `ccb24382e3ec3d279ad8a7e0b0e540d3c1408560ca7e0810bfd47f732880abb9` |
| `app/services/work_links.py` | `79fa08974b5813d29220e5278f0da2ada3e894d4bb8aabcf5e4844466ea58a6b` |
| `tests/test_chat_access_owner.py` | `1ac76909f0f142a656f759d56fd7b6f5c4e86d73e5ec012ebc83f31e2150f66c` |
| `tests/chat_access_owner_approved.py` | `e73078ee529fa60e1cb5fc5190a46990c70c15e99f7b87d117415a05cf00fada` |

Full-tree digest runner (JSON manifest: relative path + SHA256, сортировка Path;
исключаются только __pycache__ и сам runner в tests):

- app: 493 файла, `25069b2b560942622f3e3d1ca15e5eca6bcb64dd361b043390b30a0498406663`.
- tests без runner: 352 файла, `16019dfc1768df2991b85f49545db6e97ce54d12e81a24f70ea8dfebaea28046`.
- schema_migrations: 16 файлов, `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d`.
- requirements.txt: `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0`;
  pytest.ini: `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601`.

V1 отозван до запуска: V2 задаёт synthetic SEED_SUPERADMIN_* и пустой
ECOSYSTEM_COMPANIES до импорта cached Settings в delivery capture hook.
Runtime patch/tests и их SHA не изменены.

V2 также не исполнялся: review ROOT `msg_0d08170c3169` потребовал принятые guards.
V1/V2 runner bytes сохранены в `.artifacts/chat-access-owner-20261030/proposals/`
(SHA V1 `cee2f2ca63e54f36110952c5fa79f15325071c5695368ccd8fba6298290537ff`,
V2 `4ca0d26a717afbc3b114b99ac9858a64927c04116f2318733b54db7ea1a0bfd6`).
V3 использует exact Python3.13.7/glibc2.36 и inventory 61 runtime + 16 tools из
принятого R1, без установки/изменения зависимостей. До app/pytest imports:
узкая suppression/restore socket.has_ipv6 только для aiohttp, aiosmtplib, httpx,
pywebpush, requests; socket.bind всегда запрещён. Принятые main/R1 buffers-only
PG sendmsg guard и 16 pure metadata controls проверяют native fd/peer/type/proto,
weak object ownership и context capability; ancillary/flags/address не передаются.
Включены exact asyncpg target и SQL statement/lock/idle/command timeouts,
HTTP transport deny, запрет .env/secret paths и записей вне своих test roots.
Источники guards: product_contract_objects_approved.py SHA
`4f48de90e1a5b69bb03a98c4a6b7d5dfe7d35670d8740e22fb810a4e81bc1a82`,
backend_upgrade_main_approved.py SHA
`4ea9370970cbe79182efca907791c01ad2ea47f63b8137f3ce2003644baf24cd`.
Функции pure metadata controls скопированы без изменения AST.

Точные selection/counts зашиты в runner: 34 функции, 90 cases, включая 33 новых
negative/positive goldens, 6 chat boundaries, 3 room subject, 2 scope directory,
9 management runtime compatibility, 1 management chat ACL, 7 context/project
flow cases, 29 task room ACL cases. Нельзя расширять selection при запуске.

Предлагаемые ROOT-only argv/env (HOME остаётся фактическим /home/mag; DATABASE_URL
и TEST_DATABASE_URL равны; все credentials вымышленные, только для disposable DB).
ROOT зафиксировал port 33546 и synthetic clearledger/api_test_only;
runner проверяет exact host/port/database/user/password, inventory exact77.

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/chat-access-owner-20261030/root-test-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=chat-access-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_CHAT_ACCESS_OWNER_TESTS=1 RUN_CHAT_ACCESS_OWNER_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_chat_access_owner_test_20261030 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_chat_access_owner_test_20261030 \
  CHAT_ACCESS_PG_PORT=33546 \
  CHAT_ACCESS_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/chat-access-owner-20261030/root-test-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/chat-access-owner-20261030/root-test-upload \
  CHAT_ACCESS_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/chat-access-owner-20261030/root-test-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/chat-access-owner-20261030/root-test-scratch \
  CHAT_ACCESS_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/chat-access-owner-20261030/root-test-scratch \
  CHAT_ACCESS_RUNNER_SHA256=e73078ee529fa60e1cb5fc5190a46990c70c15e99f7b87d117415a05cf00fada \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/chat_access_owner_approved.py --execute-approved-chat-access-owner-tests
```

ROOT outer: CPU600/AS3GiB/FD256/FSIZE2MiB/wall650/scratch128MiB.
Runner: alarm600, bounded scratch128MiB с lstat anchors; <=4000 source files/tree, <=8 MiB/blob, <=64 MiB/tree,
<=4000 capture events, <=1 MiB JSON evidence. До pytest/conftest установлены
network/process audit gate и capture stubs mail/push/notify/global WS; разрешён
только указанный числовой loopback PostgreSQL port и buffers-only sendmsg
на собственном подключённом native PG socket. Pytest --capture=sys и log-file
направлены в evidence; basetemp/TMPDIR — в свой scratch. Источники и inventory
повторно сверяются после прогона. Новые ChatConnectionManager
в старом ACL-тесте остаются настоящими локальными объектами. Любая заблокированная
сетевая/процессная попытка означает FAIL; main lifespan/jobs не запускаются.

conftest удаляет/создаёт public/edge исключительно в выделенной DB, выполняет
штатный create_all/seed, после тестов drain_application_tasks и удаляет схемы.
ROOT удаляет выделенные DB/container и свои временные cwd/upload/scratch; сохраняет
JSON/XML receipt и подтверждает cleanup. Workers SQL/fixtures не исполняют.

## ROOT receipts и ограничения

ROOT receipt `msg_d3d3d2aeadda`: **90/90 PASS**, pytest 39.86 s,
outer 56.6867 s, exit 0, child reaped. ROOT отдельно прочитал JUnit:
source_after=true, inventory=77, все 16 metadata controls PASS,
forbidden=0, delivery capture установлен до conftest. Максимум locks=64;
после штатного teardown — 0 relations / 0 clients, после ROOT DROP database
exists=0. Runtime, SQL и очистку выполнял ROOT; worker их не запускал.

Evidence в дереве ROOT:
`.artifacts/root-chat-access-review-20261030/actual90/process.json`, `run.log`,
`r1-evidence-test/chat-access-boundary.json`, `chat-access.xml`.
V3 runner и runtime/tests после receipt не менялись. Root source review
`msg_a23ce9ef3627` независимо подтвердил whole-router AST вне согласованных
adapters/state/import и совпадение извлечённых policy bodies.

Полный CI, выпуск, клиентский прод и fuel-only не проверялись. Весь M04 не закрыт:
сохранены явные management/runtime compatibility edges и остальные
service→router зависимости за пределами согласованного состава.
Следующий владелец и release назначаются ROOT; merge/deploy не выполнялись.
