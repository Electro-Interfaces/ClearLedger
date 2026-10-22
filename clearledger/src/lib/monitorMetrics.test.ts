import test from 'node:test'
import assert from 'node:assert/strict'
import { monitorEnergy, worklistReasonMatches, worklistUpkeepCount } from './monitorMetrics.ts'

test('сумма и среднее сохраняют энергию, потерянную при округлении строк', () => {
  const stations = [{ energyKwh: 10, energyKwhRaw: 10.04 }, { energyKwh: 20, energyKwhRaw: 20.04 }]
  const total = stations.reduce((sum, row) => sum + monitorEnergy(row), 0)
  assert.equal(Math.round(total * 10) / 10, 30.1)
  assert.equal(Math.round(total / 2 * 100) / 100, 15.04)
})

test('нулевая точная энергия не подменяется округлённым полем старого API', () => {
  assert.equal(monitorEnergy({ energyKwh: 7, energyKwhRaw: 0 }), 0)
  assert.equal(monitorEnergy({ energyKwh: 7 }), 7)
})

test('плитка профилактики включает осмотр даже без поверок и ТО', () => {
  const row = { reasons: [{ kind: 'check' }] }
  assert.equal(worklistUpkeepCount([row]), 1)
  assert.equal(worklistReasonMatches(row.reasons, 'upkeep'), true)
  assert.equal(worklistReasonMatches(row.reasons, 'meter'), false)
})

test('станция с несколькими сроками считается в профилактике один раз', () => {
  const rows = [{ reasons: [{ kind: 'meter' }, { kind: 'service' }] }, { reasons: [{ kind: 'check' }] }, { reasons: [{ kind: 'silent' }] }]
  assert.equal(worklistUpkeepCount(rows), 2)
  assert.equal(rows.filter((row) => worklistReasonMatches(row.reasons, 'upkeep')).length, 2)
})

test('отбор отдельной причины и снятие отбора не подменяются профилактикой', () => {
  assert.equal(worklistReasonMatches([{ kind: 'connector' }], 'connector'), true)
  assert.equal(worklistReasonMatches([{ kind: 'connector' }], 'upkeep'), false)
  assert.equal(worklistReasonMatches([], 'all'), true)
})
