# UUID пользователей документа

Native create_doc использует старые author/responsible/signatory/registered_by/
archive_accepted_by из scalar replay snapshot при построении строгих UserKey.
Для этих пяти фактически читаемых FK применён существующий CanonicalUUID
на границе результатов ORM. DocCard.id/company_id/kind_id не меняются.

Изменены только имена type factory: физический UUID, nullable, FK/default/index,
bind/literal и строгий key kernel сохранены. Локальные casts в handler/плане
не добавлены. Теперь34 Core и86 адаптированных UUID колонок суммарно.

Source-review модели и новый actual native PG набор ещё обязательны. Прежние
232/96 и95 CREATE-profile не считаются приёмкой нового Doc source.
Полные Docs/OrgDELETE и программа20+11 остаются открытыми.
