# Создание договора партнёром: узкий допуск, новый ресурс и два principal

**V2: следующий пакет реализует `POST /api/v1/contracts` для delegated user и явно approved machine principal, без требования читать все договоры.** Отдельный create-profile ограничивает организации, виды, контрагентов и servicePoints. Одна успешная транзакция сохраняет карточку, её связи, intent, audit и право данного principal читать **только новый UUID**. Небольшой `GET /api/v1/contract-create-options` возвращает утверждённые варианты. Existing read SET/ALL/EMPTY, Query predicates и native policy сохраняются.

Это **source proposal**, не реализация, runtime scan или публикация endpoint. Exact base `c1825c51ac7e411d6f08cc52d2669a4efbc14aa9`, ветка `agent/api-contract-partner-write-admission-20261031`; privacy `e9f3b0561f240695e813e100d5edcd9211cdc38b` и bootstrap design `e4a1d373cde70d4f72d8b7f45843dfba20a67670` уже в базе. Worker runtime0, production0, old tests0. Flags OFF. Общая цель20M+11 активна.

ROOT review `msg_07c0e849434d` **не принял архитектуру V1** и потребовал narrow newborn admission, целевой machine CREATE и исправление disk budget. Точные V1 MD/JSON/freeze/92IDs сохранены в `.artifacts/contract-partner-write-admission-20261031/history-v1/`: MD SHA `5583f4a31ea37a461ce87c5a650ddaebc42a947c58ba2366159cd23c84479dec`, JSON `b0ab133704f3e5f4d278c884b457c9960df989a72dbf919733a6f0a6d22fed3b`, freeze `6ff86fc7e5151cc93d6ee772188c31edd1756d16f5d309073166fefde04292f1`. Их исходники не переписаны. V2 сохраняет факты и меняет рекомендации, явно отмечая superseded expectations четырёх старых proposed IDs. Ни один из них ещё не тест приложения.

[Парный JSON](CONTRACT_PARTNER_WRITE_ADMISSION_20261031.json) содержит full-byte manifest, Git blob SHA, source/AST hashes и строки, exact23 future paths/interfaces, **144 proposed cases** и **62 выбранных прежних**, контракты ошибок, timelines и бюджеты. Runtime всех новых сценариев UNKNOWN/NOT RUN. Исторический native extraction59PASS не текущая регрессия.

## Текущие владельцы и действительная граница

- Native `references_router.create_contract` передаёт настоящий User в `native_contract_commands.create_native_contract`. Порядок: `assert_company_member` (company/visit/member, native superadmin bypass) → CP/org validation → identity/hash → shared company/contract barrier → native key/actor/hash replay → exact business duplicate scan → active type lookup/остальные поля → add/flush. Commit/rollback остаётся у `database.get_db`. Partner token не принимается за этого User.
- Native hash использует прежний DTO model_dump без company_id/creationKey, включая defaults; explicit null и omitted default на CREATE эквивалентны там, где так задаёт native DTO. Replay проверяет стороны, но идёт **до** повторной active type validation. Native неполная identity не создаёт новый unique business constraint. Company/key уникальны в Contract; actor — user UUID. App/installation там нет.
- Native CREATE не создаёт ContractLocation даже при scopeType=locations; это проверяет старый golden. Он не вызывает audit/send/register/approval/финансы. Partner locations-команда должна атомарно создать свои реальные связи, не менять native golden.
- `contract_commands.create_imported_contract` принимает уже сопоставленные значения, add/flush и затем публикует Contract в caller ContractIndex. Producer сохраняет ACL/matcher/barriers/raw/index/транзакцию. Импортные source aliases/ambiguity и native identity/replay не взаимозаменяемы.
- `reference_identity.contract_identity` требует непустые number/type и ISO date; `lock_manual_creation` — company/entity **transaction** advisory lock до commit/rollback, общий с импортом. Подменять его session lock или новым runner не нужно.
- M10 `verify_access/live_grant` проверяет RS256/typ/kid/issuer/audience/token_use, token digest/jti, family/expiry/revoke, client/App/CompanyApp/install/company, credential, user/account/token_version/membership/eligible modules. Machine имеет отдельный grant без User. `contracts:create` и create-profile сейчас отсутствуют. Scope catalog расширяется только одновременно с новой admission policy и issuance/live negatives.
- Product `access.resolve` создаёт read/download permissions, закрывает identity session до quota; Query использует другую session. Read Facts после такого await не доказывают write authority. `RoutePolicy` проверяет серверные факты, но сам не определяет доступ к ещё не созданному Contract.
- `Query.contract_domain/conditions` применяет tenant/typed resource/own-org/object predicates до count/limit. При own-org/object ceiling CP/объекты могут зависеть от уже существующего location-scoped Contract. R3 `contract_type_metadata` делает visible Contract EXISTS до global catalog lookup. Текущие15GET не перечисляют свои организации. Dependency name/URL не доказывает ACL.
- Native/current read `validUntil` — nullable source string, не универсальная ISO-дата/бессрочность. `typeCode` — точный source Text, `type` — отдельный text, `kind` — отдельный ВидДоговора1С. `contract_types` global raw-DDL, без company_id и ORM owner. Seed rent/energy_supply не публичный live enum.
- `audit.log_audit` добавляет AuditEvent и планирует dispatch_async **до commit**; для новой no-delivery команды он не используется. Actual AuditEvent user_id/name строковые и позволяют явно атрибутировать service client без fake User.
- В identity object_scope есть truthiness, в product — explicit None distinction. Новая admission обязана пересечь пустые scopes как EMPTY; не переносить разрешающий truthy fallback и не чинить native/прочие handlers молча.

Полные нынешние source refs/строки — в JSON. Исторические native/import/freshness/serialization/identity/R1/R2/R3/SDK/security отчёты прочитаны как pins своих результатов, не как свежий PASS. Нынешние shared helpers вызываются по их owner, не через router import.

## Target authority: user и machine

Обе новые операции требуют AND `contracts:create`, `contracts:read`, `counterparties:read`, `objects:read`, current approved installation и отдельный create-profile. Company/app/installation/grant/actor берутся только из настоящего verified bearer. Body/query/header не выбирают authority. Новый RoutePolicy: owner=contracts, resource_type=`contract_creations`, action=create, policy_version=`partner-contract-create-2`; permission выбирает approved installation/profile как namespace намерения, а не будущий Contract UUID.

**Profile**: current company/client/installation binding, approved flag, `userEnabled=false`, `serviceEnabled=false` по умолчанию; отдельный typed allowset principals; SET org/type/CP/location, без wildcard/ALL. Отсутствующий, пустой либо отозванный профиль — отказ. Каждый org/CP/servicePoint реально принадлежит той же компании; каждый typeCode точный и active при первом INSERT. Профиль не создаёт право по одному OAuth scope.

| Principal | Дополнительные обязательные факты | Actor |
|---|---|---|
| Delegated user | Настоящий User, active account, current UserCompany даже для superadmin, effective references module/полный доступ, profile userEnabled и user ID в allowset; current object_scope и own_organization_id сужают выбранные refs | `DelegatedActor(kind="user",userId,subject,clientId,appId,installationId,grantId)` |
| Machine | Confidential active client + current credential/family/token/grant/install/company, scope approved для service, profile serviceEnabled и **конкретный machine grant ID** в allowset; approved org/CP/location/type и original typed grants/installation ceiling; никаких human membership predicates | `ServiceActor(kind="service",clientId,appId,installationId,grantId)` |

Это typed discriminated union, не User с флагом machine. Отсутствие человека у machine не означает «обойти его членство»: это **другая явная operation authority** от администратора компании, ограниченная конкретными refs и principal. Org всегда выбирается из approved SET, отсутствие human own-org не превращается в ALL. Поддельный machine с user_id закрывает существующий verifier; user не получает company admin из наличия scope.

Для каждого CP и всех locations одновременно нужны profile SET **и** текущий typed counterparties/objects grant, installation compatibility ceiling; у user дополнительно current member object/own-org ceiling. Пустое множество не ALL. SAME-company/name/module недостаточны вместо этих predicates. Native возможности не расширяются; partner authority уже native company-create, но определяется отдельным профилем. В Core native CREATE нет energy-only gate, поэтому новый выдуманный product gate не вводится.

Delegated-first допустим как этап разработки, **не финальный целевой контракт**. Machine CREATE остаётся обязательной частью пакета/приёмки, а не окончательным 403 unsupported.

### Как одобрить principal без циклического grant ID

Для user администратор установки заранее утверждает **реальные user IDs** с текущим членством. OAuth consent позже создаёт настоящий user grant; final live admission пересекает конкретную installation/profile с этим user. Existing eligible_scopes только определяет допустимость нового scope по current modules, не заменяет profile.

Для machine существующий admin `machine_grant` получает optional typed `createProfileId`. Если запрос включает contracts:create, он требует явный matching approved service profile/current admin; в **одной admin transaction** создаёт machine grant и добавляет его UUID в profile allowset. Старый/read grant не становится write grant автоматически. Existing grant можно явно включить через профиль. Никакого нового admin endpoint/общего framework; admin company и credential policy сохраняются. Новый write-scope issuance проверяет profile, а каждый POST и receipt read повторно проверяет current allowset предметным owner. Profile withdrawal даёт403 на CREATE/receipt-derived access, **не превращает весь mixed read+create bearer в invalid_token**: independently granted base read SET/ALL продолжает работать. Existing M10 identity/grant/client/credential/family/account revoke по-прежнему401. Это разделяет identity validity и operation authority.

## First-resource bootstrap без ослабления Query

До INSERT нет Contract UUID и не должно быть `Query.detail` будущей карточки. Предметный create owner проверяет **не существующий договорный граф**, а утверждённый profile org/type/CP/location, реальные same-company строки и current typed grants/ceilings. Разрешение этим refs явно выдал current company admin. Это bounded CREATE policy, а не blanket изменение Query.contract_domain/organization_location/conditions.

Поэтому новая company с нулём Contract может создать первый разрешённый договор и user с assigned own-org, и approved machine. User own-org должен совпасть с выбранной организацией; member/installation/object scope должен включать **все** точки. CP/точка с typed EMPTY/чужая/неутверждённая возвращает отказ. Объекты без соответствующей старой read graph-связи не становятся глобально видимыми заранее: operation-specific options показывает только утверждённые refs под create authority.

Новый `getContractCreateOptions` возвращает org/type metadata и IDs разрешённых CP/servicePoints **только из create-profile ∩ typed grants ∩ current user/installation ceilings**. Catalog types — exact current active rows, org labels — current same-company profile items, никаких `orgs[0]`/угаданных live enum. Предлагаются profile bounds1000 refs, pageSize≤100, stable exact ID/code cursor и отсутствие hidden totals. Exact query: required `kind=organizations|types|counterparties|locations`, pageSize1..100/default50, optional cursor1..4096; extra/query tenant и nonempty GET body422. Ответ discriminated `{kind,items,nextCursor}` без hidden total; refs items `{id,name}` (UUID или ObjectId по kind), types с exact metadata/isActive=true. HMAC cursor связан с kind/tenant/app/install/original grant/actor/current profile generation/ceilings/pageSize. Это новая проекция явно утверждённого права создавать. Она не меняет R3 `/contract-types`: старый metadata GET всё ещё требует независимо видимый Contract.

После atomic ContractLocation реальные links существуют; старый read graph может честно учитывать их. Площадка/site/EVSE/станция/connector не превращаются в servicePoint. Company/unassigned coverage первой версии закрыта; project budget/deadline/actor assumptions не выводятся из соседних endpoints.

## Видимость только новорождённого UUID

**Выбран вариант текущего created-resource receipt, без изменения сохранённого SET.** Durable successful intent одновременно является read receipt. Он создаётся только при реальном новом INSERT и коммитится с Card/links/audit. При business duplicate/отказе/rollback receipt не появляется; нельзя передать произвольный существующий UUID и «благословить» его этим create scope.

Receipt связан с company/app/installation/**original grant**/typed actor/createProfile ID/newborn Contract ID. Для user другое лицо не получает receipt; для machine другое приложение/установка/grant не наследует его. Новый токен/ротация credential в том же machine grant не меняет actor. Same user в новом grant не получает старый receipt автоматически: replay требует независимого current read authority либо 404. Identity/grant revoke закрывает bearer; profile revoke/удаление principal/ref закрывает receipt path.

В `access.resolve/build_facts` только для contracts:read вычисляется named effective scope из **настоящих UUID**:

- base ALL остаётся ALL — это прежняя independently approved authority, не требование CREATE;
- base SET даёт свои прежние IDs плюс точные текущие receipt IDs;
- base EMPTY/MISSING даёт только текущие receipt IDs; без них остаётся прежний403;
- read scope всё равно обязателен; receipt не заменяет OAuth scope и не даёт CP/location/file/document права.

Raw `VerifiedPartnerToken.resource_scopes`, persisted profiles и значения SET/EMPTY не переписываются. Это отдельная явно атрибутированная authority, а не изменение смысла старого SET, не фиктивный ALL и не pseudo-ID в read permission. После этого **прежние Query.conditions** всё ещё применяют company/own-org/object restrictions до totals. Effective scope и current profile generation входят в cursor authority; без receipt чужой Contract сохраняет прежний404.

Receipt helper перечитывает current profile/allowset, соответствующие org/type/CP/location approvals, verified principal/grant; type-active нужно для новой вставки, не для уже состоявшегося intent. Creation-version сохраняется для audit, но обычный update профиля с сохранением всех approvals не обязан обнулить старые receipts лишь из-за новой generation; eligibility считается по текущим refs. Delete/recreate profile с другим ID закрывает старые receipts. Current base SET/ALL может по-прежнему независимо разрешать Contract после profile revoke.

Prospective bound — до1000 retained created receipts на principal/profile; сверх —503 `create_capacity_exhausted` **до INSERT**, не тихий сброс истории или расширение ALL. Это явный предложенный локальный resource budget, не утверждение о текущем бизнес-лимите. Его тест и итоговый cap ROOT замораживает перед реализацией. Receipt scope materialization ограничена этим cap; нет неограниченного накопления UUID в request RAM.

## Body, результат, errors и официальный SDK

POST `/api/v1/contracts`, operationId=createContract; GET `/api/v1/contract-create-options`, getContractCreateOptions. Цель — прежние15GET плюс options GET и POST: **17 операций**. Canonical/server и browser OpenAPI должны документировать обе accepted OAuth profiles там, где они реализованы; machine secret не помещается в браузер. Swagger browser execution остаётся Code+PKCE view, полный server contract содержит Client Credentials. Не подделывать отсутствие machine в target.

```json
{
  "kind": "contract-card",
  "creationKey": "00000000-0000-0000-0000-000000000901",
  "number": "PCW-SYNTH-1",
  "date": "2026-10-31",
  "type": "Synthetic lease",
  "typeCode": "custom-lease-A",
  "organizationId": "00000000-0000-0000-0000-000000000401",
  "counterpartyId": "00000000-0000-0000-0000-000000000501",
  "coverage": {"kind": "locations", "locationIds": ["A-1", "A-2"]},
  "validUntil": null,
  "comment": null
}
```

Это только synthetic пример. Closed extra=forbid DTO: strict UUID, ISO calendar date, number/type nonblank1..100, exact typeCode1..256, unique raw ObjectId1..40 no NUL, count1..100. validUntil required nullable string0..20, без date-format/«бессрочность» inference; omission422. comment optional/null≤2000, omitted и null эквивалентны CREATE. Coverage discriminator только locations. Поля company/actor/app/grant/raw/source/amount/tax/sign/approval/register/responsible/project/budget запрещены. Типы/юрлица не копируются из frontend defaults.

201: `{contract:<нынешний product Contract>,creationKey,replayed:false}`, relative Location разрешённой карточки. Replay200: envelope с текущей разрешённой projection/replayed:true, не обещание immutable snapshot после дальнейшей правки. Response DTO валидируется до commit; success только после commit. Cache-Control no-store и X-Request-Id всегда. Current GET после CREATE получает именно newly-created receipt, не весь tenant.

| Status | Предлагаемый код и смысл |
|---|---|
| 401 | invalid_credentials: неподходящий JWT/type/token/issuer/aud/expiry или current revoked identity/client/credential/grant/family |
| 403 | access_denied: live identity действительна, но profile/allowset/scopes/current ceiling не допускают operation |
| 404 | not_found: выбранная ссылка чужая/скрытая/неутверждённая/нет доступа к replay result; без ID enumeration |
| 409 | creation_key_conflict или contract_identity_conflict; не выдавать hidden duplicate IDs |
| 413 / 415 | request_too_large / unsupported_media_type |
| 422 | invalid_request / invalid_contract_type; malformed/null/date/unknown или inactive global type |
| 429 | rate_limited + Retry-After |
| 500 / 503 | safe internal_error / api_unavailable; explicit bounded create_capacity_exhausted отдельно в503 |

Current `_problem` не различает эти 409/413/415/422 причины: нужен узкий per-operation typed error adapter без изменения старых GET goldens. Не выдавать HTTP500 за отсутствие commit: транспортный acknowledgement failure может случиться после durable commit, его разрешает fresh same-key retry.

Canonical OpenAPI3.1.0 содержит exact method/path/operationId/scope AND/security, body discriminator/required-nullable/constraints, errors/examples/idempotency/Location/no-store. Exact17 manifest приходит в exporter и официальный generator, не общий allow-any-POST. Существующие15 handler bodies/DTO/read policy и чужие method-not-allowed сохраняются. Для `/contracts` описание405 обновляется точно по новой регистрации.

Wire types ROOT генерирует официальным openapi-typescript7.10.1, не вручную `.d.ts`. Новый consumer использует `operations["createContract"]["requestBody"]["content"]["application/json"]`, responses201/200/problem+json и typed query options. Positive user/server examples, negative tenant/actor/unknown discriminator/missing nullable fields. Ни as never, broad Any, opaqueJSON, ни второй transport. Нынешние4 consumers запрещают POST других ресурсов/связей и остаются byte-exact. Runtime UUID/ObjectId validation не приписывается TypeScript.

## Shared owner, transaction и revoke timelines

Bounded domain services: `partner_contract_policy` (create refs/profile/principal), `partner_contract_commands` (одна команда и atomic intent/receipt/audit), `contract_card_creation` (точный native duplicate scan + typed constructor/add/flush, без ACL/commit). Transport `product_api/contract_write` владеет bounded HTTP admission и завершением transaction. Current identity predicates остаются у partner_identity; новый locked verification seam не копирует JWT/live_grant правила. Services не импортируют routers; no module injection/callback dictionary/framework.

Native сохраняет User/company/parties/type/req/hash/replay/order/defaults и caller commit, делегируя два extracted primitives с reverse AST нормализацией. Остальные native handlers/import producers/Contract schema unchanged. `access.build_facts` извлекает прежнее verified-token→Facts с source parity и отдельно добавляет scoped receipt authority для contracts. Query predicates не копируются/не ослабляются. Shared owner не становится router-shaped facade.

Порядок новой transaction:

1. Проверить gates, Bearer/media и bounded body≤16KiB независимо от Content-Length; duplicate JSON keys/invalid UTF8/неоднозначный объект422. Auth и обязательная distributed quota до дорогих domain selections; bounded parsing до дорогостоящих действий. При выключенном/недоступном budget новый write503, read поведение прежнее. Quota коммитится независимо — это допустимая явно ожидаемая mutation даже при последующем отказе.
2. Реальный verifier + explicit profile/principal admission; private token evidence не сериализуется/логируется. Отдельная domain session/transaction под no_autoflush; company/contract advisory xact barrier до FK/row locks/INSERT.
3. После await — согласованный порядок authority row locks и **тот же** fresh verifier. Затем current typed actor и org/type/CP/location approvals ∩ original typed grants ∩ installation/user ceilings. Не использовать закрытый read Facts/identity-map snapshot как write authority.
4. Intent namespace/actor/hash: replay после current authority и receipt/base read validation; same actor/hash200 без повторного аудита. Иначе first create active type + exact business duplicate under same barrier; Card/flush, all locations/flush.
5. Success intent/receipt на реальном новом UUID + один direct typed-actor AuditEvent; response projection использует свой pending receipt и прежние read ceilings, проходит DTO validation. Commit один в transaction adapter, затем201.
6. KNOWN precommit error/cancel — rollback/reap/no rows/no delivery. CancelledError не превращается в успех. Ошибка/потеря подтверждения commit может оставить durable rows: fresh retry с тем же key определяет outcome, без duplicate. Никакой exactly-once SMTP/outbox гарантии, SMTP вообще не вызывается.

**User timeline:** token verification → company barrier await → canonical locks → fresh token/account/member/CompanyRole/modules/object/own-org/profile/user allowset → resource locks/check → INSERT+receipt+user audit → commit. Member/module/token revoke, committed пока create ждёт barrier, должен закрыть admission; snapshot не даёт права продолжить. Current eligibility revoke в verifier может дать401; действительная identity, но удалённый create allowset/profile даёт403; скрытый ref404.

**Service timeline:** current confidential client/credential/family/grant/install/App/company → barrier → canonical locks/fresh SAME verifier → serviceEnabled + explicit machine grant allowset + approved refs/typed resource ceilings → INSERT+receipt+actual-client audit → commit. Нет User/membership row, имитирующей человека. Credential/family/grant revoke до lock-point401; valid machine с withdrawn profile/allowset403. Credential rotation в том же grant не меняет actor/key, но новая credential должна быть действительной. Отдельно проверяется атомарный admin machine-grant/profile approval, чтобы failed approval не оставлял write authority.

Обоим нужны canonical locks CompanyApp/install/profile/client/App/grant/family/token/credential и соответствующих resource rows; user ещё User/UserCompany/CompanyRole. Existing approve_installation берёт CompanyApp FOR UPDATE, revoke/refresh — family lock. Поэтому **точный глобальный lock order, row predicates и отсутствие обратных await paths — отдельная обязательная freeze граница implementation**, не утверждение, что произвольный FOR SHARE всё решил. Snapshot после lock перечитывается populate_existing/current scalar rows. Revoke, начавшийся после удержания share locks, может commit после create; это честная линеаризация, не отмена уже коммитящегося write. Expiry clock повторяется до mutation/commit boundary.

## Idempotency, actor audit и схема

Namespace `(company_id,app_id,installation_id,operation=createContract,creationKey)`, typed actor сравнивается отдельно. User→service с тем же key в одной installation409. Machine actor — actual client/app/install, не credential UUID: credential rotation same grant replay200; другой grant не наследует receipt. Different app/install не видит чужой intent, но та же business identity всё равно409 без hidden UUID.

Hash v1: SHA256 UTF8 ensure_ascii=False/sort_keys/compact JSON, schema version/kind/валидированные поля/defaults включены; UUID canonical, date strict ISO; location set сортируется как точные строки, без trim/casefold/URI decoding; validUntil:null включён, comment omission=null. Actor/app/install/operation namespace не из body. jti/grant/credential не меняют hash. Это новый command hash, не native model_dump hash и не import matcher.

Contract.creation_* остаются native namespace; partner сохраняет actor/key/hash в отдельном durable success intent. Exact native `contract_identity` и business duplicate scan общие, импортный index/upsert не вызывается. Нельзя выдать receipt на duplicate существующий Contract вместо нового или автоматически его присоединить к профилю.

AuditEvent action `partner.contract.create`: user — actual ID/name; service — user_id=`partner-client:<actual client_id>` (≤100), name actual App label≤255, details actor_kind/client/app/install/grant/contract/request/hash-version. Service FK пользователя NULL. Это атрибуция приложения, не native User/system impersonation. No log_audit/dispatch; no token, secret, full body, запрет unintended delivery. Intent/receipt/card/links/audit atomic.

Предлагаются новые typed ORM/tables: profile header; principal user-FK XOR machine-grant-FK allowset; typed organization/CP/location items с kind/exactly-one constraints; exact type items; durable success intent/receipt. Composite profile↔installation/client/company FK переиспользует нынешний unique tuple. Same-company также проверяется на admin approval/use, простой org FK не объявлен tenant proof. Global raw-DDL typeCode не получает выдуманный ORM FK.

Intent хранит immutable namespace/typed actor identity/original grant/createProfile/newborn ID; nullable user FK SET NULL для user, service user FK NULL; contract FK SET NULL плюс immutable ID tombstone. Не блокировать native delete новым RESTRICT и не удалять key history через installation/app/user CASCADE. Deleted/hidden result404, не recreate. Profile generation для audit/current cursor, eligibility по current поля/allowset. Company retention определяется отдельным existing lifecycle решением, не предполагается.

Только существующий `schema_migrations` framework: ROOT назначает next ordinal после bootstrap-owner handoff; SQL+metadata contract+catalog verifier+manifest, fresh/upgrade/repeat/exact adoption, mismatch failclosed. Нет CREATE при GET/POST, второго runner, прямого live ALTER или правок чужих main/database/gate. Rollback — flags OFF/убрать две registrations, сохранить additive tables/history, no DROP business data. Старый код игнорирует новые таблицы, native поля сохраняются.

## Точный будущий diff и source review

JSON `future_package.files` содержит **23 пути**: product app/dto/access + new contract_write; new partner policy/commands/shared primitive + native command extraction; partner_identity locked/default scopes, schemas_partner, bounded installation **и existing machine_grant** adapters; new models_partner_contracts; manifest/3 ROOT-numbered revision artifacts; exporter/official generator/generated types/new consumer/tsconfig; new test/helper. `NNNN` явно proposed ordinal placeholder, не существующий путь; исполняемый wrapper сейчас не написан.

Не нужны references_router/PATCH/import producers/Contract ORM/main/database/schema runner/gate/common auth/Query bodies/frontend transport/UI/deps/version edits. Другая необходимость возвращается ROOT до edits. Current Corebootstrapworker исключительный владелец startup/schema runner/gate; производство implementation только новой authority после handoff. Не уменьшать source protection ради нового scope; exact changed-file/function AST, all-other-app bytes и old assertions проверяются ROOT.

Вопросы ROOT технические: принять bounded explicit create sets и оба principals; newborn receipt/first-resource CREATE policy без Query relaxation; lock-order/verifier seam/schema sequencing; resource caps/ошибки/retention. Это не вопрос МАГу о безопасных implementation choices. Полномочия finance/approval/project/responsible и остальные бизнес lifecycle не выводятся из scope.

## Falsifiable acceptance: 144 новых +62 прежних NOT RUN

Сохранены92V1 ID с4 явно superseded expected, добавлено52: machine20, newborn18, bootstrap14. V2 groups: identity12/admission20/body22/replay14/concurrency15/options-wire9/machine20/newborn18/bootstrap14 = **144**. JSON содержит каждый ID/status/error/invariant; это дизайн, не collection. Старые IDs с V1 названием про unsupported/ALL имеют V2 expected и явную историю, не менялись старые test files.

Fixed world: две companies/user/apps, свои org/CP/servicePoint UUID/IDs; profile/user/machine allowsets, active/inactive/custom codes, foreign/hidden refs и first-resource мир без Contract. Golden PCW-SYNTH-1, 2026-10-31, Synthetic lease/custom-lease-A, validUntil:null, точно A-1/A-2. Новый Contract UUID генерирует реальный server, берём из201 и сравниваем replay; остальные fixture IDs фиксированы. Schema/SDK/body expected literals до реализации.

User и service проходят настоящие OAuth issuance/current verifier/ASGI/SQL. Success ровно Card1/links2/intent-receipt1/audit1, real actor/type/scope; raw SET/EMPTY unchanged, только newborn доступен этому actor/app/install/grant. Foreign/newother UUID404, no hidden total/cursor/409 IDs; base ALL не обязателен. Никакого receipt на duplicate/failed INSERT; новая first-create не требует старого Contract graph, но typed CP/location/member own-org/пустые scopes не обходятся. Options/metadata tests проверяют разграничение новой create projection и старого R3 gate.

Concurrency barriers/pg_locks/pg_blocking_pids, не sleep-race/fake lock True/NullPool. Profile/credential/family/grant/membership/module/object/own-org/type/reference revoke коммитится до снятия barrier → реальный отказ. Отдельно обратный row-lock revoke timeline, machine approval/allowset atomicity, cancel, flush/audit/receipt/known commit failure. **Unknown commit acknowledgement** не доказывает rollback: fresh same-key retry должен дать один результат/receipt, не дубль. Quota отдельно ожидаемо пишет, auth setup до fingerprint. Sender/SMTP/COM/notify/files capture до app imports; no delivery/no jobs.

Прежний selection остаётся **native module55** (все CREATE поля/defaults/order/persistence/duplicates затронуты extraction) и **R3 metadata gate7** (новые options не открывают старый каталог). Итого206proposed. Native55 жёстко требует `api_native_contract_create_test_20261030`; metadata7 — `api_contract_classification_test_20261031`: отдельные serial fresh группы, старые DB guards/expectations неизменны. Новые144 — отдельная `api_partner_contract_create_test_20261031`. Не ретаргетировать старые tests и не выдавать исторические59 за current PASS. После authored tests ROOT отдельно фиксирует full parameterized IDs/counts/plugin provenance.

## Будущая ROOT runtime граница и исправленный бюджет

Только ROOT actual после новой implementation freeze. Предложен 127.0.0.1:33546 с exact fresh DB выше; candidate77 Python3.13.7 и package inventory ROOT проверяет, не предполагает установленными. Будущий argv `<verified-python> -I -S -B <reviewed-absolute-helper> --execute-approved-partner-contract-create --group <new|native55|metadata7>`. Helper ещё не существует: точный исполнимый argv/self SHA появятся лишь после source approval/авторства. Pytest `--noconftest -p pytest_asyncio.plugin -q <полный exact IDs list>`, explicit fixture plugin, no app.main/lifespan/jobs. Official generation/check/consumer — отдельный ROOT offline stage с existing locked generator, без network/install.

Clean allowlist env, preserved HOME, APP_ENV=test, LANG=C.UTF-8, plugin autoload OFF/bytecode OFF, synthetic key; matching dedicated DATABASE_URL/TEST_DATABASE_URL без вывода credentials; exact opt-ins/test-only OAuth/API/budget Settings до cached Settings. Четыре private0700 пустых own roots cwd/upload/scratch/evidence. До imports: exact fullapp/tests/schema/support/tool/self pins/sourceAfter; candidate77, five import IPv6 suppression/restore, owned-buffer PG sendmsg16, env/process/net/write controls. SQLAlchemy before_cursor_execute **плюс** raw asyncpg logger; raw-only не full capture. Exact target/lease/key negatives, no external network/process/unowned write.

**8 GiB floor означает свободный ДИСК ROOT**, на source/evidence и DB/WAL volumes перед стадией. Это не available RAM и не AS minimum. V1 RAM floor8GiB отозван, точные байты сохранены. Prospective per-volume reservations: source/evidence128MiB, scratch128MiB, capture16MiB, synthetic DB+WAL2048MiB, schema tooling temp256MiB; это план, не измеренные footprints. Existing envs не переустанавливаются. Если нужен новый package staging, он получает отдельный approved disk budget. При нехватке floor ROOT не удаляет чужие proofs.

Предлагаемые **prospective** stage caps: source/offline-schema CPU180/wall240/SQL0/net0; new144 real OAuth/ASGI/SQL CPU600/wall650; native55/metadata7 serial CPU600/wall650; offline official types CPU180/wall240/SQL0/net0. AS3GiB — **comparator accepted P11**, не замер текущих contracts и не floor; actual RSS UNKNOWN, ROOT измеряет/пересматривает при freeze. Никаких новых немотивированных RAM floors/общего320MiB. SQL stage FD256/FSIZE2MiB, scratch128MiB4096 entries/evidence2MiB/capture4000; pool2 overflow0/max8sessions, stmt20s/lock2s/idle30s/connect10s/command30s; proposed SQL cap15000new/12000old. Это source-specific план, пределы окончательно фиксируются по authored fixtures/скриптам до запуска.

После EXIT/reap/join/clients0 ROOT обычным DROP убирает только свои созданные DB, fresh exists0, no FORCE/terminate/GUC/global cleanup. Checkpoint disk/RSS/SQL и отказ guard не маскируются зелёным результатом. Worker не запускал app/pytest/SQL/codegen/Node/HTTP/контейнеры/servers/installer.

## Reproducibility и оставшееся

Tracked manifest **app504/AST494, tests393, schema24, frontend1220, SDK tools9, scripts26 =2176 файлов**, дополнительно10 requirements/pytest/package/tsconfig support pins. Каждый byte равен exact Git blob, `mail_secrets.py`/все secret-named source включены; никаких `.env`/credential reads. Stdlib read/hash/AST ceiling10000files/100MiB/90s; JSON<8MiB. Полные hashes/anchors/inputs и source-only scripts в JSON/ignored evidence. AST spelling edges не full runtime callgraph. Внешние ROOT-owned platform/plan/completion snapshots — read-only байты с SHA, не чужой accepted commit/WIP claim; operational rows не копировались.

Остаются actual implementation обоих principals после bootstrap owner handoff, locked authority/revoke доказательство, additive schema/official SDK/real tests, остальные Contract PATCH/delete/sync/lifecycle и все domains/Support/Auditor/CI/pilots/deprecation. Privacy follow-up имеет отдельную следующую authority; текущие2reports не меняют privacy/startup owners. Этот admission не закрывает M03/M06/M09/M12 или20M+11 и не разрешает публикацию API.

### Current source anchors (unchanged from V1)

Полные SHA256 ниже относятся к файлу целиком; AST/Git blob SHA каждого символа и всех остальных файлов находятся в JSON.

| Current symbol | Строка | File SHA256 |
|---|---:|---|
| `services/native_contract_commands.py::create_native_contract` | 23 | `36216c6598133a4c707d1deff8ff64a7b0576b7280e7bf2cc88eeda09c095ad4` |
| `services/reference_validation.py::_validate_contract_parties` | 47 | `fec7fca58c47db80683e8bd39bc0394377c1be35d832061e1d0a004b98192d7b` |
| `services/reference_validation.py::_check_type_code` | 36 | `fec7fca58c47db80683e8bd39bc0394377c1be35d832061e1d0a004b98192d7b` |
| `services/reference_identity.py::contract_identity` | 176 | `e3d68cde68cbceb973eef2d52788b9e947eb0b3186bd056f4631debe78616e97` |
| `services/reference_identity.py::lock_manual_creation` | 188 | `e3d68cde68cbceb973eef2d52788b9e947eb0b3186bd056f4631debe78616e97` |
| `services/partner_identity.py::live_grant` | 304 | `9fe9679f48bbe6b6254e7dd50aafd94dfe31b96457abc5c8dcd8f6773b93225f` |
| `services/partner_identity.py::verify_access` | 698 | `9fe9679f48bbe6b6254e7dd50aafd94dfe31b96457abc5c8dcd8f6773b93225f` |
| `services/partner_identity.py::eligible_scopes` | 200 | `9fe9679f48bbe6b6254e7dd50aafd94dfe31b96457abc5c8dcd8f6773b93225f` |
| `product_api/access.py::resolve` | 67 | `f6014e3cda1561da640ebd66b8a46ad63830660baa2581a4b605d880dc890ed2` |
| `product_api/queries.py::Query.contract_domain` | 49 | `cf8757ce4af40410cd5a3fb0c0737d5fffcd3ec2e5e2f866a6234eb328a6a713` |
| `product_api/queries.py::Query.conditions` | 70 | `cf8757ce4af40410cd5a3fb0c0737d5fffcd3ec2e5e2f866a6234eb328a6a713` |
| `product_api/queries.py::Query.contract_type_metadata` | 175 | `cf8757ce4af40410cd5a3fb0c0737d5fffcd3ec2e5e2f866a6234eb328a6a713` |
| `routers/partner_admin_router.py::approve_installation` | 104 | `9f414995519be27cafcf5f332ba9c22873a02aa002bcd3044f5fa37afcedf261` |
| `api_contracts/routing.py::PolicyRoute.get_route_handler` | 138 | `131f3bb5daebfd0631296999aef646449bfd02eddeea7b22e21887e30f2e48c0` |
| `audit.py::log_audit` | 14 | `2db3d8a5c33dd08fd551aeeab01eb9be592f3968ec9eaafac4dc85052424b4b5` |
