# Состояние сети и агрегаты зарядных визитов объекта

[Начало](../onboarding.md) · [Вход](../auth.md) · [Словарь](../data-dictionary.md) ·
[Ошибки](../errors.md) · [Каталоги](read-catalogs.md) · [Договоры](contracts.md) · [Документы](documents.md)

Candidate/default-off; база Source `24af3535565381d46f9e51c2841c2feb80b1c8f3`.
Здесь два метода чтения user/service профиля energy. Полный состав — в
[канонической таблице 18 операций](../../PARTNER_QUICKSTART.md#current-source-contract-20261101).
Автор DX не запускал HTTP/schema/runtime; примеры вымышлены и не являются измерением.

<!-- operation:getNetworkState -->
## getNetworkState

Требуются **`objects:read` AND `monitoring:read`**, typed objects grant и текущие
права пользователя либо approved service. Финансовый модуль сам по себе не
разрешает операционный мониторинг; Core admin bearer здесь не требуется.
Метод читает только разрешённые текущие обслуживаемые точки `energy`.

Query: `pageSize` 1..200 (default 50), необязательный `cursor` 1..4096,
`asOf` — ISO date от `2000-01-01` до сегодня МСК, `region` — до 20 непустых
точных токенов через `|`, суммарно 1..200 символов; `onlyProblems` — строго
`true`/`false`, default false. Не передавайте `days`, tenant или финансовый отбор.
GET body отсутствует. Все значения ниже вымышлены:

```http
GET /api/v1/monitoring/network-state?pageSize=50&asOf=2026-10-30&onlyProblems=true HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

Вымышленный полный DTO для одной активной станции без наблюдений; это иллюстрация,
не сохранённый ответ сервера. В нём явно присутствуют nullable и все status keys.

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "items": [{"objectId":"Учебная точка 1","status":"working","lastChargeAt":null,"silentDays":null,"mismatch":true}],
  "summary": {
    "stations": 1,
    "mismatch": 1,
    "byStatus": {"working":1,"no_link":0,"disabled":0,"decommissioned":0,"on_repair":0,"maintenance":0,"not_working":0,"unknown":0}
  },
  "context": {
    "asOf": "2026-10-30T23:59:59.999999+03:00",
    "dataThrough": null,
    "dataLagHours": null,
    "requestedDate": "2026-10-30",
    "catalogMode": "current",
    "boundaryScope": "authorizedOperatedRegion",
    "availability": "unknown"
  },
  "nextCursor": null
}
```

`mismatch` означает native `working` без зарядки либо более семи календарных дней
молчания МСК. Пять полей строки — весь опубликованный item; денег в нём нет.
`summary` — по всему отбору M после `onlyProblems`, до страницы. Boundary берётся
по доступному обслуживаемому региону до `onlyProblems`. `asOf` ограничивает
наблюдения концом дня МСК, но каталог и статусы остаются текущими. `dataThrough`
может быть позже исторического asOf; null и `availability=unknown` не заменяйте
нулём или утверждением об исправности сети.

Порядок — точные UTF-8 bytes `objectId`: не trim, не UUID-parse и не нормализовать
Unicode. При ненулевом `nextCursor` передайте его целиком URL-encoded и повторите
исходные фильтры и pageSize. Каждый запрос заново проверяет актуальный доступ.
Cursor связан с operation/version, правами, отбором, pageSize и scoped boundary;
общий snapshot не обещан. Изменённый либо чужой cursor, binding или boundary:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{"type":"about:blank","title":"Bad Request","status":400,"code":"invalid_cursor","requestId":"80000000-0000-4000-8000-000000000001","detail":"Cursor is invalid or belongs to another query"}
```

После 400 отбросьте частичный обход и начните без cursor с теми же фильтрами и
pageSize. При смене пользователя/компании/grant/политики также нужен новый обход.
401 требует актуальной авторизации, 403 — решения владельца доступа, без расширения
отбора. 404 может означать профиль, отличный от energy. Неверный query (например
`onlyProblems=1`, будущий `asOf`, неизвестный `sort`) или непустой GET body — 422
`invalid_request` после применимых auth/quota checks. Квота 429 `rate_limited`
содержит `Retry-After`. Admission/timeout даёт 503 `api_unavailable` без частичного
успеха: 10000 текущих разрешённых сетевых кандидатов до owner/region, read и local
SQL deadline 5 s. Это инженерные ограничения, не SLA или доказанная ёмкость.
У 500 общий `internal_error`; неожиданный отказ не является концом пагинации.

Далее сверяйте [словарь](../data-dictionary.md#networkstate-обслуживаемая-сеть-без-финансовых-полей).
<!-- /operation:getNetworkState -->

<!-- operation:getObjectMonitoring -->
## getObjectMonitoring

Требуются **`objects:read` AND `monitoring:read`**, самостоятельный typed objects
grant, current actor и компания профиля `energy`. Для сотрудника scope monitoring
связан с актуальными операционными модулями (`ops`, `ops:ops_state`,
`ops:ops_reliability` либо полным доступом); финансовый `ops:ops_overview` его
не заменяет. Наличие объекта само не расширяет ранее выданное согласие.

Возьмите exact ObjectId из [каталога](read-catalogs.md). Допустимый query — только
`days` (1..366, default 90) и `asOf` (строго `YYYY-MM-DD`); pageSize/cursor здесь нет.
GET body отсутствует, origin HTTPS:

```http
GET /api/v1/objects/20000000-0000-4000-8000-000000000001/monitoring?days=7&asOf=2026-10-30 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <PARTNER_ACCESS_TOKEN_PLACEHOLDER>
Accept: application/json
```

Полный 200 DTO ниже предполагает наблюдаемую сессию в конце выбранного дня.
Давность 12 часов здесь вымышлена для объяснения provenance.

```http
HTTP/1.1 200 OK
Content-Type: application/json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
```

```json
{
  "pointId": "20000000-0000-4000-8000-000000000001",
  "status": "working",
  "window": {
    "days": 7,
    "start": "2026-10-23T18:00:00+03:00",
    "end": "2026-10-30T18:00:00+03:00",
    "timeZone": "Europe/Moscow",
    "interval": "inclusive"
  },
  "totals": {
    "sessions": 3,
    "visits": 2,
    "successfulVisits": 1,
    "unsuccessfulVisits": 1,
    "energyKwh": 12.5
  },
  "lastSeenAt": "2026-10-30T18:00:00+03:00",
  "provenance": {
    "asOf": "2026-10-30T18:00:00+03:00",
    "dataThrough": "2026-10-30T18:00:00+03:00",
    "dataLagHours": 12.0,
    "requestedDate": "2026-10-30",
    "catalogMode": "current",
    "snapshotNote": "Сессии — на выбранный день (МСК). Состав парка и паспортные статусы — текущие; история состава не восстановлена.",
    "boundaryScope": "object",
    "source": "charge_sessions",
    "visitSuccess": "any attempt energy_kwh > 0"
  }
}
```

Отказ, например нет monitoring scope или достаточных ресурсных разрешений:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
WWW-Authenticate: Bearer realm="product-api"
```

```json
{"type":"about:blank","title":"Forbidden","status":403,"code":"access_denied","requestId":"80000000-0000-4000-8000-000000000001","detail":"Access is denied"}
```

Следующий шаг при отказе: сверить **оба** scopes, typed objects grant и текущие
модули с владельцем; при необходимости получить новое согласие. 404 не позволяет
отличить отсутствующий/недоступный объект от неподходящего профиля компании.
Не обходить отказ company-wide запросом или внутренним мониторингом.

После 200 показывайте окно, статус и provenance вместе. Для следующего объекта
используйте его собственный ID и boundary; watermark другой точки или всей
компании здесь не подходит. Сохраните unknown/null поля без подстановки нулей.
<!-- /operation:getObjectMonitoring -->

## Как читать время и totals

Окно **включительно** `[end − days, end]` по Europe/Moscow, с явным `+03:00`.
End — наблюдаемая верхняя граница сессий этого объекта, ограниченная концом
`asOf` дня (23:59:59.999999 МСК), либо текущим временем при отсутствии boundary.
Если наблюдения закончились раньше, end также раньше requested дня. Это не семь
полных calendar days и не UTC created_at отбор из каталогов.

`provenance.asOf` — фактический end, `requestedDate` — исходный query день.
`dataThrough` отражает последний started_at в доступном ряду объекта и может
оказаться позже исторического end; `dataLagHours` считается от текущего времени,
а не от asOf. При отсутствии наблюдений `dataThrough/dataLagHours/lastSeenAt`
могут быть null. Zero totals в таком случае не доказывают исправную работу.

Sessions и visits разные: несколько попыток могут относиться к одному визиту;
успех визита — хотя бы одна попытка с `energy_kwh > 0`. Энергия суммируется
по исходным данным и только затем округляется; `energyKwh` измеряется в кВт·ч.
Это не показатель мощности из equipment.powerKw.

Статус здесь текущий, ограничен опубликованными значениями
`working`, `no_link`, `disabled`, `decommissioned`, `on_repair`, `maintenance`,
`not_working`, `unknown`. Неизвестный исходный operational status становится
`unknown`. Паспорт и состав парка также текущие, что прямо записано в
`catalogMode=current` и snapshotNote. Historical asOf не восстанавливает
паспортное состояние, состав оборудования или работу с заявками на прошлую дату.

Метод не публикует raw sessions, клиентов, заявки, деньги или SLA. Он не заменяет
полный operations процесс, историю состава сети или финансовый отчёт.

## Свидетельства исходников

Исторические ссылки строк для object monitoring на
`9eb236a4d69f0452208857ac603fd1da515f52d8`:

- `clearledger/server/app/product_api/app.py:108–115,261–334`: required scopes, principal kinds и вызов object-scoped метода.
- `clearledger/server/app/product_api/monitoring.py:14–40`: energy gate, разрешённый объект и object-scoped queries.
- `clearledger/server/app/product_api/dto.py:326–532`: query и полный Monitoring DTO.
- `clearledger/server/app/services/ops_monitor_context.py:8–34,51–101`: МСК, provenance, visits и энергия.
- `clearledger/server/app/services/partner_identity.py:206–235,340–354`: eligible monitoring scopes и текущие user/machine ограничения.

Network-state на принятой базе `24af3535565381d46f9e51c2841c2feb80b1c8f3`:
`product_api/dto.py:NetworkState*`, `product_api/app.py:get_network_state`,
`product_api/network_state.py:read` и `services/network_state.py:operational_network_state`.
Root сообщил backend 75 случаев/225 фаз без ошибок в `msg_11824f7b96be`;
это не собственный runtime автора DX и не приёмка сгенерированного SDK.

Далее: [документы](documents.md) · [ограничения данных](../data-dictionary.md).
