# M14: время попытки исходящего Core event

> Разделы до «Отдельный пакет: обязательная подпись URL webhook» сохраняют отчёт
> timestamp-пакета `c8b99684`. Актуальное закрытие его signing GAP описано в
> добавленном разделе ниже; исходный отчёт остаётся доступен в immutable commit.

Ограниченный пакет на immutable Ledger integration `9e9170da`, в ветке
`agent/api-events-delivery-20261030`. Меняется только выбор timestamp подписи
в `services/space_events.py`; существующие event tests дополнены, сеть и БД
в тестах не используются. Нового partner endpoint, регистрации webhook,
scopes/grants, общей network policy или выпуска этот пакет не добавляет.
Это не завершение M14 и не заявление полной CloudEvents/Standard Webhooks
совместимости всех приложений экосистемы.

## Подтверждение первичными источниками

[Standard Webhooks 1.0.0, metadata](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md#webhook-metadata)
отделяет время попытки от времени события: retry обновляет первую метку,
ID остаётся устойчивым. Подписываются ID, timestamp и фактически переданные
байты тела. Получатель проверяет допустимую давность метки и дедуплицирует ID.
Это требование свежести попытки, не ограничение возраста бизнес-события.

[Официальный Python verifier](https://github.com/standard-webhooks/standard-webhooks/blob/main/libraries/python/standardwebhooks/webhooks.py)
использует окно ±5 минут. Спецификация требует допустимый tolerance, но не
назначает именно пять минут каждому получателю. Поэтому тестовый receiver
проверяет совместимый профиль с tolerance=300 секунд; нового окна настоящему
Core/Support receiver мы не добавляем.

[CloudEvents 1.0.2, time](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md#time)
определяет `time` как время возникновения факта. Переписывать его при retry
ради прохождения freshness нельзя.

Проверено по официальным источникам 30.10.2026. Никакие сторонние библиотеки
или новые зависимости не установлены; verifier в тесте независимо вычисляет
HMAC-SHA256 по настоящим `httpx.Request.content` bytes через stdlib, без вызова
sender `sign()` для проверки. Freshness и MAC проверяются раздельно.

## До и после

До исправления `_send` строил envelope из `row.occurred_at` и использовал ту же
метку для `webhook-timestamp`. После шести часов ожидания корректный
HMAC не проходит у внешнего получателя с пятиминутным окном свежести.
Это воспроизведено regression RED до изменения sender: фактический заголовок
1787218200 вместо времени попытки 1787239800.

Теперь `_send` берёт `datetime.now(timezone.utc)` непосредственно при подписи
**каждой** попытки. Время не берётся из batch `deliver_pending(now)`: обработка
предыдущих получателей может съесть replay window ещё до отправки этой строки.
Optional keyword-only `now` у приватного `_send` нужен для детерминированной
проверки; runtime dispatcher его не передаёт. Public endpoint/query управлять
этим временем не может.

Меняются `webhook-timestamp` и зависящая от него `webhook-signature`. `event_id`,
`webhook-id`, persisted `occurred_at`, `CloudEvents.time`, payload и его
сериализация и `Content-Type: application/json` не меняются этим patch.
Полный HTTP binding CloudEvents отдельно не сертифицирован. При одинаковом адресате и mapping body
байт-в-байт одинаков на попытках; app mapping по-прежнему определяется текущей
парой компаний, а не новым snapshot-хранилищем.

Сохранены существующие contracts:

- Одна outbox строка на подписчика, один event ID у fanout факта; успех одного
  адресата не возвращается в очередь из-за отказа другого.
- `publish` участвует в транзакции вызывающего бизнес-кода; `deliver_pending`
  не делает commit/rollback/flush за него. Advisory lock scheduler и
  `FOR UPDATE SKIP LOCKED` не меняются.
- TTL подписки считается по `occurred_at`; cancelled/expired не тратят попытку.
  Только 2xx означает done; retry с 5 минут, экспонентой до 6 часов,
  MAX_ATTEMPTS=12 и terminal failed остаются прежними.
- Ключи остаются Fernet-encrypted, алгоритм подписи и его формат прежние.
- App destination получает свой `data.companyId` из mapping; служебный Bearer
  имеет `aud=app_code`, `scope=events`, а не projection. URL destination не
  получает Core/SSO Bearer.

## Контрдоказательство: текущий Core → Support

Изучен **immutable Support `09c221c4b5135984173e3a924fd38f65cc208637`**, не старый
clone: `scripts/routes/v1/eco.js:1640–1705` и
`scripts/lib/webhooks.js:126–129`. В `checkCoreSignature` сознательно нет
freshness window. Он проверяет HMAC по rawBody и timestamp заголовка;
`verifySignature` не сравнивает его с `ce.time`. Дополнительный `coreService`
guard требует служебный scope events, а `(provider='core', external_id=ce.id)`
в inbound receipts даёт дедупликацию.

Поэтому **нынешний поздний retry Core → Support не доказан как сломанный**.
Новая метка совместима с изученной проверкой: подписываются те же bytes и
переданная метка, ID не меняется. Это source-level compatibility evidence,
не живой или end-to-end тест Support. Проверка совпадения header и body time
у иных подписчиков неизвестна: перед rollout их владельцы должны подтвердить
профиль. Support outbound со своим event-time timestamp этим пакетом не меняется.

## Отдельный evidence: SSRF, redirects, DNS и секреты

Этот раздел фиксирует границы исходного кода, без сканирования сети, DNS lookup,
рабочих адресов, keys или попытки эксплуатации.

| Область | Evidence в baseline | Вывод и ограничение |
|---|---|---|
| Право выбрать адрес | `routers/space_events_router.py:_admin` требует компанию, продукт docs и администратора; `_check_shape` проверяет только scheme http/https + netloc | Это не публичная registration. Admin gate ограничивает участников, но не доказывает допустимость сетевой цели |
| Внешний URL | `_send` использует `sub.url` напрямую; в validator/sender нет IP range allow/deny, запрета userinfo, проверки DNS ответов или запрета loopback/private/link-local | Из этих файлов нельзя заключить SSRF safety. Допустимый URL может указывать на внутренний ресурс; достижимость и внешняя egress policy не проверялись |
| DNS/rebinding | Между строковой валидацией URL и connect нет проверки/привязки resolved address | Возможность смены DNS и обхода простой hostname проверки — обоснованный риск, не проверенный exploit. Одной проверки при registration для будущей защиты недостаточно |
| Redirect | Production pin `httpx==0.28.1`, `_send` не включает follow_redirects; настоящий MockTransport-тест 307 даёт ровно один request и retry/pending | Redirect автоматически не выполняется. Это не исправляет прямой URL/DNS риск |
| App destination | `_target` ищет реестр и пару компаний, `_internal_base_url` берёт `config.internalUrl/internal_url` либо docker service code | Внутренние адреса здесь нужны намеренно. Общая блокировка private network без отдельной trusted app политики сломала бы mapping и service auth |
| Proxy/TLS/environment | HTTPX defaults сохраняются: verify=True, trust_env=True; timeout=10 s | Из кода нельзя доказать безопасную egress topology или отсутствие proxy env. Environment и соединения не изучались, redirects не включались |
| Нерасшифрованный секрет | Существующий `decrypt_secret` возвращает пустую строку при отсутствии/неверном ключе, а `_send` пропускает webhook headers; в app ветке остаётся service auth, в URL ветке Bearer нет | Предшествующий fail-open GAP подписи URL, не созданный этим patch. Ключи не меняются; исправление требует отдельного решения по остановке/ошибке доставки и migration |

HTTPX defaults подтверждены [официальным API](https://www.python-httpx.org/api/#asyncclient)
и тестом на установленном pin. Timestamp patch не меняет ни эти defaults,
ни целевые адреса, ни политику подписи при отсутствии расшифрованного секрета.
Описанные риски не основание выдавать новый внешний доступ.

Для отдельного согласованного network пакета понадобятся политика внешних целей
(HTTPS, допустимые порты/адреса/userinfo), проверка всех IPv4/IPv6 DNS результатов
и фактического connect без TOCTOU, контроль каждого redirect при его разрешении,
egress на уровне инфраструктуры, раздельная политика trusted внутренних apps
и явный fail-closed режим неподписанной URL доставки. Здесь это предложения,
не выполненные изменения и не свидетельство готовности M14.

## Тесты и воспроизведение

```sh
cd clearledger/server
/path/to/venv/bin/python -m pytest \
  tests/test_space_events.py tests/test_space_events_router.py -q
```

Все новые проверки используют `httpx.MockTransport` с настоящими сериализацией,
HTTP Request bytes, synthetic Fernet key, HMAC и проверкой freshness. Сокеты,
DNS, реальный HTTP transport и DB fixtures не используются; SQL окно не нужно.
Модульный conftest импортируется обычным pytest, но destructive setup_database
не запрашивается. Это unit/transport acceptance, **не DB integration или сетевой
end-to-end тест**. Конкурентное поведение PostgreSQL и production topology не
проверяются.

Покрыты задержанный первый send, повторные 5m/10m/20m/6h интервалы, явный now
с другим timezone, неизменные wire bytes/id/time, stale valid-MAC negative
control, replay через 301 секунду, подмена метки без новой подписи, пересборка
JSON, чужой секрет, app mapping/auth failures, независимый fanout, retry,
redirect, terminal failed, cancel/expiry и ownership транзакции.

## Rollout и rollback

Пакет не выпущен. Перед отдельным разрешённым rollout проверить потребителей:
приём должен использовать timestamp заголовка для HMAC/freshness, `time` payload
для времени факта и ID для receipt dedup; header не должен требоваться равным
payload time. Проверить синхронизацию часов и допустимый tolerance, наличие
расшифровываемого секрета и исходящую политику; этот отчёт сам их не подтверждает.
Сначала синтетический подписчик: задержать доставку более пяти минут, получить
2xx, повторить ID без повторного бизнес-эффекта, оставить другой адресат в retry.
Проверять счётчики done/pending/failed, не логировать body, keys и credentials.

Миграций данных и перезаписи outbox нет. Rollback — revert только focused commit
этого пакета либо восстановление прежнего sender через обычную процедуру поставки;
ID/occurred_at/receipt записи сохраняются. Это вернёт старый event-time header и
может снова ломать strict external freshness receiver, поэтому не лечить rollback
отключением проверки подписи или очисткой receipts. Изменять receiver time window,
перезапускать failed/expired строки, ротировать ключи или включать внешний доступ
этот patch не поручает.


## Фактическая проверка пакета

- Regression до runtime fix: **1 expected FAIL**, заголовок содержал occurrence
  epoch вместо epoch фактической попытки через шесть часов.
- После фикса: **38 PASS**, `test_space_events.py` + неизменённый
  `test_space_events_router.py`, 0.99 s; предупреждений нет.
- `compileall` изменённого Python и `git diff --check`: PASS.
- DB tests не запускались; SQL окно не занималось, другие тестовые DB и
  конфигурация PostgreSQL не затрагивались.
- Сеть/рабочие credentials/ключи, выпуск, merge и PR не использовались.
  Проверка official specifications — публичное readonly чтение.

Focused runtime diff: приватный keyword-only `now` и выбор времени подписи у
`_send`; `deliver_pending`, fanout, scheduler, models, main, identity, receivers
и registration не меняются. Существующий network/signing GAP зафиксирован
отдельно, без изменения политики получателей.


## Отдельный пакет: обязательная подпись URL webhook

Outcome: **fixed** в границе URL signing. Основа — immutable `c8b99684`,
та же owned ветка `agent/api-events-delivery-20261030`; timestamp commit
не переписывается. Меняются только sender, его существующие tests и этот report.

### Уязвимый путь и воспроизведение

Источник — сохранённый `EventSubscription.secret_enc` и каноническая функция
`decrypt_secret`. При отсутствующем ciphertext/ключе или неуспешной расшифровке
возвращалась пустая строка. Условие `if secret` пропускало всю подпись, после чего
`_send` создавал AsyncClient и делал URL POST без HMAC. В URL ветке нет service
Bearer. Повреждение/rotation encryption key — подтверждённый lifecycle trigger;
это не утверждение о неаутентифицированном доступе к регистрации подписок.

Regression до правки на c8: **1 expected FAIL**, MockTransport захватил один
неподписанный POST, приложение посчитало HTTP 204 успешной доставкой.
Проверка на missing ciphertext охватывает legacy/неконсистентное состояние:
текущая registration/DB constraint требуют ciphertext, но само наличие ciphertext
не доказывает его расшифровываемость. `database.py:ck_eco_event_subs_target` и
router разрешают только app/url; их схемы и права не меняются.

### Выбранная граница

Инвариант: **target_kind=url не достигает AsyncClient/post, пока невозможно
сформировать подпись**. Проверка находится в общем `_send`, через который идёт
`deliver_pending`, до HTTP клиента и всех его сетевых побочных эффектов.

Для URL требуется непустой расшифрованный секрет. У `whsec_` проверяется строгий
Base64 и непустой decoded key: прежний permissive decoder мог игнорировать мусор
и получить пустой ключ. Непрефиксный legacy секрет остаётся UTF-8 ключом по
существующему контракту; новые ограничения длины/миграция ключей не вводятся.
В plaintext вместо ciphertext не переходим, новые секреты не генерируем.
`_key` и существующий выбор EVENTS_SECRET_KEY/SECRET_KEY не меняются.

Ошибка расшифровки, формата или signer превращается для URL в безопасный
`RuntimeError("URL webhook: невозможно сформировать подпись")` без деталей
ключа/ciphertext и без исходного exception chain в отображаемом traceback.
`deliver_pending` сохраняет эту общую причину, `last_status=None`, failure streak
и backoff; `delivered_at` не устанавливается, после 12 попыток — failed.
Ошибка одного адресата не прерывает delivery другого; commit остаётся у caller.

Для `target_kind=app` сохраняется прежний optional HMAC: если секрет недоступен,
service Bearer остаётся обязательным и используется прежний canonical signer
с `aud=app_code`, `svc=events`. Company mapping и отказ при отсутствии mapping
или service token не меняются. Ошибки присутствующего malformed app signer
перекидываются как прежде; политика URL не переносится на app.

### Проверка границы и совместимости

По запрету делегирования два прохода investigation/review выполнены самим
исполнителем: сначала data flow decrypt→sign→AsyncClient и direct caller,
затем отдельная проверка обеих ветвей app/url, malformed key representations,
legacy secrets, безопасной ошибки и retry/recipient isolation. Чужие файлы,
receiver, registration, models/main/identity и network policy не менялись.

Команда из `clearledger/server`:

```sh
/path/to/venv/bin/python -m compileall -q app/services/space_events.py tests/test_space_events.py
/path/to/venv/bin/python -m pytest tests/test_space_events.py tests/test_space_events_router.py -q --tb=short
```

Результат после проверки: **61 PASS**, 1.34 s, предупреждений нет; `git diff --check`
PASS. Это исходные 38 timestamp/router tests и новые focused signing controls:

- Missing/empty ciphertext, missing encryption key, rotation, corrupt token,
  ciphertext в plaintext, empty/non-UTF8 decrypted value и malformed whsec
  (empty/junk/non-ASCII/padding/whitespace) — строго **0 requests и 0 clients**.
- Ошибка signer не раскрывает crypto details и не создаёт HTTP клиента.
- Корректный whsec, legacy Unicode secret и прежний stack-key fallback дают
  настоящие wire bytes/HMAC, проходящие независимую проверку свежести и подписи.
- App без HMAC при missing ciphertext/key/rotation отправляется с настоящим
  **синтетическим RS256 service JWT**: locally verified issuer/aud/support,
  svc/events и sub/service:events. `_target` заменён fake mapping, не реальной БД;
  JWT signer и cryptographic verification настоящие, keys созданы только в памяти.
- 12 signing failures дают retry→failed, не done; другая подписка получает 204
  и корректную подпись. Сохраняются ID/body/occurred_at и ownership транзакции.

Все HTTP клиенты в tests используют только MockTransport, requests не покидают
процесс. Нет DB fixtures, DNS, sockets, SQL окна, живых API или рабочих keys.
Это unit/transport validation, не PostgreSQL integration, network audit или
end-to-end Support тест. Установленный test tooling и зависимости не менялись.

### Rollout/rollback и оставшийся GAP

Перед разрешённым rollout отдельно проверить доступность encryption key и
расшифровываемость URL secrets на стороне владельца поставки: прежние скрытые
ошибки теперь станут видимыми retries/failed. Не печатать секреты и не заменять
потерянный ключ произвольным новым. Состояние очереди/ключей здесь не читается и
не исправляется; генерация, rotation и восстановление — отдельная операция.
Миграций данных нет, TTL/backoff/MAX_ATTEMPTS прежние.

Rollback focused fail-closed commit сохраняет timestamp fix c8, но **возвращает
риск неподписанного URL POST**. Его нельзя считать безопасным способом починить
missing key; владельцу следует восстановить совместимую конфигурацию/секрет либо
прекратить проблемную подписку по действующему процессу. При rollback не менять
receipt ID/occurred_at и не отключать проверку подписи у получателя.

Signing fail-open GAP из исторической таблицы выше закрыт только для URL.
**SSRF/DNS/rebinding/egress остаются explicit GAP**: нужен отдельный согласованный
профиль внешних адресов, проверка resolved IPv4/IPv6 и connect/redirect без TOCTOU,
миграция существующих URL и раздельные правила для trusted internal apps.
Административный gate registration не делает egress безопасным и не равен
unauthenticated bypass. Этот commit не меняет network policy, не открывает
новые endpoints/партнёрские URL и не означает готовность M14 целиком.

Пакет только commit/push; merge, PR, release и изменения ВМ не выполнялись.
