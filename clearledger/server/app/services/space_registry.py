"""Реестр объектов пространства (docs/SPACE.md §5).

Объект компании — общая сущность пространства: на него ссылаются ВСЕ приложения-разрезы
(заявка Координатора и смена Учёта об одной и той же АЗС). Поэтому у объекта один
владелец — компания, и один канонический адрес — `/api/registry/objects`.

Физически данные лежат в той же таблице `service_locations`, что и раньше: реестр — это
подъём существующей сущности в статус общей, а не вторая копия объектов. Разница в
контракте: здесь отдаётся ТОЛЬКО паспорт пространства (код, наименование, тип, статус,
адрес, гео, регион). Прикладные атрибуты (ЭЗС-паспорт: мощность, коннекторы, OCPP;
привязки к источникам) остаются приложению и через реестр не ходят.

Скоуп — всегда компания: `code` уникален в пределах компании, запрос без компании
невозможен (см. роутер). В мультикомпанийном контейнере это единственное, что не даёт
объектам одной компании утечь другой.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditEvent, Contract, ContractLocation, Counterparty, EzsEquipmentUnit, ServiceLocation,
)

# Типы объектов пространства (совпадают с ServiceLocation.type).
OBJECT_TYPES = {"fuel_station", "ev_charging", "retail", "office", "warehouse", "other"}
# Жизненный цикл карточки. Операционное состояние (работает/ремонт) — прикладное,
# им управляет разрез, а не реестр.
OBJECT_STATUSES = {"active", "planned", "closed"}


def to_card(loc: ServiceLocation) -> dict[str, Any]:
    """Паспорт объекта пространства — без прикладных полей разрезов."""
    return {
        "id": loc.id,
        "companyId": str(loc.company_id),
        "code": loc.code,
        "name": loc.name,
        "type": loc.type,
        "status": loc.status,
        # Операционное состояние отдаём только для чтения: разрезам удобно видеть его
        # рядом с паспортом, но менять — через API приложения, не через реестр.
        "operationalStatus": getattr(loc, "operational_status", "unknown") or "unknown",
        # Адрес у объекта пространства необязателен (паспорт бывает неполным), а
        # приёмник вправе требовать его непустым (в Координаторе `locations.address`
        # NOT NULL). Отдаём пустую строку, а не null: смысл «адрес не указан» тот же,
        # но одна неполная карточка не роняет проекцию всего реестра.
        "address": loc.address or "",
        "city": getattr(loc, "city", None),
        "street": getattr(loc, "street", None),
        "house": getattr(loc, "house", None),
        "latitude": getattr(loc, "latitude", None),
        "longitude": getattr(loc, "longitude", None),
        "regionId": str(loc.region_id) if getattr(loc, "region_id", None) else None,
        "description": loc.description,
        "createdAt": loc.created_at.isoformat() if loc.created_at else "",
        "updatedAt": loc.updated_at.isoformat() if loc.updated_at else "",
    }


async def list_objects(
    db: AsyncSession, company_id: uuid.UUID, *, status: str | None = None,
    type_: str | None = None, query: str | None = None,
) -> list[dict[str, Any]]:
    """Объекты компании, отсортированные по коду.

    Со скоупом данных участник видит здесь только выданные ему объекты: реестр —
    тот же список сети, открытый из «Управления». Проекция в приложения идёт от
    админа, у которого скоупа нет, и остаётся полной.
    """
    from app.scope import scope_location_conds

    stmt = select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        *scope_location_conds(ServiceLocation.id),
    )
    if status:
        stmt = stmt.where(ServiceLocation.status == status)
    if type_:
        stmt = stmt.where(ServiceLocation.type == type_)
    if query:
        like = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            ServiceLocation.code.ilike(like) | ServiceLocation.name.ilike(like)
        )
    res = await db.execute(stmt.order_by(ServiceLocation.code))
    return [to_card(l) for l in res.scalars().all()]


async def get_object(
    db: AsyncSession, company_id: uuid.UUID, object_id: str,
) -> dict[str, Any] | None:
    loc = await _load(db, company_id, object_id)
    return to_card(loc) if loc else None


async def _load(
    db: AsyncSession, company_id: uuid.UUID, object_id: str,
) -> ServiceLocation | None:
    """Объект строго в пределах компании и скоупа: чужой id даёт None, а не карточку."""
    from app.scope import scope_location_conds

    res = await db.execute(select(ServiceLocation).where(
        ServiceLocation.id == object_id, ServiceLocation.company_id == company_id,
        *scope_location_conds(ServiceLocation.id)))
    return res.scalar_one_or_none()


async def code_taken(
    db: AsyncSession, company_id: uuid.UUID, code: str, *, except_id: str | None = None,
) -> bool:
    """Код уникален в пределах КОМПАНИИ: у двух компаний холдинга может быть своя «Площадка 1»."""
    stmt = select(ServiceLocation.id).where(
        ServiceLocation.company_id == company_id, ServiceLocation.code == code)
    if except_id:
        stmt = stmt.where(ServiceLocation.id != except_id)
    return (await db.execute(stmt)).first() is not None


async def create_object(
    db: AsyncSession, company_id: uuid.UUID, data: dict[str, Any], *, actor: Any | None,
) -> dict[str, Any]:
    loc = ServiceLocation(
        id=uuid.uuid4().hex[:24],          # id — строка (исторически клиентский nanoid)
        company_id=company_id,
        code=data["code"].strip(),
        name=data["name"].strip(),
        type=data.get("type") or "other",
        status=data.get("status") or "active",
        address=data.get("address"),
        description=data.get("description"),
        source_bindings=[],
    )
    _apply_optional(loc, data)
    db.add(loc)
    await db.flush()
    await _audit(db, company_id, actor, "space.object.create", loc, {"code": loc.code})
    await db.commit()
    await db.refresh(loc)
    return to_card(loc)


async def update_object(
    db: AsyncSession, company_id: uuid.UUID, object_id: str, data: dict[str, Any],
    *, actor: Any | None,
) -> dict[str, Any] | None:
    loc = await _load(db, company_id, object_id)
    if loc is None:
        return None

    changed: dict[str, Any] = {}
    for field in ("code", "name", "type", "status", "address", "description"):
        if field in data and data[field] is not None and getattr(loc, field) != data[field]:
            changed[field] = {"from": getattr(loc, field), "to": data[field]}
            setattr(loc, field, data[field].strip() if isinstance(data[field], str) else data[field])
    _apply_optional(loc, data, changed)

    if changed:
        await _audit(db, company_id, actor, "space.object.update", loc, changed)
    await db.commit()
    await db.refresh(loc)
    return to_card(loc)


def _apply_optional(
    loc: ServiceLocation, data: dict[str, Any], changed: dict[str, Any] | None = None,
) -> None:
    """Адрес и гео — часть паспорта пространства, поэтому правятся через реестр."""
    for field, key in (("city", "city"), ("street", "street"), ("house", "house"),
                       ("latitude", "latitude"), ("longitude", "longitude")):
        if key in data and data[key] is not None:
            if changed is not None and getattr(loc, field, None) != data[key]:
                changed[field] = {"from": getattr(loc, field, None), "to": data[key]}
            setattr(loc, field, data[key])


async def list_organizations(
    db: AsyncSession, company_id: uuid.UUID, *, query: str | None = None,
) -> list[dict[str, Any]]:
    """Организации компании — общие карточки юрлиц (docs/SPACE.md §3).

    Источник — `counterparties`: контрагенты уже ведутся в Учёте, реестр даёт им общий
    контракт. В карточку идут только реквизиты; РОЛЬ юрлица («поставщик топлива»,
    «подрядчик») остаётся прикладной и в реестр не поднимается.
    """
    stmt = select(Counterparty).where(Counterparty.company_id == company_id)
    if query:
        like = f"%{query.strip().lower()}%"
        stmt = stmt.where(Counterparty.name.ilike(like) | Counterparty.inn.ilike(like))
    res = await db.execute(stmt.order_by(Counterparty.name))
    return [{
        "id": str(c.id),
        "name": c.name,
        "shortName": c.short_name,
        "inn": c.inn,
        "kpp": c.kpp,
        "type": c.type,
        "legalAddress": getattr(c, "legal_address", None),
        "phone": getattr(c, "phone", None),
        "email": getattr(c, "email", None),
    } for c in res.scalars().all()]


# Направление обязательства по ВидуДоговора 1С (`Contract.kind`). Реестр договоров один
# на компанию, и в нём соседствуют обе стороны: кому компания платит (аренда участка,
# энергоснабжение, обслуживание) и кто платит компании (зарядка корпоративным клиентам,
# поставка). Отдельной колонки в БД нет — направление выводится из вида договора, чтобы
# не заводить второй источник правды и не мигрировать уже загруженные реестры.
_DIRECTION_BY_KIND = {
    "СПоставщиком": "in", "СКомитентом": "in", "СКомитентомНаЗакупку": "in",
    "СКомиссионеромНаЗакупку": "in", "СТранспортнойКомпанией": "in",
    "СФакторинговойКомпанией": "in", "ЗаемПолученный": "in",
    "СПокупателем": "out", "СКомиссионером": "out",
}


def contract_direction(kind: str | None) -> str:
    """in — компания платит, out — платят компании, unknown — вид не задан."""
    return _DIRECTION_BY_KIND.get(kind or "", "unknown")


async def list_contracts(
    db: AsyncSession, company_id: uuid.UUID, *,
    query: str | None = None, direction: str | None = None,
) -> list[dict[str, Any]]:
    """Договоры компании — общая сущность пространства (docs/SPACE.md §3).

    Источник — `contracts`: та же ось контрагент↔договор↔объекты, что ведёт Учёт. Реестр
    добавляет к ней одно: контрагент уже РАЗРЕШЁН в имя. В самой таблице он лежит
    идентификатором 1С (`external_ref`) либо нашим UUID, и каждый разрез, которому нужен
    договор (эксплуатация — аренда и энергоснабжение, корпоратив — договоры ЮЛ, Координатор —
    обслуживание), повторял бы этот джойн у себя.

    База договоров одна на компанию — входящие и исходящие, любых типов. Кому какие
    видны — вопрос прав в приложении, а не отдельного реестра: разрез фильтрует то, что
    отдаёт эта ручка, но не заводит своих договоров.

    Суммы, взаиморасчёты и платёжная дисциплина не поднимаются: это прикладное, у них
    свои разрезы (`station_contract_settlements`, документы Финансов).
    """
    cps = (await db.execute(
        select(Counterparty).where(Counterparty.company_id == company_id))).scalars().all()
    by_key = {k: c for c in cps for k in (c.external_ref, str(c.id)) if k}

    covered = dict((await db.execute(
        select(ContractLocation.contract_id, func.count())
        .where(ContractLocation.company_id == company_id)
        .group_by(ContractLocation.contract_id))).all())

    stmt = select(Contract).where(Contract.company_id == company_id)
    if query:
        like = f"%{query.strip().lower()}%"
        stmt = stmt.where(Contract.number.ilike(like) | Contract.type.ilike(like))
    res = await db.execute(stmt.order_by(Contract.is_closed, Contract.date.desc()))
    out: list[dict[str, Any]] = []
    for c in res.scalars().all():
        dir_ = contract_direction(c.kind)
        if direction and dir_ != direction:
            continue
        cp = by_key.get(c.counterparty_id)
        out.append({
            "id": str(c.id),
            "number": c.number,
            "date": c.date,
            "type": c.type,
            "kind": c.kind,
            "direction": dir_,
            "basis": c.basis,
            "counterpartyId": str(cp.id) if cp else None,
            "counterpartyName": cp.name if cp else None,
            "counterpartyInn": cp.inn if cp else None,
            # company — весь периметр, locations — набор объектов, unassigned — охват не задан.
            "scopeType": c.scope_type,
            "objectsCount": covered.get(c.id, 0),
            "validUntil": c.valid_until,
            "isClosed": c.is_closed,
        })
    return out


async def list_equipment(
    db: AsyncSession, company_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Единицы оборудования компании — паспорт (что за железо и где стоит).

    Сервисная история, ремонты и амортизация — прикладные, остаются в разрезах.
    Единицы без привязки к объекту тоже отдаём: приложение решит, принимать ли их
    (Координатору железо без площадки не нужно).
    """
    res = await db.execute(
        select(EzsEquipmentUnit).where(EzsEquipmentUnit.company_id == company_id)
        .order_by(EzsEquipmentUnit.serial_number))
    return [{
        "id": str(u.id),
        "ecoObjectId": u.current_location_id,
        "type": u.kind or "station",
        "model": u.model,
        "manufacturer": u.vendor,
        "serialNumber": u.serial_number,
        "inventoryNumber": u.inventory_number,
        "status": "active" if (u.state or "").startswith("installed") else "storage",
        "state": u.state,
        "warrantyUntil": u.warranty_until,
    } for u in res.scalars().all()]


async def _audit(
    db: AsyncSession, company_id: uuid.UUID, actor: Any | None,
    action: str, loc: ServiceLocation, details: dict[str, Any],
) -> None:
    """Реестр обязан помнить, кто и когда изменил карточку — иначе расхождения не разобрать."""
    db.add(AuditEvent(
        company_id=company_id,
        user_id=str(actor.id) if actor else "system",
        user_name=(getattr(actor, "name", None) or getattr(actor, "email", None)) if actor else "система",
        action=action,
        details=json.dumps(
            {"objectId": loc.id, "objectCode": loc.code, "objectName": loc.name, **details},
            ensure_ascii=False, default=str),
    ))
