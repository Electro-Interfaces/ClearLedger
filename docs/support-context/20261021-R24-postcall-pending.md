# R24: первоначальный переход wrapup → postcall

Core различает допустимое ожидание Node `ended` и окончательный отзыв.
Первоначальный `/postcall` из проверенного действующего wrapup может вернуть
HTTP409 `error.code=postcall_pending`, `error.retryable=true`, без grant, данных,
действий, фиксации deadline и изменения источника. После подтверждённого
`ended/endedAt` новый DPoP proof позволяет выдать обычный ticket-only grant.

Ветка: `MagLook/support-context-core-20261020`, PR18.
Входной clean commit: `84fa48788dec63ce10f5d6c8a2a465b3b41f38e9`;
входной runtime: `133909486d997cc3b194944c703cc4d3631940e8`.
Первый проверенный runtime: `0c0ef45982a3e27d8f9c23398dcea82fde83e7d7`, pushed
и сразу передан координатору, R25 и V20 сообщениями `msg_e51308f273e3`,
`msg_719e0bef3a6f`, `msg_0acace91f837`.
Итоговый runtime с отказом при нулевой postcall-политике: `c29bc8ba4ab9a90bfb6e8149237c34b67c3ce442`, pushed и передан тем же владельцам сообщениями
`msg_9742aa9dc864`, `msg_0915286e2f4b`, `msg_da6778355c16`.

## Основание и неизменный контракт

Actual V20 на Node47b/Support10cdb/Core133/CCea15/Edge675 выявил естественный
разрыв: Node phaseDeadline `00:22:50.734`, JWT exp `00:22:50.000`, первые postcall
в `.459/.568` получили 403 до Node ended в `.742`. Позднее тот же назначенный
оператор получил настоящий ticket-only postcall200. Источник:
`/home/mag/orca/workspaces/contact-hub/contact-hub-q-20261018/support-context-v17-cc-preflight-20261021/docs/support-context/evidence/V20/natural-postcall-timer/natural-A.json`
(SHA256 `0e963c9f6a26198ecafcce58a8c207049ef2ddd39a552dfbe338b8abb4448cd9`),
рядом `failure.png`; сообщение `msg_bc06fb21f5e6`.

Согласованный Root sidecar скопирован без изменений:
[postcall-transition-v1.md](postcall-transition-v1.md), SHA256
`78c560e1c7ed96319576c33a9c4def4ee00f48347152846ab75296c04b1dee13`.
C02 [contract-v1.md](contract-v1.md), SHA256
`df916e2194429268b06be2ab2b1c03eb32e0d81503df8ce3043d5eb9c73eba12`,
body/JWT/scopes, округление exp вниз и hard deadlines не менялись.

## Реализация

`check_postcall_node` сначала проверяет неизменность call/context/connection/act,
assignmentVersion, admissionRef и jkt, отсутствие explicit revoke. Только
initial issue допускает промежуточный wrapup, через действующие проверки
active, MFA и будущего phaseDeadline. Нулевая `postcallMaxSec` сразу означает
окончательный 403, поскольку при ней postcall никогда не может быть действующим.

Перед pending Core запрашивает свежий Support actor-resolve как для будущего
postcall: ожидаемые binding/permissions versions, точный ticketRef, прежние
Core sub/bindingRef/supportUserRef, current membership/active, текущие
назначение, assigned_ticket/vendor mask и непустые ticket capabilities.
Посторонняя заявка и недостаточные права не скрываются pending.

После HTTP Core заново читает root grant и ACL. Появившийся за это время
postcallDeadline, revoke, смена сеанса/членства/доступа/объектного scope приводят
к окончательному отказу. Проверяется, что wrapup/context deadline ещё не истёк.
Row lock берётся после всех HTTP; на pending транзакция чтения завершается без
записи grant/deadline/revoke. DPoP replay сохранён до HTTP и переживает отказ;
клиент повторяет запрос с новым proof.

Existing ticket_postcall и обычный current/introspect остаются strict:
возврат Node из ended в wrapup даёт 403, включая повтор от исходного grantId
после первой выдачи. Выдача grant по-прежнему требует Node ended и корректного
endedAt; hard deadline закрепляется как endedAt + политика, ограничивается
context expiry и не продлевается повторными запросами. Просроченный live JWT
не открывает прежнее dossier и не получает дополнительного срока.

Изменены только `app/services/support_context.py`, минимальный error helper
`support_context_protocol.py`, целевые тесты и документация. Support UI, Node,
CC, Edge и harness не изменялись.

## Проверки

Все запуски используют собственный PostgreSQL16 в отдельном контейнере на
случайном `127.0.0.1` порту и собственной БД `core_support_context_r24`.
[test runner](evidence/R24/run-tests.py) создаёт контейнер и удаляет его в
`finally`; для каждого запуска сохранён `*-resources.json` с `cleanup:true`.
Core — настоящий Uvicorn TCP HTTP, Node/Support — ограниченные HTTP protocol
peers с проверкой настоящих RS256 service JWT; клиент использует ES256 DPoP.
Часы Core, JWT и SQL phase в положительной проверке не подменяются.
Коммиты, результаты, cleanup receipts и SHA256 артефактов закреплены в
[manifest.json](evidence/R24/manifest.json).

Повтор из корня checkout (каждая команда создаёт и удаляет свой PG):

```sh
python3 docs/support-context/evidence/R24/run-tests.py replay-postcall tests/test_support_context_v1.py -k postcall
python3 docs/support-context/evidence/R24/run-tests.py replay-renew-source tests/test_support_context_v1.py tests/test_support_context_source_v1.py -k 'renew or source or consult or restricted_core or current_core or revoke'
```

| Проверка | Результат | Evidence |
|---|---|---|
| До изменения runtime: новый initial wrapup сценарий | 1 failed: 403 postcall_revoked вместо 409 | [red-pending.tap](evidence/R24/red-pending.tap) |
| Полный целевой postcall набор на 0c0ef459 | 53 passed, 97 deselected | [green-postcall.tap](evidence/R24/green-postcall.tap) |
| Scoped renewal, consult, revoke, current Core ACL, object scope и source | 52 passed, 99 deselected | [green-renew-source.tap](evidence/R24/green-renew-source.tap) |
| Нулевая postcall-политика до дополнительного guard | 1 failed: ошибочный pending вместо окончательного 403 | [red-disabled-policy.tap](evidence/R24/red-disabled-policy.tap) |
| Итоговый policy guard, expired-live → pending → ended, existing rollback | 3 passed, 148 deselected | [green-policy-final.tap](evidence/R24/green-policy-final.tap) |

Положительный сценарий ждёт настоящее истечение floor JWT до дробного wrapup
deadline и требует 401 introspection старого токена, 409 pending без токена/
actions/данных, неизменные claims/authority/expiresAt/revoked_at и число grants.
Проверяет запрос точного ticketRef с ожидаемыми версиями, отказ повторного proof
и повторный 401 старого токена. После реального истечения deadline peer
подтверждает ended; новый proof даёт единственный ticket/read+append, max120s JWT,
стандартный hard deadline endedAt+3600s. Изменённый endedAt не продлевает право.

Негативная матрица покрывает explicit revoke, inactive, assignment/act/connection/
jkt/admission/call/context, MFA, неверную фазу, expired/missing wrapup deadline,
Support binding/identity/versions/membership/active, unassigned/wrong ticket/mask/
capabilities, Core session/membership/module/object scope, context expiry,
установленный/истёкший hard deadline и нулевую политику. Отдельный HTTP barrier
меняет grant/Core ACL или устанавливает deadline между исходной проверкой
и ответом HTTP: требуется 403 без выдачи нового grant. Барьер берёт root lock
`NOWAIT` из другой PG-сессии и доказывает отсутствие row lock во время HTTP.

После policy guard повторены затронутые ветки; ранее зелёный postcall набор
и scoped renewal/source относятся к 0c0ef459. Полный CI без причины не повторялся.
`git diff --check` и компиляция изменённых Python-файлов прошли.

## Границы результата

Это проверка Core с protocol peers. Она не подменяет актуальную Support ACL
транзакцию, реальный Node timer, браузерный iframe/key/draft и бизнес-эффекты всей
цепочки. R25 отвечает за UI-обработку pending; actual natural-timer V20 ведётся
отдельно на immutable кандидатах и не объявляется пройденным этим отчётом.
Полная A01–A18 также не объявляется пройденной.

Рабочие стеки, секреты и DSN, prod/SSH/ВАТС/почта не использовались; общий I11 PG
не использовался. Собственные контейнеры/БД удалены, loopback listeners закрыты
фикстурами. Ветка pushed; PR18 body обновлён без комментариев, смены base/draft,
merge или deploy.
