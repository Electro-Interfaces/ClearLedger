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

- `after_commit` отмечает successful commit текущего transaction.
- `after_transaction_end` передаёт файлы успешно released SAVEPOINT родителю;
  root commit освобождает tracking, сохраняя bytes. Без success marker удаляются
  файлы данного transaction, включая close без commit.
- `after_rollback` также очищает новый файл при DBAPI rollback failed flush.
  Внутренние flush transactions без собственных файлов не затрагивают parent.
- Нет перехвата чужого commit, SQL из commit hook, private `_state/_parent`
  или анализа внутренних transaction enums; используются публичные getters,
  `SessionTransaction.parent` и documented events.

Nested commit остаётся условным до root commit; inner rollback не удаляет outer.
Повторное использование session не переносит tracking успешного commit в новую
транзакцию. Ошибка observer **после** durable DB commit не является rollback и
не удаляет успешно сохранённый файл. Настоящий Task.cancel после flush очищается
при выходе из transaction/session. Ошибки unlink логируются только с file UUID.

Первичные источники, прочитанные при реализации:

- [SQLAlchemy transaction events и root/SAVEPOINT detection](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_transaction_end)
- [after_commit и after_rollback](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_commit)
- [SAVEPOINT flush/release/rollback](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#using-savepoint)
- [События AsyncSession через sync Session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-events-with-the-asyncio-extension)

## Проверка

Только выделенная локальная PostgreSQL `api_file_store_test`, 127.0.0.1:33546,
container `api-modernization-test-20261029`, owner clearledger. Новый модуль до
fixtures требует этот явный TEST_DATABASE_URL. UPLOAD_DIR — абсолютный tmp path;
рабочие данные, VM, env и другие БД не использовались. Conftest с DROP schemas
прочитан до запуска; отсутствующую БД создал координатор.

Целевой прогон: **112 PASS**: 24 новых real PostgreSQL/file/adapter cases,
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
