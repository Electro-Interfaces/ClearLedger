# План регрессии обновления backend, 30.10.2026

Статус: **пакет подготовки завершён; ROOT diagnostic FAIL подтверждён;
full376 не принят**. На новом runtime обнаружен lifecycle compatibility defect:
`PolicyRouter.startup` отсутствует, а `create_policy_app` вызывает его при startup.
Исправление приложения передано отдельному владельцу; этот пакет его не меняет.
Подготовлен отдельный [runner](../../server/tests/backend_upgrade_approved.py).
Worker не импортировал runner/app/pytest, не выполнял collect/SQL/venv/install,
не менял прежние testcase expectations, приложение или активные зависимости.
Проверка подготовки ограничена чтением исходников/metadata, AST и compile в памяти.


Фактические ROOT attempts различаются по объёму:

| Attempt | Собрано / исполнено | Принятый результат |
|---|---|---|
| v2 / attempt1 | 327 cases +2 module-level SKIP;0test calls | Collection gate FAIL; missing opt-ins исправлены только в runner |
| v3 / attempt2 | Частичный full376, точные outcomes неизвестны | Supervisor livefile race прервал child; PASS/FAIL counts не принимаются |
| v4 / attempt3 | 56 collected;1test call,1FAIL;55не исполнялись | Нормально завершённый diagnostic: actual AttributeError startup, полный376 не принят |

Worker ограничился source/metadata/receipts/AST/compile и Git. Все actual imports,
pytest/SQL/install выполнены ROOT по отдельным review decisions. Полный v4 runner
заморожен без изменений, SHA-256
`b13d20b54e8dbf5804ba9ba77f2d00b42092847914e81fb4d88d226e50ca744a`;
его source commit `078d4a79ac7057938ef0c837f06c0ac26e30ef57`.

## Два разных доказательства runtime

[Target report](BACKEND_UPGRADE_TARGET_20261030.md): ROOT Docker CPython3.13.18,
glibc2.41, compiler8, runtime60+pip61, target resolution/offline install PASS.

ROOT дополнительно подготовил **новый** host environment CPython3.13.7/glibc2.36;
worker сопоставил exact61 inventory в runtime-prepare-proof с target inventory,
проверил пять command exit0/childReaped. Это только ROOT installation evidence,
без импорта app/tests; прежний installed test environment здесь не используется.
Новая functional проверка не заменит доказательство поведения Docker3.13.18.
Runtime60 и pip26.2.2 заморожены; packaging26.3 остаётся runtime.

Host runtime preparation receipt SHA-256:
`abbd7b18db3ba39bc18ad6ded7158347e8964af1126128472f9b9868a8863a42`.

## Точные selectors и ожидаемые случаи

Все selectors ниже относительны `clearledger/server`; ROOT runner передаёт
абсолютные paths в одном pytest session. Существующие assertions не меняются.
Число — ожидание по AST: длины literal parametrization, произведения stacked
parametrization, для `list(ScopeMode)` четыре члена enum из source AST; imported
unittest fixture helpers не наследуют дополнительные testcase. Subtests/циклы
внутри одного testcase отдельно не считаются. Это **не результат collect**.
На actual collection runner требует точного совпадения по каждому файлу; новый
fixture/dynamic parametrization, skip/xfail или расхождение требуют STOP/review.

| Selector | Ожидается | Зачем повторяется на новом dependency runtime |
|---|---:|---|
| `tests/backend_upgrade_approved.py` | 6 | Six new synthetic dependency probes described below |
| `tests/test_api_contracts_context.py` | 34 | Immutable access facts, enum scope intersection/tenant isolation |
| `tests/test_api_contracts_http.py` | 56 | PolicyRoute/FastAPI includes/mounts, guards before body/dependency validation, errors/lifecycle |
| `tests/test_auth.py` | 13 | Core login/refresh/token and user serialization |
| `tests/test_contract_liability.py` | 1 | Existing liability extraction from supplied text; no PDF parser claim |
| `tests/test_doc_text.py` | 9 | Existing file validation/docx extraction/inbox bounds; does not prove pypdf |
| `tests/test_docs_portal.py` | 22 | Actual OAuth cookie authority, canonical server/browser OpenAPI HTTP surfaces, logout/revoke/CSRF |
| `tests/test_docs_register.py` | 23 | Real application uploads/version bytes, duplicate/unsafe file, document ACL and registration routes |
| `tests/test_partner_identity.py` | 67 | Real raw signed JWT, OAuth code/PKCE/token/revoke/rotation/concurrency, UserInfo/claims/issuer/audience/algorithm |
| `tests/test_partner_product_integration.py` | 20 | Real login + consent + codePKCE + mounted productHTTP/SQL; no verifier override |
| `tests/test_partner_userinfo_wire.py` | 14 | ASGI UserInfo challenges/status/headers/serialization with stub verifier; not JWT/SQL proof |
| `tests/test_product_api.py` | 57 | Product SQL tenant/resource/documentACL, exact file bytes/download, errors/validation/schema; fake verifier is explicit |
| `tests/test_product_http_profile.py` | 12 | Offline actualASGI wire: errors, headers, files; projections/verifier mocked |
| `tests/test_product_object_ids.py` | 27 | Opaque/encoded Unicode object IDs, invalid422-beforeSQL and tenant restrictions |
| `tests/test_product_openapi_http_contract.py` | 8 | Formal OAS3.1/local refs + actual response contracts; projections mocked |
| `tests/test_product_service_openapi.py` | 7 | Canonical vs public browser schema, machine/security alternatives and protected HTTP wiring |

Итого ожидается **376** testcase. Завершённого full376 результата нет; точный
объём каждого actual ROOT attempt указан ниже, diagnostic1FAIL не заменяет376.

Точные новые selectors:

- `tests/backend_upgrade_approved.py::test_upgrade_dotenv_synthetic_stream`: StringIO,
  quotes/export/interpolation/empty/no-value; реальная .env не читается.
- `tests/backend_upgrade_approved.py::test_upgrade_raw_jwt_verification`: настоящий
  PyJWT RS256 decode, required claims, неверные audience/issuer/algorithm/signature
  и истечение. Прежний identity suite проверяет реальную app JWT verification.
- `tests/backend_upgrade_approved.py::test_upgrade_pdf_actual_library_and_application_extract`:
  pypdf пишет синтетический текстовый PDF (>200 символов), app contract_liability
  извлекает его через настоящий PdfReader; blank page даёт прежнее предупреждение.
- `tests/backend_upgrade_approved.py::test_upgrade_pdf_malformed_is_library_error`:
  malformed bytes вызывают PdfReadError. OCR/pdftotext здесь не подтверждаются.
- `tests/backend_upgrade_approved.py::test_upgrade_multipart_filename_and_exact_bytes`:
  реальный FastAPI/Starlette/python-multipart, Unicode/path-like filename,
  нулевые и binary bytes, size/content type. Это parser contract, не разрешение
  использовать filename как storage path; прикладной upload проверяет старый suite.
- `tests/backend_upgrade_approved.py::test_upgrade_multipart_validation_and_limits`:
  missing file422, missing multipart boundary400, maxfiles/maxfields/maxpartsize400.

Исследованы `auth.py`, `services/partner_identity.py`, `services/sso.py`,
`routers/partner_oauth_router.py`, `config.py` (pydantic-settings/env_file),
`services/contract_liability.py`, `services/doc_text.py`, реальные upload routers,
`product_api`/docs portal и указанные tests. Дополнительно прочитаны retained
Starlette requests/formparsers и pypdf writer source внутри wheel ZIP, без импорта.
Новые probes проверяют изменившиеся библиотеки, а не исправляют application code.

## Оснастка отдельно от runtime

Пять pytest pins получены metadata-only через stdlib importlib.metadata по старому
dist-info; старый interpreter/pytest/app не запускались. Retained caches просмотрены
до сети. ROOT дополнительно разрешил десять точных validator JSON/wheels и reuse
six1.17.0; shared runtime packages не дублируются и не меняются. Всего extra16,
ожидаемый installed inventory **runtime61 + tools16 =77** без других distribution.

| Extra test distribution | Версия | Wheel SHA-256 |
|---|---|---|
| iniconfig | 2.3.1 | `9121e2c1fdb355232495be3194c8dfe87ccc2d5dee45947b78e68f499790d7a7` |
| jsonschema | 4.26.0 | `d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce` |
| jsonschema-path | 0.5.0 | `2790a070bc7abb08ea3dbe4d340ece4efadf639223001f020c7503229ba068e2` |
| jsonschema-specifications | 2025.9.1 | `98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe` |
| lazy-object-proxy | 1.13.0 | `4046337019bd862440764930dffc47747a36b2e5d74346f0d404eadf1e3e6fa7` |
| openapi-schema-validator | 0.9.0 | `faa3bbe7c3aa8ca2087ad83f709dc3b7d920283153a570c03e24ea182558aa25` |
| openapi-spec-validator | 0.9.0 | `222fecffc7714f6d0a6ad62c0e4b66cc2b7dbfafb7b93acfc6c308abbdb51af8` |
| pathable | 0.6.0 | `82c4ca6c98c502ad12e0d4e9779b6210afee93c38990988c8c5d1b49bdcdf566` |
| pluggy | 1.7.0 | `7dd7b0d8832ba3cb632c306926ded123429211b83641b35dc5c41ad2d34f9bec` |
| pygments | 2.21.0 | `2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9` |
| pytest | 9.2.0 | `07acdcf88ec174f907dc01af70bf52d49b014bbab03faeeade31c96b18c2e588` |
| pytest-asyncio | 1.4.1 | `507afa78ec77c6661164ef1a2368bc7820383fd1a14b2a7f813de8b5a92949cc` |
| referencing | 0.37.0 | `381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231` |
| rfc3339-validator | 0.1.4 | `24f6ec1eda14ef823da9e36ec7113124b39c04d50a4d3d3a3c2859577e7791fa` |
| rpds-py | 2026.9.1 | `7868b85224291c6cb6759f9b5adb9745f486d226f62b16a614dd5a2a5ab2b35b` |
| six | 1.17.0 | `4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274` |

Первые пять: 5 official versionJSON +5 universal wheels, 0.444 с. Дополнительная
фаза ROOT: 10 official versionJSON +10 wheels (8 universal и cp313 manylinux x86_64
lazy-object-proxy/rpds-py) + один OSV batch16, 1.209 с. TLS strict, redirects
запрещены, ≤25 с/request, concurrency≤3, ≤180 с/phase, суммарные private артефакты
2.73 MB (<16MiB), сетевые журналы <2MiB. ZIP metadata/hash прочитаны без extraction,
.pth/sitecustomize/usercustomize отсутствуют, никакой код wheel не исполнялся.
Six использует retained pip cache: worker проверил metadata/version/SHA без
refetch; ROOT отдельно запросил официальный six1.17.0 JSON и подтвердил совпадение
SHA/11050bytes retained wheel. JSON SHA
`d8de39dd52b73048d81a8fd78022ee2bc72f8b568bcf0d88e5d5069c302b1208`.
Полные private receipts сохранены.

Supported-subset closure проверен по metadata declarations для Linux/Python3.13
без extras; активные shared runtime attrs/PyYAML/pydantic/pydantic-settings/packaging
сохраняют pins кандидата. Pytest -> iniconfig/packaging/pluggy/Pygments;
pytest-asyncio -> pytest; validators -> jsonschema/specifications/pathable/
referencing/rpds/lazy-object-proxy/rfc3339-validator/six. Windows/oldPython и
optional format/dev/docs/testing/ecma-regex extras не активированы. Это source
closure, не resolver/installer PASS worker. ROOT независимо проверил packaging26.3 closure
(29 active edges), установил tools offline с hashes (2.604s), выполнил pip check
(0.401s) и metadata77 (0.202s); runtime61 неизменен. Worker сопоставил receipt
inventory с exact runtime61+tools16, три exit0/childReaped и официальный six JSON.
Installation receipt SHA:
`f183375c1a42089673fe47824868e0670874aa3a884a32c0a3296cd5990bfe39`;
source/closure proof SHA:
`13b1c6c29aeea489167e3061dbfc9dc11ffd0d01e0b0d91a92e36d1330d84d66`.

OSV query содержит **только16 extra tools**, shared runtime исключён; точный
input order и все16 rows сохранены, matches0, pagination/errors0. Alias/range
данных в пустых результатах нет; отсутствие match не доказывает безопасность,
exploitability, reachability или закрытие alerts. Runtime OSV scope остаётся в
историческом artifact report. Для оснастки OSV status теперь проверен отдельным
batch, а не выведен из runtime query66.

| Private evidence | SHA-256 |
|---|---|
| tool closure manifest | `0a6d35bcdc363f9c396edce1e3b3f3ae468a81ecc09ae144e630bf2f886a1e85` |
| OSV request16 | `10c58f8e47cf97cd13e3897c755435c297153a19b522c24b52a40f061fb43d85` |
| OSV response16 | `779addf5f90cdb43d0e150749ce4d40fece88defcb67781af29152713ec4b621` |

## ROOT review и границы будущего исполнения

До первого стороннего/app import runner требует независимый ownSHA от ROOT,
полные hashes app/tests/schema_migrations и отдельных inputs, ровно новый
candidate interpreter3.13.7/glibc2.36, flags `-I -S -B`, отсутствие site/app/pytest
в sys.modules и site-packages/cwd в sys.path. По metadata проверяются exact77,
no system site, no .pth/customize/symlinks. Actual account HOME сохраняется;
worker/runner не заменяют его фиктивной папкой. Проверка существования .env
во всех соответствующих ancestors идёт без чтения, audit hook запрещает open .env.

Новый own execution root создаёт **три fresh private dirs**: empty cwd, uploads,
evidence. Повторный запуск в существующие dirs запрещён, старое evidence остаётся.
Child получает только фиксированный allowlist окружения и синтетические values.
DB: **api_backend_upgrade_test_20261030**, пользователь clearledger, только
127.0.0.1:33546, без query/fragment/target override; ROOT создаёт её отдельно и
подтверждает ownership. Перед fixture SELECT проверяет actual database/user,
пустоту и отсутствие других подключений. Это не право на другую DB/порт.
Существующий PostgreSQL и другие базы не изменяются runner.

До fixtures и импорта conftest включены socket/DNS/subprocess/.env audit guards,
блокировка HTTP transports/requests/aiohttp/webpush, SMTP stub, email sender
stubs и notify dispatch stub. ASGITransport остаётся рабочим; внешний транспорт
не доступен. OCR/doc_text external command stub возвращает пустой результат:
ни OCR, ни внешняя доставка этими suites не подтверждаются. Asyncpg connect
принимает только exact approved target, проверяет actual database/user и ставит
30s statement/command, 1s lock, 30s idle-in-transaction timeouts. Socket connections
разрешены только на точный loopback PG; UNIX socketpair нужен asyncio, UNIX
connect/listeners/datagrams/child subprocesses запрещены.

Deadline supervisor900s, CPU600s, AS2GiB, child file2MiB, openfiles256; scratch
≤64MiB/4096files, aggregate log≤2MiB, JUnit/proofs bounded2MiB/file, DB≤256MiB
pre/post. Проверены unchanged file fixtures: запись 1001 файла по одному байту
в test_doc_text; «large» fixture содержит9bytes; PDF upload samples — короткие
синтетические bytes, docx — небольшой ZIP. Записи valid>2MiB в выбранных sources
нет; RLIMIT_FSIZE2MiB сохранён без изменения testcase expectations.
На failure/timeout/boundary violation supervisor kill process group,
reap child и сохраняет bounded evidence. Retries, смена pin и application fixes
автоматически не выполняются. ROOT после просмотра очищает только свои DB/dirs.

Acceptance: collection counts точно равны AST expectation376, pytest exit0,
каждый testcase passed (SKIP/XFAIL/missing не принимаются), JUnit содержит376 без
failure/error/skipped, hashes после прогона сохранены, actual HOME не изменён,
pre-import/boundary/supervisor proofs и log/JUnit SHA записаны. **Нулевые blocked_network/blocked_subprocess/denied_env_reads обязательны
одновременно в child и независимо в supervisor**: даже подавленная background
попытка отменяет PASS. Stub sender calls записываются отдельно и могут быть
ненулевыми. SQL allow counters не считаются нарушением.
Runner сохраняет full nodeids/outcomes и точный inventory; это private artifacts.

## Frozen исходники и следующий шаг

| Дерево (все файлы, исключая __pycache__; own runner hash отдельно) | SHA-256 |
|---|---|
| app | `6eff5b153368ec492b91664a76825bd4ae360bfe4af55e902651f95d0d679981` |
| schema_migrations | `c641925633181647d39f788fd29765322d3a2027f6fcaeaefe533e870d1f1f0e` |
| tests | `faa034c1241dabd15aceb82f1ed6e90e47a0131b9af6ab0342cf00f7a898e722` |

Runner SHA-256: `b13d20b54e8dbf5804ba9ba77f2d00b42092847914e81fb4d88d226e50ca744a`.

ROOT получает отдельный private frozen proposal с commit, full file hashes,
источниками16 tools без копирования retained40MB, принятыми installation receipts,
точным будущим runner argv/env, SQL target, bounds и evidence acceptance.
Повторять installation/compiler не требуется: ROOT уже принял exact77. После
review и освобождения SQL окна ROOT отдельно создаёт approved empty DB и запускает
reviewed runner. Worker ждёт решения, сам runner/SQL/install не исполняет.

Docker target/host installation receipts не выдаются за functional PASS.
Реальный браузер, Docker app behavior, full backend CI, deployment, production,
independent rebuild/security certification не проверяются этим планом.
Requirements/Dockerfile/Compose/features/CI, baseline locks, прежние app/tests,
рабочие данные и другие branches сохранены. Merge/deploy отсутствуют.


## Коррекция после ROOT source review

Исходный commit56b4a63a/runnerSHA362fcbc0 и private proposal-v1 сохранены без
перезаписи. В corrective commit добавлены strict zero-forbidden-counters в двух
независимых acceptance путях, sender stub counts до fixtures и .env/PG guard до
импорта application sender modules. RLIMIT проверен против unchanged fixture
sources; pin/runtime/порядок expected tests и все прежние assertions сохранены.
Actual execution остаётся ROOT-only; source-only v2 proposal имеет отдельный hash.


## ROOT attempt1: collection gate stopped, 0 testcase calls

ROOT исполнил reviewedv2 в новом host candidate: outer18.514903652481735s,
supervisor17.64159861486405s, childexit4. Собрано327case; два unchanged модуля
(docs_portal22 и product_object_ids27) дали module-level SKIP из-за отсутствующих
opt-in flags. Collection guard сохранил expected376 и остановил запуск до
fixtures/test calls; testcase assertions не исполнялись. В boundary proof:
blocked_network1, blocked_subprocess0, denied_env_reads0, PGconnect2; БД пустая
7,765,015bytes, HOME сохранён, exact77. Все sender stub counts0. Это **не PASS**
и не обнаруженная application assertion regression.

ROOT выполнил normal DROP только own dedicated DB: relations0, connections0,
exists0; max_locks_per_transaction64 сохранён. Worker SQL не вызывал. Все v2
артефакты остаются неизменными; новый запуск использует fresh attempt2 directory.

| Сохранённое evidence первого actual attempt | SHA-256 |
|---|---|
| boundary proof | `985ec83bbc3d062e2c09780636dc1e68705defd95f915fa9e81e2f356069c7b6` |
| supervisor proof | `cadf2c6028c41770342829ab23bc2f2b5e5deaef35973627c4a5196b58cc4191` |
| run.log | `fc7e087ac35aa74d009b832bb0009de27ceff10f7a2d3342f20a2d10c85c3dbd` |
| JUnit | `d6e4afafa23512f635ac37af08756027dc1281873b683ed367fdd90e36c01f2c` |

Для v3 добавлены только требуемые unchanged suites opt-ins
`RUN_DOCS_PORTAL_TESTS=1` и `RUN_PRODUCT_OBJECT_ID_TESTS=1`. Count376 и testcase
expectations не меняются. Первые ≤32 запрещённых audit events сохраняют только
kind и ≤12 code-file/function/line frames; source lines, args, addresses,
environment values, locals и tokens в диагностике отсутствуют.

Source review retained urllib3/util/connection.py114–137 и независимое чтение
ROOT объясняют startup counter1: `_has_ipv6("::1")` вызывает bind и подавляет
Exception. Actual stack первого attempt не собирался, поэтому это source-backed
объяснение. ROOT разрешил временно назначить socket.has_ipv6=False **только на
пять explicit initial imports** aiohttp/aiosmtplib/httpx/pywebpush/requests,
затем восстановить exact original в finally до любых application imports и
fixtures. Это подавляет import capability probe без выполнения bind. Никаких
разрешений socket bind/listen/network не добавлено, counter discounts нет;
strictzero в child/supervisor сохранён. Evidence записывает suppressed/restored,
original capability boolean и bind_allowance=False. IPv6/реальный HTTP transport
этот ASGI прогон не валидирует. Любая иная запрещённая попытка означает FAIL.


## ROOT attempt2: interrupted partial run; next profile is diagnostic

ROOT начал actual v3/full376 на неизменном runtime77. Supervisor прервал own child
из-за FileNotFoundError между rglob/stat live scratch: temporary sample.bin
был удалён тестом. Supervisor204.63358381204307s, ROOT205.65794378332794s,
child killed/reaped. Run.log386bytes содержит dots и failures, но final JUnit и
boundary отсутствуют; атомарного per-test checkpoint в v3 не было. **Точное число
PASS/FAIL неизвестно и не принимается**, выводить его из progress symbols нельзя.
Original attempt2 целиком сохранён. Worker не исполнял runner/SQL.

V4 исправляет только observer/harness: точный owned root lstat anchor(dev/ino/uid),
bounded os.walk(followlinks=False), lstat каждого child. Игнорируется **только**
FileNotFoundError/ENOENT с exact filename исчезнувшего descendant внутри own root;
missing/drifted root, permission/I/O и любые иные errors остаются failure.
Symlinks/FIFOs negative file-policy fixtures учитываются в count, не обходятся и
не читаются; regular bytes≤64MiB, all observed entries≤4096. Проверка anchor
повторяется после обхода. Использован reviewed target-driver ENOENT-only pattern;
anchor identity и error policy записываются supervisor receipt.

После каждого pytest report phase пишется атомарный bounded checkpoint:
exclusive no-follow sibling temp, flush/fsync и os.replace в evidence. Содержит
nodeids/outcomes, last phase, counters/stub counts и safe failure trace при FAIL.
Каждый trace≤16KiB UTF-8, суммарно≤1MiB; после budget записывается truncated marker.
Pytest showlocals выключен, URL credentials/JWT/credential assignment values
редактируются; реальные .env/credentials в child отсутствуют. JSON≤2MiB,
private aggregate scratch≤64MiB и aggregate stdout log≤2MiB сохранены.
Неполный checkpoint явно complete=False/full376_accepted=False; это не PASS suite.

Следующий **отдельный diagnostic profile**:
`--profile api-contracts-http-first-failure` выбирает только
`tests/test_api_contracts_http.py`, ожидает **56 collected cases** по прежнему AST
и добавляет `--maxfail=1`. При первой неудаче нормально сохраняются testcase trace,
JUnit, boundary, atomic checkpoint и supervisor receipts. Это ожидаемый diagnostic
FAIL для получения первой причины, **не приёмка376**. Даже если все56 пройдут,
статус DIAGNOSTIC_PASS/full376_accepted=False не означает полный functional PASS.

Профиль `--profile full376` сохраняет прежние 376 selectors/counts/assertions и
не добавляет maxfail. ROOT не повторяет его до понимания первой ошибки. V4 имеет
fresh attempt3 directory; original attempt1/2 и frozen proposals1–3 сохранены.
ROOT отметил source lead: sync TestClient/lifespan и app.router.startup/shutdown
в create_policy_app. Это пока гипотеза; actual trace следующим diagnostic прогоном
получает ROOT. Application/API/dependencies/tests ожидания не меняются ради обхода
startup; никаких application fixes в ownership этого пакета нет.


## ROOT attempt3: первая actual ошибка подтверждена, preparation принят

Reviewed v4 diagnostic завершён нормально: **56 collected /1test call /1FAIL**,
pytest0.96s, supervisor16.393642026931047s, ROOT outer17.513004108332098s,
pytest/child exit1, own children reaped. Первый exact selector:
`tests/test_api_contracts_http.py::test_missing_invalid_wrong_kind_tenant_scope_resource_or_action_deny_before_handler[None-401]`.

Actual trace: `TestClient.__enter__` входит в настоящий lifespan и доходит до
`app/api_contracts/routing.py:280`, `await app.router.startup()`, затем
`AttributeError: 'PolicyRouter' object has no attribute 'startup'`. Ошибка
воспроизведена на FastAPI0.133.0/Starlette1.3.1. Запрос ещё не дошёл до проверяемого
401 response; ни startup, ни testcase expectation не обходились и не подменялись.
ROOT передал runtime fix владельцу lifecycle, worker не менял application file.

Boundary: blocked_network0, blocked_subprocess0, denied_env_reads0, audit[];
PGconnect2 (preflight/final control), exact runtime61+tools16, actual HOME сохранён.
IPv6 import probe suppressed=True, original flag restored=True, bind_allowance=False.
Atomic checkpoint сохранил failed nodeid, call trace4616bytes без truncation и
последний teardown phase. `full376_accepted=False` во всех итоговых receipts.
Это подтверждённый diagnostic FAIL, не security/production certification.

Получены две bounded warnings: Starlette deprecated httpx TestClient path и
anyio.abc.BlockingPortal alias. Они сохранены в run.log, версии/оснастка по ним
не менялись и новых network names не добавляли.

Worker проверил SHA итоговых log/JUnit/boundary по supervisor receipt, один
failed outcome в checkpoint/final boundary, collection56, strictzero counters и
root summary. ROOT summary подтверждает normal DROP только own exact test DB:
relations0/connections0/existsAfter0, max_locks_per_transaction64, без FORCE/GUC.
Это чтение сохранённых ROOT receipts; live SQL worker не выполнял.

| Actual attempt3 evidence | SHA-256 |
|---|---|
| ROOT summary | `ebeea461f822ff513d16f7dd869ab20df3ba8b7c353aea9e095967df7a91189a` |
| ROOT process | `4c4248fc24ddc1000fbc692d50faf6243afb72dd08d697c636db3727d0fa75bf` |
| Atomic outcome checkpoint | `5986b73fde40e04d3722b5402fc92a301509053463aefc1625bcab8f8526de6d` |
| Boundary proof | `ac8dd14a3bee566a152f7e0614535d08b3e50a2e0c29e6cf5ce5ead9cfe6deab` |
| Supervisor proof | `a13dc4fd02c1e131e0a6d88868e25204c5f461b8cf3c2d95e94a1fe328c5359d` |
| JUnit | `f1436c2517d150edb4b63c6a546b3fd5b12060aef91c855d4a8de2170ba5a488` |
| Run log | `f85adc3a3c4494849a98f990ab4b79046a7c77371b97777c83a12c0f240ed8a6` |
| Frozen execution proposal v4 | `cc6d89125e6df5424b3f470c75f45da09f5c9458487a410ba135a404191336b7` |

Подготовка target locks/evidence, test tooling и функционального runner завершена;
ROOT принял report-only finalization этого пакета. Дальше нужны отдельный
проверенный application lifespan fix, frozen updated source hashes и ROOT-owned
verification сначала relevant HTTP/lifecycle, затем согласованный полный376.
Текущие full376 claims не повышаются до PASS. Старые failures/provenance и все
три actual attempt artifacts сохранены; v4 runner не меняется после diagnostic.
Requirements/Dockerfile/Compose/features/CI, baseline locks, версии77, старые
app/tests и рабочие данные worker не менял. Merge/deploy/production не выполнялись.
