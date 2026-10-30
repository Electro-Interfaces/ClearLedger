# M05: ручное переименование точки сохраняется при W10

30.10.2026. Immutable baseline `8e18fe76a977a42814383793ec0893776e827230`;
origin foundation branch сохранена на этой ревизии. Ветка результата
`agent/api-location-manual-names-20261030`. После фактического изменения имени
через native PATCH, existing-ID native POST/upsert или registry PATCH W10
`refresh_location_names` сохраняет ручное имя и прежний nameHistory.

Это edit-only slice: **initial create остаётся unmarked**, как и старые записи,
для которых происхождение неизвестно. Имя из W07/W08/CPO и их cached metadata
writers этим пакетом не защищены. Activation полного M05-B не выполнялась.

## Source checkpoint и intent

Решение согласовано до grant/runtime fix по принятому design `11c5a291`, особенно
F11/F19 и manual provenance. Изменены четыре runtime файла: location_commands,
locations_router, space_registry и только refresh_location_names в
stations_normalize. Новые test/report дополняются одним отдельно согласованным
golden update в test_location_number_history; всего 7 файлов. Auth/models/DDL,
остальные import/session/unit/link writers, финансовая логика и старый plan/map
не менялись.

- Native PATCH: `name_intent="manual"` только при name в model_fields_set;
  omission не является переименованием, explicit null по-прежнему 422.
- Native POST: name required, поэтому intent явный; **только existing-ID ветка**
  upsert применяет его. New-ID create не маркируется. Старые default/full-form
  sourceBindings/type/status/metadata semantics не меняются.
- Registry update: существующий authenticated wrapper передаёт intent при
  наличии actor и name в data. Его route уже использует exclude_none=True;
  name:null остаётся прежним omission, admin-only/enums/confirm не менялись.
- Source/actor без intent не означают manual. Это отдельный keyword-only
  internal command argument; client metadata не задаёт authority, actor/source
  берутся из существующих wrapper arguments. Ни новых прав, ни principal cache.
- Команды сначала выполняют прежние ID/company locks, tenant reload с
  populate_existing и текущую O/G admission. Только затем сравнивается prepared
  name с **актуальным** loc.name. Actual change пишет provenance; no-op/replay
  не меняет время/actor/source и не создаёт дополнительный registry audit.

`location_commands.py:_with_manual_name_provenance` добавляет ровно
metadata.fieldProvenance.name = {authority: manual, actor, source, recordedAt}.
Actor — строковый ID пользователя, source — native.locations или
registry.objects, recordedAt — серверное время записи в UTC. Это текущая
provenance последней явной правки, **не** valid-time или append-only name ledger.
Изменение вместе с именем принадлежит прежней T; commit/rollback/audit/projection
ownership и freeze/no-reuse/typed identifier histories не менялись.

## Readonly, malformed state и W10

fieldProvenance добавлен к server-owned metadata keys. Если create-команда
получила этот ключ в metadata, ответ 422 при любом supplied value. Update
игнорирует echo/подделку, включая scalar/null/list, и сохраняет stored JSON
любого shape; клиент не может стереть ключ или сам объявить имя ручным.
В registry DTO metadata как и прежде не является редактируемым реквизитом.

При actual manual name change stored root должен быть dict, а существующий
name marker — известной формы: authority manual/cpo_registry/sessions,
actor/source/aware ISO recordedAt. Manual actor не null; для unattended known
source marker допустим null actor. Неизвестные sibling/extra fields сохраняются.
Unknown/malformed root/name даёт generic 409 до mutation, без repair. Omission,
неименная правка или name no-op не пытаются чинить старую provenance. Initial
create и legacy metadata не получают массовую разметку; происхождение по тексту
или source строке не угадывается.

W10 получил единственный дополнительный qualified current-row guard:

```sql
AND coalesce(sl.extra_metadata#>>'{fieldProvenance,name,authority}', '') <> 'manual'
```

Проверяется именно текущая `sl`, не предварительный список или CTE snapshot.
После ожидания row lock PostgreSQL повторно проверяет predicate: committed
manual marker не позволяет W10 затереть имя. Даже старый partial marker с
literal authority=manual пропускается без repair. Другие legacy nonmanual
случаи сохраняют прежнее поведение. Существующий nameSource=cpo_registry guard,
company predicates, latest valid station_name/btrim, nameHistory append и int
count неизменны. Новых advisory locks, FK writes или commits в W10 нет.

W07/W08 могут перезаписать имя/metadata вне этой boundary; initial manual create
и старое meaningful имя без marker по-прежнему доступны legacy W10. Эти границы
явные: пакет не исправляет все source authority/lock-order/chunk/reconciliation
проблемы принятого M05-B design и не меняет late-created stations/retire.

## Actual baseline и candidate

До отдельного SQL grant выполнены source/test preparation, AST и source
checkpoint; runtime fix внесён **после actual baseline**. Final test bytes на
immutable baseline и candidate совпадают. Baseline primary сначала сравнивает
реальные count/name/nameHistory после W10, а не падает на отсутствии нового key.
Использованы actual native/upsert/registry wrappers, настоящие ChargeSession
source_station_id/station_code/station_name/started_at и сам SQL W10; они не
mock-ятся. Synthetic ASGI world подменяет login principal/projection как прежний
корпус, это не OAuth/production API acceptance.

| Проверка | Результат | pytest / runner |
|---|---|---|
| Immutable 8e18fe76, 5 baseline cases | **3 FAIL + 2 PASS**, 0 ERROR/SKIP; три actual manual-loss cases и независимые CPO/unmarked controls | 17.86 /30.982с |
| Same-file candidate, 68 новых | **68 PASS**, 0 FAIL/ERROR/SKIP | 23.76 /34.904с |
| Final combined | **441 PASS** = 68 новых + 372 старых с прежними expectations + 1 согласованный updated golden; 0 FAIL/ERROR/SKIP/DESELECTED, EXIT 0/reaped | **59.43 /70.648с** |
| Opt-out | 1 module SKIP, 0 collected, штатный pytest EXIT 5 | 0.08 /10.541с |
| Fresh cleanup | tables 0/conns 0 перед normal own DROP; fresh DB exists 0/own conns 0/other clients 0/maxlocks 64; без FORCE/terminate | EXIT 0 |

Все три baseline primary получили actual
`[1,"Synthetic session label",["Synthetic older label","Synthetic manual label"]]`
вместо 0/manual/unchanged history. Поэтому доказана фактическая потеря ручного
имени существующим W10 после каждого из трёх входов. В candidate результат
`[0,"Synthetic manual label",["Synthetic older label"]]`; metadata/raw/history
и foreign company point сохранились. Формат/readonly/unknown-state случаи —
новый additive contract, их отсутствие в baseline не называется отдельным
прежним defect или отсутствующим-symbol bug.

Проверены readonly echo/create422, omission/null semantics, unmarked name no-op,
replay с другим actual actor и source, unknown/malformed state без repair,
сохранение opaque siblings, direct same-source/actor без intent, rollback после
реальной flush при projection/audit failure, foreign/O/G/role admission.

Concurrency: manual-first удерживает настоящий native wrapper row lock;
W10 наблюдаемо ждёт его по pg_blocking_pids, после commit возвращает 0 и сохраняет
name/history. W10-first удерживает собственный UPDATE; native wrapper читает
старую ORM-копию, ждёт row lock, после commit/rollback source делает прежний
reload и сохраняет корректную актуальную nameHistory плюс manual provenance.
Обе очередности подтверждены actual transactionid wait graph и конечным state,
без sleep как доказательства. Полный перебор расписаний/нагрузка не заявляются.

## Старый golden и состав регрессий

С разрешения координатора изменён только
`test_location_number_history.py::test_preexisting_double_station_number_is_not_reconciled_or_renumbered`.
Полная проверка **всех прежних metadata keys** сохранена, как и ID/shared current
station_number/numberHistory. Отдельно требуется ровно fieldProvenance.name,
четыре protocol keys, authority=manual, actual actor/source, aware UTC timestamp
в пределах фактического запроса. Другие 42 case этого файла и прочие 11 старых
modules не менялись. Нельзя выдавать результат за 373 побайтно неизменённых cases:
это 372 прежних expectations плюс 1 обоснованно обновлённый golden.

Распределение старого корпуса: foundation 60, identifier 89, number scope 34,
commands 84, number history 43, metadata 3, mapping 29, freeze 6, bindings 5,
object scope 5, scope screens 11, projection 4 = 373. Новый manual module содержит 68.
Function-scoped AST comparison подтвердил, что остальные функции
stations_normalize и старые lock/number/history/admission helpers не изменились.

## Изоляция, rollback и ограничения

Private runner до connect/admin/pytest проверил exact назначенный synthetic
PostgreSQL 16 target и exists 0 до CREATE. Empty cwd, absolute PYTHONPATH/test
UPLOAD_DIR, TEST_DATABASE_URL=DATABASE_URL, assigned Python 3.13.7 и все 7 flags,
включая singular RUN_LOCATION_LOCK_SET_TESTS; HOME/CODEX_HOME без override.
Новый suite использует общий partner_test_safety_error и настоящий ORM listener.
Новые tests не меняют PG settings, observers ограничены собственными sessions.
Setup/tests/drop последовательны, дочерние процессы EXIT/reaped, probes закрыты.
После свежего cleanup и normal ownDROP отправлен SQL_SLOT_RELEASED; далее SQL
не выполнялся. Runner/logs/JUnit/manifest — в .artifacts/location-manual-names/,
Git их не содержит, operational/client data в публичный отчёт не копировались.

Rollback не требует schema down: новые данные живут в существующем JSONB.
Однако старый W10 не понимает marker, а старый merge допускает scalar overwrite
этого ключа: code revert не сохраняет новую гарантию. Перед откатом нужно
остановить соответствующие mutating jobs либо сохранить совместимый guard/key
protection; это не новая операция выпуска в данном пакете. Не стирать provenance
ради совместимости старого writer. No-reuse и сохранение inventory не меняются.

Не выполнены realenv/SSH/real API, full repo CI/security scan, browser acceptance,
merge/deploy, mass backfill или activation B. Stale W07/W08/CPO writers, initial
create и полный multi-row/import protocol остаются отдельными prerequisites.

## Измеренные хеши

| Артефакт | SHA-256 |
|---|---|
| Baseline clearledger/server/app/services/location_commands.py | `f981511ff74790b892fc7e4cf8c2ad9ab619686719c36b1aef5e6235f998c53b` |
| Final clearledger/server/app/services/location_commands.py | `c30d118b25c504e8921817183f1d5738ac39a216aed6534f3857e13f6ee0cfb4` |
| Baseline clearledger/server/app/routers/locations_router.py | `8ad9fa597212a71ef0cbc08ea9f36ae8b0fa120862fd7726e0c89e7a8cdca894` |
| Final clearledger/server/app/routers/locations_router.py | `e2a6d5e7fc011ff98078bc1d7108ffe94e5a182ed0145ee45c17429cc05c13c1` |
| Baseline clearledger/server/app/services/space_registry.py | `bdf7dbecd3ec34a11e5e7eacf4a2ad092d40f575dae9b47481a232b59ddf0c6c` |
| Final clearledger/server/app/services/space_registry.py | `97f86a8abce571c7b87cd2cfcdc646ad7e41be049fc19282dfe800301c910771` |
| Baseline clearledger/server/app/services/stations_normalize.py | `468869d96705e6a3627f24c909c46ef240c615c950c053874e417ffbda3fa2e9` |
| Final clearledger/server/app/services/stations_normalize.py | `0cfde91babd868d56b7f472875d396180d7d3e4fb74f9b9b80ce75a6e9ba7645` |
| Baseline clearledger/server/tests/test_location_number_history.py | `e701876feb54e90c002e617973335c44a72b8ac1e07293f363e2785abbabef62` |
| Final clearledger/server/tests/test_location_number_history.py | `5e57227aa4f20f0bf85166576a061290bc91bbbc22e8e3f59bc3952ba16d06d2` |
| Final clearledger/server/tests/test_location_manual_names.py | `8e4ad918b11be679aa7ef175ddb1dcc3f460c0b94cd8b1c9863e78e96d145ff4` |
| Private baseline.xml | `fb1345d4ca8399e58331591aa4b74a520e588a38c7485530044fe003108552bc` |
| Private candidate.xml | `ea8b5b8ddff0858578b93f6c5ab9c137746ff773a931be6bf110edce11c16692` |
| Private regressions.xml | `9442b482c3bfa12c5cfc33e4841aa0d58d16fda0a17a8a1b68a4cc9ce9d245e2` |
| Private skip.xml | `4b6b215672aa54e5c59ced9cd6c35971156f8f2a8a273c362b1a6159a9a76c0a` |
| Private cleanup.log | `ae9bb72bdfe309eea60f8ac7c24bf1e8eecddb1a26ae7b64a2b789882141badb` |
| Private source-boundaries.json | `421f432f8f585fdf6cbd2a18a785cf10188be773ae4339bcbb8133b7f44c60f7` |
| Private runner.py | `475748c7c9c661a1400241de08ec7fc391005888ce5ae81f93af16efd018836c` |
