import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getDemoStoreExchange,
  getDemoStoreOverview,
  getDemoStoreSales,
  getDemoStoreStock,
} from '../services/storeDemoService.ts'

test('демо магазина сужается до выбранной станции', async () => {
  const all = await getDemoStoreOverview('2026-08-11', '2026-08-24')
  const one = await getDemoStoreOverview('2026-08-11', '2026-08-24', ['208'])

  assert.equal(all.operational.stations_count, 3)
  assert.equal(one.operational.stations_count, 1)
  assert.equal(one.by_station[0]?.station, 'АЗС 208')
  assert.ok(one.financial.total_revenue < all.financial.total_revenue)
})

test('продажи и остатки используют один набор демо-товаров', async () => {
  const sales = await getDemoStoreSales('2026-08-11', '2026-08-24', {
    groupBy: 'sku', category: 'all', marked: 'all', stations: ['101'],
  })
  const stock = await getDemoStoreStock({ stations: ['101'] })

  assert.equal(sales.groups.length, 8)
  assert.equal(stock.stations?.length, 1)
  assert.deepEqual(
    new Set(sales.groups.map((row) => row.key)),
    new Set(stock.items.map((row) => row.guid)),
  )
})

test('диспетчерская показывает три разных состояния станций', async () => {
  const exchange = await getDemoStoreExchange('2026-08-11', '2026-08-24')

  assert.equal(exchange.totals.stations, 3)
  assert.equal(exchange.totals.online, 2)
  assert.ok(exchange.totals.queue_pending > 0)
  assert.ok(exchange.stations.some((station) => station.state === 'молчит'))
})
