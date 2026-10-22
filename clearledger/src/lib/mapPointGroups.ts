export interface PointGroup<T> {
  key: string
  lat: number
  lon: number
  items: T[]
}

/** Совпадающие координаты не разойдутся при приближении: сохраняем все объекты. */
export function groupPointsByCoordinates<T>(
  points: T[],
  getLatLon: (item: T) => [number, number],
  getKey: (item: T) => string,
): PointGroup<T>[] {
  const groups = new Map<string, PointGroup<T>>()
  for (const item of points) {
    const [lat, lon] = getLatLon(item)
    const coordinate = `${lat}:${lon}`
    const group = groups.get(coordinate)
    if (group) group.items.push(item)
    else groups.set(coordinate, { key: getKey(item), lat, lon, items: [item] })
  }
  return [...groups.values()]
}
