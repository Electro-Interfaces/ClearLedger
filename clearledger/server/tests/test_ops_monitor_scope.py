import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.models import ChargeSession, Company, ServiceLocation
from app.services.network_reliability import network_reliability
from app.services.network_state import network_state
from app.services.network_vendors import network_vendors
from app.services.ops_monitor_context import monitor_locations
from app.services.ops_tickets import ops_tickets
from app.services.ops_worklist import ops_worklist, _с_дня


@pytest_asyncio.fixture(loop_scope='session')
async def monitor_fleet(db):
    company = Company(name='Проверка мониторинга', slug='monitor-' + uuid.uuid4().hex, profile_id='energy')
    other = Company(name='Другая компания', slug='monitor-' + uuid.uuid4().hex, profile_id='energy')
    db.add_all([company, other])
    await db.flush()
    stations = []
    for key, region, brand, cid in [('a', 'Москва', 'Марка A', company.id),
                                    ('b', 'Омская область', 'Марка B', company.id),
                                    ('foreign', 'Москва', 'Марка A', other.id)]:
        station = ServiceLocation(id='monitor-' + uuid.uuid4().hex, company_id=cid,
                                  code='serial-' + key, name='Станция ' + key, type='ev_charging',
                                  operational_status='working', station_number='new-' + key,
                                  brand=brand, extra_metadata={'number': 'new-' + key, 'federalSubject': region,
                                                              'buNumber': 'old-' + key})
        db.add(station)
        stations.append(station)
    await db.flush()
    for station in stations:
        for i in range(12):
            db.add(ChargeSession(company_id=station.company_id, location_id=station.id,
                                 station_code=station.station_number, session_ext_id=station.id + str(i),
                                 started_at=datetime(2026, 10, 15, 12) + timedelta(hours=i),
                                 energy_kwh=0 if i < 4 else 10, amount=100,
                                 result='Complete', user_id=str(i), visit_key=station.id + str(i)))
    await db.flush()
    yield db, company.id, stations
    await db.rollback()


@pytest.mark.asyncio(loop_scope='session')
async def test_station_numbers_intersection_and_company_boundary(monitor_fleet):
    db, cid, (a, b, foreign) = monitor_fleet
    assert await monitor_locations(db, cid) is None
    assert await monitor_locations(db, cid, station_codes='new-a') == {a.id}
    assert await monitor_locations(db, cid, station_codes='old-a') == {a.id}
    assert await monitor_locations(db, cid, station_codes='new-foreign') == set()
    assert await monitor_locations(db, cid, station_codes='missing') == set()
    assert await monitor_locations(db, cid, a.id, 'new-b') == set()
    assert await monitor_locations(db, cid, a.id + '|' + b.id, 'old-a') == {a.id}
    replacement = ServiceLocation(id='monitor-' + uuid.uuid4().hex, company_id=cid, code='serial-reused',
                                  name='Новый владелец номера', type='ev_charging', station_number='old-a')
    db.add(replacement)
    await db.flush()
    assert await monitor_locations(db, cid, station_codes='old-a') == {replacement.id}


@pytest.mark.asyncio(loop_scope='session')
@pytest.mark.parametrize('selected', ['a', 'empty'])
async def test_scoped_rows_totals_groups_trend_and_worklist(monitor_fleet, selected):
    db, cid, (a, b, foreign) = monitor_fleet
    scope = {a.id} if selected == 'a' else set()
    count = len(scope)
    day = date(2026, 10, 17)
    state = await network_state(db, cid, location_ids=scope, as_of=day)
    assert {r['locationId'] for r in state['stations']} == scope
    assert state['totals']['stations'] == count
    assert sum(r['stations'] for r in state['regions']) == count
    reliability = await network_reliability(db, cid, location_ids=scope, min_sessions=1, as_of=day)
    assert {r['locationId'] for r in reliability['stations']} == scope
    assert reliability['totals']['populationStations'] == count
    assert reliability['totals']['visits'] == count * 12
    assert reliability['trend']['current']['visits'] == count * 12
    vendors = await network_vendors(db, cid, location_ids=scope, vendor='*', as_of=day)
    assert vendors['totals']['stations'] == count
    assert {r['locationId'] for r in vendors['stations']} == scope
    with patch('app.services.ops_worklist.network_upkeep', AsyncMock(return_value={'rows': []})):
        queue = await ops_worklist(db, cid, location_ids=scope, open_work={}, as_of=day)
    assert {r['locationId'] for r in queue['rows']} == scope
    assert queue['totals']['rows'] == count
    assert queue['totals']['failing'] == count
    assert queue['totals']['upkeepUnknown'] == 0
    outside_region = await network_state(db, cid, location_ids=scope, region='Омская область', as_of=day)
    assert outside_region['totals']['stations'] == 0


@pytest.mark.asyncio(loop_scope='session')
async def test_tickets_keep_old_open_only_inside_selected_scope(monitor_fleet):
    db, cid, (a, b, foreign) = monitor_fleet
    rows = [{'id': key, 'number': key, 'ecoObjectId': loc,
             'created_at': '2026-01-02T12:00:00Z', 'is_open': True, 'in_window': False}
            for key, loc in [('a', a.id), ('b', b.id), ('unmapped', None), ('foreign', foreign.id)]]
    raw = {'rows': rows, 'asOf': '2026-10-17T12:00:00+03:00'}
    with patch('app.services.ops_tickets.space_projection.monitoring_tickets', AsyncMock(return_value=raw)), \
         patch('app.services.ops_tickets.space_projection.network_open_tickets', AsyncMock(return_value={'objects': []})):
        selected = await ops_tickets(db, cid, location_ids={a.id})
        assert [r['id'] for r in selected['rows']] == ['a']
        assert selected['totals']['open'] == 1
        assert selected['totals']['inWindow'] == 0
        empty = await ops_tickets(db, cid, location_ids=set())
        assert empty['rows'] == []
        assert empty['totals']['open'] == 0
        region = await ops_tickets(db, cid, region='Омская область')
        assert [r['id'] for r in region['rows']] == ['b']


def test_reason_date_keeps_year():
    assert _с_дня('2025-12-31', False) == 'с 31.12.2025'
    assert _с_дня('2026-01-01', True) == 'с 01.01.2026 и раньше'
