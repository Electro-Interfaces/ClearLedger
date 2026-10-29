# Локальный sandbox партнёрских пилотов

Это purpose-built тестовый HTTPS-сервис для независимых пилотных клиентов M18.
Он использует реальные Core login/gate, M10 admin/OAuth/OIDC/consent, портал
документации и curated product child application с настоящими JWT и SQL-политиками.
`app.main`, production seed, фоновые jobs, nginx и SSO не запускаются.
Внешний партнёр, production acceptance и проверка внешней доставки сюда не входят.
Успешный запуск fixture сам по себе не означает успех пилотных клиентов.

Исходники владельца: `tools/partner-pilots/sandbox/`. Клиентские инструменты
`tools/partner-pilots/clients/` принадлежат другому исполнителю и не импортируют ORM.
Все команды ниже выполняются из `clearledger/`. Python берётся из согласованного
тестового venv; Node dependencies используются из актуального lockfile без изменения.

## Границы и разрешение SQL

Единственная разрешённая цель: PostgreSQL `127.0.0.1:33546`, роль `clearledger`,
вымышленный пароль `api_test_only`, отдельная БД `api_partner_pilots_test`.
Создание, наполнение и очистка требуют одновременно:

- `RUN_PARTNER_PILOT_SANDBOX=1`;
- явный `TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_partner_pilots_test`;
- явный `UPLOAD_DIR=/tmp/partner-pilot-sandbox-test-uploads`;
- отдельное сообщение root об эксклюзивном SQL-окне после завершения чужого окна;
- `PARTNER_SANDBOX_SQL_WINDOW` с идентификатором этого сообщения.

Флаг SQL-окна является утверждением оператора, а не автоматическим разрешением.
До сообщения root нельзя запускать `init` или `cleanup`. `init` откажется работать
с непустой БД или непустым upload-каталогом: скрытого reset/drop/reseed нет.
Первичная схема создаётся фактическим `app.database.create_all`, включая штатный
безопасный bootstrap `phone_to_e164`; модели и runtime не переписываются.

## Ресурсы и конфигурация

Все данные вымышлены: две компании energy; owner с реальным admin membership и
обычный employee с `equipment` и одним объектом; два разрешённых объекта,
один скрытый и чужой объект второй компании; два разрешённых контрагента и договора со
строго типизированными связями, а также настоящие скрытые и чужие записи для 404; оборудование и object-scoped ChargeSessions
с разными днями наблюдения (разрешённые 29/28 октября, скрытый 30 октября,
чужой 31 октября 2026), визиты пересчитываются штатным `recompute_visits`.
Разные дни позволяют обнаружить ошибочный глобальный watermark вместо
object-scoped наблюдения. Ожидаемые дни и SHA-256 synthetic файлов выдаются
клиенту в manifest вместе с ID.
Две private DocCard имеют версии и реальные SourceFile bytes: owner является
автором одной, employee второй, поэтому права owner допускают только первую.
Дополнительно созданы company-doc для второго разрешённого результата пагинации
и документ чужой компании для реального tenant denial. Employee не получает
document scopes через реальную серверную eligibility. Delegated subject этого
ограниченного пилота — owner-admin (`subjectKind=company-owner`), а не обычный
сотрудник с docs-role; проверки последнего здесь нет.

Внутри процесса окружение очищается до импортов Core, `.env` не читается,
секрет Core и RSA signing key генерируются на запуск. OAUTH/API/DOCS flags
включаются явно только в этом процессе. Сетевой guard запрещает DNS/connect
за пределы loopback. Email и доставка notify замещены заглушками, auth не
замещается; HTTP access logs и печать request/response bodies отключены.

`clearledger/.artifacts/partner-pilot-sandbox/` игнорируется Git; каталог 0700,
ключи и JSON 0600. В нём находятся:

| Файл | Получатель |
| --- | --- |
| `ca.pem` | root и независимый клиент: CA для каждого HTTPS-запроса |
| `callback.pem`, `callback.key` | независимый клиент: TLS leaf только callback listener |
| `issuer.pem`, `issuer.key`, `ca.key` | только server owner |
| `client-manifest.json` | независимый клиент: только его client credentials и разрешённые/запрещённые synthetic IDs |
| `owner-state.json` | только root/server owner: fake Core accounts, IDs управления, origin/PID/status |
| `owner-error.log`, `build-error.log` | только server owner: частная диагностика при ошибке |

Core password/token не попадает в client manifest. Owner state не передавать
клиентскому процессу. Все credentials выдаются через настоящий admin API после
реального login, raw client secret сохраняется только в private client manifest.

## Запуск и ранняя передача

```sh
python tools/partner-pilots/sandbox/server.py prepare
```

`prepare` не импортирует Core и не подключается к БД. После этого root передаёт
клиенту `ca.pem`, callback leaf/key и закрытый handoff-каталог. Клиент поднимает
реальный HTTPS listener с `bind(127.0.0.2, 0)` и сообщает точный redirect URI.
Нельзя регистрировать фиктивный callback без слушателя. Callback использует
отдельный loopback IP 127.0.0.2: host-only Core `cl_gate` cookie для issuer
127.0.0.1 не уходит клиенту даже при навигации браузера. Cookie/Authorization
не фильтруются тестовым перехватчиком для маскировки этой границы.

После отдельного SQL-разрешения, с указанными выше переменными:

```sh
python tools/partner-pilots/sandbox/server.py init
python tools/partner-pilots/sandbox/server.py serve --callback https://127.0.0.2:PORT/callback
```

Сервис сам удерживает сокет `127.0.0.1:0`, публикует точный origin в owner state,
создаёт клиентов через реальные admin HTTP API и печатает `API_READY` с путями
CA/client manifest. OIDC discovery доступен по `origin/.well-known/openid-configuration`.
Затем собираются актуальные main/public React с Vite API без release-version/PWA
emitters; `UI_READY` означает готовность реального consent UI.
Private assets проверяют обычный `cl_gate`/`gate_ok`, public `/p` работает при
истёкшем gate, source font-loader сохранён с системным fallback в hermetic browser.

Клиенты:

- `references`: confidential, objects/equipment/counterparties/contracts read;
- `monitoring`: confidential, objects/equipment read + monitoring read;
- `documents`: public delegated, `openid documents:read documents.files:download`;
- `portal`: отдельный issuer-owned public client, две фиксированные callback:
  `/developer/api/callback` и `/api/developer/docs/oauth2-redirect`; он не передаётся
  независимому клиенту и не подменяет `documents`.

Объекты и типизированные справочники задаются SET, оборудование references — ALL,
невыданные ресурсы — EMPTY. Все установки ограничены двумя разрешёнными объектами
своей компании; foreignCompany нигде не устанавливается. Оба private документа
входят в installation SET, чтобы различие allow/deny доказывала реальная doc ACL.

## Consent и отзыв

Клиент хранит state/verifier только у себя, создаёт authorize URL в private файле
и сообщает путь root через Orca. Owner выполняет отдельным браузером:

```sh
node tools/partner-pilots/sandbox/owner.mjs consent \
  --authorize-file /absolute/private/authorize.json \
  --callback-file /absolute/private/callback.json
```

Браузер вводит fake Core credentials из owner state, выбирает компанию и
разрешённые scopes в настоящем UI; callback обслуживается клиентским HTTPS
listener, callback URL сохраняется только в закрытом файле. Клиент сам выполняет
настоящий code exchange своим процессом. Owner Chromium ограничен двумя SPKI pins конкретных fixture issuer/callback leaf
через `--ignore-certificate-errors-spki-list` и строгим loopback route allowlist.
Это точечное fixture browser исключение: per-request CA verification выполняют
независимый SDK и HTTP helper. HOME и системное хранилище доверия не меняются,
`ignoreHTTPSErrors` и глобальный TLS disable не используются.
Optional fonts блокируются при сохранённом source loader. Для проверки employee
eligibility можно перед consent выполнить ту же команду с
`--as employee --expect-denied`: document checkbox должен быть disabled,
одобрение и code exchange при этом не выполняются.

Manifest соответствует клиентскому wire-формату: `origin`, `caFile`, `runId`,
`sourceRevision`, `rental` (references), `operations` (monitoring), `documents`.
В каждом сценарии выдаются настоящие `vectors` с `allowed`, `foreign`, `ungranted`;
для документов — `allowedContent` с SHA-256 и `deniedContent`. References equipment
имеет ALL в пределах location boundary и не используется как проверка SET denial.

По запросу root реальные owner controls:

```sh
python tools/partner-pilots/sandbox/control.py operations-narrow
python tools/partner-pilots/sandbox/control.py rental-grant-revoke
python tools/partner-pilots/sandbox/control.py documents-member-revoke
```

`control.py` входит fake owner через HTTPS с per-request CA verification и вызывает
настоящие admin API. `operations-narrow` повторно одобряет установку с более
узким SET; `rental-grant-revoke` отзывает machine grant; `documents-member-revoke`
удаляет membership фактического delegated subject. Последняя команда выполняется
строго после остальных admin controls: в этой fixture субъект и единственный
owner-admin совпадают, после удаления его membership admin-доступ закрывается. HTTP bypass/control routes отсутствуют. Изменение
синтетических данных SQL возможно только в новом явно разрешённом SQL-окне.

## Завершение и проверки

По команде root:

```sh
python tools/partner-pilots/sandbox/server.py stop
```

Проверяется принадлежность PID; UVicorn завершается, owned pool закрывается,
незавершённая сборка останавливается. Browser helper всегда закрывает context/browser.
Перезапуск с потерянными process keys не маскируется: требуется отдельный полный
цикл очистки/инициализации. После остановки и нового SQL-разрешения:

```sh
python tools/partner-pilots/sandbox/server.py cleanup
```

`cleanup` удаляет только выделенную БД (без FORCE), соответствующий test upload
каталог, временные frontend/browser файлы и приватные ключи; сохраняет безопасную
`cleanup-summary.json`. До root stop сервис может оставаться явно owned test service
под наблюдением root для M18 workflow.

Проверки без БД: `python -m unittest discover -s tools/partner-pilots/sandbox -p test_guard.py`;
импорт реальных роутеров/curated policy проверяется отдельно без `app.main`;
main/public smoke build выполняется из текущих исходников. SQL/HTTP/browser результаты
относятся только к конкретному запуску и передаются root отдельно с origin, PID,
путями CA/client manifest/owner state, SHA и фактическими ограничениями.
