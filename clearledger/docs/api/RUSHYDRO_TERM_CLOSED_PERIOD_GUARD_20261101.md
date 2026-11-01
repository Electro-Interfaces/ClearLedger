# Защита условий в закрытых месяцах

Source-контракт от 01.11.2026. Runtime: **NOT RUN** автором; native-приёмкой
и всей тестовой PostgreSQL управляет Root. Выпуск и изменение схемы не входят в патч.

`create_term` запрещает пересечение нового диапазона с любым закрытым месяцем
компании. `update_term` на месте проверяет объединение прежнего и нового
диапазонов, включая уход из закрытого месяца; промежуток между диапазонами
в объединение не входит. `delete_term` проверяет прежний диапазон и ссылки
начислений: текущий закрытый `period` либо любой NONNULL `closed_in_period`
сохраняет `term_id`, даже вне прежнего диапазона и после reopen. Reopen не
очищает этот исторический маркер. Для открытых и reopened месяцев без таких
исторических ссылок остаётся прежнее удаление ожиданий и FK `SET NULL`.
Учитывается только `CLOSED_STATUSES = ("closed",)` своей компании.

Новая версия проверяет новый диапазон и реально отрезаемый старый хвост:
`effectiveDate..oldEnd`, если `oldEnd >= effectiveDate`, либо бесконечный хвост
при NULL. При `oldEnd < effectiveDate` хвост пуст, старая версия не продлевается.
Закрытое прошлое до effectiveDate сохраняется; закрытый месяц effectiveDate
запрещает операцию. Конечная дата новой версии не скрывает закрытие в старом хвосте.
Нативные правила дат и значений по умолчанию сохранены, включая наследование
`contract.valid_until` при create с `validTo: null`.

Порядок блокировок: company advisory transaction barrier → contract-window
(для условий) → period/row locks. Один ключ `ops-term-period-company:{company}`,
`hashtextextended(key, 0)`: SHARED у трёх writers, EXCLUSIVE у close/reopen.
Операции не завершают транзакции. Попытка SHARED→EXCLUSIVE в одной root-транзакции
получает безопасный `ValueError` до SQL; EXCLUSIVE→SHARED использует имеющуюся
блокировку. Состояние привязано к объекту root-транзакции, поэтому commit/rollback
и повторное использование Session не оставляют старый режим. После прерванного
захвата повторная операция в этой транзакции отклоняется до её завершения.
Nested/savepoint fail closed: они не поддерживаются, поскольку rollback
savepoint может освободить блокировку раньше root-транзакции.

Под блокировками читаются свежие колонки договора/условия без обновления ORM.
До успешной проверки действует `no_autoflush`: отказ не меняет ORM, начисления,
закрытия и историю. Проверка читает существующие месяцы без ограничения в 120
месяцев и без materialize. Причина отказа — `ValueError` без идентификаторов;
прежнее HTTP-преобразование ошибок сохранено.

Конечная native-матрица: **34 ID**, `01–26` — create/inplace/delete/new_version,
границы включительно, NULL, defaults, другая компания, reopened, закрытые FK,
пустой/отрезаемый хвост (case21: reopened без истории разрешён, с маркером — отказ);
`27–34` — обе очередности term/close, свежий reopen,
изоляция компаний, SHARED/SHARED, запрет upgrade, новая root-транзакция и отказ
с dirty/pending ORM. Ожидания зафиксированы в literal-таблице нового теста.
Каждый случай создаёт свои компании и FK, не изменяя shared READ/P1a fixtures.
Гонки используют реальные sessions/events, `pg_locks`/`pg_blocking_pids`, deadlines
и finally-cleanup; время ожидания не служит доказательством результата.

Root запускает тест с внешним `--noconftest` bootstrap: отдельный флаг
`RUN_RUSHYDRO_TERM_CLOSED_TESTS=1` вместе с прежними
`RUN_RUSHYDRO_PRODUCT_READS_TESTS=1`, `ROOT_APPROVED_RUSHYDRO_PRODUCT_READS=1`,
`APP_ENV=test`, равенством `DATABASE_URL == TEST_DATABASE_URL`, точной read25
локальной тестовой целью и абсолютным тестовым `UPLOAD_DIR`. Pure safety
проверяется до импорта приложения. Используются прежние `read_world` cache и
внешняя `rushydro_read_factory` (pool8, READ COMMITTED, общий loop); тест не
импортирует `app.main`, не меняет `sys.modules`, не создаёт схемы/engine/provider.
Root отдельно подтверждает bootstrap/schema/role/OID/source/ownership и удаляет
всю принадлежащую ему тестовую БД и pools. Source AST/compile не являются
runtime PASS и не заменяют эту приёмку.
