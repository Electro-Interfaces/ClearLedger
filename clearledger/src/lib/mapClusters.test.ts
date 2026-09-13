import test from 'node:test'
import assert from 'node:assert/strict'
import { clusterPoints, clusterRadiusForZoom } from '../components/map/clusterPoints.ts'
import type { Map as LeafletMap } from 'leaflet'

type Point = { id: string; lat: number; lon: number }
let projections = 0
const map = {
  getZoom: () => 10,
  project: ([lat, lon]: [number, number], zoom: number) => {
    projections++
    return { x: lon * 2 ** zoom, y: lat * 2 ** zoom }
  },
} as unknown as Pick<LeafletMap, 'project' | 'getZoom'>
const group = (points: Point[], zoom = 10) => clusterPoints(map, points,
  clusterRadiusForZoom(zoom), (p) => [p.lat, p.lon], (p) => p.id, zoom)

test('совпадающие наши и внешние записи доступны одной группой даже вблизи', () => {
  const points = ['our:1', 'market:1', 'market:2'].map((id) => ({ id, lat: 55, lon: 37 }))
  for (const zoom of [5, 11, 12, 19, 21]) {
    const groups = group(points, zoom)
    assert.equal(groups.length, 1)
    assert.equal(groups[0].items.length, 3)
  }
})

test('при одинаковом радиусе новый масштаб действительно разделяет соседей', () => {
  const points = [{ id: 'a', lat: 55, lon: 37 }, { id: 'b', lat: 55, lon: 37.04 }]
  assert.equal(group(points, 10).length, 1)
  assert.equal(group(points, 11).length, 2)
})

test('плотная цепочка сохраняет все записи, но не склеивается в одну огромную группу', () => {
  const points = Array.from({ length: 200 }, (_, i) => ({ id: String(i), lat: 55, lon: 37 + i * .01 }))
  const groups = group(points)
  assert.ok(groups.length > 20)
  assert.equal(groups.flatMap((c) => c.items).length, 200)
  for (let i = 0; i < groups.length; i++) {
    for (let j = i + 1; j < groups.length; j++) {
      assert.ok(Math.hypot(groups[i].lon - groups[j].lon, groups[i].lat - groups[j].lat) * 1024 >= 64)
    }
  }
  assert.deepEqual(group([...points].reverse()), groups)
})

test('десять тысяч точек проецируются по одному разу, а не попарно', () => {
  const points = Array.from({ length: 10000 }, (_, i) => ({
    id: String(i), lat: 50 + Math.floor(i / 100) * .01, lon: 35 + i % 100 * .01,
  }))
  projections = 0
  const groups = group(points)
  assert.equal(projections, points.length)
  assert.equal(groups.flatMap((c) => c.items).length, points.length)
})

test('повтор записи и невалидные координаты не создают ложных меток', () => {
  const valid = { id: 'a', lat: 55, lon: 37 }
  assert.equal(group([valid, valid, { id: 'b', lat: NaN, lon: 37 },
    { id: 'c', lat: 90, lon: 37 }, { id: 'd', lat: 55, lon: Infinity }])[0].items.length, 1)
})
