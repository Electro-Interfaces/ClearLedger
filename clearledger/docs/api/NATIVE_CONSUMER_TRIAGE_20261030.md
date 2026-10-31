# M01/M12: разбор native transport boundaries

Дата: 30.10.2026. Immutable source: `62bd4a4604028309ea17100ee8c320818d9c2400`. Только source review; M00–M19 не завершена. Runtime, новые тесты, merge и deploy не выполнялись.

Пересчёт: **43 native AST-записи** (39 fetch, 2 WebSocket, XHR constructor и open), из них **9 implementation** общего apiClient и **34 вне него**. Constructor/open одного XHR не считаются двумя бизнес-запросами. Исторический inventory на `06e02207c29651682530309bea1a4157f48b3168` сохранён без изменений.

Actual scope: 1147 production source files, 304635 строк; 5266 records = 1459 shared + 43 native + 3764 unresolved wrapper candidates. От исторического summary: строк +68, wrapper candidates −5, native/shared без изменений; исключён 54 test/declaration вместо 53. Эти дельты не являются числом новых/исправленных runtime запросов. Ноль syntactic diagnostics не означает typecheck или server acceptance.

## Метод и воспроизводимость

Работа от clean own worktree, новая ветка `agent/api-native-consumer-triage-20261030` от указанного pin; другие ветки не подтягивались. Существующий generator не менялся. Его `pinnedBase` остаётся исторической константой; current label задан явным `--revision` и независимо проверен Git bytes.

```sh
git rev-parse 62bd4a4604028309ea17100ee8c320818d9c2400
node clearledger/scripts/inventory-api-consumers.mjs --root clearledger --output .artifacts/private/native-triage-20261030/inventory.json --revision 62bd4a4604028309ea17100ee8c320818d9c2400
```

Команда запускается на этом source snapshot, с уже установленным TypeScript 5.9.3, без env/module application loading или установки пакетов. Повторный private output должен дать тот же SHA-256. Независимый `git cat-file --batch` сравнил все 1147 blobs pin с manifest и рабочими байтами: 0 расхождений. AST span/expression hash каждой native записи проверяется отдельно на текущих bytes. Полные SHA-256 17 native source files приведены в `nativeSourceSha256` bounded JSON.

| Контроль | Значение |
|---|---|
| Generator SHA-256 | `a197d4788dda5502884b276dda71b0f61ef82538d20cabd9adcdae00a962cd05` |
| Source manifest canonical SHA-256 | `37e718fcf202740a545e2e37c5048b3269f7ad006a1a4025db62497770e0ead3` |
| Private inventory canonical SHA-256 | `6d80bd8cd6640e73e7884f27a1252b78a4c1f614f64df45de9958707d6149580` |
| Paired bounded JSON SHA-256 | `ed4b18f0a48ba7cf3f82e52aa62c9f247d0e2af1c3c650bf5ed274d700402d24` |

Полный manifest, raw records и selected snippets остаются только в private `.artifacts/private/native-triage-20261030/` с mode0600 и не входят в коммит. Публичный JSON содержит только triage 43 ключей, контракты и выбранные immutable refs; это не повтор raw inventory. Markdown таблицы выведены из того же JSON.

`source-reachable` означает наличие caller/entry в исходнике, а не трафик в production. `shared-implementation` отделяет реализацию от consumers; `dev-only-conditional` не считается production dispatch; `no-static-caller` оставляет используемость неизвестной. Импорт/JSX/use hook edge и непосредственный local call различаются именем ссылки; это статическая цепочка, без interprocedural runtime доказательства.

## Контракты и владельцы

Каждая строка Nxx наследует **все шесть** полей своей boundary из этой таблицы и `boundaries` JSON; `contractOverrides` сохраняют различия конкретных Auditor endpoints. Имена backend owner установлены исходником, не адресом выпущенного сервиса. External node/vendor source отсутствует в этом Git pin, его ACL не подтверждены. Auditor backend просмотрен только через immutable Git object отдельного локального repo на `ec22e16483b3a980cc85905ae647377cdd03a230`; это owner mapping, не доказательство версии стека.

| Boundary | Владелец и протокол | Auth и context | Error и abort |
|---|---|---|---|
| core-json | Core API / apiClient; route зависит от caller; HTTP JSON; BASE=VITE_API_URL | Core Bearer + X-Company-Id + X-Organization-Id snapshot на dispatch; browser credentials default; JSON success не fenced; late401 сравнивает sent Bearer после error body; demo dispatch guard | handleResponse: 204, JSON/content-type, ApiError/422/403; текущий private401 Core logout; GET принимает caller signal; JSON mutations signal не принимают |
| core-upload | Core API / apiClient upload; HTTP multipart fetch либо XHR progress; BASE=VITE_API_URL | Core headers snapshot; include только явно запрошенный upload option; intake уже переведён на upload; успешный ответ без context generation guard | fetch/XHR используют handleResponse; XHR network/timeout ApiError; upload публичного signal не имеет; xhr abort handler/signal API отсутствует |
| core-binary | Core API / apiClient binary implementation; HTTP Blob; downloadFile/downloadBlob; BASE=VITE_API_URL | Core Bearer/company/org snapshot; binary generation + header comparisons при await и перед download effects; A→B→A через setters | общий HTTP error parser; filename fallback и finally cleanup уже приняты; caller signal плюс generation guard; уже отправленную server mutation не откатывает |
| auditor-proxy-json | ecosystem-deploy services/auditor; отдельно от Core /api/auditor; same-origin /auditor/api HTTP JSON/multipart | agentHeaders: Core Bearer и явный company; отдельные export/dictate без company; reload вообще без headers; нет общего lifecycle generation; caller передаёт company; org не переносится автоматически | собственные error JSON; часть GET проверяет JSON MIME; sessions/prompts fallback []; у обычных HTTP helpers нет caller signal |
| auditor-proxy-binary | ecosystem-deploy services/auditor export-work; same-origin HTTP tar Blob → object URL → anchor click | Core Bearer; без X-Company-Id в этом вызове; нет guard между await blob и download effects; caller найден, race не воспроизведена | error JSON/message; click и revoke без finally; signal не принимается |
| auditor-proxy-sse | ecosystem-deploy services/auditor ask; POST multipart-independent JSON → text/event-stream reader | Core Bearer + явный X-Company-Id; payload context/history/files/workshop; контекст передан caller; общий session fence отсутствует; UI owns controller | проверка status/body/MIME, callbacks onError/onDone; AbortError тихо; возвращаемый AbortController.signal в fetch; reader обработан своим циклом |
| auditor-ws | ecosystem-deploy services/auditor terminal; same-origin ws(s) /auditor/ws/terminal; PTY messages | первый frame type=start: Core token + companyRef; URL без token; effect зависит attempt/tab/hasCompany; companyRef актуализируется; это не proof полноценного tenant lifecycle | UI state; 4001 detached, 4002 ended, ограниченный reconnect; effect cleanup закрывает socket/terminal и timers |
| chat-ws | Core chat_router websocket; ws(s) от VITE_API_URL; subscribe/typing/ping frames | Core token query при connect; server _ws_user/_ws_can_subscribe; connect effect с subscribe dependency; channels отдельным effect; reconnect читает новый token; lifecycle не проверен runtime | 1008 stop; exponential retry max5; polling fallback вне hook; disposed + timers cleanup + socket.close; AbortSignal не подходит WS |
| static | frontend build/public assets; HTTP BASE_URL asset; JSON/text font dictionary | Bearer/company/org не нужны; browser default credentials; не tenant data; не Core JSON consumer | свой asset-specific fallback/parse; см. item; RegionsLayer alive guard; update stopped guard; fonts shared promise без signal |
| error-telemetry | Core client_errors_router + ErrorBoundary; HTTP JSON POST keepalive | optional Core Bearer; без company/org headers; bounded per-tab rate limit; не обычный бизнес-запрос | best effort; network errors swallowed; HTTP status не потребляется; намеренно keepalive; caller signal отсутствует |
| gate-cookie | Core auth gate/logout; public bundle entry; same-origin POST HttpOnly gate cookie | gate Bearer + same-origin cookie; logout после clearToken без Bearer; ToApp gone guard перед redirect; logout снимает только cookie | gate ok→target иначе login; logout best effort без Core redirect handler; gone предотвращает effects; fetch signal отсутствует |
| docs-oauth | Core-owned docs_portal + partner_oauth; отдельная trust boundary; same-origin docs cookie/session + OAuth form-urlencoded PKCE exchange/revoke | docs scoped OAuth access token в памяти → HttpOnly docs cookie + X-Docs-CSRF; credentials omit на OAuth; Core metadata только shared get; generation/state/nonce/PKCE/currentSession.userId; cancelDocsRuntime; не хранит Core token | DocsError; нет Core logout на docs401; token response отдельно проверяется; docsRequest пробрасывает supplied signal; exchange/revoke без signal, generation cleanup |
| conf-presence | Core conf_router session_leave; HTTP POST keepalive leave; ping shared post отдельно | Bearer читается в delayed leave; companyId/sessionId захвачены closure; timer/pagehide lifetime; связь с login/context reset требует отдельного воспроизведения; backend фильтрует membership/session company/current_user presence | best effort; HTTP status не потребляется; keepalive; timer cleared при window close/pagehide; context disposal API отсутствует |
| external-sts | внешний STS fuel API; backend implementation вне этого pin; vendor HTTP JSON/text login; dev proxy либо settings base | свой STS token/storage/expiry/login и один auth401 retry; Core Bearer не используется; own settings/token keys; company generation не предусмотрена; не RusHydro Core | transport exception retries max3, HTTP ошибки у authFetch/login; demo guard; AbortSignal.timeout(30000) заменяет options signal; без caller cancellation |
| external-msto | внешний MSTO IntegratorService; backend implementation вне этого pin; vendor HTTP session + private JSON APIs; dev proxy/override/base | собственный JWT storage/expiry; credentials из connection args; один auth401 relogin; own global token keys; Core company/org headers здесь не контракт | transport exception retries max3; HTTP ошибки у authFetch/login; wrapper без demo guard; AbortSignal.timeout(60000); без caller cancellation |
| external-tradecorp | внешний TradeCorp API; backend implementation вне этого pin; vendor JSON-RPC login + versioned JSON data; dev proxy/override/base | свой token storage/expiry; один auth401 relogin; own global token keys; Core company/org headers здесь не контракт | transport exception retries max3; HTTP/RPC ошибки у login/authPost; AbortSignal.timeout(30000); без caller cancellation |
| voice-dev | dev-only voice issuer; адрес задаётся dev build, backend source не установлен; HTTP token JSON; production branch issuer через shared Core get | dev issuer без Core Bearer; cid query; итог aud=voice contract; createVoiceAuth issue + operationGeneration explicit reset guard уже принят | VoiceError dev_token; cache generation; issuer errors fenced; dev fetch без signal; operation generation запрещает поздний результат |
| voice-http | ContactHub voice node; Core только aud=voice issuer; HTTP JSON/multipart/ETag/blob в узел через voice proxy; node source вне этого pin | короткий aud=voice Bearer, company привязан к issue; один node401 refresh/retry; captureVoiceContext через dispatch/error/body/download; explicit reset fence уже принят; не Core logout | VoiceError/problem issues, 412 и accepted health503; не ApiError Core; ordinary request без caller signal; explicit reset блокирует continuation, уже отправленное не отзывает |
| voice-sse | ContactHub voice node /now/stream; fetch GET event-stream; не EventSource constructor из-за Authorization | aud=voice Bearer; один node401 refresh; explicit reset aborts registered streams; guard token/read/callback/reconnect уже принят | VoiceError, nonretry401/403/429; controlled reconnect; stop function + AbortController + reader cancel/release |
| partner-auditor-stream | Ledger partner auditorService; backend route /stream не найден в pin; same-origin POST /api/auditor/stream SSE; другой сервис чем /auditor/api | Content-Type только; ни Bearer, ни company headers; isApiEnabled branch; UI source callers найдены, runtime/deploy неизвестны | callback error/status; parser собственный; Core logout нет; возвращает AbortController, signal передан fetch |
| auditor-health | ecosystem-deploy services/auditor health; same-origin HTTP JSON health | без Bearer/company; public readiness contract; readiness не tenant business data | Error при HTTP/MIME; network/JSON errors propagate; signal отсутствует |

Core JSON, Core multipart, Core binary, Voice aud=voice, Auditor proxy, partner Auditor SSE, external STS/MSTO/TradeCorp и static assets остаются разными границами. Отсутствие общего Core error handler у чужого протокола само по себе не дефект.

## Решение для каждой actual native записи

`keep`: сохранить текущий протокол. `extract`: предложение общего adapter **внутри текущего владельца**, требующее отдельного root решения и воспроизведения перед любым runtime edit. `defer`: сначала доказать используемость/маршрут. `replace` не выбран: source-only review не обосновал безопасную прямую замену на Core JSON.

| ID / unique key | Функция и используемость | Boundary / решение | Caller refs и основание |
|---|---|---|---|
| N01 `src/components/auditor/AuditorTerminal.tsx:222:18:WebSocket` | AuditorTerminal effect; source-reachable | auditor-ws / **keep** | terminal-caller; PTY auth frame/close/reconnect требуют собственного WS adapter |
| N02 `src/components/map/MapLayers.tsx:66:5:fetch` | RegionsLayer effect; source-reachable | static / **keep** | map-caller; поставка GeoJSON, alive guard; это asset |
| N03 `src/hooks/useChatWs.ts:73:18:WebSocket` | useChatWs connect; source-reachable | chat-ws / **keep** | chat-caller, chat-ui; WS subscribe protocol нельзя заменить JSON request |
| N04 `src/lib/appUpdate.ts:25:21:fetch` | fetchVersion; source-reachable | static / **keep** | update-caller; version.json no-store + stopped guard |
| N05 `src/lib/reportClientError.ts:51:3:fetch` | reportClientError; source-reachable | error-telemetry / **keep** | error-caller; best-effort telemetry keepalive, рекурсивный error UI не нужен |
| N06 `src/public/main.tsx:62:5:fetch` | ToApp effect; source-reachable | gate-cookie / **keep** | public-router; cookie bootstrap перед reload основной сборки |
| N07 `src/services/apiClient.ts:298:21:fetch` | get; shared-implementation | core-json / **keep** | get-caller; общая реализация, не обход общего транспорта |
| N08 `src/services/apiClient.ts:306:21:fetch` | post; shared-implementation | core-json / **keep** | post-caller; общая реализация |
| N09 `src/services/apiClient.ts:318:21:fetch` | patch; shared-implementation | core-json / **keep** | patch-caller; общая реализация |
| N10 `src/services/apiClient.ts:330:21:fetch` | put; shared-implementation | core-json / **keep** | put-caller; общая реализация |
| N11 `src/services/apiClient.ts:342:21:fetch` | del; shared-implementation | core-json / **keep** | del-caller; общая реализация |
| N12 `src/services/apiClient.ts:366:23:fetch` | upload fetch branch; shared-implementation | core-upload / **keep** | upload-caller; intake include сохранён уже принятым пакетом |
| N13 `src/services/apiClient.ts:375:17:XMLHttpRequest` | upload XHR constructor; shared-implementation | core-upload / **keep** | xhr-caller; один объект progress upload; связан с N14, не отдельная отправка |
| N14 `src/services/apiClient.ts:376:5:XMLHttpRequest.open` | upload XHR open; shared-implementation | core-upload / **keep** | xhr-caller; инициализация того же XHR N13; send на строке394 |
| N15 `src/services/apiClient.ts:414:21:fetch` | fetchBinary; shared-implementation | core-binary / **keep** | binary-local-callers, binary-local-blob, binary-caller, binary-file-caller; binary fencing/cleanup уже приняты; повторного исправления нет |
| N16 `src/services/auditorService.ts:79:5:fetch` | streamAudit; source-callers-route-unmatched | partner-auditor-stream / **defer** | partner-caller; две source calls; /api/auditor/stream отсутствует в backend pin; нет deployment proof, не active production defect |
| N17 `src/services/authService.ts:128:8:fetch` | logout; source-reachable | gate-cookie / **keep** | auth-logout-caller; cookie logout после local clearToken; общий JSON client изменит границу |
| N18 `src/services/chargeExport.ts:23:16:fetch` | loadPdfFonts; source-reachable | static / **keep** | font-caller, font-ui; локальный font dictionary text/JSON без исполнения JS, promise очищается при ошибке |
| N19 `src/services/confService.ts:143:10:fetch` | следитьЗаВкладкой/выйти; source-reachable | conf-presence / **extract** | conf-caller, conf-ui; кандидат отдельного lifetime adapter после root решения и воспроизведения; keepalive сохранить |
| N20 `src/services/developerDocsService.ts:50:26:fetch` | docsRequest; source-reachable | docs-oauth / **keep** | docs-caller, docs-callback; session cookie/CSRF auth отделён от Core JSON |
| N21 `src/services/developerDocsService.ts:78:9:fetch` | revoke; source-reachable | docs-oauth / **keep** | docs-revoke-caller; OAuth form + credentials omit без Core logout |
| N22 `src/services/developerDocsService.ts:100:28:fetch` | finishDocsLogin token exchange; source-reachable | docs-oauth / **keep** | docs-callback; PKCE transaction и generation cleanup сохранять |
| N23 `src/services/fuel/stsApiClient.ts:59:26:fetch` | STS fetchWithRetry; source-reachable | external-sts / **keep** | sts-local, sts-sync, sts-ui; vendor timeout/retry/auth не Core transport |
| N24 `src/services/msto/mstoApiClient.ts:79:20:fetch` | MSTO fetchWithRetry; source-reachable | external-msto / **keep** | msto-local, msto-sync; vendor timeout/retry/auth не Core transport |
| N25 `src/services/spaceAuditorService.ts:90:21:fetch` | getHealth; source-reachable | auditor-health / **keep** | health-caller; health boolean readiness probe без user headers |
| N26 `src/services/spaceAuditorService.ts:142:21:fetch` | uploadFile; source-reachable | auditor-proxy-json / **extract** | file-caller; общий adapter внутри Auditor owner; не Core upload migration |
| N27 `src/services/spaceAuditorService.ts:197:21:fetch` | readJson/getMethods/getGrowth; source-reachable | auditor-proxy-json / **extract** | methods-caller, growth-caller; единый Auditor parser/header policy имеет смысл внутри proxy boundary |
| N28 `src/services/spaceAuditorService.ts:212:21:fetch` | getKnowledge; source-reachable | auditor-proxy-json / **extract** | knowledge-caller; сохранить MIME guard и company header в Auditor adapter |
| N29 `src/services/spaceAuditorService.ts:227:21:fetch` | exportWork; source-reachable | auditor-proxy-binary / **extract** | export-work-caller; runtime candidate: lifetime/blob cleanup в Auditor owner; Core binary API не переносить вслепую |
| N30 `src/services/spaceAuditorService.ts:257:21:fetch` | act; source-reachable | auditor-proxy-json / **extract** | act-caller; явное подтверждение действия + company/Bearer, без самовольного повторения |
| N31 `src/services/spaceAuditorService.ts:268:21:fetch` | getSessions; source-reachable | auditor-proxy-json / **extract** | sessions-caller; сохранить осознанный [] fallback отдельно от ошибки auth |
| N32 `src/services/spaceAuditorService.ts:285:21:fetch` | getPrompts; source-reachable | auditor-proxy-json / **extract** | prompts-caller; сохранить [] fallback; source race без reproduction не дефект |
| N33 `src/services/spaceAuditorService.ts:292:21:fetch` | deleteAgentFile; source-reachable | auditor-proxy-json / **extract** | delete-caller; Auditor API JSON/status boundary |
| N34 `src/services/spaceAuditorService.ts:310:21:fetch` | uploadKnowledge; source-reachable | auditor-proxy-json / **extract** | upload-knowledge-caller; Auditor multipart, не storage Core |
| N35 `src/services/spaceAuditorService.ts:324:21:fetch` | saveAgentFile; source-reachable | auditor-proxy-json / **extract** | save-caller; Auditor JSON mutation, не Core settings endpoint |
| N36 `src/services/spaceAuditorService.ts:343:21:fetch` | reloadAgent; no-static-caller | auditor-proxy-json / **defer** | статический caller не найден; definition-only: нет статического caller; без headers при server auth guard лишь source mismatch, не active defect |
| N37 `src/services/spaceAuditorService.ts:355:21:fetch` | dictate; source-reachable | auditor-proxy-json / **extract** | dictate-caller, dictate-dispatch; ASR multipart, свои 502/503 messages; отдельный Auditor auth |
| N38 `src/services/spaceAuditorService.ts:373:21:fetch` | getSkills; source-reachable | auditor-proxy-json / **extract** | skills-caller; Auditor-specific MIME guard при отсутствующем профиле |
| N39 `src/services/spaceAuditorService.ts:418:3:fetch` | ask; source-reachable | auditor-proxy-sse / **keep** | ask-caller; SSE callbacks/controller принадлежат stream adapter |
| N40 `src/services/tradecorp/tradecorpApiClient.ts:81:20:fetch` | TradeCorp fetchWithRetry; source-reachable | external-tradecorp / **keep** | tradecorp-local, tradecorp-sync; vendor timeout/retry/auth не Core transport |
| N41 `src/services/voiceService.ts:26:23:fetch` | выпустить/dev branch; dev-only-conditional | voice-dev / **keep** | voice-issue-binding, voice-issue-caller; import.meta.env.DEV guard; production issue через Core shared get |
| N42 `src/services/voiceService.ts:185:39:fetch` | отправить; source-reachable | voice-http / **keep** | voice-http-caller, voice-caller; aud=voice HTTP+body/reset guard уже принят |
| N43 `src/services/voiceService.ts:390:23:fetch` | nowStream/раз; source-reachable | voice-sse / **keep** | voice-caller; SSE explicit reset boundary уже принят |

Решения: **defer: 2**, **extract: 13**, **keep: 28**. Всего 43 уникальных ключа; каждый имеет собственный source span, используемость, caller refs либо явный unknown, inherited owner/protocol/auth/context/error/abort и основание решения.

`N16` имеет два caller в partner AuditorPage, но в backend pin `auditor_router` нет `/stream`; широкая проверка `server/app` также не нашла этот путь. Это источник для уточнения backend/source owner и продуктовой актуальности, не подтверждённый production отказ. `N36 reloadAgent` имеет только определение, без статических callers; отсутствие заголовков при auth-protected backend не заявляется действующим production дефектом.

## Сопоставление с принятыми пакетами

- **Voice reset guard присутствует**: operationGeneration, resetVoiceAuth, token/HTTP/body/SSE guards в `voice-context`, N41–N43. Сохраняются aud=voice, одноразовый node401 refresh и отсутствие Core logout. Старые reset races не переносятся в backlog повторно; граница касается явного reset и не отменяет server effect.
- **Intake upload присутствует**: uploadIntake вызывает общий upload с include (`upload-caller`); отдельного native callsite в intakeDocsService нет. N12–N14 — implementation, а не повтор обхода. Success context fencing upload не входил в принятый контракт и не объявляется новым validated defect.
- **Core binary присутствует**: N15 = fetchBinary; generation/header guards, signal, общий error parsing, filename fallback/finally cleanup в apiClient. Уже исправленные binary reset/error/filename проблемы не повторяются. Проверка реального download manager здесь не проводилась.

Ссылки на исторические результаты: [Voice](VOICE_CONTEXT_BOUNDARY_20261030.md), [Intake](INTAKE_UPLOAD_TRANSPORT_20261030.md), [Core binary](CORE_BINARY_TRANSPORT_20261030.md). Их прежние тестовые счётчики не выдаются за новые прогоны этого review.

## Только два кандидата для следующего root решения

1. **R1 / N29 — Auditor exportWork**. Caller: AuditorPage export button (`export-work-caller`). После await blob нет guard перед созданием URL/click; cleanup не finally. Нужен отдельный actual-service synthetic reset/abort и failure-cleanup reproduction. Владелец следующего шага: Auditor proxy frontend owner. Простая замена на Core binary смешает endpoint/error/auth boundary; без отдельного решения её не выполнять.
2. **R2 / N19 — conference presence leave**. joinMeeting/start flow создаёт timer/pagehide closure со старым session/company, а leave читает текущий Bearer. Backend при этом проверяет компанию сессии/членство и пишет presence текущего пользователя (`backend-conf`), поэтому из исходника нельзя выводить чужую мутацию. Следующему Core conference owner нужен отдельный synthetic delayed callback/reset reproduction и проверка disposal.

Оба пункта — **source suspicion, не validated vulnerability**. Новых тестов или исправлений для них не создавали; runtime ownership передаётся root, не присваивается этим отчётом. Остальные source debts и unknown не расширяют этот список кандидатов.

## Проверка и ограничения

PASS: offline inventory repeated deterministically; 1147/1147 immutable Git blob bytes; 43/43 native AST spans/expression SHA; unique keys/decisions/refs и JSON→MD agreement; selected immutable snippets hashes; `git diff --check`. Runtime tests, npm typecheck/build/install, SQL/DB/connect, реальные env, API/браузер/SSH и deployment: SKIP по прямому ограничению задачи. Git push своей ветки отдельно разрешён.

Проверка охватывает актуальные source records генератора, а не скрытые вызовы third-party libraries, динамический dispatch, выпущенные bundle, конфигурацию reverse proxy, real-cookie/CORS и server acceptance. Наличие frontend caller не доказывает активность функции в текущем стеке. Программа M00–M19 остаётся незавершённой; любые PR только draft, merge/deploy запрещены.

## Immutable source refs

JSON содержит точные revision/path/startLine/endLine и SHA-256 **выбранного snippet** для каждой ссылки ниже. Полные snippets доступны только в private evidence. Все Ledger ссылки относятся к одному pin; строки проверены по Git object, а не по текущему master.

- **N01**: [clearledger/src/components/auditor/AuditorTerminal.tsx:222](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorTerminal.tsx#L222)
- **N02**: [clearledger/src/components/map/MapLayers.tsx:66](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/map/MapLayers.tsx#L66)
- **N03**: [clearledger/src/hooks/useChatWs.ts:73](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/hooks/useChatWs.ts#L73)
- **N04**: [clearledger/src/lib/appUpdate.ts:25](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/lib/appUpdate.ts#L25)
- **N05**: [clearledger/src/lib/reportClientError.ts:51–59](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/lib/reportClientError.ts#L51)
- **N06**: [clearledger/src/public/main.tsx:62](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/public/main.tsx#L62)
- **N07**: [clearledger/src/services/apiClient.ts:298](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L298)
- **N08**: [clearledger/src/services/apiClient.ts:306–310](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L306)
- **N09**: [clearledger/src/services/apiClient.ts:318–322](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L318)
- **N10**: [clearledger/src/services/apiClient.ts:330–334](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L330)
- **N11**: [clearledger/src/services/apiClient.ts:342–345](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L342)
- **N12**: [clearledger/src/services/apiClient.ts:366–371](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L366)
- **N13**: [clearledger/src/services/apiClient.ts:375](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L375)
- **N14**: [clearledger/src/services/apiClient.ts:376](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L376)
- **N15**: [clearledger/src/services/apiClient.ts:414](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L414)
- **N16**: [clearledger/src/services/auditorService.ts:79–84](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/auditorService.ts#L79)
- **N17**: [clearledger/src/services/authService.ts:128](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/authService.ts#L128)
- **N18**: [clearledger/src/services/chargeExport.ts:23](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/chargeExport.ts#L23)
- **N19**: [clearledger/src/services/confService.ts:143–146](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/confService.ts#L143)
- **N20**: [clearledger/src/services/developerDocsService.ts:50](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/developerDocsService.ts#L50)
- **N21**: [clearledger/src/services/developerDocsService.ts:78–79](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/developerDocsService.ts#L78)
- **N22**: [clearledger/src/services/developerDocsService.ts:100–102](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/developerDocsService.ts#L100)
- **N23**: [clearledger/src/services/fuel/stsApiClient.ts:59](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/fuel/stsApiClient.ts#L59)
- **N24**: [clearledger/src/services/msto/mstoApiClient.ts:79](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/msto/mstoApiClient.ts#L79)
- **N25**: [clearledger/src/services/spaceAuditorService.ts:90](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L90)
- **N26**: [clearledger/src/services/spaceAuditorService.ts:142–146](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L142)
- **N27**: [clearledger/src/services/spaceAuditorService.ts:197](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L197)
- **N28**: [clearledger/src/services/spaceAuditorService.ts:212](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L212)
- **N29**: [clearledger/src/services/spaceAuditorService.ts:227–229](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L227)
- **N30**: [clearledger/src/services/spaceAuditorService.ts:257–261](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L257)
- **N31**: [clearledger/src/services/spaceAuditorService.ts:268](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L268)
- **N32**: [clearledger/src/services/spaceAuditorService.ts:285](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L285)
- **N33**: [clearledger/src/services/spaceAuditorService.ts:292–295](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L292)
- **N34**: [clearledger/src/services/spaceAuditorService.ts:310–314](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L310)
- **N35**: [clearledger/src/services/spaceAuditorService.ts:324–332](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L324)
- **N36**: [clearledger/src/services/spaceAuditorService.ts:343](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L343)
- **N37**: [clearledger/src/services/spaceAuditorService.ts:355–359](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L355)
- **N38**: [clearledger/src/services/spaceAuditorService.ts:373](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L373)
- **N39**: [clearledger/src/services/spaceAuditorService.ts:418–427](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L418)
- **N40**: [clearledger/src/services/tradecorp/tradecorpApiClient.ts:81](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/tradecorp/tradecorpApiClient.ts#L81)
- **N41**: [clearledger/src/services/voiceService.ts:26](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L26)
- **N42**: [clearledger/src/services/voiceService.ts:185–188](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L185)
- **N43**: [clearledger/src/services/voiceService.ts:390–393](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L390)
- **terminal-caller**: [clearledger/src/pages/AuditorPage.tsx:152](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L152)
- **map-caller**: [clearledger/src/components/map/MapLayers.tsx:107](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/map/MapLayers.tsx#L107)
- **chat-caller**: [clearledger/src/contexts/SupportContext.tsx:170](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/contexts/SupportContext.tsx#L170)
- **chat-ui**: [clearledger/src/components/chat/ChatPanel.tsx:2390](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/chat/ChatPanel.tsx#L2390)
- **update-caller**: [clearledger/src/components/common/MobileShell.tsx:71](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/common/MobileShell.tsx#L71)
- **error-caller**: [clearledger/src/components/common/ErrorBoundary.tsx:28](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/common/ErrorBoundary.tsx#L28)
- **public-router**: [clearledger/src/public/main.tsx:55](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/public/main.tsx#L55)
- **get-caller**: [clearledger/src/services/authService.ts:115–116](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/authService.ts#L115)
- **post-caller**: [clearledger/src/services/authService.ts:86–89](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/authService.ts#L86)
- **patch-caller**: [clearledger/src/services/tasksService.ts:433](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/tasksService.ts#L433)
- **put-caller**: [clearledger/src/services/docsService.ts:444](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/docsService.ts#L444)
- **del-caller**: [clearledger/src/services/chatService.ts:389](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/chatService.ts#L389)
- **upload-caller**: [clearledger/src/services/intakeDocsService.ts:58](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/intakeDocsService.ts#L58)
- **xhr-caller**: [clearledger/src/services/chatService.ts:435](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/chatService.ts#L435)
- **binary-caller**: [clearledger/src/services/confService.ts:274](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/confService.ts#L274)
- **binary-file-caller**: [clearledger/src/services/sitesService.ts:1021](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/sitesService.ts#L1021)
- **binary-local-callers**: [clearledger/src/services/apiClient.ts:107–109](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L107)
- **binary-local-blob**: [clearledger/src/services/apiClient.ts:424–427](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L424)
- **partner-caller**: [clearledger/src/pages/partner/AuditorPage.tsx:165](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/partner/AuditorPage.tsx#L165)
- **auth-logout-caller**: [clearledger/src/contexts/AuthContext.tsx:130](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/contexts/AuthContext.tsx#L130)
- **font-caller**: [clearledger/src/services/chargeExport.ts:234–238](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/chargeExport.ts#L234)
- **font-ui**: [clearledger/src/components/workspace/analytics/ExportButton.tsx:10](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/workspace/analytics/ExportButton.tsx#L10)
- **conf-caller**: [clearledger/src/services/confService.ts:176](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/confService.ts#L176)
- **conf-ui**: [clearledger/src/pages/conf/parts.tsx:106](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/conf/parts.tsx#L106)
- **docs-caller**: [clearledger/src/pages/DeveloperApiPage.tsx:31](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/DeveloperApiPage.tsx#L31)
- **docs-callback**: [clearledger/src/public/DocsCallbackPage.tsx:20](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/public/DocsCallbackPage.tsx#L20)
- **docs-revoke-caller**: [clearledger/src/services/developerDocsService.ts:136–138](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/developerDocsService.ts#L136)
- **sts-local**: [clearledger/src/services/fuel/stsApiClient.ts:78](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/fuel/stsApiClient.ts#L78)
- **sts-ui**: [clearledger/src/pages/SourcesPage.tsx:24](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/SourcesPage.tsx#L24)
- **sts-sync**: [clearledger/src/services/channelSyncService.ts:97](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/channelSyncService.ts#L97)
- **msto-local**: [clearledger/src/services/msto/mstoApiClient.ts:92](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/msto/mstoApiClient.ts#L92)
- **msto-sync**: [clearledger/src/services/channelSyncService.ts:200](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/channelSyncService.ts#L200)
- **tradecorp-local**: [clearledger/src/services/tradecorp/tradecorpApiClient.ts:94](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/tradecorp/tradecorpApiClient.ts#L94)
- **tradecorp-sync**: [clearledger/src/services/channelSyncService.ts:297](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/channelSyncService.ts#L297)
- **external-ui**: [clearledger/src/pages/ChannelDetailPage.tsx:2268](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/ChannelDetailPage.tsx#L2268)
- **methods-caller**: [clearledger/src/pages/AuditorPage.tsx:327](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L327)
- **growth-caller**: [clearledger/src/pages/AuditorPage.tsx:510](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L510)
- **knowledge-caller**: [clearledger/src/pages/AuditorPage.tsx:463](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L463)
- **export-work-caller**: [clearledger/src/pages/AuditorPage.tsx:374](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L374)
- **act-caller**: [clearledger/src/components/auditor/AuditorPanel.tsx:130](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorPanel.tsx#L130)
- **sessions-caller**: [clearledger/src/components/auditor/AuditorTerminal.tsx:85](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorTerminal.tsx#L85)
- **prompts-caller**: [clearledger/src/components/auditor/AuditorPanel.tsx:201](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorPanel.tsx#L201)
- **delete-caller**: [clearledger/src/pages/AuditorPage.tsx:612](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L612)
- **upload-knowledge-caller**: [clearledger/src/pages/AuditorPage.tsx:674](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L674)
- **save-caller**: [clearledger/src/pages/AuditorPage.tsx:281](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L281)
- **dictate-caller**: [clearledger/src/components/auditor/DictateButton.tsx:26](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/DictateButton.tsx#L26)
- **dictate-dispatch**: [clearledger/src/components/auditor/DictateButton.tsx:48](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/DictateButton.tsx#L48)
- **skills-caller**: [clearledger/src/pages/AuditorPage.tsx:163](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/AuditorPage.tsx#L163)
- **ask-caller**: [clearledger/src/components/auditor/AuditorPanel.tsx:259](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorPanel.tsx#L259)
- **file-caller**: [clearledger/src/components/auditor/AuditorPanel.tsx:231](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorPanel.tsx#L231)
- **voice-caller**: [clearledger/src/pages/voice/VoiceNowPage.tsx:59](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/pages/voice/VoiceNowPage.tsx#L59)
- **voice-http-caller**: [clearledger/src/services/voiceService.ts:362](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L362)
- **voice-issue-caller**: [clearledger/src/services/voiceService.ts:86](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L86)
- **voice-issue-binding**: [clearledger/src/services/voiceService.ts:43](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L43)
- **voice-context**: [clearledger/src/services/voiceService.ts:43–86](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/voiceService.ts#L43)
- **core-headers**: [clearledger/src/services/apiClient.ts:272–280](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L272)
- **core-errors**: [clearledger/src/services/apiClient.ts:196–268](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L196)
- **core-guard**: [clearledger/src/services/apiClient.ts:399–422](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/apiClient.ts#L399)
- **auditor-headers**: [clearledger/src/services/spaceAuditorService.ts:125–128](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/spaceAuditorService.ts#L125)
- **docs-guard**: [clearledger/src/services/developerDocsService.ts:85–127](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/services/developerDocsService.ts#L85)
- **backend-gate**: [clearledger/server/app/routers/auth_router.py:558–585](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/auth_router.py#L558)
- **backend-chat**: [clearledger/server/app/routers/chat_router.py:3295–3338](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/chat_router.py#L3295)
- **backend-conf**: [clearledger/server/app/routers/conf_router.py:737–756](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/conf_router.py#L737)
- **backend-error**: [clearledger/server/app/routers/client_errors_router.py:82–105](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/client_errors_router.py#L82)
- **backend-docs**: [clearledger/server/app/routers/docs_portal_router.py:47–103](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/docs_portal_router.py#L47)
- **backend-oauth**: [clearledger/server/app/routers/partner_oauth_router.py:131–153](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/partner_oauth_router.py#L131)
- **backend-partner-auditor**: [clearledger/server/app/routers/auditor_router.py:33–34](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/auditor_router.py#L33)
- **backend-voice-issuer**: [clearledger/server/app/routers/sso_router.py:327–350](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/sso_router.py#L327)
- **backend-intake**: [clearledger/server/app/routers/intake_docs_router.py:1–15](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/server/app/routers/intake_docs_router.py#L1)
- **auditor-backend**: `ecosystem-deploy@ec22e16483b3a980cc85905ae647377cdd03a230:services/auditor/server.js:2129–2201`
- **auditor-health-backend**: `ecosystem-deploy@ec22e16483b3a980cc85905ae647377cdd03a230:services/auditor/server.js:2115–2127`
- **build-version**: [clearledger/vite.config.ts:29–43](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/vite.config.ts#L29)
- **auditor-ws-backend**: `ecosystem-deploy@ec22e16483b3a980cc85905ae647377cdd03a230:services/auditor/server.js:2222`
- **health-caller**: [clearledger/src/components/auditor/AuditorTerminal.tsx:89](https://github.com/Electro-Interfaces/ClearLedger/blob/62bd4a4604028309ea17100ee8c320818d9c2400/clearledger/src/components/auditor/AuditorTerminal.tsx#L89)
