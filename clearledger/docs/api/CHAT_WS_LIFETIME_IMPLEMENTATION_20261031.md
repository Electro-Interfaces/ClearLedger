# CP-01: серверный lifetime native WebSocket, implementation freeze

База: `bcb915e8af44c0909e007ac1a55ba2c7954cd43e`, ветка `agent/api-chat-ws-backend-implementation-20261031`.
Dispatch: `task_bab73cc1512a` / `ctx_2b223a35efe9`.
Статус: **SOURCE5 неизменён; ROOT single backend150 и legacy90 приняты раздельно; ROOT report composition принята; TCP / frontend / full CI/API pending; worker application runtime0**.

Реализован серверный пакет в шести разрешённых production paths. ROOT отдельно расширил scope на две старые fixture-only paths и Core same-session delivery seam; вместе с новым test/helper и этими отчётами ровно12 файлов. Нет merge/deploy/live/SSH/контейнеров/installer/Node/SQL/pytest/collection/application imports у worker. Curated15GET=11dual+4user-only/OFF, frontend, Auditor/Support, main/config/settings/models/schema/deps/workflows/версии не менялись.

Принятые source-design `CHAT_WS_LIFETIME_20261031.md/json` сохранены byte-exact. Все106 prospective IDs остаются программой: frontend24 и автоматическое продление JWT **не выбраны** для этой реализации. ROOT принял fresh single backend150 и отдельный fresh single legacy90 на новом OID; lanes/evidence остаются раздельными, без общего зелёного счётчика.

## Владельцы и фактическая реализация

| Path | Изменение |
|---|---|
| `server/app/auth.py` | Existing decoded claims→User/session checks извлечены в `native_user_from_claims`; visit/unknown truthy scp в `native_visit_from_claims`; public `native_claims_context` ставит/reset own ContextVars в finally. HTTP wrapper сохраняет прежние presence/context эффекты и порядок. Никакой новой mail_only/password/login-lock revoke policy. |
| `server/app/services/chat_access.py` | `participant_eligibility` содержит прежний ACL/SQL до audit, возвращает room/foreign. `assert_participant` вызывает тот же eligibility и прежний late-bound audit. Остальные owner bodies/FOREIGN_SEEN/history/insider сохранены. |
| NEW `server/app/services/chat_ws_session.py` | Immutable signed native descriptor, finite exp/type/malformed checks на WS boundary; current native/visit/tenant/channel proofs, short DB scopes, fresh Context child tasks, fixed safe failure reasons. No router import, fake User/machine OAuth, raw JWT/email lifetime metadata. |
| `server/app/services/chat_ws.py` | Обязательный descriptor/proof при connect; guarded direct/background sends, current-proof single-flight, независимый deadline-task и current-proof watchdog, per-socket send/close serialization, tracked cleanup/failure/drain. PG notify format/7900 compaction и presence SQL сохранены. |
| `server/app/services/ticket_communications.py` | ROOT разрешил shared `delivery_room_reference` и `delivery_allowed_in_session`: прежние task/ticket/history SQL, catch и порядок сохранены; public legacy wrapper не создаёт DB session для прежних non-chat/missing/opaque early returns. |
| `server/app/routers/chat_router.py` | Только `_ws_user` и WS endpoint меняют AST; `_ws_can_subscribe` и остальные REST/admin functions byte/AST прежние. Signature decode один раз, optional company_id в том же URL, outer finally от начала регистрации, existing explicit-subscribe/typing hooks. |

Raw query token остаётся credential existing native handshake, не partner OAuth WS. Прежняя query/path logging защита12families/known WS logger formats не редактируется. Descriptor содержит только необходимые verified native fields, не raw bearer/email. Close reasons — fixed constants; PG notify не получает claims/credentials.

## Tenant truth table и context seam

| Ввод | Действие |
|---|---|
| Explicit nonempty company_id | UUID parse; public capture_company_header(explicit value) → existing scope_company_id/assert_company_member; Company existence, actual membership и visit cid проверены. Superadmin existing membership exception сохраняется. |
| Explicit blank/malformed/duplicate selector | Отказ, не скрытая трактовка как omitted; fixed safe reason. |
| Omitted, native visit | Existing current visit validator, visit cid прежде User.primary; company/header binding только после проверки. |
| Omitted, fresh primary | Primary company читается из свежего User; Company/member проверяются заново. Сам default не заменяет отозванное членство. |
| Omitted, no primary, sole membership | Existing sole-member fallback; не произвольный выбор. |
| Omitted, no primary, zero/multiple memberships | WS adapter company=None: только personal/direct compatibility; HTTP scope_company_id400 не меняется. |
| Later resolved company differs/disappears | Не переключать socket в другой tenant; access_changed/close. |

Каждый check — tracked task с `contextvars.Context()`. Внутри auth-owned scoped claims/visit setter/reset, public capture_company_header с явным значением, existing assert_company_member устанавливает object/ownorg scope. Private ContextVars не импортируются за пределы владельца; fake Request не создаётся. Ни ORM User, ни session не возвращаются в socket state. Начальная admission проверка создаётся manager как tracked fresh-Context task до первого await, а policy.open_session работает inline на нём. Отмена/shutdown видит эту задачу ещё до metadata регистрации. Preaccept denial/close также bounded/tracked; cleanup_failed и истинная ошибка close сохраняются для drain/restart. `_ws_user(token, company_id)` сохраняет call contract; optional transport передаётся только нативным endpoint. Periodic room eligibility не пишет audit/notify; explicit subscribe/typing сохраняют старые hooks.

## Deadline, revoke и send ordering

Signed exp проверяется wall UTC и консервативным monotonic remaining deadline до/после ожиданий и перед ASGI send. Native at horizon повторяет strict `>7days`, optional at и legacy tv0; новый JWT TTL не вводится. Backward wall jump не продлевает наблюдённый deadline; forward jump замечается local send guard и независимым deadline task, даже когда current proof ждёт SQL/ACL.

ROOT initial operational targets: C20s, auth/body5s **внутри** managed DB scope, отдельный owned same-task close/cleanup5s — max10s до завершения check; send5s, shutdown-drain5s отдельно. Это targets до measurements, не business TTL/SLA и не обещание мгновенного отзыва. Пока proof/cleanup pending, protected send не получает новый allow. Existing payload-specific task/ticket/history guards вызываются независимо; session-valid не равно room permission.

`managed_db` вызывает public AsyncSession.close на том же tracked task, не создаёт detached shielded __aexit__ closer. Native body cancellation после успешного cleanup остаётся cancellation. Cleanup timeout/interruption становится retained resource failure, не authorization success: safe1013, manager не может затем объявить успешный drain/restart. Все восемь lexical manager DB scopes проходят `_database`, sticky marker сохраняется и для start/is_online wrappers, heartbeat/online/publish/connect/disconnect/finish/stop. Startup/online/heartbeat не скрывают named DbCleanupFailed; publish сохраняет прежний best-effort return со sticky failure. Обычный SQL body failure с доказанным close остаётся прежним fallback, не становится auth revoke или lifecycle-fatal. Listener.close failure сохраняет ссылку/marker и запрещает ложный restart. No private SQLAlchemy/driver internals или global pool dispose workaround. Ordinary SQL/commit/rollback sequence presence/publish прежняя, lifecycle scopes ограничены.

Отдельный recipient payload check работает в tracked fresh Context с public claims/visit/header и реальным native User, immutable выбранным tenant и тем же managed DB scope. Room channels и roomId personal previews проверяются независимо от подписки: ordinary/direct через pure participant eligibility, task/ticket через прежний authoritative owner/history gate без duplicate subject ACL вызова. Native malformed/missing recognized room references fail closed; public legacy opaque compatibility остаётся. Перед send снова epoch/deadline/proof-age/closed; publisher claims/visit/company/object/ownorg не меняются. SQL/User reads у room payload нужны для current subject ACL; connected/pong/presence не вызывают эту SQL проверку, signature повторно не проверяется.

Все прямые connected/pong/denied frames и local/PG background delivery идут через manager guard. После awaited subject check повторяются closed/epoch/subscription/deadline условия. Per-socket lock защищает send/close/registration, global map lock не держится на external I/O. Уже переданные ASGI bytes нельзя отозвать; это явная boundary, не обещание erase или TCP last-byte timestamp. Только полученный router WebSocketDisconnect отмечает peer-terminal факт: redundant ASGI close пропускается, native presence DELETE/last_seen/watch cleanup всё равно выполняются. Истинная неизвестная close ошибка не подавляется и не пропускает cleanup; original failure повторно выбрасывается после cleanup attempt. Timeout cleanup и manager-wide drain — отдельные targets, fault path не объявляется clean. Ошибка tracked current/payload check закрывает socket даже если ожидавший caller уже отменён. Room revoke убирает только channel; background proof не добавляет новые control frames к старым data assertions, explicit отказ подписки сохраняет subscribe:denied.

| Причина | Code/reason |
|---|---|
| Signed/native horizon expired |1008 `session_expired`|
| Current user/tv/visit invalid |1008 `session_revoked`|
| Tenant selection/current authority lost |1008 `access_changed`|
| Known transient current proof/cleanup failure |1013 `temporarily_unavailable`|
| Server shutdown |1001 `server_shutdown`|

Ни одна reason не содержит token/user/email/company UUID/SQL/exception detail. Existing client1008 stop/poll/HTTP401 owner остаётся; auto refresh и client-generation changes не включены. До accept denial может быть HTTP upgrade refusal, а не видимым close frame; реальный wire подтверждает ROOT отдельной lane.

## Fixture-only изменения и прежние assertions

`tests/test_chat_ws.py`: все6 имён и все14 assertion nodes сохранены после нормализации bindings. Formatting case byte/AST прежний. Ранее offline delivery cases теперь честно DB-backed: token_for→decode/current verifier→descriptor/proof→manager.connect; нет production authless bypass. Fake transport по-прежнему не доказательство TCP wire.

| Old literal/result | New fixture binding |
|---|---|
| `user-1`, `shared-user` | `str(native_world.user.id)` — реальный synthetic User |
| `company-1`, `shared-company` setup | `str(native_world.a.id)` / verified proof tenant |
| `chat:room-1`, `chat:room-pg` | `native_world.channel` — actual approved synthetic room |
| `room-1`, `room-pg` payload | `str(native_world.room.id)`; pure formatter fixed literal остаётся |
| asserted `await worker.connect(...)` result | `ws.became_online`, сохранённый фактический return manager.connect, не injected bool |

`tests/test_task_projection_access.py`: только existing Socket.close fixture method и native proof-before-connect setup/try-finally stop в четырёх existing revocation params. Все прежние data/REST/subscribe/delivery/history/search assertions, operators/count/order неизменны. Все другие test functions byte/AST прежние. Никаких skip/xfail/assert weakening/удаления параметров.

## Approved gate reuse и ROOT lanes

Новый `tests/chat_ws_lifetime_approved.py` source-copied с принятого `chat_access_owner_approved.py`; старый helper не меняется/не исполнялся worker. Inventory/private roots/tree/self pins/PG socket metadata controls/network-process-write guard остаются прежними по AST либо строго описанному prefix normalization. Адаптированы только constants/env/self flag/33547 target/groups/source pins/plugin fixture/capture selection; добавлен import-root boundary и backend app.main denial. Проверяемые manager/ACL/task/ticket/send methods не stubbed.

Exact flag: `--execute-approved-chat-ws-lifetime-tests --group backend|legacy90`. Candidate prefix прежний `/srv/projects/api-modernization-upgrade-test-env-20261030/.venv`, SITE соответствующий3.13; ROOT копирует original77 и CPython3.13.7 read-only с теми же абсолютными путями. HOME = actual pwd entry, включая root в isolated executor, не hardcoded mag. Port **33547**, database `api_chat_ws_lifetime_test_20261031`;33546 недоступен этому gate.

- Backend: new authored tests + modifiedsix; `--noconftest`, minimal FastAPI/ASGI/native ORM FK closure; no app.main/lifespan/seed/cron. Real native issuance/current verifier/PG, external Support boundary capture отдельно маркирован, не Support wire proof.
- Legacy90: exact прежний SELECTION/EXPECTED_COUNTS; отдельный fresh serial run с original conftest, import-only app.main/create_all+seed разрешены ROOT. Lifespan/jobstart/realSMTP/COM/delivery запрещены.

Четыре отдельные private0700 own cwd/upload/scratch/evidence до imports; clean allowlisted env, -I -S -B, exact77/no.pth, immutable app/tests/schema/support/self pins; source writes/process/network вне собственного PG запрещены. SMTP/notify traps до fixtures, tested manager transport не подменяется. Source-only expected IDs/counts в JSON; actual collection/выбранные SQL cases и aggregate durations подтверждены ROOT receipts ниже; RSS/per-request SLA и реальный wire этим не доказываются. Worker helper даже --help/collection не запускал.

## Source proof и falsifiable acceptance

Historical freeze1 backend93 source snapshot/manifest сохранён в ignored `.artifacts/chat-ws-lifetime-implementation-20261031/history-freeze1/`: изменившиеся source bytes реконструированы и проверены против ранее переданных SHA. Original JSON payload freeze1 не был архивирован, его прежний SHA `96a5a27c…` зафиксирован отдельно; не заявляется восстановление exact JSON. Current replacement добавляет WS-only numeric decode errors TypeError/ValueError/OverflowError и signed exp/iat/nbf/at/tv malformed/nonfinite/container cases, HTTP policy прежняя.

JSON содержит full selected source manifest (включая mail_secrets.py), exact12 current hashes, all-app AST, changed-symbol anchors и source-only reverse proofs. Для ticket delivery исходный SQL/history body и catch AST совпадают с extracted in-session body; legacy classification сохраняет no-DB early-return контракт. Для HTTP get_current_user и shared assert wrapper реконструкция из extracted bodies даёт прежний AST; protected task body совпадает после разрешённого native setup/cleanup normalization. Все other router REST/admin AST прежние. Every old assertion сравнивается отдельно; no generic «всё совместимо» по одному import.

Backend150 expected cases =144 new +6 preserved fixture cases; все150 IDs и прежние assertions/ожидания сохранены; native SQL Company delete, canonical TaskParticipant и ASGI prefix исправляют fixture setup, inline send связан с той же operationTask ради обязательного barrier; legacy90 остаётся отдельной selection. Теперь150 exact IDs собраны и выполнены ROOT одной принятой серией; legacy90 принят отдельной серией. Final D gaps включены: direct-room revoked participant personal previews и manager user-channel ticket history/live-ACL drop. Source fault fixtures показывают pool state **до** ручного test-owned close; после manual repair checkedout0 считается только уборкой fixture. Для committed writer pool может быть0 до close и не доказывает завершение публичного Session.close. Lifecycle failure/restart prohibition проверяются до ремонта. ROOT real TCP normal-peer-close остаётся обязательным отдельным proof.

Backend expected count и full literal IDs генерируются stdlib AST из authored decorators; это исходная source матрица; её current150 IDs совпали с actual ROOT collection и получили450 passed phase records в одной серии. Legacy90 отдельно, Program106/frontend24 сохранены без переписывания. Requirements mapping у каждого authored test ID в JSON; cases покрывают реальные native identity/tenant/visit/room/task/history, SQL scope/context/clock/idle/current proof, send-close/cancel/cleanup failures, real local+PG delivery. Учитываются отличия fake transport, in-memory ASGI и будущей настоящей loopback wire lane.

Source checks PASS означает только parse/hash/AST/diff proof. Runtime Worker=0. ROOT выполнил обе выбранные свежие serial lanes; отдельный real upgrade/close/nativePG wire этап ещё требует source/admission и actual proof. Если driver не завершает public cleanup, failure остаётся tracked, socket закрывается и tests/drain должны FAIL; неизвестное состояние не маркируется clean. Runtime факты ниже взяты только из ROOT receipt/raw, worker application/helper runtime остаётся0.

## Первый actual ROOT run: не принят

ROOT выполнил **freeze4**, stage `5d26da3876b6`: backend **144 PASS / 6 FAIL**, native/outer exit1,133.22s native и153.404662s whole. Это **FAILED entire series**, не приёмка текущего freeze5. На момент этого failed capture legacy90 и TCP были NOT_RUN; принятый позднее legacy90 указан отдельно, TCP остаётся pending. Raw сохранён у ROOT в `.artifacts/root-chat-ws-backend-source-review-20261031/remote-ws-backend150-v1-native-evidence/`; classification рядом. Stdout SHA `ee6396b05097ecf8b2a392709bfe288f0bd7d402f7c16d65903cdc93f457febc`, JUnit `d10f70abaefaa285fcec9defb4c6fe4a6c2d6684f72143b2758f4320e40136c2`, boundary `dae1046143265e947f2d591dfaece24c4adf353fbdef201f76aa47252c5a3e9e`.

Четыре FAIL — fixture: ORM Company delete загружал отсутствующий DataEntry reverse relation; TaskParticipant отсутствовал в минимальной canonical FK closure (два params); peer-ASGI fixture не добавлял `/api` prefix. Исправлен setup с настоящим Core DELETE+commit+absence assertion, canonical TaskParticipant и тем же `/api`, что у рабочего ASGI case. Guards/ожидания не ослабляются.

Два FAIL показали pool2 вместо прежнего pool1 до manual repair. SOURCE путь: failed-check callback начинал cleanup, disconnect удалял `_sessions`, поздний awaited close возвращал sleep0, пока original cleanup мог держать checkout на UPDATE last_seen. Sampled second-checkout stack raw не содержит; это source-compatible race, а не независимо измеренная attribution. Новый `_closing` registry сохраняет owner до identity-checked DONE callback, stop также joins registry. В обоих existing cases public manager Session wrapper делегирует настоящий PG UPDATE и держит barrier до commit; original cleanup и два late close waiter должны оставаться pending, release — внутри прежнего DRAIN5. После await owner проверяется no-pending cleanup и прежние pool1 до ручного fault repair / pool0 после. Новых IDs/guard bypass/таймаутов нет.

ROOT подтвердил source928/shared15851 и77deps before-after equality, forbidden0,16 metadata controls TRUE,715 CLI reaped, exact positive exit/PID0/cgroup empty-or-gone/native+controller absent и ownPG clients/locks0; удаление только ownCID обычным rm — **recovery, не test PASS**. Полный ROOT rerun freeze5 впоследствии принят отдельно ниже; прежний failure/recovery не переименовывается в PASS.

## Принятые ROOT selected batches — без TCP/full API claim

backend: **single 150 unique IDs PASS**, 450 setup/call/teardown records PASS, errors/fails/skips0; stage `90fd7a6d939d`. JUnit130.938s, outside150.81958309793845s, controller151.83938980754465s; native/outside/controller0. Env22, original77/source928/shared15851 before-after equal,16 metadata controls отдельно, forbidden0, CLI reaped707, native+controller independent absence2, normal removal только own executor; ownPG OID16384 clients/locks0. Это выбранная серия, не whole CI/SLA/SMTP/COM/TCP.

Acceptance: [remote-ws-backend150-v2-acceptance.json](/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-chat-ws-backend-source-review-20261031/freeze5-runtime/remote-ws-backend150-v2-acceptance.json) SHA `62b14152702dbcbc7775bef75e2f3feeec9c266eb483185bfa9a520b97ad7b4d`. Boundary `c5ce2390ebb4d694fd85ac84a38967d35b790886b50356c371e47367d133a72b`, JUnit `974626d5ef7c42a65bcab796a78de79249f37f4a19ce64854465609ca51c4c0d`, outside raw `f5058f39259a0a3bf01e5e12c3a770b32f9d22252b0797b18efde43c06429899`. Все11 raw files прочитаны; path/bytes/SHA и exact IDs в JSON.

legacy90: **single 90 unique IDs PASS**, 270 setup/call/teardown records PASS, errors/fails/skips0; stage `72923c4e74e2`. JUnit46.212s, outside81.85091399005614s, controller82.56189941801131s; native/outside/controller0. Env23, original77/source928/shared15851 before-after equal,16 metadata controls отдельно, forbidden0, CLI reaped355, native+controller independent absence2, normal removal только own executor; ownPG OID25354 clients/locks0. Это выбранная серия, не whole CI/SLA/SMTP/COM/TCP.

Acceptance: [remote-ws-legacy90-v5-acceptance.json](/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-chat-ws-backend-source-review-20261031/freeze5-v5-runtime/remote-ws-legacy90-v5-acceptance.json) SHA `c8d0c2832be7e3152063d423ca11c10f79f18c928495bb88551b8e45496beabd`. Boundary `bc0ba2b8089c28c9a4a0bcf7387c868b2240ff5450a346c5b7524a9e544357a6`, JUnit `974e75393a66a75c28dd1eb11c8726ec465604b5be2ff4a1d11bfa9ff3702c64`, outside raw `4a4982956ac0ba970905bbbb72c6724af076f41fb9894a58471ba7f10390046d`. Все12 raw files прочитаны; path/bytes/SHA и exact IDs в JSON.

Legacy90 использовал fresh own DB same name/newOID25354/newlease и V5 seal `fbeab49f39cc00c131cf47430b4826cb7cef3cc7321c2c49da27fcc61ed3f4e2`. Kernel C0 принят отдельно (12 EPERM/7 positive, inherited filter1→2, R/R), это0 application cases, не часть90. Первое чтение captured shared field локальным ROOT acceptor ошибочно ожидало files вместо entries; исправлен только reader того же immutable capture, suite не повторялась из-за этой ошибки. Historical legacy exit137/60 partial lines остаётся interrupted/0 accepted. Historical144PASS6FAIL не суммируется как294 unique; backend150 и legacy90 не образуют общий whole-API зелёный счётчик.

RealTCP normal-peer / cross-worker PGwire, frontend24/refresh/reconnect и fullCI/API20M+11 остаются pending. Wire message d37d1f9170a5 — только source planning: существующий helper150 с bind/listen/child deny не изменён, новых файлов/admission нет. ROOT принял source/facts report composition и независимый D actual legacy review, msg `5380d8eeb099`; это не TCP/frontend/fullAPI acceptance. D MD SHA `28a99c01fca7c821c6c5d7276166a71e0264eed794a3b889ad21d94007f4d958`, D JSON SHA `3e2a5be4744da9297a9e60e2a7d96ca29732953e033a15b04b73260e46b0af6a`; provenance V1–V5 раскрыт. Minor erratum D MD: одна строка85 captured names должна84 (29 notify.dispatch_async +20 web_push +20 chat_mail +1 email +14 notify_person); raw84/primary90 и остальные выводы не меняются.

## Принятая backend-фаза и отдельные следующие этапы

ROOT/D immutable freeze2 source review завершён (сообщения f597/d0ee/dd56/06cffe), runtime acceptance отсутствует. Freeze2 exact reports/source snapshot сохранён в `.artifacts/chat-ws-lifetime-implementation-20261031/freeze2-backend109/`, ROOT получил свою immutable копию. Исторический freeze3 содержал F01 preaccept carrier, F02 all-owner cleanup/listener failure, F03 observed peer-terminal и final targeted cases. ROOT/D freeze3 source review завершён (06eb8069/5d6ce850), runtime acceptance отсутствует. Freeze3 source/reports exact сохранены в `.artifacts/chat-ws-lifetime-implementation-20261031/freeze3-backend140/`. Freeze4 закрывал listener acquisition/startup race из SOURCE40241/60f: raw actual connection назначается manager до первого awaited setup, setup/startup tasks tracked до await; resource-specific lock не даёт overwrite unproved старого listener; public close bounded/sticky/retained. Generation после stop проверяется после awaited шагов; stale startup не создаёт late monitor/presence jobs, cancellation reaps init children. Это instance lifecycle state, не token TTL/session/product flag. Добавлены actual-PG prospective setup error/cancel/failed close/timeout/replacement/start-vs-stop cases; public raw is_closed измеряется до fixture repair, pool0 не считается raw listener release proof. ROOT дал narrow5-path GO (в owned12) для freeze5 fixes выше; source10/helper/test/code после accepted выбранных ROOT runs неизменны; разрешён только этот facts-only update двух reports. Независимый actual-artifact/report composition review завершён и принят ROOT; разрешён Russian named exact12 commit `[skip ci]`, push только своей ветки и проверка HEAD=origin/clean, затем worker_done в узком scope backend implementation+две selected series. Git-факты сообщаются отдельно после выполнения; Root review final bytes/integration остаётся у координатора. Отдельный realTCP/PGwire этап будет новой dispatch после settlement. Никаких live release/flags/merge. CP-01 целиком, frontend phase и программа20M+11 не объявляются завершёнными этим source freeze.
