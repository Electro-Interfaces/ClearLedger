"""Сбой одной станции STS не роняет обход остальных (gig, 16.09–25.10.2026).

Станция 235 падала на дубле карточки, `rollback` истекал ORM-атрибуты канала, и у
каждой следующей станции `channel.company_id` становился lazy load → MissingGreenlet.
"""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Channel, Company, FuelStation
from app.routers import fuel_router
from app.services import channel_orchestrator


@pytest.mark.asyncio(loop_scope="session")
async def test_failed_station_does_not_break_next_stations(db, monkeypatch):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    channel = Channel(company_id=company.id, name=f"sts-{uuid.uuid4()}")
    db.add(channel)
    await db.commit()

    async def fake_context(*args, **kwargs):
        return "l", "p", "http://sts", 15, None, None, [{"code": 901}, {"code": 902}, {"code": 903}]

    seen = []

    async def ingest(body, company_id, db):
        seen.append(body.station_code)
        if body.station_code == 901:
            raise ValueError("Multiple rows were found")
        return {"created": 1}

    monkeypatch.setattr(channel_orchestrator, "_fuel_context", fake_context)
    res = await channel_orchestrator._run_sts_stations(db, channel, None, ingest, "fuel_shift")

    assert seen == [901, 902, 903]
    errors = {r["station"]: r.get("error") for r in res["by_station"]}
    assert "Multiple rows" in errors[901]
    assert errors[902] is None and errors[903] is None
    assert res["stations_ok"] == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_station_get_or_create_survives_race(db):
    company = (await db.execute(select(Company).where(Company.slug == "gig"))).scalar_one()
    code = 900000 + uuid.uuid4().int % 99999
    # Соперник уже завёл карточку, а первый SELECT её не увидел — имитируем
    # проигрыш гонки: вставляем напрямую и зовём создание с тем же кодом.
    db.add(FuelStation(company_id=company.id, code=code, name="соперник"))
    await db.commit()
    real_execute = db.execute
    calls = {"n": 0}

    async def first_select_empty(stmt, *a, **kw):
        calls["n"] += 1
        res = await real_execute(stmt, *a, **kw)
        if calls["n"] == 1:
            class Empty:
                def scalar_one_or_none(self):
                    return None
            return Empty()
        return res

    db.execute = first_select_empty
    try:
        st = await fuel_router._get_or_create_station(db, company.id, code, 15)
    finally:
        db.execute = real_execute
    assert st.name == "соперник"
    n = await db.scalar(select(func.count()).select_from(FuelStation).where(
        FuelStation.company_id == company.id, FuelStation.code == code))
    assert n == 1
