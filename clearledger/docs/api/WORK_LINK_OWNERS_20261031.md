# Общие владельцы WorkLinks, M04-P6/M07 · 31.10.2026

**Пакет принят ROOT:** 47 retained +38 corrective primary PASS и отдельные
3/3 R2 PASS; это две primary серии, не единый85-run. Итоговые receipts ниже;
M03/M04/M07 и общая M00–M19 остаются активными.

База `e106745c7c88622adb9f0be4b1ff2d9c280a9f1d`, ветка
`agent/api-work-link-owners-20261031`. ROOT semantics:
`msg_0f587f04b404` → `msg_284d717a955b`; отдельный R2 regression:
`msg_41a4ee57b830` → `msg_f4cde287a6c0`.

| Правило | Owner | Native compatibility |
|---|---|---|
| can_edit_task | existing task_access | router wrapper передаёт текущие _can_view_task и _is_admin |
| assert_actor | existing task_access | router wrapper передаёт текущие _assert_view_task и _can_edit_task |
| WorkLinks общая популяция | existing task_queries.not_personal | direct service import, прежний visibility != personal |
| Doc subject/graph EXISTS | existing doc_subject_links.subject_documents_clause | default auto; WorkLinks explicit correlate_doc=True |

View остаётся первым: чужой cid/нечитаемая задача даёт 404, читаемая без edit —
403 «Задача не ваша». Personal доступен только автору даже для admin/superadmin;
WorkLinks исключает personal целиком как общую популяцию. Author/assignee,
current admin, oversight tree и unassigned behavior прежние. Callback defaults
разрешаются при каждом вызове через is None; falsey callable не заменяется.
Повторные view/admin queries сохранены: assert_actor вызывает view и затем edit
с собственным view; WorkLinks перед этим выполняет ещё свой view. Cache нет.

Ни edit helper, ни graph predicate не дают standalone company/product authority.
Current membership и docs→plan product gate принадлежат native callers. Поэтому
после revoke author может пройти subordinate helper, но HTTP остаётся 403.
Stage/member scope и _not_personal не заменяют полный ACL. Direct WorkLinks
unknown kind по-прежнему выбирает Task; native origin отсекает его 400.
Querycompany, limits/counts, source/origin/history и commit ownership caller прежние;
helper не flush/commit/audit/send. Native action no-op title служит HTTP-проверкой
edit gate без изменения persisted rows; собственные commits ручки сохранены.

## Graph correlation и source proof

Единый subject owner сохраняет subject_ref OR tenant DocRelation EXISTS.
correlate_doc — профиль SQL construction, не режим доступа: default False оставляет
прежнюю auto-correlation для R2/native docs, True сохраняет explicit DocCard
correlation прежнего WorkLinks. Outer DocRelation joins/nested SELECT проверяются
compiled SQL и fixed реальными строками отдельно. EXISTS исключает дубли;
foreign relation company не связывает документ, foreign DocCard остаётся за caller
company/ACL. Task ветка subject_clause точно прежняя. R2 authority не расширяется.

Source evidence в `.artifacts/work-link-owners-20261031/`: before/after inventory,
before-consumers.json, after-consumers.json, before-hooks.json, source-review.json,
frozen-manifest.json. Before global inventory: 497 файлов, 487 Python parsed,
0 parse_unknown, 4795 service imports, 15 router bindings/14 sites. After: 497,
487, 0, 4798, 13/12: удалены только два WorkLinks reverse binding.

Normalized can_edit body SHA `7597031c209daa61cfb1ecdbb80d2b07c9e2445265f6102e07a9444ce2145006`;
assert_actor `afec70fc33c76be1a6cae8180561ba14d14a9ecfd5ffbc026b14d61b086f5c9d`.
Whole-router reverse AST SHA `684597a56a572e3c18762a6e4fb497ea853868a3fb4c2edf02caa88c635566bd`
совпадает с базой после возврата только двух helper bodies. Existing task_access
AST прежний после удаления двух новых функций и нового status import. WorkLinks
reverse AST точен после возврата subject_clause и двух import bindings, включая
origin и всю caller логику. Default R2 predicate body нормализуется к исходному.

Сохранён old file-store hook tasks_router._can_view_task (test_file_store_transactions:448),
старые P2 computed setattr для is_admin/visible_to/can_view_task и P5 bindings.
Native wrappers получают конкретные текущие hooks; direct services используют
свои текущие defaults. Новые falsey/short-circuit/repeated-view и poisoned router
checks проверяют эту границу. Inventory отражает статические spelling/import
candidates, не полный runtime callgraph и не доказательство arbitrary getattr.
Compile без исполнения и git diff --check PASS; старые tests/assertions неизменны.

## Frozen proposal V1 для ROOT

Worker не выполнял app import, collection, SQL, browser, build/install.
Runtime только ROOT serial fresh exact DB `api_work_link_owners_test_20261031`
на 127.0.0.1:33546, synthetic clearledger/api_test_only, без других clients.

| Source относительно server | SHA-256 |
|---|---|
| `app/services/work_links.py` | `c3aedbe44f3c47153ab5f3ebb0ad57fe6ac27b7146418c29fe6187067350ec2f` |
| `app/services/task_access.py` | `883ad577afbcaa80000a2dba83e00441c0b6ca7fde9335fb74ea4ba475647948` |
| `app/routers/tasks_router.py` | `f92d1634d8b3f7571d86a8e2b574e0dbbbab0a4449c7e228e649f88de9999c13` |
| `app/services/doc_subject_links.py` | `5f91d599f97e3abedd354617eb60ea518ac0ae591f0a6087272821fb7cbced83` |
| `tests/test_work_link_owners.py` | `3b478550c0695082e0976fb2ab07f3deefec8cbc532ee2cfc31e3b30d5a287e6` |
| `tests/work_link_owners_approved.py` | `ae62b7a5abe5e7bbf5fd732d4f3dbae8b12dedaf15f8ec4baf31ef2aa01aa7c1` |

Full manifest: sorted [relative path, SHA256], без __pycache__; tests исключает self.

| Tree | Files | SHA-256 |
|---|---:|---|
| app | 497 | `ed019a14c7d47efa3f47698b1b80a0671a7343664cb8f3baf2b535362a20ef7f` |
| tests без self | 367 | `21bbae7347d755c60b92f1cb9d38366e57ebacc43dcdab988eef023d24d2aeca` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |

requirements.txt `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0`;
pytest.ini `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601`.

**84 cases / 36 функций**: 39 новых fixed-ID goldens, 45 старых без правок.
Новые: union/ref/object/both/unlinked-prefix/empty, duplicate/foreign relations,
hidden ACL, private/personal, author/assignee/admin/superadmin/oversight/unassigned,
current membership/module revoke, exact HTTP 403/404, hooks/unknownkind/history,
полные persisted row snapshots и no flush/commit/capture delta. Старые: personal
isolation (15), oversight core/edit (7), P2 WorkLinks и lexical owners (13), пять
work-context flows и source history (6), native card/private/closed action (3),
pinned old file-store task-view hook (1). Это targeted regression, не полный CI.

| Exact selection | Cases |
|---|---:|
| `tests/test_work_link_owners.py::test_union_fixed_ids_tenant_graph_acl_and_population` | 6 |
| `tests/test_work_link_owners.py::test_shared_predicate_profiles_compile_and_fixed_rows` | 1 |
| `tests/test_work_link_owners.py::test_native_direct_actor_and_worklink_edit_outputs` | 20 |
| `tests/test_work_link_owners.py::test_current_membership_oversight_and_caller_guards` | 2 |
| `tests/test_work_link_owners.py::test_direct_worklink_bindings_and_unknown_kind_stay_compatible` | 1 |
| `tests/test_work_link_owners.py::test_document_link_does_not_add_read_or_edit_authority` | 1 |
| `tests/test_work_link_owners.py::test_helper_reads_do_not_flush_commit_audit_or_send` | 1 |
| `tests/test_work_link_owners.py::test_native_actor_hooks_are_late_bound_falsey_and_view_first` | 2 |
| `tests/test_work_link_owners.py::test_native_view_admin_hooks_preserve_short_circuit_and_repeated_view` | 1 |
| `tests/test_work_link_owners.py::test_source_origin_history_and_scope_stay_caller_owned` | 4 |
| `tests/test_personal_isolation.py::test_посторонний_не_меняет_видимость_чужой_записи` | 1 |
| `tests/test_personal_isolation.py::test_посторонний_не_дописывает_реплику_в_чужую_запись` | 1 |
| `tests/test_personal_isolation.py::test_администратор_личную_запись_не_трогает` | 1 |
| `tests/test_personal_isolation.py::test_суперадминистратор_тоже_не_трогает` | 1 |
| `tests/test_personal_isolation.py::test_автор_свою_запись_меняет` | 1 |
| `tests/test_personal_isolation.py::test_посторонний_не_видит_запись_через_ручку_действия` | 1 |
| `tests/test_personal_isolation.py::test_ни_одно_поле_не_проходит_как_реплика` | 6 |
| `tests/test_personal_isolation.py::test_голая_реплика_остаётся_репликой` | 1 |
| `tests/test_personal_isolation.py::test_запись_без_срока_срока_не_получает` | 1 |
| `tests/test_personal_isolation.py::test_датированная_запись_видна_в_моих_сроках` | 1 |
| `tests/test_oversight.py::test_рядовой_не_надзирает_ни_за_кем` | 1 |
| `tests/test_oversight.py::test_начальник_отдела_видит_свой_отдел` | 1 |
| `tests/test_oversight.py::test_начальник_управления_видит_всю_ветку` | 1 |
| `tests/test_oversight.py::test_работа_без_исполнителя_забота_надзирающего` | 1 |
| `tests/test_oversight.py::test_администратор_видит_всех` | 1 |
| `tests/test_oversight.py::test_надзирающий_вправе_вмешаться_в_своей_ветке` | 1 |
| `tests/test_oversight.py::test_личную_запись_не_трогает_и_надзирающий` | 1 |
| `tests/test_task_acl_import_boundary.py::test_work_union_and_single_read_preserve_task_doc_acl` | 11 |
| `tests/test_task_acl_import_boundary.py::test_readable_task_retains_edit_actor_guard` | 1 |
| `tests/test_task_acl_import_boundary.py::test_owner_identity_old_reexports_and_live_lexical_bindings` | 1 |
| `tests/test_work_contexts_integration.py::test_сообщение_работа_принятие_возврат_в_пять_сценариев` | 5 |
| `tests/test_work_contexts_integration.py::test_переход_к_старому_сообщению_и_граница_истории` | 1 |
| `tests/test_tasks_route.py::test_карточка_собирает_работу_целиком` | 1 |
| `tests/test_tasks_route.py::test_приватная_задача_не_видна_посторонним` | 1 |
| `tests/test_tasks_route.py::test_закрытая_задача_по_маршруту_не_ходит` | 1 |
| `tests/test_file_store_transactions.py::test_migrated_task_attachment_keeps_source_data_default` | 1 |

Strict template — accepted P5 runner SHA
`1417ba767073d87f35c4601270a63d5c0a5ff15c92cc9c1000fd7f551e63c6e1`.
AST inventory/install_boundaries/pg_sendmsg_metadata_allowed/sendmsg_metadata_controls/
scratch_bound совпадает с template. Exact candidate77 (61 runtime +16 tools),
Python3.13.7/glibc2.36, -I -S -B; пять import IPv6 probes suppression/restore без
bind, native owned buffers-only PG sendmsg с 16 metadata controls. Env/process/
write/net/capture/source/scratch guards сохранены; log/XML/JSON в evidence,
--capture=sys и TMPDIR/basetemp в своём scratch. Delivery capture установлен до
conftest; synthetic seed задан до cached Settings. ASGITransport без lifespan/jobs.
Дополнительные opt-ins: RUN_FILE_STORE_TESTS для одного старого pinned regression
и RUN_TASK_ACL_IMPORT_BOUNDARY_TESTS для трёх старых P2 функций. Запрещённый event
или skip/xfail, другая selection/count/inventory/source после запуска дают FAIL.

Точные ROOT argv/env (четыре новые пустые owned0700 directories; создать ROOT):

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=work-link-owners-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_WORK_LINK_OWNERS_TESTS=1 RUN_WORK_LINK_OWNERS_TESTS=1 RUN_FILE_STORE_TESTS=1 RUN_TASK_ACL_IMPORT_BOUNDARY_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_work_link_owners_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_work_link_owners_test_20261031 \
  WORK_LINK_OWNERS_PG_PORT=33546 WORK_LINK_OWNERS_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-upload WORK_LINK_OWNERS_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-scratch WORK_LINK_OWNERS_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-scratch \
  WORK_LINK_OWNERS_RUNNER_SHA256=ae62b7a5abe5e7bbf5fd732d4f3dbae8b12dedaf15f8ec4baf31ef2aa01aa7c1 \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/work_link_owners_approved.py --execute-approved-work-link-owners-tests
```

ROOT outer: CPU600/AS3GiB/FD256/FSIZE2MiB/wall650; scratch128MiB, reserve10GiB
и плановый allowance1GiB на одну schema/WAL, serial admission ROOT. Alarm600,
<=4000 files/tree, <=8MiB/blob, <=64MiB/tree, <=4000 captures, <=1MiB JSON;
scratch anchors/4096files/128MiB. PG connect10/command30/statement20/lock2/idle30s.
Conftest reset/create_all/seed/teardown только public/edge своей exact DB;
ROOT reaps child, проверяет 0 relations/clients, normal DROP/exists0, чистит только
свои cwd/upload/scratch, receipts хранит. Чужие ignored artifacts сохраняются.

## Отдельный supplemental R2 proposal

По msg_f4cde287a6c0 ROOT создаёт ignored immutable harness из принятого R2 boundary
с current full source pins; worker не меняет old tests, approved runner или target.
Отдельная fresh exact DB `api_contract_documents_test_20261030`, тот же numeric
loopback33546, прежние R2 opt-ins/_contract_documents_boundary и --noconftest.
Exact selection, каждый 1 case (всего3), никаких skip/xfail:

- tests/test_product_contract_documents.py::test_subject_graph_duplicate_and_mismatched_refs_match_native_read
- tests/test_product_contract_documents.py::test_shared_source_task_policy_is_not_expanded_by_contract_link
- tests/test_product_contract_documents.py::test_doc_role_allow_then_explicit_deny_is_current

Fixture closures из AST: contract_documents_database session1, db3, env3,
password_hash session1, request/monkeypatch в env; отдельной api fixture нет.
Current app/schema/support hashes выше; R2 old test source включён в full tests
manifest. Final supplemental harnessSHA/argv/env/limits и runtime admission
закрепляет ROOT перед исполнением, затем выдаёт actual receipt. Primary и R2
receipt требуются оба; worker держит runtime/app/tests замороженными до обоих.

## Corrective freeze V2 (текущий)

V1 выше остаётся историческим proposal; текущие pins/selection задаёт V2.
ROOT source-review msg_f03dd5c6d2c4 подтвердил оба owner bodies, whole-router/WorkLinks
reverse AST, прежний task_access/default predicate и 493 остальных app blobs,
full manifests и семь guard functions. Actual V1 msg_a1104a31d3b8: 47 PASS,
36 setup ERROR, 1 FAIL; pytest43.75s / outer60.62611698s / exit1/reaped.
SourceAfter=true, inventory77, 16controls PASS, forbidden0; 0relations/0clients,
normal DROP exists0/maxlocks64. Evidence: ROOT actual84/{process.json,run.log,
r1-evidence-test/work-link-owners-boundary.json,work-link-owners.xml}.

Ошибки world вызвал canonical uq_doc_cards_subject(company_id,subject_ref):
мой fixture задавал один REF сразу трём документам. Индекс/schema не менялись.
ROOT msg_aa0be5fc60c4 → msg_68272fa411f5 согласовал исправление: только direct
имеет canonical REF, он же получает graph REF (direct+graph overlap); dual и
hidden получают NULL subject и прежние graph REF. Graph сохраняет два edge kinds,
hidden strict ACL-negative и foreign другой company остаются. **Все test bodies,
fixed IDs и literal expected outputs/status неизменны**, AST подтверждён.

Old closed-route FAIL — не создан prerequisite incident type; добавлен неизменный
old initializer test_задача_идёт_по_маршруту_типа, native types/starter дважды,
непосредственно до closed-route. Production4/app/schema и все old tests прежние.
Прошедшие47 V1 не повторяются (3 new hooks +44old); требуется corrective38:
36 world +initializer1 +closed1. Весь набор после коррекции —85 разных primary
cases с новым initializer, отдельные supplemental3R2 ещё ожидаются.

| V2 source | SHA-256 |
|---|---|
| tests/test_work_link_owners.py | `16449647c83e7dc979faeba97a5fb7d71dd5b358625b6d04b3379a9bbdc8011b` |
| tests/work_link_owners_approved.py | `667fbceb05f6f6c904f232b396fafc2fda60f8ecb76246ba10375aab9a7af2e1` |
| full tests367 excluding self | `b785ff7ef03c1bbf18666b99153be5530a75764ef8f82f643b518a0a4b1e14bf` |

Full app497/schema16/support hashes прежние, V1 sources сохранены в ignored
.artifacts/work-link-owners-20261031/v1/. Коррекция только fixture, selection и
соответствующие source hashes. Неиспользуемые RUN_FILE_STORE_TESTS и
RUN_TASK_ACL_IMPORT_BOUNDARY_TESTS удалены из required/allowed env: их модули
не выбираются corrective38. Guard inventory/install_boundaries/PGmetadata16/
scratch AST exact к принятому runner; остальные env/process/write/net/capture/
source guards не ослаблены. Compile без исполнения и diff --check PASS.

| V2 exact selection | Cases |
|---|---:|
| `tests/test_work_link_owners.py::test_union_fixed_ids_tenant_graph_acl_and_population` | 6 |
| `tests/test_work_link_owners.py::test_shared_predicate_profiles_compile_and_fixed_rows` | 1 |
| `tests/test_work_link_owners.py::test_native_direct_actor_and_worklink_edit_outputs` | 20 |
| `tests/test_work_link_owners.py::test_current_membership_oversight_and_caller_guards` | 2 |
| `tests/test_work_link_owners.py::test_direct_worklink_bindings_and_unknown_kind_stay_compatible` | 1 |
| `tests/test_work_link_owners.py::test_document_link_does_not_add_read_or_edit_authority` | 1 |
| `tests/test_work_link_owners.py::test_helper_reads_do_not_flush_commit_audit_or_send` | 1 |
| `tests/test_work_link_owners.py::test_source_origin_history_and_scope_stay_caller_owned` | 4 |
| `tests/test_tasks_route.py::test_задача_идёт_по_маршруту_типа` | 1 |
| `tests/test_tasks_route.py::test_закрытая_задача_по_маршруту_не_ходит` | 1 |

Lifecycle: setup_database session1, world36, actors36, db36, auth_client2,
_reset_rate_limit38, monkeypatch36; ROOT collection exact38/no skip/xfail.
Fresh exactDB/33546 прежняя, новая четвёрка owned empty0700 dirs. Остальные
CPU/AS/FD/FSIZE/wall/SQL/scratch caps прежние; ROOT local resource admission
из msg_f03dd5c6d2c4: reserve/livefloor9GiB +768MiB (DB256/output192/WAL320),
PG readback WAL80MiB/0other clients/maxlocks64, без изменения прежних receipts
или foreign cleanup/GUC. Runtime только ROOT.

V2 exact argv/env:

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-corrective-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=work-link-owners-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_WORK_LINK_OWNERS_TESTS=1 RUN_WORK_LINK_OWNERS_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_work_link_owners_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_work_link_owners_test_20261031 \
  WORK_LINK_OWNERS_PG_PORT=33546 WORK_LINK_OWNERS_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-corrective-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-corrective-upload WORK_LINK_OWNERS_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-corrective-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-corrective-scratch WORK_LINK_OWNERS_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/work-link-owners-20261031/root-test-corrective-scratch \
  WORK_LINK_OWNERS_RUNNER_SHA256=667fbceb05f6f6c904f232b396fafc2fda60f8ecb76246ba10375aab9a7af2e1 \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/work_link_owners_approved.py --execute-approved-work-link-owners-tests
```

## Actual receipts и остаток

P6 принят ROOT `msg_f65e2b8ac17d`; уточнение DROP `msg_609efc59dd9c`.
Worker runtime/collection/SQL не выполнял; после actual изменён только отчёт.
Production/test/helper/runner остались в принятом V2 freeze.

| Серия ROOT | Результат | Pytest / outer | Boundary / cleanup |
|---|---|---|---|
| V1 actual84 | 47 PASS /36setupERROR /1FAIL | 43.75 /60.62611698s | exit1/reaped; sourceAfter/inventory77/16controls PASS, forbidden0; 0relations/0clients/DROP exists0 |
| corrective38 (`msg_ffd501f941f8`) | **38/38 PASS** | 25.16 /42.08492134s | exit0/reaped; independent XML38, no skip/error; sourceAfter=true/inventory77/16controls PASS, forbidden0; 0relations/0clients/DROP exists0 |
| separate supplemental3R2 | **3/3 PASS** | 19.57 /24.565036113s | exit0/reaped; independent XML3, failures=[], no skips; fullsourceAfter/inventory77/16controls PASS, forbidden0; notify.dispatch_async captured9 |

Primary evidence — **47 retained V1 +38 corrective =85 разных cases**, двух серий,
а не единый прогон85. Canonical fixture исправлен по ROOT approval без изменения
ID/status/expected literals/test bodies/production или old assertions. Причины
V1 ошибок и prerequisite native initializer описаны выше; failed V1 не скрыт.

Supplemental R2: exact old DB `api_contract_documents_test_20261030`, lifecycle
contract_documents_database1/db3/env3/password1/api0, old guards/targets/assertions
не менялись. ROOT own harness SHA
`5f875ca39f24425f64b44a2856d8b54f63c3cf77e77debe2dcc7246b8722fb7d`;
current fulltests368 включает approved P6 runner. ROOT namespace-only sourceguard
AST и single argv narrowing проверены. Перед normal DROP R2 **338 relations**,
0 других clients; после DROP exists0/maxlocks64. Это отдельная серия с созданной
R2 schema, не conftest teardown с нулём relations.

Фактический local resource admission ROOT: primary historical reserve9GiB +768MiB;
**corrective reserve/livefloor9GiB +384MiB** (итоговый receipt). Ранний V2 proposal
наследовал primary allowance768MiB; actual профиль ROOT закреплён отдельно.
SQL/source/target/guard caps прежние, foreign cleanup/GUC не выполнялся.

Доказательства в worktree ROOT, `.artifacts/root-work-link-review-20261031/`:

- `actual84/` и `corrective38/`: process.json, run.log,
  r1-evidence-test/work-link-owners-boundary.json, work-link-owners.xml;
- `supplemental-freeze.json`, `supplemental-r2-approved.py`;
- `supplemental3R2/process.json`,
  `supplemental3R2/r1-evidence-test/boundary.json`, contract-documents.xml.

Собственные source/freeze proofs остаются в ignored
`.artifacts/work-link-owners-20261031/`, включая архив V1 и frozen-proposals.md.

Полный CI/security scan, merge/deploy не выполнялись. M03/M04/M07 и общая цель
M00–M19 остаются активными: after inventory ещё13 service→router bindings,
включая осознанные management chat hooks и прочие native service bridges вне
этого пакета; дальнейшие owner/release назначает ROOT.
