# Варианты для создания договора: исходный протокол CREATE_OPTIONS

Статус: код и определения тестов, **NOTRUN**. Документ описывает кандидат из
ветки `MagLook/source-only-create-options`, а не работающий API. Приложение,
импорты проекта, сборка, тесты, OpenAPI exporter и SDK generator не запускались.
Полная независимая SourceReview всех 21 файлов и отдельная приёмка ROOT ещё нужны.
Версия API сохраняется `1.1.0`; готовность операции остаётся `candidate`.

База: `c3fd7cf89035cae5bd9317c7e6ac18624e12d136`.
Кодовый срез: `b17a8014ee79b605e6369839048b01b21c84e4a1`, дерево
`5b14cd72c85f4ab7557fe946999afda9b1a57447`. Этот документ и JSON-контракт
созданы отдельным дочерним коммитом; их непосредственный родитель — кодовый срез.
[JSON-контракт](api/PARTNER_CONTRACT_CREATE_OPTIONS.json) содержит хэши 19 файлов
кода и тестов именно этого родителя, без самохэширования документов.

## Запрос и ответ

`GET /api/v1/contracts/create-options`, operationId `getContractCreateOptions`,
тег `Договоры`, OAuth scope `contracts:create`. Сервер регистрирует буквальный
путь до `/contracts/{contractId}`. Принимаются канонический пользовательский
Bearer или одобренный машинный Bearer. Старый READ scope `contracts:read` и
доступ к существующим договорам не требуются; сами по себе они CREATE не дают.
Установка, приложение, клиент, grant, текущий актор и профиль CREATE должны
пройти исходные канонические проверки.

| Query | Правило |
|---|---|
| `resource` | Обязательное: `organization`, `counterparty`, `location` или `type` |
| `pageSize` | Целое 1..100, по умолчанию 50 |
| `cursor` | Необязательная непрозрачная строка 1..2048 символов |

Остальные параметры запрещены. Передавайте Bearer только в Authorization.
Query `token`/`access_token` отвергаются до чтения данных. Тела запроса нет.

Полный вымышленный пример 200, не захваченный runtime-ответ:

```json
{
  "resource": "type",
  "items": [{"value": " Учебный тип "}],
  "selectionVersion": "fictional-opaque-selection-version",
  "nextCursor": null
}
```

Все четыре ключа обязательны, в том числе `nextCursor` со значением `null`.
Каждый item содержит только `value`. Organization/counterparty UUID возвращаются
в каноническом виде; location/type сохраняют точные UTF-8, регистр и пробелы.
Порядок — по байтам UTF-8 по возрастанию. Метки, total, ID профиля, поколения,
пользователя, установки и grant в ответ не входят. Непрозрачный selectionVersion
не раскрывает эти поля. Пустой допустимый домен даёт 200 с `items: []`.

## Авторизация и домены

Новый stage `CREATE_OPTIONS` и `CreateOptionsPreflight` привязаны к точному
request, GET, пути, operationId, principal, tenant и версии политики.
`permissions=()`, database permissions и read receipt отсутствуют. Descriptor
позволяет пройти только этот guard и не служит доказательством SQL-полномочий.
Для options используется `access.configured_verifier` напрямую; подставной
READ verifier из старых transport fixtures не может дать положительный допуск.

SQL-загрузчик находится в новом `contract_create_options.py`. Он получает весь
профиль: оба вида principals, все три вида refs, types, User/Member, существующие
Role с проверкой владельца, home Company и точные machine bindings
company/client/installation/kind/user NULL. Чужой граф не обходится. Исходный
канонический verifier сохраняет прежние проверки владения ресурсами SET;
неиспользуемые raw items при ALL/EMPTY не получают нового native X запрета.

Пересечения вычисляет одна чистая функция `select_create_domains`, извлечённая
из старой E-политики CREATE. Её используют POST и options:

| Домен | Пересечение |
|---|---|
| organization | refs профиля, текущий tenant, own organization |
| counterparty | refs профиля, tenant, текущий resource scope counterparties |
| location | refs профиля, tenant, objects scope, installation locations, Member object_scope |
| type | types профиля и активный каталог |

`object_scope=None` и `[]` различаются для всех ролей, включая admin. Неактивный
посторонний grant или type не запрещает остальные допустимые варианты.
Отсутствие Member у постороннего configured user principal допускается как
стабильное отсутствие на t0; текущий пользователь обязан пройти исходную
проверку действительного членства. Это решение ROOT `msg_7fb666cf8239` сохраняет
фактическую E-семантику. Существующий чужой Role, чужой обязательный ref или
неверная machine binding по-прежнему запрещают запрос.

## Сессии, t0 и завершение

Один общий серверный deadline 10 секунд охватывает все фазы:

1. Короткая сессия канонической preflight-проверки. Она откатывается и закрывается.
2. Quota по прежнему протоколу: если включена, отдельная транзакция самостоятельно
   фиксируется и закрывается. Отказ последующего запроса не отменяет расход quota.
3. Новая чистая actual AsyncSession, привязанная к AsyncEngine. Заимствованные
   Connection, уже начатый root, dirty/new/deleted и последующий multibind/root
   drift запрещены. До первого SQL выставляются `REPEATABLE READ` и read-only.
4. Первый production SQL:
   `SELECT set_config('statement_timeout', :ms, true), pg_current_snapshot()`.
   `ms` округляется вниз и не превышает оставшееся время общего deadline; при
   остатке меньше 1 мс сервер отказывает до SQL. Настройка локальна транзакции.
   Далее каноническая авторизация, весь профиль и проекция читаются на одном t0.
5. Перед DTO повторяется тот же канонический verifier: подпись JWT, expiry,
   wall clock и process gates проверяются снова. Его DB-чтения остаются на t0.
6. Успех, отказ, timeout и cancellation завершают selection rollback и close.
   Ответ выпускается после завершения lifetime; ошибка close не считается успехом.

ROOT ратифицировал этот SQL seam сообщением `msg_9bc0d8801c36`. В PG-определениях
`after_cursor_execute` наблюдает завершившийся **production** SQL на той же RR
Connection. SHOW isolation/read-only выполняются только после него. Вход в
Python-функцию и SHOW сами по себе не доказывают t0. Заявление о поддержке
интерфейса PG16 здесь основано на Source-ответе ROOT, фактического запуска нет.

Отзыв, зафиксированный до t0, запрещает доступ. Отзыв после t0 может не появиться
в этой странице. Повторный verifier не превращает snapshot в свежую DB-проверку
после последнего ожидания. Следующая страница получает новый snapshot и полный
пересчёт. POST после выбора заново проверяет текущие полномочия и может отказать.

В options нет business DML, B/advisory/row locks, SQL stamp, CreateAdmission,
успешного intent, savepoint, промежуточного commit или retry/reset snapshot.
Quota DML находится в собственной транзакции. Новых секретов, runtime flags,
глобальных настроек и административных прав этот пакет не добавляет.

## Лимиты и курсоры

Profile users и machines ограничены 100 каждого; organization/counterparty/
location/type — 100 каждого. SQL limit+1 обнаруживает overflow каждого вида;
частичная страница вместо незавершённой загрузки не выдаётся. Ошибка загрузки,
overflow и timeout дают общий 503. Канонический verifier не объявляется
ограниченным по числу строк этими лимитами: его прежние SQL-чтения охвачены
общим deadline. Производительность и фактическая очистка ещё не проверены.

Используется существующий `Settings.cursor_key` длиной не меньше 32 байт.
Domain-separated HMAC-SHA256 `options-v1` кодирует типы и длины UTF-8, сортирует
множества; UUID канонические, opaque строки не нормализуются. Binding включает
method/path/operation/policyVersion, tenant/app/client/installation/grant,
actor kind и user либо machine client, token ID, scopes, profile ID/generation,
все четыре effective domains, own organization, resource modes/IDs,
installation locations и Member object_scope с отдельными None и пустым набором.

selectionVersion — HMAC binding. Payload курсора содержит только version,
resource, pageSize, lastValue, expiry и digest; отдельный MAC связывает payload,
binding и selectionVersion. Внутренние identity IDs и Bearer в payload не входят.
TTL не больше 300 секунд и не продлевается при переходе. MAC сравнивается через
constant-time compare. Смена ресурса, pageSize, token ID, binding или ключа,
повреждение, устаревание и expiry дают 400 после текущей авторизации. Для нового
обхода уберите cursor. Это advisory pagination, без reservation, CAS или
полномочия на запись; selectionVersion не передаётся POST как доказательство.

## Ошибки и совместимость

| HTTP | Код |
|---|---|
| 400 | `invalid_cursor` |
| 401 | `invalid_credentials` из исходной канонической проверки |
| 403 | `access_denied`, включая отключённый/отозванный CREATE-профиль |
| 405 | `method_not_allowed`, `Allow: GET` |
| 422 | `invalid_request` |
| 429 | Quota: `rate_limited`; generic HTTP429: прежний `internal_error` |
| 500 | `internal_error` вне обработанного lifetime |
| 503 | `api_unavailable`, в том числе deadline/overflow/incomplete load |

Problem использует `application/problem+json`. Приложение добавляет
`Cache-Control: no-store`, `X-Request-Id`; 401/403 содержат Bearer challenge.
Quota 429 содержит Retry-After, generic 429/503 — только когда его предоставил
доверенный обработчик. Ошибки прокси остаются вне этого контракта.

Source manifest теперь содержит ровно 17 объявлений: прежние фиксированные 15
READ (11 user/machine, 4 user-only), прежний POST и новый GET. Шесть READ-тестовых
модулей сохраняют точный oracle старых 15 и отдельные проверки POST/options.
Legacy HTTP CREATE test меняет только тело metadata oracle на exact17; все его
остальные байты и AST сохраняются. Экспортёр и генератор ожидают тот же manifest,
но их результаты не генерировались; `partner-api.d.ts` и `consumer.ts` не менялись.

Whole inverse E восстанавливает raw SHA256
`92beb9c24d6d8e30d58414c00190618ab6f1265aece0ab0b20880250bfd98c18` и весь исходный
AST. DPL overlay сначала проверяет фактический extended raw E, затем применяет
точную обратную extraction и прежние HTTP/GORG inverse-проверки. Исторические
19/17/12 и activation pins сохранены. Сам DPL не запускался. Все 19 защищённых
узлов app.py, включая 15 READ, POST, его metadata и nullable-example helper,
совпали при собственной stdlib AST-проверке автора.

## Происхождение и оставшаяся работа

Разрешение кода: ROOT `msg_b8f342be181a`, переданное позднее прямое разрешение
пользователя `msg_5f5562931d62`. Расширение exact20 до exact21:
`msg_f0d279b06c3c`. Замороженный V1 предшествовал 18 файлам реализации; V2 был
прочитан и проверен перед добавленной body-only правкой legacy файла. Замороженные
дизайны не изменялись. V2 формулировка «код пока не написан» относится к плану;
часть реализации к этому уточнению уже была написана и ещё не фиксировалась.

Написаны 10 unit definitions / 66 AST variants и 21 PG definitions / 68 AST
variants; это статический подсчёт, **не collection и не PASS**. ROOT подтвердил
provider contract (`msg_c659cb3b82bf`, `msg_1542bcb93e2c`): callable возвращает
чистые независимые actual AsyncSession, AsyncEngine даёт минимум два соединения
и отдельные writable сессии. Тесты получают engine через actual connection,
передают дополнительные synthetic users/installations/type_codes в `w.owned`;
очисткой и допуском управляет ROOT. Driver и conftest не менялись.

Остаются fresh independent FULL21 SourceReview, точный ROOT gate перед push/PR,
отдельная actual приёмка канонической авторизации/PG/cleanup/deadline/cursor и
ROOT-owned генерация SDK. Merge и deploy не разрешены. Предыдущие 139 activation,
89 Native, 22+152 Swagger и HTTP70 относятся к прежним срезам, не к этому GET.
Программа M00–M19+11 остаётся незавершённой:
`/srv/projects/preview/contract-create-workflow-20261101/report.json#/original_program`,
semantic `4ac5f8535d2f9f0b3c7fb910cad958165b8ff886eb48edc2c68726d09c005345`,
`complete=false`.
