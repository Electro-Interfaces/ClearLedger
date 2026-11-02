# Общий владелец фонового прогона каналов, M04-P11

**Реализован `services/channel_runs.py`: один владелец loaded_total, run_summary и background lifecycle. Native adapters сохраняют текущие concrete globals; scheduler обращается к service напрямую.** ROOT принял V2: исходные50случаев прошли одним запуском, failures/errors/skips0. Worker runtime0. V1 27PASS/23FAIL и alias correction сохранены в истории. Общая программа M00–M19+11 остаётся active.

База `f54ff3d4a88cc165d6d40ccc9abcce6a9e3be882`, production base `1c73980f464a0b69e5203b8798d0b307cfb8630d`; собственная ветка `agent/api-channel-run-owner-20261031`. Clean/fetch/accepted ancestry проверены до создания ветки. P10 reports, Pulse/C3/models/schema/main/old tests и ignored proofs сохранены. ROOT semantic acceptance boundary: `msg_90a4934cca49`.

## Владелец и совместимость

Production scope ровно3 файла: новый channel_runs; channels_router только import и3 adapters; channel_scheduler только `_launch` binding/call. Dispatch/ingest/publication остаются в прежнем channel_orchestrator, без второго framework.

Background сохраняет7posargs и defaults(None,False,append), добавляет4 keyword-only optional callables: `session_factory`, `orchestrate_channel`, `loaded_total_fn`, `run_summary_fn`. Каждый default выбирается через `is None`, falsey callable не теряется. Clean defaults импортируют database/models/orchestrator, не routers/HTTP. Native adapter разрешает текущие router globals на каждом вызове; summary adapter передаёт текущий `_loaded_total`. Scheduler явно передаёт свой текущий `async_session_factory`; callerdb не передаётся. Source late-global compatibility сохранена; существующие background patch tests в P10 не найдены и не объявляются доказанными runtime hooks.

Commit ownership прежний: native/scheduler add→flush→commit running log→create_task; owner открывает свою сессию; orchestrator коммитит ingest/publication по прежним веткам; final audit добавляется до finalcommit. `log_audit(actor=None)` реально пишет AuditEvent(system/Платформа) и вызывает dispatch_async ДО finalcommit. Terminal delivery захватывается, audit не подменяется. Exactly-once/outbox для audit не обещаются.

Сохранены best-effort rollback, publication failure rollback/rethrow, отсутствующие channel/log, CancelledError, skipped→partial при наличии log, unmatched override, empty by_station priority, malformed int errors, два отдельных UTCnow, docs_loaded addition. Post-session fuel follow-up сохраняет исходные status/kind/date условия, включая raw failed≠error; его отказ не меняет сохранённый status. Это characterization границы через terminal capture: fuel ingest, COM, станция/касса/1С не запускаются.

Owner не выдаёт самостоятельный tenant/ACL grant: channel/log/source association и разрешение native caller остаются у прежних callers. HTTP `get_owned`, membership/object scope, 404/422 и RunRequest/OpenAPI не менялись. Sourcepair/unknown business inconsistencies в этом extraction не исправляются.

## Source proof

Stdlib-only `.artifacts/channel-run-owner-20261031/source_proof.py` повторно читает immutable Git blobs и рабочий source; app/tests/runner не исполняет. Все3 перенесённых тела reverseAST равны исходным после разрешённых имён/швов; весь остальной router AST и23 definitions byte/AST прежние, native args/defaults прежние. Whole scheduler reverseAST равен baseline; остальные6definitions byte прежние. Из503 старых app blobs изменены только2 разрешённых;501 прежний. Все383 старых tests и24 schema files byte прежние.

Независимый полный AST services tree:334Python service modules;8statements/9router bindings после9/10 в P10. Исчез только scheduler→router background. Семь fuel/NSI bindings отложены, два management chat hooks намеренно сохранены. Recognized dynamic loaders и произвольная runtime динамика разведены: arbitrary runtime callgraph остаётся unknown.

Семь строгих guard functions AST-identical принятому C2 helper `bfb5a258f9f44cedfd82bd4c72c60ea208e28d87564e64f0532ea4cfda059eb5`: tree_digest/private_empty/inventory/install_boundaries/pg_sendmsg_metadata_allowed/sendmsg_metadata_controls/scratch_bound. Глобальный urlsplit сохранён. Новый module alias `channel_run_service` независимо проверен AST: ровно1 import binding, definitions/stores с этим именем0. Только compile/AST/hash/Git выполнены worker. Source assembly однажды отказал на literal_eval exception class Names; исправлен лишь source ID enumerator, история сохранена; runner/app не исполнялись.

## Frozen ROOT package

Freeze SHA256 `a18d56acc1310b8fea22baa27fa92b71e5e9cbb81df64f3c08ec723fe390f0a9`. JSON-сосед содержит полные app/tests/schema manifests, source pins, exact argv/env,50full IDs/14groups и caps. Owned artifacts: `.artifacts/channel-run-owner-20261031/`. После blocking freeze ask исходники/runner/tests не менять без нового ROOT review.

| Источник | Count | SHA256 manifest |
|---|---:|---|
| app | 504 | `4e5a424612b2309a4179d465c4c13207ffcbed14ad5524894421ad891ac85890` |
| tests без нового runner | 385 | `d05723bd137789894e645d47bfb73775e5661f7fc9624183d08cadb45608e017` |
| schema_migrations | 24 | `36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165` |

| Файл относительно server | SHA256 |
|---|---|
| `app/services/channel_runs.py` | `86030033933bbe17655592a1b4839f78cc763784ebd92f7ba2015e13d687bcf8` |
| `app/routers/channels_router.py` | `9bc6fb692423e3215cf926d38892a140b85285fef4606422c6ea71af067bbe17` |
| `app/services/channel_scheduler.py` | `928a25170d6306e416c726a99cde1dc0feecbc79fe6e2a0f6944e88115116d21` |
| `tests/test_channel_run_owner.py` | `4341a0c927e4ce3a151ec25ba353635647adcddb304e7a8d1f102a77eb7acca7` |
| `tests/channel_run_owner_support.py` | `ebb31e310a47250146acbe997b65c8d73884eba945536f40cff383c5cfe7dc14` |
| `tests/channel_run_owner_approved.py` | `96bc549dcd6101b2f3d504dfd7038062e43de77a9d77f4608b291f490c542cb0` |
| `tests/test_channel_failure_rollback.py` | `0c8c1270c52c6aa05de3b8d1b5c3fbfd14d69f27aafec679ffd8c9faec2fb905` |
| `tools/inventory_service_router_boundaries.py` | `7c333ba8b6591a2665751bfa3e3e116db3a244ffa710f85a584ee812218bb283` |
| `requirements.txt` | `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0` |
| `pytest.ini` | `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601` |

ROOT-only interpreter `/srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B`; argument `--execute-approved-channel-run-owner-tests`, exactrunner path вJSON. Candidate77, Python3.13.7/glibc2.36, no .pth/site hooks. Env только explicit allowlist с synthetic seed до cached Settings; `.env`/keys/prod не читаются.

Target только fresh `api_channel_run_owner_test_20261031`, numeric127.0.0.1:33546, synthetic clearledger/api_test_only. ROOT создаёт4 отдельные пустые private0700 owned roots изfreeze env (cwd/upload/evidence/scratch). Pool2/overflow0,2fixture channels≤8; stmt20s/lock2s/idle30s/connect10s/command30s. Parent CPU600/wall650/AS3GiB/FD256/FSIZE2MiB; runner alarm600; scratch128MiB/4096files на root, aggregatecapture≤4000, evidence≤1MiB. Five IPv6 import probes suppression/restore, native ownedPG sendmsg buffers-only и16 metadata controls; env/process/net/write/source/support/scratch guards. Запрещены external network/process/delivery и writes внеowned roots.

SQL capture состоит из двух раздельных streams: SQLAlchemy Engine.before_cursor_execute для prepared paths и raw asyncpg logger; bind values/recipient/content не пишутся. Raw driver `current_database()` — отдельный metadata control. Один raw logger не объявляется полным SQL capture. Commit/rollback — реальные Engine events; native/direct rows и audit проверяются SQL.

Pytest `--noconftest`: новый support plugin создаёт только21 literal FK-closed canonical ORM tables + PHONE_FUNCTION_DDL в fresh public, затем2fixed synthetic companies. Это выбранный test contract, не production bootstrap/migrations/Core parity proof. Ни app.main, ни full conftest, ни lifespan не импортируются. Старый failure test source/assertions неизменен; его dbfixture supplied только новым ROOT plugin. Helper проверяет отсутствие app.main/conftest после выполнения. Scheduler tick/run_forever не запускаются; create_task patch — отдельный module proxy, не глобальный asyncio, captured coroutine await/reap.

## Cases, fixed outputs

| Группа | Count |
|---|---:|
| `test_fixed_totals_and_summaries` | 6 |
| `test_malformed_counters_keep_errors` | 4 |
| `test_sql_lifecycle_fixed_goldens` | 12 |
| `test_early_failure_and_cancellation_keep_initial_log` | 6 |
| `test_native_hooks_and_falsey_service_seams` | 1 |
| `test_native_summary_resolves_current_loaded_hook` | 1 |
| `test_post_session_followup_is_terminal_only` | 5 |
| `test_native_http_refusals_do_not_launch_or_write` | 6 |
| `test_native_request_openapi_and_committed_task_arguments` | 1 |
| `test_scheduler_launch_direct_factory_and_durable_log` | 2 |
| `test_real_registry_file_rows_repeat_and_company_scope` | 2 |
| `test_actual_orchestrator_failure_publication_and_rethrow` | 2 |
| `test_two_separate_utc_instants_are_preserved` | 1 |
| `test_failed_import_does_not_commit_partial_records_with_failure_event` | 1 |

49new+1old=50 primary cases. Полные IDs и exact selectors вJSON; collection/skip/duplicate/subtest расхождения отвергаются. Existing `test_channel_failure_rollback` выбран целиком: непосредственно затронут orchestrator/background failure boundary, partial write rollback/failure fact commit/rethrow; остальные fuel/NSI tests не затронуты и не повторяются ради объёма.

Pure goldens фиксируют0/7/empty-list0/station2/errors text, malformed ValueError/TypeError. SQL goldens проверяют success/partial/error, loaded/skipped/duplicates/errors/events, system audit, dispatch-beforecommit, noforeignwrite, missing log/channel, externally cancelled Task с Event barrier и отсутствие finalwrites. Falsey/native late hooks проверяются без замены tested owner body.

Настоящий nonfuel path только manual_table: Workbook «Общий свод», две вымышленные строки501/999, owned file≤32KiB.501 принадлежит A,999 существует только уB. Actual orchestrator→parser→ingest создаёт2raw+1clean, одногоcounterparty иодинenergy settlement дляA; foreign supplier не создаётся. Повтор даётloaded0, без дублей; docs_loaded7→9→9. Real publication пишет2outbox rows local subscription; terminal send не выполняется. Native HTTP vs direct owner проходят тот же business путь. Controlled-result lifecycle cases отдельно помечены, не выдаются за ingest proof.

Native HTTP проверяет чужой/missing/revoked/scoped404 иinvalid422 без launch/audit; success wire/schema/defaults и commit-beforecapturedtask. Scheduler проверяет company/date/window negative clamp, current falsey factory identity иdurable log перед await actual realorchestrator no-source. Ошибки dispatch/publication и cancel сохраняют прежнюю транзакционную семантику; двеUTC instants проверяются отдельно.

## Actual receipts и границы

V1 actual ROOT receipt `msg_9a36db0293b0`:27PASS/23FAIL из50, pytest17.97s, процессreaped22.261149059s; sourceAfter true, inventory77, metadata16, forbidden0, pg_connect1, SQLAlchemy565/raw400, aggregatecapture1206, normalDROP exit0. Ошибка: новый module import channel_runs был перекрыт существующим native endpoint def channel_runs. V1 code/runner/tests/reports/freeze/evidence сохранены `.artifacts/channel-run-owner-20261031/versions/v1/` с archive-pins.json. Никакие V1 receipts не переписаны.

По ROOT correction authority исправлены только import alias→channel_run_service и3 adapter references; остальных business/handler bodies, scheduler и tests не меняли. V2 сохраняет исходные50IDs и все assertions. Worker runtime0; V2 принят ROOT `msg_0bef64bea552`: один запуск исходных50cases,50PASS, failures/errors/skips/subtests0; pytest7.55s, outer12.036026639s, exit0/reaped. sourceAfter true, inventory77, metadata controls16/16, forbidden/networkattempts0. SQLAlchemy755/raw492, aggregatecapture1564<4000. Ни app.main, ни conftest не импортированы. ROOT подтвердил21canonicalfixturetables, normalDROP exit0, connections0/exists0.

V2 evidence: `.artifacts/root-channel-run-owner-test-20261031-v2-evidence/channel-run-owner-boundary.json`, SHA256 `79353e17431389c3f8d4411f38e872e103f52b921a3d1b35432f3f8d975c84c6`; JUnit50 SHA256 `10880ad49088efd08f64e881d2f4ea5c0163fe3b4a36b0e97a04255d8a752d4a`. ROOT receipts: `.artifacts/root-channel-run-owner-review-20261031/v2/{source-review.json,acceptance.json,process.json,drop.log}`. В V2 сохранены те же50IDs/assertions; это один зелёный50-case receipt, V1 не складывается с ним в новое число тестов. ROOT выполнил source/fixture admission, serialfresh exactDB и cleanup после reap/dispose; worker самостоятельно runtime/SQL/delivery не выполнял. FORCE/GUC/global/foreign cleanup не допускаются.

Remaining: scheduler has_running-beforelock race; другие session advisory locks; source/company/log authority;7fuel/NSI edges;2intentional management hooks; произвольная динамика unknown. M04 и вся20M+11 программа не закрыты; fullCI/securityscan/release/deploy не заявляются.
