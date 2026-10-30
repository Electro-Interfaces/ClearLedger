# M12/M17: characterization экспорта наработок Аудитора

Дата: 30.10.2026. Source pin: `685f0654a2e64ee6bd5164b4c28746f534427f2c`.
Ветка: `agent/api-auditor-export-context-20261030`, создана от clean own worktree.
Предыдущие два файла native triage не изменялись. Программа M00–M19 открыта,
любые PR остаются draft; merge и deploy запрещены.

## Реализованная граница

Root принял baseline и отдельно разрешил правку import/exportWork в
spaceAuditorService. Затем разрешил immutable dependency
`1493fe83f270fb29894a15b56c5b58241865e3ca` с общим
`captureApiContextGuard(): () => void`; в этой ветке dependency находится отдельным
коммитом `9a3bb160e02cad98721ca9f2d3f34ea950d7d812`. Все пять файлов dependency
побайтово совпадают с исходным коммитом. Незакоммиченный WIP не копировался;
apiClient в собственном пакете не правился.

exportWork захватывает общий guard до dispatch и проверяет его после fetch,
разбора HTTP error body и blob, непосредственно перед созданием object URL,
после создания URL/якоря, перед click и перед успешным return. Catch повторяет
guard перед распространением ошибки. Смена principal/company/org или поколения
сессии завершает устаревшую операцию AbortError; прежняя ошибка не подменяет эту
отмену. Обычные ошибки Аудитора и их тексты сохраняются при актуальном контексте.

Nested finally удаляет созданный якорь и освобождает URL ровно один раз, также при
исключениях create/click/remove. Вложенный finally вызывает revoke даже если
anchor.remove бросил исключение. Путь остаётся с detached anchor; append не добавлен.

AST-сравнение с исходником baseline ограничивает runtime delta одним import
из apiClient и функцией exportWork; остальные функции Аудитора идентичны.
Общий guard читает snapshot поколения и Bearer/company/org из существующего
apiClient, но его заголовки не становятся заголовками Auditor запроса.

| Итоговый исходник | SHA-256 |
|---|---|
| spaceAuditorService.ts | `267a1a8cee1aac66b24872642e016086dbd762cb1c5a126029a01957ed8a353b` |
| auditorExportContext.test.ts | `d9f3f51768c90a5735d5d675e7b7e14eadd6de81e89679b73e23c26f70433bd1` |
| apiClient.ts из dependency, без собственных изменений | `247ba8ac02dc3e9f9644c52a66e9250aa72a8b330fba38d26d55f7e65eb80693` |

## Статус на первом checkpoint

До первого решения root были подготовлены только тест и этот отчёт;
runtime, commit и push на checkpoint не выполнялись. Владельцем apiClient
оставался отдельный исполнитель; разрешение на consumer дано после actual baseline.

Исследована только цепочка `AuditorPage → spaceAuditorService.exportWork`.
Кнопка при `settings.can_manage` вызывает сервис и показывает его ошибку:
[`AuditorPage.tsx:370–375`](https://github.com/Electro-Interfaces/ClearLedger/blob/685f0654a2e64ee6bd5164b4c28746f534427f2c/clearledger/src/pages/AuditorPage.tsx#L370).
Actual baseline implementation:
[`spaceAuditorService.ts:226–238`](https://github.com/Electro-Interfaces/ClearLedger/blob/685f0654a2e64ee6bd5164b4c28746f534427f2c/clearledger/src/services/spaceAuditorService.ts#L226).
Это отдельный same-origin Auditor proxy `/auditor/api/export-work`, не Core API.

| Исходник baseline | SHA-256 |
|---|---|
| spaceAuditorService.ts | `5c785e0beda4d5c798cd3e6ae925d4c0d1c68c1467f39a90f3d3ffb0bcb7c08c` |
| apiClient.ts | `72db95aeb56c1a613579def4c444593e1f1bde550b3c8c172c38533a4f7cc34c` |

## Actual-service harness и наблюдения

Новый `src/lib/auditorExportContext.test.ts` загружает **настоящие**
spaceAuditorService и apiClient через Vite SSR. Context transitions вызывают
настоящие `setToken`, `clearToken`, `setApiCompany`, `setApiOrganization`.
Подменены только fetch и его synthetic Response body, window/storage, object URL
и минимальная DOM-граница якоря. Service/auth/toast/timers не подменяются.
`configFile:false`, `envFile:false`, middleware mode без слушающего HTTP-сервера;
Core base и UI origin намеренно различаются. Все токены, URL и байты синтетические.

34 дочерних сценария, timeout каждого 8 секунд, всего parent 45 секунд.
Тестовые diagnostic records фиксируют фактические запросы, порядок effects,
число оставшихся URL и прикреплённых якорей, в том числе при падении assert.

| Группа | Наблюдение baseline |
|---|---|
| Principal/company/org при deferred fetch и blob, 6 сценариев | После transition записаны `url → create → click → revoke`; старая операция скачивает архив |
| A→B→A компании, организации и principal; clear→set и повтор set того же token, 5 сценариев | Старый export выполняет `click`; контекстные setters вызваны реально |
| После resolved blob перед download continuation, 3 сценария | Diagnostic trace начинается с `context-change`, затем создаёт URL и выполняет `click`; переход точно предшествует эффекту |
| Transition в URL/create boundary, 2 сценария | `click` выполняется после смены principal; URL в обычном завершении освобождается |
| Deferred error body при transition, 3 сценария | Возвращается прежний `Error` вместо context cancellation; Core token сохранён, download effects отсутствуют |
| Исключения create anchor / click, 2 сценария | По одному URL остаётся живым, revoke не вызывается; исходная ошибка распространяется |
| Остальные 13 controls | Обычный архив, bytes/type/filename/headers, текущий новый principal, одинаковые company/org setters, HTTP403/500/401, non-JSON500, network/body failures, delayed error без transition, исключения create URL/revoke проходят |

Baseline: **13 PASS / 21 FAIL** среди 34 child cases; node:test с parent:
**35 tests, 13 PASS / 22 FAIL, 0 SKIP/cancelled**, 1.435 секунды runner.
Это не 21 отдельная production vulnerability: сценарии описывают отсутствие
границы lifetime и cleanup одного consumer. Deferred error не доказывает скачивание
или смену сессии; он учитывается отдельно от observed download effects.

Исходный тест этих 34 child cases сохранён приватно с SHA-256
`ba439a725ce577dbf0aa498c38d8ee11c4bab41ca6f790117b968344865821b5`.
После source grant добавлены три отдельных `candidate` controls: remove ровно
один раз, исключение remove с обязательным revoke, смена principal при cleanup
перед return. Эти controls относятся к новому finally, их отсутствие в baseline
не выдаётся за дополнительное воспроизведение старого дефекта.

В baseline якорь **не добавляется** в DOM. Поэтому исключение append пока не
выдаётся за воспроизведённую ошибку. Harness поддерживает append для проверки
будущей согласованной реализации; тест на такой путь добавляется только если
runtime действительно начнёт его выполнять. После уже состоявшегося click
сохранение файла этим механизмом отменить нельзя.

## Сохранённые protocol controls

Один относительный GET `/auditor/api/export-work`, body отсутствует; только
`Authorization: Bearer <текущий synthetic token>`, без Core company/org headers
и без явного credentials override. Общий Core `VITE_API_URL` не используется.
Возвращённые bytes и Blob MIME сохраняются; имя остаётся `auditor-work.tar.gz`,
даже при другом Content-Disposition сервера. Успешный non-JSON response читается
как binary; JSON Content-Type gate не добавляется.

HTTP errors сохраняют собственный Auditor `error`/status fallback, network/body
rejection сохраняет исходный объект. В частности Auditor401 не очищает Core token
и не меняет location; Core logout/error parser не участвует. Обычный успешный
экспорт освобождает созданный URL ровно один раз.

## Согласованный объём

Изменены только import/exportWork и новый actual-service тест/отчёт. Захват context,
проверки каждого await и непосредственно перед effects остаются в caller frame;
асинхронный Core download helper не используется. Последний body-await проверяется
microtask controls, где transition предшествует URL/click. Отдельный cleanup/return
control проверяет, что смена principal при remove отменяет завершение старой
операции; ранее выполненный click при этом не выдаётся за отменённый.

Endpoint, auth profile, binary bytes, filename и Auditor errors сохранены.
Core binary/JSON transport, SSE, PTY, остальные Auditor functions, backend и ACL
не включены в собственный runtime delta. Нового append пути нет, поэтому
append-failure не заявляется проверенным ни для baseline, ни для candidate.

## Итоговые проверки

На согласованном source:

| Проверка | Результат |
|---|---|
| Исходный тест, те же bytes/SHA, 34 child cases | **35/35 PASS** с parent, 1.387 с |
| Итоговый новый модуль: те же 34 + три cleanup/return controls | **38/38 PASS** с parent, 4.551 с |
| Новый модуль + прежний состав 471 | **509/509 PASS**, 0 FAIL/SKIP/cancelled/TODO, 79.451 с |
| TypeScript app и node, раздельные own incremental caches | **PASS**, обе команды exit 0 |
| Targeted ESLint service/test | **PASS**, 0 ошибок и предупреждений |
| Source composition | 5/5 dependency files идентичны immutable source; runtime AST delta только import/exportWork |
| Original test preservation | Первые 34 cases и harness в итоговом модуле побайтово идентичны исходному 34-case test |
| diff-check итоговых own files | **PASS** |

471 уже включает прежние 415 transport/voice тестов и 56 проверок конференций.
Новый модуль прибавляет 38 с parent; отдельный повтор original35 не прибавляется
к 509. Все запущенные проверки завершились, результаты Node child прочитаны;
timeout или отменённых тестов нет. Runtime после этих прогонов не менялся.

## Воспроизведение и пределы

Из `clearledger`, на установленном наборе зависимостей:

```sh
node --test --experimental-strip-types src/lib/auditorExportContext.test.ts
node --test --experimental-strip-types src/lib/auditorExportContext.test.ts src/lib/confServiceContext.test.ts src/lib/voiceServiceContext.test.ts src/lib/voiceAuth.test.ts src/lib/apiSessionRedirect.test.ts src/lib/apiBinaryTransport.test.ts src/lib/coreExportTransport.test.ts src/lib/intakeDocsTransport.test.ts
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json --incremental --tsBuildInfoFile ../.artifacts/private/auditor-export-context-20261030/app.tsbuildinfo
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.node.json --incremental --tsBuildInfoFile ../.artifacts/private/auditor-export-context-20261030/node.tsbuildinfo
node node_modules/eslint/bin/eslint.js src/services/spaceAuditorService.ts src/lib/auditorExportContext.test.ts
git diff --check
```

Первый baseline запуск ожидаемо завершается exit 1 по реальным effects; точечный
ESLint нового теста PASS. Harness поддерживает направленный повтор immutable
service через `AUDITOR_EXPORT_BASELINE=685f0654` и фильтр
`AUDITOR_EXPORT_CASE_PATTERN`; это actual исходник из Git, не service stub.

Private evidence в own `.artifacts/private/auditor-export-context-20261030/`:
`baseline.log`, `baseline-test.ts`, `original-34-candidate.log`, `target.log`,
`combined.log`, `app-ts.log`, `node-ts.log`, `lint.log`,
`final-source-verification.json`. Артефакты игнорируются Git и не включены в коммит.

Guard не прерывает уже отправленный fetch или чтение blob: он запрещает старые
локальные effects и продолжение после context transition. Signal API не добавлялся.
После уже выполненного click загрузка не отзывается. A→B→A отслеживается через
настоящие setters; произвольный storage A→B→A без setter не обещается. React
providers/login lifecycle не монтировались; проверены actual service и setters.
Caller UI catch не менялся, quiet handling AbortError этим пакетом не обещается.

Это synthetic transport/DOM characterization, не проверка browser download
manager, серверного архива/ACL, production exploit, Full Auditor, SSE или PTY.
SQL/DB, настоящие HTTP/WS, SSH, браузер, реальные env, установка пакетов,
merge/deploy и изменения данных рабочего пространства не выполнялись. Полный CI
не запускался; этот пакет не завершает программу M00–M19 и не разрешает выпуск.
