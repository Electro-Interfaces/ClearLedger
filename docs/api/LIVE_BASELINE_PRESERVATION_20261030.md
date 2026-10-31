# M00: сохранение live backend от 30.10.2026

Статус: scoped backend preservation принят ROOT: 55 retained PASS + 8 corrective PASS.
Это split-приёмка, не единый зелёный прогон 63 случаев и не закрытие всего M00.
Этот пакет не закрывает весь M00 и не подтверждает выпуск. Стенд, реальные данные,
SSH, SQL, Docker, зависимости, версии и файлы миграций исполнитель не менял.

## Основания и происхождение

Опорный кандидат: `bdbd8ccb3798316cd4b6794bdc99ecf10af4101a`.
Первоначальная база: `5ce5779b`. ROOT read-only наблюдение:
`2026-10-30T20:44:47.128815+00:00`, `rushydro` на `elsy-eco-01`.
Backend `elsyplus/ledger-backend:v1685`, Python `3.13.15`, образ
`sha256:8c71cd88a4163e19261701cfef640857eb8437fa4a97c1901cc1c80be3b0b3bf`.
Frontend `elsyplus/ledger-frontend-rushydro:v844`, публичная версия `1.2.858`;
Support `elsyplus/tsupport-eco:eco-20261026-2`.

Исходные evidence принадлежат ROOT и оставлены без изменений:
`/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/full-api-continuation-20261030/`:
`rushydro-runtime-source-snapshot.json`, `rushydro-candidate-drift.json`,
`runtime-original-baseline-parity.json`, `live-vs-initial-source.diff`,
`runtime-source-review/` (семь файлов). Снимок SHA-256:
`9ad3db0cc5a8e8287dd6838f378ee49a16d924e2c3632daee258d72272bdab6e`.
Из 454 live Python-файлов 447 побайтово совпадают с `5ce5779b`;
семь отличий являются разрывом preservation, а не автоматическим дефектом live.

После `git fetch origin` найдены исходные коммиты:

- `722adb0d1bb3589e381483dbed2038dcc974d9db`: шесть файлов СМР и корпоративных сессий.
- `e44ea4d66e29b2897c17c10563d0ac2c17317ed0`: календарное письмо действующему участнику.

Оба доступны через `origin/fix/rushydro-corporate-smr-20261030`;
второй также локально виден через историю линии calendar fix.
Для каждого из семи файлов bytes из соответствующего коммита **полностью совпали**
с bytes snapshot и его SHA. Backend source provenance этих семи отличий подтверждён.
Это не доказывает, что полный коммит или вся история этой ветки были выпущены:
проверен конкретный исходник, а не происхождение build image целиком.
Узко применены backend hunks и три исходных тестовых файла из этих коммитов;
версии, lock-файл и frontend hunks не переносились.

## Состав и сохранённые правила

| Файл относительно server/app | Сохранённое поведение |
|---|---|
| database.py | Два существующих live bootstrap ALTER для ezs_sites; namespace/schema/quota guards кандидата сохранены |
| models.py | Nullable JSONB dismantle_location_ids и String(10) decommissioned_on; прочие колонки и decimal contracts не менялись |
| routers/sites_router.py | ValueError update_site становится HTTP 422 до commit; общий file_store кандидата сохранён |
| services/ezs_site_work.py | Весь payload проверяется до мутаций; доступны лишь ev_charging своей компании и object scope; дедупликация, clears, audit display, output |
| services/ezs_changes.py | Live label/category обоих полей |
| services/charge_sessions_normalize.py | Name+phone одной компании, лишь отсутствующий тип, опциональный channel; ADMIN остаётся ezs_admin; суммы/тарифы не пересчитываются классификатором; shared counterparty/contract commands сохранены |
| services/meeting_notice.py | Actor включён в email по настройкам и фильтрам, исключён только из self-chat; accepted owner jitsi.meeting_hosts сохранён |

Новые ALTER сохранены как существующее deployed behavior без выполнения на БД.
Точки audit/flush/commit, lifecycle sync и отправки сообщений остались прежними.
Число писем меняется именно как в live; учётчик chatted не включает actor.

| Файл | Live SHA-256 | Candidate SHA-256 |
|---|---|---|
| `database.py` | `bc1c712246d1dd0497a99bb6a7ce33f593580a8c7d02b291ebf8d043ed5886e3` | `b798aabb778072c868d9d9edfac7884776e2aa01c793dcbac3a651754027cd02` |
| `models.py` | `6aef22c515d013e282e02f39bde3431d94d45fb25077d056144250b606b509a1` | `6aef22c515d013e282e02f39bde3431d94d45fb25077d056144250b606b509a1` |
| `routers/sites_router.py` | `2e907dee625169600f8e3fba7a8e593c6b950f54318f11c9bdca08bca8282b59` | `564a384e22610fe4fefd5ed08d7b87f1dbe5815eb8b703f35f840322a60f96bf` |
| `services/charge_sessions_normalize.py` | `2369896a9dbe3363e7b789d6532ae4389bed9eb68e4f2b5ac1c673b49a09707a` | `6951409b98dcc572478e2051d7975f8e8fc622b600a56ebd0dd2c6623d174fc3` |
| `services/ezs_changes.py` | `1636290a9e3dc5b70483e5a940b720332cb3d0e2dc63a341ed851433925bcb44` | `1636290a9e3dc5b70483e5a940b720332cb3d0e2dc63a341ed851433925bcb44` |
| `services/ezs_site_work.py` | `734fb3ac87df90f6f6fc8574d2a64b09647457ad633b30a3abea96744ffa9d79` | `734fb3ac87df90f6f6fc8574d2a64b09647457ad633b30a3abea96744ffa9d79` |
| `services/meeting_notice.py` | `f5055aa8423bdf1b996bdc54c784bbb6edfc1abf5252d5598e5bddb07feb57d7` | `9d68faf4ab412c5c108520575e400100d9f3925f4a8183329d8bcc81c087be94` |

## Характеризация и приёмка

Исходные assertions из upstream сохранены без изменений:
`test_project_dismantle_passport.py` (9), `test_corporate_session_identity.py` (2),
`test_calendar_actor_mail.py` (11).
Новый `test_live_baseline_preservation.py` (28) выполняет одинаковые literal golden
controls для SHA-проверенных live function AST и candidate: invalid-date atomicity,
hidden/foreign/wrong-type station IDs, nullable clears и структурированный audit,
сохранение статуса оборудования, tenant/name/phone/channel/explicit-type/ADMIN,
actor mail preference против self-chat, fallback и несколько ведущих.
Live module imports/startup/DDL не исполняются: выбраны только функции, а ORM и
общие владельцы остаются кандидатными. Это ограниченный контроль live функций
на candidate dependencies, а не независимый прогон всего live image.

Также выбраны 5 прежних `test_project_changes.py` и
`test_conf_app.py::test_ведущие_встречи_и_пять_минут`: и 7 прежних `test_meeting_hosts_query.py`: всего ожидаются 63 случая.
ROOT разрешил точечную актуализацию
`test_meeting_hosts_query.py::test_asgi_invitation_uses_sorted_hosts_and_captured_delivery`
сообщением `msg_d682a23ac81c`: old mails3/chats3 без organizer → new mails4/chats3
с organizer в mail recipients, на основании authoritative live `e44ea4d6`.
Все остальные assertions/order/ACL/chat recipients сохранены; прежние receipts не менялись.
Независимый live/candidate golden дополнительно проверяет новое ожидание.
Это явное изменение проверяемого поведения из live, не ослабление проверки ради PASS.

Исполнитель выполнил только AST/read/compile/Git: PASS для 7 runtime и 5 новых test/runner
файлов, `git diff --check`: PASS. Pytest, collection, app imports и SQL не запускались.
Локальные evidence: `.artifacts/live-baseline-preservation-20261030/provenance.json`,
`source-review.json`, `acceptance-proposal.json`. Старые proofs не изменялись.

ROOT runner v3: `clearledger/server/tests/live_preservation_approved.py`, SHA-256
`c2986ddc4addd11354f7b7fd35f9293db3ef9ce09708fccbcaae61b2d499adbb`.
Он сверяет полный app/tests/schema source, конфиг pytest и requirements, семь live
SHA, clean allowlist env, Python 3.13.7 с -I -S -B, exact candidate77 inventory, exact disposable DB, private empty cwd/upload/evidence/scratch
до первого импорта pytest/app. Строгая network/process/env boundary взята source-only из принятых R1/main:
R1 SHA `4f48de90e1a5b69bb03a98c4a6b7d5dfe7d35670d8740e22fb810a4e81bc1a82`,
main SHA `4ea9370970cbe79182efca907791c01ad2ea47f63b8137f3ce2003644baf24cd`.
Metadata policy и 16 controls скопированы без исполнения старых runner.
Five-import IPv6 suppression восстанавливает флаг; bind/listen, внешняя сеть,
subprocess и чтение .env/secret paths запрещены. Sendmsg допускает лишь buffers
при owned IPv4/TCP PG socket с прежним fd и exact peer.
Сеть ограничена только назначенным loopback PostgreSQL;
SMTP/прочие senders перехвачены до initial conftest; synthetic cached config подменён до router imports,
original MIME tests возвращают реальный high-level meeting sender только под своим SMTP capture.
SEED_SUPERADMIN_EMAIL/PASSWORD и ECOSYSTEM_COMPANIES заданы явно;
--log-file в evidence, --basetemp в private scratch, --capture=sys.
Предложение запуска и лимиты находятся в локальном acceptance-proposal.json;
actual synthetic acceptance и назначение БД выполняет только ROOT.
Для совместимости существующего gate hosts-тестов путь БД строго
`/api_meeting_hosts_test_20261030`, но disposable ресурс и порт ROOT назначает отдельно.
ROOT подтвердил новый ресурс с этим именем в msg_fde9752782d0.
Proposal v3 заменяет v1 (c16df8ea) и v2 (42d16985); они не исполнялись.
CPU600/AS3GiB/FD256/FSIZE2MiB/wall650/scratch128MiB — согласованные ROOT лимиты.

## Ограничения

Frontend 1.2.858 зафиксирован ROOT, но src/bundle mapping, наличие frontend hunks
722adb0d и весь frontend source preservation этим пакетом не подтверждены.
Source-only сверка consumers уточнила пробел кандидата bdbd8ccb:
`src/components/sites/ProjectDismantleStations.tsx` отсутствует,
`ProjectTabs.tsx` и `services/sitesService.ts` не содержат новых полей
`dismantleLocationIds`/`decommissionedOn` из 722adb0d.
Это подтверждённый пробел source consumers относительно upstream; наличие этих
frontend hunks в live 1.2.858 по одному номеру версии не доказано.
Frontend-файлы не входят в владение исполнителя и не переносились.
Их будущий перенос также требует узкого review: sitesService кандидата содержит
другие принятые изменения, поэтому заменять файл upstream-копией нельзя.
Не проверены browser UX, реальные внешние календари/SMTP/Jitsi, production startup,
восстановление БД, изменение схемы на рабочих данных, полный API suite и выпуск.
Runtime build provenance вне семи SHA-совпавших файлов остаётся неподтверждённым.

## ROOT receipts и affected8

ROOT source review PASS: private Git index с семью candidate blobs поверх bdbd8ccb,
reverse точного diff(initial5ce→live7snapshot) восстановил весь base tree
`6a8127ebfb615df33c8d2f95f55ec569086270c3` без отличий. Рабочие файлы и index
исполнителя не менялись. Evidence ROOT:
`.artifacts/root-live-baseline-review-20261030/source-review.json`.

V3 actual63 attempt2: **55 PASS / 8 FAIL**, pytest 23.08 с, outer 41.0859823776409 с,
exit 1/reaped. Forbidden=0; source/inventory PASS; 16 metadata controls PASS.
Normal DROP: 0 relations / 0 clients / exists=0, max_locks_per_transaction=64.
Evidence ROOT:
`.artifacts/root-live-baseline-review-20261030/actual63-attempt2/`.
Первый V3 outer attempt ROOT отклонён pre-import из-за неверного opt-in flag (0 cases);
runner/source не менялись; attempt2 использовал правильный env.

Все 8 FAIL были только в новом `test_actor_email_chat_and_common_hosts`:
последний assertion ошибочно ожидал `@conf.elsyplus` для фикстуры
`https://meet.example.test/room`. Source `meeting_notice.uid_встречи`
проверяет literal regex `/ledger-[0-9a-f]+`; эта ссылка его не содержит, поэтому
правильный literal UID — `@trek`. `Settings.jitsi_domain` по умолчанию
`meet.dataworker.ru` не участвует в классификации UID; runtime/Settings не менялись.
Остальные mail/chat/host golden assertions прошли, прежние 11 MIME и 7 hosts PASS.
Исправлен только новый literal assertion с пояснением; oracle не вызывает
проверяемую функцию для вычисления expected.

Runner V4 сохраняет strict boundary V3 и выбирает только 8 ранее упавших variants;
55 прежних PASS не повторяются. SHA-256 V4:
`0a1b9e92a482b6a5eb40de81a1f759ec3a6efcb2dba32babe1f0eafa450fc7ed`.
Frozen source/argv/env/selection/limits:
`.artifacts/live-baseline-preservation-20261030/acceptance-proposal-v4.json`.
V3 source/golden bytes и все прежние FAIL proofs сохранены. App/runtime не менялись.
V4 affected8: **8/8 PASS**, pytest 15.52 с, outer 33.5573 с, exit 0/reaped.
ROOT независимо проверил JUnit: 8 cases, 0 errors/skips; forbidden=0;
source/inventory PASS. Normal DROP завершён: 0 relations / 0 clients / exists=0,
max_locks_per_transaction=64. Evidence ROOT:
`.artifacts/root-live-baseline-review-20261030/affected8/`.

Итог: **55 retained PASS + 8 corrective PASS**, не single63green.
Прежние 11 MIME и 7 meeting_hosts среди 55 успешных случаев сохранены;
55 PASS не повторялись. V1/V2 не запускались; V3 wrong-flags pre-import attempt
(0 cases) отделён от V3 actual63 с ошибочным новым UID golden. Исправлен только
новый expected literal @trek; runtime не менялся после source preservation.
Исполнитель не запускал pytest/collection/importapp/SQL; actual выполнен ROOT.
После V4 PASS изменён только этот отчёт.

Frontend preservation назначается ROOT следующим обязательным Dispatch;
этот backend-пакет не закрывает весь M00, полный API suite или выпуск.
