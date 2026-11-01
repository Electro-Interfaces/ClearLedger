# РусГидро: prerequisite чтения охвата условий

Дата: 2026-11-01. База исходников: `24af3535565381d46f9e51c2841c2feb80b1c8f3`.
Статус этой поставки: **SOURCE ONLY, runtime NOT RUN**.

Общий owner ожиданий допускает только `company` и `location`.
`site` и любое другое непустое значение больше не получают объект из
`location_id` или охват из `ContractLocation`. Для подходящего по датам,
периодичности и активности статьи условия план возвращает существующий
элемент `blocked` с причиной
`неподдерживаемый охват <scope>; требуется распределение`.
Это нерешённое обязательство, а не успешный расчёт с нулевой суммой.
Ключи элемента остаются `termId`, `contractId`, `costItem`, `reason`.

| Вход | Результат охвата / плана |
|---|---|
| `company`, в том числе с заполненным `location_id` | `[None]`, общая затрата компании |
| `location` с `location_id` | Только указанный объект |
| `location` без `location_id`, 0 связей | Прежний blocked «не заполнен охват» |
| `location` без `location_id`, 1 связь | Прежнее ожидание по одному объекту |
| `location` без `location_id`, больше 1 связи | Прежний blocked «несколько объектов» |
| Legacy `None` / пустая строка на границе домена | Те же правила, что у `location` |
| `site` / неизвестный scope, любой `location_id` | Пустой охват и отдельный unsupported blocked |

`OpsContractTerm.scope_type` остаётся `String(20) NOT NULL`, default `location`.
Проверка legacy `None` присваивает его загруженному настоящему ORM-объекту
только в контексте без autoflush с последующим rollback. Она не утверждает
наличие сохранённого SQL NULL и не меняет ограничение колонки.

Планировщик остаётся чтением без DML и изменения ORM. `expand` применяет только
`plan.changes`: в смешанном наборе создаёт допустимое ожидание, возвращает
unsupported blocked и сохраняет старые начисления неподдерживаемого условия.
История, повторный разворот, формулы сумм, порядок блокировок и ранний выход
для закрытого периода остаются прежними. Валидация записи условий по-прежнему
отвергает `site` и неизвестные значения.

## Конечная матрица: 23 случая

Источник — `server/tests/test_rushydro_term_scope_native_pg.py`.
Идентификаторы и количество зафиксированы до выполнения.

| Группа | Количество | Literal IDs |
|---|---:|---|
| `SCOPE_CASES` | 12 | company-null, company-explicit, location-explicit, location-zero, location-one, location-multi, legacy-none-explicit, legacy-none-one, legacy-none-multi, legacy-empty-explicit, legacy-empty-zero, legacy-empty-multi |
| `UNSUPPORTED_CASES` | 4 | site-null, site-explicit, unknown-null, unknown-explicit |
| `ELIGIBILITY_CASES` | 5 | future, expired, quarterly-off, annual-off, inactive |
| `FLOW_CASES` | 2 | mixed-history-repeat, closed-unchanged |

Каждый unsupported случай имеет две настоящие связи `ContractLocation`.
Для проверки 0/1/2 связей создаются отдельные учебные договоры;
исходный договор `C1` общего `read_world` имеет две связи.
Новые условия имеют собственные договоры и статью, соблюдают FK и уникальность
`uq_ops_term`; начисления сохраняют реальный ключ company/period/term/seq.
В mixed случае проверяются сумма 330 из прошлой принятой строки, сумма без НДС
275, сохранность истории и старого неподдерживаемого начисления, а затем повтор
без дополнительных изменений. Закрытый сценарий использует отдельный август,
чтобы не закрывать общий июнь остальных случаев.

## Протокол будущего native прогона

Внешний ROOT runner предоставляет настоящую `rushydro_read_factory`, native347,
проверки роли/OID/владения, пулы и удаление всей принадлежащей ему БД.
Новый модуль не создаёт схему, factory или runner, не импортирует старые
providers/conftest, не удаляет строки общей фикстуры. Допускается загрузка
через внешнее admission с `--noconftest`; прямой общий pytest здесь не является
протоколом приёмки.

До импортов приложения и SQLAlchemy обязательны:

- `RUN_RUSHYDRO_TERM_SCOPE_TESTS=1`;
- `RUN_RUSHYDRO_PRODUCT_READS_TESTS=1` — prerequisite существующего helper;
- `ROOT_APPROVED_RUSHYDRO_PRODUCT_READS=1` и `APP_ENV=test`;
- существующий `partner_test_safety_error`, точные target literals модуля,
  равенство `DATABASE_URL` / `TEST_DATABASE_URL` и отдельный абсолютный test upload.

Повторно используется текущая session-фикстура `read_world` с общим cache из
`tests.test_rushydro_product_reads_native_pg` на базе `24af3535`.
Её подготовка выполняется будущим runner до проверки бизнес-плана.
Новый модуль не импортирует `app.main`, не требует его отсутствия в
`sys.modules` и не меняет реестр модулей: bootstrap может загрузить его ранее.

Проверки обращаются к реальным сервисам и SQLAlchemy queries.
SQL event listener только наблюдает выполненные statements; он снимается в
`finally`. Сидирование завершено до listener. План сравнивает состояние
нативных строк и ORM unit of work, проверяет наличие SELECT и отсутствие
промежуточного DML/DDL. Ответы запросов, owner и положительные результаты
не подменяются. Runtime результат должен отдельно зафиксировать ROOT.

## Исходники и граница изменения

- [ExpandCtx.scope](../../server/app/services/ops_expectations.py#L149),
  [_plan_expectations](../../server/app/services/ops_expectations.py#L413);
  [expand](../../server/app/services/ops_expectations.py#L518) и остальные функции сохранены.
- [OpsContractTerm](../../server/app/models.py#L9316),
  [OpsCostItem](../../server/app/models.py#L9294),
  [OpsPeriodCharge](../../server/app/models.py#L9455),
  [OpsPeriodClose](../../server/app/models.py#L9586),
  [ContractLocation](../../server/app/models.py#L1490) — только прочитаны.
- [SCOPE_TYPES](../../server/app/services/ops_terms.py#L44),
  [_validate](../../server/app/services/ops_terms.py#L107) — без изменений.

Это prerequisite P1a, без Site ID, финансового распределения, новых writers,
маршрутов, scopes/grants, схемы или DDL. TARGET `66f43993` остаётся PROPOSED
roadmap. Будущая коррекция HTTP для добавления объектов профиля договора
на POST collection + Idempotency-Key / ObjectId JSON не входит в эту поставку.
