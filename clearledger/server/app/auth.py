"""
JWT-аутентификация: создание токена, верификация, dependency.
"""

import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Company, User, UserCompany
from app.utils import resolve_company_id

settings = get_settings()

# Хеширование паролей (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer-схема для Swagger UI
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Хеширует пароль bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет пароль против хеша."""
    return pwd_context.verify(plain, hashed)


# Сколько можно продлевать вход без пароля. Продление без предела давало токену вечную
# жизнь: однажды полученный (утёкший) токен обновлялся сам (аудит 07.10.2026).
MAX_SESSION_DAYS = 7


def create_access_token(user_id: str, email: str, tv: int = 0, auth_time: int | None = None,
                        *, extra: dict | None = None,
                        expires_at: datetime | None = None) -> str:
    """Создаёт JWT access-токен.

    `tv` — версия входа учётной записи (`User.token_version`): смена пароля, «выйти со
    всех устройств» и сброс сессий админом поднимают её, и все выданные токены гаснут.
    `at` — момент входа по паролю: продление его сохраняет, и сессия живёт не дольше
    `MAX_SESSION_DAYS` от настоящего входа.
    `extra` и `expires_at` — для сессии с областью действия (вход инженера по
    пропуску, `VISIT_SCOPE`): у неё своя компания и свой срок.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expires_at or now + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": now,
        "tv": int(tv or 0),
        "at": int(auth_time or now.timestamp()),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


# Метка входа для выдачи кода приложения (пункт 6 аудита 07.10.2026): nginx стека
# отдаёт основное приложение только с действующей меткой, остальным — публичную
# сборку (вход, ссылки). HttpOnly — скрипт страницы её не читает; для API она не
# годится (API по-прежнему по заголовку Authorization), поэтому подделка запросов
# с чужого сайта через неё невозможна.
GATE_COOKIE = "cl_gate"


def set_gate_cookie(response, token: str) -> None:
    response.set_cookie(
        GATE_COOKIE, token, max_age=settings.access_token_expire_minutes * 60,
        httponly=True, secure=settings.app_env == "prod", samesite="lax", path="/")


def clear_gate_cookie(response) -> None:
    response.delete_cookie(GATE_COOKIE, path="/")


async def gate_ok(token: str | None, db: AsyncSession) -> bool:
    """Метка входа действительна: подпись, срок, учётка есть, вход не отозван."""
    if not token:
        return False
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        uid = uuid.UUID(str(payload.get("sub")))
    except Exception:  # noqa: BLE001 — любая порча метки = «нет входа»
        return False
    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    return user is not None and session_valid(payload, user)


def token_for(user: "User", auth_time: int | None = None, **kw) -> str:
    """Токен для учётной записи с её текущей версией входа (`kw` — `extra`, `expires_at`)."""
    return create_access_token(str(user.id), user.email, user.token_version or 0, auth_time, **kw)


def session_valid(payload: dict, user: "User") -> bool:
    """Токен выпущен для текущей версии входа и не старше предела сессии."""
    if int(payload.get("tv") or 0) != int(user.token_version or 0):
        return False
    at = payload.get("at")
    if at is not None and datetime.now(timezone.utc).timestamp() - float(at) > MAX_SESSION_DAYS * 86400:
        return False
    return True
# ── Сессия инженера по пропуску ──────────────────────────────────────────────
#
# Инженер поставщика входит в пространство клиента по пропуску (space_bridge_router,
# `/eco/partner/visit`). Раньше пропуск менялся на обычный токен на сутки: без
# компании, без связи с подключением, и выключение подключения не закрывало уже
# открытые сессии. Теперь сессия помечена областью: `scp=visit`, компания `cid`,
# подключение `pvs`. На каждом запросе подключение сверяется заново, а доступ к
# компаниям, кроме `cid`, закрыт, даже если учётка с этим адресом состоит где-то ещё.
VISIT_SCOPE = "visit"
VISIT_SESSION_MINUTES = 60

# Компания сессии по пропуску на время запроса; None — обычная сессия.
_visit_company: ContextVar[uuid.UUID | None] = ContextVar("visit_company", default=None)
# Клеймы токена текущего запроса: нужны `/auth/refresh`, чтобы не превратить
# сессию с областью в обычную.
_token_claims: ContextVar[dict | None] = ContextVar("token_claims", default=None)


def visit_company() -> uuid.UUID | None:
    """Компания, которой ограничена сессия по пропуску; None — ограничения нет."""
    return _visit_company.get()


def current_token_claims() -> dict | None:
    return _token_claims.get()


def _install_visit_scope() -> None:
    """Сессия по пропуску видит только своё членство — во всех запросах сразу.

    Учётка гостя находится по адресу из чужого пропуска, и у неё могут быть членства
    в других компаниях контейнера. Проверка `assert_company_member` их закрывает, но
    членство читают ещё десятки ручек напрямую (`require_company_admin`, списки
    компаний, чаты). Поэтому сужение — на уровне ORM, как скоуп объектов
    (`scope.install_orm_scope`): пока запрос идёт по пропуску, любое чтение
    `user_companies` видит только компанию пропуска. Ставится при импорте, а не в
    lifespan: без него сессия по пропуску не должна существовать ни минуты.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session, with_loader_criteria

    @event.listens_for(Session, "do_orm_execute")
    def _apply(state):  # noqa: ANN001 — сигнатура события SQLAlchemy
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        cid = _visit_company.get()
        if cid is None:
            return
        state.statement = state.statement.options(
            with_loader_criteria(UserCompany, UserCompany.company_id == cid,
                                 include_aliases=True))


_install_visit_scope()


async def _check_visit(payload: dict, user: User, db: AsyncSession) -> uuid.UUID:
    """Сессия по пропуску жива, пока включено подключение, выдавшее пропуск."""
    from app.models import PartnerSpace

    denied = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                           detail="Сессия по пропуску закрыта")
    try:
        cid = uuid.UUID(str(payload.get("cid")))
        pid = uuid.UUID(str(payload.get("pvs")))
    except (TypeError, ValueError):
        raise denied
    partner = await db.get(PartnerSpace, pid)
    if (partner is None or partner.company_id != cid or partner.role != "vendor"
            or not partner.is_active or user.is_superadmin):
        raise denied
    m = await db.get(UserCompany, (user.id, cid))
    if m is None:
        raise denied
    return cid


def decode_token(token: str) -> dict:
    """Декодирует JWT. Бросает HTTPException при ошибке."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен истёк",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency: извлекает текущего пользователя из JWT.
    Возвращает объект User из БД.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен: отсутствует sub",
        )

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный ID пользователя в токене",
        )

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )
    if not session_valid(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия завершена — войдите заново",
        )

    _token_claims.set(payload)
    if payload.get("scp") == VISIT_SCOPE:
        _visit_company.set(await _check_visit(payload, user, db))
    elif payload.get("scp"):
        # Область, которой здесь не знают, — не повод пускать без ограничений.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Невалидный токен: неизвестная область")
    else:
        _visit_company.set(None)

    await _touch_presence(user, db)
    return user


# Как часто обновляем отметку присутствия. Писать на каждый запрос — лишняя нагрузка на
# БД, поэтому «тёплое» обновление: раз в PRESENCE_TOUCH_SECONDS активной работы. Кто
# сейчас в системе, определяется по свежести этой отметки (services/space_map).
PRESENCE_TOUCH_SECONDS = 120


async def _touch_presence(user: User, db: AsyncSession) -> None:
    """Отметить, что человек сейчас работает. Тихо: сбой отметки не ломает запрос."""
    now = datetime.now(timezone.utc)
    seen = user.last_seen_at
    if seen is not None:
        # В старых записях отметка могла лечь без таймзоны — сравниваем аккуратно.
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        if (now - seen).total_seconds() < PRESENCE_TOUCH_SECONDS:
            return
    try:
        user.last_seen_at = now
        await db.commit()
    except Exception:  # noqa: BLE001 — присутствие не важнее самого запроса
        await db.rollback()


async def assert_company_member(
    company_ref: str,
    user: User,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Резолвит company_ref (UUID|slug) в UUID и проверяет, что пользователь
    имеет к этой компании доступ.

    Суперадмин — доступ ко всем. Иначе требуется членство в user_companies.
    Бросает 400 при неизвестной компании, 403 при отсутствии членства.
    Единая точка проверки прав на компанию для всех эндпоинтов данных.

    Здесь же выставляется СКОУП ДАННЫХ запроса (`app/scope.py`) — объекты, которые
    участнику разрешено видеть. Место выбрано именно это: фильтр по объектам нужен
    десяткам ручек, и протаскивать его параметром — однажды забыть в одной и открыть
    данные. Пройти к данным компании мимо этой функции нельзя.
    """
    from app.scope import _as_ids, set_request_organization, set_request_scope

    cid = await resolve_company_id(company_ref, db)  # 400, если нет такой компании
    # Сессия по пропуску открыта ровно в одну компанию — раньше всех прочих правил.
    visit = _visit_company.get()
    if visit is not None and cid != visit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к компании",
        )
    if user.is_superadmin:
        set_request_scope(None)
        return cid
    m = (await db.execute(
        select(UserCompany).where(
            UserCompany.user_id == user.id,
            UserCompany.company_id == cid,
        )
    )).scalar_one_or_none()
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к компании",
        )
    # Админ компании видит всю сеть: иначе он не настроит то, чего не видит.
    set_request_scope(None if m.role == "admin" else _as_ids(m.object_scope))

    # Право на юрлицо СИЛЬНЕЕ выбора в интерфейсе: если человеку назначена
    # организация, заголовок её не переопределяет. Иначе достаточно подменить
    # `X-Organization-Id` руками, чтобы увидеть чужое юрлицо — а разрез по юрлицу
    # для аутсорсера это разные клиенты одного владельца.
    if m.role != "admin" and m.own_organization_id:
        set_request_organization(m.own_organization_id)
    return cid


def CompanyScope(query_param: str = "company_id"):
    """
    Фабрика FastAPI-зависимости для эндпоинтов, где company_id приходит в query.
    Достаёт company_id, проверяет членство, возвращает UUID компании.

    Использование:
        cid: uuid.UUID = Depends(CompanyScope())
    или через alias app.deps.CompanyDep.
    """

    async def _dep(
        company_id: str = Query(..., alias=query_param),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> uuid.UUID:
        return await assert_company_member(company_id, current_user, db)

    return _dep


async def resolve_member_modules(m: UserCompany, db: AsyncSession) -> list[str] | None:
    """Эффективный набор модулей члена: назначенная роль (role_id) приоритетнее
    ad-hoc modules. Возвращает None = полный доступ (admin / роль «Полный доступ»)."""
    if m.role == "admin":
        return None
    if m.role_id is not None:
        from app.models import CompanyRole
        role = await db.get(CompanyRole, m.role_id)
        if role is not None:
            return role.modules
    return m.modules


# Продукты пространства, покрывающие серверный модуль. Права раздаются ключами
# продуктов (`sales` — весь продукт, `sales:variances` — его пункт), а ручки
# гейтятся модулями Учёта (`management`): без карты любой явный набор получал
# в меню пункт, а от сервера — 403 «Доступ запрещён» на данные этого же пункта.
# Гранулярность до пункта остаётся клиентским гейтом (см. productAccess.ts) —
# сервер держит границу продукта, как и раньше держал границу модуля.
_MODULE_PRODUCTS: dict[str, tuple[str, ...]] = {
    "management": ("sales", "ops"),
    "store": ("shop",),
    "accounting": ("finance",),
    "financial": ("finance",),
    "tax": ("finance",),
}


def _module_allowed(module_key: str, mods: list[str]) -> bool:
    if module_key in mods or f"ledger:{module_key}" in mods or "ledger" in mods:
        return True
    for product in _MODULE_PRODUCTS.get(module_key, ()):
        if product in mods or any(k.startswith(product + ":") for k in mods):
            return True
    return False


async def check_module_access(
    user: User, cid: uuid.UUID, db: AsyncSession, module_key: str
) -> None:
    """RBAC-проверка модуля для УЖЕ резолвнутой компании (когда cid получен из
    X-Company-Id через scope_company_id). Полный доступ: суперадмин, admin-член,
    эффективные modules=NULL. Иначе 403, если ни module_key, ни покрывающий его
    продукт (или пункт продукта) не входят в разрешённые.
    Используется гейтом роутеров со скоупом «по юзеру» (store и т.п.)."""
    if user.is_superadmin:
        return
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role == "admin":
        return
    mods = await resolve_member_modules(m, db)
    if mods is None:
        return
    if not _module_allowed(module_key, mods):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к модулю",
        )


async def assert_company_module(
    company_ref: str, user: User, db: AsyncSession, module_key: str
) -> uuid.UUID:
    """assert_company_member + RBAC-проверка модуля.

    Полный доступ (без проверки): суперадмин, admin-член, эффективные modules=NULL.
    Иначе 403, если module_key не в разрешённых модулях (с учётом роли).
    """
    cid = await assert_company_member(company_ref, user, db)  # membership + 403
    await check_module_access(user, cid, db, module_key)
    return cid


async def assert_company_product(
    company_ref: str, user: User, db: AsyncSession, product_code: str
) -> uuid.UUID:
    """assert_company_member + право на ПРОДУКТ пространства (`pulse`, `projects`…).

    Отличие от assert_company_module: там ручка гейтится модулем Учёта и ключ
    `ledger` открывает её целиком. Продукт — самостоятельное рабочее место, и
    доступ к Учёту прав на него не даёт. Полный доступ по-прежнему у суперадмина,
    admin-члена и роли без ограничения набора.

    Нужно там, где данные продукта шире его экрана: «Пульс» отдаёт выручку сети,
    нарушения SLA и поимённую активность людей, а в пространстве есть внешние
    участники — членства в компании для такого среза мало.
    """
    cid = await assert_company_member(company_ref, user, db)  # membership + 403
    if user.is_superadmin:
        return cid
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role == "admin":
        return cid
    mods = await resolve_member_modules(m, db)
    if mods is None:  # роль «Полный доступ»
        return cid
    # Ключ продукта целиком (`pulse`) или любой его пункт (`pulse:team`).
    if product_code in mods or any(k.startswith(product_code + ":") for k in mods):
        return cid
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Нет доступа к продукту",
    )


async def assert_company_item(
    company_ref: str, user: User, db: AsyncSession, product_code: str, item: str
) -> uuid.UUID:
    """То же, но с правом на КОНКРЕТНЫЙ пункт продукта (`perimeter:pr_cash`).

    `assert_company_product` пропускает по любому пункту продукта: право на один экран
    открывает все ручки рабочего места. Для большинства продуктов это и задумано —
    разрезы одного и того же. Но там, где пункты выдаются раздельно по существу
    («Наличные» и «Люди» в «Периметре»: имена, телефоны и суммы наличных расчётов
    видит не каждый, кому открыт продукт), прятать данные одним лишь меню нельзя.
    """
    cid = await assert_company_member(company_ref, user, db)
    if user.is_superadmin:
        return cid
    m = await db.get(UserCompany, (user.id, cid))
    if m is None or m.role == "admin":
        return cid
    mods = await resolve_member_modules(m, db)
    if mods is None:  # роль «Полный доступ»
        return cid
    if product_code in mods or f"{product_code}:{item}" in mods:
        return cid
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Нет доступа к этому разделу продукта",
    )


def CompanyModuleScope(module_key: str, query_param: str = "company_id"):
    """Как CompanyScope, но дополнительно требует доступ к модулю module_key (RBAC)."""

    async def _dep(
        company_id: str = Query(..., alias=query_param),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> uuid.UUID:
        return await assert_company_module(company_id, current_user, db, module_key)

    return _dep


# Ключ, привязанный к станции, — это ключ её агента: ему открыт только обмен агента
# (`/api/edge/*`, `/api/dedup-ingest/*`). Раньше ключ одной АЗС проходил все ручки
# по внешнему ключу компании, включая данные всех станций (аудит 07.10.2026).
STATION_KEY_PATHS = ("/api/edge/", "/api/dedup-ingest/")


def legacy_key_value(raw: str) -> str:
    """Как общий ключ компании хранится в `companies.cloud_api_key`: хешем, не текстом."""
    import hashlib
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
# Области именных ключей. Ключ с областью открывает только ручки своей области,
# ключ без области — общие машинные ручки, как раньше (get_company_by_api_key).
KEY_SCOPES = {
    # Узел «Телефонии» у заказчика: кто звонит и что у него сейчас (ContactHub, Я-1, Я-2).
    "voice.identify": "Узел «Телефонии»: опознание звонящего и сводка клиента",
    # Внешняя система заказчика (мониторинг, BI) меняет ключ на служебный токен
    # `aud=voice` и с ним читает API узла без ПДн (`sso.VOICE_SERVICE_SCOPES`).
    "voice.stats": "Система: статистика, здоровье и метрики узла «Телефонии»",
    "voice.audit": "Система: журнал доступа узла «Телефонии» к ПДн",
}


# Как часто имеет смысл записывать «ключом пользовались».
#
# Отметка нужна с точностью до минуты — её показывают как «последнее обращение»
# на экране подключений. А писалась она В ОДНУ СТРОКУ на каждый входящий запрос:
# на gig это 204 971 обновление на восемь ключей. Пока транзакция запроса не
# закрыта, строка ключа заблокирована, и все обращения по тому же ключу ждут её.
# 25.10.2026 одна зависшая транзакция (`idle in transaction`, девять минут) так
# остановила всё пространство: пятнадцать запросов стояли в очереди по четыре
# минуты и отваливались по `statement_timeout`, в журнале 288 ошибок за четыре
# минуты. Строка-счётчик на горячем пути — это точка сериализации всего обмена.
#
# Пишем не чаще раза в минуту: очередь исчезает, смысл отметки сохраняется.
KEY_TOUCH_INTERVAL = timedelta(minutes=1)


def touch_key_used(key) -> None:
    """Отметить обращение по ключу, но не чаще раза в минуту."""
    now = datetime.now(timezone.utc)
    if key.last_used_at is None or now - key.last_used_at > KEY_TOUCH_INTERVAL:
        key.last_used_at = now


async def _named_key(raw: str, db: AsyncSession):
    import hashlib

    from app.models import SpaceInboundKey
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return (await db.execute(
        select(SpaceInboundKey).where(
            SpaceInboundKey.key_hash == key_hash,
            SpaceInboundKey.revoked_at.is_(None),
        )
    )).scalar_one_or_none()


def CompanyByKeyScope(scope: str):
    """Зависимость: именной ключ с областью `scope` → (компания, ключ).

    Легаси-ключ компании и ключи без области сюда не проходят: они общие, а ручки
    с областью отдают то, что общему потребителю не положено (ПДн звонящего)."""
    assert scope in KEY_SCOPES, scope

    async def _dep(
        x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
        db: AsyncSession = Depends(get_db),
    ):
        named = await _named_key(x_cloud_api_key, db) if x_cloud_api_key else None
        if named is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Невалидный API-ключ")
        if scope not in (named.scopes or []):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Ключ выдан без области {scope}")
        company = await db.get(Company, named.company_id)
        if company is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Невалидный API-ключ")
        touch_key_used(named)
        return company, named

    return _dep


async def get_company_by_api_key(
    request: Request,
    x_cloud_api_key: str = Header(..., alias="X-Cloud-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Company:
    """
    FastAPI dependency: аутентификация по X-Cloud-API-Key.
    Используется внешними системами (TSupport, дедуп-нода, edge-агенты).

    Сначала именные ключи (space_inbound_keys, по SHA256-хешу: видно, КТО ходит,
    и любого можно отозвать отдельно), затем легаси-ключ компании — он один на
    всех и остаётся, пока настроенные внешние узлы не переведены на именные.
    Ключ с областью (`KEY_SCOPES`) сюда не проходит: он выдан под свои ручки.
    """
    if not x_cloud_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется X-Cloud-API-Key",
        )

    named = await _named_key(x_cloud_api_key, db)
    if named is not None and named.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ключ выдан для другой области",
        )
    if named is not None:
        if named.station_id is not None and not request.url.path.startswith(STATION_KEY_PATHS):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Ключ станции не даёт доступа к этой ручке")
        touch_key_used(named)
        company = await db.get(Company, named.company_id)
        if company is not None:
            return company

    # Общий ключ компании — хешем; открытым текстом он лежал до 07.10.2026 и
    # переводится в хеш при запуске (database.py).
    result = await db.execute(
        select(Company).where(Company.cloud_api_key == legacy_key_value(x_cloud_api_key))
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный API-ключ",
        )

    return company
