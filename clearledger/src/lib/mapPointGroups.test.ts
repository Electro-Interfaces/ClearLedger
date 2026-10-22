import test from 'node:test'
import assert from 'node:assert/strict'
import { groupPointsByCoordinates } from './mapPointGroups.ts'
import { clusterPoints, clusterRadiusForZoom } from '../components/map/clusterPoints.ts'

const points = [
  { id: 'active', lat: 55.1, lon: 37.2 },
  { id: 'retired', lat: 55.1, lon: 37.2 },
  { id: 'nearby', lat: 55.100001, lon: 37.2 },
]
const latLon = (point: typeof points[number]): [number, number] => [point.lat, point.lon]
const key = (point: typeof points[number]) => point.id

test('совпадающие объекты сохраняются в одной точке, соседние координаты не округляются', () => {
  const groups = groupPointsByCoordinates(points, latLon, key)
  assert.deepEqual(groups.map(group => group.items.map(key)), [['active', 'retired'], ['nearby']])
  assert.equal(groups[0].lat, points[0].lat)
  assert.equal(groups[0].lon, points[0].lon)
  assert.deepEqual(points.map(key), ['active', 'retired', 'nearby'])
})

test('приближение от 12 до 19 не закрывает выведенным объектом действующий', () => {
  const map = { latLngToLayerPoint() { throw new Error('Прореживание отключено') } } as unknown as Parameters<typeof clusterPoints>[0]
  for (const zoom of [12, 13, 16, 19]) {
    const groups = clusterPoints(map, points, clusterRadiusForZoom(zoom), latLon, key)
    assert.deepEqual(groups.map(group => group.items.map(key)), [['active', 'retired'], ['nearby']])
  }
})

test('на обзоре карта сохраняет все элементы группы и маркер в реальной координате', () => {
  const map = { latLngToLayerPoint: () => ({ x: 100, y: 100 }) } as unknown as Parameters<typeof clusterPoints>[0]
  const groups = clusterPoints(map, points, clusterRadiusForZoom(5), latLon, key)
  assert.equal(groups.length, 1)
  assert.deepEqual(groups[0].items, points)
  assert.equal(groups[0].key, 'active')
  assert.equal(groups[0].lat, 55.1)
})

test('все двенадцать объектов одной площадки сохраняются, пустой список допустим', () => {
  const many = Array.from({ length: 12 }, (_, n) => ({ id: String(n), lat: 55, lon: 37 }))
  assert.equal(groupPointsByCoordinates(many, latLon, key)[0].items.length, 12)
  assert.deepEqual(groupPointsByCoordinates([], latLon, key), [])
})
