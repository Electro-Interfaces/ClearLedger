# Root: последовательность договорного API

Source TARGET `66f43993` интегрирован как `fb9db159`. Принято направление
выбранного цикла и разделение полномочий; новые scopes, DDL и 17 предложенных
операций этим не реализованы и не включены. Два существующих метода и четыре
native предпосылки не считаются новыми endpoints.

Первый code chunk — **P1a reader gate**, отдельное подмножество P1:
общий `ops_expectations` различает company/location и unsupported/site.
Неизвестный тип не разворачивается по всем ContractLocation даже при
наличии location_id. План явно возвращает blocked/pending allocation,
не меняет начисления неподдержанного условия и сохраняет валидные расчёты.
Legacy None/empty → location сохраняется. Schema/Scope/новых writers нет;
прежняя валидация ops_terms по-прежнему не разрешает site запись.

Следующие части P1 требуют отдельного точного schema/authority решения:
Site UUID и ObjectId различны; approved Site/org/user context; immutable
receipt и явная birth policy, атомарно выдающая только точный новорождённый
ресурс в пределах заранее одобренного контекста. Receipt/link сами не
выдают прав, replay не восстанавливает отозванный ресурс. Общий строгий
Site predicate обязателен и у native DocCard/file ACL, не только в query.
До совместимых readers, миграции и проверки всех binaries site writes OFF.

Для дальнейшего method design Root уточняет две вещи. Составные typed
договоры следует публиковать как новую версию ресурса contracts/sites/documents,
а не делать публичный дубль бизнес-сущности под именем contract-profiles.
Предпочтение для P2 — `/api/v2/contracts`, `/api/v2/sites`,
`/api/v2/documents`, с уникальными version-aware operationId и общей
авторизацией. V1 узкая команда, DTO, hash-v1 и0004 остаются прежними.
Это выбор направления версии, не утверждённый полный набор V2 paths/scopes.
Add-only привязка объекта — POST collection с Idempotency-Key и ObjectId
в JSON; PUT collection не должен притворяться заменой всей коллекции.
Точные пути/оболочки и преусловия фиксируются до соответствующего кода.

Decimal strings сохраняют precision/scale; PATCH различает отсутствие/null/значение.
Юридический тип и validity задаются явно, legacy null не означает бессрочность.
Link Site→Location сам не меняет суммы/сроки: coverage изменяется отдельной
командой с effectiveDate/revision/audit и сохранением истории. Фиктивных
ServiceLocation и автоматической юридической классификации нет.

Ни один из этих пунктов не расширяет текущую волну на расчёт/закрытие/оплаты
или все исторические API. Неизменные TARGET сохраняются как исходное предложение.
