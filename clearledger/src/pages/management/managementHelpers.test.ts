import { test } from 'node:test'
import assert from 'node:assert/strict'
import { initialManagementPeriod, managementDate, managementDateTimestamp, managementStatusLabel, managementTimeZone, safeManagementHref, validManagementPeriod, managementSearchLength, managementPeriodError } from './managementHelpers.ts'

test('original links reject executable schemes, credentials and browser URL normalisation tricks', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,evil', '//evil.test/a', '/\\evil.test/a', '/\nevil', ' https://safe.test/a', 'https://user:pass@safe.test/a', 'file:///tmp/a', 'https:\\evil.test']) {
    assert.equal(safeManagementHref(value), null, value)
  }
  assert.equal(safeManagementHref('/docs/work?company=a&task=b'), '/docs/work?company=a&task=b')
  assert.equal(safeManagementHref('./docs/work?task=b'), './docs/work?task=b')
  assert.equal(safeManagementHref('https://source.example.test/docs/work?task=b'), 'https://source.example.test/docs/work?task=b')
})

test('UTC near midnight displays the user calendar day; date-only deadline never moves day', () => {
  assert.match(managementDate('2026-10-24T22:30:00Z', 'Europe/Moscow'), /25 окт.*01:30/)
  assert.match(managementDate('2026-10-24T22:30:00', 'Europe/Moscow'), /25 окт.*01:30/)
  assert.match(managementDate('2026-10-24', 'America/Los_Angeles'), /^24 окт/)
  assert.equal(managementDate('invalid', 'Europe/Moscow'), 'не указано')
  assert.ok(managementDateTimestamp('2026-10-25T01:30:00+03:00') < managementDateTimestamp('2026-10-24T23:00:00Z'))
})

test('known statuses are human labels and unknown internal codes are not exposed', () => {
  assert.equal(managementStatusLabel('chats', 'group'), 'Группа')
  assert.equal(managementStatusLabel('tasks', 'open'), 'В работе')
  assert.equal(managementStatusLabel('calendar', 'planned'), 'Запланирована')
  assert.equal(managementStatusLabel('calendar', 'internal_state_v2'), null)
})

test('calendar period refuses impossible or inverted days and starts at browser local day', () => {
  assert.equal(validManagementPeriod('2026-10-24', '2026-10-24'), true)
  for (const [from, to] of [['2026-02-30', '2026-03-05'], ['2026-10-25', '2026-10-24'], ['', '2026-10-24']]) {
    assert.equal(validManagementPeriod(from, to), false)
  }
  const period = initialManagementPeriod('Pacific/Kiritimati')
  assert.equal(validManagementPeriod(period.from, period.to), true)
  assert.equal(Date.parse(period.to) - Date.parse(period.from), 6 * 86_400_000)
  assert.equal(managementTimeZone('Europe/Moscow'), 'Europe/Moscow')
  assert.doesNotThrow(() => managementTimeZone('not-a-zone'))
})

test('calendar accepts at most 367 inclusive civil days across leap years and DST', () => {
  assert.equal(validManagementPeriod('2026-01-01', '2027-01-02'), true)
  assert.equal(validManagementPeriod('2026-01-01', '2027-01-03'), false)
  assert.equal(validManagementPeriod('2024-01-01', '2025-01-01'), true)
  assert.equal(validManagementPeriod('2024-01-01', '2025-01-02'), false)
  for (const [from, to] of [['2026-03-29', '2026-03-29'], ['2026-10-25', '2026-10-25'], ['2024-02-29', '2024-02-29']]) {
    assert.equal(validManagementPeriod(from, to), true)
  }
  for (const [from, to] of [['2026-02-29', '2026-03-01'], ['0000-01-01', '0000-01-02'], ['2026-13-01', '2027-01-01'], ['2026-10-25', ''], ['2026-01-01', '2026-1-2']]) {
    assert.equal(validManagementPeriod(from, to), false)
  }
})


test('search counts Python Unicode code points without truncating emoji or combining marks', () => {
  assert.equal(managementSearchLength('я'.repeat(200)), 200)
  assert.equal(managementSearchLength('😀'.repeat(200)), 200)
  assert.equal(managementSearchLength('😀'.repeat(201)), 201)
  assert.equal(managementSearchLength('e\u0301'.repeat(100)), 200)
  assert.equal(managementSearchLength('👨‍👩‍👧‍👦'), 7)
  assert.equal(managementSearchLength('  поиск  '), 5)
  assert.equal(managementSearchLength(''), 0)
})

test('period validation explains missing, impossible, reversed and overlong input', () => {
  assert.match(managementPeriodError('', '2026-10-24')!, /обе даты/)
  assert.match(managementPeriodError('2026-02-30', '2026-03-01')!, /существующие даты/)
  assert.match(managementPeriodError('2026-10-25', '2026-10-24')!, /не раньше/)
  assert.match(managementPeriodError('2026-01-01', '2027-01-03')!, /367/)
  assert.equal(managementPeriodError('2026-01-01', '2027-01-02'), null)
})
