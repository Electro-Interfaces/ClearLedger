import uuid
from datetime import datetime, timezone

from app.services.store_dynamics import price_log


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = {}

    async def execute(self, statement, params):
        self.sql = str(statement)
        self.params = params
        return _Rows(self.rows)


async def test_price_log_keeps_previous_price_and_exact_total():
    cid = uuid.uuid4()
    session = _Session([{
        "station_id": 208,
        "price": 210,
        "valid_from": datetime(2026, 8, 8, tzinfo=timezone.utc),
        "author": "товаровед",
        "name": "Вода",
        "item_uuid": uuid.uuid4(),
        "price_prev": 190,
        "total_count": 137,
    }])

    result = await price_log(
        session, cid, "2026-08-01", "2026-08-09", [208], offset=100, limit=25)

    assert result["total"] == 137
    assert result["offset"] == 100
    assert result["truncated"] is True
    assert result["rows"][0]["price_prev"] == 190
    assert "lag(p.price)" in session.sql
    assert "WHERE valid_from BETWEEN" in session.sql
    assert "SELECT station_id FROM edge_agents WHERE company_id" in session.sql
    assert session.params["cid"] == cid
