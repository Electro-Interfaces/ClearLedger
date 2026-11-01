# Проверка уведомлений после commit

## ROOT: уведомления регистрации после commit проверены · 2026-11-01

Приняты **51 PASS /29 определений /153 фазы** на `1eac5f0f`:17 unit,25 PostgreSQL и9 native регистрации документа. Независимая SOURCE+RAW приёмка завершена. Проверены настоящие транзакции SQLAlchemy2.0.36 и полная native структура341 моделей/347 таблиц.

`register_doc` передаёт уведомление scheduler только после успешного commit корня. До callback независимая Session видит зарегистрированный документ, AuditEvent, DocEvent и transactional outbox. Другие105 вызовов аудита сохраняют immediate. Очередь хранит четыре неизменяемых значения; актор и ORM в фон не передаются.

Проверены merge/откат вложенных ORM SAVEPOINT, порядок, flush failure, cancel/close/invalidate, повторное использование и reentrance. Неучтённый Core SAVEPOINT и AUTOCOMMIT отвергаются; поздний отказ требует полного rollback. Auto/manual регистрация, повтор и коллизия409, ordinary ACL и strict read break-glass проверены настоящими обработчиками. Ошибка реального commit flush откатывает номер, документ, audit и outbox без callback.

Первый прогон сохранён NOT_ACCEPTED:51 collected/42 diagnostic PASS/9 native setup errors. Native CHECK корректно отверг URL-подписку без encrypted secret. Исправлена только fixture: настоящий encrypt_secret с синтетическим ключом, без изменения production/схемы/оракулов; затем полный51-case повтор прошёл.

PG clients/locks0/0, pool0/0 на живом loop без poolERROR, два собственных контейнера удалены штатно,41 ограниченная проекция чужих контейнеров неизменна. Уведомления перехвачены: SMTP/push и реальная доставка не проверялись. Это best effort очередь в памяти; durable/exactly-once/crash delivery не обещаны. Native вызовы используют программного актора, не HTTP/JWT. Raw transaction SQL и direct driver isolation вне поддерживаемого контракта.

Отдельно остаются права получателей Doc-уведомлений/Chat visibility, G1Case/numbering/postUPSERT admission, SQL issuer/consumer `contracts:create`, внешнийPOST/options/activation/SDK, полный Docs/OrgDELETE/CI и пилоты. Все исходные M00–M19+11 сохранены; общего процента и релизного GO нет. Merge, выпуск и рабочие flags не менялись.

Точные Source, SHA-256 и ограничения приведены в парном JSON.
