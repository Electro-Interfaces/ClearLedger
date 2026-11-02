# M07/M15: матрица эквивалентности read ACL документов, 30.10.2026

Результат: **8 PASS / 0 FAIL / 0 SKIP за 17,78 с** на выделенной synthetic
PostgreSQL 16 после source review и отдельного root GO. Opt-out отдельно:
**1 SKIP / expected exit 5**, без app/conftest imports. Runtime-кандидат не выбран
и не разрешён. Это characterization исходного контракта, не доказательство
эквивалентности будущего rewrite и не закрытие M07/M15 или M00–M19.

## Основа и границы

- Immutable root: `6e6cf5010919ca7bfbee35c35ac4745b560d1055`.
- Ветка: `agent/api-document-deny-characterization-20261030`, в уже существующем
  изолированном worktree `api-intake-upload-client-20261030`. Другие ветки не менялись.
- Ownership: только этот отчёт и новый
  `server/tests/test_document_read_acl_equivalence.py`. Root согласовал S×3/B/E/A/D/H
  ответом на ask; optional NULL-control исключён.
- Runtime, модели, auth, Query, ACL, listeners, старые тесты, DDL и ограничения
  остаются исходными. Отдельная ветка statistics-control не является runtime candidate.
- До отдельного GO выполнялись только source/AST/compile. После GO выполнены
  один opt-out без conftest и один actual SQL/HTTP baseline на собственной БД.
  Admin/CREATE/DROP/EXPLAIN/ANALYZE/browser/SSH и реальные env не использовались. Инструкции AGENTS/CLAUDE, rushydro-space,
  orchestration и Postgres прочитаны. Предписание immutable root имеет приоритет
  над общим `git pull`: основа не обновлялась и общие рабочие ветки не переключались.

## Существующее покрытие и реальные пробелы

| Источник | Уже закреплено | Что не доказывает |
|---|---|---|
| `test_doc_access_policy.py` | 84 mock policy/compile/AST checks по отчёту M07; deny read поверх owner/admin/grant для user/role/department; strict/break-glass; file gates | Фактические результаты SQL `_readable_doc_clause`, приоритет doc/kind deny при обеих настройках наследования |
| `test_docs_next.py` | Real DB `_can_doc`: private, acquaintance, doc read + kind edit; администратор управляет ACL, но не читает private; назначения approve/sign | Результат SQL clause на том же наборе; изолированное выключение kind inheritance, role/department SQL subjects |
| `test_docs_archive_security.py` | Deny read распространяется на контент; запрет другого субъекта не совпадает; break-glass permissions | Actual correlated EXISTS/anti-EXISTS |
| `test_docs_archive_flow.py::test_strict_deny_и_break_glass_закрывают_прямой_файл` | Реальные HTTP/file strict, deny download, break-glass, аудит и capabilities | SQL список strict/break-glass; совмещённый doc/kind deny |
| `test_docs_editing_unit.py` | Clause подключён к SQL выборке | Результат clause подменён в тесте |
| `test_partner_resource_query_budget.py` | Реальный verifier, SQL и HTTP, resource profiles, tenant negatives | Содержательные doc/kind ACL goldens |
| `test_product_query_scaling.py` | Actual HTTP/count/page/detail: company, private doc user allow, company doc deny, strict; tenant/member objects/organization/resource grants | Kind inheritance/precedence; роли/подразделения; delegation; NULL algebra |

Прежние **222 PASS = 138 существующих + 84 новых**, а не 222 pure policy checks.
Это исторические результаты `doc-access-policy-20261029.md`, они не переобъявляются
результатами нынешнего прогона. Новые pure bool/mock policy-тесты не предлагаются.

## Согласованная и пройденная матрица

Goldens задаются явными идентификаторами сценариев из смысла действий и старых
fixtures; они не вычисляются копией boolean implementation. Actual SELECT
вызывает штатную `_readable_doc_clause`, добавляя обязательные company/id predicates.
Actual `_can_doc(..., 'read')` сверяется с теми же константами как второй
потребитель контракта; его результат не является oracle для clause.

### S: doc/kind precedence (один grouped тест на каждый user/role/department)

Все карточки private, автор/ответственный/подписант пусты, назначений нет;
каждая карточка имеет отдельный реальный kind, чтобы kind ACL соседней строки
не влиял на результат. Субъект подтверждён настоящим UserCompany.

| ID | doc ACL | kind ACL | inherit | Golden read | Основание |
|---|---|---|---|---|---|
| S01 | allow read | — | FALSE | да | Прямой допуск не зависит от наследования |
| S02 | allow edit | — | TRUE | да | Действующий контракт edit включает read |
| S03 | — | allow read | TRUE | да | Включён допуск вида |
| S04 | — | allow read | FALSE | нет | Закрытая карточка отказалась от вида |
| S05 | allow read | deny read | TRUE | нет | Явный наследуемый запрет перекрывает допуск |
| S06 | allow read | deny read | FALSE | да | Отключённый запрет вида не применяется |
| S07 | deny read | allow edit | TRUE | нет | Прямой запрет не отменяется видом |
| S08 | deny read | allow edit | FALSE | нет | Прямой запрет действует без наследования |
| S09 | empty allow/deny | — | FALSE | нет | Пустой grant не создаёт допуск |
| S10 | — | allow edit | TRUE | да | Действующий read-from-edit для вида |

Три параметра дают 3 pytest items и 30 маленьких карточек, не 30 отдельных тестов.
Противоположные read allow/deny находятся в разных scope rows, а не в одном
payload, который HTTP writer отвергает как противоречивый.

### B: базовая видимость и назначение под запретом (один grouped тест)

Для company, author, responsible, signatory, direct approval, acquaintance:
шесть отдельных карточек, три последовательных persisted состояния: исходные
допуски, matching doc deny read, затем deny edit. Goldens: все шесть / пусто /
все шесть. Автор последней стадии заменяется на private edit-grantee с deny
download, чтобы отдельно закрепить read-from-edit без базовой видимости. Direct approval
не сужается новым правилом до текущего pending: действующий read-контракт
сохраняет доступ непосредственного адресата независимо от статуса/раунда.
Дополнительно: company + deny edit остаётся читаемым; private + allow edit /
deny другого действия не превращает этот запрет в deny read; matching allow и
deny другого пользователя не открывают/не закрывают карточку текущему человеку.
`others` означает других субъектов, не новый subject_type: constraint допускает
только user/role/department.

### E: отсутствующая роль и подразделение (один grouped тест)

Persisted UserCompany.role_id/department_id = NULL; подходящий user grant
работает, grants другим role/department не работают; deny другого субъекта не
мешает company-read. Пустые permissions/denied_permissions — реальные `[]`.
Полностью пустые subject_filters при настоящем non-null User.id недостижимы:
такой branch не покрывается подменой `_subject_ids` и не объявляется проверенным.

### A: admin/superadmin/strict/break-glass (один grouped тест)

Admin (is_superadmin=False): private без допуска не читается; company с deny read
не читается. Обычный назначенный author/grantee strict-карточки читается по
действующему контракту. Superadmin: private и company читаются даже при deny;
strict исключён из SQL списка и до, и после real persisted break-glass read.
Для `_can_doc` strict до break-glass — нет, после — да; probe
`record_break_glass_use=False` не увеличивает use_count. Это два разных контракта
списка и точечного чтения; их нельзя искусственно объявить общим golden.

### D: delegation (один grouped тест)

Реальный UserSubstitution в действующем интервале дат; текущий человек — deputy.
Private signatory=principal: draft/registered — да, archived — нет.
Private approval principal: явно current round=2 + pending — да; previous round=1 либо
не-pending — нет. Matching deny read текущему deputy перекрывает позитивное
назначение. Прямой адресат визы и deputy сохраняют разные условия; не копировать
ограничение deputy в direct assignment. Чужой/неактивный principal не выдаётся за
активное замещение. Для дат используется действующий BUSINESS_TIMEZONE без fake clock.

### H: реальный product HTTP (один grouped тест)

Переиспользуются неизменённые `budget`, `signing_pem`, `profiles` из
`test_partner_resource_query_budget.py`, штатные verifier, Query, app, sessions.
Шесть новых карточек: edit, kind-deny, inherit-off, object, organization, grant.
Сначала ALL profiles дают точный список из пяти (все кроме kind-deny), total=5.
После persisted ограничений точный список edit/inherit-off, total=2. В обеих
стадиях list, total, nextCursor и detail 200/404 имеют константные goldens;
поиск по уникальному synthetic prefix исключает три исходных документа fixture.
Tenant — отдельная чужая карточка fixture с тем же searchable prefix и 404
в обеих стадиях: её не скрывает q, поэтому count/list тоже ловят tenant leak. Позитивный
ACL у object/organization/grant отрицательных строк остаётся одинаковым:
каждая отличается только одной из этих границ. Related object resource SET
исключает объект разрешённых документов, и objectId в их DTO должен быть NULL.
Ни list/count/detail, ни read ACL не должны расширить эти границы. Настоящий
чужой tenant создаётся fixture; противоречивые cross-tenant grants/assignments
не вставляются в обход writer как якобы нормальные business fixtures.
Машинный 403 и прежний большой scaling-набор переиспользуются как evidence,
повторный полный scaling в этом маленьком ACL suite не планируется.

### N: NULL boundary, SQL control исключён решением root

`DocCard.inherit_kind_acl`: Boolean nullable=False, default/server_default TRUE;
`DocAccessGrant.subject_id/scope_id/permissions/denied_permissions` также NOT NULL.
Не вставлять NULL-карточки/subject IDs, не снимать constraints и не менять DDL.
NULL остается границей схемы: persistence/control для него не добавлен.

Согласовано **8 actual pytest items**: S×3 + B + E + A + D + H, шесть функций.
Число pytest items определено только AST исходника, без collection.

| Группа | Новые карточки | Состояния/ячейки результата |
|---|---:|---|
| S×3 | 30 (10 на item) | 30 (10×3) |
| B | 6 | 18 (6×3) |
| E | 3 | 3 |
| A | 3 | 9 (3×3); strict SQL/detail goldens разделены после break-glass |
| D | 7 | 14 (7×2); второе состояние — inactive substitution |
| H | 6 | 12 своих detail + 2 foreign negatives, 2 list/count/page проверки |

Итого 55 новых карточек, максимум 10 на item; штатная fixture дополнительно
создаёт 3 своих + 1 чужую карточку на item (32 на весь прогон). Итого **87
карточек** сверх seed/штатного create_all. Группы S/B/E/A/D проверяют 74
логические ячейки каждая через actual SQL SELECT и отдельно `_can_doc` по
одним hardcoded goldens; H делает 16 HTTP запросов (2 list + 14 detail).
Число ячеек, assertions, SQL statements и pytest items не смешиваются.
Все восемь items прошли; указанные размеры получены из полностью завершившихся
ветвей теста. Отдельный счётчик SQL statements не вводился.

## SQL gate и выполненный runner contract

- Только root выдаёт serial SQL window после statistics-среза; отсутствие ответа
  не означает GO. Никакого collect/opt-out запуска до GO.
- Own DB: `api_document_read_acl_equivalence_test`, PostgreSQL 16,
  `127.0.0.1:33546`, роль `clearledger`, synthetic password `api_test_only`.
- Обе exact URLs: `postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_document_read_acl_equivalence_test`.
- Assigned interpreter: `/srv/projects/api-modernization-test-env-20261029/.venv/bin/python`
  (этим Python 3.13.7 выполнены только AST/compile своего файла).
- До первого app/DB import: общий `partner_test_safety_error` + собственный opt-in
  `RUN_DOCUMENT_READ_ACL_EQUIVALENCE_TESTS=1`, `RUN_PARTNER_RESOURCE_TESTS=1`,
  точное совпадение обоих URI, `APP_ENV=test`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- Empty cwd: `/srv/projects/api-modernization-test-env-20261029/document-read-acl-empty-test`.
  Отдельный UPLOAD_DIR:
  `/srv/projects/api-modernization-test-env-20261029/document-read-acl-test-uploads`.
  HOME не переопределять. Empty cwd нужен до pytest, чтобы не подхватить `.env`.
- Pre-pytest preflight connection с timeout=5s: exact own database/current_user,
  PG16/max_locks_per_transaction=64, нет других client backends в synthetic
  экземпляре, size <256MiB; statement_timeout=15s, lock_timeout=1s.
  Выполняется только в согласованном SQL window. При отказе не fallback/retry.
  Timeouts 15s/1s относятся к preflight connection; pytest/conftest sessions
  сохраняют исходные настройки/listeners. Общий runner bound — 180s, без retry.
- Только затем pytest с явным `-p pytest_asyncio.plugin`, без cacheprovider,
  фиксированным собственным файлом, `--maxfail=1`, session loop и штатным
  `tests/conftest.py` (DROP public/edge → штатный create_all/seed → teardown).
  Fixture/Query/ACL/listeners не подменяются; event remove/listener bypass нет.
  Десять source pins проверяются до первого подключения, включая conftest и
  общую fixture; расхождение прекращает baseline до SQL.
- Runner: собственный файл как guarded entrypoint с точным аргументом
  `--execute-approved-baseline`. Точные source SHA и argv ниже переданы root до GO.
- Приватные junit/log/preflight — только собственный каталог вне Git, с mode0700;
  в отчёт только безопасная сводка/счётчик. Источники, pass/fail/skip и baseline
  надо различать. Длительность не доказывает оптимизацию без actual plans.

## Source pins (SHA-256 относительно clearledger)

```text
b2f8c364edf7fd84474faf7b49b3e6a4a64c4148123cb9610c2e5a36dfe3fcbd  server/app/services/doc_access.py
01952021e056ec80a5a7449e67d489225b7cc7463e96cd6199557656f4a8ecac  server/app/services/doc_approvals.py
1f53491a8e8321ae02ddb991d873836b25e7011ec4071f71cc9540dd9ddab046  server/app/product_api/queries.py
9edd931485539ffd23e696c4a37efad2e1060d1f69f434ce6b592ea1b1f85ebc  server/app/product_api/access.py
06bfb7c6f7bce8ac345dbcbe23ee642e932ec2a9341673b20a1205c4f3206fee  server/app/models.py
be856862b369d89da8c7993fd974b70481260f37f07b7ca5a6d20db6ac077c3c  server/app/database.py
32ea55b426d111d8615e0f85ac7561a55ec802ee98a2b59a336405205ab1f57b  server/tests/conftest.py
43de791a8f0b418f03d4cdc155c2d8cc2d923757134f88b91870a539609eafb1  server/tests/partner_test_safety.py
b608f568bde0d6200491d40daff981aae7af94a8e42dbd7d29c9a44f5f878704  server/tests/test_doc_access_policy.py
fb98e3ba17cf08ea428fd969e0c66d447e9ba66dbc22ffd897bea9fa47ad3b26  server/tests/test_docs_next.py
3ab47f42f37fcf538b732370aee211020f7e3c4e0e8bde6ef97a688247e4a181  server/tests/test_docs_archive_flow.py
c450c4c8836cbebb2148528ddcdc67ce5ed041ee073cb9ec2951a58e4cadead1  server/tests/test_partner_resource_query_budget.py
054f2c99deba32c25459f68688e5f29cfa4b83f8b3ec0bda2635c844620165c2  server/tests/test_product_query_scaling.py
bbae173f083b3636872d1311ed8e247e51e7149de4aa752189a2f7bb2511c601  server/pytest.ini
```

Непроверенных current-policy contradictions на этом source checkpoint не установлено.
Возможное расхождение на будущих synthetic controls сначала сообщается как гипотеза,
без объявления vulnerability/production incident и без auto-fix.

## Выполненный guarded runner (для повторения требуется новый GO)

Root создал свежую own DB и пустые test directories после normal DROP предыдущей
statistics DB; admin connection был закрыт до передачи эксклюзивного окна.
Повторный запуск либо создание БД без нового root GO не разрешены. HOME сохранён. Env flags проверяются
до app/database imports и до pytest, общий conftest неизменён.

```sh
cd /srv/projects/api-modernization-test-env-20261029/document-read-acl-empty-test
timeout --signal=TERM --kill-after=10s 210s \
  env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
  RUN_DOCUMENT_READ_ACL_EQUIVALENCE_TESTS=1 RUN_PARTNER_RESOURCE_TESTS=1 \
  TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_document_read_acl_equivalence_test \
  DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_document_read_acl_equivalence_test \
  APP_ENV=test PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 SECRET_KEY=synthetic-document-acl-test-key \
  UPLOAD_DIR=/srv/projects/api-modernization-test-env-20261029/document-read-acl-test-uploads \
  /srv/projects/api-modernization-test-env-20261029/.venv/bin/python -I \
  /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/test_document_read_acl_equivalence.py \
  --execute-approved-baseline \
  > /srv/projects/api-modernization-test-env-20261029/private-document-read-acl-20261030/baseline.log 2>&1
```

Source-only validation: AST parse + compile своего файла под assigned Python
3.13.7 PASS; 6 функций и 8 items по literal parameterization. Приложение и
модели при source-only проверке не импортировались. Actual результаты ниже.

SHA-256 нового теста: `4b94fe10d81467d5c0dfe9204ea8abc3ec88dce9890213220f1524b890b6acb5`.

Source review root: обычная module collection без own opt-in теперь SKIP до
app/DB imports; main runner без flag остаётся строгим отказом. Один разрешённый
opt-out затем подтвердил SKIP и отсутствие app/conftest imports.

Source review root: D fixture теперь явно current round=2, matching pending/
completed/denied round=2 и previous round=1; модель default=0 не менялась.
Runner очищает env, сохраняя исходный HOME, PATH/LANG и фиксированные тестовые
переменные, использует -I и external timeout210s + kill-after10s при internal180s.


## Actual baseline и передача SQL-окна

30.10.2026, 11:44 MSK. Root независимо прочитал весь test/report, измерил полный
SHA теста и сверил 10 source pins; затем явно разрешил один opt-out и один baseline.
Worker не выполнял admin SQL, provision/CREATE/DROP, EXPLAIN/ANALYZE либо retry.

| Проверка | Actual результат |
|---|---|
| Opt-out, без own flag, `--noconftest`, explicit asyncio plugin | 1 SKIP, exit 5 ожидаем, 0,08 с; assertions no app/conftest imports PASS |
| Preflight own DB | PG 160015 (16.15), clearledger, max_locks=64, other_clients=0, 7 765 015 bytes |
| S / user, role, department | 3 PASS |
| B / основания видимости, deny read, deny edit | PASS |
| E / nullable role/department, другой реальный субъект | PASS |
| A / admin, superadmin, strict, persisted break-glass | PASS; list/detail goldens различаются только по установленному контракту |
| D / current round 2, previous round 1, inactive substitution | PASS |
| H / actual verifier → Query → list/count/detail и link redaction | PASS |
| Baseline целиком | 8 PASS, 0 FAIL, 0 SKIP, 0 warnings, 17,78 с; junit time 17,786 с |
| Outer process | EXIT 0, reaped; штатный session teardown и закрытие Python процесса завершены |

74 логические SQL/per-card ячейки и 16 HTTP requests пройдены. Это не 74 pytest
items и не 16 SQL statements; SQL statement counter/latency budget не добавлялись.
Contradiction на выбранных допустимых fixtures не обнаружено. Ни уязвимость,
ни production incident, ни ускорение SQL этим результатом не заявляются.

Приватные artifacts (mode0700 directory, вне Git):
`/srv/projects/api-modernization-test-env-20261029/private-document-read-acl-20261030/`
содержит `preflight.json`, `optout.log`, `baseline.log`, `results.xml`.

После reaped EXIT0 worker сообщил root `SQL_SLOT_RELEASED`. Новых SQL/connect/
collect/retry не выполняет; независимая проверка fresh public / edge0 / conns0 и
normal DROP own DB принадлежат root. На момент этой записи подтверждение root
ещё ожидается. Полный CI, future candidate comparison, индексы, merge и deploy
не выполнялись; общая программа M00–M19 открыта.


## Независимая приёмка координатора

Root принял source commit `7ba64e2c32934a4d9970fe666f7357cf7377b9a0`
в integration как `ccfcd653f5cc01490bbf8571f9e89eae4a230ead`. Повторно
измерены SHA теста и все 10 source pins; diff содержит ровно два новых файла,
JUnit подтверждает 8 PASS / 0 FAIL / 0 SKIP за 17,786 с. Проверены preflight
и хеши четырёх приватных artifacts. Это независимая проверка исходников и
артефактов авторского прогона; второго SQL-прогона root не выполнял.

После SQL_SLOT_RELEASED root отдельно подтвердил fresh public/edge tables=0,
затем выполнил обычный DROP своей тестовой БД без FORCE. Новое соединение
подтвердило DBexists=0, ownconns=0, otherclients=0, max_locks=64. Очистка
завершена. Приватная сводка: `.artifacts/root-document-read-acl-artifact-proof.json`.

Матрица закрепляет существующие различающиеся list/detail goldens для strict
с break-glass. Новая реализация ACL не выбиралась и не сравнивалась; runtime,
схема, индексы и рабочие данные не менялись. Полный CI и выпуск не заявляются.
