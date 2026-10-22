# Контакты объекта: сквозная проверка

Настоящие компоненты, apiClient, HTTP и PostgreSQL; только контекст компании и
записи вымышленные. Startup, seed и планировщики рабочего приложения не запускаются.
Тестовый сервер слушает исключительно127.0.0.1. Нужна отдельная локальная PostgreSQL
с базой **contacts_test**. Схема этой базы пересоздаётся, чужие базы не допускаются.
TEST_DATABASE_URL задаётся снаружи, пароли не хранятся в файлах проекта.

1. Backend: `python e2e/location-contacts/server.py` при установленном server/requirements.txt.
2. Frontend: `npx vite --config e2e/location-contacts/vite.config.ts` (15437, proxy18538).
3. Browser: `node e2e/location-contacts/check.cjs`. Нужны установленные браузеры Playwright.
   При другом установленном runtime можно задать TEST_PW_MODULE; CONTACTS_QA_ARTIFACTS
   задаёт закрытый каталог доказательств (по умолчанию/tmp/location-contacts-browser).
4. ОтдельноHTTP/SQL: `PYTHONPATH=server python -m unittest discover -s server/tests -p test_location_contacts_integration.py -v`.

Не запускатьSQL-прогон одновременно с тестовымHTTP-сервером: он чистит эту же тестовую схему.
В общем pytest модуль пропускается, если TEST_DATABASE_URL не указывает на отдельную contacts_test.
API для /__test существует исключительно в этой оснастке и не включается в приложение.

Проверки: назначение/reload, независимая ответственность на двух объектах, одна
карточка человека, редактирование из объекта, снятие назначения без удаления
человека, создание контакта на месте, явное отличие общих контактов организации,
ошибка503/повтор, scoped-роль, светлая/тёмная тема, desktop/Pixel/WebKit/320px.
