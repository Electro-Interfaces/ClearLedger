# Состояние сети: проект контракта

**PROPOSED / PENDING_DESIGN; Source NOT RUN.** Кандидат
`GET /api/v1/monitoring/network-state`, `getNetworkState`, версия
`network-state-1`: не существующий маршрут и не публикация.
Git: `8cc5b0dd76ba4e2b1340b3f54d932900792a36b6`, дерево
`317ec47e1b86d3eb6f57fad35fc76e12a112cb49`. JSON: пути/строки/SHA-256,
выражения либо PENDING_DESIGN, ручные синтетические oracles.

Владелец — `services/network_state.py:72–85`: проекция/рефакторинг внутри
него переиспользует station_scope, monitor_context и точный native mismatch.
Формулы/политику в роутер не копировать. Текущий
`GET /api/v1/objects/{objectId}/monitoring` — визиты/энергия одного объекта,
а не полный network-state.

## Решения Root

Receipt `msg_5b4546895157`, доставка `msg_65920d0cac86`:
D1/D2 — **DESIGN_SELECTED_NOT_IMPLEMENTED**, не готовый API.

D1: ранний фильтр ВСЕХ запросов/подзапросов и scoped watermark;
глобальный контекст источника в публичный ответ не входит.
Предложенный доступ: monitoring:read AND objects:read; user/approved service;
energy; текущие company/grants/membership/object/org ограничения product API.
Членство в компании не заменяет org-доступ; query overrides запрещены.
E — разрешённый обслуживаемый парк после региона; context/MAX по E.
M — E после onlyProblems; полная сводка M до курсора, независимо от страницы.
EMPTY/set() никогда не None/ALL.

D2: onlyProblems — **только существующий точный mismatch**;
порядок — locationId. Деньги/loss/attention и производные состав/порядок
запрещены; новая формула не вводится.

## Разрывы исходника

`network_state.py:91–186`: company MAX до context, все SQL до Python-фильтра
location_ids на 190–191. Q1–Q9 в JSON: 8 execute и last_charge subquery;
PRE1: native resolver с вложенными SELECT. Ранних ID/org ограничений нет.
Нужен E внутри MAX/window/history/rhythm/last_charge/dry/attempts и
Region/ServiceLocation, до агрегаций/счётчиков. Пустой set убирает строки
поздно, общий watermark влияет на asOf/давность. Владелец не даёт
автоматической приватности. Уже есть scoped session_boundary
(`ops_monitor_context.py:77–91`), но network_state его не вызывает.

`network_state.py:243–251,284–288`: attention=bool(mismatch OR loss),
native only_problems использует attention, порядок — loss/revenue.
Удаление денег из DTO оставляет утечку состава/порядка/счётчиков.
Нельзя публиковать attention/loss, денежные итоги/regions revenue,
statusRaw/unchecked metadata. Нужна операционная проекция владельца
без лишних денежных вычислений, не passthrough отчёта.

## Предложенный wire и gate

Allowlist: items(objectId/status/lastChargeAt/silentDays/mismatch),
summary(stations/mismatch/byStatus), context(asOf/dataThrough/dataLagHours/
requestedDate/catalogMode/boundaryScope/availability), nextCursor.
Все имена/schema предложены; availability не подтверждает здоровье источника.
ServiceLocation ID — точная строка, не EzsSite UUID/OCPP/equipment; не сливать.
Неизвестные даты/давность — null; enum использует product unknown fallback.
Сессии — naive MSK, ответ +03:00, не UTC. asOf ограничивает сессии;
паспорт/статус текущие. dataThrough бывает позже выбранной даты, lag — до now.

Пределы asOf/region/onlyProblems — предложения в JSON. pageSize 1..200 и
cursor нативно отсутствуют. Строгий неизвестный query →422 предложен.
Root выбрал bounded page, reauth каждой страницы, явную популяцию сводки,
без snapshot обещания. **Единственный implementation gate D3:** конкретные
SQL/page/cursor/budget. Минимум в JSON: E внутри owner, summary M,
keyset id/limit и новый подписанный курсор с правами/границей.
Предложенные admission/SQL budget требуют Root, не измерены.
Native UNBOUNDED; лимит ответа не ограничивает стоимость БД.

D4–D6 — детали design review: даты/null, DTO/HTTP, регион/metadata/oracles.
Ручные ожидания требуют одобрения Root до будущей независимой SQL-проверки.
HTTP предложено наследовать из product profile: Problem, 401/403/404/422,
cursor400, quota429, 500/503, no-store/X-Request-Id, Bearer challenge,
Retry-After по источнику. Anchors — JSON; кандидат не тестировался.
CORS/ingress/live неизвестны; runtime/SQL/тесты — 0. Далее Root design review,
отдельная code Task; 19 scaling/Direct22 припаркованы.
