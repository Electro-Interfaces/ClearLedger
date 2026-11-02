# M08 slice: чтение закрытия и явная подготовка расчёта

29.10.2026. Локально реализован и проверен срез закрытия затрат эксплуатации.
Это не завершение всего M08/программы API и не выпуск на VM. Финансовые данные
клиентов, настройки и процессный движок не менялись; тестовые данные синтетические.

## Поведение

`GET /api/ops/closing?company_id=...&period=YYYY-MM-01` больше не вызывает
`expand`, `get_or_create`, `flush` или собственный `commit`. Он отдаёт только
сохранённые charges/counters, прежние blocked reasons и contractsWithoutTerms.
Если записи периода ещё нет, статус рассчитывается календарём без создания
`ops_period_close`. Общие Core presence/transaction dependencies сохраняются;
их техническая отметка пользователя не является записью в бизнес-таблицы.

Добавлен `preparation: {required, missing, stale}`. Новые условия и изменившиеся
расчётные суммы не исчезают молча: required означает, что сохранённую проекцию
нужно подготовить. Суммы в counters/charges до команды остаются сохранёнными,
а не подменяются незаписанным прогнозом. Для закрытого месяца required=false;
его подготовка не изменяет замороженные строки.

`POST /api/ops/closing/{period}/materialize?company_id=...` без тела явно создаёт
и обновляет ожидания. Ответ: `{period, created, updated, skipped, blocked}`;
updated считает реально изменённые строки, поэтому точный повтор даёт 0/0.
Закрытый месяц отвечает 409. Close по-прежнему сам подготавливает ожидания;
reopen сохраняет обязательную причину и прежнюю историю закрытия.

Расчёт один: `plan_expectations` строит read-only план через прежние `build_ctx`
и `estimate`; `expand` применяет его только в write-пути. Нет копии формул,
временного ORM flush или rollback ради получения blocked. Сравнение числовых
полей учитывает фактическую точность Numeric, чтобы округление объёма не делало
план вечно устаревшим. Исходные методы, НДС, сроки и происхождение сохраняются.
Ручные строки без term_id, строки с basis=manual, принятые документы и settled
строки не перезаписываются. Поздняя первичка сохраняет закрытое ожидание и снимок.

Фактический unique key начисления не содержит location_id: одно term/period/seq.
Если неуточнённый охват условия содержит несколько объектов, план возвращает
явный blocked «у условия несколько объектов; укажите объект в условии» вместо
выдуманного распределения суммы или unique-violation/500. Перенос неведущейся
строки со старого объекта остаётся возможным; документированная/ручная строка
остаётся на месте с прежней причиной blocked.

## Полномочия и транзакции

Закрытие — операция полного контура компании. Сервер проверяет Core session,
company membership (с обычным Core исключением суперадмина), известную роль,
принадлежность назначенной CompanyRole той же компании и право `ops` либо
канонический `ops:ops_closing`; admin/full modules сохраняют полный доступ.
Mail-only, заблокированная учётка и неизвестная роль закрыты. Проверка UI не
заменяет эту серверную проверку.

Суженный object/org/visit контекст не расширяется до компании: для closing и
periods такой запрос закрыт с 403. Любой непустой X-Organization-Id, включая
некорректный, не превращается молча в all. Пока нет безопасной частичной модели
закрытия, частичное чтение этих сводок тоже закрыто, а не показано чужими итогами.
Параметр scope в GET — только разрешённый разрез location/company/all.

Period — точное первое число месяца, с представимым следующим месяцем срока;
неверные date/scope/status, повторные/лишние параметры, чужие селекторы в теле
и неканонический force возвращают безопасные 422. Выбор компании проверяется
сервером; query/body/header не подменяют пользовательские права.

`lock_period(company,period)` — общий PostgreSQL advisory transaction barrier
для materialize/expand/close/reopen. Он удерживается до commit/rollback владельца
транзакции; get_or_create перечитывает состояние после ожидания. Параллельные
повторы не создают дубли; close, опередивший materialize, оставляет ему 409.
Команды фиксируются до HTTP ответа. Новых схем, migration runner, eventbus и
интеграции с процессным движком не вводилось.

## Собственные и неизвестные consumers

Поиск `getOpsClosing` в исходниках обнаружил единственный consumer:
`OpsClosingPanel.tsx`; transport находится в `opsService.ts`. Query/mount
выполняют только GET. Кнопка «Обновить расчёт» явно вызывает новый POST, имеет
доступное текстовое имя, pending/disabled и ошибку с повтором. Новый термин
виден через preparation-подсказку. Close сам готовит расчёт, как и прежде.

Мутация хранит исходные companyId/period в variables; onSuccess инвалидирует
ключи именно этого контура, включая все его scope-проекции, шкалу и календарь.
Поздний ответ старой компании/периода не перезапрашивает и не подменяет новый
контур. Результаты/ошибки старого close не показываются в новом периоде.
Дочерние copy-правки разрешены отдельно координатором: «Загружаем периоды»,
пустой календарь направляет к действующей кнопке либо сотруднику с доступом.

Обнаружен дополнительный consumer: `OpsPeriodsScale` вызывает `getOpsPeriods`.
В собственном transport теперь явно `expand_all=false`. Расширенный по поручению
координатора handler `GET /api/ops/periods` также по умолчанию только читает.
Единственный найденный собственный getOpsPeriods consumer — эта шкала.

**Breaking lazy-write compatibility:** прямой legacy GET /closing больше не
подготавливает данные; прежний клиент, повторявший GET ради пересчёта, обязан
вызвать POST materialize, затем GET. Клиенты, полагавшиеся на implicit expansion
обычного GET /periods, тоже должны перейти к явной подготовке нужных месяцев.
Существующие поля проекции сохранены, но отсутствие подготовленных строк теперь
честно может давать пустые charges/counters и preparation.required=true.

Для неизвестных прямых consumers временно сохранён только **явный**
`GET /api/ops/periods?...&expand_all=true`. Он выполняет прежний range expansion
под тем же write guard/barrier, не меняет закрытые месяцы и возвращает
`Warning: 299 ...`, `Cache-Control: no-store`, `Deprecation: @1793232000`.
Формат даты заголовка сверён с [RFC 9745](https://www.rfc-editor.org/rfc/rfc9745.html).
Sunset не объявлен: срок удаления не утверждён. Это остаточный deprecated GET
с бизнес-записью, поэтому все legacy GET чистыми не объявляются. Новые клиенты
должны применять POST по каждому нужному месяцу. Полной внешней telemetry
consumers и их миграции этот source search не подтверждает.

## Проверки

Итог: **113 backend PASS** (40.39 с), **10 browser PASS** (24.4 с),
`npm run typecheck`, `compileall` целевых Python-модулей и `git diff --check` — PASS.
Отдельный финальный целевой набор closing/terms: **59 PASS** (18.34 с).

Отдельная `.venv`, локальный Docker `api-modernization-test-20261029`, выделенная
БД `api_closing_test` (public/edge), uploads `/tmp/ops-closing-test-uploads`.
`api_identity_test`, `api_schema_test`, `api_integrated_test`, реальные базы,
дампы, VM и prod .env в этой задаче не использовались.

```sh
# TEST_DATABASE_URL явно задан на выделенную synthetic DB с сегментом test.
export UPLOAD_DIR=/tmp/ops-closing-test-uploads
RUN_OPS_CLOSING_TESTS=1 ../../.venv/bin/python -m pytest \
  tests/test_ops_closing_materialization.py tests/test_ops_closing.py \
  tests/test_ops_term_windows.py tests/test_contract_doc_replay.py \
  tests/test_docs_register.py tests/test_doc_workflow_unit.py \
  tests/test_contract_usage_integrity.py -q
```

Новый suite opt-in использует pure `partner_test_safety` и не допускает fallback
на обычный DATABASE_URL. Проверены repeated GET и полное сравнение domain-state,
перехват SQL DML для terms/charges/close/docs/payments/contracts/energy/DataEntry,
реальные 1200 gross/1000 net, stale term, повтор и четыре параллельные команды,
ожидание настоящего advisory lock в pg_stat_activity, close/reopen/closed freeze,
manual/no-basis/waived/late doc и строгие tenant/domain/scope/parameter negatives.

Frontend: `npm run typecheck`. Browser plugin отсутствует; применён Playwright
Chromium, настоящий компонент и opsService/apiClient transport с synthetic HTTP
routes и контролируемой сменой company context. Это не browser-приёмка с живой БД:
реальные HTTP+SQL суммы проверены отдельно серверным набором.

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
  npx playwright test --config e2e/ops-closing/playwright.config.ts
```

Desktop 1440×900 и mobile 390×844: read-only mount, явный POST→GET, pending,
ошибка/повтор, company/period races с правильной cache invalidation, disabled
подготовка закрытого месяца. Page identity/непустая отрисовка, отсутствие Vite
overlay/unhandled page errors и горизонтального переполнения проверены; screenshot
после подготовки просмотрены (`/tmp/ops-closing-desktop.png`, `...-mobile.png`).
NO_COLOR/FORCE_COLOR warnings относятся к runner; начальная попытка Vite открыть
Orca была отключена в тестовом config open=false и не повторилась.

Этот slice не проверяет полный CI/все маршруты Ops, настоящий мобильный Safari,
внешних consumers, нагрузку и все конкурентные изменения terms/docs/payments.
Общий барьер здесь охватывает перечисленные lifecycle-команды, а не объявляет
все финансовые writer-пути платформы сериализованными. Root ops_terms.store_file,
ops_payments/M06, auth/config/main/identity/product/Swagger не менялись.
Прежняя политика close для неразворачиваемых условий не расширялась: gaps охвата
видны в blocked проекции; blocking close по-прежнему относится к существующим
строкам без суммы. Отдельная политика закрытия всех mapping gaps этим срезом
не объявляется реализованной.
