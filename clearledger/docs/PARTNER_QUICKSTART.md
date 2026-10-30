# Подключение внешнего приложения: кандидат API

M06-R3 добавляет required nullable `typeCode` и `validUntil` в Contract list/detail.
Оба source-valued: код не является глобальным enum, срок хранится строкой до 20
символов без гарантии ISO date; null не означает бессрочность. В `/contracts`
поддерживается точный фильтр `typeCode` (1..256, без NUL, без trim/case folding).
Для кода из доступного договора можно прочитать подпись через
`GET /api/v1/contract-types?typeCode=...` (`getContractTypeMetadata`): нужны
`contracts:read`, typed contract grant и все текущие user/service ограничения.
Скрытый/неиспользуемый в доступных договорах код даёт 404; видимый unknown code
даёт 200 с nullable metadata, inactive сохраняет историческую подпись. Всего 15 GET
(11 user/service + 4 user-only). ROOT принял отдельные new103 и regression84/152
subtests, SDK15 generation/freshness, 6 generator checks и 4 consumers;
[границы и остаток M06](api/CONTRACT_CLASSIFICATION_READ_20261031.md).

Ниже сохранены датированные сведения прежних срезов NEXT-R2/R1/M12.

Текущий NEXT-R2 добавляет `GET /api/v1/contracts/{contractId}/documents`
(`listContractDocuments`): явные subject/graph связи с независимо доступными
документами. Нужны delegated user consent, `contracts:read` **и** `documents:read`,
а также отдельные typed resource grants обоих ресурсов. Machine-профиля нет.
Ответ: `contractId, items[].documentId, total, nextCursor`; query только
`pageSize` (1..200, default 50) и `cursor`. Чтение связи не даёт права на файлы:
для content по-прежнему нужны отдельный download scope, права документа и file policy.
Схема кандидата содержит 14 GET: 10 user/service и четыре user-only.
ROOT принял 60 новых сценариев и отдельный corrective1, regression84 с 142
subtests, official generation/freshness, 6 generator controls и 3 typed consumers.
Это отдельные локальные серии; выпуска и включения не было. Подробности: [NEXT-R2](api/CONTRACT_DOCUMENTS_READ_20261030.md).

Следующие датированные сведения о NEXT-R1 и M12 сохранены как история срезов.

NEXT-R1 добавляет кандидат GET `/api/v1/contracts/{contractId}/objects`
(`listContractObjects`): явные текущие связи договора только с независимо
доступными точками обслуживания. Одновременно нужны `contracts:read` и
`objects:read`, оба самостоятельных resource grants и текущие ограничения
сотрудника. Query принимает только `pageSize/cursor`; company/unassigned не
разворачивается на всю сеть. Кандидат расширяется с 12 до 13 GET (10 user/service,
3 user-docs); статус проверки и ограничения —
[в отчёте NEXT-R1](api/CONTRACT_OBJECTS_READ_20261030.md).

Срез 30.10.2026: код подготовлен в интеграционной ветке, рабочее РусГидро этим
документом не обновляется. OAuth, API и документация по умолчанию выключены.
Адреса `*.example.invalid` и идентификаторы ниже вымышлены. Перед пилотом владелец
пространства выдаёт адрес отдельной песочницы, учётную запись, client ID и явные
разрешения установки. Прямой доступ к БД не нужен.

## Что получает разработчик

- HTTPS origin пространства и audience продуктового API.
- Ссылку `/developer/api` для входа в защищённую документацию. Она требует свою
  учётную запись и `docs:read`; этот scope не разрешает чтение бизнес-документов.
- Зарегистрированный client ID, точные callback URI и согласованный набор scopes.
- Для серверной автоматизации — отдельный confidential client, однократно
  выданный secret и ID явно утверждённого machine grant. В браузер secret не передаётся.
- Разрешённые компанию и ресурсные профили: objects, equipment, counterparties,
  contracts, documents. OAuth scope и перечень ресурсов — разные ограничения.

Партнёрский сервер обращается к API по HTTPS. В текущем шаблоне CORS разрешает
origin самого пространства; произвольный внешний браузерный origin не включён.
Внешний интерфейс может работать через собственный сервер приложения. Отдельная
поддержка прямого browser cross-origin требует своей конфигурации и приёмки.

## Доступ от имени сотрудника

Используется Authorization Code + PKCE S256. Пароль сотрудника вводится на странице
Core; приложение получает одноразовый code, затем отдельный partner access token.
Обычный Core bearer, SSO handoff и ID token для продуктовых методов не подходят.

1. Прочитать `https://<space>/.well-known/openid-configuration`. Проверить точное
   совпадение issuer с выданным origin. Из metadata взять authorize/token/JWKS URL.
2. Создать криптографически случайные verifier, state и nonce. Сохранить короткую
   одноразовую транзакцию; challenge = base64url(SHA256(verifier)), без padding.
3. Направить браузер на authorization endpoint с параметрами:

   ```text
   response_type=code
   client_id=<выданный public client ID>
   redirect_uri=<точный зарегистрированный callback>
   scope=openid objects:read equipment:read
   state=<случайное значение этой попытки>
   nonce=<случайное значение этой попытки>
   code_challenge=<S256 challenge>
   code_challenge_method=S256
   prompt=consent
   ```

4. Сотрудник выбирает компанию и подтверждает действия. На callback проверить
   state, срок и одноразовость до обмена; при отказе показать `access_denied`.
5. Отправить POST token endpoint с `Content-Type: application/x-www-form-urlencoded`:

   ```text
   grant_type=authorization_code
   client_id=<тот же public client ID>
   redirect_uri=<тот же точный callback>
   code=<полученный одноразовый code>
   code_verifier=<исходный verifier>
   ```

6. Использовать `access_token` как Bearer. У public client нет client secret.
   Authorization code/implicit/password flow без PKCE не поддерживаются.

Access token живёт до 300 секунд. Для refresh нужны заранее разрешённый и явно
согласованный `offline_access`; обновление ротирует refresh token. Повтор старого
refresh отзывает семейство, поэтому параллельные refresh одного подключения нужно
сериализовать. Семейство не живёт дольше исходной Core-сессии и семидневного предела.
Проверку state/PKCE и обработку токенов выполнять OAuth-клиентом; access/refresh
не передавать в URL и не писать в диагностические журналы.

## Отдельная серверная автоматизация

Этот доступ действует без User и требует отдельного решения администратора.
POST `/api/oauth2/token`, HTTP Basic authentication confidential client:

```text
grant_type=client_credentials
grant_id=<ID утверждённого machine grant>
scope=objects:read equipment:read
```

В ответе нет refresh и ID token. Machine grant не открывает документы или файлы:
их предметная машинная политика ещё не реализована. Отзыв credential, grant,
installation либо client закрывает следующий API-вызов.

## Первый запрос и обход страниц

```http
GET /api/v1/objects?pageSize=50 HTTP/1.1
Host: sandbox.example.invalid
Authorization: Bearer <partner access token>
Accept: application/json
```

Ответ имеет `items`, `total`, `nextCursor`. `total` относится к доступному
отбору, а не ко всей компании. `pageSize` от 1 до 200, по умолчанию 50. Пока
`nextCursor` не null, следующий запрос повторяет исходный фильтр и передаёт cursor
как непрозрачную строку. Cursor связан с правами/компанией/отбором; после их смены
начать обход сначала. Не раскодировать cursor и не использовать offset.

ID компании передавать в query для расширения доступа нельзя: контекст выбран
при согласии/выдаче токена. Неизвестные query-параметры отклоняются. Даты в
поддерживающих их методах имеют вид `YYYY-MM-DD`; точные поля и ограничения
берутся из актуального OpenAPI, а не из примера соседнего метода.

## Три первых сценария

| Приложение | Начальные действия | Ограничение текущего среза |
|---|---|---|
| Договоры аренды и энергоснабжения | GET `/counterparties`, `/contracts`, карточки по ID; user GET `/documents` и разрешённые версии | Запись и изменение договоров внешним API ещё не реализованы |
| Эксплуатация станций | GET `/objects`, `/equipment`, `/objects/{objectId}/monitoring?days=90` | Мониторинг требует оба `objects:read monitoring:read`, typed object grant и актуальные права; заявки и финансы не входят |
| Документы | User GET `/documents`, `/documents/{docId}`; `versions` содержит разрешённые версии, `versionsTruncated` отмечает ограничение | Для содержимого дополнительно нужен `documents.files:download`; машинное чтение закрыто |

Пути в таблице относительны `/api/v1`. Общий реестр пяти уровней не подменяется
одним объектом: сейчас `/objects` отдаёт servicePoint, `/equipment` — station;
site/EVSE/connector ещё не опубликованы. Исторический `asOf` мониторинга относится
к сессиям, паспорт и статус объекта текущие; это явно отражено в provenance.

## Swagger и ошибки

На `/developer/api` сначала подтвердить доступ к документации. Затем в Swagger
нажать Authorize и отдельно согласовать business scopes. Docs cookie или docs-only
bearer бизнес-методы не открывают. Try it out выполняет только GET явно настроенной
песочницы; вне неё документация доступна для чтения. Raw OpenAPI и JS/CSS защищены
тем же коротким docs grant, публичного generic Core OpenAPI нет.

Product API возвращает Problem Details (`application/problem+json`) с `code`,
`status`, `detail`, `requestId`. Для обращения в поддержку передать requestId,
метод, путь и время запроса без токенов. Token endpoint использует OAuth `error`.

| Ответ | Действие клиента |
|---|---|
| 401 | Токен непригоден либо доступ отозван; обновить по разрешённому flow или начать вход заново |
| 403 | Нет нужного scope/ресурсного профиля; повтор тем же токеном права не добавляет |
| 404 | Объект отсутствует либо недоступен; не отличать по этому ответу чужие записи |
| 422 | Исправить параметры по схеме; неизвестные поля не игнорируются |
| 429 | Соблюсти Retry-After, ограничить собственную частоту запросов |
| 503 | API/конфигурация недоступны; ограниченный retry с backoff, без обхода на legacy endpoint |

Контракт пока имеет статус candidate. Для внешнего запуска нужны отдельная
песочница, актуальная схема после проверки выпуска, пилот по этим шагам и
подтверждённые квоты/наблюдаемость. Этот документ не выдаёт реальные учётные записи
и не означает выполнения трёх внешних пилотов.

Для генерации серверного SDK скачать полный контракт через ту же одобренную
docs session: `/api/developer/docs/openapi.server.json`. В нём отдельно описаны
пользовательский Code+PKCE и confidential client_credentials с обязательным
прикладным `grant_id`. Файл `/api/developer/docs/openapi.json` служит Swagger
в браузере и предлагает только пользовательский Code+PKCE; секрет серверного
приложения в браузер не вводится. Оба текущих представления относятся к одним 14
операциям и тем же политикам доступа.
