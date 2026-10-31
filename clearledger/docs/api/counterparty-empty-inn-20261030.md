# M06: неизвестный ИНН новой импортной карточки

Ветка `agent/counterparty-empty-inn-20261030` создана от immutable `be5da264`.
Исходный рефакторинг `876e0f36` и его отчёт `be5da264` сохранены отдельной remote
веткой `MagLook/api-counterparty-commands-20261030`, история не переписана.

## Причина и исправление

Две разные новые организации без ИНН не импортировались: второй INSERT получал
`unique_violation` индекса `uq_counterparties_inn_kpp`. Три native producer
(`ingest_reestr`, `L2Cache.counterparty`, `space_links.link_counterparties`)
через общий command сохраняли буквальную пустую строку после startup-нормализации.

Канон уже существует: `Counterparty.inn` — `String(20), nullable=True` без default;
`COUNTERPARTY_INN_MIGRATION_DDL` прямо описывает отсутствие ИНН как NULL и переводит
прежние заполнители в NULL. Индекс намеренно исключает NULL:

```sql
CREATE UNIQUE INDEX uq_counterparties_inn_kpp
    ON counterparties (company_id, inn, coalesce(kpp, '')) WHERE inn IS NOT NULL;
```

Единственная runtime-правка в `services/counterparty_commands.py`:

```python
inn=None if inn == "" else inn[:20]
```

Она применяется при создании новой карточки. Полный входной текст command остаётся
в `raw.referenceIdentity.inn`. Непустые строки, пробел, `0`, невалидный ИНН и прежнее
усечение до 20 символов сохраняют прежнюю семантику. Существующие строки не
переписываются. Matcher, company scope, права, locks, commit/rollback, source keys,
ID и договорные/финансовые поля не менялись; моделей/DDL/index правок нет.

## Доказательство регрессии

`test_counterparty_empty_inn.py` скопирован без изменения expectations в
`git archive be5da264 clearledger/server`; SHA256 обоих файлов:
`bf7906d22df1c8b2d1c7e48b580fdddc5dd8cdc2527d64feae90f0bb19c36e64`.

Три положительных native контракта создают ООО и АО с одинаковой основной частью
имени без ИНН, требуют две карточки с SQL NULL, точные raw snapshots и стабильный
replay. Два сценария проходят через настоящие legacy/L2 producers, третий через
HTTP `/api/registry/link-counterparties`. Command, matcher и SQL не подменяются;
у HTTP-сценария подменён только текущий пользователь. Legacy replay дополнительно
сверяет contract IDs, стороны/условия и RAW/clean IDs/source keys.

Первый baseline: **3 FAIL за 17.19 с**, из них legacy/L2 воспроизвели целевой
`uq_counterparties_inn_kpp`, а HTTP остановился раньше на ошибке фикстуры:
одинаковые пустые телефоны двух CorporateClient нарушали `uq_corporate_clients`.
Второму синтетическому клиенту задан отдельный телефон. Runtime не менялся.
Повтор с исправленной фикстурой на immutable `be5da264`: **все 3 FAIL за 16.61 с
именно на `uq_counterparties_inn_kpp`**, 6 остальных случаев deselected.
Этот же исправленный файл использован на кандидате.

В прежнем `test_counterparty_commands.py` только два ожидания новой колонки
`inn == ""` заменены на `inn is None` согласно указанному канону; raw expectations
сохранились. Прежний отрицательный контроль буквальной пустой пары сохранён как
direct SQL/ORM INSERT, отдельно от исправленного native импорта, с двумя вариантами
КПП (`None`/`""`). Дополнительно проверено, что старая карточка с `inn=""` не меняется
при alias update. Контроли ручной фиксации, неоднозначности и прав не удалялись.

## PASS / FAIL / SKIP

| Статус | Проверка | Результат |
|---|---|---|
| PASS | Candidate SQL/HTTP | 31 PASS в наборе из 32, 20.14 с; все новые 9 случаев и прежние 16 контрактов прошли |
| PASS | Основные 3 regression на candidate | Две новые legal forms успешно созданы, replay/ID/raw сохранены; те же expectations, что у failed baseline |
| PASS | Значения command | 6 случаев: `""`, пробел, `0`, невалидный текст, известный ИНН, длинный текст; SQL storage и полный raw |
| PASS | Дополнительные native контроли | Concurrent POST ИНН/КПП и company, неполные реквизиты, ручной PATCH, legacy replay, ambiguity 409, channel rollback |
| PASS | Pure identity/overrides | 13 PASS за 1.97 с, `--noconftest`, без SQL |
| PASS | Статика | AST трёх Python-файлов, `git diff --check` |
| FAIL, ожидаемый baseline | Новые 3 regression на `be5da264` | 3 реальных `unique_violation`, 16.61 с |
| FAIL, прежний отдельный сценарий | `test_explicit_null_clears_nullable_fields_and_survives_onec` | Candidate: 1 FAIL; immutable baseline отдельно: тот же 1 FAIL за 13.32 с |
| SKIP | Default opt-in gates | 2 module SKIP в pure прогоне, без SQL |
| SKIP | Полный CI, браузер, выпуск, остальные producer | Этим срезом не подтверждены |

Старый отдельный FAIL воспроизводится без новой runtime-строки: после HTTP PATCH
nullable реквизитов и повторного 1С-импорта `party.kpp == "771201001"`, хотя тест
ожидает None. Его код/фикстуры не менялись; причина в этом срезе не атрибутирована.
Это не green всего набора и не подтверждение полного контура ручная правка → 1С.
Ручные freeze-контроли выбранных импортных producers при этом PASS. Нужна отдельная
проверка старого 1С-сценария координатором, без смешения с этой правкой.

Локальные JUnit evidence в `.artifacts/counterparty-empty-inn/`:
`baseline.xml`, `baseline-corrected-fixture.xml`, `candidate.xml`,
`baseline-existing-clear-fields.xml`. Артефакты и параметры подключения не входят в Git.

SQL выполнялся только в заново выданное exclusive окно координатора, на собственной
`api_counterparty_commands_test`, с явными `TEST_DATABASE_URL`, тестовым UPLOAD_DIR
и `RUN_COUNTERPARTY_COMMAND_TESTS=1`; общий pure guard проверялся до подключения/DDL
и импорта pytest/conftest. Cwd пустой, PYTHONPATH абсолютный, Python root venv 3.13.
Все процессы завершились; conftest очистил собственные public/edge и закрыл pools.
Guarded проверка после завершения: 0 других соединений своей БД, 0 таблиц public/edge;
проверочное соединение закрыто, SQL окно явно освобождено. Другие БД/роли/ВМ не менялись.

Остаются отдельные M06 producer/CRUD срезы, независимая приёмка общего кандидата
и прежний 1С FAIL. Полнота M06, программы и готовность выпуска не заявляются.


После отдельного stale-overrides исправления координатор повторил оба пакета
вместе с исходным clear-fields case и регрессиями:52PASS за22.55с, без SKIP
или DESELECTED. До refresh fix независимый повтор давал28PASS/1прежнийFAIL;
неизвестный ИНН исправлялся отдельным commit безDDL и без правки старых строк.
