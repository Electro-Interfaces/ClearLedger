"""Что уезжает наружу при выгрузке (СТО раздел 12).

Правило перечнем, а не исключениями: добавленная завтра графа паспорта не должна
уехать наружу самим фактом появления. Тест это и стережёт — он падает, когда в
разрешённый состав попадает то, что норма называет непередаваемым.
"""
from types import SimpleNamespace

from app.services.export_policy import (
    NEVER_EXPORTED, PUBLIC_FIELDS, PUBLIC_PASSPORT_FIELDS, filter_for_export,
    is_publishable,
)

FULL = {
    "id": "ezs-abc123", "code": "612", "name": "Майское", "type": "ev_charging",
    "status": "active", "operationalStatus": "working", "address": "ул. Ленина, 1",
    "sourceBindings": [{"sourceId": "s1"}], "metadata": {"asuimStationId": "A-1"},
    "createdAt": "2024-01-01", "updatedAt": "2024-02-01",
    "passport": {
        "stationNumber": "276", "city": "Тюмень", "latitude": 57.1, "longitude": 65.5,
        "powerKwt": 120.0, "connectorsCount": 4, "connectorTypes": "CCS2, Type 2",
        "brand": "Sitronics", "speedClass": "fast",
        # то, что наружу нельзя
        "serialNumber": "23E001341", "inventoryNumber": "INV-9", "stationId": "u-1",
        "hubexAssetId": "H-1", "ocppProtocol": "1.6", "firmware": "2.0.1",
    },
}


def test_technical_and_accounting_identifiers_never_leave():
    out = filter_for_export(FULL)
    flat = {**out, **(out.get("passport") or {})}
    for forbidden in ("id", "stationId", "serialNumber", "inventoryNumber",
                      "hubexAssetId", "ocppProtocol", "firmware",
                      "sourceBindings", "metadata"):
        assert forbidden not in flat, forbidden


def test_consumer_facing_fields_survive():
    """Потребителю нужно знать, где станция, какой мощности и с какими разъёмами."""
    out = filter_for_export(FULL)
    assert out["code"] == "612" and out["name"] == "Майское"
    p = out["passport"]
    assert p["powerKwt"] == 120.0
    assert p["connectorTypes"] == "CCS2, Type 2"
    assert p["latitude"] == 57.1


def test_publication_requires_an_explicit_yes():
    """Не задан признак — значит разрешения нет: публикация по умолчанию это
    решение за владельца объекта, принятое молчанием."""
    assert is_publishable(SimpleNamespace(is_published=True)) is True
    assert is_publishable(SimpleNamespace(is_published=False)) is False
    assert is_publishable(SimpleNamespace(is_published=None)) is False
    assert is_publishable(SimpleNamespace()) is False


def test_allowed_lists_do_not_intersect_the_forbidden_one():
    """Перечень и запрет не должны противоречить друг другу — иначе правило
    зависит от порядка проверок."""
    assert not (PUBLIC_FIELDS & NEVER_EXPORTED)
    assert not (PUBLIC_PASSPORT_FIELDS & NEVER_EXPORTED)


def test_empty_passport_does_not_produce_an_empty_key():
    out = filter_for_export({"code": "1", "name": "X", "passport": {"serialNumber": "S"}})
    assert "passport" not in out
