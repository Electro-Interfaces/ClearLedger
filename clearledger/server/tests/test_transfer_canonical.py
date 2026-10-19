from copy import deepcopy
from datetime import datetime, timezone

from app.services.edge_transfer_register import canonical_document


def pair():
    outgoing = {"Тип": "transfer", "ИсточникUUID": "out-source", "Направление": "out",
                "ИдентификаторДокумента": "document", "КодАЗСПолучателя": 8,
                "МестоОтправитель": "208", "Товары": [{"Номенклатура": "item", "ШтрихКод": "111",
                                                       "КоличествоОтправлено": 20, "Количество": 0}]}
    incoming = {"Тип": "transfer", "ИсточникUUID": "in-source", "Направление": "in",
                "ИдентификаторДокумента": "incoming:208:document", "МестоПолучатель": "8",
                "Товары": [{"Номенклатура": "item", "ШтрихКод": "111", "КоличествоОтправлено": 20, "Количество": 20}]}
    return outgoing, incoming


def context(outgoing, incoming):
    return [{"station": 208, "source_uuid": "out-source", "doc": outgoing},
            {"station": 8, "source_uuid": "in-source", "doc": incoming}]


def test_pair_emits_same_single_source_identity_from_both_sides():
    outgoing, incoming = pair()
    rows = context(outgoing, incoming)
    first, error = canonical_document(outgoing, rows)
    assert error is None
    second, error = canonical_document(incoming, rows)
    assert error is None
    assert first == second
    assert first["ИсточникUUID"] == "out-source"
    assert first["Товары"][0]["Количество"] == 20
    assert first["МестоПолучатель"] == "8"
    assert outgoing["Товары"][0]["Количество"] == 0


def test_pending_pair_does_not_emit_zero_quantity_transfer():
    outgoing, _ = pair()
    document, error = canonical_document(outgoing, [{"station": 208, "source_uuid": "out-source", "doc": outgoing}])
    assert document is None
    assert "Ожидается" in error


def test_discrepancy_does_not_rewrite_sent_or_received():
    outgoing, incoming = pair()
    incoming["Товары"][0]["Количество"] = 18
    document, error = canonical_document(incoming, context(outgoing, incoming))
    assert document is None and "Расхождение" in error
    assert outgoing["Товары"][0]["КоличествоОтправлено"] == 20
    assert incoming["Товары"][0]["Количество"] == 18


def test_deleted_source_cannot_be_exported_through_recipient():
    outgoing, incoming = pair()
    outgoing["ПометкаУдаления"] = True
    document, error = canonical_document(incoming, context(outgoing, incoming))
    assert document is None and "отменена" in error


def test_old_receipt_cannot_confirm_reissued_outgoing():
    outgoing, incoming = pair()
    outgoing["РедакцияДата"] = "2026-10-19T10:00:00.123456+03:00"
    incoming["РедакцияОтправки"] = "2026-10-19T09:00:00.123456+03:00"
    document, error = canonical_document(outgoing, context(outgoing, incoming))
    assert document is None and "Ожидается" in error
    incoming["РедакцияОтправки"] = "2026-10-19T07:00:00.123456Z"
    document, error = canonical_document(outgoing, context(outgoing, incoming))
    assert error is None and document["ИсточникUUID"] == "out-source"
