# M17: уведомления о частичном результате загрузки, 30.10.2026

## Состав и основание

Интеграционная база: `a9be3e638b120dee9324182b34d9b10aa5970a4a`.
Фактический immutable HEAD выделенного worktree перед правкой:
`e0c3070295b325525a19e3dc357ca860738e3328`, согласован координатором.
Между ними добавлены только документы M05-B; исходный
`src/pages/ChannelDetailPage.tsx` побайтово совпадает, Git blob обеих версий:
`960cf9a72551aa7df581cef9f6b9bd9fdcdca643`.
Изменены только этот TSX и настоящий отчёт; документы M05-B не менялись.

## Trigger и результат

Фоновая обработка ручной таблицы либо API-синхронизация канала возвращает
`running=false`, `status=partial`. До исправления обе ветки проверяли только
`error`, после чего показывали `toast.success`, сообщая о полном успехе.
Статус уже описан в `ChannelRun` (`src/services/channelService.ts:369`),
а `RUN_STATUS_META.partial` в этой странице имеет подпись «Частично».

Две actual consumer ветки теперь отдельно вызывают существующий `toast.warning`:

| Source anchor после правки | При непустом `message` | При пустом `message`, `loaded=12` |
|---|---|---|
| [ManualTableCard.uploadAndRun](../../src/pages/ChannelDetailPage.tsx#L449) | «Обработано частично: » + сообщение сервера | «Обработано частично: Загружено 12» |
| [ChannelDetailPage.handleSync](../../src/pages/ChannelDetailPage.tsx#L2246) | «Загрузка завершена частично: » + сообщение сервера | «Загрузка завершена частично: Загружено 12» |

При отсутствии `loaded` fallback использует 0, без новых полей результата.
Сообщение сервера сохраняется целиком после явного обозначения частичности.
Промежуточный success «Таблица загружена (L1)» относится к доставке файла и
сохранён: он не является итогом фоновой обработки.

## Проверки

Команды выполнены из `clearledger/` на изменённом исходнике.

| Проверка | Результат |
|---|---|
| `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json` | PASS, exit 0 |
| `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.node.json` | PASS, exit 0 |
| `node node_modules/eslint/bin/eslint.js src/pages/ChannelDetailPage.tsx` | FAIL, exit 1: прежние 7 errors и 3 warnings |
| ESLint `lintText` исходника из immutable HEAD и кандидата | PASS: одинаковые rule/severity/message/column всех замечаний с учётом сдвига строк; новых замечаний 0 |
| Source review двух веток и `git diff --check` | PASS; runtime diff — две добавленные строки |
| Browser / HTTP E2E | SKIP, не выполнялись; проверка типов не заменяет эти проверки |

Прежние ESLint errors: `react-hooks/preserve-manual-memoization` и шесть
`@typescript-eslint/no-explicit-any`; warnings: две зависимости hooks и
неиспользуемая eslint-disable директива. Они вне двух изменённых веток.

Использовано существующее окружение зависимостей интеграционной рабочей копии
через локальные symlinks, с отдельным `node_modules/.tmp` для cache.
Версии всех прямых dependencies/devDependencies сверены с текущим lock:
missing=0, mismatches=0. Package/lock и версии пакетов не менялись.

## Границы проверки

Source review подтвердил сохранение error/success текстов, прежних счётчиков,
running polling, progress, refresh, return/finally и cache invalidation.
Другие статусы и localStorage pipeline не менялись; stale polling не расширялся.
Новая backend reconciliation форма, счётчики, abstraction и unit-тесты,
повторяющие простое ветвление, не добавлялись. Layout и оформление сохранены.
Реальные env, auth, API, SSH, SQL, merge и deploy не использовались;
приёмка на рабочем пространстве и полный CI этим отчётом не подтверждаются.


## Независимая проверка координатора

Исходник5d6a56ce1557c00bde3082af7c866899059caa71 перенесён какcefd8797.
Координатор повторил TypeScript app и node с собственными incremental caches:
оба EXIT0, диагностик нет. ESLint.lintText на source e0c30702 и кандидате с
одинаковым filePath подтвердил те же7errors/3warnings; совпали rule, severity,
message и column/endColumn с учётом сдвига строк. Сам ESLint остаётся FAIL
из-за прежних замечаний, ноль новых диагностик не называется общим lint PASS.
Runtime diff проверен: только два else-if для partial→warning; прежние error,
success, polling и cache calls не изменены. Browser/HTTP E2E не проводился.
Локальные evidence: `.artifacts/root-channel-partial-app.log`,
`root-channel-partial-node.log`, `root-channel-partial-eslint.json`.
