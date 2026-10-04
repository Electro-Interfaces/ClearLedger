"""Документы движения оборудования и карточка склада: проверки договора и контрагента."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import Contract, Counterparty
from app.services import ezs_equipment_docs as D

CID = uuid.uuid4()
CP = SimpleNamespace(id=uuid.uuid4(), company_id=CID, name="ООО Сервис")
OTHER = SimpleNamespace(id=uuid.uuid4(), company_id=CID, name="ООО Другой")


def contract(**kw):
    base = dict(id=uuid.uuid4(), company_id=CID, counterparty_id=CP.id, number="12/26", date="2026-01-10",
                type="Сервисное обслуживание", valid_until="2027-12-31", is_closed=False)
    return SimpleNamespace(**{**base, **kw})


class FakeDB:
    def __init__(self, *objs):
        self.objs = {o.id: o for o in objs}

    async def get(self, model, key):
        o = self.objs.get(key)
        return o


def run(coro):
    return asyncio.run(coro)


def test_договор_чужого_контрагента_отклоняется():
    c = contract(counterparty_id=OTHER.id)
    with pytest.raises(HTTPException, match="другим контрагентом"):
        run(D.check_contract(FakeDB(c), CID, c.id, CP.id))


def test_закрытый_договор_отклоняется_истёкший_предупреждает():
    closed = contract(is_closed=True)
    with pytest.raises(HTTPException, match="закрыт"):
        run(D.check_contract(FakeDB(closed), CID, closed.id, CP.id))
    old = contract(valid_until="2025-01-01")
    c, warnings = run(D.check_contract(FakeDB(old), CID, old.id, CP.id))
    assert c is old and warnings and "истёк" in warnings[0]


def test_договор_другой_компании_не_найден():
    c = contract(company_id=uuid.uuid4())
    with pytest.raises(HTTPException, match="не найден"):
        run(D.check_contract(FakeDB(c), CID, c.id))


@pytest.mark.parametrize("payload,msg", [
    ({"op": "transfer", "unit_ids": [], "doc_date": "2026-10-04"}, "Выберите единицы"),
    ({"op": "transfer", "unit_ids": ["u"], "doc_date": "04.10.2026"}, "дату документа"),
    ({"op": "to_repair", "unit_ids": ["u"], "doc_date": "2026-10-04"}, "контрагента"),
    ({"op": "fly", "unit_ids": ["u"], "doc_date": "2026-10-04"}, "Неизвестная операция"),
])
def test_документ_проверяется_до_проведения(payload, msg):
    with pytest.raises(HTTPException, match=msg):
        run(D.post_document(FakeDB(), CID, None, payload))


def test_статус_договора_склада():
    loc = SimpleNamespace(id="wh-1", name="Склад ДГК", address=None,
                          extra_metadata={"warehouse": {"ownership": "custody", "counterpartyId": str(CP.id)}})
    card = run(D.warehouse_card(FakeDB(CP), CID, loc))
    assert card["contractStatus"] == "missing" and card["counterpartyName"] == "ООО Сервис"
    old = contract(valid_until="2025-06-30")
    loc.extra_metadata["warehouse"]["contractId"] = str(old.id)
    card = run(D.warehouse_card(FakeDB(CP, old), CID, loc))
    assert card["contractStatus"] == "expired" and card["ownershipLabel"].startswith("Ответственное")


def test_у_каждой_операции_есть_документ():
    from app.services.ezs_equipment import TRANSITIONS
    assert set(TRANSITIONS) - {"receipt"} <= set(D.DOC_KINDS)
    prefixes = [p for p, _ in D.DOC_KINDS.values()]
    assert len(prefixes) == len(set(prefixes))


def test_детали_ремонта():
    d = D.repair_details("to_repair", {"ticketRef": " 12345 ", "repairKind": "warranty", "plannedReturn": "2026-11-01", "costEstimate": "15000.5"})
    assert d == {"ticketRef": "12345", "repairKind": "warranty", "plannedReturn": "2026-11-01", "costEstimate": 15000.5}
    assert D.repair_details("from_repair", {"result": "unrepairable", "costActual": 0}) == {"result": "unrepairable", "costActual": 0.0}
    assert D.repair_details("transfer", {"ticketRef": "1"}) is None
    for bad in ({"repairKind": "дружеский"}, {"plannedReturn": "01.11.2026"}, {"costEstimate": -1}, {"costEstimate": "много"}):
        with pytest.raises(HTTPException):
            D.repair_details("to_repair", bad)

