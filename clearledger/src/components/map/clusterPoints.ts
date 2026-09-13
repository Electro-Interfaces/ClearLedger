/**
 * Прореживание точек карты по расстоянию В ПИКСЕЛЯХ — по тому, что видит глаз.
 *
 * Точек рынка девять тысяч. Нарисовать их все на обзоре страны нельзя: они лягут
 * друг на друга, и мышью в них не попасть. Но и раздувать маркер по числу точек
 * внутри нельзя: круги наезжают один на другой, карта превращается в диаграмму
 * пузырей, и первое, что видит человек, — не станции, а их скопления (решение
 * МАГа 13.09.2026).
 *
 * Поэтому точка остаётся точкой одного размера, а с масштабом меняется их
 * КОЛИЧЕСТВО: на каждую клетку пиксельной сетки выводится одна, остальные ждут
 * приближения. Пропорции плотности сохраняются — где станций гуще, там гуще и
 * точки.
 *
 * Сетка, а не попарный обход: при пяти тысячах точек сравнение каждой с каждой
 * давало 25 млн операций, и карта замирала на каждом сдвиге.
 */
import type { Map as LeafletMap } from 'leaflet'

export interface ClusterOf<T> {
  key: string
  lat: number
  lon: number
  items: T[]
}

/**
 * `radiusPx = 0` отключает прореживание: на близком масштабе точки должны стоять
 * каждая на своём месте, иначе пропадает то, ради чего карту и открыли.
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
  const cell = Math.max(1, radiusPx)
  const grid = new Map<string, ClusterOf<T>>()
  for (const point of points) {
    const [lat, lon] = getLatLon(point)
    const pixel = map.latLngToLayerPoint([lat, lon])
    const cellKey = `${Math.round(pixel.x / cell)}:${Math.round(pixel.y / cell)}`
    const found = grid.get(cellKey)
    if (found) {
      // Соседи по клетке не пропадают: они лежат в `items`, и подсказка говорит,
      // сколько станций ждёт приближения.
      found.items.push(point)
      continue
    }
    // Точка клетки — первая попавшая, а не среднее её соседей: маркер должен
    // стоять на реальной станции, иначе при приближении он «отъезжает» с места.
    grid.set(cellKey, { key: getKey(point), lat, lon, items: [point] })
  }
  return [...grid.values()]
}

/**
 * Шаг сетки прореживания от масштаба. Он чуть больше самой точки, чтобы соседние
 * не слипались, но и только: чем мельче шаг, тем больше станций на экране. С
 * 12-го масштаба прореживания нет вовсе — там видно каждую.
 */
export function clusterRadiusForZoom(zoom: number): number {
  if (zoom >= 12) return 0
  return Math.max(10, 20 - (zoom - 4) * 1.2)
}
