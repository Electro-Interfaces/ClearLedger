# Транзитивные npm-зависимости: точечное обновление, 30.10.2026

Подготовлен минимальный lock-патч в ветке
`agent/api-npm-transitive-patches-20261030` от точного commit
`c78da6b2fe608ff27e15a817a47c6d893a0971e5`.
`package.json` сохранён побайтово: Vite **ровно 7.3.7**, приложение **1.2.857**,
scripts, прямые runtime/dev dependencies и прежний override uuid не менялись.
В commit входят только lock и этот отчёт.

## Целевые версии и источники

| Установленная ветка | Исходная версия | Итоговая версия |
|---|---|---|
| source-map-js | 1.2.1 | 1.2.2 |
| brace-expansion, корень | 1.1.18 | 1.1.21 |
| brace-expansion, readdir-glob | 2.1.4 | 2.1.7 |
| brace-expansion, typescript-estree | 5.0.9 | 5.0.12 |
| js-yaml | 4.3.1 | 4.3.2 |
| baseline-browser-mapping | 2.10.0 | 2.11.0 |
| browserslist | 4.28.1 | 4.28.7 |
| @humanfs/node | 0.16.7 | 0.16.8 |

Первичные источники:
[source-map-js 1.2.2](https://github.com/7rulnik/source-map-js/releases/tag/v1.2.2),
[brace-expansion GHSA-q2hr-2g5m-vwhr](https://github.com/juliangruber/brace-expansion/security/advisories/GHSA-q2hr-2g5m-vwhr),
[js-yaml GHSA-2883-xcg3-v3hh](https://github.com/nodeca/js-yaml/security/advisories/GHSA-2883-xcg3-v3hh),
[baseline-browser-mapping 2.11.0](https://github.com/web-platform-dx/baseline-browser-mapping/releases/tag/v2.11.0),
[browserslist GHSA-73wf-gq98-2v4g](https://github.com/browserslist/browserslist/security/advisories/GHSA-73wf-gq98-2v4g).
Версии, dependency ranges, tarball URLs и integrity дополнительно сверены с
публичными npm metadata и фактически установленными package.json.

Важное различие по `@humanfs/node`: входная
[GitHub Reviewed запись](https://github.com/advisories/GHSA-p498-v437-472g)
указывает `<0.16.8` и patched `0.16.8`, но
[upstream advisory](https://github.com/humanwhocodes/humanfs/security/advisories/GHSA-p498-v437-472g)
по-прежнему содержит `Patched versions: None`.
[Официальный выпуск node-v0.16.8](https://github.com/humanwhocodes/humanfs/releases/tag/node-v0.16.8)
и npm подтверждают наличие выбранной версии; release notes говорят о type dependencies.
Это сопровождение версии по reviewed metadata. Доказательства исправления
описанной symlink-уязвимости здесь не получены; расхождение источников остаётся открытым.

## Минимальный npm diff

Npm регенерировал lock в ignored копии manifests с временными подсказками,
ограниченными семьями версий, затем повторно с исходным `package.json` без этих
подсказок. Второй результат побайтово совпадает с первым. Только после этого lock
перенесён в приложение и проверен свежим `npm ci --ignore-scripts`.
Постоянные overrides и новые прямые зависимости не потребовались.

Изменены **13 записей**: 8 целевых и 5 обязательных транзитивных.
Вне этого списка записи lock, включая корень и Vite, сохранены.

| Обязательная дополнительная запись | Было → стало | Причина |
|---|---|---|
| caniuse-lite | 1.0.30001774 → 1.0.30001806 | browserslist требует ^1.0.30001806 |
| node-releases | 2.0.27 → 2.0.51 | browserslist требует ^2.0.51 |
| electron-to-chromium | 1.5.302 → 1.5.393 | browserslist требует ^1.5.393 |
| @humanfs/core | 0.19.1 → 0.19.2 | @humanfs/node требует ^0.19.2 |
| @humanfs/types | отсутствовал → 0.15.0 | node/core требуют ^0.15.0 |

Диапазоны заданы самим upstream в
[npm metadata browserslist 4.28.7](https://registry.npmjs.org/browserslist/4.28.7),
[node 0.16.8](https://registry.npmjs.org/@humanfs%2fnode/0.16.8)
и [core 0.19.2](https://registry.npmjs.org/@humanfs%2fcore/0.19.2).
`update-browserslist-db` 1.2.3 уже удовлетворяет новому диапазону и сохранён.
Изменения dependency fields и engines внутри обновлённых записей соответствуют
официальным metadata. Все целевые версии входят в диапазоны исходных родителей;
семейства brace-expansion 1/2/5 сохранены. Major update, audit fix и массового npm update нет.

## Версионный фильтр и предел его утверждений

Проверены только исходные строки 120, 119, 113, 109, 108, 103, 100 из статического
intake координатора: **7 совпадений до, 0 после**. Диапазоны GitHub с запятыми
нормализованы для npm semver; положительные baseline-совпадения обязательны.

Эти семь строк не составляли полный контракт GHSA-q2hr-2g5m-vwhr: строки brace
описывали `<1.1.21` и `>=4.0.0 <5.0.12`, оставляя установленную ветку 2.x за рамками
выборки. По первичному advisory и дополнительному указанию ROOT добавлен патч
2.1.4 → 2.1.7. Полный affected range advisory:
`<1.1.21 || >=2.0.0 <2.1.7 || >=3.0.0 <3.0.9 || >=4.0.0 <5.0.12`.
По всем установленным в текущем lock версиям brace: **3 совпадения до, 0 после**.
Ветки 3.x/4.x в этом lock отсутствуют. Exploit/PoC не запускались.

## Проверка совместимости

Проверки выполнены один раз после окончательного добавления brace 2.1.7.
До изменения состава была отдельная установка промежуточного варианта; её выводы
сохранены. Предварительный приватный verifier ошибочно передавал GitHub comparator
с запятыми прямо в npm semver и не находил исходное совпадение; исправлена только
нормализация оснастки. Первоначальный неуспешный лог и script сохранены.

| Проверка итогового состава | Результат |
|---|---|
| Свежий npm ci без install hooks, полный npm ls --all | PASS |
| Установленные версии, metadata/integrity, 13 разрешённых записей | PASS |
| TypeScript node-конфига с настоящими зависимостями | PASS |
| Targeted ESLint сервиса, SSE-теста, панели и React fixture | PASS |
| SSE / export / session actual-service SSR | 66 / 37 / 86 сценариев PASS |
| React/Chromium lifecycle | 5 сценариев PASS |
| Main production build, исходный config | PASS; 62,861 с с контроллером |
| Public production build, исходный config | PASS; 9,203 с с контроллером |
| Выходные HTML/assets/import.meta.env/версия | PASS |

SSR runner: 192 PASS / 0 FAIL с родительскими tests; browser runner: 6 PASS / 0 FAIL.
Browser plugin отсутствует; использован существующий Playwright/Chromium,
viewport 1100×850. Поток: настоящая панель аудитора → смена org/company/session
при незавершённом SSE/upload/dictation → чистый новый разговор.
Проверены title/origin, непустая панель, отсутствие console/page errors, Vite overlay
и внешних запросов; screenshots сохранены. HTTP/media синтетические,
React/providers/service/Vite SSR настоящие. Это функциональный fixture, не полный App.
Полный набор из 774 tests и ранее принятые проверки старого состава не повторялись.

Обе production-сборки локальные и разрешены ROOT как проверка совместимости.
Использован настоящий `Vite build` с исходными configs/plugins,
`envFile:false` и свежим пустым private envDir. Whitelist env содержит только
синтетические `VITE_API_URL=http://127.0.0.1:9`, `VITE_ECOSYSTEM_BRAND=Synthetic`,
`VITE_BASE_PATH=/`. Output — свой ignored `dist`, затем `dist/p`;
ссылки в родителях проверены, release workflow не запускался.
Проверены семь ссылок HTML на существующие JS/CSS assets, отсутствие необработанного
`import.meta.env` в public JS, synthetic API URL, версия 1.2.857 и main manifest.
Три исходных PWA placeholders в public HTML по-прежнему совпадают с шаблоном;
у public-конфига нет main-плагина pwaFiles. Это сохранённое ограничение, source/config
в рамках патча не исправлялись. Предупреждение main о размере чанков не блокирует build.

## Изоляция, артефакты и ограничения

Использованы только собственные node_modules и новый private npm cache,
пустые npm user/global config и whitelist env. Общие каталоги и глобальные npm
настройки не менялись. Старый `.tmp/vite-patch-20261030` сохранён;
старые browser captures и dist скопированы в версии внутри нового private каталога
до перезаписи canonical fixture/output.

Новые оснастка, manifests/metadata, exact argv/env, npm tree, TAP, версии,
source pins, budget receipts и hashes находятся в ignored
`clearledger/.tmp/npm-transitive-patches-20261030/` текущего worktree.
`selected-filter.json` содержит семь scoped checks и полный brace-range check;
`lock-diff.json` содержит ровно 13 записей; `source-pins.json` закрепляет неизменённые
service/caller/configs/fixtures; `final-manifest.json` и `build-output-manifest.json`
позволяют сверить доказательства. Raw logs и промежуточные результаты не коммитятся.

Бюджет этапа: свежий свободный диск не менее 19 GiB при входе и перед install,
резерв не менее 16 GiB, приращение не более 2 GiB и полный собственный footprint
не более 2 GiB, каждая команда не более 300 с, логи не более 16 MiB.
Проверки прошли под этими ограничениями; на контрольных точках полный worktree
около 1,1 GiB, приращение около 0,25 GiB. Слоты тяжёлых операций согласованы с ROOT;
после завершения install/build отправлен explicit drained, новых тяжёлых стадий нет.
Приватные receipts фиксируют фактические измерения и команды; глобальная очистка
и изменение лимитов не выполнялись.

Это версия-кандидат с локальным доказательством совместимости. Живые API, env-файлы,
SQL/БД, Docker/ВМ, TSupport, CI, слияние, активация и выпуск не затрагивались.
Утверждение о закрытии всех alerts, всех npm advisories или уязвимостей production
не делается; ROOT отдельно пересчитает исходный metadata snapshot на интегрированном
кандидате. Другие браузеры, мобильная вёрстка, полный App, настоящие микрофон/HTTP
и серверные побочные действия не проверялись.
