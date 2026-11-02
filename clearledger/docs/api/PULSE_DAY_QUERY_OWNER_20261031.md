# Владелец данных экрана дня «Пульс», M04-P8/M08 · 31.10.2026

**P8 принят ROOT:**77 retained V1 +3 corrective V3 +1 view V4 PASS;
в трёх сериях подтверждён81 уникальный случай. Это scoped acceptance, не единый81-green/fullCI;
M04/M08 и вся M00–M19 остаются активными.

База `5693168397e5c1be4ee424db49ee8ce284d4f49b`, ветка
`agent/api-pulse-day-query-owner-20261031`. ROOT decomposition approval
`msg_bfdabff1a65f` → `msg_75cb55dcbae8`. Worker выполнял только source/Git/AST/compile.

## Граница владельца

services/pulse_day.py владеет полным module-definition fixed-point closure
pulse_day_data: **74nodes /1863 исходных строк**, 28functions/1class/45constants,
из router на5500строк. Это именно общий query owner, не facade/reverse import.
Точный список имён/спанов/deps в closure-before.json и per-node AST hashes в
source-review.json. Перенесены день и три profile branches, card rules/money/plural,
threshold/source definitions, snapshots tickets/access/sales/objects/stations/
status/ops/projects/CC, accounting period/result/tax/date helpers и их constants.

Native router identity reexports всех74names: mutable registries остаются одним
объектом. Native day handler сохраняет company/product gate, visible/as_role и
current user; _visible_items/_may_configure/_role_items/_sees_money/_drop_money,
PULSE_ITEMS и все остальные handler bodies остаются native. Business/export/views
используют те же shared definitions через aliases; entry pulse_day_data native
остаётся late-bound global для прежнего HTTP caller. Известных old helper/clock
monkeypatch не найдено; arbitrary runtime rebind не объявляется полным callgraph.

Digest/desk получили прямые local imports owner. Их тела после обратной замены
ровно одного import AST exact. Digest порядок прежний: session advisory lock →
due companies → day visible=None → nonempty cards → current recipients → render →
send → audit insert → commit/log; finally unlock и commit. Recipient internal-party,
last_seen30days, effective modules, email preference/away rules не менялись.
System visible=None — не user-visible native slice. Desk _pulse остаётся unfiltered
system summary с тем же try/except→metrics[]; это не новый authorization contract.

## Определения и ограничения

SQL literals/namespace/rounding/units/currency/timezones/null/threshold comparisons
перенесены AST точно. Energy/fuel окна — от данных as_of, CC — от SQL now;
unknown sales profile fallback energy, office выбирает ledger/work по факту записей.
Нет оптимизации/reordering/check removal или новых actor permissions.

Query не commit/flush/send, но ProgrammingError fallbacks sources/CC могут rollback
caller session. _tickets_available ловит missing relation без rollback: следующий
SQL остаётся aborted. Это воспроизводится separately и не исправлено. В native
request rollback/commit lifecycle принадлежит прежнему get_db. Foreign roles/grants
настоящего Support не изменялись и их denial не заявляется под synthetic owner role.

Core↔Support UUID mapping main tickets query сохранён; missing mapping→0, чужие
SupportUUID строки не входят в own counts. При этом sources/CC queries местами
глобальные — старое single-company assumption, не tenant-safe claim. Office-work
population считает private/personal tasks агрегатно, scope keys work-cards частично
не заданы; это существующая business граница, не новая ACL модель.
Unknown as_role admin→None/full slice и ignored unauthorized as_role сохранены.
Net view net.sales по-прежнему передаёт None anchor и даёт empty note при непустом
экранe дня; не чинится в этом пакете. Native business считает30дней, day7дней.

Digest session advisory lock/commit/rollback взаимодействие с pooled physical
connection не переработано: tests подтверждают прежнюю последовательность, не
доказывают cross-worker exclusion во всех rollback сценариях. Scheduler/SMTP
не запускались; ROOT-only run_once использует exact synthetic factory и sender capture.

## Source proof

Собственные ignored evidence `.artifacts/pulse-day-query-owner-20261031/`:
closure-before.json/ownership-proposal.md, before/after global inventory,
before/after-consumers.json, source-review.json/frozen-manifest.json.
Все74nodes AST exact, whole-router reverse AST
`adb41a320adcf511f6f00087a754ab4fef046a38482b39b6d63906f80a54e328`.
497 прочих app blobs неизменны; digest/desk import-only AST exact. Global files
500→501, Python490→491/parse_unknown0; service imports4831→4844, reverse router
bindings12→10/sites11→9. Comparable AST call candidates не заменяют runtime callgraph.
Старые assertions/tests не менялись; compile без исполнения и diff --check PASS.

## Frozen V1 — только ROOT actual

**81cases/65functions:30новых +51старый** (весь test_pulse_rules49 +2SQLrecipient).
Старый source-only assertion public.users в _cc_tables остаётся прежним: этот
native block не перемещался. Old source counts/expected results не ослаблялись.

Новые fixed-ID goldens: energy/fuel/unknown/empty/stale/office-work/office-books,
full JSON native vsowner, desk metrics, role/money/current revoke/as_role,
ack/threshold/SOURCE_MIN_ROWS, UUID map/foreign rows/global source metadata,
real missing-table aborted transaction/fallback, native business30days/CSV/export
самостоятельный audit/view null-anchor, real recipient filters, bounded run_once
lock→query→recipients→captured send→audit→commit→unlock→commit и quiet/no-recipient/
send-error paths. Pure fault injections не выдаются за реальные privilege denials.

Fixture clock берёт SQL CURRENT_DATE; Python owner.date.today и datetime.now
фиксируются на noonUTC этого дня, включая generated_at (поля не удаляются),
SQL now остаётся исходным. Data windows на фиксированном as_of; due/absence имеют
запас относительно SQL now. Tokens/emails — plain fixture values, чтобы rollback
query не превращал ORM-expiration в ошибку test transport.

Lifecycle source selection: setup_database1, world28, tickets_contract28, db30,
auth_client2, monkeypatch29, rate-limit reset81. Test-only public.tickets projection
создаётся/удаляется только в ROOT exact fresh DB. Selected types/defaults/check
из canonical Support DDL; company_id UUID NOT NULL, не text. Support companies/users
FK graph не эмулируется: это минимальный read projection, не production schema or
permission acceptance. Полные provenance SHA (runtime исполняет только frozen literal):

| Support db/init source | SHA-256 |
|---|---|
| 002_schema.sql | `4350d533ec4843fbc46f564934c2c4da6a18299664ab28b152922d4acd36ec4c` |
| 016_extended_statuses.sql | `22b2b194c9afc0ec4cad0a17432f182a82888e6eed766fca310f926d83fc9cd5` |
| 018_archive_delete.sql | `da2d7226933e111dc1e6637d7f270c87c438cd22f86cd4c8e58c3bc0428786b6` |
| 028_hubex.sql | `a0cf50d883a9fe9aed847e3dff00928c6a1a92208bd01dc80d02045ca284c440` |

| Selection | Cases |
|---|---:|
| `tests/test_pulse_day_query_owner.py::test_fixed_profile_day_native_direct_and_desk` | 7 |
| `tests/test_pulse_day_query_owner.py::test_native_visibility_money_vs_system_and_selected_company` | 3 |
| `tests/test_pulse_day_query_owner.py::test_current_role_and_membership_revoke` | 3 |
| `tests/test_pulse_day_query_owner.py::test_as_role_and_native_late_binding` | 1 |
| `tests/test_pulse_day_query_owner.py::test_threshold_ack_and_none_empty_visibility` | 1 |
| `tests/test_pulse_day_query_owner.py::test_core_support_mapping_and_legacy_global_sources` | 1 |
| `tests/test_pulse_day_query_owner.py::test_sources_minimum_rows_and_unknown_definition` | 1 |
| `tests/test_pulse_day_query_owner.py::test_missing_support_table_aborts_legacy_query_and_desk_falls_back` | 1 |
| `tests/test_pulse_day_query_owner.py::test_native_business_export_and_existing_view_null_anchor` | 1 |
| `tests/test_pulse_day_query_owner.py::test_digest_current_recipient_filters` | 5 |
| `tests/test_pulse_day_query_owner.py::test_digest_bounded_real_query_lock_send_audit_commit_order` | 1 |
| `tests/test_pulse_day_query_owner.py::test_digest_bounded_empty_error_paths_keep_unlock_and_audit` | 3 |
| `tests/test_pulse_day_query_owner.py::test_existing_programming_error_rollback_fallbacks_are_not_permission_proof` | 1 |
| `tests/test_pulse_day_query_owner.py::test_identity_reexports_and_shared_mutable_registries` | 1 |
| `tests/test_pulse_rules.py::test_quiet_when_all_is_well` | 1 |
| `tests/test_pulse_rules.py::test_stale_data_is_the_first_alert` | 1 |
| `tests/test_pulse_rules.py::test_no_data_at_all_is_alert` | 1 |
| `tests/test_pulse_rules.py::test_own_tickets_escalate_only_when_stuck` | 1 |
| `tests/test_pulse_rules.py::test_external_backlog_needs_to_be_big` | 1 |
| `tests/test_pulse_rules.py::test_silent_stations_only_on_mass_outage` | 1 |
| `tests/test_pulse_rules.py::test_acked_card_disappears_for_the_day` | 1 |
| `tests/test_pulse_rules.py::test_cap_holds_and_alerts_come_first` | 1 |
| `tests/test_pulse_rules.py::test_insight_is_a_sentence_not_a_number` | 1 |
| `tests/test_pulse_rules.py::test_plural_reads_like_russian` | 1 |
| `tests/test_pulse_rules.py::test_contact_center_is_silent_without_telephony` | 1 |
| `tests/test_pulse_rules.py::test_missed_calls_escalate_only_above_the_target_with_margin` | 1 |
| `tests/test_pulse_rules.py::test_missed_calls_stay_quiet_when_the_week_is_improving` | 1 |
| `tests/test_pulse_rules.py::test_missed_calls_become_alert_when_it_is_a_disaster` | 1 |
| `tests/test_pulse_rules.py::test_dropped_conversations_and_repeat_callers_have_floors` | 1 |
| `tests/test_pulse_rules.py::test_operator_escalation_is_never_thresholded` | 1 |
| `tests/test_pulse_rules.py::test_sales_are_silent_without_data` | 1 |
| `tests/test_pulse_rules.py::test_revenue_dip_of_ten_percent_is_noise` | 1 |
| `tests/test_pulse_rules.py::test_revenue_drop_names_the_reason` | 1 |
| `tests/test_pulse_rules.py::test_half_the_revenue_gone_is_an_alert` | 1 |
| `tests/test_pulse_rules.py::test_stations_out_need_both_share_and_count` | 1 |
| `tests/test_pulse_rules.py::test_visit_success_escalates_only_below_the_floor` | 1 |
| `tests/test_pulse_rules.py::test_projects_are_silent_without_portfolio` | 1 |
| `tests/test_pulse_rules.py::test_stuck_projects_need_share_and_count` | 1 |
| `tests/test_pulse_rules.py::test_stuck_card_names_the_stage` | 1 |
| `tests/test_pulse_rules.py::test_ownerless_portfolio_escalates` | 1 |
| `tests/test_pulse_rules.py::test_frozen_portfolio_is_an_alert_but_movement_silences_it` | 1 |
| `tests/test_pulse_rules.py::test_overdue_next_step_has_no_threshold` | 1 |
| `tests/test_pulse_rules.py::test_operations_are_silent_without_charges` | 1 |
| `tests/test_pulse_rules.py::test_unconfirmed_costs_are_an_alert_with_the_oldest_date` | 1 |
| `tests/test_pulse_rules.py::test_a_couple_of_late_documents_is_not_an_escalation` | 1 |
| `tests/test_pulse_rules.py::test_open_periods_are_reported_but_not_alarming` | 1 |
| `tests/test_pulse_rules.py::test_cost_jump_needs_a_real_jump` | 1 |
| `tests/test_pulse_rules.py::test_sources_are_silent_when_everything_arrives` | 1 |
| `tests/test_pulse_rules.py::test_sessions_have_their_own_rule_and_are_not_duplicated_here` | 1 |
| `tests/test_pulse_rules.py::test_one_silent_source_warns_two_alert` | 1 |
| `tests/test_pulse_rules.py::test_source_that_never_delivered_is_named_plainly` | 1 |
| `tests/test_pulse_rules.py::test_access_is_silent_when_nothing_hangs` | 1 |
| `tests/test_pulse_rules.py::test_dormant_admin_rights_are_reported` | 1 |
| `tests/test_pulse_rules.py::test_stale_invitation_is_reported_singly` | 1 |
| `tests/test_pulse_rules.py::test_visibility_none_shows_everything` | 1 |
| `tests/test_pulse_rules.py::test_closed_topic_never_reaches_the_screen` | 1 |
| `tests/test_pulse_rules.py::test_selection_happens_before_the_cap` | 1 |
| `tests/test_pulse_rules.py::test_topicless_cards_stay_visible` | 1 |
| `tests/test_pulse_rules.py::test_catalog_matches_role_builder` | 1 |
| `tests/test_pulse_rules.py::test_support_users_are_addressed_by_schema` | 1 |
| `tests/test_pulse_rules.py::test_денежные_строки_недели_убираются` | 1 |
| `tests/test_pulse_rules.py::test_без_денежных_строк_список_не_ломается` | 1 |
| `tests/test_pulse_rules.py::test_station_signals_are_one_card_naming_the_worst` | 1 |
| `tests/test_email_kinds.py::test_сводка_не_уходит_отказавшемуся` | 1 |
| `tests/test_profile_security.py::test_в_отпуске_сводка_дня_не_уходит` | 1 |

| Source относительно server | SHA-256 |
|---|---|
| `app/services/pulse_day.py` | `acb09dcb6c90c5443744704666ee7f3cf539f395cda313de9dd1c7b4574294ee` |
| `app/routers/pulse_router.py` | `8255c7de2dc364ab599627950a3e04a20e59c5ff53224a27a96a00b4f2d2f996` |
| `app/services/pulse_digest.py` | `79e196e91b45b63699e9dcf08c1e3423a05ab1130720df503bd7a4cb77088678` |
| `app/services/space_desk.py` | `5b6b83aec5bcb871b4a38c8d0c0c5e5b6b8c58aa29132e24956c86d2b40b6fc9` |
| `tests/test_pulse_day_query_owner.py` | `460ecfa2a84da0cb316384de305f7390982896517d48cdb141ce8ef01d32e6ce` |
| `tests/pulse_day_query_owner_approved.py` | `3c53fc9536efbe2ba252e8a2d95c72a2913511a911be1ed2738faee5b47469ad` |

Full manifests — sorted [relative path,SHA256], __pycache__ excluded, tests exclude self:

| Tree | Count | SHA-256 |
|---|---:|---|
| app | 501 | `7b893754271d6c44677220926835991976d66b75694d3ab2e350f34354587fd7` |
| tests | 374 | `34b2332543c59064eb27696d899191a315e885d9706dae016b4dd762a8a0f521` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |

requirements.txt `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0`;
pytest.ini `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601`.

Strict template acceptedP7 SHA04818020a28a89483540ac14a6251be3825b83620f051e3dd50f3270e9eebe92:
core inventory/net/PGsendmsg16/scratch AST exact. Exact77 distributions/nohooks,
Python3.13.7/glibc2.36 -I -S -B, five IPv6 import suppression/restore/no bind,
native owned buffers-only PG sendmsg, env/process/write/net/capture/source/support/
scratch guards сохранены. Collection additionally freezes all81full raw nodeIDs,
unique count and65originalname group counts. No selectors outside exact frozen set.

ROOT review требуется до app.main/full conftest collection/imports. Capture
installed before conftest, explicit synthetic seed before cached Settings,
ASGITransport без lifespan/jobs, digest only bounded run_once (never run_forever),
no external HTTP/SMTP. Worker не выполнял app imports/collection/SQL/schedulers.

Exact ROOT argv/env, четыре fresh private empty0700 roots:

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=pulse-day-query-owner-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_PULSE_DAY_QUERY_OWNER_TESTS=1 RUN_PULSE_DAY_QUERY_OWNER_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_pulse_day_query_owner_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_pulse_day_query_owner_test_20261031 \
  PULSE_DAY_QUERY_OWNER_PG_PORT=33546 PULSE_DAY_QUERY_OWNER_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-upload PULSE_DAY_QUERY_OWNER_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-scratch PULSE_DAY_QUERY_OWNER_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-scratch \
  PULSE_DAY_QUERY_OWNER_RUNNER_SHA256=3c53fc9536efbe2ba252e8a2d95c72a2913511a911be1ed2738faee5b47469ad \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/pulse_day_query_owner_approved.py --execute-approved-pulse-day-query-owner-tests
```

ROOT admission serial exclusive fresh exactDB33546. Caps CPU600/AS3GiB/FD256/
FSIZE2MiB/wall650/alarm600, tree4000files/64MiB/blob8MiB, captures4000/JSON1MiB,
scratch128MiB/4096files/anchors; PGconnect10/command30/statement20/lock2/idle30s.
Local resource floor/allowance проверяет ROOT по текущему headroom; latest P7
corrective8GiB+384MiB — только исходный planning proposal, не разрешение запуска.
ROOT reaps/verifies clients/relations, normal DROP/exists0, сохраняет receipts и
чистит только свои dirs. Чужие ignored proofs и21старых DB не затрагиваются.

## Corrective freeze V2 — четыре exact cases (история)

ROOT source review `msg_83d25c5b7406`:74nodes/identity/reverseAST/497otherblobs,
oldtests/schema/seven guards/fullpins иSupport4DDL pins PASS. Actual81 receipt
`msg_1ff798e4c99e`: **77PASS/4FAIL/0setupERROR**, pytest25.97s/outer43.086927044s,
exit1/reaped, sourceAfter=true/inventory77/pure16 PASS/forbidden0, normalDROP:
0relations/0clients/exists0/maxlocks64. ROOT artifacts:
`.artifacts/root-pulse-query-review-20261031/actual81/` process.json/run.log,
r1-evidence-test/pulse-day-query-owner-boundary.json, pulse-day-query-owner.xml/pytest.log.
Production/helper/SQL/expected results не менялись; source V1 сохранён ignored v1/.

ROOT approval `msg_40716346d1cf` → `msg_aee591127def`:

- Office-books только: два canonical CREATE из deploy scripts/tax-regimes.sql
  SHA b4980af547c21d8248e3a0fd38fbc83bd2a529efc0d8f0370699e2b43211b273,
  schema-only core→public, nullable organizations.legal_form из того же ALTER.
  Core create_all их не создаёт. Fixture проверяет отсутствие tables, teardown
  удаляет только созданные tables/column; no fake tax_mode response/data seed.
- Digest только no-recipients/send-error: отдельный NullPool engine на exact
  TEST_DATABASE_URL; проверяются URL/current_database/pool class. Dispose и
  exact currentDB/classid0/LOCK_KEY/objsubid1 pg_locks count0; никаких unlock_all,
  force-lock-true, чужих backend cleanup или production pool изменений.
  Это изоляция test leases: legacy session-lock/rollback/pool defect сохраняется.
- View500 пока не определён: raise_app_exceptions=True **только** в failed view
  request для ROOT traceback. Guessed role-grants table не добавляется, прежнее
  ожидание200 и empty net.sales note неизменно до реальной причины/provenance.

77PASS не повторяются. Exact4full nodeIDs, normalized groups1+1+2, strict count/
duplicate-free set unchanged. Если view diagnostic подтвердит bootstrap gap,
ROOT назначит отдельную корректировку; текущий helper не объявляется acceptance.

| Corrective exact selector | Cases |
|---|---:|
| `tests/test_pulse_day_query_owner.py::test_fixed_profile_day_native_direct_and_desk[office-books]` | 1 |
| `tests/test_pulse_day_query_owner.py::test_native_business_export_and_existing_view_null_anchor` | 1 |
| `tests/test_pulse_day_query_owner.py::test_digest_bounded_empty_error_paths_keep_unlock_and_audit[no-recipients]` | 1 |
| `tests/test_pulse_day_query_owner.py::test_digest_bounded_empty_error_paths_keep_unlock_and_audit[send-error]` | 1 |

| V2 pin | SHA-256 |
|---|---|
| new test | `6307d00a85eb42b41f243c4dbe076735a47759cf99101b37f345cdf5d7efe9d2` |
| runner | `5b33d94453669d7850fd7f95260aaf70e9cc881cf103c5753f8d293f1c6c4da0` |
| fulltests374 exclude self | `2ed5c52c8be2085d78d7bf37af4c6d5b5d04dcc8c699d4281b3e4b2427545ff1` |

App501/schema16/support/production4/oldtests unchanged; core guards AST exact V1.
Дополнительный tax source pin относится к provenance frozen literal; внешние SQL
files в runtime не исполняются. CPU/AS/FD/FSIZE/wall/PG/net/write/capture/scratch caps
прежние, ROOT readmission обязательно; первичный actual profile8GiB+384MiB был
local planning сrollingfloor и не является blanket permission на новый запуск.

V2 exact argv/env, свежие private empty0700 directories, exact fresh DB прежняя:

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-corrective-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=pulse-day-query-owner-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_PULSE_DAY_QUERY_OWNER_TESTS=1 RUN_PULSE_DAY_QUERY_OWNER_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_pulse_day_query_owner_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_pulse_day_query_owner_test_20261031 \
  PULSE_DAY_QUERY_OWNER_PG_PORT=33546 PULSE_DAY_QUERY_OWNER_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-corrective-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-corrective-upload PULSE_DAY_QUERY_OWNER_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-corrective-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-corrective-scratch PULSE_DAY_QUERY_OWNER_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/pulse-day-query-owner-20261031/root-test-corrective-scratch \
  PULSE_DAY_QUERY_OWNER_RUNNER_SHA256=5b33d94453669d7850fd7f95260aaf70e9cc881cf103c5753f8d293f1c6c4da0 \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/pulse_day_query_owner_approved.py --execute-approved-pulse-day-query-owner-tests
```

## Actual receipts и остаток

На момент V2freeze ожидался corrective4/view diagnostic; итоговые actual receipts ниже. Нет fullCI/security scan/merge/deploy,
M04/M08 и вся M00–M19 не закрыты. Осталось10 service→router bindings, профильные
population/visibility/global Support assumptions выше и остальные доменные splits
вне этой границы. ROOT назначает интеграцию/следующего владельца/release.

## Frozen V3 — точная коррекция metadata guard

ROOT msg_a2be38233fb1: V2 collected4,0test executions, exit4/reaped,
outer17.031204920s. SourceAfter=true/inventory77/pure16 PASS/forbidden0; normalDROP
0relations/0clients/exists0/maxlocks64. Причина: сравнивались четыре full param
selectors и три function group keys, несмотря на разные namespaces.

По ROOT approval исправлен только guard: selector.split("[",1)[0] с суммированием
EXPECTED_COUNTS. Actual groups и calculated groups сравниваются с прежними
EXPECTED_GROUP_COUNTS; exact full4 IDs/unique/count проверяются прежним способом.
Source-only guard-metadata-selfcheck.json: groups1+1+2/4unique IDs/count4, negative
changed-count/function/param controls PASS. Никаких app imports/collection/SQL worker.

V2 runner/report/manifest сохранены в ignored v2/. Production/newtest/full app
501/tests374/schema16/support pins прежние. V3 runner SHA `e0d5c4348178fa2c5719fbadfe2d9a5103ba119507e6299c2652091e98ef8d94`.
ROOT argv/env/caps V2 прежние, кроме PULSE_DAY_QUERY_OWNER_RUNNER_SHA256=
e0d5c4348178fa2c5719fbadfe2d9a5103ba119507e6299c2652091e98ef8d94 и fresh V3-owned test directories.
77PASS не повторяются; те же4 exact IDs с view diagnostic, actual ожидается.

## Frozen V4 — последний view1 (текущий)

ROOT V3 receipt msg_4c4e6fad4173:3PASS/1diagnosticFAIL/0ERROR, pytest16.12s/
outer32.556950028s, exit1/reaped; sourceAfter=true/inventory77/pure16 PASS/
forbidden0, normalDROP0relations/0clients/exists0/maxlocks64. Tax/NullPool
коррекции прошли. Retained80PASS =77V1+3V3; повторяется только view1.

Реальная причина view: UndefinedTable pulse_view_role_grants в UNION до admin
branch. Source-only search scope/pins в view-role-provenance.json: Core569316...
и all-ref server/docs/scripts, Core introducer a6cea614598c5c7a71586aae5c12eaddc0c6277f
(Aug15, только router/frontend/manifest), tenantjoin update d3191238cb16efd6e32ada88caa42896c829d476;
Deploy currentc4ab320c3f8de1c8e59345ad7ab927de6c68da04 +ec22clone и all-ref
scripts/db/SQL/docs, Supportcurrenta6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df
+9564clone db/all-ref SQL. Tracked DDL не найден в этом scope; liveSQL/SSH не было.

ROOT approval msg_af902f5a0beb→msg_909d982a2c79: ONLY view case inferred EMPTY
public.pulse_view_role_grants(view_id UUID,role_id UUID), assertabsent и owncleanup.
БезPK/FK/NOTNULL/default/index/grants. Из current reader/writer (AST+source hashes
в artifact) доказаны только UUID casts/joins. Это не canonical production schema,
не проверка role ACL/constraints. Прежние native200/null-anchor/CSV audit assertions
сохранены. Barefresh actual500/missing bootstrap DDL остаётся M02/M08/M16 gap.

Exact selector: `tests/test_pulse_day_query_owner.py::test_native_business_export_and_existing_view_null_anchor`, count1/group1/fullID1.
V3 tests/runner/report/manifest сохранены ignored v3/. Production4/app501/schema16/
oldtests/support unchanged; все function/class AST runner V3 exact, только metadata.
New test SHA `cd9647dcb9464348090522c12ce020045263c59fe4e72da2f85ece35a9a9093e`;
runner SHA `30aae6cafa127f350201adc7d714e509d38637f6e98904efbea75e6d4bd00e7f`;
fulltests374 excludeself `39aa66a43f4a9c9b37792661625c22e87a6089255e2f191b9f751cb8571ea429`.

ROOT argv/env/caps V2 те же, кроме current runnerSHA и новых private empty
root-test-viewonly-* dirs. ROOT serial admission после M09 cleanup обязателен;
worker runtime запрещён. На момент V4freeze ожидался view1; итоговое принятие ниже, не fullCI.

## Actual acceptance ROOT и открытые границы

ROOT final receipt `msg_2f4dae8f6001`, source review `msg_83d25c5b7406`,
V2 narrow fixtures `msg_034e8a7c5aad`, V3 guard review `msg_ed6b403effb7`,
V4 source review `msg_694759480ee8`. После actual менялся только этот отчёт;
production/helper/test/runner остаются в принятом V4 freeze, worker не выполнял
app imports/runtime/collection/SQL/scheduler/SMTP.

| Серия ROOT | Outcome | Pytest / outer | Evidence и cleanup |
|---|---|---|---|
| V1 actual81 |77PASS/4FAIL/0setupERROR |25.97 /43.086927044s |sourceAfter=true/inventory77/pure16 PASS/forbidden0; exit1/reaped |
| V2 corrective4 |collected4/**0 test executions**, guard refusal |outer17.031204920s |exit4/reaped, sourceAfter/77/16 PASS/forbidden0; metadata namespace mismatch preserved |
| V3 corrective4 |3PASS/1diagnosticFAIL/0ERROR |16.12 /32.556950028s |sourceAfter/77/16 PASS/forbidden0; exit1/reaped; actual UndefinedTable confirmed |
| V4 view1 |**1PASS** |16.74 /33.580208714s |sourceAfter/77/16/exact1/JUnit verified, forbidden0; exit0/reaped |

Для каждой серии ROOT подтвердил normal DROP своей exact DB:
0relations/0clients/exists0/maxlocks64. Retained **77+3+1=81 разных случая**, три
серии с выполнением test cases; collection-only V2 не считается PASS-прогоном.
Root-owned local planning8GiB floor+384MiB/rollingfloor относился к этому bounded
набору; security/source/PG caps не ослаблялись. Чужие DB/ignored proofs не чистились.

ROOT evidence — `.artifacts/root-pulse-query-review-20261031/` в worktree ROOT:
actual81/, corrective4/, corrective4-v3/, view1-v4/ (process.json/run.log и
r1-evidence-test/pulse-day-query-owner-boundary.json, pulse-day-query-owner.xml).
Source-only свои proofs, V1/V2/V3 и frozen-proposals.md сохранены ignored
`.artifacts/pulse-day-query-owner-20261031/`.

Открытые границы не скрыты успешной fixture acceptance:

- pooled session advisory lock может остаться на другом physical backend после
  rollback/commit; NullPool fixtures устранили только cross-test contamination.
  Real pooled/cross-worker exclusion не доказан и production lock не исправлен;
- tax tables/legal_form отсутствуют в Core create_all и подставлялись из pinned
  canonical test-only DDL; положительный office-case не закрывает bootstrap gap;
- barefresh native view реально вернул500 из-за отсутствия pulse_view_role_grants.
  Его DDL не найден в указанном scope. Положительный view-case использует **inferred
  EMPTY two-UUID read projection**, не canonical table/constraints/grants/role ACL proof;
- global CC/source assumptions, system digest/desk vs native money visibility,
  office-work population и view null-anchor остаются прежними M08 вопросами.

ROOT назначает владельцев pooled-lock и missing-DDL follow-up отдельно. Этот пакет
не менял production pool, модели/DDL, правила прав, финансовые данные, рассылку,
SDK/Contract/frontend/версии/deps/flags; merge/deploy/ship/fullCI не выполнялись.
