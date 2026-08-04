from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.routers.store_router import (
    _parse_scanned_product,
    _validate_receipt_route,
    _validate_scanned_marks,
)


def test_direct_delivery_with_office_signature_can_wait_for_signature():
    _validate_receipt_route(
        "supplier_to_station", 208, None, "office_director",
        None, None, None, None, "pending", None, require_signature=True,
    )


def test_central_delivery_cannot_use_station_mchd():
    with pytest.raises(HTTPException, match="Центральный приход подписывает офис"):
        _validate_receipt_route(
            "central_warehouse", None, "Центральный склад", "station_mchd",
            "Иванов И.И.", "guid", "ФНС", date.today() + timedelta(days=30),
            "signed", "signature", require_signature=True,
        )


def test_station_mchd_must_be_valid_and_signed():
    with pytest.raises(HTTPException, match="Срок действия МЧД истёк"):
        _validate_receipt_route(
            "supplier_to_station", 208, None, "station_mchd",
            "Иванов И.И.", "guid", "ФНС", date.today() - timedelta(days=1),
            "signed", "signature", require_signature=True,
        )


def test_scanner_understands_aim_and_gs1_datamatrix():
    barcode, mark, label = _parse_scanned_product(
        "]d2010460043993125621abc<GS>91EE10\r\n")
    assert barcode == "4600439931256"
    assert mark == "010460043993125621abc<GS>91EE10"
    assert label == "GS1 DataMatrix"


def test_scanner_rejects_wrong_gtin_checksum():
    with pytest.raises(HTTPException, match="контрольная цифра"):
        _parse_scanned_product("4600439931257")


def test_marked_receipt_uses_physical_scans_not_only_upd_codes():
    code = "010460043993125621abc<GS>91EE10"
    line = {
        "requires_mark": True, "qty_fact": 1,
        "upd_codes": [code], "mark_codes": [code],
    }
    _validate_scanned_marks([line])
    line["mark_codes"] = []
    with pytest.raises(HTTPException, match="отсканировано кодов 0"):
        _validate_scanned_marks([line])
    with pytest.raises(HTTPException, match="личной УКЭП"):
        _validate_receipt_route(
            "supplier_to_station", 208, None, "station_mchd",
            "Иванов И.И.", "guid", "ФНС", date.today() + timedelta(days=30),
            "pending", None, require_signature=True,
        )
