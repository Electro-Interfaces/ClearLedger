# M18: подготовка actual app.main composition, 30.10.2026

Статус: **SOURCE PREPARED, ROOT EXECUTION PENDING**. Это предложение проверки,
не протокол успешного HTTP/SQL-прогона и не закрытие M18. База исходников:
`46c6ea484476569f17e8957335bf010acbd66bb4`, ветка
`agent/api-partner-main-composition-20261030`. Production-код, auth/ACL,
requirements/locks, Compose, CI, версии и значения feature flags не изменены.

Добавлены только этот документ, `server/tests/test_partner_main_composition.py`
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
   двенадцать GET в schema, canonical `clientCredentials` и его отсутствие в
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
полное byte-совпадение app/tests/schema и requirements/pytest.ini. Hash списков:

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
fingerprints. Ожидание baseline: **6 PASS + 1 FAIL request-ID**, не зелёный
run и не заранее измеренный результат. При дополнительном дефекте сохраняются
фактические ошибки; независимые cases продолжаются без `--maxfail=1`.
После review ROOT закрывает свои соединения и делает обычный DROP только этой
БД, сохраняя proof отсутствия DB/clients/resources. Worker этого не выполняет.

## M18-RID-01: source finding, baseline ещё не измерен

`app/security_context.py:30–43` создаёт внешний uuid4.hex, удаляет любой
вложенный `X-Request-Id` и ставит свой. Он добавлен внешним слоем в
`app/main.py:864–866`. В child `product_api/app.py:104–109` создаётся другой
`request.state.request_id`; `_problem` в строках56–59 берёт его для
`Problem.requestId` и строках69–72 — для собственного header. Последний header
затем переписывает внешний middleware. Из исходника следует ожидаемое
расхождение body/header именно в actual main composition.

ROOT подтвердил порядок: отдельный неизменённый assertion и frozen baseline
без skip/xfail/подмены middleware, затем отдельное решение об исправлении.
Этот patch не меняет runtime и не чинит/не обходит finding. Остальные error
checks проверяют статус, Problem media type, no-store и валидность каждого ID;
единственное требование равенства явно принадлежит отдельному testcase.

## Выполненная проверка и ограничения

Worker сделал только source review, stdlib AST parse двух новых Python файлов,
source manifests и Git checks. **Не выполнялись** compile gate, pytest/collect,
runner, imports app/ORM, SQL, HTTP server/browser, Docker, npm install/build,
venv или настоящая доставка. Actual HTTP/PG verdict ожидается от ROOT.

Даже будущий successful ASGI main run с перечисленными seams не проверяет
nginx/Traefik/CORS deployment trust chain, native SSO browser handoff,
real scheduling/seed, multiworker quotas, TLS/browser cookies на реальном
домене, нагрузку, живых партнёров или release acceptance. Native Core login и
gate cookie в ASGI не равны проверке полного browser SSO. Старый purpose-built
HTTPS sandbox остаётся отдельным доказательством и не переименовывается в
full composition. **M18 и программа M00–M19 остаются открытыми.**
