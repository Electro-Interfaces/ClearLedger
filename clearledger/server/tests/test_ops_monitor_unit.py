import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.services.ops_monitor_context import monitor_context, region_matches, decimal_round
from app.services.ops_worklist import ops_worklist


class MonitorContextTest(unittest.TestCase):
    def test_moscow_midnight_and_real_lag(self):
        boundary = datetime(2026, 9, 17, 21, 54, 30)
        now = datetime(2026, 9, 20, 19, 54, 30, tzinfo=timezone.utc)
        _, current = monitor_context(boundary, now=now)
        point, history = monitor_context(boundary, date(2026, 9, 1), now)
        self.assertEqual(current['dataLagHours'], 73)
        self.assertEqual(current['dataLagHours'], history['dataLagHours'])
        self.assertEqual(point, datetime(2026, 9, 1, 23, 59, 59, 999999))
        self.assertTrue(history['asOf'].endswith('+03:00'))

    def test_no_data_is_unknown(self):
        _, result = monitor_context(None, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertIsNone(result['dataThrough'])
        self.assertIsNone(result['dataLagHours'])

    def test_regions_and_decimal_energy(self):
        self.assertTrue(region_matches('Москва', 'Москва|Приморский край'))
        self.assertFalse(region_matches('Омская область', 'Москва|Приморский край'))
        self.assertTrue(region_matches(None, '— регион не указан'))
        self.assertEqual(decimal_round('120.450'), 120.5)


class WorklistTest(unittest.IsolatedAsyncioTestCase):
    async def test_quality_queue_evidence_and_unknown_work(self):
        state = {'asOf': '2026-09-17T21:00:00+03:00', 'dataThrough': '2026-09-17T21:00:00+03:00',
                 'dataLagHours': 72, 'stations': [
                     {'locationId': 'own', 'name': 'Станция', 'region': 'Москва', 'silentDays': 4,
                      'loss': 300, 'statusRaw': 'Нет связи с контроллером', 'attemptsEver': 12},
                     {'locationId': 'quiet', 'name': 'Новая', 'region': 'Москва', 'silentDays': 0,
                      'loss': 0, 'attemptsEver': 3}]}
        reliability = {'threshold': 20, 'stations': [
            {'locationId': 'own', 'visits': 12, 'failedVisitsPct': 0},
            {'locationId': 'quiet', 'visits': 3, 'failedVisitsPct': 33.3}]}
        unknown = {'state': 'unknown'}
        upkeep = {'rows': [{'locationId': loc, 'meter': unknown, 'service': unknown}
                           for loc in ['own', 'own', 'partner']]}
        class Result:
            def all(self): return []
        db = AsyncMock()
        db.execute.return_value = Result()
        with patch('app.services.ops_worklist.network_state', AsyncMock(return_value=state)), \
             patch('app.services.ops_worklist.network_reliability', AsyncMock(return_value=reliability)), \
             patch('app.services.ops_worklist.network_upkeep', AsyncMock(return_value=upkeep)):
            result = await ops_worklist(db, 'company', open_work=None)
        self.assertEqual(result['totals']['rows'], 1)
        self.assertEqual(result['totals']['lossPerMonth'], 300)
        self.assertEqual(result['totals']['upkeepUnknown'], 1)
        self.assertEqual(result['dataGaps'][0]['units'], 2)
        self.assertEqual(result['rows'][0]['reasons'][0]['note'], 'Нет связи с контроллером')
        self.assertIsNone(result['totals']['notTaken'])
        self.assertIsNone(result['totals']['lossNotTaken'])


if __name__ == '__main__':
    unittest.main()
