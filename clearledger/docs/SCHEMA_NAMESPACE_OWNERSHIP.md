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
блокирует startup вместо ложного успеха или поздней поломки. Возможна проверка
существующих relation других типов с тем же именем: это консервативный барьер,
а не доказательство совпадения структуры. Guard не устанавливает эксклюзивную
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
