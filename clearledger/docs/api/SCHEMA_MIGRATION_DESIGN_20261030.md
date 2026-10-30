# M16: владельцы схемы и дизайн versioned runner, 30.10.2026

**SOURCE ONLY.** Runner, migration SQL и изменения startup здесь не реализованы.
SQL, app imports, pytest collection, DB connections, SSH, browser, restore,
EXPLAIN/ANALYZE и выпуск **NOT RUN**. Подготовлены inventory и implementation-ready
дизайн первого узкого managed slice; вся программа M00–M19 остаётся открытой.

## Immutable основа и воспроизводимость

Основа: `ccfcd653f5cc01490bbf8571f9e89eae4a230ead`, ветка
`agent/api-schema-migration-audit-20261030` в уже выделенном worktree.
Общие рабочие деревья и прежняя ACL-ветка не переключались; pull не выполнялся.
Прочитаны родительские CLAUDE/AGENTS, `clearledger/CLAUDE.md`, rushydro-space,
предыдущие namespace/compatibility proofs. Private deployment изучен только
чтением; данные, SQL, tenant/host/role identifiers и secrets оттуда не копируются.

Источники ниже относятся к **одному указанному immutable commit**; line numbers
относятся к нему, не к будущей ветке. Полные blob IDs/SHA256/число строк ключевых
файлов сохранены в `scripts/SCHEMA_SOURCE_INVENTORY_20261030.json`.

`inventory-schema-owners.py` — stdlib source analyser, не migration runner:
читает только локальные Git objects точного SHA, выполняет AST parse; не делает
import app/ORM/config, не читает `.env`, private deploy, сеть и БД. Вывод —
только пути/строки/hashes/counts. Никакого исполнения извлечённых строк или `eval`.
Python >=3.12 нужен для синтаксиса исходного приложения; проверено Python 3.13.7.

```sh
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I \
  clearledger/scripts/inventory-schema-owners.py
```

Ограничения: <=4096 tracked server paths, <=2 MB на прочитанный файл,
<=128 SQL-looking source files; scope — `server/app/**/*.py` и fixed source pins.
Не охватывает shell/SQL scripts, dynamically assembled SQL без узнаваемого
префикса, SQL из внешних библиотек и не устанавливает runtime reachability.

## Инвентарь существующих владельцев

AST просмотрел **478 app Python files**. В **9 файлах** обнаружены **1150
DDL-looking string literal nodes**, из них **1114** в `database.py`; там же
**80 DML-looking nodes**. Это количество literal AST nodes с распознанным SQL
префиксом, а не число SQL statements, вызовов БД или применённых миграций.
DO bodies, циклы, f-strings, fragments и selectors не разворачиваются.
Объявлен **21 `*_DDL` symbol: 19 tuple + 2 selector expressions**.
Генератор исключает docstrings; generic string values вроде `grant` не считаются DDL.
Количество таблиц живой БД/полной зарегистрированной metadata здесь не измерялось.

| Владелец | Source evidence | Текущая граница |
|---|---|---|
| Bootstrap lock | [server/app/database.py:49](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/database.py#L49) | `pg_advisory_xact_lock(434532,1)` на выделенном connection; caller обязан взять его сам. |
| Namespace guard | [server/app/database.py:2206](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/database.py#L2206) | До PHONE/metadata: visible table-like `r,p,f,v,m` должны принадлежать current_schema; standalone public допустим; это не catalog-shape verifier. |
| PHONE + metadata | [server/app/database.py:2231](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/database.py#L2231) | Импорт budget model, guard, PHONE function, `Base.metadata.create_all` в первой транзакции. Metadata включает модели с schema=None и explicit edge; create_all не эволюционирует существующие колонки. |
| Legacy incremental | [server/app/database.py:2244](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/database.py#L2244) | Вторая транзакция: ALTER/CREATE/backfills, conditional edge groups и legacy data repair. Ошибка здесь не откатывает уже committed metadata phase. |
| Best-effort legacy indexes | [server/app/database.py:3084](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/database.py#L3084) | SAVEPOINT на текущем connection, exception logged/swallowed; успешный startup не доказывает наличие всех индексов. |
| Post-bootstrap readiness DDL | [server/app/database.py:987](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/database.py#L987) | Две отдельные транзакции collision-report/readiness; вызов после incremental commit на строке 5540. Вся create_all не атомарна. |
| Startup preparation | [server/app/main.py:142](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/main.py#L142) | create_all → seed → timezone/perimeter/app/info preparation → cleanup interrupted runs; несколько sessions/commits и best-effort exception branches. |
| Startup completion marker | [server/app/main.py:190](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/main.py#L190) | app_startup_runs по container instance_id; own CREATE + commits, не version journal и не migration checksum. |
| Lifespan | [server/app/main.py:251](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/main.py#L251) | Обёртывает preparation общим startup lock; прямые callers create_all не обязаны его брать. |
| Perimeter | [server/app/routers/perimeter_router.py:53](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/routers/perimeter_router.py#L53) | 20 DDL literals; каждый statement commit, ошибки rollback/swallowed; вызывается startup, не versioned migration. |
| Application catalog seed | [server/app/services/app_registry.py:294](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/services/app_registry.py#L294) | Schema ALTER перед seed, commit/rollback best effort; DDL живёт вне database.py. |
| Lazy cache | [server/app/services/analytics_cache.py:90](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/services/analytics_cache.py#L90) | CREATE table/index в собственной session; process-local _table_ready, не глобальный migration owner. |
| Lazy aggregate mart | [server/app/services/charge_mart.py:71](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/services/charge_mart.py#L71) | CREATE table/index в отдельной session; вызывается из ingest/reference path, не только startup. |
| Websocket presence | [server/app/services/chat_ws.py:90](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/services/chat_ws.py#L90) | CREATE UNLOGGED table/index + cleanup; другой advisory key (434532,2), не startup/migration lock. |
| Phone function | [server/app/services/phone_e164.py:32](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/services/phone_e164.py#L32) | DDL dependency до generated columns; owner вызывается bootstrap. |
| Declared station-move DDL | [server/app/services/edge_moves.py:24](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/services/edge_moves.py#L24) | 7 DDL literals в tuple; runtime wiring этого tuple source scan не установил, исполнение не утверждается. |
| Readiness endpoint | [server/app/main.py:673](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/main.py#L673) | Проверяет часть current-schema contracts; не полный schema diff и не журнал миграций. |
| Direct test/utility bootstrap | [server/tests/conftest.py:72](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/tests/conftest.py#L72) | Destructive public/edge fixtures вызывают create_all напрямую; server/scripts/smoke_full_sync.py:60 также вызывает его. Не эквивалент lifecycle lock. |

Граница ответственности: исторический bootstrap остаётся legacy owner; lazy
owners требуют отдельного переноса. Первый managed slice не делает runner
единственным владельцем **всей** существующей схемы. Таблица с schema=None
не становится Core-owned только из-за имени или наличия checkfirst.

## Alembic audit сохраняется audit

[server/alembic/env.py:1](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/alembic/env.py#L1): env явно документирует audit-only назначение.
[server/alembic/env.py:27](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/alembic/env.py#L27): импортируется app.main для полного metadata;
это не безопасный source-only probe. [server/alembic/env.py:40](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/alembic/env.py#L40): reflected
таблицы без model counterpart исключаются из diff, поэтому часть внешних объектов
не проверяется. [server/alembic/env.py:60](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/alembic/env.py#L60): core.alembic_version,
include_schemas=False, type/default comparison; online path делает SET search_path
и commit ([server/alembic/env.py:90](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/alembic/env.py#L90)).
[server/alembic/versions/20261025_01_baseline.py:13](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/alembic/versions/20261025_01_baseline.py#L13) — единственная
tracked revision `20261025_01`, parent=None, upgrade/downgrade содержат только
docstrings и не выполняют DDL. Её отметка не доказывает, что все legacy SQL прошли.
`alembic check/stamp` могут подключаться/записывать; здесь они NOT RUN.
Новый runner не вызывает Alembic и не читает его stamp как своё разрешение;
Support public.schema_migrations тоже отдельный журнал.

### Выбор механизма: отдельный release Alembic или bounded runner

Текущее audit environment неудобно для release; это **не** аргумент, что Alembic
неспособен обеспечить нужные гарантии. Отдельный release `script_location` с
изолированным env, без app.main/autogenerate и с собственным Core version table
может выполнить тот же explicit migration SQL. Тогда checksum/adoption/catalog
verifier, namespace preflight и common owner lock всё равно нужны как wrapper.
Alembic уже объявлен в `server/requirements-test.txt:6`; production packaging
release dependency ещё пришлось бы зафиксировать отдельно.

| Критерий первой revision | Отдельный release Alembic env | Самостоятельный bounded runner |
|---|---|---|
| Isolation от нынешнего audit | Новый env/script_location и Core version table | Новый небольшой package, не трогает audit |
| Strict adoption/OID/schema verifier | Собственный verifier/hooks | Тот же собственный verifier |
| Checksum изменённых applied artifacts | Дополнительный integrity protocol; head stamp этого не даёт | Один explicit journal с checksum/chain |
| Lock и transactions | Wrapper перед Alembic, запрет implicit commit/branch stamp | Один dedicated connection, явные transaction boundaries |
| Будущие DAG/branches/offline dialects | Готовые механизмы Alembic | В первой версии запрещены; иначе свой framework станет дорогим |
| Стоимость поддержки сейчас | Дополнительный env + wrapper + два вида истории, если сохранять head и integrity | CLI/journal/manifest надо сопровождать и тестировать самим; нет автогенерации |

Для **одной линейной transactional budget revision** выбран bounded runner:
ограниченный контракт, один integrity journal и отсутствие необходимости в
revision graph. Это не общий новый migration framework: only PG16, linear append,
нет autogenerate/downgrade/nontransactional revision. При появлении branches,
массового переноса legacy или нескольких dialects выбор пересматривается **до**
расширения runner; отдельный release Alembic остаётся допустимой альтернативой.
В любом варианте нельзя делать audit baseline родителем якобы применённой всей
исторической схемы или автоматически stamp существующую БД без catalog proof.

## Private deployment: только границы

Изучен read-only immutable deployment snapshot: provisioning path и пять
поставочных SQL sources; рабочие bytes совпали с соответствующими HEAD blobs.
Путь provisioning восстанавливает shared search_path после initial core-only
bootstrap и ориентируется на coarse table-count/health; это не fingerprint
доказательство схемы. Поставочные sources имеют transaction wrappers и свой
schema targeting, но в просмотренных текстах нет общего advisory owner lock
либо version/checksum journal. Отсутствие ON_ERROR_STOP внутри SQL-файла не
доказывает режим psql caller: фактический execution path/permissions не проверен.
Не найдено оснований автоматически считать эти scripts миграциями нового runner.

Для source review координатор получает отдельный приватный pin/path/line receipt
через orchestration. Public JSON намеренно не содержит private пути, SQL,
объекты/значения/сетевые имена. Legacy deployments, runtime drift, Support
runtime и рабочие базы по этому чтению не проверены.

## Предыдущие proofs и пределы их повторного использования

[docs/SCHEMA_NAMESPACE_OWNERSHIP.md:129](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/docs/SCHEMA_NAMESPACE_OWNERSHIP.md#L129) описывает уже принятый guard;
[docs/SCHEMA_NAMESPACE_OWNERSHIP.md:273](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/docs/SCHEMA_NAMESPACE_OWNERSHIP.md#L273) сообщает исторические 12 PASS,
включая foreign index/sequence positive и table/view/matview negatives. Это
результат прежнего dispatch, не нынешний повтор. Guard не даёт lock от другого
DDL owner и не проверяет структуру уже существующих Core relations.

[docs/PARTNER_SCHEMA_COMPATIBILITY.md:1](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/docs/PARTNER_SCHEMA_COMPATIBILITY.md#L1) описывает public/Core
профили и старые binaries. Текущий harness:
[server/tests/test_partner_schema_compatibility.py:53](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/tests/test_partner_schema_compatibility.py#L53) использует реальные
архивы `ce94e2bf30c0676208b1d70c5c135fe91d1a23f2` и
`5ce5779b20151a8d04de7d3a1681d1862a80d9dd`, exact owned model manifests,
catalog/type/default/FK/constraint/index assertions и old HTTP/ORM coexistence.
Эти архивы не заменять удалением новых моделей из current metadata. Ни старые
proofs, ни нынешний inventory не доказывают versioned runner или restore.

## Решение: отдельный managed Core runner, первая версия ограничена budget

Все следующие имена/пути — **предложение для следующего dispatch**, файлов runner
и SQL сейчас нет. Новый режим требует target namespace ровно `core`. Прежний
standalone-public bootstrap сохраняет прежний контракт и не мигрируется скрыто.
Managed Core не импортирует app.main/config/database/models, не стартует seed,
schedulers/HTTP/listeners и не пользуется `.env`/default URL.

Предлагаемый package: `server/schema_migrations/` с `runner.py`, `manifest.json`,
`catalog.py`, `journal.py`, `revisions/0001_product_api_budgets.sql` и явным
immutable contract verifier. Artifact registry — ordered allowlist, никакого
обхода произвольной папки/автогенерации SQL из текущего ORM в момент apply.
Source-only plan выводит только registry/hash без подключения; DB status/check
readonly, apply отдельная операция. Fresh bootstrap отдельная команда/поставка,
не implicit fallback при отсутствии prerequisite tables.

### Предлагаемые API и состав следующей реализации

| Файл | Минимальный API / запрет |
|---|---|
| runner.py | CLI `plan` (source-only), `check` (readonly DB), `apply` (explicit target); `run(config, mode) -> exit_code`; не запускается на import |
| manifest.json | frozen ordered revisions: id, parent, SQL/verifier/contract hashes; exact allowed target core |
| catalog.py | `inspect_prerequisites(conn)`, `verify_budget(conn) -> ContractSnapshot`; explicit OID/schema/attnum checks, read-only |
| journal.py | `read_verified_history(conn, manifest)`, `append_applied(conn, revision, action)`; transaction commit принадлежит runner |
| revisions/0001_product_api_budgets.sql | Только frozen qualified additive budget objects; parent DDL/DML/role/global GUC запрещены |
| verifier contract artifact | exact typed columns/FK/check/index/owner requirements, canonical representation + verifier source hash |
| будущий isolated harness | actual own synthetic catalog/failure/concurrency tests; общий destructive conftest не включать неявно |

Exit contract: 0 verified/no-op/applied; 2 invalid CLI/manifest; 3 namespace/target/
permissions; 4 history/integrity/catalog mismatch; 5 lock/deadline; 6 apply failure.
Безопасный error code/revision/phase, без URL/SQL parameters/строк данных в stdout.

Порядок **до первой durable записи**: проверить manifest/checksums без БД →
explicit target guard → readonly connection identity/core/permissions/prerequisite
catalog → bounded owner lock → повтор catalog/history под lock (без TOCTOU между
двумя cooperating owners) → полный existing-table verifier для adoption. Любой
unknown/wrong объект отказывает до journal CREATE. Только после этого начинается
transaction с journal CREATE при отсутствии, create/adopt, postconditions и append.
Неправильный existing journal тоже никогда не пересоздаётся автоматически.

Первый implementation package — только CLI foundation + catalog + одна revision
и actual isolated synthetic tests, **без managed startup/Compose activation**.
Он не ready/enabled для выпуска и выполняется лишь явной отдельной командой в
synthetic harness; наличие команды не создаёт нового owner работающего startup. Cutover и его проверки ниже — отдельный обязательный gate перед managed
activation, а не скрытая часть первой source-only задачи.

### Namespace и preflight

- Explicit connection config + expected DB/user/namespace identity. Проверки
  пользователя/базы/схемы/прав выполняются до DDL; совпадение строк URL — intent,
  а не доказательство владения. Для synthetic run используются отдельные guards.
- Namespace core должен существовать с заранее provisioned ownership/USAGE/CREATE;
  runner не создаёт schema/roles и не делает ALTER ROLE/ALTER DATABASE.
- Только per-connection core-only path, current_schema=core; public fallback
  исключён. Все managed tables, indexes, FK references и journal квалифицированы
  `core`, catalog queries — pg_catalog. Не переквалифицировать весь legacy ORM.
- Relation identity проверяется по namespace OID + relation OID/relkind,
  referenced constraints по conrelid/confrelid/attnums. Нельзя принять одноимённую
  public/temp relation, view/matview/FDW за managed ordinary Core table.
- Existing correct core table + public same-name не ошибка сама по себе;
  foreign index/sequence не подменяет table owner. При missing core prerequisite
  — отказ с generic provisioning error, без копирования/переименования Support.

### Один lock, один внешний owner и отсутствие self-deadlock

Global cooperative key остаётся **двухкомпонентным (434532,1)**, тем же key space,
что у database_startup_lock. Нельзя заменить его однокомпонентным hash lock и
считать эквивалентным. Внешний CLI держит session advisory lock на **одном dedicated
NullPool connection** весь batch, с bounded try-acquire и общим deadline.
DDL/journal transactions проходят на этом же connection; finally release/close,
при потере процесса lock освобождается PostgreSQL с connection. После lock-acquire
SELECT/implicit transaction завершается явно до очередного begin; dirty/failed
transaction не передаётся дальше. Другой runner после ожидания перечитывает journal.

Session lock выбран, чтобы держать ownership через несколько commits и failure
rollback. Он должен конфликтовать с прежним xact lock того же pair; это отдельный
обязательный synthetic concurrency control, а не выполненное здесь утверждение.

**Запрещённый call graph:** lifecycle держит startup lock connection A → runner
на connection B пытается захватить тот же key → ожидание самого себя. CLI запускается
до managed startup. Managed startup под прежним внешним lock делает только readonly
version/contract gate и разрешённый legacy preparation, не вызывает CLI apply.
Новый внутренний executor, если когда-либо потребуется, принимает уже locked
connection явно и не захватывает lock/не открывает второй connection; сейчас не нужен.

Прямой вызов create_all либо ручной SQL не автоматически участвует в этом protocol.
Для managed deployment utilities/tests должны явно выбрать внешний lock/отдельный
DB window; private SQL owners должны присоединиться к тому же owner protocol или
быть остановлены на время apply. Lazy owners с другим key не считаются защищёнными
этим lock; первый slice не трогает их объекты. Advisory lock не блокирует
некооперирующий manual DDL: quiescence/внешний deploy mutex — обязательная граница.

### Журнал версий и integrity

Новый журнал: **core.core_schema_versions**, отдельно от Alembic и Support.
Его формат тоже immutable contract; существующий несовместимый одноимённый объект
вызывает отказ. Journal creation под owner lock входит в ту же первую транзакцию,
что migration/adoption; не оставляет fake baseline после её rollback.

| Поле | Требование |
|---|---|
| revision | text PK; точный id manifest, для первой версии `0001_product_api_budgets` |
| ordinal | integer NOT NULL UNIQUE, непрерывный prefix начиная с 1 |
| parent_revision | nullable text; первая NULL, остальные exact previous revision |
| artifact_sha256 | char(64) NOT NULL, exact content hash artifact package |
| contract_sha256 | char(64) NOT NULL, frozen postcondition contract |
| predecessor_sha256 | char(64) nullable, hash-chain предыдущего применённого artifact |
| action | text NOT NULL, только created/adopted |
| applied_at / applied_by | timestamptz NOT NULL default now / text NOT NULL |
| app_commit / runner_format | char(40) NOT NULL / integer NOT NULL, формат 1 |

Artifact hash охватывает id/parent, raw UTF-8 LF SQL bytes, canonical contract
JSON и pinned verifier/runner format manifest с length-delimited encoding.
Raw bytes не нормализуются после выпуска; newline/whitespace edit означает новый
artifact hash. Public package хранит ожидаемые checksums до apply, journal —
наблюдавшиеся применённые значения; изменение checksum applied версии — отказ,
не автоматическая перепись журнала. Verifier source тоже versioned/pinned.

В lock-protected transaction: validate journal shape → require applied rows равны
известному contiguous manifest prefix → verify applied artifact/checksum/parent →
verify actual managed catalog → apply next → verify full postconditions → append
row → commit. Unknown/newer revision, hole, changed parent/format/hash, duplicate
ordinal, unexpected contract drift дают nonzero exit до DDL. Отсутствие journal
не означает, что legacy bootstrap завершён: prerequisites проверяются отдельно.
Repeat verified head — no DDL, no DML и no journal UPDATE/append; drift не чинится.

Failed attempts фиксируются структурированным приватным process log с revision,
phase и безопасным error code; applied journal не содержит ложного failed/applied
stamp из откатившейся транзакции. Журнал — история успешных commits, не замена
операционному журналу попыток. Commit-result unknown при disconnect решается
новым отдельным status/check по journal/catalog после восстановления доступа;
автоматически replay/patch journal в том же запуске нельзя.

### Транзакции и ошибки

Первая migration исключительно transactional: ordinary CREATE TABLE/INDEX,
никакого CONCURRENTLY, autocommit, VACUUM, extension/role changes и destructive
DOWN. Один revision + postcondition + journal append — одна transaction. Сбой
на FK/index/check/postcondition/ledger insert откатывает весь revision, включая
первый journal CREATE; предыдущие успешные версии остаются committed.
Внешний lock сохраняется через rollback до закрытия runner.

Timeouts ограничивают connect/lock/statement/idle-in-transaction и общий процесс;
конкретные budgets задаются проверяемым harness следующего dispatch, не глобально
на роли/сервере. `SET LOCAL` используется внутри каждой transaction. Cancellation
не считается успехом и не отмечает версию. Никакого swallow-and-continue из legacy
best-effort blocks; команда завершает работу на первом отказе, без retries/fallback.
Нужные в будущем nontransactional migrations требуют отдельного workflow и review.

## Первая additive/adoption migration: 0001_product_api_budgets

Source contract: [server/app/models_product_budget.py:12](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/models_product_budget.py#L12); required
parent uniqueness: [server/app/models_partner.py:50](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/models_partner.py#L50). Runtime consumer:
[server/app/product_api/budget.py:94](https://github.com/Electro-Interfaces/ClearLedger/blob/ccfcd653f5cc01490bbf8571f9e89eae4a230ead/clearledger/server/app/product_api/budget.py#L94) (quota disabled не делает SQL).
Это перенос владения существующим контрактом, **не новая quota feature или индекс
оптимизации**. На данной основе таблица уже регистрируется legacy create_all;
поэтому для существующей установки нормальный путь — exact adoption, не CREATE
IF NOT EXISTS с предположением, что структура правильная.

| Колонка в порядке declaration | Exact contract |
|---|---|
| company_id | uuid, NOT NULL, PK position 1 |
| installation_id | uuid, NOT NULL, PK position 2 |
| client_id | varchar(64), NOT NULL, PK position 3 |
| used | int4, NOT NULL |
| reset_at | timestamptz, NOT NULL |
| request_limit | int4, NOT NULL |
| window_seconds | int4, NOT NULL |

У всех семи колонок нет server default, identity или generated expression.
Сохраняются три named CHECK из source: ck_product_budget_limit (1..1000000),
ck_product_budget_window (1..3600), ck_product_budget_used (1..request_limit+1).
Один explicit BTree index ix_product_api_budgets_reset по reset_at, не unique,
без WHERE/expression; PK backing index учитывается отдельно, не как второй
explicit index. Обычная logged table; constraints validated, indexes valid/ready.

Composite FK **в порядке installation_id, client_id, company_id** должен ссылаться
именно на **core.partner_installations(id, client_id, company_id)**, delete CASCADE,
update NO ACTION, NOT DEFERRABLE; проверять реальные OID/schema/attnums всех трёх
колонок и supporting parent UNIQUE, а не строковый suffix. Parent ordinary table,
его columns/unique/identity и approved ownership/permissions — prerequisites.
Нет разрешения создавать/переделывать parent либо его constraints в этом slice.

Две ветви под одним owner lock:

1. Таблицы в core нет: validate prerequisites → создать ровно эту таблицу,
   constraints и existing-contract index → полный catalog verifier → created row
   journal. Public objects не участвуют в разрешении FK.
2. Таблица в core есть: проверить точные columns/types/typmods/nullability/defaults,
   PK/order, FK/OIDs/actions/validity, CHECK expression semantics/names, explicit
   index definition/method/order/uniqueness/predicate/validity, relation kind/
   persistence/owner/ACL/RLS и отсутствие неожиданных user triggers. Автоматические
   PG constraint names сверяются семантически по frozen contract, не изобретается
   новое имя для rename. При совпадении — только adopted row journal.

Extra/missing columns, shadow FK, unknown trigger/RLS, wrong owner или invalid
index — отказ, без ALTER/REINDEX/rename/backfill. Row data не меняется ни при
create (таблица пуста), ни при adoption; CREATE/ALTER parent/DELETE quotas запрещены.
Synthetic adoption проверяет неизменность OID, ACL/catalog и всех маленьких старых
строк до/после при остановленных quota writers. Real live counters могут изменяться
другими writers: не требовать совпадения двух non-atomic customer hashes на живой
нагрузке и не выдавать это за snapshot proof. Политика backup/restore отдельная.

## Cutover owner и fresh/upgrade/old-code порядок

**Без этого cutover implementation runner не готов к включению.** Current Base
metadata включает budget table; только добавление CLI создало бы два DDL owner.
Следующий implementation dispatch обязан сделать явный managed-mode branch:

- Legacy metadata registration сохраняет модель для ORM/namespace guard, но
  create_all получает exact table subset без budget table в managed Core mode.
  Все прочие legacy tables/statements/order остаются под прежним bootstrap.
  Не удалять таблицу из общей metadata и не подменять модель в tests.
- Startup/app_startup_runs не apply/stamp версии. Managed readiness требует
  exact known journal head/checksum + catalog contract до приёма traffic;
  completion marker контейнера не позволяет обойти этот gate.
- Managed mode включается явно после provisioning и runner; standalone public
  и прежний legacy mode сохраняют своё поведение до отдельной миграции режима.
  На старый binary сам собой новый gate/ownership protocol не распространяется.
- DDL privileges runtime сейчас нужны legacy bootstrap. Этот first slice не
  заявляет их полного отзыва и не обещает единственного owner всех legacy tables.
  Migration connection использует согласованную Core role без cluster superuser;
  полный переход к отдельной DDL role — следующий этап после удаления остальных
  runtime schema writers.

Fresh managed DB: provision core/roles/extensions отдельно → locked explicit
legacy bootstrap на current archived schema-source с managed-table exclusion
(включая реальные partner prerequisites; без HTTP/seed side effects там, где они
не нужны; отдельный legacy adapter может импортировать pinned app только для
регистрации metadata без lifespan, runner этого не делает) → close old bootstrap sessions → внешний runner v1 → readonly gate →
managed startup. Пустая DB без legacy prerequisites вызывает отказ runner, а не
неявную генерацию всей исторической схемы. Ни одна версия legacy не отмечается
успешной одной записью нового journal.

Existing Core upgrade: проверенный backup/restore отдельным этапом → остановка
конкурирующих DDL owners → snapshot Core/public catalog + bounded synthetic rows
в тестах → внешний runner create/adopt → repeat verify → managed startup/readiness.
Все остальные объекты Core/public/edge и старые rows должны совпасть со snapshot.

Old code coexistence: архивы ce94e2bf/5ce5779b не знают новых журналов и не получают
новый gate; synthetic tests запускают их реальный bootstrap + прежние HTTP/ORM
операции на обновлённой БД, сохраняя public sentinels. На immutable ccfcd653 также
проверить старого quota consumer при enabled/disabled policy и существующих rows.
Нельзя требовать от ce94/5ce consumer, которого в тех версиях ещё не было.

Rollback приложения оставляет additive schema/journal на месте; DOWN/DROP не
предусмотрен. К старому legacy binary можно вернуться только по пройденной матрице;
older managed runner с unknown/newer history обязан fail closed, а не понижать head.
Backup restore должен восстанавливать application data **вместе с journal** и
соответствующим artifact package. Restore не равен запуску create_all поверх dump.

## Следующий dispatch: критерии synthetic приёмки (всё NOT RUN)

Только отдельный root GO после exact source/runner review и сериализация SQL
window. Own synthetic loopback PG16/test DB/UPLOAD, flags до app/DB imports,
common safety guard + фактический owner/database identity, clean env с исходным
HOME, Python -I, empty cwd, explicit asyncio plugin; fixture reset только своей
БД. Никакой production restore/role-wide GUC. Tests не используют fake catalog,
удаление моделей из current metadata или mocked advisory lock как доказательство.

| ID | Actual acceptance следующего dispatch | Сейчас |
|---|---|---|
| F0 | Empty core DB → runner refuses missing prereqs, zero DDL/journal/public writes | NOT RUN |
| F1 | Real filtered legacy fresh bootstrap → runner creates budget+journal only; all constraints/FK/index exact | NOT RUN |
| F2 | repeat F1 → catalog/OID/rows/journal unchanged, no write SQL | NOT RUN |
| U1 | exact existing ccf schema + populated quota rows → adoption, no row/catalog/OID/ACL mutation except own journal | NOT RUN |
| U2 | wrong type/nullable/default/PK/CHECK/FK public OID/order/index validity/owner → rollback, zero applied stamp | NOT RUN |
| U3 | old ce94/5ce real bootstrap then explicit current legacy prerequisites → v1; additive-only delta vs frozen snapshot | NOT RUN |
| N1 | missing/non-core namespace, Support-first public shadow, temp/view/foreign/matview target → early refusal | NOT RUN |
| N2 | correct Core + public same-name, foreign index/sequence → owned OIDs used, public preserved | NOT RUN |
| J1 | checksum edit/unknown or newer row/hole/parent mismatch/wrong journal shape → fail before DDL | NOT RUN |
| T1 | injected failure after table create, index create, validation and before journal commit → whole revision rollback | NOT RUN |
| T2 | disconnect/cancel/outer timeout → no false applied row; fresh status resolves ambiguous commit | NOT RUN |
| C1 | two real CLI processes race → exactly one apply, second rechecks verified head; lock timeout bounded | NOT RUN |
| C2 | old lifecycle xact lock A vs external session lock B same pair → mutual exclusion, no self-wait graph | NOT RUN |
| C3 | direct create_all utility in managed mode needs external owner; metadata exclusion/readonly gate cannot be bypassed by marker | NOT RUN |
| O1 | ce94/5ce real old HTTP/ORM roundtrips and current ccf quota enabled/disabled work on upgraded DB | NOT RUN |
| R1 | local synthetic dump → NEW owned restore DB → catalog/row/journal equality → verified repeat no-op → old/new reader | NOT RUN |

Для R1 отдельные dump/restore privileges, stop/reap/close и cleanup plan проверяются
до GO; dump listing не считается actual restore. Root независимо проверяет
child EXIT/teardown/connections/schemas и normal DROP, worker сам не повышает
max_locks/не делает DROP чужих БД. Полный legacy boot, concurrent migration,
реальный dump/restore, CI, production compatibility остаются непроверенными.

## Source-only validation и передача

- Выполнены чтение local immutable Git objects, AST inventory, Python compilation
  собственного generator и статическая сверка JSON/source pins; app не импортирован.
- Первый запуск inventory системным Python 3.11 отказал на синтаксисе pinned source;
  generator теперь явно требует >=3.12, полноценная генерация выполнена 3.13.7.
  Existing source books_links.py:144 дал SyntaxWarning об escape, файл не менялся.
- New runtime runner/migration SQL/DDL/config/tests не добавлены и не менялись.
  Исполняемый script здесь только source inventory с локальными Git reads.
- SQL/collect/connect/SSH/browser/restore/EXPLAIN/ANALYZE: **NOT RUN**.

### Ключевые source SHA-256

```text
2cc53c2e70aa85d734fd955d90c2c4c4027f1496f99f44b4bab6ddacf1bae758  clearledger/server/alembic.ini
65936a2e28a8e47793699f5aa4706a0bc22ec569c2412fa545859f7d6155b473  clearledger/server/alembic/env.py
7b07ddcc71aac8919513211fbab802089fa9bcbfef3a8429635365299168c88b  clearledger/server/alembic/versions/20261025_01_baseline.py
be856862b369d89da8c7993fd974b70481260f37f07b7ca5a6d20db6ac077c3c  clearledger/server/app/database.py
6311430edbdc2f642f18698e5e841e2807d53ec95f5cc25e7b7990962b8e1a17  clearledger/server/app/main.py
06bfb7c6f7bce8ac345dbcbe23ee642e932ec2a9341673b20a1205c4f3206fee  clearledger/server/app/models.py
57bce6f84b8992503e2069bc3b6f7a91be830adc1312269e7742309a19087c64  clearledger/server/app/models_docs_portal.py
51695adcc2784279fa00a0b2cccd99f181ee0a51cbf6232b8499adc0a7ada916  clearledger/server/app/models_partner.py
ea09966027934d4455770c6fdddc62d6d3ccd943f8923d47e3f1a3c7153de864  clearledger/server/app/models_product_budget.py
566769d8af2f093a0bc19c1c27335bc17cc8a924eaa2e8fefae9779e7b723318  clearledger/server/app/routers/perimeter_router.py
f8eea104f0c096521cc937b6367ebca30ddea485e6b271a59e37f60359346af5  clearledger/server/app/services/app_registry.py
02556ab614fe3ece60bbe4f216fec5b8eceb9b118cb976c20acc3df5cf5a8c0e  clearledger/server/app/services/phone_e164.py
9e43e83d14e5a18755f4508854a671bad3c81afa1312eb33a69ef8465e9991ec  clearledger/server/tests/test_partner_schema_compatibility.py
6aae402d3b571039146f8f1215f5a18eb431795ea69c0d012247a1cfcd176021  clearledger/server/tests/test_schema_namespace_ownership.py
```

Inventory JSON SHA-256: `a3634f237b56106acb295036a3f33b57bbced567efc809f0c52f0cd54212cf1d`.
