# Единое представление UUID из БД

## ROOT: UUID исправлен; приняты38 и162 компонентных сценария · 2026-11-01 03:03 UTC

Общее исправление UUID результатов БД включено29baa0c6:28 Core PK/FK,
26 partner,25 dormant profile полей и Docs token_id. Exact-key ядро, драйвер,
права, планы блокировок и bind/literal обработчики сохранены. Прежние проверки
SQL-типа в dependency preflight контрагента и фильтрах API адаптированы к
известному wrapper без изменения String/Uuid/PGUUID/error semantics.

**Независимая SOURCE+RAW приёмка завершена для двух отдельных профилей:**

- **38 PASS:**21 исходный сценарий1С без изменения assertion/фикстуры,
  14 новых unit и3 PG проверки UUID.20 определений,114 успешных фаз.
- **162 PASS:**все42 исходных PG определения native договоров,9 router входов
  и direct use case.486 успешных фаз; реальные advisory/row waits, откат/отмена,
  retained state, responsible/creator FK, Org selector и финальные проверки.

Оба профиля используют новый фиксированный app Source29baa0c6 и реальную native
схему341→347 таблиц/341 модель,803 validated FK/3212 enabled RI triggers;
все80 адаптированных UUID колонок физически uuid. Это отдельный Source,
не repin прежней535-файловой матрицы. Нативные claims программные: полный
HTTP/JWT транспорт, auth/identity/Store этим не принимаются.

Прежние18 ошибок из21 сценария1С сохранены. В первом прогоне162 найден P2
оснастки: dispose пула на уже закрытом loop. V2 повторил те же162 сценария,
закрыл idle соединение на живом test-session loop и проверил pool0/0 безERROR;
независимое ревью закрыло R1-HARNESS-01. Временные контейнеры удалены,
PG connections/locks0/0,41 чужая safe projection совпала. Полный TCB не аттестован.

Docs logout SOURCE exact6 интегрирован c9f8812c после независимого recheck;
его7 source/17 PG определений ещё NOTRUN на совместном составе. Source8
контрагентов/организаций и MemberScope готовятся отдельно; начат первый
bounded implementation plan внешнего Contract CREATE. Все20 M00–M19 и11
требований сохранены. Старые47/54 вариантов схемы и семь исторических0–2
сохраняют собственный статус. Общего процента, общего CI и релизного GO нет;
merge, рабочие миграции, flags и выпуск не выполнялись.

Статус: SOURCE написан ROOT, независимое ревью и runtime-проверки ещё не выполнены.

Реальная серия1С на полной native PostgreSQL выявила18 ошибок из21 сценария.
Отдельное ORM INSERT/commit → новая сессия/db.get подтвердило, что asyncpg
возвращает собственный подкласс UUID. Exact-key ядро и guard persisted identity
его отвергали. Эта диагностика не считается успешной приёмкой1С.

Новый app/db_types.py добавляет CanonicalUUID, адаптер результата SQLAlchemy
с прежним PostgreSQL UUID impl. Только точные stdlib UUID и фактический
asyncpg.pgproto.pgproto.UUID допускаются как результаты БД. Последний
преобразуется по16 bytes до помещения значения в identity map. Неизвестные
подклассы, строки, bool, bytes и duck objects не превращаются в доверенный UUID.
Nullable None и as_uuid=False сохраняют прежнее поведение. Ядро typed keys,
его encoder/namespace/hash, ACL, dirty admission, планы блокировок и драйвер
не меняются; переданный напрямую raw driver UUID по-прежнему отвергается ключом.
Bind/literal обработчики не переопределяются. python_type делегирует impl,
cache_ok и явное состояние as_uuid отделяют cache keys True/False.

В models.py изменены только28 PK/FK/creation UUID деклараций выбранных классов:
Company, User, UserCompany, CompanyRole, App, CompanyApp, OneCConnection,
Counterparty, Organization, Contract, PartnerSpace. Полный перечень в JSON.
Прочие Core UUID поля сохраняют прежний тип. В partner identity graph и шести
моделях будущего CREATE UUID declarations используют тот же адаптер;
DocsPortalSession.token_id также согласован с графом. Это не активирует API,
выдачу профилей, receipt или flags.

TypeDecorator не проходит прежние isinstance(column.type, UUID/Uuid).
Поэтому uuid_storage_type раскрывает только точный наш класс в прежний impl:
counterparty_usage сохраняет свою проверку PG UUID, product queries свою generic
Uuid. String opaque IDs, invalid UUID→None, scope SET filtering, signed cursor400,
detail404 и predelete dependency checks не должны измениться. Произвольные
TypeDecorator не разворачиваются. Семантика tenant/usage и queries не меняется.

Новые определения:8 unit /14 параметризованных случаев и3 PG сценария.
Они проверяют actual driver object через SQLAlchemy dialect result processor,
exact kernel encoding, отказ неизвестных типов без dispatch, nullable/string mode,
DDL/bind/literal/python_type/cache, metadata families, реальные projection error
branches и counterparty usage branch. PG определения используют исходный
OneC world без переписывания: fresh-session identity/PK/FK, typed scalar/RETURNING,
refresh/NULL и actual dependency preflight. Дополнительно обязателен повтор всех
исходных21 OneC case без ослабления assertion/фикстур. Все они пока NOTRUN
на новом составе; ordinary pytest/conftest не запускались.

Физический тип остаётся PostgreSQL UUID, но одинаковый SQL DDL ещё нужно
подтвердить на новом Source. Старый model-declaration recorder отказывает
ExternalType: это известная граница отдельного тестового профиля. Его не правили,
не подменяли old535/historical675 и не переносили старые47/54 PASS на новый состав.
Требуется отдельная ROOT-композиция со своими Source/metadata/physical pins.

Raw text/direct driver outputs не получают этот mapped result processor.
Новые raw→typed-key пути остаются отдельным обязательством. Не объявляются
пройденными всеR1/auth/usersRole/invite/Store/identity/Docs или весь API.
Все20 M00–M19 и11 исходных требований сохранены, общего процента и готовности
к выпуску нет. Рабочие миграции, merge, deploy и flags не выполнялись.

Точные SHA и защищённые файлы находятся в парном JSON. Прежний OneC FAIL:
3fb2bc3b8608f319db205aa793d337a4fa2bb6c1cb81ab2c780436f77105eddd.
Actual ORM diagnostic:5ea164aa3119922c8dc8ffc2ec9af2d4dc02d2d83ebb66d04d2ded863fa6bef7.
