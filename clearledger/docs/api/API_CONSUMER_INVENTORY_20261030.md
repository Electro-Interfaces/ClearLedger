# M01/M12: каталог клиентских transport callsites

Дата: 30.10.2026. Источник: production-файлы текущего `src` на базе
`06e02207c29651682530309bea1a4157f48b3168`. Инструмент и отчёт подготовлены в ветке
`agent/api-consumer-inventory-20261030`; прежняя `MagLook/gar` сохранена.
Runtime-код, прежние tests и отчёт intake upload не менялись.

Найдено **1459 shared callsites**, **43 native AST-записи** и **3769 unresolved
service/local wrapper candidates**. Это статический каталог для выбора предметных
проверок, без автоматических migrations и выводов о дефектах backend routes.
Кандидат в wrapper может оказаться storage/helper/utility, а не сетевым consumer.

## Источник и воспроизводимость

- Scope: 1147 TS/TSX/JS/JSX-файлов, 304567 текстовых строк. Счётчик строк использует
  разбиение CR/LF, включая последнюю пустую строку после завершающего перевода строки.
- Полный sorted manifest: относительный путь, SHA-256 исходных байтов, число строк.
  Его canonical JSON SHA-256:
  `74c8e02a5a6a5664ff9641f852f3766404a71094c1254dda5e090bebe06faa4e`.
- Независимая проверка `git ls-tree` подтвердила состав 1147/1147; отдельный
  `git cat-file --batch` сравнил **все 1147 blobs** указанного pin с текущими
  байтами и SHA manifest: 0 расхождений. Это проверка исходника вне инструмента.
- `sourceRevision` в JSON является явно переданной меткой, а не результатом вызова
  Git самим инструментом. Manifest отражает фактически прочитанные байты.
  Public JSON также содержит SHA генератора и TypeScript version `5.9.3`.
- Canonical private JSON SHA-256:
  `f5b7a0b89c9a32401fd5423bdbd214903feae4ab1aa3f990270cc17a07681c69`;
  bounded paired JSON SHA-256:
  `f758ad6b80c926cb2f1b34d8fd4c4145b559e763b9e4c33a611abf8d33ecce36`.
- Исключены 53 test/declaration-файла и два дерева каталогов; внутрь исключённых
  деревьев инструмент не заходит. Symlinks не разыменовываются и отмечаются в
  private exclusions; в фактическом scope их нет. Symlink самого `src` отклоняется.
- Синтаксических diagnostics: 0. Семантическая проверка приложения здесь не проводится.

[Инструмент](../../scripts/inventory-api-consumers.mjs),
[pure fixtures](../../scripts/tests/inventory-api-consumers.test.mjs),
[bounded summary JSON](API_CONSUMER_INVENTORY_20261030.json).
Полный manifest, 5271 callsite records и diagnostics/exclusions остаются только в
own worktree `.artifacts/private/api-consumer-inventory-06e02207.json` с режимом 0600.
Проверка pin сохранена рядом в `api-consumer-pin-verification.json`.
Эти private artifacts игнорируются Git и в коммит не включаются.

## Категории и unknown

| Категория | AST-записей | Что означает |
|---|---:|---|
| Shared | 1459 | Импорт конкретной transport-функции из `services/apiClient`, включая alias/namespace |
| Native fetch | 39 | Unshadowed native reference, включая простые const aliases |
| Native WebSocket | 2 | Конструирование объекта протокола, не HTTP-запрос |
| Native XMLHttpRequest | 1 | Конструирование объекта, не доказательство отправки |
| Native XMLHttpRequest.open | 1 | `.open`, связанный с const binding конкретного native-конструктора |
| Service/local candidates | 3769 | Unresolved обращения из 166 семейств, без доказательства сети/метода/URL |

Девять native-записей находятся в [apiClient](../../src/services/apiClient.ts): это
реализация общего транспорта. Вне него остаются 34 записи, включая протоколы,
public/OAuth/asset/update/error-reporting сценарии. Их наличие само по себе
не обосновывает замену на общий JSON-клиент.

У 1502 shared/native записей пути распределены без пересечений:
692 static, 773 dynamic templates и 37 unknown. Unknown включает 23 call-expression,
12 identifier, один property-access и один отсутствующий аргумент конструктора.
Динамический template сохраняет известный каркас и `{dynamic}`; произвольные
address builders не исполняются и не превращаются в придуманный URL.

HTTP method известен у 1492 записей; у 10 остаётся unknown: три конструктора,
четыре spread/computed options, два входа, потенциально несущих Request, один
динамический method. WebSocket не получает выдуманный HTTP GET.
Default GET для fetch задаётся только при доказанном строковом входе и отсутствии
влияющих на method неизвестных options. Все 37/10 unknown классифицированы по
этим AST-причинам; ошибки анализа или parse diagnostics к ним не приписываются.

## Шесть доменов: heuristic, без утверждения ownership

Группы выведены из имени source-файла и очищенного pathname, а не из runtime
доступов, tenant, владельца данных или backend ACL. Группы могут пересекаться,
поэтому столбцы таблицы не следует суммировать. `unknown` сохранён явно.

| Heuristic group | Shared | Native | Unresolved candidates | Основные source families |
|---|---:|---:|---:|---|
| Объекты | 141 | 0 | 330 | [sites](../../src/services/sitesService.ts), [site](../../src/services/siteService.ts), [spaceObjects](../../src/services/spaceObjectsService.ts), [location](../../src/services/locationService.ts) |
| Оборудование | 66 | 0 | 102 | [equipment](../../src/services/equipmentService.ts) |
| Контрагенты | 26 | 0 | 24 | [reference](../../src/services/referenceService.ts), [ops](../../src/services/opsService.ts), [vendor](../../src/services/vendorService.ts) |
| Договоры | 29 | 0 | 48 | [ops](../../src/services/opsService.ts), [reference](../../src/services/referenceService.ts) |
| Документы | 175 | 3 | 421 | [docs](../../src/services/docsService.ts), [storeDocuments](../../src/services/storeDocumentsService.ts), [intake](../../src/services/intakeDocsService.ts), [developerDocs](../../src/services/developerDocsService.ts) |
| Monitoring | 67 | 0 | 124 | [perimeter](../../src/services/perimeterService.ts), [overview](../../src/services/overviewService.ts), [storageMonitor](../../src/services/storageMonitor.ts) |
| Unknown | 998 | 40 | 2790 | Семейство/назначение требует предметного просмотра |

Нулевой native count доменной эвристики не доказывает, что весь runtime домена
проходит через общий клиент. Особенно важно различать wrappers в универсальных
сервисах и потребителей helper-функций.

## Что полезно проверить следующим

Самое крупное native-семейство вне общего клиента:
[spaceAuditorService](../../src/services/spaceAuditorService.ts), 15 записей.
[voiceService](../../src/services/voiceService.ts) и
[developerDocsService](../../src/services/developerDocsService.ts) имеют по три.
Это кандидаты на отдельное сравнение auth, ошибок, base и protocol-контракта;
каталог не принимает решение об их миграции.

Отдельные транспортные wrappers:
[STS](../../src/services/fuel/stsApiClient.ts),
[MSTO](../../src/services/msto/mstoApiClient.ts),
[Tradecorp](../../src/services/tradecorp/tradecorpApiClient.ts).
Spread options сохраняют неизвестный method, а их входящий runtime call graph
этим сканированием не восстанавливается.

В unresolved-семействах велики
[analytics](../../src/services/analyticsService.ts), 649 candidates,
[tasks](../../src/services/tasksService.ts), 198,
[store](../../src/services/storeService.ts), 150,
и [storage](../../src/services/storage.ts), 144.
Последний пример показывает, почему candidates нельзя считать сетевыми вызовами.
Public JSON ограничен top-24 wrapper families, top-24 native source families
и 32 source fingerprints; фактически native families 17, fingerprints 17.
Лимит private wrapper records 5000, отброшено 0 candidates.

## AST, приватность и границы

TypeScript compiler host читает только заранее выбранные source buffers:
`noResolve`, `noLib`, без tsconfig, `.env`, package discovery и выполнения app modules.
Import origin определяется по точной import syntax и реальному lexical binding
checker: локальные `get`, одноимённые параметры и shadowed globals не объявляются
сетевыми. Поддержаны именованные aliases, namespaces и простые const aliases.
Re-exports, произвольный object dispatch, фабрики и полный межмодульный dataflow
не восстанавливаются. Local wrapper связывается только с ближайшей функцией,
непосредственно содержащей распознанный transport.

Records содержат относительные file/line/column/endLine, source SHA, SHA выражения
и очищенный pathname template. Raw expression/snippets не сохраняются. Authority,
URL credentials, query/hash values и coordinate-like segments удаляются;
не-HTTP и непрозрачные relative resources получают placeholders.
Public JSON не содержит callsite records, raw pathname, выражений и полного manifest.
Stdout содержит только ту же summary, что bounded paired JSON.

Этот каталог не доказывает полный runtime consumer ownership, набор внешних
партнёров, доступность маршрутов сервера, авторизацию или корректность данных.
Unresolved не является дефектом. Сеть, SQL, SSH, браузер, CI и app modules не
использовались; финансовая логика, demo и авторизация приложения не менялись.

## Повторение и проверки

Из `clearledger`:

```sh
node scripts/inventory-api-consumers.mjs --root . --output ../.artifacts/private/api-consumer-inventory-06e02207.json --summary-output docs/api/API_CONSUMER_INVENTORY_20261030.json --revision 06e02207c29651682530309bea1a4157f48b3168
node --test scripts/tests/inventory-api-consumers.test.mjs
node --check scripts/inventory-api-consumers.mjs
node --check scripts/tests/inventory-api-consumers.test.mjs
```

Pure fixtures: PASS 9/9. Они покрывают alias/namespace, lexical shadowing,
multiline/templates/unknown, fetch methods и spread/prototype options,
конструкторы/XHR binding, bounded wrappers, symlink exclusion, отсутствие
исполнения app source, redaction canaries, diagnostics hashing, manifest mutation,
детерминизм в разных временных корнях и permissions private output.

Два полных прохода на одинаковых source bytes дали byte-identical private JSON,
paired summary и stdout (`cmp`, exit 0). Targeted ESLint для двух новых `.mjs`
с Node globals и существующим `@eslint/js` recommended: 0 errors/0 warnings;
новый конфиг и зависимости не добавлялись. `node --check` и `git diff --check`
проходят. Общий app TypeScript/lint не перезапускался, поскольку runtime не менялся.
