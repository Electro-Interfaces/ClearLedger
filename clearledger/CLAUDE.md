# CLAUDE.md — ClearLedger

> Инструкции для Claude Code при работе внутри `clearledger/`.

---

## Проект

ClearLedger — система приёма, классификации и верификации документов для бизнеса. Текущая версия (v0.2) — клиентский прототип (SPA). Целевая — Docker-контейнер с FastAPI + PostgreSQL + nginx.

**Путь:** `D:\Users\magsp\OneDrive\Учет ГСМ\clearledger\`

---

## Команды

```bash
npm run dev       # Vite dev-server :3010, авто-открытие браузера
npm run build     # tsc -b && vite build → dist/
npm run lint      # eslint
npm run preview   # превью production-сборки
```

---

## Техстек

- React 19 + TypeScript 5.9 (strict) + Vite 7
- React Router 7 (маршрутизация)
- TanStack React Query 5 (кеш, мутации, инвалидация)
- shadcn/ui (Radix + Tailwind 4) — UI-компоненты в `src/components/ui/`
- react-hook-form + Zod — формы и валидация
- pdfjs-dist — PDF-парсинг (до 20 страниц)
- xlsx, fast-xml-parser, mammoth, postal-mime — парсинг Excel, XML, Word, email
- date-fns — даты
- lucide-react — иконки
- nanoid — генерация ID

**Алиас:** `@/*` → `./src/*`

---

## Архитектура хранилища (текущая, v0.2)

| Хранилище | Что хранит | Ключи |
|-----------|-----------|-------|
| localStorage | DataEntry[] (метаданные), компании, настройки | `clearledger-entries-{companyId}`, `clearledger-company`, `clearledger-companies`, `clearledger-customizations`, `clearledger-seeded` |
| IndexedDB `clearledger-store` | sources (Blob), extracts (текст + поля) | По sourceId |

**Целевая архитектура:** Docker (FastAPI + PostgreSQL 16 + nginx), 3 слоя данных. См. `../LAYER2_ARCHITECTURE.md`

---

## Ключевые сущности

### DataEntry (localStorage)

Основная бизнес-сущность. Поля: `id`, `title`, `categoryId`, `subcategoryId`, `docTypeId?`, `companyId`, `status`, `docPurpose`, `syncStatus`, `source`, `sourceLabel`, `metadata` (Record), `sourceId?`, `createdAt`, `updatedAt`.

**Статусы:** `new` → `recognized` → `verified` → `transferred` | `error`
**Назначение (docPurpose):** `accounting` | `reference` | `context` | `archive`
**Синхронизация (syncStatus):** `not_applicable` | `pending` | `exported` | `confirmed` | `rejected_1c`

**Источники:** `upload`, `photo`, `manual`, `api`, `email`, `oneC`, `whatsapp`, `telegram`, `paste`

### Профили и компании

5 профилей: `fuel`, `trade`, `retail`, `energy`, `general`. Каждый определяет набор категорий, подкатегорий, типов документов, метаполей.

5 компаний из коробки: НПК (`npk`), РТИ (`rti`), ТС-94 (`ts94`), ОФ ПТК (`ofptk`), РусГидро (`rushydro`).

**Источник истины для профилей:** `src/config/profiles.ts` (~37 КБ).

---

## Структура src/

```
components/
  ui/           — shadcn/ui примитивы (НЕ менять вручную, только через shadcn CLI)
  layout/       — MainLayout, Header, AppSidebar, MobileBottomNav
  dashboard/    — KPI-карточки, виджеты, диаграммы
  inbox/        — верификация (split-view: документ + форма)
  intake/       — drag-n-drop, очередь обработки, дубликаты
  data/         — таблицы по категориям, карточки записей
  settings/     — OneCConnectionForm, OneCSyncStatus, OneCSyncHistory
  dev/          — DevPanel (только import.meta.env.DEV)
  normalization/ — NormalizationKpiCards, ValidationResultsTable, EnrichmentResultsTable, ComplianceReport, AuditTab
  common/       — переиспользуемые примитивы
config/         — profiles.ts, categories.ts, companies.ts, statuses.ts
contexts/       — CompanyContext (текущая компания, кастомизация)
hooks/          — useEntries, useConnectors, useNormalization, use-mobile
services/       — бизнес-логика, CRUD, хранилище
  intake/       — pipeline (detect → extract → classify → dedup → save)
pages/          — по маршрутам (Dashboard, InboxPage, IntakePage, ...)
types/          — DataEntry, Connector, IntakeItem, SourceRecord, ExtractRecord
lib/            — queryClient, cn() утилита
```

---

## Паттерны и конвенции

### Данные

- CRUD через `src/services/dataEntryService.ts` — НЕ обращаться к localStorage напрямую
- IndexedDB через `src/services/sourceStore.ts` — для файлов (Blob)
- После мутации данных — `queryClient.invalidateQueries()` для обновления UI
- ID записей — `nanoid()` через `nextId()` из `storage.ts`
- Категории — через фасад `src/config/categories.ts`: `getCategories(profileId)`, `getAllDocumentTypes(profileId)`

### Компоненты

- Используй существующие shadcn/ui компоненты из `src/components/ui/`
- Новые shadcn/ui компоненты: `npx shadcn@latest add <component>`
- Стилизация: Tailwind CSS 4, утилита `cn()` из `src/lib/utils.ts`
- Responsive: `useIsMobile()` хук из `src/hooks/use-mobile.ts` (breakpoint 768px)
- Иконки: `lucide-react`

### Маршруты

Определены в `src/App.tsx`. Главный layout — `MainLayout.tsx`. Все страницы — в `src/pages/`.

### Dev Tools

- `import.meta.env.DEV` — гейт для dev-only кода
- DevPanel: lazy-загрузка в `MainLayout.tsx`
- `window.__cl`: утилиты в консоли (`__cl.stats()`, `__cl.generate(50)`, ...)
- Сервис: `src/services/devToolsService.ts` — чистые функции для манипуляции данными

### Intake Pipeline

`src/services/intake/pipeline.ts` — оркестратор. Стадии:
1. **detect** — тип файла по расширению/MIME
2. **extract** — текст из PDF/Excel/XML/Word/email (с вложениями)
3. **classify** — rule-based, 27 правил в `classify.ts` (документы, email, 1С XML, Excel, чаты, OCR)
4. **dedup** — SHA-256 + Email Message-ID + 1С GUID + семантический ключ
5. **save** — Blob → IndexedDB, DataEntry → localStorage
6. **attachments** — email-вложения рекурсивно через pipeline

---

## Важные файлы

| Файл | Что делает |
|------|-----------|
| `src/config/profiles.ts` | Определение всех 5 профилей (категории, типы, метаполя) |
| `src/services/dataEntryService.ts` | CRUD DataEntry + seed начальных данных |
| `src/services/storage.ts` | Абстракция localStorage (getItem, setItem, nextId, entriesKey) |
| `src/services/sourceStore.ts` | IndexedDB для файлов (sources + extracts) |
| `src/contexts/CompanyContext.tsx` | Контекст компании, профиль, кастомизация |
| `src/services/intake/pipeline.ts` | Intake pipeline оркестратор |
| `src/services/intake/classify.ts` | 27 правил классификации документов |
| `src/services/linkService.ts` | CRUD связей между документами (DocumentLink) |
| `src/services/oneCIntegrationService.ts` | API-сервис интеграции 1С (OData + файловый обмен) |
| `src/hooks/useOneCSync.ts` | React Query хуки для 1С (12 хуков) |
| `src/services/normalizationService.ts` | Нормализация: валидация, обогащение, compliance, аудит TSupport |
| `src/hooks/useNormalization.ts` | React Query хуки для нормализации (7 хуков) |
| `src/components/normalization/AuditTab.tsx` | Полный отчёт аудитора TSupport (5 collapsible-секций, bulk apply) |
| `src/types/index.ts` | Все TypeScript типы |

---

## Интеграция 1С

Живое подключение к 1С:БП 3.0 через OData (чтение) + EnterpriseData XML (запись). UI в Настройках → «Интеграция с 1С» (при `isApiEnabled()`).

| Компонент | Файл |
|-----------|------|
| Форма подключения | `src/components/settings/OneCConnectionForm.tsx` |
| Статус + кнопки sync | `src/components/settings/OneCSyncStatus.tsx` |
| История синхронизаций | `src/components/settings/OneCSyncHistory.tsx` |

Бэкенд: `backend/app/services/onec/` (odata_client, sync_service, mapping, file_exchange, crypto, scheduler), `backend/app/api/onec.py` (13 эндпоинтов).

---

## Документация

| Документ | Описание |
|----------|----------|
| `WHAT_IS_DONE.md` | Что реализовано в v0.2 |
| `../LAYER2_ARCHITECTURE.md` | Целевая трёхуровневая архитектура (ADR) |
| `../ARCHITECTURE_ANALYSIS.md` | Стратегический архитектурный анализ |
| `../PLAN.md` | План системы учёта (философия, модули, AI) |
| `../FUEL_ACCOUNTING_SYSTEM.md` | Модуль учёта ГСМ (сверка, матрица) |

---

## Цветовая палитра badges

Принцип: **минимум цветового шума**. Цвет несёт семантику (статус), а не декорацию (источник).

### Источники (SourceBadge) — нейтральные

Все источники — единый стиль `border-zinc-600 text-zinc-400`. Источник — вторичная информация, не должен перетягивать внимание от статуса. Определение: `src/components/data/SourceBadge.tsx`.

### Статусы (StatusBadge) — семантические, приглушённые

| Статус | Стиль | Обоснование |
|--------|-------|-------------|
| Новый | `border-blue-400/50 text-blue-300/80` | Нейтральный, требует внимания |
| Распознан | `border-amber-400/50 text-amber-300/80` | Промежуточный, в обработке |
| Проверен | `border-emerald-400/50 text-emerald-300/80` | Позитивный, outline |
| Передан | `bg-emerald-600/80 text-white` | Финальный позитивный, filled |
| Ошибка | destructive (shadcn) | Требует действия |
| В архиве | `border-zinc-600 text-zinc-500` | Неактивный |

Определения: `src/config/statuses.ts`, `src/components/data/StatusBadge.tsx`.

### Аудиторские статусы — приглушённые

`emerald-400/40`, `amber-400/40`, `red-400/40` с текстом `/70`. Дублируются в DataTable, RegisterTable, InboxTable — при изменении обновлять все три.

### Правила при добавлении новых badges

- **НЕ добавлять яркие неоновые цвета** (`-500`, `-600` без прозрачности)
- Использовать приглушённые оттенки: `300-400` с прозрачностью `/40-/80`
- Вспомогательная информация (источники, каналы, типы) → нейтральный `zinc`
- Семантическая информация (статусы, ошибки, алерты) → цветная, но мягкая

---

## Правила

1. **Кириллица в конфигах** — все лейблы, названия компаний, категорий — на русском
2. **Не ломать pipeline** — intake pipeline критичен, изменения тестировать через DevPanel
3. **Dev-only код** — оборачивать в `import.meta.env.DEV`, tree-shaking исключит из production
4. **Профили immutable** — `profiles.ts` содержит эталонные наборы. Кастомизация — через `CompanyContext.updateCustomization()`
5. **Base path** — production: `/ClearLedger/` (в `vite.config.ts`)
6. **Порт** — dev-сервер на `:3010`
