# M05: writers объектов и план сохранения жизненного цикла

Дата: 30.10.2026. Статический разбор **Ledger source `13d1b6b3d544325ce0234677d2f7536e09e4c116`**.
Результат: карта обнаруженных путей записи и следующий ограниченный пакет команд;
runtime, схема, маршруты, клиенты и данные этим документом не меняются.

`DELETE /api/locations/{id}` с 409 сохраняет запись, но **не реализует retirement**.
Простое `status=closed` тоже не реализует его: не задаёт дату/основание, не закрывает
периоды, а в одном backfill делает сессии кандидатами на перепривязку. Общая
команда уже защищает два ручных семейства, однако импорты, склад и соответствия
ещё пишут вне её барьера. Поэтому следующий шаг состоит в сведении writers и
выделении разных операций, а не в публикации нового retire endpoint.

## 1. Источники, доказательность и пределы

Все ссылки вида `server/...:N–M` ниже относительны `clearledger/` и относятся к
закреплённому source. Машиночитаемый [manifest](OBJECT_LIFECYCLE_WRITERS_20261030.json)
содержит SHA256 исходных файлов и документов; это контроль входов исследования,
не новый scanner и не инвентаризация рабочей БД.

| Источник | Что подтверждает | Чего не подтверждает |
|---|---|---|
| [LOCATION_COMMANDS](../LOCATION_COMMANDS.md), source `13d1b6b3` | Граница прежнего M05/M04, admission, barriers, freeze и известные gaps | Перевод импортов, temporal retire, полный no-reuse |
| Deploy worktree `partner-api-design-20261029`, `docs/OBJECTS.md` §1–2а, §4–8; `SPACE.md` §3, §8–10; `CORE.md` §1–2 | Принятая в проекте целевая декомпозиция, владельцы, company scope, направление проекции | Применённые сегодня DDL, количество объектов или выполнение всех требований |
| Тот же deploy, `docs/api/execution-20261029/STATUS.md:145–162` | Сохранённая сверка выпуска: Core `5ce5779b20151a8d04de7d3a1681d1862a80d9dd`, backend v1682, frontend v843 / 1.2.857; Support `09c221c4b5135984173e3a924fd38f65cc208637` | Живое состояние на момент этого отчёта; выпуск кандидата `13d1b6b3` |
| Тот же deploy, `API-MODERNIZATION-PLAN.md:114–123`; `STATUS.md:129` | Приёмка M05: пять уровней, охват list/detail/count/export и отдельные create/upsert/rename/retire | Завершение M05 по наличию read API |
| `docs/СТО. Идентификация объектов зарядной инфраструктуры (проект).docx`, п.4.4, 7.1, 7.5–7.8, 8.1–8.5, 9.1–9.6, 11.5; две редакции проекта учётной политики | Проектный intent: no-reuse, разделение ключей, дат, вывод без выбытия и выбытие | Утверждённую политику или правовую норму: в СТО незаполнены приказ и дата введения |

СТО извлечён чтением `word/document.xml`, без исполнения приложений. П.9.5 прямо
различает вывод без выбытия и закрытие номера точки; п.9.1 запрещает возврат
**станции** из «выведена». Это не основание автоматически запретить открытие
склада или назвать любое `ServiceLocation.status=closed` выбытием станции.
Упоминание ФСБУ в draft не делает выбранную здесь архитектуру юридической рекомендацией.

В `OBJECTS.md` есть датированные устаревшие описания: §2а говорит, что связи пишут
только backfill, §7 содержит «заморозки отсутствуют». На этом source есть
`sync_placement`, manual external mapping и `location_commands`; код ниже
подтверждает эти изменения. Целевая модель от этого не понижается.

Исследованы текстовые вхождения моделей/таблиц, constructors, присваивания,
`setattr`, SQL и вызывающие цепочки в `server/app`, `server/scripts`, а также
репозиторные `.sql/.sh/.ps1/.ts/.js`. Новый AST scanner не создавался.
Неизвестны вне-репозиторные SQL/скрипты, фактические расписания/каналы, исторически
применённые ограничения и удалённые строки. Нельзя назвать это полным аудитом БД
или доказательством отсутствия иных production writers.

Source pin намеренно не обновлялся `pull`: его неизменность задана Dispatch.
Прочие деревья не переключались; их чужой WIP не изменялся. Сеть/API/SSH/VM,
bootstrap, app import, SQL, браузер и секреты не использовались.

## 2. Уровни и идентичности: implemented / gap

| Уровень | Реальное хранение и writer | Чтение / граница реализации |
|---|---|---|
| servicePoint / точка обслуживания | `models.ServiceLocation:4986–5064`: opaque `id String(40)`, `company_id`, code, name, status; legacy паспорт остаётся на точке | Native locations/registry, product objects. Это не станция по одному имени API; legacy импорты ещё создают отдельные точки для пары AC/DC |
| station / оборудование | `models.EzsEquipmentUnit:6220–6340`; складские документы/импорт, backfill; `placed_at` связывает с точкой | `station_passport`, product equipment только `kind=station`. Текущий `current_location_id` не равен исторической связи |
| site / площадка | `models.EzsSite:6912…`; `ezs_project.link_location:1790–1820` и lifecycle проектов хранят скалярные ссылки с журналом | Native sites существуют; product site не exposed. `belongs_to` writer не обнаружен, нет доказанной общей temporal цепочки site↔point |
| EVSE / точка отпуска | `models.EzsEvse:6562–6589`: FK `unit_id`, number, external_id, status; два backfill | Структура и bulk наполнение есть; общей create/update/retire команды и product EVSE API нет |
| connector / разъём | `models.EzsConnector:6592–6613`: FK `evse_id`, number, тип | Bulk наполнение есть; metadata `connectors` из АСУиМ не равно полному live writer этих таблиц; product API нет |

`ObjectLink:6448–6504`: строки с типами/ключами без FK на каждый target,
`valid_from/to Date`, мягкое `basis_doc_id`, note, автор, `recorded_at`.
Канон и SQL-предикаты используют **полуинтервал `[from,to)`**. `recorded_at` есть
время записи, а не эффективная дата документа. `installed_on/decommissioned_on`
у ServiceLocation (`5050–5053`) хранятся ISO-строками, не period ledger.

`relation=number` поддержан чтением резервирования в общей команде, но constructor/
producer не обнаружен. `mounted_in` и `belongs_to` описаны в модели/каноне;
production writer на этом pin не найден. FK EVSE→unit и connector→EVSE не являются
реализацией этих периодных связей. Отдельные модули/routers с именами
`space_objects` или `temporal` в pin отсутствуют; заменять это предположением об
их API нельзя. Реальные входы: `space_registry_router` и `ops_router`, ниже.

## 3. Матрица обнаруженных writers

Обозначения: **C** = явный company predicate/проверка; **O/G** = object scope /
own organization; **T** = транзакция caller. `database.py:get_db:5543–5551`
делает commit после yield, rollback при exception.
Членство, product grant и административное право не взаимозаменяемы.
Указанная ниже нехватка явного gate не объявляет доказанный exploit: глобальный
ORM SELECT scope (`scope.py:138–168`) может дополнительно сужать чтение, но
не заменяет mutation admission, raw SQL и background context.

### 3.1 Точка: ручные adapters и обходные операции

| ID / family, file:function:lines | Что записывает | Admission, locks, commit | Authority / history effect |
|---|---|---|---|
| W01 `routers/locations_router.py:create_location:216–243`, `update_location:246–271` → `services/location_commands.py:create/upsert/update:188–238` | Новый ID (payload либо `ezs-`+random); code/name/type/status, metadata.number→station_number; sourceBindings | POST company membership, PATCH get_owned + membership; command C+O/G; ID→company advisory xact barrier, tenant-qualified FOR UPDATE + reload; flush/refresh/projection, T | Existing ID всегда та же точка, tenant не меняется. Freeze и резервирование номера; нет dated rename/status history. Native не пишет registry create/update audit; нет idempotency intent create при потерянном ответе без ID |
| W02 `routers/space_registry_router.py:create_object:135–148`, `patch_object:177–215` → `services/space_registry.py:create_object/update_object:126–156` | Server random ID, те же code/name/status через command | Company admin/superadmin, type/status enum wrapper; C+O/G command; тот же barrier/row lock. Registry wrapper audit + собственный commit/refresh | CREATE, не upsert. `space.object.create/update` хранит diff; rename незамороженного code не создаёт ObjectLink.number/numberHistory. `confirm` для active→не-active запрашивает Support impact до lock, но не является temporal retire |
| W03 `routers/locations_router.py:delete_location:274–290` | Ничего: после command update `{}` возвращает409 | get_owned + membership + command C/O/G/lock; exception→rollback T | Сохраняет ключ и ссылки, но UI DELETE consumer остаётся сломанным; не архивирует и не закрывает датой |
| W04 `routers/locations_router.py:set_operational_status:298–330` | `operational_status`, включая decommissioned | get_owned, enum allowlist; нет общей `_locked`/G-проверки команды, T; single-object projection | Audit `location_op_status` с временем записи; без effective date, не меняет lifecycle status, decommissioned_on или placed_at. Возможен обратный переход через этот endpoint |
| W05 `services/ezs_equipment.py:get_or_create_warehouse:196–219`; `ezs_equipment_docs.py:save_warehouse:620–679` | ID `wh-`+hash(company,name), code=name, status active при создании; warehouse rename меняет только name/metadata | Equipment routes `832–849`: membership; helper C/type; отдельного O/G mutation guard/barrier нет; flush, T | Склад тоже ServiceLocation; нет общего ID/history reservation/freeze. Поиск по имени при rename+повторном создании может столкнуться с прежним детерминированным ID; это inference из алгоритма, не воспроизведённый инцидент |
| W06 `ezs_equipment_docs.py:set_warehouse_status/delete_warehouse:682–750`, equipment routes `856–877` | close/reopen `status=closed/active`; физическое удаление ServiceLocation | Membership; C/type; close проверяет units/spares, delete также движения/документы склада; без общего row/barrier; T | Полезная отдельная семантика склада, но DELETE409 W03 её не покрывает. `_warehouse_usage` не является общим обходом всех ссылок/links/audit; no-reuse общей команды можно обойти |

### 3.2 Импортные точки и паспортные producers

Общий admission импортов: `routers/channels_router.py:run_channel:456–489`
делает `get_owned(Channel)`, пишет лог и запускает `_run_channel_background:327…`.
`services/channel_scheduler.py:_launch:103–123` запускает тот же background из
расписания без request user. `channel_orchestrator.py:_run_stations:557–585`,
`_run_charge_sessions:512–554`, `_run_reestr:404…`, `run_channel:631–670` передают
`channel.company_id`. Они не передают в нижние writers доказательство полномочий
на каждую изменяемую точку/организацию. Конкретные активные каналы **unknown**.

| ID / family, anchors | Что записывает | Locks / transaction / gates | Authority / history effect |
|---|---|---|---|
| W07 `services/stations_normalize.py:_ingest_compact:311–560`, особенно `429–536` | Existing: op status, lifecycle→closed при decommissioned, недостающий station_number, metadata.number, name; новый ID hash(company,ocpp/number), code=OCPP либо номер, active/closed | C/type выборка; source matching OCPP-first, неоднозначности в report; command/freeze/advisory отсутствуют. `_bump:255–265` commit по200 и в конце; не атомарный файл | CPO registry name сильнее session name; nameHistory с прежним именем, op-status audit. No lifecycle effective date, basis или number history; отсутствие карточки в replace не равно retire |
| W08 `stations_normalize.py:ingest_stations:562–843`, `697–817` | Existing: typed station_number/status/паспорт через `setattr`; metadata snapshot, nameHistory. Новый ID hash(company,ext), code=number/serial/ext | C/type; partial/append/replace и источниковые индексы; no command locks/freeze. Commit chunks через `_bump`, flush | Full `_status_from_stage:77–84` может вернуть active даже после manual closed; partial `740–744` сохраняет status кроме decommissioned→closed. Existing id/code/source_bindings сохраняются. **Typed loop всё ещё пишет loc**, несмотря на общий комментарий passport о переводе всех feeders |
| W09 `stations_normalize.py:ensure_stations_from_sessions:943–995` | ID hash(company,`sess:code`), code/number, active placeholder | C; без общей команды/резерва history/барьера; flush caller | Explicit helper, вызывается backfill только при `auto_create=True`; текущий `charge_sessions_normalize:396–397` передаётFalse. Production entrypoint True в найденных app callers не обнаружен, фактический ручной запуск unknown |
| W10 `stations_normalize.py:refresh_location_names:1087–1117`; caller `charge_sessions_normalize.py:396–416` | Raw SQL name из последней session; дописывает nameHistory | Явный C в raw SQL; O/G hook raw SQL не действует, command barrier отсутствует; T/background caller | Сохраняет CPO `nameSource=cpo_registry`; ручное имя без этого marker может быть перезаписано. Нет общей manual-field freeze/даты действия имени |
| W11 `services/station_passport.py:write_value:75–99`; `reestr_rushydro.py:_enrich_passport:1064–1121`, `ingest_obshaya:1124–1212` | installed/decommissionedOn→unit, если найден, иначе loc; inventory и иные поля паспорта | Resolver C, station map на сегодня; helper сам не выполняет admission/lock/commit; T/flush | Факты дозаполняются только при пустом passport_value, текст вывода без даты уходит в decommissionNote. Не закрывает lifecycle/links; нет общей ручной защиты полей и общего freeze producer barrier |
| W12 `services/asuim_normalize.py:ingest_connectors:330–412`, `ingest_view:1146–1154` | Count/types/power владельцу через write_value; loc.metadata.connectors snapshot; stations view→W07/W08 | C mapping; без placement/owner lock, flush/caller | Не создаёт live EzsEvse/EzsConnector и mounted_in. Snapshot может опережать bulk materialization; его status не является point retirement |
| W13 `services/ezs_equipment.py:_sync_passport:548–582` из commissioning `503–505` | Legacy loc serial/inventory/модель/count/power | Unit movement допускает компанию и держит unit row lock; loc по id без общего location barrier; T | `passportHistory` old fields + audit; не меняет point code/number. Ещё один путь возврата паспортных значений в loc, а station-first reader может предпочесть unit |

**1С и HubEx.** В `services/onec/`, `onec*.py` прямой writer ServiceLocation/
ObjectLink исследованным поиском не обнаружен: наличие `bp_ref` или source binding
«1c» не доказывает такую запись. 1С import/API entrypoint объекта вне найденных
путей **unknown**, не «отсутствует в production». В `hubex_sync.py:_asset_map:119–135`
и `_upsert_assets:261–299` объектный реестр читается для связи зеркала HubEx; это не
writer point identity. HubEx поля приходят через W07/W08, разрешённые metadata
правки W01, W11 passport и external mapping W16. Обратное изменение объекта
через зеркало HubEx не обнаружено; сам HubEx не объявляется мастером наших номеров.

### 3.3 Temporal placement, station lifecycle, bulk и delete обходы

| ID / family, anchors | Что записывает | Admission / locks / commit | Authority / history effect |
|---|---|---|---|
| W14 `services/ezs_equipment.py:apply_movement:344–507`, `sync_placement:510–545`; equipment routes `568–613`, documents `747–805` | Unit state/current_location_id; commissioned_on/decommissioned_on; close/open `placed_at` | Membership route; C unit FOR UPDATE; location C/type проверки, period cutoff, порядок документов. Нет location command barrier; T | Движение с prev, post_entry и document. Effective day из occurred_on. `sync_placement` закрывает max(day,start), новую начинает max(day,все прежние to): может сдвинуть заявленную дату. Только unit in_operation имеет placement; parent status closed не запрещён `_get_location(...want_type=site)` |
| W15 `services/ezs_equipment_docs.py:cancel_document:484–551` | Восстанавливает unit из prev, сторно; sync_placement; при отмене первичного прихода **DELETE всех placed_at станции и самой unit** | Document и movements/units FOR UPDATE, company/closed period/later moves checks; no common location barrier; T | Отмена не возвращает loc паспорт/статус, сообщает warning. Связи удаляются без проверки истории sessions/external_id/EVSE beyond shown checks; такой путь не является append-only temporal ledger |
| W16 `services/station_mapping.py:add_external_id:203–238`, `close_external_id:241–253`; `routers/ops_router.py:236–271` | `external_id` link parent_type=station, parent_id=**location_id**, child_type=`system:role`; close valid_to/reason | Membership+C по link/company; add не проверяет существование/ownership target, close не связывает link с location_id path; нет row/barrier; сервис делает **commit сам** | Optional valid_from/default today, note/author; basis_doc не заполняется. Preflight проверяет только open links чужого parent, не все интервалы. Close не запрещает to<from, повтор меняет прежнюю границу; ссылка уровня station фактически использует point key |
| W17 `scripts/backfill_stations.py:main:229–345`, helpers `93–225` | Создаёт/дозаполняет unit, state written_off/in_operation, placement; сдвигает valid_from до первой session; optional EVSE/connector с номерами | CLI resolve company, ev_charging/non-test; `--apply`/APPLY=1 иначе rollback; no caller ACL/advisory; один commit | Retired выводит из status **или** op status **или** даты. При unknown/broken close date оставляет placement open и report; для существующего link правит начало, не доводит текущий status до close. Evidence-backed migration helper, не универсальный retirement command |
| W18 `scripts/backfill_evse.py:main:98–166` | EVSE.number, connector.number; external:asuim_evse link, **не** поля EVSE.external_id/status | CLI C, dry-run rollback/`--apply` commit, no shared barrier | Использует JSON connectors и unit lookup; link valid_from из created_at точки, не доказанной даты установки. `mounted_in` не создаёт |
| W19 `scripts/backfill_external_ids.py:external_values:47–65`, `main:102–153` | External links из source snapshots; parent station с **unit UUID**, fallback point_of_service с loc key | CLI C, existing/conflict map, apply commit иначе rollback; no command locks | Иная типизация, чем W16: child_type=`external:system`, не `system:role`. Registry lookup W16 по station+location_id может не показать эти links; два источника соответствий не сведены. Начало из created_at, не полного intent документа |
| W20 `scripts/prune_stale_stations.py:main:35–80` | Bulk DELETE ServiceLocation по отсутствию соответствия xlsx | CLI C при выборе, `--apply`, commit; без freeze/history/общего barrier | Обходит W03. Комментарий «безопасно, сессии SET NULL» не означает сохранённую финансовую аналитику. Теряются FK-привязки, мягкие ObjectLinks могут остаться; успешный DELETE не доказывает целостность |
| W21 `services/ezs_equipment.py:import_units_xlsx:806–1024`, equipment router `1138–1148` | Unit create/state/current loc, дозаполнение serial/inventory и др.; склады через W05 | Membership+C; dry_run отдельная ветка; без общего identity/placement lock; T | Прямой receipt movement с file basis, не гарантированная sync_placement цепочка. Existing unit заполняет пустые поля, state не перезаписывает; worksheet state при create не point retirement |
| W22 `routers/equipment_router.py:patch_unit:467–538`, `delete_unit:541–565`; `ezs_equipment.py:unit_from_site:585–603` | Station serial/inventory и карточка; delete единицы с простым receipt; создание unit из loc | Membership+C, patch serial preflight и closed-money guard; нет общего point/freeze lock; delete проверяет движения/поставку; T | Inventory update может стать freeze producer без участия point barrier. Unit delete и FK CASCADE EVSE/connector не охвачены W03; нет общей проверки мягких links. unit_from_site копирует legacy паспорт и current_location, само не создаёт placement |
| W23 `scripts/postdeploy_ezs_nakat.py:main:36–64` | Вызывает W09-backfill с default auto_create=False: перепривязка session.location_id; отдельные финансовые шаги | CLI resolve company, **нет dry-run**, отдельный commit каждого шага, без общего point barrier | Существенный bulk entrypoint к описанному rebind. Не writer point retirement и не безопасная проверка после прозы; не запускался |
| W24 `services/ezs_project.py:link_location:1790–1820`, `routers/sites_router.py:1345–1358`, `services/ezs_lifecycle.py:sync_from_site:297…` | Site.location_id и отражение в project; не ObjectLink.belongs_to | Membership, site/loc C, без общего link barrier; log_event, route commit | Журнал смены скалярной ссылки, не периодное размещение. Дату ввода намеренно не устанавливает; process commissioning меняет site.commissioned_on отдельно (`projects_process.py:498–502`) |
| W25 `services/ezs_equipment.py:_create_receipt_unit/create_unit:284–341`; `services/ezs_supply.py:receive_line:470–575`; equipment routes `399…`, `1757–1772` | Новый unit UUID, serial/inventory, initial stock state/current warehouse; receipt и бухгалтерское движение | Membership, C/type warehouse, serial preflight; supply document/line FOR UPDATE, check_period; flush/T | Создание inventory station, не point ID/number. Receipt helper сам не делает admission/placement; факт inventory влияет на freeze, когда появится placed_at. Прямой supply producer не следует терять при переводе inventory writers |

`scripts/check_object_ticket_autoprojection.py:26–43` отдельно создаёт synthetic
ServiceLocation и удаляет её. Это диагностический writer, не штатный бизнес-вход;
его нельзя запускать приёмкой этой prose-задачи. `seed.py:346…` меняет source
bindings существующих GIG points, не их ID/number/status. `database.py` содержит
региональный backfill и schema DDL, но не исполнялся и не служит доказательством
наличия ограничений в выпущенной БД.

## 4. Что именно защищено общей командой

`location_commands.py:67–100`: `_barrier` берёт transaction advisory lock ID,
затем company; `_locked` включает tenant **до** FOR UPDATE, reload устраняет stale
identity map. `_assert_visible` проверяет O/G, create запрещён ограниченному O/G
без назначения. String ID 1..40, без NUL, без trim/remapping; id/company не входят
в editable allowlist (`138–163`). Это сохраняется во всех следующих adapters.

`_apply:166–186` проверяет изменения code, materialized station_number и
metadata.number, включая null/empty. Freeze (`object_freeze.py:40–100`) видит
договор, session, inventory у станций через placement за всю историю, external
mapping и company-wide external export log. `_assert_numbers_free:112–135`
резервирует code/number/legacy numberHistory даже closed/test points и закрытые
number links. Create (`188–220`) также ищет прежний ID в links и registry audit.

Граница гарантии существенна:

- FK inserts ContractLocation/ChargeSession сериализуются с FOR UPDATE точки
  при обычном READ COMMITTED; inventory, generic ObjectLink и export log общего
  location barrier не берут. Это подтверждённый gap, не обещание всех гонок.
- `ObjectExportLog` не хранит список ID; один внешний log замораживает компанию.
  Комментарий export route `200–203` о `is_external=False` устарел: присваивание
  `206` использует `external`. Internal проекция не должна замораживать номер.
- Ни одна успешная незамороженная смена code/number здесь не создаёт dated
  alias или numberHistory. Освободившийся code без другого следа снова доступен.
  «Reserve existing history» не равно «создать историю при каждой смене».
- При `_assert_numbers_free` ORM SELECT может быть уже сужен request scope;
  company-wide reservation вне видимого набора нельзя считать доказанной только
  наличием company predicate. Это надо охватить отдельным regression/guarded
  internal read, сохраняя запрет возвращать невидимые данные.
- В модели status строковый; registry wrapper ограничивает active/planned/closed,
  native DTO и command проверяют лишь строку/длину. Native может принять иной
  статус; переходы, date и station lifecycle не валидируются общей командой.
- ID guard не восстанавливает давно удалённый ключ без сохранившихся links/audit.
  W05/W20 обходят guard; абсолютный исторический no-reuse ещё не достигнут.

## 5. Readers: population, list/detail/count/export и as-of

| Reader / anchors | Population и закрытые точки | Историческая семантика / gap |
|---|---|---|
| Native `locations_router.list_locations:156–168`, `_out/_passport:88–143` | Все ServiceLocation C+object scope, **без status/type/is_test фильтра** | Passport station на today; closed остаётся в списке. Это не список «действует на дату» |
| Registry `space_registry.list_objects/_load:70–115`; router `89–132` | Все C+object scope, optional status/type/q; total=len того же списка; detail без lifecycle exclusion | Имена/code/status текущие. Статусный фильтр не даёт историческую версию |
| Product `product_api/queries.py:67–98,135–176,188–194` | C+typed resource grant+member O/G. Objects **не отфильтрованы по energy type, is_test, closed**; count/list одни conditions до cursor, detail тот же policy | DateFrom/To фильтруют created_at, не effective validity. Product equipment kind=station, scope через current_location_id; исторически снятая unit может исчезнуть из scoped equipment, хотя point history остаётся |
| Product monitoring `monitoring.py:20–39`, `app.py:143–151` | Authorize point первым, energy profile, затем sessions этого point. Closed доступен, если обычный detail доступен | asOf ограничивает session window и data boundary; status берётся **текущий** operational_status. Не point/station status as-of и не финансовая история |
| `station_scope.py:43–81`, consumers `network_state.py:183–195,256`; `ops_dashboard.py:252,659` | Реестр = ev_charging/ezs non-test; сеть исключает op_status=decommissioned; эксплуатация ещё исключает partner | `status=closed` с op_status working остаётся в network selection, но `network_state` active KPI исключает lifeStatus closed. Текущий фильтр сети применяется и к запросу прошлой даты: не реконструкция population as-of |
| `station_history.py:49–80`, `station_status_days.py:213–225` | Detail по C+point без исключения closed; status-days имеет собственную наблюдаемую дневную историю | Session dates ограничены; native history boundary по компании, product monitoring по point. Ни status-day source, ни audit recorded_at не доказывают effective retirement date |
| `locations_router.export_locations:171–213`, `space_projection._payload:459–466`, `project_object:124–160` | Export по company API key: internal все, external explicit publication allowlist; closed не исключён. Проекция отправляет весь реестр компании с текущим status | Нет исторического export/asOf. API-key/service admission иной, чем interactive O/G; не обещать один population без одинакового principal. Registry confirm-текст обещает исчезновение/архивирование в приложении, но здесь payload сохраняет closed; downstream эффект требует отдельной Support проверки |
| `station_passport.stations_by_location:102–160`, `passport_value:59–72` | Выбирает placed_at `[from,to)` на `on`, default today; затем station-first field fallback loc | Это **valid-time placement**, но значения unit/loc текущие; не bitemporal паспорт. При нескольких stations в point map даёт одну без детерминированного выбора: многопостовой/AC-DC detail ещё не решён |
| `object_control.py:32–90`; `backfill_stations.py:169–190` | «Retired» = lifecycle closed **или** op decommissioned **или** дата | Это диагностические эвристики/миграция, не определение новой команды. Контроль может не согласиться с population сети |
| `stations_normalize.py:build_station_index:865–941`, `backfill_session_locations:999–1084`; `session_scope.py:24–53` | Current code/number/metadata и numberHistory aliases, closed получает меньший приоритет | Индекс без dated resolution; номер может привести к текущей карточке. Stable source ID backfill перепривязывает без ограничения дат, fallback разрешает rebind shadow points, включая closed без asuimStationId |

Состояние product уровней честно отражено `product_api/app.py:392–399`: servicePoint
и station read implemented; site/EVSE/connector, writes и historical listing gap.
Общий native count «все объекты» не надо приравнивать к «нашей сети на дату».
`space_data_model.py:45–48` лишь описание источников, а не новый create producer.

Финансовые и договорные ссылки сохраняют **тот же point ID**: sessions, payments,
ContractLocation, docs, closing rows, движения оборудования/ЗИП, site/project и
мягкие source mappings. Примеры FK в `models.py:5223,5275,5881,6305–6313,6361–6363,
6637,6705,6733–6739,6851,7066,7131,7826,8659,9346,9487,10757,11216,12840,14379`
показывают смесь SET NULL/CASCADE. Это перечень найденных мест, **не полный usage
graph**. Ретайр не должен менять эти ID, пересчитывать прошлую выручку, переписывать
начисления или закрывать договор/заявку без отдельной предметной команды.

## 6. Конкретные конфликты и последствия текущего поведения

| Сценарий | Подтверждённый code path | Вывод для реализации |
|---|---|---|
| Manual PATCH закрывает point без даты | W01/W02; `_prepare` допускает status, даты не принимает | Closed не даёт valid-time end, не прекращает number/external/placement и не выводит unit. Future/retro close выразить нельзя |
| Тот же point затем импортируется | W08 full stage→active; partial сохраняет status кроме decommissioned; W07 пишет closed | Источник может открыть manual closed либо закрыть действующую point из статуса железа; source authority по lifecycle не определена общим правилом |
| Закрыли point без asuimStationId и позднее запустили backfill | `1044–1070` считает её shadow, индекс предпочитает active alias | Возможен перенос исторических sessions/выручки на другую point. Это source-supported inference; рабочая потеря данных здесь не проверялась |
| Изменили незамороженный code или номер | `_apply` заменяет значение, не пишет alias ledger | После изменения старая identity теряется для поиска/reservation; следующие matching/backfill могут создать дубль или использовать номер заново |
| Создали station withdrawal через op status | W04; W14 independently tracks unit dates/state | Network, lifecycle list, station passport и unit placement расходятся. Вывод без выбытия нельзя автоматически превратить в retirement точки |
| Замена/демонтаж станции | W14 closing/opening links, status точки не меняется | Правильное разделение аналитики point и железа уже частично есть; не ломать его общей командой closed |
| Отмена документа/складской DELETE/старый prune | W06/W15/W20/W22 | DELETE409 одного маршрута не обеспечивает no-delete history по системе; нужен контроль adapters и отдельный usage inventory до расширения |
| Конкурентные rename и external mapping/inventory/export | Command barrier только W01/W02, другие producers вне него | FK wait tests прежнего slice не покрывают эти гонки; требуются общий lock protocol и атомарность audit/reservation |
| Фактического EXCLUDE нет | `database.py:4764–4800` ловит отсутствие прав/btree_gist и выдаёт warning | Наличие DDL текста не доказывает non-overlap в БД. EXCLUDE проверяет child/type/relation, но не «одна station на parent position»; позиционного поля пока нет |
| Mapping close по другому location path / несовместимые namespaces | W16 выбирает только company+link ID, W19 использует unit UUID и external:system | Может закрыть иную company link относительно path; manual listing может не видеть bulk соответствия. Parent level/ownership, namespaces и dates проверять в adapter, без слияния по голой строке ID |

## 7. Уже определённые решения и границы будущих команд

Опора для следующих PR: одна company-owned запись на identity, пять уровней;
immutable technical key; point revenue переживает замену station; station inventory
сохраняется при переносе; свой номер, serial, inventory и external key разделены;
internal projection не freeze; освобождённые номера/ключи не переиспользуются;
effective dates отличаются от recorded time; закрытые соответствия сохраняются.
Это **проектный канон/intent draft**, согласованный с LOCATION_COMMANDS, а не
утверждение об исполнении всех правил runtime. Новый формат RR/X/CC и миграция
номеров не входят в следующий пакет; старые opaque IDs сохраняются.

Предлагаемый внутренний command contract, не новый HTTP API:

| Операция | Минимальные входы и обязательный эффект | Ограничение |
|---|---|---|
| create servicePoint | Company, actor/source, opaque ID либо server allocation, intent key+payload fingerprint, allowlisted fields; admission до mutation, ID+company barrier; сохранить reservation и audit в T | Существующий ID даёт conflict, native upsert остаётся adapter с явной update веткой. Случайный retry не создаёт ещё одну точку; collision не сливается по имени |
| update / rename name | Expected revision, changed fields, actor/source; reload за lock, explicit-null/omission rules, diff event | Name не identity; old name в audit/alias search, без изменения финансовых ссылок. Dated name version не обещать до появления ledger |
| assign/change number | Company-wide current+history reservation, old/new value, effective date, source, basis/reason; неизменный point ID | Freeze отказ остаётся409. Команда не становится обходом freeze. Legacy законные одинаковые «номера станции» из пары сохраняются, но не сливаются и не разрешают новую неоднозначную выдачу |
| withdraw station без выбытия | Station ID, effective date и basis, допустимый station transition, сохранить inventory; отдельно решить placement по реальной операции | Не закрывать number/point автоматически. Unit state, наблюдаемый op status и point status не взаимозаменяемы |
| retire servicePoint / disposal | Point ID, effective date, operation kind, document basis, revision, usage preview; сохранить identity/tombstone/reservation, отдельный event; links закрывать только по их предметному смыслу | Не применять автоматически от CPO `decommissioned`; до решения Q1 не подключать к legacy PATCH. Исторические docs/contracts/sessions остаются читаемыми под прежними ACL |
| correct / reopen | Correction с ссылкой на прежний event, причина, actor, дата, expected revision | Не стирать старую дату/автора. Reopen склада существует отдельно. Для окончательно выведенной station draft9.1 задаёт запрет; исправление ошибки не равно обычному reopen |

Границы периодов для implementation PR:

1. Даты принимаются строго ISO calendar date, `from < to` для непустой связи;
   в дату `to` связь уже не действует. Источник «последний рабочий день» должен
   явно преобразоваться в исключающую границу; неизвестную дату не подставлять
   today/created_at. Timezone сессии задаётся существующим MSK monitor contract,
   а не серверным неявным `::date`.
2. Historical correction проверяет все пересекающиеся интервалы, posted/closed
   periods и dependent events. Не clamp в max/min молча: conflict с точными
   противоречиями и отдельная correction. `recorded_at` новой записи сохраняет
   реальное время внесения. Full «что знали тогда» требует append-only revisions,
   одно исправляемое ObjectLink этого не обеспечивает.
3. Future close либо пока отвергается, либо хранится как scheduled effective event;
   до срока current status/selection не меняются. При выборе scheduled режима
   current вычисляется из событий; cron не должен становиться второй истиной.
4. Basis_doc проверяется существованием, company и доступом к документу; soft FK
   не освобождает от проверки. Разрешённый вид basis зависит от операции:
   name rename может обходиться без документа, disposal требует основания по
   принятому процессу. Не создавать фиктивный акт для source snapshot.
5. Number reservation действует и после retire/correction. EXCLUDE по времени
   разрешил бы выдачу другому после закрытия, что слабее draft no-reuse; нужен
   постоянный reservation ledger/tombstone в отдельном expand schema пакете.
   Existing shared station_number не превращать в unique constraint на point.
6. placed_at закрывается при фактическом снятии/выбытии station, не при простом
   скрытии карточки point. mounted_in/belongs_to требуют своих adapters и cardinality,
   а external_id закрывается по disposal/termination соответствия, не всем родителям
   по строковому совпадению. Исторические closed links не удалять при cancel.
7. Financial references не remap и не cascade: posted periods, договорные условия,
   начисления, платежи, sessions и support work сохраняют историю. Поздняя session
   после retire попадает в reconciliation conflict, а не resurrect/relocate.

## 8. Следующий минимальный пакет M05-W1 и последующие gates

**Следующий PR: общий writer adapter для существующих points и явная история
смены идентификаторов; без публичного write/retire API, schema rollout и новых прав.**
Не пытаться за один PR реализовать пять разных lifecycle автоматов.

| Шаг / ожидаемые файлы следующего PR | Конкретное изменение | Reviewable acceptance |
|---|---|---|
| A. `services/location_commands.py`, W01/W02 wrappers | Извлечь command context (company, actor/source, existing admission, expected current value) и единый lock helper; не прятать commit в domain command. Ввести distinction name rename / code-number change / source status observation | Прежние native upsert/registry create, status enums wrapper, 404/403/409, raw metadata/null, station passport и wrappers audit/projection сохраняются |
| B. `services/stations_normalize.py` W07/W08/W10 | Существующие точки обновлять за тем же company+ID barrier с populate_existing, через allowlisted source adapter. Freeze/number conflict возвращать как строку reconciliation, raw snapshot сохранять, код/ID не переименовывать в обход. CPO name-source rule оставить явным; ручной label с provenance не перетирать session updater | Повтор файла не меняет identity; locked manual number выигрывает у stale import; один конфликт не делает весь файл ложным success и не откатывает уже committed chunks |
| C. Та же command boundary и `_assert_numbers_free` | При разрешённой code/number change писать typed `identifierHistory` (domain, old/new, actor/source, recorded time) в той же T; защитить ключ от ручного metadata merge. Для реального point number дописать совместимый `numberHistory` с ключом `было`, **code туда не класть**: session index считает его номером. Reservation читает оба формата; existing history сохраняется | Старое значение остаётся занятым после rename, rollback убирает изменение и alias. Company-wide collision check видит невидимый conflict без выдачи его данных. JSON не заявляется valid-time ledger; технические коды не становятся алиасами station number |
| D. `services/station_mapping.py`, `ops_router.py`, `ezs_equipment.py:sync_placement` | Вынести уже существующие add/close/placement операции в internal link command: caller commit, C+parent/path+O/G admission, тип target, ISO dates, parent/child locks и overlap check. Перевести W16 и W14 без новой route/permission | Отказ не меняет link, закрытый link не редактируется повторным DELETE, wrong-path parent404; unit+placement атомарны; no silent date clamp |
| E. `stations_normalize.py:backfill_session_locations` и W06/W20 safeguards | Перестать считать business closed достаточным доказательством shadow; remap только по явной технической reconciliation policy. Обозначить W20 obsolete для обычного retirement; warehouse delete использовать общий usage/no-reuse guard до дальнейшего расширения | Closed historical sessions не переезжают по номеру; warehouse не обходит общий history guard. CLI migration не запускается автоматически и не считается API |

A–C можно принять первым отдельным bounded diff; D и E обязательны до подключения
retire к любому существующему consumer. Для B нельзя просто заменить весь import
на нынешний `create`: он запрещает номер, который законно разделяют legacy AC/DC.
В W1 existing duplicate с неизменным номером сохраняется; **новые/меняющие номер
неоднозначные import cases уходят в reconciliation**, не создают двойников и не
расширяют права. Создание W07/W08/W09, склад W05 и full dated retirement требуют
следующей явно выделенной wave, а не скрытого bypass flag.

Следующая wave после W1: persistent identity/number reservations + append-only
lifecycle events (effective/recorded time, basis, actor/source, intent+fingerprint),
expand migration и internal retire/correction. Source key reservation берётся
отдельно для new import intent; server technical ID не выводится из external ID,
сохраняется mapping. Existing deterministic IDs **не переписываются**. Лишь после
характеризации consumers native PATCH получает adapter к согласованной операции;
partner writes по-прежнему выключены. Декомпозиция site/EVSE/connector отдельно.

Порядок locks проектировать единым для writers и freeze producers: source intent
(если есть) → общий company barrier → упорядоченные point/unit/link keys → row
reload. Это **предложение следующего протокола**, не описание существующего
ID→company порядка. Переход нельзя делать частично, смешав противоположные порядки:
прежний unit-first movement и point-first command могут образовать deadlock.
Commit chunks импортов заканчивает барьер; следующий chunk переустанавливает
контекст/locks. Projection/network выносить за commit только отдельным outbox
изменением с приёмкой доставки; не незаметно менять прежний failure contract W01.

### Не более трёх продуктовых решений перед temporal retire

1. **Что означает legacy закрытие точки в текущей форме:** окончательное
   прекращение commercial servicePoint или административная недоступность?
   Предложение: различить `withdrawStation`, `closeServicePoint` и `setWarehouseStatus`;
   CPO decommissioned хранить наблюдением станции, не автоматическим disposal точки.
   Последствие: часть нынешних status PATCH должна получить adapter/409 с конкретным
   объяснением, а не массовую миграцию значений. No-reuse и сохранение inventory уже
   определены каноном, повторно их выбирать не требуется.
2. **Нужны ли в первой internal close-команде future даты и reopen коммерческой
   точки после окончательного disposal?** Предложение: первая wave поддерживает
   current close и документированную backdated correction; future schedule и
   обычный reopen disposed point отклоняются409 до отдельного event model.
   Ошибочная запись исправляется correction, а не стиранием истории; складской
   reopen сохраняется. Последствие: меньше совместимых сценариев сначала, зато
   нет преждевременного закрытия/тайного возврата station из terminal state.
3. **Как принимать backdated факт, противоречащий posted period/поздним sessions
   или будущему документу, и чем подтвердить основание?** Предложение: preview
   перечисляет conflicts; обычная команда409, correction доступна только по
   существующему полномочному процессу с basis document и review, без новых ролей.
   Последствие: импорт сохраняет raw и reconciliation, прошлые деньги/связи не
   переписываются автоматически; неизвестную дату не заменяют датой загрузки.

### Compatibility, rollback и приёмка будущего кода

Совместимость: opaque ObjectId/URL и company ID сохраняются; native POST upsert,
registry CREATE, status confirmation и DTO/null semantics характеризуются
отдельно. Closed остаётся доступным в registry/history/read API под прежними
ACL; active network и historical population получают явные разные definitions.
Счётчики, list/detail и export сравниваются для **одинакового principal, population
и даты**, а service export не выдаётся за user export. Product monitoring current
status маркируется current, а asOf относится только к наблюдаемым агрегатам.

Rollback: W1 без data rewrite откатывается code revert, но guards и DELETE409
не отключать ради старого клиента. После начала ledger wave старый код, который
пишет status/number напрямую, несовместим: до rollback выключить writer adapters
и imports, сохранить read access, проверить event/projection delivery. Expand
добавляет данные, не удаляет legacy columns; destructive down migration и alias
cleanup не входят. Перед любым реальным schema rollout отдельный свежий backup,
restore rehearsal, source drift и ограниченное окно приёмки; этот отчёт их не заменяет.

Тесты **следующего implementation PR**, здесь только требования:

- Настоящий PostgreSQL в выделенной synthetic DB: manual↔import конкурентные
  edits, import↔external mapping/inventory/export freeze race, unknown/foreign
  tenant и O/G/EMPTY scopes, невидимая number collision, несколько writers без
  legacy unique index. Проверять outcomes/state, а не вызов helper.
- Replay intent с тем же body и конфликт с иным; Unicode/space IDs, deterministic
  legacy ID, lost response; before/after alias, закрытый номер, historical ID,
  rollback после audit/link/reservation; отсутствие двойного audit/projection.
- `[from,to)` на границе/в тот же день, overlap/non-overlap, wrong company/parent
  basis, backdated/future/repeated close, open→close→correction; реальное наличие
  EXCLUDE отдельно, не по startup comment.
- Матрица point closed/station withdrawn/disposed/warehouse reopened при неизменных
  historical sessions, payment/contract/doc IDs и posted amounts; negative case:
  backfill не переселяет closed point по старому номеру.
- Полный список через cursor и count/detail/export при одинаковой population;
  current и selected past date; retired station из historical equipment не
  расширяет текущие object grants; status asOf не выдумывается из today.
- Cancel/receipt/delete и AC/DC sharing: прошлые placed_at не удаляются,
  number не переиспользуется, неоднозначное соответствие требует reconciliation.

## 9. Проверка и статус этого документа

Выполнен source review, проверка ссылочных файлов/строк и SHA256 manifest,
`git diff --check`; diff ограничен двумя названными документационными файлами.
Исполняемые тесты не запускались: изменения prose/manifest не требуют SQL,
bootstrap или app import. Результаты прежних тестов LOCATION_COMMANDS не выдаются
за новый прогон. Live DB constraints, фактические writers/данные/нагрузка,
применимость текущих статусов к каждому объекту и выпуск остаются **UNVERIFIED**.

Документ завершает bounded карту M05, но не M05 целиком. Готовый следующий шаг
для review: A–C; D/E и отдельная event/reservation wave нужны перед реальным
temporal retirement. Публикация retire API, изменение ACL и изменение рабочих
данных не выполнены и не следуют из наличия этого плана.


Независимая сверка координатора после переноса dc54b38d как f9b6cf4c:
все59Ledger и5deploy blobs совпали по SHA256 и размеру с manifest на его
закреплённых ревизиях. Source/policy выводы остаются bounded исследованием.
Для W16 назначен отдельный implementation пакет: обязательный доступ к target
и связь DELETE с объектом из URL. Он не меняет временную семантику закрытия,
commit ownership или публичный API retirement.
