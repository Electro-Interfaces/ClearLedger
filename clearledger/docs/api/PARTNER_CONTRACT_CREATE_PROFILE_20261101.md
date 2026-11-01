# CREATE-профиль: SOURCE freeze, 01.11.2026

Статус: **AUTHORSHIP COMPLETE; независимый SOURCE review PENDING; runtime NOTRUN**. Не SOURCE_PASS и не готовый внешний Contract CREATE.

База `29baa0c6a938c366edb2ee69cbcd1a60532558e4`. Первый source/test commit `4d39d84128388596c4513fa5806c510ac3c11abb`; окончательный source freeze `d0f0bbd9d9a0b54321ad26a7c4a409e27e90fe43`. Этот документ добавляется отдельным docs-only child. Push/PR/merge/выкатка не выполнялись.

## Ратификация и состав

ROOT `msg_801308d92571`, relay reply `msg_b6c79a9c6b2c` на наш ask `msg_9a1b4385f0bc`: exact8, включая этот MD, и только profile-purpose exception в `_prepare_partner_write` / `_PartnerWrite.checkpoint`. `_ROW_ORDER`/`_POINTERS` менять не потребовалось. Kernel/encoder/native/parser/DPL/models/schema/runner/Product15GET/Swagger/SDK не изменены.

Отличие от frozen phase1: GET readback обязателен; generation-aware CREATE replay не блокирует данный admin slice, его CURRENT-GENERATION SQL proof отдельно ратифицирует ROOT на issuer phase. Phase1 MD/JSON не переписаны.

Реализованы в исходниках PUT и GET `/api/developer/installations/{installation_id}/contract-create-profile`. Prefix подтверждён `app/main.py:494,605`; оба новых handler используют существующий PartnerRoute, отдельный request adapter и фактическую native auth. Это конфигурационный prerequisite, не partner Product POST и не создание договора.

## Поведение исходников

Новый `partner_contract_create_admin_enabled=False`; существующие flags/defaults не меняются, реальные env/config не читались и не активировались. Actual `require_core_user` сохраняет свой существующий OAuth enabled gate. PUT всегда пишет user_enabled=false/service_enabled=false; activation/receipt/unknown fields DTO запрещает, usecase повторно валидирует DTO. GET возвращает фактические flags/generation/allowlists, не SQL receipt proof.

PUT заменяет полные списки: userIds, machineGrantIds, organizationIds, counterpartyIds, locationIds, typeCodes, каждый максимум100; отсутствие списка запрещено, пустой явно очищает. UUID refs canonical; locations сохраняют точные Unicode/регистр/пробелы, 1..40, без NUL/UUID-нормализации; typeCodes непустые, до256. revoked default=false. expectedGeneration absent/null допустим только при создании; generation1. Existing/revoked profile требует exact positive int, CAS +1; stale/переполнение409. Не означает бизнес-идемпотентный replay: после lost ACK нужен GET current generation, затем осознанная новая CAS-команда.

Конфигурация/отзыв не требует live_grant, approved/enabled app/client/install/grant: cleanup отключённого контура доступен actual Core admin. Machine grant обязан совпасть по client/install/company/kind=machine и user=NULL. Whitelist user требует реального target membership, домашняя компания может быть другой. FK refs принадлежат компании. Только ДОБАВЛЕНИЕ code требует active core.contract_types; сохранение/удаление old inactive code не получает нового active gate. Профиль не выдаёт OAuth scopes и не становится разрешением; будущий issuer должен пересечь все текущие scopes/resources/live eligibility.

Ошибки:503 closed gate;401 отсутствующий/некорректный native Bearer/session;403 Core/admin policy;404 отсутствующая установка/профиль;422 DTO/member/grant/ref/added-type;409 CAS/исходный graph drift. Ответы используют существующий native error boundary/NO_STORE, не новый Product Problem contract. Прежние native400 parties/422 type/409 replay/duplicate/defaults не меняются.

## Один B и одна root

Clean MVCC/no_autoflush discovery до protocol/advisory/row/FK/flush сохраняет исходные указатели, отсутствие профиля, whole child sets, old+new users/home companies/members/grants/refs/type codes. Profile ID генерируется сервером upfront; Installation X защищает absence при PUT (S при GET), CreateProfile X/S; все scoped keys и actual capability выдаёт прежний kernel на той же Session/root/Connection. Нет caller-built capability/receipt, late keys, повторного плана, upgrade или retry внутри failed root.

Прежняя canonical identity row phase сохраняется. Только profile-purpose не блокирует неиспользуемые live read-grant resource parents; его собственные old/new refs идут единым порядком после Profile: CP→Organization→Location→Type, затем children. Whole installation sets остаются зафиксированы исходным composer. Actor/home/member/graph/key drift и whole-set/generation drift приводят к full root rollback, без перехода к новому unplanned winner.

Checkpoint после всех typed/row/delete/FK/flush waits повторяет actual public native session/visit/admin; named Role gate не добавлен, потому что эта native admin policy его не читает. Parent profile flush precedes child inserts (у моделей нет ORM relationships); затем children+AuditEvent flush, оба на ТОЙ ЖЕ root, с checkpoint после каждого. AuditEvent пишет реального actor, company FK parent объявлен upfront; нет audit.log_audit/notify/background. GET держит SHARE, перечитывает current generation/whole lists и завершает read root rollback без DML/presence/audit. Commit transport loss остаётся UNKNOWN даже после попытки rollback.

## Что проверено без исполнения

Только FS/Git/stdlib AST/JSON/hash и memory compile WITHOUT exec всех7 Python-файлов, git diff --check. Project/helper/auth/encoder/test imports/calls, pytest/collection, DB/SQL/HTTP и прочий runtime: **0**. AST сравнение сохранило прежние41 identity definitions,14 admin definitions,7 schema definitions вне exception; поля/прочие методы _PartnerWrite unchanged. Frozen17 handler decorator+body spans и source pins canonical policy/GET/parser/kernel совпали с29base. Это preservation исходных12 policy contracts, без исполнения registry и без нового общего аудита.

AUTHOR tests:26 definitions,95 статических параметризованных cases (66 policy +29 PG), **NOT COLLECTED / NOTRUN**. Позитивные сценарии используют original B issuer/current public native auth, не fake-positive verifier. Есть strict/false flag/activation, real disabled graph cleanup, foreign-home target member, foreign/missing refs/users/machine grants, inactive removal/added inactive denial, CAS/revoke/lost actual commit ACK+fresh readback, GET missing/coherent SHARE/no presence, actual PID+pg_blocking_pids+pg_locks typed/row waits, original absence/whole children/generation/home drift, capability lifetime negatives.

Fault/cancel cases отдельно параметризованы parent и children_audit. ДО сбоя actual SELECT counts на writer root обязаны показать (profile,principal,ref,type,audit)=(1,0,0,0,0) или (1,2,3,1,1); ПОСЛЕ rollback fresh reader должен показать отсутствие всех результатов. Это meaningful authored oracle, не результат прогона. Post-child-flush revoke изменяет actual user token_version и требует отказа настоящей public native policy.

**Standalone FK-lock wait: NOT_AUTHORED.** Проверки после actual parent/child flush не названы FK-wait тестом. Parent row SHARE/X должен переносить конкуренцию за известные FK parents в раннюю row phase, но независимый reviewer/ROOT должны подтвердить пригодный сценарий и closure; этот пробел сохранён. Existing27 parser и55 native cases frozen/reused, не запускались.

## Следующая приёмка и unknowns

ROOT единолично предоставляет isolated preimport composition и fixture `profile_admin_factory`, actual target/schema4/READ COMMITTED/admission/receipt. В репозитории parent conftest импортирует app/engine и DROP до module guard: обычный pytest/collection небезопасен и здесь запрещён. Новый модуль не предоставляет runner/URL/env/admission/schema provisioning. Независимый review отдельно оценивает source и FK-wait gap; затем ROOT решает допуск к runtime. Source compile не доказывает import/DB/concurrency/API behavior.

Следующий отдельно согласуемый consumer: SQL issuer текущих profile/generation/receipt и options usecase, затем OAuth CREATE/options scopes/ceilings и disabled partner CREATE adapter с atomic card+links+intent+receipt+audit и generation-aware replay. ReceiptBinding остаётся read descriptor, не SQL proof. Schema0004/intents не менялись. Actual API/curated Swagger/официальная SDK следуют за admitted contract; working partner POST example здесь отсутствует. Full API/B/live partner/SDK/flags/release/M00–M19+11 не закрыты.

## Канон полной программы

`/srv/projects/preview/contract-create-workflow-20261101/report.json#/original_program` сохраняется полностью. Raw report SHA256 `324a459fa5bf191d488c45425a72c7c6f760de6e2e981eb9b12be7b1eda203d0`; original_program semantic SHA256 (sorted compact ensure_ascii=False UTF8) `4ac5f8535d2f9f0b3c7fb910cad958165b8ff886eb48edc2c68726d09c005345`; plan SHA256 `2f0ce3f319b1bbeff98905f2921514b5b722c1c65d4c7c13ca8b344f9e888352`. Sections20, criteria11, completion_asserted=false. Глобальная программа не сокращена/не изменена/не закрыта.

## Exact source freeze pins

Repository Electro-Interfaces/ClearLedger, commit `d0f0bbd9d9a0b54321ad26a7c4a409e27e90fe43`; hashes ниже полных raw файлов, строки включительно. 8-й path: `clearledger/docs/api/PARTNER_CONTRACT_CREATE_PROFILE_20261101.md` (этот docs-only child).

- `clearledger/server/app/config.py`: 16459 bytes, SHA256 `e79431c356aa0de3747738bc9bd3638262894c7e847e9122875ad53153cfdbdb`.
- `clearledger/server/app/schemas_partner.py`: 4469 bytes, SHA256 `b8b925de25830ed8f2a7dc94f11cfa8bf31b7b7a29909d8d288121c5ef1772d6`.
- `clearledger/server/app/routers/partner_admin_router.py`: 15622 bytes, SHA256 `1d097bfca261e25dd6a482cd2b041fde4f6ef593ef29252c55335a5e15ca97db`.
- `clearledger/server/app/services/partner_identity.py`: 61149 bytes, SHA256 `56b38ff0c6926163e1fdd3232ed714c6053edfaf58ff2d8cd07f6cb95abcef77`.
- `clearledger/server/app/services/partner_contract_profiles.py`: 17467 bytes, SHA256 `6fdc93816c6ba7af22b97dc6c1e8e1bc91f1563cec1c0672e82e17a11c23abef`.
- `clearledger/server/tests/test_partner_contract_profile_policy.py`: 7839 bytes, SHA256 `7a433d7442a1a24368508d95e493dfa15b5355840696a09c56adaa8bd52b1eb1`.
- `clearledger/server/tests/test_partner_contract_profile_pg.py`: 25968 bytes, SHA256 `cc843b3826eebf7a1c4a9fe470375441188889cdd59f64ce79c693d0c8f10400`.

Опорные symbols/lines (те же file hashes):

- `clearledger/server/app/schemas_partner.py:86–105` `ReplaceContractCreateProfile`.
- `clearledger/server/app/schemas_partner.py:108–124` `ContractCreateProfileReadback`.
- `clearledger/server/app/routers/partner_admin_router.py:269–273` `replace_contract_create_profile`.
- `clearledger/server/app/routers/partner_admin_router.py:278–282` `read_contract_create_profile`.
- `clearledger/server/app/services/partner_identity.py:496–742` `_prepare_partner_write`.
- `clearledger/server/app/services/partner_identity.py:469–493` `_PartnerWrite.checkpoint`.
- `clearledger/server/app/services/partner_contract_profiles.py:53–64` `profile_core_user`.
- `clearledger/server/app/services/partner_contract_profiles.py:92–147` `ProfileOperation.discover`.
- `clearledger/server/app/services/partner_contract_profiles.py:154–168` `ProfileOperation.recheck`.
- `clearledger/server/app/services/partner_contract_profiles.py:170–192` `ProfileOperation.lock`.
- `clearledger/server/app/services/partner_contract_profiles.py:248–312` `replace_partner_contract_create_profile`.
- `clearledger/server/app/services/partner_contract_profiles.py:315–332` `profile_admin_request`.
- `clearledger/server/tests/test_partner_contract_profile_pg.py:227–233` `own_root_counts`.
- `clearledger/server/tests/test_partner_contract_profile_pg.py:237–254` `test_actual_flush_fault_rolls_back_profile_children_and_audit`.
- `clearledger/server/tests/test_partner_contract_profile_pg.py:458–476` `test_cancellation_after_actual_flush_rolls_back_all_rows`.
