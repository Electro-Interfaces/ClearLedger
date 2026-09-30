"""Ряд статусов витрины: с какого дня статус и какие разъёмы неисправны."""
from datetime import date

from app.services.station_status_days import status_now_from


def test_status_now_since_and_faults():
    d = [date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 14), date(2026, 9, 15)]
    s = {
        # без связи с первой книги — начало раньше, чем видно
        "a": {x: ("no_link", {"1": "Зарядка"}) for x in d},
        # отключена с 14.09 (12.09 работала)
        "b": {d[0]: ("working", {}), d[1]: ("working", {}), d[2]: ("disabled", {}), d[3]: ("disabled", {})},
        # разъём 2 в ошибке три книги подряд, разъём 1 — только сегодня
        "c": {d[0]: ("working", {"1": "Доступен", "2": "Доступен"}),
              d[1]: ("working", {"1": "Доступен", "2": "Ошибка"}),
              d[2]: ("working", {"1": "Доступен", "2": "Недоступен"}),
              d[3]: ("working", {"1": "Ошибка", "2": "Ошибка"})},
    }
    got = status_now_from(d, s)
    assert got["a"] == {"status": "no_link", "since": "2026-09-11", "openStart": True, "faults": []}
    assert got["b"]["since"] == "2026-09-14" and not got["b"]["openStart"]
    assert got["c"]["faults"] == [{"no": "2", "status": "Ошибка", "since": "2026-09-12", "openStart": False}]
    assert status_now_from([], {}) == {}


def test_worklist_speaks_in_statuses():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from app.services.ops_worklist import ops_worklist

    state = {'asOf': '2026-09-30T01:00:00+03:00', 'stations': [
        {'locationId': 'nl', 'name': 'А', 'silentDays': 16, 'loss': 9000, 'attemptsEver': 5},
        {'locationId': 'wk', 'name': 'Б', 'silentDays': 3, 'loss': 29000, 'attemptsEver': 5},
        {'locationId': 'cn', 'name': 'В', 'silentDays': 0, 'loss': 0, 'attemptsEver': 5}]}
    статусы = {
        'nl': {'status': 'no_link', 'since': '2026-09-14', 'openStart': False, 'faults': []},
        'wk': {'status': 'working', 'since': '2026-09-11', 'openStart': True, 'faults': []},
        'cn': {'status': 'working', 'since': '2026-09-11', 'openStart': True,
               'faults': [{'no': '2', 'status': 'Ошибка', 'since': '2026-09-29', 'openStart': False}]},
    }

    class Result:
        def all(self): return []
    db = AsyncMock()
    db.execute.return_value = Result()
    with patch('app.services.ops_worklist.network_state', AsyncMock(return_value=state)), \
         patch('app.services.ops_worklist.network_reliability', AsyncMock(return_value={'stations': []})), \
         patch('app.services.ops_worklist.network_upkeep', AsyncMock(return_value={'rows': []})), \
         patch('app.services.ops_worklist.status_now', AsyncMock(return_value=('2026-09-30', статусы))):
        res = asyncio.run(ops_worklist(db, 'company', open_work=None))
    by = {r['locationId']: r['reasons'] for r in res['rows']}
    assert by['nl'][0] == {'kind': 'silent', 'label': 'нет связи с 14.09', 'note': 'молчит 16 дн'}
    assert by['wk'][0]['label'] == 'на связи, энергии нет 3 дн'
    assert by['cn'][0]['kind'] == 'connector' and by['cn'][0]['label'] == 'разъём 2 — Ошибка с 29.09'
    assert res['totals']['connector'] == 1 and res['statusDay'] == '2026-09-30'
    assert '30.09' in res['snapshotNote']
