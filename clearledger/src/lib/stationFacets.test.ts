import assert from 'node:assert/strict'
import test from 'node:test'
import {
  facetValues, matchesFacets, powerBucket, sortStations, stationMeta,
  type FacetStation,
} from './stationFacets.ts'

function station(over: Partial<FacetStation>): FacetStation {
  return {
    code: '1', name: 'Станция', sessions: 0,
    region: 'Москва', city: 'Москва', address: 'Тверская, 1',
    speed: 'fast', placement: 'city', brand: 'ПСС', power: 150, ports: 2,
    connectors: ['Type 2', 'CCS Combo 2'], opStatus: 'working', lifecycle: 'active',
    corp: false,
    ...over,
  }
}

const NETWORK: FacetStation[] = [
  station({ code: '680', name: 'Тверская', sessions: 1200 }),
  station({ code: '684', name: 'Химки', city: 'Химки', speed: 'slow', power: 22,
            brand: 'Touch', connectors: ['Type 2'], sessions: 300 }),
  station({ code: '701', name: 'Невский', region: 'Санкт-Петербург', city: 'Санкт-Петербург',
            placement: 'highway', opStatus: 'no_link', sessions: 0 }),
  station({ code: '900', name: 'Без паспорта', region: '12', city: null, speed: null,
            placement: null, brand: null, power: null, connectors: [], opStatus: null,
            lifecycle: null, sessions: 5 }),
]

test('фасет сужает сеть, несколько значений одной группы складываются по «или»', () => {
  const fast = NETWORK.filter((s) => matchesFacets(s, { speed: ['fast'] }))
  assert.deepEqual(fast.map((s) => s.code), ['680', '701'])

  const both = NETWORK.filter((s) => matchesFacets(s, { speed: ['fast', 'slow'] }))
  assert.deepEqual(both.map((s) => s.code), ['680', '684', '701'])

  // Разные группы складываются по «и».
  const fastHighway = NETWORK.filter((s) => matchesFacets(s, { speed: ['fast'], placement: ['highway'] }))
  assert.deepEqual(fastHighway.map((s) => s.code), ['701'])
})

test('счётчик группы считается без неё самой — фасетом можно расширить выборку', () => {
  const values = facetValues(NETWORK, { speed: ['fast'] })
  const speed = values.get('speed') ?? []
  // «Медленные» видны с настоящим числом станций, а не с нулём.
  assert.equal(speed.find((v) => v.value === 'slow')?.count, 1)
  assert.equal(speed.find((v) => v.value === 'fast')?.count, 2)
  // Чужая группа уже сужена выбранной скоростью.
  const placement = values.get('placement') ?? []
  assert.equal(placement.find((v) => v.value === 'city')?.count, 1)
})

test('отмеченное значение остаётся в списке даже когда под него не подходит ни одна станция', () => {
  const values = facetValues(NETWORK, { brand: ['Kostad'], city: ['Химки'] })
  const brand = (values.get('brand') ?? []).find((v) => v.value === 'Kostad')
  assert.equal(brand?.count, 0)
})

test('пустой паспорт попадает в «не указано», мусорный регион туда же', () => {
  const values = facetValues(NETWORK, {})
  assert.equal((values.get('region') ?? []).find((v) => v.value === '—')?.count, 1)
  assert.equal((values.get('speed') ?? []).find((v) => v.value === '—')?.count, 1)
  assert.equal(powerBucket(null), '—')
  assert.equal(powerBucket(22), 'le22')
  assert.equal(powerBucket(150), 'le150')
  assert.equal(powerBucket(151), 'gt150')
})

test('сортировка по объёму ставит станцию с зарядками выше пустой', () => {
  assert.deepEqual(sortStations(NETWORK, 'sessions').map((s) => s.code), ['680', '684', '900', '701'])
  assert.deepEqual(sortStations(NETWORK, 'code').map((s) => s.code), ['680', '684', '701', '900'])
})

test('мета-строка называет состояние словом, а не только цветом', () => {
  const meta = stationMeta(NETWORK[2])
  assert.match(meta, /Нет связи/)
  assert.match(meta, /Трасса/)
  assert.doesNotMatch(stationMeta(NETWORK[0]), /Работает/)
})
