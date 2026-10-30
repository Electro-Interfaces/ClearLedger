"""API без типа пользователя: корпоративные суммы сохраняются и попадают в график."""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import ChargeSession, Company, CorporateClient
from app.services.analytics_service import AnalyticsService, PeriodFilter
from app.services.charge_sessions_normalize import _apply_org_enrichment, classify_corporate_sessions

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_missing_type_is_restored_without_repricing_and_only_with_registry_identity(db):
    companies = (await db.execute(select(Company).limit(2))).scalars().all()
    cid, foreign = companies[0].id, companies[1].id
    db.add(CorporateClient(company_id=cid, name="Тестовый клиент", phone="70000000001", mode="flat", rate=99))
    sessions = []
    for month, user_type, client_name, company, charge_type in [
        (7, "ЮЛ", "Тестовый клиент", cid, "RFID"),
        (8, None, "Тестовый клиент", cid, "RFID"),
        (9, " ", "Тестовый клиент", cid, "RFID"),
        (10, None, "Тестовый клиент", cid, "ADMIN"),
        (8, "ФЛ", "Тестовый клиент", cid, "RFID"),
        (8, None, None, cid, "RFID"),
        (8, None, "Другое имя", cid, "RFID"),
        (8, None, "Тестовый клиент", foreign, "RFID"),
    ]:
        session = ChargeSession(company_id=company, session_ext_id=str(uuid4()),
            user_id="70000000001", user_type=user_type, client_name=client_name,
            started_at=datetime(2026, month, 15), charge_type=charge_type, cut_key="ezs_unpaid",
            amount=0, tariff=30, client_tariff=Decimal("12.34"), client_amount=Decimal("123.40"), energy_kwh=10)
        db.add(session)
        sessions.append(session)
    await db.flush()
    assert await classify_corporate_sessions(db, cid, uuid4()) == 0
    assert await classify_corporate_sessions(db, cid) == 3
    assert await classify_corporate_sessions(db, cid) == 0
    for session in sessions:
        await db.refresh(session)
        assert session.client_amount == Decimal("123.40")
        assert session.client_tariff == Decimal("12.34")
        assert session.amount == 0
    assert [session.user_type for session in sessions] == ["ЮЛ", "ЮЛ", "ЮЛ", "ЮЛ", "ФЛ", None, None, None]
    assert sessions[1].cut_key == "ezs_corp" and sessions[3].cut_key == "ezs_admin"
    report = await AnalyticsService(db).charge_timeseries(PeriodFilter(
        company_id=cid, date_from=date(2026, 7, 1), date_to=date(2026, 9, 30),
        dim_by="user_type", dim_val="ЮЛ"), bucket="month")
    assert [item["value"] for item in report["data"]] == [123.4, 123.4, 123.4]
    await db.rollback()


async def test_automatic_enrichment_classifies_new_sessions_and_preserves_existing_prices(db):
    cid = (await db.execute(select(Company.id).limit(1))).scalar_one()
    db.add(CorporateClient(company_id=cid, name="Клиент API", phone="70000000002", mode="flat", rate=20))
    existing = ChargeSession(company_id=cid, session_ext_id=str(uuid4()), user_id="70000000002",
        user_type=None, client_name="Клиент API", client_amount=123, client_tariff=12.3, amount=0)
    fresh = ChargeSession(company_id=cid, session_ext_id=str(uuid4()), user_id="70000000002",
        user_type=None, amount=0, energy_kwh=10, tariff=30, charge_type="RFID")
    db.add_all([existing, fresh])
    await db.flush()
    orgs = [{"name": "Клиент API", "phone": "70000000002", "mode": "flat", "rate": 20}]
    await _apply_org_enrichment(db, cid, orgs, {}, None, only_missing=True)
    await db.refresh(existing)
    await db.refresh(fresh)
    assert existing.user_type == fresh.user_type == "ЮЛ"
    assert existing.client_amount == 123 and existing.client_tariff == Decimal("12.30")
    assert fresh.client_amount == 200 and fresh.cut_key == "ezs_corp"
    assert await _apply_org_enrichment(db, cid, orgs, {}, None, only_missing=True) == (0, 0, 0)
    await db.rollback()
