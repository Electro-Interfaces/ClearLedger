# Контрагенты: изолированная проверка

Настоящие `ContractorsPage`, React Query, apiClient, роутеры справочников и
объектов, HTTP и PostgreSQL. Контекст компании и записи вымышленные.
Бухгалтерская сводка и каналы возвращаются пустыми из тестовых HTTP-ручек;
бухгалтерские числа и импорт этим прогоном не принимаются. Основное приложение,
startup, планировщики и внешние отправки не запускаются.

Нужна отдельная локальная база **counterparties_test**. server.py проверяет
имя/host, создаёт таблицы и **очищает записи** при старте и перед сценарием.
Подключение передаётся снаружи как TEST_DATABASE_URL; рабочую БД использовать нельзя.
Запуски HTTP и браузера последовательные: они сбрасывают одну тестовую базу.

Из `clearledger`:

1. Установить зависимости server/requirements.txt в отдельное Python-окружение.
2. `python e2e/counterparties/server.py` (loopback18547).
3. `npx vite --config e2e/counterparties/vite.config.ts` (loopback15446).
4. `COUNTERPARTY_HTTP_RESULTS=/private/http.json python e2e/counterparties/http_check.py`.
5. `COUNTERPARTY_QA_ARTIFACTS=/private/browser node e2e/counterparties/check.cjs`.

При отличающемся установленном runtime браузеров задать TEST_PW_MODULE абсолютным
путём к @playwright/test; браузеры и пакеты не обновлять ради прогона.
Открывается `/contractors?sub=counterparties`. Подмена CompanyContext существует
исключительно в этом Vite-конфиге; приложение в production её не загружает.

Проверяются поиск/роли/договор и станция, текущая карточка/отмена, CRUD контрагента
и контакта, явная очистка, отказ503/повтор, дубли, пустые данные, сохранение после
reload, клавиатурные подписи, Chromium/Firefox/WebKit,320px,Pixel/iPhone и обе
ориентации. Эмуляция не подтверждает физические телефоны, экранную клавиатуру,
реальный Safari/iOS или рабочий вход. Trace/скриншоты содержат вымышленные записи;
папку артефактов всё равно хранить приватно и не коммитить авторизации.

Отдельные серверные регрессии — `server/tests/test_counterparty_integrity.py`
и `test_counterparty_clear_fields.py`; читать conftest.py и запускать с другой
выделенной TEST_DATABASE_URL: pytest пересоздаёт схемы. На этой базе нельзя
одновременно держать тестовый HTTP-сервер.
