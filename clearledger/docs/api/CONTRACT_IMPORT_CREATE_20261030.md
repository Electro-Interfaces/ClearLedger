# M06/P1: общая команда создания импортного Contract

Дата: 30.10.2026. База: `1c9ea350fff4502c5e0abdcb4b8b0eef65cc0e38`.
Ветка: `agent/api-contract-import-create-20261030`.
Статус: runtime реализован; первый actual run ROOT на `d80b14cc` дал
**68 PASS / 1 FAIL**. Исправлен только snapshot oracle нового теста;
повтор **35 новых случаев ещё НЕ ЗАПУСКАЛСЯ**. Worker ни на одной стадии
не импортировал приложение/драйвер и не выполнял SQL/pytest/collection.
Actual PostgreSQL-проверка остаётся только у ROOT на frozen составе и точной
синтетической базе, описанных ниже.

## Реализованный срез

Новая `app/services/contract_commands.py:create_imported_contract` принимает
явный типизированный список уже адаптированных полей: company, number/date,
counterparty/organization, type/kind/basis/scope_type и отдельный raw.
В команде ровно одна последовательность: Contract → db.add → успешный await flush
→ ContractIndex.add → вернуть Contract. Payload kwargs, нормализация, upsert,
дополнительные locks, retry, commit/rollback и manual markers не добавлены.

Только три производителя заменили свой прежний constructor/add/flush/index.add
вызовом команды и добавили необходимый импорт:

| Производитель | Что сохранил caller |
|---|---|
| `reestr_normalize.ingest_reestr` | `number=str(number)[:100]` в колонке; `str(number)` без нового усечения в raw.referenceIdentity; date fallback, CP/org, role type/kind, basis, locations scope, статистика и ContractLocation |
| `reestr_rushydro.L2Cache.contract` | Прежний `num` (100 символов либо б/н) и в колонке, и в raw; выбор Organization, supplier kind, locations scope, статистика и дополнительные ContractLocation |
| `charge_sessions_normalize._sync_corporate_contracts` | б/н, адаптация даты начала, corporate type, customer kind, company scope; CP aliases, CorporateClient phone-link и вся последующая логика |

Caller по-прежнему владеет ACL/company, матчером, выбором Organization,
порядком counterparty → contract advisory barriers, транзакцией, статистикой,
raw-адаптером и отношениями. Command не выбирает карточку при ambiguity и не
изменяет существующий Contract. Это консолидация поведения, не исправление
подтверждённой уязвимости; требование получить baseline FAIL не вводится.

Если flush неуспешен, именно новая карточка не публикуется в индексе.
Если caller позднее откатит всю транзакцию, прежние записи его Python-индекса
не очищаются автоматически. Новый helper не добавляет такого поведения;
повтор после rollback требует корректного владения индексом у caller.

## Source proof до выполнения приложения

Дерево до начала было чистым; новая ветка создана от точного локального base,
без pull и изменений общей ветки. Прочитаны принятая карта P1, отчёты 117
native PATCH/import и 79 counterparty regressions. Их результаты не выдаются
за проверку новой команды и не повторяются полными наборами.

Приватное AST-сравнение с base проверило для каждого из трёх производителей:
все прежние keyword expressions конструктора равны переданным в helper;
company передаётся тем же выражением, index — прежний; весь остальной AST
модуля совпадает после замены только этих четырёх statements и нового импорта.
Это source proof границы diff, не результат исполнения ORM/SQL.
Evidence: `.artifacts/contract-create/source-boundary.{py,json}`.

Python 3.13 разобрал AST и выполнил compile в памяти для четырёх runtime-файлов,
нового теста и runner. Ни один из них не импортировался и не исполнялся.
Число параметризованных случаев получено чистым AST-подсчётом без pytest collect.
`git diff --check` выполнен; старые тесты/модели/DDL/native/1С/store/CP commands/
ContractIndex/настройки/STATUS/inventory не менялись.

Карта `CONTRACT_WRITER_INVENTORY_20261030` остаётся историческим исследованием
на `eb5cdc513275e428e004f134e6b16d417d6f135e`, принятым ROOT как 1c9ea350.
После этой runtime-правки app другой: 490 файлов вместо 489. Старый source-proof
не регенерируется и не объявляется PASS на новом app; его воспроизводят на его pin.

## Frozen состав предложения ROOT

SHA256 файлов относительно `clearledger/server/`:

| Файл | SHA256 |
|---|---|
| `app/services/contract_commands.py` | `bb1fefc9f3a8fa0024c7354f463a17ccc70cb16a8b89f81ff92cc65fda998a6d` |
| `app/services/reestr_normalize.py` | `6020b20cfd13f1c8a21d5f0d3f60dc11a490daa0802d28595e93f84ff6ea12ed` |
| `app/services/reestr_rushydro.py` | `bcd5f19389047d57ed5dc8ecf7d4b066879443f180e8bb1f24895e42ae8883cf` |
| `app/services/charge_sessions_normalize.py` | `51b4ba21ecb956bd13084dbd5f536d49ded18c2ba54cd2def68a3519a40dcac8` |
| `tests/test_contract_import_create.py` | `cdc8feee5789e28cbe416e7094ec211e0477401558cfb96d865a1da901a2788f` |
| `tests/contract_import_create_approved.py` | `49e20180b9b78090f0b478feb021e956c84c5eeddd8db48a8dbde750100b614b` |

Runner закрепляет весь app (490 файлов) digest
`beb45c71788be8c6d9b016fed04abab60079a7598b8a634c0c464886abb60184`
и schema_migrations (16 файлов) digest
`51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d`.
Digest: SHA256 compact JSON списка `[relative-to-server path, sha256]`,
файлы отсортированы по пути, `__pycache__` исключён; ссылки и превышение 32 MiB
отвергаются. Это отдельный формат frozen execution gate, не прежний inventory digest.

Также закреплены неизменные conftest, common safety guard, helpers,
test package initializer, pytest.ini, requirements и три выбранных старых
тестовых модуля. Полный bounded proposal с этими хешами и source-only счётчиками:
`.artifacts/contract-create/proposal-oracle-v2.json`; первоначальное предложение
сохранено отдельно как `proposal.json`. Сырые данные, credentials и среда
процесса в публичный отчёт не включаются.

## Подготовленные meaningful actual checks

Новый opt-in модуль содержит **35 запланированных случаев**, ещё не collected:

| Сценарий | Число |
|---|---:|
| Все три actual producer: CREATE, same-run reuse, commit и повтор другой сессией | 3 |
| Golden адаптеров: длинный/отсутствующий номер, пустая/точечная дата, corporate б/н | 6 |
| Существующий ручной NULL/identity, raw, creation metadata, scope, CP aliases и relations | 3 |
| Неоднозначный Contract matcher и caller rollback | 3 |
| Чужая компания не используется и не меняется | 3 |
| Нет Organization / неоднозначные Organization | 6 |
| Успешный producer остаётся в caller transaction и откатывается | 3 |
| Actual constraint failure второго договора в каждом producer и общий rollback | 3 |
| Ошибка flush helper не публикует новую карточку; rollback не очищает прежний Python index | 1 |
| Раздельные адаптированная колонка 100 и полный raw 140 символов | 1 |
| Две SQL-сессии проходят реальные существующие company locks | 3 |

Проверки вызывают настоящие три функции и настоящие matcher/commands/ORM.
Expected golden — литеральные ожидаемые реквизиты синтетического ввода,
не результат вызова тестируемого кода. После commit/rollback результаты читает
независимая свежая session, а не identity map писателя. Прежний manual NULL
задан как существующее состояние карточки; native HTTP PATCH здесь не подменяется
и повторно не принимается.

Для отказа второго Contract в точной синтетической БД тест временно ставит
transactional CHECK, отвергающий заранее известный синтетический CP UUID.
Первые CP/Contract/relations успевают пройти реальную запись, второй flush
получает настоящий IntegrityError; rollback откатывает весь caller и сам CHECK.
Это DDL только тестового негативного контрола, **не изменение схемы приложения**.
Отдельный helper control получает реальный NOT NULL failure, сохраняя в памяти
прежнюю запись индекса и проверяя отсутствие новой.

Concurrency control удерживает первую транзакцию после actual producer,
запускает вторую независимую session, доказывает advisory wait через pg_locks
и pg_blocking_pids, затем коммитит первую и проверяет один persisted Contract.
Polling имеет deadline 10 секунд; задачи всегда join/cancel/reap в finally,
нет FORCE/terminate, изменения ролей либо GUC. Новые lock domains не вводятся.

Прежний legacy parser уже усекал номер до 100 до constructor. Golden длинного
legacy ввода учитывает именно этот parser. Само выражение raw `str(number)`
сохранено побуквенно; новый helper не усекает raw. Длинный L2 номер проверяется
одиночным CREATE; повтор с полной длинной строкой не объявляется новым matcher
контрактом. Same-run/repeat acceptance использует прежний нормальный номер.
Corporate UPDATE phone-link может менять updated_at клиента; сравнение сохраняет
все его бизнес-поля, исключая только этот ожидаемо обновляемый timestamp.

## Первый actual run ROOT и исправление oracle

На неизменном `d80b14cc1242df60a992bebd43c16fa52adc2251` ROOT выполнил
69 случаев: **68 passed / 1 failed**, pytest 69.62 с, процесс EXIT 1;
outer duration 82.5631846329 с. Единственный отказ — foreign-company/legacy
при сравнении DataEntry snapshot. Contract, Counterparty и relations в этом
сценарии совпадали; новый snapshot ошибочно обходил SQL table column keys,
поэтому для SQL-колонки `metadata` читал `Base.metadata`, а не `DataEntry.meta`.
Deepcopy объекта MetaData давал ложное различие и не проверял фактический JSON.
Это дефект тестового oracle, не обнаруженный дефект runtime.

По точному указанию ROOT oracle теперь использует `__mapper__.column_attrs`
и mapped attribute keys. DataEntry.meta сравнивается как настоящий JSON,
вложенные значения проверяются как scalar/list/dict; MetaData/ORM-объекты
не допускаются. Все mapped поля остальных моделей остаются в сравнении;
единственное прежнее исключение — CorporateClient.updated_at. Source AST-review
всех семи snapshot-моделей нашёл ровно один alias: DataEntry.meta → metadata.
Helper и все три runtime producer побайтово остались прежними.

Первоначальные hashes теста/runner были соответственно
`93690b8bca0a3870a53bd9262140602fdef868d684e1bfb7dad19ed68d9aa20c` и
`6e1d998a36e5aa9653ffdfe1ceddb809fdd971ab5d9a71a81ef4429a9c0d46b7`;
новые frozen hashes приведены выше. Старое evidence ROOT сохраняет приватно:
`.artifacts/root-contract-create-review-20261030/test.log`, JUnit и
`test-process.json`. ROOT подтвердил свежие relations=0/connections=0
для `api_contract_create_test_20261030`, обычный DROP DATABASE и прежний
max_locks_per_transaction=64. Worker этих подключений не выполнял.

## Предлагаемый повтор только affected 35

Первоначальный runner в d80b14cc выбирал **69 случаев**:

- новый модуль: 35;
- весь неизменённый `test_corporate_counterparty_commands.py`: 23;
- четыре выбранных producer-теста `test_counterparty_commands.py`: 7 с параметрами;
- четыре selected registry/L2/corporate-теста `test_reference_identity_api.py`: 4.

После исправления oracle ROOT запросил повтор только всех **35 новых случаев**.
Текущий frozen `SELECTION` содержит единственный новый test module; 34 unchanged
existing cases уже прошли в первом actual run и повторно не включены.
Полный прежний 117
набор native PATCH/1С не включён: его paths не менялись. Новые тесты helper
не предлагаются как baseline failure на базе, где helper ещё отсутствует.

ROOT сначала создаёт отдельную **`api_contract_create_test_20261030`** в своём
утверждённом synthetic PostgreSQL, проверяет цель и квоту, затем безопасно передаёт
credentials и approved loopback port в чистую среду runner. Runner не создаёт,
не удаляет и не подключает БД до проверки source/environment gate; pytest/conftest
и драйвер впервые импортируются только после него. Сам worker не выполняет
ни gate, ни pytest collect, ни SQL.

Gate требует одновременно:

- единственный аргумент `--execute-approved-contract-create-tests` и
  `ROOT_APPROVED_CONTRACT_CREATE_TESTS=1`;
- все три соответствующих opt-in флага, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
  PYTHONDONTWRITEBYTECODE=1, Python 3.13 без -O;
- равные явные TEST_DATABASE_URL/DATABASE_URL, scheme postgresql+asyncpg,
  host строго 127.0.0.1, точное имя БД, порт совпадает с отдельно переданным
  `CONTRACT_CREATE_PG_PORT`; URL без query/fragment и непустые credentials;
- allowlist ключей чистой среды, APP_ENV=test и synthetic SECRET_KEY;
  HOME только проверяется на сохранённое значение, не переопределяется;
- три разных пустых приватных каталога cwd/upload/evidence, принадлежащих
  текущему пользователю, mode 0700; текущий cwd именно empty test-каталог;
- frozen app/package/test hashes и неизменённый common pre-import safety guard.

ROOT запускает из своего пустого test cwd выбранным Python 3.13 окружением:

```text
python -I -B /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/contract_import_create_approved.py --execute-approved-contract-create-tests
```

Значения credentials в команду/отчёт не печатаются. UPLOAD_DIR и переменные
CONTRACT_CREATE_EMPTY_CWD/CONTRACT_CREATE_EVIDENCE_DIR задаёт ROOT; runner
принимает только пустые отдельные каталоги и пишет JUnit в private evidence.
Стандартный conftest разрушает public/edge **только этой выделенной БД**,
поднимает actual app schema/seed, а в teardown очищает схемы и закрывает engine.
Контроль client connections, фактического числа PASS/FAIL/SKIP, cleanup/обычного
DROP DATABASE и освобождение SQL-окна выполняет ROOT отдельно.

## Что ещё требуется

Нужны actual evidence ROOT для исправленного oracle и окончательная приёмка
этого среза. Статус повторного 35-case run остаётся NOT RUN; worker не завершает
Dispatch как будто runtime уже принят. При новом finding или изменении
frozen source требуется отдельное решение ROOT; baseline bugs в этот diff не правятся.

Остальные Contract writer families, native/1С/store commands, delete/scope/link
policy, внешние системы, полный CI/security scan и закрытие M06 вне этого патча.
Ни VM/контейнеры, ни сборки/зависимости, ни рабочие данные/окружения не затронуты.
Commit/push подготовленного состава не является merge, deploy или runtime acceptance.
