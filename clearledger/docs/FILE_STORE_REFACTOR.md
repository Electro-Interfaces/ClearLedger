# SourceFile: общий writer и транзакционный cleanup

29.10.2026, этап M07 после dependency `c6a51a05` (локальный cherry-pick `613290bd`).
SourceFile остаётся общим содержимым; DataEntry, DocCard и DocVersion не заменяются
новыми сущностями. ACL, domain policy, commit owners и продуктовый download gap
не менялись. M07 и вся программа этим helper не объявляются завершёнными.

## Один writer

`file_store.put` сохраняет нефлаширующий контракт и default `purpose=attachment`.
`put_and_flush` только добавляет flush; commit остаётся у use case.
`put_generated` использует тот же exclusive writer для seekable stream callback:
ZIP не загружается целиком в память. Размер и SHA-256 вычисляются по реальным bytes.
Идентификатор — UUID сервера или явно заданный внутренний UUID. Collision никогда
не перезаписывает старый файл; cleanup удаляет только созданный данным вызовом путь.

Мигрированы initial byte writers:

| Вход | Purpose и совместимость | Commit owner |
|---|---|---|
| `ops_terms.store_file` — dependency | `data`, прежние UUID/name/MIME/hash | вызывающий сценарий |
| Intake | явный `data/attachment`, прежний dedup/fallback/MIME; теперь единый UPLOAD_DIR вместо cwd/uploads | прежний get_db/use case |
| Task attachment | **data**, как старый SourceFile model default; файл/TaskAttachment имеют один id | router |
| Site document | **data**, как старый SourceFile model default | router |
| Shared organization PDF | attachment, исходное имя/MIME PDF, принудительный storage suffix `.pdf` | router |
| TP handover ZIP | attachment, stream archive, прежний manifest/content; SourceFile/DocVersion size/hash/id согласованы | enclosing workflow |

`storage_suffix` — внутренний override только расширения, не пути. Имя файла
сохраняется отдельно; каталог и filename хранения задаются UUID. Ранее сохранённые
SourceFile пути не переносятся, metadata/готовые импорты не переписываются.

## Public Session lifecycle

Файлы регистрируются после успешного `Session.add` за текущим root transaction
либо SAVEPOINT в namespaced `Session.info`. AsyncSession использует публичный
`sync_session`; обработчики установлены на SQLAlchemy Session.

- `before_commit` отмечает попытку commit текущего transaction. Сам marker
  **не доказывает** успешный commit; он запрещает вывод «нет after_commit marker,
  значит rollback». Пустой bucket учитывает файлы из последующих hooks.
- `after_commit` отмечает successful commit, если цепочка callbacks дошла до
  нашего listener. Приоритет listener не считается гарантией сохранности.
- `after_transaction_end` передаёт файлы released либо неопределённого SAVEPOINT
  родителю, не перенося commit markers на parent. Root commit освобождает tracking,
  сохраняя bytes. Close без попытки commit удаляет новые файлы; после попытки commit
  без success/rollback подтверждения сохраняет bytes и пишет предупреждение с UUID.
- `after_rollback` также очищает новый файл при DBAPI rollback failed flush.
  Внутренние flush transactions без собственных файлов не затрагивают parent.
- Нет перехвата чужого commit, SQL из commit hook, private `_state/_parent`
  или анализа внутренних transaction enums; используются публичные getters,
  `SessionTransaction.parent` и documented events.

Nested commit остаётся условным до root commit; inner rollback не удаляет outer.
Повторное использование session не переносит tracking успешного commit в новую
транзакцию. Ошибка CLASS observer **до нашего after_commit listener**, но после
durable DB commit, не является rollback и не удаляет сохранённый файл при close.
Настоящий Task.cancel после flush очищается
при выходе из transaction/session. Ошибки unlink логируются только с file UUID.

### Дополнительная проверка раннего CLASS observer

После `5fce384e` обнаружен дефект прежнего cleanup: существующий app-wide observer
(например, `task_assignments._send_refresh`) мог прервать цепочку `after_commit`.
Отсутствующий success marker затем приводил к unlink в `after_transaction_end`.
Первый PostgreSQL reproducer дал **1 FAIL / 1 PASS**: независимая session уже
видела committed SourceFile, bytes существовали до close и исчезали после него.
Control с тем же порядком регистрации без исключения прошёл. Старый тест с
INSTANCE listener не покрывал этот порядок.

Новый тест публичными `event.remove/listen` регистрирует CLASS observer **раньше**
writer listener; внутри observer проверяет, что success marker ещё не выставлен.
Исправление использует отдельное событие `before_commit`, а не перестановку
`after_commit` listeners: позже добавленный приоритетный observer также может
прервать callbacks. В частности, `insert=True` документирует prepend, но не
непрерываемое выполнение всей цепочки.

Граница гарантии преднамеренно консервативна: если commit был начат, но нет
достоверного rollback event, close сохраняет bytes даже при ошибке **до** DBAPI
commit. Такая ошибка может оставить orphan; cleanup по одному исключению либо
отсутствующему callback снова создал бы риск потери committed содержимого.
Подтверждённый `after_rollback` удаляет новые bytes, включая failed flush/commit.
Неопределённый SAVEPOINT передаёт ownership parent: его rollback/close очищает
оба набора, root commit сохраняет их. Это не обещание распределённой атомарности.

Первичные источники, прочитанные при реализации:

- [SQLAlchemy transaction events и root/SAVEPOINT detection](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_transaction_end)
- [after_commit и after_rollback](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_commit)
- [before_commit — событие до commit](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.before_commit)
- [Порядок event.listen: append и insert=True](https://docs.sqlalchemy.org/en/20/core/event.html#sqlalchemy.event.listen)
- [SAVEPOINT flush/release/rollback](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#using-savepoint)
- [События AsyncSession через sync Session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-events-with-the-asyncio-extension)

## Проверка

Только выделенная локальная PostgreSQL `api_file_store_test`, 127.0.0.1:33546,
container `api-modernization-test-20261029`, owner clearledger. Новый модуль до
fixtures требует этот явный TEST_DATABASE_URL. UPLOAD_DIR — абсолютный tmp path;
рабочие данные, VM, env и другие БД не использовались. Conftest с DROP schemas
прочитан до запуска; отсутствующую БД создал координатор.

Первоначальный прогон: **112 PASS**: 24 новых real PostgreSQL/file/adapter cases,
9 прежних root файловых тестов и 79 regression cases. Две прежние SQLAlchemy
archive DELETE warnings; FAIL/SKIP в этом прогоне нет. Лог:
`.artifacts/file-store-tests.log`.

Покрыты commit, flush→rollback, Task.cancel после flush, close без commit,
nested commit→outer rollback, inner/deep rollback с сохранением outer,
failed flush/DB commit, post-commit observer failure, repeated session,
exclusive collision/identity, ZIP hash/size и все пять migrated adapters.
Compatibility: `test_raw_intake`, `test_sites_intake`, `test_ezs_tp_steps`,
`test_calendar_papers`, `test_conf_protocol`, `test_conf_privacy`,
`test_docs_register`, `test_docs_archive_security`, `test_docs_archive_flow`.

Focused follow-up после reproducer: **40 PASS** (`test_file_store_transactions`,
`test_ops_file_store`), в том числе 7 новых cases: ранний CLASS observer с
исключением/без, прерванный callback RELEASE с parent commit/rollback/close,
ошибка commit с explicit rollback и с одним close. Последний case проверяет
консервативный orphan, warning и отсутствие tracking после close. Прежние
rollback/cancel/failed flush/SAVEPOINT/collision и 9 root cases проходят.
Логи: `.artifacts/file-store-early-observer-baseline.log` (до исправления),
`.artifacts/file-store-early-observer-tests.log` (после). Остальные 79 regression
cases здесь повторно не запускались: adapters и domain behavior не менялись.

Самостоятельный старый `test_tp_workflow_integration` жёстко требует другую
`tp_test`; его guard/условия не ослаблялись, другая БД не запускалась.
Реальный TP archive/DocVersion/SourceFile проверен новыми PostgreSQL cases.

## Инвентаризация оставшихся writers и границы

| Место | Причина оставить |
|---|---|
| `routers/ops_router.py` initial SourceFile bytes | Ownership M08; единственный оставшийся прямой initial SourceFile writer вне helper, передан координатору |
| `doc_exchange.place_package` | Внешняя папка обмена/DocExport, не SourceFile; external egress lifecycle не менялся |
| `doc_text` | Временный файл извлечения текста, не shared SourceFile creation |
| `media_shrink` | Probe/temp и in-place transform уже сохранённого файла; новый SourceFile/UUID здесь был бы несовместим |
| `main` filesystem readiness probe | Проверка доступности каталога, не byte writer SourceFile |
| SourceFile metadata/чтение/готовые imports | Это не новый byte ownership, не переписывались |

Проверены SourceFile constructors, прямые write_bytes/open и aliases/SQL inserts.
Помимо delegated ops_router конструктор SourceFile остался только в file_store.

Это in-process Session transaction cleanup, не распределённая атомарность.
Process crash/потеря подтверждения DB commit требуют reconciliation; внешние
Connection-owned transactions, двуфазный commit и посторонний unlink не сертифицированы.
Ни distributed object store, ни outbox, ни storage migration не добавлены.
Лёгкие fake sessions в чистых metadata tests не обещают SQL lifecycle; production
SQLAlchemy sessions используют events. Выпуска на рабочее пространство не было.
