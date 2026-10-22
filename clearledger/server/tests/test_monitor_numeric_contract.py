"""Числовой контракт мониторинга; только подставные источники, без БД."""
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.network_vendors import network_vendors
from app.services.ops_worklist import ops_worklist


class MonitorNumericContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_and_historical_tickets_are_unknown(self):
        state = {"stations": [{"locationId": "a", "name": "Станция",
                               "silentDays": 9, "loss": 100}]}
        work = {"a": {"open": 2, "breached": 1}}
        for open_work, as_of, known, count, breached in [
            (None, None, False, None, None),
            (work, date(2026, 9, 1), False, None, None),
            ({}, None, True, 0, 0),
            (work, None, True, 2, 1),
        ]:
            with self.subTest(open_work=open_work, as_of=as_of):
                db = AsyncMock()
                db.execute.return_value = SimpleNamespace(all=lambda: [])
                with patch("app.services.ops_worklist.network_state", AsyncMock(return_value=state)), \
                     patch("app.services.ops_worklist.network_reliability", AsyncMock(return_value={"stations": []})), \
                     patch("app.services.ops_worklist.network_upkeep", AsyncMock(return_value={"rows": []})), \
                     patch("app.services.ops_worklist.status_now", AsyncMock(return_value=(None, {}))):
                    result = await ops_worklist(db, "company", open_work=open_work, as_of=as_of)
                row = result["rows"][0]
                self.assertEqual(result["workKnown"], known)
                self.assertEqual(row["openTickets"], count)
                self.assertEqual(row["breachedTickets"], breached)
                self.assertEqual(result["totals"]["breached"], 1 if breached else (0 if known else None))
                self.assertEqual("breached" in {r["kind"] for r in row["reasons"]}, bool(breached))
                self.assertEqual(result["totals"]["lossPerMonth"], 100)
                if not known:
                    self.assertIsNone(result["totals"]["notTaken"])
                    self.assertIsNone(result["totals"]["lossNotTaken"])

    async def test_vendor_rollups_keep_energy_before_display_rounding(self):
        boundary = datetime(2026, 10, 21, 12)
        def station(lid):
            return SimpleNamespace(id=lid, code=lid, name=lid, region_id=None,
                                   extra_metadata={}, city=None, brand="Марка", model="Модель",
                                   owner="РусГидро", status="active", operational_status="working",
                                   power_kwt=50, connectors_count=2)
        db = AsyncMock()
        db.execute.side_effect = [
            SimpleNamespace(scalar=lambda: boundary),
            SimpleNamespace(all=lambda: [(lid, 1, 1, 1, energy, 100, 0)
                                         for lid, energy in [("a", Decimal("10.04")),
                                                             ("b", Decimal("20.04"))]]),
            SimpleNamespace(all=lambda: [("a", boundary), ("b", boundary)]),
            SimpleNamespace(all=lambda: []),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [station("a"), station("b")]))]
        with patch("app.services.network_vendors.visit_summary", AsyncMock(return_value={
            lid: {"visits": 1, "ok": 1} for lid in ("a", "b")
        })):
            result = await network_vendors(db, "company", vendor="*")
        vendor = result["vendors"][0]
        stations = result["stations"]
        self.assertEqual(sum(r["energyKwh"] for r in stations), 30)
        self.assertEqual(vendor["energyKwh"], 30.1)
        raw_sum = sum(Decimal(str(r["energyKwhRaw"])) for r in stations)
        self.assertEqual(raw_sum, Decimal("30.08"))
        self.assertEqual(Decimal(str(vendor["energyKwhRaw"])), raw_sum)


if __name__ == "__main__":
    unittest.main()
