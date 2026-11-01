# Native document creation: parent guards

Статус: SOURCE implementation + AUTHORDEFINITIONS, NOTRUN, включая collection.
Это отдельный producer `docs_router.create_doc`, а не приёмка всего DOCS или
удаления Organization. JSON рядом сохраняет все исходные 20 разделов программы
и 11 общих условий; каждый остаётся OPEN.

Вход владеет прежней транзакцией: новый документ делает свой прежний commit,
replay возвращает карточку без внутреннего commit. В replay native permission
может записать break-glass use, AuditEvent и вызвать dispatch; завершение такой
транзакции остаётся у get_db. В сервисе нет commit, rollback, flush или retry.

## Полный initial B

До первого legacy doc-create, row/FK wait и DML выполняются clean-entry check
и scalar MVCC discovery под no_autoflush. Pending new/dirty/deleted отклоняются
без очистки, SQL и отката за caller. До блокировок ошибки UUID не подменяются:
discovery лишь пробует выделить кандидата, оригинальный validator сохраняет
ошибку и порядок проверок.

Один immutable LockPlan содержит только SHARED:

| Ключ | Фактический набор |
|---|---|
| CompanyKey | выбранная компания, actual home actor и всех новых/наблюдаемых replay FK Users, actual owner читаемой Role |
| UserKey | actor, responsible/signatory из payload, User parents наблюдаемого replay: author/responsible/signatory/registered_by/archive_accepted_by |
| MemberKey | выбранная компания × actor и новые responsible/signatory, включая отсутствующие членства |
| RoleKey | actual owner + role_id, только когда assert_company_product реально читает именованную роль |
| RefCompositeKey | выбранная компания |

Native policy суперадмина и admin-члена не читает CompanyRole. Существующая
foreign Role не запрещается новой policy: защищается её фактический owner.
Если строки Role нет, прежний fallback к modules членства сохраняется;
отсутствующий ключ объявляется в компании членства. Появившийся иной owner
после ожидания требует whole-root rollback, а не новых ключей.

Канонические namespace, encoding, hash и physical order остаются у
`contract_write_locks`; повторного acquire, расширения и локальных casts нет.
DocKind не получает contract TypeCatalogKey: для него нужен только row SHARE.

## Порядок и свежесть

После полного B: Company SHARE по UUID → User SHARE по UUID → actual Role SHARE
→ Counterparty SHARE по UUID → Organization SHARE по UUID → Member SHARE по
UUID → DocKind SHARE. Org/CP блокируются только в выбранной компании, перед
DocCard INSERT. Чужие/невалидные ссылки затем отклоняют прежние validators.
Member SHARE следует после обоих parent SHARE: legacy Organization DELETE
сначала удаляет Org, потом SET NULL меняет Member. Обратный порядок создавал бы
цикл при own_organization_id actor или выбранного ответственного.

После всех row waits helper сверяет homes/owners/member-role/replay pointers,
обновляет clean retained identities, повторяет actual native session, visit и
assert_company_product. Caller повторяет прежние проверки kind/attrs/subject,
object/CP/Org/сотрудников в прежнем порядке. Для manual contract-document после
прежнего doc-create advisory wait выполняется ещё одна такая свежая проверка
и пересборка values до replay permission или INSERT.

Изменившийся parent либо новый replay parent вне initial plan даёт 409
«Данные изменились одновременно; повторите запрос» до DML. Нужны rollback всего
root и новый запрос. Обычные ошибки UUID, kind/attrs/refs и native admission
остаются у прежних функций. Канонизация source_ref, прежние replay конфликты,
DocEvent, commit, refresh и response сохранены. Permission replay не вызывается
в discovery; после неё clean/expiry не выполняются, чтобы сохранить её pending
audit/break-glass и прежний порядок уведомления.

## Определения проверки и границы

Unit-модуль вызывает actual plan, helper и create_doc. Подменённый I/O проверяет
только отказы до выдачи capability: pending, partial acquisition и cancellation.
Успешная capability или policy не подделывается.

PG-модуль предназначен для **синтетических данных на полной native-схеме** с
реальными ORM, FK, constraints и triggers. DDL, runner и provisioning в нём нет.
ROOT отдельно готовит одноразовую БД и изолирует родительский conftest **до любых
app imports**: conftest репозитория иначе импортирует main и удаляет схемы ещё
до локального guard. Требуются согласованный source/UUID состав, native schema
bootstrap, PostgreSQL/asyncpg, pytest/pytest-asyncio и точные согласованные env
значения из guard модуля. Guard не является разрешением runtime. Идентификаторы
данных случайные; строковые поля укладываются в реальные ограничения. ROOT
владеет удалением всей одноразовой БД; fixture закрывает только свой engine.

Отдельная OPEN prerequisite: actual replay читает DocCard.author_id,
responsible_id, signatory_id, registered_by и archive_accepted_by как UserKey
producers. Их исходный plain UUID mapping требует проверки и канонического
producer mapping владельцем persistence перед native runtime. Здесь нет
локальной нормализации, isinstance fallback или изменения модели/codec.
DocKind/id/company не получают вымышленных typed-key consumers.

Определения PG охватывают actual create_doc против actual legacy Org DELETE
в обоих порядках с ownOrg actor/selected Member и commit/rollback; actual
Organization UPDATE в обоих порядках; Counterparty UPDATE; retained identity
freshness; session/Role/home drift; visit после последнего kind/manual wait;
manual replay и поздний replay User parent; pending/cancellation; lifetime
настоящей capability; strict-superadmin break-glass/audit/notify commit/rollback.
Negative oracles наблюдают noDML/noDocEvent/noNotify и pending до caller rollback;
ожидания подтверждаются pg_blocking_pids с ограниченным временем.

Это определения, не collected cases и не PASS. Source-only проверка ограничена
AST и compile в памяти без импорта проектных объектов. Полная native runtime
приёмка, остальные DOCS roots (включая work_router → doc_action), полный child
closure Organization DELETE, physical integration и исходная программа 20+11
остаются OPEN. Прямых Python callers именно docs_router.create_doc при targeted
source search не найдено; одноимённый ops_terms.create_doc принадлежит другому
входу. FastAPI registration/DI не подтверждают исполнение маршрута.
