# UserInfo: Bearer challenge, 30.10.2026

База: `a6667d59`. Ветка: `agent/api-userinfo-protocol-20261030`, отдельное рабочее
дерево `api-userinfo-protocol-20261030`. Согласование header-only seam получено от
координатора до правки продукта. Код не выпущен; интеграцией и ревью занимается
координатор. Это исправление протокольной совместимости, не заявление об уязвимости
или полном соответствии OAuth/OIDC.

## Основание и сохранённый контракт

[OIDC Core §5.3.3](https://openid.net/specs/openid-connect-core-1_0.html#UserInfoError)
отсылает ошибки UserInfo к
[RFC 6750 §3](https://www.rfc-editor.org/rfc/rfc6750#section-3).
При отсутствии подходящих credentials/token RFC требует `WWW-Authenticate`,
схему Bearer и хотя бы один auth-param. `realm` допускается (MAY), а не требуется
сам по себе: фиксированный `realm="partner-api"` выбран локальным профилем задачи.
Для ошибки аутентификации с токеном `error` рекомендуется (SHOULD);
`error_description`, `error_uri` и подсказка `scope` необязательны (MAY).
Отсутствие credentials или неподдерживаемая схема по рекомендации не получают
`error`. Из общего 401/403 нельзя достоверно установить точную причину или scope.

Тела, статусы и решения допуска сохранены. UserInfo остаётся GET-маршрутом с
текущей JSON-сериализацией и pairwise subject. `protocol_error`, token/revoke,
Basic client authentication, JWT issuance/claims/проверки, grants, scopes,
ACL, expiry и настройки не менялись. `product_api`, app wiring, docs portal,
типы и модели не изменены. Базы рабочих пространств, ВМ и интеграции не затронуты.

## Изменённые пути

`services/partner_identity.py`:

- `partner_bearer_headers`: общий header helper с фиксированным realm.
- `get_verified_partner_token`: missing/unsupported credentials сохраняют
  `401 {"detail":"Partner bearer required"}`, получают generic Bearer challenge.
- `verify_partner_access_token`: oversized (>8192) сохраняет прежний 401/body и
  получает generic challenge до verifier; HTTPException/PartnerProblem 401/403
  дополняются на общей Bearer boundary. Существующий явный `invalid_token`
  канонического `verify_access` сохраняется и получает realm. Другие generic
  отказы не превращаются в `invalid_token` или `insufficient_scope`.
- `PartnerProblem` допускает optional headers; `problem_handler` переносит только
  явно заданный `WWW-Authenticate`. Cookies, Location, debug и попытка
  переопределить `NO_STORE` через эти headers не проходят. Неотмеченные
  PartnerProblem на других маршрутах остаются без Bearer challenge.

`routers/partner_oauth_router.py`: только явный UserInfo machine/noopenid отказ
возвращает прежние 403 и `{"error":"insufficient_scope"}` с challenge
`Bearer realm="partner-api", error="insufficient_scope"`. Подсказки `scope` нет:
machine-отказ одним добавлением openid не устраняется.

`verify_access`, `live_grant`, `user_info`, token issuance и Authlib client
authentication оставлены без изменений. Распознавание ошибок не зависит от URL,
маршрута, `detail` или текста generic отказа. Нормализация точного error работает
с текущим доверенным canonical challenge, не является общим парсером произвольных
`WWW-Authenticate` от стороннего verifier.

Уточнение source finding: в базе `a6667d59` канонический `verify_access` выдаёт
HTTPException 401 с явным `invalid_token`, а не PartnerProblem 401. Его
`require_enabled` способен выдать PartnerProblem 503, который не обогащается.
PartnerProblem 401/403 проверены контролируемым seam как общий контракт этой
Bearer boundary; наличие таких реальных ветвей текущего verifier не заявляется.

## Проверки

| Статус | Проверка | Результат |
|---|---|---|
| FAIL, ожидаемый baseline | Последние 14 pure ASGI тестов поверх исходных двух файлов `a6667d59` | 20 проваленных assertions заголовков, 0 errors; статусы/тела/positive/subject-only/8192 PASS |
| PASS | Те же pure ASGI тесты на кандидате | 14/14 |
| PASS | Offline regressions вместе с product HTTP/OpenAPI/service/budget/monitoring | 70/70, включая 14 UserInfo |
| PASS | Настоящие JWT/PostgreSQL, Code+PKCE, UserInfo и регрессии identity | 32 passed, 35 deselected, 44.34 s, pytest EXIT 0 |
| PASS | Очистка own DB и освобождение SQL-окна | 0 таблиц public/edge, 0 других сессий; own DB удалена, проверено отсутствие; все соединения закрыты, child reaped, runner EXIT 0 |
| PASS | `git diff --check` | Нет ошибок whitespace |
| SKIP | Полный CI, браузер, production/внешний OAuth клиент | Вне данной проверки |

Pure ASGI запускается через `unittest`, без `tests/conftest.py`. Используются
настоящий router, dependency, async wrapper и сериализатор; sync verifier и
pairwise lookup подменены контролируемыми фикстурами. Попытки SQL/connect
запрещены mock-барьерами. Проверяется arbitrary mount `/unrelated-prefix` и
отдельный `/unrelated-resource` с общей dependency, а не распознавание UserInfo
по строке пути. Отдельно проверены 8192/8193, generic HTTP/PartnerProblem 401/403,
неизменные 503 и Basic helper, lowercase metadata, отсутствие повторных cache
headers и whitelist PartnerProblem. Это не доказывает JWT/persistence policy.

Actual suite использует native auth, новые синтетические данные и RSA ключи:
публичный `authMethod=none` и confidential Basic, full UserInfo, только sub,
noopenid, machine; missing/unsupported/oversized/invalid, revoked family,
истёкшие JWT/row/family. Сопоставляется sub access/ID token/UserInfo; проверяются
прежние тела 401/403, no-store и точные challenges. Дополнительно выбраны
existing actual-state revocation, token confusion, discovery, machine grant и
Basic transport regressions. HTTP public/none здесь обозначает тип клиента,
а не public subject type: идентификаторы по-прежнему pairwise.

До выделенного SQL-окна SQL/connect/CREATE не выполнялись. Common safety guard
проверен до подключения, импорта pytest/conftest и DDL. Разрешена только новая
`api_userinfo_protocol_test`, локальный PostgreSQL `127.0.0.1:33546`, отдельный
тестовый upload dir. Guard требует `RUN_PARTNER_IDENTITY_TESTS=1` и явные
`TEST_DATABASE_URL`/`UPLOAD_DIR`; runner дополнительно требует
`RUN_USERINFO_PROTOCOL_TESTS=1` и точное совпадение выделенного адреса/имени БД.

## Воспроизведение и артефакты

Из корня собственного дерева, Python окружения проекта:

```sh
PYTHONPATH=clearledger/server /srv/projects/api-modernization-test-env-20261029/.venv/bin/python -m unittest tests.test_partner_userinfo_wire -v
```

Локальные артефакты в `.artifacts/` того же дерева:

- `run_userinfo_wire_baseline.py`: временная копия app, два исходных файла через
  `git show a6667d59`, последняя версия теста; основной checkout не меняется.
- `userinfo-wire-baseline.log`: исходный FAIL, тот же финальный тестовый код.
- `userinfo-wire-current.log`: PASS 14/14 на кандидате.
- `userinfo-offline-regressions.log`: PASS 70/70.
- `run_userinfo_db.py`, `userinfo-db-focused.log`: guard, own DB, native JWT suite,
  выход дочернего pytest, очистка и закрытие соединений.

Runner БД нельзя повторять без нового эксклюзивного SQL-окна координатора;
его URL передаётся окружением и в отчёте не сохраняется. Локальные логи и runner
не входят в Git. Это локальная проверка указанного состава, не результат полного
CI, внешнего клиента или установленного пространства.


Независимая проверка координатора общего кандидата9c33d932:
70offline ASGI/schema/regression cases PASS8.140с; полный identity+docs
PostgreSQL/HTTP набор89PASS117.79с, без SKIP/DESELECTED. Это расширяет
авторские32focused/35deselected, но не является полным CI/OIDC conformance
или проверкой production proxy/TLS. Правила доступа и bodies/status сохранены.
