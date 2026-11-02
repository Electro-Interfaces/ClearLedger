# РусГидро P1b: хранилище квитанций V2

SOURCE ONLY, runtime NOTRUN автором. Task `task_dbf6f2522937`, Dispatch
`ctx_8e610166ab92`, OwnRun `run_1e4d8306c273`. Назначенное дерево:
`/home/mag/orca/workspaces/ledger-app/rushydro-contract-cycle-receipts-author-20261101`.
База `cfd804c469d203c505b57668af8b57d9b4a866a2`, tree
`133b792fc56220ca1c4dcafc8483c1fe8fc5ba90`.

Решения exactBASE: `rushydro-contract-write-20261101/PERSISTENCE-DECISION.md`
(128 KiB), `ROOT-DECISION.md`, неизменное предложение TARGET `66f43993`.
Уточнение Root `msg_55461d76e9df`: исходный client — точный varchar64,
не UUID. Вся реализация ограничена 11 файлами из phase1 `msg_eb1406e550c2`.

Revision `0005_partner_contract_cycle_receipts`, parent
`0004_partner_contract_create`: ровно две ORM/SQL-таблицы, 23 колонки,
9 CHECK, 2 RESTRICT FK, 5 индексов, 2 функции, 4 триггера. Таблицы
исключены из legacy create_all по имени независимо от schema/flags.
Регистрация — существующий database bootstrap owner, без нового consumer.
Known source head5 принимает старые применённые prefixes и проверяет весь
применённый каталог; текущим v1 не требуется неприменённая revision5.
Будущий receipt writer обязан требовать полный prefix5 до записи.
Artifact SHA-256: `99d6c539f5a5e4962926e6d8978db3a5487bab0d5fb20531b31cd95daf59d42d`.

Parent UNIQUE: `(company_id,app_id,installation_id,operation,command_key)`.
Все пять обязательны. Client сохраняется без UUID parse/trim/casefold;
user/grant/profile/app/installation/target — UUID snapshots без ресурсных FK.
Company принадлежит настоящему `core.companies`, удаление RESTRICT.
Это не доказывает существование ресурсов, user grant или полномочия.
Operation version2 — структурная версия команды, hash_version1 — только
формат SHA-256 (64 lowercase hex), новый алгоритм хеширования не реализован.

Result — JSONB object, максимум 131072 байта UTF-8 его сохранённого
`result::text`; учитываются JSONB framing/пробелы, а не длина исходного HTTP.
DDL проверяет структуру, а будущий DTO owner обязан исключить секреты,
токены, storage paths, signed URLs и байты файлов. Receipt — только success.
`created_at` и реальный top transaction id принудительно назначает INSERT
trigger, включая явно поданные NULL/поддельные значения. UPDATE/DELETE
запрещены; BEFORE TRUNCATE FOR EACH STATEMENT стоит на обеих таблицах.
Это не защита от владельца SQL с полномочиями менять DDL/отключать триггеры.

Refs: organization/counterparty/location/site/contract/term/document/version;
UUID XOR точный location String40 (1–40 Unicode-символов, пробелы разрешены,
NUL не представим в PostgreSQL text). Исторические refs неизменны, не дают
прав; одинаковое значение уникально в пределах parent/kind/типа. RESTRICT
ссылка на parent, без cascade истории. INSERT refs разрешён только в той
же исходной top transaction, в том числе из savepoint; после commit запрещён.
Ключ не освобождается сроком, удалением или переписыванием success. Политика
удаления tenant/retention отдельно не решена; текущий FK отказывает.
Hash и location хранятся как text с точным CHECK длины/формата: varchar(N)
может усечь лишние хвостовые пробелы, что нарушило бы strict/noTrim семантику.

Закрытый список внутренних команд (не OAS operationId):

| Цель | Операции с префиксом `v2.` |
| --- | --- |
| contract | contract.create, contract.patch, contract.location.link |
| term | term.create, term.version, term.coverage |
| site | site.contract.link, site.location.link |
| document | document.draft.create, document.contract.link, document.register |
| version | document.version.upload |

Writer/replay в будущем заново проверяет native refs, пользователя, grant,
профиль, членство, компанию и текущие права под общими locks ДО записи/повтора.
If-Match/original expectedVersion и digest — обязанность будущего владельца.
Birth возможен только для contract.create/document.draft.create по отдельной
явной policy; здесь нет birth-кода, Site authority или выдачи прав. Routes18,
DTO/hash-v1/scopes/0004, native Site/file ACL и закрытие периода не менялись.

Автор проверяет только собственными stdlib AST/compile без exec, JSON,
независимым SHA/framing и git diff. SHA всех frozen1..4 payloads и artifacts
сохраняются; entry0005 добавляется, старые четыре entries не переписываются.
Source AST содержит 343 mapped declarations; фактические 343 mappings,
343 metadata tables и 349 физических таблиц должен доказать ROOT (уточнение
`msg_04e3f378a739`). Ожидания: native prefix3=341,
prefix4=347, prefix5=349 (в том числе шесть raw tables).

ROOT запускает ровно 34 группы из `test_rushydro_contract_cycle_receipts_native_pg.py`:
registration-flags-off/on; frozen-source-pins; fresh-prefix5; upgrade4-to5;
repeat5; required4-vs5; public-default-deny; foreign-namespace-untouched;
namespace-five-dimensions; snapshot-without-authority (включая реальные ORM
INSERT/flush/new-session reads); closed12-target-map; strict-hash-versions;
result-object; ascii128KiB; multibyte128KiB; typed-refs-xor/unique;
opaque-location40; db-owned-txid-time; parent/child-immutable;
same-topTX-savepoint; laterTX-ref-denied; key-reuse-denied;
atomic-malformed-rollback; restrict-retention; drift-index/trigger/function/
acl/default; unlogged-collision; function-collision. Fresh5 означает новую
полную native3 базу → explicit4+5, не вымышленную native0 из десяти таблиц.

Полный внешний factory/admission protocol — в docstring suite. ROOT до
импортов предоставляет живое private approval, `receipt_root_factory` и
реальные conn/config/sessionmaker/database/stranger. `bootstrap_probe`
возвращает ровно `{sql,error,metadata_stage}`; error — None либо точные
`{class,message}` исходного исключения. CoreOFF/CoreON/PublicOFF требуют
наблюдавшегося original metadata DDL stage и реального отсутствия таблиц.
PublicON требует конкретного прежнего managed-Core отказа до DDL; foreign
fallback — конкретного ownership/managed отказа. Эти отказы не являются
native PASS исключения create_all. Никаких patched owners/schema gates.
ROOT отдельно фиксирует provisioning provenance, реальные проверки каталога,
закрытие пулов и удаление только своей disposable БД. Обычная pytest collection
не разрешена: прежний conftest выполняет импорты/сброс раньше module guards.
Native SQL/PG/pytest/OAuth/CI и выпуск автором не выполнялись; PASS не заявлен.
