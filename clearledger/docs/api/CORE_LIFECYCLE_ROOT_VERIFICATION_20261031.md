# Проверка запуска Ядра: текущий срез ROOT · 31.10.2026

Принято45различных сценариев из57 в40отдельных сериях. Это компонент I5 из отдельного рабочего дерева; он ещё не является единым проверенным API-кандидатом. Все20этапов модернизации и11gates открыты.

В последних отдельных сериях подтверждены полный prepare с native readiness и частной файловой пробой, completed marker repeat без изменения состояния, отсутствие реального выполнения фоновых задач и освобождение отслеживаемых соединений. Native managed gate в LIFE выключен;8job run_forever и manager.start/stop заменены10явными captures из9модулей. Реальная работа jobs/SMTP/WebSocket этим не проверялась.

Полный prepare сначала не был принят внешним verifier из-за пропущенных в подсчёте двух поздних ARTICLES.extend. Исправленная независимая source AST-деривация всех12файлов дала276статей/455связей/59категорий. Те же сохранённые11raw прошли корректирующий V2acceptor без повторного native/SQL запуска; старый отказ и все raw сохранены. Независимый reviewer подтвердил correction/provenance.

Readiness-проверка достигла positive ready, затем намеренно удалила обязательную Pulse child table и получила строгий native typed503. Внешний V2acceptor сначала отказал на штатном warning этой отрицательной ветки. После source review V3 принимает ровно одну точную строку с закреплённым rawSHA, только вместе с source AST logger/HTTP503, настоящим native classifier и SQL/childabsence/positive-ready/cleanup доказательствами. Лог не удалён и не понижен в уровне; другие warnings/errors не разрешены. Native/SQL не повторялись, V2refusal сохранён. Первый V3manifest без tail_endpoints остановлен до исполнения и сохранён; исправление добавило точные два endpoint из V2 без изменения кода.

Все6LIFE прошли раздельно, не одной серией:66rawфайлов и1589завершённых DockerCLI.

В каждой принятой серии подтверждены source15851/77dependencies до/после, два PID1kernel census, exit/reap, обычное удаление собственного executor, три конкретных independent PID absence и PGclients/locks0. Это наблюдаемые конечные проверки, не непрерывный SLA. Actual data/catalogue здесь raw с точными named witnesses, а не новый wholecatalogue verifier из ORM.

Осталось12: REC4 и OLDUP8. Synthetic restore не заменяет проверку рабочего backup/restore; фактический старый ASGI/ORM и recovery ещё впереди. Истории FAIL/прерываний сохраняются, общий CI/выпуск не заявлены.
