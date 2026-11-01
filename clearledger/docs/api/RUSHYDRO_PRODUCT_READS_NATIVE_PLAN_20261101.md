# РусГидро: Source-пакет будущей приёмки 25 READ-cases

Статус: **Source only; runtime NOT RUN, collection NOT RUN**. Это новый
сквозной golden существующего API, а не новый API или результат приёмки.
Файл `server/tests/test_rushydro_product_reads_native_pg.py` содержит четыре
параметризованных async test-def и ровно 25 буквальных cases. Проверки Source
не подтверждают доступность приложения, работу PostgreSQL, безопасность всей
системы или прохождение общего CI.

## Матрица

| Группа | Cases | Предмет |
|---|---:|---|
| User positive | 15 | Все выбранные GET через настоящий Authlib Code+S256 PKCE access token |
| Machine document denial | 4 | Настоящий approved client_credentials; GET contract-documents, documents, document, content → 403 access_denied |
| Hidden/foreign detail | 5 | object, equipment, counterparty, contract, document; каждый case делает два GET: скрытая местная запись и чужой tenant → 404 not_found |
| Monitoring golden | 1 | Исторический MSK-интервал: 3 attempts, 2 visits, 1 successful visit; 0.04+0.04 → 0.1 после суммы |

Базовые 17 операций содержат 16 GET и один POST. Выбраны 15 GET: objects
list/detail/monitoring, equipment list/detail, counterparties list/detail,
contracts list/detail/type metadata/objects/documents, documents list/detail
и version-content. `GET /contracts/create-options` и `POST /contracts`
исключены. В буквальных `*_CASES` записаны уникальные case IDs и method keys;
это 25 cases, 30 бизнес-GET запросов с учётом двух целей каждого hidden-case.
Отдельный monitoring positive использует default days=90, golden — days=2,
asOf=2026-10-16. Это не full17 runtime, не полный scope 158/93 native.

Issuer Source запрещает машине `documents:read` и
`documents.files:download` (`partner_identity.live_grant`). Поэтому согласован
реальный machine grant только с `contracts:read`. Четыре 403 проверяют текущую
совокупную границу доступа при отсутствии документных scopes; они **не
изолируют** влияние principal-kind от влияния scopes. Подменять issuer или
расширять разрешения машины ради проверки нельзя.

## Внешний provider и pre-import admission

Единственное согласованное имя pytest fixture — `rushydro_read_factory`.
Provider **не реализован этим пакетом**. ROOT должен передать его внешним
pytest plugin при `--noconftest`, после собственного preflight и native
bootstrap. Значение fixture — фактический session-scoped SQLAlchemy
`async_sessionmaker(AsyncEngine, expire_on_commit=False)`, callable для
`async with factory() as db`, с pool_size=8, max_overflow=0, READ COMMITTED
и общим asyncio loop. Это не wrapper, приложение или готовый HTTP-client.

До app/HTTP/SQLAlchemy/cryptography imports тест требует:

- `RUN_RUSHYDRO_PRODUCT_READS_TESTS=1`;
- `ROOT_APPROVED_RUSHYDRO_PRODUCT_READS=1`, `APP_ENV=test`;
- равенство `DATABASE_URL` и явно переданного `TEST_DATABASE_URL`;
- существующий `partner_test_safety_error` и точный target: loopback
  `127.0.0.1:5432`, database `api_rushydro_reads25_test_20261101`, user `clearledger`;
- отдельный абсолютный тестовый `UPLOAD_DIR`.

В документации нет DSN или ключей. Module guard выражает разрешённую цель,
но не доказывает владение БД и обычную роль. ROOT до импорта независимо
проверяет ordinary role, DB/OID/namespace, действительный target, source и
библиотеки; владеет watchdog, native schema/bootstrap 347, всеми engine/pools
и уничтожением целиком собственной временной PG даже при setup failure.
Старые target guards и providers не изменяются и не заимствуются. Пример
команды запуска намеренно не заменяет отсутствующий admission/provider.

Тест собирает FastAPI с настоящими OAuth/consent routers, монтирует настоящий
`create_product_api`, передаёт factory в product и переопределяет только
`get_db` на новые реальные сессии той же factory. `app.main`, lifespan,
сервер, login, доставка писем, сеть, browser и SSO самим тестом не используются.
ROOT native bootstrap вправе заранее импортировать `app.main` для настоящего
model registry без вызова lifespan/server; тест не проверяет и не чистит
`sys.modules`, не копирует и не заменяет этот bootstrap.
Конфигурация включает OAuth/product и синтетический signer, отключает quota
для ограниченного golden; verifier, Query, ACL и business handlers настоящие.

## Native seed и FK closure

Все данные вымышлены. Два energy tenant, два местных юрлица A/A2 и третье
юрлицо чужого tenant позволяют пересечь company, object и own-organization
ceilings без повреждения реальных данных. Обычный employee имеет role=user,
superadmin=false, именованную роль с equipment/references/docs/ops:ops_state,
object_scope=[O1] и own_organization_id=A. Парольного входа нет; штатный
`token_for` используется только для bootstrap consent. Business positive
всегда использует access token, реально полученный через authorize → consent
GET/approve → Code+S256 PKCE exchange. Проверяются persisted consumed code,
nonce/challenge, request, user grant, token family. Machine использует
confidential client, credential digest и approved machine grant с реальным
Authlib client_credentials exchange; persisted family связан с credential.

Seed учитывает текст актуальных models, native legacy DDL и revision4:

1. Companies → Organizations, CompanyRole, User → UserCompany. Обязательные
   names/slug/profile/INN/password_hash заданы. Остальные nullable FKs пусты.
2. ServiceLocation O1/O2/foreign — настоящие String(40) с Unicode, без UUID
   coercion/нормализации; URL path сегменты кодируются. Counterparty.is_group=false.
3. `contract_types` существует после native bootstrap: seed добавляет один
   синтетический код и literal metadata до Contract. ORM не описывает этот
   legacy FK; нужна настоящая native таблица, не минимальный ORM create_all.
4. Contract → ContractLocation с настоящими company/party/org/object FKs;
   EzsEquipmentUnit.kind=station и current_location_id указывают на эти объекты.
5. DocKind → DocCard → DocRelation; у видимого документа есть subject и graph
   edge к C1, скрытый документ тоже связан с C1. Это проверяет независимую
   видимость и отсутствие дублей, а не право из одной связи. Visible DocCard
   ссылается на скрытого counterparty: публичный counterpartyId обязан быть null.
6. SourceFile и настоящий tmpfile → DocVersion; file_id — native soft link,
   фактическая цепочка проверяется production file handler. Version metadata,
   MIME, size=29 и downloaded exact bytes проверяются отдельно.
7. ChargeSession использует location_id FK, МСК DateTime без tz,
   Numeric(12,3) energy. Три исторические attempts имеют visit-a/visit-a/visit-b
   и energy 0.04/0.04/0; четвёртая позже asOf задаёт object watermark. Скрытая
   и чужая будущие сессии не должны менять watermark видимого O1.
8. App → PartnerClient и CompanyApp → PartnerInstallation → typed
   PartnerResourceScope/PartnerResourceItem → Credential/Grant. FK установки
   на eco_company_apps.id и составной grant FK сохранены. Каждая typed SET
   содержит только два местных ресурса; resource items имеют ровно одну FK
   соответствующего kind. Member/object/org ceilings независимо применяются
   настоящим Source; это проверка их пересечения, не поочерёдная изоляция.

App.code имеет 39 символов при лимите40; client IDs37/45 при лимите64.
Проверены существование constructor/snapshot колонок, nullable/default
поля и порядок обязательных FK по тексту. Native schema347 — prerequisite
ROOT, **не** результат AST или runtime этого пакета: models.py содержит316
Base classes, а полный native registry включает отдельные modules и DDL.
Нужны также пустые native связанные таблицы doc ACL/approvals/delegation,
shared-file policy task/chat/conference/store, auth registry и нативные
функции computed phone columns. Тест их не создаёт и не упрощает.

## Assertions, side effects и cleanup

Все выбранные JSON сравниваются с независимыми fixture goldens целиком,
включая nullable fields и вложенные allowlists. Lists имеют total=1,
nextCursor=null; contract objects/documents возвращают только O1/D1, хотя
посеяны скрытые связанные записи. Общий list default pageSize=50 (1..200),
fixed created_at/id ascending и nullable cursor прочитаны из Source. Новая
выборка не проверяет traversal на нескольких страницах и все invalid queries.
Metadata открытого synthetic type берётся через реально видимый договор;
отключённый catalog flag остаётся читаемым, legal inference не делается.

Monitoring проверяет literal inclusive MSK start/end, requestedDate,
lastSeenAt, object-only dataThrough, current catalog/status, суммы и visits.
Wall-clock dataLagHours проверяется только как неотрицательное число, без
второй реализации часов. Raw sessions, телефон, amount и private metadata
не должны попасть в ответ. 404/403 проверяются целиком как безопасный Problem,
с requestId, content type, cache headers и Bearer challenge при403.

До и после **каждого** business GET независимая новая actual session в read-only
transaction читает `SNAPSHOT_COLUMNS`: выбранные столбцы13 ORM business tables
только двух owned companies, плюс один synthetic contract_types code и bytes
одного owned файла. Это проверка сохранённого выбранного состояния; она не
доказывает отсутствие промежуточного DML, всех побочных записей или изменения
невыбранных полей/таблиц. Auth registry, consent/code/token/family/usage,
user presence и возможный auth audit исключены: issuance пишет по настоящему
Source до business assertions. Break-glass не посеян; его запись использования
здесь не сертифицируется. Общего all-DB equality утверждения нет.

HTTP stream всегда дочитывается и закрывается в async context manager,
клиент закрывается до удаления временного upload подкаталога. `finally`
снимает get_db override и восстанавливает settings. ROOT обязан закрыть все
пулы и уничтожить owned PG; seed-строки намеренно не удаляются вручную из
отдельных таблиц, в том числе при setup failure. Это не реализация внешней
очистки или watchdog.

## Reuse и передача

Read-only переиспользованы паттерны, а не импортированы старые tests:
`test_partner_product_integration.py` — реальные consent/PKCE и hidden list/detail;
`test_product_monitoring.py` — настоящий HTTP/SQL flow, MSK и native visits;
`test_product_contract_objects.py`, `test_product_contract_documents.py`,
`test_product_contract_classification.py` — independent graph/metadata goldens;
`test_partner_docs_portal_native_pg.py` — ordinary-user bootstrap, native
App/CompanyApp FK closure, nonce/code/family assertions и ASGI assembly.
RFC7636 verifier/challenge сохранены как известный вымышленный test vector.

Не перенесены tests.conftest, старые engine/schema fixtures/providers,
create_all/DDL/bootstrap/runner, all-DB snapshot, password-login и delivery
monkeypatches, Query/verifier positive probes или exact target другого набора.
Из tests импортируется только существующий pure safety predicate после opt-in.

Source acceptance: stdlib AST и compile без exec, буквальный count25 и parity
15 READ с17-operation baseline, статическая FK/default/type/allowlist сверка,
pre-import guard, отсутствие запрещённых imports/fixtures/schema owners,
Git diff/check и frozen всех прежних Git entries. Отдельный ROOT admission
ещё должен реализовать внешний provider и действительно исполнить25cases.
Push, PR, публикация, release и runtime этим пакетом не выполнялись.
