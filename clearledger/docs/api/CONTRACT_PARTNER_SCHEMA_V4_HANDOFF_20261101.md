# Frozen handoff: persistence0004 → domain/admin/query owners

Только SOURCE, **NOT RUN**. Схема не включает grants issuance, CREATE transport,
receipt predicates или аудит. Правила admission/V2 и решение ROOT о сохранении
history при удалении всех родителей имеют приоритет над прежними proposals.

Будущий `partner_admin` owner меняет profile header и полный набор principals,
typed refs и types **одной существующей admin transaction**. Каждое эффективное
изменение approval/revoke/children повышает `policy_generation` атомарно под
согласованными Install/Profile guards; overflow bigint означает отказ, не reset.
Disable/delete самого profile закрывает derived receipts. Замена профиля новым
UUID не наследует receipt прежнего UUID. Схема хранит generation, но не выдаёт
admin owner за уже подключённого issuer и не заявляет автоматическое увеличение
generation при каскадах или чужих изменениях ceilings. Cursor owner должен
учитывать current effective authority, включая внешние account/install ceilings.

User allowset хранит реальный User UUID; machine allowset хранит конкретный
PartnerGrant UUID. БД проверяет XOR/FK, **не** machine kind/installation/tenant
в чужой таблице: существующего composite key для этого нет. Domain и admin
обязаны повторить current user membership/account/modules/own-org/object scopes,
machine grant kind/current credential/family/client/App/install/CompanyApp,
same-company и точный installation/client/company tuple. Service не становится
native User. Новый `contracts:create` scope и issuance здесь не включены.

Org/CP/location должны принадлежать той же компании и пройти profile SET ∩
typed grants ∩ installation/user ceilings. SQL FK к live master доказывает
существование, а не принадлежность tenant. Exact nonblank typeCode TEXT должен
существовать и быть active **при новом INSERT**; история/replay/receipt проверяют
current approval, но не требуют, чтобы уже использованный тип оставался active.
FK type/profile и live ref deletion снимают approvals, history snapshots сохраняются.

Будущий command owner сначала полностью валидирует тело/authority/refs и
согласованный scoped lock plan другого owner, затем одной transaction пишет
Contract, ContractLocation, success intent и intent locations, private AuditEvent.
Success intent INSERT требует current result/user; locations вставляются после
intent, в той же верхней transaction, до COMMIT. Ключ unique:
`(company_id,app_id,installation_id,operation='createContract',creation_key UUID)`.
Actor/original grant/profile/hash проверяются при replay отдельно, без присвоения
старого success другому principal. Нельзя записывать pending/failed intent или
receipt на duplicate чужой существующей карточки. Hash-version1 canonical payload
по admission; native `Contract.creation_*` namespace сохраняется.

`AuditEvent.details` остаётся **Text**, `user_id` — **String100**, без User FK.
User attribution — actual UUID/name; service — `partner-client:<actual client_id>`
и actual App label. Не использовать `log_audit` с dispatch, не писать token/body/
secret. Current API и audit writes этим пакетом не подключены.

Receipt SQL обязан связать actor + company/app/install/client/**original grant**
и **тот же original profile UUID**, current profile flags/principal/approvals,
current live result и прежние company/own-org/object predicates. Удалённый любой
current join закрывает receipt path, immutable snapshots не заменяют authority.
EMPTY разрешается только bounded current `EXISTS`; IDs всех intent не загружаются
в память. Count + page идут одним SQL statement snapshot; это не обещание
межзапросного стабильного RR snapshot и не materialized set всех newborn UUID.
Generation сама по себе не отменяет receipt, если все current approvals сохранены.

Схема даёт namespace unique, principal/current-contract partial index,
profile/company index и typed child lookups. У неё нет нового индекса на старом
Contract, INCLUDE payload или измеренного плана. Query owner передаёт ROOT
EXPLAIN на synthetic0/1/1001/100000 history и current EXISTS/count/page без
изменения meaning SET/EMPTY. По итогам ROOT отдельно решает нужные индексы.

Приватный retention owner может явно удалить intent с его locations; profile,
user, grant, installation, app и company deletion не удаляют успешную историю.
Native result/user deletion только очищает nullable current pointer, а newborn /
actor key и provenance остаются. Восстановление pointer после NULL запрещено
immutable trigger; повторная карточка не присваивается прежнему intent.

Для проверки ROOT нужен отдельный реальный native world: company/app/client/
CompanyApp/install/grant/user/org/CP/location/type/contract и безопасные delete
fixtures без посторонних native зависимостей. PG cases не создают ни БД, ни
частичную metadata baseline и не импортируют conftest. Имена fixed target/DSN
в cases являются тестовым admission, а не разрешением занять уже работающую БД.
Сначала independent source/helper/target freeze ROOT, затем runtime только ROOT.
