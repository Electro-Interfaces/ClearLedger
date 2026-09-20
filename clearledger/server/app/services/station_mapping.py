"""Маппинг станции: под какими идентификаторами она известна другим системам.

ЗАЧЕМ ОТДЕЛЬНЫЙ РАЗРЕЗ. Одна и та же станция живёт в полудюжине систем, и в
каждой у неё свой ключ: в витрине АСУиМ — свой номер, в HubEx — asset_id, в
зарядной сети — адрес OCPP, в «Поддержке» — объект обслуживания, в роуминге —
идентификатор площадки OCPI. Пока это лежало по углам паспорта, ответ на вопрос
«почему сессии этой станции не сходятся с реестром» искали в базе.

ТРИ ВИДА ЗАПИСЕЙ, И ИХ НЕЛЬЗЯ МЕШАТЬ (СТО, docs/OBJECTS.md §2 и §4):

- **свои идентификаторы** — ключ объекта, код, номер станции, заводской номер,
  инвентарный номер. Их назначаем мы, они в составе объекта;
- **снимок внешних систем** — то, что приехало с загрузкой и лежит в сыром
  снимке: номер в АСУиМ, asset_id HubEx, адрес OCPP, ссылка в приложении. Это
  не реестр соответствий, а следы источника, и правит их загрузка;
- **реестр соответствий** (`object_links`, `relation='external_id'`) — то, что
  ведём мы сами: система, роль ключа, значение, период действия, основание и
  автор. Закрывается датой, а не удаляется; одно значение не может в один
  период принадлежать двум объектам.

Внесение значений внешних систем в поля собственных идентификаторов не
допускается (СТО п. 8.5) — поэтому разделы разные, а не одна таблица «коды».

OCPI здесь же: роуминговые ключи (party id оператора, id площадки, uid точки
отпуска) — обычные записи реестра соответствий с системой `ocpi`. Отдельной
таблицы под них не заводим: в СТО это ровно тот же механизм, а своя таблица
разошлась бы с ним на первом же изменении.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ObjectLink, ServiceLocation

# Как называются внешние системы, встречающиеся в снимке и в реестре.
СИСТЕМЫ: dict[str, str] = {
    "asuim": "Витрина АСУиМ",
    "hubex": "HubEx (сервис ЭЗС)",
    "ocpp": "Зарядная сеть (OCPP)",
    "ocpi": "Роуминг (OCPI)",
    "support": "Поддержка",
    "mobile": "Мобильное приложение",
    "1c": "1С",
    "sts": "STS (АЗС)",
    "msto": "MSTO",
    "other": "Прочее",
}

# Роли ключа — чем именно является значение. Без роли «12345» в списке кодов
# невозможно понять, номер это площадки или точки отпуска.
РОЛИ: dict[str, str] = {
    "station": "идентификатор станции",
    "location": "идентификатор площадки",
    "evse": "идентификатор точки отпуска",
    "connector": "идентификатор коннектора",
    "party": "идентификатор оператора",
    "asset": "идентификатор актива",
    "account": "лицевой счёт",
    "other": "прочее",
}


def _строка(system: str, role: str, value: str, *,
            note: str | None = None, source: str = "snapshot",
            valid_from: str | None = None, valid_to: str | None = None,
            basis: str | None = None, author: str | None = None,
            link_id: str | None = None) -> dict[str, Any]:
    return {
        "id": link_id,
        "system": system,
        "systemLabel": СИСТЕМЫ.get(system, system),
        "role": role,
        "roleLabel": РОЛИ.get(role, role),
        "value": value,
        "note": note,
        # snapshot — пришло загрузкой, registry — ведём сами, own — наш ключ.
        "source": source,
        "validFrom": valid_from,
        "validTo": valid_to,
        "basis": basis,
        "author": author,
    }


async def station_mapping(
    db: AsyncSession, company_id: uuid.UUID, location_id: str,
) -> dict[str, Any]:
    """Все известные идентификаторы станции, разложенные по происхождению."""
    s = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.id == location_id))).scalar_one_or_none()
    if s is None:
        return {"locationId": location_id, "found": False}

    meta: dict[str, Any] = s.extra_metadata or {}

    # ── 1. Свои идентификаторы ──
    свои: list[dict[str, Any]] = [
        _строка("own", "station", str(s.id), note="ключ объекта в пространстве",
                source="own"),
    ]
    if s.code:
        свои.append(_строка("own", "station", s.code, note="код объекта", source="own"))
    if s.station_number:
        свои.append(_строка("own", "station", str(s.station_number),
                            note="номер станции по реестру заказчика", source="own"))
    if s.serial_number:
        свои.append(_строка("own", "asset", s.serial_number,
                            note="заводской номер", source="own"))
    if s.inventory_number:
        свои.append(_строка("own", "asset", str(s.inventory_number),
                            note="инвентарный номер (ОС)", source="own"))

    # ── 2. Снимок внешних систем: то, что приехало загрузкой ──
    снимок: list[dict[str, Any]] = []

    def из_снимка(ключ: str, system: str, role: str, note: str) -> None:
        v = meta.get(ключ)
        if v is None or str(v).strip() == "":
            return
        снимок.append(_строка(system, role, str(v), note=note))

    из_снимка("asuimStationId", "asuim", "station", "номер станции в витрине")
    из_снимка("ext_id", "asuim", "station", "внешний идентификатор выгрузки")
    из_снимка("asuimOwnerId", "asuim", "party", "владелец в витрине")
    из_снимка("number", "asuim", "station", "номер станции в выгрузке")
    из_снимка("ocppUrl", "ocpp", "station", "адрес подключения станции")
    из_снимка("mobileLink", "mobile", "location", "ссылка на площадку в приложении")
    if s.hubex_asset_id is not None:
        снимок.append(_строка(
            "hubex", "asset", str(s.hubex_asset_id),
            note=f"связка: {s.hubex_link_status or 'статус не указан'}"))
    if meta.get("hubexName"):
        снимок.append(_строка("hubex", "station", str(meta["hubexName"]),
                              note="название в HubEx"))

    # Привязки к источникам данных: у каждой свой набор параметров, и они тоже
    # идентификаторы — по ним сходятся смены и сессии.
    for b in (s.source_bindings or []):
        if not isinstance(b, dict):
            continue
        cfg = b.get("config") or {}
        подпись = b.get("label") or f"источник {str(b.get('sourceId', ''))[:8]}"
        for ключ, роль in (("station", "station"), ("station_id", "station"),
                           ("stationNumber", "station"), ("system_id", "party"),
                           ("servicePointId", "location")):
            if cfg.get(ключ) not in (None, ""):
                снимок.append(_строка("other", роль, str(cfg[ключ]), note=подпись))
                break

    # ── 3. Реестр соответствий: то, что ведём сами ──
    записи = (await db.execute(select(ObjectLink).where(
        ObjectLink.company_id == company_id,
        ObjectLink.relation == "external_id",
        ObjectLink.parent_type == "station",
        ObjectLink.parent_id == str(location_id),
    ).order_by(ObjectLink.valid_from.desc()))).scalars().all()

    реестр = [
        _строка(
            (l.child_type or "other"), "other" if not l.basis_note else "other",
            l.child_id,
            note=l.basis_note, source="registry",
            valid_from=l.valid_from.isoformat() if l.valid_from else None,
            valid_to=l.valid_to.isoformat() if l.valid_to else None,
            basis=str(l.basis_doc_id) if l.basis_doc_id else None,
            author=l.recorded_by_name, link_id=str(l.id))
        for l in записи
    ]
    # Роль и систему храним в child_type/basis_note; разбирать их обратно —
    # дело представления, а не хранения.
    for r, l in zip(реестр, записи, strict=False):
        система, _, роль = (l.child_type or "other").partition(":")
        r["system"] = система
        r["systemLabel"] = СИСТЕМЫ.get(система, система)
        r["role"] = роль or "other"
        r["roleLabel"] = РОЛИ.get(роль or "other", роль or "прочее")

    действующие = [r for r in реестр if not r["validTo"]]
    роуминг = [r for r in действующие if r["system"] == "ocpi"]

    return {
        "locationId": location_id,
        "found": True,
        "name": s.name,
        "own": свои,
        "snapshot": снимок,
        "registry": реестр,
        "roaming": роуминг,
        "systems": [{"code": k, "label": v} for k, v in СИСТЕМЫ.items()],
        "roles": [{"code": k, "label": v} for k, v in РОЛИ.items()],
        "note": ("свои идентификаторы назначаем мы; снимок приходит загрузкой и "
                 "правится источником; реестр соответствий ведём вручную — он "
                 "закрывается датой, а не удаляется (СТО, раздел 8)"),
    }


async def add_external_id(
    db: AsyncSession, company_id: uuid.UUID, location_id: str, *,
    system: str, role: str, value: str,
    valid_from: date | None = None, note: str | None = None,
    author_name: str | None = None, author_id: str | None = None,
) -> dict[str, Any]:
    """Завести соответствие внешней системы.

    Значение не может в один период принадлежать двум объектам (СТО п. 8.4) —
    в базе это держит EXCLUDE-ограничение, здесь только понятная проверка, чтобы
    человек получил объяснение, а не ошибку драйвера.
    """
    занято = (await db.execute(select(ObjectLink).where(
        ObjectLink.company_id == company_id,
        ObjectLink.relation == "external_id",
        ObjectLink.child_type == f"{system}:{role}",
        ObjectLink.child_id == value,
        ObjectLink.valid_to.is_(None),
    ))).scalars().first()
    if занято is not None and занято.parent_id != str(location_id):
        raise ValueError(
            f"Значение «{value}» уже закреплено за другим объектом "
            f"({занято.parent_id}) и не закрыто датой")

    link = ObjectLink(
        company_id=company_id,
        parent_type="station", parent_id=str(location_id),
        child_type=f"{system}:{role}", child_id=value,
        relation="external_id",
        valid_from=valid_from or date.today(),
        basis_note=note,
        recorded_by_id=author_id, recorded_by_name=author_name,
    )
    db.add(link)
    await db.commit()
    return {"id": str(link.id), "system": system, "role": role, "value": value}


async def close_external_id(
    db: AsyncSession, company_id: uuid.UUID, link_id: uuid.UUID, *,
    valid_to: date | None = None, reason: str | None = None,
) -> dict[str, Any]:
    """Закрыть соответствие датой. Удалять нельзя: история связи — часть учёта."""
    link = (await db.execute(select(ObjectLink).where(
        ObjectLink.company_id == company_id, ObjectLink.id == link_id))).scalar_one_or_none()
    if link is None:
        raise ValueError("Запись соответствия не найдена")
    link.valid_to = valid_to or date.today()
    link.closed_reason = reason
    await db.commit()
    return {"id": str(link.id), "validTo": link.valid_to.isoformat()}
