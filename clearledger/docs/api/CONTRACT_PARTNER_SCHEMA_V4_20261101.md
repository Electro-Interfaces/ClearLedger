# Partner Contract CREATE: SOURCE revision0004

Пакет от `d71e4f3754efce7c911cc95cb46eb22707e8efbc`, Task
`task_59227e1bdafa`, Dispatch `ctx_b573a2312fc1`. ROOT выделил ordinal4,
`0004_partner_contract_create`, parent `0003_pulse_view_role_grants`.
Это авторство исходников, без подключения БД, импорта приложения, collection,
тестов, HTTP activation или выпуска. Runtime всех новых случаев: **NOT RUN**.

Исходный manifest SHA256:
`6fa42ed6f411e493a05904c5df46b8fa0fb56fabd0d52d82750b92a15d3ed016`.
Payloads и artifact IDs0001–0003 сохранены побайтно, `journal_format1` прежний.
Точные pins и локальная source-проверка находятся в
`evidence/partner-contract-schema-v4-20261101/source-pins.json`.

| Таблица | Смысл и удаление |
|---|---|
| `partner_contract_create_profiles` | UUID, exact installation/client/company composite FK к текущему unique tuple, одна установка/профиль; user/service false, revoked false, generation bigint >0 default1 |
| `partner_contract_create_principals` | Typed user FK XOR machine-grant FK; CASCADE только approval, partial unique для каждого вида |
| `partner_contract_create_refs` | Exactly-one organization UUID / counterparty UUID / location VARCHAR40, live FK CASCADE, typed partial unique |
| `partner_contract_create_types` | `(profile_id,type_code TEXT)` PK; SQL FK к реальному raw `contract_types(code)` CASCADE; ORM-модель типа не выдумана |
| `partner_contract_success_intents` | Success-only namespace unique; immutable actor/hash/provenance/newborn snapshots; nullable current user/contract FKs SET NULL |
| `partner_contract_intent_locations` | Exact VARCHAR40 historical snapshot без live-location FK; `(intent_id,location_id)` PK, intent CASCADE только при явном удалении истории |

История сохраняется при удалении Company/App/installation/grant/profile/user.
Новых RESTRICT для native lifecycle нет. Успех требует текущий Contract и для user
текущий User при INSERT; последующие FK SET NULL сохраняют immutable UUID/key.
Функция UPDATE разрешает только очистку current pointers и неизменные значения.
Snapshots компании, приложения, установки, исходного grant, client, исходного
profile, actor, namespace/key, newborn, hash v1/lowercase SHA256, created refs/type
и timestamptz нельзя переписать. Снимки сами по себе не дают current authority.

Две узкие SECURITY INVOKER функции и два BEFORE trigger принадлежат0004.
`created_txid TEXT` устанавливается БД из epoch-aware `pg_current_xact_id()` при
INSERT и неизменен: добавлять intent locations можно только в той же верхней
транзакции. Поздние INSERT/UPDATE/DELETE children запрещены; явный DELETE intent
разрешён для будущего приватного retention owner и каскадно убирает children.
Прямой TRUNCATE/DDL владельцем БД не является публичным retention API.
Нет TTL, lifetime1000, eviction или нового ограничения числа успешных intent.

Каталог проверяет Core/PG16/owner и нужные реальные parent headers, типы,
NULL/default и PK/installation unique; родительские таблицы не объявлены полной
моделью бизнес-схемы. Для своих таблиц проверяются exact columns/constraints/
indexes/predicates/opclasses, FK actions и RI triggers, row types, heap/options,
RLS/policies/inheritance/rules/ACL; для функций exact body/owner/search_path/
signature/ACL/volatility/security и exact trigger catalogue. Неполные или уже
занятые собственные имена без journal4 отклоняются, включая совпадающую схему:
adopt/repair/stamp0004 отсутствуют. Applied4 допускает только action `created`.

`load_known_head` теперь0004, default `load`/CLI по-прежнему0001. Read-only prefix
при required0001/2/3 допускает прежние префиксы1/2/3; required0004 требует4.
Unknown future, foreign/partial history и unrecorded0004 occupancy отклоняются.
Startup не требует4, не применяет4 и исключает шесть таблиц из `create_all` во
всех namespace. Core Pulse0003 и прежний явный public provisioning сохраняются.

Explicit `apply --revision 0004_partner_contract_create` делегирует существующему
sequence **до открытия соединения**. Все недостающие0001–4 и journal пишутся на
одном dedicated connection в одной write transaction под прежним owner lock;
read-only preflight остаётся отдельным snapshot того же соединения. Требуется
прежний explicit calendar acknowledgement `--legacy-sent-before 2000000000`.
Explicit bootstrap target0003 выполняет только0001–3. Check0004 остаётся read-only.
Cancellation закрывает dedicated connection; неизвестный исход COMMIT не
превращается в обещание rollback и не вызывает автоматический retry.

Десять Core bootstrap parents не включают native Contracts/CP/locations/grants/
types. Поэтому пустая Core + bootstrap target4 отклоняется до DDL: полного
четырёхдоменного fresh baseline здесь нет. Fresh *revision4* и continuation
prefix0/1/2/3 требуют настоящие заранее provisioned native parents, а не выдачу
частичного `Base.metadata` за полную схему. Ни одна старая revision не изменена
ради этого требования.

Индексы покрывают immutable replay namespace, typed approvals, profile/company
и current principal/contract (`WHERE succeeded AND current_contract_id IS NOT
NULL`). INCLUDE не добавлен без плана; старые Contract/ContractLocation индексы
не изменены. EXPLAIN, скорость, ёмкость и стоимость exact count **не измерены**.

Добавлены 9 offline pure test methods и отдельные ROOT-only PG case functions:
old required prefixes, append/tamper/future, continuation/repeat/same owner,
partial occupancy, catalogue/prerequisite/history drift, rollback/cancel/lost
COMMIT acknowledgement, XOR/typed refs/uniqueness/immutable snapshots, live FK
deletes и historical locations. Это authored cases, не PASS/collection count.
Исторические Core3 55/57 и synthetic H01 264 PASS не перенесены на0004.

Остаётся ROOT review/freeze нового execution helper и disposable native fixture,
PG16 прогоны, ORM mapping проверка, fresh/upgrade/rollback/cancel/delete proof,
затем отдельные domain/query/admin/HTTP/SDK пакеты. Текущие фиксированные helpers
и их source pins не изменены; новый PG module проверяет exact DSN без query
redirects до project/helper imports и требует существующий ROOT envelope, который
этот новый source пока не допускает. Исходники не опубликованы и не выпущены.
