# M12/M17: общий транспорт загрузки первички

Дата: 30.10.2026. Изменение подготовлено в отдельном worktree на базе
`d43ad8c91ea5aaf594891075839b0cc983bb8571`, ветка `MagLook/gar`.
При старте HEAD совпадал с root, рабочее дерево было чистым. После обновления
root до `2bf73253` исходники `apiClient.ts` и `intakeDocsService.ts` остались
побайтово одинаковыми с исходной базой; перенос документационных коммитов не требовался.

## Поведение

`uploadIntake` передаёт FormData существующему `apiClient.upload`.
Удалены отдельный fetch, чтение токена из localStorage и ошибка
`upload failed: <status>`. Используются общий снимок Bearer/company/organization
заголовков, `VITE_API_URL`, обработка JSON/API ошибок и защита новой сессии от
позднего 401 прежнего токена.

Контракт аргументов и результата `uploadIntake` сохранён. FormData содержит ровно
`company_id`, `declared_type`, `source=file`, `file`; имя, MIME и байты файла
сохраняются. JSON результата возвращается без преобразования, включая `batchId`,
`columns`, необязательные `items` и `error`. Разбор не вызывает accept и не повторяет
запрос при ошибке. `acceptIntake` остаётся отдельным явным действием человека.
Код UI, authService, backend и остальных consumers не менялся.

Адрес загрузки теперь собирается по общему правилу `${VITE_API_URL}/api/intake-docs/upload`.
Раньше относительный `/api/intake-docs/upload` всегда уходил на origin интерфейса.
Это намеренное выравнивание с общим клиентом: синтетическая проверка использует
разные origin интерфейса и API. При пустой базе путь остаётся относительным.
Загрузка также наследует существующий demo guard общего upload; общий демо-сценарий
и `demoWrite` не менялись и отдельной приёмкой этого изменения не покрываются.

## Решение по credentials

До правки выявлено различие: intake явно запрашивал fetch `credentials: 'include'`,
а общий upload не задавал credentials, то есть применял fetch default `same-origin`.
В первоначальных трёх разрешённых файлах сохранить include через существующий API
было невозможно. На checkpoint координатор отдельно разрешил четвёртый файл
`apiClient.ts` и узкое совместимое расширение:

```ts
upload<T>(path, formData, onProgress?, options?: { credentials?: 'include' }): Promise<T>
```

Intake вызывает `upload(path, fd, undefined, { credentials: 'include' })`.
Fetch получает credentials из options; в XHR явный include устанавливает
`withCredentials=true` после `open` и до `send`. Вызовы без options сохраняют
прежний fetch default и XHR default `withCredentials=false`.
Значения `omit` и `same-origin` API не обещает: XHR не даёт честно воспроизвести
все варианты fetch credentials. Политика аутентификации и обработчик 401 не менялись.

## Проверки

Новый `src/lib/intakeDocsTransport.test.ts` использует существующий подход
node:test + Vite SSR: загружаются реальные сервис и apiClient, подменены только
fetch, storage, toast, таймер редиректа и контрольный XHR. `envFile:false`,
`configFile:false`, middleware mode, все данные синтетические.

Пять сценариев проверяют:

- Сериализованный multipart wire с ровно четырьмя полями, исходными байтами,
  кириллическим именем файла и MIME; общий API base, актуальные заголовки после
  смены контекста A→B, include и неизменный объект ответа. Следующий accept
  выполняется только отдельным явным вызовом.
- Прежний fetch default при отсутствии четвёртого аргумента.
- XHR include/default, порядок open/send, заголовки и progress 0.5.
- JSON 422 с fieldErrors, JSON 409, HTML 503, HTML 200 и повреждённый JSON 200:
  общие классы/тексты ошибок, один запрос без retry.
- Текущий 401 завершает сессию и использует общий toast/redirect; поздний 401
  после начала чтения body сохраняет новый токен, без toast и таймера.

Контроли fetch default и XHR include/default относятся к добавленному API,
а baseline-контроль ниже проверяет только прежний consumer. Каждый дочерний
сценарий ограничен 10 секундами, включая ожидание начала чтения 401 body.
Общий multipart upload не получает binary fencing: отбрасывание успешного ответа
при смене компании/организации во время запроса этой правкой не реализуется.

Команды из `clearledger`:

```sh
node --test --experimental-strip-types src/lib/intakeDocsTransport.test.ts
node --test --experimental-strip-types src/lib/apiBinaryTransport.test.ts src/lib/apiSessionRedirect.test.ts src/lib/coreExportTransport.test.ts
./node_modules/.bin/tsc --noEmit -p tsconfig.app.json
./node_modules/.bin/tsc --noEmit -p tsconfig.node.json
./node_modules/.bin/eslint src/services/apiClient.ts src/services/intakeDocsService.ts src/lib/intakeDocsTransport.test.ts
```

Новый набор: PASS 6/6 с учётом родительского теста. Прежние transport/session/export
наборы: PASS 386/386, файлы этих тестов не менялись. Targeted eslint исходных двух
сервисов на baseline: 0 ошибок и предупреждений; после изменения сервисы и новый
тест также проходят lint. TypeScript app/node: PASS (обе команды, exit 0);
те же проверки на исходной базе также прошли.

Регрессионный контроль без изменения рабочего исходника:

```sh
INTAKE_SERVICE_BASELINE=d43ad8c9 INTAKE_CASE_PATTERN='wire has' node --test --experimental-strip-types src/lib/intakeDocsTransport.test.ts
```

Он ожидаемо падает на старом сервисе: фактический относительный URL отличается от
ожидаемого адреса с синтетической API base. Обычный прогон всегда проверяет текущий
worktree. Фильтр нужен только для этого направленного baseline-контроля.

Это transport proof на синтетических границах, а не server acceptance.
Реальные `.env`, API, SQL, SSH, стендовый браузер и данные не использовались;
проверка браузерного CORS/cookie обмена с сервером и выпуск в стек не выполнялись.
Общий binary transport и финансовая логика не изменялись.
