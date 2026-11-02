# Согласие внешнему приложению — M10/M11 frontend

База: `922637f7b67203e6e67531adf5787865afd76e0b`, тот же worktree и ветка
`fix/location-company-context-20261029`. Это реализация браузерной формы согласия,
не выпуск OAuth backend и не включение feature flag.

`/developer/authorize?requestId=...` — отдельная ветка настоящего router под
`AuthProvider`, без admin gate и оболочки выбранной компании. Страница использует
`ProtectedRoute` и допускает запрос только при реальной Core-сессии. Offline и
demo показывают недоступность до consent HTTP. Новый `developerService` вызывает
только существующие `get/post`, без нового transport, retry или mock fallback.

Контракт согласован с координатором:

| Вызов | Результат |
|---|---|
| GET `/api/developer/authorization-requests/{id}` | `id`, `clientName`, `requestedScopes[{code,description}]`, `companies[{id,name,eligibleScopes}]`, `expiresAt` |
| POST `.../{id}/approve` | Тело `{companyId,scopes}`; ответ `{redirectUrl}` |
| POST `.../{id}/deny` | Ответ `{redirectUrl}` |

Компания и действия не выбраны автоматически. При смене компании отметки
сбрасываются; отправить можно только пересечение requested/eligible выбранной
компании. Если запрошен `openid`, его пользователь тоже отмечает явно, и без
него разрешение недоступно. Отказ доступен без выбранной компании и даже при
отсутствии компаний с доступными действиями. Обе команды требуют явного клика.

Проверяется поколение запроса, сессия и срок действия до команды и после ответа.
При смене requestId/user прежняя форма размонтируется; смена Core-сессии не
показывает поздний GET и запрещает старый callback. Синхронный ref блокирует
два клика до render, а после успешного решения остаётся заблокирован до ухода.
Нет автоматических повторов команд. Уже отправленную команду UI не откатывает.

Callback берётся только из ответа approve/deny; query redirect игнорируется.
Клиент разрешает HTTPS, а HTTP только для точного loopback hostname и только в
dev-сборке; credentials в URL, управляющие символы, относительные адреса и иные
схемы запрещены. Переход — обычная browser navigation, Core Bearer не отправляется
на callback. Frontend не хранит OAuth code/token/client_secret и не заменяет
серверные проверки redirect registration, request ownership, membership и grant.

401 показывает необходимость входа, 403 — честный общий текст «запрещён или
отозван», 404 — запрос не найден/недоступен, 409 — уже обработан, 410 — истёк,
400/422 — некорректный выбор, 503/сеть — недоступность. Текущий transport сохраняет
status/detail, поэтому UI не выдумывает machine code из отсутствующего поля.
Default-off feature даёт явную недоступность, без пустого успешного согласия.

Возврат после входа использует штатные `state.from` и `/login?next=...`, который
проверяет существующий `safeBackTo`. Target строится из постоянного внутреннего
пути и закодированного opaque requestId. Дублирование через `next` необходимо:
провайдер фильтра на login может делать replace и стирать `history.state`.

Координатор расширил ownership общего `apiClient` сообщением
`msg_70e6abadf14d`, затем подтвердил в ответе на ask: исправлять корень 401,
без специального исключения для developer route. Отложенный redirect теперь
сохраняет уже достигнутый login/public route, отменяется при `setToken` и
проверяет наличие новой сессии перед выполнением. Если человек всё ещё на
защищённой странице, строится внутренний `next` через `safeBackTo` с учётом
basename. Прежнее уведомление «Сессия истекла» и guard параллельных 401 сохранены.
`PUBLIC_PAGES` не расширялся, новый persistent login-intent механизм не вводился.

Запуск из `clearledger`:

```bash
node --test --experimental-strip-types src/lib/developerService.test.ts
node --test --experimental-strip-types src/lib/apiSessionRedirect.test.ts
node --test --experimental-strip-types tests/developer-authorization/browser.test.ts
npm run test:unit
npm run typecheck
node node_modules/eslint/bin/eslint.js src/pages/DeveloperAuthorizePage.tsx src/services/developerService.ts src/services/apiClient.ts src/lib/developerService.test.ts src/lib/apiSessionRedirect.test.ts tests/developer-authorization/browser-entry.tsx tests/developer-authorization/browser.test.ts
git diff --check
```

Браузерный прогон использует **настоящие App/router/AuthProvider/ProtectedRoute/
LoginPage и apiClient**. Vite запускается только на loopback с `configFile: false`,
`envFile: false`, без PWA/main scheduler. Все API и callback перехвачены
Playwright; любая прочая внешняя сеть запрещена. Пользователь, пароль, компании,
действия и сессии синтетические. Рабочие API, БД, ВМ и credentials не использовались.
Browser plugin not available; использован уже установленный Playwright Chromium.

Покрыты ordinary user, отсутствие autoapprove, обязательный openid и allowed
selection, сброс выбора, double submit, deny без доступных компаний, поздние GET
и POST A→B, смена Core-сессии во время GET/POST, ошибки GET/POST, expiry по часам
браузера, небезопасный callback, отсутствие Authorization на callback, настоящий
login с возвратом к opaque requestId, demo/offline запрет.

Результаты 29.10.2026: unit сервиса **10/10 PASS**, общий 401 redirect
**7/7 PASS**, полные unit **290/290 PASS**, браузерные
сценарии **16/16 PASS**, typecheck и точечный ESLint **PASS**. Финальный состав
проверен в этом worktree; package/lock не менялись, зависимости те же, что для
предыдущей задачи (совпадающий lock, локальная `.tmp` для tsc).

Regression proof для 401 использует настоящий старый transport из Git, не меняя
рабочий файл:

```bash
CONSENT_API_BASELINE=922637f7 node --test --experimental-strip-types src/lib/apiSessionRedirect.test.ts
```

Это **ожидаемо отрицательный** прогон: 6 FAIL / 1 PASS на старом коде, включая
стирание `next`, неснятый guard после нового входа и отсутствие внутреннего
return target/basename. В обычном режиме тот же тест проверяет текущий
`apiClient`, все 7 проверок проходят. Отдельно browser-тест до правки воспроизвёл
hard `/login?f=...` с потерянным requestId после истёкшей Core-сессии; после
правки проверяет сохранение `next` и настоящую повторную авторизацию до окна
старого redirect, без выброса новой сессии.

Визуальная проверка: desktop/light 1440×1000, mobile/dark 390×844, отсутствие
горизонтального overflow, overlay и неожиданных JS/console ошибок в основных
сценариях. Скриншоты и computed styles — `/tmp/developer-authorize-20261029/`;
ожидаемые HTTP 4xx/503 в отрицательных fixtures не считаются JS-сбоем.
Impeccable detector: `[]`. Из-за прямого запрета делегирования финальный
визуальный просмотр выполнен в этой сессии. Токены DESIGN/index.css, Manrope,
14px body/12px meta, существующий Button и native form controls сохранены;
DESIGN и дизайн-система не менялись.

Ограничения: проверена frontend-граница на синтетическом HTTP-контракте;
интеграция с реализацией backend worker и реальные OAuth/provider callbacks
не проверялись. Не включались flags, не выполнялись PR/выпуск и обращения к
рабочим сервисам. HTTPS host allowlist, одноразовое использование request/code,
право выдать grant и действительные scopes остаются обязанностью backend.
