# service_contracts: устранение повторного source, 01.11.2026

SOURCE ONLY. Runtime, SQL, HTTP, тесты и сборки NOTRUN. Исходные 20M/11 OPEN. Первый freeze 4851a7ab отклонён по R1 guard; повторный SOURCE-review ожидается.

Старые probes contract_id сохранены. Новый узкий helper вызывается только при двух источниках и убирает view, если другая service_contracts физическая (r/p), pg_depend подтверждает её OID, а deparse точно совпадает с полной прямой проекцией каталожных колонок в прежнем порядке. Сохраняются id и contract_id. Проверяются видимость basename в search_path и квалификация схемы; допускаются только две точные формы колонок, с префиксом единственной таблицы и без него. Нормализуются пробелы, имена колонок ограничены простым ASCII. Эталон строится из каталога кандидата; сохранённое ROOT-наблюдение не служит expected.

RLS/FORCE RLS, любые reloptions, дополнительные relation dependencies, фильтр, join, distinct, aggregation, limit, CTE, ONLY, неполная/вычисляемая проекция и непонятные имена сохраняют оба source. Helper не разбирает произвольный SQL. Две физические таблицы сохраняются, включая одинаковые UUID. Схема payload и число строк внутри физического источника не меняются.

Написан один целевой unittest-файл по конвенции Core: отдельная локальная contract_usage_alias_test и NullPool. Случаи: прямой и обратный alias, три search_path, обе независимые таблицы, старый public без колонки, filtered/multibase/complex/unknown, security/options, company scope, NULL и пустое использование. Контрольные случаи написаны, но не выполнены; точные pins и ожидания в JSON. conftest прочитан; общий bootstrap не запускался.

R1: URL разбирается один раз; engine получает разобранный URL только с drivername postgresql+asyncpg, пустым query и точными local host/database. Unknown/malformed отклоняются до engine. Написаны 3 guard-теста: допустимые URL, query database/host overrides, wrongdriver/host/database/malformed. Они NOTRUN; fallback отсутствует.

Статически: Python AST всех прежних узлов модуля, кроме изменённого _sources, совпадает с базой 675654298f9a7cde30f3ab8097935478bb534088. Router побайтно прежний: tenant/ACL/deleteguard predicates не редактировались. Оба Python-файла скомпилированы только в памяти без exec/import. Это не подтверждает PG-format, фактические ACL, HTTP, удаление или полный CI.

Меняются ровно service contract_usage.py, один новый targeted test и эта пара новых отчётов. Старые PLAN/PR30/PR31 и отчёты сохранены. Далее: независимый review frozen commit/diff и отдельное решение ROOT о runtime. Публикация и выпуск здесь не выполнялись.
