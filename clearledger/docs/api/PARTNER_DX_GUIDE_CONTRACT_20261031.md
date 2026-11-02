# D2+C1: руководство партнёра и метаданные текущего контракта

31.10.2026 · Run `run_781185341d88` · база `cec2c9845431a0bc07e4b4f115eb21eed8d5caa9`.

Реализованы восемь новых страниц руководства и документационный слой существующих15GET:111Field/alias descriptions/examples, summaries/descriptions и14полных fictional JSON200 плюс отдельный binary200. Добавлены два набора тестов с12test definitions, **WRITTEN_NOTRUN**. Подготовлены независимые статические доказательства; приложение, framework, тесты и генерация не запускались. Полные runtime/SDK/schema/partner gates не закрыты.

## Разрешение и состав

Прямой ответ пользователя в этом чате: **«Разрешаю узкий C1 и draft PR без запуска и выпуска»**. Он разрешает описания/примеры двух существующих файлов, новые тесты без исполнения и публикацию draft PR; обработчики, wire semantics, права, flags и работающие сервисы не меняются. До ответа C1 был изолирован и не отправлялся, исходные локальные коммиты сохранены. Разрешение не выводилось из отсутствия ответа. Отдельный docs-only [PR81](https://github.com/Electro-Interfaces/ClearLedger/pull/81) сохраняется как снимок D2 до разрешения; для совместной приёмки используется настоящий18файловый пакет. Дублирующее слияние обоих PR не требуется.

Исходный аудит поставки PR58 остаётся draft/без merge. ROOT-Run не принимался в управление, его очередь и исполнители не использовались. Свои два исполнителя завершены и штатно released.

| Область | Точный состав и назначение |
|---|---|
| D2 · 8 новых страниц | `docs/partner/{onboarding.md,auth.md,data-dictionary.md,errors.md,recipes/read-catalogs.md,recipes/contracts.md,recipes/monitoring.md,recipes/documents.md}` относительно clearledger |
| C1 · 2 существующих файла | `server/app/product_api/dto.py`, `app.py`: только Field descriptions/examples и operation summaries/descriptions/response examples |
| Новые тесты | `server/tests/test_partner_dx_metadata_20261031.py`, `test_partner_dx_examples_20261031.py`; написаны, не собирались и не исполнялись |
| Статические утилиты | `scripts/verify_partner_dx_metadata_20261031.py`, `verify_partner_guide_examples_20261031.py`; только Git/stdlib AST/literals/hash/in-memory compile, без app/helper/framework imports |
| Доказательства | `docs/api/PARTNER_DX_METADATA_SOURCE_20261031.md/json` исполнителя B и данный `PARTNER_DX_GUIDE_CONTRACT_20261031.md/json`; все18путей/SHA-256 перечислены в JSON |

Коммит A `74107e9c652ef60f76f6599c61c3ad411df76a3f` перенесён как `adb823a130717a58821b885d9f53b7ab1a703967`. Коммит B `b220a97cffa99ee49b87a606ff90cd1810a5b48d` перенесён как `74e56c955dfc90175aed2189bbd13123111b9d8d`. Собственные отчёт/утилита добавляются поверх, чужой WIP не включён.

## Руководство для первого чтения

Вход: [onboarding](../partner/onboarding.md). Восемь страниц позволяют подготовить первый read walkthrough без чтения исходников: заявка и квитанция owner/client/app/install/grant; отдельные Core login/OIDC/delegated/service/docs flows; PKCE, refresh rotation/revoke;15полных request/200/отказ/следующий шаг. На сложную семантику даны42immutable source references в отдельных блоках сопровождения, не обязательных для интегратора.

[Словарь](../partner/data-dictionary.md) и [ошибки](../partner/errors.md) объясняют required nullable, redacted links, opaque ID и URL caveats, open strings, raw validUntil≤20, q/wildcards, created_at UTC inclusive, live paging и optional Retry-After. Рецепты [каталогов](../partner/recipes/read-catalogs.md), [договоров](../partner/recipes/contracts.md), [мониторинга](../partner/recipes/monitoring.md) и [документов](../partner/recipes/documents.md) показывают client join оборудования, явные текущие связи, current catalog/MSK provenance, cap200 текущих версий, bytes/headers и partial stream failure.

Machine не получает documents/files/identity/docs; пароль и Core admin token партнёру не передаются. Scope не заменяет independent resource grant и текущие права. Нет новых write/admin/events/site/EVSE/connector, денег, выдуманных enum, SLA или квот. `.invalid`, placeholders и UUID/показатели только вымышленные. Reduced read walkthrough не заменяет полные rental/energy/operations пилоты.

## Что доказывает source-проверка

**PASS_SOURCE_ONLY:** нормализованные AST двух изменённых файлов совпадают с immutable базой после удаления строго указанных documentation keywords. Сохраняются аннотации, aliases, required/nullable/default/min/max/pattern/validators, paths/operationId/methods, response_model, response schemas/headers/statuses, scopes/principals/grants/tenant/file policy, handlers и общий operation helper. Helper, `_problem`, `_describe_http_responses`, SQL/бюджеты не редактировались. Девять остальных product_api/api_contracts файлов побайтно идентичны базе.

Normalizer не удаляет responses или kwargs целиком: исключены только summaries/descriptions конкретных операций,200.description и200.content.application/json.examples. Binary schema остаётся точной. Required поле без default отличается от default=None. Отрицательные mutation tests написаны для проверки этих границ, но **NOTRUN**.

**Независимая проверка guide:**8страниц,15операций,14полных success DTO+1binary,15полных Problem отказов,34JSON,97локальных ссылок,42source-range groups. Типы/поля/literals/длины/границы сопоставлены с immutable AST DTO. Это ограниченная явная грамматика stdlib checker, не Pydantic coercion/JSON Schema/OpenAPI validation и не HTTP-проверка.

Файл `src/generated/partner-api.d.ts`, exporter, generator/lock/deps, ROOT quickstart/SDK/pilot и общие STATUS/CURRENT-STATE/COMPLETION-MATRIX не изменены. Generated freshness не установлена: новое описание/примеры должны войти в отдельный проверяемый export/regeneration у ROOT. Статическое доказательство не присоединяет исторические PASS других составов.

## План будущей проверки ROOT

Ниже команды **не выполнялись**, это точный план после выбора изолированного frozen окружения. Общий conftest импортирует приложение и может готовить тестовые схемы; окружение и исполнение остаются в ведении ROOT.

```sh
# Source-only evidence from the Ledger repo root; does not import app/framework.
python3 clearledger/scripts/verify_partner_dx_metadata_20261031.py --scope metadata
python3 clearledger/scripts/verify_partner_guide_examples_20261031.py

# Future ROOT execution only, from clearledger/server in its isolated test environment.
python -m pytest -q tests/test_partner_dx_metadata_20261031.py tests/test_partner_dx_examples_20261031.py
```

Два новых набора проверяют реальные DTO/schema examples и negative missing/null/type/ID/constraint cases; exact route/policy registry; неизменность helper/error profile и отрицательные мутации normalizer; корректность связанной fictional chain и binary schema.12definitions не объявлены12успешными тестами; параметризованные cases тоже не исполнялись.

Далее в ROOT-приёмке предусмотрены server/browser OpenAPI export, schema/headers/security/example checks, штатные types regeneration/freshness/typecheck и существующие relevant regression tests на одном составе. Не править `.d.ts` вручную и не выдавать source builder за HTTP-приёмку. Обычный сотрудник, callback/CORS/ingress, файлы/отзыв и самостоятельный внешний разработчик требуют отдельной согласованной песочницы. Ни одна такая проверка здесь не запускалась.

## Неприменённый hunk для владельца quickstart

ROOT зарезервировал `docs/PARTNER_QUICKSTART.md`, `PARTNER_SDK_TYPES.md` и `tools/partner-pilots/clients/{guards.ts,guards.test.ts,scenarios.ts}`. Они не входят в diff этого пакета. Предлагается только навигационный переход:

```diff
--- a/clearledger/docs/PARTNER_QUICKSTART.md
+++ b/clearledger/docs/PARTNER_QUICKSTART.md
@@ -1 +1,4 @@
 # Подключение внешнего приложения: кандидат API
+
+Текущая инструкция: [подключение партнёра](partner/onboarding.md).
+В ней 15 GET: 11 user/service и 4 user-only; candidate/default-off, source-only.
```

## Ограничения и исходная программа

App/helper/framework imports, pytest/collection/typecheck, Node/exporter/codegen, HTTP/browser/OIDC/SQL/Docker/SSH, установка зависимостей, CI, credentials/.env, live flags, workflow/billing, пилоты, merge/release/deploy и ai-base не выполнялись. Инфраструктура, БД и рабочие данные не менялись.

Полные исходные20M и11gates сохранены в JSON с оригинальными текстами и `completion=unproven`, `closesSections=[]`, `closesGates=[]`. Метаданные и guide подготовлены; весь M09/M11/M18, CONTRACT, FINAL-COMPOSITION, LIVE-PILOT и RELEASE этим пакетом не закрываются. Исторические2491поверхности не использованы как сегодняшний реестр. При передаче ROOT получает exact files/hashes, source proof и план проверок, а не утверждение готовности всей системы.
