# ClearLedger

Корпоративная среда подготовки документов для менеджеров компании — **до того**, как они попадут в бухгалтерию. Не буфер, не ETL, не «универсальный intake». Рабочая среда не-бухгалтерских ролей, на которой параллельно строятся слои (учётная подача, маркетинг, финансы, управленческий, аналитика).

Первый клиент — ГАЗИНВЕСТГРУПП (сеть АЗС), профиль `fuel`.

## Идеология (финальная редакция 23.05.2026)

**Цикл «симбиоз с бухгалтерией»:**

1. ClearLedger непрерывно читает БП ГИГ через OData → реплицирует справочники + проводки **закрытых периодов** в свою нормализованную БД (immutable эталон).
2. В рабочей зоне «незакрытый период» накапливает поток источников (STS, банк, ТТН-сканы, email, ручной ввод). Менеджеры обрабатывают: нормализация, классификация, сверка между источниками и **с эталоном**.
3. Когда подготовлено — расширение `GIG_Ledger.cfe` в БП **тянет** готовые документы из ClearLedger по REST/HTTP. Проводки делает 1С.
4. Бухгалтер закрывает период → ClearLedger при следующей репликации видит новый закрытый период → переводит данные в эталон → открывается следующий незакрытый период.

**БП тянет, ClearLedger не пихает.** Это переворачивает наивную схему «ClearLedger → XML → БП».

Подробности — `D:\Users\magsp\.claude\plans\ethereal-tumbling-valley.md` + memory `project_clearledger_ideology_v3.md`.

## Текущая версия — v0.7-snapshot (23.05.2026)

Один большой snapshot-коммит (`7170045`) после 46 дней работы без коммитов. Включает функционал v0.3–v0.6.2 + pipeline-v2. Граница версий условна — см. `WHAT_IS_DONE.md`.

### Что реально работает в коде

- ✅ SPA-фронт (`http://localhost:3010/ClearLedger/`) — 7-режимный конвейер UI, intake pipeline, inbox, dashboard, reports, export
- ✅ FastAPI бэк (16 роутеров: auth, entries, audit, connectors, document_links, settings, intake, references, accounting_docs, reconciliation, audit_data, ocr, export, reports, stats, fuel)
- ✅ STS API клиент на бэке (`server/app/services/sts_client.py`) — JWT, кэш токена, поддержка нескольких `system_id`
- ✅ Fuel CRUD (`server/app/routers/fuel_router.py`) + POST `/api/fuel/normalize`
- ✅ PostgreSQL модели (включая `FuelStation/Shift/Tank/Pump/Receipt/ExportDoc`)
- ✅ Аудитор TSupport UI (демо-данные `DEMO_AUDIT_RESULT`)
- ✅ Docker-compose (postgres + api + nginx)

### Что **не работает** (несмотря на заявки в WHAT_IS_DONE.md)

- ❌ **OData-клиент к БП** — фронт `OneCConnectionForm.tsx` / `useOneCSync.ts` зовёт `/api/onec/*`, бэка нет. Заявленные `server/app/services/onec/*` не существуют.
- ❌ **REST pull-API** — нет эндпоинтов «забери готовое за период».
- ❌ **Расширение `GIG_Ledger.cfe`** для БП — не существует.
- ❌ **Понятие «период» в моделях** — нет `Period`, `PeriodClosure`, `ReferenceSnapshot`.
- ❌ **Alembic-миграции** — только `SQLAlchemy.create_all()`.
- ⚠️ **Аудитор TSupport** работает на демо-данных, бэк-сервиса нет.

### Запуск (dev)

```bash
# SPA-only (без бэка, localStorage)
npm install
npm run dev          # http://localhost:3010/ClearLedger/
```

```bash
# Полный стек (Docker)
docker-compose up --build
# http://localhost/ (web), http://localhost/api/health
```

Логин по умолчанию (docker): `admin@clearledger.ru` / `admin123`.

## Структура

```
clearledger/
  src/                       # React SPA
    components/              # UI компоненты (по доменам)
    services/                # бизнес-логика + хранилище
      fuel/                  # STS-нормализация, типы fuel
      intake/                # intake pipeline (detect, extract, classify, dedup)
      msto/                  # клиент MSTO (онлайн-заказы)
      tradecorp/             # клиент TradeCorp (корп. карты)
      reconciliation/        # сверки (фронтовые)
    pages/                   # маршруты
    hooks/                   # React Query hooks
    types/                   # TypeScript типы (включая channel.ts)
  server/                    # FastAPI бэк
    app/
      models.py              # SQLAlchemy модели
      main.py                # FastAPI приложение, lifespan
      routers/               # API роутеры
      services/              # business services (STS, OCR, sync)
  docker-compose.yml         # postgres + api + nginx
  Dockerfile                 # frontend (multi-stage с nginx)
  server/Dockerfile          # backend
```

## Дорожная карта

См. план переосмысления — `C:\Users\magsp\.claude\plans\ethereal-tumbling-valley.md`.

Кратко по шагам:
- **Шаг 0** ✅ (в процессе) — зачистка, snapshot-коммит, перенос из OneDrive в локальную папку.
- **Шаг 1** — архитектура «периодов» в моделях.
- **Шаг 1.5** — подсистема каналов (Source/Channel/Stage) + первые адаптеры.
- **Шаг 2** — OData-клиент к БП ГИГ + непрерывная репликация эталона.
- **Шаг 3** — STS-смена → нормализованная БД с привязкой к периоду.
- **Шаг 4** — маппинг и сверка с эталоном.
- **Шаг 5** — REST pull-API + новое расширение `GIG_Ledger.cfe` для БП.
- **Шаг 6** — пилот end-to-end + замыкание цикла на одной АЗС за месяц.
- **Шаг 7** — чистка, Alembic, фича-флаги, production-readiness.
- **Шаг 8** — SDK для следующих слоёв (маркетинг/финансы/управленческий).

## Документация

| Документ | Описание |
|----------|----------|
| [WHAT_IS_DONE.md](./WHAT_IS_DONE.md) | Что заявлено в коде по версиям (с маркировкой «фронт-only»/«демо») |
| [LAYER2_ARCHITECTURE.md](../LAYER2_ARCHITECTURE.md) | Архитектура хранилища (ADR, февраль 2026) |
| [ARCHITECTURE_ANALYSIS.md](../ARCHITECTURE_ANALYSIS.md) | Стратегический анализ архитектуры |
| [ARCHITECTURE_v2.md](../ARCHITECTURE_v2.md) | Архитектура v2 — 7-режимный конвейер (апрель 2026) |
| [PLAN.md](../PLAN.md) | План системы учёта (философия, сравнение, модули) |
| [FUEL_ACCOUNTING_SYSTEM.md](../FUEL_ACCOUNTING_SYSTEM.md) | Модуль учёта ГСМ (7-сверочная матрица) |
| [MARKETING_AND_IP_STRATEGY.md](../MARKETING_AND_IP_STRATEGY.md) | Стратегия позиционирования и IP |

## Техстек

| Слой | Технология |
|------|-----------|
| Frontend | React 19, TypeScript 5.9, Vite 7, TanStack Query 5, shadcn/ui (Radix + Tailwind 4), react-hook-form + Zod |
| Backend | Python 3.12, FastAPI 0.115, SQLAlchemy 2.0 (async), asyncpg, PyJWT, bcrypt, httpx |
| База данных | PostgreSQL 16 |
| OCR | Tesseract (rus+eng) на бэке + Tesseract.js fallback на фронте |
| Деплой | Docker + docker-compose + nginx (multi-stage build) |

## Местоположение проекта

Корень репозитория перенесён из OneDrive в локальную папку:

- **Текущий путь:** `D:\Users\magsp\ELSYPLUS\Ledger\app\` (перенесён 2026-06-27 в кластер Ledger; было `D:\Users\magsp\Ledger\`)
- **Старый путь (до 23.05.2026):** `D:\Users\magsp\OneDrive\Ledger\` — нельзя, OneDrive sync ломает hydration cloud-only файлов при работе с git.

Причина переноса — OneDrive периодически выгружает файлы в облако (атрибут `O`), что вызывает ошибки git и docker. Dev-папки не должны жить в OneDrive.
