"""Обязательства станции: вся договорная обвязка одного объекта.

ДВА ВЗГЛЯДА НА ОДНО. Реестры «Контрагенты» и «Договоры» смотрят со стороны
стороны сделки: с кем мы связаны и на что. Инженеру нужен обратный разрез — он
приходит от станции: чем эта площадка обвязана, кто по ней отвечает, что и когда
платится, до какого числа действует гарантия. Данные те же самые, поэтому здесь
не новая модель, а сборка по оси объекта.

Что собирается вместе:

- **договоры станции** — адресные (`contract_locations`) и общекомпанейские
  (`scope_type='company'`), разложенные по ролям: аренда, энергоснабжение,
  поставка ЭЗС, сервис, монтаж и подряд, корпоративная зарядка;
- **условия начисления** (`ops_contract_terms`) — ставка, периодичность, день
  оплаты, ожидаемые документы: по ним видно, что должно приходить и когда;
- **платёжная дисциплина** (`station_contract_settlements`) — по какое число
  закрыто, есть ли долг;
- **ответственность поставщика** (`contracts.liability`) — срок устранения,
  санкция за простой, гарантия. То, без чего претензию не написать.

Чего здесь намеренно нет: сумм по месяцам и актов сверки. Это работа
«Хозяйства» (docs/OPS-ECONOMY.md), и в паспорте объекта она сделала бы главным
то, чем инженер не занимается.

Про поверку счётчиков. Заказчик ждёт её в этом же разрезе, но в загружаемых
данных её нет — ни номера счётчика, ни даты поверки: колонок под них нет ни в
витрине, ни в паспорте объекта. Поэтому раздел возвращается пустым с честной
причиной, а не молча отсутствует: «не ведётся» — это тоже ответ, и он сам по
себе задача.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract,
    ContractLocation,
    Counterparty,
    DocCard,
    OpsContractTerm,
    ServiceLocation,
    StationContractSettlement,
)

# Роли обвязки в порядке важности для эксплуатации: сначала то, из-за чего
# станция стоит, потом то, из-за чего с нами судятся.
РОЛИ: dict[str, str] = {
    "supply": "Поставка станции",
    "maintenance": "Сервис и обслуживание",
    "works": "Монтаж и подряд",
    "energy_supply": "Энергоснабжение",
    "rent": "Аренда площадки",
    "charging_service": "Корпоративная зарядка",
    "other": "Прочие",
}

# Виды документов «Трека», которые относятся к обвязке площадки. Не весь
# документооборот объекта: приказы и переписка живут во вкладке «Трек».
ДОКУМЕНТЫ_ОБВЯЗКИ = ("tp_act", "land_contract", "commissioning_act", "work_docs")


def _дата(v: Any) -> str | None:
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    return str(v)[:10] if v else None


def _роль(c: Contract) -> str:
    код = (c.type_code or "").strip()
    return код if код in РОЛИ else "other"


def _договор(c: Contract, имя_контрагента: str | None, станций: int,
             адресный: bool) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "number": c.number,
        "date": _дата(c.date),
        "title": c.title,
        "type": c.type,
        "role": _роль(c),
        "counterpartyId": str(c.counterparty_id) if c.counterparty_id else None,
        "counterparty": имя_контрагента,
        "validUntil": _дата(c.valid_until),
        "isClosed": bool(c.is_closed),
        "basis": c.basis,
        # Адресный договор заведён на эту площадку, общий — на всю компанию.
        # Разница важна: претензию по общему договору пишут не из карточки
        # станции, а централизованно.
        "scope": "location" if адресный else "company",
        "locationsCount": станций,
        "liability": c.liability,
    }


async def station_obligations(
    db: AsyncSession, company_id: uuid.UUID, location_id: str,
) -> dict[str, Any]:
    """Договорная обвязка станции: кто, за что и в какие сроки отвечает."""
    станция = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.id == location_id))).scalar_one_or_none()
    if станция is None:
        return {"locationId": location_id, "found": False, "groups": []}

    адресные_id = [r for (r,) in (await db.execute(
        select(ContractLocation.contract_id)
        .where(ContractLocation.company_id == company_id,
               ContractLocation.location_id == location_id))).all()]

    # Общекомпанейские берём НЕ все: эквайринг и ОФД к площадке отношения не
    # имеют, а вываленные в каждую станцию делают паспорт нечитаемым. Берём
    # только то, чем площадка действительно обвязана.
    ОБЩИЕ_РОЛИ = ("supply", "maintenance", "works", "energy_supply", "rent")
    все = (await db.execute(select(Contract).where(
        Contract.company_id == company_id,
        (Contract.id.in_(адресные_id) if адресные_id else Contract.id.is_(None))
        | (Contract.scope_type == "company")))).scalars().all()
    адресные_множество = set(адресные_id)
    договоры = [c for c in все
                if c.id in адресные_множество
                or (c.type_code or "") in ОБЩИЕ_РОЛИ]

    имена = dict((cid, name) for cid, name in (await db.execute(
        select(Counterparty.id, Counterparty.name)
        .where(Counterparty.company_id == company_id))).all())

    # Сколько станций у договора: инженеру важно, что этот же договор держит
    # ещё сто тридцать площадок — претензия по нему не про одну точку.
    счёт = dict((cid, n) for cid, n in (await db.execute(
        select(ContractLocation.contract_id, func.count())
        .where(ContractLocation.company_id == company_id)
        .group_by(ContractLocation.contract_id))).all())

    адресные = адресные_множество
    строки = [
        _договор(c, имена.get(c.counterparty_id), счёт.get(c.id, 0), c.id in адресные)
        for c in договоры
    ]

    # ── условия начисления по этим договорам ──
    условия_бд = (await db.execute(select(OpsContractTerm).where(
        OpsContractTerm.company_id == company_id,
        OpsContractTerm.contract_id.in_([c.id for c in договоры] or [uuid.uuid4()]),
    ))).scalars().all()
    условия: dict[str, list[dict[str, Any]]] = {}
    for t in условия_бд:
        # Условие на конкретную площадку берём только своё; общекомпанейское
        # показываем всем станциям договора — оно и заведено на всех.
        if t.scope_type == "location" and t.location_id != location_id:
            continue
        условия.setdefault(str(t.contract_id), []).append({
            "id": str(t.id),
            "costItem": t.cost_item,
            "periodicity": t.periodicity,
            "amountGross": float(t.amount_gross) if t.amount_gross is not None else None,
            "tariffRub": float(t.tariff_rub) if t.tariff_rub is not None else None,
            "payDueDay": t.pay_due_day,
            "docDueDay": t.doc_due_day,
            "expectedDocs": t.expected_docs,
            "counterpartyEmail": t.counterparty_email,
            "validFrom": _дата(t.valid_from),
            "validTo": _дата(t.valid_to),
            "note": t.note,
        })

    # ── платёжная дисциплина ──
    расчёты = [
        {
            "role": s.role,
            "counterpartyId": s.counterparty_id,
            "contractId": str(s.contract_id) if s.contract_id else None,
            "paymentStatus": s.payment_status,
            "paidThrough": _дата(s.paid_through),
            "basis": s.basis,
            "comment": s.comment,
        }
        for s in (await db.execute(select(StationContractSettlement).where(
            StationContractSettlement.company_id == company_id,
            StationContractSettlement.location_id == location_id))).scalars().all()
    ]

    # ── документы обвязки из «Трека» ──
    документы = [
        {
            "id": str(d.id),
            "kind": d.kind_code,
            "title": d.title,
            "number": d.reg_number,
            "date": _дата(d.reg_date),
            "status": d.status,
        }
        for d in (await db.execute(select(DocCard).where(
            DocCard.company_id == company_id,
            DocCard.object_id == location_id,
            DocCard.kind_code.in_(ДОКУМЕНТЫ_ОБВЯЗКИ)))).scalars().all()
    ]

    группы = []
    for код, имя in РОЛИ.items():
        свои = [r for r in строки if r["role"] == код]
        if not свои:
            continue
        # Действующие выше закрытых: инженер смотрит, чем обвязана площадка
        # сейчас, а история нужна реже и лежит ниже.
        свои.sort(key=lambda r: (r["isClosed"], r["scope"] != "location",
                                 r["date"] or ""), reverse=False)
        группы.append({
            "role": код, "label": имя, "contracts": свои,
            "terms": {r["id"]: условия.get(r["id"], []) for r in свои},
        })

    # ── чего не хватает: называем дыры, а не прячем ──
    пробелы: list[str] = []
    роли_есть = {g["role"] for g in группы}
    if "supply" not in роли_есть and "maintenance" not in роли_есть:
        пробелы.append("нет договора поставки или сервиса — претензию производителю "
                       "адресовать не от чего")
    if "energy_supply" not in роли_есть:
        пробелы.append("нет договора энергоснабжения")
    if "rent" not in роли_есть:
        пробелы.append("нет договора аренды или иного основания на площадку")
    без_ответственности = [c for g in группы if g["role"] in ("supply", "maintenance")
                           for c in g["contracts"] if not c["liability"]]
    if без_ответственности:
        пробелы.append(f"условия ответственности не заведены "
                       f"({len(без_ответственности)} дог.): срок устранения и санкции "
                       "берутся из текста договора")

    return {
        "locationId": location_id,
        "found": True,
        "name": станция.name,
        "number": станция.station_number,
        "brand": станция.brand,
        "model": станция.model,
        "installedOn": _дата(станция.installed_on),
        "groups": группы,
        "settlements": расчёты,
        "documents": документы,
        "gaps": пробелы,
        # Раздел зарезервирован и честно пуст: данных о счётчиках и поверке в
        # загружаемых таблицах нет.
        "metering": {"known": False,
                     "note": "номер счётчика и дата поверки в загружаемых данных "
                             "не приходят — раздел заполняется отдельной выгрузкой"},
    }
