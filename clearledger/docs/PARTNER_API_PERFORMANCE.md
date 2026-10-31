# M15: производительность и пределы внешнего API

30.10.2026. Статический разбор **`32c0d77d74b4f0cfba223a9ce944f63095216e53`**.
Разделы P1/P2 ниже сохраняют исходный source-only анализ; в конце добавлен
отдельный измеренный runtime slice на новой базе `9e9170da`.
Источник: локальный Git integration worktree, чтение через `git show`/`git archive`;
checkout, runtime и настройки не менялись. Все пути и номера строк ниже относятся
именно к этому SHA, а не к текущему HEAD интеграции.

Вывод: ограниченная страница и SQL-фильтрация уже есть; основной кандидат для
сокращения round trips — live resource loader. Exact count на каждой странице,
широкие ORM rows, обход связей файла и отсутствие отдельного product rate budget
нуждаются в измерениях. Ускорение в миллисекундах, пропускная способность и предел
конкурентных клиентов **не подтверждены**: БД, серверы, HTTP и нагрузка здесь
не запускались в source-only этапе, окно M11 принадлежало координатору.

Изменение исходного этапа — только документ. Новый static test не добавлялся:
проверка наличия `.limit()`/имён функций в AST не доказывает SQL budget и обход
ACL. Ниже определены наблюдаемые SQL/HTTP проверки для следующего runtime этапа;
существующие DB suites тогда не перезапускались. M11 Portal sessions
отсутствуют в анализируемом составе и требуют отдельного анализа final candidate.

## Источники immutable состава

Сокращения в таблицах ниже — ссылки на эти файлы того же полного SHA.

| Код | Путь и строки | Предмет |
|---|---|---|
| Q | [server/app/product_api/queries.py:24–211](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/product_api/queries.py#L24-L211) | Predicates, count, keyset, проекция |
| A | [server/app/product_api/access.py:66–145](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/product_api/access.py#L66-L145) | Verifier, membership, domain facts |
| R | [server/app/product_api/app.py:49–159](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/product_api/app.py#L49-L159) | Sessions, handlers, версии, no-store |
| D | [server/app/product_api/dto.py:9–51](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/product_api/dto.py#L9-L51) | Валидация query и ID |
| I | [server/app/services/partner_identity.py:169–331](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/services/partner_identity.py#L169-L331) | Fresh account/grant/installation/resource checks |
| V | [server/app/services/partner_identity.py:671–715](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/services/partner_identity.py#L671-L715) | JWT profile и persisted token/family/subject |
| C | [server/app/services/partner_identity.py:104–140](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/services/partner_identity.py#L104-L140) | Конфигурация и преобразование RSA key |
| T | [server/app/services/partner_identity.py:418–649](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/services/partner_identity.py#L418-L649) | Code/nonce/refresh/issuance/revocation |
| O | [server/app/routers/partner_oauth_router.py:29–209](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/routers/partner_oauth_router.py#L29-L209) | Throttle, form size, pending requests/consent |
| PM | [server/app/models_partner.py:32–177](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/models_partner.py#L32-L177) | Partner PK/FK/indexes/expiry |
| M | [server/app/models.py](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/models.py) | Core fields/indexes; точные строки ниже |
| B | [server/app/database.py](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/database.py) | Pool 20–40, фактический bootstrap DDL |
| F | [server/app/product_api/files.py:39–84](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/product_api/files.py#L39-L84) | Version/source/shared-use/download/stream |
| ACL | [server/app/services/doc_access.py](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/services/doc_access.py) | Clauses 389–459; native download 528–565 |
| G | [server/app/guard.py:145–163](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/guard.py#L145-L163) | Общая охрана и дополнительный SQL |
| RL | [server/app/rate_limit.py:30–60](https://github.com/Electro-Interfaces/ClearLedger/blob/32c0d77d74b4f0cfba223a9ce944f63095216e53/clearledger/server/app/rate_limit.py#L30-L60) | Группы legacy rate limits |

## P1. Число запросов: разделять verifier, adapter и проекцию

**Подтверждено по control flow**, не profiler: таблица считает явные вызовы DB
методов на успешном пути, без транзакционного протокола, pool pre-ping,
SQL middleware/аудита и возможных ORM loader events. EXISTS в одном SELECT —
часть того же SQL statement, но может иметь дорогой plan/много loops внутри БД.

| Домен | List: count + page + ссылки | Detail, включая проекцию |
|---|---:|---:|
| objects | 2 | 1 |
| equipment | 2–3 | 1–2 |
| counterparties | 2 | 1 |
| contracts | 2–3 | 1–2 |
| documents | 2–4 + D | 2–4 + D, включая SELECT версий |

Источники: Q:135–158,160–185; R:106–153. Ссылки проверяются одним SELECT на
вид ресурса, а не на row; пустые IDs/нет OAuth scope/EMPTY пропускают SELECT.
List читает максимум 201 entity, возвращает максимум 200; ссылки строятся уже
по обрезанным rows. Версии detail читаются с LIMIT 201, возвращаются первые 200
и `versionsTruncated`. В row-loop Q:187–210 DB-вызовов нет: N+1 по размеру
обычной страницы в этой проекции не обнаружен.

`D` — подготовка document ACL: 0 для superadmin; для обычного пользователя
`_subject_ids` вызывает membership get, затем `active_principals_for` — SELECT
замещений. Это 1 get + 1 execute, обычно два SQL в отдельной query session,
без per-document запросов (ACL:56–63,389–401;
`services/doc_approvals.py:293–305`). Доменная оценка documents максимум 6
вызовов для обычного пользователя; дополнительный resolver ниже считается отдельно.

Для verifier обозначим S = число SET profiles до пересечения с membership
(0…5), L = 1 при непустых installation location rows, R = 1 при чтении
CompanyRole в `eligible_scopes`, C = 1 при confidential credential check.

| Участок | Явные DB-вызовы успешного пути |
|---|---:|
| Persisted token + family | 2 (V:683–687) |
| Grant/client/installation/CompanyApp/Company/App | 6 (I:280–291) |
| Installation locations + tenant validation | 1 + L (I:297–303) |
| User + membership в eligible_scopes + повтор membership + optional role | 3 + R (I:188–203,308–312) |
| Resource profiles + raw IDs + tenant validation | 5 + 2S (I:254–274) |
| Confidential family credential | C (I:322–329) |
| Pairwise subject user | 1 (V:693–697) |
| **User verifier всего** | **18 + 2S + L + R + C**, то есть 18…31 |
| **Machine verifier всего** | **14 + 2S + L + C**; confidential C=1, то есть 15…26 |

Adapter A:119–140 дополнительно вызывает до двух `get` для user/membership,
optional `resolve_member_modules` (ещё get CompanyRole) и get Organization.
Не считать первые два гарантированно бесплатными: verifier возвращает immutable
IDs, ORM references не передаются; identity map может не удержать объекты.
[SQLAlchemy описывает слабые ссылки Session](https://docs.sqlalchemy.org/en/20/orm/session_state_management.html#session-referencing-behavior).
R:49–52 открывает затем отдельную query session, поэтому identity-map cache
resolver не заменяет подготовку document ACL. PolicyRoute вызывает resolver
один раз перед handler (`api_contracts/routing.py:138–165`).

Для ориентира, ALL/admin public-client objects page: verifier 18 + до 2 adapter
gets + 2 domain = 20…22 явных DB-вызова, а не «два SQL на HTTP».
Parent guard дополнительно перечитывает SecurityBlock раз в 30 секунд процесса
(G:145–163); connection pre-ping задан B:20–33. Эти расходы не входят в формулу.
**Не проверено:** реальный wire count, время каждого участка, plan каждого EXISTS.

**Оптимизация:** batch loader ниже и отдельное измерение трёх стадий.
**Проверка:** DB event counter на полном штатном M10 verifier, pageSize 1/50/200,
сравнение All/Set/Empty, user/machine, restricted organization и docs role.
**Откат:** вернуть loader commit; сохранять прежние protocol и DTO contracts.

## P1. Batch live resource loader без cache прав

Подтверждение I:254–274: каждый вызов обходит все пять profiles независимо от
запрошенного endpoint и OAuth scopes. PM:59–83 даёт составной PK profiles,
но `partner_resource_items` имеет только UUID PK и FK, отдельного индекса
`(installation_id,kind)` в модели/partner bootstrap не найдено. FK сам по себе
не означает индекс на referencing columns. Фактический каталог не проверен.

Безопасный первый runtime slice, **ещё не реализован**:

1. Прочитать все profiles данной installation одним SELECT с refresh semantics
   (`populate_existing`), собрать map; отсутствие profile сохраняет EMPTY.
2. Для SET profiles прочитать typed items одним SELECT этой installation с
   фильтром kind; сохранить отдельные typed ID sets, не смешивать UUID и string.
3. Сохранить tenant validation каждого kind в его canonical model, включая
   profiles, не используемые текущим endpoint; чужой/deleted ID по-прежнему
   отклоняет весь grant. ALL/EMPTY и membership intersection не расширять.
4. Сохранить все account/token_version/member/role/client/App/CompanyApp/
   installation/credential/family checks; не подменять их cached claims.

Для S≥1 это меняет resource loader с `5+2S` на `1+1+S` явных вызовов,
экономия **4+(S−1)**, максимум 8; при S=0 — 5→1, экономия 4.
Это расчёт количества вызовов, **не измеренное ускорение**. Объём IDs остаётся
тем же. Дубликаты typed items дедуплицируются как раньше; неожиданные строки не
должны создавать доступ. Нельзя молча обрезать grant до первых N IDs.

Два повторных `fresh(UserCompany)` сейчас явные (I:191,311). Удалять их или
возвращать новый user/context record в первом batch slice не требуется:
это отдельное изменение границы актуальности, не бесплатный «identity map fix».

**Файлы следующего slice переданы root:** `server/app/services/partner_identity.py`
и новые targeted SQL-count/deny tests. Root подтвердил отдельный dispatch;
этот документ не разрешает правку runtime в текущем этапе.
**Проверка:** измеренный −4/−8 SQL для profiles ALL/пяти SET при прежних
результатах; отзыв user/tv/member/role/grant/client/App/install/credential и
удаление/чужой tenant ID дают тот же отказ на следующем вызове; missing profiles
и object_scope EMPTY не превращаются в ALL. **Откат:** один loader commit,
без изменения схемы, persisted grants и VerifiedPartnerToken.

## P1. Pagination корректно ограничивает rows, но не стоимость count

Подтверждено Q:46–98,135–165: company + resource grant + membership objects +
organization + document ACL включены в SQL до count и LIMIT. У contracts/
counterparties используются correlated EXISTS, без размножения outer rows.
Detail сохраняет те же predicates. Это свойство нужно сохранить, не заменять
фильтрацией Python после LIMIT и не считать total по всей компании без ACL.

`total` — exact count всего отфильтрованного набора **до cursor**, выполняется
на каждой странице. Keyset имеет `(created_at,id)` ASC, LIMIT pageSize+1,
OFFSET отсутствует (Q:144–158). Binding включает tenant, principal, grant,
policy, scopes, все resource sets, organization и фильтры (Q:100–133).
Подпись cursor не заменяет live authorization следующей страницы.

Не проверены scan/sort buffers, selectivity, MVCC и latency. Exact count может
обходить много строк даже при pageSize=1; [PostgreSQL описывает стоимость count](https://www.postgresql.org/docs/16/functions-aggregate.html).
Отдельные count/page SELECT не дают обещания общего snapshot при конкурентных
записях; менять isolation level в рамках оптимизации не предлагается.

**Оптимизация:** сначала индексы и узкая проекция; count оставить точным и на
том же predicate set. Approximate/cached/optional total, COUNT OVER после cursor,
отсутствие total на поздних страницах меняют API и сюда не входят.
**Проверка:** пустая/последняя страница, одинаковые created_at, denied rows до
первой разрешённой, tenant/resource scope changes, total без cursor predicate,
EXPLAIN отдельно count и page. **Откат:** убрать новые query options/indexes,
сохранив прежние count/cursor/ACL predicates и wire names.

## P1. Узкая list-проекция, без изменения download detail

Подтверждено Q:153–154: `select(model)` загружает ORM entity целиком.
DTO Q:187–209 использует малую часть полей. В частности, у Counterparty есть
`raw` JSONB и реквизиты (M:1137–1176), Contract — `raw`, attrs и liability
(M:1386–1443), DocCard — дополнительные metadata. Allowlist предотвращает
их сериализацию наружу, но не чтение/декодирование из БД.

**Оптимизация после измерений:** только в `listing` выбрать необходимые DTO
поля через `load_only(..., raiseload=True)`, обязательно включая id/created_at
для cursor и поля object/counterparty links; отдельная map по resource.
`detail` пока оставить полным: F:40 использует его для native document policy,
которой нужны поля за пределами public DTO. Predicate columns не удалять.
[SQLAlchemy column loading](https://docs.sqlalchemy.org/en/20/orm/queryguide/columns.html#using-load-only-to-reduce-loaded-columns)
описывает этот механизм; async implicit lazy loading недопустимо.

**Не проверено:** реальная ширина rows/TOAST, выигрыш CPU/RSS/network.
**Файлы:** `server/app/product_api/queries.py` и targeted tests; root отложил
этот slice до измерений, в текущем этапе файл не меняется.
**Проверка:** прежний JSON byte-equivalent после нормализации requestId,
тот же SQL count на 1/200 rows, отсутствие deferred/lazy SQL, cursor roundtrip,
native download policy без регрессии. **Откат:** вернуть list options map.

## P2. Кандидаты индексов: source inventory, не EXPLAIN verdict

Ни один индекс ниже в этом этапе не создавался. Сверены модели и bootstrap
immutable SHA; состояние живого каталога неизвестно. Сначала synthetic каталог/
EXPLAIN, затем отдельный additive patch существующего bootstrap; новый migration
runner и CREATE INDEX CONCURRENTLY внутри его общей транзакции не предлагаются.
Одной новой Index в ORM недостаточно для уже существующей таблицы: upgrade
требует явного идемпотентного DDL. Index patch также меняет semantic catalog:
нынешний M16 harness сравнивает прежние index definitions строго. Любое
расширение его ожиданий согласуется отдельно по exact index names/definitions,
без общего разрешения менять старые таблицы. Первый batch slice схемы не меняет.

| Query shape / источник | Уже объявлено | Предложение и условия |
|---|---|---|
| Resource items installation+kind (I:261–262; PM:70–83) | UUID PK; composite FK без собственного индекса | `(installation_id,kind)`; полезность особенно проверить после batch, который может читать всю installation |
| Nonce replay client+nonce (T:525–533; PM:123–136) | code_hash PK, client_id index | Неуникальный `(client_id,nonce)`; не вводить новую unique semantics/не удалять старые reservations |
| Objects page company/order (Q:153–154; M:4986–5064) | company_id, region_id; B:2667 company/type,2902–2903 company/region | `(company_id,created_at,id)` |
| Equipment station page (Q:74–79; M:6335–6339) | company/state, company/current_location, company/supply | `(company_id,created_at,id) WHERE kind='station'`; план для SET location и organization измерить отдельно |
| Counterparties page (Q:82–87; M:1112–1176; B:4339) | company, INN/KPP и phone indexes | `(company_id,created_at,id) WHERE is_group=false` |
| Contracts page и party EXISTS (Q:46–65,85–87; M:1346–1455; B:3534,4335–4336) | creation key, company/type_code, company/counterparty | Сначала `(company_id,created_at,id)`; `(company_id,organization_id,created_at,id)` только при частом org equality |
| ContractLocation EXISTS (Q:52–65; M:1490–1515) | single company/contract/location и unique(contract_id,location_id) | Не добавлять дубликат вслепую; EXPLAIN existing unique + company predicate, затем оценить `(company_id,location_id,contract_id)` |
| Document page/versions (Q:88–97; R:147–150; M:12893–12921,12993–13003) | card company и created_at отдельно, registry/counterparty/retention; versions doc_id, company/doc/tombstoned, current role unique | Candidate card `(company_id,created_at,id)`; существующих version indexes может хватать для 201 live rows, новый индекс только по plan |
| File shared-use (F:58–63; M:10436–10498,10894–10916,14247–14295; B:3126–3127) | ChatMessage file_url partial index; у TaskAttachment.file_id/ConfSession.recording_file_id/StoreDocFile.file_id own index не найден | Проверить single-column indexes на три последних lookup columns; lookup общий по файлу, company filter самовольно не добавлять |
| Native file→versions (ACL:537–541; M:12954–13003) | doc_id и составные doc/live indexes, но file_id index не найден | Candidate `(file_id)`; помогает lookup, не устраняет обход всех связанных doc policies |

[B-tree ordering + LIMIT](https://www.postgresql.org/docs/16/indexes-ordering.html)
и [leading equality в multicolumn index](https://www.postgresql.org/docs/16/indexes-multicolumn.html)
объясняют форму page candidates; наличие индекса не гарантирует выбор planner.
Широкие covering indexes на все DTO поля пока не обоснованы: стоимость записи/
размер/visibility map не измерены. [PostgreSQL CREATE INDEX](https://www.postgresql.org/docs/16/sql-createindex.html)
также описывает ограничения concurrent build и invalid-index recovery.

Q:139 использует `ILIKE '%'+q+'%'`; q ограничен 100 символами, `%`/`_` сохраняют
смысл wildcard. Простые B-tree name/number не дают обещания быстрого substring
поиска. Возможен [pg_trgm GIN/GiST для ILIKE](https://www.postgresql.org/docs/16/pgtrgm.html#PGTRGM-INDEX),
но extension availability, короткие/wildcard-only patterns, collation, write cost
и выбор конкретных search columns не проверены. Не менять поиск на prefix/FTS
и не вводить minimum q length без отдельного API решения.

**Проверка для каждой строки:** source DDL → фактический semantic catalog →
EXPLAIN (ANALYZE,BUFFERS) synthetic count/page/lookup с ALL/SET и skew tenants;
измерить sort spill, rows removed, EXISTS loops, index size и write overhead.
**Откат:** вернуть query patch; отдельно удалить только exact новые non-unique
indexes согласованным DDL после остановки эксперимента. Удаление индекса не
откатывает данные; существующие PK/FK/unique и чужие indexes сохраняются.

## P1/P2. Download: отдельный потенциально растущий обход

F:40–69 выполняет scoped document detail, exact version+company, source+company,
один SQL с четырьмя shared-use EXISTS, затем `_can_doc(download)` и canonical
`authorize_docs_file_download`. Здесь нет page-size budget.

Подтверждено ACL:537–550: native helper загружает **все** DocVersion данного
file_id и затем связанные DocCard; в цикле вызывает `_can_doc` до первого
разрешения. V связанных версий может приводить к O(V) policy reads и большой
памяти. `_can_doc` читает ACL/subjects и рекурсивно проверяет read/fallback
(ACL:133–158,248–256). Это потенциальный N+1 именно file-policy path, не
обнаруженный N+1 обычного list. V и худший фактический count не измерены.

F:73–78 читает файл по 65 536 bytes в chunk, что ограничивает chunk buffer,
но не суммарные bytes, длительность или число одновременных streams. Размер
source/version в metadata не является HTTP bandwidth quota. Disconnect/FD и
момент освобождения DB session нужно измерить с pinned FastAPI **0.115.6**
(`server/requirements.txt:1`), не переносить поведение newer yield dependencies.

**Оптимизация:** сначала lookup indexes/метрики; извлечение общей batch file ACL
только с её владельцем. Нельзя убрать canonical check, ограничить версии первым
N, сузить общий helper одним company или обойти shared-file guard ради скорости.
**Проверка:** denied docs до разрешённого в разных tenant, несколько revisions,
tombstone/purge, shared task/chat/conference/store, explicit deny, strict и
download-vs-read; затем длительный synthetic stream и disconnect FD/pool checks.
**Откат:** query/index patch отдельно от canonical-policy изменений; исходные
guards остаются обязательными. Изменение SourceFile/doc_access здесь не поручено.

## P1. Rate, cache, CPU и серверные лимиты

| Подтверждено в immutable составе | Не проверено / следующий шаг / откат |
|---|---|
| D:9–24: ID ≤128, pageSize 1…200 default 50, cursor ≤4096, q ≤100, строгие даты/unknown fields | Эти пределы ограничивают вход/выход, не DB work exact count. Проверить 0/201, max cursor/q и safe errors; сохранить значения при оптимизации |
| O:46–60,74–91,104–108: OAuth 120/min по socket peer/process, 10 000 IP buckets, form ≤16KiB, ≤24 fields, auth header ≤8192, authorize query ≤8192; V:712–715 token ≤8192 | Несколько workers умножают budget, reverse proxy может объединять клиентов под peer. Upstream trusted-IP/body/time limits неизвестны; отдельно проверить proxy trust и multiworker counters, не включать доверие XFF вслепую |
| Product R:65–162 собственного rate/concurrency/bytes budget не содержит; RL:40–60 не включает `/api/v1` | Parent охрана остаётся (`main.py:373–415`), но `guard.py:285–291` mass_read — наблюдение после ответа, не product admission 429. До SQL нужен coarse unauthenticated cap; после verifier — client+installation+company cost/concurrency budget. Числа согласовать после measurement, отдельно downloads. Откат нового limiter не отключает существующую охрану |
| B:20–40 общий engine pool_size=10/max_overflow=20 на процесс; query и resolver используют последовательные sessions | 30 не является установленным безопасным concurrency/SLO; workers и прочие Core endpoints делят ресурс. Не увеличивать pool/worker count без DB capacity; проверить queue wait/timeouts и 429/503 без token leakage. Вернуть только новые local limits/settings |
| R:76–82 и I:47,73–91 выставляют no-store; `http_cache.py:56–75` сохраняет этот cache-control | Это не ускоряющий result cache. Positive auth/grant TTL cache несовместим с «отзыв на следующем вызове». Shared response cache по URL запрещён; даже с tenant key меняются ACL/tv/role/installation. Проверять no-store и immediate deny; сохранять прежние headers при откате |
| C:123–140 и V:678 дважды строят public JWK из PEM в одном verify path; signing_key заново base64-decodes | CPU cost не измерен. Отдельный кандидат: reuse parsed public material для exact key fingerprint+kid, bounded cache без claims/DB facts. При смене ключа новый cache key, issuer/aud/flags/alg/type проверяются каждый раз. Проверить malformed/weak/new key и rotation; откат public-key helper, не cache прав |

Размер selection ограничен `schemas_partner.py:20–30`: до 1000 IDs в каждом
из пяти typed resource sets и до 1000 legacy locations. Live loader читает
сохранённые rows без LIMIT (I:261–265,297–301); это корректно для полного grant,
но повреждённые/исторические данные и membership.object_scope не получают
гарантии cardinality из DTO. Не вводить silent LIMIT. Отдельно нужны admission
body budget, наблюдение stored cardinality и fail-closed handling аномалий.
Неограниченный `eligible_installations` и per-company `eligible_scopes` в
O:200–209 дают N+1 по числу installations на consent screen; это не page API.
Число installations/грантов не ограничено проверенным tenant quota; отдельный
batch membership/roles возможен с сохранением проверок, без усечения компаний.

OAuth throttle O:46–57 вызывает `require_enabled` **до** проверки счётчика;
поэтому RSA preparation C:123–140 выполняется и для over-limit попыток.
Лимит сокращает обращения к БД, но не устраняет эту CPU-работу. Это ещё один
аргумент измерить и отдельно переиспользовать parsed public material, не менять
проверки конфигурации и не объявлять throttling полным пределом CPU.

## P1. Retention: expiry доступа не равен разрешению удалить строку

В app subtree этого SHA не найден cleanup для partner codes/requests/tokens/
families; модели не задают DB TTL (PM:104–177). Внешний scheduler/DDL и реальный
объём БД не проверены. Ротация добавляет rows (T:620–639), расход растёт с числом
выдач даже при коротком access TTL. Приведённые ниже сроки — **runtime expiry**,
не принятая retention policy.

| Данные / source | Нынешняя семантика | Допустимая следующая работа и ограничение |
|---|---|---|
| Pending request (O:117–123,185–193) | TTL 5 минут, finished/expired дают 409/410, user binding хранится | Согласовать срок хранения и последующий 404; очистка меняет наблюдаемое состояние, не добавлять её под видом прозрачной оптимизации |
| Code (T:424–446,525–533) | ≤120 секунд/parent limit, consumed сохраняется; nonce проверяется по всем persisted(client,nonce), без expiry predicate | **Не удалять expired codes вслепую:** иначе ранее запрещённый nonce снова допустим. Нужна отдельная retention/nonce-reservation policy либо сохранение tombstone; индекс client+nonce безопаснее изменения правила |
| Token row (T:472–503,625–639) | Access ≤300 секунд, refresh hash в той же row живёт по family; refresh reuse отзывает family | **Не чистить по token.expires_at:** это access expiry, refresh может быть действителен дольше. Used refresh rows нужны для reuse detection до конца family плюс согласованный safety/audit horizon |
| Family (T:614–625; I:316–329) | User ≤parent expiry и MAX_SESSION_DAYS=7 (`auth.py:44–46`), M2M 300 секунд; revoked/expired deny | После окончательного family expiry кандидат на batched GC с lock/recheck и cascade tokens (PM:171); срок аудита/rollback предварительно согласовать, не удалять активные families/credential links |
| Subject, grant, installation, credential (PM:32–119; `routers/partner_admin_router.py:74–99,165–200`) | Stable pairwise sub; persisted approvals/revocations; credential 90 дней | Не TTL-delete subject/grant/installation ради размера. Disabled/revoked — состояние, не команда удаления; поведение при повторном включении и аудит сохраняются |

**Проверка GC после отдельного policy решения:** замороженное время, 300-second
access expired + refresh valid, oldest used refresh replay, last-moment rotation/
revoke vs cleanup, parent limit, nonce повтор после expiry и после cleanup,
повтор job, small batches. Cleanup indexes по family/request expires_at выбирать
после плана; access expiry index не обосновывает удаление refresh row.
**Откат:** остановить GC до изменения данных; DELETE не имеет автоматического
обратного хода. Поэтому retention patch не входит в безопасный первый slice.

## Порядок следующего этапа и acceptance

1. **Отдельный dispatch loader:** только partner_identity.py и SQL-count/deny
   tests. Новый verified record/AccessContext и изменение доменных ACL не нужны.
   Это принято root как следующий ограниченный этап, пока не реализовано.
2. **После освобождения root DB окна:** новая собственная synthetic test DB,
   явный opt-in/TEST_DATABASE_URL/test uploads, loopback либо явный CI service.
   Не использовать api_integrated_test/schema DB root и не запускать тяжёлый
   bootstrap/drop параллельно M11 даже на другой БД того же PostgreSQL.
3. **Baseline:** listeners на всех DB sessions полного HTTP пути; отдельные
   auth/adapter/domain counters, checkout/pre-ping учитывать отдельно. Сохранить
   median/p95/p99, DB time/count, rows/bytes/RSS, count/page EXPLAIN buffers,
   pool wait и потоковые bytes/FD. Не логировать Bearer, raw cursor, secrets,
   personal document contents или high-cardinality resource IDs в метриках.
4. **Synthetic матрица:** маленький и крупный skewed tenant; 1/50/200 rows,
   same-created_at ties; ALL/EMPTY/SET 1/1000 IDs; user/machine, organization,
   role change, пять SET profiles, missing/foreign/deleted resources;
   first/last/empty cursor pages, q wildcard/короткий/обычный и широкий date range.
   Размер large fixture и число concurrent readers согласовать с владельцем
   окна; цифры SLO из этого статического отчёта не выводятся.
5. **Query-count regression:** число SELECT не растёт с pageSize; batch profile
   load даёт рассчитанное сокращение без устранения live checks. Нужен реальный
   verifier: `tests/test_product_api.py:398–416` подставляет verifier для deny
   tests и не является измерением полного auth path. Existing product tests
   `:144–229,322–346,385–416` покрывают tenant/scope/pagination/deny; повторить их
   вместе с identity lifecycle и новыми count tests в отдельном согласованном окне.
6. **Только затем:** list column projection; по одному обоснованному индексу;
   отдельное решение product budgets; отдельное решение retention. Для каждого
   commit повторить same-data predicate/DTO/deny сравнение и соответствующий
   negative test. Объединять их в один «performance patch» не требуется.

План не является доказательством performance readiness, готовности M11 schema,
принятым production SLO или разрешением на feature-on/деплой. Подтверждены только
указанные source paths/control flow на immutable SHA; все DB/HTTP/load результаты
следующего этапа остаются непроверенными.

Проверка самого отчёта: 16 immutable source links сверены с Git archive и
`git show`, проверены границы строк и Python AST в своей venv Python 3.13;
`git diff --check` — PASS. Приложение при этом не импортировалось и DB connections
не создавались. Это проверка достоверности source references, не runtime тест.

## Реализация M15: batch resource loader на root 9e9170da

Отдельный runtime этап, 30.10.2026. База:
`9e9170da553d38313c4f23498c8c13634d79ad98`, новая ветка
`agent/api-resource-loader-20261030`; прежняя identity-ветка сохранена.
Source-only report перенесён отдельной dependency `1f9da783` (patch `b1b29ed3`);
runtime patch следует отдельным commit. Выводы исходного анализа `32c0d77d`
не объявляются измерениями нового состава.

### Состав и сохранённые ограничения

Runtime изменён только в `server/app/services/partner_identity.py`, функция
`resource_scopes` (на baseline начинается со строки 259). AST остального модуля
сверен с `9e9170da` и совпадает. Mapping/catalog/protocol, row locks,
account/member/role/token_version/client/App/CompanyApp/installation/credential/
family checks не меняются. DDL, indexes, GC/retention, pools, main/config, DTO
и schema compatibility harness не менялись.

Вместо пяти `fresh(PartnerResourceScope)` — один SELECT всех profiles своей
installation с `populate_existing=True`. Вместо S чтений typed items — один
SELECT scalar columns своей installation только для SET kinds. Валидация
каждого SET по canonical model и company_id сохранена, включая виды, отсутствующие
в текущем endpoint/OAuth scope. Сохраняются native UUID/string values, затем
прежние frozensets/MappingProxyType. Profile отсутствует → EMPTY; SET потерял
все items → EMPTY; пересечение с пустыми installation locations → EMPTY.
Нет cache authority, усечения IDs и новой доверенной информации из запроса.

### Метод A/B и граница измерений

`tests/test_partner_resource_query_budget.py` извлекает **точную функцию**
`resource_scopes` из immutable `9e9170da` через Git/AST; не переписывает baseline
вручную и не импортирует старые настройки/.env. На одинаковых данных поочерёдно
устанавливает baseline и batch function, исполняя остальные настоящие verifier,
models, transactions и product policy/handlers. Отдельный static AST check
подтвердил, что runtime diff вне этой функции отсутствует.

Все счётчики — реальные события SQLAlchemy `before_cursor_execute`, а не stub
DB и не число вызовов функций. Записывается только SQL text без parameters;
JWT, credential secret и personal IDs в JUnit properties не сохраняются.
Fixtures создают синтетический RS256 key, корректный JWT и настоящие persisted
client/App/CompanyApp/installation/grant/credential/family/subject/token rows.
Verifier не подставляется. HTTP исполняется через ASGI product app с настоящим
resolver/verifier; outer Core middleware не входит в эти HTTP budgets. Его
наличие отдельно сохраняется в protocol revoke control через основной app.
Implicit BEGIN/ROLLBACK, driver health checks вне этих events, сетевые пакеты,
EXPLAIN/BUFFERS, latency/RSS и production throughput здесь не измерялись.

Fixtures HTTP содержат **201 row каждого из пяти видов**, с одинаковым
created_at и разными id. На pageSize 1/50/200 фактически возвращаются 1/50/200
items и cursor, total=201. Сравниваются весь успешный JSON и cursor baseline/
batch, SQL count и число profile/item SELECT; на denied responses исключается
только случайный requestId. EMPTY возвращает прежний 403 без доменных rows.

### Реальные SQL counts

User: confidential client, обычный member с CompanyRole; legacy locations
не ограничены. Это fixture profile, не универсальный budget всех ролей.

| SET profiles S, остальные ALL | Baseline verifier | Batch verifier | Уменьшение |
|---:|---:|---:|---:|
| 0 | 20 | 16 | 4 |
| 1 | 22 | 18 | 4 |
| 2 | 24 | 19 | 5 |
| 3 | 26 | 20 | 6 |
| 4 | 28 | 21 | 7 |
| 5 | 30 | 22 | 8 |
| Все profiles EMPTY | 20 | 16 | 4 |

Machine verifier: ALL **15→11**, пять SET **25→17**. Document access machine
по-прежнему запрещён; foreign document ID в stored SET отклоняет весь grant
даже на `/objects`, хотя documents отсутствует в machine OAuth scopes.

Ниже каждая цифра одинакова на pageSize **1, 50 и 200**; это полный product
HTTP path с verifier/adapter/domain SQL, без outer middleware.

| Endpoint | ALL baseline→batch | Пять SET baseline→batch | EMPTY baseline→batch (403) |
|---|---:|---:|---:|
| objects | 24→20 | 34→26 | 20→16 |
| equipment | 25→21 | 35→27 | 20→16 |
| counterparties | 24→20 | 34→26 | 20→16 |
| contracts | 25→21 | 35→27 | 20→16 |
| documents | 29→25 | 39→31 | 20→16 |

Profile SELECT **5→1**; item SELECT **S→1** при S>0, при S=0 остаётся ноль.
Canonical validation SELECT по каждому SET сохранён. Получено рассчитанное
снижение **4…8 actual statements** без page N+1, изменения predicates/total/
cursor/DTO или пропуска live checks. Это не утверждение о снижении latency
на такой же процент.

### Negative controls и воспроизводимость

Обе функции проходят одни и те же проверки следующего HTTP-вызова после
role/module change, удаления membership, mail_only/lock/tv, disable client/App/
CompanyApp/install/grant/credential, credential/token/family expiry, parent
session limit, family/token revoke и сужения client/install/grant scopes.
Есть настоящий `/api/oauth2/revoke` и последующий product 401.

Проверяются foreign resource ID **каждого** вида вне текущего endpoint,
отсутствующий profile, удаление canonical equipment с cascade typed items,
held ORM profile/typed item после commit второй сессии, данные другой installation
и мусорные items в ALL profile. Ничто из последнего не создаёт доступ.
Live membership subset сужает фактический результат. У пустого membership scope
старый контракт — **200, items=[], total=0**, а не 403; первоначальное неверное
ожидание теста исправлено. EMPTY resource profile/installation scope отдельно
остаётся 403. Runtime ради унификации этих ответов не менялся.

Тесты запускаются только с собственным `RUN_PARTNER_RESOURCE_TESTS=1` и общим
portable guard: явные TEST_DATABASE_URL/test DB/absolute test uploads, loopback
либо single CI service при CI=true/1, без connection overrides/default fallback.
Нет привязки admission к порту или конкретному DB name. CI clone должен содержать
baseline Git object; отсутствие baseline — ошибка, не скрытый SKIP.

Создана и использована только новая `api_resource_budget_test` в локальном
`api-modernization-test-20261029`, localhost:33546; uploads —
`/tmp/partner-resource-budget-test-uploads`. Старт — только после сообщения root
об эксклюзивном окне. Другие DB, VM, реальные app credentials и prod .env не
использовались; конфигурация контейнера/роль/search_path не менялись.

```sh
# clearledger/server; TEST_DATABASE_URL явно задаётся для своей synthetic DB.
RUN_PARTNER_RESOURCE_TESTS=1 \
UPLOAD_DIR="${RUNNER_TEMP:-/tmp}/partner-resource-budget-test-uploads" \
../../.venv/bin/python -m pytest tests/test_partner_resource_query_budget.py -q \
  --junitxml=partner-resource-budget.xml -o junit_family=xunit1
```

Legacy regression gate имеет отдельное ограничение: старый
`test_partner_identity.py::test_partner_table_recreation_and_repeat_bootstrap_preserve_core`
выбирает для DROP только `app.models_partner`, но в новой базе M11
`partner_docs_sessions.token_id` ссылается на `partner_tokens`. Прогон дошёл до
**134 PASS + 1 FAIL** на этом DROP; ошибка `DependentObjectsStillExistError`
передана root. Loader там не вызывается; legacy test/schema в этом patch не
меняются и FK не обходится. Повтор остальных regression cases делается с одним
явно указанным deselect, не объявляется полным green identity suite.

Итог согласованного partial-regression прогона: **193 PASS, 1 SKIP,
1 DESELECTED**, 127.51 с. В составе: **86/86 новых budget cases PASS**,
51 identity PASS (legacy DROP case deselected), 56 product PASS и 1 product SKIP.
Skip — `test_formal_openapi_31_validation`: в своей venv отсутствует optional
`openapi_spec_validator`. Это не пройденная формальная OpenAPI проверка; runtime
loader не меняет schema/OpenAPI. Root подтвердил отдельное исправление legacy
M11 table recreation manifest и повтор этого case, не бессрочное исключение.
Новые tests не скрывают этот failure и не редактируют чужой test module.
Root сообщил immutable исправление `e94427bf`; оно не применялось в этой ветке
и не входит в её результат. Повтор исправленного case остаётся за root.

```sh
# TEST_DATABASE_URL уже явно задан для своей свободной synthetic DB.
RUN_PARTNER_RESOURCE_TESTS=1 RUN_PARTNER_IDENTITY_TESTS=1 RUN_PRODUCT_API_TESTS=1 \
UPLOAD_DIR="${RUNNER_TEMP:-/tmp}/partner-resource-budget-test-uploads" \
../../.venv/bin/python -m pytest tests/test_partner_resource_query_budget.py \
  tests/test_partner_identity.py tests/test_product_api.py \
  --deselect=tests/test_partner_identity.py::test_partner_table_recreation_and_repeat_bootstrap_preserve_core \
  -q --junitxml=partner-resource-budget-final.xml -o junit_family=xunit1
```

Статические проверки: `compileall` loader/new tests и `git diff --check` PASS;
AST вне resource_scopes совпадает с immutable baseline. Финальный pytest process
и teardown завершены; root получил точную границу освобождения SQL окна.
После этой границы дополнительные DB процессы не запускались. Проверки CI
service networking, профиля core/public schema, полноценного EXPLAIN/load/SLO и
перезапуска VM этим slice не объявляются выполненными.

Откат runtime slice: вернуть commit с loader, без DDL/изменения persisted
grants. Initial source report остаётся отдельной dependency. Сохранённые
ограничения count/index/download/rate/retention и потребность измерений следующих
этапов остаются в силе; этот slice не закрывает весь M15 или программу API.
