# Первые партнёрские приложения РусГидро: применимость API

**Вывод:** кандидат позволяет сотруднику читать разрешённые объекты, оборудование, контрагентов, договоры и документы, а также получать сессионные агрегаты мониторинга. Он пока не позволяет внешнему приложению провести подтверждённую связь выбранного договора с ЭЗС или найти именно бумаги этого договора. Самостоятельное ведение договоров, загрузка файлов и согласование через партнёрский API отсутствуют.

Следующий ограниченный пакет рекомендуется посвятить **чтению явных связей «договор → доступные ЭЗС»**. Это общий необходимый шаг обоих приложений. Первый необходимый write не подтверждён; данный анализ не разрешает включать запись или feature flags. Наличие внутреннего use case создания договора не устраняет отдельную задачу партнёрского допуска.

## Снимок и смысл статусов

Неизменный источник Ledger/app: **`07f12c6575cbb397e9945c7f9efda724445615c2`**. Анализ выполнен на новой ветке `agent/api-partner-readiness-20261030`, созданной именно от этого коммита; исходники приложения не изменялись. Программа и предметный канон прочитаны в отдельном дереве ecosystem-deploy на **`dde050c8a4a952f3785a44f5650f19a1bd9d7f58`**. Его ветка и существующие untracked `__pycache__` не менялись. Новый отчёт не является снимком работающего пространства.

[Парный JSON](PARTNER_APPLICATION_READINESS_20261030.json) содержит точные пути, символы, строки, Git blob SHA и SHA-256 всех цитируемых источников, 12 операций и 16 действий. Ссылки вида `query.Query.conditions` обозначают ключ `sourceRefs` в JSON; полные хеши относятся к исходному коммиту, не к будущему коммиту документа. Для каждого source pin проверено побайтовое равенство рабочего файла Git blob. Канон поставки используется только для предметного смысла; рабочие данные и примеры из него сюда не переносились.

| Статус | Значение |
|---|---|
| `exists_external` | Реализован внешний candidate-контракт; это не утверждение о его включении или приёмке реального партнёра |
| `current_native_only` | Нужное действие существует у Core с native user/session policy; partner access token не превращает его в публичный API |
| `missing` | Нужной внешней операции или проекции в текущем curated-контракте нет |
| `needs_product_choice` | Требование к приложению ещё не выбрано; предлагаемое действие не считается поручением на реализацию |

Readiness двух приложений не равна завершению M00–M19. Принятые карты `RUNTIME_API_INVENTORY`, `CONTRACT_WRITER_INVENTORY`, `OBJECT_LIFECYCLE_WRITERS` и consumer inventory использованы на их исторических pins; полный аудит 1703 операций не повторялся. Уточнялись только применимые call chains. Топливные пути ГИГ не включались как доказательство готовности РусГидро.

## Фактическая внешняя поверхность: 12 GET

Во всех строках статус `exists_external`, доступность **candidate/default-off**. Полный путь включает mount `/api/v1`. `U` означает delegated partner user access token, полученный Code+PKCE; `S` означает отдельный partner machine access token. Это разные principals, а не два способа выдать сотруднику одинаковый доступ. `C/O/E/P/D/M` ниже обозначают точные пределы доступа.

| Method/path | operationId | Scopes | Tokens / предел | Source pin |
|---|---|---|---|---|
| GET `/api/v1/objects` | `listObjects` | `objects:read` | U/S / O | [objects:137](../../server/app/product_api/app.py#L137), blob `17fe2e15ce3e` |
| GET `/api/v1/objects/{objectId}` | `getObject` | `objects:read` | U/S / O | [object_detail:141](../../server/app/product_api/app.py#L141), blob `17fe2e15ce3e` |
| GET `/api/v1/objects/{objectId}/monitoring` | `getObjectMonitoring` | `objects:read`, `monitoring:read` | U/S / M | [object_monitoring:145](../../server/app/product_api/app.py#L145), blob `17fe2e15ce3e` |
| GET `/api/v1/equipment` | `listEquipment` | `equipment:read` | U/S / E | [equipment:155](../../server/app/product_api/app.py#L155), blob `17fe2e15ce3e` |
| GET `/api/v1/equipment/{equipmentId}` | `getEquipment` | `equipment:read` | U/S / E | [equipment_detail:159](../../server/app/product_api/app.py#L159), blob `17fe2e15ce3e` |
| GET `/api/v1/counterparties` | `listCounterparties` | `counterparties:read` | U/S / P | [counterparties:163](../../server/app/product_api/app.py#L163), blob `17fe2e15ce3e` |
| GET `/api/v1/counterparties/{counterpartyId}` | `getCounterparty` | `counterparties:read` | U/S / P | [counterparty_detail:167](../../server/app/product_api/app.py#L167), blob `17fe2e15ce3e` |
| GET `/api/v1/contracts` | `listContracts` | `contracts:read` | U/S / C | [contracts:171](../../server/app/product_api/app.py#L171), blob `17fe2e15ce3e` |
| GET `/api/v1/contracts/{contractId}` | `getContract` | `contracts:read` | U/S / C | [contract_detail:175](../../server/app/product_api/app.py#L175), blob `17fe2e15ce3e` |
| GET `/api/v1/documents` | `listDocuments` | `documents:read` | U / D | [documents:179](../../server/app/product_api/app.py#L179), blob `17fe2e15ce3e` |
| GET `/api/v1/documents/{docId}` | `getDocument` | `documents:read` | U / D | [document_detail:183](../../server/app/product_api/app.py#L183), blob `17fe2e15ce3e` |
| GET `/api/v1/documents/{docId}/versions/{versionId}/content` | `downloadDocumentVersion` | `documents:read`, `documents.files:download` | U / D | [document_content:196](../../server/app/product_api/app.py#L196), blob `17fe2e15ce3e` |

Callable owner всех строк: вложенный handler `app.product_api.app.create_product_api.<имя>` из указанного pin. Для списков/деталей он вызывает общий `Query`; мониторинг вызывает `product_api.monitoring.detail`, content вызывает `product_api.files.content`. Полные имена и отдельные source refs есть в JSON. Итого **шесть доменных групп, девять U/S и три только U**, без внешних write-операций. OAuth и portal не добавляются к этим 12 предметным GET.

### Tenant, самостоятельные grants и текущие права

Общий предел `T`: tenant берётся только из verified token. Живые client, installation, grant, family/credential и membership проверяются заново; scopes пересекаются с разрешёнными клиенту, установке и grant. Подмена компании заголовком/query/path не расширяет доступ. Для каждого предметного ресурса нужен **его собственный** typed grant `ALL/SET/EMPTY`; отсутствующий/пустой grant даёт 403 до предметного запроса. Ограничение объектов пользователя пересекается с installation/location ceiling; `None` и сохранённый пустой список имеют разный смысл. Собственная организация также пересекается; конфликт контекста даёт отказ. Admin/superadmin не расширяет узкий grant партнёра. Источники: `identity.live_grant`, `identity.resource_scopes`, `access.resolve`, `api._policy`.

| Предел | Что добавляется к `T` |
|---|---|
| `O`, objects | Typed `objects` grant, текущий object ceiling, при own-org ограничении совместимый location-scoped договор. В `Query.conditions` **нет** population-фильтра `ev_charging`, `is_test` или `closed` |
| `E`, equipment | Typed `equipment` grant, `kind=station`, текущий `current_location_id` внутри object ceiling/own-org. Поле `objectId` выдаётся лишь при самостоятельном видимом `objects` scope/grant; иначе null |
| `C`, contracts | Typed `contracts` grant, own organization. При ограниченном object ceiling требуются `scope_type=locations` и хотя бы одна совместимая `ContractLocation`; company/unassigned не превращаются в ALL. `counterpartyId` требует самостоятельной видимости контрагента |
| `P`, counterparties | Typed `counterparties` grant, исключение групп. При object/own-org ограничении нужен совместимый договор через `contract_domain`; одного object grant недостаточно |
| `D`, documents | Только настоящий delegated User, текущий доступ к продукту docs/роли, typed `documents` grant, native readable ACL, object/own-org predicates. Content требует ещё download scope, native download ACL и цепочку company → DocCard → DocVersion → SourceFile |
| `M`, monitoring | `O`, оба scopes `objects:read` и `monitoring:read`, профиль компании `energy` до агрегации. Boundary и агрегаты ограничены конкретным разрешённым объектом |

Фильтры/ACL применяются до count/limit; скрытые связи DTO становятся null. Это не разрешение клиенту вычислять скрытые ID из native endpoints. Content консервативно отказывает для SourceFile, связанного также с task/chat/conf/store; native download не используется как обход. Источники: `query.Query.conditions`, `query.Query.project`, `files.content`, `docpolicy._readable_doc_clause`.

У `/objects` ID обозначает **точку обслуживания**, у `/equipment` только станционную единицу. Площадка/site, EVSE и connector не опубликованы. Канон пяти уровней (`canon.objects`, §1) не позволяет назвать servicePoint земельным участком или оборудованием. Для минимального пилота допустима явно выбранная установка с известным SET точек; общий список сам по себе не подтверждает состав действующего парка ЭЗС.

### Поиск и связи: существенные ограничения

`q` ищет **имя** объекта, **серийный номер** оборудования, **имя** контрагента, **номер** договора или **заголовок** документа. Он не является поиском по ИНН/КПП, объекту договора, юридическому виду, `subject_ref` или всем реквизитам. Общие `dateFrom/dateTo` фильтруют `created_at` в UTC, а не дату заключения/юридического действия договора. Известные ID можно читать отдельно; передать `counterpartyId`, `objectId` или `contractId` как незадокументированный list filter нельзя: unknown query отклоняется. Источники: `search`, `query.Query.listing`, `dto.ListQuery`.

Публичный `Contract`: только `id, number, date, title, isClosed, scopeType, counterpartyId`. Нет `organizationId`, type/kind/typeCode, сроков, условий, location IDs, document IDs или статуса согласования. `Document` содержит видимые `objectId/counterpartyId`, но не `contractId/subject_ref/relations`. Совпадение контрагента/названия документа не доказывает принадлежность конкретному договору. Деталь документа перечисляет только current, не tombstoned/purged versions, максимум 200 с `versionsTruncated`; это не полный исторический каталог редакций. Источники: `dto.Contract`, `dto.Document`, `api.create_product_api`, `query.Query.project`.

## Сценарий A: аренда и электроснабжение площадки

| Действие сотрудника | Статус и доступный путь | Следствие для первого приложения |
|---|---|---|
| Войти, выбрать компанию, подтвердить действия | `exists_external`: GET authorize → consent → POST token, Code+PKCE; `oauth.*`, `identity.eligible_scopes` | Для references нужны текущий модуль references и согласованные `contracts:read/counterparties:read`; для объектов equipment, для документов docs. Собственные роли пространства участвуют в расчёте |
| Выбрать доступную ЭЗС и оборудование | `exists_external`: `listObjects/getObject/listEquipment/getEquipment`, O/E | Не отождествлять точку обслуживания с площадкой и станцией; тип/состав текущей выборки оговорить |
| Найти контрагента и номер договора | `exists_external`: `listCounterparties/getCounterparty/listContracts/getContract`, P/C | Можно просматривать доступный минимальный паспорт. Нельзя обещать список «все договоры аренды этого объекта» по этим DTO |
| Проверить связь договора с ЭЗС | `current_native_only`: GET `/api/references/contracts/{item_id}/locations` | Партнёрский GET отсутствует; именно этот разрыв закрывает NEXT-R1 |
| Найти бумаги именно этого договора | `missing`: публичного relation/query нет | Общий список docs не заменяет доказуемую contract→DocCard связь; отдельный следующий read-пакет |
| Открыть доступный документ и скачать файл | `exists_external`: три документные GET, D | Для чтения файла отдельно `documents.files:download`; разрешения компании/роли/документа/файла должны одновременно пройти |
| Создать/исправить паспорт, контрагента или объектную привязку | `current_native_only`, **предлагаемый сценарий** | Native CREATE/PATCH/link endpoints перечислены ниже; внешний write, поля и actor ещё не выбраны |
| Загрузить договор/скан, зарегистрировать, отправить и решить согласование | `current_native_only`, **предлагаемый сценарий** | Это lifecycle DocCard/версий/approval, отдельно от паспорта Contract; file_store не является партнёрским upload API |
| Отозвать своё подключение, сменить доступ сотруднику | OAuth revoke `exists_external`; управление membership/install/grants только Core admin | Следующий GET должен заново проверить доступ; ранее скачанные байты отозвать невозможно |

Канон `canon.economy`, §«Две стороны одного дела»: договорные ожидания, первичка и кассовый факт различаются; инженерный мониторинг не даёт прав на деньги. Привязка бумаги или согласование сами по себе не меняют условия начисления. `contract_usage` подтверждает несколько разных ссылок на Contract, включая DocCard `subject_ref`, DocRelation и attrs; этот внутренний обход использования не является безопасной внешней проекцией.

## Сценарий B: эксплуатация ЭЗС и мониторинг

| Действие | Статус / конкретный вызов | Что приложение вправе показать |
|---|---|---|
| Вход сотрудника и выбор объектов/станций | Те же U flow и четыре O/E GET | Только разрешённые текущие карточки, с независимыми resource grants |
| Посмотреть состояние выбранной точки | `exists_external`: `getObjectMonitoring`, M | Текущий operational status, наблюдаемая граница источника, sessions/visits/successfulVisits/energy; без финансов, PII, сырых сессий и tickets |
| Найти контрагента/договор и подтвердить привязку | P/C GET есть; contract→objects `current_native_only` | Та же общая связь нужна инженеру и менеджеру; не строить её из совпадения адресов или названий |
| Прочитать инструкцию/акт/файл | Три D GET при user grant и docs роли | Документная часть недоступна machine principal даже при machine мониторинге |
| Записать осмотр, приложить фото, изменить обслуживание | `current_native_only`, **предлагаемый сценарий** | Native station-check/upkeep существуют, публичных операций/скоупов нет |
| Заявка на ремонт, alarm/live OCPP, история размещения, EVSE/connector | `needs_product_choice`; такого curated-контракта нет | Если это цель запуска, нужны отдельные контракты владельцев; слово «мониторинг» не подтверждает эти требования |
| Изменение/отзыв доступа | Тот же live verifier и OAuth revoke | Смена ceiling должна сузить следующий ответ; старый cursor при rebinding не продолжает прежнюю выборку |

Мониторинг использует общее `ops_monitor_context`: успех визита определяется хотя бы одной попыткой `energy_kwh > 0`, raw энергия суммируется до округления. `days=1..366`, окно `[asOf − days × 24 часа, asOf]`, МСК; `asOf` ограничивает сессии концом дня либо более ранней наблюдаемой границей. `dataThrough` не доказывает полноту загрузки, `dataLagHours` относится к текущему времени. Статус/каталог остаются текущими даже при историческом `asOf`; нет historical passport/retirement ledger. Источники: `monitor.detail`, `metrics.monitor_context`, `metrics.visit_summary`, `report.monitorproof`.

## Владельцы native действий и существующие общие use cases

Следующая таблица описывает **native Core**, не публичную партнёрскую поверхность. Во всех строках token class — Core user session, partner scopes отсутствуют. Явный стабильный curated `operationId` для них **не задан**: JSON хранит `operationId=null` с причиной; автоматически вычисленный native OpenAPI ID здесь не угадывается и не обещается внешнему клиенту. Точный callable, строки/blobSHA и per-action ceiling закреплены в JSON.

| Native method/path | Callable owner / действующая граница | Доказательство |
|---|---|---|
| POST `/api/references/contracts` | `references_router.create_contract` → `native_contract_commands.create_native_contract`; настоящий User, `assert_company_member`, same-company стороны/type, identity/replay barrier; flush, commit/rollback у caller/get_db | `native.create_contract`, `nativecase.create_native_contract`; принятые 59 native-проверок, не partner write |
| PATCH `/api/references/contracts/{item_id}` | `references_router.update_contract`; прежние допуск, lock/reload, manual override/null rules | `native.update_contract`; historical PATCH/import characterisation в принятой карте, нового прогона нет |
| POST `/api/references/counterparties`, PATCH `/api/references/counterparties/{item_id}` | `create_counterparty/update_counterparty`; member/owned row, identity uniqueness, manual fields. Проверка verified отдельная | `native.create_counterparty/update_counterparty`; import commands не заменяют native policy |
| GET `/api/references/contracts/{item_id}/locations` | `get_contract_locations`; native company member, join ContractLocation; нет partner grants/DTO projection | `native.get_contract_locations`; здесь только код, без новой runtime/ACL-приёмки |
| PUT `/api/references/contracts/{item_id}/scope` | `set_contract_scope`; company/locations/unassigned, same-company locations, перестройка связей | `native.set_contract_scope`; нельзя напрямую переиспользовать как partner write policy |
| POST/DELETE `/api/references/contracts/{item_id}/locations/{loc_id}` | `link_contract_location/unlink_contract_location`; member, same-company link; company scope не превращается в locations молча, последняя отвязка → unassigned | Соответствующие `native.*`; не новое внешнее разрешение |
| POST `/api/docs` | `docs_router.create_doc`; docs product, reference validation, настоящий author, router commit | `docs.create_doc`; отдельно DocCard, не Contract |
| POST `/api/docs/{doc_id}/versions` | `upload_version`; docs+edit ACL до/после lock, lifecycle/approval/retention/file guards; `file_store.put`, router commit | `docs.upload_version`, `writer.put`; policy/writer acceptance относится к своим pins |
| POST `/api/docs/{doc_id}/approval/start` и `/api/docs/approvals/{approval_id}` | `approval_start/approval_decide` → `doc_approvals.start/decide`; route snapshot, action ACL, назначенный actor/deputy, row/round locks, router commit | `docs.approval_start/approval_decide`, `docflow.*`; public approve отсутствует |
| POST `/api/ops/station-check/{location_id}` | `post_station_check` → `station_check.add_check`; native membership, helper same-company location, общий file writer, router commit | `ops.post_station_check`, `checks.add_check`; partner/object policy этим не подтверждена |
| PUT `/api/ops/station-upkeep/{location_id}` | `put_station_upkeep` → `station_upkeep.set_upkeep`; membership, unit company/current_location, router commit | `ops.put_station_upkeep`, `upkeep.*`; null здесь пропускается, пустая строка очищает, не переносить это на общий PATCH |

Общие импортные команды уже существуют: `contract_commands.create_imported_contract` выполняет constructor/add/flush и лишь затем публикует запись в ContractIndex; `counterparty_commands` владеет импортным CREATE/alias. Caller сохраняет matcher, raw, стороны, компанию, ACL, locks, связи, статистику и транзакцию. Три Contract producer включают два реестровых пути, применимых к РусГидро; corporate path не выдаётся за нужную функцию аренды. Импортные commands принимают уже допущенные значения, не являются authorization use case для нового партнёра.

Принятый `create_native_contract` принимает `ContractCreate` и настоящий `User`, включая `company_id` и native replay actor. Передать partner principal как фиктивный User или подставить tenant из тела было бы новым поведением. Модель Contract имеет `is_closed`, но **не имеет draft lifecycle DocCard**. Поэтому рекомендация «просто открыть draft-only Contract CREATE» без продуктового определения черновика некорректна. CREATE, PATCH, scope/link, бумага, upload, условия, approval и исполнение процесса требуют раздельных решений и пакетов. Источники: `schema.ContractCreate`, `models.Contract`, `nativecase.create_native_contract`, `importcase.create_imported_contract`, `usage.contract_usage`.

## Пять функциональных препятствий запуску

Это максимум пять приоритетов, а не требование закончить всю модернизацию перед любым чтением.

| Приоритет | Что блокирует | Что делать |
|---|---|---|
| G1 | Доказуемый путь договор → ЭЗС → бумаги договора | Сначала NEXT-R1 для явных объектов; затем отдельная безопасная contract→DocCard проекция. Не выдавать общий docs search за связь |
| G2 | Автоматический предметный отбор аренды/электроснабжения и их реквизитов | Выбрать необходимый public allowlist классификации/сроков/собственной организации; текущий паспорт этого не содержит |
| G3 | Самостоятельное ведение договора партнёром, **если это цель запуска** | Утвердить первый write и actor, затем shared policy/usecase; native CRUD/upload/approval не публиковать автоматически |
| G4 | Расширенная эксплуатация, **если нужны** site/EVSE/connector, alarms, tickets или хозяйство | Зафиксировать цель первого приложения; сессионный мониторинг уже доступен кандидатом, расширение отдельное |
| G5 | Реальный внешний запуск даже минимального чтения | Отдельная приёмка выбранного release/spec, onboarding обычных сотрудников, grants/отзыв, callback и BFF/CORS, доступность нужных файлов. Локальные synthetic PASS её не заменяют |

## NEXT-R1: ограниченный следующий пакет реализации

**Предложение к реализации, не существующая операция и не разрешение на активацию.** Добавить один GET `/api/v1/contracts/{contractId}/objects`, `operationId=listContractObjects`. Цель: показать только **явные текущие связи** выбранного доступного договора с независимо доступными точками обслуживания. Это ещё не полный юридический охват площадки и не привязка бумаги.

### Actor, поля и переиспользование

- Scopes строго **`contracts:read` AND `objects:read`**. Допускаются те же U и отдельно утверждённый S, что у существующих contract/object GET. Машина не получает User или docs роль. Новых OAuth scopes, write grants и автоматического расширения installations нет.
- Request allowlist: path `contractId` по текущему `dto.Id`; query только `pageSize` 1..200/default50 и `cursor` bounded как текущий list cursor. Body отсутствует; unknown query/body отклонять. Нет `companyId`, object selector, `q`, дат или флага «показать скрытые».
- Response allowlist: **`contractId, scopeType, items[].objectId, total, nextCursor`**. `objectId` использует существующий opaque ObjectId без trim/remapping. Имена и оборудование читать уже существующими GET. Нет raw, notes, внутренних relation IDs, скрытых IDs/counts, organization или документов.
- Переиспользовать **`Query.detail("contracts", contractId)` и `Query.conditions("objects")`**: это существующий общий read use case, которому уже подчиняются list/detail/count и DTO links. Отношение выбрать через same-tenant `ContractLocation` с разрешённым Contract.id; count/пагинацию строить по **distinct видимым объектам** с теми же predicates до count/limit. Оба scopes и оба resource grants проверять в отдельном bounded admission до любого domain/detail/relation SQL; policy ресурса contracts не проверяет objects grant автоматически. EMPTY objects не превращается в успешный пустой ответ.
- Если нужен новый callable, его владелец — текущий `product_api.queries.Query`, например `contract_objects`; handler остаётся тонким. Не вызывать `references_router.get_contract_locations`, `_location_brief`, `contract_usage` или HTTP handler из service. Native endpoint сохраняет прежнее поведение и не получает новый внешний DTO. Generic all-domain repository не требуется.
- `scopeType=locations` выдаёт видимые явные связи. Для company/unassigned вернуть пустой набор **явных** связей и тот же scopeType; не разворачивать company на всю сеть и не сообщать, будто договор юридически не действует на объект. При ограниченном employee ceiling такой договор может быть недоступен уже по прежнему contract policy.
- Не выполнять flush/commit, materialize, hooks или запись в business tables; управление read session остаётся у `query_dependency`. Обычные auth/quota transitions учитывать отдельно. Все прежние native handlers, 12 GET, auth semantics и transaction owners сохраняются.

### Повтор, конфликты и null-intent

GET повторяем без business side effects; `creationKey` и Idempotency-Key ему не нужны. Это live pagination, не снимок отношений на дату. Порядок — текущий стабильный object `(created_at,id)`; relation predicate применяется к нему до limit. Переиспользовать существующий HMAC cursor primitive, но **новое binding должно включать contractId и relation kind**, а также tenant, actor/client/install/grant, scopes, оба typed grants, object/own-org ceilings и page size. Между договорами cursor не переносится. Любой rebinding даёт безопасный 400; auth denial имеет прежний приоритет. Оптимистический 409 конфликта записи здесь не нужен.

Записываемых nullable полей нет: null не очищает связь. Пропущенный cursor означает первую страницу; строка `cursor=null` не является null, даёт invalid cursor. Пустой `items` означает «нет доступных явных связей» и не различает отсутствие связей от полностью скрытых связей. В `total` считаются только видимые объекты; скрытого общего счётчика нет. История размещения и действующие на дату юридические отношения этим пакетом не обещаются.

### Обязательная отрицательная матрица и приёмка

| Проверка в отдельной синтетической среде будущего владельца | Ожидание |
|---|---|
| Нет Bearer; вместо него Core/ID token/docs cookie | 401, без relationship data |
| Нет любого из двух OAuth scopes | 403 до предметной выборки |
| `contracts` EMPTY или `objects` EMPTY | 403 до relation query, включая admin |
| Чужой/отсутствующий/не входящий в contracts SET договор | Одинаковый 404 |
| Договор видим, часть связанных объектов вне objects SET/employee ceiling | 200; только разрешённые ID и только их total |
| Две компании, две own organizations; чужая/несогласованная ContractLocation.company | Ни чужих IDs/counts, ни расширения own-org; некорректный контекст 403 / недоступная карточка 404 |
| Admin с узким partner SET; ordinary employee с одним объектом | Нет расширения до company ALL |
| Machine grant с обоими read scopes и grants | Те же независимые ceilings; документы всё ещё запрещены |
| Cursor от другого договора/tenant/grant/page size или после сужения ceiling | Safe400; не продолжает прежнюю выборку |
| Отзыв user membership/grant/install/client; machine credential revoke | Следующий GET отказывает с прежней verifier semantics |
| Company/unassigned доступный договор | Пустые явные связи, исходный scopeType; никакого implicit ALL |
| Disabled flags; неизвестные query/body; равные timestamps; несколько страниц | 503 до data queries; 422/валидатор body; стабильный tie breaker без дублей/потерь на неизменных данных |

Приёмка должна вызвать настоящий HTTP handler/shared Query/SQL predicates, проверить список/detail/total по явному synthetic golden и независимым before/after fingerprints business rows/files; auth/quota state оценивать отдельно. Не вычислять expected результат копией Query. Подтвердить unchanged native semantics и отсутствие service→router imports. Проверить текущие 12 operations и новую отдельно, затем canonical server schema, browser projection, официальный codegen/freshness/consumer и negative drift. **Только после реализации** ожидаются 13 GET, 10 U/S + 3 U-docs; сейчас актуальные числа остаются 12, 9+3. Новая схема, examples и критерии ниже пока только design, runtime acceptance не выполнена.

Вне пакета: Contract/Counterparty CRUD, document relations/create/upload/approve, условия и начисления, деньги, заявки, object lifecycle, новые уровни оборудования, включение flags, deploy и реальный пилот.

### API examples для разработчика

Все значения вымышлены. Следующие shell-команды можно выполнить **в отдельной одобренной песочнице разработчика после штатного Code+PKCE**, когда BASE и ACCESS_TOKEN уже безопасно заданы в его сессии. Они здесь не исполнялись; секреты в URL или аргумент тела не добавляются. Для пользователя требуются отдельные scopes/grants каждого вызова. `q` в contract query означает номер, не объект.

```sh
: "${BASE:?HTTPS origin выданной песочницы без завершающего /}"
: "${ACCESS_TOKEN:?partner user access token после Code+PKCE}"
curl --fail-with-body -sS "$BASE/api/v1/objects?pageSize=50" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl --fail-with-body -sS --get "$BASE/api/v1/counterparties" \
  --data-urlencode 'q=Пример Энергия' -H "Authorization: Bearer $ACCESS_TOKEN"
curl --fail-with-body -sS --get "$BASE/api/v1/contracts" \
  --data-urlencode 'q=DEMO-2026-001' -H "Authorization: Bearer $ACCESS_TOKEN"
curl --fail-with-body -sS "$BASE/api/v1/objects/synthetic-point/monitoring?days=2&asOf=2026-10-16" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

**Только дизайн NEXT-R1:** после его будущей реализации и создания вымышленной fixture с указанными ID:

```sh
curl --fail-with-body -sS \
  "$BASE/api/v1/contracts/00000000-0000-4000-8000-000000000101/objects?pageSize=50" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
{
  "contractId": "00000000-0000-4000-8000-000000000101",
  "scopeType": "locations",
  "items": [{"objectId": "synthetic-point"}],
  "total": 1,
  "nextCursor": null
}
```

Например, второй связанный объект скрыт обоими grant/employee ceilings: он отсутствует и в items, и в total. При чужом договоре — 404; при отсутствии objects scope — 403; попытка `?companyId=...` — 422. Текст и requestId конкретной ошибки генерирует существующий Problem handler; примеры не притворяются сохранёнными runtime responses.

Для уже доступного **независимо найденного** документа можно получить current versions и content; UUID ниже тоже fixture, не способ найти бумаги договора:

```sh
curl --fail-with-body -sS \
  "$BASE/api/v1/documents/00000000-0000-4000-8000-000000000201" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
# versionId берётся из разрешённого ответа, нужен дополнительный download scope.
curl --fail-with-body -sS \
  "$BASE/api/v1/documents/00000000-0000-4000-8000-000000000201/versions/00000000-0000-4000-8000-000000000301/content" \
  -H "Authorization: Bearer $ACCESS_TOKEN" --output ./synthetic-document.bin
```

## Подключение, отзыв и минимальный пилот без записи

Внешнее приложение проходит GET `/api/oauth2/authorize` с `openid`, нужными business scopes, state/nonce и S256; consent выбирает company/installation. POST `/api/oauth2/token` меняет code+verifier на partner access token. `offline_access` требуется только если выбрано обновление; rotating refresh сериализовать. Контекст сотрудника выводится из текущего UserCompany/CompanyRole, не из client-supplied actor/company. В JSON для протокольных endpoints `operationId=null`: это OAuth protocol, за пределами curated business operationId registry, с точным owner `partner_oauth_router.authorize/token/revoke`.

Отдельный confidential server client использует POST `/api/oauth2/token`, `client_credentials`, явный `grant_id`, `client_secret_basic`; он не получает User, ID/refresh token или document scopes. Нельзя подменять им сотрудника или docs роль. Core административные DELETE `/api/developer/grants/{grant_id}`, `/api/developer/installations/{installation_id}`, `/api/developer/clients/{client_id}/credentials/{credential_id}` принадлежат `partner_admin_router` и требуют Core user/admin policy, а не business access token. Сам OAuth POST `/api/oauth2/revoke` существует для клиента; изменения membership/scopes/resources проводят их владельцы в Core. `live_grant` и product resolver перечитывают ограничения на следующем запросе; приложение сбрасывает старый cursor/кеш при отказе и не показывает прежние данные как текущие.

Swagger `/developer/api` требует отдельную docs сессию и `docs:read`; вход туда не выдаёт business access. Canonical `/api/developer/docs/openapi.server.json` содержит `ProductOAuth` и `ProductServiceOAuth`; `/api/developer/docs/openapi.json` только browser Code+PKCE projection. В браузер секрет confidential client не вводится. Три document операции не получают service alternative. Flags OAuth/API/docs/quota в исходниках выключены. Рабочие настройки не читались.

Минимальный **read-only пилот уже текущего кандидата**, без NEXT-R1: два зарегистрированных приложения или заранее согласованный один client, ordinary employee с явными модулями references/equipment/docs и ops для monitoring; отдельные ограниченные installations/resource SET. Приложение A показывает независимо выбранный паспорт контрагента/договора и доступный документ, **без утверждения связи с выбранной ЭЗС/договором**. Приложение B показывает разрешённые точки/station equipment и текущий статус с provenance/зарядными агрегатами. Независимый документ можно открыть только по настоящему user grant. Никаких create/update/upload/approve, обхода на native routes или имитации успешного сохранения. Это сокращённый просмотр, а не приёмка полного сценария аренды; если главное условие пилота — провести связь договор↔ЭЗС, сначала нужен NEXT-R1.

Технически остаются выбранный sandbox/release, точная server spec, callback registration, OAuth verifier/audience и grants, поведение отзывов и HTTP ошибок. Quickstart указывает same-origin CORS; внешний UI может идти через свой сервер/BFF. Прямой browser cross-origin требует отдельной конфигурации/приёмки. Пилот, callback/CORS и административные изменения в этой задаче не выполнялись.

Продуктовые решения для МАГа/ROOT, отдельно от техники: (1) достаточно ли первому показу текущих связей точек, или обязательна юридическая площадка/site и история; (2) какие реквизиты отличают аренду/электроснабжение и обязательно ли сразу видеть бумаги договора; (3) какое **одно** действие партнёр должен первым сохранять и кому оно разрешено; (4) достаточно ли сессионного мониторинга без repair tickets/live alarms. Ответы не предполагаются. Технические решения NEXT-R1 — два scope/grant, fail-closed SQL пересечение, явные связи, cursor binding и сохранение transaction owners — сформулированы выше и не требуют придумывать бизнес-процесс.

## Доказательства и пределы проверки

| Что уже принято в прежних отчётах | Точный смысл для этой карты |
|---|---|
| Product: первоначальные 147; интеграционные 296 на своих исходных составах | Подтверждают прежние synthetic HTTP/SQL predicates; не новый прогон 12 operations на текущем HEAD |
| Monitoring: source `9a4a5aee` + `c0f94af2`, 38 PASS, затем отдельные 115 PASS и 10 subtests | Реальные synthetic Code+PKCE/machine, scope/window/revoke проверки, разные серии |
| Main composition: corrective `79daf4c6a8d8e149fea912012fd4f1847351af34` | исходные 7: 5 PASS / 2 FAIL, повтор затронутых 3: 3 PASS; ordinary employee scoped flow, docs-role denial/positive и machine covered; не единый прогон всех 8. nginx/browserSSO/production jobs подменены/вне границы |
| Native CREATE `1cd272c6`, 59 PASS | Настоящие native HTTP/SQL replay/party/lock/rollback, не разрешение partner CREATE |
| Import CREATE `92620919`, исправленные 35 PASS после первых 68 PASS / 1 oracle FAIL | Сохранение producer semantics/caller transaction; не общий внешний contract use case |
| Document policy/read/file writer на своих frozen pins | 222 policy-проверки: 138 прежних + 84 новых; позже отдельные 8 read equivalence и 119 writer/archive, 2 photo HTTP. Не суммируются в новый общий CI |
| Codegen/quickstart/service profiles | Проверены прежние accepted материалы, декларации текущего `.d.ts`, exporter и canonical/browser code. Fresh generation/freshness/typecheck на текущем source **не запускались** |

Все эти наблюдения взяты из закреплённых public reports (`acceptedProofs` в JSON), без нового исполнения и без независимого чтения сырых execution artifacts этим worker. Старый product-read документ описывает 11 routes до добавления мониторинга; для текущего числа использованы **12 actual AST route declarations**, текущий shared policy и canonical/browser exporters. Generated types содержат текущие operation names, но их наличие не считается доказательством runtime или freshness. Swagger login, зелёный unit и synthetic клиент не являются реальным пилотом двух приложений.

В этой задаче выполнены: read-only чтение исходников/принятых карт; AST-разбор Python 3.13; извлечение ровно 12 route declarations; проверка путей/символов/строк и byte equality Git blobs; внутренняя проверка JSON/Markdown counts и ссылок; `git diff --check`. Первоначальный AST-разбор системным Python 3.11 остановился на уже существующем синтаксисе f-string Python 3.12+; затем source-анализ выполнен Python 3.13. Ни один модуль приложения не импортировался. Это ограничение инструмента анализа, не дефект приложения.

**NOT RUN:** app imports, pytest/collect/unit/SQL/ORM, Docker/venv/install/dependencies, HTTP/API/браузер/Swagger/OIDC, startup/lifespan, полный runtime inventory 1703, exporter/codegen исполнения, рабочий пилот, deploy/activation. Контейнерная приёмка принадлежит другому владельцу; её будущий результат не присоединяется к этому неизменному снимку задним числом. Изменены только эти два новых файла отчёта; app/tests/requirements/locks/Dockerfile и существующая документация сохранены.

## Указатель проверяемых исходников

Для каждой строки ниже полный Git blob SHA, файл SHA-256, symbol и границы строк находятся в JSON. Сокращение SHA здесь служит указателем, не новым snapshot. Доменные каноны поставки закреплены отдельно как `canon.*`; они не копируются в публичный отчёт.

| Ref | File : symbol : line | Git blob SHA (prefix) |
|---|---|---|
| `api._policy` | [server/app/product_api/app.py:82](../../server/app/product_api/app.py#L82), `_policy` | `17fe2e15ce3e` |
| `access.resolve` | [server/app/product_api/access.py:67](../../server/app/product_api/access.py#L67), `resolve` | `b1bcb6228d5d` |
| `identity.eligible_scopes` | [server/app/services/partner_identity.py:200](../../server/app/services/partner_identity.py#L200), `eligible_scopes` | `87ad62e90567` |
| `identity.live_grant` | [server/app/services/partner_identity.py:304](../../server/app/services/partner_identity.py#L304), `live_grant` | `87ad62e90567` |
| `query.Query.contract_domain` | [server/app/product_api/queries.py:46](../../server/app/product_api/queries.py#L46), `Query.contract_domain` | `f071b14d5024` |
| `query.Query.conditions` | [server/app/product_api/queries.py:67](../../server/app/product_api/queries.py#L67), `Query.conditions` | `f071b14d5024` |
| `query.Query.listing` | [server/app/product_api/queries.py:135](../../server/app/product_api/queries.py#L135), `Query.listing` | `f071b14d5024` |
| `query.Query.project` | [server/app/product_api/queries.py:179](../../server/app/product_api/queries.py#L179), `Query.project` | `f071b14d5024` |
| `dto.Contract` | [server/app/product_api/dto.py:140](../../server/app/product_api/dto.py#L140), `Contract` | `bc0e3a69fd9a` |
| `dto.Document` | [server/app/product_api/dto.py:150](../../server/app/product_api/dto.py#L150), `Document` | `bc0e3a69fd9a` |
| `monitor.detail` | [server/app/product_api/monitoring.py:20](../../server/app/product_api/monitoring.py#L20), `detail` | `de83a383e7cb` |
| `metrics.visit_summary` | [server/app/services/ops_monitor_context.py:51](../../server/app/services/ops_monitor_context.py#L51), `visit_summary` | `422eee6a04ff` |
| `files.content` | [server/app/product_api/files.py:39](../../server/app/product_api/files.py#L39), `content` | `7bff6141305a` |
| `native.get_contract_locations` | [server/app/routers/references_router.py:1209](../../server/app/routers/references_router.py#L1209), `get_contract_locations` | `a106bb1ff895` |
| `nativecase.create_native_contract` | [server/app/services/native_contract_commands.py:23](../../server/app/services/native_contract_commands.py#L23), `create_native_contract` | `e6abcc8158bb` |
| `importcase.create_imported_contract` | [server/app/services/contract_commands.py:15](../../server/app/services/contract_commands.py#L15), `create_imported_contract` | `8efcd9ec771d` |
| `parties.create_imported_counterparty` | [server/app/services/counterparty_commands.py:17](../../server/app/services/counterparty_commands.py#L17), `create_imported_counterparty` | `b75657fdd18d` |
| `usage.contract_usage` | [server/app/services/contract_usage.py:120](../../server/app/services/contract_usage.py#L120), `contract_usage` | `dbe2d5cc105f` |
| `docs.upload_version` | [server/app/routers/docs_router.py:5342](../../server/app/routers/docs_router.py#L5342), `upload_version` | `fd7f872b6532` |
| `docpolicy._readable_doc_clause` | [server/app/services/doc_access.py:389](../../server/app/services/doc_access.py#L389), `_readable_doc_clause` | `122ef365a54a` |
| `writer.put` | [server/app/services/file_store.py:125](../../server/app/services/file_store.py#L125), `put` | `4aa23deedfdc` |
| `docflow.decide` | [server/app/services/doc_approvals.py:525](../../server/app/services/doc_approvals.py#L525), `decide` | `98db6f0dc203` |
| `api.curated_openapi` | [server/app/product_api/app.py:362](../../server/app/product_api/app.py#L362), `curated_openapi` | `17fe2e15ce3e` |
| `api.public_client_openapi` | [server/app/product_api/app.py:449](../../server/app/product_api/app.py#L449), `public_client_openapi` | `17fe2e15ce3e` |
| `main` | [server/app/main.py:490](../../server/app/main.py#L490), `<file>` | `a19f2de12fe7` |
| `config` | [server/app/config.py:55](../../server/app/config.py#L55), `<file>` | `30737e55974a` |
