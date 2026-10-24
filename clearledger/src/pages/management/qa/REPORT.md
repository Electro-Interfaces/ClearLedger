# Управляющее пространство V1: frontend и проверка

Дата: 24.10.2026. База: `bc08cfb7`. Ветка: `MagLook/elsy-control-ui-20261024`.

Реализован защищённый `/management` внутри MainLayout: Чаты / Задачи / Календарь,
фильтр пространства, поиск по названию, обновление, источник и организация каждой
строки, давность ответа, безопасная ссылка на оригинал. Режим помечен «Только просмотр».

Единственный новый вход в навигации: «Профиль и настройки» → «Обзор пространств».
Общий HeaderUserMenu уже присутствует в MainLayout и на отдельном рабочем столе `/`,
на desktop и mobile. Пункт появляется только после успешного
`GET /api/management/status` с `enabled=true`; при загрузке/ошибке/disabled скрыт.
Прямой адрес показывает понятное состояние, включая отсутствие API-конфигурации.

## Изоляция и отказы

- Используется обычный API-клиент Ядра с JWT и `X-Company-Id`.
- В queryKey входят actor, companyId и все query-параметры, включая `time_zone`.
- При смене компании keyed remount сбрасывает поиск, пространство и выбранную вкладку
  до первого запроса новой компании. Старые строки не подставляются.
- Persistent cache отсутствует; содержимое query освобождается при уходе (`gcTime: 0`).
- При 401/403/404 старый ответ скрывается, кеш обзора текущего actor/company удаляется;
  повтор возможен явно. Успешный partial forbidden заменяет старые записи.
- При сетевой/5xx ошибке предыдущий ответ допускается только с явной подписью о давности.
  Ошибка/disabled статуса скрывает данные и очищает кеш; обновление сначала проверяет статус.
- `source.error` не выводится и не сохраняется в распарсенных данных. HTTP-ошибки
  преобразованы в известные публичные сообщения до попадания в UI или общий toast.
- Truncated на уровне ответа или источника явно обозначает неполную выдачу.
- UI проверяет href: локальный путь либо http(s), без исполняемых схем, control chars,
  обратных слешей, protocol-relative URL и встроенных credentials. Основной allowlist — у API.

## Календарь и оригиналы

`date_from`/`date_to` включительны в зоне браузера; UI передаёт IANA `time_zone`.
UTC timestamps отображаются в этой зоне; date-only срок сохраняет календарный день.
Порядок agenda сравнивает абсолютные моменты, включая разные ISO offsets.
V1 API возвращает в календаре встречи; UI не синтезирует там задачи и не обещает их сроки.
Поле due_at показывается отдельной строкой «Срок» только если оно присутствует в ответе.

Company/chat bridge стоит после авторизации и на `/`, и в MainLayout. Он проверяет
membership из `/me` до монтирования оригинала; неизвестная организация блокируется.
Точная backend-ссылка `/?company=…&chat=…` открывает штатную комнату в InteractionModal
рабочего стола. `task` в `/docs/work?view=errands` открывает существующий TaskCard;
`event` уже поддержан существующим CalendarPage. Исходные ChatPanel, TaskCard и CalendarPage
не менялись. Их штатные действия доступны после перехода к оригиналу; новый обзор их не вызывает.

## Проверки

Локальные dev servers: `127.0.0.1:3817` с тестовым API origin и `127.0.0.1:3818` без
VITE_API_URL. Chromium `/usr/bin/chromium`, Playwright, зона Europe/Moscow;
desktop 1440×1000, mobile 390×844. Browser plugin в окружении не предоставлен,
использован установленный Chromium через Playwright; bundled headless shell отсутствует.
Все API-ответы браузерных проверок синтетические и перехватываются только тестовым harness.

| Проверка | Результат |
|---|---|
| `npm run typecheck` | PASS |
| Node helper tests | 4/4 PASS |
| Playwright, весь набор | 13/13 PASS |
| Дополнительный targeted ESLint нового кода | PASS |
| Повтор после изменения denial callback | 403/404 revoke + retry PASS |
| `git diff --check` | PASS |
| Impeccable detector | `[]`, замечаний нет |
| Framework overlay / runtime errors нового экрана | Не обнаружены |
| Desktop/mobile, подписи, переносы, горизонтальное переполнение | PASS |

Сценарии: три вкладки; поиск со спецсимволами; пространство; календарный период и
time_zone; UTC-встреча 24.10 22:30Z → 25.10 01:30; срок задачи date-only;
смена организации с задержанным ответом; loading; total error/retry;
source forbidden/error/not_configured; empty; отсутствие источников;
status error/disabled; missing API config; общий и source truncated;
безопасные/небезопасные href; отсутствие management-мутаций; отзыв 403 и 404;
partial forbidden после успешного ответа; точные chat/task/event ссылки;
ожидание membership и отказ неизвестной организации; вход с homepage и mobile.

Воспроизведение из clearledger:

```bash
VITE_API_URL=http://127.0.0.1:3817 npm run dev -- --host 127.0.0.1 --port 3817 --strictPort
# Во втором терминале:
VITE_API_URL='' npm run dev -- --host 127.0.0.1 --port 3818 --strictPort
# Проверки:
MANAGEMENT_QA_UNCONFIGURED_URL=http://127.0.0.1:3818 npx playwright test --config src/pages/management/qa/playwright.config.mjs
node --test --experimental-strip-types src/pages/management/managementHelpers.test.ts
```

Снимки просмотрены: [desktop](evidence/desktop.png), [mobile](evidence/mobile.png),
[calendar](evidence/calendar.png). Это тестовые записи, а не снимок реальных данных.

## Impeccable: итоговая проверка расширения

`disposition: ship` в границах изменённой поверхности, по тестовым данным.
Отдельный агент не запускался по прямому запрету Dispatch; финальные review и
documenter выполнены в текущем потоке по degraded references навыка.

**persistence:** PASS — SURFACE.md хранит локальный контракт; PRODUCT.md/DESIGN.md
и глобальная тема сохранены. Снимки desktop/mobile/calendar валидны и просмотрены.

**fidelity:** заголовок, фильтры, вкладки, списки и состояния соответствуют установленному
Operate-интерфейсу. Мобильная колонка сохраняет подписи и доступность действий.
Фикстуры находятся только в QA; product UI не содержит синтетических записей.

**ceiling:** для scoped extension сохранены существующие tokens, Manrope/системный
шрифт, шкала 18/14/12, shadcn и Lucide. Собственные цвета и декоративные материалы не вводились.

**material_fixes:** открытых замечаний изменённой поверхности нет по проверенной матрице.

**keep:** указание источника/организации, явная неполнота и давность, блокировка
отозванных данных и отсутствие мутаций в обзоре.

Documenter: No changes в PRODUCT.md/DESIGN.md; проверены эти файлы, index.css,
репрезентативная страница настроек, используемые UI-компоненты и снимки результата.
Палитра семантическая; заголовок 18, тело 14, мета 12; фильтры именованы;
интерактивные элементы наследуют focus/disabled; состояния словесные.
Унаследованный WorkspaceTabBar использует общий fallback названия для нового пути;
отдельная регистрация приложения не добавлялась и не канонизирована как новое правило.

## Что остаётся координатору

Проверить собранный frontend против настоящего management API-стенда и интегрированной
API-ветки. Реальные grants, делегирование, source ACL и production не проверялись этим
frontend Dispatch. Выкатка и push не выполнялись. `git pull --ff-only` в начале отказал
из-за отсутствия upstream у отдельной worker-ветки; база Dispatch сохранена.
