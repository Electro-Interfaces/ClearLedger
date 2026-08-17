from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import app.auth as auth
from app.routers import analytics_router, overview_router
from app.services.analytics_service import AnalyticsService
from app.services.charge_payment_state import effective_paid_at
from app.services.charge_reconciliation import _WHERE
from app.services.overview_service import OverviewService


def test_effective_payment_uses_confirmed_bank_transaction():
    sql = str(select(effective_paid_at()).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))

    assert "charge_payments" in sql
    assert "bank_txn_id IS NOT NULL" in sql
    assert "session_ext_id = charge_sessions.session_ext_id" in sql


def test_error_sessions_are_not_everything_except_complete():
    row = SimpleNamespace(
        g="Вся сеть", cnt=8000, energy=10, amount=20, duration=30,
        success=7500, errors=275, paid=7000, cnt_retail=7800, charged=6000,
        dur_charged=25, visits=6200, visits_ok=5900, cnt_retail_charged=5800,
        unpaid_charged=12, ports=100, stations=50,
    )

    metrics = AnalyticsService(None)._cs_metrics("result", row, period_days=1)

    assert metrics["error_sessions"] == 275
    assert metrics["error_sessions"] != row.cnt - row.success


def test_reconciliation_treats_unconfirmed_attempt_as_unpaid():
    assert "pay.pay_ok = 0" in _WHERE["no_payment"]
    assert "pay.pay_all" not in _WHERE["no_payment"]


@pytest.mark.asyncio
async def test_management_only_role_cannot_open_sales(monkeypatch):
    company_id = uuid4()
    user = SimpleNamespace(id=uuid4(), is_superadmin=False)
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(role="user")))
    monkeypatch.setattr(auth, "assert_company_member", AsyncMock(return_value=company_id))
    monkeypatch.setattr(auth, "resolve_member_modules", AsyncMock(return_value=["management"]))

    with pytest.raises(HTTPException) as exc:
        await auth.assert_company_product(str(company_id), user, db, "sales")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_sales_registry_route_requires_sales_product(monkeypatch):
    period = SimpleNamespace(company_id=uuid4(), station_codes=None, regions=None)
    filter_mock = AsyncMock(return_value=period)
    rows_mock = AsyncMock(return_value={"rows": [], "total": 0})
    monkeypatch.setattr(analytics_router, "_filter_from_query", filter_mock)
    monkeypatch.setattr(AnalyticsService, "charge_rows", rows_mock)

    await analytics_router.get_charge_rows(
        company_id="rushydro", date_from="2026-08-01", date_to="2026-08-17",
        limit=50, offset=0, user_type=None, region=None, connector=None,
        result=None, paid=None, search=None, sort="started_at", sort_dir="desc",
        stations=None, regions=None, station_id=None, db=SimpleNamespace(),
        current_user=SimpleNamespace(),
    )

    assert filter_mock.await_args.args[-1] == "sales"
    rows_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_sales_overview_route_requires_sales_product(monkeypatch):
    company_id = uuid4()
    access_mock = AsyncMock(return_value=company_id)
    overview_mock = AsyncMock(return_value={"meta": {}})
    monkeypatch.setattr(overview_router, "assert_company_product", access_mock)
    monkeypatch.setattr(OverviewService, "overview", overview_mock)

    await overview_router.charge_overview(
        company_id="rushydro", date_from="2026-08-01", date_to="2026-08-17",
        compare="prev", stations=None, regions=None, tz="msk",
        db=SimpleNamespace(), current_user=SimpleNamespace(),
    )

    assert access_mock.await_args.args[-1] == "sales"
    overview_mock.assert_awaited_once()
