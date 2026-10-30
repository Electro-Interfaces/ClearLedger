# Проверка партнёрской авторизации M10/M11

30.10.2026. Выполнен один Standard Codex Security workflow по исходникам
`b55d99597ae0dbd3986e8cde0469f7e117d18177`.
Scan ID: `ffa86c91-1afc-4646-9193-471e16e62fc4`.
Host MCP принял финальный semantic draft и успешно выполнил
`complete_codex_security_scan`: статус `complete`, canonical report сформирован
и запечатан инструментом. Этот файл содержит только краткую сводку;
канонические модель, findings, coverage и report сохранены в managed scan storage.

Подтверждённых уязвимостей в проверенном составе не найдено. Это результат
статического анализа ограниченного набора, не сертификация и не приёмка API.

## Фактический состав

Каталога `app/identity` в этой ревизии нет. Основная реализация расположена
в `server/app/services/partner_identity.py`.
Полностью прочитаны и проверены десять файлов, 2020 строк; пути ниже
относительно `clearledger/server/app/`:

- `services/partner_identity.py`, `services/docs_portal.py`;
- `routers/partner_oauth_router.py`, `routers/partner_admin_router.py`,
  `routers/docs_portal_router.py`;
- `models_partner.py`, `models_docs_portal.py`, `schemas_partner.py`;
- `docs_portal_assets/portal-init.js`, `docs_portal_assets/oauth-callback.js`.

Launcher принимает только каталог, поэтому с согласования координатора
`clearledger/server/app` использован как общий directory envelope.
Покрытие этого каталога **partial**: host насчитал 488 файлов, остальные
модули не входили в запрошенный аудит. Шесть проверенных поверхностей
закрыты source-backed dispositions; оставшийся app envelope сохранён
отдельным deferred item `app-envelope-outside-requested-review`.

`product_api/access.py` прочитан как граница use-time admission.
Связанные участки `auth.py`, `services/sso.py`, `services/app_identity.py`,
`main.py`, `config.py`, продуктовых queries/monitoring, developer frontend,
документации и тестов использованы только для трассировки и контрпроверки.
Они не расширяют заявленное покрытие на весь API или приложение.

## Что прослежено

| Граница | Результат проверки исходников |
|---|---|
| Code/consent/PKCE | Явное Core-согласие, пересечение доступных scopes/компаний, S256, точный callback, блокировка и одноразовое потребление кода. |
| Refresh/revoke | Ротация сериализуется по family; повторное использование отзывает family; результат транзакции фиксируется до ответа. |
| Типы identity | Partner access проверяет тип, ключ, issuer/audience, назначение, сохранённый hash и subject/client; ID/Core/handoff не заменяют этот capability. Machine grant имеет отдельные ограничения. |
| Tenant и живые права | Проверяются актуальные client/App, installation/CompanyApp, grant/family/credential, пользователь, членство/роль и типизированные ресурсы. Product admission дополнительно применяет текущие ограничения пользователя и компании. |
| Docs session/raw/assets | Короткая cookie связана с token/family и verification profile; UI, оба schema JSON, callback и assets вызывают общий live guard. Мутации проверяют Origin/CSRF, имена assets ограничены allowlist. |
| Собственный browser glue | Проверены state/PKCE, одноразовый callback, generation/expiry, разделение Core/docs/business credentials, память токенов и разрешённые цели запросов. |

Подозрение на расширение пустого membership `object_scope` не подтвердилось
для прослеженного product пути: `product_api/access.py` пересекает его
с `selected([])`, а `product_api/queries.py` превращает EMPTY в запрещающее
условие. Другие потребители не объявляются проверенными этим выводом.
Во включённых основных файлах не обнаружены встроенные credentials
с подтверждёнными по исходникам полномочиями.

## Ограничения и оставшаяся проверка

Preflight вернул `ready` с предупреждениями о delegation: вложенные агенты
запрещены заданием. Использован документированный последовательный fallback;
независимого generic baseline и независимого architecture reviewer не было.

Анализ был offline и read-only. Тесты и collection не запускались; приложение
не импортировалось, БД, сеть, браузер, реальные настройки и ключи не читались.
Существующие тесты служили контекстом и не считаются выполненными проверками.
Конкурентные запросы и живой отзыв между workers требуют отдельной разрешённой
приёмки на изолированных синтетических данных. Proxy/log/key configuration
действующего выпуска этим анализом не подтверждена.

Внутренности Authlib/joserfc/PyJWT и vendor Swagger bundle не проходили
самостоятельный аудит; проверены собственные adapters и glue.
Legacy keyed partner approvals/bridge/sync и остальные app-модули,
schema migrations, runtime и инфраструктура остаются за границами результата.
Предыдущий аудит API contracts не использовался как доказательство identity.

Runtime, tests, requirements и config не менялись. OAuth/API/docs flags остаются
выключенными по исходным defaults; merge, enablement и deploy не выполнялись.
