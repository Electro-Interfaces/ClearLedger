# M09: machine profile и публичный Swagger, 30.10.2026

Пакет поверх root `a5e1a0ad162605e2d4c04454f1e86088b4643ac7`, отдельная ветка
`agent/api-service-openapi-20261030`; прежняя authfix-ветка и remote сохранены.
Решение и ownership согласованы root сообщениями `msg_7a9116be233c`,
`msg_9543efc38569`, `msg_00e891fb5341`. SQL, actual verifier/issuer/token/grant,
policies, AuthContext/apiClient, main mount, ORM, feature flags, realenv и VM
не менялись. Generated types/artifacts/locks остаются за root.

## Фактический gap и контракт

Baseline curated schema имела только ProductOAuth.authorizationCode, хотя
реальная policy принимает SERVICE у9 операций. Три операции документов допускают
только PARTNER. MachineGrant уже требует confidential client_secret_basic,
explicit approved grant_id UUID и непустой scope; live_grant отказывает identity
и document scopes. Это source evidence, новый механизм выдачи token не добавлялся.

Canonical curated schema теперь содержит отдельный oauth2 ProductServiceOAuth
с clientCredentials/tokenUrl. Требования каждой операции получены из фактических
principalKinds/scopes: OR между ProductOAuth/ProductServiceOAuth, полный AND
набора scopes внутри каждой альтернативы. Это семантика
[OpenAPI3.1 Security Requirement](https://spec.openapis.org/oas/v3.1.0.html#security-requirement-object).
Machine flow использует стандартный
[OAuth Flows clientCredentials](https://spec.openapis.org/oas/v3.1.0.html#oauth-flows-object),
а vendor extension x-elsy-token-request явно описывает обязательный custom grant_id,
form POST, nonempty scope и client_secret_basic. grant_id не выдается за стандартный
параметр OAuth или автоматически поддерживаемый SDK parameter.

Token endpoint: `/api/oauth2/token`, Content-Type application/x-www-form-urlencoded,
Authorization HTTP Basic; body grant_type=client_credentials, grant_id UUID,
scope с явно запрошенными business scopes. Body client_id/client_secret вместе
с Basic отвергается существующим router. Ресурсные GET получают Bearer access token;
Basic не добавлен к resource security requirements. Confidential-only соответствует
[RFC6749 §4.4](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4), Basic encoding
описан в [§2.3.1](https://www.rfc-editor.org/rfc/rfc6749.html#section-2.3.1).
Связь grant с client/installation/company и resource scopes продолжает проверять
существующий runtime. Machine профиль не предлагает documents, identity или refresh.
Product child сохраняет12 операций и6 предметных tag groups; OAuth endpoint
не добавлялся к списку product operations.

## Защищённые представления документации

`/api/developer/docs/openapi.server.json` возвращает полный canonical contract
через тот же docs_session, no-overrides и no-store, что остальные docs bytes.
`/openapi.json` возвращает deep-copy public Code+PKCE execution projection:
в securitySchemes только ProductOAuth и только соответствующие user alternatives.
Machine flow остаётся читаемым в description/vendor metadata, а fixed relative
download link ведёт к полному защищённому server contract. Projection маркирована
x-elsy-authentication-projection; она не меняет canonical/cache, paths, DTO/Problem,
tags, runtime registry или runtime policies.

Public Swagger не получает confidential auth widget. Существующее скрытие пустого
Code-flow clientSecret поля сохранено, persistAuthorization=false и PKCE S256
сохранены. Actual glue принимает только ProductOAuth auth state. Interceptor
блокирует client_credentials, Basic и непустой client_secret при обмене code,
grant_id/неожиданные/duplicate token parameters, credentials в query и URL userinfo.
Пустой Swagger placeholder client_secret удаляется до отправки. Schema fetch
снимает Authorization также из Headers instances/нестандартного регистра имени.
Разрешённый business Bearer GET и live docs-session recheck сохранены.
Новых credential stores, secret values в schema/config и передачи Core Bearer
в business transport нет.

## Проверки

| Проверка | Результат |
|---|---|
| Baseline HTTP/schema suite | PASS20, gap машинной схемы тогда не проверялся |
| New offline policy/schema/formal/deep-copy + docs HTTP gate wiring | PASS7 |
| Aggregate HTTP/schema/budget/monitoring/new contracts, final | PASS56, FAIL0, SKIP0 |
| Actual interceptor + pinned Swagger metadata/browser | PASS6, FAIL0, SKIP0 |
| Те же JS проверки с immutable old glue a5e | PASS2, FAIL4, SKIP0 (negative proof) |
| Hermetic exporter vs real-database-module no-connect export | PASS, byte-identical JSON |
| Actual SQL docs-session revocation/expiry/defaultoff/new endpoint | SKIP здесь, source tests расширены для root repeat |
| Actual HTTPS token exchange/M2M/full Swagger flow | SKIP здесь, root integration/repeat |
| Generated types regeneration | SKIP, ownership root |

Python HTTP probes используют настоящие docs handlers/live_session checks с fake
row lookup, crypto setup/live-grant stubs; они доказывают gate wiring, а не реальный
M10/SQL lifecycle. Existing SQL tests расширены новым endpoint для anonymous/Core/
product Bearer denial,10 причин отзыва/expiry, authorized canonical/projection,
no-overrides и disabled503, но не запускались без SQL окна.

JS tests вызывают фактический requestInterceptor/plugin из portal-init.js.
Проверяются code PKCE и очистка empty-secret, M2M/Basic/secret/grant_id/duplicates
deny, query/userinfo deny, Headers Authorization removal и разрешённый business GET.
Для последнего применяется только synthetic in-memory auth state и session-metadata
stub; успешный OAuth/business HTTP response не подделывается.

Browser plugin not available; использован существующий Playwright Chromium.
Настоящие pinned JS/CSS bytes сверены с manifest SHA256. В browser перехватываются
только metadata/schema/asset bytes, HTML рендерится actual router function; OAuth
и business endpoints не возвращают fake success. Pinned UI показал12 операций,
6 групп, один ProductOAuth Code+PKCE modal, отсутствие visible secret input,
fixed canonical download link и настоящий PKCE popup без secret/Bearer в URL.
Все backend/OAuth navigation attempts остановлены context route до сети.
Screenshot: `.artifacts/service-openapi-browser/public-code-only.png`.

Промежуточно: исправлены import syntax error и browser-fixture missing query_params
(6 hook failures); page→context interception исправило пропуск первого popup request.
Broad Python run55PASS/1FAIL выявил старое single-ProductOAuth ожидание monitoring,
обновлённое по согласованию root; финальный повтор56PASS. Runtime monitoring не менялся.
Negative old-glue4FAIL намеренны: прежние guards пропускали extra grant_id/query
credentials/Headers Authorization/неверный auth profile. Ошибки не объявлены production SLO.

## Повтор

Из корня owned worktree, без backend/SQL:

```sh
PYTHONPATH=clearledger/server /srv/projects/api-modernization-test-env-20261029/.venv/bin/python -m unittest tests.test_product_service_openapi tests.test_product_openapi_http_contract tests.test_product_http_profile tests.test_product_budget_unit tests.test_product_monitoring_unit -q
cd clearledger
node --test tests/developer-docs/service-profile.check.mjs
PORTAL_GLUE_BASELINE=a5e1a0ad162605e2d4c04454f1e86088b4643ac7 node --test tests/developer-docs/service-profile.check.mjs
```

Логи `.artifacts/service-openapi-{baseline,current,contract,final-python,browser,glue-baseline}.log`;
exports `.artifacts/service-openapi-{offline,runtime}.json` локальные и не коммитятся.
Формальная OpenAPI validation подтверждает структуру, refs и profile/policy mapping;
это не сертификация полной OAuth/OIDC conformance. Root переносит пакет, регенерирует
artifacts/types и отдельно принимает live SQL/HTTPS. Мобильный layout fix согласован
как следующий отдельный commit и не входит в этот schema пакет.


## Независимая интеграционная проверка

Root перенёс canonical/browser пакет как e1818fae. На общем составе:
56 offline Python checks PASS7.808с;6 actual interceptor/pinned Swagger
checks PASS8.431с;22 реальных HTTP/PostgreSQL docs cases PASS61.76с, включая
новый server contract, protected access, expiry/revocation/default-off/override
отказы. Canonical12-operation wire types заново сгенерированы, freshness check
PASS. После отдельной responsive правки086eb928 полный настоящий HTTPS Swagger
(main/public/CodePKCE/SQL/Try/logout/revoke) PASS110.21с. Это не production
conformance/нагрузка и не permission на merge или выпуск.
