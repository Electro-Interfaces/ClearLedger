from datetime import timezone

from app.services.edge_stock import normalize_snapshot


def test_normalize_snapshot_accepts_only_book_rows_and_aggregates():
    payload = {"Документы": [{
        "Тип": "stock_snapshot",
        "ИсточникУчета": "edge_ledger",
        "Момент": "2026-08-04T12:30:00+03:00",
        "Касса": [{"ШтрихКод": "cash", "Остаток": 999}],
        "Учет": [
            {"Номенклатура": "u1", "ШтрихКод": "4601", "Наименование": "Кофе",
             "Место": "208", "МестоНаименование": "Торговый зал", "Остаток": 2,
             "Цена": 150},
            {"Номенклатура": "u1", "ШтрихКод": "4601", "Наименование": "Кофе",
             "Место": "208", "Остаток": 3, "Цена": 150},
            {"Номенклатура": "u1", "ШтрихКод": "4601", "Наименование": "Кофе",
             "Место": "20800002", "Остаток": 7, "Цена": 150},
        ],
    }]}

    source, taken_at, rows = normalize_snapshot(payload, 208)

    assert source == "edge_ledger"
    assert taken_at.tzinfo is not None
    assert taken_at.astimezone(timezone.utc).hour == 9
    assert len(rows) == 2
    assert {str(row["quantity"]) for row in rows} == {"5", "7"}
    assert all(row["barcode"] == "4601" for row in rows)


def test_normalize_snapshot_labels_legacy_source():
    source, _, rows = normalize_snapshot({"Документы": [{
        "Тип": "stock_snapshot", "Учет": [{"ШтрихКод": "1", "Остаток": 1}],
    }]}, 208)

    assert source == "legacy_snapshot"
    assert len(rows) == 1
