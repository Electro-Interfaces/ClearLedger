# HTTP CREATE договора: исходный срез

Статус: AUTHOR / NOTRUN. Исходный код: `0e0cc68ab702e73695b3b0a48325e6fc52e7d8a3`, база: `cdb65361f3207f82283c88da8b431625a5b1804c`. Независимая проверка исходного кода ожидается. Этот документ описывает реализованный код и определения тестов; успешная HTTP/SQL-приёмка здесь не заявлена. Запуск, сборка, exporter, генератор SDK и даже импорт/collection тестов в этом срезе не выполнялись.

ROOT ратифицировал D1/D2 сообщением `msg_dc2f907bf07e`, точное извлечение общего coarse gate и расширение scope до 11 source/test + 2 docs сообщением `msg_85a4864d991c`. Исторические DPL 19/17/12 и GORG pins сохранены; HTTP extension задаёт отдельный SHA authority и обратную AST-проекцию всего исходного модуля.

## Запрос и ответ

Операция: `POST /api/v1/contracts`, путь дочернего приложения `/contracts`, `operationId=createContract`, версия API `v1`, OpenAPI info `1.1.0`, тег «Договоры», scope `contracts:create`. Существующие 15 GET остаются; POST добавляет шестнадцатую операцию. На коллекции разрешены GET и POST; ответ 405 содержит `Allow: GET, POST`. На прочих прежних путях сохраняется `Allow: GET`.

Авторизация: действительный Bearer пользователя с делегированным grant либо confidential machine с фактическим machine grant, `user_id=NULL` и `client_secret_basic`. Обязательны текущая canonical policy и соответствующие flags/principal CREATE-profile. Машина не подменяется объектом User. Успех не даёт разрешения читать созданный договор.

Тело читает только существующий `parse_contract_create_body` в `server/app/product_api/contract_create_body.py`. Он применяет существующую `ContractCreateBody`, проверяет фактический поток до 16384 байт включительно и не доверяет Content-Length. Разрешён application/json с необязательным charset=utf-8; сжатие, повторные JSON-ключи и лишние поля запрещены. Никакая FastAPI Body dependency не читает запрос заранее. OpenAPI requestBody и вложенные definitions получаются из этой же модели через `model_json_schema(by_alias=True, mode="validation")`; отдельной ручной схемы нет.

Пример ниже полностью вымышленный. Идентификаторы необходимо заменить на явно разрешённые текущим профилем и grants; пример не обещает существования справочников.

```json
{
  "kind": "contract-card",
  "creationKey": "10000000-0000-4000-8000-000000000001",
  "number": "Учебный-001",
  "date": "2026-11-01",
  "type": "Учебный договор",
  "typeCode": "synthetic-contract",
  "organizationId": "20000000-0000-4000-8000-000000000001",
  "counterpartyId": "30000000-0000-4000-8000-000000000001",
  "coverage": {"kind": "locations", "locationIds": [" Учебная точка 1 "]},
  "validUntil": null,
  "comment": null
}
```

`creationKey` идентифицирует намерение. `validUntil` обязателен и допускает null; `comment` необязателен. UUID, строки, discriminators и массив из 1..100 location IDs проверяет прежний parser. Location ID остаётся точной непрозрачной строкой; пробелы и регистр сохраняются. Существующий hash-v1 не меняется.

Успех нового CREATE: 201, повтор: 200. В обоих случаях только `{"contractId":"40000000-0000-4000-8000-000000000001","replayed":false}`; у повтора `replayed=true`. Это вымышленный ответ. Intent/profile/grant/generation/hash и скрытые дубли не возвращаются. Заголовок Location и последующее право GET не обещаются.

## Транзакционная граница

1. Canonical Bearer verification и общий coarse CREATE gate выполняются в короткой read Session. Она закрывается.
2. Настроенный budget выполняет свою независимую транзакцию и commit. Отказ по quota происходит до чтения тела и до пяти частей бизнес-записи. При disabled budget quota Session не открывается.
3. Новая request Session/root повторяет canonical verification и coarse gate. Typed request-bound descriptor допускает только CREATE_NEWBORN; он не является SQL authority. `contracts=EMPTY` остаётся EMPTY и не запрещает неизвестный newborn ID.
4. Guard охватывает handler, strict stream parser, serialization, commit и close. Реальный `create_partner_contract(db, bearer, body)` получает именно эту request Session, root и Connection. Он по-прежнему выдаёт фактическую SQL admission через полный issuer, проверяет body/refs/types/current permissions, входит в один B и атомарно пишет пять частей.
5. Ответ сериализуется до caller commit и покидает lifetime только после завершения. Ошибка, отказ handler, отмена или ошибка commit ведут к whole-root rollback. HTTP rollback защищён от AnyIO cancellation. Savepoint, nested root, ранний commit, повторный B и поздние lock keys не добавлены.

Coarse gate извлечён ровно из прежнего flags/scope/principal/confidential-machine префикса `CreateOperation.policy`. Старый issuer использует тот же gate на прежнем SQL snapshot. Новый preflight loader читает только Profile/principals, без B/locks/DML/stamp. Полный body-aware tail, freeze, discovery, parent stage, locks, rechecks, capability, stamp, consumer и replay сохраняются. Обратная AST-проекция восстанавливает весь прежний authority-модуль; это статическое свидетельство, а не runtime-приёмка.

При потере подтверждения commit исход неизвестен. Повтор выполняется новым HTTP-запросом и новым root с тем же creationKey и текущим Bearer; реальный consumer заново проверяет исходный grant, actor, профиль и ссылки. Старый stamp не переносится. Текущая CREATE-авторизация нужна даже для повтора; конфликт проверяется только после неё.

## Ошибки и метаданные

| HTTP | Problem.code |
|---|---|
| 401 | invalid_credentials |
| 403 | access_denied |
| 409 | conflict |
| 413 | request_too_large |
| 415 | unsupported_media_type |
| 422 | invalid_request |
| 429 от quota | rate_limited |
| Прочий application HTTP429 | internal_error |
| 500 | internal_error |
| 503 | api_unavailable |

Ошибки приложения до начала ответа имеют application/problem+json с прежним Problem allowlist. Details не раскрывают входные значения, ID скрытых объектов, наличие intent, hash или profile/grant/generation. Ответы имеют `Cache-Control: no-store`, `X-Request-Id`; requestId в Problem совпадает с заголовком. 401/403 содержат Bearer challenge. Quota 429 содержит Retry-After; у generic 429/503 он передаётся только из доверенной ошибки. Ошибки proxy и обрыв доставки после commit не превращаются в подтверждённый откат.

## OpenAPI и дальнейшая проверка

Protected Swagger сохраняет canonical user+machine описание. Browser projection оставляет только public Authorization Code + PKCE; service credentials не вводятся в Swagger. Offline exporter и generator исходники проверяют точный method/path/operationId manifest 15 GET + POST. Consumer/identity/authority imports отложены до runtime; прежние запреты exporter на auth/config/identity и сетевой/DB I/O не снимаются.

В новом `test_partner_contract_http_create.py` определены 21 тест / 57 параметризованных случаев, NOTRUN. Они используют frozen issuer fixture и внешний ROOT-owned `partner_contract_issuer_factory`: настоящие Authlib user/machine tokens, canonical policy/B/consumer и SQL. Положительных auth/cap/receipt mocks нет; наблюдатели делегируют оригиналам, отрицательные fault injections выделены.

Ожидаются независимый Source review и отдельный ROOT admission для импорта/collection и фактического запуска. FK/foreign/wait/parity gaps прежней программы остаются открыты. Предыдущие ограниченные ROOT-наблюдения компонентных тестов не переносятся на HTTP.

GET create-options, OPTIONS, activation protocol и SDK generation относятся к следующему срезу. Flags/defaults и admin PUT activation сохранены false/без изменений. Generated `partner-api.d.ts` не обновлён; свежесть SDK и CI-pass здесь не заявляются. Это не приёмка whole SQL issuer, API, B, full partner, pilot или release.

Полная исходная программа M00–M19 и 11 критериев передаётся только ссылкой `/srv/projects/preview/contract-create-workflow-20261101/report.json#/original_program`, semantic `4ac5f8535d2f9f0b3c7fb910cad958165b8ff886eb48edc2c68726d09c005345`, counts 20/11, completion=false.
