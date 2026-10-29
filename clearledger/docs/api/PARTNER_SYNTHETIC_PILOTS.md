# M18: внешние synthetic contract pilots

30.10.2026. Client base: `2ae3635a251f5189e1d6d76bb5ecc81bb8db00df`, ветка
`agent/api-partner-pilots-20261030`. Код клиента — только
`tools/partner-pilots/clients`, без runtime/server/ORM/test-internal imports.
Server/bootstrap — отдельный root-owned `tools/partner-pilots/sandbox`.

**Synthetic HTTP acceptance этого slice: 3 читающих сценария,
8 machine/owner-control cases + 6 docs cases PASS в двух явно раздельных фазах.**
Pure guards и compile перечислены отдельно от наблюдённых HTTP результатов. Нет реальных партнёров,
production API/данных, VM/трекера, deploy/merge или утверждения о готовности M18.

## Основание клиента

До server fixture прочитаны только PARTNER_QUICKSTART/PARTNER_IDENTITY/
PARTNER_SDK_TYPES и generated wire types. Клиент не использует app, verifier,
ORM, schema helpers или прямой SQL и не подписывает JWT самостоятельно.
Ответы success не подставляются. Типы Object/Contract/Monitoring/DocumentDetail
импортируются из публичного `src/generated/partner-api.d.ts` как type-only.

HTTP — стандартный [Node HTTPS request](https://nodejs.org/api/https.html#httpsrequestoptions-callback)
с assigned CA, `rejectUnauthorized: true`, hostname validation, ограничением
времени/размера и без автоматического follow redirects. OAuth/OIDC выполняет
зрелый **openid-client 6.8.3 (MIT)**: discovery, ClientSecretBasic/None,
client credentials, PKCE S256, state/nonce, ID token signature через JWKS,
UserInfo subject check и revocation. Используются
[официальный Authorization Code Grant](https://github.com/panva/openid-client/blob/main/docs/functions/authorizationCodeGrant.md),
[clientCredentialsGrant](https://github.com/panva/openid-client/blob/main/docs/functions/clientCredentialsGrant.md)
и [customFetch](https://github.com/panva/openid-client/blob/main/docs/variables/customFetch.md).

Зависимости изолированы в client package/lock: openid-client 6.8.3,
TypeScript 5.9.3, @types/node 22.19.0. Установка не меняет application/M12 locks
или shared node_modules. Integrity SDK закреплена в lock:
`sha512-AoY/NaN9esS3+xvHInFSK0g3skSfeE0uqQAKRj4rB6/GsBIvzwTUaYo9+HcqpKIaP0dP85p5W07hayKgS4GAeA==`.
Это отдельные внешние test applications, не второй Core transport/token store
и не перевод Core UI на partner OAuth.

## Admission и конфиденциальность

- Перед любой provider сетью обязательны RUN_PARTNER_PILOTS=1, явный private
  manifest и PARTNER_PILOTS_ORIGIN, совпадающий с выданным origin в manifest.
  Нет default URL. Принимается только exact loopback HTTPS; origin path/query/
  fragment/userinfo/canonicalization shortcuts и cross-origin requests запрещены.
- Разрешены product GET, discovery/JWKS/UserInfo, POST token/revoke. Business
  POST/PATCH/PUT/DELETE, Core admin/login/references и legacy files не разрешены.
  Authority не извлекается из query/body, companyId spoof проверяется как отказ.
- SDK customFetch использует только этот transport. TLS bypass, remote resolver,
  произвольные browser origins и широкое доверие proxy не добавлены.
- Core пароль/bearer, OAuth signing key и операторские account credentials
  клиент не получает. Machine secret читается только из private client manifest;
  access/ID tokens и verifier остаются в памяти. Нет refresh/token persistence.
- Authorization URL и callback code проходят через private `.artifacts`
  handoff files 0600; working directory 0700. Они не коммитятся и не печатаются.
  После exchange handoff files удаляются. Ошибки сохраняют только allowlisted code/errorName/causeName/phase.
  Logs содержат case/status/requestId,
  но не Authorization/body/code/state/verifier/secret/token или URL query.

## Три сценария и требуемые negative controls

| Сценарий | Наблюдённые реальные запросы | Проверки |
|---|---|---|
| Аренда/энергоснабжение, machine | Objects/counterparties/contracts list+detail, client_credentials по approved grant | Exact scoped rows/total, pagination без duplicates, foreign/SET-ungranted 404, companyId query 422, nested party links не шире grant, machine docs 403 |
| Эксплуатация, machine | Objects/equipment, object monitoring | Сохраняется servicePoint/station identity, все разрешённые объекты, чужие/невыданные monitoring 404, current provenance, typed links, сужение installation на следующем вызове |
| Business documents, delegated user | Реальный Browser consent → Code+PKCE+nonce → token, UserInfo, metadata, exact version bytes | Foreign/ungranted docs, native file deny, binary SHA256, ID token как API bearer 401, удаление membership закрывает следующий вызов |

Delegated subject по решению root — **synthetic company-owner/admin,
is_superadmin=false**. Это не ordinary employee business-docs pilot. Обычный
employee предназначен для отрицательного docs/consent control на стороне root;
не следует приписывать его успешному delegated сценарию. `docs:read`/portal
cookie не используются для business files; scopes — openid, documents:read,
documents.files:download.

Vectors следуют фактической policy: для SET нужны ≥2 allowed, foreign и own
ungranted ID; ALL сам не создаёт own ungranted, но effective location/kind/ACL
ceiling может скрывать собственный ресурс. Такой отказ берётся только из
explicit root vector, не выводится из HTTP response/company inventory.
Foreign company проверяется в обоих режимах. PageSize=1 проходит несколько страниц, затем
pageSize=200 возвращает тот же полный набор/total. Cursor остаётся opaque.
ID не нормализуются и не разбираются как UUID для объектов; path segment
кодируется encodeURIComponent. Пропуск negative из-за нехватки fixture data
не объявляется PASS.

Owner controls выполняет root через настоящий Core/admin контур, не клиент:
**operations-narrow → rental-grant-revoke → documents-member-revoke**.
Каждый token проверяется на достаточный остаток TTL до/после control, чтобы
отказ из-за expiry не выдавался за доказательство немедленного revoke.
Клиент хранит token в живом процессе и ждёт явного `continue` после root action.
Для самого browser consent дополнительного `continue` нет: после настоящего HTTPS
callback listener SDK немедленно обменивает code; root receipt сохраняется отдельно.
Дополнительно проверяется собственный token revocation endpoint и чужой
client grant/scope escalation. Никаких бизнес-записей клиент не запрашивает.
Методный ledger сам по себе не заменяет server-side DB evidence об отсутствии
business DML; такое подтверждение при наличии прикладывает root отдельно.

## Callback boundary

По root-разрешению reserved HTTPS listener находится на отдельном loopback
host **127.0.0.2**, issuer — на 127.0.0.1. Cookie не изолируется портом, поэтому
старый callback на issuer host закрыт до регистрации; browser request не
санитизируется. Callback отвергает Cookie/Authorization, не принимает Core
credentials и не отражает code/state в body/log. TLS leaf+key выданы root только
для synthetic callback, не для OAuth/Core signing. CA/hostname verified probe
без auth уже дал PASS; это проверка TLS, не product/OAuth acceptance.

Фактический reserved URI этого запуска: `https://127.0.0.2:34639/callback`;
он передан root до регистрации и не используется как fallback fixture URL. Новый запуск получает свой URI через bind0 и exact
регистрацию до authorize. Режим запуска требует RUN_PARTNER_CALLBACK=1.

```sh
# clearledger: только свой client node_modules, Node22.18+.
npm ci --prefix tools/partner-pilots/clients --ignore-scripts --no-audit --no-fund
npm --prefix tools/partner-pilots/clients run typecheck
npm --prefix tools/partner-pilots/clients run test:unit

# Только после root permission: reserve callback, затем root выдаёт leaf/config.
RUN_PARTNER_CALLBACK=1 PARTNER_CALLBACK_HOST=127.0.0.2 \
  npm --prefix tools/partner-pilots/clients run callback

# Origin/manifest задаёт root; не подставлять production URL или чужую fixture.
RUN_PARTNER_PILOTS=1 PARTNER_PILOTS_ORIGIN="$ROOT_ASSIGNED_SANDBOX_ORIGIN" \
PARTNER_PILOTS_MANIFEST="$ROOT_PRIVATE_CLIENT_MANIFEST" \
  npm --prefix tools/partner-pilots/clients run pilot

# Только при документированном разделении фаз/новом browser consent:
RUN_PARTNER_PILOTS=1 PARTNER_PILOTS_ORIGIN="$ROOT_ASSIGNED_SANDBOX_ORIGIN" \
PARTNER_PILOTS_MANIFEST="$ROOT_PRIVATE_CLIENT_MANIFEST" \
  npm --prefix tools/partner-pilots/clients run pilot -- --docs-only
```

## Evidence log этого этапа

- Pure local guards/body-adapter regression: **5 PASS**, без сети и fake success responses.
- Client typecheck: PASS; типы взяты из wire artifact, не runtime моделей.
- Callback TLS chain/hostname с assigned CA, без auth: PASS.
- Actual runtime sourceRevision — `71611507`; explicit fixture vector revision —
  `607fc85352429cf9b5e3c2b904efe4c51ae61381`. Sandbox purpose-built actual Core
  M10/admin/docs/product assembly + Postgres + HTTPS, не full production main/nginx.
- Первый rental read/paging/tenant/SET case PASS; дополнительный ALL-equipment
  total остановился на ошибочной client inference ALL=raw company inventory.
  Root дал explicit ALL∩installation.location∩station vector из seed facts;
  этот случай не исправлялся по runtime response и не является server regression.
- Повтор actual SDK процесса: **8 HTTP cases PASS, 70 requests**, включая
  rental/ALL equipment и operations/monitoring, OAuth scope escalation/wrong
  client grant, self token revoke, owner narrowing/revoke. Статусы ledger:
  200×41, 400×4, 401×2, 403×2, 404×15, 422×6; business-write methods — 0.
  После real operations-narrow тем же token: old cursor400, новый subset,
  monitoring прежнего объекта404. После real rental grant revoke: GET401 и
  повторный client_credentials invalid_grant. Expiry не выдавался за revoke.
- Immutable private machine evidence SHA256:
  `42ce18a18241b10697634d955be90cda3dd0091b8cc546967eeda05199d6fa84`.
  Raw original results сохранены отдельно. У старого runner failedCase label
  при отмене docs ожидания остался от последнего успешного owner-revoke case;
  восемь completed results/actual observations сохранены без переписывания.
- Первый pending docs flow: **NOT_COMPLETE**, client transaction истёк, root
  подтвердил отсутствие approve/callback. Причина — отдельная подтверждённая
  Core React session cleanup race, которую исправляет root-owned worker.
  Runtime/client authentication не обходится. Verifier/state были только в
  завершившемся процессе; старый authorization handoff удалён, срок не продлён.
- Исправленная Core UI: `56f7c674a810f5ee0bd33f7919e105051206a931`.
  Реальный owner login → выбор company/scopes → approve → отдельный HTTPS callback
  подтверждён root; callback listener не получал Core Cookie/Authorization.
- Следующий docs-only запуск подтвердил token200/JWKS200 и завершение strict
  SDK ID signature/claims validation, затем остановился **до UserInfo HTTP**:
  ClientError(cause Error), phase=userinfo-subject-validation. Source inspection
  установленного oauth4webapi показал стандартный UserInfo GET `body:null`,
  который наш adapter ошибочно отвергал. Исправлено null→absent, добавлен pure
  regression test. Это client defect; signature/nonce/TLS checks не отключались,
  provider expiry/signature defect не подтверждены. Старые code не переиспользуются.
- Финальный `npm ... run pilot -- --docs-only` запущен после UI_READY с новым
  discovery/verifier/state/nonce и автоматическим deadline 5 минут. Он не
  переигрывает revoked rental grant и сохраняет отдельный results-documents.json;
  две фазы агрегируются прозрачно, не превращаются в один якобы непрерывный run.
- Финальный docs-only с исправленным adapter: **6 cases PASS, 19 requests**,
  статусы 200×12, 401×2, 404×4, 422×1. Наблюдены actual browser callback,
  SDK Code+PKCE/state/nonce, JWKS signature, UserInfo subject match, scoped
  metadata/list/detail, pageSize1/200 без repeats, exact SHA256 version bytes,
  foreign/ungranted/native-file denies и ID token bearer401.
- Последним root подтвердил настоящий Core DELETE owner membership **204**
  (receipt `msg_afd7aab0214b`); без перевыдачи токена следующий docs GET получил
  **401**. Остаток token TTL проверен до/после control. Runner завершён exit0;
  callback listener закрыт exit0. Клиентских процессов/listeners не осталось.
- Immutable private docs evidence SHA256:
  `ae393f3b8c63c0c7d629e50c0d7abd3f0271a12645d10eaf839e8418d4376c0f`.
  Первоначальные adapter-failure evidence сохранены отдельно, не переписаны
  как success. Два final phase ledgers суммарно содержат **89 HTTP requests**
  и **0 business-write methods**; вспомогательные неудавшиеся attempts в эту
  сумму не включены. Wrong-state — local SDK denial до token HTTP.

## Ограничения и повторение

- **Server business-row immutability UNVERIFIED**: root подтвердил отсутствие
  исходного DB fingerprint baseline. Client ledger доказывает только отсутствие
  business POST/PATCH/PUT/DELETE; OAuth/admin controls перечислены отдельно.
  Не заявляется SQL-level отсутствие любых side effects у GET.
- Delegated positive subject — owner/admin, не superadmin. Успешный ordinary
  employee docs pilot и его отдельный consent-denial flow этим клиентом
  не измерены. Profile/email/offline_access/refresh не запрашивались.
- После owner revoke исходная fixture намеренно больше не повторяет весь flow.
  Полный повтор требует **новой root-provisioned synthetic fixture**, новых
  grants/membership и exact callback registration. Клиент не восстанавливает
  permission/state, не запрашивает SQL/admin bypass и не переиспользует code.
- Sandbox не доказывает full production main/nginx, CORS, quotas, load/SLO,
  реальные партнёры или выпуск в РусГидро. Это contract pilots, не факт
  production readiness M18 или завершения всей программы.
- Для актуального состава API root отдельно регенерирует wire artifact;
  этот этап не меняет M12 generator/schema/transport Core и не объявляет
  runtime/spec frozen. Client compile проверен на указанном base artifact.

Все обнаруженные нарушения API/spec/документации сообщаются root по безопасным
method/path/status/requestId примерам. Сервер исправляет root; client не добавляет
обход policy, подменный verifier, TLS disable или legacy fallback.
