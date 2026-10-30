# Пять Core XLSX-экспортов через общий transport

Дата: 30.10.2026. База: `13d1b6b3d544325ce0234677d2f7536e09e4c116`.
Ветка: `MagLook/core-export-consumers-20261030`.

Пять цепочек `fetch → blob → anchor` заменены вызовом существующего
`apiClient.downloadFile`. Изменены три сервисных файла, добавлены сервисная
регрессия и этот документ. `apiClient.ts`, экраны, сервер, модели, БД,
зависимости и lock-файлы не менялись. Финансовые расчёты и состав XLSX
остаются ответственностью прежних серверных операций.

## Сохранённый контракт запросов

Все операции сохраняют GET без тела и выполняют ровно один запрос.
Пути ниже указаны без неизменной базы `VITE_API_URL`.

| Публичная функция | Путь | Параметры query | Прежнее запасное имя |
| --- | --- | --- | --- |
| `exportMonthlyMatrixXlsx(companyId)` | `/api/charge-sessions/export/monthly-matrix` | `company_id`; прежняя прямая интерполяция | `station_monthly_matrix.xlsx` |
| `exportChargeSessionsXlsx(p)` | `/api/charge-sessions/export` | `company_id`, `date_from`, `date_to`; непустые `user_type`, `client`; непустые массивы `stations`, `regions` через запятую | `sessions_${dateFrom}_${dateTo}.xlsx` |
| `exportChargeSessionsPivotXlsx(p)` | `/api/charge-sessions/export/pivot` | `company_id`; непустые `date_from`, `date_to`; непустые массивы `stations`, `regions` через запятую | `Сессии ЭЗС со сводной ${span}.xlsx`, где `span` = `${dateFrom} — ${dateTo}` при обеих датах, иначе `весь период` |
| `exportCorporateBillingUpd(p)` | `/api/corporate/billing-export` | `company_id`, `date_from`, `date_to`; непустой `client`; `vat_rate` при `vatRate != null`, включая 0; непустые массивы `stations`, `regions` через запятую | `billing_upd_${client ? 'client' : 'all'}_${dateFrom}_${dateTo}.xlsx` |
| `exportXlsx(companyId, report, fileName?, params?)` | `/api/sites/export/${report}` | `company_id`, затем прежние `params`: `undefined`, `''`, `false` пропускаются; `true` → `1`; 0 и строки сохраняются | `fileName ?? ${report}.xlsx`, включая явно переданную пустую строку |

Сериализация через `URLSearchParams` сохранена. В `sites` прежний порядок
`qs.set` также сохранён: переданный `params.company_id` способен заменить
начальный параметр. Эта миграция не добавляет проверку входных бизнес-параметров.
`exportPortfolioXlsx(companyId)` по-прежнему вызывает общий sites-экспорт с
`report = portfolio` и запасным именем `projects_portfolio.xlsx`.

Исходные callers сверены до правок на базе:

- `clearledger/src/components/workspace/EnergyExportView.tsx:121,131,141,151`:
  строки сессий, биллинг, pivot и monthly; передаваемые экраном отборы сохранены.
- `clearledger/src/components/workspace/CorporatePanel.tsx:250,325`:
  сессии ЮЛ и биллинг с клиентом/сетевым контуром.
- `clearledger/src/components/sites/ExportButton.tsx:33`:
  четыре позиционных аргумента sites-экспорта.
- `clearledger/src/services/sitesService.ts`:
  существующий wrapper портфеля сохраняет свою сигнатуру.

Существующие вызовы и `Promise<void>` сохранены. Для четырёх функций
зарядных сессий/биллинга добавлен второй необязательный аргумент
`options?: { signal?: AbortSignal }`; для `exportXlsx` это пятый аргумент.
Новый параметр не требует изменений callers. Типы приложения проверяют
существующие реальные вызовы, сервисные тесты исполняют старые варианты.

## Общий целевой контракт downloadFile

До миграции эти пять экспортов самостоятельно читали только Bearer токен,
проверяли `res.ok` общей ошибкой и всегда использовали локальное имя файла.
Теперь транспорт использует принятый M12-контракт из `apiClient.ts`:

- Снимок текущих `Authorization`, `X-Company-Id`, `X-Organization-Id` при старте.
  Компания и организация остаются текущим контекстом transport; существующие
  query-фильтры сервисов сохранены отдельно.
- Имя из `Content-Disposition` имеет приоритет: валидный UTF-8 `filename*`,
  затем quoted `filename`, затем прежнее запасное имя сервиса. Повреждённый
  `filename*` возвращает выбор к quoted `filename` или запасному имени.
  Это намеренное общее поведение, включая случай явного sites `fileName`.
- Неуспешный HTTP-ответ отклоняет Promise через `ApiError`; 422 сохраняет
  `ApiValidationError` и ошибки полей; 403 сохраняет пояснение сервера.
  Тело HTTP-ошибки не превращается в скачанный XLSX.
- Актуальный 401 использует общий механизм истёкшей сессии: удаление токена,
  одно уведомление и отложенный безопасный переход на вход. Поздний ответ
  прежнего контекста отклоняется как `AbortError`, не завершая новую сессию.
- `AbortSignal` передаётся в fetch. Поколение сессии/компании/организации и
  сигнал проверяются вокруг асинхронного чтения ответа и перед кликом.
  Смена A → B → A и новый вход с тем же токеном также инвалидируют запрос.
- Общий `finally` удаляет anchor и отзывает object URL при успехе,
  исключении DOM и изменении контекста после создания ссылки.

Защита относится к контексту, изменённому во время запроса. Она не обнаруживает
произвольные устаревшие `companyId`, даты или другие query-параметры, уже
переданные caller до старта запроса; отдельный тест прямо фиксирует эту границу.
После клика браузер управляет скачиванием самостоятельно: транспорт не обещает
отменять или удалять загрузку в browser download manager.

`voiceService` не переносился: у него другая граница доверия. ACL, серверные
фильтры, финансовые данные и реальные выгрузки здесь не проверялись и не менялись.

## Локальная проверка

`clearledger/src/lib/coreExportTransport.test.ts` использует существующий подход
Vite SSR: загружает настоящие три сервиса и настоящий `apiClient`. Подменены
только fetch, storage, DOM, toast и таймер перехода. Сервер Ядра, SQL, ВМ,
рабочие токены и реальные данные не используются. Двоичные байты синтетические;
это проверка клиентского транспорта, не формул и содержимого XLSX.

Для каждой из пяти операций проверены точный GET/path/query, отсутствие лишних
запросов и тела, текущие заголовки, прежнее запасное имя, приоритет имени сервера,
целостность байтов и cleanup. Дополнительно проверены HTTP 403/404/422/500,
не-JSON 502, текущий 401 с уведомлением/переходом, сетевая ошибка, отмена до
fetch/во время fetch/чтения blob, смена company/session/org на fetch/blob/чтении
JSON 401, A → B → A, новый вход с тем же токеном, внешний токен и смена контекста
при DOM append. В stale/abort-сценариях клика нет; при исключении click cleanup
сохраняется. Отдельные варианты проверяют пустые фильтры, односторонние даты
pivot, VAT 0/20/отсутствующий, старые 2/3/4-аргументные sites callers и portfolio.

| Проверка | Результат |
| --- | --- |
| Новая сервисная серия | PASS: 251 сценарий + родительский тест, `252/252` |
| Выбранные binary/session/location + новая серия | PASS: `403/403`, без skip |
| Typecheck app, отдельный tsBuildInfoFile | PASS |
| Typecheck node, отдельный tsBuildInfoFile | PASS |
| ESLint трёх сервисов и нового теста | PASS |
| `git diff --check` | PASS |
| Полный CI / сборка / browser download manager / приёмка на стенде | Не запускались в рамках этой задачи |

Команды из `clearledger/`:

```sh
node --test --experimental-strip-types src/lib/apiBinaryTransport.test.ts src/lib/apiSessionRedirect.test.ts src/lib/locationService.test.ts src/lib/coreExportTransport.test.ts
../node_modules/.bin/tsc --noEmit -p tsconfig.app.json --tsBuildInfoFile ../.artifacts/cache/core-export-app.tsbuildinfo
../node_modules/.bin/tsc --noEmit -p tsconfig.node.json --incremental --tsBuildInfoFile ../.artifacts/cache/core-export-node.tsbuildinfo
../node_modules/.bin/eslint src/services/chargeSessionsService.ts src/services/corporateService.ts src/services/sitesService.ts src/lib/coreExportTransport.test.ts
git diff --check
```

Среда: Node `v22.23.2`, TypeScript `5.9.3`. Зависимости переиспользованы через временный корневой
`node_modules` symlink на
`/home/mag/orca/workspaces/ledger-app/api-client-context-20261029/clearledger/node_modules`
(Vite `7.3.6`); установки пакетов и изменений package/lock не было. Зависимости
использовались только для чтения; общий `node_modules/.tmp` не менялся.
После проверок удалён только созданный symlink, его целевой каталог сохранён. Новый
Vite-кеш и оба tsBuildInfoFile расположены в собственной `.artifacts/cache`.
Логи локальных проверок: `.artifacts/core-export-consumers/` (не коммитятся).

Checkpoint совместимости отправлен координатору до правок через Orca,
сообщение `msg_97a190313c79`. `git pull --ff-only` не применил изменений:
исходная Orca-ветка не имела upstream; сохранена заданная база.
Общие отчёты/память не менялись согласно владению ровно пятью файлами.
Результат предназначен для проверки и интеграции координатором: PR, merge и
выпуск в рабочее пространство не выполнялись.
