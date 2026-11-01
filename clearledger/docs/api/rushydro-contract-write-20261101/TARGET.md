# РусГидро: договорная запись MVP

**PROPOSED до Root review; Source-only, runtime NOTRUN.** Контракт — [TARGET.json](TARGET.json): operationColumns описывает строки operations; общие правила обязательны. 2 existing + 17 proposed, 4 native dependencies; P1 отдельно, writers OFF.

Source `08b88afcaf0669a3207509543fbb83797ddaae64`, tree `58e0d03e28eb409c358e9fcc6937f544e9ffd386`. Inputs/paths/SHA256 и file:symbol:line — в JSON; READ25 принят ROOT, не повторялся.

Выбран полный Lease/PowerSupply-цикл, включая Site до станции. Контрагент — существующая независимо разрешённая ссылка. Нет нового общего create/edit контрагента: отсутствие/неоднозначность требует отдельной native-операции через matcher с правом на общую карточку. Локальная ссылка не изменяет её.

| Пакет | Результат |
|---|---|
| P1 | Native authority, approved newborn SET/actions, receipts; shared native Site/file ACL; migration |
| P2 | Typed options/create/get/update карточки; отдельные Site/contract/location links |
| P3 | create/version условий; отдельная changeContractTermCoverage с effectiveDate/revision |
| P4 | DocCard draft → state → upload → content → explicit link → register |
| P5 | После реальной приёмки: routes/schema/SDK/recipes |

В JSON: ownerFiles/deps/приёмка и 10 synthetic goldens. Повторных matcher/ops_terms/DocCard нет. Финансы/closing/payment/network-state исключены.

Существующие POST /api/v1/contracts и GET /api/v1/contracts/create-options сохраняются. Это narrow card + начальный охват locations, без Site, полного юридического профиля, условий и документов. Старые DTO/profile/hash-v1/receipt не расширяются произвольными ORM-полями. Typed profile использует общие owners/locks, но отдельные явные полномочия и новые receipts: существующий DDL ограничивает operation/hash version.

Финансовый wire: decimal string → Decimal → Numeric по precision/scale Source, без float; legacy _as_dict не эталон. PATCH: отсутствие сохраняет, null очищает только nullable, значение заменяет. Юридический профиль явный; validity различает unknown/openEnded/until, legacy null не означает бессрочность. Изменения требуют If-Match и согласованного expectedVersion; replay повторно проверяет полномочия.

Site UUID и ServiceLocation ObjectId/String40 — разные сущности. Land pointer принадлежит Lease, PowerSupply использует отдельный ContractLink. Site-only не становится company scope. Нужны Site SET, native user-site assignment и org-context; после связывания станции дополнительно ObjectId ceiling. Связь и receipt не дают прав. Approved birth policy при первом create атомарно добавляет только newborn в SET с allowed actions/аудитом; без policy403. Replay не восстанавливает отозванный item; receipt не grant.

ROOT подтвердил PROPOSED site terms. Все consumers различают company/location/site/unsupported; site означает pending allocation, не нулевое обязательство или завершённый расчёт. Reader-first: запись выключена до обновления всех binaries и миграции; старый fallback недопустим при site rows. Link Site→Location не меняет условий. Отдельная coverage-команда копирует финансовые значения в новую location-version с effectiveDate, закрывает старую по предыдущий день, сохраняет историю/аудит. Фиктивная станция не создаётся.

Минимальное хранение: typed Site authority/context, operation receipts, Site-контекст OpsContractTerm/DocCard и validity kind. Точный DDL — code-task. Семантический ETag под общими locks не требует нового revision-счётчика. Closed-period guard **новый**: текущий ops_terms проверяет окна, но не закрытые месяцы. Terms и native close/reopen должны разделять барьер до period/term locks, без расширения правил расчёта.

Narrow download обоснован Source query.conditions: baseline object-limited documents predicate исключает null object_id. Для Site нужен query AND общий строгий native DocCard/file Site predicate, без allow_null_object; независимый DocGrant/native ACL и files.content сохраняются. Baseline неизменен; user-only, documents:read AND documents.files:download. Это Source-вывод, не выполненный HTTP404. Draft, upload, relation и register — разные транзакции. Native counter/audit/outbox/check/seal сохраняются; consumer без commit. Глобальный native source_ref без собственного совпадающего receipt даёт409, не принятие чужого draft.

Lost commit ACK сверяется тем же ключом со свежей авторизацией; файл сохраняется до выяснения результата. Нет обещания atomicity всего multiHTTP-цикла. Ссылка не даёт чужих прав.

Статически: parse/размеры/уникальность/ссылки/покрытие/Git pins. SQL/OAuth/файлы/тесты/build NOTRUN. Будущая приёмка — реальная изолированная БД/байты/literal SQL oracle.
