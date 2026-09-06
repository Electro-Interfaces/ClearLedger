# Ledger/app — вход для Claude Code

Здесь находятся Ядро пространства и React-интерфейс, приложение — `clearledger/`.
Сначала читать `clearledger/CLAUDE.md` и текущий общий канон:
`D:/Users/magsp/ELSYPLUS/ecosystem-deploy/docs/CURRENT-STATE.md`.

Сводка включает работу всех агентов: Проекты/Чат/Трек, сценарии, Пульс, календарь,
Mango и фактические версии пространств. Коммит общего дерева не доказывает,
что оно целиком проверено и выпущено. Перед выкаткой выбирать отдельный состав
и сохранять доработки ГИГ по работающему образу.

Основной рабочий инструмент пользователя — Claude. Память этого контекста:
`C:/Users/magsp/.claude/projects/D--Users-magsp-ELSYPLUS-Ledger-app/memory/`.
Общий порядок памяти — `D:/Users/magsp/ELSYPLUS/ecosystem-deploy/docs/AGENT-MEMORY.md`.
В конце работы обновлять общие документы и указатель Claude; память Codex отдельно
не заменяет передачу результата.

Проверки из `clearledger`: `npm run typecheck`, `npm run test:unit`.
Backend-тесты запускать только с отдельной `TEST_DATABASE_URL`: conftest удаляет
тестовые схемы. Сборку/выкатку выполнять навыком `elsy-deploy` под явный стек.

Origin `Electro-Interfaces/ClearLedger` публичный. Исходники и вымышленные примеры
можно коммитить; рабочие выгрузки, credentials, сессии и операционные отчёты клиентов
хранятся локально или в частном репозитории поставки.
