"""Граница исторической расшифровки: SQL и API-контекст, без живой БД."""
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.station_history import station_history
from app.services.station_visits import station_visits


class DrillPeriodTest(unittest.IsolatedAsyncioTestCase):
    boundary = datetime(2026, 10, 21, 12)
    cutoff = datetime(2026, 9, 30, 23, 59, 59, 999999)

    def location(self):
        return SimpleNamespace(id="a", code="a", name="Станция", city=None,
                               extra_metadata={}, operational_status="working",
                               connectors_count=2, power_kwt=50)

    def assert_session_cutoff(self, statement, cutoff):
        sql = str(statement)
        self.assertRegex(sql, r"charge_sessions.started_at <= :started_at_\d+")
        self.assertIn(cutoff, statement.compile().params.values())

    async def test_history_caps_all_session_queries_and_status_events(self):
        for as_of, cutoff in [(date(2026, 9, 30), self.cutoff), (None, self.boundary)]:
            with self.subTest(as_of=as_of):
                db = AsyncMock()
                db.execute.side_effect = [
                    SimpleNamespace(scalar_one_or_none=self.location),
                    SimpleNamespace(scalar=lambda: self.boundary),
                    SimpleNamespace(one=lambda: (1, 0, 0, 1, 5, 100, 10)),
                    SimpleNamespace(all=lambda: [(date(2026, 9, 30), 1, 0, 5, 100)]),
                    SimpleNamespace(all=lambda: [(datetime(2026, 9, 30, 12),)]),
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
                    SimpleNamespace(scalar=lambda: datetime(2026, 9, 30, 12)),
                ]
                result = await station_history(db, "company", "a", as_of=as_of)
                statements = [c.args[0] for c in db.execute.call_args_list]
                # Итоги, посуточный ряд, перерывы и последняя попытка обязаны
                # иметь верхнюю границу, включая микросекунды последнего дня.
                for i in (2, 3, 4, 6):
                    self.assert_session_cutoff(statements[i], cutoff)
                self.assertIn("audit_events.timestamp <=", str(statements[5]))
                event_cutoff = next(v for v in statements[5].compile().params.values()
                                    if isinstance(v, datetime))
                self.assertEqual(event_cutoff.replace(tzinfo=None), cutoff)
                self.assertEqual(event_cutoff.utcoffset().total_seconds(), 3 * 3600)
                self.assertEqual(datetime.fromisoformat(result["asOf"]).replace(tzinfo=None), cutoff)
                self.assertEqual(result["work"]["sessions"], 1)
                self.assertEqual(result["station"]["silentDays"], (cutoff.date() - date(2026, 9, 30)).days)

    async def test_visits_window_is_bounded_even_when_no_visits(self):
        for as_of, cutoff in [(date(2026, 9, 30), self.cutoff), (None, self.boundary)]:
            with self.subTest(as_of=as_of):
                db = AsyncMock()
                db.execute.side_effect = [
                    SimpleNamespace(scalar_one_or_none=self.location),
                    SimpleNamespace(scalar=lambda: self.boundary),
                    SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
                ]
                result = await station_visits(db, "company", "a", as_of=as_of)
                self.assert_session_cutoff(db.execute.call_args_list[2].args[0], cutoff)
                self.assertEqual(result["totals"]["visits"], 0)
                self.assertEqual(result["visits"], [])
                self.assertEqual(datetime.fromisoformat(result["asOf"]).replace(tzinfo=None), cutoff)


if __name__ == "__main__":
    unittest.main()
