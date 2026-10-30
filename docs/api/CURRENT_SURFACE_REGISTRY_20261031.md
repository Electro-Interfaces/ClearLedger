# Текущий срез API-поверхностей, 31.10.2026

Это датированный пакет M01/M09 для Core, Support и Auditor. Общая цель включает
M00–M19 и 11 сквозных критериев; пакет не закрывает M01/M09, full CI, пилот или выпуск.
Внешний curated read API является частью Core, а не всем API пространства.

**Срез Core `264ad50b` относится к состоянию до M14 и уже отстаёт от integration
ROOT `6fb8fd5bad332a9e0aff86408d10ae35ad70a0db` на момент приёмки.**
Это датированная проверяемая база, а не current final ROOT registry. После
интеграции M14/P6 и следующих волн нужны новые pins, exports и regeneration;
полученные ниже receipts относятся только к указанному срезу.

ROOT согласовал состав ответом на semantic plan Dispatch `ctx_dc35325ed8ac`:
новый root snapshot и current protocol appendix, без перезаписи historical
`clearledger/docs/api/*20261030`. Production handlers, auth, DTO, SDK, schema,
dependencies и frontend не менялись. Support/Auditor/Deploy только читались.

## Источники и границы доказательства

| Источник | Точный Git pin | Состав |
|---|---|---|
| Core | `264ad50bec46e73f2bb42a2f9c27969ed909314f` | `clearledger/server`; frontend consumer source отдельно `clearledger/src` |
| Support | `a6a109c9d0ce573f55d18a6c1bf36bb4adfbd5df` | candidate `agent/support-create-client-20261030`, не историческая common copy |
| Auditor / поставка | `6e1d33cceca5d12c5615a301dfc8c16c89fcc92f` | `services/auditor`, manifests `apps/*.yml`, existing scanner |

Scanner получает immutable Git blobs. Чужие working tree edits, untracked
`__pycache__`, `.env`, данные, внешние skills/work/kits, зависимости и test directories/
test-name patterns исключены правилами existing scanner. Acceptance harness с другим
именем может присутствовать как отдельный source app, см. исключения ниже.
Каждый включённый файл имеет размер
и SHA256; в JSON сохранены source pins, tool hashes, mount graph, diagnostics,
unattached declarations, duplicate groups и native candidates.

Исторические published artifacts не являются текущим denominator:

| Artifact | Состояние на этом срезе |
|---|---|
| `RUNTIME_API_INVENTORY_20261030.md` | Actual 1703/12 на `e1cb1a53`; historical receipt, не current export |
| `CORE_PROTOCOL_PASSPORTS_20261030.json` | 44+31 passport, source `e4f866d0`, runtime `e1cb1a53`; нуждается в hash/registration review |
| `ROUTE_OVERLAP_TRIAGE_20261030.json` | 109 match-only pairs исторической регистрации; требуется новый receipt, не oracle |
| `API_CONSUMER_INVENTORY_20261030.json` | AST source `06e02207`; не current consumer map |
| Deploy `INVENTORY-20261029.md` | Core initial/Support `9564`/Auditor historical source-only; не текущий runtime |
| Deploy completion matrix / STATUS | Plan snapshot `6e1d33cc` сохранён как evidence; ROOT обновляет собственные документы отдельно |

Число 1706 было гипотезой до actual export. Изменение framework/parser/Python version
может менять static coverage. Composer требует Python 3.13+; пробный запуск под
3.11 обнаружил три PEP701 parse errors и не принят как текущий denominator.

`actual_registration` означает регистрацию в выбранном offline app tree,
а не запрос, ACL-приёмку или live composition. `static_*`, `unattached_*` и
`native_condition_candidate_not_route` остаются отдельными наблюдениями.
Support `scripts/server.js` и Auditor `server.js` не исполняются: их entrypoints
содержат DB/AI/process/timers/listen. Для них actual whole-app export пока unknown.

Физический authority/base URL и gateway rewrite не подтверждены этим пакетом.
Ключ содержит logical service authority, app, protocol, method, path, mount chain
и registration order; для static order unknown, исходные ordinal/declaration ID
сохраняют повторные объявления. Разные сервисы и mount instances не схлопываются.

Python 3.13.7 static scan: Core содержит 1691 разрешённую запись основного app
и ещё два unresolved synthetic harness объявления (`full376.py`, `/echo`, `/limited`).
Последние не являются production API; app/source key отделяет их, а actual Core
export берёт только `app.main.app`. Core: 579 source files, 7 diagnostics,
8 unattached declarations. Support: 740 mounted endpoint instances (737 static,
3 unresolved), 454 files, 91 diagnostics, 27 unattached declarations.

У Support четыре повторно смонтированных объявления: GET/POST
`first-contact-assessments` и GET/POST `sla-escalations` доступны по разным v1 и
v2 SDK mount paths. Это не exact method/path duplicate. Static exact duplicate
groups во всех трёх источниках равны нулю; runtime duplicates/shadowing требуют
actual receipt. 91 Support diagnostics включают 64 middleware/unresolved mounts,
14 factory mounts, 10 factory exports, 2 scoped name collisions и 1 computed
registration. Три unresolved endpoint instances: catch-all `/{*splat}` с conditional
registration, dynamic MSTO path и computed ticket-relations method/path.
Auditor даёт 16 native conditions и одну unsupported-native diagnostic; отсутствие
Express registrations не означает отсутствие API.

## Владельцы, решения и потребители

Technical owner здесь означает координату реализации, а не назначенного человека.
Domain owner известен только при реальном `PolicyRoute.binding.policy` и остаётся
декларацией policy, не доказательством выполнения guard. Tags, названия handlers,
dependencies и `response_class` не определяют ACL, бизнес-владельца или публикацию.

Product routes имеют `candidate` только на основании actual identity и default-off
composition. Другие строки получают `needs-owner-decision`; `supported_external`,
`internal`, `legacy`, `integration` не назначаются по имени пути. Нужны решения
владельцев доменов о поддерживаемом контракте и судьбе старых surfaces.

Consumer map переиспользует `inventory-api-consumers.mjs`. Точное совпадение shared
Core transport method/path является source candidate, а не runtime request или
доказанным reachability. Source hash/line и confidence сохранены. Dynamic paths,
native calls с redacted origin, неизвестные methods и wrappers не угадываются.
Support/Auditor/mobile/external consumers остаются unknown, если нет отдельного
источника. Сопоставление не доказывает отсутствие других потребителей.

## Current protocol appendix

Исторические 44 special passports и 31 integration comparator сохранены как
источник evidence. Новый JSON сравнивает каждый исходный file hash с текущим pin,
показывает drift и сопоставляет method/path/endpoint с текущей регистрацией.
Совпадение одного файла сохраняет source facts; оно не подтверждает текущие
admission/dependencies/tenant semantics. Изменившиеся файлы требуют review.

Explicit `operationId` и generated `unique_id` публикуются раздельно. Generated ID
не выдаётся за явно утверждённый контракт. Product identity/method multiset parity
заменяет исторические фиксированные числа, а не вводит новый oracle на 1706.

Первый ROOT actual run дал 24 PASS и один repeat FAIL: default FastAPI generator
выбирает suffix через `list(route.methods)[0]`, поэтому multi-method generated IDs
меняются между изолированными процессами при неизменном app. R3 сохраняет оба raw
exports до comparison assertion и raw observed IDs без переименования. Общий
comparator допускает только варианты default generator по точному reviewed
`fastapi/utils.py` SHA `0d7d15ae73307d5b19c51cfc222b50e36736fbef9f0f398566479131947650ca`,
actual function identity, отсутствующему explicit ID и полному registered method set.
Prefix, методы, порядок, path, source, policy и остальные поля обязаны совпадать.
Custom/explicit/single-method IDs, поддельный basis и несогласованные IDs внутри
одного multi-method route не получают исключения. `rawByteIdentical` и hashes
публикуются отдельно от validated registration equivalence; byte identity свежих
exports не заявляется. `--check` требует byte equality для тех же frozen inputs.

Для native Auditor есть ограниченный reviewed addendum по точному source hash:
`/ws/terminal` WS, `/api/ask` SSE, `/api/export-work` binary gzip, multipart upload,
method-unspecified `/health` и prefix redirect. Это source facts, не actual dispatch.
Фабрики Support, dynamic SSE, middleware/static/catch-all/proxy/webhook/industry
поверхности вне доказанного passport chain перечислены как unknown. Ноль найденных
SSE/route declarations не означает отсутствие таких dispatch paths.

## Support live selected-source correspondence

ROOT выполнил read-only сверку 30.10.2026 22:43 UTC: стабильные CID/image/start,
два одинаковых чтения, Node `v22.23.2`, 455 выбранных путей, 5 783 116 bytes.
Image `sha256:759a2db4d7a8bc5dd98c14f4fba98121696cc0c1cee7dec81d7425e38e3127b8`;
CID `5ad8c51dbe69d52b4ee3aaa9c133b94f13fde20b07be72f1db41d9c815c51ebe`,
start `2026-10-25T22:55:42.016479959Z`.

С baseline `09c221c4b5135984173e3a924fd38f65cc208637` совпали 448 JS-файлов;
`package.json` и `package-lock.json` отличаются. С candidate `a6a109c9` совпали 445;
дополнительно отличаются `ticket-commands.js`, v1 `tickets.js`, v2 `sdk-tickets.js`.
Пять новых candidate files отсутствуют в live/reference union. Причина manifest
drift не установлена; baseline `9564` и common copy не считаются actual baseline.

Evidence в ROOT `.artifacts/full-api-continuation-20261030/`:
`rushydro-support-source-snapshot.json`, `support-source-parity.json`,
`support-source-process.json`, `read-only-support-source-snapshot.py`.
JSON фиксирует SHA receipts. Охват только selected tracked scripts JS/manifests;
runtime-only/untracked/shared/frontend не перечислены. App, DB и runtime requests
не использовались. Полная Support source/runtime parity и frontend v844/public
1.2.858 correspondence не доказаны.

## Воспроизведение и drift

`clearledger/scripts/current-surface-registry.py` является composer existing tools,
не новым scanner. Default mode строит static из pinned Git blobs; optional ROOT
actual/consumer/overlap inputs должны иметь соответствующие revision/hash/guard
provenance. Ошибочные, stale, blocked или смешанные receipts отклоняются.
`--check` пересобирает тот же состав и требует byte equality с JSON.
R2 также проверяет exact consumer producer file/Git SHA, ordered manifest SHA/
files/lines и все summary counters. Raw input SHA256/bytes сохраняются в receipt;
данные читаются одним ограниченным чтением. Runtime/tool sources после R2 freeze
не меняются до ROOT review; controls выполняет ROOT.

Limits: 10 000 source files/service, 64 MiB selected source/service, 10 000 surface
и consumer rows, 16 MiB/input/output, 30 секунд/Git call, 240 секунд/composer.
Temporary staging удаляется context manager; зависимости не устанавливаются.
Core actual export ограничен 120 секундами/call и deny guard для SQL/network/process/
writes/secrets; actual tests и exports выполняет ROOT после frozen review.

## ROOT acceptance receipts

ROOT принял R3 31.10.2026 для указанных frozen pins. Итоговый JSON:
13 462 209 bytes, SHA256
`ff144d91c4c9f453736017cb1623ee43dd17f52fac2d54c20ddd86347bce88cf`.

| Проверка / наблюдение | Результат |
|---|---|
| Controls | 24 ранее прошедших + 17 новых = 41 различных control в нескольких сериях, не один run41 |
| Новая серия | ID controls 2 PASS; affected repeat 1 PASS; composer 7 PASS; overlap controls 7 PASS |
| Actual Core | 1706 operations, 15 curated, 1 WS, 1 mount, 0 unresolved, 0 duplicates |
| Весь dated snapshot | 2491 surface row; 15 candidate, 2476 needs-owner-decision |
| Support / Auditor | 737 static + 3 unresolved + 27 unattached / 16 native candidates + 2 manual source rows; не actual |
| Actual match-only overlap | 109 literal-precedes-parameter, 24.068s; остальные поля exact, 12 approved ID variations |
| Consumer AST | Node22.23.2 / TS5.9.3, 10.372s; 5267 records: 1460 shared, 43 native, 3764 wrappers; 0 omitted/diagnostics |
| Consumer correspondence | 640 surface rows с exact method/path source candidates; не 640 доказанных runtime consumers |
| Passports | 58 unchanged-file source facts / 17 drift; без policy recertification |
| Composer / same-input check | PASS 159.626s / PASS 159.944s; frozen code/source pins после запусков совпали |

Raw Core first SHA `a4f97aad3c92b4cbc2a7213e7276d6c97b054d5fb5980f8cae35b98f371bde95`,
repeat SHA `72ec26b79a5473a6c5c06bafc42a48353b60d1c0f06b8e3e8f821a783468839d`:
`rawByteIdentical=false`, `allOtherFieldsExact=true`, `equivalent=true`, 12 enumerated
generated-ID variations. Raw consumer input SHA
`3a6dfea50dd06397e04a82e96985025335de44544fc3b3c9db9a5645dea54269`, 4 162 879 bytes.

Первый composer был stopped/reaped (`exit=-15`, `free_floor`, 137.754s) до записи
нового report: это не PASS. ROOT изменил только свой local resource profile с
9 GiB до 8 GiB free floor / 512 MiB no-SQL planning и возобновил composer/check
в owned TMPDIR. Оба завершились; уже принятые controls/overlap/consumer не повторялись.
Чужая очистка, удаление прежних БД, GUC/dependency/production changes не выполнялись.
Temporary TS link удалён; worker не запускал runtime/app/tests/SQL.

Evidence ROOT: `.artifacts/root-current-registry-review-20261031/`:
`controls-1.log`, `r3/controls-processes.json`, `r3/remaining14/controls-processes.json`,
`tail-r3/processes.json`, `tail-r3-compose-retry/processes.json`.
Own raw captures и repeat comparison:
`.artifacts/current-surface-registry-20261031/root-acceptance/`.
Proposals r1/r2/r3 сохранены; report-only corrected copy уточняет старый текст
о raw byte identity без изменения шести accepted code pins или static input.

## Открытые предметные шаги

1. API owners: назначить human/domain owners, decisions и подтверждённых consumers
   всем неизвестным строкам; определить судьбу internal/legacy/integration surfaces.
2. Support/Auditor owners: подготовить отдельный контролируемый actual exporter
   без server entrypoint, scheduler/listen/AI/delivery; не заменять actual fake router.
3. Protocol owners: review changed passport chains, dynamic factories/SSE, uploads,
   binary/proxy/webhook/industry contracts и current operationId/schema/errors/scopes.
4. ROOT: при интеграции M14/P6/Awebhook/Bworklinks проверить source drift и обновить
   срез на новом pin тем же pipeline после приёмки P7; новый scanner не нужен.
   Этот frozen snapshot не является final composition CI.
5. M00: завершить полное runtime/source correspondence отдельно, включая manifest
   drift Support и frontend 858. Этот реестр не закрывает live preservation или выпуск.
