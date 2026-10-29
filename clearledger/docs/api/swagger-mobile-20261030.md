# Перенос описаний групп Swagger на узком экране, 30.10.2026

Отдельная правка после M09 schema commit `e59885e7`, по root
`msg_8992cf4c9025`. Основной отчёт: [service-openapi-20261030.md](service-openapi-20261030.md).
Применён Impeccable: context, adapt, craft-floor; режим Read, существующее оформление
сохранено. Меняется только собственный inline CSS в docs router HTML.
Pinned Swagger bundle/CSS bytes, доступ к assets, OAuth и schema не менялись.

На390px заголовок и длинное описание делили одну flex-строку. Измеренная ширина
описания сжималась до60–115px, высота достигала112–144px. При этом scrollWidth390
равнялся clientWidth390: одной проверки отсутствия горизонтального scroll было
недостаточно. На1200px описания имели высоту16px и читались нормально.

При ширине до600px описание теперь занимает отдельную полную строку под
заголовком; управляющая стрелка остаётся у заголовка. Параметры переноса и
естественная высота заменяют сжатие текста; overflow:hidden/обрезание/ellipsis
не добавлялись. Desktop правила не изменяются. Тексты и шрифты сохранены.

| Проверка | Статус |
|---|---|
| Immutable HTML baseline e59885e7, тот же pinned layout390/1200 | 6 PASS, 1 FAIL, 0 SKIP |
| Final pinned metadata/interceptor + layout390/1200 | 7 PASS, 0 FAIL, 0 SKIP, 11.944s |
| clientWidth/scrollWidth на390 | 390/390 |
| clientWidth/scrollWidth на1200 | 1200/1200 |
| Высота описаний390 после правки | 32–48px; раньше64–144px |
| Desktop measured geometry | совпадает с baseline |
| Pinned vendor JS/CSS SHA256 | PASS, соответствуют manifest |
| Реальный телефон/Safari/full HTTPS оболочка | SKIP здесь, root repeat |

Тест проверяет bounding rectangles заголовка, полное непустое описание, читаемую
высоту строк и scrollWidth<=clientWidth. Он не принимает совпадение CSS-класса
за доказательство поведения. Используются actual router HTML и pinned assets;
скриншоты390/1200 просмотрены одной парой. Authorize/PKCE и machine-profile
metadata regression проверки проходят в том же прогоне. Успешный OAuth/token
обмен и реальные backend ответы в этом metadata fixture не подделываются.

Browser plugin not available; Chromium Playwright, эмуляция viewport, не физический
телефон. Impeccable cycle: один batched baseline, одна CSS-правка, один batched
final. Дальнейшая визуальная полировка не выполнялась.

Из `clearledger`:

```sh
SWAGGER_UI_BASELINE=e59885e7 node --test tests/developer-docs/swagger-mobile.check.mjs
node --test tests/developer-docs/swagger-mobile.check.mjs
```

Baseline loader читает старый router через git show без изменения рабочих файлов.
Логи `.artifacts/swagger-mobile-{baseline,final}.log`.
JSON `.artifacts/service-openapi-browser/layout-{baseline,candidate}.json`.
Снимки в том же каталоге: `layout-candidate-390.png`, `layout-candidate-1200.png`
и соответствующие `layout-baseline-*`. Данные синтетические; SQL, VM и env не трогались.


Координатор независимо повторил итоговый pinned UI batch на общем составе:
7PASS за12.219с. Дополнительно полный actual HTTPS Swagger браузер со штатными
main/public сборками и PostgreSQL PASS110.21с. Визуально просмотрены mobile
390px и desktop: описания групп читаются отдельной строкой, горизонтального
переполнения в bounded cases нет. Проверка не распространяется на все экраны
продукта и все устройства. Vendor bytes не менялись.
