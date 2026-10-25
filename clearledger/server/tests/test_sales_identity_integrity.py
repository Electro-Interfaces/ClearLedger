"""История объекта, классификация и точные итоги на синтетических данных."""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import ChargeSession as S, Company, ServiceLocation
from app.services.analytics_service import AnalyticsService, PeriodFilter
from app.services.charge_hourly_occupancy import hourly_occupancy
from app.services.charge_identity import client_type, client_type_sql
from app.services.session_scope import station_match, station_scope_sql
from sqlalchemy import text
from app.services.charge_visits import visits_report
from app.services.charge_unpaid import unpaid_report
from app.services.port_efficiency import port_efficiency


DAY = date(2026, 10, 1)


@pytest.fixture
async def sales_history(db):
    company = Company(id=uuid4(), name="Проверка продаж", slug="sales-" + uuid4().hex, profile_id="energy")
    db.add(company)
    await db.flush()
    first = ServiceLocation(id="sa-" + uuid4().hex, company_id=company.id, code="serial-1",
                            station_number="NEW", name="Первая ЭЗС", type="ev_charging",
                            extra_metadata={"numberHistory": [{"было": "OLD"}]})
    second = ServiceLocation(id="sb-" + uuid4().hex, company_id=company.id, code="serial-2",
                             station_number="REUSED", name="Вторая ЭЗС", type="ev_charging")
    db.add_all([first, second])
    await db.flush()
    samples = [
        (first, "OLD", "1", None, "retail", None),
        (first, "NEW", "1", None, "corp", "Организация"),
        # Исторический номер теперь принадлежит второй станции. Связь с первой
        # нельзя потерять или переприсвоить по совпавшей строке номера.
        (first, "REUSED", "2", None, None, None),
        (second, "REUSED", "1", "ФЛ", None, None),
    ]
    for i, (loc, code, no, kind, account, client) in enumerate(samples):
        db.add(S(company_id=company.id, session_ext_id=uuid4().hex, location_id=loc.id,
                 station_code=code, station_name="", connector_no=no, connector_type="CCS",
                 user_type=kind, user_id=account, client_name=client,
                 started_at=datetime(2026, 10, 1, i), finished_at=datetime(2026, 10, 1, i, 10),
                 duration_min=10, visit_key=uuid4().hex, visit_seq=1, visit_size=1, visit_charged=True, energy_kwh=Decimal("0.049"), amount=Decimal("1.01"),
                 client_amount=Decimal("2.02") if client else None))
    await db.flush()
    yield company.id, first, second
    await db.rollback()


@pytest.mark.asyncio
async def test_client_type_preserves_unknown_and_agrees_with_registry(db, sales_history):
    cid, *_ = sales_history
    types = (await db.execute(select(client_type()).where(S.company_id == cid).order_by(S.started_at))).scalars().all()
    assert types == ["ФЛ", "ЮЛ", None, "ФЛ"]
    raw_types = (await db.execute(text("SELECT " + client_type_sql() + " FROM charge_sessions WHERE company_id=:cid ORDER BY started_at"), {"cid": cid})).scalars().all()
    assert raw_types == types
    unknown = await AnalyticsService(db).charge_sessions(PeriodFilter(cid, DAY, DAY, dim_by="user_type", dim_val="—"))
    assert unknown["totals"]["sessions"] == 1
    svc = AnalyticsService(db)
    for kind, expected in [("ФЛ", 2), ("ЮЛ", 1)]:
        f = PeriodFilter(cid, DAY, DAY, dim_by="user_type", dim_val=kind)
        report = await svc.charge_sessions(f, group_by="user_type")
        registry = await svc.charge_rows(f, user_type=kind)
        assert report["totals"]["sessions"] == registry["total"] == expected
        assert all(row["user_type"] == kind for row in registry["rows"])


@pytest.mark.asyncio
async def test_aliases_group_ports_and_hours_by_object(db, sales_history):
    cid, first, _ = sales_history
    svc = AnalyticsService(db)
    f = PeriodFilter(cid, DAY, DAY, station_codes=["NEW"])
    report = await svc.charge_sessions(f)
    assert len(report["lines"]) == 1
    assert report["lines"][0]["label"] == "Первая ЭЗС (NEW)"
    assert report["totals"]["sessions"] == 3
    assert report["totals"]["stations"] == 1
    assert report["totals"]["ports"] == 2
    hours = await hourly_occupancy(db, f, group_by="station")
    assert sum(p["starts"] for s in hours["series"] for p in s["points"]) == 3
    # Перечень фильтра не создаёт вторую станцию из старого номера.
    dimensions = await svc.charge_dimensions(cid)
    assert {s["code"] for s in dimensions["stations"]} == {"NEW", "REUSED"}
    assert next(s for s in dimensions["stations"] if s["code"] == "NEW")["sessions"] == 3
    # SQL и ORM должны одинаково обрабатывать повторно занятый номер.
    orm_ids = set((await db.execute(select(S.location_id).where(S.company_id == cid,
        station_match(S.station_code, S.location_id, cid, ["REUSED"])))).scalars())
    sql_ids = set((await db.execute(text("SELECT location_id FROM charge_sessions WHERE company_id=:company_id AND "
        + station_scope_sql()), {"company_id": cid, "stations": ["REUSED"]})).scalars())
    assert orm_ids == sql_ids
    assert first.id not in orm_ids


@pytest.mark.asyncio
async def test_total_energy_does_not_depend_on_group_rounding(db, sales_history):
    cid, *_ = sales_history
    svc = AnalyticsService(db)
    totals = []
    for group in ("station", "connector", "user_type", "day", "tariff"):
        data = await svc.charge_sessions(PeriodFilter(cid, DAY, DAY), group_by=group)
        totals.append((data["totals"]["energy_kwh"], data["totals"]["amount"]))
    assert totals == [(0.196, 5.05)] * 5


@pytest.mark.asyncio
async def test_sql_report_filters_share_classification_and_object_scope(db, sales_history):
    cid, first, _ = sales_history
    for kind, count in [("ФЛ", 2), ("ЮЛ", 1)]:
        visits = await visits_report(db, cid, DAY, DAY, user_type=kind)
        ports = await port_efficiency(db, cid, DAY, DAY, user_type=kind)
        debt = await unpaid_report(db, cid, DAY, DAY, user_type=kind)
        assert visits["totals"]["sessions"] == count
        assert ports["totals"]["sessions"] == count
        assert sum(debt["totals"][key]["sessions"] for key in ("debt", "postpaid", "probes")) == count
    visits = await visits_report(db, cid, DAY, DAY, stations=["NEW"])
    assert len(visits["stations"]) <= 1
    assert visits["totals"]["sessions"] == 3
