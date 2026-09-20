import assert from 'node:assert/strict'
import { test } from 'node:test'
import { demoMonitoring } from '../demo/demoMonitoring.ts'

test('пять демо-экранов согласованы по региону, отказам и недобору', () => {
  for (const region of [undefined, 'Демо-регион', 'Второй демо-регион']) {
    const state = demoMonitoring('/api/ops/network-state', { region })!
    const work = demoMonitoring('/api/ops/worklist', { region })!
    const reliability = demoMonitoring('/api/ops/reliability', { region })!
    const vendors = demoMonitoring('/api/ops/vendors', { region, vendor: '*' })!
    const tickets = demoMonitoring('/api/ops/tickets', { region })!
    assert.equal(state.totals?.lossPerMonth, work.totals?.lossPerMonth)
    assert.equal(state.totals?.stations, vendors.totals?.stations)
    assert.equal(reliability.totals?.visitsFailed, vendors.totals?.visitsFailed)
    assert.equal(reliability.totals?.badStations, vendors.totals?.badStations)
    assert.equal(tickets.totals?.total, tickets.rows?.length)
    assert.equal(work.workKnown, false)
  }
})

test('пустой исторический период не получает будущие сессии', () => {
  const r = demoMonitoring('/api/ops/reliability', { as_of: '2026-08-01' })!
  assert.equal(r.totals?.visits, 0)
  assert.equal(r.totals?.stations, 0)
})
