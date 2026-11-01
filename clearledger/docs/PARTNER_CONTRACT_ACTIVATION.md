# Административная активация профиля создания договоров

Статус: `ACTIVATION-SOURCE-01` исправлен в исходниках (`SOURCE_ONLY`), требуется
новый независимый FULL SourceReview. Первый FULL review завершился
`CHANGES_REQUESTED_SOURCE`; положительный source verdict здесь не заявляется.
Выполнение, collection, SQL, HTTP и проверка интеграции не проводились,
Runtime UNKNOWN. Review и разрешение на выпуск принадлежат ROOT.
Этот документ не даёт команду включать флаги на работающей установке.

Основание: codegate `msg_4b02011dc305`, утверждённые V1/V2 и уточнение ROOT
`msg_cc8cade6fd88` о структурной готовности конфигурации. Исходная база
`4a4ba3bc041b69ccb4064a7865873eadd6f0f00f`; неизменяемый коммит исправления кода
и определений тестов `cd32cd7edf1860f095a94b0a688cbfad27108334`, tree
`3f46b319325ea4afa0ab1a40ea6351931e7c9c86`. JSON-контракт находится рядом:
[api/PARTNER_CONTRACT_ACTIVATION.json](api/PARTNER_CONTRACT_ACTIVATION.json).

## История исходников и review

Первый код: `638f940eefcebb35bcce9fff239522b0d7737f4b`, tree
`c5f09ce663cbf697e670b68aa8a41b045833f5cc`; первый docs child:
`0e397ece235dd50adf3157005e9747095b606021`, tree
`c793de6b9423f715eaad83a3a7dd40dca60cf60a`. SHA256 исходного service:
`c1a7fb76be8b4f044eab0dada99662be7af0d9624526d91233ab5f83c6643ce5`.
Первый FULL review хранится без изменений в
`/srv/projects/preview/partner-contract-activation-review-20261101/`:
`review.md` SHA256 `ff549ced9cfc407e521f0c8576e71e8f9f4fe0d04902c6109edf0d90198e17f8`,
`review.json` SHA256 `264ce0dc7c6fb26f752a086b4faa1b014640a51d3ab2c4a71b022a99a4c5c456`.
Замечание P1: tenant-фильтр исходного discovery терял foreign canonical refs,
а стабильность raw snapshot не доказывала их корректность. Это нарушение графа
административной активации; обход внешнего OAuth/CREATE не установлен.

Исправление меняет только `ActivationOperation.freeze`, добавляет определения
PG-проверок и обновляет только `ACTIVATION_SOURCE.service_sha` в DPL.
SHA256 исправленного service:
`6b97c9e6c5420af95587b85947c26295b95d82941ada2bc1c6f5912e648ad9a5`.
Этот коммит является прямым потомком первого docs child; данный docs child
меняет ровно два документа. Полный итоговый manifest девяти файлов и evidence
хранятся в `/srv/projects/preview/partner-contract-activation-fix-author-20261101/`.

## Запрос и результат

Отдельный внутренний административный маршрут:

```http
PUT /api/developer/installations/{installation_id}/contract-create-profile/activation
Authorization: Bearer <обычная Core-сессия администратора компании>
Content-Type: application/json

{"expectedGeneration":1,"userEnabled":true,"serviceEnabled":false}
```

Все три поля обязательны. `expectedGeneration` принимает строго целое число
от 1 до 9223372036854775807. Два флага принимают строго JSON boolean.
`null`, дополнительные поля, строки и числовые заменители boolean отклоняются.
Сервис также повторно проверяет точный тип DTO, его поля и данные экземпляров,
созданных через `model_construct` или `model_copy`.

Успех возвращает HTTP 200 и прежнюю модель `ContractCreateProfileReadback`:
`profileId`, `installationId`, `clientId`, `companyId`, `policyGeneration`,
`userEnabled`, `serviceEnabled`, `revoked`, `userIds`, `machineGrantIds`,
`organizationIds`, `counterpartyIds`, `locationIds`, `typeCodes`.
Дочерние наборы сохраняются, generation увеличивается на один. Запрос с теми же
значениями флагов при правильной generation также создаёт новую generation и audit.
Маршрут скрыт из Swagger; публичный API партнёра и его манифест здесь не расширяются.

## Права и условия включения

Используются исходные публичные функции native Core auth, проверка обычной
Core-сессии, администратор компании установки и закрытый gate
`partner_contract_create_admin_enabled`. Gate и текущая native-авторизация
проверяются после ожиданий блокировок и фактического flush.

Включение означает согласованную конфигурацию допуска. Оно допускается до
готовности OAuth: не требует активных App/client/CompanyApp, approved grant или
заранее выданного пользовательского OAuth grant. Выдача и проверка внешних токенов,
consent, действующие scopes и CREATE остаются у своих прежних владельцев.
Включённый профиль при выключенном App или отозванном grant продолжает получать
отказ исходного внешнего verifier и POST. Поля готовности OAuth в ответ не добавляются.

До включения должна существовать полная согласованная структура профиля:
все пользовательские principals и их членства, home Company, реальные владельцы
именованных Role, machine grant с точным company/client/installation/kind/userNULL,
все ссылки профиля и текущие Member pointers. `Member.organization_id` ссылается
на Counterparty; `Member.own_organization_id` ссылается на Organization.
Чужие родители не становятся новым графом обхода.

До B проверяются все raw canonical `PartnerInstallationLocation.location_id`
и все typed target ID из `PartnerResourceItem` по исходному `RESOURCE_MODELS`:
objects, equipment, counterparties, contracts, documents. Каждый target должен
реально существовать в той же компании и входить в полный frozen descriptor
набор. Проверка охватывает исходные raw sets, включая ссылки, которые tenant
filter не включил в `ordered`; scope modes ALL/EMPTY/SET, `all_locations` и
запрошенные flags её не отключают. Missing/foreign target даёт общий private
admin 409 `Activation profile graph is invalid` до B, без обхода или блокировок
графа чужой компании. Затем замораживается полный union родителей.
Canonical extras сохраняют native ID буквально: допустим и не выбранный в
профиле whitespace-only ID, если такой ServiceLocation существует в компании.
Новых trim/normalize, OAuth readiness или unrelated inactive veto нет.

Для `userEnabled=true` нужен хотя бы один настроенный User с текущим членством,
для которого непусты допустимые наборы. Для `serviceEnabled=true` нужен хотя бы
один настроенный machine principal с точной привязкой grant и confidential client
`client_secret_basic`. Общие допустимые наборы должны содержать Organization,
Counterparty, location и хотя бы один активный type code. Counterparty пересекается
с canonical resource scope; location пересекается с resource scope и installation
locations. Для пользователя дополнительно учитываются `own_organization_id` и
`object_scope`, включая администратора: `None` не ограничивает, `[]` даёт пустой набор.
Opaque location/type значения сохраняются буквально.

Неактивный дополнительный type и неготовый к OAuth дополнительный principal/grant
сами по себе не запрещают включение при наличии требуемой legal selection.
Повреждение обязательной структуры запрещает операцию. У revoked профиля
нельзя включить ни один флаг. Запрос `false/false` разрешает отключение без
проверки непустоты legal selection, но сохраняет проверку структуры и прав.

## Транзакция и блокировки

Новый точный private тип `ActivationOperation` и purpose
`contract-profile-activation` проходят единственный исходный B entrance.
Вложенный `ProfileOperation(installation_id, None)` остаётся в режиме чтения:
переиспользуются исходные discover/snapshot/recheck/readback. Старые read/replace
и CREATE не маскируют новую операцию и сохраняют прежние тела.

Вся структура, полные SQL rows, mutable JSON scopes, дочерние наборы, current
Member Org/CP pointers, canonical installation/resource sets и credentials
замораживаются до B. InstallationKey и CreateProfileKey имеют EXCLUSIVE режим.
Ключи объединяются до B; позднего расширения плана и второго B нет.

Физический порядок только для activation:

1. Company/App/PartnerClient/User/CompanyRole.
2. Полное объединение Counterparty/Organization/ServiceLocation из canonical
   refs, профиля и текущих Member pointers, по модели и идентификатору.
3. Member и остальные canonical identity rows.
4. Profile EXCLUSIVE, Type SHARE, дочерние наборы SHARE.

Граница перед Member существует и при отсутствии строк Member. Каждый wait
завершается checkpoint; уже взятые родители повторно не блокируются. Остаются
исходные Session, root, Connection и capability. Наблюдаемый drift прекращает
весь запрос без следования новым родителям и повторного B.

После CAS обновляются только generation и два флага профиля. В той же root
транзакции добавляется `AuditEvent` с action `partner.contract_profile.activation`
и details ровно `profileId`, новая `generation`, `userEnabled`, `serviceEnabled`.
Дочерние principal/ref/type rows, договоры, counters, success intents, scopes,
grants и consent не изменяются. Затем выполняется настоящий flush, checkpoint
текущих прав и согласованное readback; HTTP-владелец завершает commit.

## Ошибки и восстановление

| Статус | Условие |
| --- | --- |
| 401/403 | Исходная native-сессия или права администратора больше не допускают запрос |
| 404 | Установка или профиль отсутствует |
| 409 | Stale generation, overflow, drift, revoked enable, несовместимая структура (включая raw canonical missing/foreign target до B) или пустая legal selection |
| 422 | Неверный strict DTO; прежние discovery helpers также отклоняют неверные refs/grant bindings этим статусом |
| 503 | Закрытый административный gate или исходный отключённый OAuth/Core gate |

Исключения и отмена запроса откатывают всю root. При потере подтверждения commit
исход операции остаётся UNKNOWN: ошибка rollback после этого не доказывает,
что сервер не сохранил commit. Восстановление начинается с нового current-auth
GET `/api/developer/installations/{installation_id}/contract-create-profile`.
Не повторяйте старую CAS вслепую. Отключение или возврат к согласованным флагам
выполняется новым CAS с текущей generation; старую generation не восстанавливают.
Replace по-прежнему всегда выключает оба флага; defaults остаются false.

## Определения проверок и пределы доказательств

Подготовлены 8 определений strict/source тестов с 37 literal variants и
19 определений PG тестов с 102 literal variants (до исправления было 16/62).
Все NOTRUN, включая collection; 27 определений / 139 literal variants не
означают пройденные проверки.
PG определения используют настоящие own-claims Core bearer, Authlib bearer,
get_db/AsyncSession, caller completion, независимые свежие SQL reads, реальные
PostgreSQL PID и `pg_blocking_pids`, physical row waits, отрицательные SQL-инъекции
после wait/flush, CAS-конкуренцию, cancellation и unknown ACK. Положительных
подмен verifier или SQL-доказательств нет. ROOT отдельно предоставляет admitted
factories и безопасную composition; обычный parent conftest опасен для collection.

Новые определения охватывают canonical-only foreign installation location при
обоих `all_locations` и enable/false-false (4 variants), каждый из пяти typed
foreign resource targets при ALL/EMPTY/SET и enable/false-false (30 variants),
local canonical extras с literal whitespace-only ID и полным parent union
(6 variants). Negative cases вызывают настоящий current-native маршрут,
наблюдают исходный B с делегированием ему и ожидают ноль вызовов, общий 409,
отсутствие foreign graph follow/locks/DML и неизменность через fresh independent
SQL. Fixtures соблюдают native FK/Check constraints. Прежние реальные Authlib
canonical PASS → App/grant off → activation success → external DENIED определения,
physical wait/PID/current-native/CAS/rollback/cancel/unknown ACK сохранены побайтно.

Собственная статическая проверка автора сравнила полные inverse AST
identity/router/schema с базой, 20 frozen essential файлов и 91 исходное
определение, исходные DPL literals 19/17/12 и GORG/HTTP, байты всего профиля,
поля моделей, raw overlay pins и in-memory compile без exec. Старые PG/helper
тела и unit 8/37 сохранены побайтно. Это не заменяет SourceReview или
runtime. Исходная программа 20+11 остаётся незавершённой по ссылке
`/srv/projects/preview/contract-create-workflow-20261101/report.json#/original_program`,
semantic `4ac5f8535d2f9f0b3c7fb910cad958165b8ff886eb48edc2c68726d09c005345`.
`completion_asserted=false`. Старые 95/122/observer2 результаты не переносятся.
OPTIONS остаётся PLANONLY; эта работа не разрешает push, PR, merge или активацию.
После нового FULL source review требуется точный текущий ROOT PR gate до push.
