# Команды точки обслуживания: M05/M04

Baseline `94e27132`, 29.10.2026. Это ограниченный slice двух native mutation
входов, не завершение M05/M04 или программы модернизации. Продуктовый API,
identity, финансовые данные, station/site/EVSE/connector commands не меняются.

Канон прочитан в актуальном deploy worktree `partner-api-design-20261029`:
`docs/OBJECTS.md` (§1, §2, §2а), `SPACE.md` (§3, §8–10), `CORE.md` (§1–2).

| Уровень | Runtime |
|---|---|
| Площадка | `EzsSite` / site |
| Точка обслуживания | `ServiceLocation` / servicePoint; только она меняется этими командами |
| Станция | `EzsEquipmentUnit`, отдельная единица оборудования |
| Точка отпуска | `EzsEvse` |
| Коннектор | `EzsConnector` |

Номер точки не становится серийным/инвентарным номером станции. Native passport
продолжает читать station через `station_passport`, не копирует железо в точку.

## Контракт и владельцы

`services/location_commands.py` не импортирует FastAPI, routers и HTTP. Он
возвращает `ServiceLocation` либо `Mutation(location, changes)` и бросает
`LocationConflict(status, detail)`; HTTP wrappers переводят отказ в прежний HTTP
контракт. Команда не вызывает flush/commit, audit, projection и внешние API.

| Use case | Admission | Mutation | Side effects и commit |
|---|---|---|---|
| `POST /api/locations` | членство компании | UPSERT: переданный ID означает ту же точку, tenant неизменяем | прежний native DTO, station passport и single-object projection; commit у `get_db`/caller |
| `PATCH /api/locations/{id}` | прежний `get_owned` + company context | partial UPDATE, обязательные scope/freeze/uniqueness | прежний native DTO и projection; commit у `get_db`/caller |
| `POST /api/registry/objects` | прежний company admin | CREATE нового server ID, никогда не UPSERT | registry DTO и `space.object.create` audit; commit у `space_registry` wrapper |
| `PATCH /api/registry/objects/{id}` | прежний company admin | partial UPDATE | registry DTO и `space.object.update` audit; commit у `space_registry` wrapper |

Audit diff снимается внутри общей команды после получения row lock и reload,
а добавляется в прежнем registry use case. Native не приобретает registry audit
или registry projection. Registry preflight остаётся для совместимости;
авторитетная повторная проверка выполняется внутри команды за барьером.

Команда пересекает текущие object и organization scopes. При ограничении по
organization существующая точка требует compatible ContractLocation/Contract;
unassigned fallback нет. Новая точка без возможности назначить такой контур
отклоняется. Member по-прежнему может менять разрешённую native точку, но не
получает registry admin admission. Вход в другую компанию не переносит старую
карточку даже при членстве в обеих; отказ 404.

## Номер, metadata и идентичность

- До изменения проверяются `code`, материализованный `station_number` и
  `metadata.number`, включая explicit null/empty. Contract, session, accounted
  station и external export вызывают прежний freeze guard, теперь на всех входах.
- Code/name нормализуются по краям; null/blank обязательного поля и null
  sourceBindings дают 422 до изменения, вместо неявного нарушения SQL constraints.
- Native nullable address/description очищаются explicit null; отсутствующие
  поля PATCH сохраняются. Registry продолжает свой прежний exclude-none контракт.
- Отсутствующий number в metadata dict сохраняет номер; explicit null/empty
  очищает его только без freeze. `0` означает номер `"0"`, не отсутствие номера.
- Initial create сохраняет raw metadata и source bindings. Update сохраняет
  import-owned snapshot, legacy numberHistory и ручные source links по прежним
  merge rules. Не вводится новый JSON history writer.
- Уникальность сверяется с code/station_number/metadata.number всех карточек
  компании, включая closed/test, и доступным legacy numberHistory; existing dated
  `ObjectLink(relation='number')` учитывается и после закрытия периода.
- CREATE не обновляет существующий ID. Также нельзя создать ID, который найден
  в сохранившихся ObjectLinks либо registry create/update audit. ID/company_id
  нельзя передать как изменяемые поля общей команды.

## Транзакционный барьер и его предел

Оба входа берут PostgreSQL `pg_advisory_xact_lock`: стабильный domain-separated
ключ ID, затем ключ компании. Он остаётся до caller commit/rollback и защищает
check/insert и duplicate UPDATE между поддерживаемыми командами, в том числе при
отсутствующем legacy partial unique index. Индексы/схема рабочих данных не меняются.

Перед freeze read существующая точка загружается с `SELECT FOR UPDATE` и
`populate_existing`, включая уже загруженную admission identity map. Этот lock
конфликтует с FK key-share проверкой ContractLocation/ChargeSession; если producer
вставил FK раньше, команда ждёт его завершения и читает freeze заново. Если команда
была первой, вставка FK ждёт её commit/rollback. Гарантия рассчитана на обычный
PostgreSQL READ COMMITTED и один mutation use case на транзакцию.

Это **не** общий lock всех импортов и freeze producers. Generic ObjectLink,
equipment inventory changes и ObjectExportLog не имеют FK на service point и
не обязаны брать advisory lock. Их одновременная запись вне этого slice остаётся
gap; blanket table locks и массовая смена чужих writers не добавлены. Проекция
native выполняется в прежней транзакции и может продлить время удержания locks.

ObjectExportLog хранит company/fields/count, но не состав IDs. Поэтому прежний
fallback «любой external log замораживает компанию целиком» сохранён: сузить
исторический log до выдуманных IDs нельзя. Internal interapp projection/log не
вызывает freeze; это проверяется отдельным control.

Первичный источник: [PostgreSQL: row locks, FOR UPDATE и advisory transaction locks](https://www.postgresql.org/docs/current/explicit-locking.html).

## Оставшиеся temporal и five-level gaps

В runtime нет законченной перенумерации с effective date, основанием, закрытием
старого номера и поиском/печатью на дату. Generic ObjectLink допускает такие
записи, но готовая команда/producer номера отсутствует; legacy numberHistory
не заменяет temporal ledger. Замороженный номер через обычные POST/PATCH менять
запрещено. Customer numbering migration не выполнялась.

Нет общего tombstone/retired_at реестра. Для давно удалённого ID без сохранившихся
links/audit невозможно доказать прежнее использование. Абсолютный no-reuse всех
исторических IDs/номеров и temporal retirement требуют отдельного шага, а не
обещания по текущим колонкам. Другие import writers не переведены на эти команды.
**Breaking limitation:** legacy `DELETE /api/locations/{id}` теперь даёт 409
после обычной авторизации и owned/scope lookup; чужой/несуществующий ID даёт 404.
Он больше не удаляет единственное свидетельство технического ключа и историю.
Старому DELETE consumer потребуется отдельная temporal retire-команда; endpoint
не имитирует её изменением status и не предлагает несуществующее действие.
Temporal placement станции, site lifecycle, EVSE/connector mutation и строгая
декомпозиция всех legacy passport readers остаются отдельными задачами.

## Проверки

Только synthetic `api_objects_test` на `127.0.0.1:33546`, явный TEST_DATABASE_URL,
абсолютный отдельный UPLOAD_DIR. База создана в разрешённом локальном контейнере;
прочие БД, VM, рабочие env/данные не использованы. Fixtures используют настоящий
PostgreSQL и настоящие FastAPI routers; projection заменена fixture для запрета
сети. Admission берёт реальные synthetic membership rows, user resolver fixture
не заявляется интеграцией с production identity.

Baseline: **3 FAIL** (после исправления обязательных полей synthetic fixtures):
frozen registry code PATCH возвращал 200; two-tenant upsert возвращал 200 и менял
company; duplicate existing-ID upsert возвращал 500. Лог:
`.artifacts/location-commands-baseline.log`.

Финальный основной прогон: **93 PASS за 22,11 с**, включая новые cases
`test_location_commands` и прежние из `test_location_metadata_merge`,
`test_object_freeze`, `test_location_bindings`, `test_object_scope`,
`test_scope_reaches_screens`, `test_space_projection_batching`. Отдельно прежний
HTTP-модуль `test_location_types`: **5 PASS за 19,35 с**. Итого 98 различных cases;
FAIL/SKIP в финальных прогонах нет. Логи `.artifacts/location-commands-tests.log`
и `.artifacts/location-types-regression.log`. Проверяются оба HTTP контракта,
отказы до mutation/audit/projection, freeze и internal control, scopes, raw data,
null/partial edit, history/retired IDs, caller rollback, concurrent POST/PATCH
без unique index и ожидание незавершённых FK contract/session inserts; обратный
порядок проверяет блокировку FK insert до caller rollback. Legacy standalone
`test_location_contacts_integration` требует другую contacts_test; его guard не
ослаблялся, другая БД не запускалась. Full CI и нагрузочная проверка не заявляются.
