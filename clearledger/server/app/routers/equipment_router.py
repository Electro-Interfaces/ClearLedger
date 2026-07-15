"""
API складского учёта оборудования ЭЗС: единицы, движения, склады, ЗИП, импорт.

Раздел «Управленческий» → группа «Оборудование» (energy/РусГидро).
Авторизация — членство в компании (assert_company_member, как ops_router);
точечная модульная политика — расширение.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    EzsEquipmentMovement, EzsEquipmentUnit, EzsSparePart, EzsSparePartMovement,
    EzsSparePartStock, ServiceLocation, User,
)
from app.services.ezs_equipment import (
    OP_LABELS, STATE_LABELS, TERMINAL_STATES, allowed_ops, apply_movement,
    create_unit, dismantle_from_site, import_units_xlsx, spare_apply_movement,
)

router = APIRouter(prefix="/equipment", tags=["Оборудование ЭЗС"])


# ─── схемы входа ────────────────────────────────────────────────────────────

class UnitIn(BaseModel):
    kind: str = "station"
    serialNumber: str | None = None
    vendor: str | None = None
    model: str | None = None
    stationType: str | None = None
    powerKwt: float | None = None
    connectorsCount: int | None = None
    connectorTypes: str | None = None
    inventoryNumber: str | None = None
    supplier: str | None = None
    purchaseDoc: str | None = None
    purchaseDate: str | None = None
    warrantyUntil: str | None = None
    isUsed: bool = False
    notes: str | None = None
    # для создания: склад поступления + реквизиты движения receipt
    initialLocationId: str | None = None
    occurredOn: str | None = None
    basis: str | None = None
    comment: str | None = None


class UnitPatch(BaseModel):
    serialNumber: str | None = None
    vendor: str | None = None
    model: str | None = None
    stationType: str | None = None
    powerKwt: float | None = None
    connectorsCount: int | None = None
    connectorTypes: str | None = None
    inventoryNumber: str | None = None
    supplier: str | None = None
    purchaseDoc: str | None = None
    purchaseDate: str | None = None
    warrantyUntil: str | None = None
    notes: str | None = None


class MovementIn(BaseModel):
    op: str
    occurredOn: str | None = None
    toLocationId: str | None = None
    toState: str | None = None          # только для correction
    custodian: str | None = None        # to_repair: contractor|vendor; correction
    counterparty: str | None = None
    reservedForLocationId: str | None = None
    basis: str | None = None
    comment: str | None = None
    syncPassport: bool = False


class DismantleIn(BaseModel):
    siteLocationId: str
    warehouseId: str
    occurredOn: str | None = None
    basis: str | None = None
    comment: str | None = None
    setDecommissioned: bool = False


class SparePartIn(BaseModel):
    name: str
    category: str = "other"
    vendor: str | None = None
    article: str | None = None
    compatibleModels: str | None = None
    unitLabel: str = "шт"
    notes: str | None = None


class SpareMovementIn(BaseModel):
    op: str
    qty: float = Field(gt=0)
    fromLocationId: str | None = None
    toLocationId: str | None = None
    targetUnitId: str | None = None
    targetLocationId: str | None = None
    occurredOn: str | None = None
    basis: str | None = None
    comment: str | None = None


# ─── сериализация ───────────────────────────────────────────────────────────

def _loc_brief(loc: ServiceLocation | None) -> dict[str, Any] | None:
    if loc is None:
        return None
    return {"id": loc.id, "name": loc.name, "type": loc.type, "address": loc.address}


def _unit_out(u: EzsEquipmentUnit, locs: dict[str, ServiceLocation]) -> dict[str, Any]:
    return {
        "id": str(u.id), "kind": u.kind,
        "serialNumber": u.serial_number, "vendor": u.vendor, "vendorRaw": u.vendor_raw,
        "model": u.model, "stationType": u.station_type, "powerKwt": u.power_kwt,
        "connectorsCount": u.connectors_count, "connectorTypes": u.connector_types,
        "inventoryNumber": u.inventory_number, "supplier": u.supplier,
        "purchaseDoc": u.purchase_doc, "purchaseDate": u.purchase_date,
        "warrantyUntil": u.warranty_until,
        "state": u.state, "stateLabel": STATE_LABELS.get(u.state, u.state),
        "isUsed": u.is_used,
        "custodian": u.custodian, "custodianName": u.custodian_name,
        "location": _loc_brief(locs.get(u.current_location_id or "")),
        "originLocation": _loc_brief(locs.get(u.origin_location_id or "")),
        "reservedFor": _loc_brief(locs.get(u.reserved_for_location_id or "")),
        "notes": u.notes,
        "createdAt": u.created_at.isoformat() if u.created_at else None,
        "updatedAt": u.updated_at.isoformat() if u.updated_at else None,
        "allowedOps": allowed_ops(u.state),
    }


def _move_out(m: EzsEquipmentMovement, locs: dict[str, ServiceLocation],
              unit: EzsEquipmentUnit | None = None) -> dict[str, Any]:
    out = {
        "id": str(m.id), "unitId": str(m.unit_id),
        "op": m.op, "opLabel": OP_LABELS.get(m.op, m.op),
        "fromLocation": _loc_brief(locs.get(m.from_location_id or "")),
        "toLocation": _loc_brief(locs.get(m.to_location_id or "")),
        "fromState": m.from_state, "toState": m.to_state,
        "fromStateLabel": STATE_LABELS.get(m.from_state or "", m.from_state),
        "toStateLabel": STATE_LABELS.get(m.to_state or "", m.to_state),
        "counterparty": m.counterparty,
        "occurredOn": m.occurred_on, "basis": m.basis, "comment": m.comment,
        "createdBy": m.created_by_name,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
    }
    if unit is not None:
        out["unit"] = {"serialNumber": unit.serial_number, "vendor": unit.vendor,
                       "model": unit.model, "inventoryNumber": unit.inventory_number}
    return out


async def _locations_map(db: AsyncSession, company_id) -> dict[str, ServiceLocation]:
    rows = (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company_id)
    )).scalars().all()
    return {l.id: l for l in rows}


def _payload_movement(body: MovementIn) -> dict[str, Any]:
    return {
        "op": body.op, "occurred_on": body.occurredOn,
        "to_location_id": body.toLocationId, "to_state": body.toState,
        "custodian": body.custodian, "counterparty": body.counterparty,
        "reserved_for_location_id": body.reservedForLocationId,
        "basis": body.basis, "comment": body.comment,
        "sync_passport": body.syncPassport,
    }


# ─── единицы ────────────────────────────────────────────────────────────────

@router.get("/units")
async def list_units(
    company_id: str = Query(...),
    state: str | None = Query(None), location_id: str | None = Query(None),
    vendor: str | None = Query(None), custodian: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(500, le=1000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    U = EzsEquipmentUnit
    conds = [U.company_id == cid]
    if state:
        conds.append(U.state.in_(state.split(",")))
    if location_id:
        conds.append(U.current_location_id == location_id)
    if vendor:
        conds.append(U.vendor == vendor)
    if custodian:
        conds.append(U.custodian == custodian)
    if q:
        like = f"%{q.strip()}%"
        conds.append(U.serial_number.ilike(like) | U.model.ilike(like) |
                     U.inventory_number.ilike(like) | U.vendor.ilike(like))
    total = int((await db.execute(select(func.count()).select_from(U).where(*conds))).scalar_one())
    rows = (await db.execute(
        select(U).where(*conds).order_by(U.updated_at.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )).scalars().all()
    locs = await _locations_map(db, cid)
    return {"items": [_unit_out(u, locs) for u in rows], "total": total}


@router.post("/units")
async def create_unit_ep(
    body: UnitIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    unit = await create_unit(db, cid, user, {
        "kind": body.kind, "serial_number": body.serialNumber,
        "vendor": body.vendor, "vendor_raw": body.vendor,
        "model": body.model, "station_type": body.stationType,
        "power_kwt": body.powerKwt, "connectors_count": body.connectorsCount,
        "connector_types": body.connectorTypes, "inventory_number": body.inventoryNumber,
        "supplier": body.supplier, "purchase_doc": body.purchaseDoc,
        "purchase_date": body.purchaseDate, "warranty_until": body.warrantyUntil,
        "is_used": body.isUsed, "notes": body.notes,
        "initial_location_id": body.initialLocationId,
        "occurred_on": body.occurredOn, "basis": body.basis, "comment": body.comment,
    })
    await db.flush()
    await db.refresh(unit)
    locs = await _locations_map(db, cid)
    return _unit_out(unit, locs)


@router.get("/units/{unit_id}")
async def get_unit(
    unit_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    unit = await db.get(EzsEquipmentUnit, unit_id)
    if unit is None or unit.company_id != cid:
        raise HTTPException(404, "Единица не найдена")
    moves = (await db.execute(
        select(EzsEquipmentMovement).where(EzsEquipmentMovement.unit_id == unit_id)
        .order_by(EzsEquipmentMovement.created_at.desc())
    )).scalars().all()
    locs = await _locations_map(db, cid)
    out = _unit_out(unit, locs)
    out["movements"] = [_move_out(m, locs) for m in moves]
    return out


@router.patch("/units/{unit_id}")
async def patch_unit(
    unit_id: uuid.UUID, body: UnitPatch, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    unit = await db.get(EzsEquipmentUnit, unit_id)
    if unit is None or unit.company_id != cid:
        raise HTTPException(404, "Единица не найдена")
    from app.services.ezs_equipment import _serial_conflict, canon_vendor
    data = body.model_dump(exclude_unset=True)
    mapping = {
        "serialNumber": "serial_number", "vendor": "vendor", "model": "model",
        "stationType": "station_type", "powerKwt": "power_kwt",
        "connectorsCount": "connectors_count", "connectorTypes": "connector_types",
        "inventoryNumber": "inventory_number", "supplier": "supplier",
        "purchaseDoc": "purchase_doc", "purchaseDate": "purchase_date",
        "warrantyUntil": "warranty_until", "notes": "notes",
    }
    if "serialNumber" in data:
        s = (data["serialNumber"] or "").strip() or None
        if s and await _serial_conflict(db, cid, s, exclude_id=unit.id):
            raise HTTPException(409, f"Единица с серийным номером «{s}» уже есть")
        data["serialNumber"] = s
    if "vendor" in data:
        unit.vendor_raw = data["vendor"]
        data["vendor"] = canon_vendor(data["vendor"])
    for k, v in data.items():
        setattr(unit, mapping[k], v)
    await db.flush()
    await db.refresh(unit)
    locs = await _locations_map(db, cid)
    return _unit_out(unit, locs)


@router.delete("/units/{unit_id}")
async def delete_unit(
    unit_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    unit = await db.get(EzsEquipmentUnit, unit_id)
    if unit is None or unit.company_id != cid:
        raise HTTPException(404, "Единица не найдена")
    n_moves = int((await db.execute(
        select(func.count()).select_from(EzsEquipmentMovement)
        .where(EzsEquipmentMovement.unit_id == unit_id)
    )).scalar_one())
    if n_moves > 1:
        raise HTTPException(409, "У единицы есть история движений — используйте списание или корректировку")
    await db.delete(unit)
    return {"deleted": str(unit_id)}


@router.post("/units/{unit_id}/movements")
async def unit_movement(
    unit_id: uuid.UUID, body: MovementIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    unit, move = await apply_movement(db, cid, user, unit_id, _payload_movement(body))
    await db.flush()
    await db.refresh(unit)
    await db.refresh(move)
    locs = await _locations_map(db, cid)
    return {"unit": _unit_out(unit, locs), "movement": _move_out(move, locs)}


@router.post("/dismantle")
async def dismantle(
    body: DismantleIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Демонтаж станции с площадки → склад (карточка создаётся при отсутствии)."""
    cid = await assert_company_member(company_id, user, db)
    unit, move, created = await dismantle_from_site(db, cid, user, {
        "site_location_id": body.siteLocationId, "warehouse_id": body.warehouseId,
        "occurred_on": body.occurredOn, "basis": body.basis, "comment": body.comment,
        "set_decommissioned": body.setDecommissioned,
    })
    await db.flush()
    await db.refresh(unit)
    await db.refresh(move)
    locs = await _locations_map(db, cid)
    return {"unit": _unit_out(unit, locs), "movement": _move_out(move, locs), "unitCreated": created}


# ─── журнал движений ────────────────────────────────────────────────────────

@router.get("/movements")
async def list_movements(
    company_id: str = Query(...),
    op: str | None = Query(None), location_id: str | None = Query(None),
    unit_id: uuid.UUID | None = Query(None),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(200, le=1000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    M = EzsEquipmentMovement
    conds = [M.company_id == cid]
    if op:
        conds.append(M.op.in_(op.split(",")))
    if location_id:
        conds.append((M.from_location_id == location_id) | (M.to_location_id == location_id))
    if unit_id:
        conds.append(M.unit_id == unit_id)
    if date_from:
        conds.append(M.occurred_on >= date_from)
    if date_to:
        conds.append(M.occurred_on <= date_to)
    total = int((await db.execute(select(func.count()).select_from(M).where(*conds))).scalar_one())
    rows = (await db.execute(
        select(M, EzsEquipmentUnit).join(EzsEquipmentUnit, EzsEquipmentUnit.id == M.unit_id)
        .where(*conds).order_by(M.occurred_on.desc(), M.created_at.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )).all()
    locs = await _locations_map(db, cid)
    return {"items": [_move_out(m, locs, unit=u) for m, u in rows], "total": total}


# ─── склады и обзор ─────────────────────────────────────────────────────────

@router.get("/warehouses/summary")
async def warehouses_summary(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Остатки по складам: единицы по состояниям + позиции/количество ЗИП;
    плюс синтетические строки «у подрядчика» / «у производителя»."""
    cid = await assert_company_member(company_id, user, db)
    U = EzsEquipmentUnit
    locs = await _locations_map(db, cid)
    warehouses = [l for l in locs.values() if l.type == "warehouse"]

    unit_rows = (await db.execute(
        select(U.current_location_id, U.state, func.count())
        .where(U.company_id == cid, U.current_location_id.is_not(None))
        .group_by(U.current_location_id, U.state)
    )).all()
    by_wh: dict[str, dict[str, int]] = {}
    for loc_id, state, n in unit_rows:
        by_wh.setdefault(loc_id, {})[state] = int(n)

    spare_rows = (await db.execute(
        select(EzsSparePartStock.location_id,
               func.count(func.distinct(EzsSparePartStock.part_id)).filter(EzsSparePartStock.qty > 0),
               func.coalesce(func.sum(EzsSparePartStock.qty), 0))
        .where(EzsSparePartStock.company_id == cid)
        .group_by(EzsSparePartStock.location_id)
    )).all()
    spare_by_wh = {r[0]: {"positions": int(r[1] or 0), "qty": float(r[2] or 0)} for r in spare_rows}

    ext_rows = (await db.execute(
        select(U.custodian, func.count(), func.array_agg(func.distinct(func.coalesce(U.custodian_name, "—"))))
        .where(U.company_id == cid, U.custodian.in_(("contractor", "vendor")),
               U.state.notin_(tuple(TERMINAL_STATES)))
        .group_by(U.custodian)
    )).all()

    out = []
    for wh in sorted(warehouses, key=lambda w: w.name):
        states = by_wh.get(wh.id, {})
        sp = spare_by_wh.get(wh.id, {"positions": 0, "qty": 0.0})
        out.append({
            "location": _loc_brief(wh),
            "unitsByState": states,
            "unitsTotal": sum(states.values()),
            "sparePositions": sp["positions"],
            "spareQty": sp["qty"],
        })
    external = [{
        "custodian": r[0],
        "custodianLabel": "У подрядчика (ремонт)" if r[0] == "contractor" else "У производителя",
        "unitsTotal": int(r[1]),
        "names": [n for n in (r[2] or []) if n and n != "—"],
    } for r in ext_rows]
    return {"warehouses": out, "external": external}


@router.get("/overview")
async def equipment_overview(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    U = EzsEquipmentUnit
    by_state = {r[0]: int(r[1]) for r in (await db.execute(
        select(U.state, func.count()).where(U.company_id == cid).group_by(U.state)
    )).all()}
    by_custodian = {r[0]: int(r[1]) for r in (await db.execute(
        select(U.custodian, func.count()).where(U.company_id == cid).group_by(U.custodian)
    )).all()}
    by_vendor = [{"vendor": r[0] or "—", "count": int(r[1])} for r in (await db.execute(
        select(U.vendor, func.count()).where(U.company_id == cid)
        .group_by(U.vendor).order_by(func.count().desc())
    )).all()]

    # ремонты дольше 30 дней: последнее движение to_repair старше месяца
    from datetime import date, timedelta
    threshold = (date.today() - timedelta(days=30)).isoformat()
    M = EzsEquipmentMovement
    last_repair = (
        select(M.unit_id, func.max(M.occurred_on).label("d"))
        .where(M.company_id == cid, M.op == "to_repair").group_by(M.unit_id).subquery()
    )
    in_repair_over = int((await db.execute(
        select(func.count()).select_from(U)
        .join(last_repair, last_repair.c.unit_id == U.id)
        .where(U.company_id == cid, U.state == "in_repair", last_repair.c.d < threshold)
    )).scalar_one())

    recent = (await db.execute(
        select(M, U).join(U, U.id == M.unit_id).where(M.company_id == cid)
        .order_by(M.created_at.desc()).limit(10)
    )).all()
    locs = await _locations_map(db, cid)
    return {
        "countsByState": by_state,
        "countsByCustodian": by_custodian,
        "countsByVendor": by_vendor,
        "inRepairOver30d": in_repair_over,
        "recentMovements": [_move_out(m, locs, unit=u) for m, u in recent],
    }


# ─── импорт ─────────────────────────────────────────────────────────────────

@router.post("/import")
async def import_units(
    company_id: str = Query(...), dry_run: bool = Query(False),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Импорт складского реестра оборудования (xlsx, толерантный к колонкам)."""
    cid = await assert_company_member(company_id, user, db)
    content = await file.read()
    if not content:
        raise HTTPException(400, "Пустой файл")
    return await import_units_xlsx(db, cid, user, content, file.filename or "файл.xlsx", dry_run)


# ─── ЗИП ────────────────────────────────────────────────────────────────────

def _part_out(p: EzsSparePart) -> dict[str, Any]:
    return {
        "id": str(p.id), "name": p.name, "category": p.category,
        "vendor": p.vendor, "article": p.article,
        "compatibleModels": p.compatible_models, "unitLabel": p.unit_label,
        "notes": p.notes, "isArchived": p.is_archived,
    }


@router.get("/spare-parts")
async def list_spare_parts(
    company_id: str = Query(...),
    q: str | None = Query(None), category: str | None = Query(None),
    include_archived: bool = Query(False),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    P = EzsSparePart
    conds = [P.company_id == cid]
    if not include_archived:
        conds.append(P.is_archived.is_(False))
    if category:
        conds.append(P.category == category)
    if q:
        like = f"%{q.strip()}%"
        conds.append(P.name.ilike(like) | P.article.ilike(like) | P.vendor.ilike(like))
    parts = (await db.execute(select(P).where(*conds).order_by(P.name))).scalars().all()
    stock = (await db.execute(
        select(EzsSparePartStock).where(EzsSparePartStock.company_id == cid)
    )).scalars().all()
    locs = await _locations_map(db, cid)
    by_part: dict[str, list[dict[str, Any]]] = {}
    for s in stock:
        if float(s.qty) == 0:
            continue
        by_part.setdefault(str(s.part_id), []).append({
            "locationId": s.location_id,
            "locationName": locs.get(s.location_id).name if locs.get(s.location_id) else "—",
            "qty": float(s.qty),
        })
    out = []
    for p in parts:
        rows = by_part.get(str(p.id), [])
        out.append({**_part_out(p), "totalQty": sum(r["qty"] for r in rows), "byLocation": rows})
    return out


@router.post("/spare-parts")
async def create_spare_part(
    body: SparePartIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    dup = (await db.execute(
        select(EzsSparePart.id).where(
            EzsSparePart.company_id == cid,
            func.lower(EzsSparePart.name) == body.name.strip().lower(),
        ).limit(1)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"Номенклатура «{body.name.strip()}» уже есть")
    p = EzsSparePart(
        company_id=cid, name=body.name.strip(), category=body.category,
        vendor=body.vendor, article=body.article,
        compatible_models=body.compatibleModels, unit_label=body.unitLabel,
        notes=body.notes,
    )
    db.add(p)
    await db.flush()
    return _part_out(p)


@router.patch("/spare-parts/{part_id}")
async def update_spare_part(
    part_id: uuid.UUID, body: SparePartIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    p = await db.get(EzsSparePart, part_id)
    if p is None or p.company_id != cid:
        raise HTTPException(404, "Номенклатура не найдена")
    p.name = body.name.strip()
    p.category = body.category
    p.vendor = body.vendor
    p.article = body.article
    p.compatible_models = body.compatibleModels
    p.unit_label = body.unitLabel
    p.notes = body.notes
    await db.flush()
    return _part_out(p)


@router.delete("/spare-parts/{part_id}")
async def delete_spare_part(
    part_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    p = await db.get(EzsSparePart, part_id)
    if p is None or p.company_id != cid:
        raise HTTPException(404, "Номенклатура не найдена")
    n = int((await db.execute(
        select(func.count()).select_from(EzsSparePartMovement)
        .where(EzsSparePartMovement.part_id == part_id)
    )).scalar_one())
    if n > 0:
        p.is_archived = True
        return {"archived": str(part_id), "reason": "есть движения — номенклатура отправлена в архив"}
    await db.delete(p)
    return {"deleted": str(part_id)}


@router.post("/spare-parts/{part_id}/movements")
async def spare_movement(
    part_id: uuid.UUID, body: SpareMovementIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    move = await spare_apply_movement(db, cid, user, part_id, {
        "op": body.op, "qty": body.qty,
        "from_location_id": body.fromLocationId, "to_location_id": body.toLocationId,
        "target_unit_id": body.targetUnitId, "target_location_id": body.targetLocationId,
        "occurred_on": body.occurredOn, "basis": body.basis, "comment": body.comment,
    })
    await db.flush()
    stock = (await db.execute(
        select(EzsSparePartStock).where(
            EzsSparePartStock.company_id == cid, EzsSparePartStock.part_id == part_id)
    )).scalars().all()
    locs = await _locations_map(db, cid)
    return {
        "movementId": str(move.id),
        "stock": [{"locationId": s.location_id,
                   "locationName": locs.get(s.location_id).name if locs.get(s.location_id) else "—",
                   "qty": float(s.qty)} for s in stock],
    }


@router.get("/spare-parts/movements/journal")
async def spare_movements_journal(
    company_id: str = Query(...),
    part_id: uuid.UUID | None = Query(None), location_id: str | None = Query(None),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(200, le=1000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    M = EzsSparePartMovement
    conds = [M.company_id == cid]
    if part_id:
        conds.append(M.part_id == part_id)
    if location_id:
        conds.append((M.from_location_id == location_id) | (M.to_location_id == location_id))
    if date_from:
        conds.append(M.occurred_on >= date_from)
    if date_to:
        conds.append(M.occurred_on <= date_to)
    total = int((await db.execute(select(func.count()).select_from(M).where(*conds))).scalar_one())
    rows = (await db.execute(
        select(M, EzsSparePart).join(EzsSparePart, EzsSparePart.id == M.part_id)
        .where(*conds).order_by(M.occurred_on.desc(), M.created_at.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )).all()
    locs = await _locations_map(db, cid)
    items = []
    for m, p in rows:
        items.append({
            "id": str(m.id), "part": {"id": str(p.id), "name": p.name, "unitLabel": p.unit_label},
            "op": m.op, "qty": float(m.qty),
            "fromLocation": _loc_brief(locs.get(m.from_location_id or "")),
            "toLocation": _loc_brief(locs.get(m.to_location_id or "")),
            "targetUnitId": str(m.target_unit_id) if m.target_unit_id else None,
            "targetLocation": _loc_brief(locs.get(m.target_location_id or "")),
            "occurredOn": m.occurred_on, "basis": m.basis, "comment": m.comment,
            "createdBy": m.created_by_name,
        })
    return {"items": items, "total": total}
