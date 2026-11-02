# CORE-B02: convergence владельца ServiceLocation, source-only

База: `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Ветка и дерево B: `/home/mag/orca/workspaces/ledger-app/service-location-writer-tests-20261031-2`, HEAD совпадает с базой. B пишет только новый тест и эти два отчёта; четыре production-файла принадлежат A. Коммитов, push и runtime не было.

**Все тесты NOTRUN.** AST-разбор и компиляция в памяти не подтверждают импортируемость, корректность fixture, состояние PostgreSQL или прохождение сценариев. Финальные SHA256 четырёх production-файлов A из msg_41dce4767ce3, переданные coordinator msg_b537a63ef3e9, сверены с exact bytes; hashes перечислены ниже и в JSON. Runtime остаётся NOTRUN.

Frozen production source SHA256 (не runtime evidence):

- `clearledger/server/app/routers/locations_router.py`: `33d6ce2f89a8c348eff42d73eba860731178c56e9bac2027cdbf37153ec6f503`
- `clearledger/server/app/services/location_commands.py`: `28a02dfb18db53cdf615a20d895b9ad765b32530c90ea3457194b941ada33836`
- `clearledger/server/app/services/ezs_equipment_docs.py`: `bf85fe837f153f9ab54b63739513bb80090ab037024ed4634e2fe4e11cef8a2b`
- `clearledger/server/app/services/ezs_equipment.py`: `9813f1ff7858d38a852109ec8b174bdfeee3a2e89bcbda49c10af7df85befc22`

## Состав и цепочки

Полный разрешённый состав пакета: `locations_router.py`, `location_commands.py`, `ezs_equipment_docs.py`, `ezs_equipment.py` в server/app; новый `server/tests/test_service_location_writer_convergence_20261031.py`; этот MD и одноимённый JSON в docs/api. B изменяет только последние три файла. Исходные preparation/PR59 artifacts, общие документы, чужие tests и WIP не изменены.

- Operational раньше: route → validation400 → get_owned → assignment → audit → flush/refresh → stations → projection. После: между get_owned и audit стоит именованная команда `set_operational_status`; внешний admission, audit и эффекты остаются у route.
- Warehouse helper раньше: ci-trim SELECT → early return либо deterministic ID/constructor/add/flush. После: только constructor/add передаётся `create_warehouse`, исходный flush остаётся. Import loop/cache/dry_run/commit не меняются.
- Card раньше: lookup → domain validation/partial preparation → assignment → flush/card. После: `warehouse_for_mutation` проверяет существующий target, domain готовит поля, `update_warehouse_details` пишет name/address в прежней точке до User lookup/autoflush; `update_warehouse_card` пишет metadata в прежней точке. Native merge_metadata не используется.
- Close/reopen раньше: owned lookup → close-only units/spares guard → status → flush/card. После: только запись status через `set_warehouse_status`.
- Delete раньше: owned lookup → units/spares/history guards → zero-stock DELETE → row delete → один audit у equipment_router → caller commit. После: row delete через `delete_unused_warehouse`; название команды не доказывает отсутствие использования без внешнего workflow.

## Поля, admission, транзакция, audit и эффекты

| Путь | Admission / политика | Поля | Транзакция, audit, эффекты |
|---|---|---|---|
| operational | old get_owned membership/visit and named owner company/current object ceiling; no native ContractLocation org join | operational_status only; same-status audit preserved | same caller session; existing flush then refresh; no new lock/commit; one location_op_status from/to/reason, actor unchanged at route; stations_by_location then exactly one projection; failed result ignored as before, raised exception propagates |
| warehouse helper/create | company admitted by outer route/service; legacy ci-trim lookup and deterministic constructor profile; actual full formcreate outside nonempty O uses narrowly phased same-session/root/object origin; existing-resource ceiling remains | id/code/name/type/status from legacy warehouse profile; no native number reservations or generic create preparation | helper retains original add/flush in caller; no new barriers after pending import/FK work; no new helper/create audit; import loop/cache/dry_run/report/commit bodies outside allowed edit |
| warehouse card | outer assert_company_member, owned type/company and explicit current ceiling including warm map; domain party/contract/MOL validation retained | name[:300] source rule; address[:500]; workflow-built warehouse subtree; all other metadata/code/id/history/bindings preserved | details command writes name/address before real User lookup/autoflush; card command writes metadata at old point; original outer flush/card remains; no new card audit; no projection or new side effects |
| warehouse lifecycle | owned type/company/current ceiling; close checks units/nonzero stock, reopen skips close-only restriction | status closed/active only | existing caller session and flush; no locks or commit added; no new status audit; card only; history stays |
| warehouse delete | owned type/company/current ceiling; domain usage/history checks retained, not replaced by generic persistence call | only unused warehouse plus old zero-stock cleanup; same-company point_of_service ObjectLink parent/child generic409; other soft-history/concurrency UNKNOWN | cleanup, named row deletion and outer audit in same caller transaction; two rollback tests written; equipment_router adds exactly one equipment_warehouse_delete; no projection; native DELETE409 unaffected |

Нативные create/update/upsert/identifier/manual name/null/history/number rules и generic allowed patch fields не расширяются. Нативная `_assert_visible` с ContractLocation org-join не навязывается старым путям. O/G ContextVar не очищаются внутри операций. Членство пользователя остаётся внешним admission, helper не становится авторизацией для произвольного service caller. Никаких новых session/commit/savepoint/advisory или row lock. Старый native порядок id→company→row и lock capability не переписываются. Это не доказательство устранения всех гонок склада.

## Написанные сценарии

25 test functions, 80 вариантов по статической параметризации; это **не collection count**. Подготовительные 37 семейств остаются guidance, а не 37 выполненными тестами. Точные test IDs, варианты и assertions находятся в JSON.

| Семейства | Setup | Независимый oracle / ожидаемые assertions |
|---|---|---|
| OP-01/02 | all eight statuses including same unknown | Persisted status-only change; one exact old audit; stations then one projection seeing flushed audit; no commit before caller |
| OP-03 | invalid status own/foreign/missing | 400 precedes location admission, unchanged committed rows/history/audit, no effects |
| OP-07/08 | projection returned failed vs raised | failed return still commits old behavior; exception plus explicit caller rollback restores rows/audit, effect invocation remains observed |
| OP-04 | foreign tenant | 404, exact independent snapshot unchanged, no audit or projection |
| OP-05/WH-13 | operational/rename/close/delete cold and warm | 404 before mutation; warmed target attributes unchanged; independent committed rows/history preserved |
| WH-13 | foreign company/wrong type/no membership | 404 for target mismatch, 403 for company admission; no committed changes |
| WH-07/08/09 | partial rename/null address/phone | trim name, code/id/number/bindings/history unchanged; nested opaque metadata and omitted note retained; warehouse subtree updated |
| WH-03/04 | helper ci-trim lookup vs form duplicate | helper returns same row without mutation; form create returns409 |
| WH-01/TX-01 | new unscoped warehouse then outer rollback | deterministic exact ID/code/type/status; actual metadata fresh note; same active root transaction; independent snapshot old until outer rollback |
| WH-11/TX-01 | late rent validation and pending caller edit | 400; new staged row and pending description edit both rolled back |
| WH-18 | seven independent usage guards | active unit, nonzero stock and five movement/document history paths each block deletion409; full usage-model snapshots unchanged |
| WH-14/15/16 | close/reopen | active unit/nonzero stock block409; zero stock, terminal unit and document history allow close/reopen; history preserved, no audit/effects |
| WH-17/20/21 | zero-stock delete and two injected faults | real SQL cleanup then row deletion; success exactly one outer audit; fault after cleanup or outer audit add rolls back warehouse/stock/history |
| SRC-01 | six common-owner denial spies | actual workflows call named owner once; injected409 propagates with unchanged PG state; additional architecture check, not sole oracle |
| OP-06/WH-13 | selected organization without ContractLocation join | operational and card writes retain current context; no newly imposed native org-join policy; rollback both |

Основной oracle: фактические ORM-записи PostgreSQL, прочитанные независимой сессией после commit/rollback; снимки обеих компаний, audit, stock и всех семи usage/history источников. Spy отказа общего владельца только дополнение. Projection observer проверяет новый status и уже flushed audit, наблюдает ровно один вызов; удалённый эффект не объявляется откатываемым.

Отдельный cold/warm operational case оставляет членство admin/full, но сужает текущий object ContextVar: тёплая строка проходит старый get_owned, и отказ должен обеспечить общий владелец до мутации.

Дополнительно написаны реальный MOL lookup/autoflush case (name/address уже в SQL, metadata ещё старая) и operational/card cases с legacy `[]` object context. Ни один сценарий не запускался.

Инициализация нового склада использует private receipt от constructor/add: exact session, object, company, id, активная root transaction и persistent identity после прежнего helper flush. Фаза details допускает только первое заполнение name/address, затем card допускает metadata и consumes receipt; `warehouse_for_mutation` отзывает его по ID до existing lookup. Operational/status/delete его не используют. Никаких bypass kwargs/context clear или новых locks. Отдельные NOTRUN негативные cases покрывают commit/new root, rollback/new root, cross-session, metadata до details, повтор после consumes, existing-by-id вход и другой warmed hidden target, а также operational/lifecycle/delete при активной инициализации. Произвольные raw db.get/db.refresh и все внешние writers не объявляются покрытыми этим отзывом.

## Fixture и будущий запуск ROOT

Модуль самодостаточен: не переиспользует `db`, `native_world`, `world`, `setup_database` из существующих tests. Общий conftest импортирует app.main, seed/startup и удаляет схемы, поэтому он исключён через `--noconftest`. Тесты напрямую вызывают существующие route/service функции с синтетическим actor; они исполнят настоящие get_owned/assert_company_member и ORM scope listener. JWT/session/visit middleware, HTTP serialization/DTO и полный путь get_current_user этим harness не проверяются.

Guard до app/framework imports: уникальный `RUN_SERVICE_LOCATION_WRITER_CONVERGENCE_TESTS=1`, stdlib-only `partner_test_safety_error` с этим flag, явные безопасные TEST_DATABASE_URL и абсолютный test UPLOAD_DIR, свежий процесс без загруженных app.main/app.config и cwd без .env. `SERVICE_LOCATION_WRITER_SCHEMA_READY=1` задаёт только ROOT после review. Guard намерения и loopback/test-name не доказывает владение БД. Глобальный conftest, уже запущенный до модуля, нельзя сделать безопасным задним числом.

ROOT заранее предоставляет disposable schema, сверенную с frozen models/schema: все mapped columns, типы/defaults/nullability/FK/indexes и значимые constraints. 14 напрямую используемых таблиц: companies, users, user_companies, service_locations, audit_events, ezs_equipment_units, ezs_equipment_movements, ezs_equipment_documents, ezs_spare_parts, ezs_spare_part_stock, ezs_spare_part_movements, ezs_spare_documents, ezs_supply_documents, object_links. Статическая транзитивная FK-closure дополнительно включает regions, company_roles, counterparties, organizations, org_departments, data_entries, channels. JSON содержит scoped source hashes. Табличный preflight проверяет только наличие, не эквивалентность схемы; ROOT ещё проверяет import-time dependency closure и актуальные constraints.

На case максимум две компании, один обычный пользователь, одно admin membership, три базовых объекта; usage добавляет один spare, одну unit и максимум одну history/stock row; history/delete-fault cases также одну ObjectLink. Всего по статическим 80 cases не более160 company/80 user/320 location rows; pool=3, overflow=0. Нет create_all/startup/migration runner/DDL/TRUNCATE/DROP/общей очистки; строки остаются до удаления disposable БД владельцем ROOT. Самостоятельный executor не добавлен.

Следующий шаблон **NOTRUN / PENDING ROOT freeze + schema/import review**, не готовая команда на текущем окружении. Все ROOT_* значения задаёт только ROOT; рабочие URL/секреты здесь отсутствуют.

```sh
cd "$ROOT_TEST_CWD"
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH="$ROOT_FROZEN_LEDGER/clearledger/server" RUN_SERVICE_LOCATION_WRITER_CONVERGENCE_TESTS=1 SERVICE_LOCATION_WRITER_SCHEMA_READY=1 TEST_DATABASE_URL="$ROOT_APPROVED_TEST_DATABASE_URL" UPLOAD_DIR="$ROOT_APPROVED_TEST_UPLOAD_DIR" "$ROOT_REVIEWED_PYTHON" -m pytest -p pytest_asyncio.plugin --noconftest -q "$ROOT_FROZEN_LEDGER/clearledger/server/tests/test_service_location_writer_convergence_20261031.py" --junitxml="$ROOT_REPORT_DIR/service-location-writer-convergence.xml"
```

Existing regression selectors остаются неизменными и NOTRUN: test_location_commands, test_location_identifier_history, test_location_metadata_merge, test_location_source_number_patch, test_location_manual_names, test_location_lock_sets, test_equipment_docs. Их fixtures/opt-ins/root database setup нужно отдельно рассмотреть; generic pytest по этим файлам здесь не предлагается.

## Решения ROOT и сохранённые неизвестные

ROOT msg_b78ac8e3a4c3 (coordinator msg_2b0cb71c761b) явно разрешил сохранить legacy NEW full formcreate вне nonempty O при обязательном existing-resource ceiling; occupied renamed deterministic ID сохраняет старый PK-fail/rollback. Дополнительный новый guard: same-company ObjectLink с parent/child type point_of_service и warehouse id, любой relation/valid_to включая закрытые, блокирует delete generic409. Foreign-company links не раскрываются и не удаляются. Это конкретное расширение history policy, не утверждение полной history closure.

Новые NOTRUN cases: полный formcreate под nonempty O и последующий warm existing edit404; occupied deterministic ID после rename и IntegrityError/rollback; parent/child × current/closed known link409 при zero stock; foreign links сохраняются при допустимом unused delete и во всех injected rollback cases. ObjectLink добавлен в preflight и независимые full-column snapshots, FK ведёт только к companies; DDL не добавлен.

- **NEW-SCOPED-WAREHOUSE / ROOT_DIRECTION_IMPLEMENTED_SOURCE_FROZEN_NOTRUN**: Legacy genuinely new full formcreate outside nonempty O preserved through private same-session/object/company/id/active-root persistent origin; details->card then consumed; existing-by-id entry revokes. General db.get/db.refresh revocation or global writer closure UNKNOWN. Tests are source-written NOTRUN.
- **DETERMINISTIC-ID-COLLISION-REUSE / COLLISION_DIRECTION_CONFIRMED_RECREATION_UNKNOWN**: Occupied renamed deterministic ID retains old PK error/rollback; unused-deleted identity formula stays unchanged and recreation/no-reuse remains UNKNOWN, no tombstone/number/history policy added.
- **OPAQUE-HISTORY / KNOWN_OBJECTLINK_GUARD_APPROVED_NOTRUN_OTHER_HISTORY_UNKNOWN**: ROOT adds only same-company ObjectLink point_of_service parent/child guard, any relation/current or closed; generic409, no foreign disclosure/deletion. Existing seven usage terms remain. Concurrent link insertion and unenumerated audit/other soft-history categories remain UNKNOWN.
- **LONG-NAME-SCHEMA / BASELINE_RUNTIME_UNKNOWN**: save_warehouse slices name[:300], model name is String(255); helper code=full name is String(100). No 256/300-name success asserted; no native name255 validation silently substituted.
- **LOCKS-RACES / NOTRUN_UNKNOWN**: Native lock functions unchanged; warehouse/operational acquire no new advisory/row locks. Concurrent ci-trim create, stale-card overwrite, delete-vs-movement and FK timing not proven serializable.
- **MALFORMED-LEGACY-METADATA / PRESERVED_UNKNOWN**: dict(loc.extra_metadata or {}) and warehouse subtree assumptions retained. Unknown warehouse child keys rebuilt by old workflow may be dropped; independent top-level subtrees retained. No repair policy invented.
- **TRUST-AUTH / OUTSIDE_DIRECT_TEST_HARNESS**: Tests call actual route functions with synthetic actor and real admission; do not execute get_current_user token/session/visit resolution or prove service/legacy/OAuth boundaries. Auth source unchanged; independent acceptance required.
- **NATIVE-REGRESSION / NOTRUN**: Existing native identifier/manual-name/null/number/history/lock suites untouched, not run. Native DELETE409 and CORE-B03/mirrorDelete unchanged by scope; no global source write closure claimed.

Полный исходный план M00–M19 и все11 общих критериев скопированы без сокращений в `original_program` JSON из read-only plan-preservation. Ничего из20M+11 не закрыто; **M05 открыт**. API v1 остаётся прежние15 GET/OFF, native DELETE409/CORE-B03/locationService.mirrorDelete не меняются. Auth/main/database/bootstrap/schema/migrations/WebSocket/DTO/OpenAPI/SDK/client/guides/Support/Auditor/финансы/workflow вне изменения.

В JSON дополнительно записаны AST-hashes неизменённых native commands/lock API, warehouse usage/card/party-contract checks, _wh_loc_id/import loop и DTO/native DELETE. Сравнение AST является source evidence, не исполнением control/test. Scoped manifest не претендует на полный transitive import/write closure.

Проверки B: только filesystem/Git, stdlib AST/hash и compile-memory; кодовый объект не исполнен, pyc не создавался. Ноль app/helper/framework/fixture imports, collection/tests/pure controls, SQL/HTTP/SSH/Docker/Node/browser/build/install. Ни baseline, ни candidate runtime PASS не утверждается.
