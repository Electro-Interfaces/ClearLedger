# M12: общий binary transport Ядра — 30.10.2026

База: `7b204feeaa17c5d5eb6c6a4670291a6c7ca81c2e`, ветка
`agent/core-binary-transport-20261030`. Локальная доработка общего Ledger,
применимая к РусГидро и другим пространствам. Выпуска и проверки рабочего
пространства не было.

## Причина и состав

В исходном `src/services/apiClient.ts` функции `downloadFile` и `downloadBlob`
вызывали `fetch` отдельно от `handleResponse`. Первая имела собственный разбор
`detail`, вторая возвращала только `statusText`; обе обходили уведомление и
redirect текущей истёкшей сессии. Они не принимали signal, не отбрасывали байты
после смены контекста, а исключение при декодировании `filename*` или работе
с якорем могло оборвать успешную выгрузку либо оставить blob URL.

Изменены только:

- `src/services/apiClient.ts`;
- `src/lib/apiBinaryTransport.test.ts`;
- этот отчёт.

`handleResponseError` теперь единожды разбирает HTTP-ошибки для JSON и binary:
сохраняются `ApiError`, `ApiValidationError`, серверное объяснение 403 и
прежний общий текст 403 без объяснения. Невалидный JSON/plaintext HTTP-ошибки
даёт прежний status/statusText, его тело не становится файлом. JSON success,
204, проверка Content-Type, повреждённый JSON, 422 и правила текущего/позднего
401 сохранены. Успешный binary-ответ читается как Blob независимо от Content-Type.

Совместимые сигнатуры:

```ts
downloadBlob(path, { signal })
downloadFile(path, fallbackName, { signal })
// Прежние downloadBlob(path) / downloadFile(path, fallbackName) также работают.
```

`fetchBinary` фиксирует Authorization, company и organization при старте.
Границы проверки: до отправки, после fetch, после разбора HTTP-ошибки,
перед blob, после blob и после await helper в публичном методе. Для файла
проверка повторяется непосредственно перед созданием URL/якоря, добавлением
якоря и click. Отмена через signal сохраняет его причину; устаревший контекст
отклоняется `DOMException` с именем `AbortError`. Новая сессия не очищается
поздним 401, в том числе после асинхронного чтения error body.

На актуальном 401 защищённая обычная страница и приватная
`/developer/authorize` получают прежнее уведомление, очистку токена и delayed
redirect с safe next. Публичные login/invite/space-guest не очищают токен и
не перенаправляют пользователя. Существующий `setToken` отменяет старый redirect.

Binary-only generation увеличивается при фактической смене company/org и
при каждом `clearToken`/`setToken`. Сравнение одного snapshot не заметило бы
A→B→A; поколение замечает этот переход через setters, а также clear→set и
повторную установку того же токена как границу новой сессии. Повтор установки
той же company/org не отменяет загрузку. JSON-запросы поколение не проверяют:
их существующее поведение намеренно сохранено. Дополнительное сравнение
текущего Authorization замечает прямую запись другого токена в localStorage.

Для имени сохраняется приоритет корректного RFC 5987 `filename*`, затем
quoted `filename`, затем аргумент `fallbackName`. Ошибка percent decoding
использует запасное имя. После создания blob URL `finally` удаляет якорь и
освобождает URL; вложенный finally освобождает URL даже при исключении remove.
Сетевые и body-ошибки распространяются вызывающему коду без synthetic fallback.
Явный demo отклоняет оба binary-метода до fetch через существующий
`DemoReadOnlyError`; прежний demo-контракт `downloadBlob` сохранён.

## Проверки

Из `clearledger`:

```bash
node --test --experimental-strip-types src/lib/apiBinaryTransport.test.ts src/lib/apiSessionRedirect.test.ts src/lib/locationService.test.ts
node e2e/auth-context-lifecycle.check.mjs
npm run typecheck
node node_modules/eslint/bin/eslint.js src/services/apiClient.ts src/lib/apiBinaryTransport.test.ts
git diff --check
```

Новый набор загружает настоящий apiClient через Vite SSR, следуя существующему
`src/lib/apiSessionRedirect.test.ts`. Подменены только внешние границы:
fetch, storage, toast, timers и минимальный DOM probe, учитывающий добавленные
якоря и blob URL. Удерживаемые promises воспроизводят поздние ответы
транспорта, игнорирующего signal; microtask после body проверяет отдельную
границу await helper. Это intercepted transport/DOM tests, не E2E.

Покрыты оба binary-метода: abort до/после fetch, во время и сразу после body;
смена token/company/org на fetch/blob/401-body; A→B→A через setters,
clear→set, новый set того же токена; анонимный late401 и новая сессия;
текущие private/public401; 403, field/string422, plaintext502; точные binary
байты и текущие заголовки; Unicode/ascii/отсутствующее/повреждённое имя;
исключения create/append/click/remove; abort/context-change при создании
ресурсов до click; отсутствие оставшегося якоря и revoke URL. JSON-регрессии
проверены для GET/POST/PUT/PATCH/DELETE/fetch-upload. XHR401 и его поздний
Bearer дополнительно проверяет существующий session-redirect suite.

Результаты: новый набор **117/117 PASS** (включая родительские test nodes),
выбранный общий transport/session/location состав **151/151 PASS**,
AuthContext React/Chromium lifecycle **15/15 PASS**, точечный ESLint **PASS**,
`git diff --check` **PASS**, `npm run typecheck` **PASS**, в том числе финальный
прогон с изолированным `.tmp` на итоговом apiClient.

Для negative proof тот же harness читает immutable исходник apiClient из Git:

```bash
BINARY_API_BASELINE=7b204feeaa17c5d5eb6c6a4670291a6c7ca81c2e \
BINARY_CASE_PATTERN='filename|cleanup when create|HTTP error|current 401|demo explicitly' \
node --test --experimental-strip-types src/lib/apiBinaryTransport.test.ts
```

Focused baseline: **16 PASS / 20 FAIL / 81 SKIP**, ожидаемый ненулевой exit;
19 провалившихся leaf cases и один общий родительский test node.
Он выявляет прежние ошибки 401/403/422, повреждённое
имя, отсутствие revoke при исключении create и demo-fetch в downloadFile.
JSON-регрессии проходят также на baseline. Фильтр пропускает удерживаемые
abort-кейсы, поскольку исходный клиент не поддерживал отмену.

Зависимости повторно использованы локально без установки и изменения
package/lock: SHA256 lock
`33e8580295715406eab6ca35a84a4d2b5da7b5ea4c4e0bef0822d02cd9e41d92`;
все 530 установленных package entries совпадают с lock по version/integrity.
Финальный TypeScript cache `.tmp` изолирован в этом worktree.

## Ограничения

Caller AbortSignal передаётся в настоящий fetch и позволяет браузеру отменить
запрос. Context generation сама не прерывает уже начавшийся network/body:
она запрещает устаревший результат и последующие локальные download effects.
После уже выполненного click отменить сохранение нельзя.

A→B→A доказан для изменений через API setters этой вкладки. Произвольные прямые
storage mutation в других вкладках с возвратом того же токена этим поколением
не отслеживаются; новой глобальной session lifecycle механики не добавлено.
Не проверялись реальный сервер, browser download manager и рабочий стенд.
Chromium suite проверяет AuthContext, не настоящий экспорт. Полный CI не
повторялся; server/auth/runtime/router/DB/Compose, зависимости и рабочие данные
не менялись. PR, merge и deploy не выполнялись; интеграцией владеет координатор.


## Независимый повтор координатора

После переноса408588ab в общий кандидат02e6e963: transport/session/location
151 PASS за4.513с, без SKIP; React/Chromium lifecycle15 PASS за12.729с.
Оба TypeScript project checks (app/node) PASS с отдельными tsBuildInfoFile
в root .artifacts, точечный ESLint из clearledger и diff-check PASS.
Это локальная приёмка общего состава, не full CI или browser download manager.
Прямые fetch в других services/screens этим пакетом не переводились.
