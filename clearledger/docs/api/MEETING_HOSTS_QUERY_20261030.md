# M04/P1: общий запрос ведущих встречи

**Статус: ROOT scoped PASS — 8/8 cases, cleanup подтверждён.** ROOT выполнил
frozen runtime/tests/runner; worker выполнял только source-проверки и compile
в памяти. Полный M04 не закрыт, выпуска, активации функций и изменения рабочих
данных нет.

База: `05e462d99009580bd529e3096740fdc077e83dd2`, собственная ветка
`agent/api-meeting-hosts-query-20261030`. Историческая карта на d70581b4 не меняется.
Проверенный frozen commit: `c4b245e627c716b09d1868b86a72dae9557145ab`.
Полная воспроизводимая proposal и доказательства находятся в
`.artifacts/meeting-hosts-query/` этого рабочего дерева.

Изменены ровно три runtime-файла:

- `server/app/services/jitsi.py`: `async meeting_hosts(db, ev) -> set` с прежними
  query и fallback, с локальными imports select/CalendarAttendee.
- `server/app/routers/conf_router.py`: прежняя `ведущие_встречи` с теми же async,
  аргументами, annotations и set-результатом делегирует новому owner.
- `server/app/services/meeting_notice.py`: единственный локальный router import
  удалён, вызов заменён на уже импортируемый `jitsi.meeting_hosts`.

Сохранены исходные event_id/is_host IS TRUE, set и fallback
`отмечены or {ev.organizer_id}`. Новых ACL, фильтров компании, сортировки,
обработки NULL и commit нет. JWT/signing, комнаты, moderator/wait/presence,
entry policy, текст приглашений, cancel/move, ICS/SEQUENCE, recipients и
transaction owners не менялись. Для external monkeypatch старого router helper
не заявляется влияние на notices: оно теперь идёт к сервису напрямую.
Существующий entry seam через `conf_router.ведущие_встречи` сохранён; отдельного
repo consumer с monkeypatch этого helper исходники не показывают.

## Source proof, выполненный worker

`source_proof.py` не импортирует app/tests/runner. Он сравнил query+fallback
**точными source segments и AST**, проверил wrapper signature/annotations,
удалил из нового jitsi только новый helper и обратил две разрешённые подстановки
в других модулях. После этого AST всех трёх модулей целиком совпал с базой:
остальные тела и global bindings сохранены. Результат — `source-proof.json`.
Все пять Python-файлов патча разобраны и скомпилированы только в памяти;
`git diff --check` выполнен. App tests, pytest collect/gate/SQL worker не запускал.

Новый source-only inventory на frozen commit подтвердил
**492 файла / 482 AST / 19 sites / 28 bindings**, удалена ровно историческая E19.
Остальные 28 полных edge records совпали за исключением перенумерованных ID.
Pin, hashes и сравнение сохранены в приватных `proposal.json`,
`inventory-comparison.json`, `inventory/receipt.json`. ROOT независимо
подтвердил AST-границы трёх runtime-модулей.

## Принятый ROOT набор: 8 cases

Новые `server/tests/test_meeting_hosts_query.py` содержат семь focused cases:
три literal goldens (нет/один/несколько marked hosts с приоритетом над
организатором), read-only SQL без commit/rollback/token issuance, caller rollback,
проброс execute error и actual ASGI `/api/work/calendar` → actual notice с
отсортированными именами и захваченной доставкой/ICS. Чужой event с отмеченным
ведущим присутствует как negative control; наблюдения выполняются свежими sessions.

Обязательный восьмой case без правки старого файла:
`tests/test_conf_app.py::test_ведущие_встречи_и_пять_минут`.
Никакие остальные conference/backend или ранее принятые 59/35/117 suites
в selection не входят. Его jitsi_key fixture генерирует только синтетический
ключ; реальные ключи и account tokens не используются.

ROOT-only runner: `server/tests/meeting_hosts_query_approved.py`, аргумент
`--execute-approved-meeting-hosts-tests`. До любых pytest/app/ORM imports он
проверяет полный app/tests/schema hash+count, requirements/pytest.ini hashes,
собственный SHA из отдельного approval, allowlisted synthetic env с сохранённым
HOME, matching DATABASE_URL/TEST_DATABASE_URL, числовой loopback/approved port,
точную БД `api_meeting_hosts_test_20261030` и три разные owned/private/empty dirs.
Runner не резервирует БД и не меняет роли, quota или GUC.

После gate сетевой audit допускает только согласованный PostgreSQL socket.
Pytest plugin перед test setup заглушает и захватывает meeting email, chat,
SMTP, notify/dispatch, chat mail, Web Push и WS delivery; это действует и на
старый выбранный тест. Интеграционный case использует ASGITransport без сети,
подменяя только auth principal/session injection; реальные route/model/query/
membership/product checks и notice formatting остаются. Тест не подменяет
meeting_hosts и не вычисляет ожидаемый список имён production helper-ом.

| Frozen источник | SHA-256 |
|---|---|
| app, 492 файла | `716fa867894646a1977ea89c970503d319c9205c0b0459e73682a7722534a5fe` |
| tests без самого runner, 338 файлов | `40c99db8e6f3b22b489d277c4514e9af8baf8988322932160375d63ec522b64b` |
| schema_migrations, 16 файлов | `51e2a65737f599b7a2b2ceabfeb0b6e054046e64bbce8765ecb1e333b451e79d` |
| runner | `3a52fc2b89b646fcf467847fb23ad712a1565ab1be2208205215968251c5012b` |

## Фактическая проверка и границы результата

ROOT выполнил только frozen selection на отдельной
`api_meeting_hosts_test_20261030`: **8 passed in 16.46s**, runner exit 0,
внешнее время процесса 28.521037242375314s, child reaped. Проверены семь новых
cases и обязательный прежний тест ведущих/пяти минут. XML содержит ровно восемь
cases без failure/error/skip; worker проверил это чтением XML, не запуском тестов.

Boundary evidence: `external_delivery_stubbed=true`,
`network_attempts_blocked=0`; invitation case захватил **3 письма и 3 чат-сообщения**.
Здесь ноль blocked attempts означает, что попыток запрещённой сети не было;
само наличие stubs подтверждается отдельным boundary receipt.

ROOT сообщил штатный DROP disposable БД: fresh non-system relations 0,
connections 0, exists after DROP 0; maxLocks остался 64. Это подтверждение ROOT,
worker SQL/драйверы/gate/pytest не запускал. Сообщение приёмки:
`msg_9b4ffb0ef97d`, Dispatch `ctx_53ed903bb0bf`, 30.10.2026.

Evidence находится в ROOT integration worktree, под
`.artifacts/root-meeting-hosts-review-20261030/`:

| Artifact | SHA-256 |
|---|---|
| test-process.json | `3ff52dafdbb97fc03a56acd99ca56ed6c33820e0d930b4c5ff1b03e174bfc6a8` |
| evidence-test/meeting-hosts.xml | `d87a58792ff326aad7998f89f2fa8a4f7f1c91be98a4224b9c3956621470e082` |
| evidence-test/meeting-hosts-boundary.json | `19797906aba18ebe69047698285913f56fe4fb5f2cef0e748e5e0a8b4c8e2131` |

Пути и hashes также записаны в приватный
`.artifacts/meeting-hosts-query/root-evidence-references.json` рабочего дерева
worker. После actual evidence изменён только этот отчёт; runtime, test и runner
сохраняют frozen bytes и hashes таблицы выше. Это focused приёмка P1, не полный
conference/backend suite, не проверка live Jitsi/почты и не завершение всей M04.
