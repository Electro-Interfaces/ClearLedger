"""
CRUD для ServiceLocation (точки обслуживания) — АЗС/магазины/офисы/склады.

Перенесено из localStorage фронта в бэкенд: точки общие для всех браузеров и
совпадают с конфигом каналов. Публичный (как sources/channels), company-scoped.
id — клиентский nanoid (String), чтобы фронт и бэк совпадали.
"""
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_company_by_api_key, get_current_user
from app.database import get_db
from app.deps import CompanyDep, get_owned
from app.services import location_commands, object_control, space_projection
from app.services.export_policy import (
    PUBLIC_FIELDS, filter_for_export, is_publishable)
from app.services.location_commands import merge_metadata as _merge_metadata
from app.services.station_passport import passport_value, stations_by_location
from app.models import (
    AuditEvent, Company, ObjectExportLog, ServiceLocation, User, location_bindings)
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
    # Технический ключ присваивает система (СТО п. 7.1): клиент вправе прислать
    # свой при повторной отправке того же объекта (ручка работает как upsert), но
    # придумывать ключ за систему ему больше не нужно. Формат к прочтению людьми
    # не предназначен и в документах не применяется.
    id: str | None = None
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


def _passport(l: ServiceLocation, unit=None) -> dict[str, Any] | None:
    """Типизированный паспорт (L2) объекта → dict непустых полей, либо None.

    Графы железа берутся у станции, стоящей в этой точке (`station_passport`), с
    фолбэком на прежние колонки объекта: после разделения уровней заводской номер,
    модель, мощность и инвентарный номер принадлежат станции, а не точке. Контракт
    ответа при этом не меняется — экраны читают те же ключи, что читали.

    Графы самой точки — адрес, координаты, регион, класс размещения, признак
    тестового объекта — остаются здесь: станция к ним отношения не имеет.
    """
    fields = {
        "serialNumber": passport_value("serialNumber", l, unit),
        "stationNumber": getattr(l, "station_number", None),
        "city": getattr(l, "city", None), "street": getattr(l, "street", None),
        "house": getattr(l, "house", None),
        "latitude": getattr(l, "latitude", None), "longitude": getattr(l, "longitude", None),
        "powerKwt": passport_value("powerKwt", l, unit),
        "connectorsCount": passport_value("connectorsCount", l, unit),
        "connectorTypes": passport_value("connectorTypes", l, unit),
        "owner": passport_value("owner", l, unit), "ownerId": getattr(l, "owner_id", None),
        "brand": passport_value("brand", l, unit), "model": passport_value("model", l, unit),
        "ocppProtocol": passport_value("ocppProtocol", l, unit),
        "firmware": passport_value("firmware", l, unit),
        "stage": getattr(l, "stage", None), "isTest": getattr(l, "is_test", None),
        "hubexAssetId": passport_value("hubexAssetId", l, unit),
        "hubexLinkStatus": getattr(l, "hubex_link_status", None),
        "rating": getattr(l, "rating", None), "successPct": getattr(l, "success_pct", None),
        "regionId": str(l.region_id) if getattr(l, "region_id", None) else None,
        # атрибуты из сводной выработки (слот obshaya, v2.14)
        "locationClass": getattr(l, "location_class", None),
        "speedClass": passport_value("speedClass", l, unit),
        "installedOn": passport_value("installedOn", l, unit),
        "decommissionedOn": passport_value("decommissionedOn", l, unit),
        "inventoryNumber": passport_value("inventoryNumber", l, unit),
        "isCorp": True if getattr(l, "is_corp", False) else None,
        # Идентификатор станции — чтобы карточка открывала её напрямую, а не
        # угадывала по серийнику. Пуст, пока связь не заведена.
        "stationId": str(unit.id) if unit is not None else None,
    }
    out = {k: v for k, v in fields.items() if v is not None}
    return out or None


def _out(l: ServiceLocation, unit=None) -> LocationOut:
    return LocationOut(
        id=l.id, code=l.code, name=l.name, type=l.type, status=l.status,
        operationalStatus=getattr(l, "operational_status", "unknown") or "unknown",
        address=l.address, description=l.description,
        sourceBindings=location_bindings(l),
        metadata=l.extra_metadata,
        passport=_passport(l, unit),
        createdAt=l.created_at.isoformat() if l.created_at else "",
        updatedAt=l.updated_at.isoformat() if l.updated_at else "",
    )


@router.get("/control")
async def objects_control(cid: CompanyDep, db: AsyncSession = Depends(get_db)):
    """Обязательный контроль объектов (СТО п. 14.2).

    Объявлен до `/{location_id}`: иначе FastAPI разберёт «control» как
    идентификатор объекта и ручка ответит 404 — грабля, на которую уже наступали
    со `/summary` в «Задачах».
    """
    return await object_control.run(db, cid)


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
    rows = res.scalars().all()
    stations = await stations_by_location(db, cid, [l.id for l in rows])
    return [_out(l, stations.get(l.id)) for l in rows]


@router.get("/export")
async def export_locations(
    scope: str = Query("internal", pattern="^(internal|external)$"),
    company: Company = Depends(get_company_by_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Выгрузка реестра объектов.

    `scope=internal` (по умолчанию) — обмен между системами организации: полный
    состав, иначе Поддержка не сможет вести заявку по объекту. Такая передача не
    замораживает номера (СТО п. 7.6).

    `scope=external` — передача вовне: только объекты с разрешением на публикацию
    (п. 12.4) и только разрешённый состав (п. 12.1–12.2), без технического ключа,
    заводского и инвентарного номеров и параметров подключения.
    """
    res = await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company.id)
        .order_by(ServiceLocation.code)
    )
    rows = res.scalars().all()
    external = scope == "external"
    if external:
        rows = [l for l in rows if is_publishable(l)]
    stations = await stations_by_location(db, company.id, [l.id for l in rows])
    out = [_out(l, stations.get(l.id)) for l in rows]
    if external:
        out = [filter_for_export(item.model_dump()) for item in out]

    # Журнал выгрузок (СТО п. 12.3): кто, когда, какой состав и объём. Ручка
    # ходит по ключу интеграции — это обмен между системами ОРГАНИЗАЦИИ, поэтому
    # `is_external=False`: такая передача номера не замораживает (п. 7.6), иначе
    # первая же синхронизация с Поддержкой заморозила бы всю сеть.
    db.add(ObjectExportLog(
        company_id=company.id, actor_kind="integration", actor_ref="cloud-api-key",
        destination=scope, is_external=external,
        fields=(sorted(PUBLIC_FIELDS | {"passport"}) if external
                else sorted(LocationOut.model_fields.keys())),
        objects_count=len(out),
        note=("Выгрузка реестра объектов наружу" if external
              else "Выгрузка реестра объектов по ключу интеграции"),
    ))
    return out


@router.post("", response_model=LocationOut)
async def create_location(
    payload: LocationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await assert_company_member(payload.company_id, current_user, db)
    new_id = (payload.id or "").strip() or f"ezs-{uuid.uuid4().hex[:20]}"
    data = payload.model_dump(exclude={"id", "company_id"})
    if "metadata" not in payload.model_fields_set:
        # Omission is not an explicit request to erase the object number.
        data.pop("metadata")
    try:
        loc = await location_commands.upsert(db, cid, new_id, data)
    except location_commands.LocationConflict as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    await db.flush()
    # onupdate=func.now() истекает updated_at после flush на UPDATE-ветке upsert
    # → _out не должен триггерить синхронную дозагрузку (MissingGreenlet).
    await db.refresh(loc)
    # Станция подтягивается и здесь: иначе карточка после сохранения показывала бы
    # прежние колонки точки, а список рядом — паспорт станции. Одна выборка по
    # одному объекту, N+1 тут неоткуда взяться.
    stations = await stations_by_location(db, loc.company_id, [loc.id])
    # Объект уехал в приложения сразу: между заведением станции и её появлением
    # у сервисной службы больше нет человека, который должен нажать кнопку.
    await space_projection.project_object(db, loc.company_id, loc.id)
    return _out(loc, stations.get(loc.id))


@router.patch("/{location_id}", response_model=LocationOut)
async def update_location(
    location_id: str,
    payload: LocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    # Establish both object and own-organization context for path-only admission.
    cid = await assert_company_member(str(loc.company_id), current_user, db)
    data = payload.model_dump(exclude_unset=True)
    try:
        mutation = await location_commands.update(db, cid, location_id, data)
    except location_commands.LocationConflict as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    if mutation is None:
        raise HTTPException(404, "Не найдено")
    loc = mutation.location
    await db.flush()
    await db.refresh(loc)
    # Станция подтягивается и здесь: иначе карточка после сохранения показывала бы
    # прежние колонки точки, а список рядом — паспорт станции. Одна выборка по
    # одному объекту, N+1 тут неоткуда взяться.
    stations = await stations_by_location(db, loc.company_id, [loc.id])
    await space_projection.project_object(db, loc.company_id, loc.id)
    return _out(loc, stations.get(loc.id))


@router.delete("/{location_id}")
async def delete_location(
    location_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loc = await get_owned(ServiceLocation, location_id, current_user, db)
    cid = await assert_company_member(str(loc.company_id), current_user, db)
    try:
        # Reuse mandatory scope/tenant checks without changing or retiring data.
        mutation = await location_commands.update(db, cid, location_id, {})
    except location_commands.LocationConflict as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    if mutation is None:
        raise HTTPException(404, "Не найдено")
    raise HTTPException(409,
        "Физическое удаление объекта недоступно: требуется вывод из эксплуатации с сохранением истории")


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
    # Станция подтягивается и здесь: иначе карточка после сохранения показывала бы
    # прежние колонки точки, а список рядом — паспорт станции. Одна выборка по
    # одному объекту, N+1 тут неоткуда взяться.
    stations = await stations_by_location(db, loc.company_id, [loc.id])
    # Смена «работает / в ремонте» нужна сервисной службе раньше всех остальных
    # правок карточки: по ней решают, ехать ли на объект.
    await space_projection.project_object(db, loc.company_id, loc.id)
    return _out(loc, stations.get(loc.id))


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
