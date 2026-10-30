# Свежесть ручных реквизитов договора перед импортом 1С

Дата: 30.10.2026. База исследования: `605cd79ad1513dfdf8e9323531c5e4913334ee1d`.
Ветка: `fix/contract-manual-freshness-20261030`.

## Результат

Подтверждена потеря сохранённой ручной правки договора при повторном импорте
в прежней SQLAlchemy-сессии. Исправлена только существующая company-scoped
выборка Contract в `_sync_contracts`: добавлен `populate_existing=True` после
уже имеющихся lock и flush. После исправления прошли 57 проверок.

Исследование и воспроизведение выполнены на синтетических данных в отдельной
PostgreSQL 16.15, Python 3.13.7. До явного SQL-разрешения координатора
выполнялись только чтение исходников, подготовка тестов и компиляция в памяти.
После завершения БД удалена, соединения закрыты, SQL-окно освобождено.

## Прослеженный путь

- Native `PATCH /api/references/contracts/{id}` загружает договор своей SQL-сессией,
  различает отсутствие поля и явный `null` через `model_fields_set`, вызывает
  `mark_reference_changes`, затем flush/refresh. `manual_overrides` содержит только
  действительно изменённые реквизиты; raw не переписывается ручной формой.
- `_sync_contracts` берёт существующий `lock_manual_creation` для компании/договора,
  делает flush, строит индексы сторон, затем выполняет company-scoped SELECT Contract.
  SELECT базы `605cd79a` не требует `populate_existing`: живой объект сессии
  `expire_on_commit=False` может сохранить поля и маркеры прежней загрузки.
- `apply_import_values` использует маркеры переданного ORM-объекта. Для доказательства
  потери ручной правки требуется новое значение источника, которое создаёт изменение
  SQLAlchemy history и настоящий UPDATE промо-поля. Повтор тех же значений источника
  может оставить устаревший Python-объект без перезаписи сохранённого NULL.
- Исправление контрагентов `e1cb1a53` показывает аналогичный подход, но не служит
  доказательством дефекта договоров.

## Проверки

`server/tests/test_contract_manual_freshness.py` использует существующий `db` fixture
с PostgreSQL, настоящий router НСИ в локальном FastAPI, HTTP dependency fixtures
только для пользователя и отдельной сессии БД. Пользователь и членство синтетические;
проверка владения и остальные обработчики настоящие. Транспорт 1С заменён локальным
Source fixture; алгоритм импорта, matcher, SQL и manual markers не подменяются.

1. Держать сильную ссылку на Contract в import session после commit, очистить
   nullable-поля HTTP PATCH в другой session, подтвердить NULL и manual markers
   новой сессией, изменить upstream и повторить настоящий импорт с commit.
2. Читать сохранённый результат ещё одной сессией, а не `get` старой identity map.
   Повторить импорт; проверить raw, незамороженный реквизит, UUID, стороны, source
   identity, creation metadata, локальный охват, links/locations и статистику.
3. Отдельный same-upstream control: сохранённый NULL может пережить исходный
   импорт даже при устаревшем Python-объекте; это не persisted-overwrite finding.
4. Границы намерения PATCH: omitted, unchanged, null→null, changed→null,
   changed→value; только реальные изменения замораживают промо-поле.
5. Свои незавершённые ручные изменения проходят flush и сохраняются при commit;
   rollback вызывающего откатывает импорт и правку. Импорт не получает собственный commit.
6. Такой же external_ref другой компании не обновляется и не освежается случайно.

Тест требует отдельного `RUN_CONTRACT_MANUAL_FRESHNESS_TESTS=1` и существующего
`partner_test_safety_error`: явная TEST_DATABASE_URL с test-сегментом имени БД,
loopback/явный CI service, абсолютный тестовый UPLOAD_DIR. Общий conftest не меняется.

## Воспроизведение до исправления

На неизменённом `sync_service.py` базы `605cd79a` выполнены первые два сценария
того же нового тестового файла: **1 FAILED, 1 PASSED**, 17.43 секунды.

После native HTTP PATCH отдельная сессия подтвердила четыре NULL и маркеры
`amount_incl_vat`, `amount_limit`, `payment_term_days`, `valid_until`.
Сильная ссылка на объект прежней import session по-прежнему содержала
`valid_until='2026-12-31'` и пустой список ручных маркеров.
После изменённого upstream, настоящего `_sync_contracts` и commit третья
сессия прочитала следующий сохранённый результат:

| Поле | После PATCH | После исходного импорта |
|---|---|---|
| `valid_until` | NULL | `2027-12-31` |
| `amount_limit` | NULL | `200.00` |
| `amount_incl_vat` | NULL | false |
| `payment_term_days` | NULL | 20 |

Ручные маркеры остались в БД: исходный импорт перезаписал именно промо-колонки,
руководствуясь устаревшим объектом в памяти. Все значения в таблице вымышленные.
Контроль с неизменённым upstream прошёл: сохранённый NULL остался NULL.
Таким образом, находка подтверждена новой сессией после commit, а не чтением
устаревшего `get` и не одной аналогией с контрагентами.

Локальный закрытый лог: `.artifacts/baseline-proof.log`. Первый технический
вызов runner с относительным путём завершился exit 4 / collected 0, не запускал
setup и не входит в доказательство; повтор с абсолютными путями дал результат выше.

## Минимальная правка

Company filter и advisory lock не изменены. Имеющийся flush сохраняет собственные
pending changes до refresh; company-scoped SELECT перечитывает поля и ручные
маркеры перед построением `ContractIndex`, поиском внешней ссылки и импортом.
Новые lock/commit/rollback, изменения matcher, raw/source identity, маршрутов,
моделей, статистики и семантики nullable-полей не вводились. Контрагенты
и организации не изменены.

## Проверки после исправления

Один последовательный combined-прогон: **57 PASSED, 0 FAILED, 0 SKIPPED**,
35.40 секунды. Состав:

| Файл в `server/tests/` | PASS |
|---|---:|
| `test_contract_manual_freshness.py` | 10 |
| `test_counterparty_clear_fields.py` | 1 |
| `test_counterparty_explicit_null.py` | 9 |
| `test_reference_identity_onec.py` | 6 |
| `test_reference_identity_api.py` | 10 |
| `test_contract_creation_replay.py` | 1 |
| `test_contract_doc_replay.py` | 3 |
| `test_contract_scope.py` | 9 |
| `test_contract_direction.py` | 1 |
| `test_contract_usage_integrity.py` | 7 |

Локальный закрытый лог: `.artifacts/candidate.log`. Воспроизводимый запуск:
`python -m pytest -c "$SERVER/pytest.ini" -vv --tb=short` с абсолютными путями
перечисленных файлов. `SERVER` — абсолютный путь к `clearledger/server`.
Запуск выполнялся из пустого каталога, с абсолютным PYTHONPATH, отдельным HOME,
абсолютным тестовым UPLOAD_DIR и изолированным окружением без наследования `.env`,
ключей, connector settings и авторизаций. DATABASE_URL явно равнялся
TEST_DATABASE_URL. Кроме нового opt-in, для регрессии контрагентов включён
существующий `RUN_COUNTERPARTY_COMMAND_TESTS=1`.

Новый тест проверяет две последовательные синхронизации изменённого источника:
ручные NULL сохраняются, незамороженное `signed` следует 1С, полный raw обновляется.
Проверены UUID, стороны договора, исходная source identity, reference source,
creation metadata, локальные basis/liability/scope, links/locations, отсутствие
дубликатов и прежняя статистика. Чужой Contract с тем же external_ref сохраняет
свои данные; company-scoped refresh не освежает даже удержанный чужой ORM-объект.

## Освобождение SQL-окна

Использовался только назначенный контейнер `api-modernization-test-20261029`
и отдельная `api_contract_manual_freshness_test`. Bootstrap, прогоны и очистка
были строго последовательны, `max_locks_per_transaction=64` не изменялся.
После завершения pytest fresh snapshot через `pg_stat_clear_snapshot()` показал
0 соединений своей БД и 0 других client backends, исключая текущий проверочный psql.
После обычного DROP DATABASE повторный fresh snapshot подтвердил 0 соединений,
отсутствие своей БД и 0 других client backends. FORCE/terminate не применялись.
Координатору отправлен отдельный `SQL_SLOT_RELEASED`; после него SQL не выполняется.

## Ограничения

Результат относится к завершённому PATCH перед очередной выборкой импортера;
новая сериализация PATCH, начавшегося после этой выборки, не вводится.
Полный CI, OAuth E2E, реальная 1С, рабочие API и приёмка на стенде не запускались.
Реальные договоры, финансы и коннекторы не затрагивались; PR, merge и deploy
не выполнялись. В логах bootstrap есть известное предупреждение совместимости
passlib/bcrypt; оно не помешало setup и не изменяет результат тестов.
