# Совместный срез API после M14/P6/M16/P7, 31.10.2026

Срез привязан к Core `5693168397e5c1be4ee424db49ee8ce284d4f49b`, включающему
принятый P7. Это база этой волны: pending Acalendar/P8 и последующие изменения
сюда не входят. M01/M09 остаются частичными, общая цель M00–M19 и 11 критериев
активна; полный CI, live pilot и release не подтверждаются этим пакетом.

Исторические `CURRENT_SURFACE_REGISTRY_20261031.md/json` на Core `264ad50b`
сохранены побайтно. Использован тот же pipeline без изменения шести accepted
Python tools/tests или `inventory-api-consumers.mjs`; новый scanner не создавался.
Исторические CLI defaults не переписывались: все три revision передаются явно.

## Immutable sources

| Источник | Git pin | Наблюдение |
|---|---|---|
| Core | `5693168397e5c1be4ee424db49ee8ce284d4f49b` | M14/P6/M16 + принятый P7; свой worktree fast-forward из `5e435c9a` после ancestry check |
| Support | `a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df` | тот же candidate, actual whole-app unknown |
| Deploy / Auditor | `03450b4d96f8ef631198a0ee9a0bb11a5e6530b8` | readonly Git blobs, manifests и existing scanner |

Новый stdlib static scan выполнен Python 3.13.7 с `-I -S -B`, в owned TMPDIR,
без app imports, Node, tests/collection, SQL, network, startup или requests.
Он читает immutable Git blobs, исключает чужой WIP/untracked, сохраняет hashes,
mount graph, diagnostics, native/unattached/factory/dynamic evidence.

Core static fingerprint:
`df759dfc3fc32c288c1a40cca083553009fcaa2179026c5ccbeefc1878b054b7`.
490 `server/app/**/*.py`, full manifest SHA
`5914d88f3e729cec836b723e467d0203ab25d524ca531fb33323f40147f15a40`.
От прежнего source отличаются 12 файлов (три добавлены), удалённых нет.
Это новый срез source bytes, а не старый `264ad` JSON с новым revision label.

Новый static input:
`.artifacts/composed-surface-registry-20261031/static-5693168397e5.json`,
4 136 596 bytes, SHA256
`cfd729043a3bbd0f6b58b1a1f46bcced8fb4cf545fa89a2b93c629039092391e`.

## Static evidence и ограничения

| Источник | Static evidence, не actual |
|---|---|
| Core | 582 files; 1691 resolved records, два synthetic harness declarations (`/echo`, `/limited`), 7 diagnostics, 8 unattached |
| Support | 454 files; 737 static + 3 unresolved endpoint instances, 27 unattached, 91 diagnostics |
| Auditor | 5 files; 16 native condition candidates + два manual native source rows; отсутствие Express routes не означает отсутствие API |

Support повторно монтирует четыре объявления по различным v1/v2 SDK путям;
factory/middleware/computed/catch-all случаи остаются явно unresolved. Native
Auditor WS/SSE/binary/multipart/prefix dispatch имеют source evidence с SHA,
но не actual registration или conformance proof. Physical authority/gateway
rewrites и другие compositions неизвестны; ключи сохраняют logical authority,
app, protocol, method/path, mount chain и registration order/unknown ordinal.

Technical owner означает координату реализации. Domain owner берётся только из
реального PolicyRoute binding и не означает human owner или выполнение ACL.
Tags, handler names, dependencies и response classes не доказывают права.
Решения о поддерживаемом external/internal/legacy/integration контракте и
неподтверждённые consumers остаются unknown/needs-owner-decision.

Новый source comparison исторических 75 protocol passports снова даёт
58 unchanged-file facts / 17 drift. Совпадение этих чисел с прежним срезом не
является conformance PASS: admission/dependencies/scopes/errors/schema semantics
требуют отдельной приёмки. Dynamic SSE, native/factory/proxy/webhook/industry
границы вне доказанного source chain не растворяются в нуле.

Переиспользована ROOT selected-source сверка Support от 30.10.2026 22:43 UTC:
455 выбранных paths / 5 783 116 bytes, две одинаковые выборки, stable CID/image/start,
Node22.23.2. Baseline `09c221c4` совпал по 448 JS, candidate `a6a109c9` по 445;
два package manifests отличаются, у candidate ещё три ticket JS deltas и пять
новых отсутствующих файлов. Scope только selected scripts JS/manifests, не весь
Support/shared/frontend. Full actual Support/Auditor и frontend858 correspondence
не подтверждены; source receipts и их SHA сохранены в machine JSON.

## ROOT acceptance boundary

ROOT принял новую пару actual Core exports, strict shared comparison, match-only
overlap, source AST consumer export, composer и same-input check. Прежние 41
control переиспользованы без повторного запуска при неизменных tools. Новый source
проверен одним существующим opt-in case для пары exports; это не новый run41 и
не полный CI совместного приложения.

| ROOT step | Результат |
|---|---|
| Actual pair | PASS, 32.702s; Core1706 / curated15 / WS1 / mount1 / unresolved0 / duplicates0 |
| Match-only overlap | PASS, 23.982s; 109 literal-precedes-parameter, strict equivalence |
| Consumer source AST | PASS, 11.232s; 5267 records: 1460 shared / 43 native / 3764 wrappers; 0 omitted / 0 diagnostics |
| Composer | PASS, 158.986s |
| Same-input check | PASS, 156.185s |

Итог: 2491 surface row, 15 candidate и 2476 needs-owner-decision/domain-owner
unknown; 640 surface rows имеют exact method/path source candidates, 1851 — без
доказанного сопоставления. Это не 640 доказанных runtime consumers. Support:
737 static + 3 unresolved + 27 unattached; Auditor: 16 native candidates + два
manual source rows, actual whole-app по-прежнему unknown.

Final JSON: 13 462 824 bytes, SHA256
`ca668c80019f554f81420d9577bd2704858f170f0569b32055cfdde0e70d7054`.
Raw Core first SHA
`d7d6001060b68bad20fc17baf328bc326dc1b1ceaa64aedccfbfbcba6cef1e37`,
repeat SHA `0820ec3fa2bbb4db9a1819702f7bb43309a38924a62daf0d79385f07cebbe1df`:
allOtherFieldsExact/equivalent true, rawByteIdentical false, 12 enumerated approved
generated-ID variations. Consumer raw input: 4 162 879 bytes, SHA
`c32e463a3fe930d701c09232d95e72f403f58cd69c793b8f2371d563d25a8203`.

Explicit operationId и raw generatedUniqueId сохраняются раздельно. Исключение
в comparison допускает только reviewed default-generator identity и
`fastapi/utils.py` SHA `0d7d15ae73307d5b19c51cfc222b50e36736fbef9f0f398566479131947650ca`,
отсутствующий explicit ID, полный sorted method set и exact prefix. Custom/single/
explicit/forged basis и остальные metadata differences не допускаются.
Raw captures сохраняются до comparison; rawByteIdentical и raw hashes публикуются
отдельно от strict registration equivalence. Byte identity свежих процессов не
обещается; `--check` сравнивает результат тех же frozen inputs побайтно.

Frozen proposal содержит exact argv/env/order, code/source/static hashes,
candidate77 и readonly Node22.23.2/TS5.9.3 toolroot, owned resolver link guard/cleanup.
Limits: 16 MiB input/output, 10 000 rows/files, 64 MiB source/service, Git30s,
composer240s, exporter child120s; ROOT resource profile8 GiB floor / 512 MiB
no-SQL planning. Temporary staging удаляется context manager; worker не запускает
runtime, не трогает venv/node_modules/old DB и не делает foreign cleanup.

Все пять ROOT processes завершились exit0/reaped без resource boundary;
sourceAfter=true после каждого шага, resolver отсутствует после cleanup.
Шесть tool hashes, static input и исторические CURRENT MD/JSON не изменились.
ROOT использовал ранее проверенный inline inode/target guard с сериализованным
JSON receipt вместо исполнения proposal setup strings; ownership и cleanup
семантика сохранены. Worker runtime/app/Node/tests/SQL не выполнял.

ROOT evidence: `.artifacts/root-composed-registry-review-20261031/`:
`run.py`, `source-review.json`, `venv-config-check.json`, `processes.json`,
`node-resolver-state.json`, `acceptance-summary.json`. Exact raw captures и
comparison: own `.artifacts/composed-surface-registry-20261031/root-acceptance/`;
frozen proposal и свежий static input сохранены рядом. Historical report SHA
`ff144d91c4c9f453736017cb1623ee43dd17f52fac2d54c20ddd86347bce88cf` сохранён.

## Следующие владельцы

ROOT выполнил actual acceptance этой frozen волны. Далее нужны назначенные
human/domain owners и решения для неизвестных surfaces/consumers, контролируемые
Support/Auditor exporters, protocol characterization и новая regeneration после
последующих волн тем же pipeline. Этот snapshot не закрывает M01/M09, M00–M19,
11 критериев, full CI или release.
