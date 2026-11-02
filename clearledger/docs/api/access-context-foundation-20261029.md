# Основа M03: AccessContext и исполняемые route policies

29.10.2026. Изолированная ветка `refactor/doc-access-policy-20261029`, продолжение
после `9003b83c`. Добавлены только новый пакет `server/app/api_contracts`, два
тестовых модуля и этот документ. Legacy authentication, scope, main, модели,
document policy и frontend не изменены. Подключения к рабочим API/БД нет.

Это исполняемая основа для следующих продуктовых маршрутов и настоящего OAuth
resolver, а не завершение M03 или реализация OAuth/revocation persistence.

## Контекст и разрешения

`Principal`, `AccessContext`, `ResourcePermission`, `ResourceScope`, `RoutePolicy`
используют frozen dataclasses. Входные коллекции копируются в `frozenset`/`tuple`.
Обычный `User`, словарь с `is_superadmin`, неявное приведение строк к principal
kind и дубли resource/action permissions не принимаются.

- `Principal.kind`: `USER`, `PARTNER`, `SERVICE`, `PUBLIC`; идентичность содержит
  subject, client, installation и grant. Машинный principal требует client/grant;
  public не может содержать authenticated identity.
- `AccessContext`: principal, company, policy version, OAuth/grant scopes,
  отдельные resource permissions и `valid`. По умолчанию `valid=False`.
- `ResourcePermission`: resource type, action, resource scope, field scope.
  OAuth scope не подменяет resource/action permission или field access.
- `ResourceScope`: `ALL`, `SET`, `EMPTY`, `UNINITIALIZED`.
  `selected([])` всегда `EMPTY`; строки, null и неполные идентификаторы не
  интерпретируются как ALL. Неинициализированный scope сохраняется как отсутствие
  подтверждённого доступа при пересечении.

Пересечение контекстов возможно только для одной идентичности, компании,
installation/grant и policy version; scopes, действия, ресурсы и поля пересекаются.
Результат invalid, если invalid любой вход. Пересечение user-admin с partner
identity отклоняется: самостоятельный delegation protocol ещё не реализован.
Роли администратора и `is_superadmin` не дают обхода partner grant.

## Исполнение маршрута

`PolicyRouter(context_resolver=server_callable)` регистрирует endpoint через
`operation(path, policy=RoutePolicy(...), ...)`. Обязательны owner, principal
kinds, resource/action, required scopes, policy version, tenant requirement;
private policy также требует имя security scheme. Public является отдельной
явной policy, несовместимой со смешанным public/authenticated контрактом.

`PolicyRoute` получает неизменяемый binding policy/resolver/selector. Проверка
исполняется до разбора JSON, Pydantic validation, handler dependencies и handler:

1. Resolver возвращает именно валидный серверный `AccessContext` актуальной
   policy version, иначе 401. Resolver вызывается заново на каждый запрос.
2. Principal kind, обязательная company, scopes, resource/action permission и
   явно требуемые поля проверяются независимо, иначе 403.
3. Необязательный серверный `tenant_selector(Request)` должен вернуть company
   ровно из контекста. Параметр пути/запроса является только selector, не authority.
4. Серверный `selector(Request)` должен вернуть непустой SET, целиком входящий
   в разрешённый resource scope; invalid/missing/EMPTY/ALL selector отклоняется.
   В handler передаётся дополнительно суженный context.

Синхронный resolver/selector выполняется в thread pool, асинхронный — напрямую.
Нет автоматической десериализации контекста из body/header/query, зависимости
от legacy `User` и возможности заменить bound guard обычным FastAPI dependency
override. Handler получает подтверждённый context через `Depends(get_access_context)`.
Обычные overrides остальных зависимостей FastAPI сохраняются.

**Граница доверия:** resolver — явно установленный серверный код. Он должен
проверять credentials, тип токена, текущий grant/отзыв и версию политики, а затем
создавать context. `valid` является его проверенным решением; пакет сам не
проверяет JWT, не читает grant DB и не выпускает токены. Ошибочное доверие к
body/header внутри будущего resolver этим пакетом исправлено не будет.

**Граница предметных правил:** guard не угадывает ACL по URL, не фильтрует SQL,
не проверяет доменное состояние и не маскирует response автоматически. Query
обязан применять company/resource scope, а команды — прежнюю domain ACL и
доступ именно к изменяемым полям. Для endpoint с выбранным id/company следует
передать соответствующие серверные selectors; скрытое определение их по имени
параметра намеренно отсутствует. EMPTY и UNINITIALIZED сейчас дают 403 даже
для collection routes; возврат пустого списка вместо отказа — отдельный контракт.

### Seam к M10 VerifiedPartnerToken

Публичные типы `ContextResolver`, `ResourceSelector`, `TenantSelector` фиксируют
серверную точку подключения. Будущий adapter сначала вызывает
`partner_identity.verify_partner_access_token` либо dependency M10, затем
получает domain permissions и возвращает один `AccessContext`:

- machine token → `PrincipalKind.SERVICE`, пользовательская партнёрская
  установка → `PrincipalKind.PARTNER`; subject/client берутся из проверенного
  результата, installation/grant/company UUID переводятся в канонические строки;
- `scopes` берутся только из verified результата; `policy_version` и `valid`
  задаются актуальной проверкой сервера, а не DTO или token claim без проверки;
- отдельные resource grants объектов, оборудования, контрагентов, договоров и
  документов превращаются в permissions соответствующих resource/actions с
  сохранением ALL/SET/EMPTY и пересекаются с domain/field policy;
- location grant не становится автоматически grant на все домены;
  отсутствующая policy не превращается в ALL;
- machine не получает пользовательский document ACL: пока самостоятельная
  machine domain policy не реализована, document permissions отсутствуют,
  а соответствующий principal kind не включается в document RoutePolicy.

Verified token не заменяет context, и adapter не создаёт фиктивный `User`.
Зависимости пакета от незавершённого verifier M10 нет; adapter и его интеграционные
тесты принадлежат следующей совместной работе M03/M10/product routes.

## Минимальная регистрация

```python
from fastapi import Depends
from app.api_contracts import (
    AccessContext, PolicyRouter, PrincipalKind, ResourceScope, RoutePolicy,
    create_policy_app, get_access_context,
)

# resolve_verified_context — будущий настоящий серверный resolver,
# а document_query — владелец tenant/resource SQL и доменных правил.
app = create_policy_app(context_resolver=resolve_verified_context)
router = PolicyRouter(context_resolver=resolve_verified_context)
policy = RoutePolicy(
    owner="documents", accepted_kinds={PrincipalKind.PARTNER},
    resource_type="document", action="read", required_scopes={"documents.read"},
    policy_version="1", tenant_required=True, security_scheme="ProductOAuth",
    required_fields={"title"},
)

@router.operation(
    "/documents/{document_id}", policy=policy, methods=["GET"],
    selector=lambda request: ResourceScope.selected([request.path_params["document_id"]]),
)
async def read_document(document_id: str, access: AccessContext = Depends(get_access_context)):
    return await document_query(document_id, access=access)

app.include_router(router, prefix="/v1")
```

Эти integration functions не реализованы примером. Без настоящего resolver
продуктовые операции подключать нельзя; пакет не выдаёт фиктивный admin context.

## Регистрация, includes, mounts и metadata

`create_policy_app` создаёт отдельную FastAPI-поверхность с `PolicyRouter`;
unannotated HTTP/native/WebSocket/callback routes отклоняются. WebSocket и
callbacks потребуют собственных adapters. Legacy routes не меняются и не
включаются автоматически.

Обычные FastAPI/APIRouter includes сохраняют bound `PolicyRoute` и resolver при
копировании маршрутов; это проверено реальными HTTP-запросами через два include.
Mounted policy applications сохраняют собственный guard. Рекурсивный
`policy_registry(app)` проверяет mounts, metadata, дубли route templates и
operationId, циклы и unknown/opaque ASGI routes. Factory повторяет проверку
при startup и обнаруживает позднее добавленные неразмеченные дочерние маршруты.

FastAPI 0.115.6 штатно пропускает Mount внутри `include_router`. Новый
`PolicyRouter.include_router` переносит их явно с сохранением порядка,
prefix и исходного lifecycle. Для surface с mounts используйте factory или
прямой `app.mount`; обычный внешний FastAPI.include_router по-прежнему имеет
своё upstream ограничение и не переносит mounts.

`security=[]`, `[{}]`, подмена security scheme или `x-access-policy` для private
операции отклоняются. Registry даёт path/method/operationId/owner/kinds,
tenant requirement, scopes, resource/action/fields и security scheme для curated
OpenAPI. Metadata сопровождает runtime enforcement, не заменяет его.
Пакет не публикует OpenAPI/docs HTTP endpoints; регистрация определения security
scheme и защищённого curated publisher остаётся M09–M11. Имя scheme не означает
готовый OAuth issuer или реализованный protocol flow.

## Проверка

Из `clearledger/server`:

```sh
PYTHONPATH="$PWD" /srv/projects/api-modernization-test-env-20261029/.venv/bin/python \
  -m pytest --noconftest -q tests/test_api_contracts_context.py tests/test_api_contracts_http.py
```

**90 PASS, 1.10 с**, Python 3.13.7, FastAPI 0.115.6 / Starlette 0.41.3.
Один исходный DeprecationWarning anyio BlockingPortal из Starlette TestClient.
Без conftest, БД, реальных credentials, сетевых API или запуска рабочего app.
Лог: `.artifacts/api-contracts-pytest.log`. Это целевой набор, не полный CI.

Покрыты 16 пересечений scope modes, selected empty/invalid, immutability,
principal/grant identity, independent resource/action/field gates, scopes и
company, invalid/revoked/stale context, fake admin, selectors и cross-tenant,
повторное решение resolver, guard до validation/dependencies/handler,
sync/async execution, nested includes, mounts/prefix/lifecycle, fail-closed
registration/startup, late mutation, циклы/дубли и security overrides.

Остались реальные token/grant resolver, persistence отзыва, delegation, новые
product routes и их domain/query интеграция, curated OpenAPI и независимая
приёмка. PR, merge и выпуск этой задачей не выполнялись.
