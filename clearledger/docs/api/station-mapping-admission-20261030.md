# W16: допуск к target и привязка external mapping к пути

30.10.2026. База: `f9b6cf4c81b8d63fef9b07e6ff5caa184f6472d6`.
Ветка: `MagLook/station-mapping-admission-20261030`; прежняя ветка аудита
`MagLook/guillemot` / `dc54b38d` сохранена.

Исправлена ограниченная native write boundary: нельзя создать соответствие для
несуществующей/чужой/недоступной точки или закрыть link другой точки через
подстановку пути. На неизменённом source это воспроизводилось настоящими
HTTP/SQL проверками; после исправления те же assertions и прежние регрессии
прошли. Новые routes, scopes, роли, schema и retire API не добавлены.

## Дефект и выбранная граница

`POST /api/ops/station-mapping/{location_id}` проверял членство компании,
но `station_mapping.add_external_id` создавал `ObjectLink` без обязательного
lookup ServiceLocation. У мягкой ссылки нет target FK: обычный участник мог
передать отсутствующий ID, ID другой компании или ID вне своего object/org
контура и получить201 с сохранённой записью. Выбор `company_id` в query и иной
`X-Company-Id` не должны давать полномочий на переданный target.

`DELETE /api/ops/station-mapping/{location_id}/{link_id}` искал только
company+link UUID, не связывая запись с target в URL, типом parent и relation.
В синтетическом примере link точки B закрывался по пути точки A; таким же
путём менялись `number`, `placed_at` и links с другим parent_type.
Кроме того,409 при занятом значении содержал ID другого parent, даже если
этот parent не входил в разрешённый контур.

Shared enforcement остаётся в service, до lookup/mutation ObjectLink:

| Файл | Изменение |
|---|---|
| `server/app/services/location_commands.py:104–114` | Публичный `locked_visible`: существующий `_locked` → 404 при отсутствии → существующий `_assert_visible`. Нет flags, бизнес-мутации, commit или изменения lock order |
| `server/app/services/station_mapping.py:216–239` | POST сначала вызывает общий guard; конфликт сохраняет409 и понятное сообщение, убран ID другого parent |
| `server/app/services/station_mapping.py:242–257` | DELETE сначала admission target, затем predicate `company_id + id + parent_type='station' + parent_id=location_id + relation='external_id'` |
| `server/app/routers/ops_router.py:246–276` | Передаёт `location_id` в close; переводит `LocationConflict` в native HTTP status/detail |

Оба найденных callers `add_external_id/close_external_id` прослежены до этих
routes; других repo callers close не обнаружено. Python-сигнатура close теперь
требует location_id: вызов без привязки к target больше не поддерживается.

`_locked` по-прежнему берёт ID→company advisory transaction locks, затем делает
tenant-qualified `SELECT FOR UPDATE` с `populate_existing`. Чужую row не
блокирует; `_assert_visible` читает **текущий** object context и связь с own
organization через ContractLocation/Contract. Формат opaque ID проверяется
прежним валидатором общей команды; native validation422 не заменяется новой
нормализацией/trim. Membership остаётся ответственностью caller, как прежде.
Member не обязан становиться admin для разрешённой операции.

## Совместимость и остаточный долг

Сохранены успешные POST201 `{id, system, role, value}`, DELETE200 `{id, validTo}`,
прежние GET200/`found:false` для missing/foreign и Unicode/пробелы/reserved
символы существующего point ID. Создаваемая запись сохраняет legacy
`parent_type='station'` с **ServiceLocation.id**, не unit UUID; исправление
представления и миграция bulk namespaces сюда не входят.

Отказы по валидному missing/foreign/scoped target и неправильному link binding
дают безопасный404; неверный UUID link также сохраняет404. При409 скрытый ID
больше не выдаётся. Общие auth/deps, политика компаний и чтение GET не менялись:
этот пакет не является новым аудитом всех read scopes или OAuth.

Сознательно сохранён долг:

- Даты и их трактовка, отсутствие полного interval overlap контроля, optional
  basis и today defaults здесь не исправлены; repeated close по-прежнему может
  менять valid_to/reason. Публичный retirement этим не реализован.
- `add_external_id` и `close_external_id` по-прежнему делают собственный commit;
  helper ничего не commit. Перевод на caller-owned transaction/outbox не входит.
- Полный набор import/bulk/warehouse writers, различие station withdrawal и
  servicePoint retirement, историческая population, reservation ledger и все
  freeze producer races остаются за границей этого patch.
- Native `_as_ids` исторически трактует **stored []** как неограниченный scope.
  Тест EMPTY отдельно задаёт `current_object_scope=[]` после настоящей проверки
  членства; поведение хранения членства этим исправлением не переопределяется.
- Случайный legacy station/unit parent namespace не преобразуется по одному
  совпадению строкового ID. Права на чужой target не добавляются.

Откат кода технически возможен обычным revert, но восстановит подтверждённую
границу обхода admission/path binding; откат не является исправлением клиента.
Data migration отсутствует: ранее ошибочные links автоматически не исправлялись
и не удалялись. Рабочие данные не исследовались и не менялись.

## Baseline и проверки

Все SQL прогоны выполнялись **последовательно** только в выделенной локальной
synthetic DB `api_station_mapping_admission_test`, PG16 из выделенного root
контейнера. Перед стартом прочитаны actual `conftest.py` (setup/drop схем,
dispose) и `partner_test_safety.py`; использованы explicit TEST_DATABASE_URL и
DATABASE_URL этой DB, абсолютный отдельный test UPLOAD_DIR, пустой cwd и
абсолютный PYTHONPATH. Рабочие `.env`, SSH/VM/API/БД и секреты не использовались.
Credentials и операционные данные в Git не сохранены.

Тестовый HTTP app монтирует **настоящий ops router**; `get_current_user` заменён
синтетическим ordinary member, `get_db` — сессиями выделенной PostgreSQL.
Membership, object scope, own organization и SQL predicates настоящие;
dependency fixture не является real OAuth/login/production E2E.

| Этап | Результат и точная граница |
|---|---|
| Первая попытка fixture | 29 ERROR, 26.17с: в синтетической Company пропущен обязательный profile_id. Исправлена только fixture до meaningful baseline, ошибка сохранена отдельно |
| Source checkpoint перед production fix | HEAD=f9b6cf4c; три runtime файла byte-identical базе, hashes ниже |
| Meaningful baseline, новый модуль | **20 FAIL / 9 PASS**, 20.31с; без errors/SKIP. Реальные запрещённые writes, sentinel changes, ID disclosure, stale identity map и current context bypass |
| Syntax gate | In-memory compile трёх runtime файлов и нового теста PASS; без app import/записи pyc |
| Candidate, один combined setup/teardown | **147 PASS**, 27.47с; 29 новых +118 прежних, без FAIL/ERROR/SKIP/DESELECTED |
| Последний перенос test guard | Только portability delta: удалён hardcoded local URL/name/user guard; сохранены opt-in и неизменённый общий pure guard. Fixtures и все assertions byte-identical. Новый module compile и diffcheck PASS; повтор всего current module выполняет root после интеграции |

Новый модуль проверяет POST/DELETE missing/foreign/object/org/явный EMPTY target;
DELETE wrong path/parent_type/relation/foreign UUID/missing/invalid UUID;
сохранность persisted links при отказе;409 без hidden parent ID; четыре positive
ordinary-member scope combinations; Unicode ID с `?/#/%`; GET found:false;
company selector не расширяет доступ; reload stale target и текущего контекста;
404 под удерживаемым чужим row lock (lock_timeout300ms, request timeout3s).

Combined suite: `test_station_mapping_admission`, `test_location_commands`,
`test_location_metadata_merge`, `test_object_freeze`, `test_location_bindings`,
`test_object_scope`, `test_scope_reaches_screens`, `test_space_projection_batching`.
Это focused domain regression, не весь repository CI, OIDC conformance или
проверка нагрузки. UI/schema миграции не менялись, frontend checks неприменимы.

Форма команды (runner обязан заранее задать только разрешённую synthetic DB,
absolute test UPLOAD_DIR, empty cwd, PYTHONPATH и Python3.13.7 venv):

```sh
RUN_STATION_MAPPING_ADMISSION_TESTS=1 RUN_OBJECT_COMMAND_TESTS=1 \
python -m pytest -c "$SERVER/pytest.ini" \
  "$SERVER/tests/test_station_mapping_admission.py" \
  "$SERVER/tests/test_location_commands.py" \
  "$SERVER/tests/test_location_metadata_merge.py" \
  "$SERVER/tests/test_object_freeze.py" \
  "$SERVER/tests/test_location_bindings.py" \
  "$SERVER/tests/test_object_scope.py" \
  "$SERVER/tests/test_scope_reaches_screens.py" \
  "$SERVER/tests/test_space_projection_batching.py" \
  --junitxml="$EVIDENCE/candidate.xml" -q
```

Local assignment не зашит в committed test: pure common guard остаётся
переносимым, а это не разрешение запускать тесты на произвольной БД.

### Provenance evidence

| Артефакт / checkpoint | SHA256 |
|---|---|
| Baseline station_mapping.py | `00872175f99912acf3b3da1a6d2b43cd23ad9743d68d61302e4924cad8188ef7` |
| Baseline ops_router.py | `2fd8f3d104cff7ecb39ede69ac84859a24d09ba85e39d359ed84c2fb4cd7290b` |
| Baseline location_commands.py | `a1182683d4e556482a9328cf840a14c1e0a335c32a6f1d86c202d9f9707641a1` |
| Тест meaningful baseline +147 candidate | `61e7cae6983b464773e522f392d7969aa82b3f709433df1dada9015e44c9bc0e` |
| Текущий portable guard test | `8bf77dd7eff6106713a6bf98ba41caccd1f7a9cd3be4de68f1c17509cb68923c` |
| Baseline JUnit | `2c5c6e0a0fe65390f66bb52742d32a08b4eb03b863ed6520ee70cf4cacfcdff9` |
| Candidate147 JUnit | `ba4771562833573c617ab807266496a8551b5e2012743d2cd87a774d1f3b4784` |

Вне Git в author worktree: `.artifacts/station-mapping-admission/` содержит
baseline/candidate `.log/.xml`, fixture-profile-error `.log/.xml` и исходный
`baseline-test-snapshot.py`. Snapshot восстановлен с проверкой исходного SHA;
часть файла начиная с app imports побайтно совпадает с portable module.
Не выдаётся за прогон final test SHA:147 относятся предыдущему guard.

Тестовые процессы завершены; после candidate контроль показал0 иных connections
к dedicated DB, далее отдельный контроль перед release показал1, о расхождении
сразу сообщено root. Схема public оставлена пустой (tables0), max_locks64 не
менялся. Root отдельно подтвердил последующий fresh checkpoint в01:15 UTC:
`pg_stat_activity` для assigned DB дал0rows из контрольного соединения в другой
локальной control DB; соединений принудительно не завершали. Это отдельное
последующее подтверждение, прежняя1 не приписывается источнику без доказательств.
Root владеет следующим SQL окном; после передачи окна author SQL не запускал.

Выпуска, PR/merge и исправления прежних рабочих записей не было. Итог ограничен
проверенным runtime fix и portable тестовым кандидатом; независимый current
combined repeat у root остаётся отдельной приёмкой.
