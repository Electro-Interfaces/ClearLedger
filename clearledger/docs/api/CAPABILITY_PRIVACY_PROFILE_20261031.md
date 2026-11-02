# Capability URL: Core logger и поставляемый frontend nginx

**Реализован source-кандидат для 12 семейств: 6 API и 6 UI.** Core logger маскирует capability suffix и private query/fragment в известных HTTP/WS/referrer форматах. Inline nginx поставляемого `clearledger/deploy/frontend.Dockerfile` классифицирует normalized URI до SPA rewrite, сохраняет map result и использует raw request fallback для parse400. Public fallback `/p/public.html` теряет query в журнале и получает no-referrer до React. **ROOT scoped acceptance: offline460PASS и отдельный clean combined nginx231+old9PASS. Worker runtime0.**

База `7e82e158827f585529f7f1a163a5c390a037d054`, ветка `agent/api-capability-privacy-profile-20261031`. Worker выполняет только Git/read/stdlib AST/hash/compile; app/test/runner imports, pytest collection/tests, SQL, HTTP/nginx/Docker/Node/build/install/servers/jobs/SSH/live — **0**. Исторические ignored proofs, CP02/CP03, contract source V1/V2 и другие owners сохранены. Общая цель20M+11 активна.

## Scope и согласованное изменение одного golden

Изначальные6 файлов расширены ROOT reply **`msg_7717a23e12f8`** ровно на `server/tests/test_protocol_privacy.py`, всего7:

- `server/app/api_access_logging.py`: только logging classification; filter/sink/install section побайтно прежний;
- `deploy/frontend.Dockerfile`: только inline logging/referrer/warmup;
- `server/tests/test_protocol_privacy.py`: один intentional expected branch;
- новые `server/tests/test_capability_privacy_profile.py`, `capability_privacy_profile_approved.py` и эти MD/JSON.

Old dot-prefix case требовал сохранять `/api/./invite/SYNTHETIC_CAPABILITY_20261031` в логе; это конфликтовало с новым alias privacy requirement. ROOT выбрал защиту, **не production-исключение для одного literal**. Сохраняются146 прежних case IDs/inputs/param IDs, **145 ожиданий прежние +1 intentional updated** на `[redacted-capability-target]`. Ни xfail/skip/deselect/delete, ни production SYNTHETIC special case нет. Whole-file reverse source proof подставляет только прежнее тело этой функции и получает exact base bytes; decorators неизменны. Old146PASS остаётся историей состава e9f3b056/c1825c51, а не новым утверждением «146 assertions byteexact». Current146 входят в принятую460серию с145прежними+1согласованным ожиданием.

Старые `test_api_access_logging.py`, `protocol_privacy_approved.py` и `services/export_files.py` byte-exact. Старый approved helper имеет старый full-app pin и не переписывается/не исполняется под новым app. Новая обёртка замораживает нынешний полный состав. Native wire4/XLSX SQL7 не выбираются.

## Два logging профиля одной classification

| Семейство | App canonical example | Nginx fixed target |
|---|---|---|
| /api/doc-share/ | /api/doc-share/[redacted]/ack; verify/file/version suffix прежний | /api/doc-share/[redacted] |
| /api/invite/ | /api/invite/[redacted]/ics; прежние respond/poll/vote | /api/invite/[redacted] |
| /api/work/calendar/feed/ | /api/work/calendar/feed/[redacted].ics | /api/work/calendar/feed/[redacted] |
| /api/auth/reset-password/ | prefix+[redacted] | /api/auth/reset-password/[redacted] |
| /api/invitations/accept/ | prefix+[redacted] | /api/invitations/accept/[redacted] |
| /api/showcase/ | prefix+[redacted] | /api/showcase/[redacted] |
| /doc-share/ | prefix+[redacted] | /doc-share/[redacted] |
| /doc-verify/ | prefix+[redacted] | /doc-verify/[redacted] |
| /meeting/ | prefix+[redacted] | /meeting/[redacted] |
| /invite/ | prefix+[redacted] | /invite/[redacted] |
| /reset-password/ | prefix+[redacted] | /reset-password/[redacted] |
| /showcase/ | prefix+[redacted] | /showcase/[redacted] |

Это logging-only policy. API method/path/body/auth/tenant/ACL/expiry/revoke не меняются. Например, POST `/api/auth/reset-password` передаёт token в body: это обычный target без path capability, body не превращён в URI. Source routes/UI anchors и hashes закреплены полным manifest; URLprefix не объявлен проверкой ACL.

App сохраняет canonical outputs первых3API и прежние query/WS правила. Новые9семейств скрывают whole opaque suffix. HTTP(S) absolute referrer canonical сохраняет безопасный origin; opaque percent/quotes/Unicode не нормализуются для вывода. Raw malformed/control/неоднозначный known target даёт fixed marker. Нестрочные значения возвращаются тем же объектом, обычные query/непохожие paths/unsupported error formats сохраняются.

`_capability_alias` читает только structural prefix до первой известной family boundary: slash/dot/single percent ASCII и прежний ClearLedger alias. Он останавливается **до opaque suffix**; decoded token не создаётся/не логируется, реальный URI не меняется. Для alias возвращается fixed marker, не normalized URL. Dot/parent/double-slash/encoded-dot/slash/absolute формы охвачены literal fixtures; identity parsing/универсальный URL framework не добавлен. V2 ограничивает join не только≤4segments, но и O(1) проверкой len каждого сегмента≤14 (максимум literal частей12prefixes). Длинные обычные сегменты сохраняются в stack: поздний .. может их удалить и открыть family; early returnFalse не добавлен. Поэтому повторные /x/../ после трёх больших частей не копируют эти части на каждом шаге. Case-distinct `/API/invite/` остаётся прежним ordinary app target; nginx profile консервативнее и case-insensitive.

Literal feed без token и literal feed/rotate не являются capabilities; их query сохраняется до прежнего auth-query filtering. Encoded rotate ambiguity может консервативно скрыться. Старые branch bodies doc-share/invite/feed и generic query fallback совпадают AST. Секция `OAuthAccessFilter` и install побайтно прежняя: SafeAtoms copy/missing/custom escaping, U+r+q/f/custom referer propagation и auth/cookie redaction не изменены. Known Uvicorn5tuple и3WSformats сохраняют logger/arity boundary.

## Inline nginx до React и rewrite

Прочитан **read-only** Deploy V3:
`/home/mag/orca/workspaces/ecosystem-deploy/api-ingress-capability-privacy-20261031`.
Router SHA `46e63869d64ed93de3075cc983616591bb99de8a418e0a2cbaf3874b161b43bd`, checker SHA `384d780640f137c37c414ad05cb6e97283bece91ad7bbcd85d136cf58c88c635`. Его12markers/231literal expectations сохранены без изменения в парном JSON. Это другой owner, его файлы не редактировались.

Frontend raw12map bodies совпадают с Deploy V3 после замены namespace stack_→frontend_. Normalized `$uri` map читает family до любых try_files/internal rewrites. Первый server directive `set $frontend_privacy_warmup $frontend_capability_path` только вычисляет logging variable. Map **без volatile** сохраняет value; header/log позже используют cached classification, а не lazy `/index.html`. Для malformed до rewrite raw `$request` fallback маскирует single encoded structural prefix, не token.

Map lazy/default caching описана в [официальной документации nginx map](https://nginx.org/en/docs/http/ngx_http_map_module.html); server rewrite phase — в [rewrite module](https://nginx.org/en/docs/http/ngx_http_rewrite_module.html). ROOT проверил эти документы; **фактическая сохранность map после rewrite требует ROOT actual**, source proof её не заменяет. Worker новых HTTP-запросов не выполнял.

Router `@public` сохраняет args при rewrite в `/p/public.html`. Поэтому frontend имеет отдельный **точный** `/p/public.html` (также ClearLedger alias) logging profile: target без любых query, no-referrer до React. Без него path token уже исчез, но private_note/fragment-like query мог бы утечь во втором nginx. Direct/cookie-on known UI сохраняют fixed family marker; cookie-off fallback — `/p/public.html` без query.

Server no-referrer variable имеет пустой ordinary default, чтобы не менять прежний header обычного frontend. В6cache-bearing locations добавлен такой же Referrer-Policy, иначе их `add_header Cache-Control` отменяет наследование server header. Callback location с прежним explicit no-referrer/access_log off/no-store не менялся. CacheControl/assets/mime/gzip/status/try_files/alias/ARG/CMD/build stages/tail Dockerfile reverse-byte-exact после удаления только согласованных privacy additions. Реальный URI/redirect301/route/gate не переписан. Ordinary query диагностически остаётся видим, общего access_log off нет.

## Независимые offline cases: 314 новых +146 текущих

| Новая группа | Cases |
|---|---:|
| 12families × plain/HTTPS/opaque/Unicode literal outputs | 48 |
| 12families ×10structural alias spellings | 120 |
| Known malformed/quoted/control/scheme/userinfo wrappers | 60 |
| Ordinary/near-miss/static feed/body command preservation | 19 |
| Nonstring identity | 4 |
| Реальные LogRecord для12families × HTTP/Gunicorn/SafeAtoms/WS | 48 |
| Absolute alias referrers и Gunicorn request line | 12 |
| Installation idempotence/state cleanup | 1 |
| Long ordinary prefixes и поздний parent после длинного сегмента | 2 |
| **Новых** | **314** |

Expected targets — фиксированные literals, не SUT/regex-generated result. LogRecord действительно форматируется через StreamHandler/Formatter; проверяются U/r/q/f/custom referer, SafeAtoms type/copy/missing/escaping, известные WS formats, logger state. Новые tests не делают app requests, Settings, SQL, файловые операции или delivery. Старые XLSX2 используют настоящий in-memory openpyxl и private/no-store helper; helper не менялся.

Новый ROOT-only helper выбирает **460 exact full IDs**:314new+146legacy, **1380 primary phases** без skip/xfail/error/subtest. В146 входит8 прежних boundary negatives, они остаются8controlled denials, не successes неизвестных операций. 145unchanged+1intentionalupdated явно отражены в evidence. Полный selection/group counts/параметризованные IDs есть в JSON/`.artifacts/capability-privacy-profile-20261031/selection.json`; Исходный AST-подсчёт сам не был collection/PASS; ROOT затем фактически принял ровно этот460набор. V2 добавляет ровно2long-path regressions, всего9новых групп.

Guard `tree_digest/private_empty/inventory/scratch_bound` совпадает AST с принятым old helper; весь `OfflineBoundary`, включая8controls и five-library IPv6 suppression/restore, тоже exact AST. Никакого ослабления old helper pins. SQL запрещён полностью, PGmetadata16 не исполняется/не объявляется PASS. Secrets/env/process/socket/write/import guards действуют до third-party/app imports. Таймер — только просмотренный180s source alarm, не application jobs.

## Frozen source и приёмка ROOT

Worker source proof: `.artifacts/capability-privacy-profile-20261031/source-proof.json`.
Full inventories: app504 (включая mail_secrets.py), tests394 без нового self runner/395total, schema24. Остальные503app/392старыхtest/24schema blobs равны exact Git base. Никаких исключений по secret-name. Остальные source outside7files не менялись. Python выполнял AST/compile в памяти только source; runner/SUT не исполнялись.

План offline argv, cwd — ROOT-created empty0700:

```text
/srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/capability_privacy_profile_approved.py --execute-approved-capability-privacy-profile-tests
```

Точный14-key proposed env — JSON: actual HOME=/home/mag, PATH=/usr/bin:/bin, LANG=C.UTF-8, bytecode/plugin-autoload controls, ROOT_APPROVED_CAPABILITY_PRIVACY_PROFILE_TESTS/RUN_CAPABILITY_PRIVACY_PROFILE_TESTS/RUN_PROTOCOL_PRIVACY_TESTS=1, runner SHA, CAPABILITY_PRIVACY_EMPTY_CWD/SCRATCH_DIR/EVIDENCE_DIR, UPLOAD_DIR и TMPDIR=scratch. LC_ALL допускается, но в proposed env отсутствует. Нет DBURL/Settings/.env/keys. ROOT проверяет candidate77Python3.13.7/glibc2.36/exact77versions/no.pth/no sitecustomize fresh; ожидаемые pins не выдаются за установленный runtime worker.

Четыре separate private owned0700 roots вне app/tests/schema: `.artifacts/root-capability-privacy-test-20261031-v1-{cwd,scratch,upload,evidence}`. Они создаются ROOT, не worker. Full app/tests/schema/support/dependency4sources/frontend/self SHA проверяются до imports и после tests. Old approved wrapper остаётся frozen историческим файлом внутри полного manifest.

Parent caps: CPU180s/wall240s/AS2GiB/FD128/FSIZE2MiB, scratch64MiB4096entries, evidence1MiB/capture4000. **Free disk8GiB +80MiB planning**, не RAM floor; SQL/PG/WAL budget отсутствует. No network/process/servers/wire/SQL. ROOT reap/join child и сохраняет evidence; cleanup только своих private roots, чужие ignored receipts не удаляются.

Отдельная combined nginx приёмка ROOT после обеих source freezes: DeployV3 checker231literal cases +9unchangedOAuthassertgroups, cached image `sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3`, private empty Docker config, unix socket/local internal network,3disposable containers,96MiB planning и8GiBdiskfloor, normal own cleanup. No build/npm/browser/SQL. Full argv/source pins/case IDs в JSON; ROOT заменит approved artifact target до admission, редиректы301 не follow, POST body literal не URI.

## История доказательств и пределы

ROOT baseline25requests:19router/12frontend token observations,9oldOAuthgroupsPASS, sourceAfter/normal cleanup3containers+network, child reaped (6517 — tool session, не PID authority). Immutable baseline SHA `e1dbfc16a024f37f51ebeba74f311d87814f4160337b45180676fb5a9279842b`. Это доказательство прежней утечки, не защиты кандидата.

ROOT V2router+**старый frontend**:75observations,149failure entries/46failedIDs, old9OAuthgroupsPASS; router private hits0/coordinatefailures0, frontendFAIL ожидаемо плюс отдельно E02fixture body/hop ошибка. Duration5.528957330s, toolSession85363/childreaped/normalcleanup (PID здесь неизвестен); V3 исправил только согласованную E02fixture, raw receipts не менялись. Это историческая V2router+oldfrontend серия, combined PASS на ней не было; clean repeat с новым frontend принят отдельно ниже.

Source-preparation history: первый private reverse-AST lookup ошибся на quote style ast.unparse и остановился StopIteration до app execution; исправлен AST-expression comparison. До V1 freeze emission rows исправлены с first3 на all12families, дублированный alias input заменён отдельной combined-dot-parent формой, названия env roots закреплены в private generator. Это source-authoring corrections, не runtime tests/failures; provenance сохранён в JSON.

Откат — вернуть только logger/inline privacy changes и согласованный expected branch в их исторические bytes; не трогать handlers/cache/ACL/старый wrapper/другие owners. ROOT разрешил final facts-only update двух reports; production/helper/tests остаются exact V2. Далее named7filecommit/push; нет merge/deploy/flags/ship/tracker/email.

Остаются globalM09/fullCI/liveHAProxy/TLS/другие stacks, arbitrary debug/custom/error logs и unknown physical ingress, WSexpiry/sessionrenew/revoke и вся20M+11. Contract user+service write после bootstrap handoff/global lockorder/scalable receipt SQL обязателен отдельно; его code не начат. Кандидат не является broad leak-free certificate.

## V2 source correction: bounded segment lengths

ROOT `msg_92c3ad9c06c8` не принял V1 claim linear: join четырёх **очень длинных** segments при повторе /x/../ давал квадратичное копирование. V1 exact7files/freezes/proofs/312+146=458NOTRUN сохранены в `.artifacts/capability-privacy-profile-20261031/history-v1/`; freeze SHA `bf8b27cb4b2b0b89af7bfa4712fed77225a6b227353ab6ce1f89dbc7a09a3db2`. Новая source correction касается только helper bound/new2literal cases/new wrapper pins/reports. Frontend `34ff35e2...` и oldtest `7b68e973...` неизменны.

Два новых expected fixtures независимы от SUT: три ordinary4096-character части +256повторов/x/.. сохраняют исходный target;16384-character первая часть затем/../api/invite/синтетическийtoken даёт fixed marker. Expected source literals, без performance sleep/timer oracle и без исполнения worker. V2count314+146=460, primary phases1380, на freeze все NOTRUN; фактический ROOT результат приведён ниже. В private source proof первоначально сработал stale458-invariant после добавления2cases; исправлен на460, это source-проверка, не application/test failure.

Counterpart metadata65b5867 по ROOT исправляет toolSession/PID provenance, nginx/checker/231cases прежние. JSON хранит V1manifest hash и актуальный V2metadata pin отдельно от authority процесса; фактические4SHA/cleanup даст ROOT. V2 app/helpersource freeze и отдельно уже frozen frontend не требуют изменения маршрутов или бизнес-данных.

## Фактические ROOT receipts и финальная граница

ROOT `msg_b8c66f64e1ad` независимо принял sourceV2:7SHA, app504/tests394+runner/schema24,921original source blobs с ровно2изменёнными (logger/intentional oldtest), reverseAST/filter/install/canonical/fallback,4guards+wholeBoundary, fresh77. Исполняемые5файлов после freeze не менялись; обновлены только эти2reports. Exact V2reports/freeze/proofs сохранены history-v2 без переписывания V1.

| Серия | Actual | Время | Process provenance |
|---|---|---|---|
| Offline app | **460PASS**,314new+146currentlegacy;145unchanged+1intentional;1380primary phases/33groups | pytest2.07s, outer3.429502323s | OSPID1598189, toolSession53848, exit0/reaped |
| Combined nginx clean repeat | **231cases+9oldOAuthgroups PASS** |6.045731852s | OSPID1577116, toolSession5292, exit0/reaped; all29CLIreaped |

Offline: independent JUnit460, no fail/error/skip;8expectedcontrolled denials/0uncontrolled, sourceAfter=true,77inventorysame, IPv6restored, domain/SQL imports0, offline network/server/wire0. Boundary evidence SHA `885ed36c38ec425817c9200ed0d4cbdd3cf2666951cbd249d30daf6c47c1031c`, runner `bcbd2c437104388cbc578855b272d7c95bf3b9e46d544539bc895ece097dc614`, accepted freeze `49d695829079acca486a92421ff897291b058ed479c7ee2ab0398f750a647256`. Native wire4/XLSX SQL7 не выполнялись.

Nginx clean repeat проверил routing/headers/logs/gate на cached72ba65eb во всех3containers, sourceAfter=true, normal cleanup3containers+internalnetwork и независимое absence подтверждение, все29CLI reap. Minimum observed active free8748896256bytes при floor8589934592bytes; cleanup независимо от diskfloor. Frontend34ff35e2/router46e63869/checker384d7806 не менялись. Observations SHA `fab05d63df17dc838d6901b7f9e342cc10136cc0da09a6c38e3fe54a0cf5eccc`; ROOT receipt внутренний acceptanceSHA `075d95dd417a3b64ef2e4e43efa232a5c24fd6713794434ef57c7d7bdc9798e4` не выдаётся за SHA самого combined-acceptance.json. Полные file hashes обоих receipts записаны в парном JSON.

**Предыдущий combined231 не переименован в зелёный запуск.** Его функциональные231+9 прошли, но ROOT parent overstrict disk-floor guard прервал cleanup (OSPID1558897/toolSession56027); остались stopped backend+network. ROOT восстановил normal cleanup и независимо проверил отсутствие ресурсов, сохранил failed-attempt evidence. Затем исправил только phase-aware parent: active floor8GiB остаётся, cleanup разрешён и ниже floor, и выполнил отдельный clean full231repeat выше. Это дефект parent admission/cleanup, не изменение candidate logger/nginx/helper/test.

Private ROOT receipts прочитаны полностью: `.artifacts/root-capability-privacy-profile-review-20261031/acceptance.json` и `.artifacts/root-ingress-privacy-candidate-review-20261031/combined-acceptance.json` в ROOT integration tree. Они подтверждают scoped code/tests/синтетический ingress, не liveTLS/HAProxy/SQL/appACL/WSwire/fullCI/fullM09. Working stacks, rollout/flags и broad debug/custom logging не принимались. Интеграция/следующая authority/release принадлежат ROOT.
