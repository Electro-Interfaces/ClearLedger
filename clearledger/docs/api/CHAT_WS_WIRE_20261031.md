# CP-01: native WebSocket TCP/PG wire, source freeze 31.10.2026

## Prestate admission: source finding и контракт до DDL

Работа ведётся source-only от exact base `e325ca4495ac88c19e89a81bc2e783c391362b11`,
ROOT Run `run_19ce21b41b2c`, task `task_f9722222c537`, dispatch `ctx_67a8437d0e9d`.
Исторические F1/F2 доказательства ниже описывают прежний снимок; текущая правка
не является новым runtime receipt. Worker runtime=0; новые controls NOT_RUN.

Подтверждённая ROOT source finding: прежний prepare проверял только часть
`pg_class`, пропуская отдельную public-функцию. Первый canonical statement,
`CREATE OR REPLACE phone_to_e164`, мог заменить её, а посторонняя функция могла
остаться. При пустой схеме `clearledger` default search_path мог также направить
unqualified DDL вне public, тогда как snapshot смотрел public/service_fixture.
Подтверждение здесь только по исходнику; SQL/PoC не выполнялись.

Контракт допуска: до первого DDL проверять actual exact leased DB/OID, роль и
владельца, полный разрешённый inventory namespaces, effective public namespace
и search_path на raw и на самом DDL-engine соединении. На fixture-session
проверять ту же идентичность перед записью. `service_fixture` до DDL отсутствует.
Непредусмотренный объект отвергается; GRANT/DROP/SET/нормализации/починки нет.
Состав разрешённых extensions задаётся только явными ROOT fixture literals,
не внешним boolean и не произвольным именем роли, схемы или extension.

Catalog classes контракта: `pg_class` (все relkind, включая indexes, composite
relations, sequences, views), `pg_proc` (functions/procedures/aggregates),
`pg_type` (base/array/composite/domain/enum/range/multirange), `pg_constraint`,
`pg_operator`, `pg_opclass`, `pg_opfamily`, `pg_collation`, `pg_conversion`,
`pg_ts_config`, `pg_ts_dict`, `pg_ts_parser`, `pg_ts_template`,
`pg_statistic_ext`, `pg_default_acl`; дополнительно прямые зависимости любых
catalog addresses от public/service_fixture в `pg_depend` отвергаются по
умолчанию. Extension-members учитываются только относительно exact allowlist.
Широкое исключение internal dependencies запрещено.

Postprepare обязан сверить reviewed source `TABLES` (20 domain tables) и native
presence именно в public, две control tables именно в service_fixture, их
владельцев. Это отдельный placement oracle; hash собственного snapshot после
DDL не доказывает полный канонический catalog contract. ROOT по-прежнему
отвечает за независимый DDL compiler/seal, private lease и отсутствие concurrent
writers, внешнюю изоляцию PG/namespace/network, 3 PID supervision и cleanup.
Native wire, DDL compiler и supervisor здесь не исполнялись; Python audit не
является OS sandbox. OLD report12, production/real data и 20M+11 неизменны.

ROOT source-GO задал будущую fixture, ещё не измеренную: image
`721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`,
PostgreSQL 16.15 (`160015`), bootstrap `POSTGRES_USER=clearledger`, новая DB из
template0 с owner clearledger. Единственный extension: plpgsql 1.0, pg_catalog,
owner clearledger, nonrelocatable, без config/condition. Его direct member
inventory: язык plpgsql и pg_catalog routines plpgsql_call_handler(0 args),
plpgsql_inline_handler(1), plpgsql_validator(1), owner clearledger. Определения
системных функций остаются prerequisite доверенного ROOT image; inventory не
доказывает побайтовую каноничность их тел.

Владельцы namespaces: public = pg_database_owner;
pg_catalog/information_schema/pg_toast = clearledger; service_fixture после
нашего DDL = clearledger. Точный search_path: `"$user", public`, без backslash;
current_schema = public; current_schemas(false) = [public], с implicit schemas
= [pg_catalog, public]; temp schema OID = 0. Любая дополнительная схема, включая
пустую clearledger или чужую pg_temp_*, отвергается. Lease/OID/CID ROOT выдаст
отдельно перед своим запуском; источник не придумывает OID и не подменяет lease.

Coverage ограничен namespace-классами выше и прямыми namespace dependency
addresses. Отдельный произвольный cast/transform/event trigger/publication,
database/role grants, ACL/system catalogs/functions/objects вне public и
service_fixture, серверные настройки и concurrent mutation не образуют здесь
full-cluster admission contract. Эти состояния не допускаются по внешнему
ROOT prerequisite свежей template0 fixture и закрытой lease; они не объявлены
проверенными source checker. Неизвестный объект с namespace dependency внутри
периметра отвергается. Новые расширения и internal extension-type closure не
поддерживаются: текущий plpgsql не имеет public types и не требует исключений.

Future prestate controls (все **NOT_RUN**, отдельно от прежних 13 controls и
шести wire cases):

- P01: чистая exact fixture проходит оба pre-DDL checker; verify no extra DDL.
- P02: одна public.phone_to_e164 с sentinel definition; отказ до DDL, definition
  и весь исходный catalog неизменны. P03: отдельная чужая public function,
  overload, procedure или aggregate также отвергаются.
- P04: domain/enum/base/array/composite/range/multirange type; P05: table,
  standalone index, partitioned index/table, sequence, view, matview, foreign
  table и composite relation. Каждый объект в отдельной fresh leased fixture:
  отказ без DROP/GRANT/repair и без canonical[0].
- P06: constraint/operator/opclass/opfamily/collation/conversion, каждая text
  search class, extended statistics, schema default ACL; P07: дополнительный
  namespace dependency address вне явного class list. Отказ, объект сохранён.
- P08: лишний/неверный/missing extension, версия/схема/owner/member drift,
  public-объект, присоединённый к plpgsql; отказ, auto-install отсутствует.
- P09: уже существующая service_fixture, пустая clearledger или temp schema,
  лишняя/недостающая схема или неверный schema owner; отказ до DDL.
- P10: exact default path с effective clearledger, изменённый literal path,
  implicit/explicit namespace drift, temp namespace; отказ на actual connection.
- P11: неправильные DB name/OID/version/owner/current_user/session_user; отказ
  до DDL. Повторить отдельно для raw и фактического DDL-engine connection.
- P12: ошибочный fixture-session context отвергается перед первой ORM-записью;
  public TABLES20/presence и service_fixture control2 сверяются по reviewed
  names/kind/persistence/owner, включая missing/extra/wrong-placement варианты.
- P13: вне helper ROOT independently проверяет lease/OID/CID/image/template0,
  отсутствие writers, namespace/network rights, native SUT hashes, DDL seal,
  budgets и положительные exits/cleanup; worker не запускал этот контроль.

ROOT уточнил в msg_a7cfe1634a13: каждое фактическое raw/DDL-engine/session
соединение проверяется перед собственной первой DDL/DML; общий connection
удерживать не нужно. Session ещё пуста и не autoflush-ит до guard.

Source proof текущей правки хранится в JSON `prestate_revision`: полный
обновлённый manifest, AST/compile-in-memory, reverse AST к exact base, code diff,
immutable guards и список этих future controls. Executable hashes в таблице
ниже обновлены; прочие F1/F2 runtime-ожидания и source ranges ниже исторические.

Текущий prestate source-кандидат меняет ровно четыре существующих файла. Статус: PRESTATE_SOURCE_PENDING_ROOT_REVIEW. Worker runtime=0: выполнены чтение, Git, stdlib AST/hash и компиляция в памяти; helper, приложение, framework, controls, SQL, TCP и контейнеры не запускались.

База и origin: `7c49296663e23f6ba1b38d9a069e3295d1cbe0b0`, ветка `agent/api-chat-ws-backend-implementation-20261031`. Все 12 файлов принятого backend commit сохранены byte-exact и AST-exact; reverse diff пуст. Результаты ROOT backend150 и legacy90 относятся к прежним сериям и не доказывают wire. Все исходные design106, включая frontend24, сохранены в прежних отчётах; новые шесть не заявлены покрытием всех106. Curated15 GET=11dual+4user-only/OFF неизменён. Native WS не становится OAuth machine API.

## Историческая F2: ограничение всего poll

ROOT разрешил единственную code-коррекцию msg_e8ae52f9071d. В `until` весь poll, включая зависший await check(), окружён asyncio.timeout(seconds). Собственный timeout выдаёт прежний fixed safe failure code; посторонний TimeoutError из check не подавляется, если scope не expired. Detached tasks не создаются. C20/5, шесть case IDs и golden assertions не менялись.

F1 exact4 сохранён в `.artifacts/chat-ws-wire-20261031/freeze1` (0700, файлы0600), все четыре bytes/SHA совпали с переданным ROOT freeze. В JSON `F2_vs_F1` приведены unified diff и source-only AST reverse proof: при восстановлении только old until AST cases полностью равен F1; helper AST полностью равен F1 после восстановления единственного literal tests/chat_ws_wire_cases.py SHA. Все иные app/tests AST прежние. Runtime0, controls NOTRUN.

## Исполняемый состав

| Новый source | SHA256 |
|---|---|
| `clearledger/server/tests/chat_ws_wire_approved.py` | `d3d8d3d2c00fa1b375d055a35515366c585bc15b5da80c39d50d6f0c7e954b57` |
| `clearledger/server/tests/chat_ws_wire_cases.py` | `37a2e4549a296482d3fb0b550e63c0e3ef849684fe051a63d5375d9643c3615a` |

Полный selected manifest: 2278 файлов, SHA256 `8e0ee74c2c8e4284bfc7188b295230f755a60c8224b0e46fca28df0b74f70ad1`; AST/compile 999 Python sources, импортов при проверке 0. В JSON есть все пути/размеры/SHA, 2099 function/class AST evidence с диапазонами, exact124 app import allowlist, runtime929 source pins, полный dependency4201 manifest и15 wire-library pins. `mail_secrets.py` включён как исходник, не исключён по имени. Старые ignored proofs/history сохранены. Новые отчёты исключены из собственного manifest, их внешние SHA передаются ROOT отдельно.

## Три ROOT-owned invocation и два app-процесса

ROOT принял отдельный prepare PID1 перед receiver/publisher. Prepare завершается до запуска двух app-ролей; ROOT снаружи доказывает отсутствие его PG clients и процесса. Две app-роли используют общий закрытый network namespace собственного PG: receiver слушает только 127.0.0.1:33548, publisher/client подключается только к этому WS и PG127.0.0.1:33547. PID1 каждой роли запускает ровно один Python без fork/subprocess/дочерних workers; supervisor/CID/cgroup/netns/положительные exits принадлежат ROOT вне этих файлов. Hostpublished ports отсутствуют.

Helper требует exact `-I -S -B`, CPython3.13.7/glibc2.36, прежние77 pinned packages, чистую env, собственный SHA, source before/after и4201 dependency source digest. Четыре свежих непересекающихся root0700: пустой cwd, scratch, evidence, uploads; запись только в последние три. Любой symlink в source/site/путях запрещён. Loader компилирует исходный `.py`, не читает `.pyc`; .pth/sitecustomize/usercustomize запрещены. Метаданные окружения и точный argv в JSON `role_environment`.

Первый этап всех ролей metadata-only. Connect/bind/DNS запрещены до совпадения полного external `CHAT_WS_WIRE_SCHEMA_DDL_SHA256`. ROOT независимо импортирует metadata и компилирует/review упорядоченный поток DDL без SQL и сети, затем задаёт seal. Значение worker не выдумывал и не вычислял через запрещённые imports. Schema hash включает phone function, canonical tasks_number_seq,20таблиц, их original full constraints/FK/CreateIndex, deferred AddConstraint, native presence и точный service DDL. Prepare исполняет именно этот поток; global create_all/main/lifespan/seed/jobs отсутствуют.

Prepare допускает только заранее выделенные ROOT dedicated DB `api_chat_ws_wire_test_20261031`, положительный OID и lease UUID; до DDL проверяет пустоту public/service_fixture. Исходник не создаёт и не удаляет базу. Compact immutable prepare-handoff содержит lease/stage/DBoid/ownerOID/sessionUserOID/schema snapshot SHA/source SHA/row IDs; full catalog остаётся приватным prepare-schema.json. Обе роли сравнивают OID/owner/lease/rows/catalog hash и stored receipt. Отдельная `service_fixture.wire_lease` ограничена одним singleton, `wire_control` максимум4строками; fixed enum и seq, UUID correlations, result<=2048B. Команды не содержат JWT/SQL/python/URLs/arbitrary payload. Они не добавляют production route.

## Каноническая schema closure

Root tables: `Company`, `CompanyRole`, `User`, `UserCompany`, `ChatRoom`, `ChatParticipant`, `PartnerSpace`, `Task`, `TaskParticipant`, `TaskWatcher`, `ChatMessage`.

Фактический transitive FK closure (20): `chat_messages`, `chat_participants`, `chat_rooms`, `companies`, `company_roles`, `counterparties`, `org_departments`, `organizations`, `eco_partner_spaces`, `regions`, `service_locations`, `tasks`, `task_participants`, `task_projects`, `task_sprints`, `task_types`, `task_versions`, `task_watchers`, `users`, `user_companies`. В JSON каждой модели соответствуют AST ranges/hash и все source column/constraint expressions. `Task.number` ссылается на native Sequence `tasks_number_seq`; она включена в DDL seal. Native User computed phone columns требуют canonical `phone_to_e164`, также до CREATE TABLE. Task ORM before_insert/before_update сохранены; Task rows в этой wire fixture не вставляются. Native presence создаётся exact текущим DDL, принадлежит production manager; только service_fixture является тестовой схемой. Journal0001–0003 и будущая schema ownership не меняются.

## Реальные точки приложения

- `clearledger/server/tests/chat_ws_wire_cases.py:163–198` — полная metadata-only компиляция и comparison внешнего seal до первой сети/SQL.
- `clearledger/server/tests/chat_ws_wire_cases.py:328–436` — минимальный FastAPI с actual chat_router под /api, actual uvicorn.Server.serve на заранее ограниченном listener; lifespan=off.
- `clearledger/server/tests/chat_ws_wire_cases.py:534–644` — реальные TCP-client сценарии, actual manager broadcast/PG, committed mutations и SQL oracles.
- `clearledger/server/app/routers/chat_router.py:3230–3268` — неизменный native endpoint, actual JWT decode/current manager/guarded sends и safe close.
- `clearledger/server/app/services/chat_ws.py:367–379` — actual PG handler, own-origin ignore, guarded local send. Дополнительный observer установлен на той же actual asyncpg connection; production callback не заменяется.
- `clearledger/server/tests/chat_ws_wire_approved.py:253–459` — отдельные fd/inode/peer/listener capabilities, fixed PG/WS ports; нет широкого bind/send.

Сохраняются native User/token_for/current verifier/session policy, native room ACL, manager/check cadence20/body5/cleanup5/send5/drain5, presence и PG listener. Только три async_session_factory привязаны к реальному синтетическому engine(pool2,overflow0), исходная фабрика/engine освобождаются. Public scope.install_orm_scope и api_access_logging.install_oauth_access_filters вызываются без app.main. SMTP/mail/notify/webpush external senders source-reuse capture установлены до router import, это исключение явно не доказывает SMTP wire. Авторизация, ASGI close, транспорт, manager и listener не заменены успешными mocks.

## Шесть нормативных wire cases, все PROSPECTIVE_NOT_RUN

| ID | Действие и независимый oracle |
|---|---|
| `CP01-WIRE-01-NORMAL-PEER-CLEANUP` | Actual native upgrade and ordinary peer close preserves cleanup; SELECT count(*) FROM chat_ws_presence WHERE user_id=:user_a => 1 before close, then 0; SELECT last_seen_at IS NOT NULL FROM users WHERE id=:user_a => true |
| `CP01-WIRE-02-SIGNED-IDLE-EXPIRY` | Signed finite native expiry closes an idle real peer; presence(user_a)=0 after terminal close |
| `CP01-WIRE-03-CURRENT-TV-REVOKE` | Committed current tv revoke is observed at native cadence, no protected frame after terminal close; committed token_version=1; presence(user_a)=0 |
| `CP01-WIRE-04-ROOM-ACL-DROP` | Actual room ACL revoke drops guarded delivery and unsubscribes room while tenant remains live; committed count(chat_participants room_a,user_a)=0 |
| `CP01-WIRE-05-CROSSWORKER-PG-OWN-ORIGIN` | Distinct ROOT-owned processes, actual publisher PG notify to receiver TCP, own PG origin ignored; receiver listener SELECT pg_listening_channels() includes clearledger_chat_ws |
| `CP01-WIRE-06-STOP-DRAIN` | Bounded actual stop/drain and no remaining own native resources; SELECT count(*) FROM chat_ws_presence =>0; SELECT count(*) FROM pg_stat_activity WHERE datid=:oid AND application_name=:receiver =>0; service_fixture.wire_control exactly4 done rows; wire_lease exactly1 row; schema catalog hash remains prepare hash |

В JSON каждый ID имеет конкретные шаги, literal golden frames/close codes/SQL и предел доказательства. Wire01 делает настоящий upgrade/connected/pong/normal1000 и проверяет presence1→0/last_seen. Wire02 использует свежий actual signed expires_at=now+8s и idle1008 session_expired. Wire03 коммитит tv+1, ждёт native C20 close1008 session_revoked, затем проверяет отсутствие protected frame после терминального close; мгновенный revoke не заявляется. Wire04 сначала доказывает разрешённую room delivery, удаляет actual participant, проверяет drop и реальное watchdog unsubscribe, denied для same room/foreign company и живой pong. Wire05 отправляет cross marker из manager без local sockets через real PG на TCP другой роли; own publish даёт ровно один кадр, при этом тот же actual receiver listener наблюдает own PG event и завершение production delivery task. Wire06 вызывает actual stop/drain, close1001 server_shutdown, освобождение ASGI/native ресурсов и независимый receiver PG clients0.

Presence кадры принимаются только как известный background type со строго ограниченными полями; произвольные лишние кадры не игнорируются. Нет full packet trace/JWT query logging. Свежие signed tokens живут только в памяти клиента/настоящего handshake. Receipt содержит только fixed enum facts/корреляции. Logger privacy R3/12family не меняется; helper не выводит repr/tracebacks, включая URI из исключений.

## Ресурсные и временные границы

- Исходные C20/body5/cleanup5/send5/drain5 не меняются. TTL8s выбран только для synthetic issued token; никакой business TTL/sessionflag не добавлен.
- Prepare cooperative60s, app role270s, receiver loop240s, общий SIGALRM300s. Open/start15s, frame/close5s, revoke35s, room-drop30s, own PG10s, raw PG close5s. ROOT снаружи выбирает hard wall и cleanup grace; начальные кандидаты90/360s не измерены и не являются SLA.
- Четыре последовательных TCP подключения, одновременно по case source одно; listener accept cap4/backlog8, max peer64frames, max frame64KiB/client payload2KiB, queue8, PG connect cap32/role.
- Domain fixture10строк:2companies/2users/2memberships/2rooms/2participants. Presence peak1→0; service1lease+4control. Initial source estimate1–16MiB DB/catalog и1–32MiB WAL, не measured upper bound. Final source checkpoints отвергают приростDB>64MiB или own-cluster WALdelta>128MiB. ROOT измерит настоящий рост/LSN/RSS и отдельно подтвердит закрытую собственную PG среду.
- Каждая capture<=1MiB, private root checkpoint<=128MiB/4096entries, compact handoff20k/result2KiB/capture512. Это source bounds/checkpoints, не kernel disk quota. Root memory2GiB/PIDs64 лишь исходный внешний envelope для review.

13 исходных metadata predicate controls выделены отдельно, также PROSPECTIVE_NOT_RUN; их нельзя складывать с6wire/150backend/90legacy/106design. Python audit guards не являются native syscall sandbox; ROOT отдельно доказывает OS restrictions, inherited-FD отсутствие, положительные PID/cgroup exits и cleanup. Нормальный результат требует receipts обоих app PID1, ровно6unique case IDs, source/77deps/catalog intact, own PG clients/locks/listeners/presence0 и независимые outside absence facts. Неуспех/таймаут/незавершённый task никогда не становятся green. Helper не удаляет чужие файлы, не посылает kill и не drop-ает DB.

## Следующий ROOT gate

Нужны independent metadata-only full DDL seal, отдельный ROOT-owned outside supervisor/3invocation role plan и prepare receipt. До этого никакого actual запуска, commit/push/worker_done. После source review ROOT сможет запросить corrections и выполнить собственные real TCP/PG измерения. Все runtime facts будут добавлены в эти два новых отчёта только из ROOT receipt. Frontend24 refresh/reconnect/session lifecycle остаются следующей отдельной фазой; full106/20M+11/fullCI/deploy сейчас не доказаны.
