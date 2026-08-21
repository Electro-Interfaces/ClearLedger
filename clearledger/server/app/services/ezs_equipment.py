"""
Складской учёт оборудования ЭЗС: единицы (станции-железки), движения, ЗИП.

Ядро — словарь переходов TRANSITIONS: какое движение (op) допустимо из какого
состояния, куда оно переводит единицу и что требует (склад/площадка/контрагент).
Валидация переходов — ТОЛЬКО здесь; фронт получает готовый allowedOps в UnitOut.

Карточки единиц НЕ создаются массово для работающего парка (~620 станций) —
рождаются при закупке (receipt), демонтаже с площадки (автосоздание из паспорта),
Excel-импорте складского реестра или ручном вводе. После монтажа карточка живёт
дальше (in_operation) — жизненный цикл замкнут: склад → монтаж → эксплуатация →
демонтаж → склад/ремонт → возврат производителю / списание.

Транзакционность: методы НЕ коммитят (общий commit из get_db); юнит и строка
остатка ЗИП блокируются with_for_update на время операции.
"""
from __future__ import annotations

import hashlib
import io
import re
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditEvent, EzsEquipmentMovement, EzsEquipmentUnit,
    EzsSparePart, EzsSparePartMovement, EzsSparePartStock,
    ServiceLocation, User,
)

# ─── состояния и переходы ───────────────────────────────────────────────────

STATES = (
    "in_stock_new", "in_stock_used", "reserved", "in_installation",
    "in_operation", "in_repair", "returned_to_vendor", "written_off",
)
TERMINAL_STATES = {"returned_to_vendor", "written_off"}
STOCK_STATES = {"in_stock_new", "in_stock_used"}

STATE_LABELS = {
    "in_stock_new": "На складе (новая)",
    "in_stock_used": "На складе (б/у)",
    "reserved": "Резерв",
    "in_installation": "В монтаже",
    "in_operation": "В эксплуатации",
    "in_repair": "В ремонте",
    "returned_to_vendor": "Возвращена производителю",
    "written_off": "Списана",
}

OP_LABELS = {
    "receipt": "Поступление",
    "transfer": "Перемещение",
    "reserve": "Резервирование",
    "unreserve": "Снятие резерва",
    "to_installation": "Передача в монтаж",
    "commissioning": "Запуск в эксплуатацию",
    "dismantle": "Демонтаж",
    "to_repair": "Передача в ремонт",
    "from_repair": "Возврат из ремонта",
    "to_vendor": "Возврат производителю",
    "write_off": "Списание",
    "correction": "Корректировка",
}


def _back_to_stock(unit: EzsEquipmentUnit) -> str:
    """Куда возвращаться на склад: б/у-грейд единицы определяет состояние."""
    return "in_stock_used" if unit.is_used else "in_stock_new"


# op → правило перехода. from_states=None — op создаёт карточку (receipt) или
# применим из любого нетерминального (write_off) / любого вообще (correction).
# to_state: строка либо callable(unit). loc: требование к to_location
# ('warehouse'|'site'|'same_site'|None). custodian: чем становится держатель.
TRANSITIONS: dict[str, dict[str, Any]] = {
    "receipt":         {"from": None, "to": lambda u: _back_to_stock(u), "loc": "warehouse", "custodian": "warehouse"},
    "transfer":        {"from": STOCK_STATES | {"reserved"}, "to": lambda u: u.state, "loc": "warehouse", "custodian": "warehouse"},
    "reserve":         {"from": STOCK_STATES, "to": "reserved", "loc": None, "custodian": "warehouse"},
    "unreserve":       {"from": {"reserved"}, "to": lambda u: _back_to_stock(u), "loc": None, "custodian": "warehouse"},
    "to_installation": {"from": STOCK_STATES | {"reserved"}, "to": "in_installation", "loc": "site", "custodian": "site"},
    "commissioning":   {"from": {"in_installation"}, "to": "in_operation", "loc": "same_site", "custodian": "site"},
    "dismantle":       {"from": {"in_operation"}, "to": "in_stock_used", "loc": "warehouse", "custodian": "warehouse"},
    "to_repair":       {"from": STOCK_STATES | {"reserved"}, "to": "in_repair", "loc": None, "custodian": "external"},
    "from_repair":     {"from": {"in_repair"}, "to": "in_stock_used", "loc": "warehouse", "custodian": "warehouse"},
    "to_vendor":       {"from": STOCK_STATES | {"in_repair"}, "to": "returned_to_vendor", "loc": None, "custodian": "vendor"},
    "write_off":       {"from": "any_nonterminal", "to": "written_off", "loc": None, "custodian": "none"},
    "correction":      {"from": "any", "to": None, "loc": None, "custodian": None},
}


def allowed_ops(state: str) -> list[str]:
    """Операции, доступные из состояния (для UnitOut.allowedOps)."""
    out: list[str] = []
    for op, rule in TRANSITIONS.items():
        if op == "receipt":
            continue  # receipt — только создание карточки
        frm = rule["from"]
        if frm == "any":
            out.append(op)
        elif frm == "any_nonterminal":
            if state not in TERMINAL_STATES:
                out.append(op)
        elif isinstance(frm, set) and state in frm:
            out.append(op)
    return out


# ─── канонизация вендора ────────────────────────────────────────────────────

# Кириллические гомоглифы → латиница (StarСharge с кириллической «С» и т.п.)
_HOMOGLYPHS = str.maketrans("саоерхСАОЕРХ", "caoepxCAOEPX")

# Первый токен → каноническое имя вендора (ключи и кириллицей, и латиницей —
# матчим дважды: по оригиналу и по гомоглиф-транслитерации).
_VENDOR_CANON = {
    "фора": "Фора", "fora": "Фора",
    "псс": "ПСС", "pcc": "ПСС", "pss": "ПСС",
    "реватт": "Реватт", "rewatt": "Реватт",
    "парус": "Парус", "parus": "Парус",
    "терра-ток": "Терра-Ток", "терра": "Терра-Ток", "terra": "Терра-Ток",
    "starcharge": "StarCharge",
    "bosch": "Bosch", "bosh": "Bosch",
    "нартис": "НАРТИС", "nartis": "НАРТИС",
    "efacec": "Efacec", "abb": "ABB",
}


def _vendor_lookup(low: str) -> str | None:
    first = low.replace("_", " ").split()[0].strip(" .,«»\"'") if low.split() else ""
    return _VENDOR_CANON.get(first) or _VENDOR_CANON.get(low)


def canon_vendor(raw: str | None) -> str | None:
    """Нормализовать вендора к канону (по образцу canon_region).

    Матч по первому токену ДВАЖДЫ: по оригинальному lower (кириллические имена)
    и по гомоглиф-транслитерации (StarСharge с кириллической «С» → starcharge).
    Неизвестный — как есть."""
    s = str(raw or "").strip()
    if not s:
        return None
    low = s.lower().replace("ё", "е")
    return _vendor_lookup(low) or _vendor_lookup(low.translate(_HOMOGLYPHS)) or s


# ─── хелперы локаций ────────────────────────────────────────────────────────

async def _get_location(db: AsyncSession, company_id, loc_id: str,
                        want_type: str | None = None) -> ServiceLocation:
    loc = await db.get(ServiceLocation, loc_id)
    if loc is None or loc.company_id != company_id:
        raise HTTPException(404, "Локация не найдена")
    if want_type == "warehouse" and loc.type != "warehouse":
        raise HTTPException(400, f"«{loc.name}» — не склад (тип {loc.type})")
    if want_type == "site" and loc.type != "ev_charging":
        raise HTTPException(400, f"«{loc.name}» — не площадка ЭЗС (тип {loc.type})")
    return loc


def _wh_loc_id(company_id, name: str) -> str:
    """Детерминированный id склада по имени (паттерн _loc_id станций)."""
    return "wh-" + hashlib.md5(f"{company_id}|{name.strip().lower()}".encode()).hexdigest()[:20]


async def get_or_create_warehouse(db: AsyncSession, company_id, name: str) -> ServiceLocation:
    """Склад по имени (ci-trim): найти или создать ServiceLocation type=warehouse."""
    nm = name.strip()
    row = (await db.execute(
        select(ServiceLocation).where(
            ServiceLocation.company_id == company_id,
            ServiceLocation.type == "warehouse",
            func.lower(func.btrim(ServiceLocation.name)) == nm.lower(),
        ).limit(1)
    )).scalar_one_or_none()
    if row is not None:
        return row
    loc = ServiceLocation(
        id=_wh_loc_id(company_id, nm), company_id=company_id,
        code=nm, name=nm, type="warehouse", status="active",
    )
    db.add(loc)
    await db.flush()
    return loc


# ─── единицы оборудования ───────────────────────────────────────────────────

_UNIT_FIELDS = (
    "kind", "serial_number", "vendor_raw", "model", "station_type", "power_kwt",
    "connectors_count", "connector_types", "inventory_number", "supplier",
    "purchase_doc", "purchase_date", "warranty_until", "notes",
)


async def _serial_conflict(db: AsyncSession, company_id, serial: str,
                           exclude_id=None) -> bool:
    q = select(EzsEquipmentUnit.id).where(
        EzsEquipmentUnit.company_id == company_id,
        func.lower(EzsEquipmentUnit.serial_number) == serial.lower(),
    )
    if exclude_id is not None:
        q = q.where(EzsEquipmentUnit.id != exclude_id)
    return (await db.execute(q.limit(1))).scalar_one_or_none() is not None


def _movement(company_id, unit: EzsEquipmentUnit, op: str, *, user: User | None,
              from_location_id=None, to_location_id=None, from_state=None,
              to_state=None, counterparty=None, occurred_on=None, basis=None,
              comment=None, supply_id=None, supply_line_id=None) -> EzsEquipmentMovement:
    return EzsEquipmentMovement(
        company_id=company_id, unit_id=unit.id, op=op,
        from_location_id=from_location_id, to_location_id=to_location_id,
        from_state=from_state, to_state=to_state, counterparty=counterparty,
        occurred_on=occurred_on or date.today().isoformat(),
        basis=basis, comment=comment,
        supply_id=supply_id, supply_line_id=supply_line_id,
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None,
    )


async def _create_receipt_unit(
    db: AsyncSession, company_id, user: User | None, *,
    warehouse: ServiceLocation, serial: str | None, is_used: bool,
    fields: dict[str, Any], supply_id=None, supply_line_id=None,
    purchase_amount=None, vat_amount=None,
    occurred_on=None, basis=None, comment=None,
) -> EzsEquipmentUnit:
    """Создать карточку единицы на складе + первое движение receipt.

    Единый примитив прихода: зовётся из ручного create_unit и из приёмки по
    документу поставки. Серийник и склад — обязанность вызывающего (проверка
    коллизии/типа делается ДО вызова). fields — уже готовые паспортные поля
    (vendor канонизирован вызывающим)."""
    unit = EzsEquipmentUnit(
        company_id=company_id,
        serial_number=serial,
        state="in_stock_used" if is_used else "in_stock_new",
        is_used=is_used,
        current_location_id=warehouse.id,
        custodian="warehouse",
        supply_id=supply_id, supply_line_id=supply_line_id,
        purchase_amount=purchase_amount, vat_amount=vat_amount,
        **fields,
    )
    db.add(unit)
    await db.flush()
    db.add(_movement(
        company_id, unit, "receipt", user=user, to_location_id=warehouse.id,
        from_state=None, to_state=unit.state,
        supply_id=supply_id, supply_line_id=supply_line_id,
        occurred_on=occurred_on, basis=basis, comment=comment,
    ))
    return unit


async def create_unit(db: AsyncSession, company_id, user: User | None,
                      payload: dict[str, Any]) -> EzsEquipmentUnit:
    """Создать карточку единицы + первое движение receipt на склад."""
    serial = (payload.get("serial_number") or "").strip() or None
    if serial and await _serial_conflict(db, company_id, serial):
        raise HTTPException(409, f"Единица с серийным номером «{serial}» уже есть")
    wh_id = payload.get("initial_location_id")
    if not wh_id:
        raise HTTPException(400, "Укажите склад поступления")
    wh = await _get_location(db, company_id, wh_id, want_type="warehouse")

    fields = {k: payload.get(k) for k in _UNIT_FIELDS
              if k != "serial_number" and payload.get(k) is not None}
    fields["vendor"] = canon_vendor(payload.get("vendor") or payload.get("vendor_raw"))
    return await _create_receipt_unit(
        db, company_id, user, warehouse=wh, serial=serial,
        is_used=bool(payload.get("is_used")), fields=fields,
        occurred_on=payload.get("occurred_on"), basis=payload.get("basis"),
        comment=payload.get("comment"),
    )


async def apply_movement(db: AsyncSession, company_id, user: User | None,
                         unit_id, payload: dict[str, Any]) -> tuple[EzsEquipmentUnit, EzsEquipmentMovement]:
    """Применить операцию к единице: валидация перехода + атомарное обновление."""
    op = payload.get("op")
    rule = TRANSITIONS.get(op or "")
    if rule is None or op == "receipt":
        raise HTTPException(400, f"Неизвестная операция: {op}")

    unit = (await db.execute(
        select(EzsEquipmentUnit).where(
            EzsEquipmentUnit.id == unit_id,
            EzsEquipmentUnit.company_id == company_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if unit is None:
        raise HTTPException(404, "Единица не найдена")

    # допустимость перехода
    frm = rule["from"]
    ok = (frm == "any") or \
         (frm == "any_nonterminal" and unit.state not in TERMINAL_STATES) or \
         (isinstance(frm, set) and unit.state in frm)
    if not ok:
        raise HTTPException(
            400, f"Из состояния «{STATE_LABELS.get(unit.state, unit.state)}» "
                 f"операция «{OP_LABELS.get(op, op)}» недоступна")

    from_state = unit.state
    from_loc = unit.current_location_id
    to_loc_id = payload.get("to_location_id")
    counterparty = (payload.get("counterparty") or "").strip() or None

    # требования к целевой локации
    if rule["loc"] == "warehouse":
        if not to_loc_id:
            raise HTTPException(400, "Укажите склад-получатель")
        if op == "transfer" and to_loc_id == from_loc:
            raise HTTPException(400, "Перемещение на тот же склад не имеет смысла")
        await _get_location(db, company_id, to_loc_id, want_type="warehouse")
    elif rule["loc"] == "site":
        if not to_loc_id:
            raise HTTPException(400, "Укажите площадку ЭЗС")
        await _get_location(db, company_id, to_loc_id, want_type="site")
    elif rule["loc"] == "same_site":
        to_loc_id = unit.current_location_id  # запуск там, где смонтирована
    else:
        to_loc_id = payload.get("to_location_id") if op == "correction" else None

    # целевое состояние
    if op == "correction":
        to_state = payload.get("to_state")
        if to_state not in STATES:
            raise HTTPException(400, f"Недопустимое состояние корректировки: {to_state}")
        if not (payload.get("comment") or "").strip():
            raise HTTPException(400, "Для корректировки обязателен комментарий")
    else:
        to = rule["to"]
        to_state = to(unit) if callable(to) else to

    # контрагент для внешних передач
    if op in ("to_repair", "to_vendor") and not counterparty:
        raise HTTPException(400, "Укажите контрагента (кому передано)")

    # Даты ввода и вывода обязательны при смене состояния (СТО п. 9.3, 9.5,
    # бэклог п. 15.7). Дата берётся из даты операции, а не из «сегодня»: акт
    # подписывают одним числом, а вносят другим, и подставлять день внесения —
    # ровно та ошибка, из-за которой дата ввода равнялась дню просмотра карточки.
    if op in ("commissioning", "write_off", "to_vendor"):
        occurred = (payload.get("occurred_on") or "").strip()
        if len(occurred) != 10:
            raise HTTPException(
                400, "Укажите дату операции: она становится датой "
                     + ("ввода в эксплуатацию" if op == "commissioning" else "вывода"))
        if op == "commissioning":
            unit.commissioned_on = occurred
        else:
            unit.decommissioned_on = occurred

    # применяем к юниту
    unit.state = to_state
    if op in ("dismantle", "from_repair"):
        unit.is_used = True
    if op == "reserve":
        rf = payload.get("reserved_for_location_id")
        if rf:
            await _get_location(db, company_id, rf, want_type="site")
        unit.reserved_for_location_id = rf
    if op in ("unreserve", "to_installation"):
        unit.reserved_for_location_id = None

    custod = rule["custodian"]
    if op == "correction":
        unit.current_location_id = to_loc_id
        unit.custodian = payload.get("custodian") or unit.custodian
        unit.custodian_name = counterparty or unit.custodian_name
    elif custod == "external":
        unit.current_location_id = None
        unit.custodian = payload.get("custodian") if payload.get("custodian") in ("contractor", "vendor") else "contractor"
        unit.custodian_name = counterparty
    elif custod == "vendor":
        unit.current_location_id = None
        unit.custodian = "vendor"
        unit.custodian_name = counterparty
    elif custod == "none":
        unit.current_location_id = None
        unit.custodian = "none"
        unit.custodian_name = None
    else:
        unit.current_location_id = to_loc_id
        unit.custodian = custod
        unit.custodian_name = None

    move = _movement(
        company_id, unit, op, user=user,
        from_location_id=from_loc, to_location_id=to_loc_id,
        from_state=from_state, to_state=to_state, counterparty=counterparty,
        occurred_on=payload.get("occurred_on"), basis=payload.get("basis"),
        comment=payload.get("comment"),
        supply_id=payload.get("supply_id"), supply_line_id=payload.get("supply_line_id"),
    )
    db.add(move)

    # commissioning: опционально синхронизировать паспорт площадки из карточки
    if op == "commissioning" and payload.get("sync_passport") and to_loc_id:
        await _sync_passport(db, company_id, user, unit, to_loc_id)

    return unit, move


async def _sync_passport(db: AsyncSession, company_id, user: User | None,
                         unit: EzsEquipmentUnit, site_id: str) -> None:
    """Перенести непустые отличающиеся поля карточки в паспорт площадки;
    прежние значения — в extra_metadata.passportHistory (паттерн nameHistory)."""
    site = await db.get(ServiceLocation, site_id)
    if site is None:
        return
    mapping = {
        "serial_number": unit.serial_number, "brand": unit.vendor,
        "model": unit.model, "power_kwt": unit.power_kwt,
        "connectors_count": unit.connectors_count,
        "connector_types": unit.connector_types,
        "inventory_number": unit.inventory_number,
    }
    old: dict[str, Any] = {}
    for field, val in mapping.items():
        if val in (None, "") or getattr(site, field) == val:
            continue
        old[field] = getattr(site, field)
        setattr(site, field, val)
    if not old:
        return
    meta = dict(site.extra_metadata or {})
    hist = list(meta.get("passportHistory") or [])
    hist.append({"at": date.today().isoformat(), "source": "equipment", "fields": old})
    meta["passportHistory"] = hist
    site.extra_metadata = meta
    db.add(AuditEvent(
        company_id=company_id,
        user_id=str(user.id) if user else None,
        user_name=(user.name or user.email) if user else None,
        action="equipment_passport_sync",
        details=json.dumps({"location_id": site_id, "unit_id": str(unit.id), "fields": list(old)},
                           ensure_ascii=False),
    ))


async def dismantle_from_site(db: AsyncSession, company_id, user: User | None,
                              payload: dict[str, Any]) -> tuple[EzsEquipmentUnit, EzsEquipmentMovement, bool]:
    """Демонтаж станции с площадки → склад. Если карточки единицы нет —
    автосоздание из паспорта площадки (складской контур наполняется событиями)."""
    site_id = payload.get("site_location_id")
    wh_id = payload.get("warehouse_id")
    if not site_id or not wh_id:
        raise HTTPException(400, "Укажите площадку и склад-приёмник")
    site = await _get_location(db, company_id, site_id, want_type="site")
    await _get_location(db, company_id, wh_id, want_type="warehouse")

    unit = (await db.execute(
        select(EzsEquipmentUnit).where(
            EzsEquipmentUnit.company_id == company_id,
            EzsEquipmentUnit.current_location_id == site_id,
            EzsEquipmentUnit.state == "in_operation",
        ).with_for_update().limit(1)
    )).scalar_one_or_none()

    created = False
    if unit is None:
        serial = (site.serial_number or "").strip() or None
        if serial and await _serial_conflict(db, company_id, serial):
            serial = None  # серийник уже занят другой карточкой — не дублируем ключ
        unit = EzsEquipmentUnit(
            company_id=company_id,
            serial_number=serial,
            vendor=canon_vendor(site.brand), vendor_raw=site.brand,
            model=site.model, power_kwt=site.power_kwt,
            connectors_count=site.connectors_count, connector_types=site.connector_types,
            inventory_number=site.inventory_number,
            state="in_operation", is_used=True,
            current_location_id=site_id, custodian="site",
            origin_location_id=site_id,
        )
        db.add(unit)
        await db.flush()
        created = True

    _, move = await apply_movement(db, company_id, user, unit.id, {
        "op": "dismantle", "to_location_id": wh_id,
        "occurred_on": payload.get("occurred_on"),
        "basis": payload.get("basis"), "comment": payload.get("comment"),
    })

    # опционально: пометить площадку выведенной (журнал тот же, что ручной PATCH)
    if payload.get("set_decommissioned") and site.operational_status != "decommissioned":
        prev = site.operational_status
        site.operational_status = "decommissioned"
        db.add(AuditEvent(
            company_id=company_id,
            user_id=str(user.id) if user else None,
            user_name=(user.name or user.email) if user else None,
            action="location_op_status",
            details=json.dumps({"location_id": site_id, "from": prev,
                                "to": "decommissioned", "reason": "демонтаж оборудования"},
                               ensure_ascii=False),
        ))
    return unit, move, created


# ─── импорт складского реестра (xlsx) ───────────────────────────────────────

# Синонимы колонок (lower, сжатые пробелы). Докручивается по реальному файлу.
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "serial": ("серийный номер", "серийный №", "сер. номер", "сер.номер", "зав.№", "зав. №",
               "заводской номер", "заводской №", "серийник", "serial", "serial number", "s/n", "sn"),
    "vendor": ("производитель", "вендор", "изготовитель", "бренд", "марка", "manufacturer", "vendor"),
    "model": ("модель", "model", "тип станции", "наименование модели"),
    "warehouse": ("склад", "местонахождение", "место хранения", "локация", "место", "warehouse",
                  # Заказчик пишет одной графой адрес и склад: «Адрес / место хранения».
                  "адрес / место хранения", "адрес/место хранения", "адрес места хранения"),
    "state": ("состояние", "статус", "state", "status"),
    "inventory": ("инв.№", "инв. №", "инвентарный номер", "инвентарный №", "инв номер"),
    "power": ("мощность", "мощность, квт", "квт", "kw", "power"),
    "connectors": ("разъёмы", "разъемы", "коннекторы", "порты", "connectors"),
    "purchase_date": ("дата закупки", "дата поступления", "дата прихода", "дата покупки"),
    "supplier": ("поставщик", "supplier"),
    "notes": ("примечание", "комментарий", "комментарии", "заметки", "notes"),
    # Графы складского реестра заказчика: где лежит, кто хранит, чем числится.
    "region": ("регион", "субъект", "region"),
    "keeper": ("подрядчик", "подрядчик (монтаж/хранение)", "хранитель", "ответственный"),
    "accounting_no": ("бух. № объекта", "бух.№ объекта", "бух № объекта", "бух. № объекта (сч.08)",
                      "инв. номер сч.08", "№ сч.08"),
    "external_no": ("№ zoi-1", "№ zoi", "zoi", "зевс", "№ зевс"),
    "purchase_doc": ("№ и дата договора поставки", "договор поставки", "№ договора"),
    "warranty": ("гарантийный срок", "гарантия", "гарантийный срок, окончание"),
}

# Колонки-разъёмы: у заказчика каждый тип отдельной графой с количеством портов.
# Одной колонкой «разъёмы» это не выражается, а порты — главный вопрос к станции
# на складе: без них непонятно, на какую площадку её вообще можно ставить.
CONNECTOR_COLUMNS: dict[str, str] = {
    "ccs2": "CCS2", "ccs": "CCS2", "chademo": "CHAdeMO", "gb/t": "GB/T", "gbt": "GB/T",
    "type2": "Type 2", "type 2": "Type 2", "type1": "Type 1", "type 1": "Type 1",
}

_STATE_SYNONYMS = (
    (("б/у", "бу", "демонтир",), "in_stock_used"),
    (("резерв",), "reserved"),
    (("ремонт",), "in_repair"),
    (("монтаж", "установк"), "in_installation"),
    (("списан", "утил"), "written_off"),
    (("возврат производ", "производител"), "returned_to_vendor"),
    (("нов", "склад", "хранен"), "in_stock_new"),
)


def _map_state(raw: str | None) -> tuple[str, bool]:
    """Текст состояния → (enum, распознано). Пусто → in_stock_new."""
    s = str(raw or "").strip().lower()
    if not s:
        return "in_stock_new", True
    for keys, state in _STATE_SYNONYMS:
        if any(k in s for k in keys):
            return state, True
    return "in_stock_new", False


def _detect_header(rows: list[tuple], scan: int = 10):
    """Найти строку заголовка → (row_idx, {col→key}, {col→тип разъёма}, unknown).

    Колонки-разъёмы выделяются отдельно от паспортных: их несколько, они несут
    количество портов каждого типа, и складывать их в общий `colmap` значило бы
    оставить в карточке только последний найденный тип.
    """
    best = None
    for ri, row in enumerate(rows[:scan]):
        colmap: dict[int, str] = {}
        conns: dict[int, str] = {}
        unknown: list[str] = []
        for ci, cell in enumerate(row):
            label = " ".join(str(cell or "").strip().lower().split())
            if not label:
                continue
            conn = CONNECTOR_COLUMNS.get(label)
            if conn:
                conns[ci] = conn
                continue
            hit = next((key for key, syns in COLUMN_SYNONYMS.items()
                        if any(label == s or label.startswith(s) for s in syns)), None)
            if hit and hit not in colmap.values():
                colmap[ci] = hit
            else:
                unknown.append(str(cell).strip())
        if len(colmap) >= 3 and (best is None or len(colmap) > len(best[1])):
            best = (ri, colmap, conns, unknown)
    if best is None:
        raise HTTPException(400, "Не найдена строка заголовка (нужны минимум 3 знакомые колонки: "
                                 "серийный №, производитель, модель, склад, состояние…)")
    return best


def _warehouse_name(raw: str | None) -> tuple[str | None, str | None]:
    """Графа «Адрес / место хранения» → (название склада, примечание).

    Заказчик пишет туда и склад, и историю станции целым предложением: «ЭЗС №268
    (была поставлена изначально в г. Байкальск)…». Заводить склад с таким именем
    нельзя — это не место, а рассказ; но и терять рассказ незачем.
    """
    text = " ".join(str(raw or "").split())
    if not text:
        return None, None
    head = re.split(r"\s*[(.,;]\s*", text, maxsplit=1)[0].strip()
    if not head or len(head) > 80:
        # Названия склада тут нет вовсе — только пояснение.
        return None, text[:400]
    note = text[len(head):].strip(" (.,;") or None
    return head[:100], (note[:400] if note else None)


def _connectors(row: tuple, conns: dict[int, str]) -> tuple[int | None, str | None]:
    """Порты станции из колонок-разъёмов → (сколько всего, чем именно).

    Пустая строка портов — не ноль, а «неизвестно»: у станции, которую ещё не
    подтвердил поставщик, портов не бывает ноль, их бывает «пока не сказали».
    """
    found: list[tuple[str, int]] = []
    for ci, name in conns.items():
        if ci >= len(row):
            continue
        raw = row[ci]
        if raw in (None, ""):
            continue
        try:
            count = int(float(str(raw).replace(",", ".")))
        except (TypeError, ValueError):
            continue
        if count > 0:
            found.append((name, count))
    if not found:
        return None, None
    total = sum(c for _, c in found)
    label = ", ".join(f"{name}×{c}" if c > 1 else name for name, c in found)
    return total, label[:200]


async def import_units_xlsx(db: AsyncSession, company_id, user: User | None,
                            content: bytes, filename: str, dry_run: bool) -> dict[str, Any]:
    """Импорт складского реестра оборудования: толерантный к колонкам/состояниям."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    # Реестр приходит вкладками по классу станции — «Быстрые ЭЗС» и «Медленные ЭЗС».
    # Брать только активный лист значило бы молча потерять половину склада, и
    # заметили бы это по недостаче на инвентаризации, а не при загрузке.
    sheets = [(ws.title, [tuple(c for c in r) for r in ws.iter_rows(values_only=True)])
              for ws in wb.worksheets]
    wb.close()
    if not any(rows for _, rows in sheets):
        raise HTTPException(400, "Пустой файл")

    # существующие единицы компании — индексы дедупа
    existing = (await db.execute(
        select(EzsEquipmentUnit).where(EzsEquipmentUnit.company_id == company_id)
    )).scalars().all()
    by_serial = {u.serial_number.strip().lower(): u for u in existing
                 if u.serial_number and u.serial_number.strip()}
    by_alt = {(u.vendor or "", u.model or "", u.inventory_number or ""): u
              for u in existing if u.inventory_number}

    report: dict[str, Any] = {
        "created": 0, "updated": 0, "skipped": 0,
        "errors": [], "unknownColumns": [],
        "warehousesCreated": [], "stateUnknown": [], "dryRun": dry_run,
    }
    wh_cache: dict[str, ServiceLocation] = {}
    known_wh = {w.name.strip().lower() for w in (await db.execute(
        select(ServiceLocation).where(ServiceLocation.company_id == company_id,
                                      ServiceLocation.type == "warehouse")
    )).scalars().all()}

    def cell(row: tuple, key: str, colmap: dict[int, str]) -> str | None:
        for ci, k in colmap.items():
            if k == key and ci < len(row) and row[ci] is not None:
                v = str(row[ci]).strip()
                return v or None
        return None

    report["sheets"] = []
    for sheet_name, rows in sheets:
        if not rows:
            continue
        try:
            header_idx, colmap, conns, unknown_cols = _detect_header(rows)
        except HTTPException:
            # Лист без узнаваемой шапки — не повод валить загрузку остальных: в книге
            # заказчика рядом с реестром живут пояснения и черновики.
            report["sheets"].append({"sheet": sheet_name, "skipped": "нет строки заголовка"})
            continue
        for u in unknown_cols:
            if u not in report["unknownColumns"]:
                report["unknownColumns"].append(u)
        # Класс станции берётся из названия вкладки: в самих строках его нет, а
        # «быстрая» и «медленная» — разные и по мощности, и по применению.
        speed = ("fast" if "быстр" in sheet_name.lower()
                 else "slow" if "медлен" in sheet_name.lower() else None)
        sheet_stat = {"sheet": sheet_name, "rows": 0, "unconfirmed": 0}
        report["sheets"].append(sheet_stat)
        for ri, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
            if all(c is None or str(c).strip() == "" for c in row):
                continue
            sheet_stat["rows"] += 1
            try:
                serial = (cell(row, "serial", colmap) or "").strip() or None
                vendor_raw = cell(row, "vendor", colmap)
                vendor = canon_vendor(vendor_raw)
                model = cell(row, "model", colmap)
                inv = cell(row, "inventory", colmap)
                wh_name, wh_note = _warehouse_name(cell(row, "warehouse", colmap))
                state_raw = cell(row, "state", colmap)
                state, recognized = _map_state(state_raw)
                if state_raw and not recognized:
                    report["stateUnknown"].append({"row": ri, "value": state_raw})

                ports, port_types = _connectors(row, conns)
                if port_types is None:
                    port_types = cell(row, "connectors", colmap)
                # Позиция считается неподтверждённой, когда поставщик ещё не сказал
                # главного: где она и с какими портами. Такие строки принимаются —
                # выбросить их значило бы потерять то, что уже известно, — но
                # помечаются, чтобы не попасть в остаток наравне с проверенными.
                gaps = []
                if not state_raw:
                    gaps.append("статус")
                elif not recognized:
                    # «В производстве завода» — не состояние склада: станции ещё нет
                    # физически, и показывать её остатком наравне с принятой нельзя.
                    gaps.append(f"статус «{state_raw[:40]}»")
                if ports is None:
                    gaps.append("порты")
                confirmed = not gaps
                reason = ("поставщик не подтвердил: " + ", ".join(gaps))[:200] if gaps else None
                if not confirmed:
                    sheet_stat["unconfirmed"] += 1

                extra = {
                    "region": cell(row, "region", colmap),
                    "keeper": cell(row, "keeper", colmap),
                    "accounting_no": cell(row, "accounting_no", colmap),
                    "external_no": cell(row, "external_no", colmap),
                    "purchase_doc": cell(row, "purchase_doc", colmap),
                    "warranty_until": cell(row, "warranty", colmap),
                }

                # дедуп
                unit = by_serial.get(serial.lower()) if serial else None
                if unit is None and not serial and inv:
                    unit = by_alt.get((vendor or "", model or "", inv))

                if unit is not None:
                    # обновление: дозаполняем пустые паспортные поля
                    changed = False
                    fields = [("vendor", vendor), ("vendor_raw", vendor_raw),
                              ("model", model), ("inventory_number", inv),
                              ("supplier", cell(row, "supplier", colmap)),
                              ("purchase_date", cell(row, "purchase_date", colmap)),
                              ("connector_types", port_types),
                              ("speed_class", speed),
                              ("notes", cell(row, "notes", colmap))]
                    fields += list(extra.items())
                    for field, val in fields:
                        if val and not getattr(unit, field, None):
                            if not dry_run:
                                setattr(unit, field, val)
                            changed = True
                    if ports and not unit.connectors_count:
                        if not dry_run:
                            unit.connectors_count = ports
                        changed = True
                    # Подтверждение — это новость, а не «пустое поле»: если реестр
                    # наконец назвал порты и статус, отметку снимаем.
                    if confirmed and not unit.data_confirmed:
                        if not dry_run:
                            unit.data_confirmed = True
                            unit.unconfirmed_reason = None
                        changed = True
                    pw = cell(row, "power", colmap)
                    if pw and unit.power_kwt is None:
                        try:
                            if not dry_run:
                                unit.power_kwt = float(str(pw).replace(",", "."))
                            changed = True
                        except ValueError:
                            pass
                    report["updated" if changed else "skipped"] += 1
                    continue

                # создание
                wh: ServiceLocation | None = None
                if wh_name:
                    key = wh_name.strip().lower()
                    if not dry_run:
                        wh = wh_cache.get(key) or await get_or_create_warehouse(
                            db, company_id, wh_name)
                        wh_cache[key] = wh
                    if key not in known_wh and wh_name.strip() not in report["warehousesCreated"]:
                        report["warehousesCreated"].append(wh_name.strip())
                elif state in STOCK_STATES or state == "reserved":
                    # Склада нет, но позиция известна: неподтверждённую принимаем без
                    # места хранения — она и есть «ещё не приехала».
                    if confirmed:
                        report["errors"].append({"row": ri, "message": "не указан склад"})
                        continue

                if dry_run:
                    report["created"] += 1
                    continue

                power = None
                pw = cell(row, "power", colmap)
                if pw:
                    try:
                        power = float(str(pw).replace(",", "."))
                    except ValueError:
                        power = None
                # Терминальное состояние (списана/возврат) держателя на складе не
                # имеет: current_location=None, custodian vendor|none (не «warehouse»).
                terminal = state in TERMINAL_STATES
                loc_id = None if terminal else (wh.id if wh else None)
                custodian = ("vendor" if state == "returned_to_vendor" else "none") \
                    if terminal else "warehouse"
                unit = EzsEquipmentUnit(
                    company_id=company_id,
                    serial_number=serial, vendor=vendor, vendor_raw=vendor_raw,
                    model=model, power_kwt=power,
                    connectors_count=ports, connector_types=port_types,
                    speed_class=speed,
                    inventory_number=inv, supplier=cell(row, "supplier", colmap),
                    purchase_date=cell(row, "purchase_date", colmap),
                    notes=" · ".join(x for x in (cell(row, "notes", colmap), wh_note) if x)[:500]
                    or None,
                    state=state, is_used=(state == "in_stock_used"),
                    current_location_id=loc_id, custodian=custodian,
                    data_confirmed=confirmed, unconfirmed_reason=reason,
                    **{k: v for k, v in extra.items() if v},
                )
                db.add(unit)
                await db.flush()
                db.add(_movement(company_id, unit, "receipt", user=user,
                                 to_location_id=loc_id,
                                 to_state=state, basis=f"импорт: {filename} · {sheet_name}"))
                if serial:
                    by_serial[serial.lower()] = unit
                report["created"] += 1
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001 — строка не валит импорт
                report["errors"].append({"row": ri, "sheet": sheet_name, "message": str(e)[:200]})

    return report


# ─── ЗИП ────────────────────────────────────────────────────────────────────

SPARE_OPS = {"receipt", "issue", "transfer", "write_off", "correction"}


async def _stock_row(db: AsyncSession, company_id, part_id, location_id,
                     create: bool) -> EzsSparePartStock | None:
    row = (await db.execute(
        select(EzsSparePartStock).where(
            EzsSparePartStock.company_id == company_id,
            EzsSparePartStock.part_id == part_id,
            EzsSparePartStock.location_id == location_id,
        ).with_for_update()
    )).scalar_one_or_none()
    if row is None and create:
        row = EzsSparePartStock(company_id=company_id, part_id=part_id,
                                location_id=location_id, qty=0)
        db.add(row)
        await db.flush()
    return row


async def spare_apply_movement(db: AsyncSession, company_id, user: User | None,
                               part_id, payload: dict[str, Any]) -> EzsSparePartMovement:
    """Движение ЗИП с транзакционной корректировкой материализованных остатков."""
    op = payload.get("op")
    if op not in SPARE_OPS:
        raise HTTPException(400, f"Неизвестная операция ЗИП: {op}")
    part = await db.get(EzsSparePart, part_id)
    if part is None or part.company_id != company_id:
        raise HTTPException(404, "Номенклатура не найдена")
    try:
        qty = Decimal(str(payload.get("qty") or 0))
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Некорректное количество")
    if qty <= 0:
        raise HTTPException(400, "Количество должно быть больше нуля")

    from_id = payload.get("from_location_id")
    to_id = payload.get("to_location_id")

    async def debit(loc_id):
        await _get_location(db, company_id, loc_id, want_type="warehouse")
        row = await _stock_row(db, company_id, part_id, loc_id, create=False)
        have = Decimal(str(row.qty)) if row else Decimal(0)
        if have < qty:
            fmt = lambda d: f"{d:f}".rstrip("0").rstrip(".") or "0"  # noqa: E731 — без экспоненты (1E+2)
            raise HTTPException(409, f"Недостаточно остатка: есть {fmt(have)}, нужно {fmt(qty)}")
        row.qty = have - qty

    async def credit(loc_id):
        await _get_location(db, company_id, loc_id, want_type="warehouse")
        row = await _stock_row(db, company_id, part_id, loc_id, create=True)
        row.qty = Decimal(str(row.qty)) + qty

    if op == "receipt":
        if not to_id:
            raise HTTPException(400, "Укажите склад прихода")
        await credit(to_id)
    elif op in ("issue", "write_off"):
        if not from_id:
            raise HTTPException(400, "Укажите склад списания")
        await debit(from_id)
    elif op == "transfer":
        if not from_id or not to_id or from_id == to_id:
            raise HTTPException(400, "Укажите разные склады: откуда и куда")
        await debit(from_id)
        await credit(to_id)
    elif op == "correction":
        # корректировка = установка фактического остатка на складе
        if not to_id:
            raise HTTPException(400, "Укажите склад корректировки")
        if not (payload.get("comment") or "").strip():
            raise HTTPException(400, "Для корректировки обязателен комментарий")
        row = await _stock_row(db, company_id, part_id, to_id, create=True)
        row.qty = qty

    target_unit_id = payload.get("target_unit_id")
    if target_unit_id:
        tu = await db.get(EzsEquipmentUnit, target_unit_id)
        if tu is None or tu.company_id != company_id:
            raise HTTPException(404, "Станция-получатель не найдена")

    move = EzsSparePartMovement(
        company_id=company_id, part_id=part_id, op=op, qty=qty,
        from_location_id=from_id, to_location_id=to_id,
        target_unit_id=target_unit_id,
        target_location_id=payload.get("target_location_id"),
        occurred_on=payload.get("occurred_on") or date.today().isoformat(),
        basis=payload.get("basis"), comment=payload.get("comment"),
        supply_id=payload.get("supply_id"), supply_line_id=payload.get("supply_line_id"),
        created_by_id=str(user.id) if user else None,
        created_by_name=(user.name or user.email) if user else None,
    )
    db.add(move)
    return move
