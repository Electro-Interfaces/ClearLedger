# Проверка занятости номера при ограничении объектов

30.10.2026. Immutable source baseline: `2ed52b9cf9d4333bbc41f0b2722bd33eb03ce02c`.
Задача M05; проверка только на синтетической локальной PostgreSQL после
отдельного разрешения координатора. Merge/deploy и рабочие данные исключены.

## Границы исходников

Владелец изменения: `server/app/services/location_commands.py`,
`server/tests/test_location_number_scope_collision.py` и этот отчёт.
`counterparty_commands`, `charge_sessions_normalize`, models/DDL, auth, ORM
listener, routers, projection и другие writers не меняются. Внешний контракт
ошибок сохраняется, включая исправленный existing404/new403 в upsert.

`scope.install_orm_scope` устанавливает `Session.do_orm_execute` с
`with_loader_criteria(ServiceLocation, ServiceLocation.id.in_(ids))`.
И `_assert_numbers_free` (полные ORM entities), и `code_taken` (ORM column)
выбирают ServiceLocation и потенциально получают суженный набор.
Фактический PG baseline подтвердил влияние listener на обе проверки;
результаты и контроль скрытого чтения приведены ниже.

Фикстура: A и B принадлежат одной компании; actor видит только A;
у B текущий code=`code-1`, station_number=`number-1`, прежний alias=`old-1`.
HTTP PATCH A.code/A.metadata.number и native POST existing-ID upsert пытаются
занять `old-1`. Проверка ожидает generic409 до записи, неизменный свежий Core
snapshot и отсутствие projection. Отдельный positive control проверяет обычные
ORM list/get B и запрет правки B с реальным listener.

Registry HTTP допускает запись только администратору: scoped member должен
сохранить 403; проверка истории registry выполняется с администратором без
подмены admission. Direct command дополнительно покрывает current/history,
tenant, object/EMPTY/org admission, freeze, caller rollback и identity map.
`code_taken` проверяется отдельно; global ID collision при scoped create должен
остаться закрыт 403 до flush. Это не основание расширять ID lookup.

## Проверка и результаты

Opt-in: `RUN_LOCATION_NUMBER_SCOPE_TESTS=1` и `RUN_OBJECT_COMMAND_TESTS=1`,
общий `partner_test_safety_error` без локальных адресов в committed tests.
Private runner обязан проверить exact synthetic target до импорта pytest,
использовать empty cwd, абсолютный PYTHONPATH/UPLOAD_DIR и явные одинаковые
TEST_DATABASE_URL/DATABASE_URL. HOME, home, CODEX_HOME не переопределяются;
реальные .env/auth/SSH и БД не читаются. Baseline и candidate запускают
побайтно одинаковый новый тест; старый app runtime фиксируется immutable SHA.
SQL setup/drop последовательны; cleanup требует conns0 и normal DROP без FORCE
или terminate, после чего передаётся SQL_SLOT_RELEASED.

SQL grant получен от координатора отдельно после READY_FOR_SQL. PostgreSQL 16,
Python 3.13.7 из предоставленного venv. Private runner и логи лежат в локальном
`.artifacts/location-number-scope/`; synthetic target проверяется до импорта
asyncpg/pytest и любого подключения. Исходный app извлечён через git archive
immutable commit; новый тест скопирован без изменения байтов.

| Прогон | Результат | Время pytest / runner |
|---|---|---|
| Initial baseline | 18 FAIL, 14 PASS: 17 product failures и 1 неточное ожидание теста | 19.84 / 33.841 с |
| Collision baseline, 32 случая | 17 ожидаемых FAIL, 15 PASS | 21.22 / 32.881 с |
| Collision candidate, тот же 32-case hash | 32 PASS, exit 0, child reaped | 18.34 / 32.104 с |
| Combined 162 / затем 191, до admission fix | 161 PASS + 1 FAIL / 190 PASS + 1 FAIL | 34.18 / 45.782 с; 37.38 / 49.508 с |
| Pinned old admission control + hidden-read positive control | 1 FAIL (403 вместо 404), 1 PASS | 15.35 / 26.702 с |
| Final pinned baseline, 34 случая | 18 ожидаемых FAIL = 17 collision + 1 admission; 16 PASS | 19.47 / 31.190 с |
| Final candidate, тот же final test hash | 34 PASS, exit 0, child reaped | 19.11 / 30.434 с |
| Final combined: 34 новых + 43 history + 147 прежних | **224 PASS, 0 FAIL/ERROR/SKIP/DESELECTED**, exit 0, reaped | 35.47 / 47.139 с |
| Opt-out guard | 1 module SKIP, collected 0; ожидаемый pytest exit 5 | 0.11 / 11.024 с |
| AST двух Python-файлов / diff whitespace | PASS | — |
| Cleanup own DB / SQL release | PASS: public+edge tables0, own conns0; normal DROP, fresh dbexists0/conns0/other client backends0, maxlocks64; SQL_SLOT_RELEASED отправлен | — |
| Полный CI, merge, deploy, проверка рабочего API | Не выполнялись | — |

Initial ожидание исправлено только для disjoint scope: `update` штатно
возвращает None, когда listener скрывает строку; explicit EMPTY допускается
listener до `_assert_visible`, который поднимает 404. Это сохраняемые варианты
контракта команды, не продуктовый дефект. После поправки повторён baseline
на прежнем неизменённом app, до runtime fix; оба baseline log сохранены.

В collision baseline все четыре HTTP попытки (PATCH/upsert × code/metadata.number)
вернули 200 с присвоенным `old-1` вместо 409. Двенадцать direct current/history
проверок не подняли LocationConflict, а code_taken вернул False для текущего
кода B. Positive control: ordinary ORM list/get B не возвращает строку; HTTP
list содержит только A, PATCH B закрыт 404. Все 15 контрольных случаев 32-case baseline прошли.
Unique index по текущему code не мог защитить исторический alias `old-1`.

## Узкое исправление

`code_taken` и `_assert_numbers_free` используют `ServiceLocation.__table__.c`
с обязательным company predicate. Первая выборка читает один scalar id с LIMIT 1;
вторая читает id/code/station_number/extra_metadata, необходимые старому matcher.
Скрытые ORM entities не создаются и не попадают в identity map. Контекст actor
не сбрасывается, глобального bypass и расширения actor admission нет.
Сопоставление current, исторических aliases, legacy numeric/whitespace и
ObjectLink осталось прежним, текст generic409 не содержит скрытых ID/значений.

В combined с настоящим listener старый тест
`test_native_member_scope_cannot_expand_through_mutation[upsert]` получил 403
вместо ожидаемого 404. Отдельный контроль на pinned old runtime воспроизвёл
это расхождение вместе с PASS скрытого чтения: проблема существовала до fix.
Координатор явно расширил текущую границу до узкого исправления admission.
Два новых случая (hidden existing и действительно new) проверяют direct+HTTP,
свежий snapshot, неизменённый actor context и отсутствие скрытых ORM entities.
Final baseline запускает тот же 34-case файл, что и final candidate: 17
collision failures и 1 admission failure отделены от прочих controls.

В upsert только после `_locked`→None выполняется Core scalar existence по
id И company. Существующая скрытая точка даёт generic404; отсутствие своей
точки идёт в прежний create с 403 для scoped actor. Global ID lookup в create,
чтение foreign данных и его текущий 403 admission не расширялись.

ID→company advisory locks, tenant-first `_locked`, freeze, caller commit,
metadata merge, raw snapshots, запись numberHistory, audit/projection и API
контракт не менялись за исключением восстановления ожидаемого 404 hidden upsert. Global ID lookup source-reviewed и проверен для scoped
same/foreign-tenant create: текущий 403 admission не допускает flush/new row,
так что расширять lookup вне этой задачи не потребовалось. Registry preflight
по текущему code сохраняет прежний публичный контракт и текст ответа; новый
код не добавляет публичную выдачу данных скрытых объектов.

| Артефакт | SHA-256 |
|---|---|
| Pinned old location_commands.py | `c6984e7d211f9b6939da1ae1b9c75276bb9169f473d6442c825097efff6e5896` |
| Collision-only runtime, исторический промежуточный | `6c2bb5e9cd4120fe2649fa7652af63d43de4f379e4761862591cc2c095000f67` |
| Final candidate location_commands.py | `8287fcac52c37b6356951c39162620914d681f495fcded3acd49329d1bf1ccf9` |
| Initial test | `6f7b3d869ae303be1015908af4495d3166e24fefb12337ec1baae1e1b82e510c` |
| Collision-only test, одинаковый для 32-case baseline/candidate | `e74b3182b138926a03a4634128bcebe1040bd0f1232c677195087eca8b490222` |
| Final test, одинаковый для 34-case baseline/candidate | `5751c0847da505a52d838ed544776d11c58b5d7dd9139749a886096673a261e9` |

Новый модуль запускается вместе с существующими регрессиями в одном процессе;
module fixture устанавливает production listener и не снимает его перед old
modules. Старые тесты, matcher и scope не monkeypatch-ятся. Подмена projection
принадлежит существующей synthetic HTTP fixture; real DB/ORM/guard/admission
остаются настоящими. Проверка positive create/read/write на стенде и все
остальные writers за пределами этой выборки не заявляются проверенными.

Полный agreed batch содержит test_location_number_scope_collision (34),
test_location_number_history (43) и 147 прежних из test_station_mapping_admission,
test_location_commands, test_location_metadata_merge, test_object_freeze,
test_location_bindings, test_object_scope, test_scope_reaches_screens,
test_space_projection_batching. Явно включены все четыре RUN_* flags.
Промежуточные 162/191 не выдаются за этот полный состав; их единственное
падение admission сохранено в истории, прежние assertions не менялись.

Смешение технического code и number в существующем numberHistory не исправлялось:
координатор выделил domain-separation в отдельный follow-up. Этот slice проверяет
занятость по сохранённому matcher и не подтверждает правильность доменной
интерпретации code историческими читателями.

Финальный cleanup выполнен после reaped pytest: own schema tables=0 и свежие
own connections=0, затем обычный DROP и новый контроль dbexists=0, own
connections=0, other client backends=0. FORCE/terminate не использовались,
max_locks_per_transaction=64 сохранён. SQL_SLOT_RELEASED передан координатору;
после этого SQL не выполнялся. Cleanup proof: private cleanup.log.

| Дополнительный артефакт | SHA-256 |
|---|---|
| Private regressions.xml | `95871c5437a181562db253509187c933f0f36926569e7bcc7a09bae6a8c321d6` |
| Private cleanup.log | `4945b2cf80e81e217d31995f0646278ab7c50d02563579d4558781baa5853bb5` |
| Private runner.py | `ff1e311b5afdb460e20e8fab3cea536e2a696e98ba99772ae775a1f1efbae1d5` |


## Независимая проверка координатора

Исходник5c0deb220ab328eacad6c098121a46c8fcfb94ad перенесён как461c9ed4.
Root повторил ровно34new+43history+147old с четырьмя явными opt-in flags и
настоящим listener в одном процессе: **224PASS37.58с**, без FAIL/ERROR/SKIP
и DESELECTED. Тест5751c084 и runtime8287fcac сохранились без изменения.
Параллельный read-only route triage не менял runtime; тестовый source pin461c9ed4.
Процесс5576 EXIT0/reaped; отдельная собственная syntheticDB после закрытия
engine имела public/edge tables0/conns0, затем удалена обычным DROP без FORCE
или terminate. Новый контроль подтвердил dbexists0/maxlocks64; probes закрыты.
Evidence: `.artifacts/root-location-number-scope-final.log`.
Code-vs-number domain separation по-прежнему отдельная незавершённая задача;
224PASS не доказывают отсутствие её архитектурной ошибки.
