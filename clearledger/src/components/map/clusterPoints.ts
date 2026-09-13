/**
 * Склейка точек карты по расстоянию В ПИКСЕЛЯХ — по тому, что видит глаз.
 *
 * Обобщение приёма из карты «Топлива» (`FuelMapPanel`): на обзорном плане точки,
 * стоящие в паре километров, физически не могут не пересечься — сколько ни уменьшай
 * маркер, разводить нечего. Поэтому на дальних масштабах они складываются в один
 * маркер с числом точек, а при приближении расходятся сами.
 *
 * Здесь это нужно ещё и по другой причине: точек рынка девять тысяч, и рисовать их
 * по одной — не карта, а каша, в которую вдобавок не попасть мышью.
 */
import type { Map as LeafletMap } from 'leaflet'

export interface ClusterOf<T> {
  key: string
  lat: number
  lon: number
  items: T[]
}

/**
 * `radiusPx = 0` отключает склейку: на близком масштабе точки должны стоять каждая
 * на своём месте, иначе пропадает то, ради чего карту и открыли.
 */
export function clusterPoints<T>(
  map: LeafletMap,
  points: T[],
  radiusPx: number,
  getLatLon: (item: T) => [number, number],
  getKey: (item: T) => string,
): ClusterOf<T>[] {
  if (radiusPx <= 0) {
    return points.map((item) => {
      const [lat, lon] = getLatLon(item)
      return { key: getKey(item), lat, lon, items: [item] }
    })
  }
  const out: ClusterOf<T>[] = []
  const used = new Set<string>()
  for (const point of points) {
    const key = getKey(point)
    if (used.has(key)) continue
    used.add(key)
    const [lat, lon] = getLatLon(point)
    const base = map.latLngToLayerPoint([lat, lon])
    const group: T[] = [point]
    for (const other of points) {
      const otherKey = getKey(other)
      if (used.has(otherKey)) continue
      const [oLat, oLon] = getLatLon(other)
      if (base.distanceTo(map.latLngToLayerPoint([oLat, oLon])) <= radiusPx) {
        used.add(otherKey)
        group.push(other)
      }
    }
    // Центр группы — среднее её точек: так маркер стоит там, где скопление, а не
    // на случайной первой станции.
    const sum = group.reduce(
      (acc, item) => {
        const [gLat, gLon] = getLatLon(item)
        return [acc[0] + gLat, acc[1] + gLon] as [number, number]
      },
      [0, 0] as [number, number],
    )
    out.push({
      key: `c:${key}`,
      lat: sum[0] / group.length,
      lon: sum[1] / group.length,
      items: group,
    })
  }
  return out
}

/**
 * Радиус склейки от масштаба: чем дальше, тем крупнее «пятачок». Ниже 30 px не
 * опускаемся — столько занимает сам маркер с обводкой; с 12-го масштаба склейки
 * нет вовсе.
 */
export function clusterRadiusForZoom(zoom: number): number {
  if (zoom >= 12) return 0
  return Math.max(30, 70 - (zoom - 4) * 7)
}
