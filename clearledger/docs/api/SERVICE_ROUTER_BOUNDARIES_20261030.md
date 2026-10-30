# Services → routers: границы и следующий патч, 30.10.2026

Статус: **source-only карта и план готовы к ревью ROOT**. Runtime не изменён,
M04 всей программы этим отчётом не закрывается. Это архитектурный анализ,
не security scan/triage и не подтверждение поведения действующего пространства.

Следующее фактическое извлечение: **P1 — запрос ведущих встречи из
`conf_router.ведущие_встречи` в существующий `services/jitsi.py`**. Отдельный
ещё более механический P2 убирает пять зависимостей от реэкспортов task ACL,
направляя потребителей в уже существующий `services/task_access.py`.
Новый универсальный слой CRUD, клиенты внешних систем и набор новых сервисов
для этих шагов не нужны.

## Зафиксированный источник и состав результата

- Репозиторий: Ledger/app; отдельное предоставленное дерево
  `/home/mag/orca/workspaces/ledger-app/api-intake-upload-client-20261030`.
- Исходное дерево было чистым. Собственная новая ветка
  `agent/api-service-router-boundaries-20261030` создана ровно от
  `d70581b4c98d5a523badf0220c9d2990de4844d8`.
- Git tree `clearledger/server/app`:
  `da3edbc37ad2f4385f543860df4e5291525f32eb`.
- Rootbranch по Dispatch: `MagLook/api-modernization-integration-20261029`;
  кандидат обозначен ROOT как `app492`. Это контекст плана, не проверка образа.
- Новые публичные файлы: этот отчёт, соседний
  `SERVICE_ROUTER_BOUNDARIES_20261030.json`,
  `clearledger/server/tools/inventory_service_router_boundaries.py`.
- Полные манифесты, импорты, проверочные скрипты и receipts остаются приватно
  в `.artifacts/service-router-boundaries/`. Старые отчёты, commits, STATUS,
  runtime, тесты, конфиги, schema и зависимости не менялись.

Инструмент читает **Git blobs выбранного commit**, не working-tree `app`.
Для каждого из всех 492 файлов манифест содержит путь, Git blob, mode, число
байтов и SHA-256. Python AST содержит отдельный SHA-256 канонического
`ast.dump(include_attributes=False)`; строки и столбцы сохранены в ссылках.
Таким образом, перевод строк или изменение комментария видны в byte hash,
даже если AST hash остался прежним.

| Покрытие snapshot | Результат |
|---|---:|
| Файлы / байты всего `app` | 492 / 17 118 036 |
| Python-модули, успешно разобранные Python 3.13.7 | 482 |
| Остальные файлы, с byte hash без AST | 10 |
| Ошибки разбора / неизвестный AST | 0 |
| Python-файлы `app/services`, включая подпакеты | 323 |
| Все import bindings внутри services, независимо от назначения | 4 748 |
| Router import statements / bindings | 20 / 29 |
| Service-файлы / router-модули этих связей | 12 / 10 |
| Наблюдаемые call-spelling references | 36 |
| Узнанные literal loader calls | 2, оба `__import__('sqlalchemy')` |
| Нелитеральные выражения узнанных loaders в snapshot | 0 |

Предупреждение сохранено явно: `services/books_links.py:144`, `SyntaxWarning`
об escape-последовательности. Файл разобран; предупреждение не превращено в
ошибку и не скрыто. Python 3.11 непригоден как грамматический эталон этого
snapshot: первичный пробный обход остановился на f-string нового синтаксиса.
Все итоговые числа, fixture-прогоны и hashes относятся к Python 3.13.7.

## Что именно означает связь

Публичный JSON ограничен 256 KiB (фактически 153 103 байта). В `inventory.edges`
лежат все 29 bindings: ID, source path/byte hash, строка/столбец, вложенный
function/class scope, границы и AST hashes enclosing definitions, guards,
запрашиваемый import target, его определение/реэкспорт и call-spelling refs с
собственными строками/AST hashes. `edge_assessments` даёт решение и основание
для каждого ID. Полных текстов функций, SQL, рабочих записей и credentials
в публичном индексе нет; `call_spellings` — только имена из исходного кода.

Обход AST включает тело каждой функции и класса. Поддерживаются обычные и
относительные imports, aliases, `import app.routers.X`,
`from app.routers import X` и импорт самого пакета routers. Модуль и функция
различаются по Git-модулям/определениям; простые однозначные реэкспорты
прослеживаются до исходного owner. Пример: `_is_admin`, `_visible_to`,
`_can_view_task` в `tasks_router` определены в `services/task_access.py`,
а `projects` в `ProjectsContext.execute` — модуль. Последний вызывается через
`projects.attach_file/decision/link` и конструкторы трёх моделей, не как функция.

Наблюдаемые вызовы — **синтаксические кандидаты по написанию и ancestry scope**.
Это не полный runtime call graph, не reaching-definition/dominance analysis,
не доказательство исполнения или отсутствия вызова. Возможное затенение
параметрами/присваиваниями отмечается, порядок исполнения не вычисляется.
Class namespace, поздние bindings, косвенные callbacks, присваивания aliases,
возвраты loaders и monkeypatching требуют отдельного анализа. Например,
`_run_sts_stations` вызывает переданный `ingest_fn`; это важная предметная
связь, но инструмент не приписывает ей вычисленный runtime target.

Guards фиксируются как source ancestry (`if`, `try`, loops, `with`, match),
с ветвью, строкой и AST hash. Отсутствие guard не означает безусловное исполнение:
предшествующие return/raise и пути вызова не вычисляются. `TYPE_CHECKING`
сохраняется как условие, не объявляется ни исполняемым, ни автоматически
безопасным. Среди реальных router bindings такого guard нет; fixture его проверяет.

`importlib.import_module` и `__import__`, включая импортированные aliases,
учитываются только при статически распознанном loader. Literal имена
разрешаются; относительный `import_module` требует literal package.
Вычисляемое имя/неподдерживаемый относительный `__import__` получает `unknown`.
Строки и комментарии сами imports не создают. В snapshot распознаны только
два loader calls из `edge_nsi.resolve_partner_draft`, строки 886 и 889,
оба к sqlalchemy, без router edge. Произвольный `getattr`, `exec`, пользовательский
loader или alias через присваивание не разрешается: полнота произвольной
динамической загрузки **неизвестна** и не заявлена. Wildcard/re-export cycles,
неразобранные источники и неизвестный owner остаются unknown при их обнаружении.

## Решение по каждой связи

В таблице пути сокращены до `services/` и `routers/`; полные точные ссылки,
AST/byte hashes, owner line и вызовы перечислены в JSON. `extract` — предложение
следующей или отложенной работы, не выполненное перемещение. `keep` означает
сохранить текущую границу на этом этапе. Общие зависимости применимы к РусГидро;
`fuel-only` отмечает границу анализа, без поручения менять клиентский прод.

| ID | Источник: import line; scope | Фактический owner / назначение | Решение и основание |
|---|---|---|---|
| E01 | channel_orchestrator:292; _run_sts_stations | fuel_router:259 NormalizeRequest, Pydantic DTO | **keep**, fuel-only: request shape; per-station savepoint/commit у вызывающего |
| E02 | channel_orchestrator:345; _run_fuel | fuel_router:637 ingest_fuel_shifts | **extract**, fuel-only, позже: существующее ядро STS/L1; flush внутри, progress/commit/rollback снаружи |
| E03 | channel_orchestrator:361; _run_fuel_delivery | fuel_router:1040 ingest_fuel_deliveries | **extract**, fuel-only, позже: сохранить текущие ключи дедупликации, STS-клиент и transaction owner |
| E04 | channel_orchestrator:381; _run_msto | online_orders_router:174 ingest_online_orders | **extract**, fuel-only, позже: tenant connector, reconciliation_proxy и L1, без второго клиента |
| E05 | channel_scheduler:105; _launch | channels_router:327 _run_channel_background | **extract**, позже в channel-runner: собственная async session, rollback/commit, audit и fuel followup; риск выше P1/P2 |
| E06 | context_chats:9; ensure_room | chat_router:186 _assert_participant | **extract**, позже единым chat-access: выбранная компания, ticket/task ACL, membership/scope, audit; не простой предикат |
| E07 | context_chats:9; ensure_room | chat_router:112 _is_insider | **extract**, позже рядом с существующим chat_scope: async сравнение основной компании, не членства |
| E08 | edge_nsi:1221; ingest_station_catalog | store_router:1021 _queue_nsi_delta | **extract**, fuel-only, позже в существующий NSI-контур: очередь целой карточки; helper не делает commit |
| E09 | fuel_shift_refresh:304; refresh_shifts | fuel_router:11 _parse_dt | **extract**, fuel-only, позже: fromisoformat, empty → None; сохранить исключения; caller периодически commits |
| E10 | item_draft_auto:209; разобрать_заявку | store_router:1021 _queue_nsi_delta | **extract**, fuel-only, вместе с E08: не дублировать очередь; caller связывает barcode/решение/дельту и commits |
| E11 | management_local:30; read_local | tasks_router:56 _assert_work | **keep**: docs → legacy plan fallback через assert_company_product; не подменять видимостью Task |
| E12 | management_local:30; read_local | task_access:12 is_admin через tasks_router re-export | **extract / P2**, направить к существующему owner; сохранить local alias и membership-based admin |
| E13 | management_local:30; read_local | tasks_router:389 _names | **keep**: batch projection, _route_of и несколько справочников; не самостоятельный ACL |
| E14 | management_local:30; read_local | tasks_router:529 _not_personal | **keep**: отдельный от ACL отбор общей ленты, исключающий личные записи |
| E15 | management_local:30; read_local | task_access:19 visible_to через re-export | **extract / P2**, прямой owner; company filter остаётся у caller |
| E16 | management_local:50; read_local | work_router:1112 _my_events_clause | **extract**, позже calendar selector: organizer OR attendee; product/company/date/company-visibility остаются снаружи |
| E17 | management_local:71; _chats | chat_router:186 _assert_participant | **extract**, позже вместе с E06; чтение может писать audit; сохранить обработку только 404 |
| E18 | management_local:71; _chats | chat_router:300 _chat_scope → chat_scope.chat_scope_of | **keep**: runtime compatibility hook явно закреплён test_management_runtime_compat; missing/denied остаются fail-closed |
| E19 | meeting_notice:131; известить | conf_router:611 ведущие_встречи | **extract / P1**, в существующий jitsi: один запрос host-флагов и fallback к организатору, без commit/token/ACL |
| E20 | project_work_context:41; ProjectsContext.resolve | chat_router:112 _is_insider | **extract**, позже вместе с E07; сохранить async, mail_only и правила подсказок команды |
| E21 | project_work_context:68; ProjectsContext.execute | project_workspace_router:110/191/237 link/decision/attach_file и модели:104/182/231 | **transport-adapter**: настоящие HTTP handlers, membership/message-history ACL, locks/events/commit; будущие команды требуют отдельного контракта |
| E22 | pulse_digest:137; run_once | pulse_router:1571 pulse_day_data | **extract**, позже cohesive read model Пульса: profile/support mapping и helpers; digest держит advisory lock, email и commit |
| E23 | space_desk:111; _pulse | pulse_router:1571 pulse_day_data | **extract**, вместе с E22: сохранить единственный расчёт, форму cards/stale и fallback плитки |
| E24 | work_links:20; visible_work | task_access:12 is_admin через re-export | **extract / P2**, существующий owner; company/doc ACL и task/doc union не менять |
| E25 | work_links:20; visible_work | tasks_router:529 _not_personal | **keep**: отдельный task-filter общей выдачи, документный ACL другой |
| E26 | work_links:20; visible_work | task_access:19 visible_to через re-export | **extract / P2**, прямой owner, сохранение SQL-предиката и company filter |
| E27 | work_links:52; readable_entity | tasks_router:608 _assert_actor | **keep**: композиция view/edit/oversight, не alias; сохранить 403/404 и personal-author правила |
| E28 | work_links:52; readable_entity | task_access:34 can_view_task через re-export | **extract / P2**, прямой owner; personal exclusion и edit guard остаются у caller |
| E29 | work_links:83; origin | chat_router:241 _history_from | **extract**, позже cohesive chat access: nullable timestamp cutoff; participation/message checks у caller |

Транзакционные наблюдения взяты из тел функций и их вызывающих мест, не из имён.
Отсутствие прямого `commit` не исключает транзитивного эффекта: например,
`_assert_participant` способен вызвать `_audit_foreign_access`/`log_audit`.
`_chat_scope` — wrapper, а не alias; наличие готового chat_scope сервиса само
по себе не отменяет существующий контракт Management. В E21 шесть наблюдаемых
написаний: три обработчика и три конструктора. Их commit/ACL нельзя переносить
на весь импортируемый модуль или объявлять свойствами моделей.

## P1: первое узкое извлечение, приоритет

**Точная allowlist runtime-патча, требующего отдельной Task ROOT:**

1. `clearledger/server/app/services/jitsi.py`: добавить `async meeting_hosts(db, ev)`
   с телом текущей `conf_router.ведущие_встречи`. В этом существующем сервисе уже
   находятся `event_room` и `share_series_url`; локальные SQL/model imports
   соответствуют его нынешнему устройству. Новый сервис/клиент не создавать.
2. `clearledger/server/app/routers/conf_router.py`: сохранить
   `ведущие_встречи(db: AsyncSession, ev: CalendarEvent) -> set` как совместимый
   async wrapper к новому owner. Оставить выдачу JWT, moderator/wait policy,
   присутствие и проверки входа в их нынешних функциях.
3. `clearledger/server/app/services/meeting_notice.py`: заменить только локальный
   router import/use в `известить` на уже импортируемый `jitsi.meeting_hosts`.
   Не менять приглашения, отмену, ICS, SEQUENCE, порядок доставки/commit.
4. `clearledger/server/tests/test_conf_app.py`: при необходимости расширить
   существующие сценарии; новые test-файлы не обязательны.
5. Новый короткий отчёт именно P1 в `clearledger/docs/api/` для подтверждения
   результата и состава. Других runtime/config/schema/lock файлов в allowlist нет.

Совместимость: сохранить await/signature у router wrapper и set-результат;
отмеченные участники имеют приоритет, при пустом результате возвращается
`{ev.organizer_id}`. Не добавлять фильтр company_id, сортировку, новый ACL,
исключение для null organizer или commit под видом перемещения. Helper принимает
уже выбранный event; авторизация и tenant selection остаются у caller.
Это механическое сохранение поведения, не исправление возможных предметных правил.

Проверки будущей Task: до запуска прочитать conftest и использовать только
изолированную тестовую БД/заглушенные отправители. Проверить no-host fallback,
одного и нескольких отмеченных ведущих, приоритет флага над организатором,
одинаковый набор ведущих в уведомлении и входе, отсутствие commit/rollback/token
выдачи в helper. Существующий
`test_conf_app.py::test_ведущие_встречи_и_пять_минут` проверяет роль и ожидание;
дополнить наблюдаемой отправкой приглашения с именами, если этого сценария нет.
Сохранить существующие privacy/entry guards; проверить import-cycle и router
wrapper вызов на изолированном приложении. Регенерация AST должна убрать ровно
E19 из service→router bindings: 19 statements/28 bindings при неизменности остальных.
Эти app-проверки **здесь не запускались**.

Риски: смешанная доставка файлов может оставить новый вызов без helper;
замена только notices на старом runtime не является готовым патчем. Доставлять
три runtime-файла одним составом поверх согласованного кандидата. Wrapper
сохраняет старые импорты, но не доказывает совместимость внешнего monkeypatch
роутера с новым путём notices: будущая Task должна явно проверить нужный seam.
Откат — весь P1 commit; схем и данных для миграции нет. Выпуск не поручен.

## P2: убрать пять обходных импортов существующего task ACL

Отдельная минимальная allowlist runtime: только
`app/services/management_local.py` и `app/services/work_links.py` внутри
`clearledger/server/`; при необходимости расширить существующие
`tests/test_management_api.py` и `tests/test_task_projection_access.py`, плюс
новый отчёт P2. `task_access.py` и `tasks_router.py` менять не требуется.

В `management_local.read_local` локально импортировать
`is_admin as _is_admin`, `visible_to as _visible_to` из `services.task_access`;
в `work_links.visible_work` те же aliases, в `readable_entity` —
`can_view_task as _can_view_task`. Оставить остальные imports, gate, personal
filters, query/result shape и edit guard на месте. Не заменять `_assert_actor`
простым can_view и не удалять старые router реэкспорты.

Основание точное: это уже aliases одного definition, не переписанные ACL.
Для будущего патча нужны сценарии company/private/personal, участие watcher/
participant, чужая компания, company-admin и superadmin, существующий edit
actor guard и read-only проекция. Проверить, что server imports используют
тот же owner и старые router imports ещё доступны; наблюдать query results и
статусы, а не только наличие строк импорта. Сохранить Management tests на
оригинальные chat hooks. Старые раздельно обновляемые runtimes без task_access
требуют отдельной проверки состава, snapshot не подтверждает их совместимость.

Из-за смешанных statements число bindings уменьшится на пять, но число
statements останется 20: в каждой исходной строке останутся другие router
symbols. Не задавать для P2 неверный критерий «пять строк импорта исчезло».
При последовательном P1 + P2 ожидаются 19 statements / 23 bindings.
Текущие 36 call-spelling refs не являются требуемым runtime-числом вызовов.

## Воспроизведение и доказательства

Из корня этого дерева, без зависимостей приложения:

```bash
~/.local/bin/python3.13 -I clearledger/server/tools/inventory_service_router_boundaries.py \
  --git-pin d70581b4c98d5a523badf0220c9d2990de4844d8 \
  --output .artifacts/service-router-boundaries/root-regeneration
```

Output должен быть **новым** каталогом внутри репозитория. Инструмент запрещает
`..`, symlink components, существующий output и сокращённый pin; читает только
regular Git blobs выбранного `app`, отключает replacement objects. Лимиты:
4 000 файлов, 8 MiB на blob, 100 MiB суммарно, 1 MiB generated public.json,
90 секунд (SIGALRM плюс timeout Git subprocess). POSIX/Python 3.13+ обязательны.
Приложение, ORM и DB drivers не импортируются, AST не исполняется; `eval` нет.
Исходники инструмента просмотрены статически перед запуском; compile только
в памяти. Публичный companion собирает reviewed assessments поверх inventory;
независимая регенерация должна сравнивать его `inventory`, не ручные оценки.

```bash
~/.local/bin/python3.13 -I - <<'PY'
import json
from pathlib import Path
published = json.loads(Path('clearledger/docs/api/SERVICE_ROUTER_BOUNDARIES_20261030.json').read_text())
regenerated = json.loads(Path('.artifacts/service-router-boundaries/root-regeneration/public.json').read_text())
assert published['inventory'] == regenerated
PY
```

| Доказательство | SHA-256 |
|---|---|
| source tool | `7c333ba8b6591a2665751bfa3e3e116db3a244ffa710f85a584ee812218bb283` |
| final-a/manifest.json | `59fbdcab550bcedbf691422ecd53afd646500e0159b2838c863771ea061548b9` |
| final-a/public.json | `327b513380bd75b1fa311ffdd6ac0e45cb98261930bcab13de7f3f61389ecc66` |
| final-a/service-imports.json | `c743b0e226f2c08317c922aaee9ee7d7ba3170098bc56d075f723786b4c5e39b` |
| fixtures.py | `6d8e8931ee258f334658f2080370470ec096bdd3a6c3f22dbfc746b13f01956e` |
| independent_oracle.py | `430df56d9a085271f4688772147df5c094d6586e2e023a3a4b69bc3e6acbf05d` |
| fixtures-result.json | `6c5dea969a19042fe7b57ecb3b6f17b6d02d1d231e298a918ba653f12fd5602e` |
| oracle-result.json | `dec5b30955c1b818b9706946ccf45d55bd9bcfdf6ffeaa324f76d3936fe152e3` |
| validation.json | `d23c4e82daea7f3464b1ad5dfb0615af29e4b4e85276e43eb0278ff4a2002549` |

Все короткие artifact paths таблицы лежат под
`.artifacts/service-router-boundaries/`. `final-a/receipt.json` фиксирует
версии, hashes, размеры и лимиты; `final-b/` — второй прогон финального tool.
Четыре outputs, включая receipt, **побайтно идентичны** между этими прогонами.
`run-a/run-b` — промежуточные диагностические результаты прежней версии tool,
их hashes не являются итоговым доказательством.

Pure fixtures (приватный `fixtures.py`, исходник доступен ROOT в этом дереве)
загружают только tool через stdlib runpy, никогда app. **12/12 PASS**:
комментарии/строки, relative import, class+method nesting, aliases, module import
против функции, package alias, re-export owner, TYPE_CHECKING guard, три literal
loader формы, два вычисляемых unknown, shadowing и явный parse error.
Отдельный простой `ast.walk` oracle с собственной нормализацией относительных
imports повторно прочёл все 323 service Python blobs и независимо подтвердил
29 import refs с точным совпадением path/line/requested/AST hash и 20 sites.
CLI negative cases existing output/traversal/short pin завершились отказом.

Не запускались приложение, pytest collection, прежние принятые наборы
59/35/117 или другие app tests, SQL, Docker, install/build, HTTP/API и VM-команды.
Git push ветки с тремя новыми безопасными файлами — только передача результата
по Dispatch; он не является выпуском или разрешением на runtime-патч.
