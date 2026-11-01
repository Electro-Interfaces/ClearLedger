# Владение native регистрацией документа

SOURCE-ONLY / NOTRUN, включая collection и импорты приложения. База: `cdb65361f3207f82283c88da8b431625a5b1804c`. Этот протокол описывает реализацию и определения проверок; выполнение PostgreSQL, регрессии, CI и выпуск ещё не подтверждены.

## Вход и порядок ожиданий

Один исходный набор B определяется scalar MVCC-чтением до ожиданий: actor, пять User FK карточки, реальные домашние компании пользователей, фактический владелец читаемой роли, указатели членства, CP/Org, все кандидаты вывода Org, текущий/default Case и их Org, visit issuer, все кандидаты замещения (включая будущие), ID и FK Approval/Acquaint, совпавшие подписки `doc.registered`. Ссылки детей разрешаются через существующий canonical User.id. Department/object записываются как указатели; новые typed consumers не вводятся.

Используются один существующий LockPlan и capability того же Session/root. Физические строки: Company S → отсортированные смешанные User S/X → Role S → CP/Org S → visit PartnerSpace S → Member S → подготовленные Subscription S → прежний Case catalog S → Kind S → Card X. Новый родитель или изменённый указатель после ожидания даёт 409 без расширения плана. Нормативные UUID/missing ошибки остаются у прежних validators. Новых запретов foreign/member нет.

Kind grant SAVE/DELETE получают Kind X перед предикатами и DML; doc scope сохраняет прежний Card X. Замещения выбирают deputy User X до первой User-блокировки и повторяют прежний admin guard после ожиданий. Inbound acquaint блокирует существующий parent Card до child DML, сохраняя root вызывающего.

## Fresh policy и собственные изменения

Checker обновляет только чистые Company/User/Member/Role/Kind/PartnerSpace/parents/grants, восстанавливает исходный selector и вызывает native user/visit/product, затем тот же `_can_doc(edit, record_break_glass_use=False)`. Pending Card/Acquaint/history не expire/refresh; точный снимок собственных изменений и историй проверяется до и после evaluator. `updated_at` исключён как server/onupdate clock, чтобы не вызвать неявный async I/O. Temporal substitution и READ вычисляются заново.

Approval X не берётся. Pending deputy assignment сохраняет native READ. Настоящий `doc_approvals.decide` безусловно добавляет DocEvent; его Card FK KEY SHARE сериализует завершение с Card X, в том числе при `approval_status=none` и параллельных pending rows. Для этого определены оба реальных порядка. Одна scalar-проверка не считается доказательством замыкания READ. Полное замыкание raw/dynamic и всех approval/archive/TP writers остаётся UNKNOWN. Проверка visit disable обозначена как physical probe; инвентарь app writers PartnerSpace этим не подтверждён.

## Native DML и завершение

Сохранён порядок counter → fresh check → number/date/token/autoflush → status/default Case → прежний поздний Case X → fresh check → supersede/events/audit/outbox → explicit final flush внутри прежнего commit IntegrityError try → CURRENT check после flush → clean seal → прежние commit/postcommit refresh. Case не предблокируется перед counter: смешанные старые root иначе могут образовать цикл. Outbox selector выполняется под `no_autoflush`, чтобы оставшиеся event/audit/outbox DML попали в final flush. Early ensure_token IntegrityError остаётся вне старого commit409 catch.

Publish имеет optional expected-parent receipt, default None сохраняет остальные вызовы. Один прежний selector сверяет ID/company и receipt того же root с заранее SHARE-held подписками до Outbox add; поздних parent locks нет. Envelope/data/return0 не изменены, сети нет.

Seal before_flush не выполняет SQL и проверяет exact Session/root/capability; запрещает новое DML после финальной проверки, удаляется на actual root end/rollback/invalidate/reuse и до G3 callback. G3 notification keyword, queue и audit helpers сохранены. При отказе владелец откатывает весь root, включая counter; проверки изучают собственное pending-состояние ДО rollback. Savepoint retry отсутствует.

Commit/cancel/refresh ambiguity остаётся UNKNOWN: запрос мог зафиксироваться без ответа. Нужна сверка отдельным GET, нельзя обещать откат или replay-success; повтор регистрации возвращает прежний 409.

## Прежние ошибки и ограничения

После native product/edit проверок сохранён порядок: already registered → draft → pending approval → attrs → future date → вывод Org → manual trim → admin → reason → busy. Manual не двигает counter. Прежний commit IntegrityError конвертируется в «номер занят»; ранний token IntegrityError этим catch не поглощается. Последующий refresh не доказывает отсутствие записи при ошибке ответа.

Три PG-модуля содержат определения actual writer orders, PIDs/pg_locks, counter/Case/token/outbox ожиданий, собственной истории до rollback, final check/seal/G3/root reuse и ambiguity. Для исполнения требуются отдельная одобренная БД, preimport isolation предкового conftest, full native schema/codecs/constraints и очистка владельцем. Здесь provisioning, обходов UUID, fake Scope, копии ACL и substitute commit нет. Имеющийся Case oracle адаптирован только с Company X на настоящий unique-index wait, сохраняя оба направления. Ни один результат старой серии не переносится на новый состав.

## Исходная программа: все 20 разделов и 11 условий OPEN

Канонический SHA256 ORIGINAL-PROGRAM.json: `84f8dd31e6e047bf6fc647f4e601c1c89783dc8ebbeb4fe324814d51a7fb2ba1`. Полный исходный объект также включён в соседний JSON без сокращений. Ни один из критериев ниже не закрыт этой SOURCE-ONLY работой.

### M00 — OPEN

P0: актуальный совместимый source/runtime baseline

Владелец: Выпуск + Core/Support. Зависимости: Нет.

Исходная приёмка: Точные версии/хеши/состав, реестр активных потребителей; старый Support не выдан за baseline

### M01 — OPEN

P0: завершить реестр поверхностей и владельцев

Владелец: API + владельцы доменов. Зависимости: M00.

Исходная приёмка: Dynamic/factory/native/WS/SSE/files/proxy разобраны, каждому маршруту назначены class/owner/decision и потребители

### M02 — OPEN

P0: characterization и измеряемые сценарии

Владелец: Домены + проверка. Зависимости: M00, уточнения M01.

Исходная приёмка: Golden outputs/ошибки и отрицательная ACL-матрица на синтетике; исходные SQL/RAM/latency budgets измерены

### M03 — OPEN

P0: общий проверенный контекст/route policy

Владелец: Identity + домены. Зависимости: M00, M02.

Исходная приёмка: Типы токенов/отзыв; ALL/SET/EMPTY/UNINITIALIZED; selector не расширяет доступ; неизвестная новая операция закрыта

### M04 — OPEN

P0: границы слоёв и владение транзакцией

Владелец: Core/Support architecture. Зависимости: M02, M03 skeleton.

Исходная приёмка: Извлечённые services не импортируют routers; старые входы вызывают те же правила без изменения поведения

### M05 — OPEN

P0: объекты, scopes, population и temporal identity

Владелец: Core objects/equipment. Зависимости: M03, M04.

Исходная приёмка: Матрица пяти уровней implemented/gap; одинаковый охват list/detail/count/export; create/upsert/rename/retire проверены отдельно

### M06 — OPEN

P0: контрагенты, договоры и идентичность

Владелец: Core references/contracts. Зависимости: M03, M04.

Исходная приёмка: Один matcher и scope service; ambiguous явно; replay/concurrency/null/связи проверены; старые подтверждённые связи сохранены

### M07 — OPEN

P0: документы и файлы

Владелец: Core documents/files. Зависимости: M03, M04.

Исходная приёмка: Карточка/версия/содержимое/тип связи разделены; один writer, domain ACL, rollback cleanup, register/approve отдельно от edit

### M08 — OPEN

P0: энергия, начисления и мониторинг

Владелец: Core energy/ops. Зависимости: M05, M06.

Исходная приёмка: Общие definitions/provenance; чистый GET closing; материализация командой; исторический срез описан честно

### M09 — OPEN

P0: протокольный профиль и product OpenAPI

Владелец: API contracts + домены. Зависимости: M01, M03, соответствующие M05–M08.

Исходная приёмка: Схемы/ошибки/scopes/examples/operationId совпадают с runtime; описательные x-поля не заменяют guard

### M10 — OPEN

P0: OAuth/OIDC и developer access

Владелец: Identity + integrations. Зависимости: M03, M09 profile.

Исходная приёмка: Code+PKCE, machine grants отдельно; docs portal/spec/API permissions разделены, отзыв действует и протестирован

### M11 — OPEN

P0: защищённый Swagger и quickstart

Владелец: API docs + Identity. Зависимости: M09, M10, sandbox.

Исходная приёмка: UI/raw spec/bundles закрыты; Authorize/Try it out работает на синтетике; нет client secret или общего admin token в браузере

### M12 — OPEN

P1: клиентские transports и typed operations

Владелец: Core/Support frontend. Зависимости: M02, M09.

Исходная приёмка: Один transport на trust boundary; generation/signal, refresh/errors/binary; wire types generated, без `as never`

### M13 — OPEN

P1: Support factories и service adapters

Владелец: Support + Core integration. Зависимости: M03, M04, M06.

Исходная приёмка: Общий ticket lifecycle с параметрами команд; SLA/subject replay/actor и parent SSO ограничения сохранены

### M14 — OPEN

P1: доставка событий и change feed

Владелец: Domain owners + integrations. Зависимости: M03, M04, применимые M13.

Исходная приёмка: Локальные outbox, единый envelope/signature; определены момент подписки, retry/replay/cursor и права перед выдачей

### M15 — OPEN

P1: ограничение нагрузки и оптимизация

Владелец: Backend/DB + домены. Зависимости: M02 и зрелые queries.

Исходная приёмка: Измерены SQL/строки/RAM/pool/cache; достигнут принятый бюджет без изменения результата/ACL; большие выгрузки/jobs ограничены

### M16 — OPEN

P1/P2: migration/schema ownership

Владелец: Persistence + выпуск. Зависимости: M00, M02.

Исходная приёмка: Fresh/restore/upgrade/repeat совпадают; Alembic audit отделён от runner; новый DDL versioned и совместим со старым кодом

### M17 — OPEN

P1: перевести собственные приложения

Владелец: Владельцы продуктов. Зависимости: M05–M13 по домену.

Исходная приёмка: Переведены UI/service consumers, contracts и workflows проходят регрессию; нет silent online→demo fallback

### M18 — OPEN

P0 к внешнему запуску: пилоты и независимая приёмка

Владелец: Партнёрский пилот + проверка. Зависимости: M09–M17 применимо.

Исходная приёмка: Три внешних сценария и общий блок из четырёх доменов реализуются по документации без чтения исходников

### M19 — OPEN

P2: deprecation и удаление дублей

Владелец: Домены + выпуск. Зависимости: M17, M18, usage evidence.

Исходная приёмка: Потребители переведены, срок совместимости окончен; старые key/path/adapter удаляются отдельным PR с откатом

### FULL-SCOPE — OPEN

Все20M и все поверхности Core/Support/Auditor классифицированы; обязательные документы/контрагенты/договоры/ЭЗС/оборудование/accounts не исчерпывают объём.

Исходное completion: unproven.

### SOURCE — OPEN

Точный актуальный source/runtime/consumer baseline; не потерять параллельные live исправления.

Исходное completion: unproven.

### DOMAIN — OPEN

Единственный владелец правила, tenant/object/org/date scope до count/limit/aggregate/export, текущие actor/grants; неизвестная операция fail-closed.

Исходное completion: unproven.

### CONTRACT — OPEN

OpenAPI/Swagger/SDK/runtime совпадают, содержат реальные auth, errors, headers, limits, null-intent, examples; binary/multipart/SSE/WS/webhook/industry profiles проверяются отдельно.

Исходное completion: unproven.

### CHARACTERIZATION — OPEN

Старые golden outputs и отрицательные матрицы двух компаний/пользователей/apps/resources, реальные SQL/bytes там где требуется; metadata count не заменяет ACL assertion.

Исходное completion: unproven.

### MIGRATION — OPEN

Fresh/restore/upgrade/repeat/old-code, checksums, locking и rollback; перед working migration свежая backup и фактическое восстановление.

Исходное completion: unproven.

### CONSUMERS — OPEN

Полный перевод согласованных UI/service consumers, без stale-context effects и silent fallback; usage evidence перед retirement.

Исходное completion: unproven.

### MEASUREMENTS — OPEN

SQL/RAM/latency/pool/cache/exports/jobs на представительном объёме и принятые бюджеты, без необоснованных pool/index changes.

Исходное completion: unproven.

### FINAL-COMPOSITION — OPEN

Единый окончательный состав исходников и соответствующие проверки; разные frozen серии не объявляются общим полным CI.

Исходное completion: unproven.

### LIVE-PILOT — OPEN

Фактическая приёмка выбранного release/ingress/SSO/callback/CORS/ordinary employee и партнёров; synthetic localhost не подменяет её.

Исходное completion: unproven.

### RELEASE — OPEN

Ревью человеком/согласованный состав/откат; merge и рабочая активация отдельны от зелёных тестов.

Исходное completion: unproven.

