# M01: offline runtime registry Core

Опора: `e1cb1a53ee0ba90a74805d0105d2358974660dcd`, собственная ветка
`agent/api-runtime-inventory-20261030`. Предыдущая remote ветка M06 сохранена.

## Назначение и границы

Статическая основа прочитана read-only: deploy `scripts/api_inventory.py`,
`docs/api-inventory-tool.md` и локальный M01 `summary.md`. AST scanner не импортирует
приложения; ASGI mount, фабрики/computed registrations, framework routes и некоторые
условные поверхности явно остаются unknown. Новый инструмент дополняет результат
обходом реального route tree, не копирует AST parser и не определяет права.

`clearledger/scripts/export-runtime-inventory.py` после source checkpoint и
одобрения координатора реализует следующий порядок:

1. CLI launcher запускает отдельный Python process из нового пустого cwd, с
   полностью заменённым окружением и минимальными synthetic settings. Никаких
   .env/реальных issuer/keys/секретных каталогов. SOURCE_REVISION — явный SHA;
   композиция APP_ENV=dev, default-off partner OAuth/API/docs. Флаги входят в provenance;
   это выбранная source-композиция, не снимок работающего РусГидро.
2. До импорта Core устанавливаются audit hooks: deny socket/DNS, subprocess,
   чтение .env/secret paths/key files и записи. Реальный app.database импортируется
   без подмены Base, на заведомо synthetic loopback:1 URL; do_connect real engine
   также запрещён. Затем импортируется настоящий `app.main`, без lifespan/startup,
   HTTP/WS запросов и вызова main.openapi. Base/models/engine настоящие, не fake.
   Отказ импорта — failure с очищенными exception type/module/relative frame,
   без exception text/locals/полных путей и без замены fakeapp.
3. Walk настоящих app.routes с сохранением registration order: APIRoute,
   Starlette Route/WebSocketRoute, Mount рекурсивно; циклы/opaque/unknown route
   classes — unresolved/manual review. Строки mount/path строятся по tree, не nginx.
4. Каждая операция: protocol/method/path/mount chain, source module/qualified
   endpoint, route class/name, response_class и recursive qualified dependency names. Параметры/defaults,
   closures, app.state и значения конфигурации не выводятся. Только реальные
   PolicyRoute получают metadata реального binding.policy, без выполнения guard.
5. Curated 12 определяются реальными PolicyRoute mounted product app; остальные
   legacy/public/internal остаются candidates с неизвестным business owner и
   ручной классификацией. Имена URL/dependencies не становятся доказательством ACL.
   Отдельно exact duplicates, parameter-shape и literal/parameter overlap candidates, mixed-method paths,
   unresolved mounts и registration order; никаких удаления/автоматических gates.
6. JSON stdout и human Markdown report строятся детерминированно: без timestamps,
   absolute private paths, secrets, реальных пользователей и полного OpenAPI.
   Сравнение с JSON статического inventory — множества method/path и diagnostics,
   с явными static-only/runtime-only; исходный AST scanner исполняется отдельно.

Зависимости и response_class — факты registry, не доказательство прав, MIME или
фактического SSE/file streaming. Никакой классификации ACL по имени URL/функции,
изменения gates или удаления маршрутов не производится. Строки с неизвестным
business owner/class требуют ручного review.

## Публичные ресурсы и история безопасных отказов

Первый actual import был **BLOCKED / EXIT2** на `ZoneInfo("Europe/Moscow")` из
store_documents: guard запрещал чтение вне Python/server roots. Следующий child
остановился на openpyxl → stdlib mimetypes. Координатор отдельно согласовал ровно
два read-only OS ресурса: `/usr/share/zoneinfo/Europe/Moscow` и `/etc/mime.types`.
Проверяются точный realpath, TZif magic / MIME shape; в provenance входят логические
имена и SHA256, без содержимого. Соседние Europe/London и /etc/hosts запрещены.
Весь /usr/share или /etc не разрешался; ключи/.env/секретные каталоги запрещены.

Ещё один actual import дошёл до registry, но библиотека поймала read denial при
importlib.metadata → zipfile: стандартный отсутствующий ZIP entry из sys.path.
Экспорт правильно остался BLOCKED, хотя исключение было обработано библиотекой.
Вместо разрешения нового файла child запускается с `-I -B`, import path сужен до
реального server и существующих каталогов interpreter libraries. Каждый повтор
исполнялся новым процессом; прежние отказы не скрывались и не сбрасывались внутри child.

Любой timeout/OSError/nonzero/malformed child результат даёт очищенный BLOCKED JSON
и EXIT2, включая nonzero с формально успешным JSON. Child stdout/stderr/argv и текст
исключения не пересылаются; известный import failure проходит whitelist очистку
типов/модулей/relative frames. Даже восстановленный библиотекой guard denial
инвалидирует весь экспорт. Родитель пишет только явно заказанный local Markdown;
child не имеет writable paths. Сеть, DNS, SQL и subprocess внутри child запрещены.

## Проверенный результат

На неизменённых Core исходниках `e1cb1a53ee0ba90a74805d0105d2358974660dcd`:

| Наблюдение | Значение |
|---|---:|
| Actual registrations (method/path) | 1703 |
| Настоящие curated PolicyRoute | 12 |
| Mount / WebSocket operations | 1 / 1 |
| Exact duplicate groups / unresolved route tree | 0 / 0 |
| Одинаковые parameter shapes | 0 |
| Literal/parameter overlap candidates | 109 |
| Общие пути разных методов/протоколов | 203 |

109 candidates и 203 shared paths **не являются 312 ошибками**: порядок сохранён
для отдельного ручного разбора, общего доказательства shadowing нет.

Статический scanner повторно запущен read-only по этому же Core SHA: 557 файлов,
1691 endpoint, 7 diagnostics, 8 unattached declarations. Runtime comparison:
`sourceRevisionMatches=true`, 1691 common pairs, 0 static-only и **ровно 12 runtime-only**:
mounted curated операции `/api/v1` для objects/monitoring, equipment, counterparties,
contracts, documents и version content. AST parser не дублировался и не менялся.

Сравнение с настоящим историческим M01 JSON `5ce5779b20151a8d04de7d3a1681d1862a80d9dd`
явно показывает `sourceRevisionMatches=false`, 1663 common / 40 runtime-only /
0 static-only. Эти 40 нельзя представлять как пропуски статического parser на
одинаковом исходнике: туда входят изменения источников между SHA.

| Статус | Проверка |
|---|---|
| PASS | Финальный opt-in прогон после review: 20 tests, 23.401 с; synthetic trees, настоящие audit denials, launcher failures, actual Core repeat/static comparison |
| PASS | Два actual child экспорта byte-for-byte одинаковы при synthetic ambient .env/SECRET_KEY/DATABASE_URL sentinels; sentinels и private paths не попали в JSON |
| PASS | После последней точечной обработки malformed failure envelope: 4 launcher tests, 0.003 с |
| PASS | Final actual CLI EXIT0: real Base, APP_ENV=dev, no lifespan/requests/OpenAPI, 0 denied attempts; local JSON + Markdown |
| FAIL, сохранённая история | Первые безопасные import attempts BLOCKED на timezone/MIME/metadata probing; fake success не выдавался |
| SKIP | Без opt-in actual Core test пропускается; pure suite и negative guard tests доступны независимо |
| SKIP | SQL/HTTP endpoint acceptance, deployment/gateway/runtime flags, security scan и consumer ownership |

Локальные артефакты `.artifacts/runtime-inventory/`: `runtime.json`, `runtime.md`,
`static/inventory.json`, `historical-comparison.json` и отдельные blocked JSON/MD.
Генерируемый каталог маршрутов не публиковался по HTTP или в Git.

## Воспроизведение

Из корня Ledger, в Python с зависимостями Core (проверено root venv Python 3.13):

```bash
python -B -m unittest discover -s clearledger/scripts/tests -p test_runtime_inventory.py -v
python -B clearledger/scripts/export-runtime-inventory.py \
  --source-revision e1cb1a53ee0ba90a74805d0105d2358974660dcd \
  --static-json .artifacts/runtime-inventory/static/inventory.json \
  --markdown .artifacts/runtime-inventory/runtime.md > .artifacts/runtime-inventory/runtime.json
```

Для actual repeat test задать `RUN_CORE_RUNTIME_INVENTORY_TESTS=1` и абсолютный
`RUNTIME_INVENTORY_STATIC_JSON` на настоящий static inventory. Статический файл
создаётся прежним deploy `scripts/api_inventory.py --source Core=<server> --output <own-output>`;
output должен находиться вне server. Никакая TEST_DATABASE_URL или SQL window не нужна.
SourceRevision задаётся явно оператором; output не подтверждает live/deployed revision.

## Приёмка и ограничения

Pure synthetic ASGI trees: nested/repeated mounts, factory/dynamic registration,
WS, duplicates/parameter names, dependencies, real PolicyRoute metadata,
opaque mounts/cycles/unknown classes, deterministic/safe serialization.
Отдельные subprocess negative controls: .env/secret-file read, socket/DNS,
SQL do_connect до DBAPI, child process, no-startup sentinel. Дополнительные controls
также запрещают direct exec и raw sqlite3.connect до создания соединения.
Launcher controls
проверяют timeout/OSError, malformed JSON и nonzero даже с success envelope,
очистку private frame paths и лишних полей failure metadata.

Владение: только exporter, новые pure tests и этот документ. Runtime/router/policy/
ORM/auth/compose/env не меняются. SQL и реальные интеграции отсутствуют.
Это один M01 slice: consumer ownership, все композиции и security review не закрыты.
Middleware-generated OPTIONS, redirects, opaque static/proxy dispatch, Host/custom
route classes и динамически возвращаемый SSE не гарантируются этим registry walk.
Overlap-анализ не является полным решателем regex или доказательством ACL/доступности.
CPython audit controls предназначены для этого offline импорта проверенных исходников;
здесь не заявляется изоляция от произвольного вредоносного native extension.


## Независимая проверка общего кандидата

Координатор перенёс d10c921d как7896039f. Собственный static scanner получил
1691 endpoint /557files /7diagnostics /8unattached, sourceRevision7896039f,
server snapshot SHA2564ebd8d26e5394f9e1af5d35c0b64ee367af9c99b32fed08ed5afc8107d896f71.
Полный opt-in набор **20PASS за22.742с**, без SKIP; два actual Core child
экспорта повторно совпали byte-for-byte и сохранили12curated/1WS.
Во время этой проверки менялись только документы; server source оставался
тем же. Это registration proof выбранного состава, не приёмка запросов/ACL
или развёрнутого пространства. Сеть и SQL для этого прогона не использовались.
