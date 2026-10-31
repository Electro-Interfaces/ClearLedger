# M14-P1: граница внешних webhook-назначений

Статус: ROOT source review V2 и controlled actual завершены **172/172 PASS**.
Выпуска и включения новых возможностей на рабочих пространствах не было. База `18c4bff53151e8287315498549189c52099342d4`, ветка
`agent/api-webhook-delivery-boundary-20261031`. Это один поток M14, не завершение
M14, всего API, полного CI или выпуска. Security scan/finding IDs, severity и
эксплуатация не заявляются. Worker не импортировал app и не исполнял tests/SQL.

## Observed: что подтверждает source

`space_events_router._check_shape` прежде проверял http/https и netloc, а create
и PATCH сходились в `_check_target`. `_send` формировал compact UTF-8 bytes и
Standard Webhooks HMAC, затем использовал HTTPX AsyncClient. Ошибки sender
попадали в last_error через прежний outbox loop. Source snapshot содержит 61
прежний тест: 47 delivery/signature и 14 target-shape cases (число по AST).

HTTPX0.28.1 по умолчанию не следует redirects, но доверяет environment для proxy;
URL userinfo может превратиться в BasicAuth. Это свойства прочитанной библиотеки,
не утверждение о настроенном proxy или фактических маршрутах площадки.
[HTTPX environment docs](https://www.python-httpx.org/environment_variables/),
[versioned client source](https://github.com/encode/httpx/blob/0.28.1/httpx/_client.py).

HTTPcore передаёт origin hostname в network backend и отдельно в TLS;
AnyIO разрешает hostname при connect, а canonical numeric IP обрабатывает иначе.
[HTTPcore1.0.9 source](https://github.com/encode/httpcore/blob/1.0.9/httpcore/_async/connection.py),
[AnyIO4.15.1 source](https://github.com/agronholm/anyio/blob/4.15.1/src/anyio/_core/_sockets.py).
Mail-specific net_guard имеет override и fail-open DNS error, поэтому не является
владельцем новой webhook policy и не менялся. Internal app registry/company map/
SSO имеет отдельную authority и также не менялся.

## Inferred: инженерный вывод

Проверка имени до обычного POST не связывает разрешённое назначение с адресом
socket. Мы не доказали live reachability или exploit; наблюдаем разделённое
владение admission и connect. URL grant должен разрешать получателя события,
а не использовать сетевую власть backend к его соседям. Одного preflight DNS
при повторном hostname lookup недостаточно для выбранного invariant.

## Proposed → выбранный ROOT вариант

ROOT выбрал один domain helper `services/webhook_delivery.py` и публичный
HTTPcore AsyncConnectionPool(network_backend=...), без private HTTPX hooks.
[Public backend contract](https://www.encode.io/httpcore/network-backends/).
Generated design portfolio, JSON, source hashes, diagrams и implementation plan
сохранены через Codex Security MCP вне Git. Это derived analysis по source,
не canonical scan и не proof of remediation. Полный portfolio содержит честные
альтернативы: local guard с остающимся DNS gap и dedicated egress proxy, которому
нужны свой владелец и deployment ACL. Ни alias, ни plugin settings не менялись.

Выбранные правила:

- Только http80/https443, canonical IDNA/host/authority. Userinfo, fragment,
  controls/backslash, malformed ports и неоднозначные numeric forms запрещены.
- Только public unicast IPv4/IPv6. Блокируются private/loopback/link-local/
  metadata/reserved/multicast/unspecified/CGNAT, mapped и transition/NAT64 forms.
- DNS full set <=64. Mixed/unknown/empty/error означает отказ целиком, без
  truncation. Каждый send имеет новый immutable snapshot; connect получает
  только его numeric addresses. Public fallback ограничен тем же набором и
  remaining deadline; общего DNS monkeypatch/cache нет.
- Original canonical name остаётся Host и TLS server_hostname; IP literal имеет
  корректный bracketed Host. Certificate/hostname verification не отключается.
  CA берётся явно из установленного bundle, ambient SSL/proxy/auth не наследуются.
  [TLS verification contract](https://docs.python.org/3.13/library/ssl.html#ssl.SSLContext.check_hostname).
- HTTPcore не следует redirects и не строит URL auth или environment policy;
  proxy=None задан явно. [HTTPcore policy scope](https://www.encode.io/httpcore/).
  Внешний путь не получает service Bearer/Cookie/Proxy-Authorization.
- Total deadline 10s включает resolve/connect/TLS/write/read/close; response
  полностью drain с cap 64 KiB. Ошибки — фиксированный безопасный класс без raw
  URL/query/secret/SSL exception. Oversized/timeout дают прежний видимый retry.

Same owner используется для signup/PATCH и send-time. Manual disable пропускает
DNS только при persisted url target и enabled true→false, если raw target fields
не изменены; он не создаёт новый secret. Label-only, target changes и enabling
проверяются полностью. Legacy blocked subscriptions не переписываются, не
удаляются и не отключаются миграцией: получают safe last_error и обычный retry.
Существующий disable_dead, expiry/deadletter и caller transaction не менялись.

Подпись остаётся по прежним bytes/id/timestamp; время факта и время попытки не
смешиваются. Internal Support/app путь сохраняет registry/company mapping,
служебный events Bearer и прежний transport; external rule на него не натянут.

## Проверки и оставшиеся ограничения

ROOT исполнил 111 новых случаев и прежние 61 без ослабления assertions. Старый
signed_delivery fixture получил только recording adapter нового external seam;
actual helper conformance проверяется отдельно. Новый набор покрывает parser/IP/
IDNA/ports, full DNS/rebind/pinning, original SNI/Host, реальные owned loopback
HTTP/HTTPS receivers со strict RFC5280-compatible synthetic CA,
wrong-name/untrusted-CA без application data,
redirect/proxy/headers, cap/deadline и actual native socket FD cleanup на timeout,
safe history/retry. Verify flags STRICT/PARTIAL_CHAIN/check_hostname/CERT_REQUIRED
не ослабляются.

NoSQL handler stubs показывают target-validation order и disable exception,
но не являются proof всей admission ACL. `_admin` и transaction/outbox owners
защищены reverse AST/source proof, real SQL/whole-app ACL не заявляются. Runtime
делает только ROOT по exact frozen source/argv/env/ports на candidate77, без
внешнего traffic; actual artifacts созданы в managed temporary storage и
импортированы через MCP. Результаты указаны ниже.

Прямое использование уже установленного transitive HTTPcore API сопровождается
version/source proof и upgrade-contract test, без изменения dependencies.
HTTP без TLS сохранён по решению ROOT: конфиденциальность HTTP остаётся residual
и отдельным HTTPS criterion M09/M18 external pilot. Системная маршрутизация/NAT
и доверие публичному получателю не доказываются application-level guard.
Outbox/replay redesign, full M14, M00–M19, CI и release остаются открыты у ROOT.

## Фактический receipt ROOT V2

Runner SHA256: `c8aacb4c7170fcdd2bfdfc6a8e3b421da8653ecb962f32503121b06db27e7a64`.
ROOT независимо сверил frozen app496/tests365/schema16/support и 13 SDK source
pins; whole sender/router reverse AST, old47 fixture-seam-only, old14 blob и
остальные 493 app blobs совпали с согласованной границей изменения.

| Проверка | Фактический результат |
|---|---|
| Primary cases | **172/172 PASS**: new111 + old61 |
| Subtests / errors / failures / skips | 0 / 0 / 0 / 0 |
| Pytest / outer time | 4.46 s / 8.584 s |
| Exit / reap | 0 / подтверждён |
| Candidate inventory / metadata controls | 77 / 16, PASS |
| Source after / forbidden / delivery | PASS / 0 / 0 |
| Controlled binds / connects | 14 / 7 |
| Fixture setup/ready/finalized | frozen_boundary111, handler9, receivers7, exact |
| Порты 33547/33548 до/после | Свободны; SQL и external network не использовались |

Фактические HTTP/HTTPS cases подтвердили exact signed bytes/id/timestamp,
original Host/SNI и strict valid-CA TLS. Wrong-name/untrusted-CA не получили
application body. Actual timeout cases сохранили native socket references до
проверки FD=-1 и завершения peer tasks: GC не подменяет cleanup proof.
Controlled dial adapter сознательно отображает проверенный logical public IP
на owned loopback receiver. Это proof policy/dial/wire contract в контролируемом
окружении, а не измерение production routing, Internet reachability или p95/RSS.

V1 не исполнялся: strict CA и actual-FD fixture были уточнены source review до
actual. Начальный V2 parent остановился на disk preflight до создания child;
ROOT затем освободил только 61.8 MiB собственных завершённых frontend caches,
сохранив PNG/JSON evidence и reserve, и выполнил принятый запуск. Этот preflight
не переименован в test failure или PASS. App/helper не менялись после review.

Retained derived portfolio/inputs находятся в managed standalone analysis
`hardening/webhook-delivery-boundary-20261031-ctx-c03c90b31555/` вне Git.
ROOT импортировал **actual bytes**, не transcription: `validation/actual-v2/`
с parent script/process/log и boundary/failures/JUnit/pytest log;
`validation/root-runtime-summary-v2.json` и `root-source-review-v2.json` содержат
независимую проверку. Все записи выполнены Codex Security save/read MCP.
Публичный предметный report остаётся отдельным project-owned документом.

NoSQL handler stubs не доказывают всю живую admission ACL. Не заявлены full
M14/outbox/replay, M00–M19, CI или release; HTTP-конфиденциальность остаётся
residual HTTPS criterion M09/M18. Следующий владелец интеграции/выпуска — ROOT.
