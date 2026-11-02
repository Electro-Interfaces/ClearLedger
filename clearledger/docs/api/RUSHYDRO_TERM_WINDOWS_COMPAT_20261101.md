# Совместимость прежних окон условий — 01.11.2026

Статус автора: **runtime NOT RUN**. Добавлен только opt-in адаптер
`server/tests/test_rushydro_term_windows_compat_native_pg.py`; существующие файлы
не меняются. Он напрямую импортирует и экспортирует четыре функции из
`tests.test_ops_term_windows` под исходными именами: сохраняются объекты функций,
их тела, декораторы и общий helper. Собственных `test_*` определений нет.
SHA256 прежнего модуля:
`fe8a2321ffbea19439b0107decec13408820396185a35302bd6983bebb80189a`.

Ровно пять прежних случаев:

| Функция | Случай |
|---|---|
| `test_overlapping_create_and_update_are_rejected` | Отказ при пересечении CREATE и UPDATE, сохранение прежней границы |
| `test_new_version_closes_old_window_and_preserves_history` | Новая версия с 01.07.2026 закрывает старую 30.06.2026 и сохраняет сумму |
| `test_invalid_windows_are_rejected` | `start=2026-06-01`, `end=2026-05-01` |
| `test_invalid_windows_are_rejected` | `start=2026-99-01`, `end=None` |
| `test_waiting_patch_checks_fresh_slot_after_concurrent_change` | Ожидающий PATCH проверяет свежую статью и окно после конкурентного изменения |

Последний случай сохраняет прежний опрос `pg_stat_activity` с `asyncio.sleep`.
Это прежняя регрессия, а не новое доказательство детерминированной гонки.

## Допуск и фикстуры

Все проверки допуска стоят до импорта приложения, SQLAlchemy, прежнего теста и
`read_world`: `RUN_RUSHYDRO_TERM_WINDOWS_COMPAT_TESTS=1`, неизменённый чистый
`partner_test_safety_error`, `RUN_RUSHYDRO_PRODUCT_READS_TESTS=1`,
`ROOT_APPROVED_RUSHYDRO_PRODUCT_READS=1`, `APP_ENV=test`, равенство `DATABASE_URL`
и `TEST_DATABASE_URL`. Разрешён только `postgresql+asyncpg`, host `127.0.0.1`,
port `5432`, path `/api_rushydro_reads25_test_20261101`, user `clearledger`,
без query/fragment; `UPLOAD_DIR` абсолютный, с `test` в последнем компоненте.
Без собственного opt-in модуль пропускается; иной неверный допуск отклоняется.
Значения окружения и DSN не выводятся.

Root запускает адаптер с `--noconftest` и своим настоящим
`rushydro_read_factory`: pool size 8, READ COMMITTED, общий session loop.
Используется неизменённая фикстура `read_world` и её точный кеш
`_rushydro_native_reads_world`; чужие строки READ не изменяются.

Отдельный session-scoped setup создаёт собственную компанию
`a6701101-0000-4000-8000-000000000051`, name
`Synthetic legacy-window compatibility`, slug `gig`, profile_id `energy`.
Это исторический slug изолированной тестовой компании; доступа к реальному ГИГ нет.
До INSERT проверяется отсутствие и slug, и UUID; коллизия завершает setup ошибкой,
существующая строка не принимается за свою. Создаются две собственные активные
статьи с кодами `synthetic-window-compat-20261101-a` и
`synthetic-window-compat-20261101-b`; коллизия также отклоняется.
После отдельного COMMIT setup повторно проверяет сохранённые признаки владения
компанией и обеими статьями. Прежний helper выбирает коды глобально, без отбора
по активности и без ORDER BY: наличие этих двух строк не доказывает выбор именно
их. Запросы и результаты helper не подменяются.

Фикстура `db` выдаёт настоящий `AsyncSession` общей фабрики, без savepoint,
обёрток и `begin_nested`; в `finally` выполняет rollback, затем context закрывает
сессию. Конкурентный случай сам делает COMMIT и использует настоящую неизменённую
`app.database.async_session_factory` на том же допущенном DSN. Root отвечает за
проверку владения БД, native schema, закрытие обоих engines/pools в том же loop
и удаление всей своей БД после прогона, включая ошибочный. По-табличной очистки,
создания схемы, новой фабрики/engine/provider в адаптере нет.

## Проверка и границы

Автор выполнил только Git/FS и stdlib AST/hash/compile без исполнения исходника:
точный импорт/экспорт четырёх функций, отсутствие новых testdefs, литеральные пять
случаев из прежнего декоратора, порядок guard/import, структура фикстур,
неизменность прежних entries и `git diff --check`. Pytest, collection,
импорты проекта, ORM/SQL, БД/API/сеть не запускались.
Native запуск и проверка фактической identity функций остаются Root до schema0005;
старый модуль отдельно не собирается. Этот source handoff не подтверждает
HTTP, auth, финансовую приёмку или выпуск РусГидро.
