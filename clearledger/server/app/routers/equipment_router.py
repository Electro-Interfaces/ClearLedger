"""
API складского учёта оборудования ЭЗС: единицы, движения, склады, ЗИП, импорт.

Раздел «Управленческий» → группа «Оборудование» (energy/РусГидро).
Авторизация — членство в компании (assert_company_member, как ops_router);
точечная модульная политика — расширение.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.models import (
    AuditEvent, EzsEquipmentMovement, EzsEquipmentUnit, EzsSparePart, EzsSparePartMovement,
    EzsSparePartStock, EzsSupplyDocument, Region, ServiceLocation, User,
)
from app.services.ezs_equipment import (
    OP_LABELS, STATE_LABELS, TERMINAL_STATES, allowed_ops,
    create_unit, dismantle_from_site, import_units_xlsx,
)
from app.services import ezs_supply

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
    # Реквизиты для 1С (14.10.2026): номенклатура, контрагенты ссылками, стоимость, ОС.
    nomenclatureId: str | None = None
    supplierId: str | None = None
    ownerId: str | None = None
    purchaseAmount: float | None = Field(None, ge=0)
    vatAmount: float | None = Field(None, ge=0)
    accountingNo: str | None = None
    okof: str | None = None
    depreciationGroup: str | None = None
    usefulLifeMonths: int | None = Field(None, ge=1, le=1200)
    bpRef: str | None = None


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
    # Номенклатура под 1С: вид, модель, единица ОКЕИ, ставка НДС, счёт, ссылка БП.
    kind: str = "spare"
    model: str | None = None
    unitCode: str | None = None
    vatRate: str | None = None
    account: str | None = None
    bpRef: str | None = None


class SpareMovementIn(BaseModel):
    op: str
    qty: float = Field(ge=0)         # ноль допустим только у корректировки
    fromLocationId: str | None = None
    toLocationId: str | None = None
    targetUnitId: str | None = None
    targetLocationId: str | None = None
    occurredOn: str | None = None
    basis: str | None = None
    comment: str | None = None


# ─── сериализация ───────────────────────────────────────────────────────────

# Производитель единицы. Колонку `vendor` заполняет загрузка поставок, а парк,
# приехавший из реестра сети, знает только марку станции (`brand`) — у 537 станций
# в эксплуатации пилота графа «Производитель» из-за этого выходила пустой.
def _vendor_col():
    U = EzsEquipmentUnit
    return func.coalesce(func.nullif(U.vendor, ""), U.brand)


def _loc_brief(loc: ServiceLocation | None) -> dict[str, Any] | None:
    if loc is None:
        return None
    return {"id": loc.id, "name": loc.name, "type": loc.type, "address": loc.address}


def _unit_out(u: EzsEquipmentUnit, locs: dict[str, ServiceLocation],
              supplies: dict[Any, str] | None = None) -> dict[str, Any]:
    return {
        "id": str(u.id), "kind": u.kind,
        "serialNumber": u.serial_number, "vendor": u.vendor or u.brand, "vendorRaw": u.vendor_raw,
        "model": u.model, "stationType": u.station_type, "powerKwt": u.power_kwt,
        "connectorsCount": u.connectors_count, "connectorTypes": u.connector_types,
        "inventoryNumber": u.inventory_number, "supplier": u.supplier,
        "purchaseDoc": u.purchase_doc, "purchaseDate": u.purchase_date,
        "warrantyUntil": u.warranty_until,
        "purchaseAmount": float(u.purchase_amount) if u.purchase_amount is not None else None,
        "vatAmount": float(u.vat_amount) if u.vat_amount is not None else None,
        "state": u.state, "stateLabel": STATE_LABELS.get(u.state, u.state),
        "isUsed": u.is_used,
        "custodian": u.custodian, "custodianName": u.custodian_name,
        "location": _loc_brief(locs.get(u.current_location_id or "")),
        "originLocation": _loc_brief(locs.get(u.origin_location_id or "")),
        "reservedFor": _loc_brief(locs.get(u.reserved_for_location_id or "")),
        "notes": u.notes,
        # Графы складского реестра заказчика: где лежит, кто хранит, чем числится
        # в его учёте — и подтвердил ли поставщик то, что здесь написано.
        "region": u.region, "keeper": u.keeper, "ownerName": u.owner_name,
        "accountingNo": u.accounting_no, "externalNo": u.external_no,
        "speedClass": u.speed_class,
        "dataConfirmed": u.data_confirmed,
        "unconfirmedReason": u.unconfirmed_reason,
        "supplyId": str(u.supply_id) if u.supply_id else None,
        "supplyLineId": str(u.supply_line_id) if u.supply_line_id else None,
        "supplyNumber": (supplies or {}).get(u.supply_id) if u.supply_id else None,
        "nomenclatureId": str(u.nomenclature_id) if u.nomenclature_id else None,
        "supplierId": str(u.supplier_id) if u.supplier_id else None,
        "ownerId": str(u.owner_id) if u.owner_id else None,
        "okof": u.okof, "depreciationGroup": u.depreciation_group,
        "usefulLifeMonths": u.useful_life_months, "bpRef": u.bp_ref,
        "createdAt": u.created_at.isoformat() if u.created_at else None,
        "updatedAt": u.updated_at.isoformat() if u.updated_at else None,
        "allowedOps": allowed_ops(u.state),
    }


def _move_out(m: EzsEquipmentMovement, locs: dict[str, ServiceLocation],
              unit: EzsEquipmentUnit | None = None,
              supplies: dict[Any, str] | None = None,
              docs: dict[Any, str] | None = None) -> dict[str, Any]:
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
        "documentId": str(m.document_id) if m.document_id else None,
        "documentNumber": (docs or {}).get(m.document_id) if m.document_id else None,
        "supplyId": str(m.supply_id) if m.supply_id else None,
        "supplyNumber": (supplies or {}).get(m.supply_id) if m.supply_id else None,
        "createdBy": m.created_by_name,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
    }
    if unit is not None:
        out["unit"] = {"serialNumber": unit.serial_number, "vendor": unit.vendor,
                       "model": unit.model, "inventoryNumber": unit.inventory_number}
    return out


async def _doc_numbers(db: AsyncSession, moves) -> dict[Any, str]:
    """Номера документов движения для строк журнала."""
    from app.models import EzsEquipmentDocument as D
    ids = {m.document_id for m in moves if m.document_id}
    if not ids:
        return {}
    return dict((await db.execute(select(D.id, D.number).where(D.id.in_(ids)))).all())


async def _auto_doc(db: AsyncSession, cid, user, op: str, move: EzsEquipmentMovement, **kw) -> str:
    """Документ с автономером для движения прежней формы; возвращает его номер."""
    from app.services import ezs_equipment_docs as D
    return (await D.document_for(db, cid, user, op, [move], **kw)).number


async def _locations_map(db: AsyncSession, company_id) -> dict[str, ServiceLocation]:
    rows = (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company_id)
    )).scalars().all()
    return {l.id: l for l in rows}


async def _supplies_map(db: AsyncSession, company_id, supply_ids) -> dict[Any, str]:
    """{supply_id: number} для подписи «из поставки №» (join без N+1)."""
    ids = [s for s in set(supply_ids) if s]
    if not ids:
        return {}
    rows = (await db.execute(
        select(EzsSupplyDocument.id, EzsSupplyDocument.number).where(
            EzsSupplyDocument.company_id == company_id,
            EzsSupplyDocument.id.in_(ids)))).all()
    return {sid: num for sid, num in rows}


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

def _scope_location_ids(cid, regions: list[str], codes: list[str], loc_ids: list[str]):
    """Подзапрос: точки компании, попавшие в контур рабочей области.

    Контур — union по измерениям, как на карте: точка входит, если её регион,
    её код или она сама выбраны. Регион берём каноном (`regions.name` через
    `region_id`), а не денорм-полем — так же, как считает аналитика сессий."""
    L = ServiceLocation
    ors = []
    if regions:
        ors.append(L.region_id.in_(
            select(Region.id).where(Region.company_id == cid, Region.name.in_(regions))))
    if codes:
        # Код станции в фильтре — это `charge_sessions.station_code`, и с `code`
        # объекта он совпадает лишь у 88 станций из 461: у остальных номер живёт
        # в паспорте (`number`, совпадений 441). Сверяем по обоим, иначе сужение
        # по конкретной ЭЗС молча даёт пустой список.
        ors.append(L.code.in_(codes)
                   | (L.extra_metadata["number"].astext.in_(codes)))
    if loc_ids:
        ors.append(L.id.in_(loc_ids))
    if not ors:
        return None
    cond = ors[0]
    for o in ors[1:]:
        cond = cond | o
    return select(L.id).where(L.company_id == cid, cond)


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else []


class ScopeQ:
    """Контур рабочей области, общий для всего раздела «Оборудование».

    Панель фильтров стоит над разделом целиком, поэтому её обещание («Приморский
    край · ЭЗС 648») обязаны выполнять все его экраны, а не только парк —
    жалоба заказчика 24.08.2026 была про раздел.
    """

    def __init__(
        self,
        region_ids: str | None = Query(None, description="регионы через запятую"),
        station_codes: str | None = Query(None, description="коды ЭЗС через запятую"),
        location_ids: str | None = Query(None, description="точки через запятую"),
    ) -> None:
        self.regions = _csv(region_ids)
        self.codes = _csv(station_codes)
        self.locs = _csv(location_ids)

    @property
    def empty(self) -> bool:
        return not (self.regions or self.codes or self.locs)

    def locations(self, cid):
        """Подзапрос точек контура или None, если контур не задан."""
        return _scope_location_ids(cid, self.regions, self.codes, self.locs)

    def unit_cond(self, cid):
        """Единица в контуре: стоит на его точке ИЛИ сама числится в его регионе
        (склад принадлежит региону, а точкой сети не является)."""
        sub = self.locations(cid)
        if sub is None:
            return None
        cond = EzsEquipmentUnit.current_location_id.in_(sub)
        return cond | EzsEquipmentUnit.region.in_(self.regions) if self.regions else cond


@router.get("/units")
async def list_units(
    company_id: str = Query(...),
    state: str | None = Query(None), location_id: str | None = Query(None),
    vendor: str | None = Query(None), custodian: str | None = Query(None),
    q: str | None = Query(None), kind: str | None = Query(None),
    sort: str = Query("updatedAt"), dir: str = Query("desc"),
    scope: ScopeQ = Depends(),
    page: int = Query(1, ge=1), page_size: int = Query(500, le=1000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    U = EzsEquipmentUnit
    conds = [U.company_id == cid]
    if kind:
        conds.append(U.kind.in_(kind.split(",")))
    if location_id:
        conds.append(U.current_location_id == location_id)
    if vendor:
        conds.append(_vendor_col() == vendor)
    if custodian:
        conds.append(U.custodian == custodian)
    in_scope = scope.unit_cond(cid)
    if in_scope is not None:
        conds.append(in_scope)
    if q:
        like = f"%{q.strip()}%"
        # Поиск идёт и по станции, где единица стоит: люди ищут «Гоголя», а не серийник.
        at_location = U.current_location_id.in_(
            select(ServiceLocation.id).where(
                ServiceLocation.company_id == cid,
                ServiceLocation.name.ilike(like) | ServiceLocation.address.ilike(like)
                | ServiceLocation.code.ilike(like)))
        conds.append(U.serial_number.ilike(like) | U.model.ilike(like) |
                     U.inventory_number.ilike(like) | _vendor_col().ilike(like) |
                     U.keeper.ilike(like) | at_location)
    # Плитки над реестром считаются здесь, по всему отбору, а не в браузере по
    # загруженной странице. Состояния — без отбора по состоянию: иначе, выбрав
    # «Резерв», человек видит одну плитку и нули в остальных.
    by_state = {s: int(n) for s, n in (await db.execute(
        select(U.state, func.count()).where(*conds).group_by(U.state))).all()}
    if state:
        conds.append(U.state.in_(state.split(",")))
    total = int((await db.execute(select(func.count()).select_from(U).where(*conds))).scalar_one())
    unconfirmed = int((await db.execute(
        select(func.count()).select_from(U).where(*conds, U.data_confirmed.is_(False)))).scalar_one())
    # Сортировка на сервере: реестр листается, и порядок одной страницы — не порядок реестра.
    place = select(ServiceLocation.name).where(
        ServiceLocation.id == U.current_location_id).scalar_subquery()
    col = {"serialNumber": U.serial_number, "vendor": _vendor_col(), "model": U.model,
           "powerKwt": U.power_kwt, "state": U.state, "place": place,
           "inventoryNumber": U.inventory_number}.get(sort, U.updated_at)
    order = (col.asc() if dir == "asc" else col.desc()).nulls_last()
    rows = (await db.execute(
        select(U).where(*conds).order_by(order, U.id)
        .limit(page_size).offset((page - 1) * page_size)
    )).scalars().all()
    locs = await _locations_map(db, cid)
    return {"items": [_unit_out(u, locs) for u in rows], "total": total,
            "counts": {"byState": by_state, "unconfirmed": unconfirmed}}


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
    move = (await db.execute(select(EzsEquipmentMovement).where(
        EzsEquipmentMovement.unit_id == unit.id))).scalar_one()
    number = await _auto_doc(db, cid, user, "receipt", move, doc_date=body.occurredOn,
                             basis=body.basis, comment=body.comment)
    await db.refresh(unit)
    locs = await _locations_map(db, cid)
    return {**_unit_out(unit, locs), "documentNumber": number}


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
    supplies = await _supplies_map(db, cid, [unit.supply_id, *(m.supply_id for m in moves)])
    out = _unit_out(unit, locs, supplies)
    docs = await _doc_numbers(db, moves)
    out["movements"] = [_move_out(m, locs, supplies=supplies, docs=docs) for m in moves]
    return {**out, **await _unit_refs(db, unit)}


async def _unit_refs(db: AsyncSession, unit: EzsEquipmentUnit) -> dict[str, Any]:
    """Названия справочных ссылок карточки: номенклатура, поставщик, балансодержатель."""
    from app.models import Counterparty
    from app.services.ezs_accounting import KINDS, default_account, unit_account
    from app.services.ezs_equipment import stock_account
    part = await db.get(EzsSparePart, unit.nomenclature_id) if unit.nomenclature_id else None
    sup = await db.get(Counterparty, unit.supplier_id) if unit.supplier_id else None
    own = await db.get(Counterparty, unit.owner_id) if unit.owner_id else None
    return {
        "nomenclature": {"id": str(part.id), "name": part.name, "kind": part.kind,
                         "kindLabel": KINDS.get(part.kind, ("", "", False))[0],
                         "account": part.account or default_account(part.kind)} if part is not None else None,
        "supplierName": sup.name if sup is not None else None,
        "ownerRefName": own.name if own is not None else None,
        # Счёт, на котором единица числится сейчас (07 → 08.03 → 01.01).
        "account": unit_account(unit.state, await stock_account(db, unit)),
    }


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
        "nomenclatureId": "nomenclature_id", "supplierId": "supplier_id", "ownerId": "owner_id",
        "purchaseAmount": "purchase_amount", "vatAmount": "vat_amount", "accountingNo": "accounting_no",
        "okof": "okof", "depreciationGroup": "depreciation_group", "usefulLifeMonths": "useful_life_months",
        "bpRef": "bp_ref",
    }
    from app.services.ezs_equipment_docs import check_counterparty
    from app.services.ezs_accounting import SERIAL_KINDS
    if data.get("nomenclatureId"):
        part = await db.get(EzsSparePart, uuid.UUID(data["nomenclatureId"]))
        if part is None or part.company_id != cid:
            raise HTTPException(400, "Номенклатура не найдена в справочнике пространства")
        if part.kind not in SERIAL_KINDS:
            raise HTTPException(400, f"«{part.name}» учитывается количеством, а не по экземплярам — "
                                     "выберите номенклатуру вида «Зарядная станция» или «Оборудование»")
        data["nomenclatureId"] = part.id
    for key in ("supplierId", "ownerId"):
        if data.get(key):
            data[key] = (await check_counterparty(db, cid, data[key])).id
    # Стоимость и номенклатура дают сумму и счёт всем прошлым движениям единицы: в
    # закрытом периоде их не меняют, как в 1С после даты запрета изменений.
    from app.services.ezs_accounting import money

    def differs(k: str) -> bool:
        old, new = getattr(unit, mapping[k]), data[k]
        if k == "nomenclatureId":
            return (str(old) if old else None) != (str(new) if new else None)
        return (None if old is None else money(old)) != (None if new is None else money(new))
    if any(differs(k) for k in ("purchaseAmount", "vatAmount", "nomenclatureId") if k in data):
        from app.services.ezs_equipment import closed_until, live_moves
        closed = await closed_until(db, cid)
        first = (await db.execute(select(func.min(EzsEquipmentMovement.occurred_on)).where(
            EzsEquipmentMovement.unit_id == unit.id, *live_moves()))).scalar() if closed else None
        if first and first[:10] <= closed:
            raise HTTPException(409, f"Единица на учёте с {first[:10]}, а период закрыт по {closed}: стоимость и "
                                     "номенклатура изменили бы сверенные с бухгалтерией остатки")
    for key in ("nomenclatureId", "supplierId", "ownerId"):
        if key in data and not data[key]:
            data[key] = None
    for key in ("accountingNo", "okof", "depreciationGroup", "bpRef"):
        if key in data:
            data[key] = (data[key] or "").strip() or None
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
    return {**_unit_out(unit, locs), **await _unit_refs(db, unit)}


@router.delete("/units/{unit_id}")
async def delete_unit(
    unit_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    unit = await db.get(EzsEquipmentUnit, unit_id)
    if unit is None or unit.company_id != cid:
        raise HTTPException(404, "Единица не найдена")
    # Стереть можно только карточку, заведённую по ошибке и ничем не подтверждённую:
    # одно поступление без документа и без поставки. Всё остальное убирается
    # отменой документа или списанием — иначе приход исчезал бы без следа.
    moves = (await db.execute(
        select(EzsEquipmentMovement).where(EzsEquipmentMovement.unit_id == unit_id)
    )).scalars().all()
    if len(moves) > 1 or any(m.op != "receipt" or m.document_id or m.supply_id for m in moves) or unit.supply_id:
        raise HTTPException(409, "Карточку с документом, поставкой или историей движений удалить нельзя — "
                                 "отмените документ либо оформите списание")
    db.add(AuditEvent(
        company_id=cid, user_id=str(user.id), user_name=user.name or user.email, action="equipment_unit_delete",
        details=json.dumps({"unit_id": str(unit_id), "serial_number": unit.serial_number,
                            "vendor": unit.vendor or unit.brand, "model": unit.model, "state": unit.state,
                            "location_id": unit.current_location_id}, ensure_ascii=False)))
    await db.delete(unit)
    return {"deleted": str(unit_id)}


@router.post("/units/{unit_id}/movements")
async def unit_movement(
    unit_id: uuid.UUID, body: MovementIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    # Прежняя форма (корректировка из карточки) проводится тем же документом, что и
    # новая: номер присваивается сам, движение без документа не возникает.
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    p = _payload_movement(body)
    doc = await D.post_document(db, cid, user, {
        **p, "unit_ids": [str(unit_id)],
        # Дату ввода и вывода называет человек: сегодняшний день за него не подставляется.
        "doc_date": p.get("occurred_on") or ("" if body.op in ("commissioning", "write_off", "to_vendor")
                                              else date.today().isoformat()),
        "counterparty_text": p.get("counterparty")})
    unit = await db.get(EzsEquipmentUnit, unit_id)
    await db.refresh(unit)
    move = (await db.execute(select(EzsEquipmentMovement).where(
        EzsEquipmentMovement.unit_id == unit_id,
        EzsEquipmentMovement.document_id == uuid.UUID(doc["id"])))).scalar_one()
    locs = await _locations_map(db, cid)
    return {"unit": _unit_out(unit, locs),
            "movement": _move_out(move, locs, docs={move.document_id: doc["number"]}),
            "documentNumber": doc["number"], "warnings": doc["warnings"]}


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
    number = await _auto_doc(db, cid, user, "dismantle", move, doc_date=body.occurredOn,
                             basis=body.basis, comment=body.comment)
    await db.refresh(unit)
    await db.refresh(move)
    locs = await _locations_map(db, cid)
    return {"unit": _unit_out(unit, locs), "movement": _move_out(move, locs, docs={move.document_id: number}),
            "unitCreated": created, "documentNumber": number}


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
    # Контур рабочей области здесь НЕ применяется намеренно: 72 движения из 88 не
    # имеют ни точки отправления, ни точки прибытия, и любое сужение обнуляет
    # журнал. Вернуть, когда точки в движениях будут заполняться (проверять
    # запросом, а не на глаз).
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
    supplies = await _supplies_map(db, cid, [m.supply_id for m, _ in rows])
    docs = await _doc_numbers(db, [m for m, _ in rows])
    return {"items": [_move_out(m, locs, unit=u, supplies=supplies, docs=docs) for m, u in rows], "total": total}


# ─── склады и обзор ─────────────────────────────────────────────────────────

# ─── документы движения и карточка склада ───────────────────────────────────

class EquipmentDocIn(BaseModel):
    op: str
    unitIds: list[str] = Field(default_factory=list)
    docDate: str
    number: str | None = None
    toLocationId: str | None = None
    counterpartyId: str | None = None
    contractId: str | None = None
    responsibleFrom: str | None = None
    responsibleTo: str | None = None
    basis: str | None = None
    comment: str | None = None
    custodian: str | None = None
    reservedForLocationId: str | None = None
    toState: str | None = None
    syncPassport: bool = False
    details: dict[str, Any] | None = None
    primaryNumber: str | None = None
    primaryDate: str | None = None
    draft: bool = False              # сохранить черновиком: номер занят, движений нет


class WarehouseIn(BaseModel):
    name: str | None = None
    address: str | None = None
    ownership: str | None = None
    counterpartyId: str | None = None
    contractId: str | None = None
    responsible: str | None = None
    responsibleUserId: str | None = None
    phone: str | None = None
    note: str | None = None
    bpCode: str | None = None
    bpRef: str | None = None


def _doc_payload(body: EquipmentDocIn) -> dict[str, Any]:
    return {
        "op": body.op, "unit_ids": body.unitIds, "doc_date": body.docDate, "number": body.number,
        "to_location_id": body.toLocationId, "counterparty_id": body.counterpartyId,
        "contract_id": body.contractId, "responsible_from": body.responsibleFrom,
        "responsible_to": body.responsibleTo, "basis": body.basis, "comment": body.comment,
        "custodian": body.custodian, "reserved_for_location_id": body.reservedForLocationId,
        "to_state": body.toState, "sync_passport": body.syncPassport, "details": body.details,
        "primary_number": body.primaryNumber, "primary_date": body.primaryDate,
    }


@router.get("/documents/meta")
async def documents_meta(user: User = Depends(get_current_user)):
    """Виды документов, подходящие типы договоров, виды владения складом."""
    from app.services import ezs_equipment_docs as D
    return {"kinds": {op: {"prefix": p, "title": t} for op, (p, t) in D.DOC_KINDS.items()},
            "contractTypes": {k: list(v) for k, v in D.CONTRACT_TYPES.items()},
            "counterpartyRequired": sorted(D.COUNTERPARTY_REQUIRED), "ownership": D.OWNERSHIP,
            "storageForms": {k: {"prefix": p, "title": t} for k, (p, t) in D.STORAGE_FORMS.items()}}


@router.get("/documents")
async def documents_list(
    company_id: str = Query(...), op: str | None = Query(None), q: str | None = Query(None),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    status: str | None = Query(None), counterparty_id: uuid.UUID | None = Query(None),
    contract_id: uuid.UUID | None = Query(None), location_id: str | None = Query(None),
    unit_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.list_documents(db, cid, op=op, q=q, date_from=date_from, date_to=date_to, status=status,
                                  counterparty_id=counterparty_id, contract_id=contract_id,
                                  location_id=location_id, unit_id=unit_id, limit=limit, offset=offset)


@router.get("/documents/{doc_id}")
async def documents_get(
    doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.get_document(db, cid, doc_id)


@router.post("/documents")
async def documents_post(
    body: EquipmentDocIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Провести документ движения по одной или нескольким единицам — атомарно,
    либо сохранить черновиком (`draft`)."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    if body.draft:
        return await D.save_draft(db, cid, user, _doc_payload(body))
    return await D.post_document(db, cid, user, _doc_payload(body))


@router.patch("/documents/{doc_id}")
async def documents_draft_update(
    doc_id: uuid.UUID, body: EquipmentDocIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Изменить черновик: проведённый документ не правится."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.save_draft(db, cid, user, _doc_payload(body), doc_id=doc_id)


@router.post("/documents/{doc_id}/post")
async def documents_draft_post(
    doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Провести черновик: те же проверки, что у документа, проведённого сразу."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.post_draft(db, cid, user, doc_id)


@router.delete("/documents/{doc_id}")
async def documents_draft_delete(
    doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Удалить черновик. Проведённый документ не удаляется — он отменяется."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.delete_draft(db, cid, doc_id)


class CancelIn(BaseModel):
    reason: str = ""


@router.post("/documents/{doc_id}/cancel")
async def documents_cancel(
    doc_id: uuid.UUID, body: CancelIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Отменить проведённый документ: единицы возвращаются в прежнее состояние."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.cancel_document(db, cid, user, doc_id, body.reason)


@router.get("/audit")
async def equipment_audit(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Разбор данных складского учёта: что не так и каким документом закрывается."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.audit(db, cid)


@router.get("/warehouses/{loc_id}/card")
async def warehouse_card(
    loc_id: str, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    loc = await db.get(ServiceLocation, loc_id)
    if loc is None or loc.company_id != cid or loc.type != "warehouse":
        raise HTTPException(404, "Склад не найден")
    return await D.warehouse_card(db, cid, loc)


@router.post("/warehouses")
async def warehouse_create(
    body: WarehouseIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.save_warehouse(db, cid, None, body.model_dump())


@router.patch("/warehouses/{loc_id}")
async def warehouse_update(
    loc_id: str, body: WarehouseIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.save_warehouse(db, cid, loc_id, body.model_dump(exclude_unset=True))


class WarehouseStatusIn(BaseModel):
    closed: bool


@router.post("/warehouses/{loc_id}/status")
async def warehouse_status(
    loc_id: str, body: WarehouseStatusIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Закрыть пустой склад (уходит из выбора, история остаётся) или открыть снова."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    return await D.set_warehouse_status(db, cid, loc_id, body.closed)


@router.delete("/warehouses/{loc_id}")
async def warehouse_delete(
    loc_id: str, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Удалить склад, заведённый по ошибке: без единиц, остатков и истории."""
    from app.services import ezs_equipment_docs as D
    cid = await assert_company_member(company_id, user, db)
    out = await D.delete_warehouse(db, cid, loc_id)
    db.add(AuditEvent(company_id=cid, user_id=str(user.id), user_name=user.name or user.email,
                      action="equipment_warehouse_delete", details=json.dumps(out, ensure_ascii=False)))
    return out


# ─── настройки учёта: закрытый период ───────────────────────────────────────

class EquipmentSettingsIn(BaseModel):
    closedUntil: str | None = None


@router.get("/settings")
async def equipment_settings(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.ezs_equipment import closed_until
    cid = await assert_company_member(company_id, user, db)
    return {"closedUntil": await closed_until(db, cid)}


@router.put("/settings")
async def equipment_settings_update(
    body: EquipmentSettingsIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Закрыть период по дату включительно — как дата запрета изменений в 1С.

    Меняет администратор пространства: закрытие отрезает отмену документов, и
    поставить его по ошибке рядовой участник не должен.
    """
    from app.models import Company, UserCompany
    cid = await assert_company_member(company_id, user, db)
    if not user.is_superadmin:
        role = (await db.execute(select(UserCompany.role).where(
            UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
        if role != "admin":
            raise HTTPException(403, "Закрывает период администратор пространства")
    day = (body.closedUntil or "").strip() or None
    if day:
        try:
            day = date.fromisoformat(day).isoformat()
        except ValueError:
            raise HTTPException(400, "Дата закрытия периода указана неверно")
    company = await db.get(Company, cid)
    custom = dict(company.customization or {})
    custom["equipment"] = {**(custom.get("equipment") or {}), "closedUntil": day}
    company.customization = custom
    db.add(AuditEvent(company_id=cid, user_id=str(user.id), user_name=user.name or user.email,
                      action="equipment_period_close", details=json.dumps({"closedUntil": day}, ensure_ascii=False)))
    await db.flush()
    return {"closedUntil": day}


@router.get("/people")
async def equipment_people(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Участники пространства для выбора МОЛ склада: только имя, без почты и ролей."""
    from app.models import UserCompany
    from app.services.service_accounts import not_service
    cid = await assert_company_member(company_id, user, db)
    rows = (await db.execute(select(User).join(UserCompany, UserCompany.user_id == User.id).where(
        UserCompany.company_id == cid, not_service()).order_by(User.name))).scalars().all()
    return [{"id": str(u.id), "name": u.name or u.email} for u in rows]


@router.get("/accounting/meta")
async def accounting_meta(user: User = Depends(get_current_user)):
    """Справочники учёта под 1С: виды номенклатуры, счета, единицы ОКЕИ, ставки НДС."""
    from app.services.ezs_accounting import ACCOUNTS, COST_ACCOUNTS, DEFAULT_COST_ACCOUNT, KINDS, OKEI, VAT_RATES
    return {"kinds": {k: {"label": l, "account": a, "serial": s} for k, (l, a, s) in KINDS.items()},
            "accounts": ACCOUNTS, "okei": OKEI, "vatRates": list(VAT_RATES),
            "costAccounts": COST_ACCOUNTS, "defaultCostAccount": DEFAULT_COST_ACCOUNT}


class NomenclatureFromUnitsIn(BaseModel):
    unitIds: list[str] = Field(default_factory=list)
    dryRun: bool = False


@router.post("/nomenclature/from-units")
async def nomenclature_from_units(
    body: NomenclatureFromUnitsIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Связать единицы без номенклатуры с номенклатурой по их модели.

    Группа — «производитель модель» из карточки; номенклатура с таким названием
    берётся из справочника, иначе заводится видом «Зарядная станция» (счёт 07).
    `dryRun` показывает группы, ничего не меняя.
    """
    from app.services.ezs_equipment_reports import unit_item
    cid = await assert_company_member(company_id, user, db)
    U = EzsEquipmentUnit
    q = select(U).where(U.company_id == cid, U.nomenclature_id.is_(None))
    if body.unitIds:
        q = q.where(U.id.in_([uuid.UUID(i) for i in body.unitIds]))
    units = (await db.execute(q)).scalars().all()
    groups: dict[str, list[EzsEquipmentUnit]] = {}
    for u in units:
        groups.setdefault(unit_item(u, {})[1], []).append(u)
    parts = {p.name.strip().lower(): p for p in (await db.execute(select(EzsSparePart).where(
        EzsSparePart.company_id == cid))).scalars().all()}
    out = []
    for name, members in sorted(groups.items()):
        found = parts.get(name.lower())
        out.append({"name": name, "units": len(members), "exists": found is not None,
                    "nomenclatureId": str(found.id) if found is not None else None})
        if body.dryRun or name == "Модель не указана":
            continue
        if found is None:
            first = members[0]
            found = EzsSparePart(company_id=cid, name=name[:300], kind="station", category="other",
                                 vendor=first.vendor or first.brand, model=first.model, unit_label="шт",
                                 unit_code="796", vat_rate="20%", account="07")
            db.add(found)
            await db.flush()
            parts[name.lower()] = found
            out[-1]["nomenclatureId"] = str(found.id)
        for u in members:
            u.nomenclature_id = found.id
    await db.flush()
    return {"groups": out, "linked": 0 if body.dryRun else sum(g["units"] for g in out if g["name"] != "Модель не указана")}


@router.get("/warehouses/summary")
async def warehouses_summary(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Остатки по складам: единицы по состояниям + позиции/количество ЗИП;
    плюс синтетические строки «у подрядчика» / «у производителя».

    Контур рабочей области здесь НЕ применяется намеренно: региона нет ни у
    одного из шести складов, и сужение по нему оставляет пустой экран. Вернуть,
    когда у складов появится регион.
    """
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

    # Сумма остатка склада: стоимость единиц на складе и сумма остатка ЗИП.
    unit_cost = dict((await db.execute(
        select(U.current_location_id, func.coalesce(func.sum(U.purchase_amount), 0))
        .where(U.company_id == cid, U.current_location_id.is_not(None),
               U.state.in_(("in_stock_new", "in_stock_used", "reserved")))
        .group_by(U.current_location_id))).all())
    spare_cost = dict((await db.execute(
        select(EzsSparePartStock.location_id, func.coalesce(func.sum(EzsSparePartStock.amount), 0))
        .where(EzsSparePartStock.company_id == cid).group_by(EzsSparePartStock.location_id))).all())
    from app.services.ezs_equipment_docs import warehouse_card as _card
    out = []
    for wh in sorted(warehouses, key=lambda w: (w.status == "closed", w.name)):
        states = by_wh.get(wh.id, {})
        sp = spare_by_wh.get(wh.id, {"positions": 0, "qty": 0.0})
        out.append({
            "card": await _card(db, cid, wh),
            "location": _loc_brief(wh),
            "status": "closed" if wh.status == "closed" else "active",
            "unitsByState": states,
            "unitsTotal": sum(states.values()),
            "sparePositions": sp["positions"],
            "spareQty": sp["qty"],
            "amount": float(unit_cost.get(wh.id, 0) or 0) + float(spare_cost.get(wh.id, 0) or 0),
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
    scope: ScopeQ = Depends(),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    U = EzsEquipmentUnit
    # Плитки обязаны считаться по тому же контуру, что и список под ними: иначе
    # «всего 691» над списком из 84 читается как потеря записей.
    base = [U.company_id == cid]
    in_scope = scope.unit_cond(cid)
    if in_scope is not None:
        base.append(in_scope)
    by_state = {r[0]: int(r[1]) for r in (await db.execute(
        select(U.state, func.count()).where(*base).group_by(U.state)
    )).all()}
    by_custodian = {r[0]: int(r[1]) for r in (await db.execute(
        select(U.custodian, func.count()).where(*base).group_by(U.custodian)
    )).all()}
    # Выражение производителя берём ОДНИМ объектом: каждый вызов `_vendor_col()`
    # заводит свой bind-параметр для `nullif(vendor, '')`, и Postgres считает
    # SELECT и GROUP BY разными выражениями — вся ручка падала с GroupingError.
    vendor_col = _vendor_col()
    by_vendor = [{"vendor": r[0] or "—", "count": int(r[1])} for r in (await db.execute(
        select(vendor_col, func.count()).where(*base)
        .group_by(vendor_col).order_by(func.count().desc())
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
    from app.services.ezs_accounting import KINDS, default_account, unit_label
    return {
        "id": str(p.id), "name": p.name, "category": p.category,
        "vendor": p.vendor, "article": p.article,
        "compatibleModels": p.compatible_models, "unitLabel": unit_label(p.unit_code, p.unit_label),
        "notes": p.notes, "isArchived": p.is_archived,
        "kind": p.kind or "spare", "kindLabel": KINDS.get(p.kind or "spare", ("", "", False))[0],
        "serial": KINDS.get(p.kind or "spare", ("", "", False))[2],
        "model": p.model, "unitCode": p.unit_code, "vatRate": p.vat_rate,
        "account": p.account or default_account(p.kind), "bpRef": p.bp_ref,
    }


def _part_fields(body: SparePartIn) -> dict[str, Any]:
    """Поля номенклатуры из формы с проверкой справочников учёта."""
    from app.services.ezs_accounting import ACCOUNTS, KINDS, OKEI, VAT_RATES, default_account, okei_code
    if body.kind not in KINDS:
        raise HTTPException(400, "Неизвестный вид номенклатуры")
    code = (body.unitCode or "").strip() or okei_code(body.unitLabel)
    if code not in OKEI:
        raise HTTPException(400, "Единица измерения — из классификатора ОКЕИ")
    if body.vatRate and body.vatRate not in VAT_RATES:
        raise HTTPException(400, "Ставка НДС — 20%, 10%, 0% или «Без НДС»")
    account = (body.account or "").strip() or default_account(body.kind)
    if account not in ACCOUNTS:
        raise HTTPException(400, f"Счёт учёта {account} не из плана счетов раздела")
    return {"kind": body.kind, "model": (body.model or "").strip() or None, "unit_code": code,
            "unit_label": OKEI[code], "vat_rate": body.vatRate or None, "account": account,
            "bp_ref": (body.bpRef or "").strip() or None}


@router.get("/spare-parts")
async def list_spare_parts(
    company_id: str = Query(...),
    q: str | None = Query(None), category: str | None = Query(None),
    include_archived: bool = Query(False),
    kind: str | None = Query(None), include_serial: bool = Query(False),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Номенклатура. По умолчанию — количественная (ЗИП, материалы): её показывают
    остатки и строки документов ЗИП. Модели станций — `include_serial` или `kind`."""
    from app.services.ezs_accounting import SERIAL_KINDS
    cid = await assert_company_member(company_id, user, db)
    P = EzsSparePart
    conds = [P.company_id == cid]
    if not include_archived:
        conds.append(P.is_archived.is_(False))
    if category:
        conds.append(P.category == category)
    if kind:
        conds.append(P.kind.in_(kind.split(",")))
    elif not include_serial:
        conds.append(P.kind.notin_(tuple(SERIAL_KINDS)))
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
            "qty": float(s.qty), "amount": float(s.amount or 0),
        })
    units_by_part = dict((await db.execute(select(EzsEquipmentUnit.nomenclature_id, func.count()).where(
        EzsEquipmentUnit.company_id == cid, EzsEquipmentUnit.nomenclature_id.is_not(None))
        .group_by(EzsEquipmentUnit.nomenclature_id))).all())
    out = []
    for p in parts:
        rows = by_part.get(str(p.id), [])
        out.append({**_part_out(p), "totalQty": sum(r["qty"] for r in rows),
                    "totalAmount": round(sum(r["amount"] for r in rows), 2), "byLocation": rows,
                    "units": int(units_by_part.get(p.id) or 0)})
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
        compatible_models=body.compatibleModels,
        notes=body.notes, **_part_fields(body),
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
    from app.services.ezs_accounting import SERIAL_KINDS
    fields = _part_fields(body)
    # Вид меняет способ учёта: запчасть с остатком не становится станцией, а модель
    # с единицами — количественной позицией.
    if (fields["kind"] in SERIAL_KINDS) != ((p.kind or "spare") in SERIAL_KINDS):
        used = int((await db.execute(select(func.count()).select_from(EzsSparePartMovement).where(
            EzsSparePartMovement.part_id == part_id))).scalar_one()) + int((await db.execute(
            select(func.count()).select_from(EzsEquipmentUnit).where(
                EzsEquipmentUnit.nomenclature_id == part_id))).scalar_one())
        if used:
            raise HTTPException(409, "По номенклатуре уже есть движения или единицы — вид учёта "
                                     "(по экземплярам или количеством) не меняется")
    dup = (await db.execute(select(EzsSparePart.id).where(
        EzsSparePart.company_id == cid, EzsSparePart.id != part_id,
        func.lower(EzsSparePart.name) == body.name.strip().lower()).limit(1))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(409, f"Номенклатура «{body.name.strip()}» уже есть")
    p.name = body.name.strip()
    p.category = body.category
    p.vendor = body.vendor
    p.article = body.article
    p.compatible_models = body.compatibleModels
    p.notes = body.notes
    for k, v in fields.items():
        setattr(p, k, v)
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
    )).scalar_one()) + int((await db.execute(
        select(func.count()).select_from(EzsEquipmentUnit).where(EzsEquipmentUnit.nomenclature_id == part_id)
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
    """Одна строка — тот же документ ЗИП с автономером: движений без документа не бывает.
    Корректировка оформляется описью на одну позицию (qty — фактический остаток)."""
    from datetime import date
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    inventory = body.op == "correction"
    if inventory and not (body.comment or "").strip():
        raise HTTPException(400, "Для корректировки обязателен комментарий")
    doc = await SD.post_document(db, cid, user, {
        "op": "inventory" if inventory else body.op,
        "doc_date": body.occurredOn or date.today().isoformat(),
        "lines": [{"partId": str(part_id), "fact" if inventory else "qty": body.qty}],
        "from_location_id": body.fromLocationId, "to_location_id": body.toLocationId,
        "target_unit_id": body.targetUnitId, "target_location_id": body.targetLocationId,
        "basis": body.basis, "comment": body.comment,
    })
    move_id = (await db.execute(select(EzsSparePartMovement.id).where(
        EzsSparePartMovement.document_id == uuid.UUID(doc["id"])).limit(1))).scalar_one_or_none()
    stock = (await db.execute(
        select(EzsSparePartStock).where(
            EzsSparePartStock.company_id == cid, EzsSparePartStock.part_id == part_id)
    )).scalars().all()
    locs = await _locations_map(db, cid)
    return {
        "movementId": str(move_id) if move_id else None,  # опись без расхождения движения не даёт
        "documentId": doc["id"], "documentNumber": doc["number"],
        "stock": [{"locationId": s.location_id,
                   "locationName": locs.get(s.location_id).name if locs.get(s.location_id) else "—",
                   "qty": float(s.qty)} for s in stock],
    }


@router.get("/spare-parts/movements/journal")
async def spare_movements_journal(
    company_id: str = Query(...),
    part_id: uuid.UUID | None = Query(None), location_id: str | None = Query(None),
    op: str | None = Query(None),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(200, le=1000),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.models import EzsSpareDocument
    cid = await assert_company_member(company_id, user, db)
    M = EzsSparePartMovement
    conds = [M.company_id == cid]
    if part_id:
        conds.append(M.part_id == part_id)
    if op:
        conds.append(M.op == op)
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
    doc_ids = {m.document_id for m, _ in rows if m.document_id}
    docs = {i: (n, note) for i, n, note in (await db.execute(select(
        EzsSpareDocument.id, EzsSpareDocument.number, EzsSpareDocument.target_note).where(
        EzsSpareDocument.id.in_(doc_ids)))).all()} if doc_ids else {}
    unit_ids = {m.target_unit_id for m, _ in rows if m.target_unit_id}
    units = {u.id: u for u in (await db.execute(select(EzsEquipmentUnit).where(
        EzsEquipmentUnit.id.in_(unit_ids)))).scalars().all()} if unit_ids else {}
    items = []
    for m, p in rows:
        tu = units.get(m.target_unit_id)
        items.append({
            "id": str(m.id), "part": {"id": str(p.id), "name": p.name, "unitLabel": p.unit_label},
            "op": m.op, "qty": float(m.qty), "delta": float(m.delta) if m.delta is not None else None,
            "documentId": str(m.document_id) if m.document_id else None,
            "documentNumber": docs.get(m.document_id, (None, None))[0],
            # получатель расхода — названием: станция в эксплуатации — именем станции,
            # прочая единица — моделью; объект без привязки к станции — текстом документа
            "targetUnit": {"id": str(tu.id), "serialNumber": tu.serial_number,
                           "name": (getattr(locs.get(tu.current_location_id or ""), "name", None)
                                    if tu.state == "in_operation" else None)
                           or " ".join(x for x in (tu.vendor or tu.brand, tu.model) if x)} if tu else None,
            "targetNote": docs.get(m.document_id, (None, None))[1],
            "fromLocation": _loc_brief(locs.get(m.from_location_id or "")),
            "toLocation": _loc_brief(locs.get(m.to_location_id or "")),
            "targetUnitId": str(m.target_unit_id) if m.target_unit_id else None,
            "targetLocation": _loc_brief(locs.get(m.target_location_id or "")),
            "occurredOn": m.occurred_on, "basis": m.basis, "comment": m.comment,
            "createdBy": m.created_by_name,
        })
    return {"items": items, "total": total}


# ─── документы ЗИП: приход, отпуск, перемещение, списание, инвентаризация ─────

class SpareDocLineIn(BaseModel):
    partId: str
    qty: float | None = None         # у описи не заполняется
    fact: float | None = None        # фактическое количество — только у описи
    price: float | None = Field(None, ge=0)  # цена без НДС: приход; у описи — оценка излишка


class SpareDocIn(BaseModel):
    id: uuid.UUID | None = None      # ключ от формы: повторная отправка не проводит дважды
    op: str
    docDate: str
    number: str | None = None
    lines: list[SpareDocLineIn] = Field(default_factory=list)
    fromLocationId: str | None = None
    toLocationId: str | None = None
    targetUnitId: str | None = None
    targetLocationId: str | None = None
    targetNote: str | None = None    # объект без привязки к станции — текстом
    repairDocumentId: str | None = None
    counterpartyId: str | None = None
    contractId: str | None = None
    responsibleFrom: str | None = None
    responsibleTo: str | None = None
    basis: str | None = None
    comment: str | None = None
    primaryNumber: str | None = None
    primaryDate: str | None = None
    costAccount: str | None = None   # счёт затрат отпуска и списания (20.01, 91.02…)
    costItem: str | None = None      # статья затрат
    draft: bool = False


class SpareDocCancelIn(BaseModel):
    reason: str


def _spare_doc_payload(body: SpareDocIn) -> dict[str, Any]:
    return {
        "id": body.id, "op": body.op, "doc_date": body.docDate, "number": body.number,
        "lines": [ln.model_dump() for ln in body.lines],
        "from_location_id": body.fromLocationId, "to_location_id": body.toLocationId,
        "target_unit_id": body.targetUnitId, "target_location_id": body.targetLocationId,
        "target_note": body.targetNote, "repair_document_id": body.repairDocumentId,
        "counterparty_id": body.counterpartyId, "contract_id": body.contractId,
        "responsible_from": body.responsibleFrom, "responsible_to": body.responsibleTo,
        "basis": body.basis, "comment": body.comment,
        "primary_number": body.primaryNumber, "primary_date": body.primaryDate,
        "costAccount": body.costAccount, "costItem": body.costItem,
    }


@router.get("/spare-documents/count-sheet")
async def spare_documents_count_sheet(
    company_id: str = Query(...), location_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Лист пересчёта склада: текущие остатки как заготовка строк описи."""
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.count_sheet(db, cid, location_id)


@router.get("/spare-documents")
async def spare_documents_list(
    company_id: str = Query(...), op: str | None = Query(None), status: str | None = Query(None),
    location_id: str | None = Query(None), counterparty_id: uuid.UUID | None = Query(None),
    contract_id: uuid.UUID | None = Query(None), part_id: uuid.UUID | None = Query(None),
    date_from: str | None = Query(None), date_to: str | None = Query(None), q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.list_documents(
        db, cid, op=op, status=status, location_id=location_id, counterparty_id=counterparty_id,
        contract_id=contract_id, part_id=part_id, q=q, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset)


@router.get("/spare-documents/{doc_id}")
async def spare_documents_get(
    doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.get_document(db, cid, doc_id)


@router.post("/spare-documents")
async def spare_documents_post(
    body: SpareDocIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Провести документ ЗИП на одну или несколько строк — атомарно, либо сохранить черновиком."""
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    if body.draft:
        return await SD.save_draft(db, cid, user, _spare_doc_payload(body))
    return await SD.post_document(db, cid, user, _spare_doc_payload(body))


@router.patch("/spare-documents/{doc_id}")
async def spare_documents_draft_update(
    doc_id: uuid.UUID, body: SpareDocIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.save_draft(db, cid, user, _spare_doc_payload(body), doc_id=doc_id)


@router.post("/spare-documents/{doc_id}/post")
async def spare_documents_draft_post(
    doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.post_draft(db, cid, user, doc_id)


@router.delete("/spare-documents/{doc_id}")
async def spare_documents_draft_delete(
    doc_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.delete_draft(db, cid, doc_id)


@router.post("/spare-documents/{doc_id}/cancel")
async def spare_documents_cancel(
    doc_id: uuid.UUID, body: SpareDocCancelIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Отменить документ: сторно движений возвращает остаток, номер остаётся занят."""
    from app.services import ezs_spare_docs as SD
    cid = await assert_company_member(company_id, user, db)
    return await SD.cancel_document(db, cid, user, doc_id, body.reason)


# ─── документы поставки/возврата (слой оснований поверх движений) ────────────

class SupplyLineIn(BaseModel):
    lineKind: str = "station"        # station | spare
    partId: str | None = None        # номенклатура: ЗИП, у станции — её модель
    name: str | None = None
    qtyPlanned: float = Field(gt=0)
    unitPrice: float | None = None
    vatRate: str | None = None
    note: str | None = None
    # шаблон станции (для lineKind=station)
    vendor: str | None = None
    model: str | None = None
    stationType: str | None = None
    powerKwt: float | None = None
    connectorsCount: int | None = None
    connectorTypes: str | None = None


class SupplyIn(BaseModel):
    docType: str = "supply"          # supply | return
    number: str
    docDate: str | None = None
    counterpartyId: str | None = None
    counterpartyName: str | None = None
    contractId: str | None = None
    warehouseId: str | None = None
    currency: str = "RUB"
    vatTotal: float | None = None
    note: str | None = None
    lines: list[SupplyLineIn] = Field(default_factory=list)


class SupplyPatch(BaseModel):
    number: str | None = None
    docDate: str | None = None
    counterpartyId: str | None = None
    counterpartyName: str | None = None
    contractId: str | None = None
    warehouseId: str | None = None
    currency: str | None = None
    vatTotal: float | None = None
    note: str | None = None


class SupplyStatusIn(BaseModel):
    action: str                      # confirm | close | cancel


class ReceiveUnitIn(BaseModel):
    serial: str | None = None
    inventoryNumber: str | None = None
    warrantyUntil: str | None = None


class ReceiveIn(BaseModel):
    warehouseId: str | None = None
    occurredOn: str | None = None
    basis: str | None = None
    comment: str | None = None
    qty: float | None = None                       # ЗИП / безсерийные станции
    units: list[ReceiveUnitIn] = Field(default_factory=list)   # станции с серийниками
    unitIds: list[str] = Field(default_factory=list)           # станции к возврату
    allowOverage: bool = False


def _line_payload(ln: SupplyLineIn) -> dict[str, Any]:
    return {
        "line_kind": ln.lineKind, "part_id": ln.partId, "name": ln.name,
        "qty_planned": ln.qtyPlanned, "unit_price": ln.unitPrice,
        "vat_rate": ln.vatRate, "note": ln.note, "vendor": ln.vendor,
        "model": ln.model, "station_type": ln.stationType, "power_kwt": ln.powerKwt,
        "connectors_count": ln.connectorsCount, "connector_types": ln.connectorTypes,
    }


@router.get("/supplies")
async def list_supplies_ep(
    company_id: str = Query(...),
    doc_type: str | None = Query(None), status: str | None = Query(None),
    counterparty_id: str | None = Query(None),
    date_from: str | None = Query(None), date_to: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(100, le=500),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await ezs_supply.list_supplies(
        db, cid, doc_type=doc_type, status=status, counterparty_id=counterparty_id,
        date_from=date_from, date_to=date_to, q=q, page=page, page_size=page_size)


@router.post("/supplies")
async def create_supply_ep(
    body: SupplyIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    doc = await ezs_supply.create_supply(db, cid, user, {
        "doc_type": body.docType, "number": body.number, "doc_date": body.docDate,
        "counterparty_id": body.counterpartyId, "counterparty_name": body.counterpartyName,
        "contract_id": body.contractId, "warehouse_id": body.warehouseId,
        "currency": body.currency, "vat_total": body.vatTotal, "note": body.note,
        "lines": [_line_payload(ln) for ln in body.lines],
    })
    await db.flush()
    return await ezs_supply.get_supply(db, cid, doc.id)


@router.get("/supplies/{supply_id}")
async def get_supply_ep(
    supply_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.patch("/supplies/{supply_id}")
async def update_supply_ep(
    supply_id: uuid.UUID, body: SupplyPatch, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    data = body.model_dump(exclude_unset=True)
    payload = {
        {"number": "number", "docDate": "doc_date", "counterpartyId": "counterparty_id",
         "counterpartyName": "counterparty_name", "contractId": "contract_id",
         "warehouseId": "warehouse_id", "currency": "currency", "vatTotal": "vat_total",
         "note": "note"}[k]: v for k, v in data.items()
    }
    await ezs_supply.update_supply(db, cid, user, supply_id, payload)
    await db.flush()
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.delete("/supplies/{supply_id}")
async def delete_supply_ep(
    supply_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    await ezs_supply.delete_supply(db, cid, supply_id)
    return {"deleted": str(supply_id)}


@router.post("/supplies/{supply_id}/lines")
async def add_supply_line_ep(
    supply_id: uuid.UUID, body: SupplyLineIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    await ezs_supply.add_line(db, cid, supply_id, _line_payload(body))
    await db.flush()
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.patch("/supplies/{supply_id}/lines/{line_id}")
async def update_supply_line_ep(
    supply_id: uuid.UUID, line_id: uuid.UUID, body: SupplyLineIn,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    await ezs_supply.update_line(db, cid, supply_id, line_id, _line_payload(body))
    await db.flush()
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.delete("/supplies/{supply_id}/lines/{line_id}")
async def delete_supply_line_ep(
    supply_id: uuid.UUID, line_id: uuid.UUID, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    await ezs_supply.delete_line(db, cid, supply_id, line_id)
    await db.flush()
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.post("/supplies/{supply_id}/status")
async def supply_status_ep(
    supply_id: uuid.UUID, body: SupplyStatusIn, company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    await ezs_supply.set_status(db, cid, user, supply_id, body.action)
    await db.flush()
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.post("/supplies/{supply_id}/lines/{line_id}/receive")
async def receive_supply_line_ep(
    supply_id: uuid.UUID, line_id: uuid.UUID, body: ReceiveIn,
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    await ezs_supply.receive_line(db, cid, user, supply_id, line_id, {
        "warehouse_id": body.warehouseId, "occurred_on": body.occurredOn,
        "basis": body.basis, "comment": body.comment, "qty": body.qty,
        "units": [{"serial": u.serial, "inventory_number": u.inventoryNumber,
                   "warranty_until": u.warrantyUntil} for u in body.units],
        "unit_ids": body.unitIds, "allow_overage": body.allowOverage,
    })
    await db.flush()
    return await ezs_supply.get_supply(db, cid, supply_id)


@router.get("/suppliers")
async def list_suppliers_ep(
    company_id: str = Query(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    cid = await assert_company_member(company_id, user, db)
    return {"items": await ezs_supply.list_suppliers(db, cid)}
