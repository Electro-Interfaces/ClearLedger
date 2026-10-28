import test from 'node:test'
import assert from 'node:assert/strict'
import { eventDaySegment, layoutDayEvents } from './calendarLayout.ts'

// Даты ниже заданы по местным часам, а раскладка считает по поясу компании
// (Москва): на машине в UTC тесты падали, хотя код верен (QA 27.10.2026).
process.env.TZ = 'Europe/Moscow'

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

test('повторяющееся дело раскладывается вперёд и не дублирует прошедшее', async () => {
  const { recurrenceTimes } = await import('./calendarLayout.ts')
  // 12–18 октября 2026, понедельник — воскресенье.
  const days = Array.from({ length: 7 }, (_, i) => new Date(2026, 9, 12 + i))
  const after = new Date(2026, 9, 13, 12, 0)
  assert.equal(recurrenceTimes({ mode: 'daily', at: '09:00' }, days, after).length, 5)
  const weekly = recurrenceTimes({ mode: 'weekly', at: '15:30', weekday: 4 }, days, after)
  assert.deepEqual(weekly.map(d => [d.getDate(), d.getHours(), d.getMinutes()]), [[16, 15, 30]])
  assert.equal(recurrenceTimes({ mode: 'monthly', day: 12 }, days, after).length, 0)
  assert.equal(recurrenceTimes({ mode: 'monthly', day: 18 }, days, after).length, 1)
})

test('Встреча растягивается на свободные колонки, а не делит ширину с чужим часом', () => {
  // Сутки целиком — длинная (как отменённая «Продолжение» 28.10); вечером три встречи разом.
  const result = layoutDayEvents([event('long', 0, 24), event('morning', 10, 11),
    event('e1', 20, 21), event('e2', 20, 21), event('e3', 20, 21)], day)
  const morning = result.find(row => row.event.id === 'morning')!
  assert.equal(morning.columns, 4)
  assert.equal(morning.column, 1)
  assert.equal(morning.span, 3, 'утренняя занимает всё справа от длинной')
  assert.deepEqual(result.filter(row => row.event.id.startsWith('e')).map(row => row.span), [1, 1, 1])
})

test('Короткие встречи не ложатся друг на друга: длина по высоте блока', () => {
  const at = (h: number, m: number, s = 0) => new Date(2026, 8, 7, h, m, s).toISOString()
  const short = (id: string, m: number) => ({ id, starts_at: at(9, m), ends_at: at(9, m, 13) })
  const result = layoutDayEvents([short('a', 4), short('b', 9), short('c', 40)], day, 25)
  assert.deepEqual(result.map(row => [row.event.id, row.column, row.columns]), [
    ['a', 0, 2], ['b', 1, 2], ['c', 0, 1],
  ])
  // Без поправки на высоту все три в одной колонке — так было на снимке 28.10.
  assert.deepEqual(layoutDayEvents([short('a', 4), short('b', 9)], day).map(row => row.column), [0, 0])
})
