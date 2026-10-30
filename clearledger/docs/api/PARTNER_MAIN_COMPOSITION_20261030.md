# M18: подготовка actual app.main composition, 30.10.2026

Статус: **ROOT BASELINE 5 PASS / 2 FAIL; CORRECTIVE RETEST PENDING**.
Исходный frozen baseline выполнен ROOT, дефект request ID подтверждён.
Подготовлен ограниченный фикс и повтор трёх затронутых cases; M18 не закрыт.
База исходников:
`46c6ea484476569f17e8957335bf010acbd66bb4`, ветка
`agent/api-partner-main-composition-20261030`. Auth/ACL, requirements/locks, Compose, CI, версии и значения feature flags
не изменены. После baseline ROOT отдельно разрешил единственную runtime-правку
`app/product_api/app.py`: использование trusted outer request ID в child.

В исходном baseline добавлены только этот документ, `server/tests/test_partner_main_composition.py`
и `server/tests/partner_main_composition_approved.py`. Старые тесты и sandbox
остались исходными. Существующие `.tmp`, `node_modules` и evidence сохранены.

## Что именно собирается

Runner импортирует **исходный `app.main`**, а тесты используют `main.app` через
`httpx.ASGITransport`. Все исходные routers, их порядок, middleware, mount
`/api/v1`, exception handlers и child settings/verifier остаются на месте.
Не создаётся параллельный FastAPI, не копируется OAuth, нет dependency override
`get_current_user`/`get_db`, fake JWT или замены domain handlers.

Исходный lifespan действительно входит и выходит. Неизменёнными остаются
`install_orm_scope`, проверка секрета, `database_startup_lock`, создание и отмена
восьми scheduler tasks. Явные process-only seams:

| Seam | Причина и предел доказательства |
|---|---|
| `Settings(_env_file=None)` + замена accessor до импортов приложения | Нет чтения `.env`; исходные defaults сначала проверяются выключенными. Только внутри дочернего процесса включаются OAuth/product/docs, задаются synthetic issuer/audience/RSA key. Quota и managed schema gates остаются выключенными. |
| `main._prepare_database_once` | Подсчитанный no-op вместо production seed, backfill, startup DML и повторного bootstrap. До lifespan fixture вызывает настоящий `database.create_all()` на новой пустой БД, включая исходные миграции. Это не тест production seed/startup backfill. |
| `chat_ws.manager.start/stop/broadcast` | Подсчёт вместо LISTEN/presence/доставки WS. Реальный WS-протокол не проверяется. |
| `run_forever` восьми модулей из `main.py:265–338` | Каждая исходная задача стартует один раз и паркуется без выполнения планировщика. Исходный shutdown отменяет задачи; fixture ждёт их и проверяет cancellation. Работа расписаний не проверяется. |
| SMTP/email/notify/chat_mail/web_push/Jitsi signing | Stubs установлены до `app.main` и fixtures. Они сохраняют только счётчик вызовов без адресов, текста и credentials. Ожидаются восемь `notify.dispatch_async` от восьми настоящих Core login; остальные доставки запрещены результатом boundary. |
| HTTP transport boundary | `AsyncClient.send` разрешает только ASGITransport; socket audit разрешает только точный PostgreSQL `127.0.0.1:ROOT_PORT`. DNS вне этого адреса, listeners, UDP, дочерние процессы, `.env`, `.ssh`, `.vault`, `.claude` запрещены. |
| `partner_docs_client_id` | После настоящей admin-регистрации выставляется ID synthetic public client как deployment config. Не меняются docs eligibility, cookie/CSRF и live grant verification. |

Перечень schedulers: `channel_scheduler`, `pulse_digest`, `task_scheduler`,
`mail_poller`, `store_price_scheduler`, `onec_read_scheduler`,
`space_projection_scheduler`, `intake_watch`. Подмена всего lifespan и отключение
охраны/rate limiter не используются. ASGI client IP отдельный на testcase;
счётчики охраны не очищаются ради прохождения отрицательных проверок.

## Семь независимых cases

1. `test_main_problem_request_id_matches_outer_security_context`: исходное
   равенство `body.requestId == X-Request-Id`. Сохраняется без skip/xfail;
   ROOT воспроизводит baseline до исправления, см. M18-RID-01 ниже.
2. `test_main_mount_order_anonymous_docs_and_version_guards`: фактическая
   ссылка mount на `main.app.state.product_api`, порядок middleware, закрытые
   native/child raw OpenAPI/docs, все Swagger session/UI/schema/assets/callback
   URL без docs session, product401, query-token denial, gate-check и настоящий
   OIDC discovery. Native SSO JWKS без fixture SSO key возвращает пустой набор.
3. `test_ordinary_employee_scoped_entities_refresh_and_revoke`: настоящий
   Core password login → `me`/gate cookie → admin registration/install → свежая
   employee PKCE transaction/consent POST → token → независимая RS256/JWKS,
   issuer/audience/nonce/at_hash/UserInfo проверка → object/equipment с одним
   site, hidden/foreign404, strict query422, Core/ID bearer401, native-file401,
   actual refresh rotation/revoke и отказ ранее действовавшего access token.
4. `test_ordinary_employee_document_eligibility_denial_is_not_owner_consent`:
   сотрудник `role=user`, `modules=[equipment]`, один site; в consent доступны
   только `openid`, а `docs:read`, `documents:read`, `documents.files:download`
   недоступны. Настоящий approve POST получает422; другой subject (owner)
   получает404 на уже связанный request; employee admin registration403.
   Независимое чтение БД подтверждает отсутствие grant/code этого клиента.
5. `test_explicit_docs_role_employee_allowed_bytes_hidden_and_foreign_404`:
   отдельный обычный сотрудник с `CompanyRole.modules=[docs,equipment]`, а
   `UserCompany.modules=[]`; источником прав служит настоящая роль. Отдельный
   login/consent/token, allowed document/version/known bytes, private owner
   document404, hidden-site/foreign404 и mismatched version404. Это **новая
   подготовленная проверка**, не ранее выполненный ordinary-employee pilot.
6. `test_main_swagger_canonical_projection_assets_session_csrf_and_live_revoke`:
   реальный owner grant настроенного public docs client; Bearer сам по себе
   не открывает bytes. Same-Origin/CSRF bootstrap, Secure/HttpOnly/Strict cookie,
   UI/raw canonical/browser projection/все assets, запрет query override,
   двенадцать GET в schema, `ProductServiceOAuth.clientCredentials` в canonical и его отсутствие в
   browser projection, реальная пагинация object/equipment/party/contract,
   scoped monitoring GET и tenant404. DELETE session с CSRF отзывает family;
   оригинальная cookie повторно посылается и тоже получает401.
7. `test_main_confidential_registration_admin_machine_grant_and_live_revoke`:
   реальная confidential registration, credential issuance, admin machine
   grant и client_credentials через HTTP Basic; scoped product GET,
   UserInfo/documents403 и admin revoke grant → прежний access401/token400.

PKCE verifier/challenge — фиксированный RFC7636 Appendix B vector; callback
HTTPS URL только записывается/разбирается в памяти и **не вызывается**. Никаких
listeners, browser, TLS termination, real partner или production key нет.

## Независимый persisted oracle

Каждый исполняемый testcase после synthetic fixture seed сохраняет baseline,
а после auth/read phases — новые снимки. В `finally` сохраняется ещё один
снимок и сравниваются business/files даже при падении HTTP assertion.

Fixture содержит две вымышленные компании, три своих site и foreign site,
owner/admin без superadmin, equipment employee, отдельного docs-role employee,
организации, контрагентов, location-scoped договоры/связи, station equipment,
company/private/hidden-site/foreign документы, SourceFile/DocVersion и известные
байты с SHA256. Native Core/OAuth identities и grants через ORM не выдаются.

Oracle читает непосредственно PostgreSQL в отдельной `READ ONLY` транзакции,
обходит **все** ordinary/partitioned tables `public`/`edge` из `pg_catalog`,
включая не описанные ORM, и хеширует отсортированный полный `to_jsonb(row)`.
Нет сравнения ORM identity map, `Base.metadata` или повторного вызова продукта.
Числа строк и row-set MD5 фиксируются по каждой таблице, file bytes — SHA256.

Auth/registry отделены **явным списком**, не prefix wildcard: `eco_apps`,
`eco_company_apps`, `audit_events`, 12 перечисленных `partner_*` tables,
`partner_docs_sessions`. У `users` только `last_seen_at`, `failed_logins`,
`locked_until` вынесены в отдельный keyed auth fingerprint; пароль, membership,
роль, token_version и все другие поля остаются в business fingerprint.
`security_events/security_blocks` также остаются business: неожиданная запись
охраны не скрывается. Каждая phase задаёт allowed/required auth table delta;
GET/pagination/docs bytes должны давать **нулевую persisted delta**.

Consent разрешает только authorization request/grant/code; token exchange —
code/family/token/pairwise subject; refresh — tokens; revoke — family; docs
session — docs session; close — docs session/family. Company registry может
меняться только в phase admin registration/installation. Дополнительно после
обмена code независимо прочитываются consumed code и delegated grant:
проверяются точный user, company, scopes и kind. Это row-state evidence, не
утверждение об отсутствии transient DML, полностью откатившегося до снимка.

## Frozen gate и конкретное предложение ROOT

До первого pytest/app/ORM/driver import runner требует собственный SHA из
ROOT approval, точный CLI argument, `-I`, Python3.13 без `-O`, обе ROOT/test flags,
полное byte-совпадение app/tests/schema и requirements/pytest.ini. Hash списков **исходного baseline d2d014d8** (не corrective runner):

| Набор | Count | SHA256 |
|---|---:|---|
| app, все файлы | 492 | `716fa867894646a1977ea89c970503d319c9205c0b0459e73682a7722534a5fe` |
| tests, все файлы кроме самого runner | 340 | `76b527332b6bc3af52f2edad271f5bfd646e486329eab9e0e46b67f5263f950e` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |
| runner | 1 | `e08b24422ed4bca0b43adcda4a3a41d6a9bbcc9d8de5bc19885efcb7cfc5b053` |
| новый test module | 1 | `354dc2ec8540a24b41f9cd3e0552f1ca2df4988631fbd793c27f901ee932c950` |

Private source manifest и exact launch proposal сохраняются в
`.artifacts/m18-main-composition-20261030/` этого worktree. В manifest runner
отделён от tests aggregate, чтобы не создавать самоссылочный hash.

Предлагаемый target: **только** новая disposable БД
`api_partner_main_test_20261030` на `127.0.0.1:33546`, synthetic role
`clearledger`. Порт — предложение из существующего test environment, не
проверенный/зарезервированный worker ресурс. ROOT сначала резервирует sole SQL
slot, проверяет ownership/freshness/отсутствие клиентов и отдельно создаёт БД.
Перед исполнением оба URL должны побайтно совпадать, host должен быть numeric
127.0.0.1, port должен совпадать с ROOT-approved `M18_PG_PORT`; любые query/fragment
connection overrides запрещены. Runner не создаёт/не удаляет БД, fixture
создаёт `edge` только после fresh-relation check и запускает исходный bootstrap.

ROOT создаёт **три новые отдельные owned0700 пустые директории**: empty cwd,
upload и evidence; сохраняется настоящий HOME. Child env — только явный
allowlist, без наследования секретов/proxy/PYTHONPATH/`.env`. Изолированный
interpreter — существующий
`/srv/projects/api-modernization-test-env-20261029/.venv/bin/python`.
Ничего не устанавливается и не собирается. Внутренний alarm540s, предложение
outer supervisor — deadline600s, combined log8MiB, evidence16MiB, DB256MiB;
ROOT обязан ограничить процесс, дождаться выхода/reap и записать elapsed/exit.

Evidence: JUnit `main-composition.xml`, `boundary.json` со всеми outcomes,
точными capture counts и network/process attempts, per-case baseline/phase/final
fingerprints. Первоначальное ожидание baseline **6 PASS + 1 FAIL request-ID** оказалось
неполным: ROOT измерил **5 PASS + 2 FAIL**. Второй FAIL — ошибочный predicate
нового Swagger testcase, исправляемый по существующему контракту, без изменения
OpenAPI или OAuth runtime. При дополнительном дефекте сохраняются
фактические ошибки; независимые cases продолжаются без `--maxfail=1`.
После review ROOT закрывает свои соединения и делает обычный DROP только этой
БД, сохраняя proof отсутствия DB/clients/resources. Worker этого не выполняет.

## M18-RID-01: дефект подтверждён ROOT baseline

`app/security_context.py:30–43` создаёт внешний uuid4.hex, удаляет любой
вложенный `X-Request-Id` и ставит свой. Он добавлен внешним слоем в
`app/main.py:864–866`. В child `product_api/app.py:104–109` создаётся другой
`request.state.request_id`; `_problem` в строках56–59 берёт его для
`Problem.requestId` и строках69–72 — для собственного header. Последний header
затем переписывает внешний middleware. Из исходника следует ожидаемое
расхождение body/header именно в actual main composition.

ROOT подтвердил порядок: отдельный неизменённый assertion и frozen baseline
без skip/xfail/подмены middleware, затем отдельное решение об исправлении.
Baseline patch не менял runtime. После его исполнения ROOT разрешил
точечный corrective patch, описанный ниже; middleware и assertion не подменяются. Остальные error
checks проверяют статус, Problem media type, no-store и валидность каждого ID;
единственное требование равенства явно принадлежит отдельному testcase.

## Выполненная проверка и ограничения

Worker сделал source review, stdlib AST parse двух новых Python файлов и единственного runtime-файла,
source manifests и Git checks. **Не выполнялись** compile gate, pytest/collect,
runner, imports app/ORM, SQL, HTTP server/browser, Docker, npm install/build,
venv или настоящая доставка **со стороны worker**. ROOT actual baseline
выполнен отдельно; corrective HTTP/PG verdict ещё ожидается.

Даже будущий successful ASGI main run с перечисленными seams не проверяет
nginx/Traefik/CORS deployment trust chain, native SSO browser handoff,
real scheduling/seed, multiworker quotas, TLS/browser cookies на реальном
домене, нагрузку, живых партнёров или release acceptance. Native Core login и
gate cookie в ASGI не равны проверке полного browser SSO. Старый purpose-built
HTTPS sandbox остаётся отдельным доказательством и не переименовывается в
full composition. **M18 и программа M00–M19 остаются открытыми.**


## ROOT baseline evidence и corrective patch

ROOT исполнил immutable `d2d014d873b6eb763f3cd03cc529dc3491d45cfb`:
**5 PASS, 2 FAIL, 0 SKIP**, pytest72.40s, outer87.22030024975538s,
exit1, child reaped. Сообщение ROOT `msg_3619c332886f` расширило ownership только
на `app/product_api/app.py`, сохранив запрет worker на app/SQL/pytest execution.

PASS: anonymous/mount guards; обычный employee objects/equipment + native
login/PKCE/refresh/revoke; отдельный employee document eligibility denial;
обычный docs-role employee allowed bytes/private/foreign404; confidential
admin machine grant/read/live revoke. Они **не повторяются** без причины.

FAIL1: отдельное неизменённое equality assertion body/header request ID.
FAIL2: новый Swagger testcase искал `clientCredentials` внутри `ProductOAuth`,
хотя существующий контракт хранит его в **отдельном** `ProductServiceOAuth`.
Это ошибка нашей проверки, не OAuth/spec defect. Ранее существующий
`test_product_service_openapi.py:55–58,158–159` и исходный schema builder
подтверждают две canonical security schemes и одну browser scheme. Исправлены
только predicates нового теста. Хвост Swagger testcase (pagination/monitoring/
close/replayed cookie) после первоначального неверного assertion не считался
проверенным; его завершает целевой повтор.

ROOT evidence находится в integration worktree:
`.artifacts/root-main-composition-review-20261030/`:

| Artifact | SHA256 |
|---|---|
| `test-process.json` | `68cd52f493cba6dbc76549e849eea26ae1321154a7f017cd77ebb4e635ef0cd3` |
| `evidence-test/boundary.json` | `bb46f4d2f0254d79746a54feaf8416f964b83b9472d53861710e91eab6829ccb` |
| `evidence-test/main-composition.xml` | `1b7175a1cc91e7b83bbd79686958079f3c8a003660c6f62a12dc5978e8ea7aea` |

Worker независимо прочитал эти **уже существующие** artifacts: семь pairs
baseline/final business/files совпадают; сохранённые промежуточные phases тоже
не меняют business/files. Это чтение evidence, не новый SQL-прогон. Boundary:
8 schedulers, start/stop/prepare по1, notify8, network/process attempts0,
unexpected delivery0. ROOT сообщил обычный DROP exact DB, retained relations344,
fresh clients0, exists0, maxlocks64; database/listeners не остаются у worker.

Runtime fix: child request-ID middleware читает существующий
`app.security_context.current` ContextVar. При наличии внешнего контекста
использует его ID; standalone child генерирует свой uuid4. Входящий HTTP
`X-Request-Id` не читается, глобальный mutable ID не добавлен. Остальная AST
runtime-файла вне одного нового import и одной вложенной функции byte-структурно
совпадает с baseline; auth/ACL/schema generator не менялись.

Корректирующий runner выбирает **только три node IDs**:

- прежний request-ID testcase с сохранённым equality и новыми forged-header/
  восьмью concurrent-request controls;
- прежний Swagger testcase с исправленными scheme predicates;
- новый `test_standalone_child_unavailable_problem_request_id_without_sql`:
  настоящий standalone child, disabled product feature → actual ASGI503,
  два разных UUID, body/header equality, forged input игнорируется, отсутствует
  outer ContextVar. SQL listener отвергает любую попытку до исполнения и пишет
  нулевой счётчик в JUnit/private evidence.

Для трёх cases ожидаются notify1 от единственного owner login; восемь parked
jobs и один lifecycle сохраняются. Все остальные gates/границы прежние,
но frozen hash обновлён на corrective source. Новые proposal/source manifest
имеют суффикс `-v2`; исходные artifacts и baseline не перезаписываются.

| Corrective source | Count | SHA256 |
|---|---:|---|
| app | 492 | `fc73c090cd736b7e4a8f43df42025d78dee7114572989936a5ac27e99236e62a` |
| tests excluding runner | 340 | `bd352e7f2c77947355ea5377a9eb0c1ad251037885798ef55e6cf83c74dce320` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |
| runner | 1 | `23fa037557b16ab2ffcf672a7759fa89ff1adf2e11d4afbb5644fc534fea5bd8` |
| test module | 1 | `acf6332c769baf232ca4e8f18ce70695942f92c22cd5d76e306e5887eee5e74c` |
| runtime app.py | 1 | `91c2c8165e9d1b25d04c2f930167a7f5aeb34ef4b6882b4fe5f0c4275ced82e5` |

ROOT отдельно reviewed/re-reserves fresh target/directories и исполняет этот
повтор после своего dependency-candidate окна. Worker corrective code не запускал.
До новых actual evidence фикс остаётся подготовленным, не принятым по runtime.
