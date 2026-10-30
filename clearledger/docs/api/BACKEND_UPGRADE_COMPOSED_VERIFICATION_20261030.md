# Совмещённая проверка backend upgrade, 30.10.2026

**SCOPED VERIFICATION COMPLETE: full376 —375PASS/1schemaFAIL; M18 —3сохранённыхPASS+5correctivePASS. Единого нового376GREEN или single8GREEN нет.**
Пакет замораживает согласованный source с принятым lifecycle fix и содержит
два ROOT-only entrypoint на candidate runtime77. ROOT выполнил full376, main8
и единственный affected5 retest; worker проверил retained receipts без исполнения.
Worker не импортировал/не исполнял app, pytest, ORM, SQL, entrypoint или драйвер,
не создавал env, не устанавливал пакеты и не обращался в сеть за зависимостями.

## Принятый состав

Exact source base: `330883aaf8e387e106e93d790806a182acbe526d`.
Новая ветка начата от `a1cc45f15809ce5c77e38067d82813ebccc10f59`, затем целиком
переведена на согласованный ROOT head без reset/force/merge commit и без WIP.
App, прежние testcases, schema и support inputs совпадают с этим ROOT snapshot.
Единственный runtime lifecycle fix принадлежит его владельцу, не этому worker:
принятый bound public default lifespan context вместо removed startup/shutdown.
ROOT подтвердил corrected matrix12PASS на old и12PASS на new runtime; исходные
fixture failures сохранены. Поздний ROOT lifecycle report — docs-only, source
base этого пакета остаётся330883aa.

В snapshot включены принятые M18 request-ID/Swagger/actual employee changes,
P2 task/site/binding boundaries и lifecycle module/focused12/gate. Полный source
freeze включает эти файлы; текущий full376 selector не расширяет execution до
всех repository tests. M00–M19 остаётся открыт; это не общий CI или выпуск.

[Прежний target report](BACKEND_UPGRADE_TARGET_20261030.md) и
[прежний regression report](BACKEND_UPGRADE_REGRESSION_PLAN_20261030.md) заморожены.
Все три прошлых actual attempts остаются прежними evidence: collection0calls,
interrupted partial с неизвестными accepted counts и diagnostic56collected/1FAIL
на missing PolicyRouter.startup. Их результаты не переименованы в новую проверку.

## Source approval без цикла между двумя entrypoints

[Full376 gate](../../server/tests/backend_upgrade_approved.py) и
[Main8 gate](../../server/tests/backend_upgrade_main_approved.py) перед первым
сторонним/app/ORM import требуют **оба** exact SHA через ROOT-approved args:
`--approved-sha256` (self) и `--approved-other-sha256` (второй entrypoint).
Из tests tree исключены строго эти два owned files, их bytes проверяются отдельно.
Остальные app/tests/schema files входят полностью; нет взаимного embedded SHA цикла.
Изменение любого другого file/count или одного из двух SHA останавливает gate.

| Полное дерево | Число файлов | SHA-256 |
|---|---:|---|
| app | 492 | `748c5eda4d956dc73771aa84462c6bc789d80cbdcddc0b86825e141f04a8c3c0` |
| tests | 345 | `08ae0ee2ed47661fe8d6d5dc89fab61641fbeccb49fa3cbf76e82a7b4dd5f0a9` |
| schema_migrations | 16 | `c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e` |

Full376 runner SHA-256: `b77fe80f9cdd3ab54cc60ec04469c26f1fde8d9bd8035b6fa7b5fd70e7f94f23`.

Main8 runner SHA-256: `4ea9370970cbe79182efca907791c01ad2ea47f63b8137f3ce2003644baf24cd`.

Support freeze содержит Dockerfile, .dockerignore, requirements.txt,
requirements-upgrade input, pytest.ini и **все** server/locks files. Их содержимое
не изменено. Per-file manifest и count/hash доказательства остаются private в
proposal. ROOT должен проверять именно этот состав, а не прежний cf209237 snapshot.

## Один runtime, две отдельные acceptance

Candidate — уже подготовленный ROOT env
`/srv/projects/api-modernization-upgrade-test-env-20261030/.venv`:
**CPython3.13.7 /glibc2.36, runtime60+pip1+testtools16=77**.
Exact distribution names/versions и preparation receipts закреплены в обоих gate.
Packaging26.3 остаётся runtime; дополнительных пакетов, installer/compiler/network
нет. Old env79 не используется и не выдаётся за новый runtime.

Прежний Docker resolver/offline install PASS относится к Python3.13.18/glibc2.41;
эти host regressions не доказывают приложение внутри Docker. ROOT lifecycle
focused12 old/new PASS — отдельное уже принятое evidence, здесь не повторяется.
Old M18 five baseline PASS и corrective three PASS были раздельными на old env;
новый main8 плюс affected5 проверяют тот же union на изменённых deps/source.
Старые old-env proofs не переименованы в новые; ниже точный объём новых запусков.

| ROOT-only profile | Объём | Exact disposable DB | Fresh execution root |
|---|---|---|---|
| full376 |376cases | `api_backend_upgrade_test_20261030` | backend-upgrade-functional-execution-20261030-attempt4 |
| main8 |8distinctcases | `api_partner_main_test_20261030` | backend-upgrade-composed-main8-execution-20261030-attempt1 |

Оба root расположены только под private `.artifacts` этого worktree. ROOT исполняет
их **последовательно** в своём SQL окне и сам создаёт/резервирует/удаляет БД.
Main DB уточнена отдельным решением ROOT: сохранена исходная техническая цель,
жёсткий guard unchanged testcase не менялся; новая `api_backend_upgrade_main_test`
не используется. Main8 и376 имеют разные DB и разные fresh dirs/evidence.
Существование старого каталога запрещает retry с его перезаписью.

## Exact full376 selection

Все selectors относительны clearledger/server, с сохранёнными assertions/counts.
Суммы получены из AST/parametrize, не pytest collect. Шесть дополнительных probes
внутри gate побайтно/AST те же: raw RS256 JWT, dotenv synthetic stream, actual
pypdf/app extraction и malformed PDF, multipart filenames/bytes/limits/errors.

| Selector | Cases |
|---|---:|
| `tests/backend_upgrade_approved.py` | 6 |
| `tests/test_api_contracts_context.py` | 34 |
| `tests/test_api_contracts_http.py` | 56 |
| `tests/test_auth.py` | 13 |
| `tests/test_contract_liability.py` | 1 |
| `tests/test_doc_text.py` | 9 |
| `tests/test_docs_portal.py` | 22 |
| `tests/test_docs_register.py` | 23 |
| `tests/test_partner_identity.py` | 67 |
| `tests/test_partner_product_integration.py` | 20 |
| `tests/test_partner_userinfo_wire.py` | 14 |
| `tests/test_product_api.py` | 57 |
| `tests/test_product_http_profile.py` | 12 |
| `tests/test_product_object_ids.py` | 27 |
| `tests/test_product_openapi_http_contract.py` | 8 |
| `tests/test_product_service_openapi.py` | 7 |

Итого376: ROOT завершил375PASS/1FAIL/0ERROR/0SKIP и149passed subtests.
XML содержит376testcase elements; suite tests525 включает149subtests.
Неудача — unchanged test_pure_schema_distinguishes_object_identity_from_other_ids. Прежние HTTP
expectations не исправлялись ради upgrade. Full376 работает со штатным conftest
на отдельной exact DB; он выполняет actual create_all/seed и свои схемные операции.
Full gate изменяет только source approval/profiles/counts/fresh target: прежние
owned-anchor ENOENT-only observer, atomic checkpoints/redaction, kill/reap,
network/process/env guards и шесть probes сохранены AST-идентичными auditedv4.

## Exact main8 selection и действительный app composition

Ниже eight existing cases из unchanged test_partner_main_composition.py, по одному
case, без parametrization или нового testcase expectation:

- `tests/test_partner_main_composition.py::test_main_problem_request_id_matches_outer_security_context`
- `tests/test_partner_main_composition.py::test_standalone_child_unavailable_problem_request_id_without_sql`
- `tests/test_partner_main_composition.py::test_main_mount_order_anonymous_docs_and_version_guards`
- `tests/test_partner_main_composition.py::test_ordinary_employee_scoped_entities_refresh_and_revoke`
- `tests/test_partner_main_composition.py::test_ordinary_employee_document_eligibility_denial_is_not_owner_consent`
- `tests/test_partner_main_composition.py::test_explicit_docs_role_employee_allowed_bytes_hidden_and_foreign_404`
- `tests/test_partner_main_composition.py::test_main_swagger_canonical_projection_assets_session_csrf_and_live_revoke`
- `tests/test_partner_main_composition.py::test_main_confidential_registration_admin_machine_grant_and_live_revoke`

Main8 gate сохраняет audited M18 pytest_configure/delivery setup/bootstrap seams:

- `--noconftest`, явный pytest config/plugin, без исходного общего conftest/seed.
  Settings(_env_file=None), проверка default feature flags OFF до synthetic
  process-only configuration; app/main импортируется после source/site/network
  guards и delivery captures, до fixtures.
- Patch только штатного startup prepare/seed seam `_prepare_database_once`;
  fixture отдельно вызывает **настоящий database.create_all** и настоящий
  `main.app.router.lifespan_context`. Production bootstrap/seed этим seam не доказан.
- Восемь run_forever заменены parked корутинами; должны стартовать ровно once,
  оставаться parked и все восемь cancelled при actual lifespan shutdown.
- Настоящие core login/gate, HTTP registration/consent/CodePKCE/token/JWKS/raw JWT
  verification/refresh/revoke, actual employees и explicit docs role, scoped
  two-company projections, native document bytes/foreign404, new request-ID,
  canonical/browser Swagger responses и CSRF. Auth/verifier/current_user/handlers
  не подменяются, готовые успешные токены не фабрикуются.
- Source даёт **8login**, standalone case добавляет0: expected capture
  notify.dispatch_async8. Prepare1, chat_ws.start1/stop1, каждый scheduler1;
  любая другая delivery capture означает FAIL. ROOT independently подтвердил count8.
- Существующий independent read-only PG oracle сравнивает все business rows,
  явный auth-table inventory и file fingerprints по baseline/каждой phase/final.
  Новые seeded fixture rows допустимы только до baseline; бизнес-данные и bytes
  после baseline должны совпасть. Тестовый oracle/допустимые auth tables не изменялись.

Полные app/test/schema hashes покрывают M18 helpers/fixture/oracle целиком.
Main8 gate копирует сохранённые audited M18 методы setup, captures и unconfigure;
только selection8, exact77/source/own SHA и private evidence wrapper относятся к
новой проверке. Parent независимо проверяет main8_accepted, jobs/counters/counts,
JUnit8/no errors/skips и exact source. После child reap формируется bounded
retained-evidence manifest со SHA/size всех main evidence files, включая fingerprints.

## Сохранённые границы

До imports: exact new interpreter3.13.7, flags `-I -S -B`, no system/user site,
no `.pth`/customize/symlinks, metadata exact77, own/other/source/support SHA,
чистый фиксированный environment и **реальный HOME** без подмены. Main8 дополнительно
сохраняет old M18 no-O check, owned0700/distinct test dirs/no ancestor symlinks и
запрет чтения .env/.env.* и credential directories. App не получает настоящие env.

Socket/DNS guards принимают только numeric127.0.0.1:33546 PostgreSQL; asyncpg
проверяет exact database/user и отсутствие target overrides. Bind/listen/datagrams,
внешние HTTP/process attempts и secret env reads запрещены. SMTP/email/chat/WS/
push/Jitsi captures установлены до fixtures; main8 сохраняет строгий audit delivery
inventory. Выбранные tests могут контролировать только свои существующие seams.

Подтверждённая urllib3 import IPv6 bind probe подавлена **только** временным
socket.has_ipv6=False вокруг ровно пяти initial imports aiohttp/aiosmtplib/httpx/
pywebpush/requests; exact original восстанавливается в finally до app/fixtures.
Нет bind allowance/counter discount; actual прежняя диагностика после suppression
дала forbidden0. IPv6/external transport этим ASGI прогоном не валидируются.

| Bound | full376 | main8 |
|---|---:|---:|
| Supervisor wall deadline |900s |540s, плюс исходный M18 SIGALRM540 |
| CPU /AS /FD |600s /2GiB /256 |600s /2GiB /256 |
| Aggregate stdout log /individual child file |2MiB /2MiB |2MiB /2MiB |
| Scratch |64MiB /4096entries |64MiB /4096entries |
| Proof JSON /failure trace |2MiB /16KiB per+1MiB total |тот же bound |
| Database size |256MiB pre/post |256MiB pre/post, existing oracle≤700tables |

Observer проверяет exact owned anchor(dev/ino/uid), no-follow/lstat и bytes/count;
только точный child ENOENT исчезнувшего live scratch entry допускается. Root missing/
drift, permissions и иные errors не игнорируются. Atomic outcomes после каждого
report phase сохраняют partialFalse; redaction не выводит JWT/URL credentials/locals.
На failure/timeout — process group kill/reap и bounded evidence, без automatic
rerun/version change. Три fresh private directories на профиль; старые attempts
не используются повторно и не удаляются worker.

## ROOT execution и acceptance

Оба entrypoint требуют отдельный ROOT review frozen commit/bytes/proposal до
app/pytest/SQL. После review ROOT запускает full376, принимает его самостоятельный
outcome/normal DROP, затем main8 на отдельной свежей DB. Формат argv/env и exact
пары SHA находится в private immutable proposal; этот документ не разрешает worker
исполнение. Никакого нового install/compiler или network preparation не требуется.

PASS376 требует exactly376 collected+passed, JUnit376/no failures/errors/skips,
pytest exit0, source hashes unchanged, forbidden network/process/env counters0,
capability restore и HOME preserved, checkpoint/boundary/supervisor receipts.
PASSmain8 требует отдельно exactly8 collected+passed, JUnit8, реальный main/lifespan,
expected lifecycle/delivery counts, cancelled8jobs, unchanged business/files,
forbidden0 и отдельные complete receipts. Один PASS не заменяет другой.

Normal DROP выполняет ROOT только по своему retained creation proof, fresh size/
relations/connections и без FORCE/GUC. Прежние M18 normalDROP344relations receipts
остаются историческими; новый actual relation count/normalDROP ещё не получен и
не выводится из старого доказательства. SQL cleanup worker не выполняет.

Actual warnings, FAIL/SKIP, несовпадения pins/source/counts сохраняются; assertions
и public API не меняются ради gate. Активация requirements, production flags,
CI/fullrepository certification, Docker app proof, browser/nginx/SSO, release,
merge/deploy отсутствуют. После actual evidence здесь выполнена только report-only
finalization; M00–M19 не закрывается этим пакетом.


## Фактические ROOT результаты на source330883aa /new77

| Запуск | Exact scope | Результат | Время pytest /ROOT outer |
|---|---|---|---|
| Full376 attempt4 |376collected,16selectedfiles,6original probes |375PASS/1FAIL/0ERROR/0SKIP,149subtestsPASS |200.62s /217.6631768811494s |
| Main8 attempt1 |8distinct existing cases |3PASS/5guardFAIL; не app defect verdict |45.94s /62.046643800102174s |
| Corrective main affected5 attempt2 |exact5::nodeids,3PASSнеповторялись |5PASS/0FAIL/ERROR/SKIP |69.72s /86.57828894723207s |

Supervisor full376216.80523755121976s, affected5 child85.83150733355433s;
все owned children завершены/reaped. Ни worker, ни gate не меняли dependencies,
app или testcase expectations для получения PASS. Данные/manifest fingerprints
проверяются внутри каждого synthetic baseline; разные attempts не приравниваются
по UUID/содержимому разных новых fixture datasets.

Единственный full376 failure:
`tests/test_product_object_ids.py::test_pure_schema_distinguishes_object_identity_from_other_ids`.
FastAPI0.133 inlines objectId path schema с прежними type/min1/max40/NULpattern,
а assertion требует `$ref` на ObjectId; model refs/Monitoring не изменились.
Root noSQL diagnostic установил эту compatibility причину, старый assertion не
ослаблялся. Отдельный publisher fix принят ROOT после14old/14new tests и включён
в его более позднюю integration, но **не включён в наш замороженный source330**.
Здесь остаётся actual375/1 этого snapshot; это не376GREEN позднего HEAD.

Main8 first attempt:5failures вызваны audit socket.sendmsg в Python3.13
asyncio.selector_events._write_sendmsg/writelines →asyncpg.executemany →bulk
installation_locations INSERT. Первый gate строже старого M18 запрещал sendmsg
целиком; это guard defect, не установленная ошибка бизнес-логики. ROOT штатно
удалил own DB после344relations/0connections, затем открыл NEWmain-only correction.

Сохранённые3PASS — main trusted request-ID, standalone child/noSQL request-ID и
main mount/anonymous/version guards. Они не запускались повторно. Affected5 —
ordinary employee scopes/refresh/revoke, explicit eligibility denial, docs-role
bytes/foreign404, Swagger/canonical/browser/CSRF и confidential machine grant/revoke.
Их unchanged fixture login counts2+2+2+1+1 дают expectednotify8;8parked jobs остаются.

## Узкое transport исправление только NEWmain

Buffer-only sendmsg разрешён лишь ранее учтённому exact PG socket:
AF_INET, native SO_TYPE=SOCK_STREAM, TCP/defaultTCP, connected peer127.0.0.1:33546,
weak object identity и тот же nonnegative nativefd от approved connect audit.
Closed/detached/reused/unowned socket не проходит. Wrapper не принимает никаких
extra args/kwargs, включая explicit empty ancillary, flags0 или addressNone, и
вызывает native sendmsg только с buffers без чтения/записи/логирования payload.

Native audit разрешает это только в privateContextVar scope и exact wrapper
code frame, повторяя peer/type/protocol/fd/weak-ownership checks; direct native
bypass запрещён. Bind/listen, UDP/Unix/IPv6/raw/otherpeer, ancillary/flags/address
не получили exemptions. Остальные source/site/HOME/privacy/strictzero/limits
остались прежними. Full376 runner/probes не менялись.

ROOT исполнил16pure metadata controls: один positive и15negative (unowned,closed,
fdreuse,wrongpeer/unconnected,dgram,Unix,IPv6,raw,protocol,ancillary/flags/address
в positional/keyword формах). Это проверки predicate metadata без socket probes;
worker их не исполнял. В actual affected5 согласованный PG sendmsg использован5раз,
PGconnect3; forbiddennetwork/process/env0, audit[]. ВсеglobalSMTP/pushcaptures0,
notify8, prepare/start/stop1, восемь jobs started/cancelled. Exact inventory77,
реальный HOME, noenv/nosite и capability suppressed/restored подтверждены receipts.
`affected5_accepted=True`, **`main8_accepted=False`**: частичный retest не выдаётся
за single full8 run. По case coverage сохранённые3+corrective5 покрывают8разныхcases.

## Пары gates и сохранённые scopes

| Actual run | Full gate SHA-256 | Main gate SHA-256 |
|---|---|---|
| Full376 |`b77fe80f9cdd3ab54cc60ec04469c26f1fde8d9bd8035b6fa7b5fd70e7f94f23`|`717811dcabb14c04024422306765bb99f51298c2e17399c72bba298d097366b7`|
| Main8 first attempt |`b77fe80f9cdd3ab54cc60ec04469c26f1fde8d9bd8035b6fa7b5fd70e7f94f23`|`7b6b2efdf60f8294fd13f77150034c24c02bd5235c46d87a74af955019c8e7d9`|
| Corrective affected5 |`b77fe80f9cdd3ab54cc60ec04469c26f1fde8d9bd8035b6fa7b5fd70e7f94f23`|`4ea9370970cbe79182efca907791c01ad2ea47f63b8137f3ce2003644baf24cd`|

Не-runner app/tests/schema/support bytes и runtime одинаковы на всех этих runs.
Main gate менялся только между ROOTreap+normalDROP и следующимreview; SourceGuard
не обманывался редактированием взаимно hashed file во время активного child.
Full376375PASS не повторялись из-за изменения guard/profile. Frozen proposals и
неудачные attempts сохранены полностью, включая прежние v1–v4 прошлого пакета.

ROOT independently сверил все58items affected5 retained manifest по SHA/bytes,
затем42phase snapshots пяти baseline cases: business/files равныbaseline,
authchanged совпадаетrecorded, withinallowed и includesrequired, final==lastphase.
Worker дополнительно read-only сверил58file SHA/size, log/JUnit/boundary receipts,
exact5outcomes и controls/counters. Это receipt audit, без SQL/retest.

| Actual evidence | SHA-256 |
|---|---|
|ROOT full376 summary|`0ea930ed87e1db496b1dd5167516de63755bb0d80fe901ec254f69329b1cc4c3`|
|ROOT affected5 summary|`45968937e8ba8f1769360ad02d524e62c53f83f7983318d9238cd310ea894347`|
|full376 boundary_sha256|`8eff3c810e439c1495c897853733d0fb1e1e0224528a478f4f18b53ea751c351`|
|full376 supervisor_sha256|`b3f5ba0e397785e01e9628adcb9c505ee3f62b64d45e1460ae59fe292980f8c0`|
|full376 junit_sha256|`50ac3252a3479db73541fe79e9860ce61619cc3af0dceb895fafe99eec7e6250`|
|full376 log_sha256|`f0e3961f8548024290801373d1c5b78ac23f7cd58b8e4f562379448934b177e4`|
|full376 checkpoint_sha256|`c4af0bcb0f6d7e18e134fd9960f6971086c142c2763044f8d04c68c3c49e6003`|
|main8_attempt1 boundary_sha256|`b618dbc645b34597d238ebcf16f3549664feae4e11dd05d2a17963e13c87e012`|
|main8_attempt1 supervisor_sha256|`3d711d57908fc65993c8155b3c4629c2d894a6bd4db0e486cb9003bc89472bbb`|
|main8_attempt1 junit_sha256|`ebac7818eaf655e1595ff7a9e37085816ab4f60ad2877f83f5986a8aadc7422e`|
|main8_attempt1 log_sha256|`c195f9ee810c1ea5f61e0f7b5bb7de6432309e41210dea6cea5232d039240cfd`|
|main8_attempt1 checkpoint_sha256|`df04b06a7b5178a414ad7b7900a8a02b9f90cf50e942d40fd137ea08c0531148`|
|affected5 boundary_sha256|`04d4cc769659d02c1a9d6d8a0ebc4ba9d94447809b98d51aa8ae3b25c9c60739`|
|affected5 supervisor_sha256|`1f7b0f3c8c3ada93f0b0d291170b8eb4d21354ec590b2ba9dbf7d8eb49b045a6`|
|affected5 junit_sha256|`8cab0b53a2bff97e64c8c5e5bd62a74c1affb3df9c0c9372e48c59e2cd1dbb88`|
|affected5 log_sha256|`2b537a3eb748e7f0ff875497b8f7a3834337fd281422b66e615b4ba589c591e3`|
|affected5 checkpoint_sha256|`20c1db675a6a984e4a4811bc7b3523129e9940afb3064ce81a8ab13779ade9ec`|
|affected5 manifest|`0cef5e1b17f8e46a9de591937f7405b79c3ffda99daca2887482e5976887ef47`|

Full376 warnings сохранены: deprecated Starlette httpx TestClient path,
anyio BlockingPortal alias и InsecureKeyLengthWarning на **преднамеренном22byte
HMAC fixture** token-confusion testcase. Они не означают смену production key и
не исправлялись изменением versions/assertions. Affected5 log:5passed69.72s.

ROOT normalDROP proofs: full376 freshrelations0/connections0/exists0/maxlocks64;
main8 first attempt и corrective affected5 —344relations/connections0/exists0,
maxlocks64. Retained own creation/size/read-only checks, без FORCE/globalGUC;
worker SQL/cleanup не выполнял. ВсеDBtargets и свежиеevidenceкаталоги различены.

Подготовка и scoped verification этого пакета завершены. ProgrammeM00–M19 открыт;
нет заявления о single376GREEN/single8GREEN, полномCI, production/security
certification или Docker3.13.18 app proof. Новые installer/compiler/network,
requirements activation, sourcefeatureflags, merge/deploy не выполнялись.
Последняя правка — report-only; оба runner/app/tests после bff0ac14 заморожены.
