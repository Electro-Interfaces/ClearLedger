# Независимая проверка managed Core budget startup gate, 30.10.2026

Проверен **только EXACT четырёхфайловый снимок**, указанный ниже, относительно
base `0f847b6f9bd94e1faff1476913ace2219749ced4`. Это source-only correctness/design
review. Найдена одна конкретная проблема интеграции: штатный backend Dockerfile
из base не доставляет зависимость `schema_migrations`, необходимую включённому gate.
Других доказанных ошибок в перечисленных ниже ветках снимка не найдено; работа
на SQLAlchemy/asyncpg/PostgreSQL этим заключением не подтверждается.

## Идентичность входа

Каталог снимка:
`/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/cutover-gate-review-20261030/`.
Manifest: `snapshot.json`, SHA256
`7d47109c42bdd1b03b3ef157fd9012fd62f03b9e4131eae16ff5f790abc4df9b`.
Все четыре actual SHA256 проверены **до чтения исходников** и повторно перед
AST/compile. В таблице пути относительно каталога снимка; все последующие ссылки
`S:` относятся к этим копиям, а `B:` — к `git show <base>:<path>`.

| Файл | Actual SHA256, совпавший с manifest |
|---|---|
| `clearledger/server/app/config.py` | `90c5da106f20fe90e31c899a88018ef741e6b3207a555fedbd58bafaa61780e8` |
| `clearledger/server/app/database.py` | `ee4633ecc50be527ccb15eda8a53633b9129bb97daac4ed8f4aa751a57c0b0a6` |
| `clearledger/server/app/main.py` | `8a4f76e9ef8fe4c27418d8617b5d98b18d75ffbae2e6bbd24ac2994e9b488637` |
| `clearledger/server/app/services/schema_version_gate.py` | `6e51660673e40188705e243c34de61c2e7b1f2cf9c93811bea476839460ba7e4` |

Движущийся author WIP не использован. Изменения автора после создания снимка,
новые Dockerfile, тесты и будущий candidate этим отчётом не проверены.

## F1 — включённый gate не работает в штатном backend-образе из base

**Приоритет P1 для включения managed режима; default-off не затронут.**

Доказательства:

- `S:clearledger/server/app/services/schema_version_gate.py:19,41–42` импортирует
  `schema_migrations.runner`, `schema_migrations.manifest` и `runner.state`.
- `B:clearledger/server/Dockerfile:8–23` собирается из `server/`, устанавливает
  `requirements.txt` и выполняет единственный COPY исходников `COPY app ./app`
  (строка 22). Соседний каталог `server/schema_migrations` в образ не копируется.
- `B:clearledger/server/requirements.txt:1–23` не устанавливает этот локальный пакет;
  он находится отдельным каталогом в Git base, вне `app`.
- `S:clearledger/server/app/main.py:193–196` вызывает `require_engine` до проверки
  completion marker. В `require_connection` импорт зависимости попадает в
  `except Exception` (`S:clearledger/server/app/services/schema_version_gate.py:38–66`).

Механизм: обычная сборка по Dockerfile base с новыми четырьмя файлами, без
дополнительного mount/package, не содержит `schema_migrations`. При
`managed_core_budget_enabled=True` первый gate заканчивается
`ModuleNotFoundError`, обёрнутым в `RuntimeError("Managed Core budget schema is not ready")`.
Startup останавливается даже при полностью применённой и корректной ревизии БД;
готовый completion marker не помогает. Вызов readiness в таком окружении
при достижении обработчика вернёт 503 по той же причине.

Это вывод из build recipe и импортов, без сборки образа или исполнения приложения.
Для включения режима владельцу нужен отдельный проверяемый packaging change,
доставляющий неизменённый frozen пакет и его артефакты в образ, и проверка
фактического образа. В этом review ничего не исправлено. Короткий checkpoint
передан координатору сообщением `msg_12cf6359cedd`.

## Проверенные свойства и границы положительных выводов

| Условие | Source evidence и вывод |
|---|---|
| Настоящее соединение приложения вместо отдельного forced-core подключения | `S:clearledger/server/app/services/schema_version_gate.py:44–60,69–79`: используется переданный engine/connection, DSN из Config не открывается. Probe сверяет `current_database`, `current_user`, `current_schema` с ожидаемыми database/user и `core`. `B:clearledger/server/schema_migrations/runner.py:47–59` повторяет identity и проверяет PG16, owner, privileges, replication role. Никакого SET search_path helper не делает; public при включении должен отказать. |
| Lazy SQLAlchemy transaction → raw asyncpg | `S:clearledger/server/app/services/schema_version_gate.py:46–59`: сначала awaited SQL через SQLAlchemy, затем `get_raw_connection().driver_connection`, затем `is_in_transaction()`, затем `state`. Порядок устраняет передачу ещё не начатой физической транзакции raw verifier. Фактическая адаптация драйвера и поведение при cancellation не запускались. |
| Completion marker не обходит gate | `S:clearledger/server/app/main.py:191–213`: `require_engine` раньше HOSTNAME, CREATE/SELECT marker и early return. Это справедливо для prod/non-prod и отсутствующего instance_id по control flow. |
| Прямой `create_all` проверяет gate до изменений | `S:clearledger/server/app/database.py:2231–2251`: сначала регистрация модели и `engine.begin`, затем `require_connection`, namespace guard, PHONE DDL, metadata. `S:clearledger/server/app/main.py:142–147`: seed следует после `create_all`. Отказ gate не доходит до этих DDL/seed. |
| Исключается ровно управляемая таблица | `S:clearledger/server/app/database.py:2234,2244–2251`: модель остаётся зарегистрированной; список таблиц исключает только объект `ProductAPIBudget.__table__` сравнением `is`. Остальные metadata сохраняются. `B:clearledger/server/app/models_product_budget.py:12–28`: модель без явной schema, FK указывает на partner_installations; в base app нет входящих FK к budget, которые потребовали бы повторного создания этой таблицы. |
| Legacy namespace guard сохраняется | `S:clearledger/server/app/database.py:2206–2228,2240`: guard проверяет все незаквалифицированные metadata-имена, включая зарегистрированный budget, и отказывает при видимой таблице из другой схемы. Он остаётся перед PHONE/metadata; qualified модели не исключаются из metadata-списка. |
| Helper только читает состояние | `S:clearledger/server/app/services/schema_version_gate.py:41–63` вызывает `load` и `state`, не `execute/apply`; `B:clearledger/server/schema_migrations/runner.py:62–71` только identity/catalog/history. `B:clearledger/server/schema_migrations/catalog.py:4–30`, `B:clearledger/server/schema_migrations/revisions/catalog_v1.py:34–200`, `B:clearledger/server/schema_migrations/journal.py:21–28` выполняют SELECT. Нет apply, stamp, repair, DDL или записи history. |
| Нет самоблокировки на owner lock | `S:clearledger/server/app/main.py:257–258` сохраняет внешний startup lock; `S:clearledger/server/app/database.py:48–57` использует пару `(434532,1)`. Helper вызывает `runner.state`, который не берёт advisory lock; получение Foundation owner lock находится в другом `runner.execute` (`B:clearledger/server/schema_migrations/runner.py:95–100`) и недостижимо по этому пути. Ожидание внешнего startup lock осталось прежним и не входит в 15 секунд helper. |
| Readiness отказывает с 503 | `S:clearledger/server/app/main.py:679–682,790–795`: gate внутри try до старых readiness SELECT; обычное исключение helper становится HTTP 503 с общим detail. Liveness `/api/live` не менялась. External task cancellation специально не следует считать обычным HTTP failure. |
| Default false сохраняет старое поведение | `S:clearledger/server/app/config.py:42–46`: false и пустые expected identity. В `main` оба новых вызова за флагом; в `database` disabled branch вызывает прежний `Base.metadata.create_all`. Diff к base содержит только эти guarded вставки и новые настройки. Helper импортируется лениво; при false дополнительных gate SQL нет, public/Core bootstrap и регистрация модели остаются как в base. Это вывод из ветвления, без подсчёта runtime SQL. |
| Config missing, URL query и TLS | `S:clearledger/server/app/services/schema_version_gate.py:17–31`: разрешён только postgresql+asyncpg без query, default port 5432; `Config.validate` из `B:clearledger/server/schema_migrations/runner.py:31–44` требует непустые ожидаемые database/user допустимого формата, совпадение с URL, host/password, отсутствие fragment/query и namespace core. Пустые expected identity отказывают. Query, включая TLS/options, целиком отвергается в managed режиме, а не удаляется. Helper использует существующее соединение; он не создаёт новое с ослабленными TLS/options. Поддержка query-based TLS здесь отсутствует по явному ограничению; handshake не проверялся. |
| Ошибки и cleanup | `S:clearledger/server/app/services/schema_version_gate.py:38–66,73–81`: общие ошибки без DSN/catalog details, 10 секунд на borrowed check и 15 секунд на engine scope, контекстные менеджеры для owned connect/transaction. Borrowed helper не вызывает commit/rollback/close или execution_options. Owned helper задаёт REPEATABLE READ/readonly до begin; receipt сообщает параметры, но сам не используется как дополнительный assertion. Async cancellation/rollback/pool reset требуют runtime evidence. |

## Воспроизводимые supporting source hashes

Все supporting исходники читались из Git base, не из чужого рабочего дерева.
Ключевые SHA256:

| Путь относительно `clearledger/server/` | SHA256 |
|---|---|
| `Dockerfile` | `a34cfbbefe26f0864f7bfce33df844fffea75023947d0d85536646da1f26ae09` |
| `requirements.txt` | `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0` |
| `app/models_product_budget.py` | `ea09966027934d4455770c6fdddc62d6d3ccd943f8923d47e3f1a3c7153de864` |
| `schema_migrations/runner.py` | `375a6f68ca9024895e463584b7f79201b48500ab527d9cdcab16fdc0b2f41504` |
| `schema_migrations/manifest.py` | `55e5d7caca47c6bbd243f1e02e9e8a764b163067b16cd8eb41052967e4c78a09` |
| `schema_migrations/manifest.json` | `ef4189a61f162c81dda01b6602eae3a362c242e95ee954c6c971db9ff6404116` |
| `schema_migrations/catalog.py` | `6460f815ecb53436981c3633769a5792642824923197f5cf15277c31f356a242` |
| `schema_migrations/journal.py` | `16394ef23a5074c5c42c7780b30e15389c5eb4e6b03fb79a0afc1539db18fe39` |
| `schema_migrations/revisions/catalog_v1.py` | `ae3c42d51a7e7e37ee293b2c64f73addd421cf792b63af6bed6c36b1ed5f24f5` |

## Что выполнено и что осталось непроверенным

Выполнены сравнение трёх существовавших файлов с `git show` base, чтение нового
helper и достижимых frozen verifier/history путей, статический разбор ветвей,
`ast.parse` и `compile` всех четырёх копий **без исполнения code object**.
Синтаксических ошибок не найдено. Эти действия не импортировали приложение или
Foundation и не загружали Settings/.env.

Не выполнялись imports, tests/collect, DB/SQL, SSH, browser, сборка/запуск образа,
чтение реального окружения/ключей или проверка живой инфраструктуры. Git push
отчётной ветки является отдельно порученной доставкой результата, не проверкой
целевого сервиса. Frozen Foundation, manifest, V1 SQL и verifier не изменены;
результат прежних 14 pure + 13 PG проверок не воспроизводился и не расширяется
на этот gate.

Остаются непроверенными: успешный managed startup в реальном образе, настоящая
граница SQLAlchemy 2.0.36/asyncpg 0.30.0, readonly/isolation на сервере,
таймауты и возвращение соединения в пул после raw-driver cancellation, отсутствие
остаточной/aborted транзакции, конверсия readiness в реальном ASGI запросе,
фактический набор DDL при metadata exclusion и ноль дополнительных SQL при
false. Для readiness получение `await db.connection()` находится **до** входа в
10-секундный helper timeout (`S:clearledger/server/app/main.py:682`); поэтому 10 секунд не являются
лимитом всего readiness запроса. Общий startup lock также вне helper deadline.
Контекстные менеджеры показывают предусмотренный путь cleanup, но строгий
wall-clock предел завершения cleanup одним source review не доказывается.

Scope gate ограничен Core budget ревизией и её prerequisite/history; прочие
legacy миграции и seed продолжают выполняться. Отчёт не является security scan,
сертификацией всей схемы или разрешением merge/deploy. Исправления F1 и будущие
кандидаты принадлежат владельцу реализации; этот снимок остаётся отдельным
объектом проверки.


## Приёмка отчёта координатором

Source report commit `71e22a3cae343bbe6645539ca30525f2d600e4ef` перенесён
в integration как `6e0ca835`. Root повторно проверил SHA manifest снимка,
четыре source SHA и девять supporting Git pins относительно exact base.
Report SHA до этой приёмки: `94ac822d1cde2a972352697fd90ca4050748789c2d204c57d5e96bfed4c485a1`.
Это проверка целостности отчёта и подтверждение source finding F1; новый
security scan и runtime проверки не выполнялись.

Владелец получил разрешение добавить COPY frozen package в Dockerfile.
Исходный push-src script пакует весь server; `.dockerignore` не исключает
пакет. Сборка образа, доставка на ВМ и приёмка будущего candidate этим
source-only review не подтверждаются. Текущий отчёт остаётся исторической
проверкой снимка, последующее закрытие F1 отражается в cutover report.
