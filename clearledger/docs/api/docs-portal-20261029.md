# Защищённая документация API и проверка на синтетическом пространстве

M11, 29.10.2026. Реализован портал, а не публичная копия Core OpenAPI. Флаги
остаются выключены; рабочие пространства, grants, credentials и ВМ не менялись.
Продуктовый контракт остаётся `candidate`, не автоматически `runtime-verified`.

## Состав и wiring

Рабочая линия начинается после `d9285dd4`. Зависимости перенесены без собственных
правок их runtime:

| Канонический SHA | Cherry-pick в этой ветке | Назначение |
|---|---|---|
| `103b5516` | `ac18327f` | Framework access contracts |
| `f609a383` | `d705f1e7` | M10 identity/Authlib |
| `1cbf47ea` | `83356331` | Curated product read API |
| `19941093` | `8bf9c1ac` | Root wiring, config flags, callback policy |
| `d9bc1ca1` | `c8111796` | Issuer validation |

Собственный код M11 — **после `c8111796`**, отдельно от этих зависимостей.
Main/config/root requirements принадлежат координатору. Требуемая регистрация
до startup/create_all:

```python
from app.routers.docs_portal_router import router as docs_portal_router
app.include_router(docs_portal_router, prefix="/api")
```

Импорт роутера регистрирует новую `DocsPortalSession` в существующем metadata.
Существующий root wiring должен предоставить `app.state.product_api`; вызывается
только deferred `app.product_api.curated_openapi(child)`, с точным same-space
`servers`. `main.openapi()` не используется. `policy_registry(child)` должен
быть явно вызван root при mount, поскольку lifespan child сам не запускается.

## Настройка отдельного синтетического пространства

Предусловия: принятый M10, HTTPS issuer пространства, отдельная тестовая БД,
синтетический сотрудник с реальным Core входом и членством. Не выполнять эти
шаги на рабочем пространстве по данному документу.

1. Обычным Core admin API зарегистрировать **public** client (`authMethod=none`),
   без client secret. Указать ровно два redirect URI:
   `https://<space>/developer/api/callback` и
   `https://<space>/api/developer/docs/oauth2-redirect`.
2. Разрешить `openid`, `docs:read` и нужные product scopes, например `objects:read`.
   Явно включить client и одобрить installation только синтетической компании;
   задать собственные resource profiles. Наличие docs:read не разрешает business API.
3. Серверные параметры:

   ```text
   PARTNER_OAUTH_ENABLED=true
   PARTNER_API_ENABLED=true
   PARTNER_DOCS_ENABLED=true
   PARTNER_DOCS_CLIENT_ID=<public client id>
   PARTNER_DOCS_ENVIRONMENT=sandbox
   PARTNER_DOCS_SANDBOX_API_URL=https://<same-space>/api/v1
   ```

   Issuer, audience и ключи M10 настраиваются отдельно по PARTNER_IDENTITY.md.
   По умолчанию docs выключены, clientId пуст, environment=`unconfigured`.
   Любой другой host/path API, production или unconfigured оставляют только
   чтение документации с явным setup-required и отключённым выполнением запросов.
4. Открыть `/developer/api`, войти в Core. «Открыть документацию» запускает первый
   Code+PKCE flow (`openid docs:read`); сотрудник выбирает компанию и даёт явное согласие.
5. Только после проверки callback создаётся короткая docs-сессия. В Swagger
   `Authorize` запускает **отдельный** public Code+PKCE flow с выбранными business
   scopes. Выбрать `objects:read`, отдельно подтвердить его, выполнить GET `/objects`.
   Без второго согласия docs cookie и docs bearer не дают product data.

## Границы доступа

`/api/developer/docs/metadata` требует обычный Core bearer. HTML `/ui`, raw
`/openapi.json`, каждый JS/CSS asset, `/session` и Swagger `/oauth2-redirect`
имеют независимую docs-cookie проверку. Core bearer, product-only bearer и
произвольный partner client их не открывают. Все ответы этих путей `no-store`;
UI/callback имеют CSP и `Referrer-Policy: no-referrer`. Query overrides url/spec/
server/config запрещены, внешний validator/CDN отсутствует.

POST `/session` требует проверенный M10 partner bearer с `docs:read`, user grant,
точный configured public client, точный Origin и явный bootstrap header. Сервер
хранит только hash случайной cookie, token jti, expiry и fingerprint публичного
verification profile. JWT не хранится. Cookie Secure, HttpOnly, SameSite=Strict,
path `/api/developer/docs`, срок до 180 секунд и не дольше исходного access token.

Каждый ресурс перечитывает token/family и вызывает **канонический M10 live_grant**:
client/App, installation/CompanyApp, grant, member, account/token_version и сроки.
Ротация issuer/audience/key также закрывает cookie. Политика не скопирована в M11;
cookie не является авторизацией `/api/v1`. Logout с Origin/CSRF очищает cookie и
вызывает существующий M10 revoke для связанного family; native Swagger logout
отзывает отдельно business token и очищает память.

Первый PKCE transaction хранит в sessionStorage только verifier/state/nonce и
его generation/expiry. Запись одноразовая, TTL пять минут; mismatch не погашает
чужую текущую попытку, expiry/replay/ошибка не дают mock success. Access/ID tokens
не пишутся в Core localStorage, sessionStorage или URL. ID token не используется
как браузерная identity: сервер проверяет access JWT и актуальный grant.
Оба PKCE flow используют crypto random/S256. Swagger сохраняет business token
только в памяти, `persistAuthorization=false`; client secret control скрыт,
непустой secret и посторонние URL отвергаются до отправки.

Try it out разрешён только для GET явного same-space sandbox. Перед каждым
запросом дополнительно перечитывается live docs-session/sandbox readiness, так
что переключение уже открытого контура в production блокирует выполнение.

## Публичная сборка и rollout

При отсутствующей/истёкшей `cl_gate` nginx отдаёт public build. В ней есть только
минимальный callback, общий dedicated OAuth transport и существующий AuthProvider;
Swagger bytes/spec/main app не включены. После успешного callback штатный Core
transport ставит gate и выполняется hard navigation на `/developer/api` без query.
Без Core, потерянного state, с replay или истёкшим кодом — только canonical restart
`/login?next=/developer/api`; code/state не восстанавливаются в login URL.

Координатор отдельно разрешил узкие `src/public/main.tsx` и ровно одну строку
`PUBLIC_PAGES` для подлинно публичного `/developer/api/callback`. Защищённый
`/developer/authorize` исключением не стал.

По отдельному расширению ownership в index.html/public.html изменено только
условие font loader: developer api/authorize ветки не инициируют Google Fonts
CSS/preconnect. Существующий системный fallback используется только здесь;
загрузка шрифтов остальных маршрутов не менялась. Проверка отсутствия внешних
запросов выполняется для всего сценария, не только iframe.

Root отдельно ведёт nginx headers/log redaction и frontend Dockerfile. До
выкладки callback должен получать `no-store/no-referrer` **до загрузки SPA**,
а query OAuth code/state не должны попадать в nginx/Uvicorn/rproxy журналы или
client-errors/analytics. Наш callback чистит query при module evaluation; HTML
и ошибки не отражают параметры. Логи реальной edge/TLS инфраструктуры не проверены.

## Воспроизведение

Только локальный Docker `api-modernization-test-20261029`, БД
`api_docs_portal_test`, отдельный upload directory. Guards тестов проверяют
host/port/database до destructive fixtures; identity/product тестовые БД не трогаются.

```bash
cd clearledger/server
TEST_DATABASE_URL=postgresql+asyncpg://clearledger:api_test_only@127.0.0.1:33546/api_docs_portal_test \
UPLOAD_DIR=/tmp/docs-portal-test-upload \
RUN_DOCS_PORTAL_TESTS=1 RUN_DOCS_PORTAL_BROWSER_TESTS=1 \
/srv/projects/api-modernization-test-env-20261029/.venv/bin/python -m pytest \
  tests/test_docs_portal.py tests/test_docs_portal_browser.py -q

cd ..
node --test --experimental-strip-types src/lib/developerDocs.test.ts
npm run test:unit
npm run typecheck
```

`test_docs_portal.py` проверяет настоящий HTTP/SQL M10+portal+curated product:
каждый закрытый ресурс, scope/client separation, cookie flags, все уровни
revocation, expiry/profile rotation, Origin/CSRF/logout, overrides, sandbox/defaultoff.

`test_docs_portal_browser.py` поднимает реальный локальный HTTPS backend и
Playwright Chromium. Используются настоящий собранный public build, реальный
Core login/gate, Code/PKCE/consent/token, cookie, native Swagger Authorize и
product SQL. Обе реальные main/public сборки получаются из index.html/public.html;
AuthProvider, App routing и API ответы не подменяются. Внешняя сеть запрещена; только внешние
email/notify side effects отключены. Runtime mode fixture меняет настоящую
настройку sandbox/production, а не HTTP ответ. Проверяются отсутствие partner
token в Core storage/URL, отсутствие Core bearer в OAuth/product, logout revoke,
потеря gate и invalid Core callback safe restart. Это локальный end-to-end server
прогон, а не проверка реального proxy/ВМ/production.

`developerDocs.test.ts` — **отдельно intercepted unit fixtures**, не end-to-end:
crypto PKCE, одноразовость/expiry/mismatch, StrictMode in-flight deduplication,
generation/late token, storage/transport separation и public/protected routes.
Browser plugin в сессии отсутствовал; использован установленный Playwright.

Результаты финального состава: **21 HTTP/DB + 1 real HTTPS browser = 22 PASS**
(155.13 с), **296 общих unit PASS**, включая **6 intercepted docs-client unit**;
typecheck, точечный ESLint, compileall, JS syntax и diff check — **PASS**.
Две deprecation warnings относятся к установленному uvicorn/websockets, FAIL/SKIP
в финальном целевом backend прогоне нет. Проверка main/public entry включает
настоящие App routing/AuthProvider; тестовый main build не запускает release
version/PWA emitters и не является выпускной сборкой. Визуально проверены desktop
1440×1000 и mobile 390×844, Impeccable detector: `[]`; по запрету делегирования
проверка выполнена в этой сессии. Скриншоты/логи остались в pytest temp, не в Git.

## Assets и ограничения

Официальный dependency-free `swagger-ui-dist` **5.34.0** сохранён локально с
LICENSE/NOTICE/third-party notices. NPM integrity и SHA256 лежат в
`server/app/docs_portal_assets/manifest.json`; сервер проверяет bytes JS/CSS.
Node/Python root dependencies и lock не менялись. Python swagger-ui-bundle не
нужен: его доступная версия содержит Swagger 4, тогда как curated API — OpenAPI 3.1.
Образ backend уже копирует `app/`, дополнительные CDN/build downloads не требуются.

Использованы официальные [Swagger distribution docs](https://swagger.io/docs/open-source-tools/swagger-ui/usage/installation/),
[OAuth configuration](https://swagger.io/docs/open-source-tools/swagger-ui/usage/oauth2/)
и [plugin API](https://swagger.io/docs/open-source-tools/swagger-ui/customization/plugin-api/).
Internal auth wrapActions закреплены точной версией; при обновлении обязателен
настоящий browser PKCE/Authorize/Try it out прогон.

Реальный внешний партнёр, производственные grants/credentials, proxy logs,
несколько backend workers/нагрузка и независимая приёмка здесь не проверялись.
Flags не включались на стендах, PR и выпуск не выполнялись. Результат локальных
проверок не объявляет всю M10/M11 программу или candidate API принятыми.


## Интеграция координатора

Роутер зарегистрирован в основном Core до startup/create_all. Тесты переведены
на общий portable safety guard: HTTP требует `RUN_DOCS_PORTAL_TESTS=1`, реальный
browser дополнительно `RUN_DOCS_PORTAL_BROWSER_TESTS=1`; обязательны явная
локальная либо CI test DB и абсолютный test upload directory. Фиксированное
имя локальной базы больше не скрывает проверки в CI. Browser выполняется
отдельным job с Node/Playwright, а общий backend job проверяет HTTP/SQL.
Workflow остаётся `disabled_manually`; изменения конфигурации не означают
подтверждённый удалённый CI. Независимый повторный integration прогон ещё идёт.
