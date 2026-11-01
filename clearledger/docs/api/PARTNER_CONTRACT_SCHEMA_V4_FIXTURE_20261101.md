# Native fixture schema0004: исходники для отдельного прогона ROOT

Статус **SOURCE-only, runtime NOTRUN**. Base
`aaf472b8123bf1d01538049ef8b5308c9b72fd6b`, Task `task_eda7770863f3`,
Dispatch `ctx_91dad10f4b5e`. Изменены ровно пять разрешённых путей: новый fixture,
новый approval, только admit-import/comment в существующих cases, этот MD и парный
JSON. Все остальные байты cases, включая 13 групп, варианты, DSN, SQL и assertions,
сохранены. Schema/DDL/catalog/manifest/database/models/main и frozen Core3 не менялись.

Это конкретная тестовая оснастка native Core. Она не владеет production bootstrap,
не выбирает существующую БД, не создаёт контейнеры/роли/порты, не запускает server,
pytest, conftest, lifespan, seed_data, seed_apps, seed_info или jobs. Она не создаёт
execution envelope и не выдаёт себе разрешение. Старые Root99 helper PASS,
native18 FAIL/9 PASS, Core3 и 23 offline schema4 PASS не являются её runtime proof.
M00–M19 и исходные 11 общих условий остаются в scope и не объявлены выполненными.

## Конкретный API и порядок

После независимого freeze и admission в новом private namespace ROOT вызывает
этот async context manager из собственного уже проверенного envelope:

```python
from tests.partner_contract_schema_v4_approval import require_running_approval
require_running_approval()  # раньше app/ORM/driver/fixture imports
from tests.partner_contract_schema_v4_fixture import native_world, catalogue_coverage
from tests import partner_contract_schema_v4_cases as cases

# Внутри coroutine ROOT; отдельный CLI runner здесь не создаётся.
async with native_world(prefix=3) as f:
    await cases.fresh_continuation_repeat(f['conn'], f['config'], 3)
    from app import database
    physical4 = await catalogue_coverage(f['conn'], database, prefix=4)
```

Для lifecycle ROOT берёт **другой новый** world через `native_world(prefix=4)` и
передаёт `f['w']` одной выбранной case function. Каждый drift, occupancy и destructive
вариант получает отдельный disposable namespace. Нет reset, TRUNCATE, DROP или
очистки при выходе: закрываются только соединения и настоящий native engine;
удалением owned container занимается ROOT. `asyncio.timeout` охватывает создание
и тело context manager, срок берётся из private contract ROOT, максимум 1200 s.

Порядок builder:

1. Обязательный `require_running_approval()` с filesystem admission: чтение
   private contract, lease и frozen source/helper closure. Только после успешного
   admission проверяется prefix; допустимы только 3/4. Prefix0–2 отклоняются
   **до runtime app/ORM/driver imports и DB I/O**, но после filesystem admission.
2. Raw connection к точному DSN, read-only `preflight_identity(conn)`, пустые
   `core`/`edge`, исходное отсутствие всех шести таблиц0004.
3. Реальный `runner.execute_sequence(target_revision=manifest.PULSE_ID,
   fresh_prerequisites='core_prerequisites_v1', legacy_sent_before=2000000000)`.
   Frozen literal prerequisites +0001/2/3 идут штатным owner. Это промежуточная
   десятитабличная проекция; полным native Core она не называется.
4. Полный настоящий `app.main` со всеми его imports/route composition, проверка
   origins, native settings, `preflight_startup_sources`, `require_startup_schema`,
   native `database_startup_lock` и **неизменённый** `database.create_all()`.
   Нет подмены metadata/DDL/commands, patch функций или отдельных sinks.
5. Проверка, что шесть0004 по-прежнему отсутствуют, journal имеет настоящий3,
   calendar проверяется через явный **manifest.CALENDAR_ID**, затем registry /
   metadata / catalogue coverage и реальные native ORM parents/children.
6. Проверка всех actual incoming FKs безопасных delete parents, native0004
   prerequisites. Для prefix4 — явный apply0004 и повторное coverage.

Source-рецепт основан на read-only
`api-schema-gate-history-20261031/.../core_bootstrap_sequence_cases.py::Context.setup/prefix/prepare`
и текущем `runner.execute_sequence`. Старый helper не импортируется. Current
`create_all` требует Core Pulse3 до первого legacy DDL; `_prepare_database_once`
добавил бы `_prepare_database` с seed/backfill и startup marker, которых задача
не требует. Поэтому вызывается его настоящий DDL-owner напрямую. Сама native
`create_all` сохраняет встроенные catalog UPSERT, incremental DDL/backfill и
readiness validation; они не заглушены и входят в будущие реальные эффекты.
Подготовка десяти таблиц без последующего полного native этапа недостаточна.

Prefix0–2 **не построены**: current startup требует3, а полный native downgrade
source-рецепт не доказан. Fixture сначала выполняет `require_running_approval()`
с filesystem I/O; только после успешного admission отказывает prefix0–2 до
runtime app/ORM/driver imports и DB I/O. Без private contract первым будет отказ
admission, а не отказ prefix. Все случаи prefix0–2 остаются обязательными/NOTRUN.
Это описание исправляет неточный docstring `native_world`; helper bytes и порядок
кода сохранены. Удаление journal или переименование managed
calendar в «доревизионный» не применяется. `head.parent` при head4 — Pulse3;
старое `head.parent.contract` не является calendar contract.

## Полнота и native lifecycle

Frozen source inventory: **535** app/schema source files, **14 634 443** bytes,
канонический SHA256
`0ee5f6b05c6988af5260b365bb3f0cdd6ee9e0dd88b1e5919a74e1b3a21aa7d1`.
Формат manifest — отсортированный JSON-массив `[relative_path, bytes, sha256]`,
`separators=(',', ':')`, ASCII. Включены `.py/.sql/.json/.yml/.yaml` под `app/`
и `schema_migrations/`; executable runtime dependencies/envelope ROOT проверяет
отдельно. Полные source entries и AST model inventory находятся в парном JSON.

AST текущих шести `models*.py` даёт 337 named models, registry SHA256
`908ed501126a74b20ee97b4a790e41f4371d90dad5a0a18d7e49e744aead9f49`:
models.py316, partner12, partner_contracts6, product_budget1, dedup1, docs_portal1.
Это ожидаемый source set, **не доказательство runtime completeness**. Код требует
точного совпадения qualified mapped class/table names, metadata table set и
origin каждого app/schema module, включая настоящий PEP420 bootstrap namespace.
Проверяются реальные таблицы/owner/relkind, наличие каждой mapped column,
упорядоченные PK, каждый declarative FK/target/action, validation и четыре
enabled internal RI triggers каждого physical FK. Native дополнительные columns
и FKs возвращаются поимённо с actual types; полная type/default equivalence всех
старых моделей не заявляется. Точные0004 columns/types/defaults/constraints/
indexes/functions/triggers/ACL проверяет неизменённый native revision verifier.

Для этого empty-edge energy baseline ожидается физический set:

| Этап | Модельные таблицы core | Дополнительные raw core | edge | Всего ожидается |
|---|---:|---:|---:|---:|
| После native create_all, prefix3 | 331: все337 кроме шести0004 | 5 | 1 | 337 |
| После explicit0004, prefix4 | 337 | 5 | 1 | 343 |

Пять raw core: `accounting_adjustments`, `accounting_closing_date`,
`contract_types`, `edge_packet_revision_decisions`, `core_schema_versions`.
Единственная edge table — `edge.nsi_proposal`, создаваемая настоящим native DDL.
`edge.item` отсутствует; SKU/MATRIX/MARK_GROUP/LOCAL_BARCODE ветви не включаются,
их store-only raw tables не обещаны. Это полный текущий native **Core** с полным
model registry; provisioned Edge/станция не входят в него. Табличные количества
выше только вывод named set, код не принимает одну цифру276/337 за покрытие.
Managed budget0001 и Pulse0003 созданы их owner до native DDL; native managed
mode исключает budget, Core исключает Pulse, во всех namespace исключаются шесть0004.

`w` содержит `company, app, installation, grant, user, organization, counterparty,
contract, contract_location` (UUID), `client, location, type_code` (строки).
`installation` одновременно CompanyApp UUID. Создаются настоящие Company/App/
User/Organization/Counterparty/ServiceLocation, UserCompany, CompanyApp,
PartnerClient, PartnerInstallation, machine PartnerGrant, PartnerInstallationLocation,
Contract с creation_actor_id и ContractLocation. Использованы native ORM/defaults;
`contract_types` вставляется raw SQL в настоящий native справочник, ORM типа не
выдумана. Нет логина/токенов/issuance/domain CREATE/HTTP/audit dispatch.

Все incoming FKs к User/Contract/location/grant/install/App читаются из actual
catalogue. Допускаются только одиночные известные native children world с
CASCADE/SET NULL; любые блокирующие или посторонние строки дают отказ. Проверка
не удаляет строки/constraints и не отключает triggers. Сами случаи удаляют
Contract и User настоящими DELETE: ContractLocation/UserCompany каскадируются,
intent current pointers очищаются native FK SET NULL, immutable provenance и
historical location остаются. Удаление location снимает approval и installation
child, история сохраняется; profile→grant→install→App не каскадирует success history.
Profile/principals/typed refs/types/intent children создают неизменённые cases.
После записи native parents новая ORM session читает каждую committed row и
composite children; writer identity map не принимается за persistence proof.
Prefix4 дополнительно выполняет SELECT всех mapped columns каждой из шести
пустых owner-created таблиц: это проверка SQL shape, не ORM write roundtrip0004.

## Admission contract, который отдельно готовит ROOT

`partner_contract_schema_v4_approval` не исполняет проверку при импорте; первый
явный `require_running_approval()` обязателен до app/ORM/asyncpg/schema/fixture
imports. Повторные вызовы заново сверяют contract/source/lease; fixture import
дополнительно требует уже активный admission. Никакого нового env bypass нет.
Явный admission включает filesystem I/O и предшествует проверке prefix внутри
`native_world`; отсутствие всего filesystem I/O до отказа prefix не обещается.
ROOT включает `sys.dont_write_bytecode` (`-B`) и убирает project bytecode caches
из своего нового frozen source mount; app/schema/tests caches отклоняются.

Единственный путь — `/test/control/partner-schema4-approval.json`: обычный файл
root-owned, mode0444; `/test` и `/test/control` root-owned без group/other write,
без symlinks. Python работает non-root. Имя файла не authority: ROOT должен
независимо проверить и readonly mount source, helper bytes, actual новый owned
container, нулевой список published ports, DB/role/namespaces/OIDs и budget, а
потом выдать private process-bound lease. Worker не создавал такой файл.

Контракт имеет только следующие верхние поля:

- `profile`: fixed `partner-contract-schema4-native-v1`.
- `source_root`, `working_directory`: exact current absolute paths; в cwd нет `.env`.
- `immutable_source`: exact fixed SHA/bytes/files выше; actual bytes пересчитываются
  против этого ожидания. Это integrity, само по себе не разрешение.
- `helpers`: ровно три именных helper файла, для каждого independently frozen ROOT
  `sha256` и `bytes`; approval включает собственные bytes через внешний контракт.
- `target`: fixed database/user/host/port и положительные actual `database_oid`,
  `role_oid`, `core_oid`, `edge_oid`. Фиксированная синтетическая цель:
  `api_partner_contract_schema_v4_test_20261101`, `127.0.0.1:33546`, `clearledger`.
- `run_lease`: ROOT `run_id`, nonce, exact Python PID + `/proc/self/stat` starttime,
  issued_at/expires_at с длительностью ≤1800 s. Чужой процесс/PID reuse/expired
  lease/изменение contract отклоняются.
- `disposable_namespace`: exact64hex container_id, `published_ports=[]`,
  `source_read_only=true`, `independently_verified_by_root=true`; это аттестация
  ROOT, не проверка Docker со стороны fixture.
- `runtime_seconds`: integer1..1200.

Обе env URL равны неизменённому EXACT_DSN cases с synthetic password
`api_test_only`; APP_ENV=test, MANAGED_CORE_BUDGET_ENABLED=true, expected DB/user
равны target. Никаких query redirects, иных DSN, админской роли или fallback.
Администратор заранее создаёт пустые owned core/edge и устанавливает btree_gist,
pgcrypto, uuid-ossp вне core, задаёт native role/database search_path ровно core;
fixture это не исправляет. PostgreSQL слушает33546 **внутри нового namespace**,
host-порт не публикуется и никакой существующий PG/порт не резервируется.

Отдельный `preflight_identity(conn)` после admission выполняет только SELECT:
actual PG16, DB/user/search_path/server address/port, ROOT OIDs, владельцы core/edge,
origin replication и отсутствие SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS,
наличие трёх admin extensions. Он не владеет транзакцией, не делает SET/DDL/locks.
Root-owned attestation не заменяет независимую проверку execution envelope.

## Все исходные 13 групп и варианты

Для каждой строки обязательны описанный admission, actual identity и новый
native world. Все строки **NOTRUN**, включая поддержанные builder prefix3/4.

| Группа / функция | Варианты и отдельные world | Fixture prefix / граница |
|---|---|---|
| fresh-continuation-repeat / fresh_continuation_repeat | prefix0,1,2,3; apply/check/repeat + один owner/transaction | 3 authored; 0–2 обязательны/NOTRUN, отказ после filesystem admission, до runtime imports и DB I/O |
| old-prefix-required / old_prefix_required | prefix1,2,3,4; каждый ancestor/successor required; explicit3 не применяет4 | 3/4 authored; 1/2 обязательны, recipe отказан |
| occupied-no-adopt / occupied_no_adopt | partial, index-name, type-name, array-name, function-name, exact-unrecorded | 3, шесть отдельных world |
| catalogue-drift / catalogue_drift | default, null, check, fk, index, predicate, trigger, function-path, function-security, acl, rls, options, column, column-type, unknown-check, check-inheritance, fk-action, extra-index, function-acl, function-overload, extra-trigger, foreign-namespace | 4, 22 отдельных world; в каждом check/apply |
| prerequisite-drift / prerequisite_drift | missing, null, type, key | 3, четыре отдельных world |
| history-drift / history_drift | future, foreign-owner, adopted4, foreign4 | 4, четыре отдельных world |
| rollback-cancel / rollback_cancel | cancel=False/True × prefix0/3, fault после настоящего DDL4 | 3 authored; prefix0 остаётся обязательным без recipe |
| unknown-commit / unknown_commit | один настоящий COMMIT и потерянный ACK; check + явный повтор | 3, отдельный world |
| principal-xor-typed-ref-unique / principal_typed_refs_unique | foreign company; defaults/generation0; user/machine unique; 4 invalid principal tuples; org/CP/location unique; 4 invalid ref tuples; type duplicate/missing/blank; blank location | 4 + реальные w parents |
| success-namespace-immutable / success_namespace_immutable | namespace/child duplicate; 8 invalid intent changes; 6 immutable column changes; child UPDATE/DELETE; late INSERT; отдельный machine success | 4 + реальные w parents |
| current-fk-tombstones / current_fk_tombstones | Contract DELETE, User DELETE, полная parity snapshots, history location, runner check | 4 + native ContractLocation/UserCompany и safe delete dependencies |
| approval-ref-deletes / approval_ref_deletes | location approval; Contract DELETE → location DELETE; approval исчезает, snapshots остаются | 4 + safe native world |
| parent-history-retention / parent_history_retention | profile → grant → installation → App DELETE; только current User/Contract FKs у history; явный history DELETE каскадирует children | 4 + safe native world |

## Source-проверка и передача

В этой работе разрешены и выполнены только чтение файлов/Git, stdlib AST/hash/JSON,
in-memory compile без exec и `git diff --check`. Application/helper/test modules
не импортированы, функции не запускались, collection/pytest/SQL/SSH/Docker/Node/
network отсутствуют. Private approval и живой execution envelope не создавались.
Ошибку native DDL/mapping/coverage будущий запуск обязан сохранить как FAIL либо
конкретный отказ; исправлять чужие owners из fixture нельзя. Реализованный builder
не гарантирует, что существующий native bootstrap пройдёт; это предмет ROOT runtime.

| Source | Bytes | SHA256 |
|---|---:|---|
| tests/partner_contract_schema_v4_approval.py | 8363 | b04d51a5f7dcf9bc58d743e3ef4b05cac9dfa123dff27d1d4bbfdf0091d40958 |
| tests/partner_contract_schema_v4_fixture.py | 26272 | f58d08b78bde7b999d919181b4779f6d3452922a3573541cfbab54d3ead25698 |
| tests/partner_contract_schema_v4_cases.py | 28676 | 9a01b637de8f8740ae4852eba044b50d24973d5d4f6d0dc8a8a032f28501dde7 |

Остаются source review/freeze ROOT, отдельный реальный PG16 запуск с новым
execution envelope, физические DDL/ORM/lifecycle proof и законный full-native
prefix0–2 recipe. Общая schema4 и программа M00–M19+11 не имеют статуса PASS.
