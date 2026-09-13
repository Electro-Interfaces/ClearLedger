import type { Map as LeafletMap } from 'leaflet'

export interface ClusterOf<T> {
  key: string
  lat: number
  lon: number
  items: T[]
}

/** Экранная сетка хранит центры групп: поиск только в девяти соседних ячейках. */
export function clusterPoints<T>(
  map: Pick<LeafletMap, 'project' | 'getZoom'>,
  points: T[],
  radiusPx: number,
  getLatLon: (item: T) => [number, number],
  getKey: (item: T) => string,
  zoom = map.getZoom(),
): ClusterOf<T>[] {
  const out: ClusterOf<T>[] = []
  const cells = new Map<string, { cluster: ClusterOf<T>; x: number; y: number }[]>()
  const used = new Set<string>()
  const ordered = points.map((item) => ({ item, key: getKey(item) }))
    .sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0)

  for (const { item, key } of ordered) {
    const [lat, lon] = getLatLon(item)
    if (used.has(key) || !Number.isFinite(lat) || !Number.isFinite(lon)
      || Math.abs(lat) >= 90 || Math.abs(lon) > 180) continue
    used.add(key)
    if (radiusPx <= 0) {
      out.push({ key, lat, lon, items: [item] })
      continue
    }
    const { x, y } = map.project([lat, lon], zoom)
    const col = Math.floor(x / radiusPx)
    const row = Math.floor(y / radiusPx)
    let nearest: ClusterOf<T> | undefined
    let distance = radiusPx * radiusPx
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const candidate of cells.get(`${col + dx}:${row + dy}`) ?? []) {
          const d = (candidate.x - x) ** 2 + (candidate.y - y) ** 2
          if (d < distance) {
            nearest = candidate.cluster
            distance = d
          }
        }
      }
    }
    if (nearest) {
      nearest.items.push(item)
    } else {
      // Якорь остаётся на реальной точке: сдвиг к среднему снова наложил бы группы.
      const cluster = { key: `c:${key}`, lat, lon, items: [item] }
      out.push(cluster)
      const cell = `${col}:${row}`
      const bucket = cells.get(cell) ?? []
      bucket.push({ cluster, x, y })
      cells.set(cell, bucket)
    }
  }
  return out
}

export function clusterRadiusForZoom(zoom: number): number {
  return Math.max(64, 80 - (zoom - 4) * 4)
}
