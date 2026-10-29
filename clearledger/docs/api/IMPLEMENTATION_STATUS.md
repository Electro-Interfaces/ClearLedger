# Партнёрский API: интеграционный кандидат

Версионированный child API подключён к `/api/v1`. Он использует отдельный
партнёрский verifier; Core session, SSO handoff и ID Token не заменяют access
token API. Реестр child проверяется явно при сборке приложения: parent mount
сам по себе не запускает его lifespan. Ключ cursor стабилен между workers и
рестартами и выведен из серверного секрета с отдельным назначением HMAC.

По умолчанию `PARTNER_OAUTH_ENABLED`, `PARTNER_API_ENABLED` и
`PARTNER_DOCS_ENABLED` выключены. Для Swagger зарезервированы настройки
`PARTNER_DOCS_CLIENT_ID`, `PARTNER_DOCS_ENVIRONMENT=unconfigured`,
`PARTNER_DOCS_SANDBOX_API_URL`. Сам портал ещё в отдельной работе.
`SOURCE_REVISION` используется как идентификатор состава при экспорте;
значение `unverified` не подтверждает готовность публикации.

Независимая интеграционная проверка: 52 identity и 57 product тестов PASS;
19 тестов настоящей цепочки Core login → consent → code/PKCE → mounted API
PASS. Без подмены verifier проверены SQL scope/total/detail/pagination,
редакция полей, token confusion, живой отзыв client/installation/account,
изменение object scope и привязки cursor, отдельные default-off gates.
Typecheck и 290 frontend unit тестов PASS. Экспортированный curated OpenAPI
прошёл общий offline design gate, runtime readiness остаётся candidate.

При независимом review исходного OAuth-патча обнаружено, что сохранённый
development callback не классифицировался повторно после смены конфигурации.
Canonical exact-match теперь также проверяет действующую URI policy перед
authorize/consent, а token endpoint закрывает непогашенный code с запрещённым
теперь redirect. Regression проверяет dev → prod и выключение loopback flag;
раньше согласованная конфигурация не остаётся бессрочным исключением.

Также issuer проверяется до записей в реестр: порт обязан быть допустимым,
а исходная строка не может содержать control/whitespace/backslash, которые
URL parser способен нормализовать или проверить позднее. Проверено отсутствие
новой регистрации при отказе 503; discovery и curated OpenAPI также закрыты
при непригодном origin. Повторены восемь изменённых issuer/exporter случаев.

Удалённый workflow `.github/workflows/checks.yml` имеет состояние
`disabled_manually`; его не включали. Отсутствие GitHub checks не означает
прохождение CI: приведённые выше результаты относятся к локальным прогонам.

Identity/product тесты переведены на явный opt-in с общим pure safety guard,
без жёсткой привязки к машине/порту/имени БД. На одном интеграционном составе
128 identity/product/полных-chain тестов PASS. Schema suite запускается
отдельным процессом/job: у исполнителя 25 fresh/upgrade/repeat/guard проверок
PASS с настоящими предыдущими исходниками. Запуск в production search_path
`core` и полная матрица старых предметных операций ещё не подтверждены.

Это часть программы модернизации. Write API, все уровни объектов, общий
идентификатор предметных команд, события, оптимизация и перевод всех старых
потребителей ещё не завершены. Локальные тесты не подтверждают независимую
приёмку всей программы, совместимость всех клиентов или рабочий выпуск.
