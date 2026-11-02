# Приватность capability URL и XLSX, M09 CP02+CP03

**Реализованы два локальных изменения: central logging redaction capability-сегментов и `Cache-Control: private, no-store` у общего XLSX helper.** ROOT принял source preservation/AST proof и один actual запуск146offline cases PASS:438passed phases, failures/errors/skips/subtests0. Worker application/runtime0; M09 и программа20M+11 остаются active.

База `00f081f7e129d3225c7e13ddc0f6a168bcc5a7d0`, собственная ветка `agent/api-protocol-privacy-20261031`, clean/fetch/HEAD=origin проверены до branch. Применены rushydro-space/orchestration, проектный канон и accepted CORE_PROTOCOL_CURRENT. ROOT explicit implementation GO:2existingowners, без дополнительного pre-edit разрешения. Historical reports/ignored proofs сохранены.

## Ровно два production owner

`app/api_access_logging.py`: safe_target, закрытые константы трёх families и необходимое распространение safeU в OAuthAccessFilter. `app/services/export_files.py`: ровно один дополнительный headerKV в xlsx_response. Ни routes/signatures/ACL/tenant SQL/config/main/schema/frontend/deps/versions, ни filename/body/transaction/audit не менялись. Из504old app files изменены только2, остальные502 byte прежние;386old tests и24schema files прежние. Новый тест и offline runner — отдельные files.

## Полный source inventory capability routes

| Method/path | Native function/line |
|---|---|
| GET `/api/doc-share/verify/{token}` | `verify_registration`:94 |
| GET `/api/doc-share/{token}` | `open_link`:144 |
| GET `/api/doc-share/{token}/file/{version_id}` | `download`:187 |
| POST `/api/doc-share/{token}/ack` | `acknowledge`:236 |
| POST `/api/doc-share/{token}/decide` | `decide_by_link`:283 |
| GET `/api/invite/{token}` | `invite_card`:99 |
| POST `/api/invite/{token}/respond` | `invite_respond`:117 |
| POST `/api/invite/{token}/propose` | `invite_propose`:137 |
| GET `/api/invite/{token}/poll` | `invite_poll`:162 |
| POST `/api/invite/{token}/poll/vote` | `invite_vote`:199 |
| GET `/api/invite/{token}/ics` | `invite_ics`:233 |
| GET `/api/work/calendar/feed/{token}.ics` | `calendar_feed`:1413 |

12source operations:5doc-share,6invite,1feed. Source SHA/definition lines каждого route вJSON. GET `/doc-share/verify/{token}` — отдельный token position; он учтён, а не потерян за generic `{token}`. Static `/work/calendar/feed` и POST `/work/calendar/feed/rotate` не маскируются как capability; их прежняя auth-query privacy сохраняется.

## Точная logging policy

1. Raw origin-form path либо HTTP(S)absolute target/referrer с canonical family распознаётся только по source-owned prefix и известной форме suffix. Обозначенный token segment целиком заменяется `[redacted]`; nonsecretprefix/suffix и absolute authority сохраняются. Query/fragment удаляются целиком, включая повтор synthetic credential в произвольном query key.
2. Token остаётся opaque raw строкой: quotes, Unicode и `%xx` не декодируются. `unquote`, HTTP routing, token validation, JWT/DB/ACL здесь отсутствуют. Бounded regex raw spellings трёх exact structural prefixes служит только для fail-closed marker; он не нормализует URL для приложения.
3. Unknown suffix/empty token/control characters/quoted or whitespace wrappers, encoded structural/static ambiguity, userinfo, protocol-relative или иной scheme за knownfamily дают `[redacted-capability-target]`. Это logging-only отказ от target, не HTTP refusal/redirect.
4. Реальная коллизия `/api/doc-share/verify/ack` или `/verify/decide`: GET `verify/{token}` и POST `{token}/ack|decide` имеют разные token positions. Метод отсутствует у safe_target/referrer, поэтому весь loggingtarget заменяется marker; ACL/метод не угадываются. Encoded spelling verify тоже failclosed.
5. Near-miss/case-distinct/unknown family остаётся прежней; прежние OAuth/chat/query правила выполняются после новых правил. Например dot-prefix `/api/./invite/...` и URL, вложенный в query другого ресурса, не объявлены защищённым canonical target. Multi-stage gateway decoding/root_path и arbitrary debug/custom formats остаются unknown, глобальный leak-free сертификат не заявляется.

Existing regexes `_PRIVATE`, `_AUTH_QUERY`, known uvicorn.error formats и install_oauth_access_filters byte/AST прежние. ReverseAST показывает сохранение старой nonstring/query/chat fallback. Static rotate отдельно возвращается в прежний fallback, поэтому query token там не стал виден.

Gunicorn trap устранён в sink: copy(atoms) сохраняет SafeAtoms type/missing/custom-header escaping; safe target записывается в существующий U **и** requestline r, q очищается. f и known `{referer}i` проходят тот же sanitizer, auth/cookie/set-cookie markers сохранены. При отсутствующем U ключ остаётся отсутствующим, SafeAtoms missing atom всё ещё `-`. Остальные logger branches AST прежние; arbitrary error/debug/preformatted/custom outputs не переписываются новым универсальным parser.

## XLSX

В xlsx_response добавлено только `Cache-Control: private, no-store`. ReverseAST после удаления этой KV равен целому прежнему export_files module; все save/body/MIME/disposition/status/filename sanitizer branches прежние.7callers:corporate1/reconciliation1/charge_sessions3/docs2, тела unchanged по app manifest. Их SQL/ACL/audit flows **не запускались** этой offline приёмкой.

Это локальная privacy policy; [RFC9111 §5.2.2.5](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.2.2.5) описывает no-store semantics, не требует этот header у каждого GET и не гарантирует удаление сохранённых пользователем файлов. URI privacy reference — [RFC9110 §17.9](https://www.rfc-editor.org/rfc/rfc9110.html#section-17.9). Filename formatter и его historical RFC5987/browser description не менялись; current RFC6266/8187 статус проверен в accepted source audit. Новых browser/conformance обещаний нет.

Вне delta: CSV/ZIP/HTML/ICS/native FileResponse/store alias/product file generator/proxy caching. Эти две owner functions не создают auth authority и не исправляют WS expiry, tenant/file association или финансовую политику Pulse.

## Offline ROOT selection:146 PASS

123new +23existing offline cases; весь unchanged `test_api_access_logging.py` выбран. Historical25PASS/2wsprotoSKIP включал2wirePASS+2wireSKIP; эти4wire cases не выбраны, не объявлены новым currentPASS/SKIP. Весь test_api_ws_logging_wire.py source/assertions byte прежний; серверы/sockets/processes не нужны для actual Source-format tests обоих backend.

| Case group | Count |
|---|---:|
| `test_all_source_capability_shapes_fixed_outputs` | 48 |
| `test_origin_and_absolute_targets_keep_only_safe_coordinates` | 8 |
| `test_ambiguous_known_families_fail_closed_without_path_decoding` | 19 |
| `test_unmatched_targets_and_static_feed_operations_are_unchanged` | 12 |
| `test_existing_query_authority_policy_remains_effective` | 4 |
| `test_nonstring_target_identity` | 4 |
| `test_actual_uvicorn_http_log_emission` | 3 |
| `test_known_ws_logger_formats_emit_only_safe_target` | 3 |
| `test_gunicorn_U_r_q_f_and_custom_referer_all_propagate_safe_target` | 6 |
| `test_gunicorn_missing_U_keeps_SafeAtoms_missing_semantics` | 1 |
| `test_unsupported_error_formats_keep_existing_boundary` | 4 |
| `test_filter_installation_restores_global_logger_state` | 1 |
| `test_real_workbook_response_private_headers_cells_and_filename` | 2 |
| `test_offline_boundary_denial_controls` | 8 |
| `test_uvicorn_access_record_drops_auth_query_before_formatting` | 1 |
| `test_gunicorn_default_and_custom_atoms_drop_authority` | 1 |
| `test_normal_access_diagnostics_are_preserved` | 1 |
| `test_exact_chat_ws_path_drops_query_independent_of_key_encoding` | 4 |
| `test_chat_ws_noquery_policy_requires_exact_path` | 4 |
| `test_filter_installation_is_idempotent` | 1 |
| `test_gunicorn_safe_atoms_keep_custom_header_and_missing_atom_semantics` | 1 |
| `test_pinned_backend_handshake_log_records_from_source` | 2 |
| `test_uvicorn_error_non_handshake_records_unchanged` | 7 |
| `test_handshake_filter_requires_exact_logger_format_and_arity` | 1 |

Source-only newtests проверяют все12forms ×4rawtoken representations, fixed expected URLs, query/fragment/absolute/encoded/near-miss/static/malformed cases; emitted logging.Handler strings для Uvicorn HTTP/3knownWS formats; настоящие LogRecord +dict/SafeAtoms U/r/q/f/customreferer, missing/quote state и installation cleanup. Никаких настоящих токенов: только fixed SYNTHETIC markers/example.invalid.

XLSX test использует настоящий in-memory openpyxl Workbook, проверяет200/MIME/private header/точный Unicode filename disposition и read-back fixed cells. Не сравнивает ZIP timestamps и не обещает произвольную byte identity разных save. Workbook temporary XML пишет только в owned TMPDIR.

8expected boundary denial controls: socket creation, DNS, process launch, forbidden env mutation, .env read, outside-root write, app.main import и SQL-module import. Все попытки сохраняются отдельно в evidence; ни одна не считается успешной операцией. Acceptance требует8exactcontrolled denials и0uncontrolled. Это не подмена PG success и не общий0denials claim.16PG metadata controls не нужны/не выбираются при SQL0; разрешённого PG target вообще нет.

## Frozen ROOT-only execution

Freeze SHA `63ccd031f3a1705c5464cc0575820fff678f67541d2d8a8a47b1debbac1e2cde`, runner SHA `38da72604035c3d02af225f519d88b5a62d94186e699b7ed12d448ab37be2ba6`. JSON содержит full app/tests/schema manifests, support/dependency hashes,146fullIDs/24groups и exact argv/env. Worker runner/tests/app не исполнял.

| Scope | Count | SHA256 |
|---|---:|---|
| app |504|`e5ea28fc6a7e0ff3181f5f5a64a2d18dfc1ceb9aedda616af53674af34c196ac`|
| tests without newrunner |387|`04f1a70c784a027d4a03a86f2996bc17ca12449bcb163e1c267f0004fd4d3ded`|
| schema |24|`36144e75b41d79b27e5e8d455e963d46deb400968582d6f53983d440344b2165`|

| Changed/retained selected source | SHA256 |
|---|---|
| `app/api_access_logging.py` | `ef1ccd1c140a07cbdafbae45c9e3a2c7b8b889792b4bcdeb3f0fed09e449164d` |
| `app/services/export_files.py` | `0e3bcccdde545aaf443ca7bcf7e04d168be30e961c63699e7567f591cbee9526` |
| `tests/test_protocol_privacy.py` | `869c30f59eb8bae6309779910d3da3756748a8d4909cc853e57980a4a8d22a33` |
| `tests/protocol_privacy_approved.py` | `38da72604035c3d02af225f519d88b5a62d94186e699b7ed12d448ab37be2ba6` |
| `tests/test_api_access_logging.py` | `f95c516a833b7c2605a41b5001470f8738c663fc3cdbbfbc732e8f3479294288` |
| `tests/test_api_ws_logging_wire.py` | `9fa0e5b672df6d55db116cc737ca144be1a02028e2238a472a838b0e4ed2a007` |

Candidate77 Python3.13.7 `-I -S -B`, exact metadata/no .pth/site hooks, pytest --noconftest, no app.main/conftest/Settings/database/SQL modules. Only app/api_access_logging +services/export_files and package __init__ allowed; import guard rejects domain imports. No DATABASE_URL/SECRET_KEY, no .env/real secret env. Four distinct empty private0700roots are literal in freeze env; actual HOME preserved. All sockets/DNS/bind/connect/listen/processes denied; five import IPv6 probes suppressed/restored. SQL0/no DB allocation/cleanup. File mutations confined to owned scratch/upload/evidence; pytest bookkeeping env keys only. Sources/support/dependency pins checked before and after; four guard functions AST-identical accepted P11 template.

ROOT caps:CPU180/wall240/AS2GiB/FD128/FSIZE2MiB/scratch64MiB4096entries/evidence1MiB/capture4000. Runner alarm180. ROOT resource admission/serial execution, exact case/phase/count/no skip/error, global logger filter cleanup and sourceAfter required. Source baseline read/AST/git proof found no unrelated changed files/race. SQL/network wire/main/lifespan/SMTP/jobs/Node never requested in this package.

## Actual receipts и rollback

ROOT receipt `msg_8f01680e38e8`: source review PASS,914old files/exact2prod/reverseAST/4guard identity, exact146IDs/24groups. Один actual запуск:146PASS за1.50s,438passed phases, failures/errors/skips/subtests0; outer2.809576724s, exit0/reaped. SourceAfter всех pins true, inventory77 прежний, noDomainSQL и IPv6 restored. SQL/allowednetwork/servers/wire0;7nativeSQLflows не запускались.

Восемь контролируемых попыток действительно отклонены: socket.__new__,socket.getaddrinfo,subprocess.Popen,environment-mutation,secret-file,outside-write,application-import,sql-import. Uncontrolled denials0. Это8refused attempts, а не blanket0attempts или fakePGsuccess.

Boundary `.artifacts/root-protocol-privacy-test-20261031-v1-evidence/protocol-privacy-boundary.json`, SHA256 `bf1d7ff736c520c7bbdd8b0411ff8bb613c7602ce2489aea6a4f43ae389befaf`; JUnit SHA256 `1d0c929a52475416eb38c032e279d912adbd30d99e9c8cc883bbe5441dbbfc0e`. ROOT acceptance: `.artifacts/root-protocol-privacy-review-20261031/acceptance.json` в integration worktree.

До actual первый ROOT parent attempt ошибся в собственном env-count15 при реальном14; исправлена exact allowlist. Child/app/SQL до этого не стартовали. Это parent preparation issue, не candidate test failure; actual series146 была одна. Frozen production/tests/runner/freeze после review не менялись. Worker выполнил только source/read/receipt audit; runtimeworker0.

Rollback: revert these2 owner changes and newtests/runner/report as appropriate; no data/schema migration, token rotation, source authority or flags involved. Existing WS/query policy, raw historical reports/old assertions preserved. Remaining ingress/debug/root_path/multi-decode and WS session/tenant/financial decisions documented above; fullM09/currentCI/release не заявляются.
