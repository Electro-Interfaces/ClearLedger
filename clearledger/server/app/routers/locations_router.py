"""
CRUD для ServiceLocation (точки обслуживания) — АЗС/магазины/офисы/склады.

Перенесено из localStorage фронта в бэкенд: точки общие для всех браузеров и
совпадают с конфигом каналов. Публичный (как sources/channels), company-scoped.
id — клиентский nanoid (String), чтобы фронт и бэк совпадали.
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_company_by_api_key, get_current_user
from app.database import get_db
from app.deps import CompanyDep, get_owned
from app.models import AuditEvent, Company, ServiceLocation, User, location_bindings
from app.scope import in_scope, scope_location_conds
from app.services import hubex_service

# decommissioned входит в белый список: раньше значение существовало только как
# продукт ингеста CPO («Выведена из эксплуатации»), а ручная смена и демонтаж
# оборудования (складской контур) выставить его не могли — асимметрия.
# no_link/disabled — статусы CPO «Нет связи»/«Отключена»: показывают текущее
# состояние станции и раньше схлопывались в unknown/not_working, теряя смысл.
OP_STATUSES = {"working", "no_link", "disabled", "not_working", "on_repair",
               "maintenance", "unknown", "decommissioned"}

router = APIRouter(prefix="/locations", tags=["Точки обслуживания"])


class LocationIn(BaseModel):
    id: str
    company_id: str
    code: str
    name: str
    type: str = "other"
    status: str = "active"
    address: str | None = None
    description: str | None = None
    sourceBindings: list[Any] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class LocationUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    type: str | None = None
    status: str | None = None
    address: str | None = None
    description: str | None = None
    sourceBindings: list[Any] | None = None
    metadata: dict[str, Any] | None = None


class LocationOut(BaseModel):
    id: str
    code: str
    name: str
    type: str
    status: str
    operationalStatus: str = "unknown"
    address: str | None = None
    description: str | None = None
    sourceBindings: list[Any]
    metadata: dict[str, Any] | None = None
    # Нормализованный паспорт L2 (типизированные колонки) — заполнен для объектов ЭЗС
    # (type=ev_charging), NULL для прочих. Приходит из нормализации канала «Справочник станций».
    passport: dict[str, Any] | None = None
    createdAt: str
    updatedAt: str


def _passport(l: ServiceLocation) -> dict[str, Any] | None:
    """Типизированный паспорт (L2) объекта → dict непустых полей, либо None."""
    fields = {
        "serialNumber": getattr(l, "serial_number", None),
        "stationNumber": getattr(l, "station_number", None),
        "city": getattr(l, "city", None), "street": getattr(l, "street", None),
        "house": getattr(l, "house", None),
        "latitude": getattr(l, "latitude", None), "longitude": getattr(l, "longitude", None),
        "powerKwt": getattr(l, "power_kwt", None),
        "connectorsCount": getattr(l, "connectors_count", None),
        "connectorTypes": getattr(l, "connector_types", None),
        "owner": getattr(l, "owner", None), "ownerId": getattr(l, "owner_id", None),
        "brand": getattr(l, "brand", None), "model": getattr(l, "model", None),
        "ocppProtocol": getattr(l, "ocpp_protocol", None), "firmware": getattr(l, "firmware", None),
        "stage": getattr(l, "stage", None), "isTest": getattr(l, "is_test", None),
        "hubexAssetId": getattr(l, "hubex_asset_id", None),
        "hubexLinkStatus": getattr(l, "hubex_link_status", None),
        "rating": getattr(l, "rating", None), "successPct": getattr(l, "success_pct", None),
        "regionId": str(l.region_id) if getattr(l, "region_id", None) else None,
        # атрибуты из сводной выработки (слот obshaya, v2.14)
        "locationClass": getattr(l, "location_class", None),
        "speedClass": getattr(l, "speed_class", None),
        "installedOn": getattr(l, "installed_on", None),
        "decommissionedOn": getattr(l, "decommissioned_on", None),
        "inventoryNumber": getattr(l, "inventory_number", None),
        "isCorp": True if getattr(l, "is_corp", False) else None,
    }
    out = {k: v for k, v in fields.items() if v is not None}
    return out or None


# Ключи снимка, которые ведут конвейеры загрузки, а не человек в форме:
# по ним карточка находится при следующей выгрузке. Правка объекта из интерфейса
# присылает `metadata` целиком, и до 12.08.2026 запись заменяла снимок ЦЕЛИКОМ —
# редактирование одного поля сносило `asuimStationId`/`hubexAssetId`/историю
# номеров, карточка выпадала из индексов витрины и заводилась заново дублем.
_SERVICE_META_KEYS = {
    "ext_id", "stationId", "ocppId", "ocppUrl", "source", "nameSource",
    "nameHistory", "numberHistory", "zoi1", "buNumber", "connectorsSource",
}


# Ключи, которые человек ЗАПОЛНЯЕТ руками, но которые нельзя терять, если форма
# их не прислала: привязка к активу HubEx заводится вручную (поля типа
# «Электрозарядная станция»), а стирать её молчаливым PATCH-ем нельзя.
_EDITABLE_LINK_KEYS = {"hubexAssetId", "hubexName", "hubexNote", "linkStatus",
                       "zoi1", "buNumber", "ocppUrl"}


def _is_service_meta(key: str, value: Any) -> bool:
    """Служебный ключ снимка: его ведёт загрузка, форма его не трогает вовсе.

    Структурные значения (списки/словари: `connectors`, история) тоже служебные —
    форма их всё равно не редактирует и присылает обратно потерянными."""
    return (key.startswith("asuim")
            or key in _SERVICE_META_KEYS
            or isinstance(value, (dict, list)))


def _merge_metadata(current: dict | None, incoming: dict | None) -> dict | None:
    """Снимок после правки из интерфейса: служебное — из базы, остальное — из формы.

    Три категории: служебные ключи загрузки берутся только из базы; ключи связи
    (`hubexAssetId` и соседи) — из формы, если она их прислала, иначе из базы;
    все прочие — только из формы, поэтому очистка поля по-прежнему работает."""
    cur, inc = current or {}, incoming or {}
    kept = {k: v for k, v in cur.items()
            if _is_service_meta(k, v) or (k in _EDITABLE_LINK_KEYS and k not in inc)}
    edited = {k: v for k, v in inc.items() if not _is_service_meta(k, v)}
    merged = {**kept, **edited}
    return merged or None


def _sync_station_number(loc: ServiceLocation) -> None:
    """Номер из формы — в колонку паспорта, а не только в снимок.

    Поле «Номер станции» правится через `metadata.number`, а резолв сессий идёт по
    колонке `station_number`. Без синхронизации правка выглядела применённой, но
    заезды продолжали ходить по старому номеру."""
    num = (loc.extra_metadata or {}).get("number")
    num = str(num).strip() if num is not None else ""
    if num and str(loc.station_number or "").strip() != num:
        loc.station_number = num[:60]


async def _assert_code_free(db: AsyncSession, company_id, code: str, except_id: str | None = None):
    """Код объекта уникален в компании (уникальный индекс v2.16) — 409 вместо 500."""
    stmt = select(ServiceLocation.id).where(
        ServiceLocation.company_id == company_id, ServiceLocation.code == code,
        ServiceLocation.is_test.is_(False))
    if except_id:
        stmt = stmt.where(ServiceLocation.id != except_id)
    if (await db.execute(stmt)).first():
        raise HTTPException(409, f"Код «{code}» уже занят другим объектом компании")


def _out(l: ServiceLocation) -> LocationOut:
    return LocationOut(
        id=l.id, code=l.code, name=l.name, type=l.type, status=l.status,
        operationalStatus=getattr(l, "operational_status", "unknown") or "unknown",
        address=l.address, description=l.description,
        sourceBindings=location_bindings(l),
        metadata=l.extra_metadata,
        passport=_passport(l),
        createdAt=l.created_at.isoformat() if l.created_at else "",
        updatedAt=l.updated_at.isoformat() if l.updated_at else "",
    )


@router.get("", response_model=list[LocationOut])
async def list_locations(cid: CompanyDep, db: AsyncSession = Depends(get_db)):
    # Скоуп данных: участнику с выданными объектами отдаём только их. Это корневой
    # список сети — из него строятся селектор станций, карта, парк и карточки, —
    # поэтому сужение здесь закрывает разом все экраны, перечисляющие объекты.
    res = await db.execute(
        select(ServiceLocation)
        .where(ServiceLocation.company_id == cid, *scope_location_conds(ServiceLocation.id))
        .order_by(ServiceLocation.code)
    )
    return [_out(l) for l in res.scalars().all()]


@router.get("/export", response_model=list[LocationOut])
async def export_locations(
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company.id)
        .order_by(ServiceLocation.code)
    )
    return [_out(l) for l in res.scalars().all()]


@router.post("", response_model=LocationOut)
async def create_location(
    payload: LocationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(payload.company_id, current_user, db)
    existing = await db.get(ServiceLocation, payload.id)
    if existing:
        # upsert по клиентскому id — но чужую точку (другой компании) перехватить
        # нельзя: get_owned бросит 404, если нет членства в её компании.
        await get_owned(ServiceLocation, payload.id, current_user, db)
        existing.company_id = cid
        existing.code = payload.code
        existing.name = payload.name
        existing.type = payload.type
        existing.status = payload.status
        existing.address = payload.address
        existing.description = payload.description
        existing.source_bindings = payload.sourceBindings
        existing.extra_metadata = _merge_metadata(existing.extra_metadata, payload.metadata)
        _sync_station_number(existing)
        if payload.code != existing.code:
            await _assert_code_free(db, cid, payload.code, except_id=existing.id)
        loc = existing
    else:
        await _assert_code_free(db, cid, payload.code)
        loc = ServiceLocation(
            id=payload.id, company_id=cid, code=payload.code, name=payload.name,
            type=payload.type, status=payload.status, address=payload.address,
            description=payload.description, source_bindings=payload.sourceBindings,
            extra_metadata=payload.metadata,
        )
        db.add(loc)
    await db.flush()
    # onupdate=func.now() истекает updated_at после flush на UPDATE-ветке upsert
    # → _out не должен триггерить синхронную дозагрузку (MissingGreenlet).
    await db.refresh(loc)
    return _out(loc)


@router.patch("/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: str,
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    if data.get("code") and data["code"] != loc.code:
        await _assert_code_free(db, loc.company_id, data["code"], except_id=loc.id)
    if "sourceBindings" in data:
        loc.source_bindings = data.pop("sourceBindings")
    if "metadata" in data:
        loc.extra_metadata = _merge_metadata(loc.extra_metadata, data.pop("metadata"))
        _sync_station_number(loc)
    for k, v in data.items():
        setattr(loc, k, v)
    await db.flush()
    await db.refresh(loc)
    return _out(loc)


@router.delete("/{location_id}")
async def delete_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    await db.delete(loc)
    return {"ok": True}


class OpStatusBody(BaseModel):
    status: str
    reason: str | None = None


@router.patch("/{location_id}/operational-status", response_model=LocationOut)
async def set_operational_status(
    location_id: str,
    body: OpStatusBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сменить операционный статус станции (работает/ремонт/...) + запись в журнал."""
    if body.status not in OP_STATUSES:
        raise HTTPException(400, f"Недопустимый статус: {body.status}")
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    prev = loc.operational_status
    loc.operational_status = body.status
    db.add(AuditEvent(
        company_id=loc.company_id,
        user_id=str(current_user.id),
        user_name=current_user.name or current_user.email,
        action="location_op_status",
        details=json.dumps(
            {"location_id": loc.id, "from": prev, "to": body.status, "reason": body.reason or ""},
            ensure_ascii=False, separators=(",", ":"),
        ),
    ))
    await db.flush()
    await db.refresh(loc)
    return _out(loc)


@router.get("/{location_id}/operational-status/history")
async def operational_status_history(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Журнал смен операционного статуса станции (из audit_events)."""
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    res = await db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.company_id == loc.company_id,
            AuditEvent.action == "location_op_status",
            AuditEvent.details.like(f'%"location_id":"{loc.id}"%'),
        )
        .order_by(AuditEvent.timestamp.desc())
        .limit(50)
    )
    out: list[dict[str, Any]] = []
    for ev in res.scalars().all():
        try:
            d = json.loads(ev.details or "{}")
        except (ValueError, TypeError):
            d = {}
        out.append({
            "at": ev.timestamp.isoformat() if ev.timestamp else "",
            "user": ev.user_name,
            "from": d.get("from"), "to": d.get("to"), "reason": d.get("reason", ""),
        })
    return out


@router.get("/{location_id}/hubex-tasks")
async def hubex_tasks(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сервисные заявки HubEx FSM по станции (по metadata.hubexAssetId)."""
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    # Привязка к активу живёт и колонкой паспорта (350 объектов), и в снимке:
    # чтение только снимка отдавало пустой список заявок на связанной станции.
    asset_id = loc.hubex_asset_id or (loc.extra_metadata or {}).get("hubexAssetId")
    if not hubex_service.is_configured():
        return {"configured": False, "assetId": asset_id, "tasks": [], "total": 0}
    if asset_id in (None, "", 0):
        return {"configured": True, "assetId": None, "tasks": [], "total": 0}
    try:
        res = await hubex_service.get_asset_tasks(int(asset_id))
        return {"configured": True, "assetId": int(asset_id), **res}
    except Exception as e:  # внешний API недоступен — не роняем cockpit
        return {"configured": True, "assetId": asset_id, "tasks": [], "total": 0,
                "error": str(e)[:200]}
