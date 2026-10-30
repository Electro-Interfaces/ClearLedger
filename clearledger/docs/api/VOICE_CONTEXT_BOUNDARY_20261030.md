# M12: граница voice-операции при явном reset контекста

Дата: 30.10.2026. База: `f4229831c9e1af39b3a66e13ed8f06f290ffb5f6`,
ветка `agent/api-voice-context-boundary-20261030`. Исследуется отдельный transport
узла `aud=voice`: его node401 не является основанием для Core logout.

## Source trace и исходный checkpoint

Прочитаны [voiceService](../../src/services/voiceService.ts),
[voiceAuth](../../src/lib/voiceAuth.ts),
[cacheReset](../../src/services/cacheReset.ts),
[CompanyContext](../../src/contexts/CompanyContext.tsx) и
[AuthContext](../../src/contexts/AuthContext.tsx).

`AuthContext.logout` вызывает `resetServiceCaches` после выхода из Core.
`CompanyContext.activateContext` сбрасывает те же кэши при изменении userId или
companyId, включая **нового пользователя той же компании**, и затем выполняет
`setServicesCompany`. `main` только задаёт исходную компанию для demo; он не
является дополнительным caller полного reset.

`cacheReset.resetServiceCaches` вызывает `resetVoiceAuth` синхронно. На baseline
тот только инвалидирует voiceAuth cache. Защита поколений в voiceAuth предотвращает
сохранение позднего токена в новом кэше, но намеренно возвращает issued token
уже ожидающему caller. Отдельной границы lifetime/dispatch у операции voiceService
нет. После node401 service инвалидирует company cache и рекурсивно повторяет
запрос один раз; SSE имеет похожую отдельную ветку.

SHA-256 исходников на baseline:

| Файл | SHA-256 |
|---|---|
| voiceService | `989b09cbc7f376f5e8fa056b393dec6de9cff49718dd01330fa55241dba7d6d8` |
| voiceAuth | `8dadcdbc5daf01545c90fd3919258f44d61cea1371684fe3f8510abba9e6fc51` |
| cacheReset | `4df470772027c466b744cb344f927a9c08f5ba8597906f2f147b80beb088ae11` |

## Воспроизводимый baseline actual-service

[Новый тест](../../src/lib/voiceServiceContext.test.ts) загружает реальные
voiceService, voiceAuth, apiClient и cacheReset через Vite SSR. Остальные
reset-функции агрегатора также настоящие. Подменены только synthetic fetch,
storage, часы, toast и таймер Core redirect. Vite использует `envFile:false`,
`configFile:false`, middleware mode; dev issuer отключён явным define.
React providers не монтируются: переход A→B воспроизводит их порядок через смену
Core Bearer, сохранение одной компании, actual `resetServiceCaches` и
`setServicesCompany`. Это проверка service boundary, не браузерная приёмка login.
Каждый child test ограничен восемью секундами, parent — 45 секундами.

Исходный запуск: четыре protocol controls PASS, две race-проверки FAIL
(node:test считает также упавший parent: 4 pass / 3 fail).

| Синтетическая последовательность | Наблюдение baseline |
|---|---|
| Начать PUT с Core A, задержать token issue A, сменить Core на B в той же компании и выполнить actual reset, получить voice B, отпустить issue A | Старое намерение отправляет HTTP PUT с поздним voice A уже после reset; ожидаемый dispatch count 0, фактический 1 |
| Отправить PUT с voice A, задержать node401, сменить Core на B в той же компании и выполнить reset, получить/cache voice B, отпустить node401 | Старый запрос инвалидирует cache B, делает ещё одну выдачу под Core B и повторяет старый PUT с новым voice B; наблюдаемая цепочка node Bearer A→B |

Failure основан на перехваченных HTTP dispatch/credentials, а не на отсутствии
нового symbol или выдуманной ошибки. Это воспроизведение гонки на synthetic
transport, без утверждения о реальной эксплуатации, утечке или server acceptance.

Положительные controls на исходном сервисе:

- Обычный node401 вызывает ровно одну выдачу нового voice token и один retry;
  сохраняются PUT body, If-Match и ответ `{data, etag}`.
- Второй node401 завершает попытку VoiceError, очищает отвергнутый voice token
  для следующего ручного запроса; Core token, toast и redirect не затрагиваются.
- Сохраняются problem JSON/issues, nonJSON error, сообщение 412, специальный
  Health JSON при 503, удаление с 204, multipart fields/filename/bytes.
- SSE после обычного node401 обновляет токен один раз, принимает event-stream,
  разбирает событие и останавливается по возвращённой stop-функции без Core logout.

## Одобренная правка

После воспроизводимого baseline координатор отдельно разрешил runtime ownership
только `voiceService.ts`: итоговый пакет содержит три own files (service/test/report).
voiceAuth, apiClient, auth/cacheReset callers, UI и backend не менялись.

Поколение операции увеличивается только существующим явным `resetVoiceAuth`.
Snapshot сохраняется с начала операции сквозь одноразовый node401 refresh/retry.
Проверки до/после await token и HTTP не дают старому запросу отправиться либо
инвалидировать новый cache; поздняя выдача экспортируемого `voiceToken` и поздние
error paths отвергаются с `AbortError`.

Snapshot сохраняется и при чтении JSON, health JSON, monthly export blob и sound
blob. Проверяется lifetime до возврата результата и создания object URL.
После await helper есть прямые проверки **в вызывающем frame** перед
`забыть(companyId)` и `URL.createObjectURL`: проверки внутри helper недостаточно,
поскольку reset microtask может попасть между helper и внешним await continuation.

SSE хранит один snapshot на lifetime потока. Reset прерывает его AbortController;
проверки после token/HTTP/body read и перед event/onState/reconnect не позволяют
устаревшему потоку продолжать работу. Его reader отменяется и освобождается;
устаревший context завершается quietly. Обычный stop убирает controller из registry.
Normal node401 по-прежнему допускает один refresh; второй отказ не разлогинивает Core.
Event parsing, Accept, problem errors, backoff, body/ETag/form и audience не менялись.
Voice не переносился на общий Core JSON transport.

## Дополнительные controls и измерения

Финальный targeted-набор: 17 child tests, 18/18 с parent. Помимо исходных двух
сценариев проверены reset во время refresh issue, exported token issue и issuer
error; deferred JSON/health/export/audio body; deferred parse rejection; SSE
late401, pending issue и buffered event после reset. Positive controls проверяют
также обычный issuer503, export bytes/filename и audio object URL.

Два отдельных microtask controls воспроизводят await-hop: в промежуточном candidate
`8c4999269c889f92893f05fbf23d8518ec5906c0c1c15d052296c69ae196fca2`
с проверкой только внутри helper наблюдались лишняя выдача B (cache B2→B3) и один
старый object URL вместо нуля. Прямые проверки перед собственными side effects
закрывают обе ситуации; в final tests они проверяют cache B и отсутствие URL.
Это объясняет необходимость проверок в caller frame, без изменений protocol/API.
Этот checkpoint относится к промежуточной правке, а не к двум исходным baseline
гонкам на `f4229831`; они не суммируются в четыре production-уязвимости.

На финальных test bytes replay исходного service из `f4229831` выбирает только
две primary races: обе ожидаемо FAIL по прежним HTTP dispatch/credentials;
node:test: 0 pass, 3 fail с parent, 15 skipped. Наблюдения baseline сохраняются
после добавления остальных controls, а не заменяются missing-symbol проверкой.

| Измерение | SHA-256 |
|---|---|
| Final voiceService | `96c8fe505a147caba962b1c7cb6245173ce15fe2f4a3de0aac74f18f6bcb310d` |
| Final targeted test | `51b492cfed64086336be3d310f14f85bd0a371940cefaf7749f9eec90dcb2421` |

voiceAuth/cacheReset сохранили baseline hashes из первой таблицы. Прежние
voiceAuth cache-generation tests не менялись: они доказывают политику кэша,
а service dispatch boundary проверяется новым actual-service набором отдельно.
Исторический consumer inventory с pin `06e02207` не переписывается после этого
runtime изменения: его manifest остаётся доказательством прежнего source snapshot.

## Проверки и пределы

Из `clearledger`:

```sh
node --test --experimental-strip-types src/lib/voiceServiceContext.test.ts
node --test --experimental-strip-types src/lib/voiceAuth.test.ts src/lib/apiSessionRedirect.test.ts src/lib/apiBinaryTransport.test.ts src/lib/coreExportTransport.test.ts src/lib/intakeDocsTransport.test.ts
VOICE_SERVICE_BASELINE=f4229831 VOICE_CASE_PATTERN='^(reset during token issue|reset before late node401)' node --test --experimental-strip-types src/lib/voiceServiceContext.test.ts
./node_modules/.bin/tsc --noEmit -p tsconfig.app.json
./node_modules/.bin/tsc --noEmit -p tsconfig.node.json
./node_modules/.bin/eslint src/services/voiceService.ts src/lib/voiceServiceContext.test.ts
```

Обычный прогон всегда проверяет рабочий service. На финальных bytes:
targeted **18/18 PASS**, прежние voiceAuth/transport **397/397 PASS**;
app и node TypeScript **PASS**, обе команды завершились с exit 0.
Targeted ESLint: baseline service 0 errors/0 warnings, финальные service/test
0 errors/0 warnings; единственный временный unused parameter нового harness
убран до финального прогона. `git diff --check` проходит.

Private synthetic logs остаются в own `.artifacts/private/voice-boundary-*.log`:
targeted, regressions и directed primary baseline. В публичный отчёт не попадают
реальные credentials, координаты клиента или записи узла.

Граница относится к **явному reset** из существующих callers. Прямая замена Core
token/storage без reset этим изменением не обещается и не тестируется как поддержанный
переход. React login/logout lifecycle не монтировался; сопоставление его reset-цепочки
основано на source trace. Наружные callbacks после уже возвращённого результата
не отзываются. Уже отправленная на сервер мутация не отменяется и не откатывается:
fence блокирует её продолжение/retry после reset, а не совершённый сервером эффект.

Это synthetic transport proof, не production exploit/leak claim и не server
acceptance. Реальные voice/Core/API, SQL, `.env`, SSH, браузер и CI не использовались;
выкатка не выполнялась. Узловой протокол и backend ACL вне этого изменения.
