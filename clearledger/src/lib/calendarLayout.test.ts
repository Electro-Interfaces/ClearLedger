import test from 'node:test'
import assert from 'node:assert/strict'
import { eventDaySegment, layoutDayEvents } from './calendarLayout.ts'

const day = new Date(2026, 8, 7)
function event(id: string, start: number, end: number) {
  const at = (hour: number) => new Date(2026, 8, 7, hour).toISOString()
  return { id, starts_at: at(start), ends_at: at(end) }
}

test('Встреча через полночь видна на обоих днях и обрезается границей дня', () => {
  const night = event('night', 23, 26)
  const first = eventDaySegment(night, day)!
  const next = eventDaySegment(night, new Date(2026, 8, 8))!
  assert.equal(first.startMinute, 1380)
  assert.equal(first.endMinute, 1440)
  assert.equal(next.startMinute, 0)
  assert.equal(next.endMinute, 120)
  assert.equal(next.continues, true)
  assert.equal(eventDaySegment(event('end', 22, 24), new Date(2026, 8, 8)), null)
})

test('Отдельная встреча занимает всю ширину независимо от последующих пересечений', () => {
  const result = layoutDayEvents([event('morning', 9, 10), event('a', 12, 14), event('b', 13, 15), event('late', 17, 18)], day)
  assert.deepEqual(result.map(row => [row.event.id, row.column, row.columns]), [
    ['morning', 0, 1], ['a', 0, 2], ['b', 1, 2], ['late', 0, 1],
  ])
})

test('Цепочка пересечений сохраняет колонки, соседние интервалы не пересекаются', () => {
  const result = layoutDayEvents([event('a', 9, 12), event('b', 10, 11), event('c', 11, 13), event('d', 13, 14)], day)
  assert.deepEqual(result.map(row => [row.event.id, row.column, row.columns]), [
    ['a', 0, 2], ['b', 1, 2], ['c', 1, 2], ['d', 0, 1],
  ])
})
