# CLAUDE.md — ClearLedger (продукт = TradeLedger)

> Инструкции для Claude Code при работе внутри `clearledger/`.
> 📛 **Имя продукта = TradeLedger** (канон: `D:\Users\magsp\ELSYPLUS\Ledger\app\GLOSSARY.md`). `ClearLedger`/`clearledger/` — текущее имя кодовой базы; переименование в `tradeledger/` — отдельная Tier-3 миграция (затрагивает прод-деплой `ledger.dataworker.ru/ClearLedger/`). Термины входного слоя (Источник/Канал/Поток/Разрез сверки) и **4 слоя данных** (L1 RAW→L2 CLEAN→L3 EXPORT→L4 1C_REF) — по GLOSSARY.

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
  inbox/        — верификация (split-view: документ + форма)
  intake/       — drag-n-drop, очередь обработки, дубликаты
  data/         — таблицы по категориям, карточки записей
  settings/     — OneCSyncStatus, OneCSyncHistory (форма подключения — pages/oneC/ConnectionPage)
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
| `src/components/workspace/WorkspaceLayout.tsx` | Каркас рабочего стола: меню разделов (полная высота) + тулбар + холст |
| `src/components/workspace/PanelViewTabs.tsx` | **Ур. 3** — табы вида пункта (единый компонент для всех панелей) |
| `src/components/workspace/ViewParamsBar.tsx` | **Ур. 4** — панель параметров текущего таба |
| `src/components/workspace/WorkspaceFilterBar.tsx` | **Ур. 2** — чипы фильтра + `PeriodControl` (пресеты, кварталы, календарь-диапазон) |
| `src/components/workspace/WorkspaceScopePopover.tsx` | Модальный выбор сети: регионы · станции/точки · сводка «Выбрано» |
| `src/types/index.ts` | Все TypeScript типы |

---

## Интеграция 1С

Живое подключение к 1С:БП 3.0 через OData (чтение) + EnterpriseData XML (запись). UI в Настройках → «Интеграция с 1С» (при `isApiEnabled()`).

| Компонент | Файл |
|-----------|------|
| Форма подключения | `src/pages/oneC/ConnectionPage.tsx` |
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

## Иерархия управления рабочей области (обязательный паттерн)

Пять уровней сверху вниз. У каждого — своя поверхность и подпись, вес убывает:
чем ниже уровень, тем он локальнее и тише. Пользователь должен понимать, к чему
относится каждый блок управления.

| # | Уровень | Компонент | Оформление |
|---|---------|-----------|------------|
| 1 | **ЭКРАНЫ** — закрепление и переключение экранов | `layout/WorkspaceTabBar.tsx` | `bg-card` + `border-b border-border` + `shadow-soft`, метка `▦ ЭКРАНЫ` |
| 2 | **ФИЛЬТР рабочей области** — общий контур (период · сеть · данные) | `workspace/WorkspaceToolbar.tsx` → `WorkspaceFilterBar.tsx` | `bg-card`, слева **акцентный якорь** (иконка в `bg-primary/10 text-primary` + подпись); чипы-параметры `h-11` с рамками |
| 3 | **ВИД** — табы конкретного пункта меню | `workspace/PanelViewTabs.tsx` | сегменты на плашке `bg-muted/60` + рамка; **активный залит `bg-primary text-primary-foreground`**; метка `ВИД` |
| 4 | **ПАРАМЕТРЫ** — настройка содержимого текущего таба | `workspace/ViewParamsBar.tsx` | панель `bg-muted/30` + `border` + `rounded-lg`, метка `⧩ ПАРАМЕТРЫ` |
| 5 | **Данные** — карточки, таблицы, графики | панели разделов | холст `bg-background` |

### Правила

1. **Не копипастить разметку уровней 3–4.** Табы вида — только через `PanelViewTabs`,
   строка параметров — только через `ViewParamsBar`. Раньше underline-табы были
   продублированы в 8 панелях и вид расходился.
2. **Активный выбор = залитый primary** (`bg-primary text-primary-foreground`) —
   единый язык для табов вида, `ClientTypeToggle` (Все/ФЛ/ЮЛ) и активных чипов фильтра.
3. **Панели-«шасси» (ур. 1–2) на `bg-card`**, рабочий холст (ур. 5) на `bg-background`.
   Границы между зонами — сплошной `border-border`, не полупрозрачный.
4. **Не дублировать метку**, если рядом уже есть контекстный бейдж
   («Только ЮЛ», «ФЛ · псевдонимы», «Карты + ведомости») — передавать `label={null}`.
5. **Не дублировать в заголовке то, что видно в меню.** Название активного раздела
   не выводить отдельной строкой — оно подсвечено в `WorkspaceModeSidebar`.
6. **Специализированные селекторы вместо общей модалки.** Клик по чипу фильтра
   открывает только свои функции: период → `PeriodControl` (пресеты + календарь
   диапазоном), сеть → `WorkspaceScopePopover.tsx` (регионы · станции/точки ·
   панель «Выбрано»). Общий фильтр — по кнопке «Фильтры».
   **Выбор ведётся в черновике и применяется по кнопке** (модель диалога
   «Настройка периода» в 1С), а не на каждый клик. Причина: контур — это
   несколько параметров сразу, их набирают, а не выбирают по одному. Применение
   на лету закрывало окно раньше времени, схлопывало диапазон дат (первый клик
   отдаёт `{from, to: undefined}`) и перезапрашивало данные на каждый чекбокс —
   при 400+ станциях особенно заметно. «Отмена» обязана возвращать как было.
   Чип снаружи показывает применённый контур, подвал окна — черновик.
7. **Не показывать числа без ясной привязки к фильтру.** Счётчики из справочников
   (`charge-sessions/dimensions`) не зависят от выбранного периода — в селекторах
   сети их не выводим, чтобы не вводить в заблуждение.

**Статус раскатки ур. 3–4:** `PanelViewTabs` — во всех 8 панелях; `ViewParamsBar` —
в `ChargeSessionsPanel`, `FuelFillsPanel`, `FuelRetailPanel`, `FuelTariffsPanel`,
`FuelCorporatePanel`. В `RetailPanel` / `TariffsPanel` / `CorporatePanel` (ЭЗС)
собственных строк параметров нет — там только табы.

### Взаимодействие верхнего фильтра и параметров таба

Разделение по вопросу, на который отвечает контрол:

| Слой | Вопрос | Что входит | Где живёт | Персист |
|------|--------|-----------|-----------|---------|
| **1. КОНТУР** | «какие данные я смотрю» | период · сеть/регионы/станции · типы данных · источник | **только** ур. 2 (`FilterContext`) | по компании |
| **2. ПРЕДСТАВЛЕНИЕ** | «как я на них смотрю» | разрез · метрика · шаг/нарезка · топ-N · год-к-году | ур. 4 (`useTabParams`) | по компания × пункт |
| **3. НАВИГАЦИЯ** | «найти строку» | поиск в таблице · сортировка · пагинация | ур. 5, рядом с таблицей | **не персистится** |

**Правила:**

1. **Единственный источник контура.** Период/сеть/типы задаются только наверху.
   Таб контур *читает*, но не переписывает.
2. **Сузить можно, расширить — нельзя.** Локальное сужение (3 станции из выбранных)
   допустимо: это подмножество контура, выводы остаются валидны. Молча выйти за
   контур — недопустимо: на экране будет не то, что заявлено в шапке.
3. **Расширение — только именованным параметром «Горизонт анализа»** и только там,
   где время само является предметом анализа: Динамика (тренд), Нарезка,
   Сравнение периодов. В видах-срезах (Разрезы, Обзор, Время и загрузка,
   Надёжность) своего периода нет — они всегда живут в контуре.
4. **Любое отклонение видно** чипом с ✕ в зоне ПАРАМЕТРЫ (`Горизонт 90 дн ✕`,
   `Только 3 станции ✕`). Скрытых состояний быть не должно — цифры идут в бухгалтерию.
5. **Жизненный цикл.** Смена контура сбрасывает то, что теряет смысл в новой
   выборке — **поиск по таблице и пагинацию** (иначе пользователь остаётся на 5-й
   странице, которой уже нет, или видит пустоту из-за запроса от прошлого периода).
   Хук: `useResetOnScopeChange` из `@/hooks/useScopeReset` — он следит за отпечатком
   контура (период · сеть · типы данных). Сохраняются: **представление** (метрика,
   разрез, шаг, топ-N) и **сужения по справочникам** (станция, топливо, статус) —
   они остаются валидными в любом периоде. Смена компании → сбрасывается всё локальное.
   **Горизонт не персистится между сессиями** (иначе через неделю таб молча покажет
   старый период).
6. **Мостик наверх:** локальное сужение поднимается в контур кнопкой
   «Применить ко всей области» — компонент `ApplyToScope.tsx` (сам прячется,
   когда поднимать нечего или контур уже равен выбору).
7. **Экспорт печатает фактический контур** в шапке файла — хук `useScopeSubtitle`
   из `@/hooks/useScopeReset` (период · область учёта · типы данных · источник).
   Не собирать подпись выгрузки вручную из `dateFrom`/`dateTo`.

⚠️ **Не класть контурные поля в `useTabParams`** — он персистит в localStorage по
(компания × пункт) и переживает сессии. Там место только слою «представление».
Горизонт держать в `useState` + `useEffect` сброса на `[dateFrom, dateTo]`.

### Обязательные правила запросов (из аудита 18.07)

1. **`companyId` — всегда в `queryKey`.** Запросы скоупятся заголовком `X-Company-Id`,
   а не параметром URL: без companyId в ключе React Query отдаёт кеш прошлой компании.
   Исключение — ключи по глобально-уникальному id (uuid комнаты, entryId).
   ⚠️ Не вставлять элементы в середину ключа, по которому идёт `invalidateQueries`
   с префиксом — сломается сопоставление.
2. **Каждый параметр из `queryFn` обязан быть в `queryKey`.** Иначе смена фильтра
   не перезапрашивает данные: пользователь меняет условие, цифры остаются старыми.
3. **Сужение по сети — через `scopeStationCodes`** (`@/services/locationService`):
   резолвит точки и регионы контура в коды станций. Эталон: `useFuelNarrow`
   в `FuelFillsPanel`, `useNarrow` в `ChargeSessionsPanel`.
4. **Подпись экспорта не должна врать.** Если панель не умеет сужать по сети
   (нет параметра в API) — `useScopeSubtitle({ scopeApplied: false })`, тогда в
   шапке файла печатается «Вся сеть» вместо несуществующего сужения.
5. **Никаких `onRun={() => {}}`.** Неподключённое действие должно честно говорить
   об этом (`toast.info('… пока не подключена — нужен источник …')`), а не молчать.
6. **Контрол, который ни на что не влияет, — удалять.** Так был убран фильтр
   «Типы данных»: показывался во всех разделах, не применялся ни в одном.

### Достоверность данных (аудит 18.07)

7. **Скоуп компании — в каждом запросе и в каждом ключе кеша.** Система
   мультитенантная (ГИГ, РусГидро, НПК, РТИ, ТС-94, ОФ ПТК). Проверено больно:
   ключ кеша MSTO без `company_id` отдавал компании Б данные компании А.
   - выборка по id — только через `get_owned` (иначе чужой пакет можно пометить
     обработанным, и смена не дойдёт до 1С);
   - `if company_id:` вокруг фильтра — запрещено: при NULL выгружались все тенанты;
   - нет подключения у компании → **ошибка**, а не подстановка глобальных кредов
     из `.env` (иначе компания молча получает и ПИШЕТ к себе чужие данные).
8. **Границы периода включительно.** `created_at <= 'YYYY-MM-DD'` для `DateTime`
   отбрасывает весь последний день (Postgres приводит к полуночи). Эталон —
   `analytics_service.py`: добавлять `T23:59:59`.
9. **Ставки налогов не хардкодить.** НДС считать из данных (`СуммаНДС`), а не
   `amt*100/122`: у товаров 10% и 0% фиксированная ставка даёт неверные суммы.
10. **Демо-данные — только с заметным баннером и отключёнными действиями.**
    Бейдж 10px у заголовка недостаточен: цифры выглядят настоящими и уходят в
    работу. Никогда не писать сгенерированные записи в реальное хранилище
    (так делал `connectorService.simulateSync` — удалён).
11. **`VITE_API_URL` обязателен при сборке.** Без него `isApiEnabled()` = false и
    приложение молча собирается в офлайн-контур на демо-данных.

**Статус:** модель раскатана во всех панелях — `PeriodOverride` удалён из кодовой
базы полностью. В видах-срезах период берётся из контура; в аналитических
(Динамика, Нарезка) — `HorizonControl.tsx` (бейдж расхождения, без персиста,
сброс при смене контура). Обзорные дашборды (`FuelOverviewPanel`,
`OverviewDashboardPanel`) переведены на контур целиком.

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
