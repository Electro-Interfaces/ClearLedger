"""Импорт реестра РусГидро: подбор договора станции (чистка 05.10.2026).

Номер из строки не совпал — заводится договор с этим номером, а не берётся первый
договор контрагента: так договор «4» встал на 21 чужую станцию.
"""
import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.models import Contract
from app.services.reference_identity import IdentityConflict
from app.services.reestr_rushydro import L2Cache


class _Db:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for o in self.added:
            if getattr(o, "id", None) is None:
                o.id = uuid.uuid4()


def _pick(existing: list[str], number):
    cache, db, res = L2Cache(), _Db(), {}
    cache.org_id = str(uuid.uuid4())
    cp = SimpleNamespace(id=uuid.uuid4(), external_ref=None)
    for n in existing:
        c = Contract(id=uuid.uuid4(), counterparty_id=cp.id, number=n, type="Аренда")
        cache.contracts.add(c)
    loc = SimpleNamespace(id="loc-1")
    got = asyncio.run(cache.contract(db, uuid.uuid4(), cp, "Аренда", number, "", "", loc, res))
    return got.number, res.get("contracts", 0)


def test_номер_не_совпал_заводится_свой_договор():
    assert _pick(["4"], "74") == ("74", 1)


def test_номер_совпал_берётся_существующий():
    assert _pick(["4", "74"], "74") == ("74", 0)


def test_без_номера_единственный_договор_берётся_несколько_нет():
    assert _pick(["4"], None) == ("4", 0)
    with pytest.raises(IdentityConflict, match="Неоднозначное"):
        _pick(["4", "5"], None)


def test_same_run_create_then_reuse_and_missing_organization():
    cache, db, res = L2Cache(), _Db(), {}
    cp = SimpleNamespace(id=uuid.uuid4(), external_ref=None)

    async def run():
        with pytest.raises(IdentityConflict, match="Organization"):
            await cache.contract(db, uuid.uuid4(), cp, "Аренда", "74", "", "", None, res)
        cache.org_id = str(uuid.uuid4())
        first = await cache.contract(db, uuid.uuid4(), cp, "Аренда", "74", "", "", None, res)
        again = await cache.contract(db, uuid.uuid4(), cp, "Аренда", "74", "", "", None, res)
        assert first is again
        assert res["contracts"] == 1
        assert len(db.added) == 1

    asyncio.run(run())
