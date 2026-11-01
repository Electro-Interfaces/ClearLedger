# Внутренний SQL issuer и CREATE consumer

SOURCE AUTHORED; independent review **PENDING**; runtime **0**; все определения
проверок **NOTRUN**, включая imports и collection. Это отчёт об авторстве, не
SOURCE_PASS, PG PASS или приёмка полного API. Profile95/RawSource95 приняты ROOT
только для прежнего компонента и не подтверждают готовность этого issuer.

База: `011f0c571912aa7c5d972e851b0d0e3acdf645a9`.
Неизменяемый source/test commit: `5c0b5028fd197151b17b877c6fbdf9c2259b83f1`.
Ратификация: `msg_d78d5ba7a19d`, `msg_4bc270231cbd`; расширение точных путей:
`msg_c014d327b3a5`. Ровно восемь Python-путей и два документа; schema0004,
models, kernel, driver, native adapters, config, CI, SDK и flags не менялись.
Машиночитаемые pins, SHA-256 исходных файлов и точные диапазоны строк находятся
в `api/PARTNER_CONTRACT_SQL_ISSUER.json`; source commit выше закрепляет каждый pin.

## Реализованный внутренний вызов

`await create_partner_contract(db: AsyncSession, bearer: str, body: ContractCreateBody)`
возвращает `PartnerContractCreateResult(contract_id: UUID, replayed: bool)`.
Caller: только будущая ROOT-admitted test composition. HTTP CREATE/options,
activation endpoint, новые flags и обещания SDK отсутствуют.

`prepare_create` проверяет настоящий bearer через `verify_access` на actual
`db.sync_session`, создаёт один общий B через `_prepare_partner_write` и выдаёт
приватный SQL stamp. `require_create` отдельно проверяет зарегистрированный
экземпляр admission, Session/root/Connection, исходную capability, generation,
canonical body bytes и namespace. Dataclass, copy, manual stamp, caller binding,
hash и receipt не создают записи в приватном реестре.

После каждого использования снова проверяется actual SQL graph и
`verify_locked_partner_access`, который вызывает канонические
`verify_access/live_grant/resource_scopes`. Нет отдельной Session, копии read
policy или вызова Product `access.resolve`. Lifetime принадлежит существующей B
capability: commit, rollback, nested transaction, invalidation и другая
Connection прекращают пригодность stamp; новый root требует нового issuer.
Неудачная проверка удаляет его запись; освобождение handle убирает weak entry.

## Явное расширение policy

Раньше `eligible_scopes` выдавал модулю `references` `counterparties:read` и
`contracts:read`. Теперь добавлен **только** mapping `contracts:create` →
`references` и описание scope. Прежние active User, actual Membership, приоритет
current named Role над ad-hoc modules, admin/superadmin с actual membership и
семантика `modules=None` сохранены. Это намеренное расширение выдачи scope,
а не разрешение CREATE по одному модулю или admin role.

| AST eligible_scopes | SHA-256 |
|---|---|
| baseline | `1524bb5ebec7869c2ac8c742c830da0fd234e9433fcc70f7ed7809c76ef78107` |
| с расширением | `cb9fc729c9b13a563f43c79161e3aba7983c1b45dd6600a20a20e1e4201724d9` |

В DPL сохранены исходные 19/17/12 literals и прежние overlay pins. Добавлены
именованный accepted-extension record, точный новый file pin и AST-проекция:
удаление ровно одного нового mapping должно вернуть прежний hash policy.
Другие 11 canonical функций и все 17 прежних branch pins сохранены.
Ни old hashes, ни проверки не заменены широким allow.

Для CREATE требуются одновременно текущий scope `contracts:create`, пересечение
client/install/grant/token ceilings, живой bearer и отдельный SQL профиль:

- User: `user_enabled=true` и exact user principal; реальное Membership/Role.
- Machine: настоящий confidential client grant с `user_id=NULL`,
  `service_enabled=true` и exact machine-grant principal; вымышленного User нет.
- Organization: profile organization ∩ current company ∩ actual own-org restriction.
- Counterparty: profile CP ∩ verified counterparties scope ∩ current company.
- **Каждый** location: profile locations ∩ verified objects scope ∩ grant locations
  ∩ native user object_scope ∩ current company. Opaque IDs не приводятся к UUID,
  не обрезаются и не нормализуются.
- Type: profile types ∩ actual active catalog. EMPTY и пустые sets запрещают;
  explicit ALL/SET/EMPTY сохраняются. `None` у canonical location ceiling
  сохраняет его исходное значение ALL; пустой set не превращается в ALL.

`contracts:read`, admin, hash и receipt сами не дают CREATE. Contracts resource
scope не служит источником CREATE; собственный immutable intent даёт только
внутренний result ID после полной текущей CREATE-проверки. Канонический verifier
продолжает проверять все существующие resource profiles.
Оба profile flags по умолчанию false; admin PUT всегда устанавливает их false,
как прежде. Positive definitions используют только настоящие synthetic SQL
profiles с true; механизма активации для пользователей этот срез не добавляет.
Profile cleanup не получил нового live_grant gate.

## Блокировки и атомарность

До единственного B замораживаются полный identity/tenant/pointer/absence graph,
credential/install sets, профиль, **полные** principal/ref/type sets, requested
parents и namespace/существующий intent со всеми location children/result parents.
После B до canonical rows вызывается существующий `lock_manual_creation` в
порядке company-counterparty → company-contract. Нет второго плана, late keys,
upgrade, reentry, child retry или нового global barrier.

После каждого legacy/identity/profile/ref/type/child row wait, после последнего
ожидания и после каждого flush выполняются свежие SQL snapshot checks и current
public partner auth/CREATE policy. Generation берётся из текущего SQL снимка
этого root, не из исторического intent. Drift означает rollback всего root без
перехода к новым родителям. Проверки используют scalar rows с копированием JSON.

Consumer повторно использует `contract_identity`, `find_contract_card_duplicates`
и `create_contract_card`. Он создаёт карточку с native creation key/actor/hash
NULL, scope_type=locations, is_closed=false и nullable native реквизитами NULL.
Parent card flush → check → ContractLocation flush → check → immutable intent
flush → check → intent locations + AuditEvent flush → check. Все пять частей
находятся в одной actual Session/root/Connection. Commit принадлежит caller;
любая ошибка или cancellation вызывает полный rollback. AuditEvent добавляется
прямо в этот root; log_audit, notify и background work не вызываются.

## Replay и неизвестный commit

Namespace: company/app/install/createContract/creationKey. Replay требует полной
текущей CREATE eligibility, того же client/app/install, **исходного grant.id**,
exact actor binding, текущего профиля и original refs/type/locations/result.
Новая family или credential в том же grant допустима только после настоящей
текущей проверки. Новый grant, смена actor, потеря CREATE или original coverage
запрещают replay; read fallback отсутствует. Hash mismatch получает 409 лишь
после current auth. Hidden/foreign/absent result не раскрывает id/hash/generation.
Matcher conflict не возвращает IDs read-hidden договоров.

При unknown commit caller открывает новый root с тем же key и реальным bearer;
issuer выдаёт новое current-generation evidence. Смена key и перенос старого
proof не служат восстановлением. Immutable schema0004 и модели не менялись.

## Проверки и предел доказательств

Написаны 30 PG definitions / 103 статических parametrized variants, 8 unit
source definitions и один новый DPL extension definition (DPL всего 9).
Матрица содержит 30 записей, по одной на PG definition. Это подсчёт AST,
**не collection и не runtime outcomes**. Выполнены только stdlib AST/JSON/hash,
компиляция восьми Python-файлов в памяти без exec и Git diff checks.

PG definitions используют actual HTTP/Authlib user/machine tokens, настоящие
SQL profiles и original issuer. Наблюдатели передают original return; fake
positive auth/capability/proof отсутствуют. Wait definitions проверяют actual
PID, pg_blocking_pids/pg_locks и fresh-reader SQL, а не только task.done/sleep.
Post-flush faults подтверждают существование actual rows до negative injection.

Отдельный dedicated FK-wait definition не объявлен runtime-доказательством:
в предусмотренном протоколе все FK parents уже SHARE-locked до INSERT, поэтому
конкурирующий key UPDATE/DELETE должен блокироваться раньше, на parent phase.
ROOT должен независимо проверить эту достижимость и фактические server triggers;
flush fault не считается dedicated FK wait. Native duplicate parity definition
не заменяет полный прогон всех исторических native/import/profile/DPL suites.

ROOT остаются admission/preimports/schema4/Core/RC target, исполнение определений,
raw evidence, bounded synthetic cleanup, независимый review и решение о draft
publication. Parent conftest импортирует app/engine и DROP до module guards:
обычный pytest, даже collection, запрещён. Автор ничего не импортировал и не
исполнял из проекта, не подключался к SQL/DB/HTTP и не запускал CI.

Original M00–M19 + 11 сценариев сохранены только ссылкой на
`/srv/projects/preview/contract-create-workflow-20261101/report.json#/original_program`:
semantic `4ac5f8535d2f9f0b3c7fb910cad958165b8ff886eb48edc2c68726d09c005345`,
counts 20/11, completion=false. RFC113 остаётся отдельной работой; его ветки и
артефакты не использовались и не менялись.
