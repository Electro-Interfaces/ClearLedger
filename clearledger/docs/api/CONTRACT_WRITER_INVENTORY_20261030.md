# M06: карта записей Contract и следующий срез команд

Дата: 30.10.2026. Исходники Ledger закреплены на
`eb5cdc513275e428e004f134e6b16d417d6f135e`. Собственная ветка:
`agent/api-contract-writer-inventory-20261030`. Это инвентаризация исходников
и подготовка следующих патчей. Runtime, схемы, тесты приложения и окружение не менялись.
M06 остаётся открытым; принятые 117 PostgreSQL/ASGI/reference-проверок
native PATCH ↔ импорт 1С здесь не повторялись.

## Решение для следующего патча

Первым выделить узкую команду **создания уже сопоставленного импортного Contract**
для трёх мест: `reestr_normalize.ingest_reestr`, `L2Cache.contract` в
`reestr_rushydro` и `_sync_corporate_contracts` в `charge_sessions_normalize`.
В каждом повторяется одна последовательность: конструктор → `db.add` → успешный
`flush` → публикация в текущем `ContractIndex`. Общая команда должна владеть
этой последовательностью. Политика допуска, выбор компании/сторон, matcher,
блокировки, адаптация исходных значений, статистика и связи остаются у caller.

Это минимальная консолидация существующего поведения, не исправление доказанной
ошибки. Она создаёт общую точку для последующих инвариантов, не смешивая три
разных правила сопоставления и два режима охвата. Первый патч не должен включать
1С, native CRUD, SQL магазина, условия начисления или DDL.

## Основания и воспроизводимость

Перед исследованием проверены чистое дерево и HEAD `3efe30720d50fb5562e67b08a086643ed6d78484`
прежнего освобождённого worker. Новая ветка создана от точного локального pin
`eb5cdc51`; pull, переключение общих деревьев и перенос чужих изменений не выполнялись.
Прочитаны проектные инструкции, `rushydro-space`, `orchestration`, принятые отчёты
freshness/serialization и обеих итераций counterparty commands.

Программа поставки прочитана в отдельном read-only дереве:
`ecosystem-deploy/partner-api-design-20261029`, коммит
`af80398398b5d625102b8d374f4ac6b9d58a4133`:

- `docs/API-MODERNIZATION-PLAN.md`, §5 и строка M06: домен владеет командой,
  transaction принадлежит use case; один matcher/scope service; явная ambiguity;
  сохранение replay/concurrency/null/связей.
- `docs/api/execution-20261029/STATUS.md`: принятые локальные проверки отделены
  от оставшихся commands/null-intent. Отдельного Ledger `M06.md` нет, что
  координатор подтвердил в текущем Dispatch.

Оба документа при чтении побайтово совпадали с их Git-коммитом. Их SHA256,
а также pin/hash пяти принятых Ledger-документов находятся в
`context_documents` парного JSON. Это контекст решения, не доказательство
runtime-состояния пространства.

Новый `clearledger/scripts/inventory-contract-writers.py` использует только
Python 3.13 stdlib и read-only команды Git. Он получает **все** Git blobs
под `clearledger/server/app/`, сравнивает каждый с рабочим файлом, разбирает
каждый Python-файл AST, затем собирает текстовые попадания, операции записи
и spelling вызовов. Исходники приложения не импортируются и не исполняются;
`exec`/`eval`, драйверы, SQL, БД, контейнеры, API и браузер не использовались.

| Доказательство исходников | Значение |
|---|---:|
| Закреплённые файлы app / побайтовые совпадения | 489 / 489 |
| Python-файлы, разобранные AST | 479 |
| Семейства решений, включая смежные/исключения/unknown | 28 |
| Уникальные source references с file/AST hashes | 127 |
| Проверенные spelling-рёбра caller → callee | 27 |
| Current/preserved countercases | 15 |
| Импортированные ORM-конструкторы именно `app.models.Contract` | 5 |
| Литеральные SQL sinks договорного контура | 9 |
| Широкие AST-кандидаты, включая unknown receivers | 13 204 |
| Текстовые попадания / AST callsites всего app | 2 095 / 109 009 |
| Чистые контроли классификации/хеша | 13 |

SHA256 полного приватного манифеста файлов:
`7cb11cfeace8357724362143b8d23e1751f5783d76dad02453581e617d93e4d8`.
SHA256 самого анализатора записан в `proof.generator_sha256` парного JSON.
13 204 — число синтаксических кандидатов во всём app, **не число Contract writers**.
109 009 — уникальные позиции AST Call, включая определения моделей и модульный код,
не число достигнутых runtime-вызовов.

Публичный JSON ограничен владельцами, решениями, полями, caller-цепочками,
source refs и хешами. Он не содержит полного манифеста app, SQL-текстов,
сниппетов, содержимого клиентов или сырых результатов поиска. Полный манифест,
`raw-hits.json`, `candidates.json`, `calls.json` и `proof.json` сохраняются
только в игнорируемой `.artifacts/contract-writers/` этого изолированного дерева.

Для независимого повтора из корня этого дерева:

```bash
/home/mag/.local/bin/python3.13 clearledger/scripts/inventory-contract-writers.py
git diff --check
```

Первая команда сверяет готовый JSON и пишет только private evidence. Она откажет
при изменении pinned app/evidence, повторе ID, несовпадении hashes/counts,
непроверенном точном ORM/SQL sink, потерянном caller spelling или неигнорируемом
выходном каталоге. Оптимизированный Python с отключёнными assertions отвергается.
`--refresh` предназначен только для осознанного обновления производных хешей
нового отчёта после source review; обычной проверке он не нужен.

## Общие корни

`reference_identity.ContractIndex` хранит текущую и исходную идентичность,
сопоставляет UUID/строки/внешнюю ссылку контрагента и требует однозначности.
Он не является командой записи, ACL или ограничением БД. Полные ручные
`number/date/type` нормализует `contract_identity`; импортные пути сохраняют
свои адаптеры и намеренно неполные критерии.

`lock_manual_creation` задаёт company/entity advisory barrier до конца
транзакции. Native CREATE использует его при полной business identity либо
creationKey; native PATCH и `_sync_contracts` используют для сериализации.
Реестры и corporate берут counterparty → contract. Это разные условия входа,
не единая уже завершённая Contract command policy.

`reference_overrides` отделяет system/raw поля от ручных колонок:
snapshot → реальные изменения → `manual_overrides`; импорт применяет только
незамороженные значения. Generic `setattr` внутри helper относится к Contract
лишь через прослеженного caller; остальные динамические receivers не объявлены
Contract по имени переменной.

`get_owned` проверяет компанию, visit-company, членство и объектный допуск.
`assert_company_member` устанавливает request scope. Startup ORM hook в `scope.py`
добавляет критерии для ServiceLocation/ChargeSession, не для Contract; наличие
этого hook не подменяет отдельную договорную политику. Для raw SQL он также
не является автоматическим скоупом. Отсутствие прямого `get_owned` в конкретной
функции — исходная граница review, не готовый вывод об эксплуатации.

`get_db` завершает request transaction commit/rollback. Background channel
использует собственную сессию; orchestrator откатывает неудавшуюся dispatch-операцию
перед публикацией failure fact. Некоторые владельцы явно коммитят сами. Перенос
этих границ в общий helper без отдельного среза изменил бы поведение.

## Карта записей паспорта и его собственного охвата

Идентификаторы CWxx и reference IDs однозначно связаны с парным JSON; там для
каждого указаны поля, ACL/preconditions, transaction, locks, identity/replay,
manual NULL, raw ownership и используемый либо обойдённый общий helper.
`fieldsets` перечисляет точные колонки паспортных CREATE/UPDATE, nullable clear
и отдельно сохраняемые существующие поля. Native PATCH не очищает nullable
kind/currency через null: эти ветки требуют non-null. Принятые NULL-контроли
не объявляются общей реализацией null-intent для любой nullable колонки.

| Семейство | Фактический владелец / caller | Запись и границы |
|---|---|---|
| CW01 | `references_router.create_contract`, native POST | ORM CREATE: реквизиты, стороны, company, creation metadata. Проверка компании/сторон, type code, business duplicate; creationKey связан с actor/request hash. Flush, commit у get_db. Raw не заполняет; общего Contract create command нет. |
| CW02 | `references_router.update_contract`, native PATCH | Get-owned до барьера под no_autoflush → barrier → flush → scoped populate_existing → fresh membership/get_owned → поля/markers → flush/refresh. Explicit nullable intent через model_fields_set. Принятая граница 117 проверок сохранена. |
| CW03 | `references_router.delete_contract`, native DELETE | Get-owned → contract_usage → 409 при использовании → db.delete. Сам по себе не «закрывает» использованный договор. Явного общего Contract barrier в функции нет. |
| CW04 | `set_contract_scope`, PUT scope | Меняет scope_type и пересобирает ContractLocation; для locations берёт подходящие локации своей компании. SELECT Contract → assert_company_member; manual markers не ставит. |
| CW05 | `link_contract_location`, POST location | Проверяет компанию/локацию, отвергает company-wide договор, добавляет связь при отсутствии, ставит locations. |
| CW06 | `unlink_contract_location`, DELETE location | Убирает связь; последняя связь переводит locations → unassigned. Общего lifecycle command/barrier в функции нет. |
| CW07 | `set_contract_dimension`, PUT dimension | Удаляет/создаёт ContractDimension одного типа. Не меняет паспорт, но влияет на его аналитические связи. |
| CW08–CW09 | `add_contract_link` / `delete_contract_link` | Get-owned Contract; добавление проверяет app и company project, удаление — принадлежность link договору. Самостоятельные relation writers без общей Contract command. |
| CW10 | ops PUT liability → `contract_liability.set_liability` | SELECT по company+Contract, замена локального JSON liability, source=manual, escalation defaults; None-ключи входа убирает; **service commit**. Raw/markers не трогает. |
| CW11 | legacy `ingest_reestr` | ORM CREATE только при отсутствии совпадения и наличии номера. Усечение номера, исходные date/type/kind/basis, scope=locations, identity snapshot. Связи добавляет caller. |
| CW12 | `L2Cache.contract` | ORM CREATE после matcher; при отсутствии номера возможен б/н. Caller/build владеет company indexes/locks/Organization, helper также добавляет ContractLocation. |
| CW13 | POST charge-sessions/enrich → `_sync_corporate_contracts` | Corporate ORM CREATE: б/н, адаптированная дата начала, scope=company, buyer kind. Существующий Contract по CP+type сохраняет. Телефонная связь CorporateClient — отдельная запись контрагента, не паспорт договора. |
| CW14 | 1С catalogs/full → `_sync_contracts` | ORM CREATE либо promo UPDATE через apply_import_values; отдельно external_ref/full raw. Shared barrier, flush, fresh company-scoped rows; explicit source/connection/key conflicts. Scope/basis/liability/creation metadata существующей записи не переписывает. |
| CW15 | store POST partners → `store_partner_create` | Optional raw SQL INSERT contracts вместе с каноническим CP/edge partner. Network authority; organization presence в этом блоке, без локального company ownership SELECT организации. Отдельный commit, нет ContractIndex/creationKey. |
| CW16 | store POST contracts → `store_contract_save` | Raw SQL INSERT либо UPDATE number/date/title/kind/currency/comment по id+company. Ветка UPDATE не меняет CP/org/type; присланные стороны всё равно обязательны для входа. Нет manual markers/reference barrier; response не проверяет rowcount. |
| CW17 | lifespan → prepare_once → prepare_database → create_all | Legacy DML нормализует date/valid_until/type_code; backfill охвата и OpsContractTerm. Также legacy cast amount_limit/party UUID. Namespace/startup ownership, а не user ACL. Исключение migration lifecycle. |
| CW28 | модель Contract и FK/соседние модели | Декларированы SET NULL system actor/responsible при удалении User, CASCADE собственных links/locations/dimensions при удалении Contract, restrictive стороны. Установленные constraints/triggers этой работой не проверялись. |

Пять ORM constructors: native CREATE, legacy reestr, L2Cache, corporate, 1С.
Девять SQL sinks: четыре Contract-нормализации bootstrap, два bootstrap backfill
охвата/условий, один store partner INSERT, store INSERT и UPDATE.
Это счёт выражений с закреплёнными AST anchors, не число бизнес-команд,
срабатываний DDL или реальных записей.

## Достижимые source-цепочки

Для основных writers закреплены 27 caller spelling-рёбер с line/column/AST hash.
Прямые импорты, локальные aliases и экземпляры классов обозначены раздельно:

- Native references/store/ops/onec/charge роутеры подключены в pinned `main.py`.
  HTTP handlers остаются исходными entrypoints, не проверенными здесь запросами.
- Channels `run_channel` создаёт background задачу. Она вызывает import alias
  `orchestrate_channel` → service `run_channel` → `_dispatch` → `_run_reestr`
  → `run_reestr_file`. Ветка svod вызывает legacy; svodnaya/arenda/tariffs
  конструируют локальный L2Cache, делают build и вызывают `l2.contract`.
  Наличие L2Cache в obshaya само по себе не означает создание договора;
  его не включаем четвёртым contract caller.
- Charge-sessions POST `/enrich` проверяет product sales, вызывает
  `enrich_sessions_with_orgs` → `_sync_corporate_contracts`; commit у роутера.
  Другие операции enrichment не объявлены writers Contract по общему имени.
- 1С `sync_catalogs` и `sync_full` создают OneCSyncService; catalogs вызывает
  `_sync_contracts`. Transport COM/OData выбирается отдельно и не меняет
  существование этого source writer. Настоящие источники не открывались.
- Ops liability/terms вызывают свои services; bootstrap идёт через
  `_prepare_database_once` и `_prepare_database`, не прямым вызовом из lifespan.

Проверка spelling подтверждает присутствие выражения вызова в закреплённом
caller. Она не доказывает достижение ветки, runtime type произвольного объекта,
полноту Python call graph, порядок планировщика или эффективные права токена.

## Версионные условия и смежные ссылки

CW18 — `ops_terms.create_term/update_term/delete_term`, HTTP ops POST/PATCH/DELETE
terms. Это отдельный aggregate OpsContractTerm, а не UPDATE Contract.
EDITABLE whitelist не даёт переназначить компанию/договор произвольным полем;
`_check_window` проверяет интервал article+location под ops-term-window barrier.
Update берёт этот барьер до fresh select. New version закрывает старую
предыдущим днём и создаёт новую; delete удаляет untouched expectations,
сохраняя закрытые учётные факты. В delete-функции нет того же явного барьера.
Барьер условий отличается от reference-create-v1; взаимная сериализация
этих двух доменов этой картой не заявляется.

| Семейство | Смежные записи, влияющие на использование Contract |
|---|---|
| CW19 | Settlements, OpsCounterpartyDoc, IntakeItem/AccountingDoc, books relink, периодные expectations. Поля contract_id и проводочные dt/kt refs — самостоятельные учётные факты. |
| CW20 | StoreReceipt и canonical refs/snapshots, `_set_receipt_party`, edge `_ingest_receipts`. Generic setattr в edge меняет receipt, не Contract. |
| CW21 | `ezs_project.link_contract`, project integration contractIds и project workspace DocRelation. Проектная привязка не изменяет паспорт. |
| CW22 | Equipment/supply/spare documents, ops-meter owner, warehouse metadata contractId. Draft payload/dynamic field maps сохраняют unknown до локальной проверки типа/receiver. |
| CW23 | `set_member_contracts`: company admin, проверка выбранных company Contract; запись UserCompany.contract_ids. Это основание участия, не выдача доступа. |
| CW24 | DocCard subject_ref/attrs, DocRelation target_ref; Task, CalendarEvent, Reminder, partner topics/messages, ConfSession, MarketGrowthLead. Владение и допуск остаются у соответствующих доменов. |
| CW27 | MailRule.set_contract_id: create/update через `_validate_rule_refs`; не UPDATE Contract. |

`contract_usage` объединяет прямые ссылки и soft refs, собственные links,
locations/dimensions и при наличии колонки — Support core/public.service_contracts.
Оно не опрашивает проводки gl_turnovers и не устанавливает блокировочную границу
между всеми потребителями. Соседний Support имеет своего владельца исходников;
его внешние writers здесь не сканировались.

Смежные семейства — границы владельцев и исходные точки следующего review,
не полная приёмка ACL каждого task/mail/equipment/calendar endpoint. Конкретные
процедуры в JSON имеют закреплённые hashes, остальные generic/dynamic варианты
видны в полном private AST/text inventory и остаются unknown.

## Сохранённые различия и исключения

CW25 исключает `product_api.dto.Contract` и `dto.Contract(...)` из ORM writers:
GET-проекция остаётся ответом DTO. Пакет `api_contracts` описывает API-протокол,
а не модель contracts. В pinned app нет отдельного ORM ContractDoc: пользовательская
бумага договора реализована DocCard/relations/source_ref. `contract-document:<UUID>`
связывает намерение создать бумагу; project workspace promote также создаёт DocCard.
Ни один из этих путей не становится Contract constructor из-за названия документа.

CW26 сохраняет **unknown** для неразрешённых receivers, aliases, reflected/model-map
операций, in-place JSON/collection mutations, динамически составленного SQL и
внешних restore/adapters. Analyzer собирает также bulk/merge/execute/setattr,
attribute/subscript stores и collection mutations. Импортные bindings в анализаторе
лексические; это не полноценный resolver затенения имён или произвольного data flow.
Отсутствие ещё одного точного конструктора не равно доказательству отсутствия
произвольного динамического writer.

Restore не найден как приложение-владелец Contract CRUD: пользовательские
restore endpoints здесь возвращают DataEntry/архивные файлы. Внешний pg_restore,
административный SQL, установленная схема, триггеры и скрипты вне app не входили
в source universe. Ранее принятая DDL/dump-restore инвентаризация их бизнес-команды
не закрывает. CW17/CW28 отделены как migration/FK effects.

15 countercases в JSON разделены на девять сохранённых source-тестов и шесть
текущих исходных различий. Среди сохранённых: оба порядка native PATCH/import,
pending autoflush, свежий допуск после ожидания, same-upstream отрицательный контроль,
creation replay, отдельные намерения бумаг, ambiguity, исходная manual identity
и сохранение истории версии условий. Это hashes прежних тестов, не новый PASS.

Текущие различия: ORM/DTO; отсутствие номера в legacy/L2/corporate; native markers
против SQL магазина; DocCard promotion; два lock domains; scalar scopeType native
PATCH против пересборки links отдельным scope endpoint. Эти контрпримеры удерживают
будущий общий helper от необоснованного «выравнивания» существующего поведения.

## Следующие патчи по порядку общих корней

### P1. Три импортных CREATE, выбранный минимальный следующий срез

Владелец: Core references/import. Новая `services/contract_commands.py`; изменения
строго в трёх конструкторах CW11–CW13 и новом meaningful opt-in тестовом модуле.
Существующие CP commands, matcher, DDL, native APIs и 1С вне первого diff.

Вход: уже выбранная company, ContractIndex текущего прогона, проверенные caller
parties/Organization, полностью адаптированные number/date/type/kind/basis/scope,
исходный identity snapshot. Лучше явные параметры/allowlist полей вместо
неограниченного ORM kwargs из HTTP/import payload. Helper не получает полномочий
самостоятельно выбирать CP/Organization либо сопоставлять конфликтующий договор.

Инварианты: flush предшествует index.add; неуспешный flush не публикует объект;
helper не делает commit/rollback; caller отвечает за locks до flush, transaction,
statistics и ContractLocation; raw сохраняет именно прежние значения/форму,
ручные поля существующих Contract не обновляются. Не добавлять UUID/date/string
нормализацию, урезание raw, creationKey, новый unique index или SQL upsert.

Будущая приёмка на новой выделенной synthetic PostgreSQL, после отдельного
SQL-разрешения: по каждому настоящему producer CREATE + same-run/repeat reuse;
ambiguity отказывает без частичной записи; foreign-company совпадение не используется;
два последовательных успеха и ошибка второго flush откатываются caller целиком;
индекс после отказа не содержит новую карточку; два независимых sessions под
прежними locks не дублируют соответствующее бизнес-намерение. Проверять новый
persisted state отдельной сессией, не старой identity map. Номер/дата отсутствуют,
длинный номер, CP UUID/string/external ref, неоднозначная Organization, разные
scope/raw адаптеры — обязательные контролы. Ранее ручные NULL/identity markers,
creation metadata и links существующего Contract должны сохраниться на replay.

### P2. Общий ручной PATCH policy и store adapter

Владелец: Core references + Shop; отдельный ограниченный патч после P1.
Граница: выделить из принятого native PATCH общий manual-edit use case, затем
подключить `store_contract_save` UPDATE через адаптер прежней формы/ошибок/полей.
Native accepted lock/refresh/admission/no-autoflush порядок переносится целиком.
Transaction ownership магазина и его raw/source semantics требуют явного контракта;
не объявлять CP/org/type изменяемыми в старой UPDATE-ветке.

Будущие negative controls: shop изменил promoted nullable → changed upstream 1С
в другой session в обоих порядках; persisted NULL и markers после commit/replay;
foreign Contract/party/org, missing id и changed membership во время ожидания;
failed flush/rollback без частичного CP/edge Contract. Omitted, empty string,
explicit null, unchanged и null→null характеризовать по существующему store adapter,
не импортировать native-семантику молча. Пока это source bypass общей manual policy,
не доказанная потеря данных и не vulnerability finding.

### P3. Единая политика scope/link/delete

Владелец: Core contracts + adjacent link owners. Граница: CW03–CW09, CW10 и
contract_usage; общий scoped loader/action policy и согласованный lifecycle barrier.
Сначала определить желаемое действие для object-limited участника и company-wide
договора, scalar PATCH scopeType против отдельного scope endpoint, разрешённые
dimensions/app/project и операцию close/delete. Вопросы записаны в JSON; новый
вопрос пользователю в этой задаче не требуется.

Будущие controls: concurrent delete ↔ add location/link/term/soft document reference;
foreign company/невыданный объект, повторный link, empty/full/unassigned transitions,
очистка последней локации, ссылки через attrs и subject_ref, присутствующие/отсутствующие
Support колонки. Проверить, что отказ 409 не удаляет и не закрывает паспорт сам;
references не теряются через SET NULL. Нужен единый порядок reference/row/FK/term
locks и доказательство отсутствия deadlock на тестовых двух sessions.

### P4. 1С UPDATE и условия/схема как отдельные владельцы

Владелец: Core imports для CW14; Core ops/Persistence для CW18/CW17.
После shared roots вынести imported apply из адаптера, сохраняя source assertion,
полный raw, предыдущую referenceIdentity, connection ownership, manual freeze,
локальный scope/basis/liability, creation metadata и статистику. Не объединять
это с DDL migration или interval-version logic.

Будущие controls: другой Ref_Key/connection/source → явный conflict без частичного
применения; same/changed upstream, manual NULL, retained identity map, повтор в
той же/другой session, caller rollback. Для terms отдельно delete/update/new-version
concurrency и сохранение закрытой истории; для migration исключений — fresh/upgrade/
repeat/restore в M16. Это будущая программа приёмки, не результаты данной работы.

## Предел результата

Полный pinned app прочитан/разобран и побайтово сверён; для известных writers
зафиксированы реальные owner/caller/field boundaries. Динамические возможности
Python и внешние владельцы не получили фиктивного нулевого остатка.
Ни синтаксическая запись, ни отсутствие вызова helper сами по себе не доказывают
уязвимость, потерю данных, effective ACL, runtime transaction ordering или готовность
выпуска. Полный security scan/certification и закрытие M06 не заявляются.

Новые файлы этого среза: только данный Markdown, парный JSON и source-only
анализатор. Старые исходники/тесты/status/memory/skills не редактировались.
Runtime suites, SQL, DB/Docker/images, `.env`, рабочие API, VM/CI, зависимости,
merge и deploy не запускались; новых workers не создавалось. Собственный commit/push
передаёт координатору материал для независимого воспроизведения и выбора патча.
