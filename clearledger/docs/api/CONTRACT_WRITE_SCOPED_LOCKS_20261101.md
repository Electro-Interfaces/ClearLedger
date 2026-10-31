# Scoped contract write locks: frozen helper API

01.11.2026. B1 follow-up: ровно helper, PG specifications и эти MD/JSON.
Exact follow-up base `c9e841c48ddf4864eb258e6bd5ddd7401a3833ea`;
исходный implementation base `d71e4f3754efce7c911cc95cb46eb22707e8efbc`
(PR95/96 + H01). Unit module сохранён byte-exact относительно c9.
ROOT `msg_b211505b113a` разрешает первую implementation ступень B; это не
новый общий аудит, не доказательство writer closure и не включение CREATE.
Все runtime/testcases **NOTRUN**, включая imports/collection. Только чтение,
stdlib literal hashing/JSON, AST и in-memory compile без exec.

## B1: область DB root вместо области Session

Независимое SOURCE-ревью c9 нашло один P1 B1: прежний Session registry
разрешал второй план после смены Session/ORM root, когда внешний DB root
продолжал удерживать прежние locks. SQLAlchemy-managed `rollback_only`
`commit()` и `close()` сохраняют внешний RootTransaction; это не raw-control
сценарий. Новый follow-up устраняет этот путь по исходникам, **runtime closure
не подтверждён** и независимый ретест follow-up не выполнен.

Ревью: task `task_6281b7f6ab2b`, dispatch `ctx_c6ca2db07081`,
worker_done `msg_c6583890f657`. Неизменённые внешние артефакты:
`/srv/projects/preview/contract-scoped-locks-review-20261101/review.md`
(SHA256 `4cb6cccdfa7fe37fb19c77db7ab5b1d010a43df8bc251ccf4ba34fdf3e08c89e`)
и `review.json`
(SHA256 `7471abd58c541e36e7a27426f8c3017eb8bd527933885432c3e3db4377ed32e0`).
Follow-up author: task `task_09b1f4ffb939`, dispatch `ctx_b6b4e8de03a7`.
ROOT `msg_5e53b6a0849a` подтвердил managed gap и требование маркера actual
DB root до первого lock SQL; получено через coordinator `msg_b7d21c4aea80`.
c9 не получил PASS, публичный API остаётся замороженным; этот узкий source fix
не закрывает общую программу. Users/roles follow-up принадлежит отдельному
task `task_fdb8ae27074c` / dispatch `ctx_2691863683f8` и здесь не меняется.
Все c9 test definitions и начало PG module, включая target guard, сохранены
byte-exact; добавлены пять PG test functions. Итого **9 unit + 21 PG = 30**
test functions, все **NOTRUN**, parametrized case count UNKNOWN без collection.
Текущие source SHA256/spans и исходные pins приведены в JSON; финальные raw
SHA256 четырёх изменённых файлов передаются отдельно в freeze status, чтобы
не создавать самоссылочный hash JSON. M00–M19/11 и пять parent report pins
сохранены; outside-repo closure **UNKNOWN**.

## API для следующего author users/roles

Модуль `app.services.contract_write_locks`, без HTTP/actors/ACL/application models:

```python
class LockMode(IntEnum): SHARED = 1; EXCLUSIVE = 2
LockRequest(key: ScopedKey, mode: LockMode)  # frozen, exact types
LockPlan(requests: tuple[LockRequest, ...])  # frozen, nonempty full tuple
# plan.requests: original logical keys/modes, including duplicates
# plan.locks: tuple[ActualLock(namespace: int, key: int, mode: LockMode), ...]
ScopedLockCapability(plan: LockPlan)  # frozen; construction does NOT issue it
encode_key(key: ScopedKey) -> bytes
advisory_key(key: ScopedKey) -> tuple[int, int]
acquire_scoped_locks(session: Session, plan: LockPlan) -> ScopedLockCapability
async acquire_scoped_locks_async(session: AsyncSession, plan: LockPlan) -> ScopedLockCapability
require_scoped_locks(session: Session, capability: ScopedLockCapability,
                     required: tuple[LockRequest, ...]) -> None
```

Async acquisition вызывает **тот же** sync implementation через `run_sync`;
validator вызывается с `async_session.sync_session`, не делает IO. Ошибки
формы дают `TypeError`; нарушение entrance/lifetime/coverage даёт
`ScopedLockError`, требующий rollback всей root. Никаких commit/rollback,
flush, DDL, actors/ACL, row locks, fallback или retries внутри helper.

| Exact key constructor | ROOT namespace | Payload `key` |
|---|---:|---|
| `AppKey(app_id: UUID)` | `0x50430010` | app |
| `ClientKey(client_id: str)` | `0x50430020` | client |
| `UserKey(user_id: UUID)` | `0x50430030` | user |
| `CompanyKey(company_id: UUID)` | `0x50430040` | company |
| `InstallationKey(installation_id: UUID)` | `0x50430050` | installation |
| `CreateProfileKey(profile_id: UUID)` | `0x50430060` | create_profile |
| `RoleKey(company_id: UUID, role_id: UUID)` | `0x50430070` | role |
| `MemberKey(company_id: UUID, user_id: UUID)` | `0x50430080` | member |
| `RefCompositeKey(company_id: UUID)` | `0x50430090` | ref_composite |
| `TypeCatalogKey(type_code: str)` | `0x50430095` | type_catalog |

UUID parts принимают только `type(value) is UUID`; строки UUID, bool и
subclasses отвергаются. Client/type codes: exact nonempty `str`, без trim,
casefold, Unicode normalization или UUID coercion; пробел сам по себе не пуст.
Key/Request/Mode/Plan subclasses не принимаются. Role/member всегда содержат
company, одинаковый role/user в разных companies имеет разную logical identity.

## Canonical v1 bytes и полный порядок

Единственный encoder: объект `{"v":1,"key":kind,"parts":{field:value,...}}`,
UUID представлен lowercase hyphenated `str(UUID)`. `json.dumps(sort_keys=True,
ensure_ascii=True, separators=(",",":"), allow_nan=False).encode("utf-8")`.
ASCII escaping сохраняет точную строку; UTF-8 bytes не содержат BOM/newline.
Namespace не входит в payload; kind различает типы. SHA256, первые четыре
байта, big-endian **signed32**. Namespace тоже PostgreSQL signed32 integer.

Literal bytes, полные SHA256 и signed32 для всех десяти типов закреплены в
JSON `golden_vectors` и unit module; ожидания вычислены независимо stdlib из
literal bytes, production encoder не вызывался. Например:

```text
{"key":"client","parts":{"client_id":"client-A"},"v":1}
SHA256 69630af0726cee7674ef25bafbbfbd4b3618b154c08f668bc34a3b16815a3e56
(namespace, key) = (1346568224, 1768098544)
```

До первого acquisition план объединяет одинаковые **actual** `(namespace,
signed32key)` в strongest mode и сортирует эти числовые пары. Отрицательные
ключи идут раньше положительных внутри namespace. Один merged key означает
ровно один SQL acquire, без SHARED→EXCLUSIVE upgrade. Оригинальные typed keys
и их режимы сохраняются: если A SHARED столкнулся с B EXCLUSIVE, SQL берёт
EXCLUSIVE, но validator по-прежнему не разрешает A EXCLUSIVE. Незаявленный
logical key с тем же hash не покрыт capability. Реальная literal коллизия:
Client `collision-12634` / `collision-44041`, prefix `c1aec7ae`, key `-1045510226`.

SQL shape: две статические text statements с **двумя** `bindparam(type_=Integer)`
и явными `CAST(:namespace AS INTEGER), CAST(:key AS INTEGER)`:
`pg_advisory_xact_lock_shared` / `pg_advisory_xact_lock`. Session-level и
однопараметрические bigint locks helper не использует. Targeted comparison
existing producers и их source pins находится в JSON; диапазон не совпадает
с `434532`, `4711`, `0xed012`, `0x1ed9e12`, `0x9c1ce5`, `0x1a5c5ed`, `0x1d7a0`.
Legacy location/reference bigint bytes остаются прежними, это другой PG keyspace.
Outside-repo namespace/writer closure **UNKNOWN**.

## Entrance, lifetime и обязанности caller

Caller входит с реальными пустыми `Session.new/dirty/deleted`, active Session,
без активного/неактивного nested объекта Session/Connection, без twophase и
AUTOCOMMIT. Чистая Session может начать root; read-only MVCC discovery в уже
начатой clean root разрешён под `no_autoflush`. Helper не обнаруживает
произвольные предыдущие SQL/row/FK/advisory locks; caller обязан исключить их.
Поддерживается одна PostgreSQL Connection, один фактический RootTransaction.
Multi-bind enlistment отвергается, добавление другой connection инвалидирует cap.

Один acquisition attempt на фактическую пару **(Connection, RootTransaction)**;
повторный acquire, extension и upgrade отвергаются до нового lock SQL.
Отдельный `_ATTEMPTS` — WeakKeyDictionary с actual RootTransaction key и
**weakref Connection value**. Он не хранит Session, ORM root или `_Entrance`,
который удерживал бы DB root через value. Маркер ставится до первого lock SQL
и остаётся после успешного или частичного acquisition, независимо от Session,
`Session.info`, смены ORM root, `rollback_only` commit/close. Пока DB root жив,
даже другая Session на той же Connection не получает второй план. Отказ другой
Session не инвалидирует действующую cap первоначального issuer. Старый маркер
может жить до GC завершённого RootTransaction; новый фактический DB root имеет
другой key. Только реальное завершение DB root и новая DB transaction допускают
новую попытку с подходящим свежим ORM root, а не один лишь Session commit/close.

Для использования subset вызывают validator. Issuance registry связан с
**объектом issuing sync Session**, actual SessionTransaction root, actual
Connection и её DB RootTransaction, проверяет source-pinned enlistment
`root._connections`. Cap должна быть тем самым зарегистрированным объектом;
foreign Session, copy/deepcopy/replace или сконструированная cap не принимаются.
Validator допускает authorized pending ORM writes, не требует clean state.

Per-Session `after_transaction_create/end` сохраняют invalidation при nested
истории и завершении root; `after_begin` отвергает другой connection. На
конкретной Connection commit/rollback/savepoint/rollback_savepoint/release_savepoint
сразу poison state. После begin_nested→rollback/release прежняя active root
и исчезнувший nested объект **не восстанавливают** capability. Обычный internal
flush child с `nested=False` не инвалидирует cap. Любой `BaseException` во время
acquisition оставляет poisoned state; caller откатывает **всю** root, затем
заново делает discovery и full plan. Helper не выпускает частичную cap.

Гарантия относится к **SQLAlchemy-managed lifetime** и object enlistment;
это не backend receipt и не универсальная проверка server transaction ID.
Эта граница принята ROOT `msg_c15b81d3670a`; B1 исправлен внутри неё.
Raw SQL COMMIT/ROLLBACK/SAVEPOINT и прямой driver transaction control запрещены
в participating caller: такие операции обходят эти API events. Helpers не
парсят SQL и не доказывают отсутствие hidden prior locks. После ожиданий caller
перечитывает pointers/identity/policy/rows на той же root/connection; изменение
плана требует rollback и fresh full plan. Cap не означает business identity,
авторизацию, участие всех writers или успешный commit.

Для users/roles adapters следующая ступень: membership root заранее объявляет
User SHARED + old/new Role SHARED + Member EXCLUSIVE; возможное удаление User
требует User EXCLUSIVE **заранее**. Role update/delete объявляет Role EXCLUSIVE
перед holder probe/mutation. Company и прочие keys добавляются по реально
затронутым parents, не автоматически EXCLUSIVE для всех tenant writers.
Эти adapters сейчас не изменены и не объявлены замкнутыми.

## Source pins и будущие проверки

JSON содержит exact SHA256/ranges первичных installed SQLAlchemy **2.0.36**
`orm/session.py`, `orm/events.py`, `engine/base.py`, `engine/events.py`;
прочитаны только filesystem/source/AST. Использование `_connections` и
`_is_autocommit_isolation` является узкой version-sensitive интеграцией;
смена SQLAlchemy требует отдельного review и runtime verification.
Для B1 дополнительно закреплён `engine/util.py:59–67`: TransactionalContext
объявляет `__weakref__`; `engine/base.py:2509` задаёт наследование Transaction,
`2652–2676` — наследование/slots RootTransaction. Возможность weak key выведена
из этих исходников, без импорта SQLAlchemy и без runtime weakref probe.
`orm/session.py:1205–1258,1310–1328,1405–1434` закрепляет сохранение внешнего
DB root при `rollback_only` join/commit/close.
Parent reports закреплены raw pins и не переписаны; сохранённый общий аудит
этим helper не сокращён и не закрыт.

Авторские unit specifications покрывают exact types/encoding/goldens/order,
коллизии/merge/SQL two-int/forgery. PG specifications требуют real двух Sessions,
actual transactions, SHARED coexistence, EXCLUSIVE wait по `pg_locks` +
`pg_blocking_pids`, disjoint companies, logical collision coverage, commit/
rollback/savepoint/foreign/copy/dirty-entry/authorized flush, cancellation-style
BaseException и общий async path. Ни fake lock True, ни sleep-race, ни NullPool.
Все **NOTRUN**; latency, pool behavior, driver behavior и guarantees не измерены.

PG module до app/SQLAlchemy/driver imports требует exact равенства явных
`CONTRACT_SCOPED_LOCKS_PG_URL` / `CONTRACT_SCOPED_LOCKS_PG_ROOT_APPROVED_URL`,
approval marker `ROOT-approved-synthetic-contract-scoped-locks-v1`, схему URL
`postgresql+psycopg`, DB `contract_scoped_locks_synthetic_<suffix>`, без query/
fragment. ROOT отдельно заморозит target и execution limits. Этот guard
**не защищает conftest**, который pytest может загрузить раньше; ordinary pytest
не объявляется безопасным. Новый runner/installer не добавлен.

Schema/CREATE/OAuth routes **OFF**. Последующее ROOT `msg_cbf16474f85b`
зарезервировало SOURCE ordinal4 `0004_partner_contract_create`, parent `0003`,
за отдельным schema author; schema acceptance/activation ещё pending. Helper
не трогает models, schema, auth/OAuth/identity/app/company/product paths,
не включает миграции и не доказывает принятие всей ступени B.
