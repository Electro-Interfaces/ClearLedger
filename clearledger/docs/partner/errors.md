# Ошибки, повторы и диагностика

[Начало](onboarding.md) · [Вход](auth.md) · [Словарь](data-dictionary.md) ·
[Каталоги](recipes/read-catalogs.md) · [Договоры](recipes/contracts.md) ·
[Мониторинг](recipes/monitoring.md) · [Документы](recipes/documents.md)

Candidate/default-off; source pin
`9eb236a4d69f0452208857ac603fd1da515f52d8`. Текущие операции и профили — в
[единой таблице](../PARTNER_QUICKSTART.md#current-source-contract-20261101). Все примеры fictional;
HTTP/schema/runtime **NOTRUN**. Статический контракт приложения не подтверждает
поведение будущего ingress или запущенного пространства.

## Сначала status и media type

Успешный product JSON — `application/json`; ожидаемый файл —
`application/octet-stream`. Не разбирайте HTML proxy error как DTO и не считайте
любой 200 JSON-ответом. Product error до начала body stream использует
`application/problem+json`; `type`, `title`, `status`, `code`, `requestId`, `detail`
входят в полный Problem. Приложение добавляет `Cache-Control: no-store` и
`X-Request-Id`; у Problem header ID совпадает с body. Например:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
WWW-Authenticate: Bearer realm="product-api"
```

```json
{
  "type": "about:blank",
  "title": "Forbidden",
  "status": 403,
  "code": "access_denied",
  "requestId": "80000000-0000-4000-8000-000000000001",
  "detail": "Access is denied"
}
```

Классифицируйте по status/code, не по свободному `detail`. Параметры Bearer
challenge не выводите из общей ошибки: 401/403 имеют challenge, но `invalid_token`
или `insufficient_scope` не гарантированы при generic denial. Scope не расширяется
повтором запроса, а 404 скрывает отличие отсутствующей записи от недоступной.

| HTTP / code | Значение и следующий шаг |
|---|---|
| 400 `invalid_cursor` | Начать явный новый обход без cursor с согласованными фильтрами; не считать ошибку концом списка |
| 401 `invalid_credentials` | Проверить тип токена; один управляемый refresh/новый вход, затем остановить цикл |
| 403 `access_denied` | Сверить все AND scopes, отдельные typed grants, principal и текущие права с владельцем |
| 404 `not_found` | Принять отсутствие доступной карточки/связи/файла; не пытаться различить чужие записи |
| 405 `method_not_allowed` | Сверить метод с Allow: `GET, POST` для коллекции `/api/v1/contracts`, `GET` для остальных известных путей |
| 409 `conflict` | CREATE: тот же creationKey с другим содержимым либо конфликт идентичности; остановить автоматические повторы и сверить намерение |
| 413 `request_too_large` | CREATE body превысил 16384 фактических байта; исправить тело |
| 415 `unsupported_media_type` | CREATE требует application/json (допустим charset=utf-8), Content-Encoding только отсутствует либо identity |
| 422 `invalid_request` | Исправить query/path или строгий CREATE body: даты/ID, диапазоны, лишние поля и дубли JSON-ключей |
| 429 `rate_limited` | Product budget исчерпан; соблюдать Retry-After и ограничить собственную частоту |
| 429 `internal_error` | Возможный generic injected HTTP429; обработать status, не считать отсутствие rate_limited успехом |
| 500 `internal_error` | Ограниченный повтор только безопасного GET, затем поддержка |
| 503 `api_unavailable` | Функция/конфигурация недоступна; ограниченный backoff или владелец, без обхода в legacy |

Ошибки валидируются не обязательно в порядке, ожидаемом клиентом: feature gate,
identity/ACL и budget могут сработать раньше разбора параметров. Один запрос с
несколькими дефектами не доказывает доступность остальных условий.

405 с `Allow: GET, POST` относится к пути коллекции договоров, в metadata обеих
операций `listContracts` и `createContract`. У detail, create-options и всех
остальных известных путей — `Allow: GET`. HEAD и другие методы этим не открываются.
Неизвестный путь даёт 404 **без Allow**. Allow не заменяет OAuth или разрешения.
Это профиль product child application до streaming, не обещание поведения ingress.

## Другие boundaries имеют другие envelopes

| Boundary | Что ожидать |
|---|---|
| OAuth token/revoke | `application/json` с `{ "error": "invalid_grant" }` и другими OAuth errors; public form примеры в [auth](auth.md) |
| OAuth UserInfo | OAuth `{error}` для части scope/auth отказов; gate/verifier могут вернуть Partner Problem |
| Core login/admin/consent | Внутренний Core profile: возможен `{detail}` или Partner Problem; product decoder не переносится автоматически |
| Docs session/schema/assets | Возможен `{detail}` или Partner Problem; cookie/CSRF/feature gates отдельные |
| Proxy, TLS, ingress | HTML, другой JSON, разрыв без body; product Problem не гарантирован |
| Binary после headers | Частичный body или stream failure; JSON Problem уже нельзя надёжно подставить |

Выбирайте decoder по boundary и media type; обрабатывайте неизвестную/невалидную
representation как ошибку протокола с ограниченным безопасным diagnostic fragment.
Не сохраняйте полный чувствительный body в журнал. Неполный файл храните отдельно
от завершённого, не открывайте как успешный результат.

## Retry-After и пределы

При исчерпании **включённого product budget** приложение возвращает 429
`rate_limited` с `Retry-After` в целых секундах не меньше 1. Для generic 429/503
этот header **optional**, может содержать delay-seconds или HTTP-date.
Отсутствие header не означает немедленный бесконечный retry.

Пример именно quota branch:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/problem+json
Cache-Control: no-store
X-Request-Id: 80000000-0000-4000-8000-000000000001
Retry-After: 17
```

```json
{
  "type": "about:blank",
  "title": "Too Many Requests",
  "status": 429,
  "code": "rate_limited",
  "requestId": "80000000-0000-4000-8000-000000000001",
  "detail": "Product request budget is exhausted"
}
```

17 здесь вымышленный пример задержки, не согласованная квота. Product budget по
умолчанию выключен; его конфигурационные defaults не являются обещанием партнёру.
Если включён, budget общий для verified company/installation/client: разные токены
и grants того же клиента не дают независимых лимитов. Проверка после live ACL
не заменяет ограничения concurrent requests, bytes или времени скачивания.
OAuth parser/throttle и настройки synthetic клиента относятся к другим слоям.

Фактические RPS, burst, concurrency, максимальный размер файлов, timeout, fairness,
uptime и p95 владелец должен согласовать отдельно. Не заполняйте неизвестные
значения числами из server defaults или transport пилота. SLA эта инструкция
не вводит.

## Рекомендуемый алгоритм клиента

1. Задайте собственные deadline, предел попыток и страниц, byte cap для файла.
   Числа выбирает приложение с владельцем; это клиентская конфигурация.
2. Читайте страницы последовательно, фиксируя filters/pageSize и контекст.
3. Для GET при disconnect/429/500/503 допускайте ограниченный backoff с jitter;
   при Retry-After ждите не меньше указанного срока в пределах общего deadline.
4. 400/403/404/422 не повторяйте автоматически. При 401 допускайте один
   согласованный refresh/вход; при повторном отказе остановитесь.
5. Для файлов проверяйте status/media и закрывайте incomplete результат при
   обрыве. Range/resumable/ETag/checksum не опубликованы, новый GET не является
   гарантированным продолжением прежнего потока.
6. Для POST договора используйте отдельное правило ниже. Не переносите GET retry
   на token exchange, refresh/revoke, uploads или другие команды. Code одноразовый;
   повтор использованного refresh отзывает семейство.

### Неизвестный результат POST договора

Внешний candidate POST `/api/v1/contracts` принимает body `creationKey`;
Idempotency-Key и If-Match этим контрактом не объявлены. Fresh 201 возвращает
`{contractId, replayed: false}`, авторизованный replay 200 — тот же ID с
`replayed: true`, без READ grant или обещания Location. После потери ответа
сохраните исходные тело и ключ. Допустим ограниченный новый запрос с тем же
намерением и текущей авторизацией исходного grant/actor/CREATE-профиля и ссылок;
не создавайте новый ключ из-за timeout. Внутренний автоматический повтор после
неизвестного commit не обещан. 409 возвращается после полной текущей CREATE
авторизации и не раскрывает чужую карточку; отзыв прав запрещает и replay.
`contracts:read` не требуется и не заменяет `contracts:create`/CREATE-профиль.
Подробный [рецепт](recipes/contracts.md#создание-договора) содержит body и ответы.

Options 200 и `selectionVersion` не резервируют ссылки и не подтверждают admission
для POST. После изменения профиля/токена/контекста или expiry cursor возможен
400 `invalid_cursor`; для нового обхода опустите cursor. Timeout/переполнение
closure options даёт общий 503 без частичного DTO; повтор не гарантирует успеха.
Partner events/WS/SSE не опубликованы: автоматическое восстановление change feed
также не определено. Это будущие возможности с отдельными контрактами.

## Что передавать поддержке

Передайте владельцу время с часовым поясом, HTTP method, path без секретного query,
status, media type, server `requestId` (или header ID при отсутствии Problem),
локальную версию клиента и source/schema pin. Request ID — только diagnostic key,
не tenant/resource selector. При отсутствии server ID прямо укажите это.

Не передавайте Authorization, cookies, secrets, access/refresh/ID tokens,
authorization code, callback query, state/nonce/verifier, полный документ или
полный business response. В рецептах один вымышленный request ID повторён для
читаемости; настоящий сервис генерирует его для каждого запроса.

## Свидетельства исходников

Текущие свидетельства на `9eb236a4d69f0452208857ac603fd1da515f52d8`:

- `clearledger/server/app/product_api/app.py:_problem, http_problem, _describe_http_responses`: codes/headers, 405 по пути, application boundary.
- `clearledger/server/app/product_api/contract_create_body.py:parse_contract_create_body, _check_media`: 413/415/422.
- `clearledger/server/app/product_api/contract_create.py:request_lifetime, create` и `clearledger/server/app/services/partner_contract_commands.py:create_partner_contract`: 201/200, неизвестный commit и 409 после authority.
- `clearledger/server/app/product_api/contract_create_options.py:request_lifetime, decode_cursor, options`: bounded snapshot и invalid cursor.

Исторические свидетельства на `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`:

- `clearledger/server/app/product_api/app.py:51–73,279–354`: Problem, header allowlist и curated metadata.
- `clearledger/server/app/product_api/access.py:98–151` и `clearledger/server/app/product_api/budget.py:38–47,94–116`: порядок identity/ACL/budget, ключ и quota branch.
- `clearledger/server/app/routers/partner_oauth_router.py:33–100,131–185`: OAuth error/form/throttle.
- `clearledger/server/app/routers/docs_portal_router.py:15–44`: docs envelope variants.
- `clearledger/server/app/product_api/files.py:71–84`: streaming response, без общего resume/checksum контракта.
