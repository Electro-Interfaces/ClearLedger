# Исправление устаревших auth loads, 30.10.2026

Кандидат в owned worktree, ветка `agent/auth-context-stale-load-20261030` от
`4bcce27b`; прежняя `origin/MagLook/harlequin` сохранена. Root интегрирует
исправление поверх своей линии, в которой принят M15. Квота, root browser test,
Swagger/OAuth guards, generated artifacts, реальные env, VM и данные не менялись.
SQL-подключений и DDL в этой задаче не было.

## Подтверждённая причина

Root предоставил browser diagnostics: после initial docs PKCE и portal PASS,
закрытия первого Native Swagger popup с wrong-state callback повторное согласие
оказывалось на `/login` без GET `/auth/me`. Наблюдение само по себе не доказывало
причину. В исходном `AuthProvider` getMe.catch вызывал `api.clearToken()` до
проверки `alive`; cleanup защищал только setState. Приложение использует React
StrictMode и отдельные AuthProvider на developer routes.

Тесты монтируют настоящий React19 AuthProvider в Chromium через Vite, настоящие
authService/apiClient и browser localStorage. Playwright удерживает/завершает
только синтетические HTTP-ответы; эффект, transport и хранилище не подменяются.
На unmount запрос всё ещё мог удалить общий Core token; поздний A failure удалял
token B после applySession B, а поздний A success подменял React user/token B на A.
Отдельно общий apiClient.handleResponse очищал B при позднем A401 до входа в
provider.catch. Исправление только AuthContext оставило этот последний FAIL.

По дополнительному source review root подтверждена вторая граница:
authService.login сохранял access_token до возврата в provider, поэтому поздний
login A заменял B либо восстанавливал token после logout. Два controlled React
теста воспроизвели оба случая до переноса записи токена. Поиск production callers
показал, что authService.login вызывает только AuthProvider; LoginPage/RegisterPage
используют context.login. Сервис register и его существующее сохранение token
не изменены.

## Изменения

- AuthProvider использует локальную generation профиля и captured token для
  success/error/finally; cleanup инвалидирует generation и отменяет bootstrap
  GET через AbortController. Старый результат не меняет user/token/loading и
  не удаляет shared localStorage. login/applySession создают новую generation,
  logout инвалидирует pending load; поздний refreshMe не восстанавливает user.
- Current profile failure по-прежнему закрывает доступ, очищает текущий token и
  cached identity; ошибки login/applySession возвращаются caller. Сетевой отказ
  не выдаёт успешную аутентификацию.
- authService.getMe принимает необязательный AbortSignal; прежние вызовы без
  аргумента совместимы. У login сохранена request/response форма и OTP, а запись
  token выполняет AuthProvider после проверки generation и previous token.
- handleResponse получает Authorization, реально отправленный запросом.
  После await res.json, перед destructive side effects, проверяются текущий
  Core token, совпадение Bearer и отсутствие отмены. Исправлены все семь callers:
  GET, POST, PATCH, PUT, DELETE, upload fetch и upload XHR. Для anonymous/stale/
  canceled401 не удаляется новая сессия и не ставится её expiry redirect/toast;
  исходный ApiError401 всё равно возвращается caller. Действующий401 сохраняет
  logout, toast и redirect. Binary helpers, не использующие handleResponse,
  сохраняют прежнее поведение без новых side effects.

Новых token stores, передачи Core Bearer/OAuth code в сторонние хранилища,
caller-defined policy callbacks или ослабления server ACL здесь нет.
Captured Authorization существует только как metadata уже отправленного запроса.

## Evidence

| Проверка | Результат |
|---|---|
| Initial actual React baseline `4bcce27b`, 7 probes | 2 PASS, 5 FAIL, 0 SKIP |
| Intermediate AuthContext-only, те же 7 probes | 6 PASS, 1 FAIL (A401→B) |
| Expanded immutable baseline, 11 probes | 2 PASS, 9 FAIL, 0 SKIP |
| Final immutable baseline всех трёх modules, 15 probes | 4 PASS, 11 FAIL, 0 SKIP, 13.954s |
| Delayed login до переноса persistence, 2 targeted probes | 0 PASS, 2 FAIL |
| Final actual React, 15 probes | 15 PASS, 0 FAIL, 0 SKIP, 13.678s |
| Transport/redirect immutable baseline `4bcce27b` | 7 PASS, 10 FAIL, 0 SKIP |
| Final transport/redirect | 17 PASS, 0 FAIL, 0 SKIP |
| Полный npm run test:unit на final source | 306 PASS, 0 FAIL, 0 SKIP, 6.735s |
| Initial npm run typecheck | PASS |
| Final npm run typecheck после login-persistence fix | PASS, exit0 |
| Full HTTPS Swagger 12 operations / external consent | SKIP здесь, root repeat после интеграции |
| Production / VM / SQL / deployment | SKIP, вне задачи |

React final scenarios: unmount network rejection и late401; StrictMode canceled
old effect и live retry; A→B failure/success/401; current401; current network
failure; stale finally при ещё pending B; failed applySession B не оставляет
cached A; logout инвалидирует refreshMe; late login не заменяет B и не оживляет
logout; обычный login и 2FA challenge/success.

Transport probes удерживают JSON body и заменяют token во время await для всех
fetch методов. Есть отдельные anonymous401, abort во время чтения body и XHR
old/current401 controls. Ошибки старых запросов проверяются как ApiError401,
а не подменяются успешным ответом.

Browser plugin not available; использован установленный Playwright Chromium.
Проверены title/непустой rendered state, отсутствие Vite overlay и uncaught
React/page errors, реальные DOM/user/token/loading transitions. Network abort
и HTTP401 в негативных сценариях намеренны. Viewport1100×700; визуальный дизайн,
mobile и внешние provider/server интеграции этим тестом не принимаются.
Screenshots: `.artifacts/auth-context-lifecycle/candidate/new-session-preserved.png`
и `current401-logged-out.png` внутри того же каталога.

## Повтор и артефакты

Из `clearledger`, с существующими project dependencies, без backend/БД:

```sh
node --test e2e/auth-context-lifecycle.check.mjs
AUTH_CONTEXT_BASELINE=4bcce27b node --test e2e/auth-context-lifecycle.check.mjs
node --test --experimental-strip-types src/lib/apiSessionRedirect.test.ts
CONSENT_API_BASELINE=4bcce27b node --test --experimental-strip-types src/lib/apiSessionRedirect.test.ts
npm run test:unit
npm run typecheck
```

Baseline loader читает immutable provider, apiClient и authService через git show,
не меняя рабочие файлы. Vite использует configFile:false/envFile:false,
случайный loopback port и synthetic `/synthetic-api`; SQL и реальные backend
endpoint не используются. Browser contexts/server закрываются после теста.

Логи в `.artifacts/`: `auth-context-baseline.log`,
`auth-context-intermediate.log`, `auth-context-full-baseline.log`,
`auth-context-full-baseline-final.log`, `auth-context-login-intermediate.log`,
`auth-context-final.log`, `auth-transport-baseline.log`,
`auth-transport-final.log`, `auth-context-all-unit.log`,
`auth-context-all-unit-final.log`, `auth-context-typecheck.log`, `auth-context-typecheck-final.log`.

Root owns full browser acceptance, перенос в integration/sandbox frontend и
повтор реального согласия. Этот отчёт подтверждает actual React lifecycle race
и её управляемые регрессии; он не утверждает, что HTTPS Swagger/server flow
уже принят на новой сборке.
