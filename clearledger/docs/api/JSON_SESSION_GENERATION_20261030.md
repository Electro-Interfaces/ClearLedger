# M12/M17: поколение JSON-сессии перед эффектами 401

Дата: 30.10.2026. Immutable baseline:
`ccfcd653f5cc01490bbf8571f9e89eae4a230ead`. Собственная ветка:
`agent/api-json-session-generation-20261030`, существующее изолированное дерево
`/home/mag/orca/workspaces/ledger-app/api-conf-context-20261030`.
Общие ветки не переключались, pull не выполнялся. Root согласовал bounded
runtime diff после воспроизведения на неизменённом baseline.

Разрешённый состав: только `src/services/apiClient.ts`, новый самостоятельный
`src/lib/apiJsonSessionGeneration.test.ts` и этот отчёт. Сервер, auth/context,
consumers, старые тесты, зависимости, endpoints, DTO и внешние протоколы не входят
в пакет. Программа M00–M19 остаётся открытой; merge/deploy не выполняются.

## Дефект и воспроизведение до правки

Прежние binary fence и opt-in conf POST guard уже проверяют поколение
Bearer/company/org. Обычные JSON-вызовы передают в общий обработчик только
отправленный Bearer и после `await res.json()` сравнивают его с текущей строкой.
После `setToken(A)` повторно, setter A→B→A или clearToken→setToken(A) поздний
401 старого запроса опять совпадает с текущим Bearer A и выполняет logout,
toast и постановку delayed redirect для новой сессии.

Перед runtime-правкой создан и запущен новый тест:

```sh
cd clearledger
node --test --experimental-strip-types src/lib/apiJsonSessionGeneration.test.ts
```

Actual baseline: **86 leaf cases: 42 PASS / 44 FAIL / 0 SKIP**;
с родительским test node: **87 tests, 42 PASS / 45 FAIL**, CANCELLED/TODO 0,
exit 1, 1.460 с. Это 44 проявления одного клиентского дефекта, не 45 отдельных
уязвимостей или доказательств production-инцидента. Ни один failure не связан
с загрузкой нового symbol, импортами или timeout.

42 failures: семь путей GET/POST/PATCH/PUT/DELETE/fetch-upload/XHR-upload ×
три перехода `setToken(A)`, A→B→A, clear→set(A) × две границы: deferred
response и deferred error JSON. Ещё два failures: новый вход с прежним token
при успешном и неуспешном чтении error body. Во всех 44 случаях сначала
подтверждается прежний `ApiError401` и точный detail, затем падает assertion
побочных эффектов:

```text
ожидалось: token=synthetic-A, timers=0, messages=[], href=''
получено:  token=null, timers=1, messages=['Сессия истекла'], href=''
```

Это постановка redirect, а не уже совершённая навигация. В positive normal401
control таймер продвигается вручную и проверяется safe next с query/hash.
До checkpoint SHA-256 apiClient совпадал с baseline:
`247ba8ac02dc3e9f9644c52a66e9250aa72a8b330fba38d26d55f7e65eb80693`.

42 controls PASS уже на baseline: current401 всех семи путей, public pages,
параллельный normal401 и повторное истечение следующей сессии, GET explicit
abort во время error body, сохранение identity network TypeError/AbortError,
сохранение успешного JSON после смены пользователя, прежняя защита по другому
Bearer/logout, opt-in conf guard и смена company/org, включая ABA.

Baseline TAP сохранён без перезаписи:
`.artifacts/private/json-session-baseline.tap`, SHA-256
`383215bdfac951edf1f01cd24e35ffb6a9e79528bfc7a6b59d603d52de3d6055`.

## Реализованный согласованный bounded diff

Отдельный приватный `sessionGeneration` увеличивается каждым `setToken` и
`clearToken`, включая повтор того же значения. Эти функции уже обозначают
новый вход и завершение сессии; `AuthContext.login/applySession` используют
`setToken`. Снимок поколения фиксируется до dispatch каждого JSON-запроса.
Оба upload пути используют один снимок, захваченный до fetch/XHR send.

Приватные `handleResponse` и `handleResponseError` передают снимок до условия
401 side effects. После error-body await прежний Bearer должен совпадать
с текущим, а отправленное поколение — с текущим поколением сессии. При
несовпадении только session side effects пропускаются: HTTP-ошибка остаётся
`ApiError401` с прежним detail. Проверка выполняется также после rejected
error JSON; parse fallback не возвращает старому ответу права на logout.

Company/org не увеличивают sessionGeneration: выбор учётного контура не
является новым входом пользователя. Обычный JSON current401 после company/org
ABA сохраняет прежний logout. Существующее `binaryContextGeneration` остаётся
более широкой границей намерения для binary и opt-in conf. Conf guard проверяет
её перед эффектами, поэтому stale guarded401 остаётся AbortError; normal
guarded401 остаётся ApiError401 после собственного logout. После clearToken
guard повторно не вызывается, ошибка не маскируется под отмену.

Успешные обычные JSON-ответы не отменяются при смене сессии. Без изменений
остаются 204/MIME/JSON parsing, 403/422, network errors, explicit abort,
redirect safe next и single-timer guard. Нет refresh/retry, новых публичных
options, смены headers/body или demo semantics. Binary tail не меняется.

## Harness и ограничения

Node v22.23.2, существующие зависимости `clearledger/node_modules`, установка
пакетов и изменение lock не требуются. Harness следует существующим Node/Vite
SSR тестам: настоящий apiClient и настоящий sonner; toast наблюдается через
публичный `getHistory`. Нет transform runtime или замены service/error handler.
`configFile:false`, `envFile:false`, middleware mode, watcher/HMR выключены;
Vite build не запускается. Подменены только fetch/XHR, window/storage, JSON-body
на Response и redirect timers. Все URL, токены, payload синтетические.

Обе await-границы контролируются отдельными deferred promises. Для XHR тело
строит настоящий apiClient через Response, его JSON boundary удерживается
на время перехода, как и у fetch. 401 rejection наблюдается до проверки
эффектов. Каждый case ограничен 8 с; parent — 45 с. Новая fixture использует
только семь разрешённых JSON-транспортов; прежние suites отдельно проверяют
binary/conf/voice/Auditor consumers.

Прямые записи в localStorage вне setters не увеличивают поколение. Прямая
запись другого token по-прежнему обнаруживается сравнением Bearer. Прямой
storage A→B→A или повтор A между проверками, в том числе в другой вкладке,
этот пакет не обещает обнаружить. Нет глобального storage/session lifecycle.

Клиентская проверка не отзывает уже отправленные server mutations и не
откатывает принятый POST/PATCH/PUT/DELETE/upload. Доставка запроса и успешные
JSON-результаты сохраняют прежний контракт. Реальные env/keys/API, SQL/БД,
SSH, browser, server ACL и production не использовались.

Отдельная непроверенная граница: после законного normal401 синхронный
clearToken предшествует `import('sonner').then(toast.error)`. Новый вход между
этими событиями может совпасть с поздним уведомлением о прежнем истечении.
Harness не удерживает module-import promise и не воспроизводит этот сценарий;
отсутствие позднего toast после законного logout не утверждается. Этот callback
побайтно сохранён, расширение UI lifecycle не входит в согласованный diff.
Для исходно stale401 после deferred error body проверены сохранённый token,
отсутствие toast в actual sonner history и отсутствие redirect timer; source
review подтверждает пропуск ветки, ставящей import callback.

## Итоговые проверки

Новый targeted candidate: **87/87 PASS**, FAIL/SKIP/CANCELLED/TODO 0, exit 0,
1.477 с. Сохранены все 86 leaf assertions, в том числе 44 красных на baseline.
После исправления lint-замечания `no-this-alias` в новой fixture её финальные
bytes повторно запущены на immutable baseline через существующий Git-load
режим harness, без замены рабочего apiClient:

```sh
JSON_SESSION_BASELINE=ccfcd653f5cc01490bbf8571f9e89eae4a230ead \
node --test --experimental-strip-types src/lib/apiJsonSessionGeneration.test.ts
```

Повтор: **42 PASS / 44 leaf FAIL + parent FAIL**, SKIP/CANCELLED/TODO 0, exit 1,
4.475 с при параллельных проверках. Причины и actual effects прежние; первая
baseline TAP не перезаписывалась. Финальная baseline TAP:
`.artifacts/private/json-session-baseline-final-test.tap`, SHA-256
`a4e2a080af4926845cf84b38bcdd9df3d6f58f5396ff3b6a8191bb97ed7d8746`.

Восемь прежних Node suites на неизменённом baseline: **509/509 PASS**, exit 0,
74.327 с; TAP `.artifacts/private/json-session-existing-baseline.tap`.
Финальный candidate combined включает те же восемь и новый девятый файл:

```sh
node --test --experimental-strip-types \
  src/lib/apiJsonSessionGeneration.test.ts src/lib/apiSessionRedirect.test.ts \
  src/lib/apiBinaryTransport.test.ts src/lib/confServiceContext.test.ts \
  src/lib/voiceServiceContext.test.ts src/lib/voiceAuth.test.ts \
  src/lib/auditorExportContext.test.ts src/lib/coreExportTransport.test.ts \
  src/lib/intakeDocsTransport.test.ts
```

Combined: **596/596 PASS**, FAIL/SKIP/CANCELLED/TODO 0, exit 0, **71.594 с**.
Это прежние 509 test nodes + новые 87; повтора intake/voice в сумме нет.
TAP `.artifacts/private/json-session-candidate-combined.tap`, SHA-256
`48197f784a3f82211805492ba6e78f3c1dc496f454670272b38c8cd798d5bc45`.
App TypeScript: PASS, exit 0, без диагностик; процесс завершён и reaped.
Node TypeScript: PASS, exit 0; targeted ESLint apiClient и нового теста:
PASS, 0 errors/warnings, exit 0. Использованы существующие бинарники
`node_modules/typescript/bin/tsc`, `node_modules/eslint/bin/eslint.js`;
app/node tsBuildInfo изолированы в own `.artifacts/private`.

```sh
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json \
  --tsBuildInfoFile ../.artifacts/private/json-session-app.tsbuildinfo
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.node.json \
  --incremental --tsBuildInfoFile ../.artifacts/private/json-session-node.tsbuildinfo
node node_modules/eslint/bin/eslint.js \
  src/services/apiClient.ts src/lib/apiJsonSessionGeneration.test.ts
git diff --check
```

| Проверка | Immutable baseline | Candidate |
| --- | --- | --- |
| Новые 44 leaf regressions | FAIL 44 | PASS 44 |
| Новые 42 leaf controls | PASS 42 | PASS 42 |
| Новый parent node | FAIL из-за 44 children | PASS |
| Прежние восемь Node suites, 509 test nodes | PASS 509 | PASS 509 |
| Общий состав девяти suites | Не был зелёным: см. отдельные baseline прогоны выше | PASS 596 |
| App/node TS | SKIP, отдельно baseline не запускались | PASS / PASS |
| Targeted ESLint runtime + финальный новый test | SKIP, отдельно baseline не запускался | PASS, 0 warnings |
| `git diff --check` | SKIP, отдельно baseline не запускался | PASS |

SKIP в таблице означает отсутствие отдельного запуска проверки; Node suites
не содержат skipped/cancelled cases. Единственный промежуточный lint failure
был в новой fixture (`no-this-alias`), заменён хранением XHR в массиве до
финального baseline replay и combined run. Runtime после PASS не менялся.

Source review через TypeScript AST: добавлен только `sessionGeneration`,
изменены `setToken`, `clearToken`, `handleResponseError`, `handleResponse`,
`get`, `post`, `patch`, `put`, `del`, `upload`. Удалённых statements нет.
`setApiCompany`, `setApiOrganization`, `captureApiContextGuard`, `headers`,
redirect/public helpers совпали по AST source; tail с `async function fetchBinary`
до конца файла побайтно идентичен. Все **53** прежних `src/lib/*.test.ts`
сравнены с immutable pin побайтно и совпали. Других tracked runtime изменений
нет; новые тест/отчёт не заменяют старые файлы. Evidence:
`.artifacts/private/json-session-source-review.json`.
SHA-256 этого source evidence:
`2f41cf8b8a2b9ef56432203b4b1a99f3c49502318d576f1ded265001f347b05a`.

SHA-256 итоговых runtime/test:

| Файл | SHA-256 |
| --- | --- |
| `src/services/apiClient.ts` | `e392ea29cb3708b256510220eb04c564d2529fdede1384aaaeb109651c31a898` |
| `src/lib/apiJsonSessionGeneration.test.ts` | `f5dee31eb38a9e2e85911ae60f2c0ac2e72dc289c4ea9ab994015a223c237067` |

SHA самого отчёта и exact immutable commit передаются координатору после commit;
self-hash внутрь файла не включается. Игнорируемые TAP/logs остаются в собственном
дереве для локальной приёмки и не содержат реальных данных.
