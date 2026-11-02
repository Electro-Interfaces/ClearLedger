# Владелец selector «мои встречи», M04-P4 · 31.10.2026

`services/calendar_queries.my_events_clause` владеет точным SQL-предикатом
organizer OR id IN CalendarAttendee.event_id. Он только строит SQL: без сессии,
SQL execution, flush, commit и отправителей. Company/product/date/visibility
остаются независимыми ограничениями callers. Это правило участия, не общий ACL.

База `f711bd65ee20d62e206b5e977dca23d1b1f604a6`, ветка
`agent/api-calendar-query-owner-20261031`. ROOT согласовал owner/wrapper и
feed replacement: `msg_5fa0c592ee19` → `msg_723f9e84bd46`.

| Consumer до правки | После |
|---|---|
| work_router.calendar_list, mine | Прежний sync `_my_events_clause` → owner |
| work_router.calendar_list, subject_ref | Тот же wrapper плюс прежний company visibility OR у caller |
| management_local.read_local, исходный E16 | Прямой local import owner; прежний OR company visibility у caller |
| work_router.calendar_feed, inline повтор | Тот же wrapper(хозяин.id), без копии predicate |

Feed сохраняет отдельный token trust profile: его окно ±365 суток и прежний
cross-company охват владельца token не заменены company-scoped list/detail.
Удалён только неиспользуемый local CalendarAttendee import feed. Список компании,
summary, busy/availability, detail и guards участников — другие use cases, их
bodies не менялись. Management chat hooks из M04-P3 остаются прежними.

## Статическая проверка и сохранённые границы

- Тело owner AST совпадает с исходным `_my_events_clause` (включая local models import).
- Whole-router reverse AST совпадает с базой после возврата только owner import,
  wrapper body и двух feed изменений. Остальные handlers/classes/декораторы равны.
- Management AST отличается только selector import; task/chat bindings неизменны.
- Global app AST перед/после перечисляет три исходных helper call sites и точный
  inline повтор feed. Динамические computed loaders/monkeypatch не объявляются
  runtime call graph; native wrapper и прямой management binding проверяются отдельно.
- Existing inventory: 494 → 495 файлов,
  484 → 485 Python parsed,
  0 parse_unknown, service→router bindings 19 → 18, import sites 16 → 15.
  Устранён исходный E16; нумерация нового inventory сама по себе меняется.

Локальные evidence: `.artifacts/calendar-query-owner-20261031/`:
`source-review.json`, `before/`, `after/`,
`before-predicate-call-candidates.json`, `after-predicate-call-candidates.json`.
Подготовка: чтение/Git/AST/compile; без app imports, pytest collection и SQL.
Старые tests, schema/models, meeting_notice, SDK/Contract/product_api и live
preservation files не изменялись.

Отдельная legacy-profile characterization согласована ROOT
`msg_7ba805364b62` → `msg_2289f382a39c`: native `_assert_work`
(tasks_router, через auth.assert_company_product) проверяет membership/modules,
а management_local.read_local дополнительно проверяет CompanyApp.enabled.
При synthetic app OFF и member.modules=None native сохраняет 200/self event,
management — 200/empty/source forbidden; membership/modules revoke дают native 403.
Это наблюдаемое различие UI availability/API authority, его намеренность целиком
не доказана каноном. Не объявлять его новой ACL-нормой или решённым M03: в этом
пакете app-enabled gate не добавлен и прежний caller доступ не ослаблен.

## Frozen proposal V1 для ROOT

Runtime/SQL выполняет только ROOT после review. Перед исполнением ROOT создаёт
exact disposable DB `api_calendar_query_owner_test_20261031` на 127.0.0.1:33546,
synthetic clearledger/api_test_only, без других clients, и четыре новые частные
папки cwd/upload/evidence/scratch mode 0700. Чужие ignored proofs сохраняются.

| Источник относительно server | SHA-256 |
|---|---|
| `app/services/calendar_queries.py` | `7d04c914b316824db9739639b0d558d0360d23590318412d45cd5c0e0c2e05cd` |
| `app/routers/work_router.py` | `2cea00bb99052d63c040200a5eab7938e54c3718a2f437549eef896fa484828f` |
| `app/services/management_local.py` | `c92a4e48a72cf25b761d21a846b0aca70f62cb2ef569f5307d2dc44dc4354d82` |
| `tests/test_calendar_query_owner.py` | `964a34274fc4ea4e06b65764bb3c3c775700df10d029b5a1a27d0f7b7af41de3` |
| `tests/calendar_query_owner_approved.py` | `a138dbef3ee45962421ddfb55fb037ef9e4e2797c720d66c5d7307ad47410a0b` |

Full-tree manifests: sorted relative paths + SHA256, исключаются __pycache__ и
сам runner из tests. Полные sources проверяются до imports и после runtime:

| Tree | Files | SHA-256 |
|---|---:|---|
| app | 495 | `3aeecb4893e1d3bf162209de67375d75e76b2e123cb5046692bf7a18db5155a7` |
| tests без self | 356 | `9760a011bf7f6eec2777d5daaa7b16b92c502d39d4a0d1aeb473288bb36fe6f2` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |

requirements.txt `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0`;
pytest.ini `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601`.

27 функций / **97 cases**, exact selection/counts зашиты в runner:
20 новых fixed-ID SQL/HTTP goldens (organizer-only, attendee-only, оба без дублей,
nonparticipant/admin/superadmin, foreign company/profile/date, declined/cancelled,
UTC/day overlap bounds, direct management binding, read snapshots/no sends,
legacy-profile difference, token feed) и 77 прежних: 30 management bounds,
32 management HTTP extremes, 7 calendar, 2 workflow, 4 native series list,
2 management calendar/product regressions. Expected не вычисляются копией
organizer/attendee условия: сравниваются фиксированные event UUID.

Boundary перенесена из принятого chat_access_owner_approved V3
SHA `e73078ee529fa60e1cb5fc5190a46990c70c15e99f7b87d117415a05cf00fada`.
AST inventory/PG metadata policy/16 controls/install_boundaries/scratch_bound
совпадает с принятой реализацией. Exact candidate77 (61 runtime +16 tools),
Python3.13.7/glibc2.36, -I -S -B, без installer/изменений зависимостей.
Пять import probes подавлены только временным socket.has_ipv6=False для
aiosmtplib/aiohttp/httpx/pywebpush/requests с exact restore; bind не разрешён.
PG sendmsg — только native owned connected stream, buffers-only, без ancillary,
flags/address; exact target и SQL connect/statement/lock/idle/command timeouts.
Сохранены env/write/process/HTTP boundaries, synthetic seed до cached Settings,
pre-conftest delivery capture, --capture=sys, log/XML/JSON только в evidence.
Native handlers не запускают lifespan/jobs при ASGITransport tests.

Точные ROOT argv/env (все указанные папки должны быть новыми и пустыми):

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/calendar-query-owner-20261031/root-test-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=calendar-query-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_CALENDAR_QUERY_OWNER_TESTS=1 RUN_CALENDAR_QUERY_OWNER_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_calendar_query_owner_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_calendar_query_owner_test_20261031 \
  CALENDAR_QUERY_PG_PORT=33546 CALENDAR_QUERY_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/calendar-query-owner-20261031/root-test-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/calendar-query-owner-20261031/root-test-upload CALENDAR_QUERY_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/calendar-query-owner-20261031/root-test-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/calendar-query-owner-20261031/root-test-scratch CALENDAR_QUERY_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/calendar-query-owner-20261031/root-test-scratch \
  CALENDAR_QUERY_RUNNER_SHA256=a138dbef3ee45962421ddfb55fb037ef9e4e2797c720d66c5d7307ad47410a0b \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/calendar_query_owner_approved.py --execute-approved-calendar-query-owner-tests
```

Предлагаемые ROOT outer limits: CPU600, AS3GiB, FD256, FSIZE2MiB, wall650,
scratch128MiB, отдельное DB allocation/admission с учётом retained WAL.
Runner alarm600, <=4000 source files/tree, <=8MiB/blob, <=64MiB/tree,
<=4000 capture events, <=1MiB JSON, scratch lstat anchors/count/128MiB bounds.
Никаких внешних delivery/network/process; любой forbidden event означает FAIL.
Conftest сбрасывает только public/edge выделенной DB, create_all/seed, затем
штатный drain/teardown. ROOT подтверждает relation/client counts, normal DROP,
exists=0 и чистит только свои scratch/cwd/upload; evidence сохраняет.

## ROOT receipts и оставшиеся границы

ROOT receipt `msg_7b500af9b83e`: **97/97 PASS**, pytest 30.72 s,
outer 47.84533217176795 s, exit 0, child reaped. Независимый JUnit readback:
97 tests, без errors/SKIP; source_after=true, inventory=77, все 16 metadata
controls PASS, forbidden=0. Максимум locks=64; после teardown 0 relations /
0 clients, после штатного ROOT DROP database exists=0. Workers runtime/SQL не
исполняли; runtime/tests/runner после принятия не менялись.

ROOT evidence: `.artifacts/root-calendar-query-review-20261031/actual97/`:
`process.json`, `run.log`, `r1-evidence-test/calendar-query-boundary.json`,
JUnit `calendar-query.xml`; reverse AST proof — ROOT `source-review.json`.
Review `msg_15c648cfbc84` независимо подтвердил owner/full-router/management AST,
семь guard functions и полные frozen manifests/support/selection.
ROOT admission single-schema run: reserve 10GiB неизменен, planning allowance
1GiB, live floor 10GiB; free stable 12.2GB, без foreign cleanup/GUC изменений.

Полный CI и выпуск не проверялись. Весь M04 не закрыт: остаются management task
adapters _assert_work/_names/_not_personal, осознанные chat runtime hooks и другие
service→router edges вне пакета. Legacy availability/API authority split остаётся
отдельным M03 вопросом ROOT. ROOT назначает дальнейшего владельца/release;
merge/deploy не выполнялись.
