# M06-R3: классификация и срок договора во внешнем чтении

Статус: ROOT source review, new103, отдельная regression84 и official SDK15
generation/consumer acceptance завершены PASS. Ветка `agent/api-contract-classification-read-20261031`, база
`f711bd65ee20d62e206b5e977dca23d1b1f604a6`. M06 целиком этим пакетом не закрывается.
Выпуска, включения flags, изменения моделей/bootstrap/рабочих данных не было.

## Публичный контракт

Contract list/detail теперь всегда содержат **required nullable** `typeCode` и
`validUntil`. `typeCode` берётся только из `Contract.type_code`: без trim,
case folding, enum, lookup-подстановки или вывода из title/номера/type/kind/raw.
Null, пустая строка, неизвестный и custom code сохраняются.
`validUntil` берётся точно из `Contract.valid_until`: строка до 20 символов либо
null, без обещания `format:date`. Пустая/неISO/невалидная календарная строка
не исправляется. Null означает неизвестный source value, не «бессрочный».
Поля не получили default/optional ради старой fixture; transport fixture
дополнена двумя явными null, assertions остаются.

`GET /api/v1/contracts` принимает дополнительный `typeCode` (1..256 символов,
без NUL, с точным сохранением регистра и пробелов). Фильтр равенства применяется
в том же Query owner после текущих tenant/grants/own-org/object predicates и до
count/limit. Он сочетается с прежними q/dateFrom/dateTo/pageSize/cursor.
Date filters по-прежнему относятся к created_at; validUntil не превращён в
дополнительный фильтр и не сравнивается эвристически. Прежний binding owner
включает новый query value; смена кода/другого фильтра/current authority делает
cursor недействительным. В остальных ресурсах typeCode query запрещён.
Длинный source code доступен в Contract, но фильтр/metadata имеют явный limit256.

ROOT решением `msg_0925d3f8a69a` согласовал новый
`GET /api/v1/contract-types?typeCode=...`, operationId=`getContractTypeMetadata`.
Это read метаданных кода, встречающегося у независимо доступного договора.
До lookup глобального справочника Query проверяет EXISTS Contract с точным кодом
через прежний `conditions("contracts")`. Нет такого видимого договора → 404,
даже если код глобально настроен или встречается у другой компании.
Есть видимый договор, но нет catalog row → 200 с кодом и nullable metadata.
Inactive catalog row сохраняет историческую подпись и `isActive=false`.

Ответ строго: `typeCode, label, gkBasis, direction, isActive`; все поля required,
metadata nullable. Query строго один required typeCode 1..256 без NUL; непустой
body → 422 до domain lookup. Нет перечисления global catalog и скрытых типов,
нет count договоров в metadata, catalog не служит доказательством допуска.

В итоге 15 GET: прежние 14 operationId/auth profiles сохранены; новый contracts
endpoint допускает user/service на `contracts:read` и независимом typed grant.
Итого 11 user/service и четыре user-only. Новых scopes, grants, principal kinds
и обходов module/own-org/object/tenant ограничений не введено. ContractObjects и
ContractDocuments methods/handlers/ACL не менялись. GET не пишет и не flush/commit.

## Источники и честные ограничения

- `models.Contract`: type_code Text nullable — наш classifier; type String100 —
  исходный текст; kind String40 — транзакционный ВидДоговора1С.
- `basis_type` в текущей модели отсутствует: native поле называется basis,
  хранит свободный текст основания. Новые type/kind/basis поля API не вводятся.
- Native `references_router._contract_resp` отдаёт source typeCode/validUntil;
  CREATE/PATCH через `_check_type_code` требуют active global catalog row.
- `database.py` создаёт `contract_types(code,label,gk_basis,direction,is_active)`
  глобально, без company_id. Seed/backfill содержит rent/energy_supply и другие
  коды, но не задаёт закрытый публичный enum. API не повторяет bootstrap inference.
- Native manual validUntil принимает строку; импорт 1С использует `_clean_1c_date`.
  Поэтому ISO-формат нельзя обещать всем сохранённым значениям.

Самостоятельный клиент читает typeCode из разрешённых list/detail, при необходимости
запрашивает scoped metadata и использует точный код в фильтре. Читать исходники
или угадывать юридический смысл из номера/названия ему не требуется. Metadata
показывает справочную подпись, не подтверждает актуальность/юридическую силу бумаги.

## Проверка и граница исполнения

Worker выполняет read/AST/compile в памяти/Git, app/tests/runner не импортирует;
collection, SQL, installer и codegen выполняет только ROOT после frozen review.
Подготовлены 103 новых real OAuth/HTTP/PG cases: две компании, user/service,
ALL/SET/EMPTY/MISSING grants, current module/own-org/object ceilings, точный фильтр
и q/date/cursor/revoke, null/empty/unknown/inactive/custom codes, metadata gate до
catalog SQL, прежние independent query/body/principal negatives, source-valued
required schema и persisted business/auth/files equality после auth setup.

Runner использует строгие функции ROOT `chat_access_owner_approved.py` SHA
`e73078ee529fa60e1cb5fc5190a46990c70c15e99f7b87d117415a05cf00fada`:
exact candidate77, five import IPv6 suppression/restore, native owned buffers-only
PG sendmsg с16 source controls, clean env/seed до cached Settings, write/process/
network guards. Новая серия собирается один раз; отдельная regression84 использует
её fixture plugin без collection этого модуля. Primary/subtest outcomes раздельны,
failed/skipped/xfail не допускаются. ROOT владеет отдельной
`api_contract_classification_test_20261031`, fresh CREATE/normal DROP и receipts.
Рабочую БД, main/lifespan и другие пространства worker не запускает.

## Что остаётся в M06

Этот пакет даёт чтение классификации/срока и scoped metadata, не создаёт write API.
Отдельно остаются partner CREATE/PATCH contracts с явным null-intent, replay и
conflict semantics, проверкой сторон и type catalog, typed write grants/current
module scopes, а также cross-channel identity и ручное разрешение неоднозначных
сопоставлений. Native write-owner и его locks/validations не подменяются внешним
read DTO. Полная приёмка main composition, общий M00–M19 status, интеграция и
следующий выпуск принадлежат ROOT. PR78/54 draft и flags OFF сохраняются.

## Фактические ROOT receipts

V1 runner SHA `f9ad9dbe66982d6f2040bf18cb59be6a9f715accad424eecbd7c19812cc7bdb0`
и frozen источники не менялись между source review и обеими сериями.

| Серия | Фактический результат | Время tests / outer |
|---|---|---|
| new103 | 103/103 PASS | 229.37 s / 233.952 s |
| regression84 | 84/84 PASS, отдельно 152 subtests PASS | 35.91 s / 41.888 s |

ROOT независимо сверил boundary/JUnit/failures/source: exact77 и16 controls PASS,
forbidden0. Fixture lifecycle новой серии: env103/db103/password_hash1/database1,
captured notify309; regression: db57/api57/env0, captured delivery0. Product GET
immutability проверена после явно отделённой auth/catalog fixture setup.
Обе exact DB штатно DROP: new338/reg339 relations, оставшихся clients0, exists0,
max_locks64. Единственное pytest-предупреждение относится к record_property/xunit2,
тестовых failures/skips/xfail нет. Серии раздельные, полный CI/main acceptance
этим не заявлен. SDK receipt принят ниже; исходники app/tests оставались frozen.

Private receipts ROOT:
`.artifacts/root-contract-classification-review-20261031/{new103,regression84,independent-results.json}`.
Worker по-прежнему не исполнял app/tests/SQL/codegen.

## Official SDK15 ROOT

ROOT выполнил official openapi-typescript 7.10.1 generation (3.944 s) и freshness
(3.625 s). Шесть прежних generator tests не менялись: **6/6 PASS** (25.953 s).
Фактическая компиляция всех четырёх consumers: **4/4 PASS** (2.583 s). Новый
classification consumer содержит десять negative checks: required nullable source
fields и metadata, required query, tenant selector, request body/write surface;
не вводит выдуманный enum или date-тип. `.d.ts` вручную не редактировался.

ROOT передал три файла для поимённого commit: generated types, новый
contract-classification-consumer и tsconfig. SHA256:

- `src/generated/partner-api.d.ts`: `570c4f648a31626a83bfcb79f74c4995e761b5ba12f17ae161a8ec158c959abb`
- `tools/partner-api-types/contract-classification-consumer.ts`: `2efa77f5787fe94c7d7868ac8b9d4aa95e9444dcdb774e5cc7b2000dadab48d6`
- `tools/partner-api-types/tsconfig.json`: `02f89cf9edfb497dde5d5c8d904de6f4b223e048fad9213c5de9e40edd11998d`

Private SDK receipt ROOT:
`.artifacts/root-contract-classification-review-20261031/sdk-result.json` и
`sdk-evidence-test/`. Worker выполнял только source/AST/compile/Git и отчёт.
Полный CI, write/identity остаток M06 и цель M00–M19 этим не закрыты; следующий
владелец интеграции/выпуска ROOT, PR78/54 остаются draft и flags OFF.
