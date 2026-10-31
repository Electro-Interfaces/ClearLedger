# Статус объекта и агрегаты зарядных визитов

[Начало](../onboarding.md) · [Вход](../auth.md) · [Словарь](../data-dictionary.md) ·
[Ошибки](../errors.md) · [Каталоги](read-catalogs.md) · [Договоры](contracts.md) · [Документы](documents.md)

Candidate/default-off; source pin
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`. Один из 15 GET, user/service.
HTTP/schema/runtime **NOTRUN**; пример вымышленный и не является измерением.

<!-- operation:getObjectMonitoring -->
## 11. getObjectMonitoring

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

Commit `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`:

- `clearledger/server/app/product_api/app.py:145–153`: scopes и boundary метода.
- `clearledger/server/app/product_api/monitoring.py:16–40`: energy gate, разрешённый объект и object-scoped queries.
- `clearledger/server/app/product_api/dto.py:123–169`: query и полный Monitoring DTO.
- `clearledger/server/app/services/ops_monitor_context.py:21–35,51–101`: МСК, provenance, visits и энергия.
- `clearledger/server/app/services/partner_identity.py:217–223`: eligible monitoring scopes.

Далее: [документы](documents.md) · [ограничения данных](../data-dictionary.md).
