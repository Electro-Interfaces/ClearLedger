# Раздельная история технического кода и номера станции

30.10.2026. Immutable baseline: `5c0deb220ab328eacad6c098121a46c8fcfb94ad`.
Ветка: `agent/api-identifier-history-domains-20261030`.
Задача продолжает принятый scope collision slice; source карта M05-C прямо
запрещает класть technical code в numberHistory. Этот пакет не меняет readers,
models/DDL, routes/auth, финансы, map или root IMPLEMENTATION_STATUS.

## Граница и подготовка

Разрешены только location_commands.py, новый test_location_identifier_history.py,
обоснованные code-history ожидания в прежнем test_location_number_history.py,
этот отчёт и superseded-domain примечание в прежнем number-history отчёте.
147 прежних регрессий и 34 scope случая остаются побайтно прежними.

Новый PG baseline использует A с code=code-0 и station_number=number-0,
type=ev_charging, без session aliases. До rename оба actual readers находят
number-0, но не code-0. После code-only rename через native/upsert/registry
ожидается сохранение current number и отсутствие соответствия old technical code.
Upsert явно сохраняет EV type: отрицательный результат нельзя получить,
случайно превратив карточку в type=other. Отдельный positive control проверяет,
что после настоящего number rename old station number читается обоими readers.
Фактический baseline подтвердил false match в обоих readers; результаты ниже.

## Согласованный контракт

identifierHistory содержит наблюдённые изменения domain=code либо station_number,
old/new, actor/source/recordedAt; field отмечает источник наблюдения. Station
clear имеет new=null, technical code очищать нельзя. Совпадающие canonical
domain/old/new дедуплицируются внутри команды; divergent column/metadata old
значения сохраняются оба. Разные домены сохраняются раздельно даже при одинаковом
old code/number. numberHistory получает только actual number и сохраняет
совместимый ключ было со строкой, без определения valid-time.

Серверный identifierHistory: create с supplied key даёт 422, update игнорирует
входное эхо/подделку и сохраняет хранимое значение. Старый numberHistory create
контракт этим пакетом не расширяется. Reservation читает обе известные typed
domains и legacy numberHistory, остаётся company-wide Core и не грузит скрытые
ORM entities. Старый code занят для create/rename, включая исходную карточку,
но не появляется у station readers.

При identity change обе истории должны иметь list-of-dict shape; в известных
typed domains old должен быть непустой строкой, new — непустой строкой для code,
непустой строкой либо explicit null для station_number; отсутствие поля new
не означает null и требует сверки. Повреждение даёт 409 до mutation; скрытая
повреждённая история в company-wide occupancy даёт generic409 без ID/значений.
Unknown legacy dict, numeric/space number aliases и неизвестные поля сохраняются.
No-op/name-only/partial metadata без number не запускают implicit repair.

Исходные locks ID→company, reload, freeze, admission, caller commit/rollback,
raw snapshots, ручные bindings, source/actor и существующие audit/projection
сохраняются. Публичного rename/retire API, миграции или массовой очистки истории нет.

## Проверка

До отдельного SQL grant выполнялись только source/test preparation, AST и diff-check.
READY_FOR_SQL передан координатору до grant; затем использовалась только
назначенная собственная synthetic PostgreSQL 16, Python 3.13.7 из venv.
Новый модуль opt-in RUN_LOCATION_IDENTIFIER_HISTORY_TESTS=1 с общим
partner_test_safety_error и реальным install_orm_scope; guard не содержит
локального target. Private runner проверяет exact synthetic target до admin/pytest,
использует empty cwd, абсолютные PYTHONPATH/UPLOAD_DIR, явные одинаковые
TEST_DATABASE_URL/DATABASE_URL; HOME/CODEX_HOME не переопределяются.
Baseline runtime закреплён immutable SHA, новый test file побайтно тот же,
что в candidate. SQL setup/drop последовательны, cleanup — fresh conns0/tables0,
normal own DB DROP без FORCE/terminate и явный SQL_SLOT_RELEASED.

| Проверка | Состояние |
|---|---|
| AST / diff-check | PASS, source preparation |
| Final 89-case pinned baseline | 54 FAIL, 35 PASS; 28.26 с pytest / 41.689 с runner, exit 1 |
| Focused same-file reader baseline | 3 FAIL, 2 PASS; 17.53 / 28.818 с |
| Candidate 89 новых | 89 PASS, 0 SKIP; 28.54 / 40.024 с, exit 0 |
| Runtime fix | Внесён после actual baseline; readers не менялись |
| 89 новых + 43 исправленных history + 147 old + 34 scope | **313 PASS**, 0 FAIL/ERROR/SKIP/DESELECTED; 46.90 с pytest / 59.091 с runner, exit 0, child reaped |
| Pure helper shape checks | 3 PASS; AST extraction без app imports/SQL |
| Opt-out | 1 module SKIP, collected 0, ожидаемый pytest exit 5; 0.08 / 10.777 с |
| Cleanup / SQL release | PASS: fresh tables0/conns0; normal DROP; fresh dbexists0/ownconns0/other clients0/maxlocks64; SQL_SLOT_RELEASED передан |
| CI / merge / deploy / рабочие данные | Не выполнялись |

43 history случая исходного пакета пересматриваются только в ожиданиях,
которые ошибочно называли technical code station alias. Их исторические 190 PASS
не удаляются и не подтверждают правильность смешения доменов. Неизменённые 147 old
и 34 scope учитываются отдельно от этих исправленных ожиданий и новых проверок.

## Что baseline доказывает

Три actual reader cases (native/upsert/registry) получили после code-only rename
`(location_id, [location_id])` вместо `(None, [])`: первый элемент — настоящий
build_station_index, второй — настоящий station_locations_sql. И до, и после
rename current actual number на той же EV карточке находится обоими readers;
new technical code не находится. Нет ложного negative из-за type=other.
Два самостоятельных positive cases actual old station number прошли на старом
runtime. Focused baseline с -vv/long сохранил полные значения обоих читателей.

Остальные 51 ожидаемых FAIL общего baseline относятся к новому typed/readonly/
failclosed контракту. Это не 51 дополнительные ошибки или уязвимости. Тестовых
ошибок фактического baseline не обнаружено; перед baseline проверка typed station
format выделена из number-reader positive control в отдельный случай, чтобы
reader-positive имел самостоятельный PASS и не зависел от нового формата.
Во всех actual baseline/candidate использован один final test hash.

После 89 PASS source review уточнил одну проверку shape: отсутствующее new у
known station_number entry не должно считаться explicit null. Три pure checks
подтвердили missing-new409, code-new-null409 и station-new-null allowed; final
combined проверяет runtime уже с этой строкой. Test file не менялся.

## Границы регрессий и совместимости

В прежнем test_location_number_history.py сохранено 43 случая. Code-history
ожидания изменены в allowed rename (3), replay (2), absent/empty numberHistory
(3), direct rollback (1), opaque initial-create/code rename (1): всего 10 case
ожиданий и helper code_aliases. Остальные 33 случая не переписаны. No-reuse,
ACL/freeze, legacy number raw/numeric/space, reader actual-number control,
rollback/projection failure и concurrent number edits не ослаблены.
147 old и 34 scope tests не изменены побайтно; исторический отчёт 190 PASS
сохранён, добавлено только superseded-domain примечание. Новый пакет не выдаёт
эти прежние 43 за независимую старую неизменённую регрессию.

Существующие legacy code entries внутри numberHistory не удаляются и не
перетипизируются: по одному неизвестному dict нельзя угадать домен прошлого
значения. Поскольку изменяемый кандидат не выпускался, генерация новых typed
code entries исправлена без правок readers/DDL или массовой миграции.
Старый runtime не понимает typed reservations: code revert после начала их
записи не сохраняет эту гарантию, такой rollback потребует отдельной оценки.
Никаких production schema/data changes, sync/import writers или public retire
API в этот пакет не включено.

## Проверенный состав и очистка

Baseline: runtime извлечён из immutable 5c0deb22 через git archive, новый тест
скопирован без изменения байтов; исходные тесты старого runtime не изменялись.
Candidate и final combined используют ту же новую тестовую программу; в combined
также явно включены RUN_OBJECT_COMMAND_TESTS, RUN_LOCATION_NUMBER_HISTORY_TESTS,
RUN_LOCATION_NUMBER_SCOPE_TESTS, RUN_STATION_MAPPING_ADMISSION_TESTS и
RUN_LOCATION_IDENTIFIER_HISTORY_TESTS. Реальный ORM listener включён; matcher,
scope и admission не monkeypatch-ятся. Synthetic HTTP fixture подменяет только
projection как в прежних tests; отдельный failure case проверяет rollback после
реальной flush и искусственной ошибки внешней projection.

После завершения всех дочерних процессов fresh metadata snapshot подтвердил
собственные public+edge tables=0 и connections=0. Своя synthetic DB удалена
обычным DROP без FORCE/terminate; новый snapshot подтвердил DB exists=0,
own connections=0, other client backends=0, max_locks_per_transaction=64.
SQL_SLOT_RELEASED отправлен координатору; после него SQL не выполнялся.
Private runner/логи/JUnit/cleanup/source manifest хранятся в
`.artifacts/location-identifier-history/`, в Git не включены.

| Файл / артефакт | SHA-256 |
|---|---|
| Pinned old location_commands.py | `8287fcac52c37b6356951c39162620914d681f495fcded3acd49329d1bf1ccf9` |
| Final location_commands.py | `e581d0ec265de072a9b9c547b689efe300adf179ea845cab4cc246dae759dc70` |
| Same-file new test (baseline/candidate) | `00b8013bb43a8c77f46f2fa59a70b431aa8212aea521946592cd8b9d0c193c38` |
| Original 43-case history test | `625a8329ffc8de89f4ee2b221dd042d50cd023250cc4b33d7c58cd404e27efdb` |
| Updated 43-case history test | `e701876feb54e90c002e617973335c44a72b8ac1e07293f363e2785abbabef62` |
| Unchanged 34-case scope test | `5751c0847da505a52d838ed544776d11c58b5d7dd9139749a886096673a261e9` |
| Private baseline.xml | `a7de0eb7c68f71996b7a27f6a9aeaf2e0bb0f0c822b499f1f3c26576589426a1` |
| Private baseline-readers.xml | `985bb15e964a00b0dac7f3325b133f2e7f54c0680b0792178b8d2d6b6dde2d13` |
| Private regressions.xml | `ad66642e8c9fa6096de6e1cdb34cfb92acae375ee7a06a6640d44a467c51df3b` |
| Private cleanup.log | `4945b2cf80e81e217d31995f0646278ab7c50d02563579d4558781baa5853bb5` |
| Private source-boundaries.json | `d7d9dd42e8516997f41d7879d63e357d41b58b193e079ccb04913fbbddaf5bdc` |
| Private runner.py | `f68af05fe3ad801a8cf2ec06555ca8ef524801a250c01598cd8f252e1fb3fa4f` |

Полный repository CI, браузер, рабочий API, merge и deploy не выполнялись.
Гарантия ограничена общей командой и поддерживаемыми native/registry wrappers;
импортные/bulk bypass writers и полнота неизвестного прошлого не подтверждены.
