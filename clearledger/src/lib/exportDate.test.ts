import test from 'node:test'
import assert from 'node:assert/strict'
import { exportDateStamp } from './exportDate.ts'

test('имя выгрузки после московской полуночи содержит новый местный день', () => {
  const instant = new Date('2026-10-22T21:05:00Z')
  assert.equal(exportDateStamp(instant, 'Europe/Moscow'), '2026-10-23')
  assert.equal(exportDateStamp(instant, 'UTC'), '2026-10-22')
})

test('выгрузка учитывает и часовой пояс западнее UTC', () => {
  assert.equal(exportDateStamp(new Date('2026-10-23T01:00:00Z'), 'America/New_York'), '2026-10-22')
})
