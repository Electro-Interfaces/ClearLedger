# M06: актуальные ручные реквизиты при повторном импорте 1С

Ветка `agent/counterparty-explicit-null-20261030` от immutable `7c684266`.
Предыдущая remote ветка empty-INN сохранена. Первый source checkpoint согласован
координатором до изменения runtime; SQL диагностика выполнена в отдельно выданное
окно. Исправление ограничено чтением Counterparty в offline adapter 1С.

## Первый checkpoint: точный source control flow

1. `CounterpartyUpdate` (`schemas.py:750`) сохраняет различие omitted/null в
   `model_fields_set`. Validator КПП нормализует пустую строку в None, не удаляет
   наличие поля. У `_CpExtra` nullable поля также сохраняют fields_set.
2. `references_router.update_counterparty` получает owned row, берёт общий
   `lock_manual_creation` и `db.refresh` до snapshot. КПП, shortName и extras
   присваиваются по fields_set, поэтому explicit None действительно применяется.
   Target КПП для проверки уникальности тоже вычисляется по fields_set.
3. `mark_reference_changes` сравнивает значения до/после, не использует truthiness;
   изменение непустого КПП/full_name в None добавляет snake_case marker. Маркеры
   лежат отдельно от raw. Flush/refresh и commit dependency сохраняют результат.
4. `_sync_counterparties` берёт тот же advisory lock и SELECT только своей компании,
   строит `CounterpartyIndex` и by_ref, source/ref checks остаются authoritative.
   L1 `_reference_raw` хранит входящий item и предыдущий referenceIdentity; L2
   `apply_import_values` пропускает поля из `manual_overrides`, включая None.
   В `kpp or existing.kpp` нет обхода ручного marker: helper проверяет marker до
   присваивания, поэтому сам этот fallback не объясняет восстановление очищенного КПП.

Pure проверка актуальных schema/ORM/helper без SQL: fields_set содержит все 5
очищенных полей; markers становятся email/full_name/kpp/phone/short_name;
после apply_import_values(kpp=source, full_name=source) оба значения остаются None.
Следовательно, заменять None-handling схемы/helper наугад нельзя.

## Установленная причина и точный seam

`_sync_counterparties` SELECT не запрашивал populate_existing. Сессии имеют
expire_on_commit=False: SELECT возвращал ранее загруженный объект с прежними
реквизитами и `manual_overrides=[]`, хотя после HTTP PATCH authoritative БД уже
содержала None и `['full_name', 'kpp']`. Это измерено отдельной persisted-session,
без подмен helper/matcher/SQL.

Важное уточнение старого FAIL: при повторе точно того же item прежний КПП в ORM
не становится dirty, поэтому БД может сохранять None, а `db.get` показывает
устаревшую карточку. Первый диагностический baseline подтвердил именно это:
старый тест FAIL, persisted-only контроль PASS. Сам этот FAIL не доказывал
восстановление КПП в БД.

Усиленная проверка дополнительно сравнила объект после SELECT с сохранённой
строкой и изменила full_name источника. Тут stale список markers уже приводит
к настоящей потере ручного None/ручного значения: свежая SQL session видит
`'Обновление источника'` при всё ещё сохранённом `manual_overrides=['full_name']`.
Так подтверждены и источник исходного наблюдения, и реальный риск записи.

После этой атрибуции применён условно согласованный seam:
`execution_options(populate_existing=True)` в существующем scoped SELECT
Counterparty, под тем же advisory lock и до построения CounterpartyIndex/by_ref.
Перечитываются актуальные промо-поля и markers. Дополнительных SELECT на каждую
карточку и commit не добавлено. Обычный autoflush сначала сохраняет собственные
pending edits; отдельный SQL тест доказывает их приоритет и возможность caller
откатить транзакцию. Matcher, raw promotion, source/ref guards и ACL не менялись.

Не расширялась семантика ручного intent: omitted, неизменённое значение и
null→null не создают marker, изменённое значение и changed→None создают.
Это явно согласовано root: полные UI формы могут присылать много неизменённых null.
Расширение на намеренную фиксацию null→null требует отдельного дизайна.
Известный отдельный `body.inn is not None` вопрос PATCH не менялся.

## PASS / FAIL / SKIP

| Статус | Проверка | Результат |
|---|---|---|
| FAIL, диагностика исходного состояния | Immutable `7c684266`, existing + persisted-only | 1 FAIL / 1 PASS, 12.43 с; сохранённые NULL и markers корректны, ORM stale |
| FAIL, полный baseline | Existing + 9 новых HTTP/SQL контролей | 4 FAIL / 6 PASS, 20.58 с; existing, stale ORM, реальная потеря changed-null и changed-value |
| PASS | Candidate SQL/HTTP | 52 PASS, 25.17 с, без FAIL/SKIP; исходный failing test не менялся |
| PASS | Pure до правки | 13 PASS / 1 guarded module SKIP, 1.99 с, `--noconftest`, без SQL |
| PASS | Pure после правки | 13 PASS / 1 guarded module SKIP, 1.81 с, без SQL |
| PASS | Статика | AST новых/изменённых Python-файлов, `git diff --check` |
| PASS | Очистка | SQL процессы завершены, own DB: 0 других соединений и 0 таблиц public/edge; окно освобождено |
| SKIP | Полный CI, браузер, реальная 1С/COM, выпуск | Этим срезом не проверяются |

Один и тот же новый тестовый файл исполнен baseline/candidate, SHA256:
`c36360a5ff7da98fc0ac2f7601b419e568f492c2b6c9ae60e25df004996e4dd5`.
Runtime baseline распакован через `git archive 7c684266 clearledger/server`;
expectations нового файла при переносе не менялись. Первоначальный диагностический
тест был усилен проверкой cached state и изменённого source до полного baseline,
а не ослаблен ради PASS.

В 52 входят `test_counterparty_clear_fields` (1), новый explicit-null набор (9),
shared commands (16), empty-INN (9), reference_identity_onec (6),
reference_identity_api (10), channel rollback (1). Проверены omitted/null/value,
manual freeze и повтор, точный raw источника и неизменность referenceIdentity,
company scope при совпавшем external_ref, branch КПП 409, известные ИНН/КПП,
conflict источника, собственные pending edits/autoflush/rollback и прежние контракты.
Native HTTP использует обычный login; заменён только внешний 1С клиент на offline
источник синтетических item, без сети и COM. Command/matcher/SQL не подменяются.

Локальные JUnit evidence: `.artifacts/counterparty-explicit-null/`:
`baseline-diagnostic.xml`, `baseline-full.xml`, `candidate.xml`.
Параметры доступа и операционные артефакты не входят в Git.

SQL использовал только свою `api_counterparty_commands_test` на loopback33546
в отдельном exclusive окне root: явный TEST_DATABASE_URL, тестовый UPLOAD_DIR,
RUN_COUNTERPARTY_COMMAND_TESTS=1 и pure safety guard до подключения/DDL/pytest.
Cwd пустой, PYTHONPATH абсолютный, Python из root venv 3.13. Conftest очистил свои
public/edge, pools закрыты; отдельное проверочное соединение тоже закрыто.
Другие БД/роли/ВМ не менялись. Models/DDL, empty-INN command, matcher, договорные
и финансовые значения вне runtime diff.

Остаются независимая root приёмка общего кандидата, отдельные M06 producer/CRUD
срезы и дизайн расширенного null-intent. Другие reference sync пути на stale
identity-map здесь не проверялись. Полнота M06/программы и выпуск не заявляются.
