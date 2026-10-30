# M04 / P2: прямые локальные imports task ACL

База: `cf209237bf495e7b5fa981976fac20959c88d5db`, ветка
`agent/api-task-acl-import-boundary-20261030`. Изменены только пять bindings
в двух runtime-модулях. `management_local.read_local` и
`work_links.visible_work` получают `is_admin as _is_admin` и
`visible_to as _visible_to` непосредственно из `app.services.task_access`;
`work_links.readable_entity` получает `can_view_task as _can_view_task` там же.

Остальные router symbols остаются локально на прежнем месте. Владельцы ACL,
их router reexports, company/product guards, personal filters, doc/task union,
edit actor guard, исключения и chat compatibility hook сохранены.
Новые imports остаются в тех же функциях непосредственно рядом с прежним
router import, до первого обращения к ACL. Модульных imports не добавлено.

## Доказательство состава

Приватные исходники доказательства и артефакты находятся в
`.artifacts/task-acl-import-boundary/` выданного worktree. Старые evidence
сохранены. `source_proof.py` использует только stdlib/Git, не исполняет AST
и не импортирует приложение, pytest, ORM или runner. Пределы: 90 секунд,
20 секунд на Git-команду, 8 MiB на source blob, 1 MiB на итоговый proof.

Для каждого из трёх local import sites доказательство проверяет исходные
и оставшиеся router symbols, новые owner aliases, смежность и положение
в функции. Обратная подстановка только import nodes должна восстановить
**полный AST обоих модулей**, включая все функции, guards, queries и exception
handlers. Отдельно проверяются неизменность байтов `task_access.py` и
`tasks_router.py`, owner definitions и отсутствие module Store rebindings.
Runtime identity дополнительно проверяет новый PostgreSQL-тест.

Историческая карта `SERVICE_ROUTER_BOUNDARIES_20261030.{md,json}` не меняется.
Source-only inventory фиксируется на exact committed candidate. После P1+P2
ожидается **19 router import sites / 23 router bindings**; удаляются ровно
пять исторических bindings E12, E15, E24, E26, E28, без новых router edges.

Raw inventory и полный provenance diff сохраняются. Raw records двух
изменённых модулей не объявляются побайтно равными базе: source SHA,
import/enclosing AST SHA и номера строк закономерно меняются. ROOT подтвердил
этот критерий в `msg_48721575394e` (вопрос `msg_fd1770091721`): все поля
остальных 23 связей сравниваются без произвольных исключений, разрешены лишь
точные пары хешей одобренных import/enclosing nodes и модулей плюс точное
сопоставление неизменённых строк. Другие owner/binding/call/guard поля
остаются прежними. Итоговый proof и hashes передаются ROOT отдельно.

## Подготовленный настоящий PostgreSQL / ASGI набор

Существующие `test_management_api.py`, `test_task_projection_access.py` и
`test_management_runtime_compat.py` прочитаны и сохранены без правок.
Новый `test_task_acl_import_boundary.py` добавляет 16 случаев:

- Management ASGI: member, company-admin и superadmin; company/private,
  watcher/participant/author/assignee; обе personal записи исключены.
- 11 вариантов doc/task union и single read: company, private, personal;
  чужая компания, отсутствующая задача; открытый и strict документ с собственным
  документным ACL. Task 404 и документный 403 проверяются отдельно.
- Сохранённый edit actor guard: watcher читает private, получает 403 при edit;
  автор проходит edit guard.
- Старые router reexports имеют тот же owner identity. После подмены только
  старых reexports на ловушки все пять новых lexical bindings вызывают
  instrumented owner и настоящие SQL-предикаты.

Чтение проверяется по полным строкам девяти таблиц, включая timestamps.
Дополнительно выбраны 22 существующих случая: local task/company/filter/limit,
product disable, calendar, chat participation/history/read-only, оригинальный
chat hook и его missing/denied fail-closed, wrong-company projections,
14 вариантов code ref aliases с настоящим HTTP. Всего **38 случаев**,
12 точных function selectors. Поведение ACL не заменяется заглушками SQL.

## ROOT execution gate

Runner: `server/tests/task_acl_import_boundary_approved.py`, аргумент
`--execute-approved-task-acl-import-boundary-tests`. Это предложение ROOT,
а не разрешение worker на запуск. До завершения gate используются только
stdlib и проверка исходников; первый pytest/app/ORM import находится после gate.

Gate требует frozen hashes/counts всех app/tests/schema файлов, SHA самого
runner через `TASK_ACL_RUNNER_SHA256`, исходные requirements/pytest.ini,
Python 3.13 без optimize/bytecode, явные ROOT/test flags и allowlist окружения.
`HOME` обязан совпадать с фактическим домашним каталогом пользователя.
Секрет приложения только synthetic; credentials рабочей среды не читаются.
`DATABASE_URL` и `TEST_DATABASE_URL` должны быть одинаковыми, схема
`postgresql+asyncpg`, host строго `127.0.0.1`, база строго
`api_task_acl_boundary_test_20261030`. Числовой непривилегированный порт
резервирует и отдельно утверждает ROOT через `TASK_ACL_PG_PORT`.

Три свежих разных owned private empty каталога: cwd (`TASK_ACL_EMPTY_CWD`),
upload (`UPLOAD_DIR`), evidence (`TASK_ACL_EVIDENCE_DIR`). Вложенность и
symlink components запрещены. Cwd изолирует чтение `.env` по относительному пути.

За gate network audit разрешает только PostgreSQL по утверждённому адресу;
остальные connect/DNS/sendto/sendmsg/bind и внешние subprocess запрещены.
Локальный socketpair asyncio остаётся возможным. До initial conftest и setup
устанавливаются captures email/chat/SMTP/notify/task-mail/push/WS;
в capture сохраняются только названия отправителей без адресатов и содержимого.
Точное число случаев, отсутствие skips, setup/call/teardown outcomes и блокированных
попыток проверяются runner. Предел исполнения 600 секунд, capture 4000 событий,
JSON evidence 1 MiB. JUnit и JSON сохраняются только в evidence directory.

Worker не запускал runner, приложение, pytest collection, SQL, venv/install,
Docker/build или deploy. Requirements, Dockerfile, Compose, features, CI
и рабочие данные не менялись. Нет merge или выкладки. Оба ROOT прогона и очистка
завершены; результаты и hashes приведены ниже.

Откат: целиком собственный runtime/tests/runner commit; схемы и данные
не меняются. Частичная доставка этих двух runtime-файлов не считается
подтверждением совместимости старых раздельно обновляемых runtimes.

## Первый ROOT прогон и исправление fixture

Frozen commit первого прогона: `0053a9c2e578a4a574017f470ba39261a359efbe`.
SHA-256 runner: `ac66a613b6d6ec24e1d0565960142e6bb67df92e42d296838efdba1b9ee293df`.
ROOT независимо подтвердил полный AST двух модулей после обратной подстановки
пяти bindings. Первый настоящий прогон: **27 PASS / 11 FAIL**, pytest 23.39 с,
весь дочерний процесс 35.53102453239262 с, процесс завершён и reaped.

Все 11 отказов произошли до ACL assertions: новая fixture создавала два документа
с одинаковым `(company_id, subject_ref)`, что нарушило существующее ограничение
`uq_doc_cards_subject`. Это ошибка тестовых данных; runtime не менялся.
Сообщение ROOT: `msg_cd3b04a72a66`; исходные failure evidence сохранены в
ROOT `.artifacts/root-task-acl-boundary-review-20261030/`: `summary.json`,
`test-process.json`, `test.log`, JUnit и boundary JSON. ROOT сообщил успешный
обычный DROP disposable БД, до очистки fresh relations 0 / connections 0,
после DROP exists 0, `max_locks_per_transaction=64`.

По отдельному указанию ROOT исправлена только новая fixture: strict документ
получает другой subject_ref; union без ref по-прежнему проверяет его отдельный
ACL, а дополнительный same-ref запрос ожидает только public документ и доступную
задачу. Прежние ожидания task 404 / doc 403 и полные snapshots сохранены.

Текущий runner с теми же границами сужен до единственного точного selector
`tests/test_task_acl_import_boundary.py::test_work_union_and_single_read_preserve_task_doc_acl`
и **11 параметризованных случаев**. Tests tree hash обновлён, app/schema hashes
сохранены. Исходный runner для 38 случаев сохранён в первом коммите и приватной
копии `.artifacts/task-acl-import-boundary/initial-38-runner.py`.
Предыдущие 27 зелёных случаев ROOT поручил сохранить и не повторять.
Исправленный прогон выполнен ROOT; worker проверил hashes переданных evidence
чтением конкретных файлов, без запуска приложения, тестов или SQL.

## Итог ROOT проверки

Исправленный frozen commit: `0aa45f406c64bcb8a4e5d7c59cb62a70c958c6cf`.
Runner SHA-256: `3bbcfe4797fdf0a1295524f5213a34a5f2dfa52d0afdb01a5fdae53d6929ed8f`.
ROOT подтвердил **11/11 PASS**, pytest 17.33 с, дочерний процесс
30.025600762106478 с, exit 0, child reaped. Нет failures/errors/skips;
network attempts blocked 0, отправители перехвачены до conftest.
В первом прогоне перехвачены 72 вызова email/notify/WS, во втором 11 WS;
capture содержит только названия функций. Реальных внешних отправок нет.

Получены **27 PASS первого прогона + 11 PASS исправленного прогона**.
Это два отдельных прогона; единого зелёного прогона всех 38 не было.
В обеих попытках ROOT подтвердил обычный DROP точной disposable БД,
fresh relations 0 / connections 0 / exists after DROP 0, max locks 64.
Сообщение ROOT с разрешением report-only finalization: `msg_5ba8c089a0bd`.
После него runtime/tests/runner не менялись.

Source-only proof подтвердил обратную подстановку import nodes для обоих
полных модулей, точные lexical bindings и неизменные owner/reexports.
Inventory на первом frozen runtime commit: **19 sites / 23 bindings**,
ровно пять удалённых records, 23 оставшихся semantic records сохранены.
14 raw records равны базе без IDs; у других девяти всего 81 проверенное
provenance leaf difference только в двух разрешённых модулях.
Исправленный коммит меняет только новую fixture/runner/отчёт: app digest прежний.

| Источник | SHA-256 |
|---|---|
| `source-proof.json` | `05f2773ed9312018c34cd25a831c74b192358eb1b006f143b83a045ad078bece` |
| frozen `inventory/public.json` | `a58d37ed722c37fc4b54513ce0d87c3600a9aaea6698eb048ce82856cf99ca85` |
| app: 492 файла | `1360e0813ed1206204183ceb4f66a9cff00090cfc83204e6aca1f5f1f532792b` |
| corrected tests без runner: 340 файлов | `be918799bba483d2ba71b4950f617a518d1bd6c2bf039f3a7da1ba8394faab8b` |
| schema: 16 файлов | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |

Корень evidence ROOT:
`/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/`.
Первая попытка: `root-task-acl-boundary-review-20261030/` (A);
исправленный повтор: `root-task-acl-boundary-review-v2-20261030/` (B).
Все десять hashes ниже проверены worker read-only; подробный приватный manifest:
`.artifacts/task-acl-import-boundary/root-evidence-references.json`.

| Попытка / файл | SHA-256 |
|---|---|
| A / `summary.json` | `b03323266897877c9ab6e072426a26abd8aebea36c81e4eb30f6782b178aa67d` |
| A / `test-process.json` | `5d66bcef5793350341fbba0f723ce13b9a81cf23eaf39edbf75a81c1e1ddac99` |
| A / `cleanup-observed.json` | `f85c218fde90aedc66ba8c2eab48add7b441394910945cb2a56f737d6cbbc09b` |
| A / `evidence-test/task-acl.xml` | `8683af6f794fd5fde4508dd6994d1b7b225677407915a62405a262b95070fbcc` |
| A / `evidence-test/task-acl-boundary.json` | `9051213370aa7bc0ac72f96bbb1ee52fe989bd1bb6517b3c745a38d51259f75c` |
| B / `summary.json` | `1950e9426de0eb79b2fa6391f0fafd70bde243c66abdf4732b263eef67abca8d` |
| B / `test-process.json` | `1f8e02dda0c46660627a7b6581466f23d71ae67328a1b1917a5a1ee453f6e621` |
| B / `cleanup-observed.json` | `f85c218fde90aedc66ba8c2eab48add7b441394910945cb2a56f737d6cbbc09b` |
| B / `evidence-test/task-acl.xml` | `33119420231e1a06d30e248d80bfd30af198e32665f0d46f43eaf87006e70568` |
| B / `evidence-test/task-acl-boundary.json` | `3ee8e255a3d5a113ff4af380ca122e94f8816a0d4b6cc9c7900d713f8138eefe` |

Ограничения: проверен baseline environment, не candidate dependency environment;
проверены выбранные native PostgreSQL/ASGI случаи, не все API-тесты проекта.
Рабочие контуры не затрагивались; merge/deploy не выполнялись.
Worker выполнял только stdlib AST/compile-in-memory/Git и чтение ROOT evidence.
