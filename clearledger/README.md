# ClearLedger

Система приёма, классификации и верификации документов для бизнеса. AI-native подход: данные проходят автоматический парсинг, классификацию и нормализацию, выходят готовыми к учёту в 1С.

## Текущая версия (v0.2 — прототип)

SPA на React, работает полностью в браузере. localStorage для метаданных, IndexedDB для файлов. Нет бэкенда.

### Возможности

- Мультикомпания — 5 профилей деятельности (fuel, trade, retail, energy, general)
- Приём документов — drag-n-drop, вставка текста, 10+ форматов (PDF, Excel, XML, изображения, email)
- Intake pipeline — detect → extract → classify → dedup → save
- Inbox — верификация с split-view (документ + форма)
- Дашборд — KPI из реальных данных, виджеты, диаграммы
- Таблицы по категориям — с фильтрами (статус, источник, период, подкатегория)
- Коннекторы — UI-каркас для будущих интеграций (1С, банки, ОФД, ЭДО)
- Dev Tools — плавающая панель + `window.__cl` консольные утилиты (только dev)

### Запуск

```bash
npm install
npm run dev        # dev-сервер http://localhost:5173
npm run build      # production-сборка
npm run preview    # превью production-сборки
```

### Техстек

React 19 | TypeScript 5.9 | Vite 7 | React Router 7 | TanStack Query 5 | shadcn/ui (Radix + Tailwind 4) | react-hook-form + Zod | pdfjs-dist | date-fns | lucide-react

### Структура

```
src/
  components/       # UI-компоненты
    data/           #   таблицы, карточки записей
    dashboard/      #   дашборд, KPI, виджеты
    dev/            #   DevPanel (только dev)
    inbox/          #   верификация документов
    intake/         #   приём документов (загрузка, вставка)
    layout/         #   шапка, сайдбар, навигация
    settings/       #   настройки, управление компаниями
    ui/             #   shadcn/ui примитивы
  config/           # профили, категории, статусы, коннекторы
  contexts/         # CompanyContext
  hooks/            # хуки (useEntries, useMobile и др.)
  lib/              # queryClient, утилиты
  pages/            # страницы (по маршрутам)
  services/         # бизнес-логика, хранилище, pipeline
    intake/         #   intake pipeline (detect, extract, classify, dedup)
  types/            # TypeScript типы
```

## Целевая архитектура

Docker-контейнер (FastAPI + PostgreSQL 16 + nginx) с тремя слоями данных:

| Слой | Где | Что |
|------|-----|-----|
| Layer 1 (RAW) | Файловая система `/data/storage/` | Оригиналы файлов, immutable |
| Layer 1a (Staging) | PostgreSQL, schema `staging` | Черновики, очередь AI, результаты обработки. Скрыт от клиента |
| Layer 2 (Public) | PostgreSQL, schema `public` | Нормализованные записи. Клиент работает только с этим |

Один Docker-образ, два варианта деплоя: on-premise или наше облако. Нет мультитенантности — один instance на клиента.

Подробности → [LAYER2_ARCHITECTURE.md](../LAYER2_ARCHITECTURE.md)

## Документация

| Документ | Описание |
|----------|----------|
| [WHAT_IS_DONE.md](./WHAT_IS_DONE.md) | Что реализовано в текущей версии |
| [LAYER2_ARCHITECTURE.md](../LAYER2_ARCHITECTURE.md) | Архитектура хранилища и обработки данных (ADR) |
| [ARCHITECTURE_ANALYSIS.md](../ARCHITECTURE_ANALYSIS.md) | Стратегический анализ архитектуры |
| [PLAN.md](../PLAN.md) | План системы учёта (философия, сравнение, модули) |
| [FUEL_ACCOUNTING_SYSTEM.md](../FUEL_ACCOUNTING_SYSTEM.md) | Модуль учёта ГСМ (сверка, матрица) |
