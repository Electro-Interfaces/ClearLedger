# M16-C3: совместимость budget gate с проверенной историей

**ROOT scoped accepted: V7,82/82 PASS одним прогоном,85.992169740s,exit0/reaped.**
Receipt `msg_3b1695aa6f83`. Worker выполнял только source/Git/AST/compile/hash;
imports app/runner, collection/tests и SQL исполнял ROOT. Это приёмка budget gate,
не завершение всего M16/M00–M19+11, fullCI или разрешение выпуска.

## Результат и границы изменения

На исходном pin875929b3 gate выбирал `manifest.load()` default0001 и
`runner.state`: bounded history0001 отвергал любую вторую row, включая правильную
applied0002. Новый gate знает проверенные0001/0002/0003 и требует минимум0001.
Он допускает каждый полностью проверенный applied prefix1/2/3, проверяет catalogue
всех applied successors, не требует неприменённый latest/его prerequisites.
Unknown/future/gap/source/checksum/owner/actor/action/catalogue drift отказали.
Непроверенная история не срезается ради прохождения gate.

Единственный reader/verifier принадлежит принятому framework B:
`manifest.load_known_head()` и
`runner.require_applied_prefix(..., required_revision=ID)`. Framework24files
побайтно B exact, frozen0001/0002/0003 не переписаны. Default explicit
runner/CLI0001 сохраняет отказ на newer history; старый binary не объявлен
совместимым. Нет autoapply/stamp/DDL/grants/seed/ownerlock из read gate.

`_config` AST unchanged: PostgreSQL+asyncpg, отказ любых URL query/TLS overrides,
нормализация отсутствующего port5432, expectedDB/user/Core validation прежние.
ON Config/source preflight идёт до engine checkout. Unknown DB history/drift
выявляются после SELECT до write paths, а не обещаются до подключения.
OFF возвращается до Config/source/import/I/O. Flags/defaults остаются OFF.

Borrowed signature/receipt и actual connection/transaction/options/search_path/
readOnly/isolation сохраняются. Прежний SQLAlchemy probe активирует lazy PG TX;
helper его не завершает. Owned path сохраняет read-only REPEATABLE READ,
10/15s и cleanup. Models/database/main/config/B bootstrap не менялись.
Отдельное narrow разрешение ROOT изменило только managed-on block B test на
успех canonical0003; все остальные test AST B exact. Этот B native item отдельно
не запускался: actual borrowed prefix3 проверен новыми cases, full startup не заявлен.

## Immutable основание и ownership

Base `875929b3885d98ace8e370a72d62a825bf76960b`; ROOT GO `msg_8871d23f610a`.
Принятый B `1c73980f464a0b69e5203b8798d0b307cfb8630d` exact cherry-pick `3ed99e18`.
Own production file только `app/services/schema_version_gate.py`; остальные
own files: новые root-only tests/helper/immutable fixtures, narrow B test block,
этот MD и соседний JSON. ROOT/A/B/Support соседние worktrees не изменялись.

## Actual82 и ограничения доказательства

| Группа | Exact IDs PASS |
|---|---:|
| OFF | 2 |
| Known applied prefixes/create/adopt | 6 |
| History shape/required minimum | 9 |
| History fields | 30 |
| Catalogue/foreign owner/public sentinel | 11 |
| Config/source preflight | 9 |
| Actual connection/options/cold JIT | 12 |
| Historical preservation/characterization | 3 |
| **Всего, один V7 run** | **82** |

Все82 unique IDs/allpassed независимо проверены ROOT. Три invalid-action cases
доказывают SQL CHECK refusal и actual pure validator; они **не** записывали
некорректный action в штатный journal. Остальные field negatives используют
persisted bad rows. Duplicate constraints также отделены от gate refusal.
Before/after сравнивались catalogue/rows/xmin/ctid/OIDs; caller write/rollback и
fixture DDL/GRANT/seed шли вне read-gate observation. No app.main/lifespan/jobs,
external delivery или worker SQL. SourceAfter=true, inventory77 unchanged,
16 metadata controls=true, forbidden0.

Actual captures:1734 gate statements (raw1642,SQLAlchemy92),92 physical-connection
probes,27 legitimate owned gate checkouts.233 connections — **все** fixture/
migration/control/raw connects, не extra connections gate. Inside gate отдельные
socket/checkout assertions пройдены. После teardown fresh read-only receipt:
relations0,otherclients0,maxlocks64,DBbytes16194583; ROOT ordinary DROP дал exists0.

## Driver JIT: проверенный протокол, а не zero GUC

Pinned asyncpg0.30 при cold type introspection действительно выполняет JIT off,
PG14+type lookup WITH, JIT restore. Наблюдались55 ordered codec groups. Source
byte hashes driver connection/introspection проверяются до imports и после run.
Допускаются только три actual+source matched SHA, raw origin, один physical PID,
порядок OFF/TYPES/RESTORE при initialon или OFF/TYPES при off. Warm0groups допустим.
Другие WITH/SET/GUC/DML/locks, nested/incomplete/reordered groups и ordinary raw
statement внутри группы отказывают. Нет broad SELECT-set_config/WITH whitelist.

Raw scalar probes builtin int/text до/после gate не активируют lazy SQLAlchemy TX.
PID/JIT/path/options и actual TX/readOnly/isolation проверены. Owned test wrapper
отдаёт тот же real AsyncConnection и измеряет after ownedTX **до pool reset**.
Два explicit fresh JITon/off cases подтвердили >=1coldgroup, тот же PID/JIT после
gate и после caller commit; per-connection startup fixture не меняет server/global
GUC или production options. Application/framework не добавили explicit writes/
SET/locks. Это **не zero driver GUC statements** и не cold cancellation/error
restoration proof: у pinned `_introspect_types` нет finally, эти ветви UNPROVEN.

## История source/fixture коррекций

| Серия | ROOT результат и причина | Что сохраняется |
|---|---|---|
| V1 | 10 offline PASS, S-default-port fixture FAIL;1.80789385s,PG0 | URL.set(None) не убирал port; production unchanged |
| V2 | 11 offline PASS, missing global urlsplit;3.311865324s,PG0 | Добавлен stdlib binding, static globals audit0missing |
| V3 | 11 offline PASS, firstPG observer отказал;5.12112316s | Safe metadata ещё не сохранялась; no PG PASS |
| V4 | 11 offline PASS, diagnostic refusal;5.112010397s | Actual три driver SHA сопоставлены с source, no PG PASS |
| V5 | 13 PASS (11offline+2P1), legacy fixture column_order;6.916955261s | DROP/ADD оставлял attnum hole; frozen verifier не ослаблялся |
| V6 | ROOT source PASS, **actual не запускался** | Immutable M09 empty legacy fixture принят |
| V7 | **82 PASS одним прогоном**,85.992169740s,exit0/reaped | V6→V7 только equivalent explicit TEXT binding и hash updates |

Все предыдущие receipts и source/report snapshots сохранены ignored
`.artifacts/schema-gate-history-20261031/v1/`…`v5/`, `v6-unexecuted/`;
ROOT originals — `root-schema-gate-history-review-20261031`. Это не сумма
повторявшихся PASS и не single green предыдущих попыток. Пinned source подтвердил,
что regtype input тоже text encoded; ROOT разрешил сохранить уже сделанный V7
binding без undo (`msg_1c573c90d347`).

V6/V7 legacy fixture использует exact M09 old models Git ba9fc30…,965484bytes,
SHA f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e.
ROOT исполняет этот old model SOURCE под schema-only OnlyBase adapter, затем
восстанавливает exact prior app.database. Current ORM metadata не меняется.
Только EMPTYcalendar пересоздаётся без CASCADE/SET/createall; CreateTable и все
CreateIndex получены из старого ORM, типы/defaults/FKs/check/index sets и отсутствие
attnum gaps проверены. Complete outside semantic catalogue и budget/journal rows+
xmin сохранены. Исключены только Calendar-own objects и три canonical FK-dependent
RI sets: их logical shape проверена before/after, observed OIDs сохранены отдельно.
Это fixture DDL, не действие read gate и не работа с live data.

Исторические original harness/wrapper не repin. Immutable old gate bytes
6e5166… проверены на **текущем strict default framework**, воспроизведён refusal
на prefix2; это не весь старый binary. Original app489/schema16 closure независимо
source-hashed из f6588d191a3e81b431cdda42d039df4fa33bc419, старый полный harness
не перезапускался. B commit1c73980f сохраняет прежний managed-on characterization.

## Ресурсы, pins и integration route

V5 floor+320MiB admission сначала отказал до DB/runtime. ROOT сохранил все свои
original raw paths/SHA и дедуплицировал только собственные одинаковые artifacts
hardlinks; чужие files/source/deps не удалялись. Для V7 ROOT документировал
output planning32→16MiB: итоговый reserve304MiB =DB256+outputs16+WAL32 при прежнем
8GiB floor. Actual CPU/AS/FD/FSIZE/time/scratch/network/env/DB target caps прежние.
Это planning reserve, не hard DB quota; V7 clarification — отдельный ROOT artifact.

| Source | Files | SHA256 |
|---|---:|---|
| app | 503 | `824e5ae16ff330d93e2d3f66ebe19e46c0b32aecd77edba5c742e8aaf3badca0` |
| tests excluding this runner | 387 | `bf1fb7dd613c320866f2e6f009069ae54ae629635206397530415e1a396a5c34` |
| schema_migrations | 24 | `36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165` |

Accepted runner SHA256 `6845a6f8b18f61114b410397bc18237ed6b5875041f49ccc3bd8863361676559`.
Boundary SHA256 `c6b98720badee47d5be3ad794cea25ff3f13e624365ae1eb6a526bb6f9efec09`.
Acceptance JSON SHA256 `a6afc18ca9d9897443bf21c997412a61e149aad675a5b5ad4f2dcf0c3c4b638a`.
Full manifests/argv/env/82 IDs/receipts/limits/source hashes — в соседнем JSON.

ROOT разрешил Russian named commit/push только9 own files; immutable SHA и
report hashes передаются worker_done. Integration/draftPR routing остаётся у
ROOT resourceowner; merge/deploy/flags activation не выполнялись. Не заявлены
full Core startup/public/live activation/full old binary/current fullCI или
cold cancel/error restoration. Общий M16/M00–M19+11 продолжается.

Delivery check отметил один blank-at-EOF в frozen helper; accepted bytes/SHA
сохранены. Commit/push hooks отключены только на этих Git-командах, чтобы
worker не запускал Node/tests; actual82 исполнил ROOT.
