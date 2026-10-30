# M05-B foundation: полный набор location locks

30.10.2026. База `a9be3e638b120dee9324182b34d9b10aa5970a4a`.
Принятый design: `11c5a2919886e7f0936466bdc031c4fa67965ecb`.
Ветка `agent/api-location-lock-sets-20261030`; исходная design branch и её origin
ref сохранены на11c5a291. Изменены только `services/location_commands.py`, новый
`tests/test_location_lock_sets.py` и этот отчёт. Foundation проверен на isolated
synthetic PostgreSQL16; **activation B не выполнена**.

## Реализованный контракт

`location_commands.py:70–181`: `LockedLocationSet`, `acquire_location_set` и
session-local entrance marker. `locked_visible_in_set` расположен с230-й строки.
Существующие public single-ID функции, freeze и typed identifier history
сохраняются. Из прежних функций изменены только `_barrier` и `_locked`; общая
row query вынесена в `_reload_location`, без копирования командного writer.
AST остальных прежних функций/классов совпадает с immutable baseline.

Пример internal API для заранее известного полного набора:

```python
locked_set = await acquire_location_set(db, company_id, all_identifiers)
location = await locked_visible_in_set(db, company_id, identifier, locked_set)
# Caller revalidates intent, then applies its admitted operation and owns commit.
```

Это не новый публичный endpoint или business service. Import/unit/link/session
producers, routers, auth, models, DDL, старые tests и принятый план не менялись.
SourcePatch, provenance и changed_assignments из design сюда не входят.

### Порядок и lifetime

- Сначала валидируется весь набор прежним `validate_identifier`: opaque строка
  1..40 символов без NUL. Пробелы, регистр и Unicode не переписываются. Строка
  вместо коллекции отклоняется422. Дедупликация и сортировка по Python string
  order до первого lock; locale/SQL collation не участвуют.
- Берутся **все** прежние global ID keys, затем прежний company key. Namespace
  `location-command:v1:{namespace}:{value}`, UTF-8 bytes, BLAKE2b digest_size8,
  big-endian signed bigint и transaction-scoped SQL сохранены. Empty set берёт
  только C и тоже не разрешает позднее добавление ID.
- Capability immutable и связана с конкретными db object, sync root transaction
  object, company string и frozenset. Проверяется также object identity токена
  в session-local marker. Конструктор/`dataclasses.replace` не дают authority;
  токен другой session/root/company и старый токен после новой autobegin T
  отвергаются generic409 до SQL.
- Повтор того же set или subset возвращает исходный токен без новых locks.
  Extension, другой company и случайный old `_barrier/_locked/update/upsert/create`
  с неизвестным ID внутри prepared T дают generic409 **до** lock SQL. Для заранее
  включённого ID old commands продолжают guards/mutation, не получают новый lock.
- Marker отмечает также прежний single entrance **до** acquisition. Подготовка
  набора после него запрещена, даже для того же ID: наличие уже взятого C нельзя
  объявить безопасным началом batch. Обычные single-ID→company вызовы вне
  prepared context сохраняют прежние outcomes и caller commit ownership.
- Modes preparing/failed не дают токен и запрещают продолжение через old/new
  entrance. Прерванный acquisition мог взять часть IDs: нужна outer rollback.
  Отмена собственного ожидающего query проверена, чужие sessions не terminate.
- Root commit/rollback/close инвалидирует токен. SAVEPOINT после acquisition
  сохраняет root capability и предварительно взятые advisory locks и после
  release, и после rollback SAVEPOINT. Fresh acquisition внутри SAVEPOINT
  отклоняется: иначе rollback освободил бы locks при ещё живом root token.

### Reload, pending state и admission

Lookup проверяет токен, затем делает tenant-qualified FOR UPDATE с
populate_existing и текущую `_assert_visible`. Чужая tenant row не грузится и
не блокируется, даже если её ID был предварительно advisory-locked. Проверка
O/G выполняется при lookup после wait; capability не кэширует разрешение.
Principal не передаётся в эту API, поэтому **live membership reload/revocation**
во время wait не обещается. Membership остаётся обязанностью старого caller.
Тесты проверяют текущий ContextVar O и DB evidence для выбранного G, не новый
механизм аутентификации или сброс scope.

`db.no_autoflush` действует на reload и admission query. Посторонние pending
entities разрешены и не flush/commit. Сам target с реально изменёнными ORM
атрибутами отклоняется409 до SQL через inspect(identity)/is_modified, чтобы
populate_existing не стёр pending values. No-op dirty tracking без изменения
значений не считается потерей данных. Caller применяет patch **после** reload;
обычный `_locked/update` вне нового lookup этим guard не изменён. Ни lock APIs,
ни их ошибки не выполняют commit, rollback или domain mutation.

## Что должен сделать caller перед activation

Набор должен охватывать всю настоящую root T и быть подготовлен до несовместимых
row/FK writes/flush. После lock wait caller повторно проверяет identity evidence,
cardinality, targets и уже существующее admission. Неизвестный новый target
требует отказа/reconciliation; нельзя расширить набор после C или сделать
mid-import commit ради освобождения locks.

Marker замечает вход через наши прежние commands, но **не может обнаружить
произвольные прошлые SQL locks**. Чистый entrance marker не означает, что любой
существующий unit/session/import caller уже безопасен. Fresh set после обычных
MVCC discovery reads допустим; после неизвестных blocking writes это обязанность
caller, а не автоматически проверенная гарантия токена.

Этот пакет защищает advisory subgraph только при соблюдении полного set contract.
Naive old multi-command harness вне prepared context всё ещё способен построить
cycle: single outcomes намеренно не переписаны. Общая перестановка row/FK/unit/
document/link порядка, planning многолистовых книг и сессий, stale source indexes,
raw/source/manual authority, chunk commits и reconciliation/UI принадлежат
следующим prerequisites принятого design. Большие sets/lock budget, нагрузка и
все их расписания здесь **не измерялись**. max_locks_per_transaction не менялся.

No-reuse и сохранение inventory остаются каноном. Этот foundation не исправляет
старые bypass producers, receipt-cancel/delete или исторический reservation ledger
и не подключает unsafe paths. Полный security scan, production HTTP acceptance,
merge/deploy и realenv не выполнялись; из synthetic ASGI-тестов не следует OAuth
или эксплуатационная приёмка.

## Проверка и разделение evidence

До отдельного SQL grant выполнены только source/test preparation и AST/diff.
Grant прочитан и подтверждён до admin/test. Private runner проверяет exact
назначенный synthetic target до connect/pytest, использует empty cwd, абсолютные
PYTHONPATH/test UPLOAD_DIR, равные TEST_DATABASE_URL/DATABASE_URL, assigned Python
3.13.7 и все6opt-in flags; HOME/CODEX_HOME не переопределяются. Новая test suite
использует общий `partner_test_safety_error` и настоящий ORM listener. Новые tests
не меняют PG settings, не используют sleep как доказательство wait; время
ограничивается asyncio. Setup/pytest/drop выполнялись последовательно.

| Проверка | Результат | pytest / runner |
|---|---|---|
| Before-fix v1 characterization, pinned a9be3e63 | 1 PASS: две actual advisory `pg_blocking_pids` дуги, ровно один SQLSTATE40P01, второй participant завершился, rollback обоих | 16.20 /29.135с |
| Final same-file v1 characterization, тот же pinned runtime | 1 PASS, final test bytes те же, что у final candidate | 17.69 /29.707с |
| Первый foundation candidate | 54 PASS; затем добавлены prepared mutation/company и dirty-target cases | 21.12 /34.467с |
| Combined до dirty-target review | 59 новых+313 старых =372 PASS | 56.15 /67.774с |
| Dirty-target characterization первой версии foundation, final same-test | 1 ожидаемый FAIL: actual state `[null,"Synthetic point",false,"Synthetic point"]` вместо409/pending/modified/unchanged DB | 15.99 /27.066с |
| **Final candidate combined** | **60 новых+313 старых =373 PASS**, 0 FAIL/ERROR/SKIP/DESELECTED; EXIT0, child reaped | **53.21 /64.828с** |
| Opt-out | 1 module SKIP, collected0, штатный pytest EXIT5; fixtures/SQL не запускались этим модулем | 0.08 /10.974с |
| Fresh cleanup | own connections0, public+edge tables0; normal own DROP без FORCE/terminate; fresh DB exists0/own conns0/other clients0/maxlocks64 | EXIT0 |

Первый before-fix v1 run использовал test module hash8928be34…; после добавления
coverage финальный pinned run повторён с7abf32d4…, совпадающим с final combined.
Baseline не запускал candidate-only cases и не называл отсутствие новых symbols
дефектом старого runtime. Harness — будущая **наивная** интеграция существующих
commands, не существующий import path. Это отдельное доказательство cycle.

Dirty-target FAIL относится к первой новой foundation версии, не к integration
baseline или старому импорту. В final test исправленный результат записан как
`[409,"Synthetic unflushed target",true,"Synthetic point"]`, lookup не отправил
SQL, unrelated pending case прошёл. Первоначальный54-case и372-case успехи этим
дополнительным proof не заменяются и не выдаются за окончательную приёмку.

Все11старых test modules побайтно совпадают с a9be3e63; assertions не менялись.
Их final counts: commands84, mapping admission29, metadata3, freeze6, bindings5,
object scope5, scope screens11, projection4 =147; number history43, number scope34,
identifier history89; итого313. Новые60 считаются отдельно, включая v1 harness.

Actual SQL coverage нового модуля: reverse/overlapping sets и разные company
при shared global ID, реальные native PATCH/upsert/registry и mapping POST,
old single owner до set, contested late ID без попытки нового wait, root/
SAVEPOINT/commit/rollback/close/autobegin, repeat/subset, late preparation,
opaque invalid IDs, wrong/forged token, partial acquisition cancellation,
held foreign row, stale ORM reload, current O/G после observed wait, unrelated
pending, dirty target и known-ID freeze/typed history/caller rollback. Применение
PG observer ограничено собственными synthetic session PIDs; pids/логи в public
repo не включены. Первые runs дали JUnit record_property-format warnings; final
runner использует legacy JUnit format, final combined предупреждений не вывел.

После завершения всех дочерних процессов свежая проверка подтвердила cleanup,
своя DB удалена без FORCE, `SQL_SLOT_RELEASED` отправлен координатору. После
release SQL не выполнялся. Private runner/logs/JUnit/manifest находятся в
`.artifacts/location-lock-sets/`, в Git не включены. Runtime acceptance ограничена
этим synthetic тестовым набором; full repo CI и большой concurrency/load sweep
не выполнялись.

## Хеши артефактов

| Артефакт | SHA-256 |
|---|---|
| Pinned integration location_commands.py | `e581d0ec265de072a9b9c547b689efe300adf179ea845cab4cc246dae759dc70` |
| Final location_commands.py | `f981511ff74790b892fc7e4cf8c2ad9ab619686719c36b1aef5e6235f998c53b` |
| Final same-file test_location_lock_sets.py | `7abf32d441808f235318cbfd1342a6ef6c1ccc8dc24dfb2d1542bcdb9abdd653` |
| Foundation before dirty guard | `1fc830fc1a898adc92d1bbd1a98da2d577288d71bc8dfe8377376efe9612152b` |
| Private baseline-before-fix.xml | `4de4b51db6706176b457126d5bb6a0ffa0ced3e70e62afc88d2fd24d6cb6d53d` |
| Private baseline.xml | `ed0eb41009141ea818562a0c2e56c266563f027d7c4e11d97cc48d68166923df` |
| Private dirty-baseline.xml | `840be7bc030e426a151346aa7c4be7b6c0c6ed86bbda77d90530794fdac4747c` |
| Private regressions.xml | `00c19c09846a65ddb28803f1abadbb2cb7e302718b909243b233ac034b34494c` |
| Private skip.xml | `4d6675ea1ac72b35ed46698474e66d000bb3c382cf0696ba13a0850862a22964` |
| Private cleanup.log | `ae9bb72bdfe309eea60f8ac7c24bf1e8eecddb1a26ae7b64a2b789882141badb` |
| Private source-boundaries.json | `6b84e9e14f7cecd3456058343e859afb657844c370254fa1595ba904c6556eb5` |
| Private runner.py | `059dafd4d378ae13f23fbc5a1835c3241937590691371703c33d012c46e25d66` |
