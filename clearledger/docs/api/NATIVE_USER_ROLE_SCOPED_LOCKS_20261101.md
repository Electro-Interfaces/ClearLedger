# Native users/roles: scoped locks, SOURCE handoff

Код и authored tests: `cdef933bd6b42ffbcb7336516ff7aa698538af66` поверх `c9e841c48ddf4864eb258e6bd5ddd7401a3833ea` в `Electro-Interfaces/ClearLedger`. Изменены ровно 7 разрешённых путей (5 code/test + этот MD и парный JSON). AUTHOR0: только чтение/Git/stdlib AST/hash/JSON/компиляция в памяти; приложение, helper, collection и тесты не исполнялись.

`SOURCECONFIRMED`: 14 целевых users roots и `update_role`/`delete_role` входят в `assert_native_clean` до прежних чтений, затем один раз в `prepare_native_write` до записи. `update_user` имеет два взаимоисключающих source branch entrance; фактический вызов один. Общий `require_company_admin` для read-only callers не изменён.

Полный план: Company S; actor User S и Member S; target User S либо заранее X для account/remove; target Member X, в том числе отсутствующий; старая и новая Role S. Role update/delete получают Role X. Совпадение actor/target объединяет режимы через frozen LockPlan. UUID нового User создаётся до плана, без нового HTTP-поля.

Строки после ключей: Company SHARE по UUID → User SHARE/UPDATE по UUID → CompanyRole SHARE/UPDATE по UUID с tenant predicate до row lock → UserCompany SHARE/UPDATE по composite PK → прежние зависимые строки. Discovery идёт под `no_autoflush`; после ожидания identity map истекает и перечитывается через `populate_existing`. Родитель и role_id/native-role сравниваются со discovery. Затем повторяются публичные native claims/session/visit проверки и прежний native admin/superadmin ACL. Новых partner privileges нет.

Review `msg_59400860e84c` дополнительно потребовал повторить target-superadmin403 в set_member_access после prepare: повышение могло завершиться между preflight и discovery. Successor `cdef933b` сохраняет immutable `b692b0e4`, добавляет проверку по fresh locked target и отдельный authored negative PG case. Остальные mutable authority checks находятся после prepare либо повторяются внутри него.

Изменившийся указатель даёт 409 до записи и rollback через прежний get_db; повтора/расширения плана в том же root нет. ROOT `msg_5e53b6a0849a`, переданный `msg_863bad7e6c69`, отдельно разрешил fail-closed409 для legacy cross-company role FK. `role_id` — single FK: проверяется фактический owner старой роли; delete_role под Role X сначала проверяет physical table на чужих holders, включая скрытых ORM visit scope. При несоответствии прекращает операцию до mutation; составное tenant ограничение не заявляется.

`remove_user` берёт target User X/UPDATE до member DELETE/flush, сохраняя chats cleanup, audit, remaining-membership probe и условный User DELETE. Role delete держит Role X до holder UPDATE и Role DELETE; holder User keys поздно не добавляются. Полнота остальных membership writers пока не доказана.

Порядок обычных 400/403/404 веток, payload/response schemas, audits, опциональные empty/null поля и владельцы commit/rollback сохранены по source diff. Native admin в set_member_access по-прежнему игнорирует malformed role_id. System-role запрет и omission chat_scope сохранены. Caller side effects invite/chats/roster/email не перенесены в адаптер.

| Root | До → после | Commit |
|---|---|---|
| `create_user` | admin -> organization resolve -> email lookup -> membership INSERT or new User INSERT/flush -> membership INSERT/flush -> close_invites -> audit(new only) -> response → **existing: User S; new: preallocate UUID then User X; Member X including absent; actor User S/Member S; Company S; old Role S; revalidate email -> original writes/invite close/audit/response** | get_db |
| `update_user` | UUID -> company admin+membership or global superadmin -> target guard -> optional global name -> optional membership fields/audit -> flush -> response → **same company/global branches -> User X iff name is not None (including empty string), otherwise S; per-company Member X/old Role S -> same optional values, audits, flush, response** | get_db |
| `set_member_modules` | UUID -> admin -> member404 -> target superadmin403 -> modules/role_id clear -> flush -> response → **User S + Member X + old Role S -> same admin-unlimited/ad-hoc assignments -> flush -> response** | get_db |
| `set_member_access` | UUID -> admin -> member404 -> target superadmin403 -> admin branch ignores role_id, else requested Role lookup/custom -> mutate -> audit -> commit -> response → **same prechecks -> parse new role only for non-admin role mode; expected_member comparison covers preflight/discovery gap -> old/new Role S + Member X -> refreshed branch -> same audit/commit/response** | handler |
| `set_member_scope` | UUID -> admin -> member404 -> target -> own location/org validation -> object/own-org fields -> audit -> commit -> response → **User S + Member X + old Role S -> same object/org normalization, audit, commit, response** | handler |
| `set_member_business_grants` | UUID -> admin -> member/target404 -> company404 -> station/location discovery -> normalize -> business_grants -> audit -> roster -> commit -> response → **User S + Member X + old Role S -> same grant validation, audit, roster failure handling, commit, response** | handler |
| `set_station_pin` | UUID -> admin -> member404 -> target404 -> PIN validate/set -> audit -> roster -> commit -> response → **target User X + Member X + old Role S before PIN/account mutation -> same PIN/audit/roster/commit/response** | handler |
| `set_member_contracts` | UUID -> admin -> member404 -> target -> same-company contract IDs -> contract_ids -> audit -> commit -> response → **User S + Member X + old Role S -> same contract validation/audit/commit/response** | handler |
| `reset_sessions` | admin -> UUID -> target/member404 -> target superadmin403 -> token_version increment -> audit -> commit → **target User X + Member X + old Role S -> same checks/version/audit/commit** | handler |
| `reset_2fa` | admin -> UUID -> target/member404 -> target superadmin403 -> totp clear + token_version increment -> audit -> commit → **target User X + Member X + old Role S -> same checks/totp/version/audit/commit** | handler |
| `issue_reset_link` | admin -> UUID -> target/member404 -> target superadmin403 -> reset token/hash/expiry -> audit -> flush -> optional email -> response → **target User X + Member X + old Role S -> same token/expiry/audit/flush/email behavior** | get_db |
| `remove_user` | admin -> UUID -> self400 -> target/member404 -> target superadmin403 -> member DELETE/flush -> chat cleanup -> audit -> remaining-member probe -> possible User DELETE → **after self400, target User X + User UPDATE row before member DELETE/flush; Member X + old Role S; preserve cleanup/audit/remaining probe/conditional User DELETE; no late upgrade** | get_db |
| `grant_company` | admin -> UUID -> target404 -> absent member INSERT/flush -> response → **User S + same absent/present Member X + old Role S -> fresh existence -> same conditional insert/flush/response** | get_db |
| `revoke_company` | admin -> UUID -> target404 -> target superadmin403 -> optional member DELETE/flush -> chat cleanup → **User S + Member X + old Role S -> same target checks/member delete/flush/chat cleanup** | get_db |
| `update_role` | admin -> role get -> tenant404 -> system403 -> name/modules and optional chat_scope -> audit -> commit -> response → **Role X before fresh tenant-filtered Role UPDATE row -> same 404/system403 -> preserve omitted chat_scope, audit, commit, response** | handler |
| `delete_role` | admin -> role get -> tenant404 -> system403 -> ALL role_id holder probe -> holders role_id=NULL -> audit -> role DELETE -> commit → **Role X -> tenant-filtered Role UPDATE row -> same 404/system403 -> physical cross-tenant holder probe: fail409 before any mutation -> same-tenant holders ordered UPDATE -> same assignment reset/audit/DELETE/commit; no late holder User keys** | handler |

Точные per-root before/after commit/path:range и raw SHA-256 файла/символа находятся в `NATIVE_USER_ROLE_SCOPED_LOCKS_20261101.json#roots`; source manifests включают adapter, оба routers и оба test-файла. Это source traces с условными ветками, не наблюдавшийся runtime trace.

Подготовлены 6 unit/source test functions и 13 synthetic PG test functions, все NOTRUN. PG-сценарии вызывают actual routes/adapter и настоящий frozen helper, наблюдают точные `pg_locks` + `pg_blocking_pids`, используют управляемые Sessions и cleanup; fake lock receipts и sleep-race не используются. Аудит/уведомления/response decorations подменяются, релевантные four-table FK сохраняются; это не полный app schema proof.

PG guard требует два одинаковых явно одобренных URL, отдельное имя `native_user_role_synthetic_*` и approval literal до app imports. Repository conftest исполняется раньше и способен удалять схемы: guard модуля не делает обычный pytest безопасным. Только ROOT вправе отдельно выбрать изоляцию и исполнение; runner здесь не создан.

`UNKNOWN`: c9 helper не имеет SOURCE PASS по ROOT review B1 (actual Connection/DB RootTransaction lifetime через rollback_only). Замена с тем же API принадлежит helper owner; frozen helper/tests/docs не менялись. `UNKNOWN`: auth/invites/seed/CLI/import/прочие account/membership/role writers, company lifecycle и реальные PostgreSQL/ACL/runtime/CI. `PROPOSAL`: отдельный owner для будущего create_role writer. Schema ordinal4 `0004_partner_contract_create` parent0003 остаётся у ROOT.

Статически прошли AST/in-memory compile пяти файлов и git diff --check. Сравнение AST показало изменение только 14 users и 2 roles functions; read-only helpers/list/push_station_roster и create_role сохранены. Git commits сделаны с отключёнными hooks; push/PR/merge/deploy отсутствуют.

Сырые parent original 20 разделов/11 общих требований не переписаны и не закрыты. Read-only pins:

`/srv/projects/preview/api-platform-20261029/API-MODERNIZATION-PLAN.md` — SHA-256 `2f0ce3f319b1bbeff98905f2921514b5b722c1c65d4c7c13ca8b344f9e888352`, 29956 bytes, строки 1–238.

`/srv/projects/preview/api-platform-20261029/completion-matrix.html` — SHA-256 `811b7dba00cdc456a71f051527fe6e2ef425b9649fb0ac3a8e8d5564f4dab493`, 28046 bytes, строки 1–219.

`/srv/projects/preview/external-developer-experience-20261031/inputs/API-MODERNIZATION-PLAN.md` — SHA-256 `2f0ce3f319b1bbeff98905f2921514b5b722c1c65d4c7c13ca8b344f9e888352`, 29956 bytes, строки 1–238.

Этот bounded пакет не объявляет all-writer closure, общий B PASS, M00–M19/11 closure или рабочий runtime. Дальше требуется независимое source review, helper B1 handoff и отдельное ROOT решение об исполнении.

## Followup: AST oracle, 01.11.2026

Точная reviewed combined база: `d73d46fcdcb902d09e0a1aee12676296efbcfd8b`. Authority `msg_8d9ef1e3552f`, Task `task_b6ec9d1d13f3`, Dispatch `ctx_572bde69059a`. Новый successor меняет ровно три пути: unit/source test и эту пару MD/JSON. В `calls()` изменён только регион обхода на `ast.Module(body=node.body, type_ignores=[])`: собственные decorators, annotations и defaults функции исключены; docstrings не содержат AST Call. Поиск вызовов по имени/атрибуту сохранён.

Независимый stdlib AST-подсчёт исходников, без импорта или вызова test/helper functions:

| Handler | `delete` в прежнем whole-function обходе → теле | `prepare_native_write` → реальные `db.delete`, строки | Commit в теле |
|---|---|---|---|
| `remove_user` | 3 → 2 | 795 → 805, 816 | 0, владелец get_db |
| `revoke_company` | 2 → 1 | 857 → 865 | 0, владелец get_db |
| `delete_role` | 2 → 1 | 126 → 152 | 1, строка 153 |

Лишние вызовы были собственными `@router.delete` на строках 778, 843 и 116 соответственно. Ни один `db.delete` не исключён. Все 6 unit/source и 13 PG test functions, включая декораторы, параметризации и assertions, byte/AST равны базе; commit-ownership oracle сохранён целиком. PG-файл и все app-файлы byteequal базе. Статические проверки: AST и compile в памяти без exec пяти code/test файлов, raw SHA-256/Git blob pins и независимый подсчёт body calls; collection и тесты не запускались.

ROOT сообщил **18 FAIL / 9 PASS из 27 native cases** только для композиции `326457edd0b8029b2739cf5563c492f4f8169a10`: два source-oracle failures относятся к этому исправлению, остальные 16 — к отдельной SQLAlchemy OptionEngine работе helper owner `ctx_c0ef2f5caaa8`. Это исторический результат конкретной ROOT-композиции; он не переписан в PASS и здесь не воспроизводился. Minimal-helper 99 PASS не означает native PASS. **Runtime AFTERFIX: NOTRUN; closure OPEN**. Models/schema и final runtime остаются вне этого Task; старые raw reports/commits immutable.

Обновлённый raw pin unit/source test: `7f10c2876687d2a32504d90e2a3e181b6c7e1c85f4e3b75b3e4304df4fa45759`, 6747 bytes, строки 1–127. Commit этого снимка определяется содержащим successor commit, а содержимое — raw SHA-256 и Git blob в JSON, без циклической ссылки на собственный commit hash. Исторический test pin сохранён в `ast_oracle_followup.historical_unit_test_pin`; app source base `c9e841c…`, source commit `cdef933b…`, before/after traces и исходные M00–M19/11 pins не изменены. Полные новые pins и статические доказательства — `ast_oracle_followup` парного JSON.
