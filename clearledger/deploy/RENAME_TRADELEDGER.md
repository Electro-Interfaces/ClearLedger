# Миграция переименования ClearLedger → TradeLedger (инфра, Tier 3)

> Статус: ГОТОВ К ВЫПОЛНЕНИЮ в окне деплоя. Создан 13.06.2026.
> Канон имени — `D:\Users\magsp\Ledger\GLOSSARY.md` (продукт = TradeLedger).
> ⚠ НЕ выполнять частично: имя `clearledger` deploy-coupled (БД + URL). Полумера ломает прод.

## Что УЖЕ сделано (безопасный срез, в рабочем дереве)
Видимый бренд в UI → **TradeLedger**: `index.html` title, `LoginPage`, `RegisterPage`, `Dashboard`, `OnboardingWizard`, шапка `Header.tsx` (была уже). Доки/глоссарий/память — на TradeLedger. Деплой НЕ затронут.

## Что ОСТАЁТСЯ (инфра — только в окне деплоя)
`clearledger` зашит как **deploy-идентификатор** (не просто папка):
- **Postgres**: имя БД + роль + пароль `clearledger` (`server/app/config.py:22` default + прод `.env` `DATABASE_URL`).
- **Публичный URL**: базовый путь `/ClearLedger/` (Vite base, `root_path`, nginx-router, HAProxy на `rproxy`, `apiClient` `/ClearLedger/api`).
- **Папка** `clearledger/` + Docker build-context, `.github/workflows/deploy.yml`, `deploy/docker-compose.yml`, `scripts/backup.sh`.
- **Две backend-ветки**: `clearledger/server/` (канон, деплоится) и корневой `backend/` (легаси — проверить и/или удалить, НЕ деплоить).

## Развилка по БД (выбрать ДО старта)
- **A (мин. риск): оставить имя БД `clearledger`**, переименовать только папку/URL/код. `DATABASE_URL` в `.env` не трогаем → данные на месте, деплой не падает. Рекомендуется.
- **B (полный): переименовать и БД** → `ALTER DATABASE clearledger RENAME TO tradeledger; ALTER ROLE clearledger RENAME TO tradeledger;` + правка `.env`. Требует остановки приложения (нет активных коннектов) + бэкап.

## Последовательность (с откатом)
0. **Закоммитить текущий WIP** (репо сейчас грязный — рестайл + правки имени). Чистый baseline.
1. Ветка `feat/rename-tradeledger`.
2. **Папка**: `git mv clearledger tradeledger` (или оставить — см. ниже); обновить build-context в `docker-compose.yml`, пути в `.github/workflows/deploy.yml`, `scripts/backup.sh`.
3. **URL** `/ClearLedger/` → `/TradeLedger/`: Vite `base`, `root_path` (FastAPI), nginx-router location, `apiClient` базовый путь. На `rproxy` (HAProxy) добавить **301 redirect** `/ClearLedger/ → /TradeLedger/` (закладки/интеграции). ⚠ Сертификат Let's Encrypt — доменный (`ledger.dataworker.ru`), смена ПУТИ его НЕ требует переоформления.
4. **БД**: по выбору A/B выше.
5. **Сборка+деплой**: `docker compose build && up -d` на `services-01`; проверить `https://ledger.dataworker.ru/TradeLedger/` + старый `/ClearLedger/` → 301.
6. **COM-agent** (`1c-dev-01`): `extension_id`/`PullCheckpoint` — проверить, что значение не привязано к строке «ClearLedger» (иначе идемпотентность pull сбросится — НЕ переименовывать `extension_id` без сверки).
7. **Откат**: вернуть ветку/деплой из бэкапа; БД (вариант B) — обратный RENAME.

## Зависимости в коде (грепы для исполнителя)
```
grep -rn "/ClearLedger/" clearledger/ backend/ --include="*.ts" --include="*.tsx" --include="*.py" --include="*.conf" --include="*.yml"
grep -rn "clearledger" clearledger/server/app/config.py .env.example .github/ deploy/ backend/nginx/
```
Деплой-факты сети/серверов — `deploy/DEPLOY.md`, память `project_clearledger_deploy`.
