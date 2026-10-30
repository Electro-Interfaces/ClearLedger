# M00/M17: сохранение frontend consumers СМР, 31.10.2026

Статус: scoped frontend preservation принят ROOT: TypeScript fullsrc+consumer PASS
и authoritative browser confirmation **15/15 PASS** (14 scenarios + parent).
Весь M00, полная цель M00–M19 и выпуск этим пакетом не закрываются.

## Источник и границы

Ветка `agent/api-live-frontend-preservation-20261031`, база
`e0a1cee2db316e517373ac7157227045365f3c50` (accepted backend preservation191939bb,
R2 API14, chat owner). Происхождение трёх UI deltas:
`722adb0d1bb3589e381483dbed2038dcc974d9db`.
Перенесены только новый `ProjectDismantleStations.tsx` и точные hunks
`ProjectTabs.tsx`/`sitesService.ts`, затем добавлены необходимые guards и состояния.
Весь upstream sitesService не копировался; accepted transports/context/generation,
attachment/download helpers и остальные API функции сохранены.

Три production UI файла, новые tests и этот отчёт составляют весь scope.
Backend семь файлов, models/database/schema, product_api/SDK, календарь/chat,
зависимости/версии, стенд/SSH/ship/deploy, реальные данные, секреты и трекер
не менялись. Backend63/8 не повторяется.

## Поведение

- Паспорт СМР показывает перечень ЭЗС и дату вывода; выбор и дата остаются
  паспортными данными/планом, фактического снятия оборудования не выполняют.
- Селектор читает общий `/api/locations` с company_id и стандартными API headers;
  показывает только доступный ev_charging каталог, loading/empty/error/retry.
  Поиск, draft, Отмена/Применить, клавиатурные checkbox и focus return доступны
  стандартными shadcn/Radix компонентами. Длинные названия переносятся.
- Неизвестные старые IDs не отбрасываются по отсутствию в текущем каталоге;
  показана нейтральная недоступность, удалить связь можно явно. Скрытые/чужие
  данные не восстанавливаются локальным fallback.
- Дата очищается explicit null, список — explicit []; payload не включает
  нетронутые поля. После success штатный onDone перечитывает сохранённый паспорт.
- 422 сохраняет draft и показывает ошибку, success не рисуется. Серверная
  invalid-date atomicity/tenant/object scope ранее приняты ROOT backend-пакетом;
  UI mocks проверяют только отображение ответа, не доказывают сервер заново.
- Keyed project/company editors сбрасывают старый draft/selection сразу.
  Catalog query получает AbortSignal и mount-specific cache key; существующий
  captureApiContextGuard проверяет ответ, selection, save, callbacks и A→B→A /
  новый вход с тем же токеном. Старые success/error/onDone подавляются.
  Отправленный до переключения PATCH может завершиться на сервере своей компании;
  frontend игнорирует его устаревший результат и не переносит его в другой контекст.

## Дизайн и статическая проверка

Impeccable context выполнен один раз из clearledger с target
`src/components/sites/ProjectTabs.tsx`; launcher доступен без загрузок/установок.
Operate/narrow preservation по существующим PRODUCT.md/DESIGN.md;
craft-floor прочитан до UI edit, применены React правила keyed reset, отдельные
module-level компоненты и primitive dependency/query boundaries.
Редизайн, новые цвета, глобальные framework/skills не вводились.
Использованы существующие shadcn Button/Dialog/Checkbox/Alert/Skeleton/Input;
registry CLI/installers не запускались в соответствии с source-only scope.

Единственный detector run после готового UI одновременно сравнил три текущих файла
с e0a1cee2 baseline (для нового файла baseline отсутствует).
Primary: **0 current / 0 baseline**. Advisory: **5 current / 5 baseline**, все прежние
11px в ProjectTabs, не в новом селекторе; новые findings **0**, suppressions нет.
Evidence `.artifacts/live-frontend-preservation-20261031/impeccable-detector.json`.
Существующих screenshot goldens для этой поверхности в репозитории не найдено;
до ROOT review приложение/браузер не запускались, visual truth бралась из
incumbent source и зафиксированных PRODUCT/DESIGN.

`node --check browser.test.mjs` и `git diff --check`: PASS, без выполнения tests/app.
TypeScript, browser, tests, build и installers исполнителем не запускались.

## Frozen proposal ROOT

| Production path | SHA-256 |
|---|---|
| `clearledger/src/components/sites/ProjectDismantleStations.tsx` | `981487f5021104915db00d064841e1b2722396a8dd7074b9cfa630f08e48fd87` |
| `clearledger/src/components/sites/ProjectTabs.tsx` | `5a8eeb493860bb731debf1a0fc99c7ccdf0be73cd85493ccd449aa7d94f96eb6` |
| `clearledger/src/services/sitesService.ts` | `e28cb405ab5545591655f1dd4eedc4198550d016c5b423a7d8ddf0667f40dc71` |

Полный source freeze: 1232 файла frontend src/tests/config/PRODUCT/DESIGN,
`.artifacts/live-frontend-preservation-20261031/source-freeze-v6.json`, SHA-256
`4bf49e257ac4e805bae16c062eb7d5d1a7438b4470a43e8f8a6d3b49e280338a`.
Browser runner SHA-256: `9c8a1889f426916e9691e5a069122eb3f1edb5736fea2a9157faf303aa04c61e`.
Exact argv/env/selection/limits proposal:
`.artifacts/live-frontend-preservation-20261031/acceptance-proposal-v7.json`.

Одна TypeScript проверка объединяет весь src и typed consumer fixture (в том числе
negative assertions string IDs/date|null), без повторного Vite build.
ROOT назначил ранее проверенный tool root
`/home/mag/orca/workspaces/ledger-app/api-conf-context-20261030/clearledger`
и browser cache `/home/mag/.cache/ms-playwright`, без installers;
для TypeScript ROOT временно создаёт собственный ignored node_modules symlink
(до actual отсутствовал) и удаляет его после приёмки;
critical versions сверяются с frozen package-lock (Vite7.3.7/React19.2.4/TS5.9.3),
ROOT дополнительно сверил все531installedlockentries:0mismatches.
Исторический shared Vite7.3.6 не является доказательством target.
Draft v1 имел13сценариев; v2 source freeze/runner добавили14-й late401 и explicit
AbortSignal, v3 proposal уточняет exact tool/cache без изменения source. V4 source-only ограничивает expected console401 только
late401 scenario/exact controlled endpoint; unexpected401 в других случаях
остаётся finding. Все14сценариев/15cases и assertions сохранены; actual ещё не было.
Все drafts сохранены.
Browser plugin not available; предложен existing Playwright fallback.

Synthetic browser fixture рендерит настоящий PassportTab и общие apiClient/sitesService,
заменяя только несвязанный useSupportContext в target module.
Все API перехвачены scoped mock server, внешние запросы запрещены;
profile/tokens синтетические, настоящие авторизации и данные не используются.
14 последовательных сценариев (15 node:test cases с parent): desktop/mobile,
keyboard, payload/reopen, null clears, loading/error/empty/search, hidden/foreign
422, date422, late catalog/selection/save при company/session/A→B→A, late401 после нового токена
без сброса новой сессии/redirect; отмена каталога подтверждается requestfailed/AbortSignal.
Один batched visual round 1440×1000 +390×844/light+dark, максимум один confirm;
перебор вариантов/бесконечная полировка не предусмотрены.

## Live frontend correspondence

Ранее ROOT наблюдал frontend image v844/public version1.2.858; одного номера
версии и presence строк в bundle недостаточно для полной source/runtime
correspondence или семантической приёмки.
ROOT выполнил bounded read-only proof 2026-10-30T21:50:37.828905+00:00:
container `5e67187ff92699f307b8b4c85c6d245f759243b0af9124ad4470fbe7edd7c4cd`,
image `sha256:35897cb0fecd053a433b4a6b980301c030fb129c1cdc6339b03619f7d4006ffe`,
start `2026-10-30T07:10:30.492914667Z` стабильны до/после; 409 files,
15,749,199 bytes; public version1.2.858/build2026-10-30 07:07.
Selected OCI source/revision labels отсутствуют; .map assets и sourceMappingURL
в выбранных index не найдены. В `index-BfMKiPUV.js` присутствует decommissionedOn,
другие выбранные target strings отсутствуют в selected index — это не поиск по
всей семантике и не доказательство отсутствия feature во всех чанках.

Первый cap200 metadata прерван до чтения asset content; ROOT пересогласовал
bounded2000 paths/30MiB manifest и32 selected content. Без Env/keys dumps,
SQL, app imports или working writes. Evidence ROOT:
`.artifacts/full-api-continuation-20261030/rushydro-frontend-runtime-proof.json`, SHA-256
`afff58689d3df608dc52764f1bfdb3dfa8b8189a396bb9913dd702a0d8029a43`.
Полная source/runtime correspondence трёх upstream файлов **не подтверждена**.
Это ограничение не блокирует source preservation/targeted synthetic QA и остаётся
явно открытым для M00; публикация/полная semantic acceptance не заявляются.

## ROOT receipts

V4 TypeScript fullsrc+consumer: **PASS**, exit0/reaped,
161.36596426088363 с, peakGroupRSS2,141,515,776 bytes.

Browser V4: pre-render **FAIL** `EISDIR @tailwindcss/vite generate:serve src/index.css`.
Причина в test harness: blanket package aliases перенаправляли CSS @import
`tailwindcss` в директорию вместо stylesheet exports. Production UI/CSS не дефектовали
по этому наблюдению; функциональных PASS и screenshot QA не заявлялось.
ROOT остановил свой точный manager после положительно подтверждённого повторения,
exit1/reaped/drained58.23046736139804 с; peakGroupRSS2,421,506,048 bytes.
SourceAfter PASS1232; own ignored node_modules symlink удалён по inode.
Evidence ROOT `.artifacts/root-live-frontend-review-20261031/`:
`typescript.log`, `actual-process.json`, `browser.log`, `first-browser-stop.json`.

После положительного drained receipt ROOT разрешил V5 fixture-only исправление:
удалены blanket package aliases и неиспользуемое чтение pkg; сохранён только @ alias,
read-only verified tool tree и стандартные package/CSS exports через временный
owned node_modules symlink ROOT. Production3/CSS/typedconsumer/all14assertions
не менялись. TypeScript PASS сохраняется, повторять его не требуется.
V5 browser-only actual затем выполнен на новых private test paths; его результат ниже, старые proofs сохранены.
Context/detector не повторялись; один confirm допускается только для реальных
functional/UI corrections, не для полировки.


V5 ROOT outer preflight остановился до Node/app/browser child из-за retained
TypeScript V2 paths в fresh browser root-list; это отдельный 0-case operational
receipt ROOT, source не менялся. После исправления outer V5 browser действительно
запущен и завершился: **15 node cases FAIL**,89.693353 с, peakRSS3.78GB,
reaped/drained, sourceAfter PASS, own symlink удалён.
Все14 scenario failures были в общем open locator до функциональных assertions:
heading виден, console=[]/unexpectedRequests=[]; functional PASS не заявляется.
Evidence ROOT `.artifacts/root-live-frontend-review-20261031/browser-retry-v5/`
и `/srv/projects/api-live-frontend-preservation-test-20261031-v5/test-browser/browser-results.json`.

Source-only подтверждена ассоциация native Label htmlFor=passport-dismantleLocationIds
из ProjectTabs и такого же id кнопки селектора: accessible name следует полю
«ЭЗС к демонтажу», а видимый текст остаётся «Выбрать ЭЗС (…)».
Это fixture locator mismatch, не доказанный production accessibility defect.
V6 использует exact getByLabel, дополнительно сохраняет проверки button role и
видимого текста; production/ARIA не менялись. Успешный open сохраняет chooseAria;
при failure — bounded synthetic aria/body/title/url + screenshot и закрытие context.
Batch останавливается на первом actionable failure вместо14 одинаковых ожиданий;
успех требует прежние14сценариев/15cases без SKIP и без ослабления assertions.
TypeScript PASS сохраняется, context/detector не повторялись; V6 actual приведён ниже.


V6 actual: fail-fast остановил первый scenario; **2 Node FAIL /13 не исполнялись**,
outer8.229896 с/Node7.484 с, reaped/drained/sourceAfter PASS/own link removed.
`chooseAria` положительно подтвердил `button "ЭЗС к демонтажу": Выбрать ЭЗС (0)`;
picker, keyboard и selection достигнуты, console=[]/unexpectedRequests=[].
Failure `toBeFocused` был strict2matches у getByLabel: button и closing Dialog
с общим aria-labelledby/title. Focus assertion ещё не оценён; production bug
не заявляется. Evidence ROOT `browser-retry-v6/browser.log`, synthetic
`/srv/projects/api-live-frontend-preservation-test-20261031-v6/test-browser/`
содержит browser-results.json и picker-desktop.png.

V7 fixture-only: choose — exact role=button/name=ЭЗС к демонтажу;
button-role/visible-text/focus assertions сохраняются. Synthetic test navigation
для внешнего context event в открытом dialog явно использует includeHidden лишь
внутри nav «Тестовый контекст» перед programmatic click; настоящая доступность
UI/данных не ослаблялась. Все screenshot captures задают animations:disabled:
ROOT увидел opening fade на V6 PNG, это capture timing, не стиль/production edit.
14сценариев/15cases при успехе, bounded diagnostic/fail-fast и все assertions
сохранены. TypeScript PASS retained, context/detector без повторов; V7 actual/confirmation приведены ниже.


### Authoritative final receipt ROOT

Первый V7 log содержал ok всех14subtests и6PNGs, но outer ROOT поймал
FileNotFound при удалении временного Playwright descendant на teardown до final
parent exit/summary. Это отдельное operational interruption, не app/runner defect
и не final15PASS. Owned descendants drained, sourceAfter PASS1232, own link removed.
ROOT исправил только watcher: исчезнувшие descendants допустимы лишь под неизменным
owned root;5purecontrolsPASS, root/offroot/unknownfilename/PermissionError reject.
Source/runner/proposalV7 не менялись, прошлый incomplete receipt сохранён.

Одна confirmation того же V7 на fresh `...20261031-v7-confirm` завершена:
**Node15/15 PASS**,14functional scenarios+parent,0FAIL/SKIP/cancel;
45.360571372 с Node /45.76427527889609 с outer, peakRSS1.381GB.
ROOT независимо сверил summary14cases, console0/unexpectedRequests0,
sourceAfter PASS1232, own children reaped/drained, temporary node_modules symlink
удалён. TypeScript PASS161.36596426088363 с/peak2.14GB сохранён, без повтора.

Geometry: desktop width/scrollWidth1440/1440, mobile390/390, horizontal overflow нет.
ROOT принял readability/layout стабильных desktop/mobile light/dark picker captures;
6PNGs имеют SHA/dimensions в acceptance-result.json. Это synthetic Chromium
component integration с настоящими PassportTab/apiClient; не полный app route UX,
не физические мобильные устройства/Safari и не live frontend acceptance.

Authoritative evidence ROOT:
`/home/mag/orca/workspaces/ledger-app/api-modernization-integration-20261029/.artifacts/root-live-frontend-review-20261031/`:
`browser-confirm-v7/actual-process.json`, `browser-confirm-v7/browser.log`,
`acceptance-result.json` (SHA-256
`d6c4423f88e5aa26e82ed8ad121f79bfb33a53bc4f3e68a4fb9b9d78a14d3a94`),
`browser-confirm-v7-proposal.json`,
`run-browser-confirm-v7.py`, `outer-watcher-controls.json`.
Actual summary и PNG:
`/srv/projects/api-live-frontend-preservation-test-20261031-v7-confirm/test-browser/`.

После PASS изменён только этот отчёт. Предыдущие fixture failures, ROOT preflight
и watcher interruption сохранены отдельно; не заявляется единый зелёный первый
прогон всех attempts. Backend не повторялся; dependencies/версии/live не менялись.
**Весь M00/source correspondence/full CI/release остаются неподтверждёнными.**
