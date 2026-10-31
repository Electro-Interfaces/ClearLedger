# Владельцы task helpers, M04-P5 · 31.10.2026

База `d017368d5338b50dcfd4949b2bff017cc62dde0d`, ветка
`agent/api-task-helper-owners-20261031`. Ownership согласован ROOT:
`msg_0bdd2b14b672` → `msg_1e861188e19f`.

| Правило | Owner | Native compatibility |
|---|---|---|
| _assert_work | existing task_access.assert_work | Wrapper передаёт текущий router assert_company_product; docs→plan fallback прежний |
| _names | task_queries.names | Wrapper передаёт текущий router _route_of; direct management выбирает default service resolver при вызове |
| _not_personal | task_queries.not_personal | Wrapper возвращает исходный visibility != personal SQL clause |
| _route_of → DEFAULT_ROUTE | task_routes.route_of / DEFAULT_ROUTE | Тот же импортированный mutable object; native wrapper передаёт текущий router DEFAULT_ROUTE |

`_not_personal` — популяция общей работы, не ACL: NULL отсеивается SQL,
unknown/empty visibility сами по себе проходят этот отбор; отдельный visible_to
закрывает неизвестный уровень и чужие записи. Personal caller вправе читать
своё через отдельный visibility=personal; admin не получает чужое личное.
Names получает уже разрешённые caller задачи и не добавляет tenant/ACL checks:
порядок/namespace прежних 6 SELECT, все ключи, null/unknown refs и empty skip
сохранены. Route fallback сохраняет literal/order/identity DEFAULT_ROUTE,
null/empty/invalid custom stages, порядок валидных стадий; default sentinel
сохраняет explicit empty/falsey/None late replacements, callbacks проверяются
через is None, без truthiness substitution.

Management получает три прямых service bindings. Его calendar selector и оба
chat hooks неизменны; work_router/work_links продолжают прежние native adapters.
Другие два docs→plan fallback в task_access не затронуты по решению ROOT.
Availability CompanyApp.enabled у management и API authority через member modules
остаются разными caller gates, legacy различие M03 здесь не исправлялось.

## Closure, hooks и source proof

Global AST до правки: 63 _assert_work, 8 _names, 10 _not_personal,
5 _route_of call candidates и 5 DEFAULT_ROUTE loads. Это source-spelling
inventory, не полный runtime call graph: arbitrary computed loads/getattr/patch
не объявляются разрешёнными статически. Native consumers типов/create/action,
версий/спринтов, summary/search и прочие handlers сохранены целиком.

Закреплённый old hook: test_file_store_transactions.py:447 заменяет router
_assert_work при upload_attachment; выбран именно этот старый regression.
Явных old names/route/default patches AST не нашёл; dynamic setattr в старом
P2-тесте относится к is_admin/visible_to/can_view_task, эти reexports не менялись.
Новые проверки подтверждают late auth/route/default hooks, shared DEFAULT_ROUTE
со STARTER_TYPES, falsey callbacks и прямые management owners с poisoned old hooks.
Нормальные imports разделяют default object; native rebind/router hook override
относится к native adapter, direct service defaults принадлежат service owner.

Source evidence `.artifacts/task-helper-owners-20261031/`:
`before/`, `after/`, `before-consumers.json`, `after-consumers.json`,
`before-hooks.json`, `source-review.json` с normalized helper/whole-router AST SHA.
Bodies четырёх owners совпадают с исходными после явной нормализации callback/
default selection. Whole-router reverse AST совпадает с базой после возврата
только 4 wrapper bodies, DEFAULT_ROUTE assignment и новых imports.
Management — import-only delta; existing task_access — неизменный byte prefix.
Global inventory: 495→497 файлов, 485→487 Python parsed, 0 parse_unknown;
service→router bindings 18→15, import sites 15→14 (три management bindings удалены).
`git diff --check` и compile без исполнения PASS; старые tests не изменены.

## Frozen proposal V1 для ROOT

До review не выполнялись app import/collection/SQL/browser/build/install.
ROOT один владеет serialfresh exact DB `api_task_helper_owners_test_20261031`,
127.0.0.1:33546, synthetic clearledger/api_test_only, без других clients.
Нужны четыре новые пустые owned test directories mode0700; .env/keys/prod не читать.

| Source относительно server | SHA-256 |
|---|---|
| `app/routers/tasks_router.py` | `6c826cbef1fc6be10a6ecc30236974e357508a21b37d7515f8e007986a5ba97b` |
| `app/services/task_access.py` | `b7e5dfc3a7299cf2073e7ede43ef31299134e4474587e0b6db4b7de11a8d5b26` |
| `app/services/task_queries.py` | `31347cf63e046f554f4516ccc57131c36f8fcfb83c6b49f78d55c606d967e3ce` |
| `app/services/task_routes.py` | `60a6c8ebc8660dad2078df9d2bc84aed9966e091f88ea7e91ca09f8ba1bdf727` |
| `app/services/management_local.py` | `0996bf7ed67f69ee08309d3cc9182537cf00e85d5eb587ff4c9eee6e0b2a9ffe` |
| `tests/test_task_helper_owners.py` | `e63e9c50ab52094d31f6856e5d2e75eb4c55ffd7515c2686133c7d2202492d85` |
| `tests/task_helper_owners_approved.py` | `1417ba767073d87f35c4601270a63d5c0a5ff15c92cc9c1000fd7f551e63c6e1` |

Manifest — sorted [relative path, SHA256], без __pycache__; tests исключает self:

| Tree | Files | SHA-256 |
|---|---:|---|
| app | 497 | `f343bd895a6ac6260859718257e37564288081ea9b1bb3148082f945eacefcd2` |
| tests без self | 363 | `0afccc618b584c25962f52e03d3772c6c1f8f8ec78775886135771085995e249` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |

requirements.txt `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0`;
pytest.ini `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601`.

**69 cases / 27 функций**, selection/counts зашиты в runner:
24 новых fixed-ID/route outputs/SQL/HTTP/no writes cases и 45 прежних:
10 native task route/card/summary/version/sprint/work-mine/key regressions,
4 management task/calendar/chat/product cases, 30 literal-search SQL/ACL/limit
cases, 1 pinned migrated_task_attachment case. RUN_FILE_STORE_TESTS=1 нужен
только для импорта/selection этого одного старого opt-in regression; его safety
predicate проверяет explicit test DB/loopback/test upload. Иные file-store tests
не выбираются. NULL/unknown population — actual SELECT над VALUES с заменой только
fixture column в реальном owner clause, без SQL/schema writes и копии operator.

Strict boundary — accepted calendar runner SHA
`a138dbef3ee45962421ddfb55fb037ef9e4e2797c720d66c5d7307ad47410a0b`:
exact77 distributions (61 runtime +16 tools), Python3.13.7/glibc2.36, -I -S -B.
Inventory, five-probe IPv6 suppression/restore (bind forbidden), native owned
buffers-only PG sendmsg и 16 metadata controls, env/process/write/net/capture/
source/scratch guards сохранены. Synthetic seed задан до cached Settings;
log/XML/JSON в evidence, --capture=sys, TMPDIR/basetemp в своём scratch.
Explicit new opt-in flag file-store добавлен в tight allowlist; dependency install
и schema evolution не требуются. Delivery capture установлен до conftest,
ASGITransport не запускает lifespan/jobs; запрещённый event означает FAIL.

Точные ROOT argv/env:

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/task-helper-owners-20261031/root-test-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=task-helper-owners-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_TASK_HELPER_OWNERS_TESTS=1 RUN_TASK_HELPER_OWNERS_TESTS=1 RUN_FILE_STORE_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_task_helper_owners_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_task_helper_owners_test_20261031 \
  TASK_HELPER_OWNERS_PG_PORT=33546 TASK_HELPER_OWNERS_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/task-helper-owners-20261031/root-test-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/task-helper-owners-20261031/root-test-upload TASK_HELPER_OWNERS_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/task-helper-owners-20261031/root-test-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/task-helper-owners-20261031/root-test-scratch TASK_HELPER_OWNERS_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/task-helper-owners-20261031/root-test-scratch \
  TASK_HELPER_OWNERS_RUNNER_SHA256=1417ba767073d87f35c4601270a63d5c0a5ff15c92cc9c1000fd7f551e63c6e1 \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/task_helper_owners_approved.py --execute-approved-task-helper-owners-tests
```

ROOT outer proposal: CPU600/AS3GiB/FD256/FSIZE2MiB/wall650/scratch128MiB,
serial admission с reserve10GiB и плановым allowance для одной schema/WAL.
Runner alarm600, <=4000 files/tree, <=8MiB/blob, <=64MiB/tree, <=4000 captures,
<=1MiB JSON, scratch lstat anchors/4096 files/128MiB. SQL target/timeouts exact,
source и inventory сверяются до/после. Conftest reset/create_all/seed/teardown
только public/edge своей DB; ROOT после reaping подтверждает 0 relations/clients,
normal DROP/exists0, чистит только свои cwd/upload/scratch и хранит receipts.
Чужие ignored proofs сохранены, рабочие настройки/зависимости/версии не менялись.

## Actual receipts и остаток

ROOT receipt `msg_3a35654fe03d`: **69/69 PASS**, pytest 41.31 s,
outer 58.849959660321474 s, exit 0, child reaped. Независимый JUnit readback:
69 tests, 0 errors/skips; source_after=true, inventory=77, все 16 controls PASS,
forbidden=0. Pinned old file-store hook regression PASS. После teardown —
0 relations / 0 clients; штатный ROOT DROP database — exists=0, maxlocks=64.
Runtime/apps/tests/runner после принятия не менялись; worker SQL/runtime не исполнял.

ROOT evidence: `.artifacts/root-task-helper-review-20261031/actual69/`:
`process.json`, `run.log`, `r1-evidence-test/task-helper-owners-boundary.json`,
JUnit `task-helper-owners.xml`; независимые reverse AST/full manifests — ROOT
`source-review.json`. Review `msg_36a6e4032a38` подтвердил 4 normalized owners,
whole-router/default AST, import-only management, неизменный task_access prefix,
полные manifests и семь guard functions.

Полный CI, merge/deploy не выполнялись. M03 availability/API authority и весь
M04 не закрыты: local after inventory содержит 15 service→router bindings,
включая осознанные management chat hooks и work_links population/native write
bridges вне scope. Следующий owner и release назначает ROOT.
