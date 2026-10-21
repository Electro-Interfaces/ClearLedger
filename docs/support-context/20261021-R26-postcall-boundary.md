# R26: ожидание postcall на границе live deadline

Core возвращает первоначальный `postcall_pending` и тогда, когда Node всё ещё
подтверждает matching wrapup без explicit revoke, но его live phaseDeadline уже
прошёл или active=false. Проверка Core/Support ACL, назначения заявки и MFA
обязательна; ответ HTTP409 не выдаёт права, данных или действий. Context TTL,
закреплённый hard postcall deadline и окончательные отказы сохраняются.

Runtime: `59beaac9811abd1897d016310d8295c320313063`, ветка
`MagLook/support-context-core-20261020`, PR18. Вход: clean
`455faec088251180f88499b80ed746fc79d89879`, runtime
`c29bc8ba4ab9a90bfb6e8149237c34b67c3ce442`.
После целевой проверки runtime сразу закоммичен, pushed и передан Root/V20
(`msg_34c4bf1c028b`, `msg_7e4822423135`). R25 уже завершился: CLI отклонил отправку
в settled Dispatch; сведения для handoff R25 доставлены owning Run сообщением
`msg_1f356c4ece8b`. Новых агентов/Dispatch/worktree не создавалось.

## Основание и норматив

Первичное genuine evidence остаётся actual V20 `natural-A.json` на
Node47b/Support10cdb/Core133/CCea15/Edge675: fractional live deadline `.734`,
Node ended `.742`, преждевременные postcall403 до ended. Его источник и SHA256
закреплены в [отчёте R24](20261021-R24-postcall-pending.md).
R24 принят в проверенном объёме live-wrapup/zeroPolicy (53+52+3).

R26 отдельно проверяет оставшийся edge: live deadline пересекается во время
ACL HTTP либо Node ещё возвращает unrevoked wrapup после этого deadline.
Это компонентное Core воспроизведение, а не новый результат actual4app/V20.

Root дополнил [postcall-transition-v1.md](postcall-transition-v1.md): истечение
live deadline и active=false без explicit revoke не означают hard postcall revoke.
Уточнённый sidecar скопирован без изменений, SHA256
`3db9e9229418a124df476ab28f574a16ed37e692b83fd7083748301fc45e3e3c`.
Исходный C02 [contract-v1.md](contract-v1.md), SHA256
`df916e2194429268b06be2ab2b1c03eb32e0d81503df8ce3043d5eb9c73eba12`,
body/JWT/scope, exp rounding и hard deadlines не менялись.

## Воспроизведение до изменения runtime

На неизменном c29/clean455 запущены новые настоящие Core TCP HTTP/PG/RS256/DPoP
проверки с ограниченными Node/Support HTTP protocol peers. Получено **3 failed**:

- Node status возвращает matching active wrapup с будущим phaseDeadline;
  actor-resolve начинает ответ до deadline и завершает после него, права,
  binding и назначение не меняются: Core403 `wrapup_expired` вместо pending.
- Node возвращает matching wrapup/unrevoked с валидным прошлым live deadline,
  active=true: Core403 `wrapup_expired`.
- Та же проекция с active=false: Core403 `assignment_revoked`.

Барьер первого случая брал root grant `FOR UPDATE NOWAIT` из другой PG-сессии
во время actor HTTP. Захват прошёл: Core не держал row lock на HTTP. Проверки
также подтвердили неизменность source claims/authority/expires_at/revoked_at и
числа grants даже при дефектном отказе. Часы, JWT и SQL phase не подменялись.

Прямые доказательства: [red-boundary.tap](evidence/R26/red-boundary.tap),
[HTTP timing](evidence/R26/red-boundary-actor-deadline-crossing.json),
[active=true](evidence/R26/red-boundary-expired-live-true.json),
[active=false](evidence/R26/red-boundary-expired-live-false.json).

## Исправление и сохранённые ограничения

Только initial issue может пройти ветку ожидания. `check_postcall_node` сначала
проверяет phase/identity/revoke и отсутствие уже закреплённого postcall права.
Он больше не вызывает live `check_node`, требующий active и будущего deadline.
Вместо этого проверяются MFA и валидный aware ISO timestamp live phaseDeadline;
отсутствующий/null, malformed, naive и числовой deadline дают отдельный
`503 node_invalid`, без pending и без обращения к Support actor-resolve.
Настоящий bool active и весь Node envelope по-прежнему валидируются моделью.

Для ожидания hard postcall deadline ещё не известен и не вычисляется из live
phaseDeadline. После свежего Support actor-resolve и повторного чтения root/Core
ACL pending проверяет Context TTL; само пересечение live deadline на HTTP
больше не вызывает false `wrapup_expired`. Source не изменяется; DPoP replay
уже durably сохранён, следующий запрос требует нового proof.

Нулевая policy, explicit revoke, изменённые call/context/act/connection/assignment/
admission/jkt, binding/permissions/actor, Core сеанс/роль/модуль/object scope,
unassigned/wrong ticket и отсутствие ticket capabilities остаются окончательными
отказами, включая expired/inactive live projection. Истёкший Context TTL,
установленный или истёкший hard deadline не маскируются ожиданием.

Existing ticket_postcall и rollback Node ended→wrapup остаются strict403.
Перед любым 200 по-прежнему обязательны ended/endedAt и current ACL; ticket-only
read/append, JWT max120s, fixed endedAt+policy/context deadline сохраняются.
Live `check_node`, admit/renew/current не ослаблены: expired/inactive live grant
не становится действующим. Таймеров, sleep, ceiling exp или новых прав runtime
не добавляет.

## Проверки и ресурсы

| Проверка | Результат | Evidence |
|---|---|---|
| Новые boundary сценарии до правки | 3 failed, 151 deselected | red-boundary.tap |
| Scoped postcall после правки | 61 passed, 97 deselected | [green-postcall.tap](evidence/R26/green-postcall.tap) |
| Context TTL пересекается во время actor HTTP | 1 passed, 158 deselected | [green-context-ttl.tap](evidence/R26/green-context-ttl.tap) |
| Live/renew/current Core ACL/phase regression на immutable runtime | 50 passed, 109 deselected | [green-live-regression.tap](evidence/R26/green-live-regression.tap) |

Green HTTP barrier снова доказывает `NOWAIT` без lock на HTTP и требует
409 `postcall_pending/retryable=true` без token/actions/data, source mutation,
нового grant и postcallDeadline; тот же proof повторно получает replay401.
[Timing и отсутствие записей](evidence/R26/green-postcall-actor-deadline-crossing.json).

Expired wrapup с active=true/false получает pending; старый live token не
открывает dossier. После отдельного authoritative ended новый proof получает
только одну назначенную заявку/read+append и стандартный fixed hard deadline:
[active=true](evidence/R26/green-postcall-expired-live-true.json),
[active=false](evidence/R26/green-postcall-expired-live-false.json).
Это переход состояний тестового HTTP peer, не настоящий Node timer.

[Context TTL barrier](evidence/R26/green-context-ttl-context-ttl-crossing.json)
подтверждает отдельный окончательный 403 context_expired при истечении Context
TTL во время HTTP с неизменными source и числом grants. Негативная матрица R24
теперь проверяет настоящие запреты на expired/inactive live projection; прежние
inactive/live-expiry случаи перенесены в positive pending сценарии по новому
нормативу. Malformed deadline проверяется отдельной protocol матрицей.

Только собственные PostgreSQL16 контейнеры `core-support-context-r26-*`, tmpfs,
случайные порты `127.0.0.1`, БД `core_support_context_r26`; Core Uvicorn и peers
используют loopback. [Runner](evidence/R26/run-tests.py) удаляет свой контейнер в
finally, HTTP listeners закрываются фикстурами. Все resource receipts содержат
cleanup:true, base commit и SHA256 проверенного runtime service; зелёные прогоны
до commit проверяли те же runtime bytes, что immutable 59beaac9.
Результаты, hashes и cleanup закреплены в [manifest](evidence/R26/manifest.json).

Повтор из корня checkout:

```sh
python3 docs/support-context/evidence/R26/run-tests.py replay-postcall tests/test_support_context_v1.py -k postcall
python3 docs/support-context/evidence/R26/run-tests.py replay-live tests/test_support_context_v1.py -k 'renew or current_core or restricted_core or live_assignment or phase_limits'
```

`git diff --check` и компиляция изменённых Python прошли. Полный CI без причины
не повторялся. Собственные PG/HTTP ресурсы убраны; чужие/shared ресурсы,
рабочие DSN, секреты, prod/SSH/ВАТС/почта не использовались.

Изменены Core service, focused tests, sidecar/docs/evidence; protocol helper
не потребовал новой правки. Support UI/Node/CC/Edge/harness не изменялись.
Actual natural V20 с настоящими Node timer, Support ACL/business transaction и
браузерным iframe/key/draft остаётся отдельным доказательством его владельца.
PR18 body обновлён по Task-авторизации; base/draft status не менялись,
комментарии/merge/deploy не выполнялись.
