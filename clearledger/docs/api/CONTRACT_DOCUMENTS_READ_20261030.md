# NEXT-R2: явные документы договора во внешнем API

Статус: реализация, отдельные серии ROOT acceptance и официальная SDK-генерация
завершены. Выпуска, merge и включения feature flags не было. Основа изолированной
ветки `agent/api-contract-documents-read-20261030`:
`bdbd8ccb3798316cd4b6794bdc99ecf10af4101a`.

Добавлен candidate `GET /api/v1/contracts/{contractId}/documents`,
`operationId=listContractDocuments`. Всего теперь 14 GET, из них 10 user/service
и четыре только delegated user. Прежние 13 handlers, R1 contract_objects и
существующие cursor/conditions/detail primitives сохраняются.

## Источник связей и решение ROOT

`DocCard.subject_ref='contract:<canonical UUID>'` хранит предмет карточки
(models.py, process_templates.launch и document_requests.create). Native список
`docs_router.list_docs(ref=...)` учитывает также явные `DocRelation.target_ref`.
`ContractDocumentsBlock.tsx` создаёт документы договора через `annex_of` relation;
subject-only subset пропустил бы эти бумаги. Existing индекс
`uq_doc_cards_subject(company_id, subject_ref)` допускает одну предметную
карточку на ссылку; остальные бумаги используют graph edges. ROOT решениями
`msg_ecc63b5d5536`, `msg_b1df177df6d8`, `msg_7c529b1831d2` согласовал оба вида
связи и расширил владение на общий `services/doc_subject_links.py` и точечную
замену native ref block.

Общий helper `subject_documents_clause(company_id, ref)` сохраняет прежний
predicate `DocCard.subject_ref == ref OR EXISTS(DocRelation.company_id == company_id,
DocRelation.doc_id == DocCard.id, DocRelation.target_ref == ref)`.
Оба caller отдельно ограничивают компанию DocCard. EXISTS не размножает
документ при нескольких relations и одновременном subject-ref. Разные subject
и graph refs не делают документ недействительным: каждый явный граф-адресат
считается отдельной связью, как в native read. Неизвестные/null refs сами по себе
не дают связи; relation другого tenant не даёт ID или count.

`contract_usage._DOCUMENTS` дополнительно учитывает `attrs.contract_id` для
консервативной защиты удаления и счётчика использования. Найденный producer
ContractDocumentsBlock сохраняет attrs одновременно с отдельным шагом создания
graph relation. Native ref read и process template resolver не используют attrs
для этой связи. ROOT согласовал сохранить attrs как usage metadata, не выдавать
его за публичный graph edge. Title/raw/source_ref/SourceFile/общий поиск не
участвуют; `contract_usage` не менялся.

## Допуск, контракт и пагинация

Owner новой операции — documents. Действующий policy/access.resolve требует
`documents:read AND contracts:read`, каждый независимый typed grant и только
partner user; service альтернативы нет. Документный module gate сохраняется;
настоящий verifier проверяет текущий user/membership и eligible_scopes обоих
доменов. Parent разрешается прежним `Query.detail("contracts", contractId)`.
Недоступный/чужой/отсутствующий родитель даёт тот же 404.

Далее до count/limit применяются `Query.conditions("documents")`: tenant,
typed documents grant, текущие object/own-org ceilings и `_readable_doc_clause`
того же пользователя, дополненные общим explicit graph clause. Права родителя
не расширяют права на документы, private/strict карточки и bytes.

| Часть | Allowlist |
|---|---|
| Path | contractId, прежний Id |
| Query | pageSize 1..200, default 50; cursor 1..4096 либо отсутствие |
| Body | Непустой stream отклоняется 422 до detail, без накопления body |
| Output | contractId, items[].documentId, total, nextCursor |

Cursor использует существующие HMAC primitives и binding
`contract-documents:<parent UUID>`, actor/client/install/grant, tenant, scopes,
все typed grants, текущие object/organization ceilings и pageSize. Стабильный
порядок DocCard.created_at,id; live pagination без snapshot-гарантии при
конкурентном изменении графа. Другой parent/actor/install/ceilings даёт 400,
отзыв live авторизации сохраняет прежний приоритет отказа. Строка cursor=null
не имеет значения очистки. GET не вызывает write/flush/commit. Настройка auth
в тестах пишет отдельно до снимка; quota остаётся выключенной.

## Проверки и передача ROOT

Worker выполнял только чтение, AST, compile в памяти и Git/hash checks;
app/tests/runner не импортировал, pytest collection, SQL и codegen не запускал.
Сохранены source proof, diff прежних тестов и frozen proposal в private
`.artifacts/contract-documents-read/`. Прежние assertions изменены только для
согласованных counts/registry metadata в шести файлах и нового mock Domain method.

Подготовлен 61 новый HTTP/PG сценарий с real Core login, Code+PKCE/token,
admin installation/grant и действующим verifier; synthetic данные двух компаний,
нескольких users/installations, независимые ALL/SET/EMPTY/MISSING grants,
object/own-org ceilings, native ref parity, duplicate/mismatched graph edges,
private/strict/doc role, files scope/policy/shared source, live user/module/grant
revoke, parent-bound cursor, bounded query/body и persisted business/auth/files.
Отдельный approved runner имеет new61, regression84 и exact affected1 modes: новый модуль
собирается один раз; для regression только служит fixture plugin и не собирается.
Это исключает двойную регистрацию fixture из R1 V2.

ROOT владеет CREATE/DROP ровно `api_contract_documents_test_20261030`, проверяет
пустую БД и ноль клиентов, выполняет schema initialization реальным create_all
и нормальный cleanup. Worker эту БД не использовал. Фактические runtime receipts
указаны ниже; official exporter, .d.ts и typed consumer остаются у ROOT после
review frozen исходников.

### Фактические receipts ROOT

V1/V2 не исполнялись. V3 принят ROOT по exact source/support hashes;
reverse AST прежних product модулей и native router независимо подтверждён.
Первый child остановлен внешним disk-reserve guard до тестов, лог пуст;
ROOT выполнил normal DROP с нулём relations/clients. Это не test PASS/FAIL.

Завершённый V3 new61: **60 PASS, 1 FAIL** за 158.88 s (163.952 s outer).
Fixture lifecycle exact, captured login notify.dispatch_async=183,
forbidden=0, source/inventory PASS. Один FAIL находился в новой cursor-parent
fixture: общий else устанавливал own_org=org0 и скрывал parent1 с org1 до
проверки cursor. Runtime корректно вернул 404. Рабочий код не менялся.
ROOT подтвердил diagnosis и разрешил exact fixture-only fix с независимыми
destination200 → foreign-parent-cursor400 → hidden-parent404 goldens.

Завершённый V3 regression84: **84/84 PASS + 142 subtests PASS** за 36.68 s
(43.3218 s outer), exit0/reaped, normal DROP. На V3 источники оставались frozen
до terminal receipt. После него подготовлен V4 для одного exact node[parent],
fixtures1 и captured notify3; прежние60/84 не повторяются.

Завершённый V4 affected1: **1/1 PASS** за 14.39 s (19.0333 s outer),
exit0/reaped, frozen runner SHA
`2911585fdb6b0df7c34bc32664fa76ae01707d1015080ff5529b74107918d7d3`.
Независимые destination200 → cursor400 → hidden-parent404 подтверждены.
Normal DROP: 338 relations, 0 оставшихся клиентов, exists0, max_locks64.
Приёмка состоит из 60 retained PASS, одного corrective PASS и отдельного
regression84/142subtests; единого прогона «145 green» не было. Исходный V3 FAIL
сохраняется, не переименовывается в PASS. Это локальная целевая приёмка, не полный CI.

Private frozen proposals, source proofs, exact diffs и SHA находятся в
worker `.artifacts/contract-documents-read/`; runtime receipts принадлежат ROOT
в `.artifacts/root-contract-documents-review-20261030/`. Worker не импортировал
app/tests/runner и не выполнял SQL/pytest/codegen.

### SDK ROOT

ROOT выполнил official openapi-typescript 7.10.1 generation и freshness для
14 candidate GET. Прежние **6/6 generator controls PASS**; фактический TypeScript
compile прежнего, R1 и нового R2 consumers: **3/3 PASS**. Новый consumer проверяет
положительный wire response и шесть negative checks: tenant override, write,
обязательный path, обязательный nextCursor, body и bytes. `.d.ts` вручную не правился.

Первый ROOT wrapper ошибся двойным clearledger-prefix и не создал новый consumer;
шесть generator tests действительно завершились PASS. ROOT затем создал consumer
по правильному пути и выполнил tsc для всех трёх consumers, не повторяя tests.
Этот wrapper issue и корректирующий compile отражены в private sdk-result.json;
они не выдаются за один общий успешный запуск.

ROOT передал для поимённого включения в commit: `src/generated/partner-api.d.ts`,
`tools/partner-api-types/contract-documents-consumer.ts`, `tools/partner-api-types/tsconfig.json`.
Requirements/locks/версии/рабочие настройки/модели/DDL не менялись. Все тестовые БД
штатно DROP, app/main/lifespan и чужие пространства worker не запускал. PR78/54
сохраняют draft, feature flags OFF; следующий владелец интеграции/выпуска — ROOT.

SHA256 переданных ROOT SDK-файлов:

- `src/generated/partner-api.d.ts`: `5419e859ffd9e2e04f80bb8ac5d20fd894910510164a37a01d613dd148896e4e`
- `tools/partner-api-types/contract-documents-consumer.ts`: `9daeb839e1d163dc5fe42dfeede3b1f6ee63854e16ebde3cdb0ce9f2f2150dfe`
- `tools/partner-api-types/tsconfig.json`: `a18341db122fe1ad61f6f23da592c1cbc4b3ce3011712e8a0c866193546e1aa1`
