# Данные, идентификаторы и отборы

[Начало](onboarding.md) · [Вход](auth.md) · [Ошибки](errors.md) ·
[Каталоги](recipes/read-catalogs.md) · [Договоры](recipes/contracts.md) ·
[Мониторинг](recipes/monitoring.md) · [Документы](recipes/documents.md)

Candidate, default-off, source-only. Source pin:
`cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`; schema/HTTP/runtime **NOTRUN**.
Ниже описан текущий wire DTO, не обещание полноты будущих отраслевых процессов.

## Значения и IDs

JSON product API использует camelCase. Все перечисленные поля DTO входят в
ответ, в том числе nullable поля с явным `null`. **Nullable не означает optional.**
`null` — неизвестное/недоступное значение, иногда redacted ссылка. Это не ноль,
пустая строка, отрицательный результат проверки или доказательство отсутствия
сущности. Поля-ссылки проецируются только при независимом доступе к цели.

| Тип | Точное правило |
|---|---|
| `ObjectId` | Native строка длиной 1..40, без NUL; может содержать Unicode и пробелы |
| Остальные `Id` | Непрозрачная строка 1..128, первый символ ASCII буква/цифра, далее буквы/цифры/`_ . : -`; native UUID handler может вернуть 404 для другого формата |
| `date` | Calendar date `YYYY-MM-DD`; nullable там, где указан `null` |
| `datetime` мониторинга | ISO timestamp с явным `+03:00`, Europe/Moscow |
| Открытая строка | Сохраняйте исходное значение, неизвестное отображайте как неизвестное; не превращайте примеры в enum |

IDs не приводят к lower-case, не trim, не собирают из code/номера станции. В
path кодируйте **один** segment корректным URL encoder без повторного decode.
Percent-encoding не решает гарантированную адресуемость `/`, `%`, `?`, `#`, `.`/`..`
и других специальных native IDs всеми proxy/router слоями. Не меняйте такой ID
ради запроса: сохраните значение и согласуйте транспортную адресуемость с владельцем.
Наличие ID в list DTO само по себе не доказывает работу любого path через ingress.

UUID в recipes только вымышленные удобные примеры. Все заканчиваются на
`0000-4000-8000-000000000001`: префиксы `20000000` — object, `30000000` — equipment,
`40000000` — party, `50000000` — contract, `60000000` — document, `70000000` — version,
`80000000` — request. Нельзя переносить такой формат как требование к ObjectId.

## Коллекции, фильтры и время

Корневые `/objects`, `/equipment`, `/counterparties`, `/contracts`, `/documents`
принимают общий набор ниже. У `/contracts` дополнительно есть `typeCode`.

| Query | Формат и значение |
|---|---|
| `pageSize` | Integer 1..200, default 50; фиксируется на весь cursor pass |
| `cursor` | Непрозрачная строка 1..4096, следующая страница; URL-encode целиком |
| `q` | 1..100 символов, case-insensitive SQL ILIKE `%q%`; `%` и `_` работают как wildcard |
| `dateFrom` | Строго `YYYY-MM-DD`, `created_at >= 00:00:00 UTC` включительно |
| `dateTo` | Строго `YYYY-MM-DD`, `created_at <= 23:59:59.999999 UTC` включительно |
| `typeCode` | Только contracts list: exact source code 1..256, без NUL; пробелы и регистр значимы |

Если обе даты заданы, `dateFrom <= dateTo`. Это **время создания записи**, не дата
договора, регистрации, действия условий или последнего обновления. Timestamp в
date query не принимается. `q` ищет только в одном столбце:

| Коллекция | Столбец поиска |
|---|---|
| objects | `name` |
| equipment | `serialNumber` |
| counterparties | `name` |
| contracts | `number` |
| documents | `title` |

Поиска по ИНН, адресу, `objectId`, произвольным атрибутам и custom sort нет.
Порядок фиксирован: `created_at ASC, id ASC`. `offset`, `sort`, `companyId` и
другие неизвестные query отклоняются, а не игнорируются. Detail и download
используют пустой query. Contract relations допускают только `pageSize/cursor`.
Monitoring допускает только `days/asOf`; metadata classifier — только `typeCode`.

Page содержит `items`, `total`, `nextCursor`. `total` считает текущий доступный
отбор **до cursor**, не размер страницы и не глобальный размер компании.
Повторяйте исходные фильтры **и pageSize** с `nextCursor`, пока он не станет null.
Cursor привязан к resource, parent relation, компании, principal/client/install/
grant, scopes, resource policy и фильтрам. Смена отбора/размера/прав требует нового
обхода; invalid cursor — явная ошибка 400, не конец данных.

Пагинация live: между запросами нет общего read snapshot или snapshotId.
`total` может меняться, чтение не является гарантированным историческим export.
Для клиента полезны последовательный обход, собственный deadline и предел страниц,
контроль повторяющегося cursor и dedup по resource ID. Эти клиентские ограничения
не являются серверными квотами или гарантией snapshot.

## Объект: текущая точка обслуживания

| Поле | Тип | Смысл |
|---|---|---|
| `id` | ObjectId | Точная идентичность точки |
| `level` | `servicePoint` | Опубликованный уровень |
| `code`, `name` | string | Исходный код и имя; не альтернативный ID |
| `type`, `status` | open string | Паспортные значения, не мониторинговый enum |
| `address` | string/null | Паспортный адрес |
| `latitude`, `longitude` | number/null | Паспортные координаты; не подставлять 0 при null |

## Equipment: станционное оборудование

| Поле | Тип | Смысл |
|---|---|---|
| `id` | Id | Идентичность оборудования |
| `level` | `station` | Только станционное оборудование текущей проекции |
| `vendor`, `model`, `serialNumber` | string/null | Паспортные реквизиты |
| `powerKw` | number/null | Паспортная мощность, кВт; это не энергия за период |
| `state` | open string | Текущее состояние оборудования |
| `objectId` | ObjectId/null | Текущая independently visible точка; null может означать redaction |

Получите все разрешённые страницы `/objects` и `/equipment`, затем соедините
по точному `equipment.objectId == object.id` на клиенте. Не восстанавливайте
скрытые связи по code/имени/серийному номеру. Нет endpoint оборудования точки и
нет query `objectId` в `/equipment`; уровни site/EVSE/connector пока не опубликованы.

## Counterparty и Contract

| DTO | Поле | Тип и смысл |
|---|---|---|
| Counterparty | `id`, `name` | Id/string; карточка контрагента, группы исключены |
| Counterparty | `inn`, `kpp` | string/null; сохраняйте как строки, null не означает отсутствие реквизита |
| Contract | `id`, `number` | Id/string; идентичность и исходный номер |
| Contract | `date` | date/null; исходная неразбираемая дата проецируется в null |
| Contract | `title` | string/null; заголовок |
| Contract | `isClosed` | boolean; исходный признак закрытия |
| Contract | `scopeType` | open string; режим текущей связи, например `locations` |
| Contract | `counterpartyId` | Id/null; видимая независимо карточка стороны |
| Contract | `typeCode` | string/null; точный source classifier, включая unknown или пустое значение |
| Contract | `validUntil` | string/null, максимум 20 символов; сырое значение срока, **не ISO date** |

Не определяйте юридическую природу договора по догадке о typeCode, заголовку или
списку примеров. `validUntil: null` не означает бессрочность, `""` также не равно
бессрочности; исходную строку сохраняйте без принудительного разбора даты.
Пустой `typeCode` может прийти в DTO, но query metadata требует минимум один
символ: такой код нельзя отправить как допустимый фильтр или metadata lookup.

`GET /contract-types?typeCode=...` не глобальный справочник: нужен независимо
видимый договор с этим exact code. Ответ всегда содержит `typeCode`, `label`,
`gkBasis`, `direction`, `isActive`; последние четыре nullable. Unknown code
видимого договора даёт 200 с null metadata. Inactive код сохраняет историческую
подпись; `isActive: false` не означает автоматически закрытый договор. Не видимый
или не используемый доступным договором код даёт 404.

`ContractObjects` содержит `contractId`, `scopeType`, `items[].objectId`, `total`,
`nextCursor`. Это явные текущие связи с независимо доступными объектами. Для
company/unassigned/другого режима без `locations` возвращается пустой список,
а не вся сеть. Связи не доказывают историческое действие или юридическое покрытие.

`ContractDocuments` содержит `contractId`, `items[].documentId`, `total`,
`nextCursor`: текущие subject/явные graph связи, документы фильтруются своим ACL
до count/page. Чтение связи не выдаёт документы или право на bytes автоматически.

## Document, version и файл

| DTO | Поле | Тип и смысл |
|---|---|---|
| Document | `id`, `title`, `status` | Id/string/open string |
| Document | `registrationNumber`, `registrationDate` | string/null и date/null |
| Document | `currentRevision` | integer, текущая ревизия карточки |
| Document | `objectId`, `counterpartyId` | Независимо видимые ссылки либо null |
| DocumentDetail | Все поля Document + `versions` | До 200 текущих не удалённых/не очищенных версий |
| DocumentDetail | `versionsTruncated` | boolean: выдача versions ограничена; это не полная история |
| Version | `id`, `revision`, `role` | Id/integer/open string; `main` в примере не enum |
| Version | `fileName`, `mimeType`, `sizeBytes` | string/string-null/integer; имя, metadata MIME, размер в байтах |

Отдельного `/documents/{id}/versions` нет; берите разрешённые version IDs из
detail. При `versionsTruncated: true` не заявляйте полноту и не изобретайте
pagination history. Content требует отдельного download scope, native document/
file ACL и согласованной цепочки doc → version → source одной компании.

Wire content — `application/octet-stream`, даже если metadata `mimeType` равен
`text/plain` или `application/pdf`. Это bytes, не JSON и не UTF-8 string.
Generated marker `string/binary` не означает текстовое декодирование.
Общего checksum, Content-Length, Range/ETag/resume или максимального размера
файла этот профиль не обещает. Обработку прерывания см. в [recipe](recipes/documents.md).

## Monitoring

`days` — integer 1..366, default 90; `asOf` — optional строгая calendar date.
Окно включительно `[end - days, end]` в МСК; верхняя граница — последняя наблюдаемая
сессия объекта, ограниченная концом requested `asOf` дня, либо текущим временем
при отсутствии boundary. Это не UTC created_at фильтр каталогов.

| Поле | Смысл |
|---|---|
| `pointId` | Точный ObjectId разрешённого объекта |
| `status` | Текущий `working/no_link/disabled/decommissioned/on_repair/maintenance/not_working/unknown` |
| `window.days/start/end/timeZone/interval` | Длина, timestamps, `Europe/Moscow`, `inclusive` |
| `totals.sessions/visits/successfulVisits/unsuccessfulVisits` | Количество сессий/визитов; успешен визит с любой попыткой energy > 0 |
| `totals.energyKwh` | Сумма энергии в кВт·ч, округляется после суммирования |
| `lastSeenAt` | Последний session started_at объекта не позже end, nullable |
| `provenance.asOf` | Фактическая верхняя граница выбранного окна |
| `provenance.dataThrough/dataLagHours` | Boundary всего доступного ряда этого объекта и давность относительно текущего времени, nullable |
| `provenance.requestedDate` | Запрошенный asOf день либо null |
| `provenance.catalogMode/snapshotNote` | `current` и пояснение о текущем паспорте/составе парка |
| `provenance.boundaryScope/source/visitSuccess` | `object`, `charge_sessions`, `any attempt energy_kwh > 0` |

`dataThrough` может быть позже `asOf`; `dataLagHours` не возраст исторического
окна. Статус и каталог **текущие**, история парка не восстановлена. Нулевые totals
без наблюдений не доказывают исправность или фактическое отсутствие деятельности.
Мониторинг не передаёт деньги, клиентов, заявки и raw sessions.

## Свидетельства исходников

Все позиции закреплены commit `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`:

- `clearledger/server/app/product_api/dto.py:11–255`: типы, обязательные nullable keys, query и DTO.
- `clearledger/server/app/product_api/queries.py:18–23,103–235,238–279`: поиск, UTC, cursor, links и redaction.
- `clearledger/server/app/product_api/app.py:220–237`: versions limit и content route.
- `clearledger/server/app/product_api/files.py:38–84`: binary boundary и file ACL.
- `clearledger/server/app/product_api/monitoring.py:19–40` и `clearledger/server/app/services/ops_monitor_context.py:21–35,92–101`: время, provenance и агрегаты.
