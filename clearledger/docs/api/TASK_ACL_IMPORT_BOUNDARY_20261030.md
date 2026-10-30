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
38 случаев, отсутствие skips, setup/call/teardown outcomes и блокированных
попыток проверяются runner. Предел исполнения 600 секунд, capture 4000 событий,
JSON evidence 1 MiB. JUnit и JSON сохраняются только в evidence directory.

Worker не запускал runner, приложение, pytest collection, SQL, venv/install,
Docker/build или deploy. Requirements, Dockerfile, Compose, features, CI
и рабочие данные не менялись. Нет merge или выкладки. После независимого ROOT
review/execution ожидаются actual evidence и report-only finalization.

Откат: целиком собственный runtime/tests/runner commit; схемы и данные
не меняются. Частичная доставка этих двух runtime-файлов не считается
подтверждением совместимости старых раздельно обновляемых runtimes.
