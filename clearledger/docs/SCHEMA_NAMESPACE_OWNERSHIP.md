# M16: принадлежность таблиц при Core/public bootstrap

База исследования: `aba47c34319b00a63521685ac24be8b1a9320c15`.
Ветка: `agent/api-schema-ownership-20261030`. Предыдущая ветка HTTP-профиля и её
коммиты сохранены. Проверка ограничена namespace bootstrap; она не переносит
данные Поддержки и не меняет профиль развёртывания.

## Что установлено по исходникам

- `app/config.py:17–40`: Settings читает DATABASE_URL, поддерживает `.env`;
  отдельного селектора schema в этом пути нет. `app/database.py:18–39` создаёт
  engine из `settings.database_url`, без search_path/schema_translate_map.
  Поэтому фактический namespace задаёт PostgreSQL-сессия и её provisioning.
- `app/database.py:2206–2214`: bootstrap сначала исполняет PHONE_FUNCTION_DDL,
  затем `Base.metadata.create_all`; позже отдельная транзакция выполняет
  unqualified incremental migrations. `checkfirst` используется по умолчанию.
- Таблицы `app.models_partner` и `app.models_docs_portal` зарегистрированы
  с `schema=None`; их FK на Core masters также unqualified. Подключение моделей
  идёт через импорт routers/services главного приложения. Import в тесте
  регистрирует metadata, но lifespan, seed и HTTP не запускаются.
- В установленном SQLAlchemy **2.0.36** `PGDialect.has_table` вызывает
  `_has_table_query`; при `schema=None` используется `pg_table_is_visible`,
  а не равенство namespace с `current_schema()`. Исходник dialect проверен
  локально; это объяснение механизма, не замена SQL-контрпримеру.
- `tests/test_partner_schema_compatibility.py::SchemaDatabase` действительно
  сначала создаёт Core при core-only path, затем `finish_provisioning` создаёт
  public sentinels и включает core/public. Этот хороший coexistence-контроль
  не моделирует Support-first и shadow новой таблицы до первого Core CREATE.

[PostgreSQL: schema search path](https://www.postgresql.org/docs/current/ddl-schemas.html#DDL-SCHEMAS-PATH)
определяет разрешение unqualified имён по первому совпадению и текущую schema
для CREATE. Наличие второй schema не означает изоляцию имён.
[SQLAlchemy PostgreSQL search_path](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#remote-schema-table-introspection-and-postgresql-search-path)
объясняет влияние path на introspection;
[MetaData.create_all](https://docs.sqlalchemy.org/en/20/core/metadata.html#sqlalchemy.schema.MetaData.create_all)
проверяет наличие таблиц перед созданием и не является проверкой их владельца
или миграцией чужой структуры.

## Изолированные контрпримеры и контроли

Новый набор `server/tests/test_schema_namespace_ownership.py` запускается через
unittest, без destructive pytest conftest. Он требует явные
`RUN_NAMESPACE_OWNERSHIP_TESTS=1`, TEST_DATABASE_URL ровно для
`api_namespace_ownership_test` и абсолютный test UPLOAD_DIR. Имя/владелец
подключённой БД дополнительно проверяются через каталог. Соединения имеют
собственный `server_settings.search_path`; ALTER ROLE/ALTER DATABASE и глобальные
настройки не используются. `.env` в Settings отключён, окружение процесса
синтетическое. Удаляются только test tables/schemas этой отдельной БД.

| Сценарий | Явные предусловия | Проверка |
| --- | --- | --- |
| Новая partner-таблица shadowed | Настоящий Core bootstrap; затем удалены только 13 новых partner/portal tables; public.partner_clients имеет совместимый PK id, несовместимый support_marker и synthetic row | Core namespace/OID новой таблицы, FK target OID/schema, неизменность public OID/owner/ACL/columns/constraints/rows; отсутствие частичной DDL при защитном отказе |
| Support-first fresh provisioning | core пуст, public.users/companies уже принадлежат Support и содержат synthetic rows | Early refusal до создания Core таблиц и изменения public; нельзя называть этот профиль нормальным Core bootstrap |
| Core masters без shadow | Настоящие Core masters; новые partner tables отсутствуют; Support public users/companies существуют | Новые таблицы/FK появляются в core; master OIDs сохраняются; повтор idempotent; public неизменён |
| Корректный Core плюс public same-name | Полный Core существует, public.partner_clients тоже существует | Core relation остаётся авторитетной по OID; public shadow не мешает bootstrap и не меняется |
| Standalone public | Пустой public является текущей schema | Реальный bootstrap и повтор, отсутствие копий в core |
| Explicit edge | Table с явным schema=edge и FK к Core companies; одноимённый public sentinel | edge не переводится в core/public; сохраняются разные OID и правильная FK target identity |

В положительных Core/public контролях также используется **настоящий ORM source
`ce94e2bf`**: models/database/config загружаются из immutable git objects в
временный package; child process получает только synthetic env и явный engine
с нужным path. Старый ORM читает Company/User и обновляет имя synthetic Company.
Проверяются разрешение master OID и неизменность public sentinels. Это old-ORM
coexistence; старый полный bootstrap/HTTP/OIDC этим отдельным probe не запускается.

## Предложенный минимальный барьер

До первой PHONE_FUNCTION_DDL и metadata DDL проверить для **всех** owned
`Base.metadata` tables с `schema=None`, не по префиксу имени:

1. Текущая PostgreSQL schema является целевым namespace этого bootstrap.
2. Если visible relation с именем owned table разрешается в другую schema,
   прекратить bootstrap явным RuntimeError до записи.
3. Таблицы с явным schema не переопределять; standalone public не превращать
   в hardcoded core; при корректном existing Core public shadow не мешает.

Fail-closed может остановить запуск при неправильном provisioning. Это осознанная
потеря доступности вместо молчаливых FK/query к таблицам другого приложения.
Барьер не исправляет состав колонок внутри целевой schema, не переносит/копирует
данные и не даёт старому binary новую защиту. Решение о квалифицированной DDL
или отдельной provisioning migration требует собственного аудита, а не попытки
автоматически «забрать» public таблицы. Runtime change допускается только после
SQL evidence и отдельного разрешения координатора.

## Выполнение

Pure safety прогон до SQL окна: **2 PASS**, SQL cases явно SKIP. PostgreSQL окно
и создание выделенной БД отдельно разрешены координатором; baseline выполнен
на неизменённом runtime указанного SHA.

### Подтверждённый baseline

Результат **6 PASS / 2 FAIL, 158.288 s**, 8 unittest cases. Четыре положительных
SQL-контроля и два pure safety controls прошли, в том числе actual old ORM
`ce94e2bf` для core/public и явный edge. Process session92996 завершён exit 1,
cleanup synthetic schemas выполнен, SQL окно освобождено.

| Контрпример | Фактический результат исходного bootstrap |
| --- | --- |
| Public partner_clients shadow | Bootstrap завершился **успешно**, таблиц в core стало 336; пять Core FK направлены на `public.partner_clients` OID **1052683**, а не на новую Core-таблицу |
| Support-first, core пуст | Поздний `ProgrammingError: users.company_id does not exist`; к этому моменту первая bootstrap-транзакция уже сохранила **331 Core table** и **402 FK** на `public.users` OID **1061503** / `public.companies` OID **1061510** |

Пример точной первой цепочки: `core.partner_credentials` relation OID **1052690**,
FK OID **1052697**, referenced relation OID **1052683**; ещё
`core.partner_authorization_requests` relation OID **1052728**, FK OID **1052735**
ссылается на тот же public OID. Остальные три FK исходят из partner_codes,
partner_installations, partner_subjects. Каталожный запрос связывает conrelid и
confrelid с pg_class/pg_namespace; совпадением строкового имени это не подменено.

Public sentinels в обоих случаях сохранили OID, owner, ACL, columns, собственные
constraints и rows. Это не оправдывает bootstrap: возникла реальная зависимость
Core от чужих PK, включая заданные в моделях CASCADE-политики. Изменение или
удаление чужих данных в опыте не выполнялось. Для partner shadow прикладной
ORM ожидает отсутствующие у Support колонки; ошибка может появиться уже после
ложно успешного старта. Support-first дополнительно демонстрирует неатомарный
поздний отказ между двумя существующими bootstrap-транзакциями.

Механизм source-to-sink: `models_partner.py::PartnerClient.schema=None` →
`database.py:2214` → `MetaData.create_all(checkfirst)` → PostgreSQL dialect
`pg_table_is_visible` при core/public → пропуск owned CREATE и разрешение
unqualified REFERENCES к public OID. Для users/companies тот же механизм
поражает master FKs ещё до incremental migrations.

Эти результаты переданы координатору сразу после reaping процесса, до изменения
runtime. Затем получено отдельное разрешение **Guard approved + SQL now** для
минимального guard и повторного прогона в той же own DB. Локальный baseline log:
`.artifacts/namespace-baseline.log`.

## Реализованный guard и операционные ограничения

`app/database.py:2206–2226` добавляет `_assert_bootstrap_namespace`; вызов
`create_all:2234` расположен перед PHONE_FUNCTION_DDL и metadata CREATE. Два
read-only запроса проверяют current_schema и наличие visible pg_class relation
для любого unqualified metadata table, чей pg_namespace отличается от целевого.
Проверяются **все** `Base.metadata` tables с `schema=None`, без prefix/feature-flag
исключений. Явный schema не меняется. Ни модели, ни FK/CASCADE, ни config/main,
ни настройки роли не правились.

При найденном fallback или отсутствии current_schema выбрасывается один generic
RuntimeError о schema ownership/provisioning. Он не раскрывает названия relation,
schema, tenant или строк из каталога. Транзакция завершается отказом до записей;
incremental migration phase не запускается. Guard не меняет search_path сессии
и не пытается автоматически «починить» чужую таблицу.

Fail-closed означает, что ошибочно подготовленный shared namespace теперь
блокирует startup вместо ложного успеха или поздней поломки. Проверяются только
table-like relkind `r,p,f,v,m`, как у PostgreSQL has_table SQLAlchemy; foreign
namespace INDEX/SEQUENCE не запрещают допустимый CREATE в своей schema.
Принадлежность namespace не доказывает совпадение структуры. Guard не устанавливает эксклюзивную
блокировку от DDL другого приложения между проверкой и CREATE; provisioning
нескольких приложений должен координироваться отдельно.

### Runbook для владельца provisioning

1. После отказа не повторять startup с подстановкой чужой public таблицы и не
   переименовывать/копировать Support rows. Проверить реальный current_schema,
   квалифицированные relation OID и все существующие FK targets в отдельном
   согласованном аудите. Здесь такой аудит рабочих данных не выполнялся.
2. Для **первого** Core bootstrap подготовить свою schema с правильными owner,
   USAGE/CREATE правами. Все bootstrap connections временно должны использовать
   core-only search_path через управляемый provisioning profile; это пример
   Core-контура, не hardcoded требование к standalone public или explicit edge.
3. До включения общего core/public path проверить, что Core masters и новые
   partner/portal tables существуют именно в своей schema, их OID и FK targets
   принадлежат ожидаемым namespace, а Support catalog/rows не изменились.
4. Вернуть согласованный shared path, повторить обычный bootstrap и проверить
   Core/public coexistence. Test recovery показывает именно эту последовательность
   на synthetic DB после **раннего отказа**, где неправильные FK ещё не созданы.
5. Если прежний bootstrap уже создал ошибочные cross-schema FK, core-only retry
   сам их не исправит: checkfirst не пересоздаёт существующие связи. Нужна
   отдельная reviewed migration с планом восстановления; DROP CASCADE, перенос
   customer data или ослабление FK не являются частью этого изменения.

Guard относится к зарегистрированным ORM table names и проверяемому моменту
startup. Он не подтверждает корректность колонок/FK внутри уже существующей
целевой schema, не охватывает все произвольные raw SQL migration objects и
не добавляет защиту старому binary. Старый ORM coexistence подтверждён отдельно;
полная повторная old bootstrap/HTTP/CI/load проверка здесь не заявляется.

### Повторная проверка

Команда из `clearledger/server`, только в выделенное координатором SQL окно:

```sh
env -i PATH=/usr/bin:/bin RUN_NAMESPACE_OWNERSHIP_TESTS=1 \
TEST_DATABASE_URL='postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_namespace_ownership_test' \
UPLOAD_DIR=/tmp/api-namespace-ownership-test-uploads PYTHONPATH="$PWD" \
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python \
  -m unittest tests.test_schema_namespace_ownership -v
```

К исходным 8 cases добавлен missing-namespace контроль. Negative cases теперь
также проверяют неизменность function catalog и Core-only recovery до shared
retry; public OID/properties/rows сравниваются и после recovery. Реальные secrets,
рабочие БД, VM, настройки кластера и другие test DB не использовались.

Полный guarded прогон: **9 PASS за 147.839 s**, process session21683 завершён
exit 0 и reaped. Состояние после partner-shadow отказа: ровно прежние **324 Core
tables**, function catalog неизменён, foreign FK **0**; затем explicit Core-only
test recovery и shared retry прошли с правильными OID/FK targets и неизменной
public. Состояние после Support-first отказа: **0 Core tables, 0 Core functions,
0 foreign FK**. Missing namespace также не оставил DDL. Все четыре положительных
SQL profile controls и old immutable ORM controls сохранились. Локальный журнал:
`.artifacts/namespace-guard-tests.log`.

После прогона fixture cleanup завершён, test engines/old ORM child processes
закрыты и SQL окно возвращено координатору. `git diff --check` проходит;
повторных широких DB suites, remote CI, deployment и customer migrations не было.

## Уточнение relkind после `863607cca632794aca9043fcc6adf0d98428c906`

Отдельный bounded slice исправляет availability false positive прежнего guard.
Предыдущие namespace baseline/9 PASS выше сохранены как результаты исходного
slice; они не покрывали чужие INDEX и SEQUENCE с именем отсутствующей Core-таблицы.

### Первичный источник и необходимая граница

В установленном **SQLAlchemy 2.0.36** фактический `PGDialect._has_table_query`
передаёт в relkind condition `RELKINDS_ALL_TABLE_LIKE`. Точная константа:
`('r', 'p', 'f', 'v', 'm')`, построенная из TABLE/VIEW/MAT_VIEW. Константы
`RELKINDS_ALL_TABLES` в этой версии нет. Это проверено по installed source и
[исходнику SQLAlchemy tag rel_2_0_36](https://github.com/sqlalchemy/sqlalchemy/blob/rel_2_0_36/lib/sqlalchemy/dialects/postgresql/pg_catalog.py).
[Inspector.has_table](https://docs.sqlalchemy.org/en/20/core/reflection.html#sqlalchemy.engine.reflection.Inspector.has_table)
поддерживает table-like объекты, включая обычные и materialized views;
[PostgreSQL pg_class](https://www.postgresql.org/docs/current/catalog-pg-class.html)
отдельно различает relkind индексов `i`, последовательностей `S` и таблиц/представлений.
Одна лишь `pg_table_is_visible` не воспроизводит фильтр has_table.

### Реальный контрпример и положительный control

Новые SQL-проверки используют настоящий Core bootstrap и ту же own test DB.
После создания Core masters удалены только новые partner/portal tables.
В public создаётся index на synthetic host table либо sequence с именем
`partner_clients`; Core-таблица с таким именем отсутствует. Это test fixtures,
новые production tables/models не добавлены.

| Объект public | Видимость по OID | Inspector.has_table | Настоящий metadata CREATE в SAVEPOINT |
| --- | --- | --- | --- |
| INDEX, OID **1145974** | true, kind `i` | false | Создал отдельную core.partner_clients OID **1145975**, обе FK target schema = core |
| SEQUENCE, OID **1154420** | true, kind `S` | false | Создал отдельную core.partner_clients OID **1154421**, обе FK target schema = core |

SAVEPOINT откатывается до вызова guarded bootstrap, и отсутствие Core-таблицы
проверяется снова. Таким образом контроль не маскирует дефект заранее созданной
Core-таблицей и не оставляет результат raw CREATE для bootstrap. Оригинальный
guard `863607cc` после этого ошибочно выдаёт RuntimeError на INDEX и SEQUENCE.
Trace: `create_all:2234` → `_assert_bootstrap_namespace:2217–2226` → EXISTS по
любой visible relation из другого namespace; пропущен relkind condition.

Корректный baseline: **3 tests, 1 PASS / 2 ERROR, 68.529 s**, session25050 reaped.
Negative partitioned TABLE/VIEW/materialized VIEW controls при этом PASS: has_table
true, early denial до DDL/functions, public OID/definition и Core catalog неизменны.
Первый fixture-only прогон session35479 не является этим evidence: сравнивался
asyncpg `char` bytes со строкой; исправлено только чтение каталога через
`relkind::text`, затем baseline полностью повторён на неизменённом runtime.

### Исправление и остающиеся границы

Единственное функциональное изменение runtime — условие
`c.relkind IN ('r', 'p', 'f', 'v', 'm')` в существующем namespace EXISTS.
Вызов до PHONE_FUNCTION_DDL, missing current_schema denial, полный набор
unqualified Base tables и generic errors сохранены. Это не prefix exemption,
не отключение проверки namespace и не изменение FK/CASCADE.

Обычная чужая TABLE продолжает проверяться прежним тестом; новые реальные SQL
контроли отдельно проверяют partitioned TABLE, VIEW и materialized VIEW. Kind `f`
сохранён по точному dialect source; новые FDW/server/network connections ради
этой проверки не создавались. INDEX/SEQUENCE проходят полный guarded bootstrap:
проверяются собственные Core OID и FK targets, неизменность public OID/owner/ACL/
definition/host rows, а у sequence также `last_value=17,is_called=false`.
Прежние standalone public, Core repeat, explicit edge, old ORM и negative table
cases остаются в том же полном наборе; их expectations не ослаблены.

Полный финальный прогон тем же isolated unittest command: **12 PASS за
221.976 s** (все прежние 9 cases и три новых, с subTest по `p/v/m`). Для финальных
положительных контролей public INDEX OID **1223015** и rollback-only Core OID
**1223016** различаются; public SEQUENCE OID **1231787**, rollback-only Core OID
**1231788**. После rollback в обоих случаях реальный guarded bootstrap также
успешен и создаёт собственные Core relation/FK; public identity и sequence state
сохранены. Negative `p/v/m` имеют реальные OID **1197198 / 1197203 / 1197207**,
has_table=true и неизменный каталог после раннего отказа. Прежний ordinary
TABLE negative отдельно остаётся PASS.

Final process session68804 завершён exit 0 и reaped; baseline35479/25050 и old ORM
children также завершены. Cleanup synthetic schemas/engines выполнен, SQL окно
возвращено root **до worker_done** для его независимого candidate repeat.
Логи: `.artifacts/namespace-relkind-baseline.log` (ошибка fixture encoding),
`.artifacts/namespace-relkind-baseline-corrected.log` (настоящий negative baseline),
`.artifacts/namespace-relkind-final.log` (12 PASS). `git diff --check` проходит;
новых SDK dependencies, role/cluster changes, customer migrations, SSH/production,
PR/merge/release не было. Root compose candidate repeat не приписывается этому прогону.
