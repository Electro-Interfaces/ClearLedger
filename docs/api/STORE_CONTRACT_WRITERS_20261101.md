# Store contract writers · M06 · 01.11.2026

Source-кандидат от `d7a99c3182e39e8baea0fc638959f5ece9d033da`.
Оба raw writer заменены адаптером `store_contract_commands.py` с настоящими
`ContractCardValues/create_contract_card`, общим matcher и tenant-party validator.
UPDATE сначала получает tenant-owned Contract (иначе 404); duplicate decision
использует его сохранённые стороны и type, исключая текущий id. Полная identity
даёт 409 только внутри тех же tenant/сторон; неполная остаётся distinct.

Вход mixed caller: `store_partner_create` вызывает
`prepare_store_partner_contract(db, cid, payload.get("contract") or {})`
после раннего existing-INN return и до первого `db.add(канон)`/flush/edge write.
Здесь legacy CP→contract barriers и проверка Organization.company_id.
Tenant новой CP задаёт роутер; после её flush общий validator проверяет обе
сохранённые стороны перед shared creator. Без договора берётся только CP barrier.
Entry требует отсутствия pending writes; auth/_receipt_access MVCC reads допустимы.
Это точка будущего RefComposite B, его API сейчас не используется и не выдуман.

Сохранены User/_receipt_access/network ACL, required 400, response keys, прежние
title/number/falsy/null/date[:10] преобразования, смешанный фиксированный type/kind/
currency, raw.source/name CREATE; UPDATE сохраняет raw/manual_overrides и стороны/type.
Defaults модели: unassigned/false; locations не создаются. ORM title/raw setters
устраняют общий varchar/jsonb bind. Commit остаётся в обоих router callers;
адаптер/shared creator не владеют commit/rollback. Empty contract, early INN shape,
CP/edge/stations и защищённые router spans сохранены побайтово, CRLF сохранён.

Проверены только stdlib AST/memorycompile без exec/import и source/hash comparison.
Unit и отдельные PG cases **AUTHORed NOT RUN**: обычные pytest/conftest команды
запрещены, модульный guard не защищает от раннего conftest. Будущий PG executor
ROOT должен отдельно одобрить точную disposable test DB до любых импортов;
в тесте запрещены URL query/fragment и fallback. Матрица и pins — соседний JSON;
полные before/after pins и frozen diff передаются координатору отдельно.

Независимая Source acceptance запрашивается после локального freeze. Полный 20/M11
OPEN; B closure, runtime/PG/HTTP evidence, рабочие данные, merge/deploy/runtime GO
не заявлены. ИНН-only matcher остаётся отдельным backlog. Push/PR выполняет ROOT.
