# Audit: уведомление после commit корня

Реализован opt-in `log_audit(..., notification_timing="after_root_commit")`.
Его использует только `register_doc` для `doc.register`. Значение по умолчанию
`immediate` сохраняет прежнюю отправку и не проверяет владение транзакцией.
Targeted AST исходной базы: 106 вызовов в 24 файлах; остальные 105 остаются immediate.

Сериализация `target` и `details`, системный актор AuditEvent и содержимое
уведомления сохранены. Очередь содержит frozen snapshot из четырёх значений:
`company_id: UUID`, `action: str`, `who: str | None`, `details: str | None`.
UUID передаётся без преобразования; ORM, актор и сессия в фоновую задачу не попадают.
Получателей, правила, каналы и текст по-прежнему определяет существующий
`notify.dispatch` в собственной сессии после commit. ACL получателей не замораживается.

Очередь принадлежит экземпляру `sync_session` и точному `SessionTransaction`.
`after_commit` отмечает успех текущего корня либо SAVEPOINT, но не отправляет.
`after_transaction_end` сливает успешный дочерний scope в родительский по номеру
постановки; откат удаляет всё его поддерево, включая ранее слитых потомков.
Внутреннее завершение flush не отправляет уведомления. Успешное завершение
физического корня сначала отсоединяет и очищает очередь, затем вызывает scheduler.
Это исключает повтор старого payload при переиспользовании сессии и reentrance.
Rollback, flush failure, close и invalidate очищают незавершённую очередь.

Opt-in поддерживает обычный single Engine-bound AsyncSession SQLAlchemy 2.0.36.
До AuditEvent add проверяются версия, настоящий тип сессии/Engine, отсутствие
mapper binds, get_bind overrides, twophase и изменённого join mode. Текущие
соединения проверяются по actual enlistment: Engine, RootTransaction, should_commit,
autoclose и identity физической транзакции. Connection-bound и неизвестное владение
закрыты. Transaction hooks Engine, способные вернуть уже открытое соединение,
не поддерживаются. Проверки повторяются до commit и при enlistment соединения.
Проверка не приобретает соединение и не делает begin/commit/rollback за вызывающего;
обычный AuditEvent add может установить логический root через autobegin.
Если физический root так и не подтверждён, отправки нет.

Обработчики событий не читают ORM, не выполняют SQL, await и сеть. Ошибка scheduler
после commit только логируется; пакет не восстанавливается и повтор не запускается.
Фоновый scheduler сохраняет прежнее владение своей сессией и обработкой ошибок.
Это best effort в памяти: durable delivery, exactly once и доставка после аварии
процесса не гарантируются. При отмене до commit владелец откатывает/закрывает root;
при неоднозначном исходе commit успех не угадывается, runtime остаётся UNKNOWN.

Новые unit и PG определения имеют статус **AUTHORED/NOTRUN**. Они включают
immediate/system/serialization parity, immutable payload, guards до add, настоящий
AsyncSession/physical commit и независимую Session для проверки видимости до
регистрации callback, SAVEPOINT/subtree/order, flush failure, close/invalidate,
cancel/reuse/reentrance, scheduler failure, внешний bind и сосуществование со
scoped-lock transaction-end listener. Native register определения используют
настоящий handler, policy, таблицы и ограничения: auto/manual, repeat/collision409,
ordinary ACL, strict superadmin read break-glass и реальный constraint failure
в commit flush после enqueue. Подменяется только `dispatch_async`, сеть не нужна.

В этой работе выполнены только stdlib AST/JSON/hash и compile в памяти на Python
3.13 без исполнения объектов проекта. Импорты приложения/SQLAlchemy/тестов,
collection, pytest, PG, SQL и сетевые проверки не запускались. Root owner должен
обеспечить **pre-import изоляцию от ancestor conftest**, native schema bootstrap,
синтетические данные и очистку отдельной БД. Локальный module guard не защищает
от conftest, загруженного раньше него. DDL, удаление nullable FK и изменение codec
для тестов не предусмотрены.

G1 numbering/Case/token/lock rewrite, full Docs, Org DELETE, полный CI, выпуск и
program GO остаются OPEN. Прежние результаты других серий не доказывают G3.
Все исходные 20 разделов и 11 сквозных условий сохранены в соседнем JSON с OPEN;
данный source-only шаг не закрывает программу. Публикация и runtime-приёмка отдельны.
