# Поддержка: package baseline и следующий source seam, 31.10.2026

Live package-файлы отличаются от Git baseline/candidate **только metadata version
`1.2.29 → 1.2.32`**. Это реальное JSON semantic difference, не formatting-only.
Scripts, dependency specifiers, devDependencies, overrides/engines и все 917
non-root lock entries неизменны. Из этого не следует совпадение установленного
`node_modules`, native/global CLI компонентов или runtime behavior.

Support не менялся. API tools и historical CURRENT/COMPOSED reports сохранены.
Worker использовал только Git/read/stdlib JSON/text/AST/compile; app/server/Node/
npm/audit/installers/SQL/SSH/network не запускались. M00/M13/M01, полный M00–M19
с 11 критериями, full CI и release по этим двум файлам не закрываются.

## Exact evidence

ROOT прочитал два literal source bodies 31.10.2026 00:27:12.432 UTC: stable
CID/image/start, два одинаковых чтения, Node22.23.2, без app imports/DB/env/logs.
Snapshot SHA `8f25dc18c789d279e73ec1028cde775bfbfef3f64a133338d60c43f285865fa8`,
process receipt SHA `fa48fd24136c18ea12298d01698d92c036f46f5b101de5077e076b6df1ba75cd`.
Comparator проверяет whitelist ровно двух файлов, bounded reads, строгий base64,
decoded size/SHA, snapshot/process pins и strict JSON. Raw bodies/base64 и
URLcredentials не публикуются и не сохраняются в Git.

| Файл | Live SHA256 | `09c221c4` и `a6a109c9` SHA256 |
|---|---|---|
| package.json | `3c344dec6cfe8217f8d43385652a1536024d268f9b0e0e835ce82226bde4a9e4` | `7df1c5e3ea06d9f6bd7667d889a520bfd6bf1b617ee5fe49b576ee98d353f672` |
| package-lock.json | `ad7ae28502e1fdf93541bb313ea13f0b946f6db53219099360f8a01c42cabf96` | `f1077992933347c42aa9bc25b3f2489d9b8ac8cf87d8f97fa67c384ff1cbc7d1` |

Baseline `09c221c4b5135984173e3a924fd38f65cc208637` и candidate
`a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df` побайтно равны по обоим package files.
Package: 10 730 bytes / 192 LF; lock: 460 435 bytes / 12 409 LF во всех трёх
источниках. CRLF/lone CR/BOM отсутствуют, завершающий LF один. Различаются одна
и две строки соответственно; замена только version token воспроизводит exact live
bytes. Ни line endings, ни trailing newline не переписывались.

Полный semantic diff, с сохранением порядка arrays:

- package `/version`: `1.2.29 → 1.2.32`;
- lock `/version`: `1.2.29 → 1.2.32`;
- lock `/packages//version` (пустой package key): `1.2.29 → 1.2.32`.

Сравнены все 918 lock entries, включая root. Non-root 917/917 равны по всем
полям; changed resolved/integrity/dependencies entries — 0. Сравнение не ограничено
тремя названными полями: version/license/engines/optional/peer/dev flags и любые
другие поля также входят в full tree diff. Root scripts/dependencies/devDependencies/
optional/peer/overrides/engines не изменились; отсутствующие поля не подставлялись.
JSON object key order не считается семантикой, arrays ordered, numbers сравниваются
без float rounding, bool отличается от number; duplicate keys/nonfinite rejected.

## Происхождение и практическое значение

В замороженных 105 локальных refs (73 unique roots), 101 package-history commits
и 319 path objects нет package version `1.2.32` и обоих exact live blob objects.
Это отрицательное наблюдение только в изученном наборе, не утверждение об отсутствии
такого коммита где-либо или в недостижимых объектах. Network/fetch не выполнялись.

Установленный `elsy-deploy/scripts/ship-support.sh`, SHA
`5730221f4e47a8e9786ed734299e7789130c10c3372aed964f20c312ee4b859f`,
строки 43–46 описывает patch bump через `npm version patch --no-git-tag-version`.
Такой механизм согласуется с наблюдаемой version-only разницей. Доказательства,
что именно этот script/команда создали live files, нет; нельзя выводить число
выкаток, build commit или время изменения из трёх patch increments.

Практическое влияние следует из source: `scripts/server.js:227` читает package
version для `/api/health`, `vite.config.ts:7–15` включает её в `__APP_VERSION__`
при сборке. Это может менять отображаемую версию; health endpoint не вызывался,
соответствие frontend bundle этому package не проверялось. Dependency upgrades
или vulnerability/security status по данному diff не устанавливаются.
Dockerfile использует `npm ci`, native node-pty build и отдельно global CLI;
lock не удостоверяет установленное дерево, native artifacts или global CLI.

## Точная следующая база и coverage

Единого доказанного Git commit, совпадающего со всем live Support, пока нет.
Точная доказанная база задаётся компонентами: selected JS baseline `09c221c4`,
две live package bodies с SHA выше и metadata version **1.2.32**, плюс явные gaps.
Candidate остаётся exact `a6a109c9` с package metadata 1.2.29; здесь ничего не
исправлялось молча. Будущий release owner должен явно сохранить более высокую
live baseline 1.2.32 и согласовать следующий номер, не начинать patch bump от
устаревших 1.2.29 и не менять dependency target под видом version preservation.

ROOT selected-source proof от 30.10.2026 22:43 UTC охватывает 455 выбранных paths:
450 существуют, пять отсутствуют; 5 783 116 bytes. Metadata контейнера и hashes
двух package files совпали с новым body snapshot. Это не новое чтение всех JS
31.10 и не full source correspondence. Comparator независимо пересчитал parity:

- `09c221c4`: 448 JS equal, два package files different, пять missing;
- `a6a109c9`: 445 equal; дополнительно different `scripts/lib/ticket-commands.js`,
  `scripts/routes/v1/tickets.js`, `scripts/routes/v2/sdk-tickets.js`;
- missing candidate-selected files: `scripts/lib/support-create-client.test.js`,
  `scripts/lib/ticket-create.js`, `scripts/lib/ticket-create.test.js`,
  `scripts/test/ticket-create-fixture.mjs`, `scripts/test/ticket-create-integration.mjs`.

Полный candidate diff содержит 15 paths: кроме selected 3+5, есть migration,
два docs, E2E и три frontend files. Они перечислены в JSON; выбранная live сверка
их не покрывает. Shared, frontend, runtime-only/untracked и installed dependencies
остаются unknown. Весь candidate нельзя назвать live baseline по 445 совпадениям.

## Следующий bounded план реальной route composition

Это source-only план следующего исполнения для назначенного ROOT owner, не actual
registry и не разрешение запускать `scripts/server.js`. Real Express routes нельзя
подменять parser output/fake Router, а names/tags не доказывают ACL.

В server source есть 10 вызываемых factory exports: шесть legacy
`createSSHRouter(supabase)`, `createDiagnosticsRouter(supabase)`, `createAIRouter()`,
`createKnowledgeRouter(supabase)`, `createNotificationsRouter()`,
`createAIAuditRouter(getPool())`; `supabase` сейчас literal null. Ещё четыре —
`createSupportContextEntryRouter()` и три named support-context factories
(actor/service/admin). В `routes/v1/eco.js` ещё четыре реальные вложенные factories:
voice-context, ticket-communications, voice-knowledge, voice-connections.
Остальные main router imports преимущественно default Router instances; порядок
middleware/mounts, повторные v1/v2 mounts и conditional dist fallback сохраняются.

Наблюдаемые blockers с SHA/lines в JSON:

| Source | Blocker / граница |
|---|---|
| `server.js:1`, `lib/env.js:6` | загрузка `.env`/`.env.production` до сборки |
| `lib/ssh-execute.js:11–21` | import-time fallback key path probe/read |
| `routes/ai.js:41`, `routes/ai-audit.js:45`, `terminal-manager.js:153` | import-time CLI lookup, filesystem probes и fallback `execSync('npm root -g')` |
| `lib/rate-limiter.js:9` | import-time cleanup interval, даже с unref |
| `terminal-manager.js:31` | top-level await import native node-pty |
| `routes/v1/support-context.js:104`, `lib/support-context.js:440` | factory запускает context workers, если feature включён |
| `server.js:310` / `lib/db.js` | eager getPool для AI-audit factory; сам provider lazy, query/connect уже I/O |
| `server.js:440–513` | top-level migration queries, до listen, ошибки могут catch/recover |
| `server.js:514–590` | listen, WS init, outbox/SLA/process/escalation/sync/email/monitor/CLI-refresh jobs; core identity sync ещё и вне listen callback |
| `server.js:426`, context-entry | filesystem-dependent dist composition / request-time static reads, отдельный bounded variant |

Минимальный seam потребует не только выноса listen: выделить import-safe
`createSupportApp(config, providers)` с теми же реальными factory/Router exports,
guard handlers и ordered registrations. Bootstrap отдельно владеет env loading,
migrations/listen/WS/jobs. Деферировать credential/CLI/native lookup до runtime
provider и перенести rate-limiter/context-worker starts в явный bootstrap; передать
AI-audit lazy pool provider вместо eager pool call, сохранив production defaults.
Ни SQL stub, ни fake auth/query-success не должны выдавать это за actual behavior.
Transitive import graph ещё не исчерпан; каждый новый side effect должен давать
blocked receipt, а не скрытый fallback или silent omission.

Следующий ROOT proposal должен отдельно закрепить source+deps/toolroot (не брать
Ledger node_modules за доказательство Support dependencies), Node version, flags,
synthetic config variants (local/core identity, context enabled/disabled, dist),
closed module/read allowlist и независимый deny network/DNS/socket/process/worker/
native/write/SQL/delivery/timers boundary. Любой denied attempt, даже caught,
инвалидирует экспорт. Не полагаться только на JS monkeypatch/VM. Сначала guard
negative controls на synthetic paths, затем isolated real Express app/router stack
без requests/handle/lifespan/listen; WS upgrades/SSE/multipart/native/dynamic/static
dispatch, не доказанные этим tree, оставить unknown до отдельных bounded proofs.
Сопоставить source/method/mount/order/full graph и registration parity с production
composition seam; auth declarations отдельно от request ACL characterization.

## Воспроизведение и передача

Новый stdlib comparator `clearledger/scripts/compare-support-source-packages.py`
не пишет raw bodies и ничего не меняет в Support. Frozen refs в own
`.artifacts/support-package-baseline-20261031/history-refs.json` сохраняют exact
examined roots; proposal фиксирует helper/report/input hashes и exact argv.
`--check` требует детерминированного совпадения JSON; max input2 MiB/file512 KiB,
output1 MiB, JSON depth64/nodes200000, diff/lock entries10000, Git30s/wall60s.
ROOT independent oracle подтвердил только три version paths, exact token patch
и равенство всех 917 non-root entries. Три bounded source-only процесса завершились
exit0/reaped, без app/Node/SQL:

| ROOT source check | Результат |
|---|---|
| Independent regeneration | PASS, 5.650s, byte-identical 33 852 bytes |
| Same-input check | PASS, 6.787s |
| Девять grouped stdlib integrity checks | PASS, 0.084s; duplicate/nonfinite, arrays/type, base64/size/hash, bounds/pins, real lock change и отсутствие URLcredentials в output |

Frozen JSON SHA256
`6c6f61f18941410532a8d08eb2127cc60005f3f085eb46d493e1dfcbc63113f0`,
helper SHA256 `7f28daed6876e26a1a91045483f5ea106142f14eeac59cba0d24c72e6b28227d`.
ROOT sourceAfter, шесть API tools и четыре CURRENT/COMPOSED historical files
сохранили hashes. Evidence ROOT:
`.artifacts/root-support-package-review-20261031/{independent-oracle,processes,acceptance}.json`.
Own frozen proposal/refs: `.artifacts/support-package-baseline-20261031/`.

Принят только bounded source plan. Runtime tests для этой отчётной задачи не
запускались и не требуются; actual Support composition остаётся unknown.
Будущего implementation owner и acceptance environment выбирает ROOT; исполнение
потребует отдельного Support worktree и новой authority, не продолжения здесь.
