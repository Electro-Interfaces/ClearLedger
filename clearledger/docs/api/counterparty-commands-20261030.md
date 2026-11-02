# M06: команды импортных карточек контрагентов

Опора: `09bdaeb0`, собственное дерево `api-counterparty-commands-20261030`,
ветка `MagLook/api-counterparty-commands-20261030`. Runtime до ответа координатора
не менялся. После согласования выполнен fetch integration; пин базы сохранён,
pull/master не выполнялся. Общие команды согласованы только для трёх импортных путей.

## Источники и различия

| Native caller | CREATE / UPDATE | Правила, которые остаются у caller |
|---|---|---|
| `references_router.create_counterparty/update_counterparty` | Ручные реквизиты, nullable PATCH, manual_overrides | Membership/get_owned, verified ACL, 409 с ID дублей по валидным ИНН/КПП, lock+refresh перед PATCH; flush без commit |
| `reestr_normalize.ingest_reestr` | Карточка без ИНН; роль из ROLE_COLS | Locks counterparty+contract до scoped prefetch, matcher имени, счётчики, RAW/clean/договоры/ссылки/расчёты; commit родительского импорта |
| `reestr_rushydro.L2Cache.counterparty` | Та же карточка с optional ИНН; optional роль | Cache.build берёт те же locks и scoped prefetch; пропуск пустых/информационных строк, matcher с ИНН, опциональный счётчик; flush без commit |
| `space_links.link_counterparties` | Та же карточка без ИНН; роль | HTTP `/registry/link-counterparties`: apply требует admin, preview member; apply/only, lock до scoped prefetch, matcher conflict → 409, preview не пишет; собственный commit при apply |
| `charge_sessions_normalize._sync_corporate_contracts` | Похожая карточка, но КПП в полях и source snapshot | Corporate contract, phone mapping, org requirement; исключить из первого среза |
| `onec.sync_service._sync_counterparties` | Бухгалтерский источник, external_ref/raw; import overrides | Приоритет external_ref, проверка source connection, distinct КПП, verified только при создании, log/error semantics; исключить |
| `edge_nsi` / `store_router.store_partner_create` | Station draft / center manual и edge.partner | Отдельные ACL, partner resolution, source_uuid, станционные связи и договоры; исключить |

Платёжный matcher принят ранее (`PAYMENT_REFERENCE_IDENTITY.md`), карточки не
создаёт. `CounterpartyIndex`, `reference_identity`, ручные CRUD и 1С не переписывать.

## Общие команды

Только три действительно повторяющихся блока: старый реестр, L2Cache и space_links.
`services/counterparty_commands.py`:

* `create_imported_counterparty(db, company_id, index, *, name, inn, cp_type, alias)`:
  полное имя/ИНН сохраняются в `raw.referenceIdentity`; усечённые 500/20 символов
  попадают в реквизиты; external kind; aliases пустые либо одна роль; add, flush,
  index.add. Создание вызывается только после существующего matcher, без upsert.
* `add_imported_counterparty_alias(cp, alias)`: существующая сортированная сумма
  ролей через `apply_import_values`; ручная фиксация aliases сохраняется.

Caller сохраняет проверки, match, locks, scoped загрузки, счётчики и commit/rollback.
Command не выбирает company и кандидата, не пишет договоры/деньги/parent/source keys.
Изменяемые файлы: новый service, три перечисленных service caller, целевой тест
и этот документ. Models/DDL, product_api, docsportal/glue/types, AuthContext/apiClient
вне состава. Это ограниченный M06 slice, не закрытие M06 или всей программы.

## Baseline и проверка кандидата

Существующие SQL/HTTP контракты `test_reference_identity_api.py`:
`test_legacy_reestr_same_run_and_repeat_reuse_contract` проверяет actual ORM,
повтор, прежние contract/location IDs и ручную фиксацию name/aliases/number;
`test_link_counterparties_reports_ambiguous_name_as_409` проверяет отказ preview
на двух одноимённых карточках; `test_duplicate_counterparty_post_concurrent_scoped_by_company_and_kpp`
проверяет 201/409 и company/КПП разделение. Они работают и на исходной базе.

Подготовлены настоящие SQL/HTTP сценарии для двух импортных путей: обе правовые формы,
один ИНН в разных компаниях, неоднозначность без записи, preview/only без INSERT,
неизменность manual aliases/source snapshot при повторе, HTTP admin/member граница.
Один и тот же файл запускается baseline/candidate, без проверок вызова нового helper.
Pure identity/overrides выполняются с `--noconftest`, без SQL. SQL окно отдельно
выдано координатором после завершения его Swagger прогона: только новая собственная
`api_counterparty_commands_test` на loopback PostgreSQL и отдельный тестовый UPLOAD_DIR.
Guard вызывается до подключения/DDL и до pytest/conftest; default URL запрещён.
Baseline runtime распакован через `git archive 09bdaeb0 clearledger/server`,
новый контрактный тест скопирован без изменений. Конфигурация/секреты среды в Git
не входят. Conftest очищает собственные public/edge; чужие БД и схемы не затрагиваются.

Native цепочка импорта: `channels_router.run_channel` → фоновый запуск →
`channel_orchestrator.run_channel/_run_reestr` → `run_reestr_file` → старый
`ingest_reestr` либо `ingest_svodnaya/ingest_arenda/ingest_tariffs` → `L2Cache`.
Проверка владения каналом остаётся в HTTP, commit/rollback оркестратора не менялся.
Связывание ролей идёт через `space_registry_router.link_counterparties` →
`space_links.link_counterparties`; admin/member/only/preview остаются прежними.

## Обнаруженное ограничение исходной базы

Первый baseline: **10 PASS, 2 FAIL за 18.98 с**. Новый тест предполагал успешное
создание двух разных правовых форм с пустыми ИНН/КПП в одной компании. Native
импортеры допускают неизвестный ИНН и различают формы по имени, но на настоящей
схеме `uq_counterparties_inn_kpp` запрещает вторую пустую пару. Это реальный
существующий функциональный gap допустимого сценария импорта, а не запрет бизнеса.
Это прежнее поведение `09bdaeb0`, а не регрессия кандидата. Runtime и DDL ради
теста не менялись. Сценарий replay исправлен на одну создаваемую карточку;
правовые формы отдельно проверяются на двух существующих карточках с разными ИНН.
Добавлен явный negative-контракт: другая форма с пустыми ИНН/КПП получает прежний
`IntegrityError`, первая карточка и её ID сохраняются, автоматического слияния нет.
Исправленный тестовый файл одинаков для baseline и candidate.

Это открытый долг согласования DDL с семантикой черновиков без реквизитов.
Данный срез его не исправляет и не обещает успешное создание второго такого лица.

Точная исходная декларация из `app/database.py:1803`:

```sql
CREATE UNIQUE INDEX uq_counterparties_inn_kpp
    ON counterparties (company_id, inn, coalesce(kpp, '')) WHERE inn IS NOT NULL;
```

Пустая строка удовлетворяет `inn IS NOT NULL`; две пустые пары конфликтуют.
`Counterparty.inn` в `app/models.py:1127` — `String(20), nullable=True`, без
default/server_default. При этом `ingest_reestr` и `space_links` явно передают
`inn=""`, а `L2Cache.counterparty` превращает отсутствующий ИНН в `_s(None)==""`.
Native trace до этих producers описан выше; новый command передаёт то же значение.
Рядом `COUNTERPARTY_INN_MIGRATION_DDL` при старте переводит прежние `''` и нулевые
заполнители в NULL; `CounterpartyCreate/Update` также имеют validator пустых
реквизитов. Import producer создаёт новые пустые строки уже после этой нормализации.
Это рассогласование native import со схемой и ручным путём, а не доказательство,
что следует разрешить дубли настоящих ИНН или ослабить индекс.
DDL-блок ловит `unique_violation` при создании индекса и оставляет предупреждение,
поэтому присутствие ограничения может различаться на старой и чистой схеме.
Negative SQL контроль проверен на чистой схеме baseline и candidate. Отдельное
исправление импорта может хранить неизвестное значение как NULL без DDL, сохраняя
raw; оно требует отдельной регрессии с успешным созданием двух новых лиц и replay.
Если понадобится менять схему, нужны review и upgrade/repeat тесты существующих
данных; никаких изменений модели/индекса в этом срезе нет.

## Результаты проверки

| Статус | Проверка | Результат |
|---|---|---|
| PASS | Pure identity/overrides до правки | 13 тестов, 2.09 с, `--noconftest`, без SQL |
| PASS | Pure identity/overrides после правки | 13 тестов, 1.84 с, `--noconftest`, без SQL |
| PASS | Baseline `09bdaeb0`, исправленный контрактный файл | 16 SQL/HTTP тестов, 17.82 с |
| PASS | Candidate, тот же файл + существующие регрессии | 20 SQL/HTTP тестов, 18.87 с, без SKIP |
| PASS | Синтаксис и diff | AST пяти Python-файлов; `git diff --check` |
| PASS | Очистка после SQL | Оба pytest EXIT0; own DB: 0 других соединений, 0 таблиц public/edge; проверочное соединение закрыто; окно освобождено |
| FAIL | Первый baseline с неверным допущением теста | 2 FAIL / 10 PASS; причина и коррекция описаны выше, runtime не менялся |
| SKIP | SQL без явного opt-in | Default collection нового файла: 1 module SKIP, без SQL |
| SKIP | Полный CI, остальные producer, OAuth/login chain, браузер, выпуск | Вне проверки этого среза |

SHA256 одинакового контрактного файла baseline/candidate:
`252e04a58c3662b35350f8f0dc6e4c4b24d02bf16976a5f1a59d96f9ac02dec1`.
Локальные JUnit evidence: `.artifacts/counterparty-commands/baseline.xml` и
`candidate.xml`, без загрузки операционных артефактов в публичный Git.

Новые 16 случаев проверяют два импортных producer, create/replay, manual freeze,
полные source snapshots и прежнее усечение, сортированное накопление ролей,
company/ИНН, неоднозначность и rollback без частичных записей, правовые формы и
прежний SQL отказ, HTTP preview/only, admin/member/foreign ACL, 409 без записи,
привязку настоящего ID и alias UPDATE третьего producer с ручной фиксацией.
HTTP использует настоящий native router и SQL; подменён только текущий пользователь.
Это не проверка цепочки аутентификации. Command/matcher/SQL не подменяются.

Дополнительно повторены существующие
`test_legacy_reestr_same_run_and_repeat_reuse_contract`,
`test_link_counterparties_reports_ambiguous_name_as_409`,
`test_patch_marks_only_fields_that_changed` и
`test_failed_import_does_not_commit_partial_records_with_failure_event`.

Для воспроизведения сначала выделить изолированную БД, явно задать
`TEST_DATABASE_URL`, абсолютный тестовый `UPLOAD_DIR` и
`RUN_COUNTERPARTY_COMMAND_TESTS=1`. Из пустого cwd и с абсолютным PYTHONPATH
на соответствующий `clearledger/server` вызвать
`partner_test_safety_error(os.environ, flag="RUN_COUNTERPARTY_COMMAND_TESTS")`
до импорта pytest/conftest, затем `pytest.main` с абсолютным путём
`tests/test_counterparty_commands.py`. Conftest уничтожает public/edge этой БД.

Ручной CRUD, 1С, edge и corporate-sync команды требуют отдельного среза;
исправление пустых ИНН в импорте требует отдельного решения и регрессии.
Модели, HTTP-контракты, финансовые поля, source keys и договорные команды в этом
срезе не менялись. Полнота M06, всей программы и готовность выпуска не заявляются.
