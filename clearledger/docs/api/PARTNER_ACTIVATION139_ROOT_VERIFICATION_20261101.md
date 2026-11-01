# ORIGINAL Activation139: bounded PASS

На immutable `823d336c99a5986cb8ebe06ccb5a6943fe885f02` подтверждена полная
исходная семья: **139 unique cases /27 definitions /417 passed phases**.
Это **37 unit (8defs) +102 actual native PG (19defs)**, без DPL.
A55/13defs/165phases, B41/10/123, C43/4/129 проверены отдельно после frozen уведомлений.
Runtime проверяющего0; production/старые отчёты неизменны.

Полнота и source pins

Own stdlib AST/literal parameter expansion всех27 original definitions построил
точные139 expected node IDs. Они равны RAW union A/B/C; пересечения ID/defs,
missing/extra/duplicates отсутствуют. Каждый ID имеет ровно setup/call/teardown
passed; result/progress совпали по фазам/duration. Root summary сверена по RAW hashes, не по суммам. Inventory — JSON.

В каждом мире все577 snapshot bytes совпали с Git823/manifest и точным FS:
527app+34schema+16tests. Три снимка побайтно одинаковы.
Test-only8e1 интегрирован823 без production/schema edits. Проверены4 replacements9+/9-, whole PG inverse к b41 и остальные47/51top nodes.
Protected compiled observer T230–485 raw/AST неизменён. 
Четыре исправления не ослабляют проверки: ORM basenames из mappings вместо
ложного lexical core-prefix в двух местах; await list comprehensions вместо
невозможного tuple(async-generator) для5/13 настоящих snapshot queries.
Predicates/query order/normalization/whole snapshots/cardinality/order сохранены.

Actual factories, identity и schema

Runner254–280 создаёт один настоящий AsyncEngine pool_size8/max_overflow0,
READ COMMITTED и sessionmaker(expire_on_commit=False). Alias fixture
partner_contract_issuer_factory282–285 зависит от activation_admin_factory
и выдаёт ТОТ ЖЕ sessionmaker; factory() создаёт независимые actual Sessions.
Blocker/request/observer используют
реальный PG; pg_blocking_pids+ungranted pg_locks доказывают wait. Ранний empty pid-box не доказывает distinct PID.

Native claims подписаны для собственных SQL User/Member; get_db меняет лишь factory.
Issuer проходит original Authlib client_credentials/authorization-code/consent/PKCE.
Actual public native auth/admin/verifier/B не возвращают подставной успех.

Во всех3 мирах ordinary PG16.15: owner OID=role OID, elevated flags false,
SQLAlchemy2.0.36/psycopg3.2.3/Python3.13.7. Source registry341
и exact native universes341→347 совпали: FK790→803, enabled/internal RI3160→3212,
4RI/FK, validated keys/ordinary owner. Original migrations/create_all/startup lock;
не schema-only adapter. app.main/app.seed импортированы, lifespan/seed entry calls нет.
ASGI in-process, HTTP listening server нет. Audit запрещает bind/process/fork/exec
и foreign network; разрешён только ownPG127.0.0.1:5432. Denied/errors/skips0.

A55

Все37 strict DTO/forgery/type/purpose/source варианты и18PG прошли: same flags,
newCAS/disable, stale/missing/overflow/revoked, nonadmin/badBearer/closedgate,
11 principal/legal-selection условий. Protected case сохраняет одно originalB,
Session/root/Connection/capability/уникальный typed plan, Installation/Profile X,
ровно Profile UPDATE+Audit INSERT, полный orderedCP2/Org2/Location2→Member2,
и отказ capability после завершения root. Children/business DML сервис не добавляет.

B41: различать отрицательные мутации

- 20 actual last-wait cases:5phase×4change. Listener после доказанного wait и до
  освобождения blocker проверяет request PID/one-shot. Token/admin/Member-pointer
  UPDATE — внутри actual REQUEST root, gate — process setting. Они откатываются
  с запросом; это НЕ внешние committed revocations и не positive auth mock.
- 5 afterflush cases видят actualgen2/flags/один audit, затем fault/cancel/current
  auth loss. BaseException rollback и independent fresh state сохранены.
- 3 concurrent contenders replace/revoke/activation: ровно one200/one409,gen2/один audit.
  Lost ACK wrapper СНАЧАЛА await original COMMIT, потом ConnectionError; свежий GET
  видитgen2,oldCAS409,newCASdisable200. Поздний rollback не отменяет тот commit.
- Cancel только после real typed wait. Internal service сохраняет caller root:
  fresh reader до caller completion не видит flush; commit и rollback различены.
  Exact type/purpose/subclass rejection и empty-Member parent boundary прошли.
- 4 external drift cases: blocker отдельно COMMIT home/Role/MemberCP/child deletion
  до release. Request409, один исходный plan без расширения, собственные flags/audit
  не записаны. Внешняя committed мутация не объявлена отменённой request rollback.
- 3 structural cases: настоящий canonical bearer сначала eligible; App/grant/both
  выключены SQL commit, activation включается, но verifier/actual POST остаются401.
  OAuth5-query snapshot/children/business сохранены, только activation audit добавлен.

C43

3foreign owner +4canonical-only foreign install locations +30raw typed:
**5 kinds objects/equipment/counterparties/contracts/documents ×3modes×2flags**.
Даже ALL/EMPTY и false/false дают409 передB, без advisory/row locks/DML/обхода чужих
owner/Org/kind; actual native actor проверен, whole13-query snapshots двух tenants
неизменны.6local extras сохраняют буквальный32whitespace native ID вне profile
selection и полный canonical parent union доMember.1B/gen2/flags/audit и unchanged
children/business/raw sets проверены; EMPTY отключает flags, не structural guards.

RAW, isolation и cleanup

Длительности с bootstrap — в JSON; не benchmark. Warnings сохранены.
Passive CALL SQL:A53675/B55454/C20076, sums executions совпали; params не записаны.
CALL включает test mutations, lock polling, GET/readbacks/negative writes/external
commits, не чистую production нагрузку и не exactly2DML budget всей семьи.

PG starts и monotonic phase bounds упорядочены A→B→C; own IDs предыдущего мира
отсутствуют в следующем foreign-before. Каждый мир: pools после dispose0/0 на
живом loop, clients0/locks0, оба owned containers exited0/OOMfalse/removed,
все25 controller operations exit0/reaped.41foreign safe projection entries
Id/Image/Running/StartedAt равны до/после; это не аудит всех чужих данных.

PASS ограничен ORIGINAL activation139 на указанном составе. Старый accepted51
наb41 не заменяет139; DPL отдельно, OPTIONS75/SDK17 сюда не перенесены.
WholeAPI/CI/M15/performance/deploy/production flags не приняты; M00–M19+11 OPEN.
Control/env/DSN/privateRAW не читались; добавлены только эти два review файла.
