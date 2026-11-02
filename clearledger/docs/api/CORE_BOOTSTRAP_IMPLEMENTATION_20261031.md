# M16-C4: explicit Core bootstrap и настоящее обновление старых схем

**FactsOnly7, 31.10.2026: ROOT подтвердил 45 из 57 ID в 40 отдельных сериях.**

Осталось 12 обязательных сценариев: REC4 и OLDUP8. Шесть LIFE приняты отдельно:
66 raw-файлов, 1589 CLI reaps. Единого прогона 45 или LIFE6 не было. Source12,
source939, V6, V2/V3 и все 57 ID сохранены. Worker runtime0/purecontrols0;
только чтение, AST, hash и compile в памяти. M16 и 20M+11 активны.
Commit/push/worker_done остаются на HOLD.

## Факты ROOT: 45/57 в 40 сериях

ROOT msg_e11cdf10199a разрешил ровно два отчёта. Точные FactsOnly6
MD2398803a/JSON249f3705 сохранены в
.artifacts/core-bootstrap-implementation-20261031/i5-facts-only-6.
Их исторический охват 36/31/21 и объекты FactsOnly1–6 не переписаны.

Состав: baseline6 одной серией, затем отдельно 6 FRESH, 9 UPG, 9 REF,
6 CFG, 3 TX и 6 LIFE. Aggregate remote-core45-exactset-acceptance.json,
SHA256 3b8c7456b1c2eb30b34bb991ee3066b9457499937737734de6b75e582980e981,
содержит 40 receipt SHA и точное множество 45 ID. Все 40 файлов, SHA и ID
сверены чтением, включая отдельную schema baseline6 receipt. Registry order
сохранён отдельно от actual order.

| Отдельный LIFE case | Native seconds | Outside seconds | Controller seconds | CLI reaped |
|---|---:|---:|---:|---:|
| LIFE-full-prepare | 50.815917450 | 61.778001322 | 62.834294116 | 260 |
| LIFE-rejected-no-seed | 32.966850897 | 43.579621032 | 44.624299318 | 189 |
| LIFE-marker-repeat | 63.136429690 | 74.761481934 | 75.447431926 | 297 |
| LIFE-no-jobs | 59.718200709 | 71.253700770 | 72.410253892 | 279 |
| LIFE-readiness | 58.957258338 | 71.495424075 | 72.189905642 | 285 |
| LIFE-cleanup | 58.536312288 | 70.804049350 | 71.417555782 | 279 |


Root receipts подтверждают 15851/source939/77 before=after, оба положительных
private PID1 census, известные native/controller identities3 absent, ordinary
removal своего executor и OID16384/clients0/locks0. UNOBSERVEDactual0;
индивидуальная смерть неизвестных PID не заявлена. Classifier13 и metadata16
не добавляют primary ID. Полные каталоги/raw находятся в pinned Root receipts;
summaries и пути приведены в JSON.

TX3 подтвердили borrowed-транзакции, isolation/read-only, отсутствие дополнительного
connect и rollback с sentinel0. Read-only дал DBAPIError → adapter.Error →
ReadOnlySQLTransactionError, native SQLSTATE25006, orig/cause/noextraDAG и четыре
source bindings. Immutable runtime_chain_measured=False в sourcefreeze не переписан.

LIFE-negative отказал точным PULSE_PARENT до DDL/seed/marker; Core остался пустым.
Full prepare прошёл настоящий _prepare_database_once, BaseDDL/phone, полный
legacy/activegroup tail, seed/postseed и readiness с реальным file probe.
Marker повторил prod prepare с одной completed строкой и неизменным состоянием.
Cleanup проверил dispose и tracked backend0. Все шесть LIFE используют managed
gate OFF: managedON LIFE certificate не заявлен. Full/no-jobs достигли 10 terminal
capture labels в 9 stub modules: 8 run_forever и manager.start/stop. Реальные job
bodies не запускались. Prod mount200 из marker-кейса не заявлен.

## Исправления ожиданий verifier: прежние отказы сохранены

V1 full-native завершился успешно, но внешний acceptor отказал из-за неполной
source-деривации 267 статей/443 привязок: были пропущены projects.ARTICLES.extend
на строках966/1021. Полный V2 AST-обход 12 info-файлов, Assign/AnnAssign/AugAssign/
append/extend, names/concat/common partition и guide metadata без вызова функций
вывел 276 статей, 455 привязок и 59 категорий. Есть provenance каждой строки,
opaque body SHA и fail-closed на неизвестной metadata-форме. Это пересчёт исходников,
без ручной дельты и подгонки наблюдавшихся значений.

Full capture packet V1=4cdd отделён от corrector V2=6c891. Root принял receipt
efe3cbcd26a7e81151e3020a2d3232fb9c3c340ec7746bc0d00b126c6f622d3f по тем же
native/read данным. Повторного native/read запуска не было; V1 count-refusal/raw
сохранены. Actual common/energy/fuel/office статьи: 99/57/97/23.

Readiness дал настоящий ready, затем реальный DROP Pulse child и точный negative
HTTP503 через frozen READY_PULSE_CHILD classifier. V2 отказал на общем запрете
warnings: main793–798 нормативно пишет warning перед HTTP503.
Первый V3 manifest d910 не содержал tail_endpoints; ROOT остановил его до исполнения
и сохранил source finding. Исправленный 06e841 добавил только два byte-exact V2
endpoint; Python02676493 и derivation2175 остались неизменными.

V3 допускает ровно одну строку с валидным logging timestamp:
2026-10-31 18:31:28,798 [WARNING] clearledger: readiness: Pulse audience schema is not ready
Raw stderr SHA 9ff15172784042407fe490aa5985d65991f2a77e20fb024e0399733f390feb42
сохранён. Условие связано с case/nonce58ac/proof17e1750f, pinned logger/Pulse/HTTP503
AST, положительным первым ready/private probe, реальным SQL DROP и независимым
childabsence. Лог сам по себе не даёт PASS; другие WARN/ERROR/CRITICAL запрещены.
Logger, уровни, need, classifier и SUT не подменялись. Negative DAG не сериализован
в final detail: его проверил настоящий frozen native classifier; JSON DAG не придуман.

Readiness capture V2=6c891 отделён от corrector V3=06e841. Receipt
c04147027b7a0905d6f3546cc40d3596140402644845e121e848186502474c33 принят offline,
без native/read/SQL rerun. V2 WARN-refusal и source-d910 finding сохранены.

## Независимые проверки и границы результата

Два scoped SOURCE/artifact review приняты ROOT, reviewer runtime0:

- TX3 + LIFE-negative, 4 серии/44 raw: MD 0c34d1d6ce70449455abcad4a52d581b598a4eec3ad74b531c8906ccbd6bd219; JSON f8c24951262c04bf5496a6ddcc757d8985d74951bde4c3446138a09fc5e03dff.
- Full LIFE, один исторический native capture и V2 correction/11 raw: MD 8ec9ca6e9f521d2205aa7ea413cb38e23b29494346e638db0120a8d11144a078; JSON e68fd2941bcd66b64d1dd3a84a2c2bf695410eb1c66b3f169050d2e5a5eac4d4.

Scope reviews не расширен до повторного аудита всех 45; snapshots40/41 сохранены.
REC4/OLDUP8 не приняты: actual old binaries/sender/cancel/same-DB restore ещё впереди.
REC5 source подготовлен для Root review; restore последним после OLDUP8, новый actual OID.
Working backup/operational rollback, full57/final composition/fullCI/pilot/deprecation/
release и вся программа 20M+11 не закрыты. Прежний узкий artifact cancel/rollback
остаётся своей проверкой. Actual jobs не запускались.

## История FactsOnly6: snapshot 36/31/21

**I5 FACTS ONLY 6: ROOT принял 36 из 57 primary-сценариев в 31 серии; worker runtime0.**

Реализация I5 и V6 не менялись. ROOT подтвердил baseline6 одной серией и отдельно
6 FRESH, 9 UPG, 9 REF, 6 CFG: это 36 разных ID, без единого прогона 36 или CFG6.
Остаётся 21 обязательный сценарий: TX3, LIFE6, REC4, OLDUP8. Full57, полный запуск
lifespan, реальные jobs, workingbackup, operational rollback, fullCI, fullAPI и выпуск
ещё не приняты. M16 и программа 20M+11 активны.

## Факты ROOT: CFG6, текущий охват 36/57 в 31 серии

ROOT msg_53dd9c415ec3 разрешил FactsOnly6 только в этих двух отчётах после завершения
SOURCE-пакета TX3. Предыдущие два отчёта сохранены целиком в
`.artifacts/core-bootstrap-implementation-20261031/i5-facts-only-5`.
Все 57 ID и группы сохранены. Автор выполнял только чтение, AST, hash и compile в памяти;
app/helpers/новые команды не импортировал и не запускал, SQL/SSH/Docker/tests не выполнял.
Пакет TX3 передан ROOT для отдельного source review: это не результат TX runtime.

| Отдельный CFG case | Native seconds | Whole seconds | CLI reaped |
|---|---:|---:|---:|
| CFG-off | 39.718073914 | 51.482910553 | 215 |
| CFG-identity | 31.755413920 | 43.965855272 | 189 |
| CFG-url-options | 30.622632195 | 44.213001059 | 183 |
| CFG-no-port | 32.716505803 | 45.557579546 | 195 |
| CFG-real-path | 32.987520950 | 45.757415695 | 195 |
| CFG-source-before-lock | 31.528366410 | 44.363304233 | 186 |

Aggregate `remote-configuration-six-separate-acceptance.json`:
SHA256 `603ab42035aa3caeeac34cb8ba1f384f1ef76552fdb6a0289a19bb8e48f3e182`.
Шесть receipt SHA и caseproof SHA сверены с исходными файлами; полные receipts,
точные пути и границы утверждений приведены в JSON. 1163 CLI reaped относятся к CFG6;
13 classifier и 16 metadata controls в каждой серии не увеличивают primary denominator.
ROOT receipts подтверждают native/outside/controller0, source15851/77 before=after,
два положительных PID1 census, отсутствие известных native/controller identity,
ordinary removal собственного executor, OID16384 clients0/locks0. UNOBSERVEDactual0;
не заявлена индивидуальная смерть PID, которые не наблюдались.

Два независимых SOURCE/artifact review приняты ROOT, material findings0:

- CFG первые3: MD `4c2952a7dfac2bb7d829f5b5e354d9032044f8f9b7882eb98d31c2da26bbed03`, JSON `66eeeb8b1ed3039d7bb72149aea28ad39989bbe4633dcf6d7bea2f51d27a2d5d`.
- CFG tail3: MD `f09a6c98fbea5ad7e32e12c3837186df14763cdc411aea63472ac0454140edea`, JSON `fd5027002b708d38c74957f343c8c71a1070a99fe32ba04568d86988012961c6`.

Reviewer проверял сохранённые ROOT-артефакты, новых runtime/kernel/PG измерений не делал.
Первый review хранит исторический снимок 33/28/24, второй текущий 36/31/21.
Оба отчёта и FactsOnly1–5 не переписаны ради текущих чисел.

Границы CFG6: OFF доказывает отсутствие дополнительного connect на входе gate,
а не отсутствие SQL во всём процессе. Identity и URL-options проверяют конкретные
типы, source origins и causal chains. No-port классифицирует offline5432, подключения
к5432 не было. Real-path использует настоящий Core engine и borrowed PUBLIC session,
но startup owner lock уже удерживался. Source-before-lock вызывает public preflight
с неправильной database config до НОВОГО connect: это не tamper исходников и не
полный конкурентный lifespan/startup-lock proof. Setup/admin SQL остаётся в истории.

Все ранние FAIL/NOTPASS, raw receipts, ограничения REF/FRESH/UPG и исторические
счётчики сохранены. Контрольные metadata callbacks не доказывают запуск jobs.
12 sourcefiles, source939, wrapper/cases, 3 V6 sidecars остаются frozen;
commit/push/worker_done HOLD, runtime author0.

## История FactsOnly5: 30разных ID в25сериях,27ещёнеприняты

ROOT msg_8172bda1779b разрешил FactsOnly5 ровно в двух отчётах.
Baseline6one+6FRESHsingle+9UPGsingle+9REFsingle = **30primary/57 в25сериях**,
не single30green и не единая REF9green.57originalID=old49+8OLDUP сохранены.
Порядок отдельных ROOTсерий отличается отregistry;9membership совпали, исходный
registry не переставлен.12I5code/3V6supervisors неизменны; commit/push/worker_done HOLD.

| Отдельный REFcase | Native seconds | Outside seconds | Controller seconds | CLI reaped |
|---|---:|---:|---:|---:|
| REF-missing-core-public-decoy | 33.218008994 | 44.766885358 | 45.912544408 | 194 |
| REF-visible-public | 33.933419215 | 46.451658382 | 47.396387126 | 195 |
| REF-unknown-future | 36.102906317 | 47.394979934 | 48.003174514 | 201 |
| REF-gap-checksum | 38.127759269 | 50.102817796 | 50.705035408 | 213 |
| REF-owner-actor-action | 36.695357609 | 48.461742874 | 49.181098247 | 207 |
| REF-source-drift | 32.055458114 | 43.102864448 | 43.702908061 | 189 |
| REF-catalogue | 35.341304502 | 46.916339463 | 47.472440438 | 201 |
| REF-default-acl | 32.651112054 | 44.997953083 | 45.624148509 | 195 |
| REF-wrong-marker | 52.112398412 | 63.532815161 | 64.188684558 | 267 |

Rootaggregate remote-refusal-nine-separate-acceptance.json
SHA68553528d095b5e1b7247db0cbff2e0653368dcd0b76ba2a8d6cce3df8d9f455 содержит9receiptSHA,
strictoracles и fullreceipts.9файлов/embeddedJSON/actualplanlimits/seals сверены;
всеpaths/SHAs в JSON. Native/inside/outside0,15851source+77same,13classifier/16metadata
отдельно, дваPID1census,3native/controller independently absent, ordinaryrm,
OID16384/clients0/locks0,UNOBSERVEDactual0. Не заявлена индивидуальная смертьнеизвестныхPID.

REF9приняты ROOT. ROOT msg_932696c39c2d затем принял независимый SOURCE/artifact
review task_f17f84c206dc/ctx_5686912235bd:129rawfiles,1862CLIreaps,9seals,
0scopedmaterial findings. Reviewer не делал новых host/PG/kernel/runtime замеров.
DreviewMD SHAa0f74ef76a157d3cfbb058c44ef8273d1253c69b8b3178c3e11dc72981b19299,
JSON SHAa87c1d5c03937e226e8635a8db5552e50c7fc1fe8b5c57d315753a6e111d5010;
абсолютныеpaths/scope в JSON. Раннийb530/ba5 поддерживает21snapshot отдельно.
Rawaggregate полеpending осталось какна моментсоздания; closure не переписываетraw.

History3+6+5 =14подвариантов внутри3primaryID, не14дополнительныхPASS.
Unknown/future/extra-over-bound; gap/ordinal/parent_revision/artifact_sha256/
contract_sha256/predecessor_sha256; owner/applied_by/app_commit/runner_format/
action-SQLcheck-and-pure сверены соSOURCE. Actioncase: nativeCHECK23514+purevalidator;
invalidaction не persisted, DB-gate отказ persistedbadrow не заявлен.

Decoy/visiblepublic: NS_PATH/NS_FOREIGN exactsourceorigin, но directprepare уже
understartupLock, не полный pre-lockproof. Source-drift: ownedcopy30files/196966B
с11Bкомментарием; до НОВОГОconnect, ctx.setup уже имелapp/controlconnection,
не fullstartup/prelock. ACLsnapshot не весь pg_default_acl/globaldefaultACLproof.
Marker: только negativephase before=after/write0. Initialprodprepare имелnativewrites;
actualterminalcalls=[] и2088BINFOstderr. Installedcapturehooks не равны реальным
jobs; это не wholeprocesszeroIO/zeroDDL. InitialpublicprepareJSONDecodeError/600Bstderr
и отдельныйsuccessfulprepare-v2 сохранены, не extra primary и не стёртыйFAIL.

FactsOnly1–4/всеoldfailures/NOTPASS/raw и неизвестный первый FRESH-repeat PGrecheck
с поздним отдельным0/0без appretry сохранены. Publictrace/noDDL/marker10captures/
UNOBSERVED0 caveats действуют; controls/локальные2/14subvariants denominator неувеличивают.
Остались **CFG6/TX3/LIFE6/REC4/OLDUP8=27primary**. Full57/realjobs/workingbackup/
операционныйrollback/oldsourceupgrade/restore/fullCI/release ещёнеприняты;
узкаяartifactcancel/rollback ранее проверена, не весь operationalrollback.
M16/20M+11активны; runtime/purecontrols/supervisorimports автора0.

## История FactsOnly4: 21разный ID в16сериях,36ещёнеприняты

ROOT msg_3c484674242c разрешил FactsOnly4 ровно в двух отчётах.
Приняты baseline6one +6FRESHindividual +9UPGindividual: **21уникальныйprimary/57
в16сериях**, не single21green и не единая UPG9green. Полные57ID/old49+OLDUP8
сверены с frozenCASE_GROUPS; scope не сокращён. 12code и3V6supervisors неизменны.

| Отдельный UPGcase | Native seconds | Outside seconds | Controller seconds | CLI reaped |
|---|---:|---:|---:|---:|
| UPG-unversioned-adopt | 49.629520756 | 61.299887926 | 61.901029666 | 249 |
| UPG-prefix1 | 59.125608028 | 70.807161713 | 71.944649695 | 273 |
| UPG-prefix2 | 59.076819113 | 70.663111985 | 71.218965519 | 273 |
| UPG-prefix3 | 58.360904030 | 69.928732145 | 70.490783436 | 273 |
| UPG-pulse-created | 59.933821815 | 71.408652989 | 72.010599342 | 279 |
| UPG-pulse-adopted | 61.175161508 | 73.019521226 | 73.649663474 | 279 |
| UPG-head-repeat | 62.974877911 | 74.654767927 | 75.239117312 | 282 |
| UPG-calendar-cutover | 59.642228831 | 71.320566351 | 71.948731739 | 273 |
| UPG-foreign-parent | 39.223311971 | 50.680919621 | 51.323449130 | 207 |

Все9отдельно: native/inside/outside exit0,15851source+77dependencies unchanged,
13classifier+16metadata controls отдельно, дваPID1census,3native/controller identities
independently absent, ordinaryownexecutor rm, OID16384/clients0/locks0,
UNOBSERVEDactual0. ActualfinalDB/WAL, limits и planseal сохранены отдельно поcase в JSON.

Unversioned принял3canonical existing artifacts как adopted и сохранил populated
association через nativeprepare/readiness. Prefix1/2 создали только недостающие
successors; prefix3/head дали actions[] и stateinvariance. Pulse0003 отдельно
created/adopted, populatedassociation сохранена. Foreignparent дал strict
M_V1_COLUMNS/code4/columns, catalogue/data before=after и ownerwriteattempts0.

Calendar-cutover здесь **EMPTYCalendar**, не populatedsent_at/highwaterboundaryproof.
Head-repeat выполнил SOURCEassertion отказа default0001check против newerhistory;
это не отдельная полная rawnegative/wholeSQL/noDDL квитанция. Fixtures являются
каноническими literalSQL prefixes, не реальными старыми схемами ce94/5ce:
OLDUP8 остаётся обязательной отдельной работой. Полный currentstartup8успешных
кейсов использовал только разрешённые capturedterminals, не реальныйjobs/SMTP/WSlaunch.

ROOT aggregate remote-upgrade-nine-separate-acceptance.json содержит9exactID,
9acceptanceSHA/полныеreceipts и limitations; все9файлов и embeddedJSON сверены.
В JSON абсолютныеpaths/SHAs/9caseproofSHA/actualselectedlimits/planseals.
FactsOnly1–3, все старыеfailures/NOTPASS и неизвестный первый PGrecheck повторного
FRESH сохранены. Publictrace/noDDL/marker10captures/edge-only/UNOBSERVED0 caveats
действуют.13/16controls и overlapping local2 не увеличиваютprimarydenominator.

**36primary cases ещё не приняты.** REF9sourceproposal передан только как планирование;
14historysubvariants внутри3primary не станут14дополнительнымиPASS. Full57,
OLDUP/borrowed/recovery/restore/workingbackup/operationalrollback/fullCI/realjobs/
release не закрыты. Commit/push/worker_done HOLD; M16/20M+11 активны.

## История FactsOnly3: 12разных ID в7сериях,45ещёнеприняты

ROOT msg_27cd8803a09f разрешил FactsOnly3 ровно в этих двух отчётах.
Приняты baseline6 в одной серии и6FRESHcases в шести отдельных сериях.
Это **12уникальныхprimary/57 в7сериях**, не single12green и не единая fresh6green.
Original49+8OLDUP и все57ID сверены с frozenCASE_GROUPS; сокращенияscope нет.
12code/helper/SQL files и3ignoredV6supervisors не менялись; commit/push/worker_done HOLD.

| Отдельный FRESHcase | Native seconds | Outside seconds | Controller seconds | CLI reaped |
|---|---:|---:|---:|---:|
| FRESH-canonical-core | 51.211675243 | 63.807489278 | 64.852771667 | 255 |
| FRESH-repeat | 68.685936285 | 80.782301553 | 81.675349577 | 309 |
| FRESH-nonempty-refuse | 40.101814605 | 51.318240841 | 52.389342277 | 216 |
| FRESH-artifact-rollback | 33.405424029 | 45.817265664 | 46.456832657 | 195 |
| FRESH-missing-edge-extension | 33.206650181 | 45.800850566 | 46.828118556 | 195 |
| FRESH-canonical-parent-contract | 32.699018809 | 44.445050966 | 45.614696674 | 189 |

Все шесть отдельно: exit0, source15851/dependencies77 before=after,
13classifier+16metadata controls отдельно, два положительныхPID1census,
3native/controller identities independently absent, ownexecutor ordinaryrm,
PG OID16384/clients0/locks0; финальныеDB/WAL сохранены по каждомуcase в JSON.
UNOBSERVEDactual0: это не runtime-проверка transientветви.

Canonical-core: created0001→0002→0003, fresh_exact/head0003 и native readiness
ready/databaseok/storageok. Repeat: после полного startup prefix3,
prepared_root0e9b_v1, actions[], stateinvariance и readiness. Полного SQL/no-DDL
свидетельства из этого не выводим. Первый independent PGrecheck завершился
assertion с неизвестными значениями; stderr сохранён. Поздний **отдельный readonly**
recheck дал0clients/0locks; приложение не запускали повторно ради green.

Nonempty: strict MigrationError4/bootstrap_not_empty, catalogue/data before=after,
owner writeattempts0. Missing-edge: strict4/bootstrap_admin_prerequisite с теми же
invariance/0ownerwrites, но fixture удаляет только edge, не extension.
Artifact-rollback: наблюдён реальный artifactSQL, cancellation/atomicrollback,
затем retrycreated1–3. Это узкий rollback artifactcase; не рабочий backup/restore
или приёмка operationalrollback/recovery. Parent-contract: canonicalfull10/154cols,
fresh_exact, head0003/actionscreated1–3 и pinnedartifactc13b….

ROOT aggregate remote-fresh-six-separate-acceptance.json содержит6exactID,
6acceptance artifactSHA,6caseproofSHA и все метрики; actuallimits и seals взяты
из каждой соответствующей prepared-квитанции. Абсолютныйpath/SHA и полные
квитанции включены в JSON. Dreview5fad/bc98 относится к baseline6+firstcanonical1;
остальные5FRESH приняты ROOTreviewonly, независимыйDreview им не приписан.

Истории/ограничения сохранены: oldI2 broadoracle NOTACCEPTED, все прерванные
local/remote series, V4b native6passed/outerNOTPASS и V5interruption;
неполный publicSQLtrace, отсутствие wholeSQL/no-DDLproof, marker10terminalcaptures
вместо realjobs, исходные gate/env/budgets. Локальные2PASS совпадают с baselineID
и не прибавляются. Sourceupgrade9proposal отдельно передан ROOT как оценки доadmission.

**45primary cases ещё не приняты.** Existingprefix/adoption/OLDUP8/borrowed/recovery/
restore/workingbackup/fullCI/full57/realjobs иrelease не закрыты. M16/20M+11 активны.

## История FactsOnly2: одна принятая серия6/57

ROOT msg_35ce7e27e071 разрешил FactsOnly2: изменены только эти MD/JSON.
Все12I5code/helper/SQL files, Source939, wrapperac396 и cases351393 прежние;
три ignored V6supervisor files также не менялись. Commit/push/worker_done HOLD.

Принята **одна полная серия characterize_current**, nonce b4799d3aae8b:
CUR-empty-core-off, CUR-empty-core-on, CUR-public-off, CUR-marker-core-off,
CUR-template-distinct-grantee и CUR-template-owner-grantee. Все6native archived
children exit0/reaped; результаты совпали с ранее независимо проверенными oracle.
Native207.811697538s, outside220.123732533s, controller221.235167486s;
native/container/outside exit0 подтверждены отдельно от SSH/client exit.

Source-before/after15851files равны, dependencies77 unchanged;13classifiercontrols
и16metadata controls на процесс учитываются отдельно от6primary. Оба положительных
privatePIDnamespace census=[1], namespace/start сверены с actual PID1.795DockerCLI
reaped;8native+controller независимо absent, ownexecutor ordinaryrm/absence.
Финальный ownPG OID16384, DB17644567B, WALdelta18850120B, clients0/locks0;
они ниже48MiB/64MiB. Sealed stage wall/CPU600s, nativecase/childbound180s,
8GiBhostfloor+32MiBplanning прежние. Остальные точные Rootstage limits в JSON.

Это **baseline immutable e6abf86b**, не приёмка новой fresh/upgrade реализации.
CUR-public-off выполнил native legacyfullprepare/repeat/readiness; известный
неполный public SQLtrace не выдаётся за полный перечень SQL или proof no-mutation
повтора. Markercase дал10ожидаемых terminal captures, реальныхjobs не запускали.
UNOBSERVED transientcount=0: ветвь восстановления transientmapping в этом принятом
запуске не была runtime-проверена; индивидуальную «смерть» неизвестныхPID не утверждаем.

Два ранних локальных strictsingle PASS входят в те же6ID, поэтому итог **6/57, не8**.
Остальные51ID, candidatefresh/upgrade/repeat/fulltail/recovery/restore/currentCI/full57
и release остаются вне этой приёмки. Rootfirst FRESH-canonical-core планирует отдельно;
source resource estimates не становятся прошлыми измерениями или admission.

Exact ROOT receipts:

- remote-char6-v6-acceptance.json и caseproof SHA23e61b04f1bfac8041d99ee064e550548d9cd4e8529f7ed0f273bda8d83fa3d9;
- remote-char6-v6-prepared.json: sealedplan40d0c99170c12cc41c08ebc4b72ccbe7cb6565e30741bcdab0817e6b002be74c;
- remote-char6-v6-execution.json и remote-c0-v6-acceptance.json.

Абсолютные paths/receipt SHAs/полные limits/результаты6cases включены в JSON.
C0V6 отдельно принят как source-refusal transportcontrol: primary0/classifier0/
appimports0, nativeexit2, containerexit0; это не дополнительный primary PASS.

Истории сохранены без переименования: старый I2 broad-oracle NOTACCEPTED,
localdisk interruptions, remoteV4preimport archiveparentmetadata refusal,
V4b native6passed/OUTSIDENOTPASS, V5 interruptedNOTPASS. V1/V3подготовленные
supervisor версии не исполнялись; V2control failure не объявлен candidatefailure.
FactsOnly1 snapshot остаётся неизменным свидетельством своей прежней точки1/57.

## История FactsOnly1: принят1/57, char6 прерван без PASS

ROOT msg_552079ac24a5 разрешил изменить только эти два отчёта. Все12code/helper/SQL
files exactI5, Source939/wrapper/cases прежние. Immutable14file I5snapshots сохранены.
Следующие этапы и commit/push/worker_done остаются HOLD; параметры/57IDs не менялись.

Принят только CUR-empty-core-off из отдельного strictsingle запуска ROOT:
38.624456723s, parent и archivedchild reaped. Actual RuntimeError «Pulse audience
schema is not ready» из exact require_connection → canonical MigrationError4,
phase pulse_parent; проверен полный2node causalDAG. Отдельно прошли12negative и1genuine
journal classifier controls в parent/child; это13controls, не дополнительные primaryPASS.
SourceAfter939/77dependencies/16sendmsg controls same, forbidden0/DDLData0/jobs0,
каталог и строки без изменений. DB8059927B, WALdelta309480B, OID16388, clients0,
peakmemory94560256B, tmpfs48558080B, OOM0, minFree8631803904B; floor8589934592B прежний.

Отдельная char6 attempt ROOT остановлена guard reason disk_floor через43.368907554s:
parent exit-15/reaped; два owned children1871932/1874849 независимо absent.
Первый child оставил complete raw CUR-empty-core-off, второй CUR-empty-core-on
прерван. **Из этой attempt принято0primary; всей группе PASS не присвоен.**
SourceAfter939=true, OID16388, DB8059927B, WALdelta2560B, clients0, tmpfs48558080B,
OOM0. ROOT interruption review записал measuredFreeAfter8633077760B. Это не текущее
измерение автора и не допуск к следующему этапу. Candidatefailure не утверждается.
Raw, process/plan и interruption review сохранены ROOT. Данные незавершённой attempt
не выдаются за logicalcatalogue/data invariance или full native preparation PASS.

ROOT receipts (пути от root-core-bootstrap-implementation-review-20261031):

- char-first-i5/acceptance.json SHA1ebb4c2bb72bb40797ce683642a9728d6a57a3e5a3fd21761b0f003c4d9a58e4;
- strictsingle raw SHA3a12a9576227b767c90f96b76e8030dcea195e605e8d226814a8232eeaf532e2;
- char6-i5/process.json SHA067a2301268a7c2906afeb988ff05a93248269b396d90d76aad9f38825cb76f2;
- char6-i5/plan.json SHA94e0a0fd4aee80d8628b751ce602dc198de5ca8478ce5dc37f8e8ff99a48f69b.

Exact interruption-review/raw-file paths/SHAs в JSON. Старый I2 NOTACCEPTED сохранён.
Итого accepted1/57, remaining56unproven, source/package не равен runtime acceptance.
Ни char6whole, ни fresh/upgrade/repeat/fulltail/restore/full57 не объявлены успешными.
512MiBtmpfs не отменяет8GiBhostfloor; новая stage admission требует свежих измерений ROOT.

## История I5: fixed binding на момент source freeze

ROOT msg_7da585900664 дал named SOURCE GO на два helper и два отчёта.
Закреплён единственный target api_core_bootstrap_sequence_test_20261031,
user clearledger, loopback127.0.0.1:33547; lease требует execution Dispatch
ctx_258a83d73654. Source author original ctx_3c05913866a6 сохранён в provenance.
Generic env targets/dispatch selectors не добавлены. Проверки OID/UID/UUID/sourcehash/
privatepaths, все16sendmsg и13oracle controls, 57primary IDs и10production/schema
payloads сохранены. CFG-no-port удаляет только новый fixed33547 офлайн; подключения
к5432 нет. Полный14file I4/patch/receipt/delta/manifests сохранён в history-i4.

ROOT prepared receipts: own-tmpfs-pg-v2.json, own-tmpfs-pg-host-tcp.json и
own-pg-prepared-db-inventory.json; точные пути/хеши в JSON. По ним CID590f787f5d44…,
image721873c34ceb…, PG16.15/UTF8/maxLocks64; dedicated DB OID16388/8051735bytes/
clients0, admin создал только Core+edge+btree_gist, parentfixture/tables/seed0.
ROOT проверил hostTCP/asyncpg и закрыл соединение. Это факты ROOT preparation,
не PASS app/test и не измерения автора; существующий33546 не менялся.
DraftleaseUUID05754692-7806-4aab-af79-2824ae271167 ещё не sealed.

Бюджеты разделены: DB48MiB/WALdelta64MiB initialchar6 остаются stop caps внутри
RAM-backed PGDATA512MiB; container memory768MiB/CPU1/PIDs128/ROroot/log1MiB.
Hostdisk planning ROOT: log1+evidence8+scratch4+uploads4+margin15=32MiB;
архивы unique21429320bytes уже allocated, копировать заново не требуется.
Hard8GiBfloor прежний, ROOT сообщил около66MiB сверх него; actual fresh measurements
и source/resource admission ещё NONE. Это не доказательство, что full native startup
поместится в RAM/DB/WAL cap. Full4928MiB остаётся provisional: все57cases, включая
sameDB dump/restore, требуют отдельных измеренных допусков ROOT без сокращения scope.

I5 runtime0/purecontrols0. ROOT должен sealed lease с новым SourceSHA и текущими
UID/OID/UUID, проверить RAM/OOM/tmpfs/WAL/newCID/hostFS, затем дать stage admission.
Until then HOLD; helper/lease/app/SQL автором не исполняются, commit/push отсутствуют.

## История I4: synthetic classifier source fallback до GO I5

ROOT msg_aa9e37f240f4 передал continuation narrow GO msg_cb71de8256ed.
В ce94/5ce нет pulse_view_role_schema.py/schema_version_gate.py. Вложенный
classifier_controls.expected_runtime теперь берёт env.IMPORT_SERVER/path при
наличии файла, иначе env.SERVER/path из уже закреплённого source fixture.
Это только явно synthetic classifier metadata для adversarial controls. Actual
oracle origins/matches/capture, sys.path и old SUT imports/models/gates не изменены.
Полный I3, включая14files/receipt/patch/source manifests, сохранён в history-i3.
Изменены только casehelper, wrapper source pins и эти два отчёта. Все57primary IDs,
12negative+1genuine journal controls и10production/schema payloads прежние.

Source authoring продолжено в ctx_258a83d73654; frozen wrapper/lease сохраняет
source-original ctx_3c05913866a6. Новая execution attempt ещё не согласована:
ROOT отдельно решает binding после sourcefreeze; проверка lease не отключена.
Порт33546 остаётся закреплённым. Порт33547 — только ROOT plan, без полученных
preparedCID/lease/GO. План ROOT: tmpfsPG16 data512MiB/memory768MiB/CPU1/pids128/
log1MiB, cached721873image; автор ничего из этого не создавал/не измерял.
ROOT сообщил freeabove8GiBfloor≈66MiB. Это не admission: прежние caps/floor
не снижены; source review и отдельный actual resource review остаются обязательны.
Worker runtime0/purecontrols0; source AST/hash/compile only, commit/push HOLD.

## История I3: strict refusal oracle и сохранённый I2 observation

ROOT msg_38846a7bf35c выполнил только CUR-empty-core-off на I2: parent exit0/reaped,
33.449569391s, nestedchild0/reaped, SourceAfter939+archives и77dependencies same,
16controls, forbidden0/nojobs; PG3childconnections, DB8059927/WAL25248bytes,
clients0, ordinaryDROP exists0. **OBSERVATION_NOT_ACCEPTED_AS_PASS:** broad
Context.reject(error=Exception) принимал любой exception, actualtype/message/phase
не записаны (error_type был expectedException). Нельзя восстановить PASS из trace
или переименовать эту историю. Exact I2 bytes/proofs сохранены history-i2; ROOTraw
иleases остаются в root-core-bootstrap-implementation-review-20261031/char-first-i2.

ROOT согласовал narrow sourceproposal JSON9f871049: изменены только casehelper,
wrapper selfpins и эти2reports. Production/schema/C3/57IDs exactI2. Нет изменения
бизнес-полей, semanticnormalizer или budgetpolicy. Новый код не исполнялся автором.

ASTinventory:21rejectsites/24primaryIDs (15MigrationError,9applicationRuntimeError).
Каждый получает mandatoryclosed oracle_key, без defaultException. MigrationError
exact canonicalclass/integercode/literalphase/args и точный sourcepath/SHA/function/
ASTraise site. Namespace path и visibleforeign используют разные raise branches.
Полный __cause__/__context__ DAG учитывает suppressed contexts: скрытые NameError/
TypeError/AttributeError/import/OSError/driver/SQL/deadline не становятся PASS.
UNKNOWN re-raise с исходным actualtraceback. Actualqualifiedtype/code/phase/safeenum/
origin/causalleaf фиксируются независимо expected; прежние noDDL/newconnect и
catalogue/data invariance обязательны после exactclassification.

CUR-off ожидает PulseRuntimeError→Migration4/pulse_parent. CUR-on — engine→borrowed
ManagedRuntimeError→Migration4/unapplied. Marker childmissing — отдельный Runtime
leaf. Migration owner contention — только5/owner_lock с Timeout.__aexit__/Cancelled
chain, не любой timeout/deadline5. Полная case/variant classification table в JSON.

Дополнительно закрыты остальные negative branches: CFGpreflight; native readonly
25006; exactFastAPIHTTPException503/detail с Pulsechild cause; ownedsourcecopy2/
bootstrap_source; action SQLCHECK23514/ck_core_schema_action/core_schema_versions и
отдельный pureMigration4/history. Они не допускают arbitrary status503/sqlstate-only
fake, SQL/programmingerror или неправильный refusal origin.

12classifiernegativecontrols +1 genuine frozenjournal positive выполняются ROOT
передnativecase и учитываются **отдельно от57**. Direct/wrapped NameError/TypeError,
AttributeError, wrongorigin, forgedMigration/code6/wrongphase, unrelatedSQL, fake503,
missingcausalleaf должны отвергаться. Hidden-context unit inputs явноsynthetic
classifiermetadata с source-validouter, не mocked guard/DBsuccess. Positive — реальный
frozen journal.validate_history error безPG; это проверка oracle, не startupPASS.
Автор controls не вызывал.

Для readonly ROOT msg_df07f98ccfa1 прочитал actual pinned77 source безimports и дал
4libraryfileSHA. Exact outerDBAPIError/.orig AsyncAdapt_asyncpg_dbapi.Error/.cause
nativeReadOnlySQLTransactionError25006, canonicaltype identity +AST translatedraise/
actualcausalframes; librarysource pins проверяются before/after. Runtime chain ещё
не измерен, mismatch fails unchanged, не расширяет allowlist по первому error.
Worker VENV не читал. Источник authority и4SHAs включены в JSON.

DB48MiB/168MiB остались prospective caps/admission proposal, не measured/provedupperbound.
Sourcefact: только CUR-public-off выполняет полную immutablee6 preparation дважды +ready,
не10parentfixture; другие5характеризаций guards/marker/ACLmechanism. AST не доказывает
PGcatalogue/index/TOAST/WAL/FPI footprint. При Rootestimate8.13GiB168MiBсверх8GiB
не гарантированы; fresh per-stage измерения ROOT обязательны. Floor/caps/6/57IDs
не снижены; existing --case допускает отдельную admissioncheap отказов без сокращения
fullnativepublic или remaining57. Initial admission I3 не дано.

## Основа, scope и неизменяемая история

Clean/fetch: старая design ветка HEAD=origin=e6abf86be1bbe26b623c2c7eff86f8a39824e826.
В том же own worktree создана agent/api-core-bootstrap-implementation-20261031
именно от e6ab; ROOT runtime composition base0e9b923106796c9f278d6e9ef5f813eeaa91ce66.
Старые ветки/ignored proofs сохранены. ROOT/A/B/Support/Deploy read-only, агентов нет.
Read-only privacy owners app/api_access_logging.py/app/services/export_files.py не
перенесены и не исключены из будущего общего состава; здесь их base bytes сохранены.

V3 design принят ROOT с MDd82908cc/JSON09fab332. Source investigation доказал отдельный
old-schema gap: ce94e2bf/5ce5779b не имеют models_partner/двух partner parents и Pulse
role-grant mapping. Нельзя выдавать old-code coexistence на новой БД за upgrade
старой схемы. ROOT msg_79730572f2f0 выбрал **B**, добавив ровно два versioned artifacts
для old8→+2 prerequisites и обязательные actual old native bootstrap/upgrade cases.
Итого разрешённый итог:4 existing +8 new source files +2 NEW reports =14 files.
Ничего не коммитится/публикуется до ROOT actual/review.

Существующие config/models/deps/Dockerfile/oldtests не менялись. Frozen23 прежних
schema files кроме разрешённого runner побайтно исходные, включая journal/registry/
0001–0003 SQL/contracts/verifiers. Прежний C3 helper EOF оставлен: SHA
6845a6f8b18f61114b410397bc18237ed6b5875041f49ccc3bd8863361676559.

## Что реализовано

`execute_sequence` — только явный operator API/CLI с target0003. Существующие
execute/check/apply/plan default0001 не становятся latest-check и по-прежнему могут
отказать на корректной newer history. Старый binary не обещан совместимым с новым
журналом. No slicing unverified rows, no retrospective0000/stamp/hash rewrite.

Offline Config + allknown source/оба prerequisite manifests проверяются до asyncpg
import/connect. Новый verifier module проверяется по bytes до import. One physical
connection: readonly precheck → прежний session advisory lock434532,1 → recheck →
одна write transaction для prerequisites и только отсутствующих0001→0002→0003.
Shared mutation body извлечена из existing owner без изменения AST. Новый path не
вызывает execute() на другом connection под своим lock. Commit/rollback/cancel/close
принадлежат owner; cancelled close shielded/awaited. Gate/lifespan ничего не применяет.

Fresh selector требует пустой Core: class/routine/type/domain/collation/operator и
прочие namespace dependencies отсутствуют. Единственное исключение pg_default_acl
разрешается лишь после exact effective ACL comparison с pg_catalog.acldefault для
actual creator и kinds r/f/S/T. Это metadata, не разрешение создать/исправить объект.
Никаких selfgrants/revoke/extension install. Core/edge owned namespaces и btree_gist
вне Core готовит ROOT admin phase; invalid prerequisites/defaultACL refuse до DDL.
Redundant owner grants сравниваются по effective semantics, не считаются автоматически
nonNULL ACL. Distinct grantee и owner grantee проверяются отдельными native cases.

Literal fresh SQL содержит10 FULL parents/154columns и exact PHONE_FUNCTION_DDL
перед stored generated users phone columns. Это reviewed static SQL из pinned AST,
не runtime ORM discovery/metadata subset/bypass. Calendar — frozen legacy20 columns
из f066910e source, без counter/check. Existing0002 единственный creator: fresh
1created/2created/3created. Upgrade канонического уже имеющегося counter может2adopted
по прежним acknowledgement/time/catalogue правилам. Physical DB provenance из одного
catalogue не выводится: source selector — operator assertion плюс strict shape.

## Старые схемы: отдельная явная prerequisite phase

`--upgrade-prerequisites core_partner_prerequisites_v1 --predecessor-source <exactpin>`
mutually exclusive с fresh selector. Только ce94e2bf30c0676208b1d70c5c135fe91d1a23f2
и5ce5779b20151a8d04de7d3a1681d1862a80d9dd, именованные prepared_exact profiles.
Source AST: у8 старых родителей все current mapped_column declarations совпадают;
единственное отсутствующее поле текущего Calendar — protocol_sequence. Phone SQL
literal bytes совпадают. Это source facts, не измеренный каталог старого deployment.

До первого DDL: old8 exact types/defaults/PK/UK/FK/index/owner/ACL/generated/function,
canonical default privileges, legacyCalendar20/no managed counter, отсутствие обоих
partner parents и всех managed table/type/reserved names. Partial/wrong/one-parent/
unknown predecessor/nonzero partial managed history refuse. Никакого repair.

Новая phase НЕ дублирует evolving DDL definition. Два exact byte ranges из canonical
fresh SQL заморожены в дополнительном contract/manifest:

- partner_clients: bytes5714:6336, SHAe4c368f5c72c26569072ad1a1e90f9907d6737345bba8d858544e5d8ec1e6f7a;
- partner_installations: bytes6336:6932, SHA327f0f23c5a3bedb3233b43766a5f13dda58b7e329a50a0be889b2e2efcd61af.

Это фиксированные проверенные ranges, не generic SQL parser. +2 DDL, full10 profile
и1→2→3 входят в ту же owner transaction. На repeat3 никакого fresh/+2 SQL/emptyassert:
полный verified known prefix и exact named full profile. Unknown/future/gap/refusal
не превращаются в автоматическое повторное применение/срезание истории.

## Именованные профили и startup

Fresh_exact и prepared_root0e9b_v1 — цельные profiles, не per-table wildcard mix.
Подготовленный profile допускает только шесть source-backed дополнительных indexes:
users phone_mobile/office_e164 и users_calendar_feed_token_uq; organizations company;
calendar series/recurring. Span index уже в fresh artifact; named span CHECK может
пересоздаваться native tail без обещания того же OID. Все154/155 columns/defaults/
computed/type ACL и исходящие constraints/index/FK triggers проверяются точно.
Extra columns/defaults/ACL/indexes/custom triggers/partitions/inheritance/RLS не
принимаются. PG16 auth CHECK deparse допускает только две явно заданные формы.
Нет измеренных expected snapshots, подставленных вместо проверки source contracts.

Public `preflight_bootstrap_source` и gate.preflight выполняют source/config checks
до первого startup checkout/lock. Managed gate OFF возвращает до import/config/I/O;
функции _config/require_connection/require_engine AST unchanged. Новая общая startup
source boundary отдельно читает known package integrity. Minimum applied revision
budget gate остаётся0001, unapplied latest ради budget не требуется.

main.lifespan выполняет read-only actual namespace/CorePulse admission до ownerlock;
_prepare_database_once повторяет его под lock **до completed marker**. Core Pulse
catalogue обязателен независимо от managed flag. Explicit legacy public fresh не
требует child до его ORM provisioning; custom/missingCore/publicdecoy refuse.
Read snapshot RR/readonly владеет только своим connection; borrowed C3 options/TX/
searchpath semantics сохранены. Data shape checks требуют SELECT, не обещаны offline.

Полные _prepare_database/create_all/seed/postseed/tail/readiness bodies сохранены.
Это несколько native committed phases, не одна атомарная startup transaction.
До отказа guard не должно быть marker/DDL/seed/jobs; поздний tail/seed failure может
оставить прежние committed phases и требует реального recovery. Автоматический
apply из lifespan/ready/gate не добавлен. Оба flags/defaults OFF неизменны.

## ROOT-only оснастка и точные знаменатели

Оригинальные49 IDs сохранены в группах6+6+9+9+6+3+6+4. Добавлена группа8 OLDUP:
real native old bootstrap→+2phase→current fullprepare/readiness/business witnesses,
repeat noDDL и5 refusal profiles. **57primary IDs;accepted30/57в25сериях(baseline6one+6FRESH+9UPG+9REFindividual);remaining27unproven.**
14 history subvariants внутри3primaryIDs не считаются14дополнительными PASS; action
variant — SQL CHECK denial + pure validator, не persisted-invalid-action gate proof.
Все full IDs/groups/subvariants и expected source contracts — в JSON.

Первые6 запускают реальный immutable e6ab app в отдельном frozen child process.
ce94/5ce имеют отдельные полные archived app trees; никакого filtered current models
или foreign model injection. Source-before/after exact app/schema archive manifests.
Full old normal bootstrap — настоящий app.main lifespan/seed/readiness дважды; затем
explicit current upgrade и native current pipeline. Отдельно остаются ordinary old
bootstrap на новой схеме/old ORM/native ASGI HTTP/old sender/ICS/default counter.
Exact business witness parity проверяет реальные old Company/User/Calendar rows;
это не обещание byte-equality всех system seed rows после старого/нового seed.

Root terminals устанавливаются до app imports через import loader **только** на
chat manager.start/stop и8run_forever. Выполнение underlying jobs запрещено; sink
reach/unreach фиксируется. Не подменяются testedprepare/Base/gate/SQL/catalogue/seed/
marker/ready. Native ready пишет/удаляет probe в private uploads; prod mount200 здесь
не обещан. Real controlled persisted history/data/catalogue negatives, actual borrowed
TX/options/rollback, real owner contention и cancellation проверяются после ROOT GO.
Сырой raw driver и SQLAlchemy statement capture сохраняется отдельно; driver metadata
protocol не выдаётся за «нулевые GUC»: source/options preserved, нет harness GUC tuning.

Audit boundary I5 допускает только exact127.0.0.1:33547/oneDB/userclearledger fixture.
16 C3 sendmsg metadata controls сохранены source; автор их НЕ запускал. Network/
externalHTTP/SMTP/SSH/PTY/shell/fork/posixspawn/listen запрещены. Единственный Python
subprocess — тот же frozen wrapper с точным child argv/cwd/clean env и closed selectors.
Parent180s timeout + own processgroup TERM/wait/KILL/wait при необходимости; никакого
FORCE database drop. Инвентарь expected77 только comparator; ROOT измеряет actual
before/after заново, включая no.pth/driver source. Worker venv не читал.

## Lease, restore и полное accounting

До destructive fixtures независимый ROOT root-db-lease.json (0600, no symlinks)
привязывает currenttask/dispatch, UID, source manifest, target, actual OID и UUID lease.
Helper сверяет OID через реальный PG и ведёт отдельный owned-db-lease/child leases.
Контекст намеренно не удаляет leased DB автоматически. ROOT supervisor выполняет
ordinary cleanup только правильной фазы, без чужих DB/deps/GUC/maxlocks/cgroup changes.

Restoreprepare фиксирует реальный before snapshot/OID/source/lease, закрывает helper
connections и возвращает **exit75 PENDING, REC NOTPASS**. ROOT оставляет leasedDB для
pg_dump, ordinaryDROP/recreate **ТОГО ЖЕ** name/новый OID и actualpg_restore. Перед verify
переиздаёт независимый lease с тем же UUID/newOID/newhash и кладёт process receipt:
3named phases pg_dump/ordinary_drop_recreate/pg_restore, каждый exit0/reapedtrue,
otherDBconnections0, dump SHA. Helper требует actual dump file hash/newOID и сверяет
полный logicalcatalog/data snapshot существующим immutable narrow canonicalizer,
после чего выполняет native currentprepare/ready. Старый canonicalizer не менялся.

Источник/цель — одна dedicatedDB во времени; вторуюБД helper не открывает. Каждая
фаза сохраняет отдельный results/raw trace. После verify REC может стать PASS;
intentionalpending не выдаётся за успех и не теряется cleanup. final_accounting
требует57distinct accepted IDs, SourceAfter, dependencies before=after, forbidden0 и
независимый ROOT process exit/reaped. До полного покрытия возвращает missing IDs.
Нет actual backup/restore/image/fullCI/live proof; рабочая migration требует свежих
backups и реального изолированного restore по отдельному поручению.

## Ресурсы и admission I5

Hard **8GiB hostdisk floor неизменен**. ROOT сообщил около66MiB сверх floor;
это не авторское измерение и не гарантия актуального свободного места.
Initial char6 сохраняет DB48MiB/WALdelta64MiB stop caps в RAM-backed PGDATA tmpfs.
Container bounded: PGDATA512MiB, memory768MiB, CPU1, PIDs128, log1MiB, ROroot.
ROOT отдельно измеряет memory/OOM/tmpfs/WAL и CID до/после каждой actual stage.
Source не доказывает, что full legacypublic metadata/seed/repeat в эти caps поместится.

Hostdisk planning: log1 + evidence8 + scratch4 + uploads4 + margin15 =32MiB.
Archive inputs47227903logical bytes/21429320unique bytes уже allocated ROOT;
инкремент для пересоздания архивов0, worker их не создаёт/чистит/меняет.
Прежний disk-backed152+16=168MiB proposal остаётся только в истории I3/I4.
Новый32MiB plan тоже требует fresh measured ROOT admission; floor не понижен.

Fullscope4928MiB остаётся provisional worstcase и не получает admission от tmpfs512MiB.
Later DB2GiB/dump2GiB/WAL512MiB/log64MiB/scratch128MiB/uploads128MiB — прежние
prospective whole-scope caps; ROOT должен предложить stage-specific measured budgets
для всех57cases, включая actual sameDB dump/restore. Нельзя удалять случаи ради fit.
Maximum4owned connections ожидается, не измерен. Primary/child180s, stage1200s.
Client/lock/sourceAfter/processgroup/timeout/reaping/ordinaryDROP обязательны.
Никаких GUC/maxlocks/cgroup/foreignDB/deps cleanup изменений автором.

## Exact ROOT execution contract: не исполнялся автором

В JSON полный argv/env/roots/SourceSHA. Actual executable inventory, existing grantee,
namespace/extension admin phase, ownedDB OID/UID/leaseUUID/hash ROOT должен независимо
зафиксировать до admission; эти поля source-only не могут быть честно угаданы.
При отсутствии actual lease hash wrapper до app/driver imports отказывает.
Пример ROOT-only source preparation (исходник ignored и только AST compiled):

```text
/home/mag/.local/bin/python3.13 -I -S -B .artifacts/core-bootstrap-implementation-20261031/root_prepare_archives.py <NEW-private-ROOT-archive-dir>
```

Архиватор читает только exact Git blobs, не вызывает app/SQL/install/network. Сам
wrapper запускает child **только** так: тот же executable -I -S -B тот же frozenwrapper
--approved-archive-child exact40pin closedselector, exact parentcleanenv/cwd.
Никакого genericprocess allowance. Для char6 fixed parent argv:

```text
/srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B /home/mag/orca/workspaces/ledger-app/api-schema-gate-history-20261031/clearledger/server/tests/core_bootstrap_sequence_approved.py --execute-approved-core-bootstrap-sequence-tests --stage characterize_current
```

Можно заранее согласовать suffix --case CUR-empty-core-off (либо другой exactID той
же group), чтобы измерять boundary/ресурсы последовательно. Это не сокращает57cases.
Exact clean env находится в JSON; только ROOT подставляет hash actual synthetic
lease receipt. Реальные .env/vault/credentials/ProxyEnv не читаются/не наследуются.
Четыре0700 owned empty/nonnested/noSymlink roots должны быть вне source, archives
отдельные immutable inputs. Реальные paths предложены в JSON; Root вправе выбрать
другие explicit reviewed roots до freeze argv/env, не скрытно во время исполнения.

## Проверки автора и следующий шаг

AST reverse доказал: вся исходная database после удаления двух NEWhelpers совпадает;
gate после удаления NEWpublicpreflight совпадает целиком; main совпадает после
удаления только reviewed admission edits; _prepare_database/readiness bytes AST
не менялись. Config/identity/state/require_applied_prefix/Parser и shared mutation
body runner сохранены AST; default execute differs only by shared extraction.
Old23schema/C3helper exact. New source AST/compile/hash/diff-only. Ни helpers, ни
новые purecontrols, ни приложения автор не импортировал/не исполнял.

ROOT проверил I5 sourcefreeze для strictsingle. Нужны дальнейшие independent
ROOT reviews/admissions всех оставшихся12primary cases, pinned payloads/catalogues/
argv/env/resources и полного выполнения. Sourcepackage
не равен functionalacceptance/release. Commit/push разрешаются только после ROOTfacts/
review поимённо; общий fullAPI/CoreSupportAuditor/auth/domains/clients/fullCI/pilot/
deprecation остаётся активной программой20M+11.

## Полный prospective ID list


characterize_current (6):

- `CUR-empty-core-off` — ROOT SINGLE6 ACCEPTED (baseline only).
- `CUR-empty-core-on` — ROOT SINGLE6 ACCEPTED (baseline only).
- `CUR-public-off` — ROOT SINGLE6 ACCEPTED (baseline only).
- `CUR-marker-core-off` — ROOT SINGLE6 ACCEPTED (baseline only).
- `CUR-template-distinct-grantee` — ROOT SINGLE6 ACCEPTED (baseline only).
- `CUR-template-owner-grantee` — ROOT SINGLE6 ACCEPTED (baseline only).

fresh_candidate (6):

- `FRESH-canonical-core` — ROOT отдельная серия ACCEPTED; не единая fresh6green.
- `FRESH-repeat` — ROOT отдельная серия ACCEPTED; не единая fresh6green.
- `FRESH-nonempty-refuse` — ROOT отдельная серия ACCEPTED; не единая fresh6green.
- `FRESH-artifact-rollback` — ROOT отдельная серия ACCEPTED; не единая fresh6green.
- `FRESH-missing-edge-extension` — ROOT отдельная серия ACCEPTED; не единая fresh6green.
- `FRESH-canonical-parent-contract` — ROOT отдельная серия ACCEPTED; не единая fresh6green.

upgrade_candidate (9):

- `UPG-unversioned-adopt` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-prefix1` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-prefix2` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-prefix3` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-pulse-created` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-pulse-adopted` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-head-repeat` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-calendar-cutover` — ROOT отдельная серия ACCEPTED; не единая UPG9green.
- `UPG-foreign-parent` — ROOT отдельная серия ACCEPTED; не единая UPG9green.

refusal_candidate (9):

- `REF-missing-core-public-decoy` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-visible-public` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-unknown-future` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-gap-checksum` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-source-drift` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-owner-actor-action` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-catalogue` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-default-acl` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.
- `REF-wrong-marker` — ROOT отдельнаясерия ACCEPTED;REF9independentreview ROOTaccepted scoped.

configuration_candidate (6):

- `CFG-off` — ROOT отдельная серия ACCEPTED; оба CFG SOURCE/artifact review ROOTaccepted scoped.
- `CFG-identity` — ROOT отдельная серия ACCEPTED; оба CFG SOURCE/artifact review ROOTaccepted scoped.
- `CFG-url-options` — ROOT отдельная серия ACCEPTED; оба CFG SOURCE/artifact review ROOTaccepted scoped.
- `CFG-no-port` — ROOT отдельная серия ACCEPTED; оба CFG SOURCE/artifact review ROOTaccepted scoped.
- `CFG-real-path` — ROOT отдельная серия ACCEPTED; оба CFG SOURCE/artifact review ROOTaccepted scoped.
- `CFG-source-before-lock` — ROOT отдельная серия ACCEPTED; оба CFG SOURCE/artifact review ROOTaccepted scoped.

borrowed_candidate (3):

- `TX-readwrite` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `TX-readonly` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `TX-owner-contention` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.

lifecycle_candidate (6):

- `LIFE-full-prepare` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `LIFE-rejected-no-seed` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `LIFE-marker-repeat` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `LIFE-no-jobs` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `LIFE-readiness` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.
- `LIFE-cleanup` — ROOT отдельная серия ACCEPTED в FactsOnly7; scoped, не единый прогон.

recovery_candidate (4):

- `REC-old-binaries` — NOT RUN.
- `REC-old-sender-calendar` — NOT RUN.
- `REC-synthetic-restore` — NOT RUN.
- `REC-crash-and-downgrade` — NOT RUN.

old_upgrade_candidate (8):

- `OLDUP-ce94-native-upgrade` — NOT RUN.
- `OLDUP-5ce-native-upgrade` — NOT RUN.
- `OLDUP-repeat-no-DDL` — NOT RUN.
- `OLDUP-wrong-parent-column` — NOT RUN.
- `OLDUP-wrong-parent-ACL` — NOT RUN.
- `OLDUP-one-partner-present` — NOT RUN.
- `OLDUP-managed-history-present` — NOT RUN.
- `OLDUP-wrong-profile-source` — NOT RUN.

## Named source files SHA256

| Path от clearledger/server | SHA256 / bytes |
|---|---|
| schema_migrations/runner.py | `cd9fc0940c4de8dfc9b3d47a974ad5a68a363921220130e70fc922f5563c740a` /26684 |
| app/database.py | `556154faef73b11ca6efbfbe581a098d32a159d8b7f3e8ae2f862e0853014628` /387732 |
| app/main.py | `ade769500fb9295dbc2784fe945fc111a7bf7981ea687363f1b271334d43f455` /46639 |
| app/services/schema_version_gate.py | `bea3c875a04b2aa0eb10103273571fb10b59a96234851996ab3b2ead8040a71e` /4474 |
| schema_migrations/bootstrap/core_prerequisites_v1.sql | `3dab85f4430b177168d111e7952ed79122eb802ed0988c5f1b24b14563190942` /9598 |
| schema_migrations/bootstrap/core_prerequisites_v1.contract.json | `5af1123d5bd784d21269062b7af9973a19711d06e6b0cb5ebb484b4b6ff200fa` /42540 |
| schema_migrations/bootstrap/core_prerequisites_v1.manifest.json | `c13b0bc5d5162fd38449f4b3541265a5eef78518be616cb93bd26f36bbb482b2` /379 |
| schema_migrations/bootstrap/core_prerequisites.py | `be58ba1ff9c6592e838f3103b266e3875fa9e6b6872ff9a1da093320dc2f2f62` /19700 |
| schema_migrations/bootstrap/core_partner_prerequisites_v1.contract.json | `1ee6337b7f97e4c874c7a582b8fb9e6475dfe0249467f4b345cbc99a94e206b4` /5804 |
| schema_migrations/bootstrap/core_partner_prerequisites_v1.manifest.json | `b9629be565781def7d486b7fd3813761041c980cc31bd9684e798b60b8c1e1a5` /506 |
| tests/core_bootstrap_sequence_approved.py | `ac396d27e68f1d7cd045223c59cc5049be7ba26c29d9f0121c35f9100f453cbb` /285477 |
| tests/core_bootstrap_sequence_cases.py | `35139334c57e2cc0939ce5eccd99ba0dbec0fd9dfa99765da404a392a94c8371` /81737 |

Full source manifest SHA256 `e9db605c0b34ad58a7361fce3d40c49638495f1989f5198c45a989db8cb16c40`; wrapper SHA256 `ac396d27e68f1d7cd045223c59cc5049be7ba26c29d9f0121c35f9100f453cbb`.
