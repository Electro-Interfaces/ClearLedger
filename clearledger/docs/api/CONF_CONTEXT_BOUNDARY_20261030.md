# M12/M17: отложенные callbacks конференций, 30.10.2026

Статус: actual baseline воспроизведён офлайн, принят координатором; согласованный
пакет реализован. Финальный Node-прогон: **471/471 PASS**
(56 проверок конференций + прежние 415). Промежуточные 464 PASS и последующие
3 FAIL адресного review401 сохранены отдельно; все три вопроса закрыты
проверками финального пакета. Это проверка клиентского поведения
исходников, не подтверждённая уязвимость, не инцидент production и не проверка
серверного ACL. Программа M00–M19 остаётся открытой; merge/deploy не выполнялись.

## Неизменяемая база и ownership

Отдельное рабочее дерево:
`/home/mag/orca/workspaces/ledger-app/api-conf-context-20261030`.
Ветка `agent/api-conf-context-20261030` создана от
`6ca287dc5763004b0ef07c169da48d7236c614b5`, без переключения общих копий.
Заданный immutable pin имеет приоритет над обычным обновлением клона через pull.

Git blob pins этой базы:

| Файл | Blob |
| --- | --- |
| `src/services/confService.ts` | `32aec774223c0123fbd0a44f3fa067319aa62fcc` |
| `src/services/conferenceService.ts` | `834e507daf3443fcd7682c0f6769a8f3c936c454` |
| `src/services/apiClient.ts` | `5f287cf2d0dff40ed6f1d8ea4bdee3cffabfbe5e` |
| `src/services/cacheReset.ts` | `f6d2cad1f0f100c38c758e4739a4075d5cfcabef` |
| `src/contexts/AuthContext.tsx` | `bfcc63a263874af1bd463a07b7d5a8f86cdb266d` |
| `src/contexts/CompanyContext.tsx` | `b7a54f134749099d383c60b4268e1bf7441e1739` |

Первоначальный разрешённый состав до решения координатора: только новый тест
`src/lib/confServiceContext.test.ts` и этот отчёт. Исходники сервисов, auth,
context, существующие тесты и контракты на этапе baseline не менялись. Затем
координатор отдельно разрешил три runtime-файла, перечисленные ниже.
Существующие зависимости
подключены игнорируемой ссылкой `clearledger/node_modules` на установленный
`/srv/projects/ledger-app/clearledger/node_modules`; установки пакетов не было.

Placement: штатная команда
`orca worktree create --name api-conf-context-20261030 --base-branch 6ca287dc5763004b0ef07c169da48d7236c614b5 --setup skip --json`
создала отдельное дерево с указанным HEAD, затем автоматически выбранная Orca
ветка была переименована в заданную `agent/api-conf-context-20261030` внутри
нового чистого дерева. Исходный dispatch cwd находился в чужой рабочей копии
`api-station-import-ambiguity-20261030` на другой ветке; её не переключали.
Lifecycle отправлялся с первоначальными dispatch/terminal handles, дополнительных
деревьев после решения root не создавалось.

## Активность и цепочка контекста

`confService.следитьЗаВкладкой` (строка 133) действительно вызывается:

- `confService.joinMeeting` (168): `ConfTalksPage`, карточка встречи в
  `pages/conf/parts.tsx`, создание встречи с заранее открытой вкладкой,
  `HeaderInteractionButtons`;
- `confService.joinRoom` (338): `pages/conf/RoomCards.tsx`;
- `conferenceService.startEventMeeting` (77): календарь, при наличии
  `session_id` в ответе; импорт образует существующий цикл с `confService`.

Все три входа загружаются в тесте как настоящие модули. Комментарий в исходнике
о входе ведущим не заменяет реальный контракт: клиент использует поле
`moderator_url`, а фактический ответ может иметь `moderator: false`.

`apiClient.getToken` читает localStorage в момент вызова. `setToken` вызывается
в `AuthContext.login/applySession`, а logout удаляет токен и вызывает
`resetServiceCaches`. `CompanyContext.activateContext` синхронно устанавливает
`setApiCompany`, затем при изменении пользователя или компании очищает query cache
и сервисные кеши; смена пользователя при прежней компании тоже сбрасывает кеши.
`setOrganizationId` вызывает `setApiOrganization` синхронно и очищает query cache,
без `resetServiceCaches`.

Вход инженера: `SpaceGuestPage` выполняет `/api/eco/partner/visit`, затем
`applySession(res.access_token)`; он попадает в ту же границу `setToken`.
Сама React-страница и настоящий visit в этой проверке не исполнялись.
Тест использует настоящие сеттеры и `resetServiceCaches/setServicesCompany`
в порядке, соответствующем исходникам. React и query cache не эмулируются.

`cacheReset` сбрасывает source/channel/location/voice/authFiles, но не содержит
`confService` и не убирает его таймеры/pagehide. `apiClient.post` берёт текущие
Bearer, `X-Company-Id`, `X-Organization-Id` непосредственно перед fetch. Его
JSON-результат не защищён проверкой контекста после await. Поколение
`binaryContextGeneration` приватное и используется только binary transport;
не следует считать его уже действующей защитой этих JSON-вызовов.

## Воспроизводимость и результат baseline

Из `clearledger`, только установленный Node/Vite:

```sh
node --test --experimental-strip-types src/lib/confServiceContext.test.ts
```

Первый полный прогон: **35 тестов: PASS 15, FAIL 20, SKIP 0, TODO 0,
CANCELLED 0**, длительность 46.1 с. Все 20 FAIL находятся на assertions
требуемой границы; они предварительно печатают реальные requests либо browser
side effects. Нет ошибок импорта, отсутствующих новых symbols, таймаутов тестов
или незавершённых intervals. Код завершения самого Node — 1; это ожидаемый
красный baseline, а не зелёная приёмка исправления. Диагностик с actual effects
ровно 20, иных типов failures нет. Дополнительный запуск только контролей:

```sh
node --test --experimental-strip-types --test-name-pattern='^control:' src/lib/confServiceContext.test.ts
```

**15/15 PASS**, FAIL/SKIP/CANCELLED 0, 21.0 с, exit 0; Node v22.23.2.
`git diff --check` проходит, вне двух новых файлов tracked-изменений нет.

Vite запускается в SSR middleware mode, без listen, watcher и HMR, с
`configFile: false`, `envFile: false`; проектные env-файлы не читаются. Нет
transform/load-подмен исходников. Настоящий `sonner` также не подменяется:
наблюдается его публичный `toast.getHistory()`.

Подменены только fetch, window/lifecycle/popup, его timers и storage. Таймеры
присутствия хранятся в Map и продвигаются вручную; реальные 30-секундные intervals
не запускаются. Ответы fetch и json-body откладываются отдельными bounded
deferred, каждый тест ограничен 8 с. Fixture убирает Map и globals без вызова
pagehide, чтобы teardown сам не порождал leave. URL ограничены `.example.test`,
поля и токены синтетические. Никаких реальных HTTP/WS, конференций, токенов встреч,
записей, БД/SQL, браузера, SSH или env-access не было.

### Положительные контроли: PASS 15

1. Открытая вкладка: ping, POST без body, Bearer A, company A и organization A.
2. Закрытая вкладка: leave, POST без body, `keepalive: true`, Bearer A;
   нет company/org заголовков; interval прекращается.
3. Pagehide: один keepalive leave, interval прекращается, дочернее окно открыто;
   повтор pagehide не вызывает once-listener снова.
4. Без токена: фактически существующий контракт отправляет ping и leave без
   Authorization. Утверждения «нет токена → запрос невозможен» в коде нет.
5–7. Meeting, room и calendar: blank-popup открыт синхронно до ответа,
   `opener = null`, затем именно `moderator_url` и запуск присутствия.
8. Переданная вызывающим заранее открытая вкладка используется повторно.
9. Заблокированный popup: fallback на moderator URL с `noopener,noreferrer`;
   tracker с null-вкладкой выполняет leave на первом tick.
10. Вход участником сохраняет реальное объяснение через toast.
11–13. AbortError, network error и HTTP 403 при join: закрыть blank-вкладку,
   сохранить исходную ошибку, не запустить присутствие и pagehide-listener.
14. Abort/network/HTTP 503 в ping/leave поглощаются; автоматических retries нет.
15. Смена principal после уже отправленного ping не переотправляет его с B;
   исходный request уже имеет A. Отмена на сервере этим не утверждается.

### Отложенная отправка после смены контекста: FAIL 12

Четыре изменения × три callbacks: interval ping, закрытая вкладка leave,
pagehide leave. Сначала создаётся настоящий tracker A, затем меняется контекст,
только потом выполняется callback. Во всех 12 случаях наблюдается один
отправленный запрос старой session A и старой `company_id` в URL.

| Изменение перед callback | Ping: auth / company / org headers | Leave: auth / keepalive |
| --- | --- | --- |
| Другой principal, та же компания | B / A / A | B / true |
| Другая компания, тот же token | A / B / A | A / true |
| Другая организация, тот же token/company | A / A / B | A / true |
| Logout, clear company | отсутствует / отсутствует / A | отсутствует / true |

Во всех запросах body `undefined`. Leave идёт через raw fetch и вообще не
передаёт `X-Company-Id`/`X-Organization-Id`; компания остаётся в query. Отличие
headers от query — наблюдение клиента, не доказательство того, что сервер
разрешит действие.

Пример actual wire при principal A→B:

```text
POST https://core.example.test/api/conf/sessions/session-synthetic-A/ping?company_id=company%20A%20%2F%20synthetic
Authorization: Bearer core-synthetic-B
X-Company-Id: company A / synthetic
X-Organization-Id: organization-A
body: undefined
```

### Позднее завершение join после смены контекста: FAIL 8

- Три входа (meeting/room/calendar) × два места await (fetch response/json body):
  после principal A→B реальный join Promise возвращает старый payload,
  blank-вкладка переходит на старый moderator URL, начинается новый interval.
  Join был отправлен с Bearer A **до** смены контекста; тест не требует отменить
  уже принятое сервером действие и не предполагает повторного HTTP join.
- При заблокированном popup ответ meeting после смены компании открывает старую
  moderator-ссылку через fallback `window.open`.
- Ответ участника после смены организации выдаёт старое объяснение через toast.

## Предложение, переданное координатору до runtime-правок

Для исправления всей подтверждённой цепочки потребуется отдельное разрешение
ownership на `confService.ts`, `conferenceService.ts` и согласованную границу
с `apiClient.ts` (этот файл общий с другими исполнителями).

Предпочтительный вариант: координатор/владелец HTTP-клиента предоставляет маленький
context guard, использующий уже имеющееся поколение и снимок Bearer/company/org.
Не менять семантику всех JSON-запросов ради этого случая. Один guard захватывать
при создании tracker и до первого await join; перед каждым deferred dispatch,
навигацией, fallback popup, toast и созданием присутствия проверять актуальность.
Для устаревшего tracker снимать interval и pagehide без leave от нового principal;
для устаревшего join закрывать подготовленную вкладку и возвращать AbortError.
Тот же guard нужен календарному `startEventMeeting` до его side effects.

Сравнение одних строк токена недостаточно для A→B→A и нового входа с прежним
значением токена; локальный snapshot только в `confService` также не увидит
текущую компанию, поскольку публичного getter компании сейчас нет. Поэтому
самостоятельно добавлять новую auth/context систему в этот сервис не предлагается.

Сохранить обычные ping/leave с keepalive, once-pagehide, moderator URL и
синхронное открытие popup. Удалённую отмену уже отправленного join/ping/leave,
отключение Jitsi либо закрытие ранее успешно открытой конференции не обещать.

До отдельного решения root runtime, коммит и push не выполнялись. Координатор
принял 35-case baseline и разрешил runtime-пакет ниже; следующая часть отчёта
описывает выполненную работу, а не исходную гипотезу.

## Первый пакет после решения root: промежуточный состав

В `apiClient.ts` добавлен единственный export `captureApiContextGuard(): () => void`.
Он захватывает существующее поколение и фактические Authorization/company/org
headers; вызов возвращённой функции проверяет их и бросает AbortError при смене.
Сеттеры, общий JSON transport, error handling и binary-функции не изменялись.
Уточнён только комментарий к поколению, поскольку теперь им пользуются и явно
захваченные guards. Автоматических retries не добавлялось.

В `confService.следитьЗаВкладкой` guard захватывается один раз на создание tracker.
Каждый interval/pagehide callback проверяет его до запроса. При устаревании
tracker снимает interval и pagehide-listener, без нового leave и без закрытия
успешно открытой встречи. Обычные callbacks сохранили прежние query/header/body,
keepalive, no-token и once-pagehide контракты.

`joinMeeting`, `joinRoom` и календарный `startEventMeeting` захватывают guard до
await post. После него проверяют контекст до navigation/fallback, создания
присутствия, объяснения и return. В catch устаревший контекст имеет приоритет
перед поздней ошибкой запроса и возвращает AbortError; при текущем контексте
исходная ошибка сохранена. Закрывается только ещё пустая `about:blank` вкладка;
чужой origin не читается повторно после SecurityError и уже открытое человеком
окно не закрывается. Синхронный popup, `opener = null`, `moderator_url` и fallback
`noopener,noreferrer` сохранены.

`conferenceService.startMeeting`, `startTicketMeeting`, `aud=voice`, внешний
Auditor, React auth/context, серверы и старые тесты не менялись и этим пакетом
не объявляются защищёнными.

### Промежуточные проверки до дополнительного review401

Один общий Node-прогон на промежуточных runtime/test bytes:

```sh
node --test --experimental-strip-types src/lib/confServiceContext.test.ts src/lib/voiceServiceContext.test.ts src/lib/voiceAuth.test.ts src/lib/apiSessionRedirect.test.ts src/lib/apiBinaryTransport.test.ts src/lib/coreExportTransport.test.ts src/lib/intakeDocsTransport.test.ts
```

**464 PASS**, FAIL/SKIP/CANCELLED/TODO 0, exit 0, 52.9 с. Число 415 уже
включает intake и voiceServiceContext; повторно их к знаменателю не прибавляем.
Все исходные 35 conf cases сохранены, дополнены 14 случаями:

- 4 перехода (principal/company/org A→B→A, повторный `setToken` с прежним значением)
  × tracker и pending join = 8 проверок; финальные заголовки могут совпадать,
  но поколение прежнее действие уже завершает;
- повторные `setApiCompany`/`setApiOrganization` с прежними значениями сохраняют
  pending join, ping и keepalive leave;
- microtask/outer-await hop после завершения json body для всех трёх входов;
- late401 с прежним Bearer A не завершает новую сессию B; service возвращает
  context AbortError, prepared blank закрывается;
- stale join не закрывает окно, которое человек уже перевёл на другой URL.

Проверки типов и lint установленными средствами, с отдельными incremental caches
в `/tmp`, чтобы не менять кеши соседних worktrees:

```sh
./node_modules/.bin/tsc --noEmit -p tsconfig.app.json --incremental --tsBuildInfoFile /tmp/conf-context-app-20261030.tsbuildinfo
./node_modules/.bin/tsc --noEmit -p tsconfig.node.json --incremental --tsBuildInfoFile /tmp/conf-context-node-20261030.tsbuildinfo
./node_modules/.bin/eslint src/services/apiClient.ts src/services/confService.ts src/services/conferenceService.ts src/lib/confServiceContext.test.ts
```

App TypeScript, node TypeScript и targeted lint: **PASS**, exit 0; lint 0 errors,
0 warnings. `git diff --check`: PASS. Временные TAP-логи находятся на сервере
в `/tmp/conf-context-{baseline,controls,combined-final}-20261030.tap`;
долговечное evidence — source/test/report в этом пакете, `/tmp` не предназначен
для открытия с ПК.

Source review выполнен сравнением top-level TypeScript AST statements с
immutable baseline. За пределами imports и комментария изменения строго такие:

| Модуль | Изменённые/добавленные statements |
| --- | --- |
| `apiClient.ts` | только новый `captureApiContextGuard` |
| `confService.ts` | `следитьЗаВкладкой`, `joinMeeting`, `joinRoom` |
| `conferenceService.ts` | только `startEventMeeting` |

Хвост `apiClient.ts` от `async function fetchBinary` до конца файла побайтно
совпал с базой. Все прежние transport/session/intake/voice tests, `cacheReset`,
auth/context и внешние source modules сохранены.

SHA-256 промежуточных исходников до review401:

| Файл | SHA-256 |
| --- | --- |
| `src/services/apiClient.ts` | `6e62f4bee0badb750131bb6e15887485643ead7a7f9321d50dc5784e1111551a` |
| `src/services/confService.ts` | `ff6908c8ae1c5bb182ecebffff8da0a26681703d6f009342024e36951ec0e456` |
| `src/services/conferenceService.ts` | `08dbc58d16e2ae71d6c6161b36881f627f1e09e17f9e1a573cbdce97bf80d0ca` |
| `src/lib/confServiceContext.test.ts` | `f9b89bd190e4675ab248e4f9ef897fa187cb5524e0a17d528a698d66ceb1227d` |

### Дополнительный адресный review401

Координатор запросил actual-проверку конкретной гипотезы о shared error effects
и обычном current401. В fixture добавлен stub только redirect-таймеров 1500 мс;
настоящие toast, fetch/client/error handling не подменяются.

```sh
node --test --experimental-strip-types --test-name-pattern='^review401:' src/lib/confServiceContext.test.ts
```

На промежуточном runtime: **0 PASS / 3 FAIL**, SKIP/CANCELLED 0, 5.8 с.

| Сценарий | Actual token / redirect timers / toast / error | Требуется |
| --- | --- | --- |
| `setToken(A)` повторно после отправки join A, до старого401 response | null / 1 / «Сессия истекла» / AbortError | A / 0 / нет / AbortError |
| Company setter A→B→A во время отложенного json-body старого401 | null / 1 / «Сессия истекла» / AbortError | A / 0 / нет / AbortError |
| Обычный current401 без смены контекста | null / 1 / «Сессия истекла» / AbortError | null / 1 / тот же toast / ApiError401 |

Первые два случая подтвердили, что service guard после post опаздывает к
clearToken/toast/redirect в shared error handler. Третий выявил регрессию первого
candidate: безусловный guard в service catch видит поколение от собственного
clearToken и маскирует ожидаемый ApiError401. Перед расширением runtime root
переданы actual evidence и минимальный opt-in дизайн, default transport и binary
не менялись. TAP: `/tmp/conf-context-review401-before-20261030.tap`.

Предложен третий options-аргумент `post` с явно переданным contextGuard,
threading через private `handleResponse` в уже существующий guard-hook
`handleResponseError`, проверка fetch reject/response и JSON await. В join catch
убрать безусловную повторную проверку: ordinary current401 после своего logout
должен сохранять ApiError401. Guarded callers — только ping и три входа; default
post и binary сохраняют прежний контракт. Root отдельно разрешил этот opt-in
пакет; финальная реализация и проверки описаны ниже.

## Финальный пакет: guard перед эффектами ответа

Root отдельно разрешил opt-in threading в двух функциях `apiClient`:

- `post(path, body?, { contextGuard? })` проверяет явно переданный guard до
  dispatch, после fetch и при fetch rejection. Catch охватывает только fetch:
  ошибки `handleResponse` не перехватываются повторным guard после собственного
  logout;
- private `handleResponse` передаёт guard в **существующий** hook
  `handleResponseError`. Его проверка после error JSON и до 401-effects уже
  имелась; сама функция не менялась. Success JSON проверяется после await,
  parse rejection тоже проверяет контекст, поэтому отмена не маскируется под 502.

Опцию передают только presence ping, `joinMeeting`, `joinRoom` и
`startEventMeeting`, с guard исходного намерения. Сервисные проверки после post
до navigation/fallback/tracker/toast/return сохранены, включая outer-await hop.
Безусловный повторный guard из трёх join catch удалён. Стабильный current401
сначала проходит transport guard, выполняет обычный logout и возвращает
**ApiError401**; его собственный clearToken не считается поводом заменить ошибку
на AbortError. Stale401 при same-token re-login или setter ABA блокируется
**до** clearToken, redirect и toast.

Default `post` без опции, все другие HTTP methods, `handleResponseError`,
setters и binary transport сохраняют прежнюю семантику. Новых автоматических
retries, смены base URL, auth headers или body/query-контрактов нет.

Адресный повтор первых трёх review401-cases: **3/3 PASS**, 5.5 с, exit 0.
Оба stale случая сохранили token A, redirect timers 0, сообщений 0; обычный401
сохранил null token, один redirect timer, прежний toast и ApiError401.

Финальный общий запуск той же команды семи файлов: **471/471 PASS**,
FAIL/SKIP/CANCELLED/TODO 0, exit 0, **71.9 с**; Node child завершён и reaped.
Финальные app TypeScript, node TypeScript и targeted ESLint той же командной
последовательностью: **PASS**, exit 0, lint 0 errors / 0 warnings; процесс
завершён и reaped. Повторных broad checks после этого не требуется.
Это **56 conf + прежние 415**, без повторного подсчёта intake или voice.
К промежуточным 49 cases добавлены 7:

- три review401 из таблицы выше;
- один default post control с обычными 401/422/403/204, MIME, повреждённым JSON,
  network TypeError и AbortError: исходные классы/статусы/поля/body/headers и
  session/redirect/toast сохранены;
- stale JSON parse rejection остаётся AbortError, а не parser502;
- stale fetch rejection становится context AbortError без session effects;
- уже отправленный ping сохраняет **исходный** guard до позднего error response,
  не очищает token при org setter ABA и не отправляет follow-up после retirement.

Положительные контроли не ослаблялись, старые тесты не редактировались.
Промежуточные исходные 35 cases остаются в итоговом наборе.

Финальная AST-проверка разрешённых statements:

| Модуль | Изменённые/добавленные statements |
| --- | --- |
| `apiClient.ts` | новый `captureApiContextGuard`, opt-in `post`, private `handleResponse` |
| `confService.ts` | `следитьЗаВкладкой`, `joinMeeting`, `joinRoom` |
| `conferenceService.ts` | только `startEventMeeting` |

**`handleResponseError` и binary tail побайтно совпали с immutable baseline**;
остальные methods, setters, внешние modules и прежние tests не менялись.
Число неожиданных AST statement changes: 0. Весь tracked пакет — ровно пять
согласованных файлов: три runtime-модуля, новый тест и этот отчёт.

Финальные SHA-256:

| Файл | SHA-256 |
| --- | --- |
| `src/services/apiClient.ts` | `247ba8ac02dc3e9f9644c52a66e9250aa72a8b330fba38d26d55f7e65eb80693` |
| `src/services/confService.ts` | `9d20ef54978382eab812952f48acad40cbb11383adc38f6f25035b6499326c26` |
| `src/services/conferenceService.ts` | `f8d43932580539b132b50ff547d13c19f28ddf16046b2f8b476085f8dec24d72` |
| `src/lib/confServiceContext.test.ts` | `eab6cb8b9ae399dcedbe37be78df6bc1e6a94d694fe9f41520eb76405f82c368` |

Долговечные локальные артефакты в own worktree, игнорируются Git:

- `.artifacts/private/conf-context-baseline-20261030.tap`: исходные 15 PASS / 20 FAIL;
- `.artifacts/private/conf-context-controls-20261030.tap`: 15/15 positive controls;
- `.artifacts/private/conf-context-combined-final-20261030.tap`: промежуточные 464 PASS;
- `.artifacts/private/conf-context-review401-before-20261030.tap`: адресные 3 FAIL;
- `.artifacts/private/conf-context-review401-after-20261030.tap`: адресные 3 PASS;
- `.artifacts/private/conf-context-final-20261030.tap`: финальные 471 PASS;
- `.artifacts/private/conf-context-source-review-20261030.json`: разрешённый AST diff;
- `.artifacts/private/conf-context-final-checks-20261030.log`: финальные type/lint checks.

Это исходники и синтетическое evidence; реальные credentials, операционные
выгрузки клиентов, записи и session secrets в артефакты не включались.

## Границы финального результата

Поколение замечает переходы через существующие setters, включая ABA и новый
вход с тем же token. Прямой storage ABA между двумя проверками без setters
не обещается. Компания/организация здесь — клиентская граница отложенного
действия, а не доказательство серверной авторизации.

Shared error handler в целом не переводился на новую политику: opt-in guard
защищает перечисленные четыре callers. Другие unguarded методы/вызовы не
объявляются защищёнными от same-token/ABA late401. Фактически проверенные
guarded old401 и normal current401 из адресного review в финале исправлены.

Guard действует от начала соответствующего join/tracker до его return;
внешние create→await→join цепочки до вызова этих функций и callbacks вызывающего
после уже возвращённого результата не отзываются этим service. Уже отправленные
join/ping/leave не отменяются и не откатываются на сервере. Открытая ранее комната
не закрывается при смене компании или учётки.

Полного UI/production/security scan, реальной приёмки API/ACL/Jitsi, токенов встреч,
записей и БД не было. Проверка ограничена локальными синтетическими Node-тестами
и source review; программа M00–M19, merge и deployment остаются за пределами пакета.


## Независимая приёмка интеграции

Source1493fe83 перенесён в интеграционную ветку коммитом59e6822b. Координатор
повторил те же семь Node-модулей: **471 PASS, 73,763с**, без FAIL, SKIP,
CANCELLED и TODO. Child EXIT0/reaped. App TypeScript, node TypeScript и
targeted ESLint трёх сервисов и нового теста также EXIT0/reaped.

Проверены четыре финальные SHA256 выше, разрешённые AST изменения трёх
runtime-модулей и побайтовое совпадение девяти прежних source/test modules.
В частности handleResponseError, binary functions, headers и setters не
изменены. Private evidence: `.artifacts/root-conf-context-final.log`,
`.artifacts/root-conf-context-boundaries.mjs` и
`.artifacts/root-conf-context-expected-sha.json`. Это bounded клиентская
приёмка; ограничения исходного отчёта и незавершённость M00–M19 сохраняются.
