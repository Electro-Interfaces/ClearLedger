"""Пагинация полных визитов и HTTP-валидация, без рабочей или тестовой БД."""
import random
import unittest
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.auth import get_current_user
from app.database import get_db
from app.routers.ops_router import router
from app.services.station_visits import station_visits


class VisitsPaginationTest(unittest.IsolatedAsyncioTestCase):
    def sessions(self):
        # Совпадающее время на всех 222 визитах проверяет tie-breaker
        # непосредственно на границе между первой и второй страницами.
        at = datetime(2026, 9, 30, 12)
        return [SimpleNamespace(
            session_ext_id=f"session-{i:03}", visit_key=f"visit-{i:03}", visit_seq=1,
            started_at=at, finished_at=at + timedelta(minutes=10),
            energy_kwh=0 if i % 3 == 0 else 5, client_amount=0, amount=0,
            user_id=f"client-{i:03}", user_type=None, client_name=None,
            rfid=None, card_number=None, duration_min=10,
            connector_no="1", connector_type="CCS", result="Complete", tariff=0,
        ) for i in range(222)]

    async def page(self, sessions, **options):
        db = AsyncMock()
        loc = SimpleNamespace(id="a", name="Станция", extra_metadata={}, operational_status="working")
        db.execute.side_effect = [
            SimpleNamespace(scalar_one_or_none=lambda: loc),
            SimpleNamespace(scalar=lambda: datetime(2026, 9, 30, 23)),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: sessions)),
        ]
        return await station_visits(db, "company", "a", **options)

    async def test_222_visits_are_available_as_200_plus_22_without_duplicates(self):
        sessions = self.sessions()
        first = await self.page(sessions)
        # Имитируем другой допустимый порядок равных SQL-времён на новом запросе.
        shuffled = sessions.copy()
        random.Random(11).shuffle(shuffled)
        second = await self.page(shuffled, offset=200)
        explicit_first = await self.page(list(reversed(sessions)), offset=0)
        self.assertEqual(first["visits"], explicit_first["visits"])
        self.assertEqual((first["returned"], second["returned"]), (200, 22))
        self.assertEqual((first["offset"], second["offset"]), (0, 200))
        self.assertTrue(first["hasMore"])
        self.assertFalse(second["hasMore"])
        self.assertEqual(first["totalMatching"], 222)
        self.assertEqual(second["totalMatching"], 222)
        keys = [v["visitKey"] for v in first["visits"] + second["visits"]]
        self.assertEqual(keys, [f"visit-{i:03}" for i in reversed(range(222))])
        self.assertEqual(len(set(keys)), 222)
        self.assertEqual(first["totals"]["visits"], 222)
        self.assertEqual(first["totals"]["attempts"], 222)
        for field in ("totals", "patterns", "empty", "connectors"):
            self.assertEqual(first[field], second[field])

    async def test_only_failed_matching_count_is_after_filter_but_totals_stay_global(self):
        sessions = self.sessions()
        pages = [await self.page(sessions, only_failed=True, limit=30, offset=o)
                 for o in (0, 30, 60)]
        self.assertEqual([p["returned"] for p in pages], [30, 30, 14])
        self.assertEqual([p["hasMore"] for p in pages], [True, True, False])
        keys = [v["visitKey"] for p in pages for v in p["visits"]]
        self.assertEqual(keys, [f"visit-{i:03}" for i in reversed(range(222)) if i % 3 == 0])
        self.assertEqual(len(set(keys)), 74)
        unfiltered = await self.page(sessions)
        for p in pages:
            self.assertEqual(p["totalMatching"], 74)
            self.assertTrue(all(not v["charged"] for v in p["visits"]))
            self.assertEqual(p["totals"], unfiltered["totals"])
            self.assertEqual(p["totals"]["visits"], 222)
            self.assertEqual(p["totals"]["failed"], 74)

    async def test_pagination_never_splits_attempts_of_one_visit(self):
        sessions = self.sessions()[:3]
        sessions[1].visit_key = sessions[0].visit_key
        sessions[1].visit_seq = 2
        first = await self.page(sessions, limit=1)
        second = await self.page(sessions, limit=1, offset=1)
        self.assertEqual(first["totalMatching"], 2)
        self.assertEqual([v["attempts"] for v in first["visits"] + second["visits"]], [1, 2])
        self.assertEqual(first["totals"]["attempts"], 3)
        self.assertEqual(first["totals"], second["totals"])

    async def test_outside_offset_and_empty_matches_are_honest(self):
        for offset in (222, 1000):
            with self.subTest(offset=offset):
                p = await self.page(self.sessions(), offset=offset)
                self.assertEqual((p["visits"], p["returned"], p["hasMore"]), ([], 0, False))
                self.assertEqual((p["totalMatching"], p["offset"]), (222, offset))
                self.assertEqual(p["totals"]["visits"], 222)
        sessions = self.sessions()
        for s in sessions:
            s.energy_kwh = 5
        p = await self.page(sessions, only_failed=True)
        self.assertEqual((p["totalMatching"], p["returned"], p["hasMore"]), (0, 0, False))
        self.assertEqual(p["totals"]["visits"], 222)
        empty = await self.page([])
        self.assertEqual((empty["totalMatching"], empty["returned"], empty["hasMore"]), (0, 0, False))

    async def test_negative_service_offset_rejected_before_source_read(self):
        db = AsyncMock()
        with self.assertRaisesRegex(ValueError, "отрицательным"):
            await station_visits(db, "company", "a", offset=-1)
        db.execute.assert_not_awaited()


class VisitsRoutePaginationTest(unittest.IsolatedAsyncioTestCase):
    async def test_route_validates_offset_and_limit_and_forwards_valid_offset(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        async def fake_db():
            yield object()
        async def fake_user():
            return object()
        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[get_current_user] = fake_user
        company_id = uuid.uuid4()
        member = AsyncMock(return_value=company_id)
        service = AsyncMock(return_value={"visits": [], "offset": 200})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.routers.ops_router.assert_company_member", member), \
                 patch("app.routers.ops_router.station_visits", service):
                url = "/api/ops/station-visits/a"
                invalid = await client.get(url, params={"company_id": str(company_id), "offset": -1})
                self.assertEqual(invalid.status_code, 422)
                self.assertIn("offset", str(invalid.json()))
                oversized = await client.get(url, params={"company_id": str(company_id), "limit": 1001})
                self.assertEqual(oversized.status_code, 422)
                service.assert_not_awaited()
                valid = await client.get(url, params={"company_id": str(company_id), "offset": 200, "limit": 1000})
                self.assertEqual(valid.status_code, 200)
                self.assertEqual(service.await_args.kwargs["offset"], 200)
                self.assertEqual(service.await_args.kwargs["limit"], 1000)
                service.reset_mock()
                default = await client.get(url, params={"company_id": str(company_id)})
                self.assertEqual(default.status_code, 200)
                self.assertEqual(service.await_args.kwargs["offset"], 0)
                self.assertEqual(service.await_args.kwargs["limit"], 200)


if __name__ == "__main__":
    unittest.main()
