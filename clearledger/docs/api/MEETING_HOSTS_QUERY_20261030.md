# M04/P1: общий запрос ведущих встречи

**Статус: NOT RUN.** Runtime-патч и frozen tests/runner подготовлены; выполнение
pytest, SQL, импорт приложения и приёмка принадлежат ROOT. Полный M04 не закрыт,
выпуска, активации функций и изменения рабочих данных нет.

База: `05e462d99009580bd529e3096740fdc077e83dd2`, собственная ветка
`agent/api-meeting-hosts-query-20261030`. Историческая карта на d70581b4 не меняется.
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

Новый source-only inventory на frozen prepared commit должен показать
**492 файла / 482 AST / 19 sites / 28 bindings**, удалена ровно историческая E19.
Точные pin, hashes, результат сравнения остальных refs и пути inventory
фиксируются в приватной proposal после freeze, независимо от прежней карты.

## Точный набор для ROOT: 8 cases

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

ROOT резервирует disposable DB и даёт отдельный approval port/self-SHA, затем
исполняет только frozen selection из пустого cwd без .env. Evidence ожидается
в приватном evidence dir: `meeting-hosts.xml`, `meeting-hosts-boundary.json`,
лог и подтверждение cleanup БД/временных данных. После фактического результата
и cleanup обновляется только этот отчёт; до него статус остаётся **NOT RUN**.
