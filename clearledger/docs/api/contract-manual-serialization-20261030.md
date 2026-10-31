# Сериализация native PATCH договора и импорта 1С

Дата: 30.10.2026. Исходная база: `b46eb062`. Предмет: бизнес-модель Contract,
не инфраструктурный пакет `api_contracts`.

## Статус исследования

Actual baseline подтвердил потерю сохранённых ручных NULL в обоих порядках
транзакций: **2 FAILED, 2 PASSED**, 16.95 секунды. Оба контроля с прежним
upstream прошли. По отдельному разрешению координатора подготовлена bounded
правка native PATCH. Авторская проверка кандидата: **16 PASS**, затем согласованный
combined из 14 модулей: **117 PASS**, без SKIP/DESELECTED. Merge/deploy отсутствуют.

## Факты исходной базы

`references_router.update_contract`: parse UUID → `get_owned` → snapshot полей →
проверка сторон компании → применение только переданных реквизитов →
`mark_reference_changes` → flush → refresh. `get_owned` использует обычный
`db.get`, проверяет visit-company, superadmin, членство и object scope; row lock
и advisory lock здесь отсутствуют. Его чтение может вернуть ранее загруженный
объект identity map. Snapshot и маркеры вычисляются до flush.

`_sync_contracts`: существующий company-scoped advisory barrier
`lock_manual_creation(..., "contract")` → flush своих pending изменений → индексы
контрагентов/организаций → company-filtered `SELECT Contract` с
`populate_existing=True` → чтение upstream → matcher/apply_import_values → flush.
Импорт не делает commit. `apply_import_values` сохраняет только поля,
перечисленные в маркерах переданного ORM-объекта; raw обновляется отдельно.

Обозначения порядка: C — существующий company/contract advisory barrier;
R — row/FK locks при записи. Импорт получает C до своих flush/R. Native PATCH
пока не присоединён к C; его собственные R возникают при финальном flush.
Обычные проверки сторон читают записи без `FOR UPDATE`. Поэтому возможная
правка должна получать C **до** native flush/R, подавлять преждевременный
autoflush при поиске компании и повторно читать текущий объект/проверять допуск
после ожидания. Добавление C после R создаст обратный порядок блокировок.
Проверка этой гипотезы и минимальное предложение предшествуют runtime-правке.

## Подготовленные actual cases

Новый `server/tests/test_contract_manual_serialization.py` использует synthetic
world существующего freshness harness: настоящий native HTTP POST/PATCH,
настоящие membership/ownership/marker/matcher/SQL, отдельные request sessions,
настоящий `_sync_contracts`; fake Source заменяет исключительно транспорт 1С.
Ни lock helper, ни SELECT, ни manual marker semantics не подменяются.

| Порядок | Изменённый источник | Контроль с прежним источником |
|---|---|---|
| Импорт выбрал Contract первым | PATCH сохраняет ручной NULL до UPDATE импортера либо ждёт общий C | Не объявлять устаревший Python-объект persisted overwrite |
| PATCH сделал flush первым | Импорт либо читает до commit и ждёт row lock, либо ждёт общий C до SELECT | Ручной NULL должен сохраняться без ложного finding |

Событие fake Source.describe_entity возникает строго после настоящего SELECT
договоров. Dependency gate останавливает request после настоящих flush/refresh
до caller commit. При ожидании импортера фиксируются `pg_blocking_pids` и
недоставленный lock в `pg_locks`; polling interval сам по себе доказательством
не служит. Исправленный барьер может остановить импорт до SELECT: тест принимает
именно PostgreSQL advisory wait, не требует недостижимого старого SELECT.

До завершения ручного commit, когда порядок это позволяет, отдельная сессия
подтверждает четыре NULL и markers. После обеих транзакций новая сессия читает
сохранённые nullable реквизиты и маркеры. Проверяются UUID, стороны, source
identity, creation metadata, raw, незамороженный signed, scope/basis/liability,
links/locations, отсутствие дубликатов и прежняя статистика импорта.
Все значения, суммы и организации вымышлены.

## Actual baseline

Исходный runtime `b46eb062`, тест SHA256
`1cfb106e16c1f5c67e5f7cc4044b66806640cdf3d9453e77b06b6b5f35586c28`.
Один запуск собрал ровно четыре сценария; child завершился EXIT 1 и был reap.
Оба падения произошли на финальном чтении сохранённых колонок после двух
commit, а не на fixture, timeout или отсутствующем символе.

| Поле | После ручного commit | После обоих commit, оба порядка |
|---|---|---|
| valid_until | NULL | 2027-12-31 |
| amount_limit | NULL | 200.00 |
| amount_incl_vat | NULL | false |
| payment_term_days | NULL | 20 |

Все четыре manual markers остались в БД. При импорт-first native PATCH смог
сделать flush/commit после SELECT импортера до его UPDATE. При PATCH-first
импорт прочитал прежнее состояние до manual commit и реально ждал transactionid
lock ручного writer при UPDATE. После разблокировки он сохранил прежний план
обновления и затёр ручные NULL. Same-upstream controls в обоих порядках сохранили
NULL; устаревшее Python-значение без настоящего UPDATE не названо потерей данных.
Полный закрытый лог: `.artifacts/baseline.log`.

Применён просмотренный private runner, Python 3.13.7/PG16, отдельная синтетическая
`api_contract_manual_serialization_test` на loopback:33546. Перед подключением
проверялись точные own/admin URI, перед импортом pytest — общий
`partner_test_safety_error`. Child работал из пустого cwd с абсолютными путями,
UPLOAD_DIR, DATABASE_URL=TEST_DATABASE_URL, APP_ENV=test, отключённым plugin
autoload и явным pytest_asyncio.plugin. HOME унаследован без изменения; рабочие
`.env`, connector settings и внешние авторизации в child не передавались.
Разрешённые SET LOCAL ограничивали только две transaction timeouts.

После child EXIT/reap fresh контроль показал public/edge tables=0 и own
connections=0. БД удалена обычным DROP без FORCE/terminate; fresh контроль
подтвердил DB exists=0, other client backends=0, max_locks_per_transaction=64.
Admin connection закрыт; координатору передан `SQL_SLOT_RELEASED`.

## Исправление

Только native update_contract присоединён к существующему C до любых R:
начальные get_owned/discovery и получение C выполняются под no_autoflush,
после C явно flush своих pending изменений, затем company/id-filtered
populate_existing SELECT и повторный get_owned до snapshot. Исчезнувший или
перемещённый за исходную компанию договор возвращает прежний 404; чужую
компанию нельзя принять под прежним C. Matcher, raw/source identity, caller
commit, статистика и существующий импорт остаются прежними.

Членство перед повторным get_owned перечитывается отдельным scoped
populate_existing запросом и удерживается сильной ссылкой; простого повторного
get_owned недостаточно для обновления старого UserCompany в identity map.
Отсутствие членства даёт прежний 404. Общие deps/auth/lock helper не менялись.
Настоящий visit listener продолжает ограничивать UserCompany своим company;
object listener покрывает ServiceLocation/ChargeSession, а допуск Contract
проверяет get_owned по актуальному membership. Организация, глобальные права,
живое состояние superadmin/учётной записи в эту гарантию не входят.

Расширенный тест SHA256
`4b19dc90f9d7c6f8347f2fecd088fb872bc48a399c6d9a4681a64b9646adf388`
фактически собрал 16 случаев. Первые четыре случая и их параметризация
сохранены с прежним AST; измеренные baseline bytes отдельно сохранены в private
артефакте с прежним SHA256 `1cfb106e…`.

Дополнительно прошли два actual loader controls: pending dirty request
до C; payload, совпадавший с прежним значением, после чужого commit.
Семь сценариев удерживают старые Contract/UserCompany в request session,
фиксируют настоящий advisory wait, затем коммитят revoke/scope/demotion,
сохранение member/admin, перемещение или удаление договора. Ещё три проверяют
чужой Contract и чужие counterparty/organization в PATCH. Все сценарии прошли
только после отдельного разрешения на candidate SQL.

## Actual проверки исправления

Новый модуль: **16 PASS за 18.81 с**. Затем один согласованный combined:
**117 PASS за 38.37 с**, фактически collected 117, без SKIP/DESELECTED.
В обоих случаях child EXIT 0/reaped. Исходники runtime и теста между запусками
не менялись; повторные широкие прогоны без новой причины не выполнялись.

| Модуль в server/tests | PASS |
|---|---:|
| test_contract_manual_serialization.py | 16 |
| test_corporate_counterparty_commands.py | 23 |
| test_counterparty_commands.py | 16 |
| test_counterparty_empty_inn.py | 9 |
| test_reference_identity_api.py | 10 |
| test_counterparty_clear_fields.py | 1 |
| test_contract_creation_replay.py | 1 |
| test_contract_doc_replay.py | 3 |
| test_channel_failure_rollback.py | 1 |
| test_counterparty_explicit_null.py | 9 |
| test_reference_identity_onec.py | 6 |
| test_contract_manual_freshness.py | 10 |
| test_contract_scope.py | 9 |
| test_reference_overrides_unit.py | 3 |

Проверены changed/same upstream в обоих порядках, сохранение nullable и
manual markers после двух commit, актуальный snapshot после C и pending
flush под C. Ручные UUID/стороны/source identity/creation metadata, raw,
scope/basis/liability/links/locations и статистика проверяются настоящим
persisted read. Прежние тесты сохраняют omitted/unchanged/null→null, caller
rollback/commit, identity conflicts, реквизиты/type/scope, replay и foreign
company поведение. Все старые тестовые файлы остались без изменений.

Runner: `.artifacts/run-contract-serialization.py`, SHA256
`bba45986012fe11e476b9771bb9e695c52fff71e9a03805a9304d416e2ce83f0`.
Тот же exact target/guard, assigned Python 3.13.7, пустой cwd, явный async
plugin, абсолютные пути/UPLOAD, APP_ENV=test и HOME без override. Включались
`RUN_CONTRACT_MANUAL_SERIALIZATION_TESTS`, `RUN_CONTRACT_MANUAL_FRESHNESS_TESTS`,
`RUN_COUNTERPARTY_COMMAND_TESTS`, `RUN_CORPORATE_COUNTERPARTY_COMMAND_TESTS`.
Фактический guard empty-INN использует COMMAND_TESTS; лишний отдельный flag
не нужен. Закрытые логи: `.artifacts/candidate.log`, `.artifacts/combined.log`.

Отдельный opt-out с serialization flag=0 и действующим prepytest target
guard: **0 collected / 1 module SKIP за 0.17 с**, ожидаемый child EXIT 5/reaped;
database fixture не запрашивалась. Это проверка opt-in, не пропуск в combined.
Лог: `.artifacts/optout.log`.

После последнего child fresh контроль вновь показал public/edge tables=0,
own connections=0. Выполнен обычный DROP своей БД; fresh DB exists=0,
other client backends=0, max_locks_per_transaction=64, admin/probes закрыты.
Координатору передан `SQL_SLOT_RELEASED`; после этого SQL не выполнялся.

Это авторские локальные actual SQL/HTTP dependency-fixture проверки с fake
OData; независимый прогон координатора на момент отчёта не заявляется.

## Ограничения

Исследование ограничено native PATCH промо-реквизитов и `_sync_contracts`.
Оно не доказывает сериализацию всех writers модели Contract, liability,
магазинных документов и документных сценариев. Реальные данные/договоры,
коннекторы/1С, внешние API, браузер, SSH, CI, merge и deploy не используются.
Программа M00–M19 остаётся незавершённой.


## Независимая приёмка общего состава

Координатор перенёс source919b9c8d в интеграцию коммитомf5f2de3b и повторил
те же14модулей на свежей собственной synthetic БД
`api_root_contract_manual_serialization_test`: **117 PASS за35,04с**,
0FAIL/ERROR/SKIP/DESELECTED, child EXIT0/reaped. Проверены runtime/test SHA256
выше, AST изменения только update_contract и побайтовая неизменность13прежних
модулей тестов относительноb46eb062. Отдельно сверены SHA исходного baseline
файла1cfb106e и неизменность AST исходных четырёх параметризованных сценариев.
Private evidence: `.artifacts/root-contract-manual-serialization-repeat.py`,
`.artifacts/root-contract-manual-serialization-counterparty-final.log`,
`.artifacts/root-contract-serialization-boundaries.py`. Артефакты не публикуются. После child fresh public/edge tables0 и
ownconns0, ordinary DROP, fresh DBexists0/maxlocks64, admin/probes закрыты.
Это приёмка ограниченного native PATCH/import взаимодействия, не полного CI
и не всех writers Contract. Рабочие данные и сервисы не менялись.
