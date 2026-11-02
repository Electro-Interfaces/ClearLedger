# РусГидро: конечный DX-план network-state · 01.11.2026

Source-only состав поверх `24af3535565381d46f9e51c2841c2feb80b1c8f3`
(tree `8070708f272a31e75de65c02e8eb2615562978fe`), Task `task_4464f21bf452`,
Dispatch `ctx_5edba5078c21`. Один автор, максимум 17 явно назначенных путей;
runtime/DTO/owner/handler/auth/policy не меняются. Цель — только методы, нужные
РусГидро: добавить `GET /api/v1/monitoring/network-state`, operationId
`getNetworkState`, к developer contract с сохранением прежних 17 операций.
Результат: 18 операций, 17 GET + 1 POST на 17 путях; семь wire consumers.

## Границы свидетельств

Root принял backend на базе 24af: 25 старых + 50 новых = 75 уникальных случаев,
16 definitions, 225 passed phases, 0 errors/failures/skips, 69.593989256 s.
Основание — Root-сообщение `msg_11824f7b96be` и Root-owned
`.artifacts/rushydro-network-joint75-root-acceptance-20261101.json`; автор DX
этот runtime не исполнял и приватный RAW не читал. Сообщённый охват: Source 566
blobs, actual Authlib/SQL/bytes, timeout/SQL/cancel/reset/cap10001, native341/347,
cleanup pool/clients/locks/own resources, foreign unchanged. Первая серия
25 PASS + 50 setup ERROR — отдельная историческая неуспешная попытка, её не
переписываем и не складываем с принятой серией.

Здесь только Source-патч и статические проверки автора. Generated `.d.ts` и
canonical JSON bundles остаются прежними до отдельной генерации Root. Написанные
тесты не объявляются выполненными. Production SLA, CI, пилот, браузер и весь API
не приняты; исходные M00–M19 и 11 критериев остаются открытыми историческими
ссылками, не текущим all-API gate. Новый аудит или inventory 2491 сюда не входят.

## Конечная матрица до freeze

| ID | Проверка автора без исполнения проекта | Ожидание |
|---|---|---|
| S1 | BASE/parent, clean start, diff allowlist, замороженные blobs | Только перечисленные пути, максимум 17; прочие tree entries неизменны |
| S2 | Шесть явных определений manifest: app decorators, exporter, generator, profile oracle, docs-native oracle, quickstart table | Одинаковые 18 method/path/id; все старые 17 сохранены, ровно один новый GET |
| S3 | Python AST parse + compile code objects без exec для изменённых Python | Синтаксис; app runtime AST прежний после исключения doc/description/example metadata только нового route |
| S4 | Собственный stdlib разбор literal JSON примеров и DTO AST | Пять полей item, все required nullable/context, восемь status keys; app/guide/consumer fictional, old40 JSON сохранены |
| S5 | tsconfig JSON и текстовый TS контроль | Старые шесть consumers + новый; exact query/response/status, continuation/restart/access change; 12 отрицательных примеров |
| S6 | Статический diff checker и guards | Pin24af; только Literal alias NetworkStateStatus и три Field(alias) underscore keys; строгий bounded16 GET coverage, CREATE/options явно исключены; старые nullable/link checks сохранены |
| S7 | git diff --check, named-path local commit с hooks off | Один русский `[skip ci]` commit, parent24af; без push |

Статически сверены: 16 изменённых назначенных файлов (monitoring.py не потребовал
правки), шесть совпадающих manifests, неизменный runtime AST app, шесть Python
AST/compile code objects без exec, tsconfig с 7 consumers, 12 текстовых TS
отрицательных примеров. Собственный stdlib-разбор подтвердил полноту нового DTO,
совпадение fictional JSON app/guide, сохранение всех 40 старых JSON-блоков и два
новых, 102 существующие локальные ссылки восьми guide pages. Это Source-проверки,
не запуск checker, Node, TSC или тестов приложения.

## Конечные проверки Root после передачи

| ID | Действие только Root в offline isolation | Приёмка |
|---|---|---|
| R1 | Штатный exporter и parity profile без socket/env/DB I/O | Exact18 manifest; schema examples и локальные refs валидны, old17 semantics сохранены |
| R2 | Штатный generator generate, повтор generate, freshness check | Детерминированный `.d.ts`; bundle pins и SHA записаны Root, remote resolution запрещён |
| R3 | Официальные Node generation tests (прежние шесть + новый) | Результат каждого; manifest missing/renamed/extra method negatives, old drift/ref/offline guards сохранены |
| R4 | TSC по owned tsconfig после R2 | Все семь consumers, включая отрицательные `@ts-expect-error`; без сетевого SDK |
| R5 | Штатный guide checker и целевые schema/profile/docs projections | 8 страниц, 16 bounded GET regions: old15 + network; old40 JSON +2 новых; полный18 manifest отдельно; guards/factory/verifier/flows прежние |

Эта конечная передача не поручает новый runtime/PG прогон. Если Root отдельно
исполняет целевые тесты, его результат и среда фиксируются отдельно от Source
проверок автора. Поведение backend уже принадлежит принятой Root серии 75/225.

## Семантика и ограничения примеров

Новый метод требует objects:read AND monitoring:read, current user/approved service,
energy и независимый objects ACL. Только пять нефинансовых полей item, summary
по M до страницы, текущий каталог, МСК/asOf и opaque UTF-8 ID. Signed cursor
проверяется после текущей авторизации, сохраняет filters/pageSize/operation/access
boundary, при 400 нужен restart; 401/403 останавливают обход, 503 без partial.
Седьмой consumer не выполняет запросов. Иллюстрации используют только вымышленные
данные и placeholders; финансовые поля, snapshot, full contract writes и admin
доступ не добавляются. Полное [описание](../partner/recipes/monitoring.md#getnetworkstate)
и [SDK scope](../PARTNER_SDK_TYPES.md#семь-конкретных-consumers) связаны с этим планом.
