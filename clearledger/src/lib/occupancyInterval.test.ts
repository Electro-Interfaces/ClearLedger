import { test } from 'node:test'
import assert from 'node:assert/strict'
import { occupancyInterval } from './occupancyInterval.ts'

const hours = () => Array.from({ length: 24 }, (_, hour) => ({ hour, occupied_minutes: 0, available_minutes: 120, starts: 0 }))

test('00–06: занятое время сессии, начавшейся раньше, входит без лишнего старта', () => {
  const p = hours()
  p[0].occupied_minutes = 90
  p[1].occupied_minutes = 120
  p[2].occupied_minutes = 30
  p[1].starts = 2
  p[6].occupied_minutes = 120
  p[6].starts = 9
  assert.deepEqual(occupancyInterval(p, 0, 6), { occupied_minutes: 240, available_minutes: 720, occupancy_pct: 33.333333, starts: 2 })
})

test('процент считается из минут, а не средним процентов', () => {
  const p = hours();p[0].available_minutes = 60;p[0].occupied_minutes = 60
  assert.equal(occupancyInterval(p, 0, 2).occupancy_pct, 33.333333)
})

test('нет привязки в выбранном часе: неизвестное вместо нуля, расчётное время известно', () => {
  const p: (ReturnType<typeof hours>[number] & { occupancy_complete?: boolean; starts_complete?: boolean })[] = hours()
  p[2].occupancy_complete = false;p[2].starts_complete = false
  assert.deepEqual(occupancyInterval(p, 0, 6), { occupied_minutes: null, available_minutes: 720, occupancy_pct: null, starts: null })
  assert.deepEqual(occupancyInterval(p, 3, 6), { occupied_minutes: 0, available_minutes: 360, occupancy_pct: 0, starts: 0 })
})

for (const [from, to] of [[0, 0], [6, 0], [-1, 6], [0, 25], [0.5, 6]]) {
  test(`неверные границы ${from}–${to}`, () => assert.throws(() => occupancyInterval(hours(), from, to)))
}

test('потерянный час не превращается в нулевую занятость', () => assert.throws(() => occupancyInterval(hours().slice(1), 0, 6)))
