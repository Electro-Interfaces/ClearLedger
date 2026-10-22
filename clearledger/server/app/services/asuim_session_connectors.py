"""Номер физического порта из пары ID станции и ID коннектора АСУиМ.

ID коннектора повторяется у разных станций. Неоднозначный справочник и
несовпадение типа не дают основания приписывать сессии физический порт.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from sqlalchemy import select

from app.models import ServiceLocation
from app.services.mapping import normalize_default


def source_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    value = str(value).strip()
    return None if value.lower() in ("", "none", "nan", "null") else value


def build_session_connector_index(rows: Iterable[Mapping[str, Any]]) -> dict:
    """Конфликт одного составного ключа исключает его из сопоставления."""
    candidates: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
    for row in rows:
        station = source_text(row.get("id_станции"))
        connector = source_text(row.get("id_коннектора"))
        number = source_text(row.get("номер_коннектора"))
        if not station or not connector or not number:
            continue
        kind = source_text(row.get("тип"))
        kind = normalize_default("connector", kind) if kind else None
        candidates.setdefault((station, connector), set()).add((number, kind))
    return {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}


def resolve_session_connector(row: Mapping[str, Any], index: Mapping) -> str | None:
    """Явный номер источника сохраняется; отсутствующий восстанавливается точно."""
    number = source_text(row.get("номер_коннектора"))
    if number:
        return number[:20]
    if row.get("_connector_reference_checked"):
        return None
    key = (source_text(row.get("id_станции")), source_text(row.get("id_коннектора")))
    match = index.get(key)
    if not match:
        return None
    number, expected_type = match
    actual_type = source_text(row.get("тип_коннектора"))
    if actual_type and expected_type and normalize_default("connector", actual_type) != expected_type:
        return None
    return number[:20]


def with_session_connector_numbers(rows: list[dict], index: Mapping) -> list[dict]:
    return [{**row, "номер_коннектора": resolve_session_connector(row, index),
             "_connector_reference_checked": True} for row in rows]


async def load_session_connector_index(db, company_id) -> dict:
    """Сохранённый паспорт той же компании для отдельного листа сессий."""
    rows = (await db.execute(select(ServiceLocation.extra_metadata).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.type == "ev_charging",
    ))).scalars()
    connectors = []
    for metadata in rows:
        metadata = metadata or {}
        station = metadata.get("asuimStationId")
        for port in metadata.get("connectors") or []:
            if isinstance(port, dict):
                connectors.append({"id_станции": station, "id_коннектора": port.get("sourceId"),
                                   "номер_коннектора": port.get("no"), "тип": port.get("type")})
    return build_session_connector_index(connectors)
