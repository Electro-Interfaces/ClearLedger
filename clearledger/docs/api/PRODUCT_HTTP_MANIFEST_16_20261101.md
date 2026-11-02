# Manifest product HTTP: 15 GET + createContract

Статус: **WRITTEN_NOTRUN, авторское статическое свидетельство**. Это manifest текущего product child application `/api/v1`; общая цель API **M00–M19+11** сохраняется без сокращения. Готовность всего API этим документом не утверждается.

Точная база: `47da804bb075e5d627cf6064db039185f5ca9c0b`. Текущий SOURCE/test metadata correction: `9a29ce1e3a4c814499da500f4faf93c97720d5d5`; tree: `6d613ff92bf0890ea3ad1579ab473c20bcd3283d`. Два обновлённых документа образуют отдельный docs-only child; его HEAD/tree записываются только в локальный отчёт после коммита. История `b1c5fcec` → `93ba8131` сохранена без переписывания; прежняя авторская enum-ревизия **не была интегрирована**. По корректировке ROOT общий ProductAllow сохраняет исходный строгий const GET.

Полный набор: **16 операций на 15 paths: 15 GET и 1 POST**. В исходном GET subset 11 операций допускают partner+service, четыре допускают только partner. `partner` здесь означает пользовательский партнёрский grant, `service` означает machine grant. POST учитывается отдельно.

| Метод | Path child application | operationId | Scopes | Principals |
|---|---|---|---|---|
| GET | `/contract-types` | `getContractTypeMetadata` | `contracts:read` | partner + service |
| GET | `/contracts` | `listContracts` | `contracts:read` | partner + service |
| POST | `/contracts` | `createContract` | `contracts:create` | partner + service |
| GET | `/contracts/{contractId}` | `getContract` | `contracts:read` | partner + service |
| GET | `/contracts/{contractId}/documents` | `listContractDocuments` | `contracts:read, documents:read` | partner |
| GET | `/contracts/{contractId}/objects` | `listContractObjects` | `contracts:read, objects:read` | partner + service |
| GET | `/counterparties` | `listCounterparties` | `counterparties:read` | partner + service |
| GET | `/counterparties/{counterpartyId}` | `getCounterparty` | `counterparties:read` | partner + service |
| GET | `/documents` | `listDocuments` | `documents:read` | partner |
| GET | `/documents/{docId}` | `getDocument` | `documents:read` | partner |
| GET | `/documents/{docId}/versions/{versionId}/content` | `downloadDocumentVersion` | `documents.files:download, documents:read` | partner |
| GET | `/equipment` | `listEquipment` | `equipment:read` | partner + service |
| GET | `/equipment/{equipmentId}` | `getEquipment` | `equipment:read` | partner + service |
| GET | `/objects` | `listObjects` | `objects:read` | partner + service |
| GET | `/objects/{objectId}` | `getObject` | `objects:read` | partner + service |
| GET | `/objects/{objectId}/monitoring` | `getObjectMonitoring` | `monitoring:read, objects:read` | partner + service |

`POST /contracts` уже существовал на точной базе. Его metadata: `contracts:create`, partner+service, `resourceStage=create-newborn`, без `databaseAuthorityKinds`, readiness `candidate`. Это отдельный policy stage; проверка metadata без SQL не означает, что реальный CREATE обходится без SQL. Позитивный POST через старый GET fake verifier не вызывается. Полный real HTTP POST и SQL-проверки выполняет ROOT отдельно; здесь их результат не аттестуется.

Итоговый production diff к точной базе содержит только одну строку description у именованной GET-операции `listContracts`: `Allow: GET.` исправлено на `Allow: GET, POST.`. По корректировке ROOT `ProductAllow` восстановлен **точно к EXACT47da**, с `const: GET` и `example: GET`. Существующий `ProductContractsAllow` сохраняет отдельный `const: GET, POST`; response aliases и `knownPaths.methodOverrides[/contracts]` неизменны. Общего enum и нового mapping нет. Для DELETE на `/contracts` ожидается ровно `Allow: GET, POST`, на остальных 14 известных paths ровно `Allow: GET`. Новый metadata oracle проверяет оба точных const, перекрёстные отказы и malformed values, ссылки aliases и корректный фрагмент listContracts description без устаревшей строки.

Общий oracle `assert_product_manifest` в `test_product_http_profile.py` фиксирует literal tuples method/path/id исходных GET15 и whole16 для canonical schema и registry. Отдельный policy oracle сохраняет serviceGET11/user-onlyGET4 и проверяет POST create-newborn. Шесть live test-модулей используют точный whole manifest вместо общего len15. Старые положительные и отрицательные GET loops выбирают записи по actual methods; все прежние проверки успешных ответов, отказов, body, headers, schemas, references, nullability и отсутствия domain effects сохранены. Общий 405 probe использует DELETE на всех 15 известных paths и точные per-path aliases.

Имена старых test defs с `12`, `fifteen` и `fourteen` сохранены для истории. Их GET scope остаётся исходным GET15, а whole scope проверяется точным manifest16. Метаданные security/readiness теперь сопоставляются со всеми объявленными methods; строгие per-path Allow consts, listContracts description и неизменность contracts aliases имеют отдельные assertions.

Статическая проверка: семь Python-файлов скомпилированы в памяти без exec. После обратной замены только listContracts description весь `app.py` равен точной базе **побайтно и по AST**. Другие 14 GET decorators и handlers побайтно неизменны; весь handler listContracts и все остальные keys его decorator сохранены. ProductAllow и весь `_describe_http_responses` точны базе. Для шести test-модулей полный AST равен базе после обратной замены перечисленных изменённых test defs и удаления только новых helpers/test/constants: **210 определений неизменны**, изменено 15 определений, добавлено четыре, fixtures неизменны. Точные SHA-256, 14 per-GET byte pins и inverse fingerprints находятся в JSON рядом и окончательном локальном отчёте.

Ни приложение, ни библиотеки, ни tests/helpers не импортировались и не вызывались. Collection/pytest, SQL/PG, HTTP, Docker, сеть/SSH, Node/browser/install, exporter/SDK/build не запускались. **Автор не заявляет SOURCE_PASS**: независимое SOURCE review назначает ROOT после immutable freeze.

Текущие и исторические residuals (только чтение; ни один не объявлен зелёным):

- `clearledger/server/tests/test_partner_dx_metadata_20261031.py`: normalize_app сравнивает полный AST исторической базы после узкого удаления GET summary/description и success examples; замена одного count 15 на 16 не согласует новый POST и остальные интегрированные изменения. Оставлен неизменным; текущая совместимость не доказана; отдельная работа после решения ROOT.
- `clearledger/server/tests/test_partner_dx_examples_20261031.py`: Выборка method == get и прямых декораторов operation корректно сохраняет GET subset; число 15 не означает полный manifest после добавления POST. Полный запуск валидаторов/DTO в этой задаче запрещён. Оставлен неизменным; не объявлен зелёным и не расширен на POST.
- `clearledger/server/tests/model_declaration_ownership_approved.py`: Ожидание operations=15 связано с историческим frozen source/runtime/pins и собственной approval boundary; это не live whole-manifest oracle этой задачи. Не менять, не запускать, не репинить; историческое свидетельство не доказывает текущую зелёную проверку.
- `clearledger/scripts/verify_partner_dx_metadata_20261031.py`: EXPECTED_OPERATIONS и operations() описывают ровно 15 прямых GET decorators; normalize_app затем требует равенства полного AST базы вне узкого whitelist документации. Новый router.operation POST не попадает в GET inventory, но остаётся в полном AST guard. Только чтение; модуль не импортирован и helper не вызван; SDK/examples/exporter/pins не изменены.

Описание `listContracts` теперь согласовано с contracts alias и mapping: `Allow: GET, POST`. Этот ранее отмеченный residual устранён; четыре исторических DX/M16 residuals выше остаются без изменений и без green claims.

Runtime/auth/routes/transactions и остальные production файлы не менялись. `test_partner_contract_http_create.py/current70`, RootPGfix91ed, kernel/identity/authority/consumer/schema/config, SDK/examples/exporter/scripts/pins и fixtures оставлены без правок. Новые методы и 206 не обещаны; activation и generated SDK readiness не заявлены.

Итоговая область составляет ровно девять разрешённых путей: семь SOURCE/test файлов и эти два документа. Локальный окончательный отчёт: `.artifacts/product-manifest16-author-20261101/REPORT.md` и `.json`. Он фиксирует HEAD/tree уже созданного docs-only child и хеширует девять файлов, не включая собственные байты в коммит или циклический хеш. Два исходных коммита сохранены, metadata correction и docs-only child добавлены следом. Все коммиты локальные, hooks OFF, сообщения на русском с `[skip ci]`; push/PR/merge/rebase не выполнялись.
