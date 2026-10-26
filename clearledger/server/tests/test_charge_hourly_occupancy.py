"""Интервальная арифметика и контракт PostgreSQL/API, без рабочих данных."""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import ChargeSession, Company, Region, ServiceLocation, User, UserCompany
from app.routers import analytics_router
from app.services.analytics_service import PeriodFilter
from app.services.charge_hourly_occupancy import calculate_hourly_occupancy, hourly_occupancy


DAY = date(2026, 10, 22)


def stamp(value):
    return datetime.fromisoformat(value) if value else None


def station(key="a", offset=0):
    return dict(station_id=key, station_code="same-code", station_name="ЭЗС " + key,
                label="ЭЗС " + key, msk_offset=offset)


def port(key="a", no="1", kind="CCS"):
    return dict(id=f"{key}:{no}", label=f"ЭЗС {key} · №{no}", station_id=key,
                station_code="same-code", station_name="ЭЗС " + key,
                connector_no=no, connector_type=kind)


def session(start, finish, key="a", no="1", kind="CCS"):
    return dict(station_id=key, connector_no=no, connector_type=kind,
                started_at=stamp(start), finished_at=stamp(finish))


def calc(rows, *, stations=None, ports=None, **kwargs):
    return calculate_hourly_occupancy(stations or [station()], ports or [port()], rows,
                                      DAY, kwargs.pop("date_to", DAY), **kwargs)


def points(result, key=None):
    return next(s["points"] for s in result["series"] if key is None or s["id"] == key)


def test_hour_and_day_and_both_period_edges():
    rows = [session("2026-10-21T23:40", "2026-10-22T00:20"),
            session("2026-10-22T10:45", "2026-10-22T11:15"),
            session("2026-10-22T23:50", "2026-10-23T00:20"),
            session("2026-10-23T00:00", "2026-10-23T00:30"),
            session("2026-10-21T23:00", "2026-10-22T00:00")]
    p = points(calc(rows))
    assert [p[h]["occupied_minutes"] for h in (0, 10, 11, 23)] == [20, 15, 15, 10]
    assert sum(x["starts"] for x in p) == 2
    assert all(x["available_minutes"] == 60 for x in p)
    assert len(p) == 24


def test_interval_spanning_whole_period_and_daily_denominator():
    p = points(calc([session("2026-09-01T00:00", "2026-11-01T00:00")],
                    date_to=date(2026, 10, 23)))
    assert all(x["occupied_minutes"] == 120 and x["available_minutes"] == 120
               and x["occupancy_pct"] == 100 and x["starts"] == 0 for x in p)


def test_overlaps_same_port_and_different_ports_station_union():
    rows = [session("2026-10-22T10:00", "2026-10-22T10:40"),
            session("2026-10-22T10:20", "2026-10-22T10:50"),
            session("2026-10-22T10:30", "2026-10-22T11:00", no="2")]
    ports = [port(), port(no="2")]
    p = points(calc(rows, ports=ports, group_by="station"))
    assert p[10] == dict(hour=10, occupied_minutes=60, available_minutes=60, occupancy_pct=100, starts=3)
    result = calc(rows, ports=ports)
    assert result["group_by"] == "connector"
    assert points(result, "a:1")[10]["occupied_minutes"] == 50
    assert points(result, "a:2")[10]["occupied_minutes"] == 30
    assert len(result["series"]) == 2  # одинаковый тип не склеивает физические порты


def test_filter_physical_and_type_intersection_preserves_selector_catalog():
    rows = [session("2026-10-22T10:00", "2026-10-22T10:40"),
            session("2026-10-22T10:20", "2026-10-22T11:00", no="2", kind="TYPE2")]
    ports = [port(), port(no="2", kind="TYPE2")]
    result = calc(rows, ports=ports, connector_ids=["a:2"], connector_types=["TYPE2"])
    assert [s["id"] for s in result["series"]] == ["a:2"]
    assert points(result)[10]["occupied_minutes"] == 40
    assert points(result)[10]["starts"] == 1
    assert result["connectors"] == ports
    empty = calc(rows, ports=ports, connector_ids=["a:1"], connector_types=["TYPE2"])
    assert empty["series"] == [] and empty["connectors"] == ports


def test_type_filter_uses_historical_type_without_changing_physical_identity():
    rows = [session("2026-10-22T10:00", "2026-10-22T10:40", kind="TYPE2")]
    result = calc(rows, connector_types=["TYPE2"], connector_ids=["a:1"],
                  physical_connector_types={"a:1": {"CCS", "TYPE2"}})
    assert [s["id"] for s in result["series"]] == ["a:1"]
    assert points(result)[10]["starts"] == 1
    assert points(result)[10]["occupied_minutes"] == 40


def test_invalid_intervals_still_count_starts_and_quality():
    rows = [session("2026-10-22T10:00", None),
            session("2026-10-22T10:01", "2026-10-22T10:00"),
            session("2026-10-22T10:02", "2026-10-22T10:02"),
            session(None, "2026-10-22T10:30"), session(None, None),
            session("2026-10-22T11:00", "2026-10-22T11:30", no=None),
            session("2026-10-22T12:00", "2026-10-22T12:30", key=None)]
    result = calc(rows, group_by="station")
    assert points(result)[10]["starts"] == 3
    assert points(result)[10]["occupied_minutes"] == 0
    assert points(result)[11]["occupied_minutes"] == 30
    assert result["quality"] == dict(missing_interval_sessions=5, missing_connector_sessions=1,
                                      unmapped_station_sessions=1, last_session_at=None)
    filtered = calc(rows, group_by="station", connector_ids=["a:1"])
    assert points(filtered)[11]["starts"] == 0
    assert points(filtered)[11]["occupied_minutes"] == 0


def test_local_timezone_changes_calendar_period_and_hour():
    rows = [session("2026-10-21T20:45", "2026-10-21T21:15"),
            session("2026-10-22T20:45", "2026-10-22T21:15")]
    local = calc(rows, stations=[station(offset=3)], tz="local")
    assert points(local)[0]["occupied_minutes"] == 15
    assert points(local)[23]["occupied_minutes"] == 15
    assert points(local)[23]["starts"] == 1
    msk = calc(rows, stations=[station(offset=3)])
    assert points(msk)[20]["occupied_minutes"] == 15
    assert points(msk)[21]["occupied_minutes"] == 15
    assert points(msk)[0]["occupied_minutes"] == 0


def test_zero_data_and_auto_multiple_stations_with_identical_codes():
    result = calc([], stations=[station(), station("b")], ports=[port(), port("b")])
    assert result["group_by"] == "station"
    assert {s["id"] for s in result["series"]} == {"a", "b"}
    assert all(p["occupied_minutes"] == p["starts"] == p["occupancy_pct"] == 0
               for s in result["series"] for p in s["points"])
    result = calculate_hourly_occupancy([], [], [], DAY, DAY)
    assert result["series"] == result["connectors"] == []
    assert result["hours"] == list(range(24))


def test_known_type_without_physical_number_can_occupy_station():
    rows = [session("2026-10-22T10:00", "2026-10-22T10:30", no=None)]
    # Источник знает тип, но ещё не обогащён номером порта.
    result = calculate_hourly_occupancy([station()], [], rows, DAY, DAY,
                                       group_by="station", connector_types=["CCS"],
                                       available_connector_types=["CCS"])
    assert points(result)[10]["occupied_minutes"] == 30
    assert points(result)[10]["starts"] == 1
    assert result["quality"]["missing_connector_sessions"] == 1

    assert result["connector_types"] == ["CCS"]
    result = calculate_hourly_occupancy([station()], [], rows, DAY, DAY,
                                       group_by="connector", connector_types=["CCS"])
    assert result["series"] == []
    assert result["quality"]["missing_connector_sessions"] == 1


def test_unknown_port_does_not_mean_idle_and_does_not_contaminate_other_stations_or_types():
    rows = [session("2026-10-21T23:40", "2026-10-22T00:20", no=None)]
    result = calc(rows, stations=[station(), station('b')], ports=[port(), port(no='2', kind='TYPE2'), port('b')],
                  group_by='connector')
    assert points(result, 'a:1')[0].get('occupancy_complete') is False
    assert points(result, 'a:1')[0].get('starts_complete', True) is True
    assert points(result, 'a:2')[0].get('occupancy_complete', True) is True
    assert points(result, 'b:1')[0].get('occupancy_complete', True) is True
    assert points(result, 'a:1')[1].get('occupancy_complete', True) is True


def test_selecting_physical_port_keeps_uncertainty_about_unassigned_sessions():
    rows = [session('2026-10-22T01:10', '2026-10-22T01:40', no=None)]
    result = calc(rows, connector_ids=['a:1'], group_by='connector')
    assert points(result)[1]['occupied_minutes'] == 0  # известная часть; не выдаётся как полный ноль
    assert points(result)[1]['occupancy_complete'] is False
    assert points(result)[1]['starts_complete'] is False
    assert result['quality']['missing_connector_sessions'] == 1
    station_result = calc(rows, connector_ids=['a:1'], group_by='station')
    assert points(station_result)[1]['occupancy_complete'] is False


@pytest.fixture
async def occupied_scope(db):
    own = Company(id=uuid4(), name="Тест занятости", slug="hourly-" + uuid4().hex, profile_id="energy")
    other = Company(id=uuid4(), name="Чужая компания", slug="hourly-" + uuid4().hex, profile_id="energy")
    db.add_all([own, other])
    await db.flush()
    region = Region(company_id=own.id, name="Восток", msk_offset=3)
    db.add(region)
    await db.flush()
    a = ServiceLocation(id="ho-" + uuid4().hex, company_id=own.id, code="serial-a",
                        station_number="same-code", name="Первая", type="ev_charging", region_id=region.id)
    b = ServiceLocation(id="ho-" + uuid4().hex, company_id=own.id, code="same-code",
                        station_number="same-code", name="Вторая", type="ev_charging")
    foreign = ServiceLocation(id="ho-" + uuid4().hex, company_id=other.id, code="same-code",
                              name="Чужая", type="ev_charging")
    retired = ServiceLocation(id="ho-" + uuid4().hex, company_id=own.id, code="retired",
                              name="Выведена", type="ev_charging", operational_status="decommissioned")
    db.add_all([a, b, foreign, retired])
    await db.flush()

    def add(location, start, end, no="1", kind="CCS", company=None, code="same-code"):
        db.add(ChargeSession(company_id=company or own.id, location_id=location,
                             station_code=code, session_ext_id=uuid4().hex, connector_no=no,
                             connector_type=kind, started_at=stamp(start), finished_at=stamp(end),
                             energy_kwh=0, amount=0, result="CompleteError", duration_min=999))

    add(a.id, "2026-10-21T23:30", "2026-10-22T00:30")
    add(a.id, "2026-10-22T00:00", "2026-10-22T01:00")
    add(a.id, "2026-10-22T00:30", "2026-10-22T01:30", no="2")
    add(a.id, "2026-10-22T10:00", None)
    add(a.id, "2026-10-22T10:30", "2026-10-22T10:00")
    add(a.id, None, "2026-10-22T12:00")
    add(a.id, "2026-10-22T12:00", "2026-10-22T12:30", no=None)
    add(a.id, "2026-09-01T01:00", "2026-09-01T02:00", no="3", kind="TYPE2")
    add(b.id, "2026-10-22T10:00", "2026-10-22T10:10")
    add(None, "2026-10-22T10:00", "2026-10-22T10:10")
    add(foreign.id, "2026-10-22T10:00", "2026-10-22T11:00", company=other.id)
    # Даже ошибочная межкомпанейская ссылка не может раскрыть чужую станцию.
    add(foreign.id, "2026-10-22T10:00", "2026-10-22T11:00")
    add(retired.id, "2026-10-22T10:00", "2026-10-22T11:00")
    await db.flush()
    yield own, other, a, b
    await db.rollback()


@pytest.mark.asyncio
async def test_postgres_identity_intervals_filters_and_history(db, occupied_scope):
    own, other, a, b = occupied_scope
    f = PeriodFilter(company_id=own.id, date_from=DAY, date_to=DAY)
    result = await hourly_occupancy(db, f)
    assert {s["id"] for s in result["series"]} == {a.id, b.id}
    assert points(result, a.id)[0]["occupied_minutes"] == 60
    assert points(result, a.id)[1]["occupied_minutes"] == 30
    assert points(result, a.id)[10]["starts"] == 2
    assert points(result, a.id)[10]["occupied_minutes"] == 0
    assert points(result, a.id)[12]["occupied_minutes"] == 30
    assert points(result, b.id)[10]["occupied_minutes"] == 10
    assert len(result["connectors"]) == 4
    assert result["quality"]["missing_interval_sessions"] == 3
    assert result["quality"]["unmapped_station_sessions"] == 2
    assert result["quality"]["missing_connector_sessions"] == 1
    assert result["quality"]["last_session_at"] == "2026-10-22T12:00:00+03:00"
    assert result["connector_types"] == ["CCS", "TYPE2"]
    selected = await hourly_occupancy(db, f, connector_ids=[a.id + ":2"], group_by="connector")
    assert [s["id"] for s in selected["series"]] == [a.id + ":2"]
    assert points(selected)[0]["occupied_minutes"] == 30
    assert points(selected)[0]["starts"] == 1
    assert selected["quality"]["missing_connector_sessions"] == 1
    assert points(selected)[12]["occupancy_complete"] is False
    assert points(selected)[12]["starts_complete"] is False
    assert selected["connectors"] == result["connectors"]
    zero = await hourly_occupancy(db, f, connector_types=["TYPE2"], group_by="connector")
    assert [s["id"] for s in zero["series"]] == [a.id + ":3"]
    assert all(p["occupied_minutes"] == p["starts"] == 0 for p in points(zero))
    assert zero["connectors"] == result["connectors"]
    assert zero["connector_types"] == result["connector_types"]
    f.regions = ["Восток"]
    local = await hourly_occupancy(db, f, tz="local")
    assert local["group_by"] == "connector"
    assert {s["station_id"] for s in local["series"]} == {a.id}
    assert points(local, a.id + ":1")[2]["occupied_minutes"] == 30
    assert points(local, a.id + ":1")[3]["occupied_minutes"] == 60
    assert local["quality"]["unmapped_station_sessions"] == 0
    f.regions = None
    f.station_codes = ["no-such-code"]
    empty = await hourly_occupancy(db, f, connector_ids=[a.id + ":1"])
    assert empty["series"] == empty["connectors"] == []
    assert empty["quality"]["last_session_at"] is None


@pytest.mark.asyncio
async def test_passport_ports_without_sessions_remain_selectable_and_zero(db, occupied_scope):
    own, other, a, b = occupied_scope
    a.extra_metadata = {"connectors": [{"no": 1, "type": "CCS"},
                                      {"no": 4, "type": "CCS"}, {"no": 5, "type": "AC"}]}
    await db.flush()
    f = PeriodFilter(company_id=own.id, date_from=DAY, date_to=DAY)
    result = await hourly_occupancy(db, f, group_by="connector")
    catalog = {port["id"] for port in result["connectors"]}
    assert a.id + ":4" in catalog and a.id + ":5" in catalog
    assert all(p["occupied_minutes"] == p["starts"] == 0 for p in points(result, a.id + ":4"))
    assert "AC" in result["connector_types"]
    selected = await hourly_occupancy(db, f, connector_ids=[a.id + ":4"], group_by="connector")
    assert [s["id"] for s in selected["series"]] == [a.id + ":4"]
    assert len(points(selected)) == 24
    assert {port["id"] for port in selected["connectors"]} == catalog
    by_type = await hourly_occupancy(db, f, connector_types=["CCS"], group_by="connector")
    assert a.id + ":4" in {s["id"] for s in by_type["series"]}
    assert a.id + ":5" not in {s["id"] for s in by_type["series"]}


@pytest.mark.asyncio
async def test_postgres_dim_filter_does_not_expand_company(db, occupied_scope):
    own, other, a, b = occupied_scope
    f = PeriodFilter(company_id=own.id, date_from=DAY, date_to=DAY,
                     dim_by="connector", dim_val="TYPE2")
    result = await hourly_occupancy(db, f, group_by="connector")
    assert [s["id"] for s in result["series"]] == [a.id + ":3"]
    assert len(result["connectors"]) == 1
    f.company_id = other.id
    assert (await hourly_occupancy(db, f))["connectors"] == []


@pytest.mark.asyncio
async def test_postgres_current_number_preserves_history_and_object_scope(db, occupied_scope):
    from app.scope import set_request_scope
    own, other, a, b = occupied_scope
    a.station_number = "new-a"
    b.station_number = "new-b"
    await db.flush()
    f = PeriodFilter(company_id=own.id, date_from=DAY, date_to=DAY, station_codes=["new-a"])
    result = await hourly_occupancy(db, f, group_by="station")
    assert [s["id"] for s in result["series"]] == [a.id]
    assert points(result)[0]["occupied_minutes"] == 60
    try:
        set_request_scope([b.id])
        assert (await hourly_occupancy(db, f))["series"] == []
        f.station_codes = None
        result = await hourly_occupancy(db, f)
        assert {s["station_id"] for s in result["series"]} == {b.id}
        assert {c["station_id"] for c in result["connectors"]} == {b.id}
        assert result["quality"]["unmapped_station_sessions"] == 0
    finally:
        set_request_scope(None)


@pytest.mark.asyncio
async def test_real_route_denies_membership_and_sales_product(client, db, occupied_scope):
    from app.auth import get_current_user
    from app.database import get_db
    from app.main import app
    own, other, a, b = occupied_scope
    user = User(email=uuid4().hex + "@example.test", name="Проверка прав", password_hash="!unused")
    db.add(user)
    await db.flush()
    member = UserCompany(user_id=user.id, company_id=own.id, modules=["management"], role="user")
    db.add(member)
    await db.flush()
    async def request_db():
        yield db
    old_db = app.dependency_overrides.get(get_db)
    old_user = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: user
    url = "/api/analytics/charge-sessions/hourly-occupancy"
    params = dict(company_id=str(own.id), date_from=DAY.isoformat(), date_to=DAY.isoformat())
    try:
        denied = await client.get(url, params=params)
        assert denied.status_code == 403
        assert denied.json()["detail"] == "Нет доступа к продукту"
        member.modules = ["sales"]
        member.object_scope = [a.id]
        await db.flush()
        permitted = await client.get(url, params=params)
        assert permitted.status_code == 200, permitted.text
        assert {s["station_id"] for s in permitted.json()["series"]} == {a.id}
        assert {c["station_id"] for c in permitted.json()["connectors"]} == {a.id}
        # Параметры не могут расширить ни object_scope, ни компанию членства.
        foreign = await client.get(url, params=params | {"company_id": str(other.id)})
        assert foreign.status_code == 403
        assert foreign.json()["detail"] == "Нет доступа к компании"
    finally:
        if old_db is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_db
        if old_user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = old_user


@pytest.mark.asyncio
async def test_route_sales_permission_and_parameters(monkeypatch):
    period = PeriodFilter(company_id=uuid4(), date_from=DAY, date_to=DAY)
    guard = AsyncMock(return_value=period)
    service = AsyncMock(return_value={"series": []})
    monkeypatch.setattr(analytics_router, "_filter_from_query", guard)
    monkeypatch.setattr("app.services.charge_hourly_occupancy.hourly_occupancy", service)
    await analytics_router.get_charge_hourly_occupancy(
        company_id="company", date_from="2026-10-22", date_to="2026-10-22",
        stations="a,b", regions="Восток", tz="local", group_by="connector",
        connector_types="CCS,TYPE2", connector_ids='["a:1", "b:2"]', dim=None, dim_val=None,
        db=SimpleNamespace(), current_user=SimpleNamespace())
    assert guard.await_args.args[-1] == "sales"
    assert service.await_args.kwargs["connector_ids"] == ["a:1", "b:2"]
    assert period.station_codes == ["a", "b"]


@pytest.mark.asyncio
async def test_route_validation_and_auth(auth_client, client, db):
    own = (await db.execute(select(Company).where(Company.slug == "rushydro"))).scalar_one()
    url = "/api/analytics/charge-sessions/hourly-occupancy"
    base = dict(company_id=str(own.id), date_from="2026-10-22", date_to="2026-10-22")
    assert (await client.get(url, params=base)).status_code == 401
    assert (await auth_client.get(url, params={k: v for k, v in base.items() if k != "company_id"})).status_code == 422
    for extra in ({"connector_ids": "{}"}, {"connector_ids": '[1]'}, {"connector_ids": '[""]'},
                  {"connector_ids": "no"}, {"date_to": "2026-10-21"}, {"tz": "bad"},
                  {"group_by": "type"}, {"dim": "bad", "dim_val": "x"},
                  {"dim": "tariff", "dim_val": "NaN"}, {"dim": "connector"}):
        assert (await auth_client.get(url, params=base | extra)).status_code in (400, 422)
    response = await auth_client.get(url, params=base)
    assert response.status_code == 200, response.text
    assert response.json()["hours"] == list(range(24))
