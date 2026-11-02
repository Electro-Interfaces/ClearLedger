# OPTIONS28V2 и disjoint PG75: bounded PASS

Новый OPTIONS28V2: **PASS28 cases/10 original defs/84 phases** на immutable
`4e2591c867a6e496e067187cd83fe8c24c4e2b4b`.
Объединение с принятыми11/13/23: **PASS только targeted PG75 family**,
75 unique IDs/225 успешных фаз/23 исходные функции, без gaps/duplicates.
Runtime проверяющего0; production/прежние отчёты неизменны.

Source и RAW

Все579 файлов snapshot побайтно равны Git4e/manifest и initial28:
527app+34schema+18tests, точный FS без лишних/недостающих файлов.
Driver-manifest/SQL-class capture initial28/V2 равны.
Никакой правкой app/test/provider положительный результат не создавался.
Source контроллера и embedded runner прочитаны/compiled в память без exec.

В28V2 все28 collected IDs уникальны; setup/call/teardown каждого passed.
Result и progress совпали по каждой фазе/duration;84 фазы, errors/fail/skip0,
unexpectedDenied/observerErrors/poolErrors0. Exit pytest и owned Python0.
118.429797592s включает bootstrap, stdout88.09s — pytest; это не benchmark.
Warnings: fixture deprecation и две SyntaxWarning.

Real composition: ordinary PG16.15, все elevated flags false, role OID равен
owner OID БД; Python3.13.7 isolated/no_site, SQLAlchemy2.0.36/psycopg3.2.3.
Независимый AST registry341 и точные native table universes341→347 совпали:
FK790→803, enabled/internal RI3160→3212,4RI/FK, validated keys, owner clearledger.
Legacy extras сохранены явно. Оригинальные migrations/create_all/startup lock,
без schema/Session adapter. app.main/app.seed импортированы, lifespan/seed не вызваны.
ASGI HTTP внутри процесса, без HTTP listening server.

Unchanged issuer fixture40–63,108–197 выполняет реальные Authlib
client_credentials и authorization-code/consent/PKCE с настоящими SQL grants,
User/Member/Profile/refs и собственными native claims. Factory264–290 выдаёт
actual AsyncEngine/sessionmaker, capacity8/max_overflow0/READ COMMITTED;
clean DB/user/schema/isolation проверены. Только отрицательный borrowed case
создаёт настоящий Session на external Connection, чтобы проверить отказ.
Положительных fake auth/grant/Session/SQL/provider нет.

Audit: bind остаётся запрещён

Embedded runner12–34 пинит urllib3/util/connection.py SHA256
`2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74`.
Отдельная классификация требует ВМЕСТЕ event socket.bind, (::1,0), family10,
точный co_filename и co_name=_has_ipv6. Она записывает probe и немедленно
поднимает PermissionError ДО bind. Остальные bind/process/fork/exec также
запрещены; socket connect/lookup допускает только свой127.0.0.1:5432.
RAW содержит ровно1 такой blocked probe и unexpectedDenied0;7 ownPG connects.
Публикуемых портов нет, PG network none, Python shares only owned PG namespace.
Нового разрешения на сеть/listening server не добавлено. Полного stack/case ID
для probe и независимого аудита library/helper bytes здесь нет.

Initial28 сохранён NOT_ACCEPTED: сами28 тестов/84 фаз passed, но result
FAIL_OR_SKIP, owned Python exit1 из-за unclassified socket.bind denial1.
Он не включён в union. V2 — отдельный запуск классификации всё ещё запрещённой
probe, а не исправленный RAW или ретроспективная приёмка старого запуска.

Исходные10 definitions28V2

- T347–381:6 видов closure с101 настоящей SQL selection дают503 даже при
  запросе другого domain; partial200 нет, business state прежний.
- T384–411: literal UTF8 paging, actual новый Authlib token, resource/page-size,
  TTL+301 и committed generation делают старый cursor400; fresh restart работает.
- T501–538:5 fault cases после original bind: actual cancellation, deadline,
  load error, root rollback, nested root. CancelledError либо503, без business/stamp
  изменений, actual Session cleanup. Нет положительных замещений verifier.
- T543–551:5 query422 и DELETE405/Allow GET. T555–583: deadline обрывает original
  preflight/quota phase до t0; здесь quota policy disabled, не доказан SQL quota wait.
- T586–613: borrowed actual Connection отвергнут503 до t0, чужой original root жив.
  T616–637: close failure после rollback не становится200; затем real cleanup.
- T641–657: unused foreign RAW ALL/EMPTY не добавляет veto к original canonical policy.
  T660–675: actual metadata17/dual OAuth/required nullable choices,0 Session SQL;
  это один metadata test, не full OAS/SDK acceptance.
- T679–702:4 actual commits меняют ownOrg/CP scope/install locations/Member scope;
  old cursor400, fresh200 с новой selectionVersion.

SQL:10795 CALL attempts/1078 per-test shapes; сумма совпала, parameters не записаны. Включены test mutations, Authlib и fresh readers;
это не чистая production нагрузка и не счётчик committed DML.

Полнота75 и current source

Own stdlib AST expansion всех23 original definitions/parametrize (без pytest
collection/calls) построил точный набор75 expected node IDs. Он равен RAW union
11+13+23+28V2; пересечений, missing/extra IDs нет. Для каждого ID ровно три
успешных фазы. Root summary сверена по raw result/execution hashes и фазам,
одних сумм75/225 для вывода не использовано. Полный inventory/lines — JSON.

На pinned current `6f3f2f875c9c955e233212dbabe7a84ccf7acd83` app527/schema34,
PG test/issuer fixtures/profile-manifest bytes прежние. Во всех579 входах ровно
один mismatch: принятый repaired DPL oracle. Root delta4e→6f — два test oracles,
две исторические Activation51V2 docs и3 SDK-файла; SDK здесь не принят.

Принятый offline109 (95unit+14DPL, Root2dbc) переиспользован только через
immutable предыдущий отчёт; repaired test bytes current6f совпали. Прежние
REVIEW.md SHA256 05358928… и REVIEW.json 5af05702… сохранены.
Текущий OPTIONS target95+75=170, с14DPL=184. Старое165 — история90+75;
184 не означает один joint CI запуск.

Cleanup и границы

Actual factory pool0/2→0/0 и app pool0/0 на живом loop, pool errors0;
DB clients0/locks0. Оба owned контейнера exited0/OOMfalse/removed,
все25 controller operations exit0/reaped.41 foreign safe projection entries
Id/Image/Running/StartedAt побайтно равны; это не аудит данных чужих БД.

PASS ограничен OPTIONS family component и указанной source parity.
WholeAPI/jointCI/SDK/OAS/pilot/deploy/production flags не утверждены.
Initial28 и старые offline103 failures не переписаны. Полная M00–M19+11 OPEN.
Control/env/DSN/privateRAW не читались; новый runtime не запускался.
