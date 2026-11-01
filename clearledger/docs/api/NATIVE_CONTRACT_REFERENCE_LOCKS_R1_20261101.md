# Native договоры: SOURCE-кандидат R1

Новый вариант исправляет три замечания независимого SOURCE-ревью. Он ещё не принят: все новые unit/PG-тесты AUTHORED/NOTRUN, imports/collection/runtime0. CI, merge и выпуск не разрешены.

Охват: девять прежних roots договоров и трёхпозиционный `create_native_contract(db, body, current_user)`. Native member/superadmin/visit/object/org policy сохранена; именованная роль не читается, RoleKey не добавлен. Commit/rollback остаются у caller.

Полный план до блокировок включает Company S, actor Member S, RefComposite S, точные непустые TypeCatalog S и actual old/proposed responsible/creator User S с их существующими домашними Company S. Чужой User не получает новую Member/Role policy. Отсутствующий валидный UUID получает логический User S без вымышленной компании и нового 404. Ошибочный UUID discovery пропускает; прежний _req_val выдаёт ошибку в прежней очереди.

Порядок: B → CP → contract → Company → Users по числовому UUID → actor Member → стороны/readonly locations → Contract. Смена User/home или Contract pointers требует отмены всей root, без late keys. Это защищает конкретную условную SOURCE-цепочку remove_user User UPDATE → FK SET NULL Contract против PATCH Contract → responsible User FK. Runtime deadlock не воспроизведён; новая регрессия или уязвимость не заявляются.

После последнего child FOR UPDATE повторяются actual claims/visit и исходный get_owned перед удалением связи. Входной org-selector сохраняется до preflight и восстанавливается перед свежей policy: текущий own_org применяется прежним helper, легальный selector сохраняется при None/admin/superadmin.

Replay/duplicate остаются перед active-type и req UUID при CREATE; PATCH сохраняет req-before-type. Hash, CardValues, null/empty/false/zero, inactive replay, overrides и ответы сохранены по SOURCE. Для точки SHARE предшествует Contract UPDATE; ID остаётся opaque, LocationSet не вызывается.

Отдельная зависимость OneC: Company S + RefComposite X до log flush и Org/CP DML устраняет прежний Org→CP inverse в совместном составе. Собственная ветка OneC не меняет; приёмка ждёт нового совместного freeze/review. All authority/catalog/import/soft-reference writers остаются UNKNOWN; все20 разделов/11 условий OPEN.

Проверки только AST, memory compile и hashes. 3208 защищённых файлов и 411 прежних Python-файлов тестов сохранены; native16 методов/54 Assert AST не означают исполненные сценарии. Conftest импортирует приложение раньше guards и содержит DROP схем: ROOT обязан проверить отдельную preimport-композицию до импорта/запуска. Точные pins и inverse-матрица рядом в JSON.
