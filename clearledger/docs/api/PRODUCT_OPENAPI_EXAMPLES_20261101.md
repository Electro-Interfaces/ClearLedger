# Сохранение response examples в OpenAPI, 01.11.2026

Статус: **AUTHORED NOT RUN**. Подготовлено исправление metadata и проверка в существующем formal-тесте. Приложение и тесты не импортировались и не запускались; выполнены только статические проверки и compile в памяти без exec.

## Причина и уточнение задания

Исходные 14 fictional JSON200 examples соответствуют текущим DTO. Все пять Page-примеров и обе страницы связей уже содержат nextCursor: null. Object.level и Equipment.level явно объявлены в DTO. Изначальная гипотеза об ошибочных значениях исходника была снята координатором после вопроса `msg_ca750ceeb4dd`; ответ `msg_3dbaf307c667` расширил scope до metadata helper, одного вызова и проверки в существующем formal-тесте. Значения decorators остались исходными.

Установленный FastAPI 0.133.0 завершает get_openapi вызовом `jsonable_encoder(OpenAPI(**output), by_alias=True, exclude_none=True)` (utils.py:571). Encoder передаёт exclude_none в model_dump и далее рекурсивно удаляет dict-ключи со значением None (encoders.py:226–299). Это затрагивает произвольные dict внутри Example.value, включая nullable поля вложенных items. False и ноль этим условием не удаляются. Файлы utils.py и encoders.py прочитаны полностью как текст; ни одна их функция здесь не вызывалась.

Root receipt фиксирует прежний запуск b0aa31e2: 22 primary, из них 20 PASS и 2 FAIL, плюс 152 subtests PASS. Формальная проверка обнаружила пропавший nextCursor; negative control window.start остановился раньше целевого поля на другом неполном примере. Это исторические данные до исправления. Нового PASS в этой работе нет.

## Изменение

`_restore_declared_response_examples(schema, routes)` читает responses настоящих APIRoute, включённых в схему. Адрес значения определяется через path_format, method.lower(), нормализованный status (DEFAULT → default), media либо имя header. Из объявленного контейнера через deepcopy восстанавливаются только присутствующие ключи example/examples. Проверка наличия ключа сохраняет singleton null, False и 0. Named Example refs и сопутствующие summary/description копируются вместе с исходной картой без разрешения ссылок. Schema, response model, body и components этим helper не записываются.

Порядок: get_openapi → новый helper → прежняя инъекция ContractCreateBody → _canonical_object_id_paths → остальные прежние metadata → _describe_http_responses → canonical schema. Public projection делает deepcopy canonical без повторного encoder, поэтому null сохраняется в обеих проекциях. _describe_http_responses остаётся побайтно прежним и создаёт полные Problem/429 examples после этапа encoder.

## Таблица примеров и восстановления

Для всех строк suffix пути: `responses/200/content/application~1json/examples/fictional/value`. Колонка old → new описывает потерю, выведенную из прочитанного encoder; это не новый снимок runtime. Требуемые wire-поля DTO и вложенные типы перечислены ниже и в JSON.

| Example path | DTO | Обязательные поля контейнера | old → new при генерации |
|---|---|---|---|
| GET /objects | Page[Object] | items, nextCursor, total | /nextCursor: missing → null |
| GET /objects/{objectId} | Object | id, code, name, type, status, address, latitude, longitude | полное значение сохраняется без изменений |
| GET /objects/{objectId}/monitoring | Monitoring | pointId, status, window, totals, lastSeenAt, provenance | полное значение сохраняется без изменений |
| GET /equipment | Page[Equipment] | items, nextCursor, total | /nextCursor: missing → null |
| GET /equipment/{equipmentId} | Equipment | id, vendor, model, serialNumber, powerKw, state, objectId | полное значение сохраняется без изменений |
| GET /counterparties | Page[Counterparty] | items, nextCursor, total | /items/0/inn: missing → null; /items/0/kpp: missing → null; /nextCursor: missing → null |
| GET /counterparties/{counterpartyId} | Counterparty | id, name, inn, kpp | /inn: missing → null; /kpp: missing → null |
| GET /contracts | Page[Contract] | items, nextCursor, total | /items/0/validUntil: missing → null; /nextCursor: missing → null |
| GET /contract-types | ContractTypeMetadata | typeCode, label, gkBasis, direction, isActive | /label: missing → null; /gkBasis: missing → null; /direction: missing → null; /isActive: missing → null |
| GET /contracts/{contractId} | Contract | typeCode, validUntil, id, number, date, title, isClosed, scopeType, counterpartyId | /validUntil: missing → null |
| GET /contracts/{contractId}/objects | ContractObjects | contractId, scopeType, items, total, nextCursor | /nextCursor: missing → null |
| GET /contracts/{contractId}/documents | ContractDocuments | contractId, items, total, nextCursor | /nextCursor: missing → null |
| GET /documents | Page[Document] | items, nextCursor, total | /items/0/registrationNumber: missing → null; /items/0/registrationDate: missing → null; /items/0/objectId: missing → null; /items/0/counterpartyId: missing → null; /nextCursor: missing → null |
| GET /documents/{docId} | DocumentDetail | id, title, status, registrationNumber, registrationDate, currentRevision, objectId, counterpartyId, versions, versionsTruncated | /registrationNumber: missing → null; /registrationDate: missing → null; /objectId: missing → null; /counterpartyId: missing → null |

## Декларации DTO

Общий DTO: extra="forbid", allow_inf_nan=False, alias to_camel. Поле без default обязательно даже при nullable-аннотации. Для DocumentDetail наследуются поля Document; для Page[T] T соответствует ресурсу. Все исходные literal values остались прежними.

| DTO | Обязательные wire-поля | Nullable-поля | Допустимые поля с default |
|---|---|---|---|
| ContractTypeMetadata | typeCode, label, gkBasis, direction, isActive | label, gkBasis, direction, isActive | — |
| ContractObject | objectId | — | — |
| ContractObjects | contractId, scopeType, items, total, nextCursor | nextCursor | — |
| ContractDocument | documentId | — | — |
| ContractDocuments | contractId, items, total, nextCursor | nextCursor | — |
| MonitoringWindow | days, start, end | — | timeZone, interval |
| MonitoringTotals | sessions, visits, successfulVisits, unsuccessfulVisits, energyKwh | — | — |
| MonitoringProvenance | asOf, dataThrough, dataLagHours, requestedDate, catalogMode, snapshotNote | dataThrough, dataLagHours, requestedDate | boundaryScope, source, visitSuccess |
| Monitoring | pointId, status, window, totals, lastSeenAt, provenance | lastSeenAt | — |
| Object | id, code, name, type, status, address, latitude, longitude | address, latitude, longitude | level |
| Equipment | id, vendor, model, serialNumber, powerKw, state, objectId | vendor, model, serialNumber, powerKw, objectId | level |
| Counterparty | id, name, inn, kpp | inn, kpp | — |
| Contract | typeCode, validUntil, id, number, date, title, isClosed, scopeType, counterpartyId | typeCode, validUntil, date, title, counterpartyId | — |
| Document | id, title, status, registrationNumber, registrationDate, currentRevision, objectId, counterpartyId | registrationNumber, registrationDate, objectId, counterpartyId | — |
| Version | id, revision, role, fileName, mimeType, sizeBytes | mimeType | — |
| DocumentDetail | versions, versionsTruncated | — | — |
| Page | items, nextCursor, total | nextCursor | — |
| Problem | title, status, code, requestId, detail | — | type |
| ContractCreateResult | contractId, replayed | — | — |

Id: строка 1..128 с `^[A-Za-z0-9][A-Za-z0-9_.:\-]*$`; ObjectId: строка 1..40 без NUL. Все вымышленные ID соответствуют форме. Contract.validUntil допускает null либо строку до 20 символов и не объявляет формат date. Contract.date, Document.registrationDate, MonitoringProvenance.requestedDate используют date; временные поля Monitoring используют datetime. В примерах ISO-даты и datetime с явным +03:00. MonitoringWindow.days ограничен 1..366; счётчики MonitoringTotals и total связей неотрицательны; literal-поля совпадают с декларациями. Формальная проверка schema остаётся за Root.

Явных route examples POST 200/201 в текущем app.py нет. ContractCreateResult требует contractId UUID и replayed bool; новых POST examples не добавлялось. Singleton Problem содержит type/title/status/code/requestId/detail; quotaExhausted и injectedHTTP429 сохраняют полный generic payload. Component ProductInjectedRateLimit использует тот же полный Problem. Header examples сопоставлены с const/pattern и UUID-формой чтением исходника; они создаются после encoder.

## Авторская проверка и обратимость

Расширено только тело существующего test_formal_oas_local_refs_formats_and_examples. Проверка обходит объявления всех включённых routes и сравнивает с каждой проекцией значения example/examples media и headers; JSON-сравнение дополнительно различает False и числовой ноль. Счётчик ожидает 14 объявленных контейнеров в каждой проекции. Добавлены проверки независимости вложенных копий schema и route.responses. Строгий local_examples_gate сохранён и проверяет обе проекции; validator и negative test body остались побайтно прежними. Primary nodeids: прежние 13 + 9 = 22, новых функций и subtests нет. Ничего из этого здесь не запускалось.

Выполнено точное обратное преобразование исходника в памяти: удаление только нового helper с двумя разделительными пустыми строками и единственного вызова возвращает весь app.py к base и по байтам, и по AST. Замена только formal-test source span его исходной версией возвращает весь тестовый модуль к base по байтам и AST. Это доказывает сохранность всех 15 GET handler bodies, POST handler, decorator values/fields, security/readiness, policies, методов, request models и остальных функций. Оба изменённых Python-файла прошли compile в памяти без exec.

## Source pins и границы

Base commit: `9a6abac9c6887fb41ca726e1df20304269bcaf5d`; исходный app.py совпадает с Root commit `b0aa31e2d9e8da8890bff53fcfebc6c5a157d416`.

| Файл | SHA-256 |
|---|---|
| base_app.py | `cff583e1dc7bb66c7b6d4107379185c893214bd2938a347b790adc6bfbc5da93` |
| authored_app.py | `f9b4fa21c862359109cd28fed508c4b43013a5e5886a5151316abe85a57e3b3c` |
| dto.py | `5d7d5de4cb95a80b8f5cf4cfe34bbf03a779b11b1cef27b19c8e81b374739ea8` |
| authored_test_product_openapi_http_contract.py | `c1b71be1f49474f18210c3ea3379ed25c99e7565cfd36f9a522189cd7d9c5778` |
| fastapi/openapi/utils.py (установленный, только чтение) | `16f9adb21f0398af545e744976da8932c165803df60d679efe6bdcf2e7380db6` |
| fastapi/encoders.py (установленный, только чтение) | `5cfb185964b4018bf3ef0ff05cfb225ed53c3af3f7f19bef21cc12c3d5b38c56` |
| fastapi/openapi/models.py (установленный, только чтение) | `e2c633f7f4e05dc34459e12b11b37cedc709fb65ed5c82005a7c8e7d080b7353` |

Полные source paths, строки DTO, SHA исходных тестов, текущие code SHA, исторические receipt/raw SHA и детали обратного преобразования записаны в JSON. Финальные commit/tree и SHA всех четырёх файлов передаются координатору через Orca; hashes самих документов не встраиваются в них во избежание самоссылки.

Worker runtime 0: только filesystem/Git/stdlib AST/hash/json и memory compile without exec. Не запускались приложение, helper, тесты, collection/pytest, SQL/PG, Docker, сеть, Node, браузер или установка; subagents не создавались. Root выполняет свежую независимую source-проверку перед интеграцией, затем actual 22 + 152 и SDK generation/freshness. Исходные SDK16/HTTP70 остаются принятыми неизменными свидетельствами и не объявляются новым PASS.

Текущие объявления содержат только 14 named JSON200 values; singleton media/header examples и route header refs не добавлялись ради покрытия. Их восстановление предусмотрено общей узкой веткой helper и требует проверки Root в пределах согласованного объёма. Schema, DTO, handlers, permissions, identity/DPL, manifest, exporter/generator, SDK, flags и исходные fictional values не менялись. Коммит ограничен четырьмя согласованными файлами, без push/PR/выкатки.
