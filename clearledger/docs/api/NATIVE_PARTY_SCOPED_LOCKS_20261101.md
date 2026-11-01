# Native-карточки и контакты: Source-пакет

Только исходники: тесты AUTHORED / NOTRUN, runtime = 0. Импорт, CI, миграция и выпуск не подтверждены. Исходные 20 разделов / 11 условий полностью сохранены OPEN в соседнем JSON.

Охват: CREATE/PATCH/DELETE контрагента, CREATE/PATCH организации, CREATE/PUT/DELETE контакта в `references_router.py`. `delete_organization`, девять договорных команд R1, OneC, identity, schema и старые тесты неизменны. Org DELETE требует отдельного решения по FK → участникам.

`native_party_locks.py`: один полный B до legacy CP, строк и первой pending-записи. Company S защищает реальные родительские компании, User S / Member S защищают native-права. RefComposite X нужен пяти командам карточек, S трём контактным. Контакт держит CP SHARE перед своей строкой UPDATE. Допуск по id+CP сохраняется и для legacy-контакта другой компании: его фактическая Company S входит в начальный B. Смена указателя даёт 409, исчезновение 404; поздних ключей нет.

После всех ожиданий перечитываются retained-ссылки, указатели и прежние native session/visit/member/get_owned правила. Dirty/new/deleted требуют отказа всего root. Helper не делает flush, discard, commit или rollback. Capability привязана к действующим root/соединению; повторный вход запрещён. Нового RoleKey нет: прежняя политика именованную роль не читает.

ИНН/КПП, verified, aliases, nullable-поля и manual_overrides остаются у прежних владельцев. CREATE verified проверяет права раньше дублей, PATCH дубли раньше verified. Организация не получает новых проверок ИНН или правил очистки.

**Прямой Python caller CP DELETE:** savepoint удалён, поскольку отравляет capability. HTTP 409 и его текст при IntegrityError сохраняются, но транзакция требует полного rollback. Продолжение и повтор в том же root запрещены; HTTP dependency `get_db` владеет откатом.

Отдельный синтетический профиль ROOT выявил ORM UUID типа `asyncpg.pgproto.pgproto.UUID` у Company/OneCConnection: strict stdlib UUID guard отклоняет его. Boundary codec остаётся предпосылкой с владельцем Core/ROOT. Kernel не ослаблен, локальные casts запрещены; этот Source-пакет проблему runtime не исправляет и не исполнялся.

Тестовые определения используют реальные команды/checker и две PG-сессии: обе очередности согласованных peers, retained-ссылки, pending-состояние, отмену и реальную FK-ошибку. Guard не защищает от раннего repository conftest: до импорта нужен отдельный состав ROOT.

Импортные, location, User/Role и прочие writers автоматически не присоединяются. Полнота физических FK, динамические потребители и отсутствие взаимных блокировок общей системы UNKNOWN. Внешний партнёрский API не открывается.
