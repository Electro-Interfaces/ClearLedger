**Запуск быстрых встреч и видеосвязи заявки: граница контекста, 30.10.2026**

Изменение закрывает два оставшихся клиентских пути: `startMeeting()` и
`startTicketMeeting(ticketId)`. Отложенный ответ прежней сессии, компании или
организации больше не открывает полученный URL и не передаёт результат вызывающему
коду. Используется существующий `captureApiContextGuard`, без нового транспорта.

База: `2578ec8fbef3c8a21fa274df72f96b86cd3e06af`.
Неизменяемый коммит исходников и тестов, на котором выполнены финальные проверки:
`07fa0ce0e1f763e038af14b5512d26ea291a471e`.
Ветка: `agent/api-meeting-start-context-20261030`.
Последующий коммит добавляет только этот отчёт; runtime и тесты заморожены.

Guard захватывается перед синхронным `window.open('about:blank', '_blank')`.
Пустая вкладка по-прежнему создаётся до первого `await`, её `opener` обнуляется.
Один guard передаётся в POST и проверяется после `await`, перед навигацией и
перед успешным завершением. Повторная проверка после навигации замечает смену
контекста внутри синхронного browser hook и не выдаёт успешный результат.
При ошибке закрывается только подготовленная вкладка с доступным
`location.href === 'about:blank'`; открытая человеком или недоступная по origin
вкладка сохраняется, исходная ошибка не подменяется ошибкой чтения location.

Необязательный аргумент `createMeeting(contextGuard?: () => void)` необходим,
чтобы тот же guard дошёл до `post` и проверился после fetch и чтения тела ошибки,
до обработки позднего 401. Проверки только после `await createMeeting()` для
этого недостаточно. Вызов `createMeeting()` без аргумента сохраняет прежнюю
семантику обычного JSON-запроса; отдельный положительный тест это подтверждает.

| Сохранённый контракт | Результат |
| --- | --- |
| Быстрая встреча | `POST /api/meetings`, body `undefined`, результат `MeetingUrls`, навигация через `location.href` |
| Видеосвязь заявки | `POST /api/chat/tickets/${encodeURIComponent(ticketId)}/video`, body `{}`, результат `void`, `location.replace(joinUrl)` |
| Запасное открытие | `_blank`, `noopener,noreferrer`, прежний URL ответа |
| Текущий 401 | Прежний `ApiError(401)`, очистка токена, одно уведомление и таймер redirect |
| Текущие ошибки | Прежние 403/422, сетевые/AbortError по идентичности, parser 502 |
| Демо | Быстрая встреча возвращает фактические демо-ссылки без окна и fetch; ticket video сохраняет отказ демо и закрытие пустой вкладки |

Протокол ticket ACL не объединён с быстрыми встречами. Уже отправленная mutation
не отменяется и не откатывается на сервере. Guard не отзывает ранее выданные URL,
не закрывает уже открытую встречу и не обещает гарантий после возврата функции.

Новый независимый модуль `src/lib/meetingStartContext.test.ts` загружает реальные
`conferenceService`, `apiClient`, цикл импорта `confService`, демо-маршрутизатор и
`sonner` через существующий Vite SSR runner. Конфигурационные env-файлы отключены,
HTTP listener не запускается. Storage, window, fetch и задерживаемые тела ответов
синтетические; fetch разрешает только два проверяемых пути на `.example.test`.
Сетевые ping/leave из нового модуля не выполняются, регистрация presence запрещена
утверждениями fixture. У существующих регрессий собственный синтетический harness.

Baseline запущен до runtime-правки на указанной базе с теми же байтами нового
тестового модуля. Raw stdout, summary, команды, время и SHA-256 сохранены вне Git
в `.artifacts/meeting-start-context/` этой рабочей копии. У baseline все 19
положительных контролей прошли, все 98 проверок новой границы упали. Это варианты
двух путей входа, не количество отдельных уязвимостей. Прежние находки других
путей входа не включены в этот baseline.

| Новый модуль: независимые именованные тесты | Baseline PASS / FAIL | После исправления PASS / FAIL |
| --- | --- | --- |
| Задержка fetch/body: token change, clearToken, same-token setToken, clear-set session, token/company/org A→B→A; окно и fallback | 0 / 56 | 56 / 0 |
| Поздние 401/403 на fetch/body после same-token login и company/org A→B→A | 0 / 24 | 24 / 0 |
| Поздние network/parse rejection | 0 / 4 | 4 / 0 |
| Reentrant open/opener до отправки mutation | 0 / 4 | 4 / 0 |
| Reentrant navigation/fallback: отказ выдачи результата без отмены уже открытого URL | 0 / 4 | 4 / 0 |
| Очистка после ручной навигации и при недоступном origin | 0 / 4 | 4 / 0 |
| Дополнительный await после успешного чтения body | 0 / 2 | 2 / 0 |
| Текущие успешные входы, ошибки, одинаковые company/org setters, standalone createMeeting и демо | 19 / 0 | 19 / 0 |
| Итого | 19 / 98 | 117 / 0 |

Каждая попытка после отправки проверяет единственный исходный POST, его URL,
заголовки и тело: нет повтора, нового сигнала отмены или server rollback.
Проверяются отсутствие навигации, fallback и успешного результата старого
контекста, очистка blank и сохранение новой сессии без toast/redirect. Для
reentrant open/opener ожидается ноль POST, поскольку guard успевает отказать
до отправки. Положительные контролы проверяют точные пути, percent-encoding,
различие `{}`/`undefined`, способы навигации, результаты и текущие ошибки.

Все следующие команды выполнены из `clearledger`, Node `v22.23.2`, установленные
зависимости. Для сбора raw stdout/метаданных использована локальная обёртка
`.artifacts/meeting-start-context/run.py`; она не меняет runtime. Успешные
проверки без нового изменения исходников повторно не запускались.

```sh
# Baseline: исходный runtime базы, новый модуль тестов уже добавлен
node --test --experimental-strip-types src/lib/meetingStartContext.test.ts

# Финал: единый авторский прогон на 07fa0ce0e1f763e038af14b5512d26ea291a471e
node --test --experimental-strip-types src/lib/meetingStartContext.test.ts src/lib/confServiceContext.test.ts src/lib/apiJsonSessionGeneration.test.ts src/lib/apiBinaryTransport.test.ts src/lib/apiSessionRedirect.test.ts

node node_modules/typescript/bin/tsc --noEmit --incremental false -p tsconfig.app.json
node node_modules/typescript/bin/tsc --noEmit --incremental false -p tsconfig.node.json
node node_modules/eslint/bin/eslint.js src/services/conferenceService.ts src/lib/meetingStartContext.test.ts
```

| Авторская проверка | Результат | Время, с | Raw stdout / метаданные |
| --- | --- | --- | --- |
| Baseline нового модуля | Ожидаемый FAIL, exit 1: 117 всего, 19 PASS, 98 FAIL, 0 SKIP/cancelled | 74.409 | `baseline.stdout`, `baseline.json` |
| Финал пяти модулей | PASS, exit 0: 394 PASS, 0 FAIL/SKIP/cancelled | 72.642 | `final.stdout`, `final.json` |
| TypeScript app | PASS, exit 0 | 153.885 | `type-app.stdout`, `type-app.json` |
| TypeScript node | PASS, exit 0 | 1.862 | `type-node.stdout`, `type-node.json` |
| ESLint двух изменённых TS-файлов | PASS, exit 0 | 2.921 | `eslint.stdout`, `eslint.json` |

394 означает итоговый счётчик Node, включая родительские и вложенные тесты:
182 top-level и 212 вложенных записей. Новый модуль содержит 117 плоских тестов,
19 контролей плюс 98 проверок границы; все 117 найдены по точным именам в
финальном stdout и прошли. Числа не трактуются как количество leaf-сценариев
или уязвимостей. У проверок типов и линтера тестовых счётчиков нет.

Команда для одного независимого focused-прогона координатором:

```sh
node --test --experimental-strip-types src/lib/meetingStartContext.test.ts src/lib/confServiceContext.test.ts src/lib/apiJsonSessionGeneration.test.ts src/lib/apiBinaryTransport.test.ts src/lib/apiSessionRedirect.test.ts
```

Независимая проверка координатора учитывается отдельно от авторских результатов.
Этот отчёт сам по себе не объявляет её завершённой и не заменяет итоговый verdict
координатора.

TypeScript AST-проверка (`node .artifacts/meeting-start-context/preservation.cjs`
из корня) подтвердила изменение только трёх разрешённых функций. Семь остальных
top-level statements, включая все импорты, `MeetingUrls`, `сказатьОВходе`,
`getMeetingsConfig` и `startEventMeeting`, совпадают по полному тексту и SHA-256.
Публичные сигнатуры обоих start-методов сохранены. `apiClient`, `confService` и
четыре существующих тестовых модуля совпадают с базой побайтно. Доказательства:
`preservation.json` и `unchanged-modules.json`; время AST отдельно не измерялось.

| Артефакт | SHA-256 |
| --- | --- |
| `conferenceService.ts`, baseline | `f8d43932580539b132b50ff547d13c19f28ddf16046b2f8b476085f8dec24d72` |
| `conferenceService.ts`, финал | `4f484e890459b972a4d9e72fe90d69862540888751d663f6c01e382485a0eab3` |
| `meetingStartContext.test.ts`, baseline и финал | `4a5d3bebf61540f4c565ada4c4475ba6c753f5777b8afc48df616c083c0a2818` |
| `baseline.stdout` | `a4685d4350cb35ede33a5aebf1c9bf03bf4750105b7b6f688332a769821f938c` |
| `final.stdout` | `0086e2ba4e917d6318aa32b99b7006402ec35bd5796eeb12ef368af9bac96b50` |
| `source.diff` | `7d14c8f1516a2fb95b2098dd73e1583f121745fb862fd4a30bcbb950a877cff2` |

Полный diff runtime и нового теста сохранён в `source.diff` вне Git и
воспроизводится из неизменяемых коммитов:

```sh
git diff 2578ec8fbef3c8a21fa274df72f96b86cd3e06af 07fa0ce0e1f763e038af14b5512d26ea291a471e -- clearledger/src/services/conferenceService.ts clearledger/src/lib/meetingStartContext.test.ts
```

Реальный браузер, сервер, конференция, VM и production e2e: **NOT RUN**.
SSH, SQL, реальные env/session/keys и живые встречи не использовались. Build,
установка или обновление зависимостей, merge, deploy и enable не выполнялись.
Остаётся независимая приёмка координатора и последующее решение о включении в
общую линию; клиентская синтетическая проверка не подтверждает реальное
поведение popup blocker или доступность сервера конференций.
