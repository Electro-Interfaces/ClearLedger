# Команды рабочего пространства проекта, M04-P7 · 31.10.2026

**P7 принят ROOT:**64 retained V2 +7 corrective PASS,71 разных случаев в двух
сериях. Это targeted acceptance; весь M04/API и общий M00–M19 остаются активными.

База `495b66a81f07a12ae9845dde9b7a7d20b3324ac7`, ветка
`agent/api-project-workspace-command-owner-20261031`. ROOT ownership approval
`msg_08a1fec543bd` → `msg_b3acfbfc3ae0`. Runtime worker не выполнял.

Три команды принадлежат services/project_workspace_commands:
link_work, record_decision, attach_message_file. Native routes сохранили signatures,
Depends/decorators/status/errors, DTO reexports и передают конкретные текущие
assert_company_member/owned/source_message callbacks. Defaults выбираются через
is None при каждом вызове, включая falsey callable; module injection/cache нет.
ProjectsContext.execute использует прямой owner и те же runtime DTO.

LinkBody/DecisionBody/FileBody — единственные классы в flat
app/schemas_project_workspace.py. Существующий app/schemas.py остаётся модулем;
превращать его в пакет не потребовалось. NextBody/ScenarioBody используют тот же
identity reexport LinkBody; DTO classes AST точны, без copy/fork/coercion изменений.

## Authority, порядок и известные различия

- Все команды: current membership → site company/id SELECT FOR UPDATE → source/
  readable checks → событие/audit → один commit. Ни project-owner/admin gate,
  ни дополнительный product/object-scope gate здесь прежде не было. Role downgrade
  не равен revoke membership; этот пакет не вводит нового правила.
- Source: db.get message, missing/deleted404, participant, nullable history cutoff
  (строго `<`), затем room.company==cid. Source owner использует chat_access;
  native source wrapper передаёт текущие chat_router hooks. Participant может
  писать foreign-access audit и notify до проверки cutoff/company; это не чистый read.
- Current selected company берётся из deps._active_company (ContextVar), который
  заполняет capture_company_header у соответствующих router dependencies. Затем
  visit_company, user.company_id или sole-membership fallback. Команда не заменяет
  этот principal своим cid. Project/work-context routes сами header capture не
  добавляют; прежний default-primary/request-context порядок сохранён.
- Link task/doc требует readable_entity(edit=True). Другой task.subject_ref даёт
  409; первый task link добавляет edit TaskEvent. Doc basis relation проверяется
  tenant-safe EXISTS. Повтор task/doc link не плодит association/TaskEvent, но
  каждый раз пишет site note. Discussion повторяется без второго event.
- Decision требует только read и уже существующую project link, не edit authority.
  Optional deadline/budget сохраняют null/zero/type semantics. Каждый вызов пишет
  decision (text.strip), project.decision audit и notify.dispatch_async, затем commit.
- File использует SourceFile company/path-is_file validation из track_files.
  Команда не читает/копирует bytes и не создаёт DocCard/DocVersion; это association.
  Повтор site/file возвращает прежний ID/kind без второго note, но всё равно commit.

Неразрешённые business inconsistencies сохраняются: native команды не применяют
context scenario action gating; ordinary member вправе менять budget/deadline;
native length-three whitespace DecisionBody после strip даёт пустой event text,
context отвергает такое решение 400. Source-message selected-company fallback и
site lookup без дополнительного location scope не исправлялись в этой волне.

## Source proof

Собственные ignored evidence `.artifacts/project-workspace-command-owner-20261031/`:
before/after inventory, before/after-consumers.json, source-review.json,
frozen-manifest.json и source-only proof scripts. Новых runtime imports не было.

Normalized body SHA: link `8d0b68f1bd447c2b549f7f9fd33269b3c1a2d4845ac4356e909c0edf660c7cb6`,
decision `5215f241c368cb173128747f7ed39417ce4d77944645eece59beb0d03eb32bf3`,
file `774e0c12f9c3b7127de5fdfde2b3e8287f8fdf692701d93264c226901e9dfabd`.
Whole-router reverse AST `af5b8dbb481ae1bb8d211c58c95fd55e582bb10c95c74c5d75183d8c62eeface`;
whole-context reverse AST `60a046cdb5a02b5a07f057470909a956164fc3757d8fb860b4716cbe665cb2e4`.
Обратное преобразование возвращает только 3команды/2helper adapters/3DTO и новые
imports; все остальные router handlers и context methods точны. Owned body
полностью точен, source_message body точен после callback/import normalization.
496 остальных app blobs неизменны, только два новых app files добавлены.

Global inventory: files498→500, Python488→490, parse_unknown0;
service imports4811→4831, router bindings13→12/sites12→11 (один project context
module binding удалён). Comparable AST consumer candidates включают nested imports
и concrete patch spellings; это не полный runtime callgraph/arbitrary getattr.
Old direct patches project commands/DTO/owned/source в tests не найдены; native
chat hooks сохранены явно. Module attributes ezs_site_work.log_event,
track_files.message_file/project_work.readable_entity остаются shared module hooks.
Compile без исполнения и git diff --check PASS; старые tests/assertions не менялись.

## Frozen proposal V2 — ROOT-only actual

**71 cases /20 функций**: 58 новых, 13 прежних. Новые фиксируют native HTTP,
direct/context HTTP/context direct для всех3команд, repeated IDs/events/audit/bytes,
real SQL site locks и commits, revoke/role/foreign site, task/doc edit-vs-read,
source/history/selected company/file statuses и no-mutation negative snapshots,
foreign audit→decision audit/notify, late falsey hooks/defaults, shared runtime
DTO и scoped native OpenAPI. Полный app OpenAPI export не выполняется.

Старые selected regressions:5work flows, права/пагинация, file/process/promotion,
history, scenario settings, missing bytes, published-scenario defaults,
ordinary-member scenario access и note audit. Их assertions неизменны; отдельный
TP unittest harness не выбирается: hard-coded tp_test и собственный DB lifecycle.
app.main/full conftest imports предлагаются **только ROOT после review**, с
ASGITransport без lifespan/jobs и delivery capture до conftest. Worker их не импортировал.

| Exact selection | Cases |
|---|---:|
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes` | 12 |
| `tests/test_project_workspace_command_owner.py::test_current_membership_role_and_site_tenant` | 12 |
| `tests/test_project_workspace_command_owner.py::test_link_write_authority_and_repeat_counts` | 8 |
| `tests/test_project_workspace_command_owner.py::test_decision_uses_read_and_link_not_edit_authority` | 4 |
| `tests/test_project_workspace_command_owner.py::test_source_file_negative_goldens_no_mutation` | 6 |
| `tests/test_project_workspace_command_owner.py::test_source_selected_company_history_and_current_participation` | 4 |
| `tests/test_project_workspace_command_owner.py::test_foreign_audit_then_decision_audit_notify_before_single_commit` | 2 |
| `tests/test_project_workspace_command_owner.py::test_context_direct_binding_scenario_text_and_file_repeat_kind` | 1 |
| `tests/test_project_workspace_command_owner.py::test_concrete_falsey_hooks_lock_event_commit_order` | 6 |
| `tests/test_project_workspace_command_owner.py::test_source_concrete_chat_hooks_falsey_and_history_first` | 2 |
| `tests/test_project_workspace_command_owner.py::test_runtime_dto_identity_fields_validation_and_native_openapi` | 1 |
| `tests/test_work_contexts_integration.py::test_сообщение_работа_принятие_возврат_в_пять_сценариев` | 5 |
| `tests/test_work_contexts_integration.py::test_права_в_проекте_и_пагинация` | 1 |
| `tests/test_work_contexts_integration.py::test_файл_из_чата_входит_в_согласуемую_редакцию_и_повторно_не_загружается` | 1 |
| `tests/test_work_contexts_integration.py::test_переход_к_старому_сообщению_и_граница_истории` | 1 |
| `tests/test_work_contexts_integration.py::test_шаблон_этапа_и_команда_становятся_настройками_общих_функций` | 1 |
| `tests/test_work_contexts_integration.py::test_пропавшее_вложение_не_создаёт_поручение_с_битым_файлом` | 1 |
| `tests/test_project_scenario_versions.py::test_публикация_фиксирует_старые_проекты_и_новую_версию` | 1 |
| `tests/test_project_scenario_versions.py::test_обычный_сотрудник_читает_но_не_публикует` | 1 |
| `tests/test_project_audit.py::test_заметка_журнал_не_шумит` | 1 |

| Source относительно server | SHA-256 |
|---|---|
| `app/services/project_workspace_commands.py` | `9d9183560c2e33db5e0ebe440551167ddb10bd09d9e8111aee7ff66f178ec5e4` |
| `app/schemas_project_workspace.py` | `86f3f612f216dd3a5106c9a6c001318bf70709a8b8affe49bff17f26bb3df08c` |
| `app/routers/project_workspace_router.py` | `862caf9e808330ccc180f2c00ce6399a37944e224fb1620e5b62464a6958fc3b` |
| `app/services/project_work_context.py` | `117e1e9d65ec35203ff949a9604bdd383c79795033c8c9b7474547e1512e19f4` |
| `tests/test_project_workspace_command_owner.py` | `7b1e38e8d1d9c42d63b8232c3be920426ce42f7261a3d8d5d650da16201544b4` |
| `tests/project_workspace_command_owner_approved.py` | `4ed5487cfc584267fbe92755d340238504431d37497b4b0b2f30987705b11a3b` |

Manifest sorted [relative path,SHA256], без __pycache__, tests исключает self:

| Tree | Count | SHA-256 |
|---|---:|---|
| app | 500 | `cb0243fba571708c2b314b813b47f3959651652a93e5e926b03bb78287118381` |
| tests | 371 | `f518b9325f758791958c0cd4635a6e4f63d7d95124aabf8ddfc655daebe12e9e` |
| schema_migrations | 16 | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |

Support requirements.txt `f1ce1401ba8d014e2b861b1404d9b9cfecf21c73f8047b85090b9d0275e8eba0`;
pytest.ini `bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601`.

Strict template — accepted P6 runner
`667fbceb05f6f6c904f232b396fafc2fda60f8ecb76246ba10375aab9a7af2e1`;
inventory/install_boundaries/PGsendmsg metadata16/scratch functions AST exact.
Exact77 (61runtime+16tools), Python3.13.7/glibc2.36 -I -S -B, no .pth/sitecustomize/
usercustomize, five import IPv6 suppression/restore (никакого bind), native owned
buffers-only PG sendmsg. Env/process/net/write/capture/source/support/scratch guards,
synthetic seed до Settings, --capture=sys, log/XML/JSON и final sourceAfter retained.
Никаких .env/keys/prod/network/deps/server/startup действий worker не выполнял.

Точный ROOT argv/env, четыре fresh owned empty0700 test directories:

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=project-workspace-command-owner-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS=1 RUN_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_project_workspace_command_owner_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_project_workspace_command_owner_test_20261031 \
  PROJECT_WORKSPACE_COMMAND_OWNER_PG_PORT=33546 PROJECT_WORKSPACE_COMMAND_OWNER_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-upload PROJECT_WORKSPACE_COMMAND_OWNER_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-scratch PROJECT_WORKSPACE_COMMAND_OWNER_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-scratch \
  PROJECT_WORKSPACE_COMMAND_OWNER_RUNNER_SHA256=4ed5487cfc584267fbe92755d340238504431d37497b4b0b2f30987705b11a3b \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/project_workspace_command_owner_approved.py --execute-approved-project-workspace-command-owner-tests
```

ROOT proposal: serial fresh exclusive exactDB33546, CPU600/AS3GiB/FD256/
FSIZE2MiB/wall650/scratch128MiB; local resource admission ROOT, предлагается
reserve/livefloor9GiB +384MiB allowance по последнему corrective profile.
Alarm600, tree<=4000files/64MiB, blob<=8MiB, captures<=4000, JSON<=1MiB;
scratch anchors/4096files/128MiB, PG connect10/command30/statement20/lock2/idle30s.
Full conftest создаёт/очищает public/edge только своей exact fresh DB. ROOT reaps,
проверяет relations/clients и normal DROP/exists0/maxlocks64, чистит только свои
cwd/upload/scratch; чужие ignored proofs сохраняются. Без runtime receipt нет PASS.

## Corrective freeze V3 (текущий)

ROOT V2 review `msg_99f35999879b`: 3commands/owned/source normalized exact,
3DTO exactAST, все прочие handlers/signatures/decorators/context methods,
496other app blobs/oldtests/schema и seven guards/pins exact. V2 actual71
`msg_4ac44cbf935f`: **64PASS/7FAIL/0ERROR**, pytest31.40s /outer49.34381961s,
exit1/reaped. SourceAfter=true/inventory77/pure16 PASS/forbidden0; normal DROP:
0relations/0clients/exists0/maxlocks64. ROOT evidence:
`.artifacts/root-project-command-review-20261031/actual71/` (process.json/run.log,
r1-evidence-test/project-workspace-command-owner-boundary.json, XML).

Шесть FAIL — новый spy смешивал commit команды с существующим финальным commit
get_db (database.py:5555ff). Седьмой — fixture db с expire_on_commit=False держал
Task(subject_ref=None) в identity map после commit отдельной HTTP session;
readable_entity.db.get возвращал этот старый объект. Production не менялся.

ROOT approval `msg_52059f826cff` → `msg_d9bdabc0b3d9`: spy классифицирует exact
immediate caller code identity трёх owner functions/get_db; неизвестный caller
внутри invoke window даёт AssertionError. Точное окно monkeypatch.context — две
invoke calls, восстановление до fixture teardown. Native/contextHTTP trace:
site-lock→owner-commit→dependency-commit, direct/context-direct без dependency
commit; отдельно проверяются owner1/request и dependency1/HTTP request.

Только task-editable-author positive fixture перед вторым/direct вызовом читает
persisted subject и TaskEvent1, делает scoped db.refresh(Task), проверяет текущий
subject. Итоговый исходный expected TaskEvent1/IDs/status/audits сохранён.
Это выравнивание fixture caller с committed состоянием другого соединения;
production freshness policy долгой session не исправлялась и не обещается.
V2 test/runner/fullmanifest/report сохранены ignored v2/; V1 — в v1/.
64PASS не повторяются, corrective выбирает **ровно7 полных nodeIDs**, group counts6+1:

| Exact corrective selector | Cases |
|---|---:|
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[discussion-native]` | 1 |
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[discussion-context]` | 1 |
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[decision-native]` | 1 |
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[decision-context]` | 1 |
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[file-native]` | 1 |
| `tests/test_project_workspace_command_owner.py::test_three_commands_repeat_fixed_outputs_events_audit_bytes[file-context]` | 1 |
| `tests/test_project_workspace_command_owner.py::test_link_write_authority_and_repeat_counts[task-editable-author-200]` | 1 |

Collection guard требует exact duplicate-free full7 nodeID set, count7 и exact
normalized originalname groups (repeat6/link1), EXPECTED_COUNTS all1. Никакого
расширения whole param group. Остальные execution guards прежние, core5 funcs
AST exact V2/acceptedP6; compile без исполнения и diff --check PASS.

| V3 pin | SHA-256 |
|---|---|
| new test | `14d74c29a84d21f14ca1256327320d15b95476adb4e4243d69da5100abea2647` |
| runner | `04818020a28a89483540ac14a6251be3825b83620f051e3dd50f3270e9eebe92` |
| fulltests371 excluding self | `060a1f0381a3fe2cd34a79aa50df511ff058e6c7a5ebbbe1413b235e15de0425` |

Fullapp500/schema16/support pins прежние; production4 и old tests неизменны.
Current ROOT local resource profile primary8GiB livefloor +768MiB planning
(source admission msg_99f35999879b), прежний9Gi+384 proposal выше исторический;
security/source/PG guards и exactDB33546 не менялись, foreigncleanup/GUC не было.
Для corrective требуется новая fresh exact DB и четыре новые empty0700 roots,
те же CPU/AS/FD/FSIZE/wall/SQL/scratch caps, admission/normalDROP только ROOT.

V3 exact argv/env:

```sh
cd /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-corrective-cwd
env -i HOME=/home/mag PATH=/usr/bin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  APP_ENV=test SECRET_KEY=project-workspace-command-owner-boundary-synthetic-secret-only \
  SEED_SUPERADMIN_EMAIL=admin@clearledger.ru SEED_SUPERADMIN_PASSWORD=admin123 ECOSYSTEM_COMPANIES= \
  ROOT_APPROVED_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS=1 RUN_PROJECT_WORKSPACE_COMMAND_OWNER_TESTS=1 \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_project_workspace_command_owner_test_20261031 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_project_workspace_command_owner_test_20261031 \
  PROJECT_WORKSPACE_COMMAND_OWNER_PG_PORT=33546 PROJECT_WORKSPACE_COMMAND_OWNER_EMPTY_CWD=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-corrective-cwd \
  UPLOAD_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-corrective-upload PROJECT_WORKSPACE_COMMAND_OWNER_EVIDENCE_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-corrective-evidence \
  TMPDIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-corrective-scratch PROJECT_WORKSPACE_COMMAND_OWNER_SCRATCH_DIR=/home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/.artifacts/project-workspace-command-owner-20261031/root-test-corrective-scratch \
  PROJECT_WORKSPACE_COMMAND_OWNER_RUNNER_SHA256=04818020a28a89483540ac14a6251be3825b83620f051e3dd50f3270e9eebe92 \
  /srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-partner-identity-20261029/clearledger/server/tests/project_workspace_command_owner_approved.py --execute-approved-project-workspace-command-owner-tests
```

## Actual receipts и остаток

ROOT pre-actual review msg_70eb54aa4706 нашёл только опечатку нового audit test:
order_by AuditEvent.created_at заменён на реальное поле AuditEvent.timestamp.
Production, все expected literals/assertions и selection71 прежние; V1 test/runner/
manifest/report сохранены в ignored v1/. V1 runtime не запускался.
Пакет принят ROOT `msg_779401ec9457`: **64 retained V2 +7 corrective PASS =71
разный case**, в двух сериях, без утверждения единого71-green/fullCI. V2 actual71
с64PASS/7FAIL не скрыт; ошибки новых spy/fixture и pre-actual timestamp correction
описаны выше. Production/helper/DTO и old tests/expected results не менялись.
Worker runtime/app imports/collection/SQL не выполнял; после actual менялся только отчёт.

| ROOT серия | Результат | Pytest / outer | Guard / cleanup |
|---|---|---|---|
| V2 actual71 |64PASS/7FAIL/0ERROR |31.40 /49.34381961s |exit1/reaped, sourceAfter=true/inventory77/pure16 PASS/forbidden0; normal DROP0relations/0clients/exists0/maxlocks64 |
| V3 corrective7 |**7/7PASS** |16.21 /33.108461783s |exit0/reaped, independentXML7/noerrors/skips, exact7collection/groups6+1; sourceAfter=true/inventory77/pure16 PASS/forbidden0; normal DROP0relations/0clients/exists0/maxlocks64 |

ROOT source acceptance `msg_99f35999879b`/`msg_74ebccd36796`: commands/owned/source
normalized exact, DTO exactAST, all other router/context methods and496 other app
blobs unchanged; oldtests/schema/support/fullpins/seven guards verified. V3 raw
nodeID checks valid; промежуточное утверждение ROOT о prefix отозвано, V4 и реального
collection failure не было.

Фактический local resource admission ROOT: primary71 —8GiB livefloor +768MiB
planning; первая corrective768 попытка отказала **до directories/DB/test child**
(0executions), receipt corrective7-admission-attempt768.json сохранён. Затем для
точных7cases принят профиль **тот же8GiB livefloor +384MiB planning**
(DB256/output64/WAL64; WAL planning не cap). Source/security/PG/SQL/scratch guards
не менялись, чужие21 DB не трогали, foreign cleanup/GUC не выполнялись.

Evidence в worktree ROOT `.artifacts/root-project-command-review-20261031/`:
source-review-part1.json/source-review-part2.json, actual71/,
corrective-source-review.json; corrective7/process.json,
corrective7/r1-evidence-test/project-workspace-command-owner-boundary.json,
project-workspace-command-owner.xml. Собственные source/freeze proofs, V1/V2 и
frozen-proposals.md сохранены в ignored .artifacts/project-workspace-command-owner-20261031/.
 Полный CI/security scan/M04/API не закрыты;
после inventory остаются12 service→router bindings и осознанные native chat hooks.
Unknown role/scope/whitespace/scenario inconsistencies выше не исправлялись.
Интеграцию/дальнейшего владельца/release назначает ROOT; merge/deploy/flags не было.
