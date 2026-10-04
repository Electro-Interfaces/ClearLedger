# Исторический слой DataEntry, профили и интеграция 1С раннего интерфейса

> Вынесено из `clearledger/CLAUDE.md` 25.09.2026. Это описание раннего интерфейса и
> демо-слоя, а не рабочего пространства. Рабочие пространства используют FastAPI и
> PostgreSQL, изоляцию компаний и SSO; правила этого файла не переносить на API Ядра,
> «Торговый центр», Чаты, Трек и Поддержку. Сверено с кодом 25.09.2026: несуществующие
> файлы помечены, счётчики (число хуков, правил, эндпоинтов) убраны — они устаревают.

## Хранилища

| Хранилище | Что хранит | Ключи |
|-----------|-----------|-------|
| localStorage | DataEntry[] (метаданные), компании, настройки | `clearledger-entries-{companyId}`, `clearledger-company`, `clearledger-companies`, `clearledger-customizations`, `clearledger-seeded` |
| IndexedDB `clearledger-store` | sources (Blob), extracts (текст + поля) | По sourceId |

## DataEntry (localStorage)

Основная бизнес-сущность раннего интерфейса. Поля: `id`, `title`, `categoryId`,
`subcategoryId`, `docTypeId?`, `companyId`, `status`, `docPurpose`, `syncStatus`,
`source`, `sourceLabel`, `metadata` (Record), `sourceId?`, `createdAt`, `updatedAt`.

**Статусы:** `new` → `recognized` → `verified` → `transferred` | `error`
**Назначение (docPurpose):** `accounting` | `reference` | `context` | `archive`
**Синхронизация (syncStatus):** `not_applicable` | `pending` | `exported` | `confirmed` | `rejected_1c`

**Источники:** `upload`, `photo`, `manual`, `api`, `email`, `oneC`, `whatsapp`, `telegram`, `paste`

## Профили и компании

Профили — тип `ProfileId` в `src/config/profiles.ts`: `fuel`, `trade`, `retail`,
`energy`, `general`, `office`, `works`. Каждый определяет набор категорий,
подкатегорий, типов документов, метаполей. `profiles.ts` — источник истины для профилей.

Компании из коробки — `defaultCompanies` в `src/config/companies.ts` (на 25.09.2026 —
одна, `gig`). Компании рабочих пространств живут в базе Ядра (`core.companies`), а не
в этом файле.

**Профили immutable** — `profiles.ts` содержит эталонные наборы. Кастомизация — через
`CompanyContext.updateCustomization()`.

## Структура src/ раннего слоя

```
components/
  ui/           — shadcn/ui примитивы (НЕ менять вручную, только через shadcn CLI)
  layout/       — MainLayout, Header, AppSidebar, MobileBottomNav
  inbox/        — верификация (split-view: документ + форма)
  intake/       — drag-n-drop, очередь обработки, дубликаты
  data/         — таблицы по категориям, карточки записей (SourceBadge, StatusBadge)
  settings/     — OneCSyncStatus, OneCSyncHistory (форма подключения — pages/oneC/ConnectionPage)
  dev/          — DevPanel (только import.meta.env.DEV)
  normalization/ — NormalizationKpiCards, ValidationResultsTable, EnrichmentResultsTable, ComplianceReport, AuditTab
  common/       — переиспользуемые примитивы
config/         — profiles.ts, categories.ts, companies.ts, statuses.ts
contexts/       — CompanyContext (текущая компания, кастомизация)
hooks/          — useEntries, useNormalization, useOneCSync, use-mobile (useConnectors больше нет)
services/       — бизнес-логика, CRUD, хранилище
  intake/       — pipeline (detect → extract → classify → dedup → save)
pages/          — по маршрутам (Dashboard, InboxPage, IntakePage, ...)
types/          — DataEntry, Connector, IntakeItem, SourceRecord, ExtractRecord
lib/            — queryClient, cn() утилита
```

## Паттерны данных

- CRUD через `src/services/dataEntryService.ts` — НЕ обращаться к localStorage напрямую
- IndexedDB через `src/services/sourceStore.ts` — для файлов (Blob)
- После мутации данных — `queryClient.invalidateQueries()` для обновления UI
- ID записей — `nanoid()` через `nextId()` из `storage.ts`
- Категории — через фасад `src/config/categories.ts`: `getCategories(profileId)`, `getAllDocumentTypes(profileId)`

## Dev Tools

- `import.meta.env.DEV` — гейт для dev-only кода
- DevPanel: lazy-загрузка в `MainLayout.tsx`
- `window.__cl`: утилиты в консоли (`__cl.stats()`, `__cl.generate(50)`, ...)
- Сервис: `src/services/devToolsService.ts` — чистые функции для манипуляции данными

## Intake Pipeline

`src/services/intake/pipeline.ts` — оркестратор. **Не ломать pipeline** — он критичен,
изменения тестировать через DevPanel. Стадии:

1. **detect** — тип файла по расширению/MIME
2. **extract** — текст из PDF/Excel/XML/Word/email (с вложениями)
3. **classify** — rule-based правила в `classify.ts` (документы, email, 1С XML, Excel, чаты, OCR)
4. **dedup** — SHA-256 + Email Message-ID + 1С GUID + семантический ключ
5. **save** — Blob → IndexedDB, DataEntry → localStorage
6. **attachments** — email-вложения рекурсивно через pipeline

## Важные файлы раннего слоя

| Файл | Что делает |
|------|-----------|
| `src/config/profiles.ts` | Определение профилей (категории, типы, метаполя) |
| `src/services/dataEntryService.ts` | CRUD DataEntry + seed начальных данных |
| `src/services/storage.ts` | Абстракция localStorage (getItem, setItem, nextId, entriesKey) |
| `src/services/sourceStore.ts` | IndexedDB для файлов (sources + extracts) |
| `src/contexts/CompanyContext.tsx` | Контекст компании, профиль, кастомизация |
| `src/services/intake/pipeline.ts` | Intake pipeline оркестратор |
| `src/services/intake/classify.ts` | Правила классификации документов |
| `src/services/linkService.ts` | CRUD связей между документами (DocumentLink) |
| `src/services/oneCIntegrationService.ts` | API-сервис интеграции 1С (OData + файловый обмен) |
| `src/hooks/useOneCSync.ts` | React Query хуки для 1С |
| `src/services/normalizationService.ts` | Нормализация: валидация, обогащение, compliance, аудит TSupport |
| `src/hooks/useNormalization.ts` | React Query хуки для нормализации |
| `src/components/normalization/AuditTab.tsx` | Полный отчёт аудитора TSupport (collapsible-секции, bulk apply) |
| `src/types/index.ts` | TypeScript типы раннего слоя |

Файлы рабочей области (`WorkspaceLayout`, `PanelViewTabs`, `ViewParamsBar`,
`WorkspaceFilterBar`, `WorkspaceScopePopover`) — в `docs/WORKSPACE_CONTROLS.md`.

## Интеграция 1С раннего интерфейса

Подключение к 1С:БП 3.0 через OData (чтение) + EnterpriseData XML (запись). UI в
Настройках → «Интеграция с 1С» (при `isApiEnabled()`).

| Компонент | Файл |
|-----------|------|
| Форма подключения | `src/pages/oneC/ConnectionPage.tsx` |
| Статус + кнопки sync | `src/components/settings/OneCSyncStatus.tsx` |
| История синхронизаций | `src/components/settings/OneCSyncHistory.tsx` |

Бэкенд: `server/app/services/onec/` (на 25.09.2026: `odata_client`, `sync_service`,
`com_client`, `com_worker`, `http_agent_client`, `client_factory`, `crypto`,
`exceptions`), роутер `server/app/routers/onec_router.py`. Прежняя ссылка на
`backend/app/...` и модули `mapping`, `file_exchange`, `scheduler` в `onec/` — неверна.

⚠ Это не канал в боевую бухгалтерию. В боевую БП ГИГ документы кладёт расширение
`TradeLedger.cfe`, разбирая очередь `ExportPacket`; чтение боевой БП — только через
COM-агента `services/onec_accounting_read.py`. Канон канала — навык `ledger-center`
(`references/bp-channel.md`).

## Палитра бейджей раннего интерфейса

Перенесена в `DESIGN.md`, раздел «Бейджи статусов».
