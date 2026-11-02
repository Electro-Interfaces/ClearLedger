# Публичные ссылки: фактическая проверка журналов двух nginx

31.10.2026. **Пробел воспроизведён на синтетике; исправление ещё не принято.**

На конфигурации router из Deploy `6708739` и frontend из Core `f44bcdc7` выполнены
25 запросов с вымышленными capability markers. В19наблюдениях marker оказался
в accesslog router, в12 — frontend. Это подтверждение текущего пробела, а не
проверка рабочего РусГидро и не отказ прежнего пакета маскировки трёх APIсемейств.

Сохранённые9групп прежней OAuthпроверки прошли: callback/headers, publicrewrite,
privategate/assets, queryredaction, ordinarydiagnostics и discovery. Процесс6517
завершился с кодом0; три собственных контейнера остановлены и удалены обычными
командами, сеть удалена. Независимый inspect подтвердил отсутствие всех четырёх
ресурсов. Исходники после выполнения совпали; appimports/SQL/liveопераций0.

## Наблюдения

| ID | Шаблон | Cookie | Прямо frontend | Marker router | Marker frontend |
|---|---|---|---|---|---|
| 1 | `/api/doc-share/{token}` | нет | нет | да | нет |
| 2 | `/api/doc-share/verify/{token}` | нет | нет | да | нет |
| 3 | `/api/invite/{token}/ics` | нет | нет | да | нет |
| 4 | `/api/work/calendar/feed/{token}.ics` | нет | нет | да | нет |
| 5 | `/api/auth/reset-password/{token}` | нет | нет | да | нет |
| 6 | `/api/invitations/accept/{token}` | нет | нет | да | нет |
| 7 | `/api/showcase/{token}` | нет | нет | да | нет |
| 8 | `/doc-share/{token}` | нет | нет | да | нет |
| 9 | `/doc-share/{token}` | да | нет | да | да |
| 10 | `/doc-verify/{token}` | нет | нет | да | нет |
| 11 | `/doc-verify/{token}` | да | нет | да | да |
| 12 | `/meeting/{token}` | нет | нет | да | нет |
| 13 | `/meeting/{token}` | да | нет | да | да |
| 14 | `/invite/{token}` | нет | нет | да | нет |
| 15 | `/invite/{token}` | да | нет | да | да |
| 16 | `/reset-password/{token}` | нет | нет | да | нет |
| 17 | `/reset-password/{token}` | да | нет | да | да |
| 18 | `/showcase/{token}` | нет | нет | да | нет |
| 19 | `/showcase/{token}` | да | нет | да | да |
| 20 | `/doc-share/{token}` | нет | да | нет | да |
| 21 | `/doc-verify/{token}` | нет | да | нет | да |
| 22 | `/meeting/{token}` | нет | да | нет | да |
| 23 | `/invite/{token}` | нет | да | нет | да |
| 24 | `/reset-password/{token}` | нет | да | нет | да |
| 25 | `/showcase/{token}` | нет | да | нет | да |

Каждый запрос использовал свой вымышленный marker, поэтому строки разных
вариантов не были склеены по одному токену. Входы API проксировались к явному
синтетическому ответчику;200не доказывает настоящую авторизацию Core. HTML
проверялся в двух режимах gate и напрямую у локального frontend. Без cookie
router переписывает UIпуть в `/p/public.html`: path-token исчезает на втором
nginx, но исходные args сохраняются. Privatequery в этом режиме включён
в следующую матрицу исправления; эти25path-onlyнаблюдений его не проверяют.

## Охват и доказательства

В первые три APIсемейства входят doc-share, invite и calendarfeed. Исходниками
дополнительно подтверждены `/api/auth/reset-password/{token}`,
`/api/invitations/accept/{token}` и `/api/showcase/{token}`. Их маскировка
в центральном logger будет отдельным продолжением, без изменения HTTPправил.
Шесть UIсемейств: doc-share, doc-verify, meeting, invite, reset-password, showcase.
Это разные права и жизненные циклы; маскировка пути не предоставляет доступ.

Перед запуском cached `nginx:alpine` разрешён в образ
`sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3`; использован `--pull=never`. Отдельная запись Image каждого
контейнера в этой baselineсерии не сохранялась; новый приёмочный пакет должен
запускать immutableID и записывать фактические IDs. Никаких installed/live
nginxверсий, TLS/Haproxy/errorlog/debug гарантий этот отчёт не устанавливает.

Изоляция: новая Dockerinternalсеть без опубликованных hostports, три контейнера
с64MiB/.5CPU/pids64каждый, лог1MiBна контейнер. ROOTdiskfloor8GiB и planning96MiB;
это ограничения и план, не измерение peakRAM. Конфиги и синтетическая статика
смонтированы readonly; приложения/PTY/jobs/почта/БД не запускались.

ROOTevidence: `.artifacts/root-ingress-privacy-baseline-20261031/` в интеграционном
Ledgerдереве. Там sourceplan/diff/reproducer, baseline.json, два синтетических
журнала, cleanup.json и независимый acceptance.json.

- baseline.json SHA256 `e1dbfc16a024f37f51ebeba74f311d87814f4160337b45180676fb5a9279842b`;
- acceptance.json SHA256 `07306217a9f9b0e55bcf4713975aa01e441381966c286a990675c0cf4c483896`;
- router source SHA256 `f946e672627bc7942d3d70190805937e7795d11d1eaa556b216db31e8d25fde9`;
- frontend source SHA256 `7210b3e3e6f4bb4c9f600eaa1153e38c4448e215cfa2a4738893ecbbe5e29d9c`.

Первый подготовленный baseline-V1с22случаями не исполнялся: до actual добавлены
три source-confirmedAPIпути, immutable sourcechecks и полный independentcleanup.
Никакого failedruntime либо protectionPASS из этого не выводится.

## Следующий пакет

Deployисполнитель меняет только logging/referrerpolicy router и проверку.
Coreисполнитель затем меняет frontendlogging и дополнительные семейства центрального
logger. Общая матрица должна подтвердить отсутствие markers в обоих журналах,
включая UIprivatequery после rewrite, encodedprefix и malformedinputs, сохранив
старые9OAuthгрупп. Состояние до этого **NOTFIXED**.

Анализ nativeAuditor принят отдельным source-дизайном, его реализация остаётся
в плане. Общая программа20M+11, единый currentCI, внешние пилоты, все владельцы
и deprecation продолжаются; merge/ship/flags/liveданные не менялись.
