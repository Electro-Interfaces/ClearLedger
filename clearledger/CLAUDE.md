# CLAUDE.md — ClearLedger

> Инструкции для Claude Code при работе внутри `clearledger/`.

---

## Проект

ClearLedger — система приёма, классификации и верификации документов для бизнеса. Текущая версия (v0.2) — клиентский прототип (SPA). Целевая — Docker-контейнер с FastAPI + PostgreSQL + nginx.

**Путь:** `D:\Users\magsp\OneDrive\Учет ГСМ\clearledger\`

---

## Команды

```bash
npm run dev       # Vite dev-server :3000, авто-открытие браузера
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

Основная бизнес-сущность. Поля: `id`, `title`, `categoryId`, `subcategoryId`, `docTypeId?`, `companyId`, `status`, `source`, `sourceLabel`, `metadata` (Record), `sourceId?`, `createdAt`, `updatedAt`.

**Статусы:** `new` → `recognized` → `verified` → `transferred` | `error`

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
  dev/          — DevPanel (только import.meta.env.DEV)
  common/       — переиспользуемые примитивы
config/         — profiles.ts, categories.ts, companies.ts, statuses.ts
contexts/       — CompanyContext (текущая компания, кастомизация)
hooks/          — useEntries, useConnectors, use-mobile
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
3. **classify** — rule-based, 22 правила в `classify.ts` (документы, email, 1С XML, Excel)
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
| `src/services/intake/classify.ts` | 10 правил классификации документов |
| `src/types/index.ts` | Все TypeScript типы |

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

## Правила

1. **Кириллица в конфигах** — все лейблы, названия компаний, категорий — на русском
2. **Не ломать pipeline** — intake pipeline критичен, изменения тестировать через DevPanel
3. **Dev-only код** — оборачивать в `import.meta.env.DEV`, tree-shaking исключит из production
4. **Профили immutable** — `profiles.ts` содержит эталонные наборы. Кастомизация — через `CompanyContext.updateCustomization()`
5. **Base path** — production: `/ClearLedger/` (в `vite.config.ts`)
6. **Порт** — dev-сервер на `:3000`
