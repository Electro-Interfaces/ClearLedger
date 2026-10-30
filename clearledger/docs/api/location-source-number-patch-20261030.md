# M05-B prerequisite: existing-only source number patch

30.10.2026. База: immutable `bdcdfab7157045f78eb1a3a640c5fe01b2b6bef7`.
`origin/agent/api-location-manual-names-20261030` сохранена на этой базе;
новая ветка `agent/api-source-number-patch-20261030`. Основание контракта:
принятый design `11c5a2919886e7f0936466bdc031c4fa67965ecb`, independent
presence-aware SourcePatch и предварительно acquired lock set. Меняются только
`location_commands.py`, новый `test_location_source_number_patch.py` и этот документ.

## Реализованный внутренний контракт

```python
await apply_existing_source_number_patch(
    db, company_id, identifier, patch, locked_set,
    actor_id=None, source=None,
)  # -> Mutation
```

`patch` — закрытый flat dict: только `station_number` и literal
`metadata.number`. Например, `{"metadata.number": "source-next"}` сохраняет
колонку `station_number`; `{"station_number": None}` очищает только колонку.
Omission, explicit null и empty string различаются. `{}` допускается для уже
существующего admitted объекта. Расходящиеся legacy значения не синхронизируются.
Whole metadata, code/id/name/passport/sourceBindings/authority/history не входят
в этот API. Command не принимает произвольный набор ORM attributes.

| Поле | Допустимые значения | Хранение |
|---|---|---|
| `station_number` | `str` или `None` | Строка сохраняется вместе с пробелами; limit 60, NUL запрещён |
| `metadata.number` | `str`, `int`, finite `float` или `None`; bool запрещён | Копия актуального metadata, замена только `number`; limit 60 после описанной ниже numeric normalization, NUL запрещён |

Pure validation и capability check не приобретают locks. Требуется подлинный
`LockedLocationSet` для конкретных db/root transaction/company/ID из полного
заранее acquired множества. Отсутствующий, поддельный, expired, чужой token и
late ID отклоняются без fallback acquisition. Root capability сохраняет
прежние SAVEPOINT/root lifetime правила foundation; новый helper их не меняет.
Commit/outer rollback завершает её действие. Никакого create fallback: planned
missing ID даёт generic 404. Membership/role admission остаётся обязанностью
существующего authenticated caller, capability не выдаёт полномочий.

После pure check command отклоняет `db.new`, `db.deleted` или фактически
modified `db.dirty` с 409 до SQL и flush. Это относится и к unrelated pending
entities. Затем `locked_visible_in_set` под `no_autoflush` выполняет tenant-first
`FOR UPDATE` с `populate_existing` и повторяет текущий O/G admission. Состояние
scope не очищается и не кэшируется token. Чужая tenant row не загружается и не
блокируется; company-wide occupancy использует Core columns.

Caller обязан явно admit/flush свои pending changes, включая freeze facts,
до входа в patch. Это не разрешение слепо flush произвольных importer writes.
После изменяющего patch следующий patch в той же root T требует explicit
caller flush, при сохранении того же set/barrier; helper сам не flush/commit/
rollback. Так pending session/link/export/inventory не скрываются из freeze
проверки. Caller также обязан подготовить полный ID set **до** несовместимых
row/FK writes. Ни clean-entry, ни token не обнаруживают произвольные ранее
взятые SQL locks и не делают unsafe import/unit writer готовым к активации.

## Общая mutation boundary и сохранение данных

Source anchors в `location_commands.py` (SHA256 ниже):

| Функция и строки candidate | Caller / изменение |
|---|---|
| `acquire_location_set:124`, `_require_location_set`, `locked_visible_in_set:232` | Foundation без изменений; новый command использует уже acquired capability и current reload |
| `_source_number_value:476`, `apply_existing_source_number_patch:503` | Только два новых внутренних определения, активных producer callers нет |
| `_apply:448` | Новый caller и прежние native/registry command paths; отдельно определяет actual column и metadata identity assignments |
| `_assert_numbers_free:290` | Общий guard получает только changed assignments; Core company predicate, current values + protected histories + dated number links |
| `_prepare:327` | Без изменений: прежняя public DTO связывает station number и metadata number |

AST comparison с immutable base: все прежние определения, кроме `_apply` и
`_assert_numbers_free`, неизменны. Locks/hash namespace/ID validation,
manual-name provenance, native DTO, wrappers, producers, models, schema и auth
не менялись. `rg apply_existing_source_number_patch clearledger/server/app`
на candidate находит только определение, без подключения W07/W08/W10.

В `_apply` freeze и typed history/no-reuse остаются общими. Actual новый
`metadata.number` проверяется независимо от колонок, включая hidden current
aliases, typed code/station reservations, старую numberHistory и закрытые dated
links. Unchanged pre-existing shared колонка не считается новым assignment при
изменении второго номера. Clear — actual identity change с freeze/history
guards, но empty destination не выдаёт новый занятый номер. Guards завершаются
до ORM mutation; отказ не создаёт audit/projection. Сам command audit/projection
не пишет и возвращает обычный `Mutation` для будущего caller.

Защищённые histories, manual name provenance, sourceRaw и opaque siblings
сохраняются. Actual outgoing values идут в прежние typed/legacy histories через
общий writer; known malformed histories fail closed при identity change.
Canonical identity no-op не ремонтирует историю и не создаёт freeze conflict;
полностью identical replay не меняет state/history. Raw представление строки
может измениться при равной canonical identity без новой выдачи номера.

Non-null stored metadata root (`False`, list, string, int) не превращается
через `or {}` в пустой dict: requested metadata number или actual column
identity change даёт 409. Column canonical no-op при omission metadata сохраняет
opaque root verbatim. Nullable root с наблюдаемым Python `None` поддерживается
отдельно; omitted metadata.number не выдумывается. SQL NULL и JSON null здесь
специально не различались: название nullable test case не доказывает два
отдельных round trips. Opaque malformed fieldProvenance не чинится.

Согласованное сопутствующее усиление **общего** `_assert_numbers_free`:
non-null non-dict metadata root у catalog row даёт generic 409, поскольку
невозможно доказать отсутствие protected aliases. Nullable catalog root
остаётся допустимым. Это не ремонт hidden row и не её ORM load. Данный guard
затрагивает прежних public callers при новой выдаче номера; это отдельное
additive fail-closed поведение, а не обещание исправить любой malformed target
во всех native paths. No-op без occupancy scan не запускает этот guard.

## Numeric representation: измеренная граница JSONB

Первый candidate прошёл 120 новых/561 combined тестов, однако заключительный
source review выявил непокрытую границу float JSONB representation. По отдельному
согласованию добавлены ровно три cases и bounded round-trip probe в той же
выделенной БД. Probe измерил:

| Python input / JSON lexeme | JSONB/driver после чтения |
|---|---|
| `1e+20` | int `100000000000000000000` |
| `-0.0` | float `0.0` |
| `1.0`, `1.25` | float с тем же обычным представлением |
| `2.305843009213694e+18` | int `2305843009213694000` |
| `1e+100` | int со 101 цифрой |

До correction эти три новых cases на первом candidate дали 3 FAIL: missed
hidden numeric reservation, non-noop fresh-session replay и missed negative-zero
reservation. Это дефекты первого **нового** candidate, не доказанные дефекты
старого public DTO. Source-specific validator теперь до occupancy/history
приводит zero к `0.0`, integral exponential float к `int(Decimal(str(value)))`.
`int(float)` не используется: он округлил бы binary value иначе JSON lexeme.
Ordinary `1.0` и fractions сохраняются. Length проверяется на нормализованном
driver representation, поэтому `1e100` отклоняется 422. Глобальные `_number` и
`_prepare` не меняются. Все три cases входят в финальные 123/564 PASS.

## Actual baseline и проверки

До отдельного exact SQL grant выполнялись только source/AST preparation, без
pytest/DB/admin. После grant последовательные прогоны использовали immutable
base runtime, затем candidate, Python 3.13.7 и actual isolated PostgreSQL 16.15.
Baseline получает **те же final test bytes**, а не missing-symbol assertion.

Финальный bounded baseline: **5 FAIL / 2 PASS**, 0 ERROR/SKIP:

* Future independent `_apply` harness принимает reserved metadata number:
  actual `[null, "col-initial", "technical-retired"]` вместо expected 409 и
  прежних values. Это characterization будущей независимой интеграции;
  public coupled metadata-number collision control самостоятельно **PASS**.
  Отсутствие нового command на базе не называется production defect.
* Actual native PATCH с valid target и hidden OTHER malformed catalog root:
  `False` и `[]` дают 200, string и int дают 500 вместо нового generic 409.
  Nullable OTHER root control самостоятельно **PASS**. Статусы сохранены
  в JUnit properties; не все malformed cases объявлены прежними 500.

| Прогон, 30.10.2026 MSK, JUnit start | Результат | Pytest / JUnit time |
|---|---|---|
| Первый baseline, 08:09:11 | 5 FAIL / 2 PASS, initial test hash | 17.48 / 17.479 s |
| Первый candidate, 08:16:09 | 120 PASS | 27.44 / 27.442 s |
| Первый combined, 08:20:42 | 561 PASS = 120 + 441 | 73.56 / 73.564 s |
| Numeric characterization на первом candidate, 08:33:09 | 3 FAIL, 0 ERROR | 16.22 / 16.221 s |
| Финальный same-file pinned baseline, 08:35:29 | 5 FAIL / 2 PASS | 16.50 / 16.502 s |
| Финальный candidate, 08:36:28 | **123 PASS**, 0 FAIL/ERROR/SKIP | 27.42 / 27.427 s |
| Финальный combined, 08:38:10 | **564 PASS = 123 + прежние 441**, 0 FAIL/ERROR/SKIP | 74.04 / 74.046 s |
| Финальный opt-out, 08:40:23 | 1 module SKIP, 0 collected, expected exit 5 | 0.08 / 0.087 s |

Runner wall-time для final baseline 28.138 s, candidate 38.737 s и opt-out
10.854 s. Полный runner wall-time final combined отдельно не сохранён;
JUnit/pytest time измерены. Все child processes завершились и были reaped.
Ранние 120/561 PASS не подменяют финальное доказательство numeric boundary.

Новые cases проверяют independent omission/null/empty/scalars и divergent legacy
values; настоящую capability/session/company/root/commit/rollback границу и
отказ late ID без SQL lock; missing existing target; hidden reservations и
malformed histories; freeze sessions/contracts/inventory/export и clear;
сохранение protected siblings; no mutation при guard failure, no audit/commit;
pending факты до/после
explicit flush; clean-entry dirty/deleted/unrelated; same-root sequential patch;
caller rollback; текущие O EMPTY/subset и G mismatch/match; foreign held row;
stale ORM reload после controlled wait. Конкурентные проверки используют
отдельные sessions, controlled events и observed PostgreSQL wait graph из
foundation harness. Sleep не используется как доказательство ordering.

Все 13 прежних test modules byte-identical базе: manual names 68, lock sets 60,
identifier history 89, number scope 34, commands 84, number history 43, metadata
merge 3, mapping 29, freeze 6, bindings 5, object scope 5, scope screens 11,
projection 4 = 441. Assertions/goldens в этом slice не менялись.

## Hashes и воспроизводимость

| Артефакт | SHA256 |
|---|---|
| Base `location_commands.py` | `c30d118b25c504e8921817183f1d5738ac39a216aed6534f3857e13f6ee0cfb4` |
| Final `location_commands.py` | `855d25a55bc64d8ab4f55cb2b364e62972d35b8d0d6c486f8c985f17102bb4ba` |
| Final новый test file, baseline/candidate/combined | `90e6276d1feb30d960ffa011c6d10021e978b8c337c3a64b6cd3a0bb4278f945` |
| Superseded initial test file (120 cases) | `55ee3b7a1702f9736bd8bc0c010eaa963b51bbd0fbdeb4cf4cffdd8da42f1a0d` |
| Первый candidate runtime до numeric correction | `e25d1e41f353bee83ceb7d592c66b3b43165b50d09c5bdd0ab7b55d7a253196c` |

Private ignored evidence в рабочем дереве:
`.artifacts/location-source-number-patch/`: exact-target `runner.py`,
`source-boundaries.json` (включает SHA256 всех 13 old modules),
`baseline-before-numeric.xml`, `candidate-before-numeric.xml`,
`regressions-before-numeric.xml`, `numeric_probe.py`, `numeric-roundtrip.log`,
`numeric-candidate.xml`, final `baseline.xml`, `candidate.xml`, `regressions.xml`,
`skip.xml`, соответствующие stdout logs и `cleanup.log`. Connection details и
private runner не включены в public commit. Evidence использует только generic
synthetic fixtures, без private deploy inventory/координат/финансовых данных.

Runner до подключения проверяет exact scheme/host/port/user/password/db/query/
fragment назначенного synthetic target/admin, пустой cwd, absolute source/test
paths, equal `TEST_DATABASE_URL=DATABASE_URL`, explicit test UPLOAD_DIR.
`APP_ENV=test`, `PYTHONNOUSERSITE=1`, plugin autoload off и explicit asyncio
plugin; HOME/CODEX_HOME не переопределяются, `.env` не читается.
`partner_test_safety_error` исполняется до pytest import, в модуле есть отдельный
opt-in `RUN_LOCATION_SOURCE_NUMBER_PATCH_TESTS`; combined включает все прежние
семь opt-ins. Setup/test/probe/drop выполнялись последовательно, только в
назначенном SQL окне и своей БД, без изменения server settings.

Cleanup измерен fresh connections: own conns 0, `public`+`edge` tables 0;
штатный own `DROP DATABASE` без FORCE/terminate; fresh dbexists 0, own conns 0,
other client connections 0, `max_locks_per_transaction=64` неизменён. Inspector
и admin connections закрыты. Координатору отправлен **SQL_SLOT_RELEASED**;
после release SQL больше не выполнялся.

## Граница принятия и rollback

Это dormant prerequisite, не activation полного B. Native DTO не получает
independent source semantics. Ни один import/normalize/unit/link/session path
не подключён к новому command; W07/W08/W10 и дальнейшая reconciliation/provenance
wave остаются отдельными prerequisites. Подготовка полного target set,
admission source caller и protocol всех сопутствующих freeze producers должны
быть доказаны до activation. Тесты не доказывают устранение всех import races
или произвольных inventory/export concurrency schedules.

Rollback — возврат трёх файлов/коммита к базе; DDL/data migration нет. Формат
existing typed/legacy history и сохранённых metadata siblings совместим со
старым reader. Старый runtime не знает нового internal API; будущих callers
нельзя оставлять активными при его rollback. Возврат общего catalog guard
также возвращает прежнее менее строгое поведение malformed OTHER root.
Изменённые номера при необходимости откатываются только утверждённым command
с сохранением истории: no-reuse и сохранение inventory остаются каноном.

Не выполнялись realenv, реальные API/HTTP acceptance, SSH, browser, финансовые
правки, full security scan, merge, deploy или создание PR. Test client HTTP
применялся только к локальному ASGI приложению в synthetic PG cases. Source
review и перечисленные SQL regression/concurrency cases не заменяют отдельную
приёмку будущей producer activation.
