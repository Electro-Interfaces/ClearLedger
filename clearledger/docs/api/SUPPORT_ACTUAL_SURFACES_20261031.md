# Support: реестр фактических регистраций и сверка со статикой

Дата: 31.10.2026. Пакет M01/M13, отдельный service-only input для следующего
общего реестра. Полная цель API, M01/M13 и решение о публикации остаются открытыми.

Статус: **ROOT_SCOPED_SUPPORT_REGISTRY_PASS**. ROOT выполнил controls, генерацию,
check, свежий повтор и независимый reference walk; соседний JSON скопирован из
принятого ROOT first.json побайтово. Worker выполнял только чтение, Git, AST/compile
и подготовку файлов; новый parser/controls, Node, приложения, запросы, SQL и серверы
worker не запускал. Parser и frozen contract после приёмки не менялись.

## Фактическая приёмка ROOT

Receipt `.artifacts/root-support-surface-reconciliation-20261031/acceptance.json`:
2379 bytes, SHA256 `70c436b11f84e59f83de419e73920348637994360e53715260efa92feea032e4`.
Независимый `.artifacts/root-support-surface-reconciliation-20261031/reference-review.json`:
705 bytes, SHA256 `006013932808ce20d92b38a65b896aae2519d29ca131713b41d4a76d1b9435ba`.

| Фаза ROOT | Фактический результат | Время, s |
|---|---|---:|
| Controls | 30 PASS, exit 0 | 0.2120375903 |
| Generate | exit 0, source-after equal | 8.4220499611 |
| Same-input check | exit 0, bytes equal | 8.4293473614 |
| Fresh repeat | exit 0, bytes equal | 8.2352049239 |

Все процессы reaped; после каждой фазы три frozen source files совпали. App imports,
Node, SQL и network requests в этих ROOT фазах: 0. Принятый результат: **7 355 315 bytes**,
SHA256 `baa290b0328a914613ebe606da893080e4e4dbcf657c5c84843e300865d48e32`.
First и second совпали побайтово. Frozen contract SHA256
`b158fb5afe427282b746891593316201a498fe75b6d3e3f657c620194806e9ba`, parser SHA256
`e261d8bfbcff0f552ab777da9c4a6b5628ed61035d17e9df5c722a67cd705fc8`.

Независимый ROOT reference-review.py подтвердил все восемь полных input SHA,
полные trees/registrations, **6220 per-configuration method-pattern observations**
и **12 956 ordered handler coordinate comparisons**, включая prefix siblings и
physical instances. Итог: 778 canonical rows; 736 raw historical candidates плюс
один явный symbolic ALL alias, logical-only actual 41, logical-only static 0.
Три old unknown и 27 unattached сохранены с candidates и semantic UNKNOWN.
Этот PASS относится к реестру регистраций; HTTP/ACL/WS/bootstrap/live/consumers
и общий реестр 2491 не проверены и не обновлены.

## Доказательства и границы

Исходники Support зафиксированы коммитом
`e3a7cdb98896b552eed9557adefb50a23ebdf1dd`; wrapper Core:
`733da1f25d2097b036901263b80c5f0e4d01f56c`.
Принятые registrations получены ранее ROOT реальным `createSupportApp`, без
HTTP-запросов и без SQL. Этот пакет читает их JSON и immutable Git blobs;
приложение повторно не импортируется.

Входы строго перечислены в `contract.captures` соседнего
[JSON](SUPPORT_ACTUAL_SURFACES_20261031.json): originalId, серия, variant,
полные SHA256/bytes, sourceIdentity/nodeIdentity, environmentAudit, readFD,
counts и ссылки на полные capture bytes. Восемь original IDs различны:

| originalId | identity | context | dist | Серия / leaf |
|---|---|---|---|---|
| 0 | local | false | false | V10 / 00 |
| 1 | local | false | true | V10 / 01 |
| 2 | local | true | false | V10 / 02 |
| 3 | local | true | true | V10 / 03 |
| 4 | core | false | false | V10 / 04 |
| 5 | core | false | true | V10 / 05 |
| 6 | core | true | false | V12 / 00 |
| 7 | core | true | true | V12 / 01 |

ROOT acceptance:
`.artifacts/root-support-composition-isolated-v12-20261031/root-eight-configurations-acceptance.json`,
SHA256 `44f361c793db38690eb4b8159edf1ac060b7432172bec7319a3187b45885d3cd`.
Его статус `ROOT_SCOPED_EIGHT_DISTINCT_TWO_SERIES_PASS`, `single8Green=false`.
V10 остаётся BLOCKED по совокупному output budget перед седьмой конфигурацией:
приняты шесть завершённых leaves и независимый source-after; ещё две завершены
в V12. Это две серии 6+2, а не единый успешный запуск восьми. Старые 26 negative
controls и traces не доказывают HTTP/auth/ACL/security conformance.

Независимый ROOT six-prefix summary:
`.artifacts/root-support-composition-route-review-20261031/six-prefix-summary.json`,
SHA256 `e748c6af8baee6381e3e0109b3c9302ea572f071ab69f1e2414d5a1a15599ab5`.
Все пути `.artifacts/` здесь относятся к ROOT Ledger worktree
`/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029`.
Старые captures/proofs не изменяются.

## Наблюдаемые source/data facts

При stdlib-чтении JSON, без исполнения нового parser, получены:

| dist | Полных layers | route layers | method-pattern rows | concrete HTTP rows | symbolic ALL |
|---|---:|---:|---:|---:|---:|
| false | 2631 | 774 | 777 | 775 | 2 |
| true | 2634 | 775 | 778 | 776 | 2 |

Три добавочные method-pattern rows возникают из явно заданных строковых
альтернатив двух route arrays (3 и 2 пути). Массивы не теряются: исходные typed
arrays остаются в дереве и `declaredPath`, строки являются представлением их
явных альтернатив. RegExp не исполняется и не превращается в guessed string.

В пределах каждого dist значения **stack и registrations** byte-canonical
идентичны во всех четырёх конфигурациях. Целые leaves различны: variant/env и
их полные SHA256 сохраняются отдельно. Допустимы ровно две полные читаемые
композиции; никакого interning/compression codec нет.

У `.all()` route хранит `methods=["_all"]`, дочерний intrinsic handler имеет
`methods=[]`; его регистрация содержит `method="all"`. Это сохраняется дословно.
У ALL нет придуманного списка HTTP-методов. Возможный HEAD fallback для GET
относится к source semantics Express, не к actual HEAD request.
Источник: immutable dependency `node_modules/router/lib/route.js`, методы
`_handlesMethod`, `dispatch`, `all`, и capture registration/handler records.
Реестр не утверждает, что middleware пропустит запрос до этого маршрута.

Source manifest: 289 файлов Support, 3 952 434 bytes. Каждый `/work/source/...`
сопоставляется с файлом immutable Git pin, Git blob SHA1 и SHA256 байтов.
`/work/node_modules/...` сопоставляется с принятым dependency manifest
SHA256 `23d43f1d34ecba8297fb8d5821fd541a79cbcf7b1a8b5b41d6c1a6a76fb207c9`.
Toolroot повторно не сканируется, его код не выполняется; это provenance исходного
capture, не новое доказательство installed/live версии.

Два handler occurrences имеют одинаковый function SHA256
`7f99b497ca78b89966692400d0af38f6d9d9c0abe9def818bebd08f42c27b00e`
и два source candidates: `scripts/routes/v1/tickets.js:825` и
`scripts/routes/v2/sdk-tickets.js:775`. Definition остаётся UNKNOWN. Registration
frame не выбирает definition. Точное совпадение Function.toString в одном файле
показывает source candidate координату, но не человеческого/предметного владельца.
Generic `Router.handle` остаётся dependency routing machinery.

## Schema 1 и порядок

Верхний объект: `schemaVersion`, `contract`, `registry`. Frozen contract SHA256
проверяется кодом. `registry` после генерации содержит:

- `summary`: по каждой композиции, отдельные concrete HTTP и symbolic ALL counts.
- `sourceManifest`, `definitionFiles`: immutable технические исходники и отдельно
  dependency provenance; old/new source drift без утверждения semantic parity.
- `compositions`: две полные исходные ordered registrations и recursive stack.
  Все mounts, factory instances, middleware, children, handlers, hashes/arity/name,
  registrationSource, definitionSource/candidates и unknown сохранены.
- `canonicalRows`: method/path PATTERN, occurrences с полной typed mountChain,
  declaredPath, indices, registrationOrdinal, orderedRouteHandlerIndices и
  orderedPrefixContexts. Observations каждой строки ссылаются на originalId,
  полный capture SHA256 и actual indices/ordinal. Повторные physical occurrences
  не схлопываются в отсутствие дубликатов; они остаются отдельными occurrences.
- `repeatedPhysicalRegistrations`: один registrationOrdinal виден в нескольких
  mount locations, с полным порядком координат. Это не анализ пересечений patterns.
  Разные factory instances с разными ordinals остаются отдельными в полном tree и
  occurrences; поле не объединяет их и не доказывает factory equivalence.
- `reconciliation` и `unknown`: отдельные категории сравнения и ограничения.

Координата `indices=[i,j,...]` означает `stack[i].children[j]...` внутри полной
композиции. `orderedPrefixContexts={stackAt:[...],beforeIndex:n}` означает весь
исходный префикс siblings `[0,n)` данного стека, в его первоначальном порядке.
Ничего не исключается по имени middleware. Это контекст регистраций, а не
вычисленная effective execution/ACL chain: совпадение paths, fallthrough,
ошибки и поведение middleware не исполнялись. Полный tree сохраняет и последующие
siblings, которые могли бы иметь значение при fallthrough.

Порядок полей задан конструктором JSON, compact UTF-8, один финальный LF.
Порядок registrations/tree/physical occurrences/observations не сортируется.
Canonical row ID выдаётся при первом наблюдении method+typed pattern, начиная
с dist=false DFS, затем dist=true. Сортируются только имена definition files.
Unknown/ambiguous данные не заменяются предположениями. Нет timestamp, адресов
памяти или нестабильных путей временных каталогов.

## Сверка с исторической статикой

Исторический input взят из Ledger
`0a206bac567697abeae8a5d7eb9e8ecd8ea3d30e:docs/api/COMPOSED_SURFACE_REGISTRY_20261031.json`:
13 462 824 bytes, SHA256
`ca668c80019f554f81420d9577bd2704858f170f0569b32055cfdde0e70d7054`.
Его pins: Core `5693168397e5c1be4ee424db49ee8ce284d4f49b`,
Support `a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df`,
Deploy/Auditor `03450b4d96f8ef631198a0ee9a0bb11a5e6530b8`.
Это не current composition.

В старом Support: **737 static, 3 unresolved, 27 unattached**. Exact string
method-pattern совпадения являются только кандидатами. Raw comparison сохраняет
старый `*` и actual `_all` различными токенами; logical comparison отдельно
показывает symbolic ALL alias с доказательством `.all`, без HTTP expansion.
ROOT независимым walk подтвердил 736 raw exact candidates и один symbolic alias;
logical-only actual 40/41 по dist (41 в объединённом реестре). Эти counts получены
из captures, не подставлены как generated golden.

Отдельно показываются raw/logical only-actual/only-static, repeated mounts,
старые unresolved/unattached с actual registration candidates и remaining unknown.
Для byte-equal файлов сопоставляется file/line регистрации. В изменённых файлах
отдельный source anchor показывает SHA256 stripped старой declaration line и
все точные current line candidates; только единственный candidate используется
для связи. Это сохраняет, например, сдвиг MSTO line 554→560 без эвристики имени.
Совпадение declaration line или declared string path после переноса
server→factory остаётся candidate, не утверждением равенства поведения.
Сравнимые старые blobs проверяются на a6; текущие — на e3. Source drift
показан явно. Source-only parity 13 файлов/100 registrations не означает равенство
737 static routes фактическому приложению. Старый общий реестр 2491 и его tools,
исторические CURRENT/COMPOSED reports, production code не меняются.

## ROOT-only воспроизведение после frozen review

До запуска ROOT сверяет SHA256 трёх новых файлов и contract hash из freeze ask,
создаёт только свой каталог
`.artifacts/root-support-surface-reconciliation-20261031` и сохраняет before hashes.
Указанные пути замкнуты в parser; разрешены output `first.json`, `second.json`.
Файлы создаются исключительно, существующие не перезаписываются.

Working directory:
`/home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030`.
Каждый argv запускается отдельно, без окружения shell/session:

```sh
/usr/bin/env -i HOME=/nonexistent-support-registry PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 /usr/bin/timeout --signal=TERM --kill-after=5s 95s /home/mag/.local/bin/python3.13 -I -S -B clearledger/scripts/support-composition-registry.py --controls

/usr/bin/env -i HOME=/nonexistent-support-registry PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 /usr/bin/timeout --signal=TERM --kill-after=5s 95s /home/mag/.local/bin/python3.13 -I -S -B clearledger/scripts/support-composition-registry.py --root-ledger /home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029 --support-repo /home/mag/orca/workspaces/tsupport/api-support-app-composition-20261031 --output /home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-support-surface-reconciliation-20261031/first.json
```

Повторить второй argv с `--check` того же first.json; затем в новом процессе
с `--output .../second.json`. ROOT сравнивает first/second побайтово, независимо
обходит исходные восемь stack/registrations и сверяет все row observations,
handler order, prefix siblings, physical duplicates, ALL, arrays и ambiguity.
Новые Node/app/SQL проверки для этого пакета не требуются.

Исходные inputs перечитываются после projection; source/dependency/Git hashes
и полные capture bytes должны остаться прежними. ROOT отдельно проверяет source
новых файлов/остального tracked tree до и после execution. После приёмки
ROOT output побайтово заменил исходный `registry:null` в назначенном JSON;
contract неизменен. Принятые approved artifact copies прошли `--check` и свежий
byte-equal repeat. После финального копирования worker parser не исполнял.

Controls: ROOT выполнил 30 именованных случаев (23 отказа, 7 положительных), PASS.
Явные независимые fixture expectations проверяют array alternatives, regex unknown,
symbolic ALL, две physical mounts одной регистрации, prefix order, ambiguous и
missing definition. Отказы покрывают duplicate JSON keys, nonfinite, hash/bytes,
manifest count/ID/variant, path escape/type, ordinal/index/method, registration
provenance и стирание unknown. Фактический PASS зафиксирован ROOT receipt выше.

Лимиты: ровно восемь leafs, каждый ≤4 MiB, сумма ≤32 MiB; historical JSON ≤16 MiB;
289 source files ≤64 MiB; output ≤8 MiB и ≤5000 canonical rows; CPU 60 s,
wall 90 s, AS 1 GiB, FD 64; Git subprocess timeout 20 s и stdout ≤64 MiB.
Только read-only `git show`/`cat-file --batch`, без shell/hooks/pager/fsmonitor,
с отдельным cleanenv. Ни env discovery, ни Node, ни SQL, ни dependency scan.
Два outputs вместе ≤16 MiB; ROOT parent ограничивал совокупный evidence budget
32 MiB, FSIZE 8 MiB, outer CPU 90 s/wall 100 s/AS 2 GiB/FD 128 с внутренними
60 s/90 s/1 GiB/64 соответственно. Перед каждой фазой сохранялся floor 8 GiB
и no-SQL planning reserve 64 MiB.
Timeout завершает process group; subprocess timeout убивает/reap child Git.
Cleanup только двух собственных output/log files по решению ROOT, inputs read-only.

Source-only budget planning: две полные пары stack+registrations занимают
5 134 907 compact bytes; максимальная route depth 3, route handlers ≤4.
Для canonical rows/observations зарезервировано 2.5 MiB, для manifest/provenance/
reconciliation — 0.5 MiB: план около 8.28 MB, ниже 8 MiB. Это оценка source/data,
не результат запуска. Фактически ROOT получил 7 355 315 bytes; byte budget
проверен fail-closed до записи, данные ради лимита не исключались.

## Что остаётся неизвестным

Domain/human owner, внешняя публикация, scopes/grants и ACL conformance UNKNOWN.
Названия handler/tag и native/sourcecandidate не разрешают partner API.
Zero duplicate exact keys не означает zero pattern overlaps. WS, PTY, ingress,
bootstrap/lifespan, runtime containers, live/public correspondence и HTTP/request
семантика этим пакетом не проверяются. Следующий владелец/интеграция/release — ROOT.
