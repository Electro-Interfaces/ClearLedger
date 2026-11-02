# M16-C4: последовательность свежего и обновлённого Core bootstrap

**V3 SOURCE DESIGN, production0/runtime0. ROOT review требуется до кода.**
Исследован состав ROOT `0e9b923106796c9f278d6e9ef5f813eeaa91ce66`, включая P11,
Support composition, protocol audit и C3. Работоспособность полного старта на нём
**не проверялась**. C3 single82/82 относится только к его принятому budget gate;
C2 literal10parents fixture не доказывает production fresh bootstrap.

Старая C3 ветка сохранена на `0ccba868a37bee3a938d8f8c84c09ef3dcf6eddd`:
clean, fetch, ownHEAD=origin. Новая `agent/api-core-bootstrap-sequence-20261031`
создана **прямо от ROOT pin**, без merge/reset/переключения соседних деревьев.
Изменяются только этот NEW MD и NEW JSON; доказательства лежат в own ignored
`.artifacts/core-bootstrap-sequence-20261031/`. Старые ignored версии C3 сохранены.
Frozen C3 EOF warning не исправлялся. App/tests/schema/deps/artifacts байты не менялись.

## Проверяемый вывод

Для **пустой схемы Core** имеется доказанный исходниками ordering gap:

1. `main.lifespan` берёт `database_startup_lock` и вызывает
   `_prepare_database_once → _prepare_database → database.create_all`.
   Отдельного `startup_pipeline` в этом pin нет, это не фактический владелец.
2. `database.create_all:2248–2251` при effective Core требует канонический Pulse
   catalogue **перед** PHONE DDL и `Base.metadata.create_all:2257`.
3. Pulse verifier сначала требует `pulse_views` и `company_roles` с UUID ключами
   (`catalog_pulse_view_role_grants_v1:28–44`); missing parents дают refusal.
   Guard ничего не создаёт. Core исключает role-grant Table из ORM DDL.
4. Явный runner0003 сначала требует применённые0001/0002 и их каталоги,
   затем Pulse parents; 0001 требует `partner_installations` с нужным unique key,
   0002 требует `calendar_events`. Runner не создаёт эти prerequisites.
5. Deploy pin `65e21e7a27ee61050d0790004f5d518720c1db7c` в рассмотренном
   shared-DB template создаёт namespaces/extension/role/path, но не эти Core parents.
   `provision.sh:47–59` ждёт backend health до post-start path step.

Следовательно, комбинация этих source paths сама не строит пустой Core: родители
нужны до входа в прежний ORM bootstrap. Это **не установленный deployment incident**:
не измерены текущие образы, реальные init SQL/roles/configs, рабочая БД и внешние
операционные шаги. Standalone public имеет отдельный путь, existing canonical Core
может проходить catalogue guard до adopted0003. Один отказ Core не переносится на них.

## Источники и полный freeze

В соседнем JSON у каждого source-chain узла есть **полный file SHA256**, immutable
pin и line/end_line. Там же полный Ledger manifest, source anchors, все найденные
DDL/CLI candidates и model FK graph; Deploy inventory публикует только paths,
line numbers и SHA, без SQL/tenant data/credentials. Raw source-search receipt
Deploy остаётся ignored. Line numbers относятся только к указанным pins.

Digest `approved_json_rows_sha256` = SHA256 компактного JSON sorted массива
`[[server-relative-path, SHA256(full-file-bytes)], …]`. Второй `sha256` в JSON
явно помечен и использует relative-subtree path+NUL+hexSHA+LF; их не смешивать.

| Source ROOT | Files / bytes | Approved JSON rows SHA256 |
|---|---:|---|
| app, full tracked own root V3 |504 /17174224|`cc90b65d584429e3235e0e666a396ee622fc35cead9e551f671daffe6346a3de`|
| tests |391 /5502148|`24c0fcc3fe59da1938505afd841895fa1626ea8740e4c6b3018224507c8a04bc`|
| schema_migrations |24 /107419|`36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165`|
| scripts |74 /347253|`4a77990a1edfa828bcd55e604074e02ba444a003e6ebff702a4d664be13dfc9c`|
| tools |9 /295214|`b0b6610e8e9d3edca45ad7a4cda79f1dbf76e91ef8212ffab6438d5c82cbfe09`|

Основные byte identities:

| Path от clearledger/server | SHA256 |
|---|---|
| app/main.py |`aa3f045a41e5235eb421be11ca13f3d34670b1d0ed6a36b9a258f7634618c0ed`|
| app/database.py |`30c01b44669729b0bc19210b44205092f61040aed9c1d5334c3a6f5feac106ec`|
| app/config.py |`90c5da106f20fe90e31c899a88018ef741e6b3207a555fedbd58bafaa61780e8`|
| app/services/schema_version_gate.py |`8580b7745468ee65f6dbbc389565ebefa16714ced6f3d0248d3b3f3e48568dee`|
| app/services/pulse_view_role_schema.py |`10de8705e7346dc42ac8f3fcdf57f3ae57f525e4c3540518c80be94ffb1f5e92`|
| app/models.py |`ffd2c8a1231ca306bf5d569481d3c8e13b81e8a13ce312f8d39978da0e682682`|
| app/models_partner.py |`51695adcc2784279fa00a0b2cccd99f181ee0a51cbf6232b8499adc0a7ada916`|

Stdlib AST V1/V2 разобрал979 **выбранных** Python modules; ошибочно исключённый
mail_secrets.py отдельно прочитан/AST-compiled в V3, итого980 selected modules.
Это не полный репозиторий. Full app root содержит504tracked files, а прежние503
были selected coverage без одного source. Tests391/schema24/scripts74/tools9
проверены по tracked path inventory: в этих пяти roots иных omissions нет.
332 literal declarative table candidates из трёх model files не равны фактическому
imported metadata/DB catalogue. 1010 SQL-looking string candidates в10 Python
files включают docstrings и не равны executed statements. Python AST не исполнялся.
Известный `books_links.py:144` SyntaxWarning сохранён. Исторический source scanner не искал credentials, но его substring exclusion
secret был ошибкой отбора исходников; точный exclusions manifest и исправление
coverage описаны ниже. Реальные env/config/credential stores не читались.
Dynamic SQL/imports, shell expansion и загруженный внешним образом SQL не доказаны.

Прочитаны CLAUDE обоих уровней Ledger, Deploy AGENTS/CLAUDE/README/WORKFLOW/
CURRENT-STATE/AGENT-MEMORY на pin65e21e7, rushydro-space и canonical ai-base
`projects/ecosystem/README.md`, Ledger README/architecture/tech. Ai-base pin есть
в JSON; это контекст, не основание для текущих runtime claims. Прочитаны принятые
schema design/runner/cutover/restore, C2/C3, calendar, policy lifespan, Support
composition и текущий protocol report. Их исторические результаты не переименованы
в результат на ROOT0e9b. Инструкции об обновлении чужого канона не расширяют этот
разрешённый two-report scope.

## Фактическая startup цепочка

| Шаг | Source / наблюдаемое следствие |
|---|---|
| Package/entry |Dockerfile:9–24: WORKDIR /app, app+schema_migrations COPY, gunicorn app.main:app,2workers. Никакого explicit migration command перед gunicorn.|
| Import |main:22–139 imports config/database/routers/seed и строит settings; database:18–40 создаёт engine/session factory. Это не доказательство открытого socket; app imports здесь не выполнялись.|
| Namespace |Unqualified Base metadata использует actual connection current_schema/search_path. `schema_translate_map` в app source не найден; перевода public→Core код не устанавливает. Явные edge names сохраняют свой namespace.|
| Lifespan |main:233–258 installs ORM scope, проверяет prod secret, затем owner lock434532,1 на отдельном engine connection; внутри preparation использует другие connections.|
| Managed precheck |main:193–196 ON требует C3 engine gate прежде marker. OFF обходит этот gate без I/O; outer lifespan lock уже взят, поэтому общий startup не наследует обещание isolated gate «bad config before socket».|
| Marker |main:197–224 только prod+nonempty HOSTNAME: CREATE/read/commit app_startup_runs, completed→return, иначе fullprepare, INSERT/delete old markers/commit. Test/dev без marker.|
| Core DDL guard |database:2241–2257 actual begin → optional budget borrowed gate → namespace foreign visibility guard → Core Pulse catalogue → PHONE → Base subset. Core Pulse всегда excluded; budget excluded только managedON.|
| Public DDL |namespace public: ORM создаёт role-grant table, затем Pulse catalogue до первого commit. Допустим только явный legacy public path, не missingCore fallback. Другие custom namespaces не объявлены supported.|
| Legacy tail |database:2263–5559 выполняет большой ALTER/index/trigger/backfill/seed tail; затем:5561 active-group checks:987–991 в ещё двух engine.begin. Это несколько commits, не одна атомарная startup transaction.|
| Seed |main:146–188: seed_data; timezone backfill; perimeter lazy DDL; app registry; info seed; interrupted channel logs UPDATE. Есть собственные commits и swallowed warnings. Seed_data:97–145 не swallowed; timezone/perimeter/apps/info ошибки могут не остановить startup.|
| After preparation |main:260–337 chat manager.start и8 create_task: channel,digest,tasks,mail,prices,onec-read,projection,intake. Product/OAuth/managed OFF их не отключает.|
| Chat manager |chat_ws:43–57 запускает presence/listener tasks; :90–109 создаёт presence table/index и очищает stale rows под отдельным lock key2; :138 direct asyncpg connection. Это отдельный DDL/runtime owner, не тот же startup lock.|
| Ready |main:676–798 optional budget + unconditional Pulse + archive/index/trigger checks + upload file write/delete. Prod дополнительно требует mount. Ready не вызывается перед scheduler code и не заменяет startup gates; это самостоятельный request handler.|

**Marker edge:** при managedOFF completed prod marker возвращает управление до
`create_all` и Pulse guard, после чего lifespan идёт к chat/jobs. При ON budget
precheck остаётся до marker и проверяет только реально applied revisions; на
known prefix1/2 он не требует catalogue неприменённого0003. Поэтому такой marker
не является универсальным Pulse admission proof даже при ON. Readiness позже
может отказать503, но это не предотвращает уже запущенные loops. Это source
characterization, actual reproduction не выполнялась.

**Rollback edge:** owner migration transaction может быть атомарной; полный
legacy prepare содержит несколько committed phases. Если поздний seed/active-group
check упал, marker ещё может отсутствовать, но ранее committed DDL уже остаётся.
Обещать общий rollback всей подготовки нельзя. Negative gate data-preservation
проверяется до первого DDL/DML; поздние failures требуют отдельного recovery case.

## Prerequisites и реальное покрытие прежней fixture

Literal10 список из `pulse_view_role_schema_support:10–31`:
companies, users, organizations, eco_apps, eco_company_apps, partner_clients,
partner_installations, calendar_events, company_roles, pulse_views. AST FK graph
в JSON подтверждает замкнутые literal single-column FK внутри списка, включая
calendar self-link; composite constraints и SQL functions проверяются отдельно.
Источники classes: models:40/81/392/1182/8226/8263/11297/12425,
models_partner:19/41. Нужна полная форма родителей, не только необходимые verifier
колонки: `checkfirst` потом не исправит остальные поля существующей таблицы.

Принятая B fixture **вручную** создавала phone function и эти10parents через
metadata subset/checkfirst=False под lock после emptyCore assertion; затем
runner1 created/2 adopted/3 created, catalogue read, DROP Core. Она намеренно не
импортировала main. Не было real main fullprepare, полного legacy tail/seed/jobs.
Новая production phase не должна копировать test-only metadata subset как общий
обход `create_all` guard.

## V3: явная полнота source coverage и владелец calendar counter

ROOT `msg_d13d44f440ea` независимо подтвердил ordering/marker и запросил эти
**report-only** поправки. V2 сохранён byteexact в `report-v2/`; MD SHA
`9c9b5aee4309d3342b2a24b3aaf11385839266968de47885ad9ea6225fbcc0d4`,
JSON `78249d3df386525d7f89f818225a553106088bdf8e18651ac0ea8b1d67543440`.

У исходного `freeze_source.allowed` substring-фильтр secret исключил
`app/services/mail_secrets.py`. Это **исходный Python, не credentials**. Отбор503
app files и979 AST modules V1/V2 не был full app/full repository audit. V3 включает
отдельный full-byte/AST review пропуска: SHA `5d145e4baeeff682648316fb94b65b891f14d94dafaeefffd67f8a4ea9091dc6`,
4893bytes/86lines. Manifest/exclusion provenance и corrected fullapp504
в JSON. Будущий actual full-source freeze обязан включать все tracked own source,
включая такие имена; исключать реальный .env/credential data только по точным
reviewed paths/типу, а не словам secret/credential. Вне server selection весь
репозиторий/фронт/third-party source не объявляется разобранным AST.

Source import chain: main:42 → mail_router:26 → mail_secrets. В самом модуле
только stdlib top-level imports/logger/constants/function definitions; app/config/
DB imports и DDL/socket/startup calls не найдены. `_key:24` и `password_of:77`
читают имена env **при вызове**, encrypt/decrypt импортируют Fernet лениво:38/48.
Worker эти функции/модуль не исполнял и значений env не читал. Callers mail router,
mail_intake:356/380 и mail_send:128 перечислены в JSON. Это source reachability,
не proof успешной почты/безопасности key handling; внешняя доставка запрещена.

**Fresh Calendar должен принадлежать0002 по управляемой части.** Новый parent SQL
берёт legacy20-column shape из immutable source
`tests/schema_gate_history_legacy_models_20261031.py` full SHA
`f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e`,
CalendarEvent:11297–11380, class-source SHA `91523a8f5a4ef2ebfef74ebf7159e9dd073bdf55b57c70606df79cef33096ca1`.
Stdlib AST подтвердил ровно20declared fields в том же порядке, что frozen
0002_calendar_contract. Никакого legacy model import/injection в production.
Новый explicit artifact создаёт literal predecessor SQL, **без** protocol_sequence
и ck_calendar_event_protocol_sequence. Existing frozen0002 SQL SHA
`28d296c60bb1fa04534b2871febf8acd4163253156e6e00871fc6e5bad9b5835` единственный creator counter/check.
После1created →2created →3created проверяются неизменные frozen contracts.
При upgrade уже canonicalcounter допускает2adopted с прежним explicit ack/time/
source/catalogue proof. Старый B10parents proof с2adopted остаётся историческим,
не expected fresh production path. Fresh/prepared profile имеет именованные
before0002/after0002 transitions, без параллельного managed-column owner.

Exact PHONE_FUNCTION_DDL должен быть создан до users с generated expressions:
phone_e164.py:32, file SHA `02556ab614fe3ece60bbe4f216fec5b8eceb9b118cb976c20acc3df5cf5a8c0e`,
SQL-literal SHA `4560f24aea6a08a62d24b9768b2e64aca64bacb5e420547179228659d6869d2b`. users.phone_mobile_e164/phone_office_e164
сохраняют stored phone_to_e164 expressions (models:127–130); function source,
IMMUTABLE/PARALLEL SAFE/owner/ACL входят в явный artifact contract. Это prerequisite
source contract, не разрешение менять search_path или подменять функции runtime.

## V2: exact fresh и prepared profiles для повторного старта

ROOT `msg_d8fc8005070b` разрешил report-only corrections; production/runtime GO
ещё не дан. V1 сохранён в own ignored `report-v1/` с исходными полными hashes:
MD `f0e8db52c6652f3dc7c0f5698c104d16867f96fb56812154844529eeaf701ea5`,
JSON `d915077d2977e2f160b3469d9c4cc07be2010ee490d10976c65895ecb3816830`.

Предлагаемые имена profiles: `core_prerequisites_v1.fresh_exact` непосредственно
после explicit parent+revision phase и `core_prerequisites_v1.prepared_root0e9b_v1`
после **полного** legacy prepare. Это пока design names, не принятые catalogue
snapshots. На повторе запрещён fresh SQL; проверяются весь known applied prefix и
точный именованный prepared profile. Нельзя ввести «любые extra columns/defaults/
indexes/ACL допустимы» ради green. Вне выбранного versioned profile drift отказывает.
Full expected profile и его bytes надо независимо freeze до actual acceptance;
измеренного post-tail catalogue сейчас нет.

Source-backed transition list относится к database.py SHA
`30c01b44669729b0bc19210b44205092f61040aed9c1d5334c3a6f5feac106ec`.
В JSON сохранены67 полных SQL source-operation candidates с line/hash:66 literals,
один incomplete f-string prefix заменён двумя exact loop expansions away_from/away_to.
Это не67 фактических изменений: большинство `ADD/CREATE IF NOT EXISTS` может не
сделать ничего, если полный fresh model-shaped parent уже содержит объект.

| Table / source | Только конкретно названные операции для будущего profile |
|---|---|
| users:95–106,5550 |stored generated phone_mobile_e164/phone_office_e164 varchar16 на exact phone_to_e164; partial indexes ix_users_phone_mobile_e164/ix_users_phone_office_e164.|
| company_roles:158–159 |chat_scope varchar40 и app_roles JSONB, nullable/no server default по этим ADD; existing определение не заменяется автоматически.|
| users:2269–2303 |away_from/away_to DATE; email_notify JSONB; station_pin_hash varchar255.|
| companies:2290 |cloud_api_key varchar128 UNIQUE, ADD only; уже существующую неверную уникальность это не исправляет.|
| organizations:2528–2555 |full_name500; okpo20; legal_address/actual_address TEXT; phone100; email/director_name/director_position/accountant_name255; vid40,prefix10,reg_date20; okved/oktmo/okato/okopf/okfs20; registration_cert300;ifns_code10,ifns_name300;pfr_reg_number/fss_reg_number30,fss_subordination10;postal_address TEXT;fax100,cashier_name255. Exact columns перечислены в JSON, дополнительные имена не разрешаются.|
| users:2578–2582 |is_superadmin BOOLEAN NOT NULL DEFAULT FALSE; reset_token_hash64/reset_token_expires TIMESTAMPTZ; explicit company_id DROP NOT NULL.|
| users:3121–3127,4281–4282 |last_seen_at TIMESTAMPTZ; mail_only BOOLEAN NOT NULL DEFAULT FALSE;avatar_url300;phone_mobile/phone_office40.|
| organizations:4390 |idx_organizations_company(company_id), ordinary source index.|
| calendar_events:5176–5188 |ix_calendar_events_span(company_id,starts_at,ends_at); DROP/ADD named ck_calendar_event_span CHECK(ends_at>starts_at); между отдельными transactions сохранность OID не обещается.|
| users/companies:5213–5220 |tz varchar64 NOT NULL DEFAULT Europe/Moscow; users work_start/work_end TIME NOT NULL DEFAULT09:00/18:00. ADD does not change an existing wrong default.|
| calendar_events:5235–5244 |recurrence JSONB,recurrence_until DATE,series_id UUID self-FK CASCADE; partial ix_calendar_events_series(series_id) WHERE series_id IS NOT NULL и ix_calendar_events_recurring(company_id) WHERE recurrence IS NOT NULL.|
| users:5312–5317 |calendar_feed_token varchar64,partial UNIQUE users_calendar_feed_token_uq(calendar_feed_token) WHERE IS NOT NULL;task_notify JSONB. ORM unique index и этот named partial index различаются.|
| users:5520–5525 |totp_secret TEXT;totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;failed_logins/token_version INTEGER NOT NULL DEFAULT0;locked_until TIMESTAMPTZ.|
| eco_apps/eco_company_apps/partner_clients/partner_installations/pulse_views |Отдельного прямого ALTER из этой static table-specific selection не найдено; это не разрешение на изменения их defaults/ACL/columns. Incoming FKs от полного metadata и dynamic SQL требуют exact full-profile verification.|

Неизменяемые named invariants: `NS-owner-origin-v1`, `PHONE-source-computed-v1`,
`V1-partner-budget-journal-exact`, `V2-calendar-managed-and-legacy`,
`V3-pulse-parents-child-exact`, `REST-parents-full-profile-v1` (контракты в JSON).
Они сохраняют exact owners/default ACL, PK/UK/FKs/internal triggers, типы/nullability,
phone source и frozen revision checks. В частности, legacy transition profile
не разрешает обход protocol_sequence default/check0002, parent unique0001 или
Pulse child ACL/PK/FKs0003. Whole-app legacy schema ownership не заявляется.

## DDL/CLI/bootstrap callers и доставка

Просмотрены все tracked собственные text candidates Ledger и366 Deploy text files;
общие matches, включая docs/comments, перечислены с hash/lines в JSON. Приватные
данные из Deploy в публичный отчёт не перенесены. Реальные категории разделены:

- Native entry/preparation: `main.py`, `database.py`, `seed.py` и postseed calls.
  Lazy DDL: perimeter, app_registry, analytics_cache, charge_mart, edge_moves,
  phone function; chat presence после prepare. `models.py` SQL-looking match
  сам по себе не объявлен действующим writer.
- Explicit managed owner: `schema_migrations/runner.py`, check/apply/plan;
  default `--revision0001` намеренно строгий, unknown/newer history отвергает.
  Новый sequence consumer обязан explicit knownhead/prefix API; нельзя заменить
  bounded reader slicing или default1→latest для прежних клиентов.
- Manual scripts: `smoke_full_sync.py:60` вызывает настоящий create_all;
  `pull_cb_stock_dev`, `pull_cb_revaluation_dev`, `pull_cb_writeoff_dev`,
  `pull_cb_inventory_dev`, `pull_cb_transfer_dev`, `enrich_cb_nomenclature_dev`
  передают Base.metadata.create_all в run_sync напрямую. Они не становятся
  управляемым bootstrap только от этого proposal; запуск исключён.
- Alembic `env.py`/`alembic.ini` описывает drift audit/stamp tooling, схема по-прежнему
  создаётся app. Ни stamp, ни новая вторая migration authority не предлагаются.
- Deploy install создаёт stack config; provision запускает Compose и ждёт health.
  Shared support init: creates namespaces/extension/path/default privileges,
  затем внешний mounted Support init SQL. Его фактический content/image неизвестен.
  Onprem bootstrap ставит delivery stack, не содержит принятую0001–0003 chain.
  Compose использует готовый backend image; verification проверяет HTTP availability,
  не гарантирует применение ревизий. schema-sync/manual SQL существует отдельно,
  это не migration runner и не доказательство свежей сборки Core.
- Production Dockerfile source копирует schema_migrations целиком, .dockerignore
  не исключает пакет. Candidate image tools также копируют пакет, но frozen старые
  image/main harnesses на иных pins нельзя запускать как доказательство ROOT0e9b.
  Build/push/install/image inspection/copied-runtime imports здесь NOT RUN.

**Условие ACL template:** executor init — роль POSTGRES_USER; `FOR ROLE` указывает
Core creator; последующий CREATE в приложении/runner должен идти именно Core owner.
Grantee — подставленный POSTGRES_USER. В declared Support service этот grantee
отличается от Core creator; если это реально разные роли и соответствующий default
ACL действует для Core tables, новые объекты получают дополнительные grants.
Frozen0001 требует default relacl IS NULL (также parent), Pulse0003 owner-only ACL.
Если grantee=owner, redundant grant нельзя автоматически считать nonNULL ACL.
Source не измеряет defacl/relacl. Оба профиля включены в prospective actual matrix.
**Не предлагаются** изменение frozen ACL policy, автоматический revoke/grant/default
privilege reset или каталожный repair. Shared-template профиль с лишними grants
нуждается в отдельном ROOT решении о поставке/ACL после actual catalogue receipt;
его нельзя назвать принятым deployment profile только после canonical synthetic PASS.

## Один bounded implementation package для review ROOT

Предлагается **явная prerequisite phase внутри существующего migration owner**,
sequential0001→0002→0003 и раннее startup admission, затем полная real-chain приёмка.
Это достаточно для проверки настоящего пути при canonical owned Core profile;
helper-only зеленый прогон не принимается. Реализации сейчас нет.

Предлагаемые изменения (требуют нового scope ROOT):

1. Existing `schema_migrations/runner.py`: public
   `async execute_sequence(config, *, target_revision, fresh_prerequisites=None,
   legacy_sent_before=None) -> dict`; explicit CLI bootstrap mode. Existing
   `execute/check/apply/plan` default0001 остаётся прежним. Не вызывать execute()
   с новым connection под уже занятым owner lock: это self-wait.
   Перенести общее mutation body в существующем owner, без альтернативного runner
   и копии private verifier. Source/target checks до network; одна owner connection,
   прежний session lock434532,1; recheck после lock; одна transaction для fresh
   prerequisite+1..3; cancelled/error rollback, shielded close. Upgrade читает весь
   verified known prefix, затем только отсутствующие successors до explicit target3.
2. NEW `schema_migrations/bootstrap/core_prerequisites_v1.sql`,
   `.contract.json`, `.manifest.json`, `core_prerequisites.py`: frozen version1
   literal10 full parent definitions и exact phone function. Calendar parent при
   этом использует frozen legacy20-column shape, без protocol_sequence/check;
   только existing0002 создаёт counter. Fresh ожидает1created/2created/3created,
   canonical upgrade может2adopted по прежним acknowledgement/catalogue checks.
   Hash each artifact/
   verifier/source dependencies до import/connect; это bootstrap source artifact,
   **не** задним числом registry revision0000 и не fake journal stamp.
   Для fresh нужен явный selector. DB/role/PG16/path/owner/schema privileges,
   отсутствие Core relations/routines/occupied names/types проверяются под owner
   lock; namespace-generated types/extension objects требуют exact allowlist.
   Канонические defaults/constraints/FKs/indexes/ACL проверяются до/после.
   No Base metadata discovery, no filtered create_all authority bypass.
   На repeat3 fresh SQL не исполнять; принять только именованный versioned
   prepared catalogue profile и все strict known-prefix checks (подробно ниже);
   partial arbitrary Core
   не принимать за свежий и не «чинить». Namespace/edge/extension admin-owned.
3. Existing main/database/schema_version_gate: public offline source preflight
   перед первым startup checkout/lock; read-only namespace+Core Pulse admission
   перед marker и repeat admission под startup lock. Budget preflight продолжает
   early OFF/no I/O и прежние URL/TLS/expected identity semantics. Для legacy fresh
   explicit public не требовать child до штатного ORM provisioning. После preflight
   вызывается прежняя полная `_prepare_database`, без пропуска DDL tail/seed.
   Core catalogue checks не отключаются; в lifespan нет autoapply/stamp/grants.
4. NEW ROOT-only `tests/core_bootstrap_sequence_approved.py` и
   `tests/core_bootstrap_sequence_cases.py`: actual main preparation/lifespan/
   readiness и реальные catalogue/data assertions, independent immutable archives,
   rollback/refusal/repeat. Старые tests/fixtures/artifacts остаются byteexact.
   main/config public flags не добавлять только ради теста: terminal stubs ставятся
   **до imports** только на внешних chat/jobs sinks. Они записывают факт достижения,
   не исполняют ни одного job. Нельзя подменять prepare/create_all/gate/SQL/catalogue,
   Base metadata или seed success. Product child policy registration реальная.

Конкретный prospective implementation состав10files (от clearledger/server):

- `schema_migrations/runner.py`
- `app/database.py`
- `app/main.py`
- `app/services/schema_version_gate.py`
- `schema_migrations/bootstrap/core_prerequisites_v1.sql`
- `schema_migrations/bootstrap/core_prerequisites_v1.contract.json`
- `schema_migrations/bootstrap/core_prerequisites_v1.manifest.json`
- `schema_migrations/bootstrap/core_prerequisites.py`
- `tests/core_bootstrap_sequence_approved.py`
- `tests/core_bootstrap_sequence_cases.py`

Models/config/deps/Dockerfile/прежние tests сюда не входят. Это список для review,
не текущие edits; общие пути framework требуют согласования ROOT с владельцем.

Точные новые имена пока **proposal**, не runnable интерфейсы. ROOT согласует
framework change с владельцем до implementation. Для inherited noncanonical ACL
выбран bounded refusal до DDL; поддержка такого delivery profile остаётся явным
условием release review, не скрытой сменой grant policy. Frozen0001/0002/0003,
manifest registry, V1/V2/Pulse contracts/checksums и accepted old test bytes
сохраняются. Ни generic Basecreateall bypass, ни смена default managed/product flags
не нужны. Существующие lazy/manual owners не объявляются автоматически единым owner
всей legacy schema; новый bootstrap mutation имеет одного прежнего владельца/lock.

## Фальсифицируемая матрица

Ниже **49 prospective IDs**, группы6+6+9+9+6+3+6+4. Actual0, результат каждого
NOT RUN. Подварианты негативов требуют полного ID expansion и новых group counts
при implementation freeze; сейчас это source design, не frozen runnable case list.
Точные source-chain references для каждого ID есть в JSON. Реальный current
characterization сохраняется отдельно от candidate desired behaviour.

| ID | Проверяемый критерий / вопрос |
|---|---|
| CUR-empty-core-off | Пустой owned Core/edge, managed OFF; actual main preparation отказывает на Pulse parent до PHONE/Base DDL. |
| CUR-empty-core-on | Тот же target, ON с корректными expected identity: history unapplied, до marker/DDL/seed. |
| CUR-public-off | Настоящий legacy explicit-public fresh/repeat через полную preparation chain; результат UNKNOWN до ROOT run. |
| CUR-marker-core-off | Prod-style completed marker + missing/drift Pulse: текущая ветка return обходит create_all; зафиксировать jobs/preparation boundaries. |
| CUR-template-distinct-grantee | Воспроизвести FOR ROLE Core-owner default grant другому Support-role, creator=Core-owner; измерить actual defacl/relacl и штатный отказ. |
| CUR-template-owner-grantee | Контроль executor/FOR ROLE/creator/grantee=owner; не предполагать nonNULL relacl при redundant owner grant. |
| FRESH-canonical-core | Ни одной Core relation/function, admin-created namespaces/extension, canonical creator defaults; explicit owner bootstrap → реальный _prepare_database_once. |
| FRESH-repeat | Повтор нового command и полной подготовки: exact catalogue/history/sentinel rows без дублей. |
| FRESH-nonempty-refuse | Любой чужой Core relation/function/type/occupied reserved name: fresh-only artifact не выполняется, untouched snapshot. |
| FRESH-artifact-rollback | Ошибка после prerequisite SQL/до0003: одна owner transaction откатывает новые Core objects/history; namespaces сохранены. |
| FRESH-missing-edge-extension | Preflight выявляет обязательную внешнюю schema/extension capability; никаких admin grants/extension install из application. |
| FRESH-canonical-parent-contract | Все10parents: exact columns/defaults/PK/UK/FK/index/ACL/phone-function; не минимальные stubs и не metadata bypass. |
| UPG-unversioned-adopt | Полный immutable legacy Core с корректной Pulse table/history absent; явное adopt1→2→3, data parity. |
| UPG-prefix1 | Проверенный known prefix1 и реальные legacy parents: apply2 с явным acknowledgement, затем3, полная preparation. |
| UPG-prefix2 | Проверенный prefix2: только3; ни check1 на newer history, ни truncation. |
| UPG-prefix3 | Проверенный prefix3: read verify всех применённых, no migration DDL, full prepare. |
| UPG-pulse-created | Корректные parents/0002, Pulse child отсутствует: создаёт только existing0003 owner. |
| UPG-pulse-adopted | Populated canonical Pulse child:0003 adopted, associations/ownership bytewise logical parity. |
| UPG-head-repeat | Новый sequence explicit head повторяет3, старый defaultCLI1 по-прежнему отказывает на rows2/3. |
| UPG-calendar-cutover | Actual old calendar without counter; bound/time/legacy ack mandatory, prior catalogue preserved. |
| UPG-foreign-parent | Неполные/чужие prerequisites в upgrade не достраиваются fresh artifact и отказывают до owner DDL. |
| REF-missing-core-public-decoy | Configured core/public при missing Core и одноимённых public relations: отказ без fallback. |
| REF-visible-public | Core существует, но visible foreign public table: namespace guard отказывает до Base DDL. |
| REF-unknown-future | Unknown/future row не срезается; полный bounded known prefix проверяется. |
| REF-gap-checksum | Gap, duplicate/ordinal/parent, artifact/contract/predecessor hash: refusal and data/history preservation. |
| REF-source-drift | Bootstrap source/manifest/SQL/contract/verifier tamper: отказ до connect. |
| REF-owner-actor-action | Owner/actor/action/app_commit/runner_format drift; отдельные validly persisted negatives, SQL CHECK refusal не выдавать за persisted gate case. |
| REF-catalogue | Applied budget/calendar/Pulse shape/PK/FK/default/trigger/index/ACL drift: отказ после catalog SELECT, до writes. |
| REF-default-acl | Noncanonical inherited defaults для creator: отказ explicit fresh command до DDL; исходные privileges не исправлять автоматически. |
| REF-wrong-marker | Completed marker не должен скрыть Core catalogue/history refusal в кандидате. |
| CFG-off | Все прежние product/OAuth/docs/budget flags OFF; managed OFF no gate I/O, Pulse Core guard остаётся обязательным. |
| CFG-identity | Wrong expectedDB/user/namespace/source target vs actual PG identity: refusal; safe errors без DSN. |
| CFG-url-options | Query/TLS overrides/fragment/driver invalid: не silently discard; до connect там, где config можно проверить offline. |
| CFG-no-port | Существующая normalisation default5432 сохраняется; этот positive проверяется offline/isolated, реальных5432 connections нет. |
| CFG-real-path | Actual search_path/core/public and missingCore explicit-public predicates; schema_translate_map не добавляется. |
| CFG-source-before-lock | Полный startup candidate: source/config preflight перед acquisition existing startup lock/первым socket; DB drift требует SELECT. |
| TX-readwrite | Native borrowed actual TX/options/search_path/isolation сохранены; последующий sentinel DML откатывается caller. |
| TX-readonly | REPEATABLE READ/readonly snapshot и caller-owned refusal без BEGIN/SET/COMMIT/ROLLBACK дополнительных соединений. |
| TX-owner-contention | Один existing pair434532,1; concurrent new owner/startup не создаёт split-owner/self-wait, lock timeout leaves data unchanged. |
| LIFE-full-prepare | Native main _prepare_database_once/create_all/seed/postseed/marker/readiness; не заменять prepare/DDL/gates fake results. |
| LIFE-rejected-no-seed | При негативном guard snapshot до/после: no business DML, no new marker, no seed/apps/info/channel repair. |
| LIFE-marker-repeat | APP_ENV=prod synthetic HOSTNAME: real marker CREATE/read/insert/repeat + native catalogue precheck before marker return. |
| LIFE-no-jobs | Terminal external stubs BEFORE imports для chat manager start/stop и восьми run_forever; capture reached/unreached, ни одной coroutine job не исполнять. |
| LIFE-readiness | Native readiness schema/index/trigger checks и private upload file probe; missing/drift503, canonical200; prod mount predicate отдельно, без mount worker. |
| LIFE-cleanup | Dispose all engines/raw listeners; actual sameDB relation/client/lock/source-after receipts и ordinaryDROP owned DB. |
| REC-old-binaries | Независимые immutable ce94e2bf30c0676208b1d70c5c135fe91d1a23f2 и5ce5779b20151a8d04de7d3a1681d1862a80d9dd archives с manifest: old ORM/sender coexistence, не filtered current metadata. |
| REC-old-sender-calendar | Old sender/new counter default/bound/replay: наблюдать реальные persisted calendar rows и сообщения terminal sink; внешней доставки0. |
| REC-synthetic-restore | Bounded dump owned syntheticDB → ordinary drop/recreate ТОЙ ЖЕ dedicated DB → actual restore → native preparation/readiness/data+catalogue parity. |
| REC-crash-and-downgrade | Cancel/owner failure и повтор; oldbinary startup/rollback compatibility UNKNOWN пока отдельные actual old archives не исполнены; восстановление не равно image rollback. |

## ROOT preflight, команды и ресурсный план

Сейчас допустимо воспроизвести исторический selected source proof (его exclusions
нельзя считать full-source approval policy; V3 supplement в JSON обязателен):

```sh
git rev-parse HEAD
git diff --name-only 0e9b923106796c9f278d6e9ef5f813eeaa91ce66
/home/mag/.local/bin/python3.13 -I -S -B .artifacts/core-bootstrap-sequence-20261031/freeze_source.py
```

До любого future actual ROOT должен независимо freeze **новый полный состав**:
app/tests/schema/bootstrap/tools/deps/helper и этот exact integration ancestry;
full byte manifests, executable/runtime/library inventories, source-before/after,
полный expanded ID list/group counts/argv/env/target caps. Old C3 wrapper намеренно
не принимает новый composition pin: не править его frozen hashes ради запуска.
Для новых wrappers выбрать актуальный ROOT executable
`/srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python`
только после independent inventory; наличие пути не доказательство готовности.
Expected77 dependencies из C3 можно использовать как comparator, не как measured
current installed baseline. Не ставить/обновлять dependencies worker.

Предлагаемая ROOT command contract, **пока не исполнимая**:

```text
<ROOT-pinned-python> -I -S -B <own server>/tests/core_bootstrap_sequence_approved.py --execute-approved-core-bootstrap-sequence-tests
```

Новый wrapper до app/driver imports требует exact argv+approval switch, synthetic
HOME из passwd, empty0700 cwd, clean allowed env, APP_ENV=test (marker case отдельно
synthetic prod), synthetic HOSTNAME/SECRET_KEY/company, OFF product/OAuth/docs/
budget flags и per-case managed OFF/ON с explicit expectedDB/user. Никакого real
config/.env/vault. DATABASE_URL=TEST_DATABASE_URL — ровно один dedicated target
`api_core_bootstrap_sequence_test_20261031`, numeric127.0.0.1:33546; ни другого host,
port, database, query/fragment, ни дополнительных connection kwargs. Fresh owner
и caller path/options задаются явно fixture, не как silent fix gate configuration.
План предусматривает root-created **namespaces/extension only**, не10parenttables;
parent relations обязан создать reviewed explicit owner phase.

Предлагаемые раздельные owned0700 roots вне app/tests:
`/srv/projects/api-modernization-test-env-20261029/core-bootstrap-sequence-empty-test`,
`core-bootstrap-sequence-test-uploads`, `core-bootstrap-sequence-test-scratch`,
`private-core-bootstrap-sequence-test-20261031` — последние три в том же parent.
Проверить nonnested/no symlink/uid/cwd/TMPDIR/empty, не чистить чужие roots. PG33546
собственность/availability/ограничения подтверждает ROOT. Не создавать вторую БД:
synthetic restore сохраняет дамп и переиспользует **тот же** owned DB после ordinary
DROP/recreate. Runtime network guard допускает только его loopback PG, deny external
HTTP/DNS/mail/SSH/subprocess/jobs/listen; узкое исключение approved dump/restore
tools требует exact tool binary hash/argv/target. 16 прежних PG sendmsg controls
и source-after/dependency inventory сравниваются, а не объявляются повторёнными.

Сначала независимый source review этого design; затем ROOT отдельным решением
разрешает implementation; затем freeze и negative controls перед functional run.
Сначала6 current characterization cases позволяют проверить source deductions,
но не дают разрешения на остальные43 cases автоматически. При actual обнаружении
нового legacy tail failure сохранить FAIL, остановить affected stage и согласовать
новый concrete scope; не подменять tail mock/helper и не выкидывать failed IDs.

Ресурсы планируются по **полному source path**, не по узкому C3 budget test:
17.17MB selected app source плюс mail source supplement,332 declarative candidates,973 SQL-looking literals database,
несколько DDL transactions/seed/индексов/trigger validation, плюс dump/restore и
immutable archives. Это аргументы для планирования, не измеренный runtime размер.
ROOT default свободного места **8GiB minimum** сохраняется; shared PG baseline
нужно измерить отдельно, значения сейчас UNKNOWN. Prospective caps: DB2GiB,
dump2GiB, WAL delta512MiB, output/log64MiB, uploads128MiB, scratch128MiB,
всего4928MiB; не generic320MiB. Это provisional full-scope worst case,
а не automatic admission requirement для6 current characterization cases. Для
каждой stage ROOT отдельно измеряет baseline и reserves; этапы не уменьшают
обязательные full49/fresh/upgrade/restore цели. Не увеличивать cap после failed attempt без review.
Max owned connections4 (startup lock+preparation+observer/control), one-case180s,
whole run1200s provisional; для full49 matrix возможна необходимость заранее
согласовать несколько явно названных stages, а не объявлять single run.
Нужны online DB/WAL/root-bytes/client/lock/output samplers с подтверждённым источником,
process exit/reaped и ordinary cleanup. PostgreSQL max_locks/cgroup RAM/space также
измеряет ROOT до freeze; defaults не угадывать. Performance baseline отсутствует.

## Границы и следующий review

Public legacy, canonical Core, shared-DB template и другие стеки различаются.
Rushydro выбран только как известный профиль канона; флаги нигде не активированы,
other stacks не исследованы runtime. Backup/image/fullCI/performance/live state
UNKNOWN. Перед любой рабочей schema migration нужны свежие backups и **actual
restore** на изолированной копии; чтение файла/каталога backup этого не заменяет.
Возврат image не откатывает данные и не доказывает старый sender/startup.

ROOT должен отдельно решить admission/marker scope, owner API/артефакт и условный
ACL delivery profile, затем принять новый frozen synthetic package. Эти два
отчёта не разрешают код, runtime, merge, ship, SQL, запуск jobs или rollout.
Общая программа20M+11 active: финальная Core/Support/Auditor composition,
contracts/objects/accounts/clients, live pilot и deprecation остаются обязательными;
source design M16-C4 не закрывает ни M16, ни общую цель.
