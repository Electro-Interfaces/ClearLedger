# Корпоративный импорт: общие команды контрагентов

Исходник: `2326f905919f999de41c282a0b50046b650c0fe7`, отдельная ветка
`fix/corporate-counterparty-commands-20261030`. Предмет: четвёртый producer
`charge_sessions_normalize._sync_corporate_contracts`; без рабочих подключений,
данных клиентов, 1С, внешних API, финансовых расчётов и выпуска.

## Source checkpoint до изменения runtime

Исходная функция берёт locks `counterparty`, затем `contract`, загружает карточки
и договоры своей компании и существующие `Organization`. Она вызывает
`CounterpartyIndex.resolve(clean_name, original_inn, original_kpp)` до CREATE.
Договор использует `require_organization`, номер «б/н», исходную дату в ISO,
корпоративный тип, `scope_type=company`. Идентичность договоров, телефонная связь
с `CorporateClient`, locks и завершение транзакции принадлежат caller.

| Поле | Корпоративный исходник | Существующий общий helper | Требование кандидата |
|---|---|---|---|
| name | `_clean_cp_name(str(name).strip())[:500]` | `name[:500]` | Передать полное очищенное имя; прежнее усечение |
| inn | `str(o.get("inn") or "")[:20]` | `None if inn == "" else inn[:20]` | Сохранить adapter; только пустую полученную строку хранить SQL NULL |
| kpp | `o.get("kpp") or None` | Не задан | Передать исходный КПП; прежняя truthiness и отсутствие усечения |
| type | `_cp_type(name)` | `cp_type` | Прежний выбор caller |
| aliases нового | `["corporate"]` | `[alias]` либо `[]` | Та же роль |
| aliases существующего | sorted union через `apply_import_values` | Та же команда добавления роли | Сохранить manual freeze |
| kind | `external` | `external` | Без изменений |
| raw.referenceIdentity | Полные `{name, inn, kpp}`; отсутствующий КПП даёт ключ с None | Полные `{name, inn}` | Optional КПП должен различать omitted/explicit None; прежние три raw dict не расширять |
| публикация в index | Только после успешного flush | Только после успешного flush | Без изменений; отказ откатывает caller |

`Counterparty.inn` nullable, без default. В `database.py` существующая декларация:

```sql
CREATE UNIQUE INDEX uq_counterparties_inn_kpp
    ON counterparties (company_id, inn, coalesce(kpp, '')) WHERE inn IS NOT NULL;
```

Пустая строка входит в индекс. Это source evidence гипотезы конфликта двух новых
лиц без ИНН; аналогия с тремя другими importer не заменяет собственный baseline.
Ненулевые ИНН, строковый `"0"`, пробелы, числовой 0 и длинные строки обрабатываются
прежним корпоративным adapter; новая налоговая валидация не требуется.

## Подготовка baseline

Новый переносимый файл `server/tests/test_corporate_counterparty_commands.py`
содержит 23 синтетических SQL-случая. Opt-in:
`RUN_CORPORATE_COUNTERPARTY_COMMAND_TESTS=1`; перед ORM используется неизменённый
`partner_test_safety_error`. Нужны явные `TEST_DATABASE_URL`, совпадающий
`DATABASE_URL` и абсолютный отдельный тестовый `UPLOAD_DIR`. Conftest уничтожает
public/edge выделенной БД; перед его импортом частный runner обязан проверить
точную разрешённую цель. Машинные адреса и credentials в тест не зашиты.

Каждый сценарий создаёт настоящие `Company(profile_id="energy")` и
`Organization`; вызывает actual функцию и actual `CounterpartyIndex`, без mock
matcher, SQL или команд. Проверяются actual partial unique index, два новых CP,
два Contract и два CorporateClient без ИНН; replay и неизменность договорных
полей; raw/KPP/длина/type; известный ИНН и филиалы по КПП; manual aliases;
phone-link без изменения тарифных полей; foreign company; ошибки сопоставления;
rollback успеха и ошибка второго flush; отсутствие публикации неуспешного helper
в индексе. Отдельный helper-контракт оставляет прежнюю raw форму без ключа КПП.

До явного SQL grant выполнены только source inspection, тест и компиляция
в памяти. После grant проверены образ PostgreSQL 16, разрешённый loopback-порт
и `max_locks_per_transaction=64`; создана собственная отдельная БД. Baseline
runtime распакован через `git archive 2326f905 clearledger/server`, тест скопирован
без изменений. Его SHA256:
`73f25eccb83e6cae327283fef8e11f2f9c36ac6e005a7a373361b74bdeece05f`.

Baseline до runtime fix: **4 FAIL / 19 PASS за 18.78 с**, процесс завершён с кодом 1
и reaped. Все четыре отказа происходят при flush второй новой карточки без ИНН:
`IntegrityError` / `uq_counterparties_inn_kpp`, пара `inn='', coalesce(kpp,'')=''`.
Различаются только omitted, explicit None, пустая строка и числовой 0 источника.
Положительные контроли КПП, raw snapshot, длинных строк, строкового `"0"`, пробелов,
ручных полей и ролей, matcher conflicts, foreign company и rollback прошли на
неизменённом исходнике. Таким образом, gap подтверждён собственным actual PG
baseline, а не аналогией. Свежая проверка после baseline: **0 соединений** с
собственной БД и **0 таблиц public/edge**; проверочные соединения закрыты.
Runtime на этом checkpoint ещё не изменён.

## Реализованное изменение

`create_imported_counterparty` принимает optional `kpp` со sentinel отсутствия.
При omitted сохраняется прежний raw `{name, inn}`. При явном значении, включая
None, raw получает исходный `kpp`, а колонка — `kpp or None`; длина КПП не
усекается. В корпоративном блоке заменены только CREATE и добавление aliases
вызовами общих команд. Его adapter по-прежнему передаёт
`str(o.get("inn") or "")`, исходный КПП и полное очищенное имя. Поэтому только
пустой результат INN adapter теперь хранится как SQL NULL, что позволяет
различным новым лицам без ИНН сосуществовать под действующим индексом.

Matcher и `CounterpartyIndex.resolve`, порядок locks, `ContractIndex`, создание
Contract, `Organization`, телефонная связь `CorporateClient`, caller commit,
статистика и финансовые формулы не изменялись. Три прежних caller не менялись;
их raw остаётся без ключа КПП. Native APIs, 1С, модели, DDL, зависимости,
локации и авторизация вне diff. Существующие замороженные aliases по-прежнему
сохраняются через `apply_import_values`. Публикация новой карточки в индексе
происходит после flush; команда не делает commit, отказ атомарно откатывает caller.

## Проверки и границы

| Статус | Проверка | Результат |
|---|---|---|
| FAIL, подтверждённый исходный дефект | Baseline `2326f905`, неизменный новый файл | 4 FAIL / 19 PASS, 18.78 с; только второй unknown-INN CP |
| PASS | Кандидат, тот же файл и SHA256 | 23 PASS, 18.70 с, EXIT0/reaped, без SKIP |
| PASS | Existing CP/contract regressions | 41 PASS, 22.27 с, EXIT0/reaped, без SKIP |
| PASS / SKIP | Pure identity/overrides и opt-in | 13 PASS / 1 module SKIP, 2.05 с, `--noconftest`, без SQL; новый файл штатно пропущен без opt-in |
| PASS | Компиляция в памяти и diff | Три Python-файла компилируются; `git diff --check` |
| PASS | Завершение SQL окна | Свежие own DB tables0/connections0, обычный DROP DATABASE, свежий dbexists0; все probes закрыты, maxlocks64 |
| Не проверялось | Полный CI, OAuth E2E, browser, рабочие источники и выпуск | Локальные SQL/HTTP контракты этого среза не подтверждают готовность выпуска |

Existing regressions выполнены без изменения файлов:
`test_counterparty_commands.py`, `test_counterparty_empty_inn.py`,
`test_reference_identity_api.py`, `test_counterparty_clear_fields.py`,
`test_contract_creation_replay.py`, `test_contract_doc_replay.py`,
`test_channel_failure_rollback.py`. Они включают прежние три importer/raw формы,
native HTTP CRUD/связывание, ручные поля, replay договоров и бумаг и отказ канала.
HTTP здесь использует синтетических fixture users; это не проверка реального
OAuth или внешних источников.
Pure прогон отключал автозагрузку plugins; три config warnings относятся к
asyncio-настройкам без загруженного asyncio plugin и не являются SQL отказами.

SQL запуски шли последовательно в выделенном координатором exclusive окне из
пустого cwd, с абсолютным PYTHONPATH, явными DATABASE_URL=TEST_DATABASE_URL и
отдельным UPLOAD_DIR. Точная контейнерная цель и синтетические credentials
проверялись private runner до подключения и до pytest/conftest. Реальные `.env`,
auth keys и глобальные конфигурации не читались; HOME/home/CODEX_HOME не
переназначались. `partner_test_safety.py` и conftest не менялись. После регрессии
БД удалена без FORCE/terminate; положительный SQL RELEASE отправлен координатору
до отчёта об окончании. После RELEASE новых SQL подключений не было.

Локальные evidence, не входящие в публичный Git:
`.artifacts/corporate-counterparty/{baseline,candidate,regression}.{xml,log}`;
private runner `.artifacts/corporate-counterparty/run.py`. Для повторения нужно
сначала новое выделенное SQL-окно и отдельная тестовая БД, затем те же opt-in и
guard; conftest разрушает public/edge только явно выбранной тестовой базы.
Коммит и push этого состава не являются merge или deploy.


## Независимая проверка общего кандидата

Координатор перенёс c45ea2907cdf8350c2cb67d50b0e3f63555e3c14 как ffab2a10
поверх принятой истории номеров 2ed52b9c. Неизменный новый тест сохранил SHA256
73f25eccb83e6cae327283fef8e11f2f9c36ac6e005a7a373361b74bdeece05f.
Один независимый прогон дал **79 PASS за24.70с**, без SKIP/DESELECTED: новый
23-case модуль, все семь авторских regression-модулей, а также прежние
`test_counterparty_explicit_null.py` и `test_reference_identity_onec.py`.
Таким образом повтор проверяет common helper вместе с прежними importer,
ручными значениями и native HTTP/replay, а не только новый corporate caller.

Процесс19186 завершён EXIT0, дочерний pytest reaped. Private runner использовал
собственную отдельную synthetic DB, empty cwd, absolute PYTHONPATH и отдельный
UPLOAD_DIR; HOME сохранён без подмены. Свежая проверка после закрытия test engine:
public/edge tables0 и own connections0, затем обычный DROP DATABASE без FORCE
или terminate; свежий dbexists0/max_locks64. Все probes закрыты до передачи SQL
окна следующему исполнителю. Evidence только локально:
`.artifacts/root-corporate-counterparty-final.log`; raw runtime inventory и
подключения в публичный отчёт не включены. Полный CI/рабочий импорт/выпуск
этой целевой проверкой не подтверждены.
