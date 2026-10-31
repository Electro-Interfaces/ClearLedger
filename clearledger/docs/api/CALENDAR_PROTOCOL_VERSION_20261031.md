# M09-C2: сохранённая версия календарного приглашения

31.10.2026. База `ba9fc30be815a554cb0c646a6c75f59e17c19fb0`.
Статус: **ROOT accepted для draft integration:42 clean PASS; V3 native95 FUNCTIONAL / INVALID; V4 corrective19 clean PASS**.
Worker не импортировал app/runner/tests, не запускал collection, SQL или доставку.
Это пакет organizer revision; весь M09, M16, M00–M19, CI и release остаются открытыми.

## Исходное поведение

`services/meeting_notice.py::_sequence` выдавал `int(now.timestamp())` на попытку
извещения. В `conf_router._пригласить` число вычислялось даже отдельно для получателя.
Две правки в секунду могли совпасть; повтор доставки того же изменения выдавал новую
версию. `work_router.calendar_ics`, `_письмо_гостю` и `invite_router.invite_ics`
использовали отдельные `0/1`, лента подписки не передавала SEQUENCE.

CalendarEvent создают calendar_create, conf.meeting_create и materialize_series.
Organizer state меняют calendar_action, poll_open/pick, первый вход в комнату,
session_end при сокращении конца встречи, распространение URL серии.
calendar_action уже использует `calendar_series.lock_event`: голова перед экземпляром,
FOR UPDATE и populate_existing после ожидания. Остальные writers присоединены к этому
порядку. Ответы участника/гостя, COUNTER и вход в существующую комнату меняют отдельные
строки или присутствие и сами по себе не создают organizer revision.

Извещения идут после основного commit, затем отдельно сохраняется чат. Прежние
исключения доставки, email preferences, recipient filters, логика организатора,
guest revoke, аудит и ACL сохраняются. Новый counter не делает delivery атомарной
с записью встречи и не создаёт outbox. Audit/auth setup writes наблюдаются отдельно
от SQL-операций изменения встречи.

UID остаются прежними: native conference для своих `@conf.elsyplus`, обычная встреча
и гостевые каналы `@trek`. Исходное переключение собственного UID при первом добавлении
native room URL к старой встрече, ранее экспортированной как `@trek`, остаётся отдельным
gap. Соседние права также не исправляются: calendar_action сначала требует участия
даже у delegate; guest management имеет другой вход. Native product grants и проверка
CompanyApp в management API различаются; старые characterization cases сохранены.
Входящие calendar_replies сверяют DTSTAMP/responded_at, но не SEQUENCE; это отдельная
задача обработки устаревших ответов.

Ещё один существующий writer находится в legacy bootstrap `database.py:5291–5300`:
он переводит recurrence JSON-null в SQL NULL и удаляет materialized children головы
без recurrence/mode. Это не organizer edit и в пакет не перенесено. Fresh native
fixture запускает bootstrap до создания встреч; это не доказывает безопасный повторный
startup после отключения/cancel series и не исключает удаления уже published children.
ROOT уведомлён в `msg_379de982b565`; bootstrap/source/данные других пространств не менялись.

## RFC и выбранный профиль

SEQUENCE является неотрицательной organizer revision с начальным нулём. Общий
INTEGER ограничен signed32, поэтому верхняя граница SEQUENCE здесь `2147483647`.
DTSTAMP для объекта с METHOD означает время создания сообщения; LAST-MODIFIED
описывает изменение хранимых данных и является отдельным необязательным свойством.
Существующий DTSTAMP в UTC при сериализации сохраняется, LAST-MODIFIED по-прежнему
не добавляется. [RFC 5545 §3.3.8, §3.8.7](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.8.7.4).

Изменение времени/статуса и значимых условий организатором увеличивает revision;
REPLY/COUNTER её не увеличивают. UID коррелирует компонент, SEQUENCE определяет более
новую версию, DTSTAMP разрешает равенство версий. Доставка и retry одной редакции не
считаются новой правкой. [RFC 5546 §2.1.4–2.1.5](https://www.rfc-editor.org/rfc/rfc5546.html#section-2.1.4).

ROOT решения: `msg_9a4188aaa799`, `msg_df3284f09a6c`, `msg_ab3832b1d84d`.
`CalendarEvent.protocol_sequence`: int4 NOT NULL, CHECK `0..2147483647`.
Новый ORM передаёт Python default0. Один bounded owner `calendar_protocol` сравнивает
явные поля title/description/start/end/all_day/tz/location/conference_url/status/
cancel_reason/recurrence/recurrence_until и один раз увеличивает счётчик под row lock
до commit. Новые экземпляры серии начинают с нуля. Изменённые siblings получают свою
revision через тот же helper; текущая строка исключена из sibling bump.
Повтор без изменения state, чтение, PARTSTAT и добавление получателя используют
сохранённое число. Изменение времени вместе с новым участником даёт одну revision
и move старому составу / invite новому. При исчерпании диапазона изменение получает
409 и откатывается; wrap, clock counter и новый UID не применяются.

Все sender/download/guest/conference/feed consumers читают это поле. Лента получает
явный SEQUENCE. MIME, METHOD/STATUS, escaping/folding/CRLF, all-day/TZID, DTO и public
route profiles сохраняются. Прежде тихие metadata edits не получают новую рассылку
автоматически; исправление их delivery policy в этот пакет не входит.

## Legacy bound и единственный schema owner

`2000000000` является **именованной compatibility bound, не доказанным actual
legacy highwater**. Она больше обычных epoch seconds/minutes на дату пакета.
Неизвестные исторические рассылки с будущими часами восстановить из модели нельзя.
Cutover требует явного допущения «прежние отправленные SEQUENCE меньше bound» и
технического `--legacy-sent-before 2000000000` у explicit apply0002.
DB clock и max(created_at,updated_at) должны быть меньше bound; starts/ends для
этого не используются. Автоматического startup cutover нет.

`schema_migrations` расширен одним explicit target `0002_calendar_protocol_sequence`.
Default target остаётся `0001_product_api_budgets`. Единственные loader/catalog/
journal/runner принимают точный prefix0001/0002 без discovery и DOWN. Frozen0001
entry/files/artifact `301b88799018e0123f40a8bbbfec1415184147ba31bf43bb9432e9140ff15ab1`
сохранены. Explicit0002 требует проверенную applied0001 перед DDL; parent/ordinal/
predecessor checksum/source/actor/format проверяются для всей цепи. Default0001
после history0002 честно отказывает как при более новой истории.

Под прежним `(434532,1)` owner lock и ACCESS EXCLUSIVE на Core calendar_events
повторяются catalog/cutover checks; затем в одной transaction добавляются поле с
constant server default2000000000 и named CHECK, проверяется postcondition и append2.
Legacy строки получают logical baseline без изменения прежних бизнес-полей.
Adoption допускается только для точной формы нового поля/check; partial/drift не
ремонтируются. Repeat/check не меняют бизнес-строки или history xmin.
Старые columns/order/index/FK catalog до/после должны совпасть.

Core-only Config не расширялся на public. Core migration suite и native public
conftest являются двумя отдельными synthetic profiles в одной disposable DB,
выполняемыми последовательно. Public native proof не выдаётся за Core upgrade.
Fresh ORM DDL и upgrade имеют одинаковые field/default/check. SQL старого ORM
сохраняет совместимость с additive column: новые old-model INSERT получают server
baseline, новый ORM явно пишет0. Старый wire sender при rollback всё ещё использует
epoch/0/1 и не гарантирует эту protocol revision. Такой rollback и последующий
roll-forward требуют отдельного решения; автоматический DOWN/repair не добавлен.
Managed0001 gate после history0002 и rollout других namespace остаются release gates;
feature flags сохранены OFF, bootstrap/config не менялись.

## Frozen V4 inputs и ROOT-only runner

| Источник | SHA-256 / состав |
|---|---|
| Исходный models из exact Git base | `f066910e5bf5e2e37346edc8c78693d3673868186c925e1aad67f1d816f2104e` |
| Кандидат models | `be86657d24e43af2c9cbc09d9764873223cf3f04ed8ad2cf924ab90c153155af` |
| `calendar_protocol_version_approved.py` | `9cad4739cbbb472cf9818700326c5e20915cbcb1dabb244e71767a8e93249903` |
| `calendar_protocol_child_approved.py` | `30e510fec4e6eb318d1bb66437922f96149f30342ecbf63cee6fb01dbb045705` |
| Full app499 | `247876a7d8be6c4aa31e71b508d1fce581021dfa71bc1a95186ef743fc12ad95` |
| Full tests373, excluding parent runner only | `0f2a89debf5895ae1efb8ff38fd6183402f0110db1df6d2ba547df548bb8b8f0` |
| Full schema_migrations21 | `145c7feedb786d3df47d00c826b26c48ad666cd52bc60d381a4cad10ba265372` |
| SQLAlchemy268 | `a6476b4195ce507ae5c42a7dbcfec0ee256935ea27ae60e6047799e56f010beb` |
| asyncpg81 | `c716bdbecb918d51e57aa934cc19cbcf67963d4147bde7f1a428ea8b3bfca3d1` |
| Frozen0002 artifact | `203ee350a47fb3e12d2e2fb6d292fc0e1a19b4cd3cd348b507551cf233cae2f0` |

Tree digest — SHA256 compact JSON sorted `[relative_path, file_sha]`, без
`__pycache__`; относительные paths от server, для library trees от site-packages.
Девять support/tool pins, включая requirements/pytest/Dockerfile/official exporter/
SDK generator+lock+tests+consumer, перечислены в runner. Candidate77 inventory
61+16 остаётся exact. Старые pure14/PG13 harness files не менялись; все32 прежних
actor MIME assertions совпали по AST, изменён только одобренный obsolete clock
monkeypatch seam `raising=False` с честным комментарием.

Общий source-file cap остаётся8MiB. Только два exact pinned TOOL_TREES имеют
file cap16MiB: native asyncpg file9 481 488 bytes не помещается в source cap.
Полные counts/hashes/общий tree cap64MiB и отказ symlink остаются прежними.

ROOT выполняет четыре serial fresh processes и проверяет cleanup между DB phases:

| Phase | Selection | Planned cases |
|---|---|---|
| pure | unchanged PureFoundation14 + CalendarPure6 | 20 |
| foundation | unchanged ActualFoundation13, new strict guard/config bindings | 13 |
| migration | ProtocolMigration Core actual SQL + old/new source ORM DML | 9 |
| native V3 historical | test_calendar_protocol_version18 +96 old SQL/HTTP/ICS/MIME cases | 114 |
| native V4 corrective only | exact19 failed setup full IDs from V3 boundary/XML | 19 |

V3/V4 counts ниже подтверждены отдельно. Literal V4
CORRECTIVE_NODEIDS точно равен 19 setup-failed IDs из фактических V3 boundary/XML,
с сохранением параметров и уникальности. Повтора95 или предыдущих42 cases нет.
Старый PG13 guard заменяется явно reviewed boundary не слабее прежней: RAW/TARGET/
BASE/EMPTY/UPLOAD/EVIDENCE/config/guard, с old guard source SHA и new runner SHA в receipt.
Методы и assertions прежнего harness не переписаны и не пропускаются.

V4 admission касается только существующего P4 management_data fixture. Исходный
`tests/test_management_api.py` закреплён SHA
`cf0a2d05e21970fce0a1404ea6220dab5614efffa7a9f1226d26ab698e2884e5`.
MANAGEMENT_CONFIG_PATH отсутствует в исходном env; setter допускается только от
его original source code metadata и текущего setup node из exact19. Значение —
regular owned0600 management.json в tmpdir именно этого node под owned scratch;
bytes строго равны прежнему json.dumps(enabled=true,hub_enabled=true,code=desk,
name="Управляющее пространство"). Unset требует тот же binding/node, teardown и
pinned MonkeyPatch.undo; никаких общих env/path разрешений не добавлено.

`os.symlink` остаётся запрещён. Только два alias pinned `_force_symlink` заменяются
проверенным no-op: exact TempPathFactory._make_counted_dir caller, текущий setup node,
owned numbered tmpdir и исходный normalized current-link target. Pytest pathlib/
tmpdir/monkeypatch files дополнительно закреплены SHA в TOOL_SOURCE_FILES. Receipt
должен содержать ровно19 set/unset/suppression node IDs, пустые active bindings,
25 negative/positive metadata controls и exact selection без extra/duplicate/missing.
Controls на worker не исполнялись. Решение ROOT `msg_ecf77bf35a98`.

Subprocess capability ограничена пятью exact pure test sites и двумя actual CLI
запусками oldPG13 test12. Parent проверяет identity code object метода, argv/env,
count и exact script bytes, shell/extra options запрещены. Активная ContextVar
допускает только один точный Popen audit event. Child повторно проверяет source,
candidate77, target, private paths и request; реальные код/CLI исполняются с
`-I -S -B`, SQL/results не имитируются. Для pure разрешены только два frozen code
текста либо pinned runner plan / historical approved harness negative. В foundation
разрешены только actual runner apply/check default0001 с exact target. Original
credential environment восстанавливается после approval внутри child; argv
содержит только путь private0600 JSON payload, не DSN. Других process grants нет.

До imports устанавливаются numeric-owned PG socket/sendmsg buffers-only boundary
и16 metadata controls, no external DNS/HTTP/SMTP/chat/push/conference delivery,
five import IPv6 probe suppression/restore, env/write/process/scratch bounds.
Для owned loopback PG используется ssl=False без ~/.postgresql; TLS этого fixture
не доказывается. Native transaction/audit SQL counters и terminal SMTP stubs
ставятся до app imports; настоящий meeting MIME renderer остаётся действующим.
Fixtures используют только синтетические адреса/ключи. Scheduler loop не запускается;
прямые bounded series service calls проверяются в synthetic DB.

ROOT извлекает baseline blob через Git, private0600, например в
`/tmp/api-calendar-protocol-version-test-20261031-ctx5b7770/baseline-models.py`.
Для каждой phase ROOT создаёт отдельные owned0700 пустые cwd/upload/evidence/scratch
вне source, без вложенности и dotenv ancestors. Exact argv для parent:

```sh
/srv/projects/api-modernization-upgrade-test-env-20261030/.venv/bin/python -I -S -B \
  /home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030/clearledger/server/tests/calendar_protocol_version_approved.py \
  --execute-approved-calendar-protocol-version-tests
```

Exact cleanenv (`env -i`): HOME=/home/mag, PATH=/usr/bin:/bin,
LANG=LC_ALL=C.UTF-8, APP_ENV=test, SECRET_KEY=calendar-protocol-version-synthetic-secret-only,
DATABASE_URL=TEST_DATABASE_URL=`postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_calendar_protocol_version_test_20261031`,
M09_PG_PORT=33546, PYTHONDONTWRITEBYTECODE=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1,
ROOT_APPROVED_CALENDAR_PROTOCOL_VERSION_TESTS=RUN_CALENDAR_PROTOCOL_VERSION_TESTS=
RUN_CALENDAR_QUERY_OWNER_TESTS=1, SEED_SUPERADMIN_EMAIL=admin@clearledger.ru,
SEED_SUPERADMIN_PASSWORD=admin123, ECOSYSTEM_COMPANIES="",
M09_PHASE=native (V4 refuses repeats of prior phases), M09_RUNNER_SHA256=parent SHA above,
M09_BASELINE_BLOB=exact owned blob, M09_EMPTY_CWD/M09_EVIDENCE_DIR/
M09_SCRATCH_DIR/UPLOAD_DIR=phase private roots, TMPDIR=M09_SCRATCH_DIR.
Никакие ambient env/proxy/credentials не наследуются; synthetic seed задан до
первого cached Settings, проверяются OFF flags.

Parent caps: CPU480s, wall600s, address space1GiB pure /8GiB SQL+native,
FD128, file4MiB, scratch/evidence/upload128MiB каждый/4096 entries.
Child caps: CPU30s, wall35s, address1GiB pure /8GiB foundation, FD64/file2MiB;
old caller timeouts10s/25s остаются. ROOT outer650s TERM/KILL/reap всей process group,
bounded stdout/stderr и отдельный synthetic PG. Child не создаёт БД/роль/сервер.
ROOT удаляет только собственные tmp/blob/test DB и сохраняет receipts; чужие ignored
proofs и прежние M16/M14 artifacts остаются неизменными.

## Приёмка и оставшиеся ограничения

На worker выполнены только source reads, Git, AST/compile и artifact hashing.
V1 actual не запускался. Source review обнаружил ошибочный setter readonly
`Settings.jitsi_enabled` в новом fixture. По ROOT `msg_51e2d9fce3a0` V2 удаляет только
эту строку; synthetic signing_key сам включает property. Production/schema/guards/
counts/assertions не менялись; изменены tests digest и parent self SHA.
V1 runner SHA `a77f059c7bf52525ab51730028b7b7d6f04ad7c39eea05135a90705b87281c25`,
report SHA `533d84da1ca89e73bd4cf4bb97ddb5bce580cb9073402bc5c60a168819e118c8` и
input manifest сохранены в ignored
`.artifacts/calendar-protocol-version-worker-20261031-ctx5b7770/v1/`.
ROOT V2 pure parent reaped exit2 за1.0076s до tests/app/SQL: inventory отказал на
8MiB generic cap для exact asyncpg native file9 481 488 bytes. Диагностика
подтвердила SQLAlchemy268/12 426 207 bytes и asyncpg81/13 281 096 bytes с теми же
frozen hashes. По `msg_2869a125e0ad` V3 меняет только tool-file cap16MiB,
production/schema/tests/child/остальные guards не менялись. V2 архив и manifest:
`.artifacts/calendar-protocol-version-worker-20261031-ctx5b7770/v2/`;
старый runner SHA `3585c3ae6df078a12e0d28084c39f1f3acab28955b59455b6abb0bf124b05cbc`.
ROOT evidence `.artifacts/root-calendar-protocol-review-20261031/v2-pure/` и
`diagnostic-v2-pure/`.

Фактические ROOT V3 receipts `msg_98f6999068c4`, `msg_bc17620cfe81`, `msg_aa7ff9a648c4`:

| Stage | Actual result | Время suite / outer |
|---|---|---|
| pure | 20 PASS,5 strict actual children | 6.705s /8.525019955s |
| foundation | 13 PASS,2 actual strict CLI children | 24.807s /26.546720575s |
| migration | 9 PASS,real Core SQL + old/new ORM DML | 13.929s /17.032508657s |
| native V3 | 95 FUNCTIONAL call PASS,19 setup ERROR,0 call FAIL; boundary INVALID | 37.24s /54.132957052s |
| native V4 corrective | 19 PASS,clean boundary,exit0/reaped | 20.26s /36.612766533s |

Первые42 cases имеют receipt ok/sourceAfter/candidate77/16 controls/forbidden0.
Каждая SQL stage завершена normal DROP:0 relations/0 clients/exists0, maxlocks64.
Native V3 sourceAfter/77/16 true, но38 denied:19 pytest current-symlink probes и19
MANAGEMENT_CONFIG_PATH setenv из management_data115. Stacks всех deny совпадают с
этими двумя fixture sites. Все19 setup errors — зависимые P4 SQL cases; в V3 не было
per-event nodeid, поэтому95 positives не объявляются отдельным clean-boundary PASS,
а вся исходная native phase сохранена как INVALID. Source/reports/evidence сохранены
в ignored `.artifacts/calendar-protocol-version-worker-20261031-ctx5b7770/v3/`, включая
полные boundary/XML/process и input manifest; ROOT оригинал остаётся в
`.artifacts/root-calendar-protocol-review-20261031/v3-native/`.

V4 меняет только parent native admission/selection и report; production/schema/tests/
child/старые assertions неизменны. ROOT `msg_ea0ad9ea0995` принял пакет с этой границей:
corrective19 sourceAfter/candidate77/16 PG controls/25 fixture controls true,
forbidden0; exact19 set/unset/no-op node IDs проверены, system symlinks не создавались.
Normal DROP:0 relations/0 clients/exists0, maxlocks64. Evidence:
`.artifacts/root-calendar-protocol-review-20261031/v4-native/`
(`process.json`, `r1-evidence-test/calendar-protocol-boundary.json`, XML/log).
Единый156/114 clean-run и full CI **не заявляются**. После actual изменён только
этот отчёт; production/schema/tests/runner/child остались frozen.
Schema/harness drift не скрывается изменением старых
assertions или repair. Live legacy highwater, реальный backup/restore, deploy,
полный M09/M16/CI и release этим пакетом не подтверждаются.
