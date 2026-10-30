# M04/M06: выделение native CREATE договора

Дата: 30.10.2026. База: `8197c96b52aa6a1aeed23252f8cbcf585ea28731`.
Собственная ветка: `agent/api-native-contract-create-20261030`.
Статус: **реализовано и frozen source проверен; actual SQL ещё НЕ ЗАПУСКАЛСЯ**.
Worker не импортирует app/драйверы и не выполняет pytest collect/gate/SQL.

## Цель и граница

Native POST `/api/references/contracts` должен передать валидированный native
ввод и настоящего native User общему use case, затем сериализовать возвращённый
Contract прежней `_contract_resp`. Новый внешний endpoint, partner write API,
новые permissions и объединение с импортной CREATE-командой не добавляются.
Партнёрский principal не преобразуется в native User.

Создана отдельная `services/native_contract_commands.py`, чтобы не менять
bytes принятой `services/contract_commands.py` и трёх импортных producers.
Native use case принимает `body: ContractCreate`, `current_user: User`,
`db: AsyncSession`, возвращает ORM Contract. Это типизированный native порт
для существующего контракта, не generic payload/kwargs и не разрешение
будущим партнёрам пользоваться native User policy. Native HTTPException
сохраняется на этом ограниченном этапе ради точных прежних статусов/сообщений;
отдельная модель partner principal/error adaptation не вводится.

## Разобранные вспомогательные функции

Router на base имеет SHA256
`2b755bf232c22b6c23d4a1534d14dee4e2289d4a13772d3846bf8b9f9d8b65a7`.
Source anchors и AST SHA256, Python 3.13 без исполнения:

| Узел | Строки base | Прямые consumers |
|---|---|---|
| `_parse_uuid` | 115–119 | 31 функции, включая два helper; UUID-парсинг разных references routes |
| `_CONTRACT_REQ_FIELDS` | 753–758 | create_contract, update_contract, _contract_resp |
| `_req_val` | 761–765 | CREATE и PATCH; замыкает _parse_uuid |
| `_check_type_code` | 822–830 | CREATE и PATCH; actual active contract_types lookup |
| `_validate_contract_parties` | 845–854 | CREATE и PATCH; замыкает _parse_uuid/id_key и модели сторон |
| `create_contract` | 862–920 | существующий POST handler |

AST hashes в том же порядке:

- `0269d948fe39f2f897383bb7c34ee1cbde8806210f93a5f14e6daae36a4936f7`;
- `f1fce0c9f73d00f990fc4d42dda8148ae2052bee8e659947bfd9aca58c867141`;
- `f11ddae1e496b9fa77d3a0c998fa944f59abfc883c0c2fe3d10abe85a5208d6e`;
- `a712ef7f197f68a941bd0f82796af8625bd76d030f0ee98a9724e3a73728e86a`;
- `b8961c5ce3f86757adbaeb6cb558c8b0120b4145a2352c03f3613a287df60dd6`;
- `29ec839ae642f8feea04b8ff0d9ed5cedc4247435ac31b88bc21207605a5dc24`.

Полные private consumers/line anchors: `.artifacts/native-contract-create/closure.json`.
В остальных server Python-файлах прямых импортов/вызовов этих private helpers
из references_router не найдено. Это source observation, не runtime call graph.

## Владелец общих helpers

Одна новая `services/reference_validation.py` владеет пятью прежними узлами
в точности с исходными именами, сигнатурами и телами. Router получает их
прямым import под прежними private names; use case импортирует те же функции
и тот же словарь. Таким образом, бизнес-правила не копируются в новый service,
и нет service → router import. Общий UUID parser находится у references
validation, а не внутри специализированного native CREATE.

Другие route bodies, включая PATCH и serializer, не меняются. Прямые aliases
сохраняют их прежние имена; перенос helper не добавляет новую обработку
исключений, nullable semantics либо object/org policy. ROOT технически согласовал
этот перенос и allowlist до runtime edits, включая сохранение native typed port,
точного lexical closure и before-lock admission без расширения политики.

Для CREATE перенесены все прежние statements, включая assert_company_member,
порядок разбора и проверки сторон, request hash и lock, оба conflict check,
конструктор и flush. Отличия лишь в двух return: service возвращает previous/c,
transport вызывает прежнюю serializer один раз для полученного Contract.
Decorators, Depends, status 201, response model и get_db transaction остаются.

## Совместимость и source proof

1. Company/visit/member/superadmin policy вызывается прежней функцией;
   новых прав и способов подменить principal нет.
2. Оба UUID парсятся до SELECT сторон; CP проверяется до Organization.
   Невалидный/чужой ввод сохраняет status/text и порядок отказа.
3. Request hash остаётся SHA256 того же body.model_dump(mode=json), с
   исключением ровно company_id/creationKey, сортировкой ключей и compact separators.
   Пустые/default/null поля участвуют так же, строки сторон не нормализуются в hash.
4. Identity/creationKey дают прежний company/contract barrier. Проверка сторон
   остаётся до lock, replay — до business duplicate, typeCode — в прежнем месте
   конструктора. После ожидания не добавляется новая admission policy.
5. Replay с тем же actor/body возвращает прежнюю карточку; другой actor/hash
   получает прежний 409. Новый ключ не обходит business duplicate; incomplete
   identity не превращается в новую обязательную уникальность.
6. Все поля конструктора, nullable/req map и helper bodies сохраняют AST;
   flush остаётся, commit/rollback принадлежит caller/get_db.

Private source proof проверил точный AST пяти relocated узлов,
равенство перенесённого CREATE (с нормализованными return/сигнатурой/decorator),
и остальной router целиком после удаления только relocated definitions,
старых исключительно CREATE imports и нового thin handler.
Отдельно подтверждена byte equality импортной команды/трёх producers и всех старых tests,
schemas, models, auth/scope, identity/locks и migration package.

Весь router после нормализации только согласованного extraction совпадает
с base по AST; PATCH, serializer, сигнатура/decorator CREATE и остальные
route bodies не изменены. 489 прежних app-файлов, кроме извлечённого router,
побайтово совпадают с base. Проверены module imports/lexical globals каждой
перенесённой функции: старые uuid/HTTPException/AsyncSession/models/id_key/
hashlib/json/select/auth/identity bindings сохранены. Aliases router и use case
ссылаются на одни определения и один dict нового validation owner;
service → router imports отсутствуют. Это source proof, не runtime object identity.

Evidence только private: `.artifacts/native-contract-create/source-proof.{py,json}`,
closure/manifest/proposal рядом. Python 3.13 выполнил AST parse и compile в памяти
пяти Python-файлов этого среза; worker не исполнял эти модули и не делал collect.

## Согласованная allowlist

Runtime:

- изменить только `clearledger/server/app/routers/references_router.py`;
- новая `clearledger/server/app/services/native_contract_commands.py`;
- новая `clearledger/server/app/services/reference_validation.py`.

Проверки/отчёт:

- новая `clearledger/server/tests/test_native_contract_create.py`;
- новая `clearledger/server/tests/native_contract_create_approved.py`;
- данный новый `clearledger/docs/api/NATIVE_CONTRACT_CREATE_20261030.md`.

STATUS, schemas, models/DDL, PATCH body, ACL/lock policy, импортная команда,
прошлые reports/inventory и старые tests вне diff. Вложенные workers,
package install, build, API/VM/Docker/CI/merge/deploy не нужны.

## Подготовленная actual characterization для ROOT

После одобрения source границы подготовлены focused native HTTP tests
с настоящим router/use case/SQL и identity fixtures, выдающими настоящие User.
Только authentication fixture заменяет текущего пользователя; company/member/
party/type/matcher/lock/transaction правила остаются настоящими.

Сценарии: golden всех CREATE/req/nullable полей и точного request hash;
omitted/default versus explicit null; company/visit/member negatives;
обе стороны malformed/missing/foreign и порядок ошибок; active/inactive/unknown
typeCode; same-key/same-body replay, changed actor/hash, company slug versus UUID;
business duplicate и разные стороны/даты; incomplete identity с ключом/без;
конкурентные POST с реальным advisory wait; caller rollback после flush.
Expected golden определён из полного литерального synthetic ввода, не вызовом SUT.
Сохранённое состояние читается новой SQL-сессией через mapped attribute keys.

Прежние affected tests: `test_contract_creation_replay.py` и три selected
Contract-теста `test_reference_identity_api.py` (duplicate, parties CREATE/PATCH,
changed-fields PATCH) без полного 117/allContract/allCP набора.

AST-подсчёт без pytest collect: **55 новых + 4 прежних = 59 proposed cases**.
Это план количества, actual результат ещё отсутствует:

| Группа новых случаев | Количество |
|---|---:|
| Полный literal golden, defaults/null/hash, blank req | 3 |
| Member/admin/superadmin и company/visit negatives | 7 |
| Malformed/missing/foreign стороны | 6 |
| Порядок ошибок, включая type до responsible UUID | 6 |
| Active/inactive/unknown/empty typeCode | 4 |
| CreationKey conflict: actor/body/нормализуемые значения/UUID spelling | 5 |
| Company alias hash и replay до повторного type lookup | 1 |
| Проверка сторон до key conflict | 2 |
| Business duplicate, error precedence и самостоятельные договоры | 7 |
| Неполная identity, keyed/unkeyed | 8 |
| Zero/false и company-scoped creationKey | 2 |
| HTTP/direct-use-case caller rollback | 2 |
| Две native POST SQL-сессии под прежним barrier | 2 |

Concurrency держит первый request transaction после flush через dependency fixture,
доказывает блокировку второго настоящим pg_locks/pg_blocking_pids, затем завершает
оба caller с commit и читает новую session. Таймаут 10 секунд и finally join/cancel
не оставляют фоновых тестовых задач; никаких новых app locks/ролей/GUC нет.
Rollback control откатывает HTTP caller после реального flush либо вызывает
native use case напрямую с настоящим User и откатывает свою session.

## Frozen source и ROOT-only gate

SHA256 относительно `clearledger/server/`:

| Файл | SHA256 |
|---|---|
| `app/routers/references_router.py` | `6e360e5c8347e34563933c6a8cef1be4eadf6c7f38825ddaa395bf1f74651db3` |
| `app/services/native_contract_commands.py` | `36216c6598133a4c707d1deff8ff64a7b0576b7280e7bf2cc88eeda09c095ad4` |
| `app/services/reference_validation.py` | `fec7fca58c47db80683e8bd39bc0394377c1be35d832061e1d0a004b98192d7b` |
| `tests/test_native_contract_create.py` | `bf4cf2d7c22d478c2235aaead82e208bab84a4c31be3c95524c200c089152408` |
| `tests/native_contract_create_approved.py` | `8039807560e81c4ea12cad4be18bab143daf2ca081afb66f88664dcd5f7ecb04` |

Полный app: **492 файла**, digest
`5dac9d07dbfe9079dc03f765c21ecd105bbf5542c4b9ff49b62533aa05e8bd84`.
Полный tests без self runner: **336 файлов**, digest
`761b83210b77c31d7cde07233d829821cc19d8e7503883fe0644c7b4b40f445a`;
отдельный self hash выше привязывает весь tests tree из 337 файлов.
Schema migrations: **16 файлов**, digest
`51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d`.
Формат: SHA256 compact JSON отсортированных `[relative-to-server path, sha256]`;
`__pycache__` исключён, symlinks отвергаются. requirements.txt/pytest.ini
также закреплены отдельно, зависимости не менялись и не устанавливались.

ROOT-only pre-import gate предназначен только для новой точной БД
`api_native_contract_create_test_20261030`, explicit approval/opt-ins,
чистой allowlisted synthetic среды и сохранённого HOME. Credentials безопасно
передаёт ROOT. Guard проверяет полный app, tests и schema_migrations;
для self-referencing runner его SHA256 фиксируется отдельно и передаётся ROOT,
остальной tests tree — immutable digest. Все manifest/raw evidence private.
Worker выполняет только AST/compile/diff и ожидает ROOT actual result/cleanup.

ROOT создаёт точную отдельную БД, передаёт matching TEST_DATABASE_URL/DATABASE_URL
без query/fragment, numeric loopback 127.0.0.1 и approved port в
`NATIVE_CONTRACT_PG_PORT`. Нужны flags `ROOT_APPROVED_NATIVE_CONTRACT_CREATE_TESTS=1`,
`RUN_NATIVE_CONTRACT_CREATE_TESTS=1`, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 и
PYTHONDONTWRITEBYTECODE=1; APP_ENV=test, synthetic SECRET_KEY и сохранённый HOME.
`NATIVE_CONTRACT_RUNNER_SHA256` должен равняться приведённому ROOT-reviewed self hash;
это исключает рекурсивное хранение собственного hash внутри runner.

Gate принимает только clean env allowlist и три разных пустых owned каталога
mode0700 с test в имени: `NATIVE_CONTRACT_EMPTY_CWD`, `UPLOAD_DIR`,
`NATIVE_CONTRACT_EVIDENCE_DIR`. Текущий cwd должен совпадать с первым.
Synthetic SECRET_KEY: `native-contract-create-synthetic-secret-only`.
Credentials не публикуются; `.env`, auth keys и реальные подключения не читаются.
Из пустого cwd ROOT запускает своим проверенным Python 3.13:

```text
python -I -B /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/native_contract_create_approved.py --execute-approved-native-contract-create-tests
```

После всех source/env guards впервые загружаются pytest/app/driver.
Обычный conftest разрушает public/edge только этой точной disposable БД,
поднимает actual schema/seed и очищает её в teardown; gate сам не создаёт,
не удаляет и не подключает БД. JUnit пишется в private evidence, stdout лог
ROOT должен хранить отдельно от проверяемого пустого evidence каталога.
ROOT подтверждает actual counts, child exit/reap, fresh relations/connections,
обычный DROP без FORCE/terminate, прежнюю lock quota и освобождение SQL slot.

## Ограничения до ROOT actual run

Native use case сохраняет прежний допуск до lock; новая проверка admission после
ожидания не добавлена. Object/org/null-intent policy не расширена. Partner write
не появился; общий native порт не принимает partner principal вместо User.
Исторические inventory и import CREATE proof остаются на своих pins;
их результаты не регенерируются и не выдаются за проверку нового app.
Полный CI, все contracts/CP, 117-suite, VM/реальные API/источники/данные,
сборка/выкатка/активация и закрытие M06 не входят в результат этого среза.
До ROOT actual evidence Dispatch не завершается как runtime принятый.
