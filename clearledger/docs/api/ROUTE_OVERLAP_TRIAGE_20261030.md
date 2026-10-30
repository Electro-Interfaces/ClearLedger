# M01: literal/parameter overlap, 30.10.2026

Проверены ровно **109/109** кандидатов из заданного приватного артефакта на исходниках
`ffab2a10d979d323ddbb0613d233ef279f566fd3`. Для каждого конкретного синтетического
GET-пути оба маршрута возвращают `Match.FULL`, но первым FULL во всём реальном
дереве приложения выбран literal. **Подтверждённых перекрытий literal-маршрутов: 0.**
Само пересечение шаблонов здесь не является дефектом.

Это проверка выбора регистрации через `route.matches()`, а не выполнение запроса.
Обработчики, зависимости, авторизация, middleware, ASGI dispatch, startup/lifespan,
OpenAPI, сеть и SQL не запускались. Доступность и успешное выполнение endpoint,
ACL, нагрузочная устойчивость, production composition и полный security scan
этой работой не подтверждены.

## Исходники и сохранность доказательств

- Отдельное дерево: `/home/mag/orca/workspaces/ledger-app/api-route-overlap-triage-20261030`,
  исходная ветка `MagLook/seanettle`; при старте чистый HEAD равен immutable expected
  `ffab2a10d979d323ddbb0613d233ef279f566fd3`.
  Pull/переключение базы не выполнялись, чтобы сохранить заданную immutable ревизию.
- Приватный вход только читался:
  `/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-runtime-with-ws-log-privacy.json`.
  SHA256 **`5ed1476881bfb10a7647ace11dddc22e3596c58f7a0585b8d74f5be9987c901c`**;
  его `sourceRevision` = `e6659c6e7adb4843cfc7a60b8a0d14373daa7026`,
  1703 operations, 109 candidates, 1 mount, 1 websocket operation, unresolved=0.
  Это self-described provenance артефакта, дополнительно проверенная свежим экспортом.
- Повторный импорт actual `app.main.app` на immutable expected через существующий
  guarded exporter подтвердил точное равенство всех operations (включая endpoint,
  order, method/protocol, mount, compiled match pattern), mounts, unresolved,
  candidates, duplicates, parameterCollisions и sharedPaths. Сравнивались полные
  значения структур, не только количество или множества method/path.
- `server/app` Git tree изменился с `641420261c56f73187e86269de752d4969e74f41`
  на `083333f706782fc19e93ce50f7173903fbbf091a`. Изменения нельзя игнорировать:
  текущий actual экспорт выполнен заново. Все 12 файлов, содержащих 124 endpoint
  из этих пар, byte-for-byte неизменны между исходной и проверяемой ревизиями.
  `main.py`, `database.py` и существующий exporter также неизменны.
- Blob существующего exporter на обеих ревизиях:
  `059d8463107eb5ee87a7e2f7770d2327f4c33724`;
  SHA256 файла `da3e17cbb721f059ee1ad6492224081317ec9f7bc5ce28f6c856fa1b28607598`.
- Среда: Python 3.13.7, FastAPI 0.115.6, Starlette 0.41.3.
  `APP_ENV=dev`; partner_api/oauth/docs flags=false; реальные `app.database` и Base;
  синтетическое окружение существующего exporter; `python -I -B` в временном cwd.
  Во всех успешных actual импортах guard deniedAttempts=0.

Приватный raw inventory не скопирован в Git/HTTP. В репозитории только bounded
[companion JSON](ROUTE_OVERLAP_TRIAGE_20261030.json): 109 pair records и 124 уникальных
source endpoint, необходимые для этих пар, без каталога остальных маршрутов,
dependency/ACL inventory, реальных рабочих данных или секретов из private deploy canon.
Разрешение координатора на один новый offline tool и один pure test получено через
Orca ask; существующий exporter, guard и runtime не менялись.

### Хеши нормализованных секций registry

Сериализация: `json.dumps(value, sort_keys=True, separators=(',', ':')).encode()`
(стандартный `ensure_ascii=True`), затем SHA256. Все секции равны исходному артефакту.

| Секция | SHA256 |
|---|---|
| `duplicates` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `literalParameterOverlaps` | `17853efa19fdcbd28b486bf8fb35012f223cf6c46049816a748022688cdd15bc` |
| `mounts` | `f606e77c283c2e39465a227664e0fe815dd160349b88962bd7fbdf6e30edbe43` |
| `operations` | `f5743f36eab4aa429a965cf150bee2aae7623d6c52ade9d162265c41d39e47e6` |
| `parameterCollisions` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `sharedPaths` | `0bfa3baa522b1337b592ee0325f279fb881998413cdd41c14206a4b392dd27d4` |
| `unresolved` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |

## Метод проверки и ASGI Mount

[triage-route-overlaps.py](../../scripts/triage-route-overlaps.py) повторно использует
`exporter.launch_export(..., runner=triage_runner)`: изоляция, synthetic environment,
временный cwd, timeout, захват stdout/stderr и очищенный failure envelope остаются
у существующего launcher; runner меняет только путь child entrypoint. Child использует
существующие `OfflineGuard`, synthetic env, реальный engine `do_connect` запрет,
SQL/socket/process/write audit, проверку реального Base и safe_failure.
Новые разрешённые пути или обходы не добавлены; история denied не сбрасывается.

Для каждой исходной пары:

1. Route берётся по исходному registration order из actual `app.routes`,
   endpoint сверяется с текущим registry; compiled regex и convertors читаются
   с этого объекта, без пересоздания Route по строке или regex-аппроксимации.
2. Witness = полный **literal path** с его настоящими method/protocol;
   root_path пуст, query отсутствует. Literal обязан дать FULL в правильном протоколе
   и методе; parameter проверяется отдельно на том же witness.
3. Проверяется всё дерево от начала. Каждый предыдущий route получает `.matches(scope)`;
   первая FULL выигрывает, PARTIAL не перекрывает последующую FULL.
   `examinedRouteNodes` и `earlierPartialOrders` сохранены для каждой пары.
4. FULL у Mount фиксирует выбор родителя. Его `child_scope` (включая root_path и
   path_params) передаётся дочерним маршрутам. Если дочерний FULL не найден,
   возврата к следующим соседям внешнего Mount нет. Default/redirect не исполняются;
   отсутствие доказательства превращается в unknown, а не ложный shadow.
5. По исходнику endpoint сохранены файл/строки, decorators, SHA256 файла и определения,
   первый абзац docstring, аннотация path-параметра, строки его использования и return.
   Это evidence назначения обработчика; выполнение тела не заявляется.

Единственный реальный Mount: order `[0]`, path `/api/v1`, класс
`starlette.routing.Mount`, дочернее приложение FastAPI. У всех 109 witness первый
Mount даёт NONE: их пути вне `/api/v1/`. Все сами пары находятся в корневом router,
`mountPath='/'`, `mountChain=[]`; вложенной композиции ни у одной пары нет.
Значение `examinedRouteNodes` у каждой пары равно `literal.order[0] + 1`:
проверены абсолютно все более ранние узлы, включая Mount, а не только участники пары.
Более ранних PARTIAL для этих witness нет. Nested Mount/root_path, commitment без
sibling fallthrough, FULL/PARTIAL и ранний посторонний catch-all проверены pure controls.

## Результат и ровно одна primary classification

| Primary verdict | Пар |
|---|---:|
| `literal_precedes_parameter` | 109 |
| `incompatible_method_or_protocol` | 0 |
| `parameter_before_literal_shadow` | 0 |
| `other_earlier_route_shadows_literal` | 0 |
| `unknown_match_proof_insufficient` | 0 |
| **Всего** | **109** |

Все пары GET/http. Нулевое число несовместимых методов/протоколов ожидаемо:
генератор исходных candidates уже отбирает одинаковые method/protocol. Это не
доказывает отсутствие иных взаимодействий методов/протоколов вне этих 109 пар.
Набор индексов пар пересчитан: 109 уникальных пар, повторов и пропусков нет.
`firstFull.order == literal.order < parameter.order`, endpoint первого FULL равен
literal endpoint, а literalMatch=parameterMatch=FULL для каждой из 109 записей.

Во всех 109 параметрических регистрациях фактический convertor **StringConvertor**,
regex `[^/]+`. UUID-аннотации Python не являются Starlette convertor `:uuid`.
В 18 парах параметр аннотирован `uuid.UUID`, в 91 `str`; для UUID валидация FastAPI
идёт после выбора маршрута. При гипотетическом переставленном порядке возможен 422
на literal-токене до тела обработчика, но зависимости/авторизация могут завершиться
раньше; конкретный HTTP-статус здесь не проверялся. Строковые параметры также
разбираются helper-функциями/поиском внутри обработчика; FULL не означает принятую
бизнес-команду. Сейчас все эти literal-токены корректно выбирают literal-регистрацию.

### Назначение literal и parameter по source

В следующей таблице перечислены все 15 параметрических семейств. Источник каждого
literal указан отдельно в реестре 109 ниже; JSON содержит его doc/return evidence.
Значения описывают исходники, не результат вызова и не доступ пользователя.

| Параметрический маршрут | Пар | Назначение parameter и отличие literal |
|---|---:|---|
| [`/api/tickets/{ticket_id}`](../../server/app/routers/tickets_router.py#L218) | 2 | Карточка заявки; `_uuid_or_400(ticket_id)` и выбор по t.id. Literal: сводка работы / регламенты. |
| [`/api/tasks/{task_id}`](../../server/app/routers/tasks_router.py#L2269) | 11 | Карточка задачи; `_task_or_404(..., task_id)`. Literal: люди, проекты, виды, представления и сводные коллекции. |
| [`/api/docs/{doc_id}`](../../server/app/routers/docs_router.py#L5170) | 12 | Карточка документа; `_doc_or_404(..., doc_id)`. Literal: справочники, списки, доска и экспорт реестра. |
| [`/api/work/calendar/{event_id}`](../../server/app/routers/work_router.py#L1547) | 4 | Одна встреча; `db.get(CalendarEvent, _uuid_or_400(event_id,...))`. Literal: сводка, занятость, feed link и video-link. |
| [`/api/accounting-docs/{doc_id}`](../../server/app/routers/accounting_docs_router.py#L242) | 2 | Один AccountingDoc по parsed UUID. Literal: поиск по реестру и агрегаты. |
| [`/api/equipment/documents/{doc_id}`](../../server/app/routers/equipment_router.py#L737) | 1 | Один документ через `D.get_document(..., doc_id)`. Literal meta возвращает виды документов/владения. |
| [`/api/equipment/spare-documents/{doc_id}`](../../server/app/routers/equipment_router.py#L1502) | 1 | Один документ через `SD.get_document(..., doc_id)`. Literal count-sheet вызывает `SD.count_sheet`. |
| [`/api/sites/{site_id}/forecast`](../../server/app/routers/sites_router.py#L649) | 1 | Прогноз отдельной площадки после `_owned(..., site_id)`. Literal analysis/forecast строит forecast_vs_fact по портфелю. |
| [`/api/sites/{site_id}`](../../server/app/routers/sites_router.py#L744) | 8 | Карточка площадки через `ezs_sites.site_detail(..., site_id)`. Literal: портфели и сводные реестры. |
| [`/api/sites/{site_id}/report`](../../server/app/routers/sites_router.py#L762) | 1 | Отчёт отдельного проекта после `_owned`. Literal costs/report вызывает отчёт бюджета портфеля. |
| [`/api/project-workspace/{sid}`](../../server/app/routers/project_workspace_router.py#L60) | 1 | Workspace конкретной площадки через `owned(..., sid)`. Literal unlinked вызывает listing без привязки к площадке. |
| [`/api/registry/objects/{object_id}`](../../server/app/routers/space_registry_router.py#L123) | 1 | Карточка через `space_registry.get_object(..., object_id)`. Literal open-tickets: сетевой список открытых заявок. |
| [`/api/store/documents/{record_id}`](../../server/app/routers/store_documents_router.py#L1357) | 3 | Детали document projection по record_id. Literal: triage, список смен, состояние recompute. |
| [`/api/store/receipts/{receipt_id}`](../../server/app/routers/store_router.py#L6990) | 2 | StoreReceipt по receipt_id. Literal: аудит дублей и сирот. |
| [`/api/store/{report}`](../../server/app/routers/store_router.py#L9755) | 59 | Периодический fallback: dispatch-словарь receipts/suppliers/catering/categories/recipes. Literal: отдельные отчёты и коллекции с собственными контрактами. |

### Намеренный приоритет: отдельная source-аннотация, не вторая classification

- O029: [calendar_video_link](../../server/app/routers/work_router.py#L1493)
  прямо поясняет регистрацию до `/calendar/{event_id}` во избежание захвата пути.
- O100–O101: [план и план-факт](../../server/app/routers/store_router.py#L8046)
  сопровождаются указанием регистрировать их до catch-all `/{report}`.
- O106: [store_report docstring](../../server/app/routers/store_router.py#L9764)
  описывает barcodes как отдельный верхний маршрут, справочник вне периода.
- O086 (`/api/store/receipts`) также выигрывает у generic report; в fallback-словаре
  присутствует ключ `receipts`. Из source следует отдельная literal-регистрация и
  старый generic branch, но намерение сохранять именно generic branch не доказано.
  Это не parameter-before-literal shadow и не повод менять runtime в рамках triage.

Для остальных пар source подтверждает разное назначение обработчиков и реальный
порядок выбора. Историческое намерение автора без прямого комментария не приписывается.
Все эти записи имеют единственный primary verdict `literal_precedes_parameter`.

## Все 109 пар

В каждой строке synthetic witness = `GET http` + указанный literal path, без query,
root_path=''. Первый FULL всего приложения совпадает с literal endpoint в колонке
«Literal / first FULL». Order: **literal → parameter**; это векторы регистрации,
а не индексы operations в raw inventory. Индексы исходной пары, точные compiled
regex обеих route, полный module endpoint, convertors, match outcomes, проверенные
предыдущие узлы и source hashes находятся в одноимённом JSON record Oxxx.
Для всех строк primary verdict `literal_precedes_parameter`; несовместимые методы,
неизвестный winner и реальные shadows не скрыты за общей таблицей.

| ID | Literal path / witness | Parameter path | Order L → P | Literal / first FULL source | Parameter source |
|---|---|---|---|---|---|
| O001 | `/api/tickets/summary` | `/api/tickets/{ticket_id}` | `[29] → [31]` | [`tickets_summary:117`](../../server/app/routers/tickets_router.py#L117) | [`ticket_details:218`](../../server/app/routers/tickets_router.py#L218) |
| O002 | `/api/tickets/schedules` | `/api/tickets/{ticket_id}` | `[30] → [31]` | [`list_schedules:187`](../../server/app/routers/tickets_router.py#L187) | [`ticket_details:218`](../../server/app/routers/tickets_router.py#L218) |
| O003 | `/api/tasks/people` | `/api/tasks/{task_id}` | `[34] → [68]` | [`list_people:898`](../../server/app/routers/tasks_router.py#L898) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O004 | `/api/tasks/projects` | `/api/tasks/{task_id}` | `[35] → [68]` | [`list_projects:942`](../../server/app/routers/tasks_router.py#L942) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O005 | `/api/tasks/versions` | `/api/tasks/{task_id}` | `[38] → [68]` | [`list_versions:1071`](../../server/app/routers/tasks_router.py#L1071) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O006 | `/api/tasks/sprints` | `/api/tasks/{task_id}` | `[42] → [68]` | [`list_sprints:1235`](../../server/app/routers/tasks_router.py#L1235) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O007 | `/api/tasks/types` | `/api/tasks/{task_id}` | `[46] → [68]` | [`list_types:1397`](../../server/app/routers/tasks_router.py#L1397) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O008 | `/api/tasks/summary` | `/api/tasks/{task_id}` | `[51] → [68]` | [`tasks_summary:1676`](../../server/app/routers/tasks_router.py#L1676) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O009 | `/api/tasks/views` | `/api/tasks/{task_id}` | `[52] → [68]` | [`list_views:1804`](../../server/app/routers/tasks_router.py#L1804) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O010 | `/api/tasks/templates` | `/api/tasks/{task_id}` | `[55] → [68]` | [`list_templates:1901`](../../server/app/routers/tasks_router.py#L1901) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O011 | `/api/tasks/recurrences` | `/api/tasks/{task_id}` | `[59] → [68]` | [`list_recurrences:2076`](../../server/app/routers/tasks_router.py#L2076) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O012 | `/api/tasks/labels` | `/api/tasks/{task_id}` | `[62] → [68]` | [`list_labels:2157`](../../server/app/routers/tasks_router.py#L2157) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O013 | `/api/tasks/assignment-counts` | `/api/tasks/{task_id}` | `[66] → [68]` | [`assignment_counts:2238`](../../server/app/routers/tasks_router.py#L2238) | [`task_details:2269`](../../server/app/routers/tasks_router.py#L2269) |
| O014 | `/api/docs/kinds` | `/api/docs/{doc_id}` | `[112] → [181]` | [`list_kinds:806`](../../server/app/routers/docs_router.py#L806) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O015 | `/api/docs/counters` | `/api/docs/{doc_id}` | `[113] → [181]` | [`list_counters:818`](../../server/app/routers/docs_router.py#L818) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O016 | `/api/docs/contract-kinds` | `/api/docs/{doc_id}` | `[117] → [181]` | [`contract_kinds:962`](../../server/app/routers/docs_router.py#L962) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O017 | `/api/docs/process-templates` | `/api/docs/{doc_id}` | `[118] → [181]` | [`list_process_templates:1008`](../../server/app/routers/docs_router.py#L1008) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O018 | `/api/docs/access` | `/api/docs/{doc_id}` | `[120] → [181]` | [`list_access_grants:1141`](../../server/app/routers/docs_router.py#L1141) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O019 | `/api/docs/duplicate-candidates` | `/api/docs/{doc_id}` | `[129] → [181]` | [`duplicate_candidates:1619`](../../server/app/routers/docs_router.py#L1619) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O020 | `/api/docs/export` | `/api/docs/{doc_id}` | `[132] → [181]` | [`export_docs:2091`](../../server/app/routers/docs_router.py#L2091) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O021 | `/api/docs/cases` | `/api/docs/{doc_id}` | `[142] → [181]` | [`list_cases:2977`](../../server/app/routers/docs_router.py#L2977) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O022 | `/api/docs/views` | `/api/docs/{doc_id}` | `[153] → [181]` | [`list_doc_views:3519`](../../server/app/routers/docs_router.py#L3519) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O023 | `/api/docs/labels` | `/api/docs/{doc_id}` | `[156] → [181]` | [`list_doc_labels:3589`](../../server/app/routers/docs_router.py#L3589) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O024 | `/api/docs/board` | `/api/docs/{doc_id}` | `[162] → [181]` | [`docs_board:3965`](../../server/app/routers/docs_router.py#L3965) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O025 | `/api/docs/substitutions` | `/api/docs/{doc_id}` | `[177] → [181]` | [`list_substitutions:5044`](../../server/app/routers/docs_router.py#L5044) | [`get_doc:5170`](../../server/app/routers/docs_router.py#L5170) |
| O026 | `/api/work/calendar/summary` | `/api/work/calendar/{event_id}` | `[196] → [203]` | [`calendar_summary:1200`](../../server/app/routers/work_router.py#L1200) | [`calendar_card:1547`](../../server/app/routers/work_router.py#L1547) |
| O027 | `/api/work/calendar/busy` | `/api/work/calendar/{event_id}` | `[197] → [203]` | [`calendar_busy:1306`](../../server/app/routers/work_router.py#L1306) | [`calendar_card:1547`](../../server/app/routers/work_router.py#L1547) |
| O028 | `/api/work/calendar/feed` | `/api/work/calendar/{event_id}` | `[198] → [203]` | [`calendar_feed_link:1388`](../../server/app/routers/work_router.py#L1388) | [`calendar_card:1547`](../../server/app/routers/work_router.py#L1547) |
| O029 | `/api/work/calendar/video-link` | `/api/work/calendar/{event_id}` | `[201] → [203]` | [`calendar_video_link:1480`](../../server/app/routers/work_router.py#L1480) | [`calendar_card:1547`](../../server/app/routers/work_router.py#L1547) |
| O030 | `/api/accounting-docs/search` | `/api/accounting-docs/{doc_id}` | `[535] → [538]` | [`search_accounting_docs:117`](../../server/app/routers/accounting_docs_router.py#L117) | [`get_accounting_doc:242`](../../server/app/routers/accounting_docs_router.py#L242) |
| O031 | `/api/accounting-docs/stats` | `/api/accounting-docs/{doc_id}` | `[536] → [538]` | [`accounting_docs_stats:178`](../../server/app/routers/accounting_docs_router.py#L178) | [`get_accounting_doc:242`](../../server/app/routers/accounting_docs_router.py#L242) |
| O032 | `/api/equipment/documents/meta` | `/api/equipment/documents/{doc_id}` | `[808] → [810]` | [`documents_meta:710`](../../server/app/routers/equipment_router.py#L710) | [`documents_get:737`](../../server/app/routers/equipment_router.py#L737) |
| O033 | `/api/equipment/spare-documents/count-sheet` | `/api/equipment/spare-documents/{doc_id}` | `[836] → [838]` | [`spare_documents_count_sheet:1474`](../../server/app/routers/equipment_router.py#L1474) | [`spare_documents_get:1502`](../../server/app/routers/equipment_router.py#L1502) |
| O034 | `/api/sites/analysis/forecast` | `/api/sites/{site_id}/forecast` | `[897] → [898]` | [`analysis_forecast:639`](../../server/app/routers/sites_router.py#L639) | [`site_forecast:649`](../../server/app/routers/sites_router.py#L649) |
| O035 | `/api/sites/overview` | `/api/sites/{site_id}` | `[863] → [903]` | [`sites_overview:67`](../../server/app/routers/sites_router.py#L67) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O036 | `/api/sites/projects` | `/api/sites/{site_id}` | `[871] → [903]` | [`list_projects:197`](../../server/app/routers/sites_router.py#L197) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O037 | `/api/sites/integrations` | `/api/sites/{site_id}` | `[884] → [903]` | [`integrations_portfolio:427`](../../server/app/routers/sites_router.py#L427) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O038 | `/api/sites/portfolio` | `/api/sites/{site_id}` | `[885] → [903]` | [`portfolio:439`](../../server/app/routers/sites_router.py#L439) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O039 | `/api/sites/tech-connections` | `/api/sites/{site_id}` | `[888] → [903]` | [`tech_connections:483`](../../server/app/routers/sites_router.py#L483) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O040 | `/api/sites/phase-durations` | `/api/sites/{site_id}` | `[889] → [903]` | [`phase_durations:498`](../../server/app/routers/sites_router.py#L498) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O041 | `/api/sites/equipment` | `/api/sites/{site_id}` | `[891] → [903]` | [`equipment_report:569`](../../server/app/routers/sites_router.py#L569) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O042 | `/api/sites/awaiting-accounting` | `/api/sites/{site_id}` | `[894] → [903]` | [`awaiting_accounting:608`](../../server/app/routers/sites_router.py#L608) | [`get_site:744`](../../server/app/routers/sites_router.py#L744) |
| O043 | `/api/sites/costs/report` | `/api/sites/{site_id}/report` | `[893] → [904]` | [`costs_report:594`](../../server/app/routers/sites_router.py#L594) | [`project_report_data:762`](../../server/app/routers/sites_router.py#L762) |
| O044 | `/api/project-workspace/unlinked` | `/api/project-workspace/{sid}` | `[949] → [951]` | [`unlinked:44`](../../server/app/routers/project_workspace_router.py#L44) | [`overview:60`](../../server/app/routers/project_workspace_router.py#L60) |
| O045 | `/api/registry/objects/open-tickets` | `/api/registry/objects/{object_id}` | `[1026] → [1027]` | [`network_open_tickets:105`](../../server/app/routers/space_registry_router.py#L105) | [`get_object:123`](../../server/app/routers/space_registry_router.py#L123) |
| O046 | `/api/store/documents/triage` | `/api/store/documents/{record_id}` | `[1228] → [1234]` | [`documents_triage:310`](../../server/app/routers/store_documents_router.py#L310) | [`document_detail:1357`](../../server/app/routers/store_documents_router.py#L1357) |
| O047 | `/api/store/documents/shifts` | `/api/store/documents/{record_id}` | `[1229] → [1234]` | [`list_document_shifts:627`](../../server/app/routers/store_documents_router.py#L627) | [`document_detail:1357`](../../server/app/routers/store_documents_router.py#L1357) |
| O048 | `/api/store/documents/recompute` | `/api/store/documents/{record_id}` | `[1230] → [1234]` | [`recompute_status:801`](../../server/app/routers/store_documents_router.py#L801) | [`document_detail:1357`](../../server/app/routers/store_documents_router.py#L1357) |
| O049 | `/api/store/receipts/duplicate-audit` | `/api/store/receipts/{receipt_id}` | `[1337] → [1339]` | [`receipt_duplicate_audit:6910`](../../server/app/routers/store_router.py#L6910) | [`get_receipt:6990`](../../server/app/routers/store_router.py#L6990) |
| O050 | `/api/store/receipts/orphan-audit` | `/api/store/receipts/{receipt_id}` | `[1338] → [1339]` | [`receipt_orphan_audit:6927`](../../server/app/routers/store_router.py#L6927) | [`get_receipt:6990`](../../server/app/routers/store_router.py#L6990) |
| O051 | `/api/store/access-policy` | `/api/store/{report}` | `[1225] → [1416]` | [`get_store_access_policy:60`](../../server/app/routers/business_access_router.py#L60) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O052 | `/api/store/documents` | `/api/store/{report}` | `[1232] → [1416]` | [`list_documents:1162`](../../server/app/routers/store_documents_router.py#L1162) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O053 | `/api/store/stations` | `/api/store/{report}` | `[1242] → [1416]` | [`store_stations:252`](../../server/app/routers/store_router.py#L252) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O054 | `/api/store/exchange` | `/api/store/{report}` | `[1243] → [1416]` | [`store_exchange:348`](../../server/app/routers/store_router.py#L348) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O055 | `/api/store/parity` | `/api/store/{report}` | `[1251] → [1416]` | [`store_parity:1421`](../../server/app/routers/store_router.py#L1421) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O056 | `/api/store/chain` | `/api/store/{report}` | `[1252] → [1416]` | [`store_chain:1439`](../../server/app/routers/store_router.py#L1439) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O057 | `/api/store/cure` | `/api/store/{report}` | `[1253] → [1416]` | [`store_cure_report:1456`](../../server/app/routers/store_router.py#L1456) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O058 | `/api/store/kkt` | `/api/store/{report}` | `[1254] → [1416]` | [`store_kkt:1472`](../../server/app/routers/store_router.py#L1472) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O059 | `/api/store/packet-revisions` | `/api/store/{report}` | `[1256] → [1416]` | [`store_packet_revisions:1666`](../../server/app/routers/store_router.py#L1666) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O060 | `/api/store/pivot` | `/api/store/{report}` | `[1259] → [1416]` | [`store_pivot:1829`](../../server/app/routers/store_router.py#L1829) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O061 | `/api/store/reports` | `/api/store/{report}` | `[1260] → [1416]` | [`store_network_reports:1887`](../../server/app/routers/store_router.py#L1887) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O062 | `/api/store/dynamics` | `/api/store/{report}` | `[1261] → [1416]` | [`store_dynamics_compare:1906`](../../server/app/routers/store_router.py#L1906) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O063 | `/api/store/baskets` | `/api/store/{report}` | `[1262] → [1416]` | [`store_baskets_analysis:1924`](../../server/app/routers/store_router.py#L1924) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O064 | `/api/store/price-mrc` | `/api/store/{report}` | `[1263] → [1416]` | [`store_price_mrc:1952`](../../server/app/routers/store_router.py#L1952) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O065 | `/api/store/price-response` | `/api/store/{report}` | `[1265] → [1416]` | [`store_price_response:1990`](../../server/app/routers/store_router.py#L1990) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O066 | `/api/store/price-log` | `/api/store/{report}` | `[1267] → [1416]` | [`store_price_log:2031`](../../server/app/routers/store_router.py#L2031) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O067 | `/api/store/price-plan` | `/api/store/{report}` | `[1269] → [1416]` | [`store_price_plan:2102`](../../server/app/routers/store_router.py#L2102) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O068 | `/api/store/storage` | `/api/store/{report}` | `[1277] → [1416]` | [`store_storage:2322`](../../server/app/routers/store_router.py#L2322) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O069 | `/api/store/station-docs` | `/api/store/{report}` | `[1279] → [1416]` | [`store_station_docs:2533`](../../server/app/routers/store_router.py#L2533) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O070 | `/api/store/cheques` | `/api/store/{report}` | `[1280] → [1416]` | [`store_cheques:2650`](../../server/app/routers/store_router.py#L2650) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O071 | `/api/store/transfers-between` | `/api/store/{report}` | `[1281] → [1416]` | [`store_transfers_between:2779`](../../server/app/routers/store_router.py#L2779) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O072 | `/api/store/station-doc` | `/api/store/{report}` | `[1282] → [1416]` | [`store_station_doc:2901`](../../server/app/routers/store_router.py#L2901) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O073 | `/api/store/doc-files` | `/api/store/{report}` | `[1284] → [1416]` | [`store_doc_files:3085`](../../server/app/routers/store_router.py#L3085) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O074 | `/api/store/agent-versions` | `/api/store/{report}` | `[1293] → [1416]` | [`store_agent_versions:3712`](../../server/app/routers/store_router.py#L3712) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O075 | `/api/store/downlink` | `/api/store/{report}` | `[1294] → [1416]` | [`store_downlink:3778`](../../server/app/routers/store_router.py#L3778) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O076 | `/api/store/network-overview` | `/api/store/{report}` | `[1299] → [1416]` | [`store_network_overview:3937`](../../server/app/routers/store_router.py#L3937) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O077 | `/api/store/cash-sync` | `/api/store/{report}` | `[1300] → [1416]` | [`store_cash_sync:4052`](../../server/app/routers/store_router.py#L4052) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O078 | `/api/store/cash-codes` | `/api/store/{report}` | `[1301] → [1416]` | [`store_cash_codes:4134`](../../server/app/routers/store_router.py#L4134) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O079 | `/api/store/cash-check` | `/api/store/{report}` | `[1302] → [1416]` | [`store_cash_check:4195`](../../server/app/routers/store_router.py#L4195) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O080 | `/api/store/station-health` | `/api/store/{report}` | `[1303] → [1416]` | [`store_station_health:4275`](../../server/app/routers/store_router.py#L4275) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O081 | `/api/store/reconcile` | `/api/store/{report}` | `[1304] → [1416]` | [`store_reconcile:4303`](../../server/app/routers/store_router.py#L4303) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O082 | `/api/store/places` | `/api/store/{report}` | `[1305] → [1416]` | [`store_places:4320`](../../server/app/routers/store_router.py#L4320) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O083 | `/api/store/matrix` | `/api/store/{report}` | `[1306] → [1416]` | [`store_matrix:4389`](../../server/app/routers/store_router.py#L4389) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O084 | `/api/store/item-locations` | `/api/store/{report}` | `[1314] → [1416]` | [`store_item_locations:4644`](../../server/app/routers/store_router.py#L4644) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O085 | `/api/store/receipts-report` | `/api/store/{report}` | `[1334] → [1416]` | [`store_receipts_report:6771`](../../server/app/routers/store_router.py#L6771) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O086 | `/api/store/receipts` | `/api/store/{report}` | `[1335] → [1416]` | [`list_receipts:6799`](../../server/app/routers/store_router.py#L6799) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O087 | `/api/store/overview` | `/api/store/{report}` | `[1345] → [1416]` | [`store_overview:7286`](../../server/app/routers/store_router.py#L7286) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O088 | `/api/store/skus` | `/api/store/{report}` | `[1346] → [1416]` | [`store_skus:7303`](../../server/app/routers/store_router.py#L7303) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O089 | `/api/store/visits` | `/api/store/{report}` | `[1347] → [1416]` | [`store_visits:7319`](../../server/app/routers/store_router.py#L7319) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O090 | `/api/store/sales` | `/api/store/{report}` | `[1348] → [1416]` | [`store_sales:7335`](../../server/app/routers/store_router.py#L7335) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O091 | `/api/store/nomenclature` | `/api/store/{report}` | `[1356] → [1416]` | [`store_nomenclature:7858`](../../server/app/routers/store_router.py#L7858) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O092 | `/api/store/stock` | `/api/store/{report}` | `[1357] → [1416]` | [`store_stock:7879`](../../server/app/routers/store_router.py#L7879) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O093 | `/api/store/inventory` | `/api/store/{report}` | `[1358] → [1416]` | [`store_inventory:7900`](../../server/app/routers/store_router.py#L7900) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O094 | `/api/store/writeoffs` | `/api/store/{report}` | `[1359] → [1416]` | [`store_writeoffs:7916`](../../server/app/routers/store_router.py#L7916) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O095 | `/api/store/transfers` | `/api/store/{report}` | `[1360] → [1416]` | [`store_transfers:7932`](../../server/app/routers/store_router.py#L7932) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O096 | `/api/store/revaluation` | `/api/store/{report}` | `[1361] → [1416]` | [`store_revaluation:7947`](../../server/app/routers/store_router.py#L7947) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O097 | `/api/store/catering` | `/api/store/{report}` | `[1362] → [1416]` | [`store_catering:7962`](../../server/app/routers/store_router.py#L7962) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O098 | `/api/store/pricing` | `/api/store/{report}` | `[1363] → [1416]` | [`store_pricing:7977`](../../server/app/routers/store_router.py#L7977) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O099 | `/api/store/assortment` | `/api/store/{report}` | `[1364] → [1416]` | [`store_assortment:7993`](../../server/app/routers/store_router.py#L7993) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O100 | `/api/store/plan` | `/api/store/{report}` | `[1367] → [1416]` | [`store_get_plan:8061`](../../server/app/routers/store_router.py#L8061) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O101 | `/api/store/plan-facts` | `/api/store/{report}` | `[1369] → [1416]` | [`store_plan_facts:8083`](../../server/app/routers/store_router.py#L8083) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O102 | `/api/store/mrc` | `/api/store/{report}` | `[1370] → [1416]` | [`store_mrc:8106`](../../server/app/routers/store_router.py#L8106) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O103 | `/api/store/shifts` | `/api/store/{report}` | `[1372] → [1416]` | [`store_shifts:8127`](../../server/app/routers/store_router.py#L8127) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O104 | `/api/store/shift` | `/api/store/{report}` | `[1373] → [1416]` | [`store_shift_detail:8141`](../../server/app/routers/store_router.py#L8141) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O105 | `/api/store/bp-package` | `/api/store/{report}` | `[1374] → [1416]` | [`store_bp_package:8151`](../../server/app/routers/store_router.py#L8151) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O106 | `/api/store/barcodes` | `/api/store/{report}` | `[1388] → [1416]` | [`store_barcodes:8813`](../../server/app/routers/store_router.py#L8813) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O107 | `/api/store/station-drafts` | `/api/store/{report}` | `[1402] → [1416]` | [`store_station_drafts:8986`](../../server/app/routers/store_router.py#L8986) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O108 | `/api/store/barcode-collisions` | `/api/store/{report}` | `[1408] → [1416]` | [`store_barcode_collisions:9175`](../../server/app/routers/store_router.py#L9175) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |
| O109 | `/api/store/contracts` | `/api/store/{report}` | `[1412] → [1416]` | [`store_contracts:9590`](../../server/app/routers/store_router.py#L9590) | [`store_report:9755`](../../server/app/routers/store_router.py#L9755) |

## Action list

1. Исправления runtime по подтверждённому shadowing literal-маршрутов **не требуются**:
   таких случаев в заданных 109 кандидатах нет.
2. Сохранить текущий приоритет literal при следующих изменениях регистрации;
   воспроизводить bounded triage при изменении source composition.
3. Отдельно, если владельцу нужен cleanup generic `store_report.receipts`, выяснить
   контракт старого generic branch; это не найденный дефект dispatch и не поручение
   на runtime-правку. Полный поиск parameter/parameter, новых динамических регистраций,
   иных compositions и endpoint acceptance остаётся за границами этого M01 slice.

## Команды и проверки

Команды выполнялись из корня отдельного дерева. Существующий exporter не изменён.
Во время этой задачи новые файлы разрешены только в двух docs и отдельно разрешённых
tool/test; общий канон/Claude memory не редактировались из-за явного whitelist задачи.
Ни один полученный registry/raw inventory не отправлялся в Git/HTTP.

```bash
git status --short --branch
git rev-parse HEAD ffab2a10
sha256sum /home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-runtime-with-ws-log-privacy.json
git diff --stat e6659c6e7adb4843cfc7a60b8a0d14373daa7026 HEAD -- clearledger/server

/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -B \
  clearledger/scripts/triage-route-overlaps.py \
  --source-revision ffab2a10d979d323ddbb0613d233ef279f566fd3 \
  --artifact /home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-runtime-with-ws-log-privacy.json \
  --artifact-sha256 5ed1476881bfb10a7647ace11dddc22e3596c58f7a0585b8d74f5be9987c901c \
  --artifact-revision e6659c6e7adb4843cfc7a60b8a0d14373daa7026 \
  > clearledger/docs/api/ROUTE_OVERLAP_TRIAGE_20261030.json

/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -B -m unittest discover \
  -s clearledger/scripts/tests -p test_route_overlap_triage.py -v
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -B -m unittest discover \
  -s clearledger/scripts/tests -p 'test_*inventory.py' -v
git diff --check
sha256sum clearledger/docs/api/ROUTE_OVERLAP_TRIAGE_20261030.json \
  clearledger/scripts/triage-route-overlaps.py clearledger/scripts/tests/test_route_overlap_triage.py
```

Первый independent parity run до создания tool импортировал существующий exporter
через `importlib.util.spec_from_file_location`, вызвал `launch_export(fullSHA)` и
в памяти проверил equality семи секций с артефактом; raw результат не сохранялся.
Повторный запуск companion tool выполнен через `subprocess.run(..., capture_output=True,
check=True)`, его stdout byte-for-byte сравнен с сохранённым bounded JSON; одновременно
проверены uniqueness, 109 counts, все source refs, два FULL и winner/order каждой пары.

| Статус | Evidence |
|---|---|
| PASS | Immutable HEAD полным SHA, исходный artifact SHA256/sourceRevision/counts/provenance |
| PASS | Независимый fresh actual export: operations/order/mounts/все 7 секций равны артефакту |
| PASS | Guarded actual triage: 109 unique pairs, 124 source endpoints, no unknown; guard denials=0 |
| PASS | Каждый literal witness FULL; parameter FULL; первая FULL всего app равна literal; все earlier routes проверены |
| PASS | Повторный bounded companion export byte-for-byte детерминирован |
| PASS | Новый pure test: 7/7, 0.003 с; ASGI/endpoint не вызывается |
| PASS | Существующий exporter suite: 19 PASS; 20 обнаруженных тестов, 1 SKIP, 1.548 с |
| PASS | Source hashes/refs всех endpoints, candidate accounting, отсутствие raw inventory в companion |
| FAIL, исправлена среда диагностики | Ранний AST-read системным Python 3.11 не разбирал существующий Python 3.12+ f-string в docs_router.py; разбор повторён Python 3.13.7, runtime не менялся |
| SKIP | Existing actual/static parity opt-in unittest: не задан RUN_CORE_RUNTIME_INVENTORY_TESTS/static JSON; вместо него fresh actual registry parity и отдельный triage выполнены явно |
| SKIP | Endpoint/HTTP dispatch/валидация request/ACL, startup/lifespan/OpenAPI, SQL/сеть, полная security/load проверка и production composition |

Исходный артефакт имеет прежний provenance; текущий запуск доказывает регистрацию
выбранной source composition на immutable expected. Partner flags=false не доказывают
остальные конфигурации. Наличие response/handler в registry не доказывает его исполнение.
Host/custom routes, middleware-generated OPTIONS/redirects, gateway/root_path иных
композиций, static/proxy dispatch и runtime-регистрации после startup не принимались.
В actual дереве unresolved=0; pure controls проверяют только заявленные правила match.
CPython audit guards не заявляются песочницей против произвольного вредоносного native code.

## Хеши готовых bounded материалов

- `clearledger/docs/api/ROUTE_OVERLAP_TRIAGE_20261030.json`: SHA256 `f9555b8a8bb467f5674e05ad57971474e62b5fb888f52226b4321d219dd4fd27`.
- `clearledger/scripts/triage-route-overlaps.py`: SHA256 `f29e6c4212c986e102ed1adf2140e93276aecda31ecfd4a97da3e6a551e0fd6d`.
- `clearledger/scripts/tests/test_route_overlap_triage.py`: SHA256 `0db21184b3f338c2b54d4af6d21698111409ee5e600129b5fa2773f80175aa84`.
