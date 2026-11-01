# M15: инвентаризация объявленных scaling-строк — SOURCE ONLY / NOTRUN

Итоговый scope Root: **INVENTORY / VALIDATION ONLY, ZERO DML/DDL**.
`inspect_m15_owned(world, expected_database, expected_user)` читает только
объявленные native PK и проверяет известные связи через actual factory. Это
не очистка строк, не доказательство полного владения и не проверка disposal.
Имя файла `partner_activation_scaling_cleanup.py` сохранено по заданию; его
содержимое — только inventory. Ни hook, ни утилизация окружения здесь не реализованы.

Root выбирает **один scaling-case на одно свежее полностью owned native PG
окружение**. Пока world жив: inventory; затем закрытие клиентов/pools и уничтожение
точного owned PGcontainer/database силами Root. Между кейсами строки/БД не
переиспользуются. Ошибка inspection или отсутствие registry не отменяют disposal
и не превращаются в «cleanup PASS». Destructive helper снят Root с задания;
его незакоммиченный черновик сохранён только во внешних superseded артефактах.

Основа: `Electro-Interfaces/ClearLedger`, commit
`2be77a5169f51916a835e30d544b850d9568d28e`, tree
`555b295b309a74a5f1c093d36f85f9949e2b1a54`; независимо посчитано **3392** исходных
записи `git ls-tree -r`. Компонент — `core-api-development`, текущая Task/Dispatch
WT. Только два новых файла; все прежние blob/mode сохраняются. Финальные
commit/tree и SHA отчётов находятся во внешнем авторском отчёте, без самоссылки.

## Подтверждено текстом исходников

Все ссылки ниже относятся к указанному commit, без импорта или исполнения.

| Предмет | Источник с точными строками |
|---|---|
| 20 параметров, оригинальная scaling-функция | [tests/test_partner_contract_activation_batching_pg.py:475–800](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/test_partner_contract_activation_batching_pg.py#L475-L800); сама функция 486–800 |
| Setup-owned: locations/resourceitems/CP/Org, User + native membership, credentials | [тот же файл:496–534](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/test_partner_contract_activation_batching_pg.py#L496-L534) |
| Replacement 200, actual descendants capture; количество p+3r+2 | [тот же файл:537–554](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/test_partner_contract_activation_batching_pg.py#L537-L554) |
| Исходный world и базовые родители; m15 capture/hook отсутствует | [tests/test_partner_contract_activation_pg.py:39–126](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/test_partner_contract_activation_pg.py#L39-L126) |
| Native issuer: другой world; его ID не подменяют activation world | [tests/partner_contract_issuer_fixture.py:123–202](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/partner_contract_issuer_fixture.py#L123-L202) |
| Удаление прежних children и создание replacement UUID; Type использует тот же composite PK | [app/services/partner_contract_profiles.py:272–299](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/services/partner_contract_profiles.py#L272-L299) |
| Type/Principal/Ref: полные PK, typed XOR и FK CASCADE | [app/models_partner_contracts.py:43–89](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models_partner_contracts.py#L43-L89) |
| Revision4 SQL: действительные FK, включая raw Type code FK | [schema_migrations/revisions/0004_partner_contract_create.sql:21–74](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/schema_migrations/revisions/0004_partner_contract_create.sql#L21-L74) |
| UserCompany PK user_id,company_id; ссылки на CP/Org | [app/models.py:207–269](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models.py#L207-L269) |
| Parent UUID/opaque string | [app/models.py:1113](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models.py#L1113), [1183](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models.py#L1183), [4979](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models.py#L4979) |
| Credential, ResourceItem FK, TokenFamily SET NULL | [app/models_partner.py:33–41](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models_partner.py#L33-L41), [71–86](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models_partner.py#L71-L86), [159–166](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/models_partner.py#L159-L166) |
| CanonicalUUID выдаёт uuid.UUID; helper ничего не конвертирует | [app/db_types.py:10–45](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/db_types.py#L10-L45) |
| Native catalogue допускает extra physical FK сверх ORM | [tests/partner_contract_schema_v4_fixture.py:141–225](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/partner_contract_schema_v4_fixture.py#L141-L225) |
| Native lifecycle и отдельное закрытие factory/connection | [тот же файл:349–425](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/tests/partner_contract_schema_v4_fixture.py#L349-L425) |
| Raw legacy FK вне моделей | [app/database.py:2618](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/database.py#L2618), [2752](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/database.py#L2752), [4400](https://github.com/Electro-Interfaces/ClearLedger/blob/2be77a5169f51916a835e30d544b850d9568d28e/clearledger/server/app/database.py#L4400) |

Scaling-source Git blob: `aad54ce01e6546d4a509a67c64660a5dc05b0468`;
полный файл SHA256: `05eb6c901e32b925c8db54f379d01825cf415c95758b83d0b5f51b35cd17278a`.
Это pin исходника, не свидетельство исполнения функции.

## Контракт inventory helper

Вход — actual `SimpleNamespace` world и явно переданные Root точные database/user
из его owned descriptor. Используется только `world.factory`: конкретный
`async_sessionmaker` с native AsyncSession и AsyncEngine, без переданной
чужой session/connection, custom sync session или multi-bind factory.
`w.m15_owned` — непустой tuple точных пар `(model_name, native_pk)`.
Весь список проверяется до открытия session: фиксированные concrete модели,
полные PK с точным `type`, без casts/UUID-конверсии/нормализации строк.
Неизвестные модели, list/set/dict, неполные composite tuples, неверные native
компоненты, дубли и известные базовые parent IDs вызывают явный отказ.

| Разрешённая модель | Полный PK / точный Python type | Setup | Replacement descendants |
|---|---|---:|---:|
| PartnerContractCreateType | `(profile_id: UUID, type_code: str)` | 0 | 1 |
| PartnerContractCreatePrincipal | `id: UUID` | 0 | p+1 |
| PartnerContractCreateRef | `id: UUID` | 0 | 3r |
| PartnerCredential | `id: UUID` | k | 0 |
| PartnerResourceItem | `id: UUID` | c−1 | 0 |
| UserCompany | `(user_id: UUID, company_id: UUID)` | p−1 | 0 |
| User | `id: UUID` | p−1 | 0 |
| Counterparty | `id: UUID` | r−1 | 0 |
| Organization | `id: UUID` | r−1 | 0 |
| ServiceLocation | `id: str`, пробелы/Ёё сохраняются | max(r,c)−1 | 0 |


Type и UserCompany считаются как строки с двухкомпонентным PK; порядок
UserCompany — именно `(userUUID, companyUUID)`. ServiceLocation сохраняет все
пробелы и Ёё. Company/Profile/App/Installation/Role/Client/Grant отсутствуют в
allowlist. Admin/member, base CP/Org/Locations и их membership запрещены.

Новая pristine session запрашивает `postgresql_readonly=True` до первого SQL.
Настоящий SELECT проверяет `current_database()`, `current_user`, `current_schema()`
и `current_setting('transaction_read_only')`: требуется точное совпадение с
expected database/user, schema `core`, read-only `on`. Если драйвер/настройки
не поддерживают этот запрос, inspection отказывает без fallback или смены
isolation; поддержка режима остаётся runtime NOTRUN. Session всегда делает
rollback read transaction и закрывается через async context, включая исключения
и cancellation; ошибок не подавляет. Write transaction или commit здесь нет.
Допуск actual factory/provider и исходного READ COMMITTED остаётся UNKNOWN у Root;
helper не меняет isolation и не объявляет этот допуск выполненным.

Дальше читается единственный actual Profile PK по installation/client/company
и каждая объявленная строка только по полному равенству её PK. Проверяются
actual full native PK, профиль и тип selection, principal/ref pointers,
client/installation/company, User.home, UserCompany role/own-org и обе компоненты
membership. Это проверка **известных связей**, она не устанавливает историю
создания строк. Никаких generic catalogue/FK engine, snapshot guesses или
inferred IDs нет; helper не расширяет объявленный набор.

Результат содержит counts по моделям и PK-компонентам, исходные native PK в tuple
manifest и SHA256. Hash учитывает порядок registry: model-name UTF-8 и native
компоненты кодируются length-framed bytes с type tags; UUID остаётся 16 исходными
байтами, str — точным UTF-8. Native manifest не превращается в UUID-строки.
Hash доказывает только совпадение конкретного inventory manifest, не ownership
или disposal. Результат явно оставляет registry completeness, ownership capture,
physical FK closure **UNKNOWN**, row cleanup performed=false, DB disposal
**ROOT responsibility; NOT VERIFIED**. При missing registry/descriptor, mismatch
или исчезнувшем declared PK результатом является исключение, а не пустой успех.

## Что остаётся неизвестным и почему выбран whole-environment disposal

`world` хранит anchors, но не baseline Profile/Principal/Ref/Type PK или независимый
полный setup snapshot. `m15_owned` объединяет setup и descendants только после
соответствующих присваиваний. Replacement создаёт новые Principal/Ref UUID,
а Type повторно использует `(profile_id, w.code)` — before/after PK delta не
доказывает новый lifecycle этого PK. Inventory не объявляет эти проблемы решёнными.

Ошибка до заполнения registry или после commit replacement, но до/во время
capture, может оставить metadata неполной. Даже если все объявленные строки
найдены и известные связи верны, полнота ownership остаётся UNKNOWN. Таблица
формул не достраивает пропущенные ID.

Статический проход только `app/models*.py` обнаружил следующие single-column
inbound FK объявления (не полный physical catalogue):

| Родитель | CASCADE | SET NULL | RESTRICT | NO ACTION |
|---|---:|---:|---:|---:|
| User | 31 | 105 | 2 | 0 |
| Counterparty | 6 | 23 | 1 | 3 |
| Organization | 2 | 4 | 2 | 14 |
| ServiceLocation | 13 | 19 | 0 | 0 |
| PartnerCredential | 0 | 1 | 0 | 0 |

Есть также legacy SQL FK и `native_extra_fks`; отсутствие inbound FK к apparent
leaf в просмотренном ORM не означает отсутствия actual FK/триггеров. Например,
UserCompany own-org, PartnerInstallationLocation/ResourceItem и PartnerTokenFamily
создают дополнительные связи. **Row-level cleanup исключён из финального scope**,
поэтому нет попытки доказать полную closure или обойти FK ради прогона.
Root отвечает за уничтожение всего изолированного owned окружения.

## Кардинальности 20 исходных случаев

`p=principal_count`, `r=ref_count`, `c=canonical_count`, `k=credential_count`.
Независимая stdlib AST/literal арифметика по исходному decorator и циклам:

- setup: `(p−1)+(p−1)+(r−1)+(r−1)+(max(r,c)−1)+(c−1)+k`
  = **2p+2r+max(r,c)+c+k−6**;
- actual replacement descendants только после успешного capture:
  `(p+1)+3r+1` = **p+3r+2**;
- сумма при обоих полных capture: **3p+5r+max(r,c)+c+k−4**.

Это количество объявленных строк, не всего world/БД, не FK closure. Audit/profile
updates, исходные fixture parents и уже заменённые seed children не добавляются.
При failure/incomplete capture реальное владение/полнота **UNKNOWN**, формула
не заменяет actual metadata.

| Case | p/r/c/k | Setup | Desc | Total | T | P | R | Cred | Item | UC | U | CP | Org | Loc | Admission |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| graph-1 | 1/1/1/0 | 0 | 6 | 6 | 1 | 2 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |
| graph-2 | 2/2/2/0 | 6 | 10 | 16 | 1 | 3 | 6 | 0 | 1 | 1 | 1 | 1 | 1 | 1 | small candidate / NOTRUN |
| graph-8 | 8/8/8/0 | 42 | 34 | 76 | 1 | 9 | 24 | 0 | 7 | 7 | 7 | 7 | 7 | 7 | small candidate / NOTRUN |
| graph-100 | 100/100/100/0 | 594 | 402 | 996 | 1 | 101 | 300 | 0 | 99 | 99 | 99 | 99 | 99 | 99 | LARGE NOTRUN / Root resource admission |
| mixed-large-100-257 | 100/100/257/0 | 908 | 402 | 1310 | 1 | 101 | 300 | 0 | 256 | 99 | 99 | 99 | 99 | 256 | LARGE NOTRUN / Root resource admission |
| principals-1 | 1/1/1/0 | 0 | 6 | 6 | 1 | 2 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |
| principals-2 | 2/1/1/0 | 2 | 7 | 9 | 1 | 3 | 3 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | small candidate / NOTRUN |
| principals-8 | 8/1/1/0 | 14 | 13 | 27 | 1 | 9 | 3 | 0 | 0 | 7 | 7 | 0 | 0 | 0 | small candidate / NOTRUN |
| principals-100 | 100/1/1/0 | 198 | 105 | 303 | 1 | 101 | 3 | 0 | 0 | 99 | 99 | 0 | 0 | 0 | LARGE NOTRUN / Root resource admission |
| refs-1 | 1/1/1/0 | 0 | 6 | 6 | 1 | 2 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |
| refs-2 | 1/2/1/0 | 3 | 9 | 12 | 1 | 2 | 6 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | small candidate / NOTRUN |
| refs-8 | 1/8/1/0 | 21 | 27 | 48 | 1 | 2 | 24 | 0 | 0 | 0 | 0 | 7 | 7 | 7 | small candidate / NOTRUN |
| refs-100 | 1/100/1/0 | 297 | 303 | 600 | 1 | 2 | 300 | 0 | 0 | 0 | 0 | 99 | 99 | 99 | LARGE NOTRUN / Root resource admission |
| canonical-1 | 1/1/1/0 | 0 | 6 | 6 | 1 | 2 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |
| canonical-2 | 1/1/2/0 | 2 | 6 | 8 | 1 | 2 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | small candidate / NOTRUN |
| canonical-8 | 1/1/8/0 | 14 | 6 | 20 | 1 | 2 | 3 | 0 | 7 | 0 | 0 | 0 | 0 | 7 | small candidate / NOTRUN |
| canonical-257 | 1/1/257/0 | 512 | 6 | 518 | 1 | 2 | 3 | 0 | 256 | 0 | 0 | 0 | 0 | 256 | separate canonical-257 / NOTRUN |
| credentials-1 | 1/1/1/1 | 1 | 6 | 7 | 1 | 2 | 3 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |
| credentials-2 | 1/1/1/2 | 2 | 6 | 8 | 1 | 2 | 3 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |
| credentials-8 | 1/1/1/8 | 8 | 6 | 14 | 1 | 2 | 3 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | small candidate / NOTRUN |


`T/P/R` — Type/Principal/Ref; `UC` — число полных пар UserCompany, не число UUID.
Число PK-компонентов Type=2, UserCompany=2, остальных=1. Native counts отдельных
моделей не объединяются по совпадению UUID между таблицами.

15 small — кандидаты на отдельный допуск Root, все пока NOTRUN. `canonical-257`
выделен отдельно: p=r=1, исходный chunk 256+2 учитывает fixture extra_loc.
Четыре случая graph-100/mixed-large-100-257/principals-100/refs-100 остаются
**LARGE NOTRUN**, нужен отдельный ресурсный допуск Root. Credentials 1/2/8 —
выборки неограниченной кардинальности, не production cap.

## Будущий отдельный function-scoped Root fixture/hook — предложение

1. До создания world Root сохраняет надёжный owned environment descriptor:
   точный PGcontainer/database ID и ожидаемые database/user; descriptor независим
   от `w.m15_owned` и существует даже при setup failure. Нельзя находить target по
   имени, суффиксу, переменной окружения или предположению. Один selected-case
   получает один fresh wholly owned native PG environment; другой case — другое.
2. Hook получает actual world/factory до теста и сохраняет факт lifecycle; после
   теста, пока world и factory ещё живы, пытается вызвать `inspect_m15_owned` с
   expected database/user именно этого descriptor. Ветка `finally` обязательна
   также для assertion/exception/cancellation и failure setup. Это будущее
   внешнее подключение; исходные world/factory/test здесь не изменены.
3. Если world/registry отсутствует, capture неполон, descriptor недоступен или
   inspection падает, записать явный UNKNOWN/inspection failure и сохранить
   исходную ошибку. Не создавать guessed registry, FakeSession, предполагаемые
   ID/SQL результаты; не объявлять missing registry «нет строк». Если descriptor
   потерян, нужен отдельный Root ownership recovery, без широкого поиска/удаления.
4. В том же teardown после попытки inspection закрыть actual HTTP clients,
   sessions, все engine/driver pools и соединения, включая native fixture-held
   connection. Закрытие одного factory pool не означает, что всё окружение
   закрыто. При ошибке закрытия сохранять обе ошибки и идти по собственной
   процедуре disposal точного owned environment, не теряя исходный failure.
5. Root уничтожает **ровно** container/database из заранее сохранённого owned
   descriptor даже при missing registry/inspection error. Hook не должен
   зависеть от успешности inventory. Descriptor failure означает невозможность
   подтвердить disposal, требует явного отчёта и восстановления ownership;
   никакого fallback target. Реальное подтверждение уничтожения — отдельное
   наблюдение Root, не hash inventory или закрытие session.
6. Будущие Root проверки: missing registry до присваивания; replacement commit
   с неполным capture; invalid/duplicate/unknown/native-type metadata; оба
   composite PK; opaque spaces/Ёё; identity mismatch; actual read-only режим;
   missing declared row/foreign pointer; exception/cancellation и error teardown;
   доказательство close-all-pools и точного owned environment destruction.
   Здесь ни одна из них не запускалась. Нет row reuse или between-case row cleanup.

## Статус и пределы вывода

Выполнены только чтение текста/Git и собственные stdlib AST/literal arithmetic,
hash/JSON, compile без exec. Ни helper, ни app/library/test API, ни извлечённый
код не импортировались и не вызывались. Не было pytest collection, SQL/PG,
20 fixtures, runtime, Docker, Node, сети, RAW/control/env/DSN или production.
Первый широкий AST-проход остановился на существующем Python-3.12 f-string под
доступным Python 3.11; затем ограниченный проход `models*.py` и новый helper
разобраны успешно. Это не проверка исполнения всего приложения.

Со слов Root, не собственный PASS автора: 341 checkpoint Root-observed PASS;
серии 36/58/93/93 приняты; CPC93/CPD62 ещё требуют независимого RAW. Все 20 scaling
— NOTRUN. Эти наблюдения не доказывают scaling coverage или готовность всего API;
private RAW не читался. Author statics означают только статическую проверку
source-only пакета, без runtime/production acceptance.

Оригинальная программа **M00–M19 + 11 open**, complete=false, сохраняется.
Только ссылка, без чтения/изменения RAW:
`/srv/projects/preview/contract-create-workflow-20261101/report.json#/original_program`,
semantic SHA256 `4ac5f8535d2f9f0b3c7fb910cad958165b8ff886eb48edc2c68726d09c005345`.
20+11 не объявляются завершёнными. Финальный пакет следует Root inventory-only
update `msg_a275fbd7e97f`, доставленному `msg_8929426b1e11`; прежние требования
к destructive helper заменены этим scope. Runtime, fixture hook, provision и
whole-environment disposal остаются за отдельным допуском/проверкой Root.
