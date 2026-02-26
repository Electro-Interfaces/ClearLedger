# ClearLedger — что реализовано

## Идея

ClearLedger — система приёма, классификации и верификации документов для компаний с разными профилями деятельности. Текущая версия (v0.2) — полностью клиентский прототип: метаданные в localStorage, файлы в IndexedDB. Следующий этап — переход на серверную трёхуровневую архитектуру (см. [LAYER2_ARCHITECTURE.md](../LAYER2_ARCHITECTURE.md)).

> **Архитектурное решение (2026-02-26):** Зафиксирована целевая архитектура — Docker-контейнер (FastAPI + PostgreSQL + nginx) с тремя слоями данных: Layer 1 (RAW-файлы), Layer 1a (staging, скрыт от клиента), Layer 2 (public, нормализованные данные). AI-обработка на облачном сервере. Подробности → [LAYER2_ARCHITECTURE.md](../LAYER2_ARCHITECTURE.md)

---

## Мультикомпания

5 компаний из коробки: НПК, РТИ (fuel), ТС-94 (trade), ОФ ПТК (retail), РусГидро (energy). Каждая компания привязана к **профилю деятельности**, который определяет набор категорий, подкатегорий, типов документов и шаблонов коннекторов.

**Почему так**: у каждого бизнеса своя номенклатура документов. АЗС оперирует ТТН, паспортами качества, Z-отчётами. Розница — ЕГАИС, Меркурий, маркировка. Энергетика — дефектные ведомости, наряды-допуски. Профильная система позволяет одному приложению обслуживать все направления без дублирования кода.

Переключение компании — выпадающий список в шапке. Все данные, категории, KPI мгновенно меняются.

### Профили

| Профиль | Компании | Категории |
|---------|----------|-----------|
| fuel | НПК, РТИ | Первичные (ТТН, акты, счета, договоры, качество), Финансовый учёт (платежи, касса, сверки), Операционный (поставки, остатки, смены, продажи, метрология), Кадры, Юридические, Медиа |
| trade | ТС-94 | Первичные (ТОРГ-12, акты, счета, договоры), Финансовый (платежи, касса), Операционный (реестры продаж), Кадры, Медиа |
| retail | ОФ ПТК | Первичные (накладные, возвраты, списания), Контроль (сертификаты, ЕГАИС, маркировка, Меркурий), Финансовый, Операционный, Медиа |
| energy | РусГидро | Первичные (акты ТО, дефектные ведомости, договоры), Операционный (журналы, протоколы, наряды-допуски), Финансовый, Медиа |
| general | (резерв) | Первичные, Финансовый, Медиа |

### Кастомизация компаний

Для каждой компании можно отключить отдельные категории, подкатегории, типы документов и шаблоны коннекторов — без изменения профиля.

---

## Приём документов — универсальный загрузчик

Страница `/input` — «бросай всё сюда». Две вкладки: **Файлы** (drag-n-drop) и **Вставка текста** (textarea).

Поддерживаемые форматы: PDF, изображения с OCR (JPG/PNG/TIFF/WebP), Excel/CSV, XML (1С/ФНС), .eml (email), .txt, .json, .doc/.docx, WhatsApp chat (.txt), Telegram export (.json). Лимит 50 МБ.

При загрузке файл проходит **intake pipeline** из 5 стадий:

### Pipeline

```
Файл/Текст → DETECT → EXTRACT → CLASSIFY → DEDUP → SAVE
               │          │          │          │       │
            тип файла   текст    категория   hash    IndexedDB
            парсер     metadata   docType    check   + localStorage
```

1. **DETECT** — определение типа по расширению и MIME. Выбор парсера.
2. **EXTRACT** — извлечение текста. PDF → pdfjs-dist (до 20 страниц). Остальное — как plain text. OCR и Excel — заглушки для следующих фаз.
3. **CLASSIFY** — rule-based классификация. 10 правил по приоритету (см. таблицу ниже). Каждое правило проверяет имя файла и содержимое текста regex-ами. Параллельно извлекаются поля: номер, дата, сумма, ИНН, контрагент.
4. **DEDUP** — SHA-256 хеш файла + семантический ключ (тип + номер + дата + контрагент). Если совпадает с существующей записью — пометка «дубль» с возможностью принудительного сохранения.
5. **SAVE** — blob в IndexedDB, запись DataEntry в localStorage.

### Правила классификации

| Приоритет | Документ | Категория/Подкатегория | Уверенность |
|-----------|----------|----------------------|-------------|
| 1 | ТТН | primary/ttn | 85% |
| 2 | ТОРГ-12 | primary/torg | 85% |
| 3 | Счёт-фактура | primary/invoices | 80% |
| 4 | УПД | primary/invoices | 85% |
| 5 | Счёт на оплату | primary/invoices | 75% |
| 6 | Акт сверки | primary/acts | 85% |
| 7 | Акт приёма-передачи | primary/acts | 80% |
| 8 | Акт выполненных работ | primary/acts | 70% |
| 9 | Договор | primary/contracts | 80% |
| 10 | Паспорт качества | primary/quality | 85% |
| 11 | Email (со счётом/актом) | primary/invoices | 60% |
| 12 | Email (общий) | primary/unclassified | 30% |
| 13 | 1С: Накладная (CommerceML) | primary/ttn | 75% |
| 14 | 1С: Счёт-фактура | primary/invoices | 80% |
| 15 | ФНС: Электронный документ | primary/invoices | 85% |
| 16 | 1С: Платёжное поручение | financial/payments | 75% |
| 17 | 1С: Акт выполненных работ | primary/acts | 75% |
| 18 | 1С: Документ (общий) | primary/unclassified | 40% |
| 19 | Excel: Реестр транзакций | operations/sales | 65% |
| 20 | Excel: Остатки в резервуарах | operations/inventory | 70% |
| 21 | Excel: Банковская выписка | financial/payments | 65% |
| 22 | Чат: обсуждение документов | primary/unclassified | 35% |
| 23 | Чат WhatsApp (общий) | media/photos | 25% |
| 24 | Чат Telegram (общий) | media/photos | 25% |
| 25 | Скан документа (OCR, ТТН/СФ/акт) | primary/unclassified | 55% |
| 26 | Скан (OCR, текст) | primary/unclassified | 35% |
| 27 | Фото (без текста) | media/photos | 40% |

### Извлечение полей (regex)

- **Номер**: `(?:№|номер|N)\s*([...])`
- **Дата**: `(\d{2}[.\/-]\d{2}[.\/-]\d{4})`
- **Сумма**: `(?:итого|сумма|к оплате)[:\s]*(\d[\d\s,.]*)\s*(?:руб|₽)`
- **ИНН**: `ИНН\s*(\d{10,12})`
- **Контрагент**: `(?:ООО|АО|ИП|ПАО|ЗАО|ОАО)\s*[«"]?([^»"\n]{3,50})`

### Дедупликация

| Уровень | Метод | Точность | Статус |
|---------|-------|----------|--------|
| 1 | SHA-256 содержимого файла | 100% | Реализовано |
| 2 | Email Message-ID | 100% | Реализовано |
| 3 | 1С GUID | 100% | Реализовано |
| 4 | Семантический ключ (docType + номер + дата + контрагент) | 95% | Реализовано |
| 5 | Текстовый hash нормализованного текста | 90% | Реализовано |

### Почему так

- **Pipeline, а не один шаг**: каждая стадия изолирована и расширяема. Фаза 2 добавит email-парсер и 1С XML — это отдельные ветки в extract и classify, без переписывания остального.
- **Rule-based, а не ML**: для типичной номенклатуры топливного бизнеса regex-правила дают 75-85% точности при нулевых затратах на обучение. ML оправдан когда правил станет >50 и появятся нетипичные документы.

---

## Хранилище — гибрид

| Хранилище | Что хранит | Почему |
|-----------|-----------|--------|
| localStorage | DataEntry[] (метаданные), настройки компаний, счётчик ID | Быстрый синхронный доступ, работает везде |
| IndexedDB | Blob-файлы (PDF, изображения) | localStorage ограничен ~5 МБ, IndexedDB — сотни мегабайт |

Связь: поле `metadata._blobId` в DataEntry ссылается на запись в IndexedDB.

**Почему не только IndexedDB**: вся существующая логика (CRUD, фильтры, KPI) работает через localStorage. Переносить всё — большой рефакторинг без выгоды. Blob-ы — единственное, что не помещается в localStorage.

### Специальные ключи metadata

| Ключ | Назначение |
|------|-----------|
| `_blobId` | Ссылка на blob в IndexedDB |
| `_fingerprint` | SHA-256 hash файла для дедупликации |
| `_duplicateOf` | ID оригинала если дубль |
| `_confidence` | Уверенность классификации (0-100) |
| `_sourceType` | Детальный тип источника (pdf, image, text...) |
| `_extractedText` | Извлечённый текст (до 2000 символов, для поиска) |
| `_email.*` | Email-метаданные (from, subject, messageId) — фаза 2 |
| `_1c.*` | 1С-метаданные (guid, docType, number) — фаза 2 |

---

## Inbox — верификация

Все новые записи (status `new` или `recognized`) попадают во «Входящие». Бейдж в сайдбаре показывает количество.

### InboxDetailPage — split-view

Слева — превью документа. Справа — форма верификации:
- Категория, подкатегория (предзаполнены, редактируемы)
- Метаданные с confidence-бейджами для OCR (≥90% зелёный, 70-89% жёлтый, <70% красный)
- Комментарий

### Действия

| Действие | Результат |
|----------|----------|
| Подтвердить | status → `verified`, переход к следующей записи |
| Отложить | Пропустить к следующей без изменения статуса |
| Отклонить | status → `error`, причина сохраняется в `metadata.rejectReason` |

Навигация prev/next между записями без возврата к списку.

**Почему отдельный inbox**: человек должен видеть только то, что требует внимания. Верифицированные и переданные записи уходят в разделы «Данные».

---

## Жизненный цикл записи

```
new → recognized → verified → transferred
                          ↘
                         error (отклонение с причиной)
```

| Статус | Значение | Откуда попадает |
|--------|---------|----------------|
| `new` | Только загружен | Upload, intake pipeline, ручной ввод |
| `recognized` | OCR/классификация выполнена | Photo scan, pipeline с высокой уверенностью |
| `verified` | Проверен человеком | Inbox → Подтвердить |
| `transferred` | Передан во внешнюю систему | Пакетное действие над verified-записями |
| `error` | Ошибка / отклонён | Inbox → Отклонить |

---

## Данные — просмотр по категориям

Раздел «Данные» в сайдбаре — динамические пункты из профиля компании. Каждая категория — таблица с фильтрами:
- Поиск по тексту
- Фильтр по статусу
- Фильтр по источнику
- Фильтр по подкатегории
- Фильтр по периоду

Детальная страница записи: все метаданные, история изменений, превью документа.

---

## Дашборд

### KPI (считаются из реальных данных)

| Карточка | Что считает |
|----------|-----------|
| Загружено сегодня | Записи с `createdAt` = сегодня |
| Всего проверено | status = `verified` + `transferred` |
| В обработке | status = `new` + `recognized` |
| Ошибки | status = `error` |
| Передано сегодня | status = `transferred` с `updatedAt` = сегодня |

### Виджеты

- Входящие (количество + ссылка)
- Последняя активность (7 записей)
- Быстрые действия
- Статус коннекторов
- Диаграмма по категориям

---

## Коннекторы (UI-only)

Шаблоны для fuel-профиля:

| Коннектор | Тип | Интервал | Категория |
|-----------|-----|----------|-----------|
| 1С Бухгалтерия | 1c | 60 сек | Финансовый |
| 1С УНФ | 1c | 60 сек | Первичные |
| Процессинг ПТС | rest | 30 сек | Операционный |
| ГПН Агрегатор | rest | 120 сек | Операционный |
| ОФД | rest | 300 сек | Финансовый |
| Банк API | rest | 600 сек | Финансовый |
| Email IMAP | email | 300 сек | Первичные |
| ЭДО | rest | 120 сек | Первичные |
| FTP/SFTP | ftp | 600 сек | Первичные |

**Почему только UI**: реальная интеграция с 1С/банками требует бэкенда. Сейчас это каркас — показывает какие коннекторы будут и как будет выглядеть мониторинг.

---

## Источники данных

| Источник | Как попадает | Бейдж |
|----------|-------------|-------|
| `upload` | Загрузка файла (PDF, Excel) | Загрузка (синий) |
| `photo` | Фото/скан (изображение) | Фото (фиолетовый) |
| `manual` | Ручной ввод формы | Ручной (зелёный) |
| `api` | Коннектор/API | API (оранжевый) |
| `email` | Email (.eml или вставка) | Email (голубой) |
| `oneC` | 1С XML | 1С (жёлтый) |
| `whatsapp` | WhatsApp export | WhatsApp (изумрудный) |
| `telegram` | Telegram JSON | Telegram (небесный) |
| `paste` | Вставленный текст | Вставка (фиолетовый) |

---

## Техстек

### Текущий (прототип, v0.2)

| Слой | Технология | Зачем |
|------|-----------|-------|
| Фреймворк | React 19 + TypeScript 5.9 | SPA, типизация |
| Роутинг | React Router 7 | Клиентская навигация |
| Состояние | @tanstack/react-query 5 | Кеш, мутации, инвалидация |
| UI | shadcn/ui (Radix + Tailwind 4) | Готовые компоненты, тёмная тема |
| Формы | react-hook-form + Zod | Валидация, динамические поля |
| Файлы | react-dropzone | Drag-n-drop |
| PDF | pdfjs-dist (lazy, ~400 КБ) | Извлечение текста |
| Blob store | idb (~3 КБ) | IndexedDB обёртка |
| ID | nanoid (~1 КБ) | Генерация уникальных ID |
| Иконки | lucide-react | 500+ иконок |
| Даты | date-fns | Форматирование |
| Сборка | Vite 7 | HMR, code-splitting |
| Деплой | GitHub Pages | Прототип |

### Целевой (production)

| Слой | Технология | Зачем |
|------|-----------|-------|
| Контейнер | Docker + docker-compose | Единый образ, on-premise или облако |
| API | Python 3.12 + FastAPI | CRUD, парсинг, sync с облаком |
| БД | PostgreSQL 16 | staging + public schemas |
| Парсинг | PyMuPDF, openpyxl, lxml, python-docx | Механическое извлечение текста |
| Auth | JWT + bcrypt | Авторизация, роли |
| AI (облако) | Claude API | Классификация, нормализация |
| Фронтенд | React 19 + Vite → API-клиент | SPA работает с сервером |

---

## Маршруты

| Путь | Страница |
|------|---------|
| `/` | Дашборд |
| `/inbox` | Входящие (список) |
| `/inbox/:id` | Верификация записи |
| `/input` | Приём документов (универсальный) |
| `/data/:category` | Данные по категории |
| `/data/:category/:id` | Детали записи |
| `/connectors` | Коннекторы |
| `/connectors/:id` | Детали коннектора |
| `/search` | Поиск |
| `/settings` | Настройки |
| `/settings/companies` | Управление компаниями |
| `/settings/companies/:id` | Редактирование компании |

---

## Dev Tools (только в dev-режиме)

Инструменты для разработки и тестирования. Работают только при `import.meta.env.DEV`, полностью исключаются из production-бандла через tree-shaking.

### DevPanel (`src/components/dev/DevPanel.tsx`)

Плавающая панель `fixed bottom-4 right-4`. Кнопка-триггер (Wrench), раскрывается в карточку ~300px.

| Секция | Возможности |
|--------|------------|
| Компания | Переключение компании + profileId |
| Данные | Сбросить seed, очистить всё, +50/+200 записей, удалить записи |
| Статусы | Распределение по статусам (бейджи), массовая смена статуса |
| Статистика | Записей в компании, ключей в LS, размер LS, распределение по компаниям |

Интеграция: lazy-загрузка в `MainLayout.tsx`, `queryClient.invalidateQueries()` после каждой операции.

### Консольные утилиты (`window.__cl`)

Регистрируются в `src/services/devConsole.ts`, импорт в `main.tsx`.

```
__cl.stats()            — статистика хранилища (console.table)
__cl.entries(companyId?) — таблица записей
__cl.generate(n?)       — сгенерировать N записей (по умолчанию 50)
__cl.reset()            — сбросить seed + reload
__cl.clear()            — очистить всё + reload
__cl.setStatus(status)  — все записи → указанный статус
__cl.deleteEntries()    — удалить записи текущей компании
__cl.export(companyId?) — экспорт данных компании
```

### Ядро (`src/services/devToolsService.ts`)

Чистые функции для манипуляции данными: `resetSeed()`, `clearAllData()`, `generateEntries()`, `getStorageStats()`, `setAllStatuses()`, `deleteAllEntries()`. Генератор создаёт записи с валидными комбинациями category/subcategory/docType из `getAllDocumentTypes(profileId)`.

---

## Что ещё не сделано (по фазам)

### Фаза 2 — Email + 1С парсеры (реализовано)

| Задача | Библиотека | Статус |
|--------|-----------|--------|
| .eml парсер (headers, body, вложения → связанные записи) | postal-mime (~15 КБ) | Готово |
| 1С XML парсер (CommerceML, EnterpriseData, ФНС → маппинг типов) | fast-xml-parser (~35 КБ) | Готово |
| Excel/CSV парсер (листы, заголовки, поля) | xlsx / SheetJS (~280 КБ) | Готово |
| Дедупликация по Email Message-ID | — | Готово |
| Дедупликация по 1С GUID | — | Готово |
| Правила классификации для email (по теме, тексту) | — | Готово |
| Правила классификации для 1С XML (CommerceML, ФНС, EnterpriseData) | — | Готово |
| Правила классификации для Excel (реестры, остатки, выписки) | — | Готово |
| Рекурсивная обработка вложений email через pipeline | — | Готово |

### Фаза 3 — Чаты + OCR (реализовано)

| Задача | Библиотека | Статус |
|--------|-----------|--------|
| OCR для изображений (русский + английский) | tesseract.js (lazy, ~12 МБ модель) | Готово |
| WhatsApp .txt парсер (участники, даты, вложения) | — | Готово |
| Telegram JSON парсер (result.json, медиа) | — | Готово |
| Авто-определение WhatsApp/Telegram по содержимому | detect.ts refineFileType() | Готово |
| Правила классификации для чатов (документы в чатах) | — | Готово |
| OCR + classify: сканы документов → тип по содержимому | — | Готово |

### Фаза 4 — Граф связей + ручной ввод (реализовано)

| Задача | Статус |
|--------|--------|
| Сервис связей (linkService.ts) — CRUD DocumentLink в localStorage | Готово |
| Типы связей: email-attachment, duplicate, related, correction, manual | Готово |
| Компонент DocumentLinks — визуализация + добавление/удаление связей | Готово |
| Интеграция в InboxDetailPage (под превью документа) | Готово |
| Интеграция в DataDetailPage (между метаданными и историей) + кнопка «Связать» | Готово |
| Авто-связи: email → вложения (pipeline) | Готово |
| Авто-связи: дубликат → оригинал (forceSaveDuplicate) | Готово |
| Tab «Ручной ввод» в IntakePage | Готово (реализовано ранее) |

### Серверная архитектура (v0.3 — реализовано)

Полный бэкенд реализован. Подробный план → [LAYER2_ARCHITECTURE.md](../LAYER2_ARCHITECTURE.md)

| Шаг | Что делаем | Статус |
|-----|-----------|--------|
| 1 | Docker + nginx + PostgreSQL + Alembic | Готово |
| 2 | FastAPI: auth + CRUD public.entries | Готово |
| 3 | Файловое хранилище: upload → папочная структура | Готово |
| 4 | Парсинг: PyMuPDF, openpyxl → staging.raw_entries | Готово |
| 5 | Sync: staging → облако → staging → promote | Готово (sync_queue не задействован, retry backoff — TODO) |
| 6 | Миграция React SPA: API-клиент вместо localStorage | Готово |
| 7 | Аудит, роли, rate limiting | Готово (slowapi rate limiting добавлен) |
| 8 | Бэкапы, health checks | Готово (мониторинг/metrics — TODO) |
| 9 | Облачный сервер: AI pipeline | Готово (OCR, нормализация — TODO) |
| 10 | Интеграции: 1С XML-выгрузка, email-коннектор, CSV export | Готово (реальный обмен с 1С — TODO) |

#### Бэкенд (backend/)

- **Docker**: docker-compose (web + db), Dockerfile с nginx + cron + pg_dump
- **PostgreSQL 16**: public (11 таблиц) + staging (3 таблицы), Alembic миграции
- **FastAPI API** (12 роутеров): auth (JWT), entries, companies, connectors, document-links, settings, stats/kpi, audit, intake (upload + parse), files (download), export (1С XML, CSV), connector-actions (email poll)
- **Парсинг Layer 1a**: PyMuPDF (PDF), openpyxl (Excel), lxml (XML), python-docx (Word), CSV, plain text
- **Sync worker**: background task, batch staging → облако, auto-promote accepted → public
- **Бэкапы**: pg_dump + rsync, cron 03:00 ежедневно, ротация 30 дней
- **Health check**: /api/health с проверкой БД, Docker HEALTHCHECK

#### Облачный AI-сервер (cloud/)

- **POST /api/process**: batch-обработка документов от контейнеров клиентов
- **Dual-mode classifier**: rule-based (12 правил: ТТН, акты, счета, платёжки, договоры, 1С) или Claude API
- **Regex extraction**: номер, дата, сумма, ИНН из текста
- **API key verification** для авторизации клиентов

#### SPA-миграция

- **apiClient.ts**: HTTP-клиент с JWT, auto-redirect на /login при 401
- **AuthContext**: dual-mode — JWT через FastAPI или demo-пользователь (без API)
- **LoginPage**: форма входа (только API-режим)
- **dataEntryService**: все CRUD async, dual-mode (API или localStorage)
- Переключение через `VITE_API_URL` env variable

#### Аудит кода и исправления (v0.3.1)

Полная проверка бэкенда, фронтенда и архитектуры. Найдено и исправлено:

| Баг | Критичность | Исправление |
|-----|-------------|-------------|
| nginx `daemon off;` блокирует uvicorn — API 502 | CRITICAL | Убран `daemon off;`, nginx в daemon mode |
| EntryOut.metadata конфликт с SQLAlchemy | CRITICAL | `validation_alias="metadata_"` + `populate_by_name` |
| email_connector: str вместо UUID в запросе | CRITICAL | Конвертация `UUID(connector_id)` |
| email_connector: new event loop на каждое вложение | CRITICAL | Batch-обработка в одной async-сессии |
| datetime→str в 4 Pydantic-схемах | SERIOUS | Заменено на `datetime` в ConnectorOut, LinkOut, SettingOut, AuditOut |
| audit middleware: str() вместо json.dumps() для JSONB | SERIOUS | `json.dumps(details, ensure_ascii=False, default=str)` |
| audit middleware нигде не вызывался | SERIOUS | Интегрирован в entries CRUD, auth login, intake upload |
| sync.py: unused imports (SyncQueue, Source) | MINOR | Очищены |
| stats.py, seed.py: unused imports | MINOR | Очищены |
| datetime.utcnow() deprecated (storage, export) | MINOR | `datetime.now(timezone.utc)` |
| Frontend: 401 redirect игнорирует basename | MODERATE | `import.meta.env.BASE_URL` |
| Frontend: register() не сохраняет токен | MODERATE | Добавлен `setToken()` |

#### Аудит v2 и исправления (v0.3.2)

Повторная глубокая проверка: бэкенд, фронтенд, архитектура.

| Баг | Критичность | Исправление |
|-----|-------------|-------------|
| CORS `allow_origins=["*"]` + `allow_credentials=True` | CRITICAL | Конкретные origins через `CORS_ORIGINS` env |
| Rate limiting полностью отсутствовал | CRITICAL | slowapi + rate_limit конфиг + лимит на /login |
| SECRET_KEY дефолтный публично известный | CRITICAL | Warning при запуске если не изменён |
| GIN-индекс на entries.metadata отсутствует | HIGH | Миграция 002: `USING GIN (metadata jsonb_path_ops)` |
| Staging FK отсутствуют (ai_results, sync_queue) | HIGH | Миграция 002: FK с ON DELETE CASCADE |
| Frontend: exportService без await — экспорт `{}` | HIGH | `await getEntries(companyId)` |
| Frontend: Inbox API = only `new`, demo = `new`+`recognized` | HIGH | Два параллельных запроса (new + recognized) |
| classify.ts: `operations` вместо `operational` | HIGH | Исправлено на `operational` |
| classify.ts: опечатка `ФайлОбwormen` | MINOR | Исправлено на `ФайлОбмен` |
| promote_to_public: source_type hardcoded `upload` | MEDIUM | Определение из extracted_fields (email/upload) |
| Cloud API: нет company_profile | MEDIUM | Добавлена подгрузка profile_id из Company |
| Frontend: 401 race condition (множественные редиректы) | HIGH | Guard `isRedirecting` flag |
| WHAT_IS_DONE: ложные "Готово" | MEDIUM | Статусы уточнены с TODO-пометками |

#### UI/UX аудит и исправления (v0.3.1)

Комплексная проверка пользовательского опыта. Оценка: 6.3/10 → ~8/10 после исправлений.

**P0 — Критичные баги функциональности:**

| Проблема | Исправление |
|----------|------------|
| VerificationForm теряет изменения categoryId/subcategoryId при верификации | `onVerify` передаёт `VerifyPayload`, `updateEntry` перед `verifyEntry` |
| Header: кнопка «Выход» ничего не делает | `logout()` + `navigate('/login')` |
| MobileBottomNav: пути ведут на удалённые страницы | Новые пути: `/input`, `/inbox`, `/data/documents`, `/settings` |
| SearchPage: ?q= параметр из Header игнорируется | `useSearchParams()` + `useEffect` для синхронизации |
| Удаление без подтверждения (коннекторы, записи) | `AlertDialog` с подтверждением для всех деструктивных действий |

**P1 — Критичный UX:**

| Улучшение | Реализация |
|-----------|-----------|
| Toast-уведомления для всех мутаций | Библиотека `sonner`, toast на каждом CRUD-действии |
| Клавиатурные сочетания в Inbox | J/↓=следующая, K/↑=предыдущая, S=пропустить |
| Страница 404 | Catch-all route `*` → `NotFoundPage` |
| Версия в Header | `v0.3.1` (была `v0.1.0`) |

**P2 — Улучшения:**

| Улучшение | Реализация |
|-----------|-----------|
| StatusFunnel на дашборде | Визуальная воронка по статусам с прогресс-барами |
| Ctrl+K глобальный поиск | `useEffect` + `navigate('/search')` в MainLayout |
| QuickActions: битые пути | Исправлены на `/input`, `/search` |

**P3 — Полировка:**

| Улучшение | Реализация |
|-----------|-----------|
| Удаление мёртвого кода | ProcessingQueue, ClassificationPreview, DuplicateWarning (заменены IntakeQueue) |

**TypeScript-фиксы (build):**

| Проблема | Исправление |
|----------|------------|
| `getEntries()`/`createEntry()` не awaited (~30 мест в 8 файлах) | Каскадное исправление async/await |
| DocumentLinks: sync useMemo с async функцией | Конвертация в useEffect+useState |
| apiClient: TS 5.9 `erasableSyntaxOnly` (public parameter properties) | Явные свойства класса |
| pipeline: Uint8Array BlobPart несовместимость | Cast через `as unknown as BlobPart` |

#### Волна полировки (v0.3.3)

**Структурные улучшения:**

| Улучшение | Реализация |
|-----------|-----------|
| ErrorBoundary | Глобальная обёртка App, кнопки «Повторить» / «На главную» |
| Skeleton loading | 4 варианта: DetailPage, SplitView, Table, Search — вместо текстовой «Загрузка...» |
| Мобильные карточки | InboxTable, DataTable, RecentActivity — card layout на <768px |
| Responsive grid | KpiCards: `md:3 lg:5` вместо `md:5` |

**Dashboard:**

| Виджет | Реализация |
|--------|-----------|
| ActivityChart | 14-дневный bar chart (uploaded/verified), CSS-бары |
| OnboardingBanner | Приветствие + кнопки для пустого состояния |

**Batch-операции:**

| Действие | Реализация |
|----------|-----------|
| Массовое удаление | BulkActionsBar + AlertDialog подтверждение |
| CSV экспорт выделенных | UTF-8 BOM, скачивание через blob URL |

**Code splitting & бандл:**

| Оптимизация | Результат |
|------------|-----------|
| React.lazy() для 13 страниц | Dashboard eager, остальные lazy + Suspense |
| Vite manualChunks | vendor-react (100KB), vendor-radix (112KB), vendor-query (36KB), vendor-pdf (404KB), vendor-xlsx (429KB) |
| Основной бандл | 939KB → 698KB (gzip 210KB) |

**Тема light/dark:**

| Элемент | Реализация |
|---------|-----------|
| CSS-переменные | `:root` = light, `.dark` = dark (TradeFrame design) |
| useTheme хук | localStorage-персистенция, toggle(), system media query |
| Flash prevention | Inline-скрипт в index.html до React |
| Header, MobileBottomNav, CompanySelector, .sel | Переведены с hardcoded HSL на CSS-переменные |
| SettingsPage | Селектор темы (system/light/dark) применяется реально |
| Toggle в Header | Кнопка Sun/Moon рядом с профилем |

**UX-компоненты:**

| Компонент | Реализация |
|-----------|-----------|
| EmptyState | Универсальный: icon + title + description + action. Используется в InboxPage, SearchPage, ConnectorGrid |
| KeyboardHelp | Модал по `?` со списком горячих клавиш (Ctrl+K, J/K, S, Ctrl+Enter) |
| QueryError | Inline-ошибка с кнопкой «Повторить» |
| Пагинация SearchPage | 15 результатов/страница, shadcn/ui Pagination |

**Error handling:**

| Элемент | Реализация |
|---------|-----------|
| QueryCache.onError | Глобальный toast при failed background refetch |
| MutationCache.onError | Глобальный toast при ошибке мутации |
| isError + QueryError | InboxPage, InboxDetailPage, DataCategoryPage, DataDetailPage, ConnectorsPage, ConnectorDetailPage |

**Прочее:**

| Улучшение | Реализация |
|-----------|-----------|
| max-width 1400px | Ограничение контента для ultra-wide мониторов |
| AppBreadcrumb | Авто-breadcrumbs из URL, resolve названий записей/коннекторов |

---

## v0.4.0 — Аудит, отчёты, экспорт, расширенный Dashboard

### Аудит-лог

Полноценный журнал изменений: кто, когда, что сделал. Fire-and-forget запись во всех mutation hooks (created, verified, rejected, transferred, archived, restored, excluded, included, updated). localStorage с лимитом 5000 событий, dual-mode ready для API.

- `auditService.ts` — CRUD аудит-событий (logEvent, getEvents, getEventsForEntry)
- `useAudit.ts` — React Query хуки (useAuditEvents, useEntryAudit)
- Секция «Журнал изменений» в MetadataPanel — expandable, последние 5 событий
- HistoryTimeline — реальные таймстемпы из аудита вместо приблизительных

### Отчёты (/reports)

Страница ReportsPage с выбором периода (сегодня/неделя/месяц/квартал/произвольный):

| Секция | Описание |
|--------|----------|
| KPI-карточки | Загружено, проверено, отклонено, передано, ср. время верификации |
| Топ контрагентов | Таблица: контрагент, всего, проверено, отклонено |
| По источникам | PieChart (recharts) с легендой |
| Анализ ошибок | Горизонтальный BarChart по причинам отклонения |

Сервисы: `reportService.ts` (generatePeriodReport, getCounterpartyStats, getSourceStats, getErrorAnalysis).

### Расширенный Dashboard

8 KPI-карточек (5 базовых + 3 новых):

| KPI | Описание |
|-----|----------|
| За неделю | Документов за 7 дней |
| Процент отклонений | rejected / (verified + transferred + rejected) × 100 |
| Ср. верификация | Среднее время от создания до верификации |

Новые виджеты: топ-5 контрагентов, распределение по источникам (PieChart), последние ошибки.

Сервис: `dashboardService.ts` (computeExtendedKpi, getTopCounterparties, getSourceDistribution, getRecentErrors).

### Экспорт

3 формата экспорта через ExportModal:

| Формат | Описание |
|--------|----------|
| Excel (.xlsx) | Через библиотеку xlsx, выбор колонок |
| CSV | UTF-8 с BOM, разделитель `;` |
| 1С XML | Упрощённый CommerceML с реквизитами документов |

Выбор колонок (15 полей), формата даты (ДД.ММ.ГГГГ / ГГГГ-ММ-ДД). Аудит экспорта.

### Пагинация и фильтры

- `PaginationWrapper` — переиспользуемый компонент с выбором размера страницы (25/50/100), ellipsis для >7 страниц, текст «Показано X–Y из Z»
- `AdvancedFilters` — сворачиваемая панель с чипами активных фильтров: диапазон дат, диапазон сумм, контрагент (autocomplete), статус, источник
- SearchPage — расширенные фильтры + подсветка поисковых терминов (`<mark>`) + PaginationWrapper
- DataCategoryPage — PaginationWrapper вместо inline-пагинации + кнопка «Экспорт» → ExportModal

### Навигация

- Группа «Аналитика» в сайдбаре с иконкой BarChart3 → /reports
- Lazy-load маршрут /reports в App.tsx

### E2E тесты

`e2e/audit-reports-export.spec.ts` — Playwright тесты для:
- Аудит-лог в MetadataPanel (появление после верификации)
- Страница /reports (загрузка, селектор периода, ссылка в сайдбаре, модалка экспорта)
- ExportModal на DataCategoryPage
- PaginationWrapper с селектором размера
- AdvancedFilters (сворачивание, подсветка терминов)

---

---

## v0.5.0 — Storage Guard + Import + Connectors + Backend + OCR

### Storage Guard

Мониторинг использования localStorage с автоматическими предупреждениями:

| Компонент | Описание |
|-----------|----------|
| `storageMonitor.ts` | `getStorageUsage()`, `isStorageWarning(80%)`, `isStorageCritical(95%)`, `getStorageBreakdown()`, `cleanupOldAudit()` |
| `StorageWarning.tsx` | Жёлтая плашка при >80%, красная при >95%. Кнопки: «Очистить аудит», «Экспорт + Очистка» |
| `storage.ts` | try/catch на `setItem()` с toast при QuotaExceededError |
| Header | Интеграция `<StorageWarning />` |

### Импорт из JSON

Обратный импорт данных из формата ExportPayload:

| Компонент | Описание |
|-----------|----------|
| `importService.ts` | `importFromJson(file, companyId)` → `{ imported, skipped, errors }`. Валидация, дедупликация по id, merge-стратегия |
| SettingsPage | Секция «Данные»: экспорт + импорт, drag-n-drop для JSON, прогресс, информация о хранилище |

### AuditJournal

Переиспользуемый компонент журнала аудита для конкретной записи:

| Компонент | Описание |
|-----------|----------|
| `AuditJournal.tsx` | Принимает `entryId`, показывает события с бейджами действий, ScrollArea max-h-64 |
| InboxDetailPage | `<AuditJournal>` добавлен рядом с VerificationForm |

### Рабочие коннекторы (demo-sync)

Коннекторы теперь могут генерировать тестовые записи:

| Компонент | Описание |
|-----------|----------|
| `connectorService.ts` | `simulateSync()` — генерирует 2-5 DataEntry через localStorage, обновляет lastSyncAt/syncStatus |
| `useConnectors.ts` | `useSyncConnector()` — mutation hook с инвалидацией entries + connectors |
| ConnectorDetailPage | Кнопка «Синхронизировать» (с анимацией), отображение syncStatus и lastSyncAt |
| `types/index.ts` | Connector: `lastSyncAt?`, `syncStatus?`; AuditAction: `connector_synced` |

### FastAPI Backend MVP (server/)

Полный бэкенд для production-режима — 21 файл:

```
server/
  app/
    config.py          — Pydantic BaseSettings (.env, CORS, OCR, JWT)
    database.py        — AsyncSession + asyncpg, create_all при старте
    models.py          — SQLAlchemy 2.0: Company, User, DataEntry, AuditEvent, Connector (UUID PK, JSONB)
    schemas.py         — Pydantic v2 Request/Response схемы
    auth.py            — JWT (PyJWT) 30min, bcrypt (passlib), get_current_user
    seed.py            — 5 компаний + admin@clearledger.ru / admin123
    main.py            — FastAPI + CORS + lifespan + /api prefix
    routers/
      auth_router.py       — POST /login, POST /register, GET /me
      entries_router.py    — CRUD + verify/reject/transfer/archive/restore/exclude/include
      audit_router.py      — GET /audit (фильтры), GET /audit/entry/{id}
      connectors_router.py — CRUD коннекторов
      export_router.py     — GET /export/json, /export/excel, /export/csv
      reports_router.py    — GET /reports/period, /counterparties, /sources, /errors
      ocr_router.py        — POST /ocr (Tesseract rus+eng, 10MB, 30s timeout)
  Dockerfile             — python:3.12-slim + tesseract-ocr + tesseract-ocr-rus
  docker-compose.yml     — app + postgres:16 + nginx
  nginx/nginx.conf       — /api → app:8000, / → SPA static, gzip, cache
  .env.example           — DATABASE_URL, SECRET_KEY, CORS_ORIGINS, OCR_ENABLED
  requirements.txt       — fastapi, uvicorn, sqlalchemy, asyncpg, pyjwt, bcrypt, openpyxl
```

### Cloud OCR

Серверный OCR через Tesseract CLI с fallback на browser Tesseract.js:

| Компонент | Описание |
|-----------|----------|
| `ocr_router.py` | POST /ocr — subprocess.run tesseract, rus+eng, 10MB лимит, 30s timeout |
| `extract.ts` | При `isApiEnabled()` → POST /api/ocr, fallback на Tesseract.js |
| Dockerfile | `apt-get install tesseract-ocr tesseract-ocr-rus` |

---

### Запланировано

- Полнотекстовый поиск (PostgreSQL FTS)
- PWA (offline + push-уведомления)
- Интеграции: банковские API, ЭДО, ОФД
- Dashboard: сравнение периодов
- Мониторинг (metrics endpoint)
- Нормализация + fuzzy match в cloud classifier
- Alembic миграции (сейчас create_all при старте)
