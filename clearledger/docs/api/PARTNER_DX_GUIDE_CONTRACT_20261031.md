# D2: руководство партнёра; C1 сохранён локально до разрешения

31.10.2026. Собственный Run `run_781185341d88`. Результат этой ветки — **только документация D2**: восемь новых страниц для текущих15GET,14полных JSON200 и одного binary200,15 отказов и следующих шагов. Серверный код, тесты, SDK, общие спецификации, настройки и flags в этой ветке побайтно соответствуют базе. Это реализация руководства, без утверждения о работающей интеграции.

База: `Electro-Interfaces/ClearLedger@cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`.
Исходный аудит PR58 остаётся draft/без merge. Полные source refs и SHA-256 D2 находятся в [машинном отчёте](PARTNER_DX_GUIDE_CONTRACT_20261031.json).

## Граница исполнения и C1 HELD

Первое сообщение основного оркестратора было ошибочно принято за достаточное новое разрешение на server metadata. До уточнения границ исполнитель B подготовил isolated C1: `b220a97cffa99ee49b87a606ff90cd1810a5b48d`; смешанная локальная ветка сохранена на `74e56c955dfc90175aed2189bbd13123111b9d8d`. В ней111Field/alias и15operation descriptions/examples, два написанных набора тестов и source proof; runtime не запускался. **Эти изменения не входят в данную ветку/PR, не отправлены в origin и не разрешены к переносу.**

Прямой user запрет менять серверный код в исходном чате не отменён. После сообщения ROOT `msg_03940c589e94` C1 больше не изменяется и не публикуется; явный вопрос пользователю об узком scope остаётся без ответа на момент этого отчёта. Отсутствие ответа не является разрешением. Работа B сохранена без reset/stash/удаления, оба supervised исполнителя завершены и released.

Это ограничение относится к C1. Готовая новая документация D2 выделена в отдельное рабочее дерево и ветку `MagLook/partner-dx-guide-docs-only-20261031` от той же базы, перенесён только коммит A. Вся diff-область этого PR находится внутри `clearledger/docs/`; app source и тестов в diff нет.

## Что сделано

| Новая страница | Содержание |
|---|---|
| [onboarding.md](../partner/onboarding.md) | Заявка и квитанция owner/client/app/installation/grant, source pin, все15operationId, маршрут первого чтения, scopes и независимые resource grants |
| [auth.md](../partner/auth.md) | Core login, OIDC identity, delegated Code+PKCE, machine client_credentials и отдельный docs grant; token exchange, rotation, revoke, ошибки и закрытые boundaries |
| [data-dictionary.md](../partner/data-dictionary.md) | Поля/nullable/open strings, opaque IDs, UTC created_at против MSK monitoring, q/wildcards, fixed sort, live cursor, current links и недоступные возможности |
| [errors.md](../partner/errors.md) | Problem/OAuth/docs/proxy/stream envelopes, requestId, 400–503, optional Retry-After, bounded retries и отсутствие обещанного SLA |
| [recipes/read-catalogs.md](../partner/recipes/read-catalogs.md) | Шесть операций objects/equipment/counterparties, полные запросы/200/отказы, client join оборудования с разрешёнными ЭЗС |
| [recipes/contracts.md](../partner/recipes/contracts.md) | Пять операций договора/classifier/objects/documents, exact typeCode, raw validUntil и independent visibility |
| [recipes/monitoring.md](../partner/recipes/monitoring.md) | Одна операция monitoring, окно/наблюдения/provenance, current catalog, sessions/visits, units и неизвестные значения |
| [recipes/documents.md](../partner/recipes/documents.md) | Три операции document list/detail/content, user-only/download scope, current versions cap, binary bytes/headers и incomplete stream |

Все примеры используют `.invalid`, placeholders и вымышленные UUID/показатели. Machine не получает documents/files/identity/docs. Secret хранится на сервере клиента, Core admin/внутренние endpoints партнёру не предлагаются. JSON `null` не превращён в отсутствие, raw validUntil не объявлен ISO date/бессрочностью, открытые строки не сужены до enum. Для нынешнего API не добавлены money DTO, квоты, SLA или отсутствующие write/events/site/EVSE/connector.

## Проверка исходников и документов

Координатор независимо повторил разрешённую проверку D2:

- Все8страниц,97локальных ссылок и34fenced JSON синтаксически корректны.
- По15operation markers проверены реальные GET paths, Bearer placeholders, full200 и полный Problem отказа.14JSON ответов рекурсивно сопоставлены с полями/alias/type/literal/min/max/pattern **immutable AST DTO**, включая required nullable; binary не подменён JSON.
-42source references/range groups проверены против точных Git blobs базы с сохранением SHA-256.
- Проверен точный docs-only file allowlist; root-reserved quickstart/SDK/pilot, весь server source и generated types не изменены.

Стандартная библиотека Python; утилита [verify_guide_examples.py](partner-dx-guide-evidence-20261031/verify_guide_examples.py) не импортирует приложение, helpers или framework. Это ограниченный статический разбор явно поддержанной AST-грамматики, **не** Pydantic/JSON Schema/OpenAPI validation, HTTP или OIDC-проверка. Он не доказывает выдачу таких ответов работающим приложением.

Разрешённое воспроизведение проверки документов из корня Ledger:

```sh
python3 clearledger/docs/api/partner-dx-guide-evidence-20261031/verify_guide_examples.py
git diff --check cec2c9845431a0bc07e4b4f115eb21eed8d5caa9 HEAD
```

Ни app import, ни pytest/collection/typecheck, Node/exporter/codegen, HTTP/browser/OIDC/SQL/Docker/SSH, зависимости, CI, пилоты, credentials/.env, flags, workflow, выпуск, merge или продуктив не выполнялись.12написанных test definitions C1 остаются локальными и NOTRUN; в этот docs-only пакет не включены.

## Передача ROOT

Самостоятельно принимаются D2 guide, статические evidence и неизменность исходников в этом docs-only diff. Общие файлы ROOT не менялись:

`clearledger/docs/PARTNER_QUICKSTART.md`, `PARTNER_SDK_TYPES.md`, `clearledger/tools/partner-pilots/clients/{guards.ts,guards.test.ts,scenarios.ts}`.

Предлагаемый **неприменённый** навигационный hunk для владельца quickstart:

```diff
--- a/clearledger/docs/PARTNER_QUICKSTART.md
+++ b/clearledger/docs/PARTNER_QUICKSTART.md
@@ -1 +1,4 @@
 # Подключение внешнего приложения: кандидат API
+
+Текущая инструкция: [подключение партнёра](partner/onboarding.md).
+В ней 15 GET: 11 user/service и 4 user-only; candidate/default-off, source-only.
```

C1 metadata и будущая генерация schema/types остаются отдельным пакетом после явного разрешения пользователя. Для будущей ROOT-приёмки предусмотрены сравнение двух защищённых schema и generated types, настоящие framework/schema tests, сохранение denial/policies и первый read walkthrough без исходников на согласованной песочнице. Это план проверки, не требование продолжать за данного исполнителя и не заявление о выполнении.

Reduced read walkthrough не заменяет полные rental/energy/operations пилоты. Исторические2491поверхности не пересчитывались и не объявлены текущим составом. Полные исходные20M и11общих критериев сохранены в JSON с оригинальным текстом и `completion=unproven`; данный D2 пакет их не закрывает.
