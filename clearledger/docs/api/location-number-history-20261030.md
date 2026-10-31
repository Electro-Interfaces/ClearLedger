# История номеров поддерживаемых команд объектов

> Уточнение границы доменов от 30.10.2026: прежнее включение technical code в
> numberHistory противоречит M05-C, поскольку station readers считают каждый
> было алиасом номера станции. Исторические 190 PASS ниже сохраняются как
> результат прежнего состава, а не доказательство правильности этой семантики.
> [Разделение доменов и новые actual reader controls](location-identifier-history-20261030.md)
> заменяет только code-history контракт; прежние ACL/freeze/no-reuse/rollback
> требования сохраняются. Времена/хеши старого отчёта не переписываются.

30.10.2026. Source checkpoint до изменения: `2326f905`, пакет C из W1/M05.
Граница исследования writers: [M05 audit](OBJECT_LIFECYCLE_WRITERS_20261030.md).
Реализовано и проверено локально; merge и выпуск не выполнялись.

## Исходный контракт

[`session_scope.station_locations_sql`](../../server/app/services/session_scope.py)
ищет JSONB containment `{"было": string}`;
[`stations_normalize.build_station_index`](../../server/app/services/stations_normalize.py)
читает тот же ключ, выбирает ЭЗС и отдаёт приоритет текущему station_number при
коллизии. `_assert_numbers_free` уже резервирует history alias, включая прежний
номер этой же карточки. Дополнительные поля записи совместимы с читателями.

До исправления `_apply` менял code/number, не сохраняя уходящий alias. Следующий
create мог занять освобождённое значение. История наблюдённых изменений устраняет
этот дефект в поддерживаемых командах; период действия номера из неё не выводится.

## Реализованное поведение

Общая команда после существующих ID→company advisory locks, reload и проверки
freeze собирает непустые уходящие значения code, station_number и metadata.number.
Номер 0 сохраняется как строка `"0"`. При расхождении колонки и metadata сохраняются
оба уходящих значения; одинаковый alias внутри операции добавляется один раз.
Имя объекта к numberHistory не относится. station_number по-прежнему производится
из metadata.number, нового входного поля API нет.

Новая запись имеет вид:

```json
{
  "было": "old-number",
  "field": "station_number",
  "source": "native.locations",
  "actor": "synthetic-actor-id",
  "recordedAt": "2026-10-30T00:00:00+00:00"
}
```

`field` фиксирует первое изменённое поле для данного alias в порядке code,
station_number, metadata.number. `recordedAt` обозначает время наблюдённой команды,
не начало или конец действия номера. Actor означает автора этой команды, а не
владельца прежнего номера в прошлом. Native wrappers передают известный user.id,
registry wrapper — actor.id и source `registry.objects`; общий вызов без контекста
пишет actor=null, source=`unknown`. Email/name в новые записи не добавляются,
атрибуция прежних записей не дополняется текущим пользователем.

История строится новым деревом metadata, без изменения ссылок на прежние dict/list.
Она входит в единственное изменение extra_metadata у Mutation и registry audit;
новых audit/projection вызовов нет. Commit остаётся у caller, rollback откатывает
и номер, и alias. Исходные raw snapshots, source history, ручные ссылки и
sourceBindings сохраняются прежним merge. Omitted/null semantics не изменены.

После разрешённого переименования прежнее значение остаётся занятым для create
и обычного PATCH, в том числе для исходной карточки. Force/reuse flag не вводился.
Initial create, no-op, name/address-only не создают history. Повтор запроса с тем
же новым номером не добавляет запись.

Native POST upsert и PATCH поддерживают code и metadata.number. Registry HTTP
ObjectPatch поддерживает code; metadata отсутствует в его модели и по-прежнему
игнорируется как extra payload. Schema реестра не расширялась. Native JSON metadata
теперь достоверно содержит добавленные сервером записи истории после смены номера;
это ожидаемое добавочное изменение ответа. Registry card JSON сохраняет прежнюю форму.

## Legacy и решения source review

Координатор подтвердил два решения до соответствующих правок:

- Absent/null/[] допускают начало истории. Non-list или list с non-dict entry
  дают 409 с требованием сверки только при реальном уходе непустого alias, до
  mutation. No-op и правка имени/адреса не чинят и не нормализуют такую историю.
- Dedup для совместимого поиска требует exact canonical STRING. Legacy записи
  `{"было": 0}` и `{"было": " old "}` резервируются старым guard, но не соответствуют
  SQL containment по `"0"`/`"old"`. При фактическом уходе номера они сохраняются
  целиком, а рядом добавляется новая совместимая строковая запись. Повтор не
  добавляет ещё одну; чтение и no-op не запускают эту операцию.

Старые dict entries, неизвестные поля и их JSON-содержимое сохраняются. Существующие
дубли station_number, opaque/deterministic IDs и legacy aliases не перенумеровываются.
Нет массовой reconciliation, DDL, новых readers, valid-time или retirement API.

## Проверки и доказательства

PostgreSQL 16, только выделенная координатором synthetic DB. Private runner в
`.artifacts/location-number-history/runner.py` проверяет точный назначенный target;
адрес, имя БД и пользователь не зашиты в committed tests. Empty cwd, абсолютный
PYTHONPATH, явные одинаковые DATABASE_URL/TEST_DATABASE_URL и отдельный test UPLOAD_DIR;
Python 3.13.7 из предоставленного venv. HOME/home/CODEX_HOME не переопределялись;
real .env, auth keys и global configs не читались и не менялись.

| Прогон | Результат |
|---|---|
| До fix, baseline | 3 ожидаемых FAIL потери old code через native/upsert/registry и 1 FAIL: create присвоил old number с 200 вместо 409 |
| Первоначальный reader case | FAIL с fixture type=other; отдельно не доказывает дефект reader и не засчитывается как positive evidence |
| До fix, reader с positive control | 1 ожидаемый FAIL, 4 deselected: оба actual readers находят current number до rename; после native PATCH index=None и SQL=[] |
| Первый focused candidate | 39 PASS, 1 FAIL нового неверного ожидания metadata через registry; source подтвердил отсутствие поля, исправлен только новый тест |
| Final combined candidate | **190 PASS / 0 FAIL / 0 ERROR / 0 SKIP / 0 DESELECTED, 34,67 с** |

Final batch: 43 новых случая и 147 прежних из `test_station_mapping_admission`,
`test_location_commands`, `test_location_metadata_merge`, `test_object_freeze`,
`test_location_bindings`, `test_object_scope`, `test_scope_reaches_screens`,
`test_space_projection_batching`. Старые тесты и assertions не менялись.

Новые проверки используют actual native POST/PATCH, registry PATCH и общую команду,
fresh sessions после сохранения, реальный SQL обоих readers с positive controls,
rollback до commit и при ошибке projection после flush, повторы, concurrent edits
со stale identity map под блокировкой, отсутствие потерянных aliases, numeric0 и
whitespace legacy, разные старые column/metadata, explicit clears, no-op/name-only,
raw/manual links, metadata history, audit/projection и непрозрачные IDs. Прежний
batch проверяет tenant/object/organization admission, freeze, порядок блокировок
и mapping regression. Это focused domain regression, не полный repository CI.

Локальные log/JUnit: `.artifacts/location-number-history/{baseline,baseline-readers,
candidate-focused,candidate-combined}.{log,xml}`. Исторические baseline выполнялись
до финального расширения тестового модуля; результаты не выдаются за тестирование
финального SHA на исходном runtime. После финального batch runtime/tests не менялись.

SHA256 финального проверенного состава:

| Файл | SHA256 |
|---|---|
| location_commands.py | `c6984e7d211f9b6939da1ae1b9c75276bb9169f473d6442c825097efff6e5896` |
| locations_router.py | `8ad9fa597212a71ef0cbc08ea9f36ae8b0fa120862fd7726e0c89e7a8cdca894` |
| space_registry.py | `bdf7dbecd3ec34a11e5e7eacf4a2ad092d40f575dae9b47481a232b59ddf0c6c` |
| test_location_number_history.py | `625a8329ffc8de89f4ee2b221dd042d50cd023250cc4b33d7c58cd404e27efdb` |
| candidate-combined.xml | `6eb98d9dcbe394880ebd460b3ac8e242833c2320c2b5e6d826db4629d0d34850` |

После завершения процессов свежие PG snapshots подтвердили 0 подключений к своей
БД и 0 других client backends. БД удалена без FORCE/terminate; новый snapshot
подтвердил own connections=0, other client backends=0, DB exists=0. max_locks=64
сохранён. Proof: private `.artifacts/location-number-history/cleanup.json`;
SQL slot отдельно передан координатору как RELEASED перед завершением worker.

## Граница гарантии

Сохранение и резервирование alias доказаны для общей поддерживаемой команды и
её native/registry wrappers. Imports, bulk bypass, OneC и другие writers из M05
audit остаются вне этого пакета. Global no-reuse, полнота исторических событий,
миграция старых данных, retirement и temporal semantics этим изменением не обещаны.
Models/auth/scope/DDL/dependencies, UI и рабочие данные не менялись. Проверки
браузера, полный CI, production API и развёртывание не выполнялись.


Независимая проверка координатора после переноса32c1788a какd858840a:
**190PASS за31.64с**, без SKIP/DESELECTED, те же43новых+147прежних.
Пустойcwd/абсолютныепути/явныеtestURLs/UPLOAD_DIR, HOMEсохранён безoverride.
После завершенияpytest fresh0connections/publictables0/maxlocks64; owntestDB
удалена обычнымDROP безFORCE/terminate, freshDBexists0/connections0.
Это проверка данного состава, не global no-reuse: отдельный source review
проверяет, не скрывает ли ORM object scope чужие alias rows от company-wide
проверки занятости. Scope чтения для пользователя расширять не предлагается.


## Повторный архитектурный review: граница code и номера

После первоначальной приёмки координатор обнаружил несогласованность с пунктом C
карты writers: `code` попадает в `numberHistory`, хотя actual session readers
трактуют каждый `было` как номер станции и не фильтруют `field=code`.
Результат190PASS остаётся фактом проверенного состава, но не доказывает
разделение технического кода и номера. Нужен отдельный baseline с различными
code/station_number, отрицательным контролем обоих readers для old code и
положительным для actual old number. До этой проверки и исправления пакет
не принимается как завершение истории идентификаторов M05. Изменения ещё
не merged/deployed, рабочих записей этим кандидатом не создавалось.


Повторный review завершился исправлением `1f0cf49a`: технический code хранится
в typed identifierHistory, а numberHistory содержит только фактические номера.
Независимые 313 PASS за49,05с подтвердили оба actual reader negative/positive
контроля, сохранение reservation и прежние права. Актуальный контракт и пределы
приёмки описаны в [новом отчёте](location-identifier-history-20261030.md).
Исторические 190 PASS выше относятся к прежнему составу.
