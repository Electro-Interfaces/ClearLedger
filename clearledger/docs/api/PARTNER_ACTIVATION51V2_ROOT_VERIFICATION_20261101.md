# Activation51V2: PASS в границах компонента

Независимо сопоставлены SOURCE и публичный RAW на immutable
`b41ba2da0dadaf991df4bdf6e954224752182ca4`. Проверяющий ничего не запускал:
runtime0, только FS/Git/stdlib AST/hash/JSON и compile в памяти без exec.
Изменены только этот отчёт и REVIEW.json. Production не менялся.

Подтверждены **51 passed, 0 failed/error/skipped**, 22 исходные функции:
8 unit definitions/37 variants +12 DPL +2 actual native HTTP/PG.
Все51 collected ID уникальны, каждый имеет ровно setup/call/teardown passed:
153 фазы result.json в точности совпали с progress.jsonl, включая duration;
51 start. Exit0, denied=[], observerErrors=[], poolErrors=[].
52.951319891s включает bootstrap; stdout25.58s относится к pytest.
Это разные scopes, не benchmark активации. Два pytest warnings и два
SyntaxWarning в stderr сохранены; нулевые warnings не заявляются.

Состав и исполнение

Все576 raw source bytes совпали с Git b41 и source-manifest:
526 app +34 schema_migrations +16 tests; файлов сверх manifest нет.
Полный app/schema состав560, шесть основных tests/fixtures и десять
добавленных read-only DPL входов. Все десять перечислены с SHA256 в JSON.
Runner321 использует --noconftest и точный набор37+12+2; DPL читает байты/AST,
не импортирует эти входы. AST scan возможного runtime source не нашёл
import edge к ним; отсутствуют dynamic imports в selected tests/issuer fixture.
Полного runtime module log для tests нет: это source/composition proof,
а не выдуманная отдельная import telemetry.

Controller18–56 копирует/пинит Git до запуска; runner5–43 проверяет source,
driver, Python3.13.7 isolated/no_site, psycopg3.2.3/SQLAlchemy2.0.36,
свой PG/database/ordinary role до app imports. RAW PG160015 (16.15),
все elevated role flags false, role OID равен владельцу БД.
Driver-manifest независимо хеширован; повторные проверки dependency bytes
предписаны controller/runner, сами dependency files и внешний pinned helper
не открывались вне разрешённого списка. Это не аудит библиотек/helper.

Bootstrap runner208–241 использует исходные native migration runner и
app.database preflight/require/create_all под startup lock, revision4.
Независимый AST registry341 совпал с evidence; точный physical universe:
prefix3 tables341, FK790/RI3160; prefix4 tables347, FK803/RI3212.
Все таблицы ordinary и owned clearledger; PK/FK validated, RI enabled/internal,
ровно4 RI triggers/FK. Legacy extras явно сохранены (columns1, FK2→3).
Это native schema, не подставные metadata/Session/grants.

app.main и app.seed действительно ИМПОРТИРОВАНЫ; lifespan и seed entry points
не вызывались. Runner вызывает database bootstrap напрямую; seed calls в main
принадлежат не запущенному _prepare_database. HTTP идёт через реальный native
router и ASGITransport внутри процесса: listening HTTP server отсутствует.
Audit запрещает bind/process/fork/exec и чужие socket targets; RAW6 connect
только к своему PG, denied0. PG network none, Python shares owned PG namespace,
публикуемых портов нет. Нельзя называть это отсутствием любых socket connect.

Factory runner254–280 создаёт реальный async engine/sessionmaker, проверяет
БД/user/schema/isolation, выдаёт fixture и закрывает пул на живом loop.
Изолированный RSA key синтетический, settings восстановлены. World40–125
пишет настоящие User/Member/client/profile, подписывает собственные claims
каждого actor и заменяет только get_db на actual factory. Auth/verifier/B,
capability и Session не заменены положительными stand-ins.

Observer и сохранение проверок

Commit b41 меняет один тестовый файл (216+/12-), production/schema delta0
к149f3033. Whole-module inverse AST без одной target function совпал;
её signature/decorators неизменны. SHA файла совпал с fad2 Source receipt.

T230–485 теперь проверяет finite текущую grammar, а не текстовый core-prefix:
exact mapped tables/columns/node classes, четыре исходных TextClause;
оба compiled trees, запрет CTE/opaque modifiers/custom/literal/nested SQL,
DML subclasses/post-values/INSERT SELECT/multi-values/UPDATE FROM,
hints/prefixes/suffixes/dialect extensions и неожиданных operators/types.
Это ограниченный source observer, не universal SQL detector.

T412–425,462–468 требует ровно **1 Insert AuditEvent +1 Update Profile**,
exact compiled table/schema/flags, current execution params и тот же Connection.
schema=None соответствует исходному ORM при проверенном core search_path.
T269–284 берёт значения текущего execution, а не cached bind defaults;
T434–453 проверяет tenant и SHARE flags; T475–483 требует точный порядок:
CP2→Org2→Location2→Member2, весь union один раз, без лишних/пропущенных строк.
T289–303,469–485 сохраняет1 originalB, Session/root/Connection/capability,
полный уникальный plan, Installation/Profile X и отказ receipt после commit.
Нового issuer, ослабления production guard или частичной проверки union нет.

Первый PG T153–166 исполнил четыре PUT: enable/same flags/disable/re-enable,
новые CAS generations2–5, independent fresh SQL children/Contract/Intent/Grant
без изменений и точные audit payloads; старый CAS1 дал409.
DPL12 сохраняют исходные19 raw/17 writer/12 canonical guards и точный inverse
overlay; production Activation/identity/Profile/locks hashes не изменены.
Остальные17 PG definitions этим запуском не покрыты.

SQL RAW:10909 events/150 per-test shapes, сумма executions совпала;
8717 в первом CALL,2192 во втором. Inner observer слушает только activation PUT,
а Root recorder CALL включает последующий GET T473 после снятия listener.
Старый diagnostic1775 обрывался до GET на ошибочном assert. Эти числа не
before/after M15, не чистая production нагрузка и не proof ускорения.

Очистка и границы

Оба пула завершили0 checkedout/0 checkedin на живом loop; app pool errors0.
Database-after:clients0/locks0. Оба owned контейнера exited0, not running,
OOMfalse и removed=true; все25 controller operations exit0/reaped.
41 foreign safe projection entry побайтно совпали до/после: только
Id/Image/Running/StartedAt. Это не полный аудит данных чужих БД.

Root3127 initial51 остаётся NOT_ACCEPTED (49 diagnostic pass/2fail).
Оба исторических checkpoint документа побайтно равны Git9d; новое PASS
не переписывает старую ошибку missing DPL input и core-prefix oracle.

**PASS только Activation51V2 exact51.** Не full139/fullOAuth/CI/deploy,
не команда включить production flags и не runtime/code acceptance M15.
Полная исходная цель M00–M19+11 OPEN; исторические suites не суммируются.

Основные SHA256

- source-manifest: `251c0aeeaaee16f7a1622371d4802e8285a7cf0683412b7c6cc5f6ec472a7ff2`
- result: `d65e9b81f6f6a622ca4d6e1c0406e1f8f61459137685ad6f3390bd805936a9bb`
- progress: `2b6fe4aca1c0e5d196b46a41f3baeccae0587e2872406be01c535c56cfdfd8c1`
- observer test: `57d2b25225901d6c3b4206de3dd1c2e97c16fb9796e04099219ca4db57b219ce`
- controller: `006aa038fbd60da4522e65292ceafec06d1e43696541dd5974f68343bc5deb5b`

Полные input hashes, точные22 symbols/lines, controller/runner refs и ограничения
находятся в REVIEW.json; control/env/DSN/секреты не читались.
