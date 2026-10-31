# Оставшиеся services → routers, M04-P10

**Результат: 9 import statements / 10 bindings подтверждены двумя независимыми AST-обходами. Следующий предлагаемый extraction — общий владелец lifecycle фонового прогона каналов `services/channel_runs.py`.** Он уберёт одну общую зависимость scheduler → HTTP module и полезен каналам РусГидро. Семь топливных bindings откладываются; два management chat hooks сохраняются намеренно. Реализации в этом пакете нет.

Источник: accepted Pulse commit и base `1c73980f464a0b69e5203b8798d0b307cfb8630d`, app tree `77199de70167ed9c3bd916d9a460716b2179364d`. После clean/fetch HEAD=origin создана собственная `agent/api-service-boundaries-remaining-20261031`. ROOT/main/master и другие worktree не переключались. Production, старые tests/helpers/deps/SDK/versions, предыдущие Pulse reports и файлы C3 не менялись. Результат — только этот MD и соседний JSON.

## Покрытие и воспроизведение

| Метрика | Факт выбранного Git snapshot |
|---|---:|
| Все app files / bytes | 503 / 17 171 668 |
| Python app modules / parse unknown | 493 / 0 |
| Python services, включая подпакеты и __init__ | 333 |
| Все service import bindings | 4 857 |
| Router statements / bindings | 9 / 10 |
| Service files / provider router modules | 6 / 5 |
| Синтаксические call refs этих service bindings | 11 |
| Уникальные provider functions/DTO | 9 |
| Все direct/alias call candidates к этим providers в app+381 test modules | 72 |
| Recognized loader calls | 2 literal __import__('sqlalchemy'), router loaders0 |

Прочитан весь existing `tools/inventory_service_router_boundaries.py`: stdlib AST и локальные Git blobs, без app imports/ORM/SQL/network. SHA256 `7c333ba8b6591a2665751bfa3e3e116db3a244ffa710f85a584ee812218bb283`. Выполнена команда:

```sh
/home/mag/.local/bin/python3.13 -I -S -B clearledger/server/tools/inventory_service_router_boundaries.py --git-pin 1c73980f464a0b69e5203b8798d0b307cfb8630d --output .artifacts/service-router-remaining-20261031/canonical
```

Output directory намеренно должен быть новым: для воспроизведения выбрать новый собственный ignored путь. Canonical public JSON SHA `9178e0ed0299a8e2c6964d890c39cdf438c25ac1c248839c4b44c7b7d8b3ee05`; receipt содержит hashes полного app manifest/import inventory и лимиты90с/4000files/8MiBblob/100MiBtree. Независимый `independent/scan.py` отдельно разбирает immutable app+tests через stdlib AST, относительные/вложенные imports, aliases и references; он не импортирует canonical scanner или приложение. Множества `(source,line,target)` полностью совпали. Hash скрипта и результата — в JSON. SyntaxWarning books_links.py:144 об escape `\S` сохранён как известное предупреждение; AST разобран, файл не исправлялся.

Обход не вычисляет произвольный runtime callgraph, reaching definitions, plugins, assignment aliases, пользовательские loaders/getattr/exec или внешние monkeypatch. Для распознанных loaders nonliteral0; **произвольная динамическая загрузка остаётся unknown**, это не доказательство нулевых dynamic router imports. Ни import app, ни pytest collection/tests, ни SQL/application/jobs не выполнялись.

## Каждая оставшаяся связь

Пути сокращены до services/routers. Полный source byte SHA, AST SHA, строка/колонка/scope/guards, provider span/SHA и все direct/alias call candidates с hooks перечислены в JSON. ID P10 независимы от прежнего E-index; baseline ID приведён рядом.

| P10 / baseline | Source import → provider | Фактическая граница / решение |
|---|---|---|
| E01 / E01 | channel_orchestrator:292 `_run_sts_stations` → fuel_router:259 `NormalizeRequest` | Pydantic HTTP DTO; constructor:310. Обязательные station/login/password, optional shift/date, system65 и endpoint default сохраняются. **Fuel-only defer**; само тело DTO не пишет, caller имеет progress commits/savepoint/rollback. Native normalize использует тип аннотацией, хотя AST constructor call один |
| E02 / E02 | channel_orchestrator:345 `_run_fuel` → fuel_router:637 `ingest_fuel_shifts` | nested `_ingest`:348 передаёт with_receipts=False и channel/source/log traces; native normalize:634 использует defaultTrue. Helper writes/flush, без directcommit; caller фиксирует станции. **Fuel-only defer**, не смешивать с energy charging |
| E03 / E03 | channel_orchestrator:361 `_run_fuel_delivery` → fuel_router:1040 `ingest_fuel_deliveries` | nested `_ingest`:364; STS receipts/DataEntry/L1, dedup/units/density, caller savepoints/commits. Один прямой service caller, отдельного native HTTP call к helper не найдено. **Fuel-only defer** |
| E04 / E04 | channel_orchestrator:381 `_run_msto` → online_orders_router:174 `ingest_online_orders` | call:392, также native refresh_online_orders:405 и online_reconciliation.run_workspace:478. Company connector, paging, raw batch/upsert/flush; commits снаружи. **Fuel/MSTO defer**, не разрешение на агрегаторы/1С |
| E05 / E05 | channel_scheduler:105 `_launch` → channels_router:327 `_run_channel_background` | call:123 и native run_channel:489 через create_task. Не HTTP handler/DTO, а собственная сессия и финализация прогона. **Следующий общий extraction** |
| E06 / E08 | edge_nsi:1221 `ingest_station_catalog` → store_router:1021 `_queue_nsi_delta` | conditional deletion resend, cap200, per-station call:1224; helper очередь полного снимка, no directflush/commit, caller commit после check metadata. **Station/store/fuel defer**, вместе E08 |
| E07 / E09 | fuel_shift_refresh:304 `refresh_shifts` → fuel_router:11 `_parse_dt` | call:305. Falsey→None, иначе datetime.fromisoformat, offset/naive и ValueError/TypeError не нормализуются; caller nondryrun writes/commits каждые50 и в конце. **Fuel-only defer**; другой online_orders._parse_dt — другой provider |
| E08 / E10 | item_draft_auto:209 `разобрать_заявку` → store_router:1021 `_queue_nsi_delta` | calls:227/228: split ставит old+new, иначе new; human возвращает без очереди. Решение/штрихкоды/дельты до callercommit. **Fuel/store defer**, один будущий NSI owner с E06 |
| E09 / E17 | management_local:73 `_chats` → chat_router:170 `_assert_participant` | call:92, native adapter existing chat_access owner с late `_company_of/_chat_scope/_audit_foreign_access`. Может добавить audit/запланировать notify; no owncommit. **Intentional compatibility keep**, не дубль ACL |
| E10 / E18 | management_local:73 `_chats` → chat_router:238 `_chat_scope` | call:77; wrapper existing chat_scope_of. Exact attribute патчится/удаляется tests. Missing/403 остаются fail-closed, прямой service default не эквивалентен runtime hook. **Intentional compatibility keep** |

Полные provider file SHA256: channels `027df4a863a9f730b45e05ed8d283acf298b6835fa6cf42786222b3b8daf91a4`; chat `5a7d046cfd958a6c17ee7bfc0f95579d5934224621c5e8a89b1bb367ae91e58e`; fuel `c6755d318ad80086ec621cdbafc8b7708780a566904b736d6363e7689afc631a`; online_orders `870b1adb728686cf596e6f26ef01d6f33087b915689536dd77e61ba44f63fd5f`; store `4da3fdb1c76e7b39d7916af6e92ed00344c8b71acf85ec9429d32482997b2ba6`.

Все callers: JSON содержит72 конкретных file/line/column candidates, не только импортирующие services. Например queue вызывают шесть native операций nsi_item_update/nsi_set_price/nsi_add_barcode/nsi_retire_barcode/catalog_enrichment_decide/store_resolve_item_draft и три service call sites; fuel parser — десять native и один refresh call. Chat participant имеет35 calls и scope8. Counts учитывают два call expressions на одной строке отдельно. Возможное внешнее shadowing/patching не выдаётся за решённую динамику.

Management специально сохраняет выбранную компанию/current membership, участие и current role scope, ticket/task ACL и source в общем owner. Список исключает archived/inactive и предметные task/ticket rooms, stream закрывается в finally, 404 пропускается, 403 не подменяется доступом. Histories/messages/counts не запрашиваются. `test_management_runtime_compat` подтверждает positive exact scope hook и missing/denied behavior; `test_chat_access_owner` подтверждает late/awaited company/scope/audit callbacks. Participant poison в context test доказывает, что modern context обходит old binding; это **не** отдельное positive Management participant hook proof. Foreign-access audit нельзя объявлять чистым чтением/нулём writes, в том числе при гонке отзыва участия.

## Сравнение с исходным inventory

Baseline `d70581b4c98d5a523badf0220c9d2990de4844d8`:20statements/29bindings,12services/10routers. Сейчас9/10,6/5: минус11statements и19bindings, оставшиеся baseline IDs E01–E05,E08–E10,E17–E18. Полная карта19 исчезнувших/redirected edges дана JSON. Это source comparison, не повторная приёмка P1–P9 и не числовая оценка всей бизнес-логики. Root literal hint9/10 подтвердился, но не использовался как цель scanner.

## Следующий узкий владелец: background lifecycle каналов

Предлагаемый будущий production scope — **ровно три файла**, только после нового blocking ROOT scope review:

1. Новый `app/services/channel_runs.py`: общий `run_channel_background`, `loaded_total`, `run_summary` — три текущих определения channels_router:307–421. Существующий channel_orchestrator.run_channel остаётся владельцем dispatch/ingest/publication и вызывается из нового owner.
2. `routers/channels_router.py`: только imports и три legacy adapters с прежними names/signatures/defaults. RunRequest/HTTP handler/get_owned/flush/commit/create_task/response/OpenAPI остаются прежними.
3. `services/channel_scheduler.py`: только `_launch` binding в прямой service owner; `_due/_tz/_last_run/_has_running/tick/run_forever`, population/locks/window и commit ownership остаются прежними.

Нативный background получает семь прежних positional args (station_codes=None,all_period=False,mode=append); новый owner не получает Request или whole router module. Для сохранения source late globals предлагаются **четыре конкретных optional callback**, выбираемые через isNone: current session_factory, orchestrate_channel, _loaded_total, _run_summary. Legacy summary adapter использует current native loaded_total. Это ограниченный compatibility seam, не callback table/общий framework. Прямых patch-тестов background/factory/report helpers в выбранном app+tests snapshot не найдено; текущие globals — потенциальные seams, а не доказанные runtime hooks. ROOT должен явно выбрать/подтвердить эти shims и scheduler factory binding до edits. Clock/globals/внешние patches сверх этого остаются unknown, новый универсальный dependency container не предлагается.

Применимость — реальная общая инфраструктура: `_dispatch` знает manual_table registry, charge_sessions_excel, stations_excel, market_registry_file (РусГидро), а также fuel/1C/MSTO. Background owner переносит существующий lifecycle; семь fuel edges не затрагиваются. Даже после предложенного патча будет8statements/9bindings, а не ноль и не завершённый M04. Transitive fuel coupling остаётся в существующем orchestrator.

### Сохраняемый порядок и authority

Native get_owned оставляет membership/visit/object-scope404 (не новую product ACL); paused channel вручную сейчас можно запускать, scheduler выбирает active. Background получает trusted generated IDs и не является самостоятельным ACL: собственного crosscheck log.channel_id в нём нет; channel/log/source pair policy не добавляется молча.

Оркестратор сохраняет свой rollback частичного импорта → publication failure fact → отдельный commit → rethrow. Background затем best-effort rollback, обновляет log counters/status/events/finished_at и channel last_sync_at/docs_loaded, вызывает log_audit(actor=None), который добавляет AuditEvent и **планирует dispatch_async до finalcommit**. После закрытия этой сессии опциональный fuel followup вызывается только по нынешнему raw status/kind/date condition; его ошибка не меняет уже сохранённый статус. Не обещаются exactly-once delivery/outbox/retry.

Нельзя менять skipped→partial mapping, unmatched_sessions override, list by_station priority (включая emptylist→0), missinglog audit differences, malformedcounter errors и две отдельные UTC now calls. Missing channel возвращает без финализации; CancelledError не ловится exceptException и может оставить исходный running log — это characterization, не новая политика отмены.

Scheduler проверяет _has_running/_last_run **до** try xact lock, без повторной проверки после lock. Source этого не доказывает cluster exactly-once; возможная отдельная concurrency-задача не должна скрытно входить в extraction. Auto draft tick тоже держит session advisory lock при внутренних commit/rollback: pooled safety здесь не проверялась. Производственный fuel/GIG/касса/станция/1С не поручены.

## Предлагаемая ROOT-only приёмка будущего патча

Matrix и ожидаемые outcomes перечислены JSON: fixed two-company IDs, native vs clean owner, native foreign/missing404 и invalid422, commit-log-before-task, success/skipped/unmatched/by_station counters, реальный nonfuel registry/energy branch с synthetic owned file, rollback partial + durable failure fact, audit/notification ordering, missing/cancel/postprocess failure и captured fuel-followup gate без fuel-ingest. Сохраняются old test_channel_failure_rollback assertions; source-only NSI checks не объявляются runtime proof. Scheduler loops/lifespan не запускаются: только bounded `_launch` и owned captured task/coroutine.

До любого runtime нужен новый exact ROOT pin и полный freeze app/tests/schema/support/IDs/argv/env. Предлагаемый fresh dedicated DB `api_channel_run_owner_test_20261031`/127.0.0.1:33546, candidate77 Python3.13.7; owned test pool2/overflow0/≤8 fixture channels, statement20s/lock2s/idle30s/connect10s/command30s. Прежние strict five IPv6 import probes restoration, native ownedPGsendmsg16 controls, no.env/secrets/process/net/write/source/capture/scratch guards; capture HTTP/SMTP/COM/followup terminals **до app imports**. Только PG, без внешних HTTP/SMTP/1С/станций, no jobs/servers/installers.

ROOT сначала resource admission; outer wall650s/CPU600/AS3GiB/FD256/FSIZE2MiB, четыре private0700 test roots, scratch128MiB/4096files, capture4000. Await/reap только своих tasks/process, source-after/inventory77/16/forbidden0, обычный DROP только exact fresh DB и exists0/clients0/relations0. Это предложение caps, не разрешённый запуск и не новые рабочие настройки. Точные counts и fixture provenance утверждаются ROOT в следующей задаче.

P10 завершает source inventory и reviewable предложение. Никакая реализация extraction, full CI, runtime/security scan или release не выполнены; M04 и общая программа20M+11 продолжаются.
