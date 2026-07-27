"""Скоуп данных: какие ОБЪЕКТЫ пространства видит участник компании.

Права (`modules`) отвечают на вопрос «какие экраны человеку открыты», скоуп — «по
каким объектам он видит данные». Подрядчику нужен «Парк оборудования», но только на
своих станциях; директору филиала — вся его площадка целиком, включая деньги.

Хранение — `user_companies.object_scope` (список `service_locations.id`; NULL = вся
сеть компании). Скоуп есть только у обычного участника: суперадмин и админ компании
видят всё — иначе администратор не смог бы настроить то, чего не видит.

⚠ **`service_locations.id` — строка (клиентский nanoid `ezs-7b09aa…`), а не UUID.**
Отсюда сравнения строками: приведение к `uuid.UUID` молча отбрасывало бы все реальные
id и оставляло скоуп пустым.

## Как скоуп доезжает до запросов

`assert_company_member` — единственная дверь к данным компании — кладёт скоуп текущего
запроса в contextvar, а запросы читают его через `current_object_scope()`. Сделано так
намеренно: фильтр по станциям живёт в 56 ручках восьми роутеров, и протаскивать в
каждую ещё один параметр — 56 шансов забыть один и открыть данные. Контекст ставится
в той же точке, где проверяется членство, поэтому «прошёл проверку компании, но забыл
скоуп» невозможно.

# ponytail: contextvar — неявная связь; если появится второй способ входа в данные
# (фоновая задача, экспорт по api-key), скоуп надо ставить и там — искать по
# `set_request_scope`.

Что скоуп НЕ покрывает (осознанно, до отдельного решения по каждому пункту):
- агрегаты не по `charge_sessions`/`service_locations` (сверка, 1С-выгрузка, документы);
- данные в приложениях-разрезах: у Поддержки свой контур, туда скоуп поедет проекцией;
- ручки по api-key (`get_company_by_api_key`) — машинный доступ, не участник.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceLocation, User, UserCompany

# Скоуп текущего запроса: None = без ограничений, список id объектов = только они.
_current_scope: ContextVar[list[str] | None] = ContextVar("object_scope", default=None)


def set_request_scope(ids: list[str] | None) -> None:
    """Задать скоуп текущего запроса (вызывается из `assert_company_member`)."""
    _current_scope.set(ids)


def current_object_scope() -> list[str] | None:
    """Объекты, разрешённые текущему запросу. None = вся сеть компании."""
    return _current_scope.get()


def _as_ids(raw) -> list[str] | None:
    """Нормализовать хранимый набор к списку строковых id.

    Пустой набор → None (вся сеть), а не «ничего»: случайно сохранённый пустой
    список молча отрезал бы человека от всех данных.
    """
    if not raw:
        return None
    out = [str(v).strip() for v in raw if str(v).strip()]
    return out or None


async def resolve_object_scope(
    user: User, company_id: uuid.UUID, db: AsyncSession
) -> list[str] | None:
    """Объекты, доступные человеку в компании. None = вся сеть."""
    if user.is_superadmin:
        return None
    m = await db.get(UserCompany, (user.id, company_id))
    if m is None or m.role == "admin":
        return None
    return _as_ids(m.object_scope)


def scope_location_conds(column) -> list:
    """Условия сужения по объектам для колонки-ссылки (`*.location_id`, `id`).

    Возвращает список для `.where(*conds)`: пустой, если скоупа нет. Строки без
    объекта (`location_id IS NULL`) в суженном режиме не показываются — они относятся
    ко всей сети, а человек со скоупом видит только своё.
    """
    ids = current_object_scope()
    return [column.in_(ids)] if ids else []


def scope_station_codes(db_codes: list[str] | None = None) -> list[str] | None:
    """Заглушка совместимости: коды станций скоупа берутся запросом там, где нужны."""
    return db_codes


async def scope_codes(db: AsyncSession, company_id) -> list[str] | None:
    """Коды станций скоупа (для агрегатов, где ключ — `station_code`, а не id)."""
    ids = current_object_scope()
    if not ids:
        return None
    rows = (await db.execute(select(ServiceLocation.code).where(
        ServiceLocation.company_id == company_id, ServiceLocation.id.in_(ids)
    ))).scalars().all()
    return [c for c in rows if c]


def in_scope(location_id) -> bool:
    """Виден ли конкретный объект (для одиночных карточек и проверок принадлежности)."""
    ids = current_object_scope()
    if not ids:
        return True
    return location_id is not None and str(location_id) in ids


# ── Сужение raw-SQL витрин ───────────────────────────────────────────────────
#
# Аналитические витрины считаются сырым SQL и мимо ORM-события проходят. Фрагмент и
# параметры добавляются в те же `_scope*`-хелперы сервисов, где живёт сужение по
# выбранным станциям, — там оно уже собирается в одном месте на файл.

ACL_PARAM = "acl_objects"


def acl_sql(column: str = "location_id") -> str:
    """AND-фрагмент сужения по скоупу для raw-SQL (пустой, если скоупа нет)."""
    return f" AND {column} = ANY(:{ACL_PARAM})" if current_object_scope() else ""


def acl_params() -> dict:
    """Параметры к `acl_sql` — подмешиваются в словарь bind-параметров запроса."""
    ids = current_object_scope()
    return {ACL_PARAM: ids} if ids else {}


# ── Автоматическое сужение ORM-запросов ──────────────────────────────────────

def install_orm_scope() -> None:
    """Повесить скоуп на ВСЕ ORM-запросы к объектам и сессиям зарядки.

    Без этого фильтр надо помнить в каждой ручке — и он забывается: `count_sessions`
    считал по всей сети, потому что там не было пользовательского фильтра станций,
    а значит и точки, куда скоуп подмешивался. `with_loader_criteria` добавляет
    условие всякий раз, когда сущность участвует в запросе, включая агрегаты
    (`select(func.count()).select_from(ChargeSession)`) и `db.get()`.

    Не покрывает raw-SQL (`text(...)`) — там сужение живёт в `_scope*`-фрагментах
    сервисов; см. `services/overview_insights.py` и соседние.
    """
    from sqlalchemy import event
    from sqlalchemy.orm import Session, with_loader_criteria

    from app.models import ChargeSession

    @event.listens_for(Session, "do_orm_execute")
    def _apply(state):  # noqa: ANN001 — сигнатура события SQLAlchemy
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        ids = current_object_scope()
        if not ids:
            return
        state.statement = state.statement.options(
            with_loader_criteria(ServiceLocation, ServiceLocation.id.in_(ids),
                                 include_aliases=True),
            with_loader_criteria(ChargeSession, ChargeSession.location_id.in_(ids),
                                 include_aliases=True),
        )
