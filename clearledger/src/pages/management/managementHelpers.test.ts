import { test } from 'node:test'
import assert from 'node:assert/strict'
import { initialManagementPeriod, managementDate, managementDateTimestamp, managementStatusLabel, managementTimeZone, safeManagementHref, validManagementPeriod } from './managementHelpers.ts'

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
