# V2 contract domain DTO — SOURCE_ONLY, 2026-11-01

Изолированный `server/app/product_api/contract_cycle_dto.py`: настоящие типы
Pydantic V2 и чистая валидация, без подключения к приложению. Это исходник будущего
договорного цикла, не включённый API. Направление Root — V2 contracts/sites/documents;
новой сущности contract-profiles нет. Пути, scopes, OpenAPI, SDK, миграции и writers
не утверждаются этим изменением. V1 DTO/hash-v1/0004 и native owners не изменены.

## Входные pins

База `b8b1c66cb5262a908cd9e1f0cc222e822e6c6ce9`, дерево
`b81e7f81b093ea7fb0be5ff5b3be3e015530db12`. Источники относительно `docs/api/`:

| Источник | Git blob | SHA-256 raw bytes |
|---|---|---|
| `rushydro-contract-write-20261101/TARGET.json` (proposal `66f43993`) | `ff5d1d79e1cbe95ebd63e293fe054a376dc83e8e` | `2e2d3135c4f430043e803af5dfad3f57e2acf97bed5211afb45483785271f805` |
| `rushydro-contract-write-20261101/ROOT-DECISION.md` | `be776f1620217a7d2655c5d340ba20c367bc8c3d` | `14c97cf9e878942b4cc28e5dc13b92baa900b87637ffdc721456b11ff615b869` |

TARGET неизменен. Root checkpoint принят до кода: coordinator `msg_b90aa436761f`,
Root `msg_62c44f582f85` через relay `msg_3e140a64668d`; уточнение lowercase Version
и wire schema — Root `msg_f46a3f3e531d` через relay `msg_6246fcc045e9`,
ObjectId bounds metadata — coordinator `msg_b6ee6c3734ec`.
Эти сообщения не выдают HTTP/DB полномочий.

## Типы и границы

| Тип | Вход и результат |
|---|---|
| `DateV2` | JSON: ASCII `YYYY-MM-DD`; Python: такая строка или **exact** `datetime.date`, без `datetime`. Реальный календарь 0001..9999; JSON — строка даты. |
| `UUIDV2`, `SiteUUIDV2` | JSON: hyphenated UUID36; Python: такая строка или exact `UUID`. Hex любого регистра принимается; вывод UUID канонический lowercase. Без braces/URN/hex32/bytes/int. SiteUUID — семантическое назначение поля, не отдельный Python authority type. |
| `ObjectIdV2` | Exact Unicode string 1..40, без NUL; пробелы/регистр сохранены, UUID-подобная строка остаётся ObjectId. |
| `MoneyV2` | Только строка, Numeric(16,2), `0.00`..`99999999999999.99`. |
| `TariffV2` | Только строка, Numeric(14,6), `0.000000`..`99999999.999999`. |
| `RateV2` | Только строка, Numeric(5,2), `0.00`..`100.00`. |
| `VersionV2` | Непрозрачная строка `v1:` + **lowercase** hex64; uppercase отвергается, casefold нет. |

Новая **V2 lexical convention** для decimal: нет знака (включая `+` и `-0.00`),
экспоненты, нечисловых значений, пробелов, ведущих нулей целой части кроме `0`.
В Python вход decimal тоже строковый: int/bool/float/Decimal не принимаются.
После проверки хранятся exact native `Decimal` с исходным scale; Python dump
сохраняет Decimal, JSON dump отдаёт строку без float и округления. Сериализатор
отвергает неверный native тип/scale. Базовая цена допускает ноль, условие — строго >0.
`WithJsonSchema` внутри типов описывает **string/pattern/minLength/maxLength**
в validation и serialization modes; Date/UUID schemas также только string,
ObjectId schema фиксирует 1..40/noNUL.
Это metadata внутренних типов, без изменения опубликованного schema bundle.

Все модели strict/frozen, `extra=forbid` рекурсивно, int/bool без coercion.
Существующие DTO повторно проверяются через wire-представление; это сохраняет
decimal scale и `fields_set` PATCH. Frozen не делает вложенные списки immutable:
чистые функции повторно проверяют переданное состояние, но не блокируют его в БД.

`ContextV2`: `{kind:site,siteId}` или `{kind:location,locationId}`.
`CoverageV2`: site либо 1..100 уникальных exact ObjectId в `locationIds`.
Подмена site/location/equipment и смешанные discriminators отвергаются структурой;
валидный UUID сам по себе не доказывает ни тип ресурса в БД, ни доступ.

`CardV2`: явные Lease/PowerSupply, все общие реквизиты TARGET обязательны, включая
nullable значения. Lease требует явный basis из пяти вариантов; PowerSupply —
только contract. Supplier/RUB фиксированы. Validity строго unknown/openEnded/until;
until.date >= card.date. Legacy null не классифицируется.

Любая полная карточка требует `context={"todayMSK": exact_date}`; callable
`validate_contract_card(..., todayMSK=exact_date)` передаёт его явно. Это обязанность
вызывающего: определить московскую бизнес-дату. Нет import-time clock, wall-clock
fallback или пропуска проверки даже у unsigned. Signed требует signedAt <= todayMSK,
unsigned — signedAt=null. Требование signedAt >= card.date не придумано.

`TermV2`: LeaseFixed/rent/positive Money либо PowerMetered/energy/positive Tariff,
PowerSupply только monthly. validTo=null или >= validFrom; due days 1..31|null,
expectedDocs — уникальные act/upd/invoice/sf/report, 0..5, не null.
Parent profile **не добавлен в term wire**.

## Чистые функции и команды

- `merge_contract_card(currentCard, changes, todayMSK=...)`: проверяет текущее
  состояние и итог после merge. `CardChangesV2.model_fields_set` и
  `model_dump(exclude_unset=True)` различают omitted/null/value. Явный null разрешён
  только для vatPct/amountInclVat/signedAt/comment. Пустой PATCH, profile и
  organizationId отвергаются. Partial PATCH отдельно не доказывает final-state
  signed/date/validity/profile rules.
  Узкий follow-up после `92ea2c42`: остальные девять полей имеют nonnullable
  annotations и omission-only default factories; обе wire-схемы разрешают пропуск,
  не обещая explicit null или default:null. Внутренний placeholder не является
  wire-значением: PATCH сериализуется с `exclude_unset=True`. Сценарии 45/46
  фиксируют optionality/nullability/default в обоих schema modes и отвергают null
  для всех девяти полей; именованных сценариев по-прежнему ровно 50.
- `validate_contract_term(term, finalCard=..., coverage=..., todayMSK=...)`:
  явные финальная карточка и coverage; проверяет profile/costItem/condition и точное
  вхождение контекста. Ни поиска Site→Location, ни ACL/owner inference.
- `validate_term_replacement(replacement, previousTerm=..., finalCard=...,
  coverage=..., todayMSK=...)`: дополнительно сохраняет costItem/context и требует
  validFrom > previous.validFrom. Не закрывает старый интервал и не проверяет
  overlap/closed periods; это native owner, отдельный peer.

`ContractCreateCommandV2` — commandKey+card+coverage; `ContractPatchCommandV2` —
commandKey+expectedVersion+changes; `TermCreateCommandV2` — W+term;
`TermNewVersionCommandV2` — W+replacement; `MutationResultV2` —
resourceId+editVersion+strict replayed. Команды валидируют форму, не выполняют pure
compatibility автоматически без явно переданного final/previous state.

Version equality не выдаёт authority. HTTP If-Match/ETag/status, replay/hash,
receipts/birth grants, DB existence/identity, concurrency/locks, actual term windows,
закрытые периоды, persistence и выдача результата находятся за границей DTO.
Семантика exact routes/scopes/schema/миграций остаётся на будущие решения Root.

## Конечная матрица — ровно 50 именованных сценариев

`server/tests/test_rushydro_contract_cycle_dto.py`: 50 обычных функций test_01..50,
без parametrization/fuzz/генерации новых случаев. Внутри сценариев конечные явные
векторы; размеры 100/101 — только данные границы coverage, не сотни тест-кейсов.
Ожидаемые значения/ошибки заданы по домену. Native бизнес-код автором **NOTRUN**.

| Группа | Номера и сценарии |
|---|---|
| Scalar (15) | 01 calendar endpoints/leap + schema; 02 invalid dates/datetime; 03 UUID Python/JSON/canonical/schema; 04 malformed UUID; 05 Money endpoints/Decimal/wire/schema; 06 Money lexical/type rejection; 07 Tariff endpoints/wire/schema; 08 Tariff rejection; 09 Rate endpoints/wire/schema; 10 Rate rejection; 11 exact ObjectId; 12 ObjectId rejection; 13 lowercase Version; 14 malformed/uppercase Version; 15 strict bool/int. |
| Context/coverage (7) | 16 site Python/JSON; 17 location exact; 18 mixed/unknown/null/extra; 19 site coverage; 20 locations 1/100; 21 duplicate/empty/101/tuple; 22 nested extra/snake_case. |
| Card (13) | 23 Lease; 24 PowerSupply; 25 Power basis; 26 required/bounded fields; 27 payment 0/366/nullable/text endpoints; 28 payment rejection; 29 unknown/openEnded; 30 until equal/later; 31 until earlier; 32 signed today; 33 signed missing/future date; 34 unsigned nonnull date; 35 absent/datetime business clock, including nested existing DTO. |
| Terms (8) | 36 fixed/site; 37 metered/location/monthly; 38 zero/negative/mixed condition; 39 reversed interval; 40 due/docs/lease periodicities; 41 invalid due/docs; 42 profile/condition/costItem/monthly mismatch; 43 uncovered site/exact location. |
| Commands (7) | 44 create/result/strict replayed; 45 omitted/null/value and merge; 46 empty/immutable/required-null/extra patch; 47 invalid merged signed/date/profile; 48 term-create shape+separate context check; 49 valid replacement; 50 changed costItem/context/equal start. |

Статический подсчёт по написанным вызовам: 66 scenario-level validation calls;
с учётом внутренних проверок pure helpers — 98 native validation entrypoints при
полном успешном прохождении матрицы. Это подсчёт исходника, не runtime evidence;
полевая рекурсия Pydantic и сериализация не считаются отдельными кейсами.

## Evidence / передача Root

Автору разрешён только Runtime0: Git, собственные stdlib AST/hash/JSON и compile
code objects **без exec**. AST parse/compile обоих Python-исходников выполнен;
Pydantic/app/helper imports, schema generation, pytest/collection, DB/network,
Node/сборки не выполнялись. Фактический native результат всех 50 — **Root pending**.

`product_api/__init__.py` eagerly imports `.app`. Тестовый исходник загружает только
новый модуль по точному файловому пути через standalone importlib namespace,
не исполняя package initializer. Это код для будущего Root offline guard;
автор его не импортировал. Обычный server pytest остаётся под DB-owning conftest:
запускать его здесь нельзя. Root должен в изолированном guard загрузить только новый
модуль/эту конечную матрицу, отдельно исключив приложение и server conftest.
Никаких утверждений PASS/full CI/live/закрытия периода этот source chunk не делает.
