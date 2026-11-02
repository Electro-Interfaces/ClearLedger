# Auditor: проект границы native composition/bootstrap

31.10.2026. M01/M13. **SOURCE_DESIGN_PENDING_ROOT_REVIEW**.
В этом пакете изменяются только этот Markdown и соседний
[JSON](AUDITOR_COMPOSITION_DESIGN_20261031.json). Production changes: **0**.
Worker не исполнял Node, приложения, тесты, SQL, HTTP/WS, PTY, CLI Auditor,
контейнеры, installers или jobs. Все проверки ниже имеют статус
**PROSPECTIVE_NOTRUN**; это дизайн, не actual capture или execution approval.

## Замороженный предмет исследования

Ledger pin: `0c38469ffcdf2d901a4261e26acbd473ac1de620`.
Deploy pin: `48c84d81c061424578c10e238d3a81f22d68fa44`.
Чтение Deploy выполнялось из immutable Git blobs, без правки его рабочего дерева
и чужих `__pycache__`. Старые branches и ignored evidence сохранены.

JSON содержит полный selected manifest: **41 файл, 1 211 954 bytes**, с Git blob
SHA1, полным SHA256, репозиторием и pin. SHA256 canonical manifest:
`ce35b2bab9b5783dc9953f6a00bc98253ba5769dfd5402c7c2a0ce19ed92522d`.
Это выбранные исходники и канон, не весь Deploy и не installed dependency graph.
Замыкание локальных JS imports Auditor состоит из **пяти модулей, 215 546 bytes**:
server, skills, actions, shrink, workshop. Внешние imports — `node-pty`, `ws`;
их фактическое dependency/native замыкание пока UNKNOWN.

Главный файл `services/auditor/server.js`: 175 704 bytes, SHA256
`a51ba3cd14d5ee220c0e4a01cd863ce4f1aaeb5663f0905ad8e92d7083b7e578`.
Все source coordinates, SHA256 диапазонов и буквальные dispatcher blocks записаны
в JSON. Это проверяемые source ranges, не результат JS AST/runtime introspection.

ROOT firstpass:
`.artifacts/root-auditor-entry-source-review-20261031/source-review.json` в ROOT
Ledger worktree `/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029`:
2875 bytes, SHA256 `7be31828d37fc3424975850210bfd06bb1a1276f3630e712a7b31009835f60d9`.
Независимо перечитаны Git bytes шести перечисленных там файлов. Они равны текущему
Deploy pin, firstpass revision `65e21e7a27ee61050d0790004f5d518720c1db7c` и historical
`03450b4d96f8ef631198a0ee9a0bb11a5e6530b8`.
Уточнение диапазона: firstpass SHA256
`80799edeb6bfd04dfd918d19490fb2adce14decc7f3dc12358d2b3b86102bbac`
соответствует **2112–2221 включительно**; конструктор WS на 2222 в него не входит.

## Что существует в исходнике

`server.js:20–31` импортирует native `node:http`, child_process, fs, path, os,
crypto, затем `node-pty`, `ws` и четыре локальных модуля. Это **не Express**.
`createServer(async(req,res)=>...)` на 2112 хранит один настоящий условный callback.
Из него нельзя получить Express/router stack или честный список actual routes
путём перечисления registrations. Исторические 16 native candidates и две manual
rows общего COMPOSED 2491 остаются source evidence, а не actual composition.

Перед `try` на 2113 выполняется `new URL(req.url,'http://x')`. Ошибка этого шага не
попадает в catch 2210. Внешнее поведение rejection async callback нативным сервером
не проверялось. Положение try нельзя менять попутно с extraction.

Ниже приведены **16 terminal exact-path source families** в исходном порядке.
Номер ID относится к source/design, не к finding, operationId или публикации API.
Полный порядок JSON включает также parse, общий gate, redirect, fallthrough и catch:
всего **21 dispatcher step**, ни один не помечен actual.

| ID / строка | Predicate метода / path | Ответ / действие по исходнику |
|---|---|---|
| H01 / 2115 | метод не проверяется, `/health` | JSON 200; состояние CLI/credentials/flags/catalog; ASR probe/cache |
| H02 / 2139 | GET `/api/skills` | JSON 200, четыре поля каталога; общий gate |
| H03 / 2144 | GET `/api/methods` | JSON 200, FS methods; общий gate |
| H04 / 2145 | GET `/api/knowledge` | JSON 200, company/person FS scope; общий gate |
| H05 / 2161 | GET `/api/sessions` | JSON 200, tmux list-sessions и четыре вкладки пользователя; общий gate |
| H06 / 2180 | GET `/api/export-work` | Отдельный can_manage gate; tar, gzip attachment; 401/403/404/500/503 |
| H07 / 2181 | GET `/api/prompts` | JSON 200, scoped prompt files; общий gate |
| H08 / 2184 | POST `/api/knowledge/upload` | can_manage, multipart, optional markitdown, FS/Git; 200 или 400/401/403/503 |
| H09 / 2185 | DELETE `/api/agent-file` | can_manage, query path + companyFile; Git rm/commit; 200 или 400/401/403/404/503 |
| H10 / 2186 | GET `/api/growth` | JSON 200, git log; общий gate |
| H11 / 2187 | PUT `/api/agent-file` | Своя user card или can_manage; path regex, JSON text, FS/Git/audit/cache |
| H12 / 2188 | POST `/api/reload` | Bearer/can_manage; cache/seed/profile/MCP/normative jobs; 200 или 401/403/503 |
| H13 / 2198 | POST `/api/upload` | Bearer/company-format/auth-me, multipart/extension, session FS; 200 или 400/401/415 |
| H14 / 2199 | POST `/api/dictate` | Bearer/auth-me, multipart, ASR; 200 или 400/401/502/503 |
| H15 / 2200 | POST `/api/act` | UUID company + cfg.ok + action allowlist; Core response/status forwarding |
| H16 / 2201 | POST `/api/ask` | JSON admission errors, затем SSE 200; CLI/Core skills/runs/person memory |

Общий nonterminal gate **G01, 2129–2137** стоит после health и до H02. Он действует
только на GET array `[skills,methods,knowledge,prompts,growth,sessions]` с полными
`/api/` paths: Bearer отсутствует → 401; Core down → 503; `!gCfg.ok` → 403;
успех присваивает `req.agentCfg` и продолжает настоящий callback. Комментарии
2142–2152 о публичном чтении не отменяют этот gate. Они не являются ACL contract.

На 2205 unmatched GET с `!pathname.startsWith('/api')` получает **302 Location
APP_PATH**, default `/ClearLedger/auditor`. Это prefix predicate, не регулярное
выражение и не finite endpoint. GET `/ws/terminal` без Upgrade также попадает
в этот HTTP fallback по исходнику. GET `/apiUnknown` остаётся в API prefix и
получает 404. На 2209 остальным пишется JSON 404 `нет такого адреса`, не 405.
Catch 2210–2212 пишет JSON 500 `{error:e.message}` только до `headersSent`.

`/health` хранится как **symbolic unrestricted-after-native-parser**, без
expanded guessing списка HTTP methods. Одна будущая GET-проверка не докажет
GET-only. У остальных пятнадцати families метод проверяется буквально;
Express implied HEAD здесь нет. Wire body для HEAD, CONNECT/upgrade и ограничения
native HTTP parser остаются NOTRUN; не выводятся из `json(res,...)`.
RegExp matcher пути в самом dispatcher не найден: есть exact literals, GET array,
negative prefix и native URL parsing. Regex/динамика внутри payload/FS/catalog/WS
описаны отдельно и не превращены в придуманные native routes.

## Payload, ошибки и side effects handlers

Общий `json` на 1880–1883 ставит `application/json; charset=utf-8` и сериализует
объект. `readBody` 1874–1878 ограничивает **JS string length 1e6**, отвергает JSON
parse и destroy-ит запрос при превышении. Это не новый byte limit/413/422 profile:
исключения до отправки headers доходят до существующего catch 500.
Multipart parser 1542–1568 имеет byte limit, filename decoding и req.destroy;
контракт чтения/ошибок нельзя заменить parser framework.

`handleAsk` 1885–2048 проверяет Bearer, непустую company, наличие CLI и credentials
до body и `/api/auth/me`. После auth-me выставляет SSE headers 1915–1920, а
settings запрашивает уже внутри stream. `cfg.core_down` и `!cfg.ok` имеют разные
ветви. Сохраняются `data: JSON\n\n`, типы status/skills/text/findings/actions/run/error,
`data: [DONE]\n\n`, а также JSON ошибки до SSE и stream ошибки после headers.
Модель, вывод child stderr, CLI timeouts, saveRun и fire-and-forget rememberPerson
остаются настоящими handlers, не успешными mocks.

Source-only различия, которые **не исправляются**:

- Upload использует отдельную loose 36-character company regex и отображает
  неуспешный auth-me в 401; dictate без company отображает unreachable/5xx в 503.
- Act использует `safeCompany`, cfg.ok и `actions.js:98–123`: allowlisted params,
  валидацию path identifiers, company из header в query/body и тот же Authorization.
  Upstream status может быть динамическим `r.status`, не выдуманным finite enum.
- Save-file разрешает собственную карточку отдельно от can_manage; delete и
  knowledge-upload имеют свои правила. Ни соседние права, ни tenant validators
  не унифицируются этим refactor.
- UI `reloadAgent()` не задаёт Bearer, хотя source H12 его требует; exportWork()
  не задаёт X-Company-Id, а сервер вызывает settings с raw String header.
  Это наблюдения callsite/handler, не результаты HTTP-проверки.
- Client SSE abort/context guard отменяет reader/fetch. В server handleAsk нет
  привязки req close/aborted к child.kill; return функции kill внутри Promise
  executor callModel не доказывает propagation cancellation. Исправление этого
  поведения относится к отдельному решению ROOT, не к extraction.

`fetchSettings` 951–967 возвращает fallback ok=false; successful Core JSON
дополняется ok=true, 5xx/exception помечается core_down. Core endpoints settings,
runs/events/rating принадлежат **Core auditor_router.py**, а не native серверу.
Они используют get_current_user → assert_company_product → membership/module scope,
can_manage — superadmin/UserCompany role admin. Это source delegation, не доказанное
ACL conformance. Собственной service/machine identity для этих вызовов не добавляется.

## WS, PTY и lifecycle имеют разные границы

`new WebSocketServer({server:httpServer,path:'/ws/terminal'})` находится на 2222.
Это binding options. Метод/headers/origin/query matching при Upgrade определяется
фактической версией ws и пока UNKNOWN. Реальный handshake не выполнялся.

Listener `connection` 2265–2528 создаёт heartbeat **30 s до application auth**.
JSON parse failure игнорируется; pre-start строковый data buffer ограничен
64 элементами. Первое разрешающее сообщение — start: флаг WORKSHOP_ENABLED,
Bearer из msg.token, safeCompany, fetchSettings, core_down, workshopAllowed,
наличие engineBin. `workshopAllowed` — настоящий workshop.js: cfg.ok обязателен;
can_manage или all; users при наличии дополнительно сужает. Token остаётся
в первом сообщении, его нельзя переносить в URL или query.

Только затем cliEnv, audit-open, optional fresh kill и **настоящий** spawnPty
запускают tmux. Имя содержит первые восемь символов user_id и tab, clamp 0–3;
четыре вкладки, `new-session -A -D`. Сохраняются pending flush700ms, redraw500ms,
scroll/copy-mode, resize minimum20×5 и refresh120ms, raw PTY data → ws, error logs.
Exit проверяет tmux и закрывает с **4001 detached** либо **4002 ended**.
Close очищает heartbeat и убивает PTY-клиента, но оставляет tmux сеанс; guard45min
закрывает забытый сеанс позже. Комментарий 2216 про «процесс убит» не заменяет
этот конкретный lifecycle. DEBUG_INPUT может писать до120 символов ввода при
явном флаге; новая политика logging/redaction не вводится попутно.

Полная source timeline содержится в JSON AUD-BOOT01–12. Import-time effects
существуют **до хвоста**, а не только перед listen:

1. Native/WS/catalog ESM evaluation 20–31; KIT и maxRows захватываются также
   module-level expressions в skills/actions/shrink.
2. Config/constants; **seedWorkdir() на 392**: copy шаблонов/kit/external skills,
   FS, SSH-keygen, git init/add/commit, trust config. Ничего из этого не исполнялось.
3. **findBin на 497–498**: exists/`command -v` child.
4. **DELIVERY_PATHS на 1423–1433**: top-level exists/readdir snapshot после seed.
5. Native createServer2112; WSS2222; connection listener binding.
6. 2535–2542: ensureCredentials → ensureCodexAuth → writeCodexConfig →
   linkCodexAssets → markOnboarded → conditional writeMcpConfig.
7. Profile timeout3s, profile interval4h; normative timeout20s, затем interval24h.
8. listen2568 и logging callback с hasCredentials.

Profile worker читает Core через psql/Python, normative worker вызывает Python/curl
и сохраняет knowledge/Git. Это bootstrap/request-reload jobs, не composition.
Никакого SQL/CLI процесса/таймера ради inventory запускать нельзя.

## Callers, proxy и технические владельцы

По source manifest JSON и AUD-CALL01–14:

- Browser `spaceAuditorService.ts` обращается same-origin `/auditor/api/*`,
  Bearer пользователя и X-Company-Id там, где callsite их задаёт.
  Core settings/runs идут другим путём `/api/auditor/*` через apiClient.
- `AuditorPanel`, `AuditorPage`, `DictateButton` потребляют service; `AuditorTerminal`
  открывает `/auditor/ws/terminal`, start JSON и close4001 без автоподключения.
- Template nginx266–304: exact WS location с Upgrade/Connection/HTTP1.1,
  timeout86400s; exact health proxy; API prefix rewrite `/auditor` и SSE buffering/gzip
  off, timeout600s. Это reverse proxy **nginx**, не Core auth-proxy.
  Реальный ingress, forwarding и версии конфигов не проверялись.
- Native сервис передаёт тот же user Authorization в Core auth/settings/skills,
  actions, runs/events. Company — в query и, для actions, filtered body.
  Scope/permission enforcement остаётся у соответствующих Core endpoints.
- `auditorService.ts` и partner/AuditorPage — отдельный partner contour. Их имена
  и похожий `/api/auditor` prefix не доказывают потребление этого native сервиса.
- `scripts/auditor` и auditor-cli.sh — отдельный operator `docker exec` вход.
  Их доступ не доказывается HTTP gate, user-scoped WS session либо UI меню.

Технический владелец будущего extraction — отдельный Deploy исполнитель, которого
назначит ROOT. Core authorization/persistence, UI transport, nginx и CLI/worker
contracts остаются у своих текущих компонентов. Human/domain owner и external
publication decision всех source families — **UNKNOWN**. Навык/название/число
ветвей не назначает владельца ЭЗС, equipment, counterparties, contracts, documents
или accounts и не даёт допуска к внешнему API.

## Один минимальный предлагаемый пакет

**PROPOSED, production0**. После отдельного ROOT semantic/source review:

| Будущий production path | Конкретное изменение |
|---|---|
| services/auditor/server.js | Короткий entrypoint: настоящий bootstrap и прежний listen/defaults/CMD |
| services/auditor/auditor-runtime.js, NEW | Один bounded service closure factory с прежними helpers, настоящими requestHandler/onTerminalConnection, instance state и явными startup operations |
| services/auditor/Dockerfile | Только добавить новый module в существующий COPY151; зависимости/версии/CMD не менять |

`createAuditorRuntime({env,home,io,catalogs})` возвращает реальные callbacks и
явные операции существующего bootstrap, но при construction **не вызывает IO**.
Это не router registry и не transport framework. Большой набор существующих
lexical helpers переносится в одну service closure, вместо переписывания их
параметров и разбрасывания по новым абстракциям. Cache/maps принадлежат instance;
production создаёт один instance, как прежний один module instance.

`io` передаёт существующие fs/path/crypto/fetch/child/timer/clock/log primitives.
`catalogs` — реальные exports skills/actions/shrink/workshop, не fakeRouter или
придуманный успешный ответ. Production передаёт **live process.env object** для
сохранения поздних чтений, а probe — явный synthetic object. Home разрешается
bootstrap и передаётся как значение; композиция не ищет реальный HOME/CLI/credentials.
Catalog module env captures KIT/maxRows остаются в reviewed bootstrap и получают
то же окружение; каталоги и их assertions этим пакетом не меняются.

Native `node-pty` и ws загружаются динамически **только внутри production startup**,
в прежнем относительном порядке до seed/HTTP/WS/listen. Это lazy bootstrap boundary,
а не перенос отказа native addon на первый запрос. Production использует настоящий
синхронный spawnPty; pure composition не импортирует addon. Отсутствующий native
provider не заменяется успешным shim: его вызов в probe — tripwire failure,
который остаётся failure даже если приложение поймало исключение.

Entry явно вызывает прежние seed/discovery/snapshot в исходном порядке, затем
native createServer и real WSS с прежними options/listener, затем tail bootstrap,
jobs и listen. Предполагается перенос startup effects, а не их suppression в
production. Подтверждение отсутствия behavioral drift — отдельная приёмка;
дизайн не выдаёт пока недоказанную эквивалентность.

Не входят: исправление прав/tenant validators, client headers, cancellation,
протокола WS/SSE, ошибок/logging, jobs/outbox, dependency/CLI pins или schema.
Отдельно сохраняются URL-before-try, headersSent, async/await/return boundaries,
readBody/multipart limits, source defaults и fallthrough. Никакой fake registry
не заменяет настоящий условный callback.

## Что именно сможет проверить ROOT

Это **не runtime freeze**: будущих production module/probe/tests ещё нет, их SHA
и Auditor dependency graph неизвестны. Нельзя выполнить proposed argv сейчас.
Сначала ROOT review этого source design; затем отдельный implementation owner;
перед любым actual — новый полный source/deps/tool freeze и review.

Предложенные фазы и конкретные будущие ID находятся в JSON, **28 controls NOTRUN**:

1. **C0**: source/dependency/native/tool inventory и guard negative self-controls,
   без app. Полный manifest всех selected до/после source, tests/probe/launcher,
   package resolution/loader files, Node executable/flags/platform/ABI/native hashes.
   В services/auditor нет tracked lockfile; Docker копирует лишь package.json и
   делает npm install. Node `22-alpine`, Claude `latest`, semver ranges `node-pty ^1.0.0`
   и `ws ^8.18.0` не доказывают установленные версии. Support toolroot не использовать
   как доказательство Auditor deps. Installed/native/live provenance UNKNOWN до
   отдельного измерения ROOT, установки или сборки этим дизайном не поручены.
2. **C1**: под pre-import guards импортировать новый pure factory, передать explicit
   config/providers, получить настоящие callbacks. Допустимо отдельно разрешённое
   real native createServer binding без listen и real audited ws attachment.
   **Callbacks не исполняются**, IO/requests/connections запрещены. Доказательство —
   callable identity/binding/options и отсутствие side effects; это не actual
   регистрация 16 routes и не branch coverage. Source inventory остаётся source.
3. **C2**, только после нового конкретного ROOT review: bounded real native HTTP
   requests и real ws handshake в приватном namespace с exact owned socket/FD permits
   и списком допустимых timer sites. Selective synthetic Core/ASR responders могут
   проверять forwarding/ошибки; это не настоящая Core authorization/SQL conformance.
   Denied start не должен дойти до PTY. Реальный PTY/tmux/CLI — ещё отдельный native
   review; native-disabled/shim phase его не заменяет.

Группы фальсифицируемых ожиданий: C01–04 callable/binding без IO; N01–05 независимые
запреты process/network/timer/files/native и порча manifest; O01–03 source order,
defaults и bootstrap ownership; HC01–04 native methods/path/body/error profile;
A01–04 user/company/auth/proxy различия; S01–02 SSE/cancellation; W01–04 handshake,
admission и отдельная native граница; L01–02 lifecycle/jobs. Число 28 — количество
**проектных** IDs, не PASS/coverage. Tests должны иметь независимые explicit expected
observations, не golden, сгенерированный тем же exporter.

Для C1 proposed virtual argv (probe ещё не создан):

```text
/usr/bin/node --permission --no-addons
  --allow-fs-read=/work/source --allow-fs-read=/work/node_modules
  --allow-fs-read=/work/tools --allow-fs-write=/evidence
  /work/tools/auditor-composition-probe.mjs --phase=C1 --variant=accounting-claude-off
```

Только после отдельного freeze ROOT измеряет фактическую поддержку этих flags и
замыкает loader/system read paths. Четыре explicit synthetic profiles в JSON:
accounting/claude/off, space/codex/admin, space/claude/all+users,
accounting/codex/admin. Fresh env/HOME: `/home/synthetic`, no credentials/tokens/DB/
proxy vars; synthetic work/knowledge/uploads в private tmp. CORE_API/ASR_URL —
неразрешаемые `core.invalid`/`asr.invalid` строки; C1 не имеет разрешённого DNS
или «пустых DNS» substitutes. Port0 не означает разрешение listen.

Изоляция: собственные ephemeral user/mount/net/IPC/PID namespaces и chroot, readonly
selected source, **Auditor-owned** measured deps и exact system libs. Host HOME,
.env/keys/vault/proc и чужие artifacts не монтируются. Node builtin permissions
плюс независимые kernel process/network/native restrictions и JS tripwires до
imports. Запрещены spawn/exec/worker/addon, SQL/DNS/socket/listen и timers, в том
числе unref. Любой denied/caught attempt делает proof недействительным. Нет
blanket success-noop timers, global DNS monkeypatch или live receiver.

Provisional C1 caps: floor **8 GiB**; source-staging planning **64 MiB**, основанный
на selected source объёме 1.21 MB; CPU30 s/wall45 s/AS2 GiB/FD64, output4 MiB,
scratch16 MiB/2048 entries, один child app process без subprocess/worker/native
права. Это source planning, **не измерение Node/Auditor peak RSS**. ROOT должен
измерить точные deps/system/staging bytes и child peak до актуального запуска;
добавочный произвольный reserve5 GiB не вводится. C2 socket/timer/resource caps
потребуют нового review после конкретизации реального harness.

Cleanup ROOT: terminate/reap только собственного process group, закрыть только
свои FD/timers/sockets, проверить отсутствие PTY/session/jobs, удалить лишь named
owned scratch/evidence по решению ROOT. Host mounts/firewall/config не меняются.

## Решение, ожидаемое от ROOT

Проверить два source-design файла и manifest/callgraph/21-step branch order,
уточнить предложенные три future production paths и назначить implementation owner.
Commit этого документа не разрешает исполнение, установку dependencies, bootstrap
или release. Current task runtime остаётся **0**.

M01/M13 и общая программа всех 20M+11 активны: unified current Core/Support/Auditor
registry, external authorization, предметные owners, clients/full CI, pilot,
deprecation и production/native readiness остаются открытыми.
