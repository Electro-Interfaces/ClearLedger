# H01: named contract receipt permission

SOURCE prerequisite на базе `675654298f9a7cde30f3ab8097935478bb534088`, ветка
`MagLook/contract-receipt-policy`. Runtime AUTHOR0: приложения, helpers и тесты
не запускались. Это не разрешение CREATE и не доказательство writer closure.
Цель полного пакета 20M11 сохраняет delegated user и service, 17 операций.
Выбранное ROOT направление B требует отдельного доказательства scoped locks;
глобальный F не выбран. Schema ordinal, SQL, issuance и production routes здесь
не меняются; `0004` не резервируется.

## 2026-11-01: SOURCE successor для F1

Immutable parent `5325fd74f84fa838ac2cab2f8eee3530ad418a1a` сохраняется;
это новый commit, без rebase/amend. Независимый review запросил F1/P2:
предыдущий named guard не отвергал hashable str-subclass у **текущих**
company/policy/subject/client/install/original grant и policy labels до
overloaded equality. Это недостаток exact-type SOURCE contract, без
доказанного HTTP exploit, runtime failure или текущей issuance authority.

В `DatabaseResourcePermission.matches` добавлены exact nonempty str checks
этих шести current scalar fields до сравнений; direct resource/action arguments
тоже требуют exact str. В `RoutePolicy.__post_init__` exact str resource/action
требуются до contracts/read tuple constraint **только** при непустом named opt-in.
Legacy `_names`/Principal/scopes и все остальные методы не ужесточаются.
Hashable hostile equality/hash cases написаны для каждого поля и labels;
обычные str positive user/service и legacy default-empty поведение сохранены
в authored contracts. Никакие hostile objects, tests или project imports
при этой работе не исполнялись; выполнены только AST/hash/JSON/memory compile.
Статический authored inventory: successor 31 функция/174 случая, включая
6 новых функций/42 случая F1; parent 25/132 сохранён byte-exact. Это не
pytest collection и не executed test IDs; все случаи NOTRUN.

Исходные авторские MD/JSON и их claims сохранены в Git parent и как dated raw
history в текущем JSON. Их SOURCE acceptance не объявляется повторно принятой:
F1 ждёт нового независимого review и отдельного ROOT runtime решения.
Review pins: MD SHA256 `0003cdd5e4927623cc833abdeaed463fe309aafa46ee2af8494fa3f15da9f73b`,
JSON SHA256 `a12e4bf933d72311472d128298bb9ac15ae2a4f563446e7ddac6524e8942f7b0`.

## Frozen source contract

Все новые типы определены в `api_contracts/context.py`; exports package не
меняются. ROOT подтвердил независимый binding через blocking orchestration ask.

| Тип | Frozen поля / допустимые значения |
|---|---|
| `DatabaseAuthorityKind` | единственный enum member `PARTNER_CONTRACT_RECEIPT_V1 = partner-contract-receipt-v1` |
| `PartnerContractReceiptEvidence` | единственный enum member `CURRENT_ELIGIBLE_RECEIPT_EXISTS` |
| `PartnerContractReceiptBinding` | `app_id: UUID`, `create_profile_id: UUID`, `policy_generation: int > 0`; exact UUID/int, bool/string/subclass отвергаются |
| `DatabaseResourcePermission` | `authority_kind`, `company_id: str`, exact frozen `principal: Principal`, `policy_version: str`, exact `binding`, exact `evidence`, `resource_type='contracts'`, `action='read'` |
| `AccessContext` добавления | `database_permissions: tuple[DatabaseResourcePermission, ...] = ()`; независимый `receipt_read_binding: PartnerContractReceiptBinding \| None = None` |
| `RoutePolicy` добавление | `accepted_database_authority_kinds: frozenset[DatabaseAuthorityKind] = frozenset()` |

Permission связывает company, kind/subject/client/install/original grant из
Principal, policy version и app/profile/current generation. В ней нет Contract
UUID/allowset, SQL/callback или trusted bool. Enum evidence означает конкретный
положительный server-produced current EXISTS result; **сам enum не доказывает
исполнение SQL**. None/negative/no eligible receipt означает отсутствие evidence.

`authorize` меняет только EMPTY/UNINITIALIZED gate: требуется объявленный exact
kind и полное совпадение permission с независимыми текущими полями контекста
после exact-type/nonempty проверки текущих identity strings.
Старые context-valid/version/kind/tenant/OAuth и field gates сохраняются.
SET/ALL не меняются; base independently approved доступ не зависит от receipt.
Opt-in декларация допустима только для private exact-string contracts/read с contracts:read
и PARTNER/SERVICE. Новых production деклараций нет. Metadata key
`databaseAuthorityKinds` выводится только при непустом opt-in; для старых policy
словарь сохраняет все прежние ключи/значения.

`intersect` сохраняет только одинаковую authority обеих сторон и одинаковый
independent binding; иначе receipt часть исчезает. `select` удаляет receipt
permission выбранного resource/action. Исходный PolicyRoute selector по-прежнему
проверяет base.contains(selection.ids) до select и не принимает receipt UUID.
ResourceScope/ResourcePermission/Principal/_names сохранены byte-exact как
отдельные definitions, включая прежние exact checks. Сам context.py изменён;
его byte equality не заявляется.

## Фактический caller trace

`product_api.app._policy` создаёт все существующие product RoutePolicy без
database-authority opt-in. `access.resolve` проверяет current verified token,
OAuth/kind и base resource grants, затем строит Principal и AccessContext.
Delegated user отображается в `PrincipalKind.PARTNER`, machine в SERVICE;
native USER не подменяет ни одного из них. Единственный production constructor
AccessContext находится в `product_api/access.py`; ещё два constructor helpers
находятся в `test_api_contracts_context.py` и
`test_policy_lifespan_compatibility.py`.

`PolicyRoute.guarded` вызывает resolver → authorize → tenant selector → resource
selector → повторный authorize → handler. `Query` использует отдельную session,
поэтому данные resolver после quota await не доказывают текущую SQL authority.
R3 `Query.contract_type_metadata` вызывает прежние `conditions('contracts')`;
эти функции и `contract_domain` остаются исходными.

**R3 qualification:** фактическая `/contract-types` policy тоже использует
`contracts/read`, а не `contract_types`. Сейчас она default-empty/base-only.
Common seam не проверяет owner/path/operationId и не имеет intrinsic metadata
hard ban: будущий явный opt-in этой policy мог бы принять тот же named kind.
Поэтому reviewed list/detail/parent owner и отдельный resolver/SQL owner обязаны
явно исключить R3 и сохранить её прежний base-only gate. Старый negative test
доказывает только отказ policy без opt-in. Fake path/owner policy framework
не добавляется; product access/query/routes остаются исходными.

## Следующие владельцы и непроверенное

В исходном AccessContext нет app/profile/generation. Verifier имеет app_id,
но `access.resolve` его не переносит; current create profile/generation/receipt
issuance ещё отсутствуют. Добавленные поля остаются None/empty на всех прежних
constructor calls. Новый typed binding не должен заполняться из HTTP,
claims клиента, serialized bearer или предварительного EXISTS без live checks.
Ни один существующий resolver не начинает выдавать receipt permission этим diff.

SQL owner обязан заново проверить current identity, profile/allowset, все
created refs и ceilings, original grant и eligibility в той же query transaction
под reviewed B guards. Одно предварительное EXISTS не заменяет коррелированный
predicate списка/detail/count/replay; никаких receipt UUID arrays в Python.
List/detail/parent opt-in назначается отдельным reviewed owner. Selectors,
files/documents, foreign CP и другие resource types receipt не разрешает.
R3 сейчас закрыта default-empty декларацией; её future opt-in исключается
отдельным reviewed owner, как уточнено выше. Положительный synthetic guard
не доказывает наличие durable receipt.

Runtime review/изолированное исполнение принадлежат ROOT; текущий результат
ограничен source diff, authored tests, AST/JSON/compile/hash evidence.
Точный manifest base/current SHA256, caller line trace и AST-инварианты находятся
в соседнем JSON. Новый единственный test module переиспользует текущие helpers
`context`, `contract`, `fixture_api`; positive cases synthetic и только для
common guard, production R3/list/detail/query authority ими не доказывается.
Freeze commit передаётся точным HEAD в `worker_done`; push/PR/merge/deploy нет.
