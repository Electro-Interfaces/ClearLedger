# Промпт для ночной автономной сессии Claude Code

Вставить как первое сообщение в новую сессию `claude` запущенную в `D:\Users\magsp\Ledger\`.
Работать автономно до утра. По завершении каждой задачи — `TaskUpdate completed`,
писать короткий end-of-turn summary, потом брать следующий пункт из TaskList.

---

## Кто я и где работаю

ClearLedger ↔ БП ГИГ. Цель проекта — корпоративная среда подготовки документов
для менеджеров до загрузки в 1С:Бухгалтерию. **Идеология v3**: ClearLedger только
ЧИТАЕТ из 1С (pull), расширение 1С (TradeLedger.cfe / GIG_Ledger.cfe) ТЯНЕТ
подготовленные данные через ClearLedger HTTP API. Push из ClearLedger в 1С НЕ
делаем.

### Где код

| Что | Путь |
|---|---|
| Фронт (React 19 + Vite + shadcn/ui) | `D:\Users\magsp\Ledger\clearledger\src\` |
| Бэк (FastAPI + SQLAlchemy 2.0 + asyncpg) | `D:\Users\magsp\Ledger\clearledger\server\app\` |
| 1С-сторона (расширения, probe-скрипты) | `D:\Users\magsp\OneDrive\GIG Ledger\` |
| Скрипты smoke | `D:\Users\magsp\Ledger\clearledger\server\scripts\` |
| Промпт по 1С интеграции | `D:\Users\magsp\Ledger\PROMPT_подключение_к_БП_ГИГ.md` |

### Что уже работает (подтверждено end-to-end)

1. **Postgres** в Docker контейнере `clearledger-db-dev` на `localhost:5435`
   (compose-файл `D:\Users\magsp\Ledger\clearledger\docker-compose.dev.yml`).
2. **Backend** `/api/onec/*` — 13 эндпоинтов: CRUD коннектов + test + sync_catalogs
   + sync_documents + history + status. Поддерживает 2 режима:
   - `mode=odata` → HTTP клиент через httpx
   - `mode=com` → V83.COMConnector через subprocess 32-bit Python (sync, не async,
     чтобы не падало на SelectorEventLoop под Windows + asyncpg)
3. **Smoke COM** через стенд `D:\Users\magsp\GIG Base2` (Бухгалтерия 3.0.194.18):
   sync_catalogs создал **5784 записи** (Counterparty 1132 + Organization 1 +
   Warehouse 31 + Nomenclature 4620). sync_documents создал **30909 документов**
   (ПТУ + ОРП + ОПЗС + КорректировкаПоступления). Топ-5: ПТУ от ИП Петров 90M ₽,
   БРЯНСКАЯ НЕФТЯНАЯ КОМПАНИЯ 44.3M, ТРАНС-ОЙЛ 37.1M, НОРД-ЛАЙН 32.3M, БАЛТОП 31.5M.
   Скрипт: `server\scripts\smoke_full_sync.py`.
4. **UI** `/1c/connection` — переписан на бэкенд (useOneCSync хуки),
   создаёт/загружает коннект, показывает 5 кнопок. Подтверждено через playwright.

### Что НЕ работает / Open issues

См. `TaskList` — все таски с префиксом `[НОЧЬ]`:
- **#11** Кнопка «Проверить» в UI возвращает «Ошибка» (но через smoke_com_client.py
  всё работает). Логи uvicorn в `C:\Users\magsp\AppData\Local\Temp\claude\...
  tasks\bamc9acve.output`. Возможно — race между HMR reload и старым subprocess.
- **#12** Страница `/1c/references` — localStorage заглушка.
- **#13** Страница `/1c/periods` — localStorage заглушка.
- **#14** Нет UI для просмотра 30909 импортированных AccountingDoc.

---

## Запущенные процессы (НЕ запускать повторно — проверять Bash list)

| ID | Что | Порт |
|---|---|---|
| (был) `bamc9acve` | uvicorn FastAPI с --reload | 127.0.0.1:8000 |
| (был) `b9gna17t0` | vite dev-server | localhost:3010 |
| Docker | Postgres clearledger-db-dev | localhost:5435 |

Если их уже нет — запускать:
```bash
docker compose -f "D:/Users/magsp/Ledger/clearledger/docker-compose.dev.yml" up -d
cd "D:/Users/magsp/Ledger/clearledger/server" && py -3.13 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --log-level info
cd "D:/Users/magsp/Ledger/clearledger" && npx vite --port 3010
```

JWT админа `admin@clearledger.ru / admin123` уже сидится в БД при старте через `seed_data`.
Получить токен:
```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@clearledger.ru","password":"admin123"}'
```
Положить в localStorage браузера ключ `clearledger-token`.

---

## 10 граблей которые УЖЕ потеряли часы — НЕ повторять

1. **Windows + uvicorn + asyncpg = SelectorEventLoop.** `asyncio.create_subprocess_exec`
   на нём кидает `NotImplementedError`. Переписать на `subprocess.Popen` + `run_in_executor`.
   Уже сделано в `app/services/onec/com_client.py`.

2. **CDispatch 1С ссылки через pywin32 не отдают GUID** через стандартные методы
   (`УникальныйИдентификатор()`, `UUID()`, `XMLString()` — все возвращают
   `<COMObject>`). Магия: `ib.String(ref.УникальныйИдентификатор())` где
   `String` — английский алиас глобальной функции `Строка()` платформы. Сделано
   в `app/services/onec/com_worker.py:_val()`.

3. **stdout subprocess под Windows = cp1251** ломает UTF-8 JSON. Нужно
   `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` в env + `sys.stdout.reconfigure(encoding="utf-8")`
   в worker.

4. **asyncio StreamReader дефолтный limit 64KB** мало для страницы с кириллицей.
   Поднять до 8MB (теперь неактуально — мы на sync subprocess, но для async версии
   потребуется).

5. **Pagination 1С**: язык запросов имеет только `ПЕРВЫЕ N` (LIMIT), нет OFFSET.
   Для skip=K эмулируем: запрашиваем `ПЕРВЫЕ (top+skip)` и пропускаем skip в курсоре.
   Обязательно стабильный `ORDER BY Ref_Key` чтобы страницы не пересекались.

6. **CompanyContext фронта хранит slug** ('gig'/'npk'/...), а БД — UUID. Роутер
   должен принимать оба — реализовано в `_resolve_company_id()`.

7. **Компания `gig` не была засидована** изначально (seed имел только NPK/RTI/...).
   Добавлено в `seed.py`. Если в новой БД нет — добавляется автоматом при старте.

8. **VITE_API_URL должен быть в `.env`** (не `.env.local`) и vite запускается с
   `--force` для сброса кэша при первом подъёме после правки. Сейчас оба файла
   есть.

9. **AccountingDoc.date = VARCHAR(20)** — ISO datetime 25 символов не влезает.
   Обрезать до `YYYY-MM-DD` (10 симв.).

10. **`СуммаДокумента` есть НЕ у всех документов** (нет у `ОтчетПроизводстваЗаСмену`).
    Селекты строить по типу документа.

---

## Правила для ночной работы

1. **НЕ застревать на одной задаче >30 минут.** Если упёрся — перейти к следующей,
   зафиксировать блокер в комментарии таска через TaskUpdate.

2. **НЕ перезапускать dev-серверы без необходимости.** Uvicorn с --reload
   автоматически подхватывает изменения .py. Vite — изменения .ts/.tsx.

3. **НЕ доверять кэшу скриншотов.** Если делаешь screenshot после изменения —
   обязательно `--filename` с другим именем, иначе старый показывается.

4. **Прежде чем писать код для проблемы — прочитать СВОЙ код.** В этой сессии
   я потерял 1+ час пытаясь починить UI который УЖЕ работал — просто кэш
   браузера показывал старое состояние.

5. **Использовать smoke-скрипты для валидации до UI.** `smoke_com_client.py`,
   `smoke_full_sync.py` — быстро проверяют backend без браузера.

6. **Не плодить тестовые компании.** Использовать существующую `gig` (slug)
   или `smoke-gig-base2` (для тестов).

7. **TaskList в начале каждой задачи, TaskUpdate completed в конце.** Не батчить.

8. **При завершении сессии (если хватит лимита токенов или времени)** —
   обновить memory/MEMORY.md в `C:\Users\magsp\.claude\projects\D--Users-magsp-OneDrive-GIG-Ledger\memory\`
   с новыми решениями. Особенно — что было сделано за ночь, какие новые грабли,
   какие открытые вопросы.

---

## План на ночь (порядок выполнения)

### 1. Починить кнопку «Проверить» в UI (Task #11)

Логи: `Read C:\Users\magsp\AppData\Local\Temp\claude\D--Users-magsp-OneDrive-GIG-Ledger\e9af636e-ffbd-4d53-b800-20adc207645a\tasks\bamc9acve.output`
(если файл существует — он содержит вывод uvicorn). Если uvicorn уже не запущен —
поднять, повторить тест через playwright или curl:
```bash
TOKEN="<get from login>"; curl -s -X POST "http://localhost:8000/api/onec/connections/<UUID>/test" \
  -H "Authorization: Bearer $TOKEN" | jq
```

UUID коннекта получить: `docker exec clearledger-db-dev psql -U clearledger -c "SELECT id FROM onec_connections WHERE name='1С:Бухгалтерия';"`.

Если ошибка — посмотреть стек, починить. Если COM-worker умирает —
проверить что нет старого процесса (`tasklist | findstr python`).

После починки в UI нажать через playwright: «Справочники» (sync_catalogs),
дождаться ~30 сек, увидеть toast «Справочники синхронизированы. Создано N, обновлено M».
Затем «Документы» (sync_documents) — занимает 1-3 минуты.

### 2. Реализовать /1c/references (Task #12)

Сейчас `pages/oneC/ReferencesPage.tsx` использует localStorage. Переписать на
бэкенд:
- Использовать существующий `references_router` (если есть — найти через
  `grep -l references_router server/app/routers/`).
- Если нет нужных эндпоинтов — добавить: GET /api/references/counterparties,
  /api/references/nomenclature и т.п. с фильтром по company_id и пагинацией.
- UI: 4 таба (Контрагенты / Номенклатура / Склады / Организации). Таблица
  shadcn с поиском, пейджинацией, кнопкой «Обновить из 1С» (вызывает sync_catalogs).

### 3. Реализовать /1c/periods (Task #13)

Сейчас `PeriodsPage.tsx` тоже localStorage. Чтобы прочитать ДатыЗапретаИзменения
из 1С — добавить операцию в COM worker / OData client (через
`ИнформационныеРегистры.ДатыЗапретаИзменения` или подобное). Можно отложить
если объём работы слишком большой.

### 4. UI просмотра импортированных AccountingDoc (Task #14)

Новая страница / расширение существующей `DataOverviewPage` или вкладка в
`ReferencesPage`. Таблица 30909 документов. Колонки: тип, номер, дата,
контрагент, организация, сумма, статус. Сортировка/фильтр. Использовать
`accounting_docs_router` (или добавить эндпоинт).

### 5. (Опционально) Сверка ClearLedger ↔ БП ГИГ

Если успеваешь — начать реализацию сверки локальных DataEntry ↔ AccountingDoc
по external_id, ИНН контрагента, сумме. Это маркетинговый Кейс 1 ClearLedger.

---

## Контекст 1С (для понимания доменных терминов)

- **БП ГИГ** = «1С:Бухгалтерия предприятия 3.0» (ред. 3.0.194.18) для ООО ГАЗИНВЕСТГРУПП.
- **ПТУ** = «Поступление товаров и услуг» (приход от поставщиков).
- **ОРП** = «Отчёт о розничных продажах» (сменные продажи на АЗС).
- **ОПЗС** = «Отчёт производства за смену» (общепит).
- **КорректировкаПоступления** = используется как возврат поставщику.
- **TradeLedger.cfe** — расширение в БП ГИГ для приёма пакетов с АЗС.
- **TL_ЭкспортБП** — расширение в ЦБ ЭЛСИ.АЗК для выгрузки пакетов.
- **ElsyPlusMSN_TsB** — расширение для слияния SKU.

Подробности — навык `gig-1c` (загружается через `Skill gig-1c`).

---

## Memory

Записывать новые находки и решения в:
`C:\Users\magsp\.claude\projects\D--Users-magsp-Ledger\memory\` (для текущей рабочей директории Ledger).

Старые memory по 1С-стороне (которые тебе помогут понять контекст БП ГИГ, расширений, ЦБ):
`C:\Users\magsp\.claude\projects\D--Users-magsp-OneDrive-GIG-Ledger\memory\MEMORY.md`.

Особо важные:
- `project_orp_retail_vat_model` — розничная модель ОРП БП 3.0 (НЕ применять B2B-формулу).
- `project_clearledger_ideology_v3` — pull-only, расширение тянет, не push.
- `feedback_no_role_play` — не играть в роли, не симулировать агентов.

---

## Завершение ночной сессии

Когда лимит токенов близок или все задачи закрыты:
1. `TaskList` — посмотреть остаток.
2. Закоммитить осмысленные изменения: `git status` → выбрать файлы по теме →
   осмысленный коммит. **НЕ коммитить** `.env`, `*.png` скриншоты, `node_modules`.
3. Обновить `MEMORY.md` — что нового за ночь.
4. Если есть незавершённое — оставить как `in_progress` с подробным
   description что сделано / что осталось.

Удачной работы.
