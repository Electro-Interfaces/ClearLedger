# Vite: точечное обновление до 7.3.7, 30.10.2026

В отдельной ветке `agent/api-vite-patch-20261030` подготовлено обновление
`clearledger` с locked Vite 7.3.6 до **ровно 7.3.7**. Основа — заданный commit
`eb5cdc513275e428e004f134e6b16d417d6f135e`. Это сопровождение одной зависимости;
эксплуатируемость конкретного развёртывания не устанавливалась.

## Основание и минимальный diff

[Официальный выпуск 7.3.7](https://github.com/vitejs/vite/releases/tag/v7.3.7)
и пять advisory первичных репозиториев указывают 7.3.7 как исправленную ветку 7.x:

- [GHSA-9jrq-w75r-8gcw](https://github.com/vitejs/vite/security/advisories/GHSA-9jrq-w75r-8gcw).
- [GHSA-rq7h-c2jc-7f22](https://github.com/vitejs/vite/security/advisories/GHSA-rq7h-c2jc-7f22).
- [GHSA-r825-w8mm-5pxw](https://github.com/vitejs/launch-editor/security/advisories/GHSA-r825-w8mm-5pxw).
- [GHSA-587h-7wmj-h5pm](https://github.com/vitejs/launch-editor/security/advisories/GHSA-587h-7wmj-h5pm).
- [GHSA-698v-4r3x-3vcv](https://github.com/vitejs/launch-editor/security/advisories/GHSA-698v-4r3x-3vcv).

В `package.json` только `devDependencies.vite`: `^7.3.1` → `7.3.7`.
Точная фиксация удерживает выбранный минимальный патч при будущей регенерации lock.
Версия приложения **1.2.857**, scripts, overrides и остальные декларации сохранены.

`package-lock.json` регенерирован npm с `--package-lock-only --ignore-scripts`:
изменены только корневой pin и `node_modules/vite` — version, resolved, integrity.
Все остальные записи пакетов побайтово эквивалентны по JSON-содержимому исходному
lock, включая зависимости Vite. Registry metadata согласуется с tarball и integrity.
Массового обновления, audit fix, изменения overrides или глобальных npm-конфигов нет.

## Изоляция и доказательства

До установки проверена ссылка `clearledger/node_modules` на общий каталог
`/srv/projects/ledger-app/clearledger/node_modules`. Удалена только эта ссылка;
свежий собственный каталог установлен через `npm ci --ignore-scripts` с частным
npm cache и пустыми user/global config. Install hooks не запускались.

В рабочем дереве сохранены исходные service/caller, оба Vite config и существующие
regression fixtures. Их соответствие основе закреплено приватными SHA-256.
Browser plugin отсутствует; использован существующий Playwright/Chromium.
Проверяемый поток: настоящая панель аудитора → смена org/company/session во время
SSE/upload/dictation → чистый новый разговор без поздних callbacks старого.
Сервер только на loopback со случайным портом, внешние запросы браузера блокируются;
React, провайдеры, Vite SSR и сервис настоящие, HTTP/media границы синтетические.

| Проверка после обновления | Результат |
|---|---|
| Свежая установка из lock без scripts | PASS |
| `npm ls vite --all` | PASS: единственный Vite 7.3.7, плагины используют его |
| TypeScript `tsconfig.node.json`, настоящие зависимости | PASS |
| SSE actual-service SSR | 66 сценариев PASS |
| Export actual-service SSR | 37 сценариев PASS |
| JSON session generation SSR | 86 сценариев PASS |
| React/Chromium lifecycle | 5 сценариев PASS |
| Main production build, исходный config | PASS; 62,369 с с контроллером |
| Public production build, исходный config | PASS; 9,435 с с контроллером |
| Итоговые HTML/assets/import.meta.env | PASS; 7 ссылок на существующие assets, synthetic API |

Node runner включает родительские tests: SSR 192 PASS / 0 FAIL,
browser 6 PASS / 0 FAIL. Во всех пяти browser-сценариях проверены title/origin,
непустая панель, отсутствие console/page errors, внешних запросов и Vite overlay;
сохранены screenshots desktop 1100×850. Полный набор из 774 tests не повторялся:
изменение ограничено Vite и покрыто targeted SSR/browser controls.

Обе production-сборки выполнены локально как проверка совместимости зависимости,
по отдельному разрешению ROOT. Приватный wrapper вызывает настоящий
`build({root, configFile: исходный config, envFile:false, envDir: пустой private каталог})`.
Исходные плагины сохранены. Окружение процесса очищено до whitelist;
`VITE_API_URL=http://127.0.0.1:9`, `VITE_ECOSYSTEM_BRAND=Synthetic`, `VITE_BASE_PATH=/`.
Использован только свой ignored `clearledger/dist`, затем `dist/p`, без symlink.
Сборка не запускает devserver/proxy или запросы API.

Проверены итоговая версия, synthetic brand и scope/start_url main manifest,
ссылки JS/CSS обоих HTML, отсутствие необработанного `import.meta.env` в public JS
и наличие синтетического API URL. Публичный HTML сохраняет три PWA placeholders
из неизменённого `public.html`: исходный public config не содержит main-плагин
`pwaFiles`. Проверено равенство этих токенов шаблону. Это ограничение исходного
конфига по статическим данным; отдельная baseline-сборка Vite 7.3.6 не выполнялась.
Правка исходного шаблона/конфига в данный патч не входит. Предупреждение main
сборки о размере чанков не блокирует сборку.

Ограничения: перед install свободно не менее 20 GiB, резерв не менее 16 GiB,
дополнительный диск не более 4 GiB, каждая install/download/build-команда не более
300 с, логи не более 16 MiB. Выполненные итоговые проверки прошли в этих границах;
итоговый собственный объём менее 0,8 GiB, свободно более 19 GiB.
Общие node_modules/cache, глобальные процессы и конфиги не менялись.

## Приватные артефакты и пределы

Оснастка, исходные выводы команд, metadata, tree, TAP и результаты ограничений —
в ignored `clearledger/.tmp/vite-patch-20261030/`; screenshots существующего browser
runner — в ignored `.artifacts/auditor-sse-context/caller-final/` этого worktree.
`source-pins.json`, `lock-diff.json`, `tool-versions.json` и итоговый manifest
содержат детали для воспроизведения и не включены в commit. Точные wrapper, argv,
env names/синтетические значения, build manifests и предыдущие неуспешные
выводы оснастки сохранены там же; исходники приложения для них не менялись.

Оставшиеся **7 совпадений версий** из исходной сводки координатора сохранены:
остальные записи lock и dependency declarations не менялись. Их статус и
применимость здесь повторно не оценивались. Пять исходных Vite version matches
устранены выбором исправленной версии; это не доказательство устранения всех
уязвимостей приложения, закрытия Dependabot alerts или проверки production.

Живые API, секреты, настоящие env-файлы, VM, Docker, SQL, TSupport и выпуск
не затрагивались. Слияние, активация и развёртывание остаются отдельными действиями.
Проверки не покрывают полный App, production, другие браузеры, мобильную вёрстку,
реальный микрофон или серверные побочные эффекты. Эксплойты и editor PoC не запускались.
