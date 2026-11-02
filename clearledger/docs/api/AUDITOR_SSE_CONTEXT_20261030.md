# Аудитор: контекст SSE и время жизни разговора, 30.10.2026

## Результат и состав

Подтверждена гонка в настоящем `spaceAuditorService.ask`: после смены компании,
организации или сессии прежний запрос продолжал вызывать `onText`, `onError`,
`onDone` и остальные callbacks. Это могло менять последнее сообщение и занятость
нового разговора. Исправление использует существующий `captureApiContextGuard`;
общий JSON-транспорт Ядра на отдельный SSE-прокси аудитора не переносился.

Исходный commit: `cadd246ab9828e770abaf1f506376f40b2e11d71`.
Рабочая ветка: `agent/api-auditor-sse-context-20261030`.
У сервиса изменена только функция `ask`: все прочие верхнеуровневые AST-узлы,
включая imports и `exportWork`, побайтово совпадают с исходным commit.
По дополнительному разрешению координатора исправлен фактический `AuditorPanel`
и добавлен отдельный React/Chromium regression fixture.

## Сервис и сохранённый контракт

Guard захватывается на запуске запроса, проверяется перед запросом, после
`fetch`, чтения JSON ошибки и каждого `reader.read`, до callbacks и после них.
Проверка после SSE-callback находится вне `try/catch` разбора строки: изменение
контекста внутри callback останавливает и остальные строки уже прочитанной пачки.
На устаревшем/остановленном запросе callbacks, в том числе `onDone`, не вызываются.
Текущие ошибки транспорта по-прежнему дают `onError(message)` и `onDone`.
Исключения из завершающих callbacks не запускают их повторно и не порождают
необработанный Promise у функции с прежним синхронным API `AbortController`.
Историческое игнорирование ошибок SSE-callback внутри parse-catch сохранено.

Свой reader отменяется при abort и раннем выходе, освобождается в `finally`;
ошибка отмены наблюдается и не уходит в unhandled rejection. При естественном
EOF лишней отмены нет. Тело ответа, полученного уже после инвалидирования,
также отменяется. Это освобождение клиентского потока, а не подтверждение
отмены серверного процесса, обращения к модели или его побочных действий.

Сохранены:

- относительный URL `/auditor/api/ask` на origin интерфейса;
- `POST`, Bearer текущего пользователя, явный `X-Company-Id` аргумента;
- тело `question`, `context`, `history`, `files`, `workshop` и их defaults;
- отсутствие автоматического `X-Organization-Id`/Core base URL/credentials;
- возвращаемый `AbortController` и его signal в `fetch`;
- потоковый `TextDecoder`, фрагментация UTF-8 и точный префикс `data: `;
- status/skills/text/findings/actions/run/error, `[DONE]`, EOF, игнорирование
  неверных/неизвестных строк и незавершённой последней строки;
- исходные сообщения HTTP, non-SSE/HTML, пустого тела и сетевых ошибок.

HTTP 401 аудитора не переводится в обработчик 401 Ядра и не очищает новую
Core-сессию. Проверены как текущие ошибки, так и отложенный JSON старого 401.

## Явная компания и глобальный контекст

Аргумент `companyId` определяет заголовок запроса и не переписывается из
глобального выбора. Он может отличаться от текущей глобальной компании:
контрольный тест намеренно использует такую пару. Guard фиксирует время жизни
глобального UI-контекста запуска, а не равенство этих двух значений.
Смена глобальной компании, организации или сессии инвалидирует callbacks,
даже если запрос явно адресован другой компании.

Существующее поколение guard замечает A→B→A и `setToken` с той же строкой,
включая logout/relogin с прежним Bearer. Повтор одинакового company/org setter
не инвалидирует запрос. Прямая запись других токена/заголовков в storage
проверяется существующим guard, но новые межвкладочные подписки не добавлены.
Клиентский guard не устанавливает tenant ACL сервера и не доказывает полноту
авторизации маршрута аудитора.

## Реальный caller

В `AuditorPanel` callbacks добавляют поток в последнее сообщение, находки и
действия, а `onDone` снимает `busy/status`. Исходный cleanup отменял запрос
только при unmount. В `App.tsx` родительские ключи уже зависят от компании и
пользователя (`TabsProvider`, `NavigationHistoryProvider`); обе точки входа,
`RightDock` и `AuditorPage`/`ChatView`, находятся внутри этой границы.
Выход закрывает защищённый контент через `ProtectedRoute`.

Организация меняется через `CompanyContext.setOrganizationId` без изменения
родительского ключа. Одного подавления устаревшего `onDone` было бы недостаточно:
панель оставалась бы занятой, старые история/действия/вложения сохранялись бы.
Экспортированный `AuditorPanel` теперь оборачивает `AuditorConversation` с ключом
`[companyId, organizationId]`. Новая организация получает новый разговор,
черновик, историю, действия, ошибку, вложения и незанятый ввод; cleanup прежнего
разговора отменяет его controller. Родительские ключи и CompanyContext не менялись.
Поздний upload старого экземпляра не обновляет состояние и не показывает toast;
поздний текст диктовки не меняет и не фокусирует ввод новой панели.

React-проверка использует настоящие AuthProvider, CompanyProvider,
SupportProvider, ProtectedRoute, AuditorPanel, DictateButton и сервис.
Небольшой fixture воспроизводит существующий company/user ключ родителя,
а организация намеренно не входит в ключ fixture: её границу обязан обеспечить
сам компонент. Это не запуск полного `App` или реального стенда.

## Доказательства

Все входы синтетические. Env-файлы, рабочие API, SQL/БД, Python приложения,
Docker, ВМ, CI, зависимости, сборка, версии и выпуск не затрагивались.
Browser plugin отсутствует; использован имеющийся Playwright/Chromium с
собственным сервером Vite на `127.0.0.1:0`, закрытым после проверки.
Внешняя сеть браузера блокируется. Микрофон и HTTP — синтетические границы;
React, провайдеры, native ReadableStream/Response, парсер и сервис — настоящие.

| Проверка | Результат |
|---|---|
| Исходный сервис, 55 сценариев | 14 PASS, 41 FAIL; 1,488 с |
| Первичная правка, те же 55 сценариев | 55 PASS; 1,844 с |
| Итоговые SSE + session/export/conf/voice, 10 файлов | 774 PASS, 0 FAIL; 75,718 с |
| В том числе новый SSE-набор | 66 сценариев PASS; 3,588 с внутри общего запуска |
| Старый caller + исправленный сервис, итоговый browser fixture | 2 PASS, 3 FAIL; 31,878 с |
| Исправленный caller, итоговый browser fixture | 5 PASS, 0 FAIL; 12,607 с |
| TypeScript приложения | PASS; 150,356 с |
| TypeScript node-конфига | PASS; 1,476 с |
| ESLint сервиса и SSE-теста | PASS; 2,489 с |
| ESLint caller и React fixture | PASS; 2,584 с |

Числа сценариев в отдельных строках не включают родительский node:test.
Итого runner исходного SSE сообщает 56 tests / 14 pass / 42 fail,
итоговый browser runner — 6 tests / 6 pass / 0 fail.
Первый app TypeScript запуск остановлен по лимиту 120 с без diagnostics;
после изменения caller выполнен отдельный ограниченный запуск с лимитом 300 с.

Первый browser harness имел неверную форму registry response и блокировал
dev HMR; это дефекты оснастки, не дополнительные дефекты продукта.
Исходные неуспешные логи сохранены. После исправления оснастки повторены
baseline и candidate; для отрицательных проверок поздних uploads/dictation
добавлено ожидание двух кадров после resolve. Последний baseline и candidate
используют один и тот же runner. После первого полного browser PASS (16,893 с)
ESLint потребовал exports у двух компонентов fixture. Добавлены только exports;
повторный итоговый browser PASS (12,607 с) закрепляет этот состав. Предыдущие
snapshot и логи сохранены, сервисный набор после его PASS не повторялся.

Browser проверяет: открытие непустой панели; смену org во время SSE с очисткой
status/messages/findings/actions/error; новый вопрос без старой history/files;
отсутствие раннего завершения нового запроса старым потоком; поздние upload
success/error; приложенный файл и dictation при org A→B→A; смену компании;
настоящий logout/relogin с тем же токеном через AuthProvider/ProtectedRoute.
Для всех пяти candidate-сценариев проверены title/origin, отсутствие React и
console ошибок, внешних запросов и Vite overlay, сохранены screenshots
desktop 1100×850. Это функциональная приёмка lifecycle, не дизайн-аудит.

Сырые TAP, JUnit, stdout/stderr, durations/commands, snapshots и SHA-256
находятся в приватном ignored `.artifacts/auditor-sse-context/` данного worktree:
`baseline*`, `candidate-initial*`, `final-targeted*`, `caller-baseline*`,
`caller-final*`, `verification.json`, `caller-verification.json`,
`browser-verification.json`, `caller-corrected-verification.json`,
`frozen-sha256.txt`, `caller-frozen-sha256.txt`, `final-manifest.sha256`,
`scope-check.txt`. Артефакты не коммитятся.

## Закреплённые SHA-256

| Файл | SHA-256 |
|---|---|
| Исходный spaceAuditorService | `267a1a8cee1aac66b24872642e016086dbd762cb1c5a126029a01957ed8a353b` |
| Итоговый spaceAuditorService | `8c03974bc4f987245821f84f0d33013a915e1b1835c189a61e2cc2e407dc8afe` |
| Исходный apiClient, без изменений | `e392ea29cb3708b256510220eb04c564d2529fdede1384aaaeb109651c31a898` |
| Исходный AuditorPanel | `ce71e8a875124a747a47c299ee18eb862701ce91d6c8702c13f4e05371020820` |
| Итоговый AuditorPanel | `41bb0fa0784a86acba7a561b7a5236499658c1d74d0fd8148472c1f0099c17e1` |
| Исходный SSE test snapshot, 55 сценариев | `f8fd1accc8159d617ee535ed2fc582319747a2ceda15d19e7dbb52bf3376b288` |
| Итоговый SSE test, 66 сценариев | `f937e48337b41a62f6d13ec88c76218cf3d34cb61de3e4f84e73cd17159ec338` |
| Итоговый caller browser runner | `16273cf31dc21d663faf0583b60d6bce06cd615e47289e82fed6e9f59db38b69` |
| Baseline React fixture | `c2ab68ec223ace6c0aeb88774c1dbe074f80514d5cc0efa45d0b448d6600d7d3` |
| Итоговый React fixture, только добавлены exports | `8b6c2963ecb757bac1e0c722cad0d3a438322f656125f665738f628b98f137f8` |

## Воспроизведение

Из `clearledger`, с уже установленными зависимостями:

```sh
AUDITOR_SSE_BASELINE=cadd246ab9828e770abaf1f506376f40b2e11d71 node --test --experimental-strip-types src/lib/auditorSseContext.test.ts
node --test --experimental-strip-types src/lib/auditorSseContext.test.ts src/lib/auditorExportContext.test.ts src/lib/apiJsonSessionGeneration.test.ts src/lib/apiSessionRedirect.test.ts src/lib/apiBinaryTransport.test.ts src/lib/coreExportTransport.test.ts src/lib/confServiceContext.test.ts src/lib/meetingStartContext.test.ts src/lib/voiceServiceContext.test.ts src/lib/voiceAuth.test.ts
AUDITOR_CALLER_BASELINE=cadd246ab9828e770abaf1f506376f40b2e11d71 node --test e2e/auditor-sse-context.check.mjs
node --test e2e/auditor-sse-context.check.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false -p tsconfig.app.json
node node_modules/typescript/bin/tsc --noEmit --incremental false -p tsconfig.node.json
node node_modules/eslint/bin/eslint.js src/services/spaceAuditorService.ts src/lib/auditorSseContext.test.ts src/components/auditor/AuditorPanel.tsx e2e/auditor-sse-context/fixture.tsx
```

Текущий SSE-test включает дополнительные cleanup-сценарии; первоначальные
14/41 относятся к сохранённому 55-сценарному snapshot, не ко всему расширенному
набору. Baseline caller подменяет только панель; сервис берётся из рабочей версии,
чтобы изолировать дефект UI от уже исправленной гонки транспорта.

## Пределы

- Проверен один процесс вкладки; прямое изменение storage с возвратом прежних
  значений между проверками, минуя setters, не создаёт нового поколения.
- Смена контекста без новых чанков не прерывает ожидающий `read` сама по себе:
  guard срабатывает на следующей границе; явный abort отменяет reader сразу.
  Глобальных подписок/таймеров для отслеживания контекста не добавлено.
- UI A→B→A проверен как последовательность отдельных committed React-переходов.
  Пакет setter A→B→A без промежуточного render не равен доказанному remount.
- Same-token invalidation доказан на сервисе; remount UI доказан для реального
  logout/relogin. Прямой `setToken`/applySession с тем же user без выхода не
  является универсальным reset всей UI-сессии; такого API здесь не добавлено.
- Не менялись протокол, upload/dictation сервисы, серверные jobs, ACL и actions.
  Начатые операции могут завершиться на сервере; старые ошибки/уведомления
  внутри самостоятельного `useDictation`/ActionCard не переопределялись.
- Браузерная приёмка не покрывает production, полный App, другие браузеры,
  мобильную вёрстку, настоящий микрофон или живой серверный SSE.

Изменение подготовлено к ревью. Слияния, CI, выпуска и активации не было.
