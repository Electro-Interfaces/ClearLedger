import pytest

from app.services.edge_transfers import TransferRoutingError, transfer_tasks


def _outgoing():
    return {
        "Документы": [{
            "Тип": "transfer",
            "Направление": "out",
            "ИсточникUUID": "transfer-source-1",
            "ИдентификаторДокумента": "doc-1",
            "Номер": "МП-208-1",
            "Дата": "2026-08-04T12:00:00+03:00",
            "Отправитель": "АЗС 208",
            "Получатель": "АЗС 210",
            "МестоОтправитель": "208",
            "КодАЗСПолучателя": 210,
            "Товары": [{
                "Номенклатура": "item-1",
                "Наименование": "Вода",
                "ШтрихКод": "4600000000001",
                "КоличествоОтправлено": 5,
                "Количество": 0,
                "КодыМаркировки": ["dm-1"],
            }],
        }],
    }


def test_outgoing_transfer_becomes_recipient_downlink():
    tasks = transfer_tasks(_outgoing(), 208)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["kind"] == "incoming_transfer"
    assert task["station_id"] == 210
    assert task["payload"]["id"] == "incoming:208:doc-1"
    assert task["payload"]["lines"][0]["qty_sent"] == 5
    assert task["payload"]["lines"][0]["mark_codes"] == ["dm-1"]


def test_recipient_acceptance_returns_to_sender():
    payload = _outgoing()
    # Имя поля — из конверта агента (packet.Envelope.ExportedAt), а не выдуманное:
    # центр читал «Выгружено», такого ключа станция не шлёт никогда, и время
    # приёмки молча подменялось временем сервера.
    payload["ВремяВыгрузки"] = "2026-08-04T15:20:00+03:00"
    doc = payload["Документы"][0]
    doc.update({
        "Направление": "in",
        "ИдентификаторДокумента": "incoming:208:doc-1",
        "КодАЗСПолучателя": None,
    })
    doc["Товары"][0]["Количество"] = 4

    tasks = transfer_tasks(payload, 210)

    assert len(tasks) == 1
    task = tasks[0]
    assert task["kind"] == "transfer_accepted"
    assert task["station_id"] == 208
    assert task["payload"] == {
        "id": "doc-1",
        "accepted_station": 210,
        "accepted_at": "2026-08-04T12:20:00+00:00",
        "accepted_qty": 4.0,
        "sender_revision_at": "",
        "difference": -1.0,
        "revision_at": "2026-08-04T12:20:00+00:00",
        "lines": [{"item_uuid": "item-1", "barcode": "4600000000001", "qty_sent": 5.0, "qty_fact": 4.0}],
    }


def test_transfer_cannot_target_its_own_station():
    payload = _outgoing()
    payload["Документы"][0]["КодАЗСПолучателя"] = 208

    with pytest.raises(TransferRoutingError, match="станция-получатель"):
        transfer_tasks(payload, 208)


def test_central_distribution_ack_does_not_route_to_station_zero():
    payload = {
        "Документы": [{
            "Тип": "transfer", "Направление": "in",
            "ИдентификаторДокумента": "central:receipt:allocation",
            "Товары": [{"КоличествоОтправлено": 2, "Количество": 2}],
        }],
    }
    assert transfer_tasks(payload, 208) == []


def test_deleted_outgoing_creates_cancellation_not_new_receipt():
    payload = _outgoing()
    payload["ВремяВыгрузки"] = "2026-08-04T16:00:00+03:00"
    payload["Документы"][0]["ПометкаУдаления"] = True
    task, = transfer_tasks(payload, 208)
    assert task["kind"] == "incoming_transfer_cancelled"
    assert task["station_id"] == 210
    assert task["payload"]["id"] == "incoming:208:doc-1"
    assert task["payload"]["revision_at"] == "2026-08-04T13:00:00+00:00"
    assert task["idempotency_key"] == transfer_tasks(payload, 208)[0]["idempotency_key"]


def test_repost_and_cancel_have_distinct_keys_and_cancellation_time():
    payload = _outgoing()
    payload["Документы"][0]["РедакцияДата"] = "2026-08-04T12:00:00+03:00"
    original, = transfer_tasks(payload, 208)
    payload["ВремяВыгрузки"] = "2026-08-04T16:00:00+03:00"
    payload["Документы"][0]["ПометкаУдаления"] = True
    cancelled, = transfer_tasks(payload, 208)
    assert original["idempotency_key"] != cancelled["idempotency_key"]
    assert cancelled["payload"]["revision_at"] == "2026-08-04T13:00:00+00:00"


@pytest.mark.parametrize("quantity", [-1, float("nan"), float("inf")])
def test_transfer_rejects_invalid_quantity(quantity):
    payload = _outgoing()
    payload["Документы"][0]["Товары"][0]["КоличествоОтправлено"] = quantity
    with pytest.raises(TransferRoutingError, match="количество"):
        transfer_tasks(payload, 208)
